"""Real runtime prerequisites. Required environments fail rather than skip."""
from pathlib import Path
import subprocess
import time

import httpx
import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def compose(*args):
    result = subprocess.run(['docker', 'compose', *args], cwd=ROOT,
                            text=True, encoding='utf-8', errors='replace', capture_output=True, timeout=600)
    assert result.returncode == 0, f'Compose {args[:2]} failed:\n{result.stdout}\n{result.stderr}'
    return result.stdout


def wait_ready():
    for _ in range(60):
        try:
            if httpx.get('http://127.0.0.1:8000/health/ready', timeout=8).status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(1)
    raise AssertionError('API dependencies did not recover within 60 attempts')


@pytest.fixture(scope='session')
def runtime():
    assert (ROOT / '.env').exists(), 'Run python scripts/setup_local.py first'
    result = subprocess.run(['docker', 'info'], capture_output=True, timeout=20)
    assert result.returncode == 0, 'Docker engine is required and must be running'
    compose('up', '-d', '--build', '--wait', '--wait-timeout', '120')
    wait_ready()
    return compose


def demo_password(username):
    values = dict(line.split('=', 1) for line in (ROOT / '.env').read_text().splitlines() if '=' in line)
    return values[f'DEMO_{username.upper()}_PASSWORD']


@pytest.fixture
def users(runtime):
    """Exercise real Keycloak browser authorization for every HTTP test identity."""
    clients = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for username in ('alice', 'bob'):
            context = browser.new_context()
            page = context.new_page()
            page.goto('http://127.0.0.1:3000/api/auth/login')
            page.get_by_label('Username or email').fill(username)
            page.get_by_label('Password', exact=True).fill(demo_password(username))
            page.get_by_role('button', name='Sign In', exact=True).click()
            page.wait_for_url('http://127.0.0.1:3000/', timeout=15000)
            cookies = {cookie['name']: cookie['value'] for cookie in context.cookies() if cookie['name'] == 'hub_session'}
            assert cookies, 'Real Keycloak login must yield opaque BFF cookie'
            client = httpx.Client(base_url='http://127.0.0.1:8000', cookies=cookies, timeout=20)
            identity = client.get('/auth/me')
            assert identity.status_code == 200
            assert identity.json()['username'] == username
            client.headers.update({'Origin': 'http://127.0.0.1:3000', 'X-CSRF-Token': identity.json()['csrf_token']})
            clients.append(client)
            context.close()
        browser.close()
    try:
        yield clients
    finally:
        for client in clients:
            client.post('/auth/logout')
            client.close()


def seed(runtime, marker, count):
    runtime('exec', '-T', 'api', 'python', '-c', f'''from backend.database import database
with database() as db:
 owner=db.execute("SELECT id FROM identities WHERE username='alice'").fetchone()[0]
 for i in range({count}):
  ident={marker!r}+f'-{{i:04d}}'
  name={marker!r}+(' special%_\\\\.pdf' if i==0 else ' duplicate.pdf')
  state=['ready','processing','failed'][i%3]
  db.execute('INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?)',(ident,owner,name,'0'*64,1234,state,'TEST_FAILURE' if state=='failed' else None,ident,'2099-01-01T00:00:00+00:00','2099-01-01T00:00:00+00:00'))
''')


def cleanup(runtime, marker):
    runtime('exec', '-T', 'api', 'python', '-c', f'''from backend.database import database
with database() as db:
 db.execute('DELETE FROM documents WHERE substr(id,1,?)=?',({len(marker)},{marker!r}))
''')


