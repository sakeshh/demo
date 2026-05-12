import { NextRequest, NextResponse } from 'next/server';
import { proxyToBackend } from '@/lib/backend-bridge';

export const maxDuration = 1200; // 20 minutes

export async function POST(req: NextRequest) {
  const body = await req.text();
  const res = await proxyToBackend('/assess', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body,
    timeoutMs: 1_200_000, // 20 minutes
  });
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: { 'Content-Type': res.headers.get('content-type') ?? 'application/json' },
  });
}

