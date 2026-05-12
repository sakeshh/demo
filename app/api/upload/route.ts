import { NextRequest, NextResponse } from 'next/server';
import { proxyToBackend } from '@/lib/backend-bridge';

export const maxDuration = 60;

export async function POST(req: NextRequest) {
  try {
    const form = await req.formData();
    const res = await proxyToBackend('/upload?format=md', {
      method: 'POST',
      body: form as any,
      timeoutMs: 1_200_000, // 20 minutes
    });
    const text = await res.text();
    return new NextResponse(text, {
      status: res.status,
      headers: { 'Content-Type': res.headers.get('content-type') ?? 'application/json' },
    });
  } catch (err: any) {
    return NextResponse.json(
      { ok: false, error: 'UPLOAD_FAILED', message: err?.message ? String(err.message) : 'Upload failed' },
      { status: 500 }
    );
  }
}

