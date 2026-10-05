"""real provider lifecycle and adversarial HTTP/browser responses."""
import hashlib
import httpx
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import sync_playwright, expect
from conftest import demo_password
from conftest import ROOT

WEB = 'http://127.0.0.1:3000'


def test_session_csrf_revocation_and_expiry(users, runtime):
    alice, bob = users
    identity = alice.get('/auth/me')
    assert 'token' not in identity.json() and 'subject' not in identity.json()
    cookie = alice.cookies.get('hub_session')
    assert len(cookie) > 40 and '.' not in cookie
    assert alice.post('/auth/logout', headers={'Origin': 'http://evil.invalid'}).status_code == 403
    assert alice.get('/auth/me').status_code == 200
    response = alice.post('/auth/logout')
    assert response.status_code == 200
    assert response.json()['logout_url'].startswith('http://127.0.0.1:8080/realms/hub/protocol/openid-connect/logout?')
    assert 'id_token' not in response.json()['logout_url']
    assert httpx.get('http://127.0.0.1:8000/documents', cookies={'hub_session': cookie}).status_code == 401
    digest = hashlib.sha256(bob.cookies.get('hub_session').encode()).hexdigest()
    runtime('exec', '-T', 'api', 'python', '-c',
        f"from backend.database import database\nwith database() as db:\n db.execute('UPDATE sessions SET expires_at=0 WHERE id_hash=?',('{digest}',))")
    assert bob.get('/auth/me').status_code == 401
    assert bob.get('/documents').status_code == 401


def test_oidc_state_nonce_expiry_and_replay(runtime):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for mode in ('wrong-state', 'nonce', 'expired', 'valid'):
            context = browser.new_context()
            page = context.new_page()
            start = page.goto(WEB + '/api/auth/login')
            query = parse_qs(urlparse(page.url).query)
            assert query['code_challenge_method'] == ['S256'] and query['nonce'] and query['state']
            assert len(query['code_challenge'][0]) >= 43
            login_cookie = next(c for c in context.cookies() if c['name'] == 'hub_login')
            assert login_cookie['httpOnly'] and login_cookie['sameSite'] == 'Lax'
            assert 'client_secret' not in page.url
            if mode in ('nonce', 'expired', 'wrong-state'):
                column = {'nonce': "nonce='incorrect'", 'expired': 'expires_at=0', 'wrong-state': "state='incorrect'"}[mode]
                digest = hashlib.sha256(login_cookie['value'].encode()).hexdigest()
                runtime('exec', '-T', 'api', 'python', '-c',
                    f"from backend.database import database\nwith database() as db:\n db.execute(\"UPDATE login_transactions SET {column} WHERE id_hash=?\",('{digest}',))")
            callback_urls = []
            page.on('request', lambda request: callback_urls.append(request.url) if '/api/auth/callback?' in request.url else None)
            page.get_by_label('Username or email').fill('alice')
            page.get_by_label('Password', exact=True).fill(demo_password('alice'))
            page.get_by_role('button', name='Sign In', exact=True).click()
            if mode == 'valid':
                page.wait_for_url(WEB + '/')
                cookies = context.cookies()
                session_cookie = next(c for c in cookies if c['name'] == 'hub_session')
                assert session_cookie['httpOnly'] and session_cookie['sameSite'] == 'Lax'
                assert context.request.get(WEB + '/api/auth/me').status == 200
                assert callback_urls
                assert context.request.get(callback_urls[0]).status == 401  # single-use transaction/code
            else:
                expect(page.locator('body'), f'OIDC rejection mode: {mode}, intercepted callbacks: {len(callback_urls)}').to_contain_text('LOGIN_FAILED')
                assert context.request.get(WEB + '/api/auth/me').status == 401
            context.close()
        browser.close()
    for target in ('https://evil.invalid', '//evil.invalid', '/documents'):
        assert httpx.get(WEB + '/api/auth/login', params={'return_to': target}).status_code == 400
    assert httpx.get(WEB + '/api/auth/callback', params={'state': 'missing', 'code': 'fake'}).status_code == 401
    assert httpx.get(WEB + '/api/http://evil.invalid', follow_redirects=True).status_code == 404


def test_provider_generic_invalid_credentials(runtime):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        messages = []
        for username in ('alice', 'does-not-exist'):
            context = browser.new_context()
            page = context.new_page()
            page.goto(WEB + '/api/auth/login')
            page.get_by_label('Username or email').fill(username)
            page.get_by_label('Password', exact=True).fill('incorrect-password')
            page.get_by_role('button', name='Sign In', exact=True).click()
            error = page.get_by_text('Invalid username or password.', exact=True)
            expect(error).to_be_visible()
            messages.append(error.inner_text())
            assert not any(c['name'] == 'hub_session' for c in context.cookies())
            context.close()
        assert messages[0] == messages[1]
        browser.close()


def test_signed_id_token_validation_over_http(runtime):
    runtime('cp', str(ROOT / 'tests/support/oidc_fault_harness.py'), 'api:/tmp/oidc_fault_harness.py')
    result = runtime('exec', '-T', 'api', 'python', '/tmp/oidc_fault_harness.py')
    assert 'six adversarial token cases passed' in result
