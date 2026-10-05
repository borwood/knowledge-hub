"""protected business boundary over real HTTP."""
import httpx
import io
import json
import hashlib
import uuid
import subprocess
from pathlib import Path
from pypdf import PdfWriter
from conftest import ROOT, wait_ready

SAMPLE = ROOT / 'fixtures/invoice/invoice.pdf'


def upload(client, data=None, filename='invoice.pdf', **kwargs):
    return client.post('/documents', files={'file': (filename, SAMPLE.read_bytes() if data is None else data, 'application/pdf')}, **kwargs)


def pdf(pages=1, encrypted=False):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(612, 792)
    if encrypted:
        writer.encrypt('secret')
    target = io.BytesIO()
    writer.write(target)
    return target.getvalue()


def test_business_routes_require_session(runtime):
    for path in ('/auth/me', '/documents', '/documents/absent',
                 '/documents/absent/source', '/documents/absent/provenance'):
        response = httpx.get('http://127.0.0.1:8000' + path)
        assert response.status_code == 401
        assert response.json()['error']['code'] == 'UNAUTHENTICATED'
        assert response.headers['cache-control'] == 'no-store'


def test_original_bytes_provenance_isolation_and_restart(users, runtime):
    alice, bob = users
    response = upload(alice, filename='../../display.pdf')
    assert response.status_code == 201, response.text
    document = response.json()
    assert document['state'] == 'ready'
    assert document['filename'] == 'display.pdf'
    assert document['sha256'] == hashlib.sha256(SAMPLE.read_bytes()).hexdigest()
    assert document['byte_length'] == SAMPLE.stat().st_size
    document_id = document['id']
    uuid.UUID(document_id)
    assert any(row['id'] == document_id for row in alice.get('/documents').json()['documents'])
    assert all(row['id'] != document_id for row in bob.get('/documents').json()['documents'])
    for suffix in ('', '/source', '/provenance'):
        denied = bob.get('/documents/' + document_id + suffix)
        absent = bob.get('/documents/absent' + suffix)
        assert denied.status_code == absent.status_code == 404
        assert denied.json() == absent.json()
    source = alice.get(f'/documents/{document_id}/source')
    assert source.content == SAMPLE.read_bytes()
    assert source.headers['cache-control'] == 'no-store'
    assert source.headers['content-disposition'] == 'attachment; filename="source.pdf"'
    result = alice.get(f'/documents/{document_id}/provenance').json()
    assert result['normalized'] == json.loads((SAMPLE.parent / 'normalized.json').read_text())
    assert result['raw'] == json.loads((SAMPLE.parent / 'textract-shaped.json').read_text())
    fields = {field['id']: field for field in result['fields']}
    assert len(fields) == 5
    assert {e['kind'] for e in result['entities']} == {'invoice', 'vendor'}
    for entity in result['entities']:
        assert entity['document_id'] == document_id
        for attribute in entity['attributes'].values():
            assert fields[attribute['field_id']]['document_id'] == document_id
    relation, = result['relationships']
    assert relation['kind'] == 'invoice-issued-by-vendor'
    assert fields[relation['field_ids'][0]]['name'] == 'vendor'
    assert next(f['value'] for f in fields.values() if f['name'] == 'total') == '125.00'
    repeated = upload(alice).json()
    bob_upload = upload(bob).json()
    assert len({document_id, repeated['id'], bob_upload['id']}) == 3
    runtime('up', '-d', '--force-recreate', 'api', 'storage')
    wait_ready()
    assert alice.get(f'/documents/{document_id}').json() == document
    assert alice.get(f'/documents/{document_id}/source').content == SAMPLE.read_bytes()
    assert alice.get(f'/documents/{document_id}/provenance').json() == result
    assert 'foreign keys valid' in runtime('exec', '-T', 'api', 'python', '-c',
        "from backend.database import database\nwith database() as db:\n assert not db.execute('PRAGMA foreign_key_check').fetchall()\nprint('foreign keys valid')")


