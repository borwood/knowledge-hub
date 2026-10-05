'use client';
import { useEffect, useRef, useState } from 'react';
import Questions from './questions';

export type DocumentRecord = { id: string; filename: string; state: string; error_code: string | null; created_at: string; byte_length: number };
type Collection = { documents: DocumentRecord[]; total: number; page: number; total_pages: number };
type Position = { q: string; state: string; page: number; selected: string | null; scroll: number; opener: string | null };
const newest: Position = { q: '', state: '', page: 1, selected: null, scroll: 0, opener: null };

export function Metadata({ item }: { item: DocumentRecord }) {
  const bytes = `${item.byte_length.toLocaleString('en-US')} bytes`;
  const size = item.byte_length < 1024 ? bytes : `${(item.byte_length / (item.byte_length < 1048576 ? 1024 : 1048576)).toFixed(1)} ${item.byte_length < 1048576 ? 'KiB' : 'MiB'} (${bytes})`;
  return <div className="document-info"><div className="document-title"><strong>{item.filename}</strong><span className={'state-badge state-' + item.state}>{item.state}{item.error_code ? ` (${item.error_code})` : ''}</span></div>
    <dl className="document-metadata">
      <dt>Uploaded</dt><dd><time dateTime={item.created_at}>{new Date(item.created_at).toISOString().slice(0, 19).replace('T', ' ')} UTC</time></dd>
      <dt>Size</dt><dd>{size}</dd>
    </dl>
    <details className="record-details"><summary>Upload details</summary><dl className="document-metadata"><dt>Upload ID</dt><dd><code>{item.id}</code></dd></dl>
    {item.state === 'ready' && <p className="muted">Synthetic fields and invented confidence</p>}</details>
    </div>;

}

