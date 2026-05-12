import { NextRequest, NextResponse } from 'next/server';
import { proxyToBackend } from '@/lib/backend-bridge';

export async function POST(req: NextRequest) {
  const body = await req.text();
  const res = await proxyToBackend('/generate_transformation_rules', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body,
    timeoutMs: 120_000,
  });
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: { 'Content-Type': res.headers.get('content-type') ?? 'application/json' },
  });
}

