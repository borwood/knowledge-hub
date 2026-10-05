"""negative/stale browser behavior with actual API and controlled delivery."""
import hashlib
from playwright.sync_api import sync_playwright, expect
from test_ingestion_browser import sign_in, ROOT


def upload_select(page):
    if not page.get_by_label('PDF document', exact=True).is_visible():
        page.get_by_text('Upload a PDF', exact=True).click()
    page.get_by_label('PDF document', exact=True).set_input_files(ROOT / 'fixtures/invoice/invoice.pdf')
    with page.expect_response(lambda r:r.url.endswith('/api/documents') and r.request.method=='POST') as response:
        page.get_by_role('button',name='Upload PDF',exact=True).click()
    document=response.value.json()['id']
    page.get_by_role('button',name='Open uploaded document',exact=True).click()
    expect(page.get_by_role('button',name='Ask question',exact=True)).to_be_visible()
    return document


def open_document(page, document):
    page.get_by_label('Search documents',exact=True).fill(document)
    page.get_by_role('button',name='Search',exact=True).click()
    page.get_by_role('button',name='Open document '+document,exact=True).click()


def ask(page):
    page.get_by_role('button',name='Ask question',exact=True).click()
    expect(page.get_by_test_id('answer-text')).to_have_text('USD 125.00')


def test_source_failure_retry_geometry_reload_and_expiry(runtime):
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page()
        sign_in(page,'alice');document=upload_select(page);ask(page)
        page.route('**/source',lambda route:route.fulfill(status=503,json={'error':{'code':'DEPENDENCY_UNAVAILABLE'}}))
        page.get_by_role('button',name='View total evidence',exact=True).click()
        expect(page.get_by_role('button',name='Retry source')).to_be_visible()
        expect(page.get_by_test_id('source-canvas')).not_to_be_visible()
        expect(page.get_by_role('link',name='Download original PDF')).to_have_attribute('href',f'/api/documents/{document}/source')
        page.unroute('**/source');page.get_by_role('button',name='Retry source').click()
        expect(page.get_by_test_id('source-canvas')).to_have_attribute('data-rendered','true')
        # PDF has actual nonwhite ink, not merely an allocated canvas.
        assert page.get_by_test_id('source-canvas').evaluate('''c => {const data=c.getContext('2d').getImageData(0,0,c.width,c.height).data;let ink=0;for(let i=0;i<data.length;i+=4)if(data[i]<100&&data[i+1]<100&&data[i+2]<100&&data[i+3]>0)ink++;return ink>100;}''')
        for field,top in [('total',.2196969696969697),('currency',.1893939393939394)]:
            page.get_by_role('button',name=f'View {field} evidence',exact=True).click()
            expect(page.get_by_test_id('source-canvas')).to_have_attribute('data-rendered','true')
            c=page.get_by_test_id('source-canvas').bounding_box();h=page.get_by_test_id('source-highlight').bounding_box()
            assert abs((h['y']-c['y'])/c['height']-top)<.002
            assert abs((h['x']-c['x'])/c['width']-.08169934640522876)<.002
        page.reload();open_document(page, document);ask(page)
        page.get_by_role('button',name='View total evidence',exact=True).click()
        expect(page.get_by_test_id('source-canvas')).to_have_attribute('data-rendered','true')
        token=hashlib.sha256(next(c['value'] for c in page.context.cookies() if c['name']=='hub_session').encode()).hexdigest()
        runtime('exec','-T','api','python','-c',f"from backend.database import database\nwith database() as db:\n db.execute('DELETE FROM sessions WHERE id_hash=?',('{token}',))")
        expect(page.get_by_role('link',name='Sign in with Keycloak')).to_be_visible(timeout=15000)
        expect(page.get_by_test_id('answer-text')).to_have_count(0);expect(page.get_by_test_id('source-canvas')).to_have_count(0)
        browser.close()


def test_delayed_queries_and_pdf_cannot_restore_changed_or_logged_out_state(runtime):
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page()
        sign_in(page,'alice');first=upload_select(page);second=upload_select(page)
        held=[]
        page.route('**/api/graphql',lambda route:held.append((route,route.fetch())))
        page.get_by_role('button',name='Ask question',exact=True).click()
        expect(page.get_by_role('button',name='Asking…')).to_be_disabled()
        expect(page.get_by_text('Finding supporting invoice facts…')).to_be_visible()
        page.wait_for_timeout(200);assert len(held)==1
        page.get_by_role('button',name='Back to documents',exact=True).click();open_document(page, first)
        route,response=held.pop();route.fulfill(response=response)
        page.wait_for_timeout(200);expect(page.get_by_test_id('answer-text')).to_have_count(0)
        page.unroute('**/api/graphql');ask(page)
        sources=[]
        page.route('**/source',lambda route:sources.append((route,route.fetch())))
        page.get_by_role('button',name='View total evidence',exact=True).click()
        expect(page.get_by_text('Loading source page…')).to_be_visible()
        page.wait_for_timeout(200);assert len(sources)==1
        page.get_by_label('Question',exact=True).select_option('INVOICE_VENDOR')
        route,response=sources.pop();route.fulfill(response=response)
        page.wait_for_timeout(200);expect(page.get_by_test_id('source-canvas')).to_have_count(0)
        page.unroute('**/source')
        page.get_by_label('Question',exact=True).select_option('INVOICE_TOTAL')
        page.route('**/api/graphql',lambda route:held.append((route,route.fetch())))
        page.get_by_role('button',name='Ask question',exact=True).click()
        expect(page.get_by_role('button',name='Asking…')).to_be_disabled()
        page.wait_for_timeout(200);assert len(held)==1
        # Keep page loaded to observe logout clearing before navigating to provider.
        page.route('**/api/auth/logout',lambda route:route.fulfill(status=401,json={'error':{'code':'UNAUTHENTICATED'}}))
        page.get_by_role('button',name='Sign out',exact=True).click()
        route,response=held.pop();route.fulfill(response=response)
        expect(page.get_by_role('link',name='Sign in with Keycloak')).to_be_visible()
        expect(page.get_by_test_id('answer-text')).to_have_count(0)
        expect(page.get_by_test_id('source-canvas')).to_have_count(0)
        browser.close()
