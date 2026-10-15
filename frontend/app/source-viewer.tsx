'use client';
import { useEffect, useRef, useState } from 'react';
import type { PDFDocumentLoadingTask, RenderTask } from 'pdfjs-dist';
import { useEvents, useInspectable, type EventHandle } from '@borwood/demoable-react';
import { eventLifetime } from './demo-events';
import { explanations } from './demo-context';
export type Evidence = { fieldId: string; entityId: string; relationshipId: string | null; fieldName: string; value: string; documentSha256: string; page: number; blockId: string; boundingBox: {left:number; top:number; width:number; height:number}; method: string; confidence: number; confidenceKind: string };
export default function SourceViewer({documentId, evidence, onExpired}: {documentId:string; evidence:Evidence; onExpired:()=>void}) {
  const events = useEvents();
  const context = useInspectable<HTMLElement>({label: 'Source and provenance', context: explanations.source});
  const canvas = useRef<HTMLCanvasElement>(null);
  const [state, setState] = useState('loading');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const fetchEvent = events.start({label: 'Fetch original source', state: 'running', content: 'Retrieving the retained PDF through the authenticated source endpoint.', lifetime: eventLifetime});
    let renderEvent: EventHandle | undefined;
    const controller = new AbortController();
    let live = true;
    let loading: PDFDocumentLoadingTask | undefined;
    let rendering: RenderTask | undefined;
    const target = canvas.current!;
    setState('loading');
    async function render() {
      try {
        const response = await fetch(`/api/documents/${documentId}/source`, {cache:'no-store', signal:controller.signal});
        if (!live) return;
        if (response.status === 401) { fetchEvent.fail({content: 'Session expired; source access was rejected.'}); onExpired(); return; }
        if (!response.ok) throw new Error('source');
        const bytes = new Uint8Array(await response.arrayBuffer());
        if (!live) return;
        fetchEvent.complete({content: 'Original PDF bytes received. Rendering is a separate operation.'});
        renderEvent = events.start({label: 'Render source page', state: 'running', content: 'PDF.js is rendering the cited page; the normalized field geometry supplies the highlight.', lifetime: eventLifetime});
        const pdfjs = await import('pdfjs-dist');
        if (!live) return;
        pdfjs.GlobalWorkerOptions.workerSrc = '/pdf.worker.min.mjs';
        loading = pdfjs.getDocument({data:bytes});
        const pdf = await loading.promise;
        const page = await pdf.getPage(evidence.page);
        if (!live) return;
        const viewport = page.getViewport({scale:1.5});
        target.width = viewport.width; target.height = viewport.height;
        rendering = page.render({canvas:target, viewport});
        await rendering.promise;
        if (live) { setState('ready'); renderEvent.complete({content: 'The original page rendered with the cited field highlight. Inspect provenance for identifiers and extraction confidence.'}); }
      } catch { if (live) { fetchEvent.fail({content: 'Original source unavailable. Retry creates a new attempt.'}); renderEvent?.fail({content: 'PDF rendering failed. Retry or download the original PDF.'}); setState('error'); } }
    }
    void render();
    return () => { live = false; controller.abort(); rendering?.cancel(); void loading?.destroy(); fetchEvent.cancel({content: 'Source retrieval abandoned; the request was aborted.'}); renderEvent?.cancel({content: 'Source rendering abandoned; the PDF task was cancelled.'}); target.width=0; target.height=0; };
  }, [documentId, evidence, attempt, onExpired, events]);
  const box = evidence.boundingBox;
  return <section ref={context.ref} aria-label="Source evidence" className="source-panel">
    <h4>Source evidence: {evidence.fieldName}</h4>
    <p aria-live="polite">{state === 'loading' ? 'Loading source page…' : state === 'ready' ? `Source page ${evidence.page} rendered. Highlight: ${evidence.fieldName}.` : ''}</p>
    {state === 'error' && <div role="alert">Source page unavailable. Retry or download the original PDF. <button onClick={()=>setAttempt(n=>n+1)}>Retry source</button></div>}
    {state === 'ready' && <p>Scroll inside the source to inspect the full page.</p>}
    <div className="source-viewport" tabIndex={0} role="region" aria-label="Original PDF page; scroll to inspect the full page" style={{display:state === 'ready' ? 'block' : 'none'}}>
    <div className="pdf-page" style={{display:state === 'ready' ? 'block' : 'none'}}>
      <canvas ref={canvas} data-testid="source-canvas" data-rendered={state === 'ready'} aria-label={`Original PDF page ${evidence.page}`} />
      {state === 'ready' && <span data-testid="source-highlight" className="source-highlight" style={{left:`${box.left*100}%`,top:`${box.top*100}%`,width:`${box.width*100}%`,height:`${box.height*100}%`}} />}
    </div>
    </div>
    <details className="provenance"><summary>Extraction &amp; provenance</summary>
    <dl data-testid="evidence-details" className="evidence-details">
      <dt>Field</dt><dd>{evidence.fieldName}: {evidence.value}</dd>
      <dt>Page / block</dt><dd>Page {evidence.page} · {evidence.blockId}</dd>
      <dt>Field ID</dt><dd>{evidence.fieldId}</dd><dt>Entity ID</dt><dd>{evidence.entityId}</dd>
      {evidence.relationshipId && <><dt>Relationship ID</dt><dd>{evidence.relationshipId}</dd></>}
      <dt>Document SHA-256</dt><dd>{evidence.documentSha256}</dd>
      <dt>Extraction method</dt><dd>{evidence.method}</dd>
      <dt>Confidence</dt><dd>{evidence.confidence} · {evidence.confidenceKind} (invented, not answer certainty)</dd>
      <dt>Normalized bounding box</dt><dd>Left {box.left}; top {box.top}; width {box.width}; height {box.height}</dd>
    </dl>
    </details>
    <p><a href={`/api/documents/${documentId}/source`}>Download original PDF</a></p>
  </section>;
}