export default function Discovery({ csrf, onExpired, uploaded, revision, onInquiryChange }: { csrf: string; onExpired: () => void; uploaded: DocumentRecord | null; revision: number; onInquiryChange: (active: boolean) => void }) {
  const [position, setPosition] = useState<Position>(newest);
  useEffect(() => { onInquiryChange(Boolean(position.selected)); }, [position.selected, onInquiryChange]);
  const [draft, setDraft] = useState('');
  const [collection, setCollection] = useState<Collection | null>(null);
  const [selected, setSelected] = useState<DocumentRecord | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const current = useRef(position);
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const restore = useRef(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const inquiry = useRef<HTMLHeadingElement>(null);
  // History contains opaque keys only. Protected criteria/IDs live in this mounted session.
  const history = useRef({ token: '', key: 0, entries: new Map<number, Position>() });

  function show(next: Position, returning = false) {
    generation.current++; controller.current?.abort();
    current.current = next; setPosition(next); setDraft(next.q);
    setSelected(null); setCollection(null); setError(''); setLoading(true);
    restore.current = returning;
  }
  function remember(next: Position, push = false) {
    const h = history.current;
    if (push) h.key++;
    h.entries.set(h.key, next);
    const state = { ...window.history.state, hub: h.token, entry: h.key };
    if (push) window.history.pushState(state, ''); else window.history.replaceState(state, '');
  }
  function change(next: Position) { remember(next); show(next); }
  function open(id: string, opener: string | null) {
    if (current.current.selected) {
      const next = { ...current.current, selected: id };
      remember(next); show(next); window.scrollTo(0, 0); return;
    }
    const back = { ...current.current, scroll: window.scrollY, opener };
    remember(back);
    const next = { ...back, selected: id };
    remember(next, true); show(next); window.scrollTo(0, 0);
  }
  useEffect(() => {
    const h = history.current;
    h.token = crypto.randomUUID(); h.key = 0; h.entries.set(0, newest);
    window.history.replaceState({ ...window.history.state, hub: h.token, entry: 0 }, '');
    const previousRestoration = window.history.scrollRestoration;
    window.history.scrollRestoration = 'manual';
    const pop = (event: PopStateEvent) => {
      const next = event.state?.hub === h.token ? h.entries.get(event.state.entry) : undefined;
      if (next) { h.key = event.state.entry; show(next, !next.selected); }
      else { h.key = 0; remember(newest); show(newest); }
    };
    window.addEventListener('popstate', pop);
    return () => {
      generation.current++; controller.current?.abort(); h.entries.clear();
      window.removeEventListener('popstate', pop); window.history.scrollRestoration = previousRestoration;
      window.history.replaceState({ ...window.history.state, hub: null, entry: null }, '');
    };
  }, []);
  useEffect(() => {
    const request = ++generation.current;
    const abort = new AbortController(); controller.current = abort;
    setLoading(true); setError(''); setSelected(null);
    const path = position.selected ? `/api/documents/${encodeURIComponent(position.selected)}` :
      '/api/documents?' + new URLSearchParams({ page: String(position.page), page_size: '10', q: position.q, state: position.state });
    const valid = () => request === generation.current && !abort.signal.aborted;
    void (async () => {
      try {
        const response = await fetch(path, { cache: 'no-store', signal: abort.signal });
        if (!valid()) return;
        if (response.status === 401) { onExpired(); return; }
        const result = await response.json();
        if (!valid()) return;
        if (!response.ok) throw new Error(position.selected ? 'Document unavailable. Try again or return to documents.' : 'Document collection unavailable. Try again.');
        if (position.selected) setSelected(result);
        else {
          setCollection(result);
          if (result.page !== position.page) {
            const clamped = { ...position, page: result.page }; current.current = clamped; remember(clamped);
          }
        }
      } catch (error) { if (valid()) setError(error instanceof Error ? error.message : 'Documents unavailable. Try again.'); }
      finally { if (valid()) setLoading(false); }
    })();
    return () => { abort.abort(); generation.current++; };
  }, [position, revision, retry, onExpired]);
  useEffect(() => {
    if (loading) return;
    if (position.selected) inquiry.current?.focus({ preventScroll: true });
    else if (restore.current) {
      const opener = position.opener ? document.getElementById(position.opener) : null;
      (opener || heading.current)?.focus({ preventScroll: true });
      window.scrollTo(0, position.scroll); restore.current = false;
    }
  }, [loading, position]);

  return <>
    {uploaded && <div className="upload-actions"><button id="open-uploaded" onClick={() => open(uploaded.id, 'open-uploaded')}>Open uploaded document</button>{' '}
      <button onClick={() => change({ ...newest })}>Show in collection</button></div>}
    {position.selected ? <section aria-label="Document inquiry">
      <button onClick={() => window.history.back()}>Back to documents</button>
      <h3 ref={inquiry} tabIndex={-1}>Document inquiry</h3>
      {selected && <><Metadata item={selected} />
        {selected.state !== 'ready' && <p>This document is {selected.state}{selected.error_code ? ` (${selected.error_code})` : ''}. Questions require a ready document.</p>}
        <Questions key={selected.id} document={selected} csrf={csrf} onExpired={onExpired} /></>}
    </section> : <section aria-labelledby="collection-heading">
      <h3 id="collection-heading" ref={heading} tabIndex={-1}>Document collection</h3>
      <form className="collection-filters" onSubmit={event => { event.preventDefault(); change({ ...current.current, q: draft.trim(), page: 1, scroll: 0 }); }}>
        <div className="search-field"><label htmlFor="document-search">Search documents</label>
        <input id="document-search" type="search" maxLength={200} value={draft} onChange={event => setDraft(event.target.value)} placeholder="Filename or upload ID" />
        </div><button type="submit">Search</button><div className="state-field">
        <label htmlFor="document-state">Ingestion state</label>
        <select id="document-state" value={position.state} onChange={event => change({ ...current.current, state: event.target.value, page: 1, scroll: 0 })}>
          <option value="">All</option><option value="ready">Ready</option><option value="processing">Processing</option><option value="failed">Failed</option>
        </select></div>
      </form>
      {!loading && collection && <>
        <div className="collection-pagination"><p role="status">{collection.total} results · Page {collection.page} of {collection.total_pages}</p>
        <nav aria-label="Collection pages"><button disabled={collection.page <= 1} onClick={() => change({ ...current.current, page: collection.page - 1 })}>Previous page</button>{' '}
          <button disabled={collection.page >= collection.total_pages} onClick={() => change({ ...current.current, page: collection.page + 1 })}>Next page</button></nav></div>
        {collection.total === 0 ? <p>{position.q || position.state ? 'No matching documents. Try another search or state.' : 'No documents yet. Upload a PDF to get started.'}</p> :
          <ul aria-label="Documents, newest first">{collection.documents.map(item => <li key={item.id}>
            <Metadata item={item} /><button id={'open-' + item.id} aria-label={'Open document ' + item.id} onClick={() => open(item.id, 'open-' + item.id)}>Open document</button>
          </li>)}</ul>}
      </>}
    </section>}
    <p role="status">{loading ? position.selected ? 'Loading document…' : 'Loading documents…' : ''}</p>
    {error && <div><p role="alert">{error}</p><button onClick={() => setRetry(value => value + 1)}>Retry documents</button></div>}
  </>;
}
