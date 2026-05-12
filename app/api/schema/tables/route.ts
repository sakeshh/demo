import { NextRequest, NextResponse } from 'next/server';
import { proxyToBackend } from '@/lib/backend-bridge';

export async function GET(req: NextRequest) {
  const url = new URL(req.url);
  const ttlSeconds = url.searchParams.get('ttl_seconds') ?? '30';
  const qs = `?ttl_seconds=${encodeURIComponent(ttlSeconds)}`;

  const res = await proxyToBackend(`/schema/tables${qs}`, {
    method: 'GET',
    headers: { 'Content-Type': 'application/json' },
    timeoutMs: 60_000,
  });

  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: { 'Content-Type': res.headers.get('content-type') ?? 'application/json' },
  });
}

