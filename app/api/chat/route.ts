import { NextRequest, NextResponse } from 'next/server';
import { sendToAzureAgent } from '@/lib/azure-agent';
import { getBackendBaseUrl, proxyToBackend } from '@/lib/backend-bridge';

export const maxDuration = 1200; // 20 minutes

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const messages = body.messages as Array<{ role: 'user' | 'assistant' | 'system'; content: string }> | undefined;
    const threadId = typeof body.threadId === 'string' ? body.threadId : undefined;

    if (!Array.isArray(messages) || messages.length === 0) {
      return NextResponse.json(
        { error: 'messages array is required', content: null, threadId: null },
        { status: 400 }
      );
    }

    // If a backend bridge is configured, route chat to LangGraph/MCP backend instead of Azure Agent/OpenAI directly.
    if (getBackendBaseUrl()) {
      const lastUser = [...messages].reverse().find((m) => m.role === 'user')?.content?.trim();
      if (!lastUser) {
        return NextResponse.json({ content: 'No user message to send.', error: 'NO_MESSAGE', threadId: null });
      }

      const backendRes = await proxyToBackend('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: typeof body.sessionId === 'string' ? body.sessionId : 'default',
          message: lastUser,
        }),
        timeoutMs: 1_200_000, // 20 minutes
      });
      const backendJson = await backendRes.json().catch(() => null);
      if (!backendRes.ok) {
        return NextResponse.json(
          {
            content: `Backend error (${backendRes.status}): ${backendJson?.detail ?? backendJson?.error ?? 'Unknown'}`,
            error: 'BACKEND_ERROR',
            threadId: null,
            payload: backendJson?.payload ?? null,
          },
          { status: 200 }
        );
      }

      return NextResponse.json({
        content: backendJson?.reply ?? 'No reply from backend.',
        error: null,
        threadId: null,
        payload: backendJson?.payload ?? null,
        backend: process.env.DEBUG_BACKEND_PAYLOAD === 'true' ? backendJson : undefined,
      });
    }

    const result = await sendToAzureAgent(messages, null, threadId ?? undefined);

    return NextResponse.json({
      content: result.content,
      error: result.error ?? null,
      threadId: result.threadId ?? threadId ?? null,
      payload: null,
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json(
      { content: `Server error: ${message}`, error: 'SERVER_ERROR', threadId: null, payload: null },
      { status: 500 }
    );
  }
}
