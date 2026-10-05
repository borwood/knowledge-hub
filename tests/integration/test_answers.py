"""API acceptance over real authentication and persisted records."""
from test_ingestion import upload

QUERY = '''query Answer($id: ID!, $question: InvoiceQuestion!) {
 invoiceAnswer(documentId: $id, question: $question) {
 documentId question text sourceKind evidence {
 fieldId entityId relationshipId fieldName value documentSha256 page blockId
 boundingBox { left top width height } method confidence confidenceKind
 } } }'''

def answer(client, document, question='INVOICE_TOTAL'):
    return client.post('/graphql', json={'query': QUERY, 'variables': {'id': document, 'question': question}})

def test_persisted_answers_and_owner_boundary(users):
    alice, bob = users
    doc = upload(alice).json()
    response = answer(alice, doc['id'])
    assert response.status_code == 200
    payload = response.json()
    assert not payload.get('errors'), payload
    result = payload['data']['invoiceAnswer']
    assert result['text'] == 'USD 125.00'
    assert [e['fieldName'] for e in result['evidence']] == ['total', 'currency']
    assert result['documentId'] == doc['id'] and result['sourceKind'] == 'synthetic'
    fields = {f['id']: f for f in alice.get(f"/documents/{doc['id']}/provenance").json()['fields']}
    for evidence in result['evidence']:
        field = fields[evidence['fieldId']]
        assert evidence['value'] == field['value']
        assert evidence['documentSha256'] == doc['sha256']
        assert evidence['blockId'] == field['evidence']['block_id']
    vendor = answer(alice, doc['id'], 'INVOICE_VENDOR').json()['data']['invoiceAnswer']
    assert vendor['text'] == 'Juniper Example Supplies'
    assert vendor['evidence'][0]['relationshipId']
    assert answer(bob, doc['id']).json() == answer(bob, 'absent').json()

def code(response, expected, status):
    assert response.status_code == status, response.text
    assert response.json()['data'] is None
    assert response.json()['errors'][0]['extensions']['code'] == expected
    assert response.headers['cache-control'] == 'no-store'


def test_query_errors_transports_and_csrf(users):
    import httpx
    from test_ingestion import pdf
    alice, _ = users
    doc = upload(alice).json()['id']
    with httpx.Client(base_url='http://127.0.0.1:8000') as anonymous:
        code(answer(anonymous, doc), 'UNAUTHENTICATED', 401)
    code(answer(alice, 'absent'), 'NOT_FOUND', 404)
    code(answer(alice, upload(alice, pdf()).json()['id']), 'DOCUMENT_NOT_READY', 409)
    code(answer(alice, doc, 'UNSUPPORTED'), 'GRAPHQL_VALIDATION_FAILED', 400)
    payload = {'query': QUERY, 'variables': {'id': doc, 'question': 'INVOICE_TOTAL'}}
    code(alice.post('/graphql', json=payload, headers={'X-CSRF-Token':'wrong'}), 'CSRF_REJECTED', 403)
    code(alice.post('/graphql', json=payload, headers={'Origin':'http://evil.invalid'}), 'CSRF_REJECTED', 403)
    code(alice.get('/graphql', params={'query': '{ invoiceAnswer(documentId:"'+doc+'",question:INVOICE_TOTAL){text}}'}), 'POST_REQUIRED', 405)
    for body, expected in [([payload], 'INVALID_REQUEST'), ({'query':'mutation { health { status } }'},'UNSUPPORTED_OPERATION'),
        ({'query':'subscription { health { status } }'},'UNSUPPORTED_OPERATION'),
        ({'query':'{ a:health{status} b:health{status} }'}, 'QUERY_LIMIT_EXCEEDED'),
        ({'query':'{ ... on Query { a:health{status} b:health{status} } }'}, 'QUERY_LIMIT_EXCEEDED'),
        ({'query':'{health{status}} fragment X on Query {health{status}}'}, 'QUERY_LIMIT_EXCEEDED'),
        ({'query':'{ health { status } }'+' '*17000}, 'REQUEST_TOO_LARGE'),
        ({'query':'{'+'health{'*8+'status'+'}'*9}, 'QUERY_LIMIT_EXCEEDED')]:
        code(alice.post('/graphql', json=body), expected, 413 if expected=='REQUEST_TOO_LARGE' else 400)
    code(alice.post('/graphql', content='query=bad'), 'UNSUPPORTED_MEDIA_TYPE', 415)
    assert alice.get('/graphql', params={'query':'{ health { status } }'}).json()['data']['health']['status']=='ready'


