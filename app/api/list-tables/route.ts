import { NextRequest, NextResponse } from 'next/server';
import { proxyToBackend } from '@/lib/backend-bridge';
import { readFile } from 'node:fs/promises';
import path from 'node:path';

export async function POST(req: NextRequest) {
  const rawBody = await req.text();
  let bodyToSend = rawBody;
  // If client didn't supply config, use repo's sources.yaml as config text.
  // The backend supports ${ENV_VAR} placeholders in the config.
  if (!rawBody.trim()) {
    try {
      const sourcesPath = path.join(process.cwd(), 'Agent Dhara Backend', 'config', 'sources.yaml');
      const cfg = await readFile(sourcesPath, 'utf-8');
      bodyToSend = JSON.stringify({ config: cfg });
    } catch {
      bodyToSend = JSON.stringify({ config: '' });
    }
  }
  const res = await proxyToBackend('/list_tables', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: bodyToSend,
    timeoutMs: 60_000,
  });
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: { 'Content-Type': res.headers.get('content-type') ?? 'application/json' },
  });
}

