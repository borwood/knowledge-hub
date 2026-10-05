export async function GET() {
  try {
    const response = await fetch(`${process.env.API_URL || 'http://127.0.0.1:8000'}/health/ready`, {
      cache: 'no-store', signal: AbortSignal.timeout(6000),
    });
    return Response.json(await response.json(), { status: response.status, headers: { 'Cache-Control': 'no-store' } });
  } catch {
    return Response.json({ status: 'unavailable' }, { status: 503, headers: { 'Cache-Control': 'no-store' } });
  }
}
