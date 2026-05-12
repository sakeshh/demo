/**
 * Azure AI Foundry AGENT client (not the deployed model).
 * Uses the Agent API: threads, messages, runs.
 * Your agent (with actions, blob access, etc.) is invoked via create run.
 *
 * Required in .env.local:
 * - AZURE_AGENT_ENDPOINT: Project base URL (e.g. https://xxx.services.ai.azure.com/api/projects/yyy)
 * - AZURE_AGENT_API_KEY: API key from Project Settings → Keys and endpoints
 * - AZURE_AGENT_ID: Your agent's ID (from the agent page or View code in Playground)
 */

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export interface AzureAgentConfig {
  endpoint: string;
  apiKey: string;
  agentId: string;
}

export interface AgentReplyResult {
  content: string;
  threadId?: string;
  error?: string;
}

async function fetchWithTimeout(
  input: RequestInfo | URL,
  init: RequestInit & { timeoutMs?: number } = {}
): Promise<Response> {
  const timeoutMs = init.timeoutMs ?? 25_000;
  const controller = new AbortController();
  const t = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const { timeoutMs: _timeoutMs, signal, ...rest } = init;
    // If a signal is provided, we cannot combine it safely; use ours for deterministic timeouts.
    return await fetch(input, { ...rest, signal: controller.signal });
  } finally {
    clearTimeout(t);
  }
}

function getApiVersion(): string {
  // Agent APIs typically use a date-based api-version (preview). Allow override from env.
  return (
    process.env.AZURE_AGENT_API_VERSION?.trim() ||
    process.env.AZURE_OPENAI_API_VERSION?.trim() ||
    '2024-05-01-preview'
  );
}

/**
 * Get config from environment. Call this server-side only.
 */
export function getAzureAgentConfig(): AzureAgentConfig | null {
  const endpoint = process.env.AZURE_AGENT_ENDPOINT?.trim();
  const apiKey = process.env.AZURE_AGENT_API_KEY?.trim();
  const agentId = process.env.AZURE_AGENT_ID?.trim();
  if (!endpoint || !apiKey || !agentId) {
    return null;
  }
  return { endpoint, apiKey, agentId };
}

let cachedAadToken: { value: string; expiresAtMs: number } | null = null;

async function tryGetAadToken(): Promise<string | null> {
  // Matches the common Foundry/Azure Cognitive scope used for agent/project endpoints.
  const scope = process.env.AZURE_AGENT_AAD_SCOPE?.trim() || 'https://cognitiveservices.azure.com/.default';
  try {
    if (cachedAadToken && cachedAadToken.expiresAtMs - Date.now() > 30_000) {
      return cachedAadToken.value;
    }
    const mod = await import('@azure/identity');
    const credential = new mod.DefaultAzureCredential();
    const token = await credential.getToken(scope);
    if (!token?.token) return null;
    cachedAadToken = {
      value: token.token,
      expiresAtMs: typeof token.expiresOnTimestamp === 'number' ? token.expiresOnTimestamp : Date.now() + 5 * 60_000,
    };
    return cachedAadToken.value;
  } catch {
    return null;
  }
}

async function getAgentAuthHeaders(apiKey: string): Promise<Record<string, string>> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };

  // Screenshot flow: try AAD first (DefaultAzureCredential), then fall back to API key.
  const useAad = (process.env.AZURE_AGENT_USE_AAD || '').trim().toLowerCase();
  if (useAad === '1' || useAad === 'true' || useAad === 'yes') {
    const token = await tryGetAadToken();
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
      return headers;
    }
  }

  // Agent API (threads/runs) can be Bearer or api-key depending on how the project is configured.
  const auth = process.env.AZURE_AGENT_AUTH_HEADER?.trim();
  if (auth === 'api-key') {
    headers['api-key'] = apiKey;
  } else if (auth === 'ocp-apim') {
    headers['Ocp-Apim-Subscription-Key'] = apiKey;
  } else {
    headers['Authorization'] = `Bearer ${apiKey}`;
  }
  return headers;
}

function getAzureOpenAIHeaders(apiKey: string): Record<string, string> {
  // Azure OpenAI uses "api-key" header (not Bearer) for most REST calls.
  return {
    'Content-Type': 'application/json',
    'api-key': apiKey,
  };
}

/**
 * Ensure endpoint has no trailing slash for building paths.
 */
function baseUrl(endpoint: string): string {
  return endpoint.replace(/\/$/, '');
}

function looksLikeFoundryProjectEndpoint(endpoint: string): boolean {
  return /\/api\/projects\//i.test(endpoint);
}

function looksLikeAzureOpenAIEndpoint(endpoint: string): boolean {
  // Match both base endpoints and endpoints that include extra paths.
  return /\.openai\.azure\.com(\/|$)/i.test(endpoint) || /\.cognitiveservices\.azure\.com(\/|$)/i.test(endpoint);
}