def test_missing_inconsistent_and_changed_persisted_evidence(users, runtime):
    import json
    alice, _ = users
    doc = upload(alice).json()['id']
    # Persisted value modification proves answers do not use sample constants.
    runtime('exec','-T','api','python','-c',f'''import json
from backend.database import database
with database() as db:
 row=db.execute("SELECT * FROM fields WHERE document_id=? AND name='total'",('{doc}',)).fetchone()
 value=json.loads(row['payload']); value['value']='900.01'
 db.execute('UPDATE fields SET payload=? WHERE id=?',(json.dumps(value),row['id']))
''')
    code(answer(alice, doc), 'MISSING_EVIDENCE', 422)
    # Coherently changed persisted records, rather than fixture constants, drive the answer.
    runtime('exec','-T','api','python','-c',f'''import json
from backend.database import database
with database() as db:
 row=db.execute('SELECT raw,normalized FROM extractions WHERE document_id=?',('{doc}',)).fetchone()
 raw=json.loads(row['raw']);normalized=json.loads(row['normalized'])
 next(b for b in raw['Blocks'] if b['Id']=='line-5')['Text']='Total: 900.01'
 next(f for f in normalized['fields'] if f['name']=='total')['value']='900.01'
 db.execute('UPDATE extractions SET raw=?,normalized=? WHERE document_id=?',(json.dumps(raw),json.dumps(normalized),'{doc}'))
''')
    assert answer(alice, doc).json()['data']['invoiceAnswer']['text']=='USD 900.01'
    runtime('exec','-T','api','python','-c',f'''from backend.database import database
with database() as db:
 db.execute('DELETE FROM relationship_evidence WHERE document_id=?',('{doc}',))
''')
    code(answer(alice, doc, 'INVOICE_VENDOR'), 'MISSING_EVIDENCE', 422)
    runtime('exec','-T','api','python','-c',f'''import json
from backend.database import database
with database() as db:
 row=db.execute("SELECT * FROM fields WHERE document_id=? AND name='currency'",('{doc}',)).fetchone()
 value=json.loads(row['payload']);value['document_sha256']='0'*64
 db.execute('UPDATE fields SET payload=? WHERE id=?',(json.dumps(value),row['id']))
''')
    code(answer(alice, doc), 'MISSING_EVIDENCE', 422)
    runtime('exec','-T','api','python','-c',f'''from backend.database import database
with database() as db:
 db.execute("UPDATE documents SET state='processing' WHERE id=?",('{doc}',))
''')
    code(answer(alice, doc), 'DOCUMENT_NOT_READY', 409)
    runtime('exec','-T','api','python','-c',f'''from backend.database import database
with database() as db:
 db.execute("UPDATE documents SET state='failed',error_code='ACCEPTANCE_PROBE' WHERE id=?",('{doc}',))
''')


def test_query_persistence_revocation_and_dependency_errors(users, runtime):
    from backend.auth import digest
    from conftest import wait_ready
    import subprocess
    alice, bob = users
    doc = upload(alice).json()['id']
    initial=answer(alice,doc).json()
    runtime('restart','api');wait_ready()
    assert answer(alice,doc).json()==initial
    script="""import os,sqlite3,time
connection=sqlite3.connect(os.environ['SQLITE_PATH'])
connection.execute('BEGIN EXCLUSIVE');print('locked',flush=True);time.sleep(5);connection.rollback()
"""
    process=subprocess.Popen(['docker','compose','exec','-T','api','python','-c',script],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        assert process.stdout.readline().strip()=='locked'
        code(answer(alice,doc), 'DEPENDENCY_UNAVAILABLE',503)
    finally: process.communicate(timeout=15)
    for client, sql in [(alice,'UPDATE sessions SET expires_at=0 WHERE id_hash=?'),(bob,'DELETE FROM sessions WHERE id_hash=?')]:
        token=digest(client.cookies.get('hub_session'))
        runtime('exec','-T','api','python','-c',f"from backend.database import database\nwith database() as db:\n db.execute({sql!r},('{token}',))")
        code(answer(client,doc),'UNAUTHENTICATED',401)
