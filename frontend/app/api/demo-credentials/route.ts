// These two local demo passwords are intentionally displayed at sign-in.
// Read at request time: never embed environment values in the browser bundle.
export const dynamic = 'force-dynamic';
export async function GET() {
  const alice = process.env.DEMO_ALICE_PASSWORD;
  const bob = process.env.DEMO_BOB_PASSWORD;
  const headers = { 'Cache-Control': 'no-store' };
  if (!alice || !bob) return Response.json({ error: 'Local demo credentials are unavailable. Run local setup and restart the web service.' }, { status: 503, headers });
  return Response.json({ accounts: [{ username: 'alice', password: alice }, { username: 'bob', password: bob }] }, { headers });
}