async function sendToAzureOpenAIChatCompletions(messages: ChatMessage[]): Promise<AgentReplyResult> {
  const endpoint = process.env.AZURE_OPENAI_ENDPOINT?.trim() || process.env.AZURE_AGENT_ENDPOINT?.trim();
  const apiKey = process.env.AZURE_OPENAI_API_KEY?.trim() || process.env.AZURE_AGENT_API_KEY?.trim();
  const deployment =
    process.env.AZURE_OPENAI_DEPLOYMENT_NAME?.trim() ||
    process.env.AZURE_OPENAI_DEPLOYMENT?.trim() ||
    process.env.DEPLOYMENT_NAME?.trim();

  if (!endpoint || !apiKey || !deployment) {
    return {
      content:
        'Azure OpenAI is not configured. Set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY (or AZURE_AGENT_API_KEY), and AZURE_OPENAI_DEPLOYMENT_NAME in .env.local.',
      error: 'NOT_CONFIGURED',
    };
  }

  const apiVersion = getApiVersion();
  const url = `${baseUrl(endpoint)}/openai/deployments/${encodeURIComponent(
    deployment
  )}/chat/completions?api-version=${encodeURIComponent(apiVersion)}`;

  const res = await fetchWithTimeout(url, {
    method: 'POST',
    headers: getAzureOpenAIHeaders(apiKey),
    body: JSON.stringify({
      messages,
      temperature: 0.2,
    }),
    timeoutMs: 25_000,
  });

  if (!res.ok) {
    const err = await res.text();
    return {
      content: `Azure OpenAI error (${res.status}) calling ${url}: ${err.slice(0, 600)}`,
      error: 'AZURE_OPENAI_ERROR',
    };
  }

  const data = await res.json();
  const content = data?.choices?.[0]?.message?.content;
  return {
    content: typeof content === 'string' && content.trim() ? content.trim() : 'No reply from Azure OpenAI.',
  };
}

/**
 * Create a new thread, optionally with an initial user message.
 */
async function createThread(
  cfg: AzureAgentConfig,
  initialMessage?: string
): Promise<{ threadId: string }> {
  const url = `${baseUrl(cfg.endpoint)}/threads?api-version=${encodeURIComponent(getApiVersion())}`;
  const body: Record<string, unknown> = {};
  if (initialMessage?.trim()) {
    body.messages = [
      {
        role: 'user',
        content: initialMessage.trim(),
      },
    ];
  }
  const headers = await getAgentAuthHeaders(cfg.apiKey);
  const res = await fetchWithTimeout(url, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    timeoutMs: 25_000,
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`Create thread failed (${res.status}): ${err.slice(0, 300)}`);
  }
  const data = await res.json();
  const threadId = data.id ?? data.thread_id;
  if (!threadId) {
    throw new Error('Create thread response missing thread id');
  }
  return { threadId: String(threadId) };
}

/**
 * Add a user message to an existing thread.
 */
async function addMessage(
  cfg: AzureAgentConfig,
  threadId: string,
  content: string
): Promise<void> {
  const url = `${baseUrl(cfg.endpoint)}/threads/${threadId}/messages?api-version=${encodeURIComponent(
    getApiVersion()
  )}`;
  const body = {
    role: 'user',
    content: content.trim(),
  };
  const headers = await getAgentAuthHeaders(cfg.apiKey);
  const res = await fetchWithTimeout(url, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    timeoutMs: 25_000,
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`Add message failed (${res.status}): ${err.slice(0, 300)}`);
  }
}

/**
 * Start a run on the thread (invokes your agent).
 */
async function createRun(cfg: AzureAgentConfig, threadId: string): Promise<{ runId: string }> {
  const url = `${baseUrl(cfg.endpoint)}/threads/${threadId}/runs?api-version=${encodeURIComponent(getApiVersion())}`;
  const body = {
    agent_id: cfg.agentId,
  };
  const headers = await getAgentAuthHeaders(cfg.apiKey);
  const res = await fetchWithTimeout(url, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    timeoutMs: 25_000,
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`Create run failed (${res.status}): ${err.slice(0, 300)}`);
  }
  const data = await res.json();
  const runId = data.id ?? data.run_id;
  if (!runId) {
    throw new Error('Create run response missing run id');
  }
  return { runId: String(runId) };
}

/**
 * Poll run status until completed, failed, or timeout.
 */
