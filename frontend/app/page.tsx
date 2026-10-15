'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import Ingestion from './ingestion';
import { useInspectable } from '@borwood/demoable-react';
import { DemoToggle } from './demo-shell';
import { explanations } from './demo-context';

type State = 'loading' | 'ready' | 'unavailable';
type Dependencies = { sqlite?: string; object_store?: string };
export default function Page() {
  const service = useInspectable<HTMLElement>({label: 'Service readiness', context: explanations.service});
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
    <header className="app-header"><div><p className="eyebrow">DOCUMENT WORKSPACE</p><h1>Knowledge Hub</h1><p>From document to answer. Every fact, traceable.</p></div><div className="demo-entry"><span className="local-badge">Local demo</span><DemoToggle /></div></header>
    <Ingestion />
    <details className="runtime-details"><summary>Service status &amp; developer details</summary><section ref={service.ref} aria-labelledby="connection-title">
      <h2 id="connection-title">Service status</h2>
      <div className="connection"><p role="status" aria-live="polite">{state === 'loading' ? 'Checking connection…' : state === 'ready' ? 'Ready for local development' : 'Connection unavailable'}</p><button onClick={check} aria-disabled={state === 'loading'}>Check connection</button></div>
      <p>Checks run every 15 seconds.{state === 'unavailable' ? ' Run docker compose up -d, then check again.' : ''}</p>
      <table><thead><tr><th scope="col">Dependency</th><th scope="col">Status</th></tr></thead><tbody>
        <tr><th scope="row">SQLite</th><td>{state === 'loading' ? 'Checking' : dependencies.sqlite || 'Unknown'}</td></tr>
        <tr><th scope="row">SeaweedFS (S3)</th><td>{state === 'loading' ? 'Checking' : dependencies.object_store || 'Unknown'}</td></tr>
      </tbody></table>
    </section>
    </details>
    <footer>Ask a supported invoice question and follow each citation to its source page. All sample values and confidence scores are synthetic.</footer>
  </main>;
}
