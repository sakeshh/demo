import { NextRequest, NextResponse } from 'next/server';
import { proxyToBackend } from '@/lib/backend-bridge';

export async function GET(req: NextRequest) {
  const url = new URL(req.url);
  const limit = url.searchParams.get('limit');
  const path = limit ? `/sessions?limit=${encodeURIComponent(limit)}` : '/sessions';
  try {
    const res = await proxyToBackend(path, { method: 'GET', timeoutMs: 20_000 });
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
        sessions: [],
      },
      { status: 502 }
    );
  }
}

