"""OIDC confidential BFF. Tokens never enter browser storage or application logs."""
import hashlib
import os
import secrets
import time
from urllib.parse import urlencode
from uuid import uuid4

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.jose import JsonWebToken
from authlib.oidc.core import CodeIDToken
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from backend.database import database

router = APIRouter()
CLIENT = 'knowledge-hub'
COOKIE = 'hub_session'
TRANSACTION = 'hub_login'


class BusinessError(Exception):
    def __init__(self, code, status=400):
        self.code, self.status = code, status


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def origin():
    return os.environ['WEB_ORIGIN']


def issuer():
    return os.environ['OIDC_ISSUER']


def endpoint(name, internal=False):
    root = os.environ['OIDC_BACKCHANNEL'] if internal else issuer()
    return root + '/protocol/openid-connect/' + name


def authenticate(request):
    with database() as db:
        row = db.execute('''SELECT sessions.*, identities.username FROM sessions
          JOIN identities ON identities.id=sessions.owner_id
          WHERE id_hash=? AND expires_at>?''',
          (digest(request.cookies.get(COOKIE, '')), time.time())).fetchone()
    if row is None:
        raise BusinessError('UNAUTHENTICATED', 401)
    return dict(row)


def unsafe(request, session):
    if request.headers.get('origin') != origin() or not secrets.compare_digest(
            request.headers.get('x-csrf-token', ''), session['csrf']):
        raise BusinessError('CSRF_REJECTED', 403)


@router.get('/auth/login')
async def login(request: Request):
    if any(k != 'return_to' for k in request.query_params) or request.query_params.get('return_to', '/') != '/':
        raise BusinessError('UNSAFE_RETURN_URL')
    transaction, state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(4))
    with database() as db:
        db.execute('DELETE FROM login_transactions WHERE expires_at<=?', (time.time(),))
        db.execute('INSERT INTO login_transactions VALUES (?,?,?,?,?)',
                   (digest(transaction), state, nonce, verifier, time.time() + 300))
    async with AsyncOAuth2Client(CLIENT, scope='openid profile',
            redirect_uri=origin() + '/api/auth/callback', code_challenge_method='S256') as client:
        url, _ = client.create_authorization_url(endpoint('auth'), state=state,
                                                  nonce=nonce, code_verifier=verifier)
    response = RedirectResponse(url, status_code=302)
    response.set_cookie(TRANSACTION, transaction, max_age=300, httponly=True, samesite='lax')
    return response


@router.get('/auth/callback')
async def callback(request: Request):
    with database() as db:
        tx = db.execute('DELETE FROM login_transactions WHERE id_hash=? RETURNING *',
                        (digest(request.cookies.get(TRANSACTION, '')),)).fetchone()
    state = request.query_params.get('state', '')
    if (tx is None or tx['expires_at'] <= time.time() or not secrets.compare_digest(tx['state'], state)
            or not request.query_params.get('code') or request.query_params.get('error')
            or request.query_params.get('iss', issuer()) != issuer()):
        raise BusinessError('LOGIN_FAILED', 401)
    try:
        async with AsyncOAuth2Client(CLIENT, os.environ['OIDC_CLIENT_SECRET'],
                redirect_uri=origin() + '/api/auth/callback', timeout=8) as client:
            token = await client.fetch_token(endpoint('token', True),
                code=request.query_params['code'], code_verifier=tx['verifier'], grant_type='authorization_code')
        async with httpx.AsyncClient(timeout=8) as client:
            keys_response = await client.get(endpoint('certs', True))
            keys_response.raise_for_status()
        claims = JsonWebToken(['RS256']).decode(token['id_token'], keys_response.json(),
            claims_cls=CodeIDToken,
            claims_options={'iss': {'essential': True, 'value': issuer()},
                            'aud': {'essential': True, 'value': CLIENT},
                            'exp': {'essential': True}, 'sub': {'essential': True}},
            claims_params={'nonce': tx['nonce'], 'client_id': CLIENT, 'access_token': token['access_token']})
        claims.validate(leeway=0)
        expires = min(time.time() + 28800, claims['exp'], time.time() + int(token['expires_in']))
        if expires <= time.time():
            raise ValueError('Expired identity')
    except Exception:
        raise BusinessError('LOGIN_FAILED', 401) from None
    session, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with database() as db:
        db.execute('''INSERT INTO identities VALUES (?,?,?,?) ON CONFLICT(issuer,subject)
                      DO UPDATE SET username=excluded.username''',
                   (str(uuid4()), issuer(), claims['sub'], claims.get('preferred_username', 'Demo user')))
        owner = db.execute('SELECT id FROM identities WHERE issuer=? AND subject=?',
                           (issuer(), claims['sub'])).fetchone()[0]
        db.execute('DELETE FROM sessions WHERE expires_at<=? OR id_hash=?',
                   (time.time(), digest(request.cookies.get(COOKIE, ''))))
        db.execute('INSERT INTO sessions VALUES (?,?,?,?)', (digest(session), owner, csrf, expires))
    response = RedirectResponse(origin() + '/', status_code=303)
    response.delete_cookie(TRANSACTION)
    response.set_cookie(COOKIE, session, max_age=max(1, int(expires-time.time())), httponly=True, samesite='lax')
    return response


@router.get('/auth/me')
def me(request: Request):
    session = authenticate(request)
    return {'username': session['username'], 'csrf_token': session['csrf'], 'expires_at': session['expires_at']}


@router.post('/auth/logout')
def logout(request: Request):
    session = authenticate(request)
    unsafe(request, session)
    with database() as db:
        db.execute('DELETE FROM sessions WHERE id_hash=?', (session['id_hash'],))
    # client_id + registered fixed return URL avoids placing an ID token in a URL/log.
    url = endpoint('logout') + '?' + urlencode({'client_id': CLIENT, 'post_logout_redirect_uri': origin() + '/'})
    response = JSONResponse({'logout_url': url})
    response.delete_cookie(COOKIE)
    return response
