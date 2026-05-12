import { NextResponse } from 'next/server';
import { proxyToBackend } from '@/lib/backend-bridge';

export async function GET() {
  const res = await proxyToBackend('/sources', { method: 'GET', timeoutMs: 20_000 });
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: { 'Content-Type': res.headers.get('content-type') ?? 'application/json' },
  });
}