def test_input_contract_unknown_and_csrf(users):
    alice, _ = users
    for data, filename, code, status in (
        (b'not pdf', 'bad.pdf', 'INVALID_PDF', 422),
        (SAMPLE.read_bytes(), 'bad.txt', 'UNSUPPORTED_TYPE', 415),
        (b'x' * (5 * 1024 * 1024 + 1), 'large.pdf', 'FILE_TOO_LARGE', 413),
        (pdf(11), 'pages.pdf', 'TOO_MANY_PAGES', 422),
        (pdf(1, True), 'encrypted.pdf', 'ENCRYPTED_PDF', 422),
        (pdf(0), 'empty.pdf', 'INVALID_PDF', 422),
    ):
        result = upload(alice, data, filename)
        assert result.status_code == status, result.text
        assert result.json()['error']['code'] == code
    assert upload(alice, headers={'X-CSRF-Token': 'bad'}).status_code == 403
    assert upload(alice, headers={'Origin': 'http://evil.invalid'}).status_code == 403
    result = upload(alice, pdf(10))
    assert result.status_code == 201, result.text
    document = result.json()
    assert document['state'] == 'failed' and document['error_code'] == 'UNKNOWN_FIXTURE_DOCUMENT'
    provenance = alice.get(f"/documents/{document['id']}/provenance").json()
    assert provenance['fields'] == provenance['entities'] == provenance['relationships'] == []
    assert provenance['normalized'] is None and provenance['raw'] is None
    assert alice.get(f"/documents/{document['id']}/source").content == pdf(10)
    # The same PDF parser accepts the exact maximum size; unknown hash is a terminal extraction failure.
    at_limit = pdf() + b' ' * (5 * 1024 * 1024 - len(pdf()))
    assert upload(alice, at_limit).json()['error_code'] == 'UNKNOWN_FIXTURE_DOCUMENT'
    boundary = 'bounded'
    prefix = f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="large.pdf"\r\nContent-Type: application/pdf\r\n\r\n'.encode()
    chunks = iter([prefix] + [b'x' * 65536] * 82 + [f'\r\n--{boundary}--\r\n'.encode()])
    result = alice.post('/documents', content=chunks, headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
    assert result.status_code == 413  # chunked body has no Content-Length


def test_storage_failure_and_interrupted_recovery(users, runtime):
    alice, _ = users
    existing = upload(alice).json()
    try:
        runtime('stop', 'storage')
        assert alice.get(f"/documents/{existing['id']}/source").status_code == 503
        result = upload(alice)
        assert result.status_code == 503
        failed = alice.get('/documents').json()['documents'][0]
        assert failed['state'] == 'failed' and failed['error_code'] == 'DEPENDENCY_UNAVAILABLE'
        assert alice.get(f"/documents/{failed['id']}/provenance").json()['fields'] == []
    finally:
        runtime('start', 'storage')
        wait_ready()
    document_id = str(uuid.uuid4())
    code = f"""from backend.database import database
from backend.documents import now,store,bucket
with database() as db:
 owner=db.execute("SELECT id FROM identities WHERE username='alice'").fetchone()[0]
 db.execute('INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?)',('{document_id}',owner,'interrupted.pdf','0'*64,7,'processing',None,'documents/{document_id}/source.pdf',now(),now()))
store().put_object(Bucket=bucket(),Key='documents/{document_id}/source.pdf',Body=b'partial')
"""
    runtime('exec', '-T', 'api', 'python', '-c', code)
    runtime('restart', 'api')
    wait_ready()
    recovered = alice.get('/documents/' + document_id).json()
    assert recovered['state'] == 'failed' and recovered['error_code'] == 'INTERRUPTED_INGESTION'
    assert alice.get(f'/documents/{document_id}/provenance').json()['fields'] == []
    assert alice.get(f'/documents/{document_id}/source').status_code == 503


def test_database_finalization_failure_rolls_back_and_compensates(users, runtime):
    alice, _ = users
    # A real SQLite failure at the ready transition occurs after all facts are inserted.
    runtime('exec', '-T', 'api', 'python', '-c', """from backend.database import database
with database() as db:
 db.execute("CREATE TRIGGER acceptance_fail_ready BEFORE UPDATE OF state ON documents WHEN NEW.state='ready' BEGIN SELECT RAISE(FAIL,'acceptance injected disk failure'); END")
""")
    try:
        response = upload(alice, filename='finalization-failure.pdf')
        assert response.status_code == 503
        document = alice.get('/documents').json()['documents'][0]
        assert document['state'] == 'failed' and document['error_code'] == 'DEPENDENCY_UNAVAILABLE'
        result = alice.get(f"/documents/{document['id']}/provenance").json()
        assert result['fields'] == result['entities'] == result['relationships'] == []
        assert result['raw'] is None
        code = f"""from backend.documents import store,bucket
from botocore.exceptions import ClientError
try:
 store().head_object(Bucket=bucket(),Key='documents/{document['id']}/source.pdf')
 raise AssertionError('Compensated source must be absent')
except ClientError as error:
 assert error.response['ResponseMetadata']['HTTPStatusCode']==404
print('source compensated')
"""
        assert 'source compensated' in runtime('exec', '-T', 'api', 'python', '-c', code)
    finally:
        runtime('exec', '-T', 'api', 'python', '-c', "from backend.database import database\nwith database() as db:\n db.execute('DROP TRIGGER IF EXISTS acceptance_fail_ready')")


def test_client_owner_is_not_authority_and_cross_document_fk(users, runtime):
    alice, bob = users
    response = alice.post('/documents', files={'file': ('invoice.pdf', SAMPLE.read_bytes(), 'application/pdf')}, data={'owner_id': 'bob'})
    assert response.status_code == 400
    alice_doc, bob_doc = upload(alice).json(), upload(bob).json()
    result = bob.get(f"/documents/{bob_doc['id']}/provenance").json()
    field_id = result['fields'][0]['id']
    alice_result = alice.get(f"/documents/{alice_doc['id']}/provenance").json()
    entity_id = alice_result['entities'][0]['id']
    code = f"""import sqlite3
from backend.database import database
try:
 with database() as db:
  db.execute('INSERT INTO entity_evidence VALUES (?,?,?,?)',('{alice_doc['id']}','{entity_id}','cross-owner','{field_id}'))
 raise AssertionError('Cross-document evidence must fail')
except sqlite3.IntegrityError:
 print('cross-document evidence denied')
"""
    assert 'cross-document evidence denied' in runtime('exec', '-T', 'api', 'python', '-c', code)


def test_public_health_and_logs_do_not_leak_input_or_credentials(users, runtime):
    alice, _ = users
    marker = 'private-source-' + uuid.uuid4().hex
    assert upload(alice, marker.encode(), marker + '.pdf').status_code == 422
    health = httpx.get('http://127.0.0.1:8000/health/ready').text
    assert marker not in health
    logs = runtime('logs', '--no-color', 'api', 'web')
    assert marker not in logs
    assert alice.cookies.get('hub_session') not in logs
    values = dict(line.split('=', 1) for line in (ROOT / '.env').read_text().splitlines() if '=' in line)
    assert all(value not in logs for key, value in values.items() if key in (
        'OIDC_CLIENT_SECRET', 'DEMO_ALICE_PASSWORD', 'DEMO_BOB_PASSWORD', 'AWS_SECRET_ACCESS_KEY'))


def test_database_unavailable_business_response_and_recovery(users):
    alice, _ = users
    code = """import os,sqlite3,time
db=sqlite3.connect(os.environ['SQLITE_PATH'])
try:
 db.execute('BEGIN EXCLUSIVE')
 print('locked',flush=True)
 time.sleep(5)
finally:
 db.rollback()
 db.close()
"""
    process = subprocess.Popen(['docker', 'compose', 'exec', '-T', 'api', 'python', '-c', code],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
    try:
        assert process.stdout.readline().strip() == 'locked'
        response = alice.get('/documents')
        assert response.status_code == 503
        assert response.json() == {'error': {'code': 'DEPENDENCY_UNAVAILABLE', 'message': 'Dependency unavailable'}}
    finally:
        process.communicate(timeout=15)
    assert process.returncode == 0
    assert alice.get('/documents').status_code == 200
