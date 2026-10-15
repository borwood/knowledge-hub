'use client';
import { useEffect, useState } from 'react';
type Account = { username: string; password: string };
export default function DemoCredentials() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [state, setState] = useState('loading');
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch('/api/demo-credentials', { cache: 'no-store', signal: controller.signal });
        if (!response.ok) throw new Error('unavailable');
        const result = await response.json();
        if (!controller.signal.aborted) { setAccounts(result.accounts); setState('ready'); }
      } catch { if (!controller.signal.aborted) setState('unavailable'); }
    })();
    return () => controller.abort();
  }, []);
  return <section className="demo-credentials" aria-labelledby="demo-accounts-heading">
    <h4 id="demo-accounts-heading">Local demo accounts</h4>
    <p>Demo-only credentials for this local environment. Choose either account on the Keycloak sign-in page.</p>
    {state === 'loading' && <p role="status">Loading demo credentials…</p>}
    {state === 'unavailable' && <p role="status">Local demo credentials are unavailable. Run local setup and restart the web service.</p>}
    {accounts.map(account => <dl key={account.username}><dt>Username</dt><dd><code>{account.username}</code></dd><dt>Password</dt><dd><code data-demo-password={account.username}>{account.password}</code></dd></dl>)}
  </section>;
}
