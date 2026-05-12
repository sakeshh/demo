import { NextRequest, NextResponse } from 'next/server';
import { proxyToBackend } from '@/lib/backend-bridge';

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const res = await proxyToBackend('/sessions/context', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      timeoutMs: 30_000,
    });
    const text = await res.text();
    return new NextResponse(text, {
      status: res.status,
      headers: { 'Content-Type': res.headers.get('content-type') ?? 'application/json' },
    });
  } catch (err: any) {
    return NextResponse.json(
      { ok: false, error: 'CONTEXT_FAILED', message: err?.message ? String(err.message) : 'Failed' },
      { status: 500 }
    );
  }
}

