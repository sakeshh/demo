import { NextResponse } from 'next/server';

function mask(value: string | undefined | null): string | null {
  if (!value) return null;
  const v = value.trim();
  if (v.length <= 8) return '***';
  return `${v.slice(0, 4)}…${v.slice(-4)}`;
}

export async function GET() {
  const agentEndpoint = process.env.AZURE_AGENT_ENDPOINT?.trim() || null;
  const openaiEndpoint = process.env.AZURE_OPENAI_ENDPOINT?.trim() || null;

  const deployment =
    process.env.AZURE_OPENAI_DEPLOYMENT_NAME?.trim() ||
    process.env.AZURE_OPENAI_DEPLOYMENT?.trim() ||
    process.env.DEPLOYMENT_NAME?.trim() ||
    null;

  return NextResponse.json({
    hasAzureAgentEndpoint: Boolean(agentEndpoint),
    azureAgentEndpoint: agentEndpoint,
    hasAzureAgentApiKey: Boolean(process.env.AZURE_AGENT_API_KEY?.trim()),
    hasAzureAgentId: Boolean(process.env.AZURE_AGENT_ID?.trim()),
    azureAgentAuthHeader: process.env.AZURE_AGENT_AUTH_HEADER?.trim() || null,
    azureAgentApiVersion: process.env.AZURE_AGENT_API_VERSION?.trim() || null,

    hasAzureOpenAIEndpoint: Boolean(openaiEndpoint),
    azureOpenAIEndpoint: openaiEndpoint,
    hasAzureOpenAIApiKey: Boolean(process.env.AZURE_OPENAI_API_KEY?.trim()),
    azureOpenAIApiKeyMasked: mask(process.env.AZURE_OPENAI_API_KEY),
    hasAzureOpenAIDeployment: Boolean(deployment),
    azureOpenAIDeployment: deployment,
    azureOpenAIApiVersion: process.env.AZURE_OPENAI_API_VERSION?.trim() || null,
  });
}

