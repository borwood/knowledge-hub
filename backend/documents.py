"""Owner-scoped ingestion, durable source storage and traceable fixture records."""
from datetime import datetime, timezone
import hashlib
import io
import json
import os
import re
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.datastructures import UploadFile

from backend.auth import BusinessError, authenticate, unsafe
from backend.database import database
from backend.fixture import MAX_BYTES, FixtureError, adapt_bytes, artifacts, validate_pdf

router = APIRouter()
MAX_REQUEST = MAX_BYTES + 64 * 1024


def now():
    return datetime.now(timezone.utc).isoformat()


def store():
    from backend.app import storage_client
    return storage_client()


def bucket():
    return os.environ.get('S3_BUCKET', 'knowledge-hub')


def public(row):
    return {k: row[k] for k in ('id', 'filename', 'sha256', 'byte_length', 'state',
                                'error_code', 'created_at', 'updated_at')}


def owned(db, document_id, owner):
    row = db.execute('SELECT * FROM documents WHERE id=? AND owner_id=?', (document_id, owner)).fetchone()
    if row is None:
        raise BusinessError('NOT_FOUND', 404)
    return row


def cleanup(key):
    try:
        store().delete_object(Bucket=bucket(), Key=key)
    except Exception:
        # No document data/identifiers/SDK exception text in logs. See scoped recovery guide.
        pass


def recover_processing():
    # Called once before accepting traffic; a single API worker owns ingestion.
    with database() as db:
        rows = db.execute("SELECT id,object_key FROM documents WHERE state='processing'").fetchall()
        for row in rows:
            cleanup(row['object_key'])
            db.execute("UPDATE documents SET state='failed',error_code='INTERRUPTED_INGESTION',updated_at=? WHERE id=?",
                       (now(), row['id']))


def persist_facts(db, document_id, normalized):
    raw = json.loads(artifacts()['textract-shaped.json'])
    db.execute('INSERT INTO extractions VALUES (?,?,?)', (document_id, json.dumps(normalized), json.dumps(raw)))
    fields = {}
    for field in normalized['fields']:
        field_id = str(uuid4())
        fields[field['name']] = field_id
        db.execute('INSERT INTO fields VALUES (?,?,?,?)', (field_id, document_id, field['name'], json.dumps(field)))
    invoice, vendor, relationship = (str(uuid4()) for _ in range(3))
    db.executemany('INSERT INTO entities VALUES (?,?,?)',
                   [(invoice, document_id, 'invoice'), (vendor, document_id, 'vendor')])
    for attribute in ('invoice_number', 'date', 'currency', 'total'):
        db.execute('INSERT INTO entity_evidence VALUES (?,?,?,?)', (document_id, invoice, attribute, fields[attribute]))
    db.execute('INSERT INTO entity_evidence VALUES (?,?,?,?)', (document_id, vendor, 'name', fields['vendor']))
    db.execute('INSERT INTO relationships VALUES (?,?,?,?,?)', (relationship, document_id, 'invoice-issued-by-vendor', invoice, vendor))
    db.execute('INSERT INTO relationship_evidence VALUES (?,?,?)', (document_id, relationship, fields['vendor']))


@router.post('/documents')
async def upload(request: Request):
    session = authenticate(request)
    unsafe(request, session)
    # Bound total stream independently of Content-Length, before invoking multipart/PDF parsers.
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_REQUEST:
            raise BusinessError('FILE_TOO_LARGE', 413)
        data.extend(chunk)
    request._body = bytes(data)
    try:
        async with request.form(max_files=1, max_fields=0, max_part_size=MAX_REQUEST) as form:
            file = form.get('file')
            if len(form) != 1 or not isinstance(file, UploadFile):
                raise BusinessError('INVALID_MULTIPART')
            filename = file.filename or ''
            if not filename.lower().endswith('.pdf') or file.content_type != 'application/pdf':
                raise BusinessError('UNSUPPORTED_TYPE', 415)
            content = await file.read(MAX_BYTES + 1)
    except BusinessError:
        raise
    except Exception:
        raise BusinessError('INVALID_MULTIPART') from None
    try:
        validate_pdf(content)
    except FixtureError as error:
        raise BusinessError(error.code, 413 if error.code == 'FILE_TOO_LARGE' else 422) from None
    # Display-only filename. It is never used to select any path or object key.
    filename = ''.join(c for c in filename.replace('\\', '/').rsplit('/', 1)[-1] if c.isprintable())[:180] or 'document.pdf'
    document_id, timestamp = str(uuid4()), now()
    key = f'documents/{document_id}/source.pdf'
    with database() as db:
        db.execute('INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?)',
                   (document_id, session['owner_id'], filename, hashlib.sha256(content).hexdigest(),
                    len(content), 'processing', None, key, timestamp, timestamp))
    try:
        store().put_object(Bucket=bucket(), Key=key, Body=content, ContentType='application/pdf')
        try:
            normalized = adapt_bytes(content)
            state, error_code = 'ready', None
        except FixtureError as error:
            if error.code != 'UNKNOWN_FIXTURE_DOCUMENT':
                raise
            normalized, state, error_code = None, 'failed', error.code
        with database() as db:
            if normalized:
                persist_facts(db, document_id, normalized)
            db.execute('UPDATE documents SET state=?,error_code=?,updated_at=? WHERE id=?',
                       (state, error_code, now(), document_id))
    except Exception:
        cleanup(key)
        try:
            with database() as db:
                db.execute("UPDATE documents SET state='failed',error_code='DEPENDENCY_UNAVAILABLE',updated_at=? WHERE id=?",
                           (now(), document_id))
        except Exception:
            pass  # Startup reconciliation handles a row left in processing.
        raise BusinessError('DEPENDENCY_UNAVAILABLE', 503) from None
    with database() as db:
        return JSONResponse(public(owned(db, document_id, session['owner_id'])), status_code=201)


