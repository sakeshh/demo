import { NextRequest, NextResponse } from 'next/server';
import { proxyToBackend } from '@/lib/backend-bridge';

export async function GET(_: NextRequest, { params }: { params: { sessionId: string } }) {
  try {
    const res = await proxyToBackend(`/sessions/${encodeURIComponent(params.sessionId)}`, {
      method: 'GET',
      timeoutMs: 20_000,
    });
    const text = await res.text();
    return new NextResponse(text, {
      status: res.status,
      headers: { 'Content-Type': res.headers.get('content-type') ?? 'application/json' },
    });
  } catch (err: any) {
    return NextResponse.json(
      {
        ok: false,
        error: 'BACKEND_UNREACHABLE',
        message: err?.message ? String(err.message) : 'Backend unreachable',
        session: { id: params.sessionId, messages: [] },
      },
      { status: 502 }
    );
  }
}

