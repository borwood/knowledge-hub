"""advertised local identity and automatic genuine upload."""
import hashlib
import pytest
from playwright.sync_api import sync_playwright, expect
from test_ingestion_browser import ROOT, WEB, sign_in
from test_demoable_browser import activate, events


def test_advertised_demo_credentials_sign_in(runtime):
    with sync_playwright() as p:
        browser=p.chromium.launch()
        for username in ('alice','bob'):
            context=browser.new_context();page=context.new_page();page.goto(WEB)
            activate(page)
            page.get_by_role('link',name='Sign in with Keycloak').hover()
            expect(page.get_by_role('heading',name='Local demo accounts',exact=True)).to_be_visible()
            page.get_by_role('button',name='Pin Demo sign-in',exact=True).click()
            password=page.locator(f'[data-demo-password="{username}"]').inner_text()
            assert password  # Never include the credential value in assertion output.
            page.get_by_role('link',name='Sign in with Keycloak').click()
            page.get_by_label('Username or email').fill(username)
            page.get_by_label('Password',exact=True).fill(password)
            page.get_by_role('button',name='Sign In',exact=True).click()
            expect(page.get_by_text(f'Signed in as {username}',exact=True)).to_be_visible()
            context.close()
        browser.close()


def test_credentials_belong_only_to_login_inspection(runtime):
    with sync_playwright() as p:
        browser=p.chromium.launch();context=browser.new_context(permissions=['clipboard-read','clipboard-write']);page=context.new_page()
        requests=[]
        page.on('request',lambda request:requests.append(request.url) if request.url.endswith('/api/demo-credentials') else None)
        page.goto(WEB)
        login=page.get_by_role('link',name='Sign in with Keycloak',exact=True)
        expect(login).to_be_visible();page.wait_for_timeout(300)
        assert len(requests)==0
        expect(page.get_by_role('heading',name='Local demo accounts',exact=True)).to_have_count(0)
        expect(page.locator('main [data-demo-password]')).to_have_count(0)
        activate(page)
        login.hover()
        expect(page.locator('[data-demo-password]')).to_have_count(2)
        assert len(requests)==1
        pin=page.get_by_role('button',name='Pin Demo sign-in',exact=True)
        pin.focus();page.keyboard.press('Enter')
        page.locator('h1').hover()
        password=page.locator('[data-demo-password="alice"]')
        expect(password).to_be_visible()
        password.select_text();page.keyboard.press('Control+C')
        copied_matches=page.evaluate('navigator.clipboard.readText()')==password.inner_text()
        assert copied_matches, 'Pinned credentials remain selectable and copyable'
        page.get_by_role('button',name='Disable demo inspection',exact=True).click()
        expect(page.locator('[data-demo-password]')).to_have_count(0)
        activate(page)
        expect(page.locator('[data-demo-password]')).to_have_count(2)
        page.get_by_role('button',name='Inspection settings',exact=True).click()
        page.get_by_label('Component inspection',exact=True).uncheck()
        expect(page.locator('[data-demo-password]')).to_have_count(0)
        expect(page.get_by_role('region',name='Live events',exact=True)).to_be_visible()
        expect(login).to_have_attribute('href','/api/auth/login')
        browser.close()


