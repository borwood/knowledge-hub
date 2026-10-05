'use client';
import { useEffect, useRef, useState } from 'react';
import SourceViewer, {type Evidence} from './source-viewer';
type Answer = {documentId:string; question:string; text:string; sourceKind:string; evidence:Evidence[]};
type Document = {id:string; filename:string; state:string};
const query = `query Answer($id: ID!, $question: InvoiceQuestion!) { invoiceAnswer(documentId:$id, question:$question) { documentId question text sourceKind evidence { fieldId entityId relationshipId fieldName value documentSha256 page blockId boundingBox { left top width height } method confidence confidenceKind } } }`;
export default function Questions({document,csrf,onExpired}:{document:Document;csrf:string;onExpired:()=>void}) {
  const selected=document.id;
  const [question,setQuestion]=useState('INVOICE_TOTAL');
  const [answer,setAnswer]=useState<Answer|null>(null);
  const [evidence,setEvidence]=useState<Evidence|null>(null);
  const [pending,setPending]=useState(false);
  const [error,setError]=useState('');
  const generation=useRef(0);
  const abort=useRef<AbortController|null>(null);
  const busy=useRef(false);
  function clear() { generation.current++; abort.current?.abort(); busy.current=false;setPending(false);setAnswer(null);setEvidence(null);setError(''); }
  useEffect(()=>()=>{generation.current++;abort.current?.abort();},[]);
  async function ask(event:React.FormEvent) {
    event.preventDefault(); if(!selected || busy.current) return;
    clear();busy.current=true;setPending(true);
    const current=generation.current;
    const controller=new AbortController();abort.current=controller;
    try {
      const response=await fetch('/api/graphql',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({query,variables:{id:selected,question}}),signal:controller.signal,cache:'no-store'});
      if(current!==generation.current)return;
      if(response.status===401){onExpired();return;}
      const result=await response.json();
      if(current!==generation.current)return;
      if(!response.ok || result.errors) throw new Error(result.errors?.[0]?.extensions?.code || result.error?.code || 'QUERY_UNAVAILABLE');
      setAnswer(result.data.invoiceAnswer);
    } catch(error){if(current===generation.current)setError(`${error instanceof Error ? error.message : 'QUERY_UNAVAILABLE'}: Unable to answer. Try again or select another ready invoice.`);}
    finally{if(current===generation.current){busy.current=false;setPending(false);}}
  }
  return <section aria-label="Invoice questions" className="question-workspace"><div className="question-panel"><h3>Invoice questions</h3>
    {document.state!=='ready'?<p>Questions require a ready document.</p>:<form onSubmit={ask}>
      <label htmlFor="question">Question</label><select id="question" value={question} onChange={e=>{clear();setQuestion(e.target.value);}}><option value="INVOICE_TOTAL">What is the invoice total and currency?</option><option value="INVOICE_VENDOR">Who issued this invoice?</option></select>
      <button className="primary" disabled={!selected||pending} type="submit">{pending?'Asking…':'Ask question'}</button>
    </form>}
    <p aria-live="polite">{pending?'Finding supporting invoice facts…':''}</p>
    {error&&<p role="alert">{error}</p>}
    {answer&&<div className="answer-card"><p className="eyebrow">ANSWER</p><p data-testid="answer-text">{answer.text}</p><p className="muted">Synthetic source. Confidence values are invented and not calibrated; they are not answer certainty.</p>
      <div aria-label="Answer citations">{answer.evidence.map(item=><button key={item.fieldId} onClick={()=>setEvidence(item)}>View {item.fieldName} evidence</button>)}</div>
      </div>}</div>
      {evidence?<SourceViewer key={evidence.fieldId} documentId={answer!.documentId} evidence={evidence} onExpired={onExpired}/>:<div className="source-empty"><span className="eyebrow">SOURCE EVIDENCE</span><h4>See where the answer comes from.</h4><p>Ask a question, then select an evidence link to inspect the original page and its highlighted source.</p></div>}
  </section>;
}
