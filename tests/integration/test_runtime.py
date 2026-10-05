"""real Compose services and persistent volumes."""
import json
import subprocess
import httpx

from conftest import wait_ready


def test_sqlite_lock_reports_failure_and_recovers(runtime):
    code = """import os,sqlite3,time
db=sqlite3.connect(os.environ['SQLITE_PATH'],timeout=1)
try:
 db.execute('BEGIN EXCLUSIVE')
 print('locked',flush=True)
 time.sleep(6)
finally:
 db.rollback()
 db.close()
"""
    process = subprocess.Popen(['docker', 'compose', 'exec', '-T', 'api', 'python', '-c', code],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == 'locked'
        response = httpx.get('http://127.0.0.1:8000/health/ready', timeout=8)
        assert response.status_code == 503
        assert response.json()['dependencies'] == {'sqlite': 'unavailable', 'object_store': 'ready'}
        assert httpx.get('http://127.0.0.1:8000/health/live').status_code == 200
    finally:
        process.communicate(timeout=15)
    assert process.returncode == 0
    wait_ready()


def test_http_graphql_and_loopback_configuration(runtime):
    config = json.loads(runtime('config', '--format', 'json'))
    for service in config['services'].values():
        for port in service.get('ports', []):
            assert port['host_ip'] == '127.0.0.1'
    for service in ('api', 'storage'):
        assert config['services'][service]['volumes'][0]['type'] == 'volume'
    assert httpx.get('http://127.0.0.1:8000/health/live').json() == {'status': 'alive'}
    response = httpx.post('http://127.0.0.1:8000/graphql', json={'query': '{ health { status sqlite objectStore } }'})
    assert response.json() == {'data': {'health': {'status': 'ready', 'sqlite': 'ready', 'objectStore': 'ready'}}}
    assert httpx.get('http://127.0.0.1:3000/api/health').json()['status'] == 'ready'
    assert httpx.get('http://127.0.0.1:8333/knowledge-hub').status_code in (401, 403)


def test_data_survives_container_recreation(runtime):
    # Create harmless test-only records through real SQLite and signed local S3.
    write = """import os,sqlite3
from backend.app import storage_client
with sqlite3.connect(os.environ['SQLITE_PATH']) as db:
 db.execute('CREATE TABLE IF NOT EXISTS acceptance_probe (id INTEGER PRIMARY KEY, value TEXT)')
 db.execute("INSERT OR REPLACE INTO acceptance_probe VALUES (1, 'persistent')")
storage_client().put_object(Bucket='knowledge-hub',Key='acceptance/persistence.txt',Body=b'persistent')
"""
    runtime('exec', '-T', 'api', 'python', '-c', write)
    runtime('up', '-d', '--force-recreate', 'storage', 'api')
    wait_ready()
    read = """import os,sqlite3
from backend.app import storage_client
with sqlite3.connect(os.environ['SQLITE_PATH']) as db:
 assert db.execute('SELECT value FROM acceptance_probe WHERE id=1').fetchone() == ('persistent',)
 db.execute('DELETE FROM acceptance_probe WHERE id=1')
client=storage_client()
assert client.get_object(Bucket='knowledge-hub',Key='acceptance/persistence.txt')['Body'].read()==b'persistent'
client.delete_object(Bucket='knowledge-hub',Key='acceptance/persistence.txt')
print('SQLite and S3 data survived container recreation')
"""
    assert 'survived' in runtime('exec', '-T', 'api', 'python', '-c', read)
