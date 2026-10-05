import { NextRequest } from 'next/server';

// Explicit path/method allowlist: never accept a client-selected upstream URL.
async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const target = '/' + path.join('/');
  const allowed = request.method === 'GET'
    ? /^\/(auth\/(login|callback|me)|documents(?:\/[a-zA-Z0-9-]+(?:\/(source|provenance))?)?)$/.test(target)
    : request.method === 'POST' && (target === '/graphql' || target === '/auth/logout' || target === '/documents');
  if (!allowed) return Response.json({ error: { code: 'NOT_FOUND', message: 'Not found' } }, { status: 404 });
  const headers = new Headers();
  for (const name of ['cookie', 'content-type', 'origin', 'x-csrf-token']) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  try {
    const options: RequestInit & { duplex?: 'half' } = {
      method: request.method, headers, cache: 'no-store', redirect: 'manual',
      signal: AbortSignal.timeout(30000),
    };
    if (request.method === 'POST') { options.body = request.body; options.duplex = 'half'; }
    const response = await fetch(`${process.env.API_URL || 'http://127.0.0.1:8000'}${target}${request.nextUrl.search}`, options);
    const outgoing = new Headers({ 'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff' });
    for (const name of ['content-type', 'content-disposition', 'location']) {
      const value = response.headers.get(name);
      if (value) outgoing.set(name, value);
    }
    for (const cookie of response.headers.getSetCookie()) outgoing.append('set-cookie', cookie);
    return new Response(response.body, { status: response.status, headers: outgoing });
  } catch {
    return Response.json({ error: { code: 'DEPENDENCY_UNAVAILABLE', message: 'Service unavailable. Try again.' } },
      { status: 503, headers: { 'Cache-Control': 'no-store' } });
  }
}

export const GET = proxy;
export const POST = proxy;