def test_touch_login_context_can_be_pinned_and_dismissed(runtime):
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page(viewport={'width':375,'height':667},is_mobile=True,has_touch=True)
        page.goto(WEB)
        page.get_by_role('link',name='Sign in with Keycloak').scroll_into_view_if_needed()
        page.get_by_role('button',name='Pin Demo sign-in',exact=True).tap()
        expect(page.locator('[data-demo-password]')).to_have_count(2)
        page.locator('[data-demo-password="bob"]').scroll_into_view_if_needed()
        expect(page.locator('[data-demo-password="bob"]')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.get_by_role('button',name='Dismiss component context',exact=True).tap()
        expect(page.locator('[data-demo-password]')).to_have_count(0)
        page.get_by_role('link',name='Sign in with Keycloak').tap()
        expect(page.get_by_label('Username or email')).to_be_visible()
        browser.close()


def test_unavailable_demo_credentials_have_recovery_and_login(runtime):
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page()
        page.route('**/api/demo-credentials',lambda route:route.fulfill(status=503,json={'error':'unavailable'},headers={'Cache-Control':'no-store'}))
        page.goto(WEB)
        expect(page.get_by_text('Local demo credentials are unavailable. Run local setup and restart the web service.',exact=True)).to_have_count(0)
        activate(page)
        page.get_by_role('link',name='Sign in with Keycloak').hover()
        expect(page.get_by_text('Local demo credentials are unavailable. Run local setup and restart the web service.',exact=True)).to_be_visible()
        expect(page.locator('[data-demo-password]')).to_have_count(0)
        expect(page.get_by_role('link',name='Sign in with Keycloak')).to_be_visible()
        browser.close()


@pytest.mark.parametrize('failure',['http','network'])
def test_demo_sample_failure_does_not_submit_and_retry_is_real(runtime,failure):
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page()
        sign_in(page,'alice');activate(page)
        posts=[]
        page.on('request',lambda request:posts.append(request) if request.method=='POST' and request.url.endswith('/api/documents') else None)
        page.route('**/demo-invoice.pdf',lambda route:route.abort() if failure=='network' else route.fulfill(status=503,body='unavailable'))
        page.get_by_role('button',name='Upload demo invoice',exact=True).click()
        expect(page.get_by_role('alert').filter(has_text='Demo invoice unavailable. Nothing was uploaded. Try again.')).to_be_visible()
        expect(events(page,'Upload PDF','failed')).to_have_count(1)
        assert len(posts)==0
        page.unroute('**/demo-invoice.pdf')
        page.get_by_role('button',name='Upload demo invoice',exact=True).click()
        expect(events(page,'Upload PDF','succeeded')).to_have_count(1)
        assert len(posts)==1
        browser.close()


@pytest.mark.parametrize('invalidate',['logout','expiry'])
def test_delayed_demo_bytes_cannot_upload_after_session_ends(runtime,invalidate):
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page()
        sign_in(page,'alice');activate(page)
        posts=[]
        page.on('request',lambda request:posts.append(request) if request.method=='POST' and request.url.endswith('/api/documents') else None)
        # Deliberately hold blob resolution after HTTP completes, so abort alone cannot protect it.
        page.evaluate('''() => {
          const original=window.fetch;
          window.fetch=async (...args)=>{
            const response=await original(...args);
            if(String(args[0])==='/demo-invoice.pdf'){
              const blob=response.blob.bind(response);
              response.blob=async()=>{const bytes=await blob();await new Promise(resolve=>window.releaseSample=resolve);return bytes;};
            }
            return response;
          };
        }''')
        page.get_by_role('button',name='Upload demo invoice',exact=True).click()
        page.wait_for_function("typeof window.releaseSample==='function'")
        expect(page.get_by_role('button',name='Uploading…',exact=True)).to_be_disabled()
        # Even a programmatic second submit must retain one pending operation.
        page.locator('.upload-panel form').evaluate('el=>el.requestSubmit()')
        expect(events(page,'Upload PDF','running')).to_have_count(1)
        assert len(posts)==0
        if invalidate=='logout':
            page.route('**/api/auth/logout',lambda route:route.fulfill(status=401,json={}))
            page.get_by_role('button',name='Sign out',exact=True).click()
        else:
            page.route('**/api/auth/me',lambda route:route.fulfill(status=401,json={}))
            page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        expect(page.get_by_role('link',name='Sign in with Keycloak')).to_be_visible()
        expect(events(page,'Upload PDF','cancelled')).to_contain_text('No upload was submitted.')
        page.evaluate('window.releaseSample()')
        page.wait_for_timeout(100)
        assert len(posts)==0
        expect(events(page,'Upload PDF','succeeded')).to_have_count(0)
        browser.close()


def test_one_click_upload_retains_exact_fixture_and_answers(runtime):
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page()
        sign_in(page,'alice')
        expect(page.locator('input[type=file]')).to_have_count(0)
        upload=page.get_by_role('button',name='Upload demo invoice',exact=True)
        expect(upload).to_be_enabled()
        ids=[]
        for _ in range(2):
            with page.expect_response(lambda r:r.url.endswith('/api/documents') and r.request.method=='POST') as response:
                upload.click()
            record=response.value.json();ids.append(record['id'])
            assert record['filename']=='invoice.pdf'
            source=page.request.get(WEB+f"/api/documents/{record['id']}/source")
            assert hashlib.sha256(source.body()).digest()==hashlib.sha256((ROOT/'fixtures/invoice/invoice.pdf').read_bytes()).digest()
        assert ids[0]!=ids[1]
        page.get_by_role('button',name='Open uploaded document',exact=True).click()
        page.get_by_role('button',name='Ask question',exact=True).click()
        expect(page.get_by_test_id('answer-text')).to_have_text('USD 125.00')
        page.get_by_role('button',name='View total evidence',exact=True).click()
        expect(page.get_by_test_id('source-canvas')).to_have_attribute('data-rendered','true')
        browser.close()
