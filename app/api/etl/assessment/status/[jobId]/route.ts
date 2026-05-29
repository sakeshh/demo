import { NextRequest, NextResponse } from 'next/server';
import { getBackendBaseUrl, proxyToBackend } from '@/lib/backend-bridge';

export async function GET(
  req: NextRequest,
  { params }: { params: { jobId: string } }
) {
  if (!getBackendBaseUrl()) {
    return NextResponse.json(
      { ok: false, error: 'BACKEND_NOT_CONFIGURED', message: 'Set BACKEND_BASE_URL' },
      { status: 503 }
    );
  }
  try {
    const res = await proxyToBackend(`/etl/assessment/status/${params.jobId}`, {
      method: 'GET',
    });
    const text = await res.text();
    return new NextResponse(text, {
      status: res.status,
      headers: { 'Content-Type': res.headers.get('content-type') ?? 'application/json' },
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ ok: false, error: 'PROXY_FAILED', message }, { status: 500 });
  }
}
