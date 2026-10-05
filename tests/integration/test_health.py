"""HTTP contract, executed against a real ASGI server."""
import os
import socket
import subprocess
import sys
import time

import httpx


def test_missing_dependencies_are_reported_without_breaking_liveness(tmp_path):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = {**os.environ, 'SQLITE_PATH': str(tmp_path / 'missing' / 'hub.db'),
           'S3_ENDPOINT': 'http://127.0.0.1:1', 'AWS_ACCESS_KEY_ID': 'test-user',
           'AWS_SECRET_ACCESS_KEY': 'not-for-output'}
    process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.app:app',
                                '--host', '127.0.0.1', '--port', str(port)], env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=8) as client:
            for _ in range(100):
                try:
                    if client.get('/health/live').status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(.1)
            else:
                raise AssertionError('API did not start')
            response = client.get('/health/ready')
            assert response.status_code == 503
            assert response.json() == {'status': 'unavailable', 'dependencies':
                                       {'sqlite': 'unavailable', 'object_store': 'unavailable'}}
            assert client.get('/health/live').json() == {'status': 'alive'}
            (tmp_path / 'missing').mkdir()
            recovered = client.get('/health/ready')
            assert recovered.status_code == 503
            assert recovered.json()['dependencies'] == {'sqlite': 'ready', 'object_store': 'unavailable'}
            assert client.get('/auth/me').status_code == 401
    finally:
        process.terminate()
        output = process.communicate(timeout=10)[0].decode(errors='replace')
    assert 'dependency_unavailable' in output
    assert 'not-for-output' not in output
