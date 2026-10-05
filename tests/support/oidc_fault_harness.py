"""Integration fault-provider: real HTTP BFF + SQLite + signed JOSE responses.

Runs inside the built API container with isolated temporary database and loopback
ports. Complements real Keycloak tests with impossible-to-request bad ID tokens.
No production test bypass, monkeypatch or unit-level invocation is used.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import httpx
from authlib.jose import JsonWebKey, JsonWebToken

key = JsonWebKey.generate_key('RSA', 2048, is_private=True)
other_key = JsonWebKey.generate_key('RSA', 2048, is_private=True)
issuer = 'http://127.0.0.1:9081/realms/fault-provider'
mode, nonce = 'valid', ''


class Provider(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_json({'keys': [key.as_dict(is_private=False)]})

    def do_POST(self):
        self.rfile.read(int(self.headers.get('content-length', 0)))
        claims = {'iss': issuer, 'sub': 'fault-user', 'aud': 'knowledge-hub',
                  'iat': int(time.time()), 'exp': int(time.time()) + 300, 'nonce': nonce}
        if mode == 'issuer':
            claims['iss'] = 'http://evil.invalid'
        if mode == 'audience':
            claims['aud'] = 'other-client'
        if mode == 'expired':
            claims['exp'] = int(time.time()) - 1
        if mode == 'nonce':
            claims['nonce'] = 'incorrect'
        if mode == 'missing-exp':
            del claims['exp']
        token = JsonWebToken(['RS256']).encode({'alg': 'RS256'}, claims,
                                              other_key if mode == 'signature' else key).decode()
        self.send_json({'access_token': 'opaque-provider-token', 'token_type': 'Bearer',
                        'expires_in': 300, 'id_token': token})

    def send_json(self, value):
        body = json.dumps(value).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


server = ThreadingHTTPServer(('127.0.0.1', 9081), Provider)
threading.Thread(target=server.serve_forever, daemon=True).start()
with tempfile.TemporaryDirectory() as temporary:
    environment = {**os.environ, 'SQLITE_PATH': str(Path(temporary) / 'fault.db'),
                   'OIDC_ISSUER': issuer, 'OIDC_BACKCHANNEL': issuer}
    process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.app:app', '--host', '127.0.0.1',
                                '--port', '9082', '--no-access-log'], env=environment,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                if httpx.get('http://127.0.0.1:9082/health/live').status_code == 200:
                    break
            except httpx.TransportError:
                time.sleep(0.1)
        for mode in ('valid', 'issuer', 'audience', 'expired', 'nonce', 'missing-exp', 'signature'):
            with httpx.Client(base_url='http://127.0.0.1:9082') as client:
                response = client.get('/auth/login')
                parameters = parse_qs(urlparse(response.headers['location']).query)
                nonce = parameters['nonce'][0]
                response = client.get('/auth/callback', params={'state': parameters['state'][0], 'code': 'fault-code'})
                assert response.status_code == (303 if mode == 'valid' else 401), (mode, response.status_code)
                assert client.get('/auth/me').status_code == (200 if mode == 'valid' else 401)
        print('HTTP OIDC signed-token control and six adversarial token cases passed')
    finally:
        process.terminate()
        process.wait(timeout=10)
        server.shutdown()