async function waitForRun(
  cfg: AzureAgentConfig,
  threadId: string,
  runId: string,
  options: { maxWaitMs?: number; pollIntervalMs?: number } = {}
): Promise<{ status: string }> {
  const maxWaitMs = options.maxWaitMs ?? 1_200_000; // 20 minutes
  const pollIntervalMs = options.pollIntervalMs ?? 1500;
  const url = `${baseUrl(cfg.endpoint)}/threads/${threadId}/runs/${runId}?api-version=${encodeURIComponent(
    getApiVersion()
  )}`;
  const start = Date.now();
  while (Date.now() - start < maxWaitMs) {
    const headers = await getAgentAuthHeaders(cfg.apiKey);
    const res = await fetchWithTimeout(url, {
      method: 'GET',
      headers,
      timeoutMs: 20_000,
    });
    if (!res.ok) {
      const err = await res.text();
      throw new Error(`Get run failed (${res.status}): ${err.slice(0, 300)}`);
    }
    const data = await res.json();
    const status = (data.status ?? data.run_status ?? '').toLowerCase();
    if (status === 'completed' || status === 'succeeded') {
      return { status: 'completed' };
    }
    if (status === 'failed' || status === 'cancelled' || status === 'expired') {
      const lastError = data.last_error?.message ?? data.last_error ?? data.error ?? '';
      throw new Error(`Run ${status}: ${lastError || 'Unknown'}`);
    }
    await new Promise((r) => setTimeout(r, pollIntervalMs));
  }
  throw new Error('Run timed out waiting for completion');
}

/**
 * List messages and return the latest assistant message text.
 */
async function getLatestAssistantMessage(
  cfg: AzureAgentConfig,
  threadId: string
): Promise<string> {
  const url = `${baseUrl(cfg.endpoint)}/threads/${threadId}/messages?api-version=${encodeURIComponent(
    getApiVersion()
  )}`;
  const headers = await getAgentAuthHeaders(cfg.apiKey);
  const res = await fetchWithTimeout(url, {
    method: 'GET',
    headers,
    timeoutMs: 25_000,
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`List messages failed (${res.status}): ${err.slice(0, 300)}`);
  }
  const data = await res.json();
  const messages = data.data ?? data.messages ?? Array.isArray(data) ? data : [];
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    const role = (m.role ?? '').toLowerCase();
    if (role !== 'assistant') continue;
    const content = m.content;
    if (Array.isArray(content)) {
      const parts = content
        .filter((p: { type?: string; text?: { value?: string } }) => p.type === 'text' && p.text?.value)
        .map((p: { text: { value: string } }) => p.text.value);
      if (parts.length) return parts.join('\n').trim();
    }
    if (typeof content === 'string') return content.trim();
  }
  return '';
}

/**
 * Send messages to your Azure AI Foundry AGENT (threads + runs) and return the assistant reply.
 * Uses threadId when provided so the agent keeps conversation context.
 */
export async function sendToAzureAgent(
  messages: ChatMessage[],
  config?: AzureAgentConfig | null,
  existingThreadId?: string | null
): Promise<AgentReplyResult> {
  const endpointRaw = (config?.endpoint ?? process.env.AZURE_AGENT_ENDPOINT ?? '').trim();
  const cfg = config ?? getAzureAgentConfig();

  const lastUserMessage = [...messages].reverse().find((m) => m.role === 'user')?.content?.trim();
  if (!lastUserMessage) {
    return { content: 'No user message to send.', error: 'NO_MESSAGE' };
  }

  const openAiEndpointRaw = (process.env.AZURE_OPENAI_ENDPOINT ?? '').trim();

  // If Azure OpenAI is configured, prefer it when:
  // - an Azure OpenAI endpoint is set, or
  // - the "agent endpoint" actually points at Azure OpenAI.
  if (
    (openAiEndpointRaw && looksLikeAzureOpenAIEndpoint(openAiEndpointRaw)) ||
    (endpointRaw && looksLikeAzureOpenAIEndpoint(endpointRaw) && !looksLikeFoundryProjectEndpoint(endpointRaw))
  ) {
    return await sendToAzureOpenAIChatCompletions(messages);
  }

  if (!cfg) {
    return {
      content:
        'Agent is not configured. Set AZURE_AGENT_ENDPOINT (project URL), AZURE_AGENT_API_KEY, and AZURE_AGENT_ID in .env.local. If you are using Azure OpenAI instead, set AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_DEPLOYMENT_NAME.',
      error: 'NOT_CONFIGURED',
    };
  }

  try {
    let threadId: string;

    if (existingThreadId?.trim()) {
      threadId = existingThreadId.trim();
      await addMessage(cfg, threadId, lastUserMessage);
    } else {
      const created = await createThread(cfg, lastUserMessage);
      threadId = created.threadId;
    }

    const { runId } = await createRun(cfg, threadId);
    await waitForRun(cfg, threadId, runId);
    const content = await getLatestAssistantMessage(cfg, threadId);

    return {
      content: content || 'Agent completed but returned no text.',
      threadId,
    };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return {
      content: `Agent error: ${message}`,
      error: 'AGENT_ERROR',
    };
  }
}
