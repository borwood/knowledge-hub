'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import Ingestion from './ingestion';

type State = 'loading' | 'ready' | 'unavailable';
type Dependencies = { sqlite?: string; object_store?: string };
export default function Page() {
  const [state, setState] = useState<State>('loading');
  const [dependencies, setDependencies] = useState<Dependencies>({});
  const active = useRef(false);
  const check = useCallback(async () => {
    if (active.current) return;
    active.current = true;
    setState('loading');
    setDependencies({});
    try {
      const response = await fetch('/api/health', { cache: 'no-store', signal: AbortSignal.timeout(8000) });
      const result = await response.json();
      setDependencies(result.dependencies || {});
      setState(response.ok && result.status === 'ready' ? 'ready' : 'unavailable');
    } catch { setState('unavailable'); }
    finally { active.current = false; }
  }, []);
  useEffect(() => { void check(); const timer = setInterval(check, 15000); return () => clearInterval(timer); }, [check]);
  return <main>
    <header className="app-header"><div><p className="eyebrow">DOCUMENT WORKSPACE</p><h1>Knowledge Hub</h1><p>From document to answer. Every fact, traceable.</p></div><span className="local-badge">Local demo</span></header>
    <Ingestion />
    <details className="runtime-details"><summary>Service status &amp; developer details</summary><section aria-labelledby="connection-title">
      <h2 id="connection-title">Service status</h2>
      <div className="connection"><p role="status" aria-live="polite">{state === 'loading' ? 'Checking connection…' : state === 'ready' ? 'Ready for local development' : 'Connection unavailable'}</p><button onClick={check} aria-disabled={state === 'loading'}>Check connection</button></div>
      <p>Checks run every 15 seconds.{state === 'unavailable' ? ' Run docker compose up -d, then check again.' : ''}</p>
      <table><thead><tr><th scope="col">Dependency</th><th scope="col">Status</th></tr></thead><tbody>
        <tr><th scope="row">SQLite</th><td>{state === 'loading' ? 'Checking' : dependencies.sqlite || 'Unknown'}</td></tr>
        <tr><th scope="row">SeaweedFS (S3)</th><td>{state === 'loading' ? 'Checking' : dependencies.object_store || 'Unknown'}</td></tr>
      </tbody></table>
    </section>
    <section aria-labelledby="api-title"><h2 id="api-title">API</h2>
      <ul><li><a href="http://127.0.0.1:8000/health/live">GET /health/live</a> — API liveness</li><li><a href="/api/health">GET /api/health</a> — readiness through the frontend proxy</li><li><a href="http://127.0.0.1:8000/graphql?query=%7B%20health%20%7B%20status%20sqlite%20objectStore%20%7D%20%7D">GraphQL health</a> — Strawberry health query</li></ul>
      <pre><code>{'{ health { status sqlite objectStore } }'}</code></pre>
      <p>Readiness checks SQLite access and the S3 bucket. A failed dependency returns HTTP 503.</p>
    </section>
    <section aria-labelledby="fixture-title"><h2 id="fixture-title">Invoice fixture</h2>
      <p><code>fixtures/invoice/invoice.pdf</code> contains synthetic demo data. Extraction fields and confidence values are invented; no cloud extraction is performed.</p>
      <pre><code>python -m backend.fixture adapt invoice.pdf</code></pre>
      <p>The adapter accepts only the sample document hash. Input contract: unencrypted PDF, at most 5 MiB and 10 pages. See <code>docs/fixture-contract.md</code> for errors and provenance fields.</p>
    </section>
    </details>
    <footer>Ask a supported invoice question and follow each citation to its source page. All sample values and confidence scores are synthetic.</footer>
  </main>;
}
