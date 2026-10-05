'use client';
import Discovery, { type DocumentRecord } from './discovery';
import { useCallback, useEffect, useRef, useState } from 'react';

type User = { username: string; csrf_token: string; expires_at: number };
export default function Ingestion() {
  const [user, setUser] = useState<User | null>(null);
  const [uploaded, setUploaded] = useState<DocumentRecord | null>(null);
  const [revision, setRevision] = useState(0);
  const [inquiryActive, setInquiryActive] = useState(false);
  const authBusy = useRef(false);
  const ended = useRef(false);
  const identityToken = useRef<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState('');
  const busy = useRef(false);
  const generation = useRef(0);
  const input = useRef<HTMLInputElement>(null);
  const clear = useCallback(() => {
    generation.current += 1;
    ended.current = true; setUser(null); setUploaded(null); setFile(null); setMessage('');
    if (input.current) input.current.value = '';
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
        generation.current++; setUploaded(null); setFile(null); setMessage('');
        if (input.current) input.current.value = '';
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
  useEffect(() => {
    if (!user) return;
    const timer = setTimeout(clear, Math.max(0, user.expires_at * 1000 - Date.now()));
    return () => clearTimeout(timer);
  }, [user, clear]);
  async function upload(event: React.FormEvent) {
    event.preventDefault();
    if (!user || !file || busy.current) return;
    busy.current = true; setPending(true); setMessage('');
    const current = generation.current;
    const body = new FormData(); body.append('file', file);
    try {
      const response = await fetch('/api/documents', { method: 'POST', body, headers: { 'X-CSRF-Token': user.csrf_token } });
      if (current !== generation.current) return;
      if (response.status === 401) { clear(); return; }
      const result = await response.json();
      if (current !== generation.current) return;
      if (!response.ok) setMessage(`${result.error.code}: ${result.error.message}`);
      else {
        setUploaded(result); setRevision(value => value + 1);
        if (current === generation.current) setMessage((result.state === 'ready' ? 'Document ready. Synthetic extraction complete.' : `Document failed: ${result.error_code}. Original source retained; no facts extracted.`) + ` Upload ID: ${result.id}.`);
      }
    } catch { if (current === generation.current) setMessage('Upload could not be confirmed. Refresh the list before trying again.'); }
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
    {!user ? <div className="welcome-panel"><h3>Your documents, connected to their evidence.</h3><p>Sign in to upload an invoice, ask a supported question, and inspect the source behind each answer.</p><a className="sign-in" href="/api/auth/login">Sign in with Keycloak</a><p className="muted">A private collection for each demo account.</p></div> : <>
      <details className="upload-disclosure" open={!inquiryActive}><summary>Upload a PDF</summary><div className="upload-panel"><div><h3>Add a document</h3><p>Unencrypted PDF &middot; 1–10 pages &middot; up to 5 MiB</p><p className="muted">Use the supplied synthetic invoice for questions. Other valid PDFs are retained with a failed extraction.</p></div>
      <form onSubmit={upload}>
        <label htmlFor="document-file">PDF document</label>
        <input ref={input} id="document-file" type="file" accept=".pdf,application/pdf" disabled={pending}
          onChange={event => setFile(event.target.files?.[0] || null)} />
        <p>{file ? `Selected: ${file.name}` : 'No file selected'}</p>
        <button className="primary" type="submit" disabled={!file || pending}>{pending ? 'Uploading…' : 'Upload PDF'}</button>
      </form></div></details>
      <p aria-live="polite">{pending ? 'Processing upload. Please wait.' : ''}</p>
      <Discovery key={user.csrf_token} csrf={user.csrf_token} onExpired={clear} uploaded={uploaded} revision={revision} onInquiryChange={setInquiryActive} />
    </>}
    <p role="alert" className={message.startsWith('Document ready.') ? 'success-notice' : undefined}>{message}</p>
  </section>;
}
