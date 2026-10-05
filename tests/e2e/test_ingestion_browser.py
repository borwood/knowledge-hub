"""real browser login, upload, list, failure and isolation."""
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from conftest import demo_password
import hashlib
import uuid
import io
from datetime import datetime
from pypdf import PdfWriter

ROOT = Path(__file__).resolve().parents[2]
WEB = 'http://127.0.0.1:3000'


def password(username):
    return demo_password(username)


def sign_in(page, username):
    page.goto(WEB)
    page.get_by_role('link', name='Sign in with Keycloak').click()
    page.get_by_label('Username or email').fill(username)
    page.get_by_label('Password', exact=True).fill(password(username))
    page.get_by_role('button', name='Sign In', exact=True).click()
    expect(page.get_by_text(f'Signed in as {username}', exact=True)).to_be_visible(timeout=15000)


def test_browser_offers_provider_login(runtime):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(WEB)
        expect(page.get_by_role('link', name='Sign in with Keycloak')).to_be_visible()
        browser.close()


def test_duplicate_filename_uploads_have_persistent_owner_scoped_metadata(runtime):
    """distinguish identical names by actual upload identity."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        sign_in(page, 'alice')
        region = page.get_by_role('region', name='Your documents')
        uploaded = []
        for _ in range(2):
            page.get_by_label('PDF document', exact=True).set_input_files(ROOT / 'fixtures/invoice/invoice.pdf')
            with page.expect_response(lambda response: response.url == WEB + '/api/documents' and response.request.method == 'POST') as response:
                page.get_by_role('button', name='Upload PDF', exact=True).click()
            result = response.value.json()
            assert response.value.status == 201 and result['state'] == 'ready'
            uploaded.append(result)
        assert uploaded[0]['id'] != uploaded[1]['id']
        expect(region.get_by_role('alert')).to_contain_text(uploaded[1]['id'])

        def verify_records():
            for result in uploaded:
                row = region.get_by_role('listitem').filter(has_text=result['id'])
                expect(row).to_contain_text('invoice.pdf')
                timestamp = datetime.fromisoformat(result['created_at']).strftime('%Y-%m-%d %H:%M:%S UTC')
                expect(row.get_by_role('time')).to_have_text(timestamp)
                expect(row.get_by_role('time')).to_have_attribute('datetime', result['created_at'])
                expect(row).to_contain_text(f"{result['byte_length']:,} bytes")
            expect(region.get_by_role('listitem').first).to_contain_text(uploaded[1]['id'])

        verify_records()
        page.reload()
        verify_records()
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        page.screenshot(path='test-results/ingestion-metadata-mobile.png', full_page=True)
        page.get_by_role('button', name='Sign out', exact=True).click()
        page.get_by_role('button', name='Logout', exact=True).click()
        page.wait_for_url(WEB + '/')
        sign_in(page, 'bob')
        for result in uploaded:
            expect(region.get_by_role('listitem').filter(has_text=result['id'])).to_have_count(0)
        browser.close()


def test_real_login_upload_pending_refresh_logout_and_second_user(runtime):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        sign_in(page, 'alice')
        filename = f'browser-{uuid.uuid4()}.pdf'
        page.get_by_label('PDF document', exact=True).set_input_files(
            {'name': filename, 'mimeType': 'application/pdf', 'buffer': (ROOT / 'fixtures/invoice/invoice.pdf').read_bytes()})
        expect(page.get_by_text('Selected: ' + filename)).to_be_visible()
        # Hold the actual request, observe pending/duplicate prevention, then release to real API.
        pending = []
        page.route('**/api/documents', lambda route: pending.append(route) if route.request.method == 'POST' else route.continue_())
        page.get_by_role('button', name='Upload PDF', exact=True).focus()
        page.keyboard.press('Enter')
        expect(page.get_by_role('button', name='Uploading…')).to_be_disabled()
        expect(page.get_by_text('Processing upload. Please wait.')).to_be_visible()
        page.wait_for_timeout(100)
        assert len(pending) == 1
        pending[0].continue_()
        expect(page.get_by_role('region', name='Your documents').get_by_role('alert')).to_contain_text('Document ready', timeout=15000)
        page.unroute('**/api/documents')
        expect(page.get_by_role('listitem').filter(has_text=filename)).to_contain_text('ready')
        page.reload()
        expect(page.get_by_role('listitem').filter(has_text=filename)).to_be_visible()
        page.get_by_label('PDF document', exact=True).set_input_files({'name': 'invalid.pdf', 'mimeType': 'application/pdf', 'buffer': b'not pdf'})
        page.get_by_role('button', name='Upload PDF', exact=True).click()
        expect(page.get_by_role('region', name='Your documents').get_by_role('alert')).to_contain_text('INVALID_PDF')
        assert page.get_by_role('region', name='Your documents').get_by_role('alert').evaluate('el => getComputedStyle(el).display') != 'none'
        writer = PdfWriter()
        writer.add_blank_page(612, 792)
        unknown = io.BytesIO()
        writer.write(unknown)
        unknown_name = f'unknown-{uuid.uuid4()}.pdf'
        page.get_by_label('PDF document', exact=True).set_input_files(
            {'name': unknown_name, 'mimeType': 'application/pdf', 'buffer': unknown.getvalue()})
        page.get_by_role('button', name='Upload PDF', exact=True).click()
        expect(page.get_by_role('region', name='Your documents').get_by_role('alert')).to_contain_text('Document failed: UNKNOWN_FIXTURE_DOCUMENT')
        expect(page.get_by_role('listitem').filter(has_text=unknown_name)).to_contain_text('failed (UNKNOWN_FIXTURE_DOCUMENT)')
        page.reload()
        expect(page.get_by_role('listitem').filter(has_text=unknown_name)).to_contain_text('failed (UNKNOWN_FIXTURE_DOCUMENT)')
        page.screenshot(path='test-results/ingestion-desktop.png', full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        page.screenshot(path='test-results/ingestion-mobile.png', full_page=True)
        page.get_by_role('button', name='Sign out', exact=True).click()
        # RP initiated logout without ID-token-in-URL uses Keycloak's confirmation page.
        page.get_by_role('button', name='Logout', exact=True).click()
        page.wait_for_url(WEB + '/')
        expect(page.get_by_role('link', name='Sign in with Keycloak')).to_be_visible()
        expect(page.get_by_text(filename, exact=True)).not_to_be_visible()
        sign_in(page, 'bob')
        expect(page.get_by_role('listitem').filter(has_text=filename)).to_have_count(0)
        digest = hashlib.sha256(next(c['value'] for c in page.context.cookies() if c['name'] == 'hub_session').encode()).hexdigest()
        runtime('exec', '-T', 'api', 'python', '-c',
            f"from backend.database import database\nwith database() as db:\n db.execute('UPDATE sessions SET expires_at=0 WHERE id_hash=?',('{digest}',))")
        expect(page.get_by_role('link', name='Sign in with Keycloak')).to_be_visible(timeout=15000)
        expect(page.get_by_role('heading', name='Document collection')).not_to_be_visible()
        browser.close()
