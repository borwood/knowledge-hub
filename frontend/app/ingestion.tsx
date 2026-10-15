'use client';
import Discovery, { type DocumentRecord } from './discovery';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useEvents, useInspectable, type EventHandle } from '@borwood/demoable-react';
import { eventLifetime } from './demo-events';
import { explanations } from './demo-context';
import DemoCredentials from './demo-credentials';

type User = { username: string; csrf_token: string; expires_at: number };
export default function Ingestion() {
  const events = useEvents();
  const uploadEvent = useRef<EventHandle | null>(null);
  const uploadAbort = useRef<AbortController | null>(null);
  const uploadSubmitted = useRef(false);
  const uploadContext = useInspectable<HTMLDetailsElement>({label: 'Document ingestion', context: explanations.upload});
  const loginContext = useInspectable<HTMLAnchorElement>({label: 'Demo sign-in', context: <DemoCredentials />});
  const [user, setUser] = useState<User | null>(null);
  const [uploaded, setUploaded] = useState<DocumentRecord | null>(null);
  const [revision, setRevision] = useState(0);
  const [inquiryActive, setInquiryActive] = useState(false);
  const authBusy = useRef(false);
  const ended = useRef(false);
  const identityToken = useRef<string | null>(null);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState('');
  const busy = useRef(false);
  const generation = useRef(0);
  const inputContext = useInspectable<HTMLFormElement>({label: 'PDF input contract', context: explanations.input});
  const clear = useCallback(() => {
    uploadEvent.current?.cancel({content: uploadSubmitted.current ? 'Upload abandoned because the session ended. Confirmation is unavailable; check the collection after signing in.' : 'Demo invoice retrieval abandoned because the session ended. No upload was submitted.'});
    uploadAbort.current?.abort();
    generation.current += 1;
    ended.current = true; setUser(null); setUploaded(null); setMessage('');
  }, []);
  const load = useCallback(async () => {
    if (authBusy.current || ended.current) return;
    authBusy.current = true;
    const current = generation.current;
    try {
      const identity = await fetch('/api/auth/me', { cache: 'no-store' });
      if (current !== generation.current) return;
      if (identity.status === 401) { clear(); return; }
      if (!identity.ok) throw new Error('Sign-in service unavailable. Try again.');
      const nextUser = await identity.json() as User;
      if (current !== generation.current) return;
      if (identityToken.current && identityToken.current !== nextUser.csrf_token) {
        uploadEvent.current?.cancel({content: uploadSubmitted.current ? 'Upload superseded by an identity change. Check the collection before retrying.' : 'Demo invoice retrieval superseded by an identity change. No upload was submitted.'});
        uploadAbort.current?.abort();
        generation.current++; setUploaded(null); setMessage('');
      }
      identityToken.current = nextUser.csrf_token;
      setUser(nextUser);
    } catch (error) {
      if (current === generation.current) setMessage(error instanceof Error ? error.message : 'Service unavailable.');
    } finally { authBusy.current = false; }
  }, [clear]);
  useEffect(() => {
    void load();
    const timer = setInterval(load, 10000);
    const refresh = () => { if (document.visibilityState === 'visible') void load(); };
    document.addEventListener('visibilitychange', refresh);
    return () => { clearInterval(timer); document.removeEventListener('visibilitychange', refresh); };
  }, [load]);
  useEffect(() => () => {
    generation.current++;
    uploadAbort.current?.abort();
    uploadEvent.current?.cancel({content: uploadSubmitted.current ? 'Upload abandoned when the workspace closed. The server may have retained the document.' : 'Demo invoice retrieval abandoned when the workspace closed. No upload was submitted.'});
  }, []);
  useEffect(() => {
    if (!user) return;
    const timer = setTimeout(clear, Math.max(0, user.expires_at * 1000 - Date.now()));
    return () => clearTimeout(timer);
  }, [user, clear]);
  async function upload(event: React.FormEvent) {
    event.preventDefault();
    if (!user || busy.current) return;
    busy.current = true; setPending(true); setMessage('');
    const current = generation.current;
    uploadSubmitted.current = false;
    const operation = events.start({label: 'Upload PDF', state: 'running', content: 'Fetching the fixed synthetic invoice before submitting it to authenticated ingestion.', lifetime: eventLifetime});
    uploadEvent.current = operation;
    const controller = new AbortController(); uploadAbort.current = controller;
    let submitted = false;
    try {
      const sample = await fetch('/demo-invoice.pdf', { cache: 'no-store', signal: controller.signal });
      if (current !== generation.current) return;
      if (!sample.ok) throw new Error('sample');
      const file = await sample.blob();
      if (current !== generation.current || controller.signal.aborted) return;
      const body = new FormData(); body.append('file', file, 'invoice.pdf');
      operation.update({content: 'Submitting the synthetic invoice for validation, original-source retention and saved fixture extraction.'});
      submitted = true;
      uploadSubmitted.current = true;
      const response = await fetch('/api/documents', { method: 'POST', body, headers: { 'X-CSRF-Token': user.csrf_token }, signal: controller.signal });
      if (current !== generation.current) return;
      if (response.status === 401) { operation.fail({content: 'Session expired; upload was not confirmed.'}); clear(); return; }
      const result = await response.json();
      if (current !== generation.current) return;
      if (!response.ok) { operation.fail({content: 'Upload rejected by the service. The app shows recovery details.'}); setMessage(`${result.error.code}: ${result.error.message}`); }
      else {
        if (result.state === 'ready') operation.complete({content: 'Original retained and synthetic facts ready. Open the document to follow its evidence.'});
        else operation.fail({content: 'Original retained, but extraction did not produce ready facts. This is a domain failure, even with a successful HTTP response.'});
        setUploaded(result); setRevision(value => value + 1);
        if (current === generation.current) setMessage((result.state === 'ready' ? 'Document ready. Synthetic extraction complete.' : `Document failed: ${result.error_code}. Original source retained; no facts extracted.`) + ` Upload ID: ${result.id}.`);
      }
    } catch { if (current === generation.current) {
      const message = submitted ? 'Upload could not be confirmed. Refresh the list before trying again.' : 'Demo invoice unavailable. Nothing was uploaded. Try again.';
      operation.fail({content: message}); setMessage(message);
    } }
    finally { busy.current = false; setPending(false); }
  }
  async function logout() {
    if (!user) return;
    const csrf = user.csrf_token;
    clear();
    try {
      const response = await fetch('/api/auth/logout', { method: 'POST', headers: { 'X-CSRF-Token': csrf } });
      if (response.ok) window.location.assign((await response.json()).logout_url);
      else if (response.status !== 401) setMessage('Sign out could not be confirmed. Reload and try again.');
    } catch { setMessage('Sign out could not be confirmed. Reload and try again.'); }
  }
  return <section aria-labelledby="documents-title">
    <div className="workspace-heading"><h2 id="documents-title">Your documents</h2>{user && <div className="account"><span>Signed in as {user.username}</span><button onClick={logout}>Sign out</button></div>}</div>
    {!user ? <div className="welcome-panel"><h3>Your documents, connected to their evidence.</h3><p>Sign in to upload the supplied invoice, ask a supported question, and inspect the source behind each answer.</p><a ref={loginContext.ref} className="sign-in" href="/api/auth/login">Sign in with Keycloak</a><p className="muted">Your documents stay in your private collection.</p></div> : <>
      <details ref={uploadContext.ref} className="upload-disclosure" open={!inquiryActive}><summary>Upload a demo invoice</summary><div className="upload-panel"><div><h3>Add the demo invoice</h3><p>One synthetic PDF, ready to explore.</p><p className="muted">The supplied invoice uses synthetic fields and invented confidence. Each upload creates a real document in your private collection.</p></div>
      <form ref={inputContext.ref} onSubmit={upload}>
        <p>Supplied file: <strong>invoice.pdf</strong></p>
        <button className="primary" type="submit" disabled={pending}>{pending ? 'Uploading…' : 'Upload demo invoice'}</button>
      </form></div></details>
      <p aria-live="polite">{pending ? 'Processing upload. Please wait.' : ''}</p>
      <Discovery key={user.csrf_token} csrf={user.csrf_token} onExpired={clear} uploaded={uploaded} revision={revision} onInquiryChange={setInquiryActive} />
    </>}
    <p role="alert" className={message.startsWith('Document ready.') ? 'success-notice' : undefined}>{message}</p>
  </section>;
}
