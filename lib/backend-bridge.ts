export function getBackendBaseUrl(): string | null {
  const v = process.env.BACKEND_BASE_URL?.trim();
  return v ? v.replace(/\/$/, '') : null;
}

function getBackendAuthToken(): string | null {
  const v = process.env.BACKEND_AUTH_TOKEN?.trim();
  return v || null;
}

export async function proxyToBackend(
  path: string,
  init: RequestInit & { timeoutMs?: number } = {}
): Promise<Response> {
  const base = getBackendBaseUrl();
  if (!base) {
    return new Response(
      JSON.stringify({ error: 'BACKEND_BASE_URL is not set', ok: false }),
      { status: 500, headers: { 'Content-Type': 'application/json' } }
    );
  }

  const url = `${base}${path.startsWith('/') ? '' : '/'}${path}`;

  const controller = new AbortController();
  const t = setTimeout(() => controller.abort(), init.timeoutMs ?? 30_000);
  try {
    const { timeoutMs: _timeoutMs, ...rest } = init;
    const headers = new Headers(rest.headers || {});
    const token = getBackendAuthToken();
    if (token) headers.set('X-Backend-Token', token);
    if (!headers.has('X-Request-Id')) headers.set('X-Request-Id', crypto.randomUUID());
    try {
      return await fetch(url, { ...rest, headers, signal: controller.signal });
    } catch (err: any) {
      const name = err?.name ? String(err.name) : '';
      const msg = err?.message ? String(err.message) : 'Unknown error';
      const isAbort = name === 'AbortError';
      const status = isAbort ? 504 : 502;
      return new Response(
        JSON.stringify({
          ok: false,
          error: isAbort ? 'BACKEND_TIMEOUT' : 'BACKEND_UNREACHABLE',
          message: msg,
          backend: url,
        }),
        { status, headers: { 'Content-Type': 'application/json' } }
      );
    }
  } finally {
    clearTimeout(t);
  }
}