@router.get('/documents')
def documents(request: Request):
    session = authenticate(request)
    params = request.query_params
    paged = any(key in params for key in ('page', 'page_size', 'q', 'state'))
    if paged:
        try:
            page_text, size_text = params.get('page', '1'), params.get('page_size', '10')
            if not re.fullmatch(r'[0-9]+', page_text) or not re.fullmatch(r'[0-9]+', size_text):
                raise ValueError()
            page, size = int(page_text), int(size_text)
            query, state = params.get('q', '').strip(), params.get('state', '')
            if page < 1 or not 1 <= size <= 50 or len(query) > 200 or state not in ('', 'ready', 'processing', 'failed'):
                raise ValueError()
        except ValueError:
            raise BusinessError('INVALID_COLLECTION_QUERY', 422) from None
    with database() as db:
        predicate, values = 'owner_id=?', [session['owner_id']]
        if not paged:
            return {'documents': [public(row) for row in db.execute(
                'SELECT * FROM documents WHERE owner_id=? ORDER BY created_at DESC,id DESC', values)]}
        if query:
            literal = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            predicate += " AND (filename LIKE ? ESCAPE '\\' OR id LIKE ? ESCAPE '\\')"
            values.extend((literal, literal))
        if state:
            predicate += ' AND state=?'
            values.append(state)
        # One read snapshot makes the count and rows consistent even during concurrent uploads.
        db.execute('BEGIN')
        total = db.execute('SELECT COUNT(*) FROM documents WHERE ' + predicate, values).fetchone()[0]
        total_pages = (total + size - 1) // size
        page = min(page, max(1, total_pages))
        rows = db.execute('SELECT * FROM documents WHERE ' + predicate +
                          ' ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?', values + [size, (page-1)*size])
        return {'documents': [public(row) for row in rows], 'total': total,
                'page': page, 'page_size': size, 'total_pages': total_pages}


@router.get('/documents/{document_id}')
def detail(document_id: str, request: Request):
    session = authenticate(request)
    with database() as db:
        return public(owned(db, document_id, session['owner_id']))


@router.get('/documents/{document_id}/source')
def source(document_id: str, request: Request):
    session = authenticate(request)
    with database() as db:
        row = owned(db, document_id, session['owner_id'])
    if row['state'] == 'processing' or row['error_code'] in ('INTERRUPTED_INGESTION', 'DEPENDENCY_UNAVAILABLE'):
        raise BusinessError('SOURCE_UNAVAILABLE', 503)
    try:
        result = store().get_object(Bucket=bucket(), Key=row['object_key'])
        # Bounded read before response headers allows truthful 503 on truncated/outage reads.
        body = result['Body']
        try:
            data = body.read(MAX_BYTES + 1)
        finally:
            body.close()
        if len(data) != row['byte_length'] or hashlib.sha256(data).hexdigest() != row['sha256']:
            raise ValueError('Source integrity failure')
    except Exception:
        raise BusinessError('DEPENDENCY_UNAVAILABLE', 503) from None
    return StreamingResponse(io.BytesIO(data), media_type='application/pdf',
                             headers={'Content-Disposition': 'attachment; filename="source.pdf"',
                                      'Content-Length': str(len(data))})


@router.get('/documents/{document_id}/provenance')
def provenance(document_id: str, request: Request):
    session = authenticate(request)
    with database() as db:
        row = owned(db, document_id, session['owner_id'])
        extraction = db.execute('SELECT * FROM extractions WHERE document_id=?', (document_id,)).fetchone()
        fields = [{'id': field['id'], 'document_id': document_id, **json.loads(field['payload'])}
                  for field in db.execute('SELECT * FROM fields WHERE document_id=?', (document_id,))]
        entities = []
        for entity in db.execute('SELECT * FROM entities WHERE document_id=?', (document_id,)):
            attributes = {r['attribute']: {'field_id': r['field_id']} for r in db.execute(
                'SELECT * FROM entity_evidence WHERE document_id=? AND entity_id=?', (document_id, entity['id']))}
            entities.append({**dict(entity), 'attributes': attributes})
        relationships = []
        for relationship in db.execute('SELECT * FROM relationships WHERE document_id=?', (document_id,)):
            evidence = [r['field_id'] for r in db.execute(
                'SELECT field_id FROM relationship_evidence WHERE document_id=? AND relationship_id=?',
                (document_id, relationship['id']))]
            relationships.append({**dict(relationship), 'field_ids': evidence})
        return {'document': public(row), 'normalized': json.loads(extraction['normalized']) if extraction else None,
                'raw': json.loads(extraction['raw']) if extraction else None,
                'fields': fields, 'entities': entities, 'relationships': relationships}
