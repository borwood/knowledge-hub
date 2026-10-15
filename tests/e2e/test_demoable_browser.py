"""browser acceptance of the optional explanation/event layer."""
from playwright.sync_api import sync_playwright, expect
from test_ingestion_browser import sign_in, ROOT
from test_answer_recovery import upload_select, ask
from conftest import seed, cleanup
import uuid
import io
import pytest
from pypdf import PdfWriter


def events(page, label, state):
    return page.locator('.demoable-react-event').filter(has_text=label).filter(has=page.locator(f'[data-state="{state}"]'))


def activate(page):
    page.get_by_role('button', name='Enable demo inspection', exact=True).click()
    expect(page.get_by_role('button', name='Disable demo inspection', exact=True)).to_be_visible()


def test_demo_walkthrough_and_preserved_state(runtime):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width':1440, 'height':1000})
        sign_in(page, 'alice')
        activate(page)
        page.get_by_label('Search documents', exact=True).fill('draft?')
        page.get_by_label('Search documents', exact=True).press('?')
        expect(page.get_by_role('button', name='Disable demo inspection', exact=True)).to_be_visible()
        page.get_by_role('button', name='Upload demo invoice', exact=True).click()
        expect(events(page,'Upload PDF','succeeded')).to_have_count(1)
        page.get_by_role('button', name='Open uploaded document', exact=True).click()
        page.get_by_role('button', name='Ask question', exact=True).click()
        expect(page.get_by_test_id('answer-text')).to_have_text('USD 125.00')
        expect(events(page,'Ask invoice question','succeeded')).to_have_count(1)
        page.get_by_role('button', name='View total evidence', exact=True).click()
        expect(page.get_by_test_id('source-canvas')).to_have_attribute('data-rendered','true')
        expect(events(page,'Render source page','succeeded')).to_have_count(1)
        page.get_by_role('button', name='Disable demo inspection', exact=True).click()
        expect(page.get_by_test_id('answer-text')).to_have_text('USD 125.00')
        expect(page.get_by_test_id('source-canvas')).to_have_attribute('data-rendered','true')
        page.screenshot(path='test-results/demoable-inactive.png',full_page=True)
        page.locator('h1').click(); page.keyboard.press('?')
        expect(page.get_by_role('button', name='Disable demo inspection', exact=True)).to_be_visible()
        for width in (1440,375):
            page.set_viewport_size({'width':width,'height':812})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            source=page.get_by_role('region',name='Original PDF page; scroll to inspect the full page',exact=True)
            source.focus(); page.keyboard.press('End')
            page.wait_for_function('el=>el.scrollTop+el.clientHeight>=el.scrollHeight-2',arg=source.element_handle())
            page.screenshot(path=f'test-results/demoable-active-{width}.png',full_page=True)
        page.screenshot(path='test-results/demoable-walkthrough.png',full_page=True)
        browser.close()


def test_demo_collection_scroll_restoration(runtime):
    marker='demo-scroll-'+uuid.uuid4().hex
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page(viewport={'width':375,'height':812})
        sign_in(page,'alice');activate(page)
        try:
            seed(runtime,marker,25)
            page.get_by_label('Search documents',exact=True).fill(marker)
            page.get_by_role('button',name='Search',exact=True).click()
            page.get_by_role('button',name='Next page',exact=True).click()
            expect(page.get_by_text('25 results · Page 2 of 3',exact=True)).to_be_visible()
            page.get_by_role('button',name='Disable demo inspection',exact=True).click()
            expect(page.get_by_text('25 results · Page 2 of 3',exact=True)).to_be_visible()
            activate(page)
            opener=page.get_by_role('button',name='Open document '+marker+'-0014',exact=True)
            opener.focus()
            scroll=page.locator('.demoable-react-app').evaluate('el=>el.scrollTop')
            assert scroll>200
            opener.press('Enter')
            expect(page.get_by_role('region',name='Document inquiry')).to_be_visible()
            page.get_by_role('button',name='Back to documents',exact=True).click()
            expect(opener).to_be_focused()
            assert abs(page.locator('.demoable-react-app').evaluate('el=>el.scrollTop')-scroll)<2
            expect(page.get_by_label('Search documents',exact=True)).to_have_value(marker)
        finally:
            cleanup(runtime,marker);browser.close()


@pytest.mark.parametrize('operation',['question','source'])
def test_demo_session_rejection_on_question_and_source(runtime,operation):
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page()
        sign_in(page,'alice');activate(page);upload_select(page)
        if operation=='question':
            page.route('**/api/graphql',lambda route:route.fulfill(status=401,json={}))
            page.get_by_role('button',name='Ask question',exact=True).click()
            label='Ask invoice question'
        else:
            ask(page)
            page.route('**/source',lambda route:route.fulfill(status=401,json={}))
            page.get_by_role('button',name='View total evidence',exact=True).click()
            label='Fetch original source'
        expect(events(page,label,'failed')).to_have_count(1)
        expect(events(page,label,'succeeded')).to_have_count(0)
        expect(page.get_by_role('link',name='Sign in with Keycloak')).to_be_visible()
        expect(page.locator('.demoable-react-event [data-state="running"]')).to_have_count(0)
        browser.close()


def test_demo_domain_failure_pdf_failure_and_abandoned_source(runtime):
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page()
        sign_in(page,'alice');activate(page)
        writer=PdfWriter();writer.add_blank_page(612,792);pdf=io.BytesIO();writer.write(pdf)
        page.route('**/demo-invoice.pdf',lambda route:route.fulfill(content_type='application/pdf',body=pdf.getvalue()))
        page.get_by_role('button',name='Upload demo invoice',exact=True).click()
        expect(events(page,'Upload PDF','failed')).to_have_count(1)
        expect(events(page,'Upload PDF','succeeded')).to_have_count(0)
        expect(page.get_by_role('alert').filter(has_text='UNKNOWN_FIXTURE_DOCUMENT')).to_be_visible()
        page.unroute('**/demo-invoice.pdf')
        upload_select(page);ask(page)
        page.route('**/source',lambda route:route.fulfill(content_type='application/pdf',body='invalid pdf bytes'))
        page.get_by_role('button',name='View total evidence',exact=True).click()
        expect(events(page,'Fetch original source','succeeded')).to_have_count(1)
        expect(events(page,'Render source page','failed')).to_have_count(1)
        expect(page.get_by_role('button',name='Retry source')).to_be_visible()
        page.unroute('**/source')
        held=[];page.route('**/source',lambda route:held.append(route))
        page.get_by_role('button',name='Retry source').click()
        expect(events(page,'Fetch original source','running')).to_have_count(1)
        page.get_by_label('Question',exact=True).select_option('INVOICE_VENDOR')
        expect(events(page,'Fetch original source','cancelled')).to_have_count(1)
        for route in held:route.abort()
        expect(page.get_by_test_id('source-canvas')).to_have_count(0)
        events(page,'Fetch original source','cancelled').get_by_role('button',name='Dismiss Fetch original source',exact=True).click()
        expect(events(page,'Fetch original source','cancelled')).to_have_count(0)
        browser.close()


def test_demo_render_cancellation_and_network_rejection(runtime):
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page()
        sign_in(page,'alice');activate(page)
        page.route('**/api/documents',lambda route:route.abort())
        page.get_by_role('button',name='Upload demo invoice',exact=True).click()
        expect(events(page,'Upload PDF','failed')).to_have_count(1)
        page.unroute('**/api/documents');upload_select(page)
        page.route('**/api/graphql',lambda route:route.abort())
        page.get_by_role('button',name='Ask question',exact=True).click()
        expect(events(page,'Ask invoice question','failed')).to_have_count(1)
        page.unroute('**/api/graphql');ask(page)
        held=[];page.route('**/pdf.worker.min.mjs',lambda route:held.append(route))
        page.get_by_role('button',name='View total evidence',exact=True).click()
        expect(events(page,'Render source page','running')).to_have_count(1)
        page.get_by_label('Question',exact=True).select_option('INVOICE_VENDOR')
        expect(events(page,'Render source page','cancelled')).to_have_count(1)
        for route in held:route.abort()
        expect(page.get_by_test_id('source-canvas')).to_have_count(0)
        expect(events(page,'Render source page','succeeded')).to_have_count(0)
        browser.close()


@pytest.mark.parametrize('inspection',[False,True])
def test_late_document_detail_preserves_user_focus(runtime,inspection):
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page()
        sign_in(page,'alice')
        if inspection:activate(page)
        with page.expect_response(lambda r:r.url.endswith('/api/documents') and r.request.method=='POST') as uploaded:
            page.get_by_role('button',name='Upload demo invoice',exact=True).click()
        ident=uploaded.value.json()['id']
        held=[]
        page.route('**/api/documents/'+ident,lambda route:held.append((route,route.fetch())))
        page.get_by_role('button',name='Open uploaded document',exact=True).click()
        expect(page.get_by_text('Loading document…',exact=True)).to_be_visible()
        expect(page.get_by_role('button',name='Upload demo invoice',exact=True)).not_to_be_visible()
        summary=page.get_by_text('Upload a demo invoice',exact=True)
        summary.focus()
        page.wait_for_function('document.activeElement.tagName==="SUMMARY"')
        assert len(held)==1
        route,response=held.pop();route.fulfill(response=response)
        expect(page.get_by_role('button',name='Ask question',exact=True)).to_be_visible()
        expect(summary).to_be_focused()
        page.keyboard.press('Enter')
        expect(page.get_by_role('button',name='Upload demo invoice',exact=True)).to_be_visible()
        browser.close()


def test_demo_context_settings_and_mobile(runtime):
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':900})
        sign_in(page,'alice')
        expect(page.locator('.upload-panel form')).to_have_css('padding-top','0px')
        activate(page)
        expect(page.locator('.upload-panel form')).to_have_css('padding-top','34px')
        page.get_by_role('button',name='Upload demo invoice',exact=True).hover()
        expect(page.get_by_role('complementary',name='PDF input contract context',exact=True)).to_be_visible()
        page.get_by_role('button',name='Pin Document ingestion',exact=True).click()
        context=page.get_by_role('complementary',name='Document ingestion context',exact=True)
        expect(context).to_be_visible()
        context.get_by_text('Fixture adapter details',exact=True).click()
        expect(context.get_by_role('link',name='Input and fixture contract')).to_be_visible()
        page.screenshot(path='test-results/demoable-pinned-context.png',full_page=True)
        page.get_by_role('button',name='Disable demo inspection',exact=True).click()
        expect(page.locator('.upload-panel form')).to_have_css('padding-top','0px')
        expect(page.get_by_text('Supplied file: invoice.pdf',exact=True)).to_be_visible()
        activate(page);expect(context).to_be_visible()
        page.get_by_role('button',name='Dismiss component context',exact=True).click()
        page.get_by_role('button',name='Inspection settings',exact=True).click()
        page.get_by_label('Component inspection',exact=True).uncheck()
        expect(page.get_by_role('button',name='Pin Document ingestion',exact=True)).to_have_count(0)
        expect(page.get_by_role('region',name='Live events',exact=True)).to_be_visible()
        page.get_by_label('Event inspection',exact=True).uncheck()
        expect(page.get_by_role('region',name='Live events',exact=True)).to_have_count(0)
        page.get_by_label('Component inspection',exact=True).check()
        page.get_by_role('button',name='Close settings',exact=True).click()
        page.screenshot(path='test-results/demoable-context.png',full_page=True)
        mobile=browser.new_page(viewport={'width':375,'height':667},is_mobile=True,has_touch=True)
        sign_in(mobile,'alice')
        expect(mobile.get_by_role('region',name='Demo orientation',exact=True)).to_be_visible()
        expect(mobile.get_by_role('button',name='Disable demo inspection',exact=True)).to_have_count(0)
        mobile.get_by_role('button',name='Pin Document ingestion',exact=True).tap()
        expect(mobile.get_by_role('complementary',name='Document ingestion context',exact=True)).to_be_visible()
        mobile.get_by_role('button',name='Dismiss component context',exact=True).tap()
        mobile.get_by_label('Search documents',exact=True).fill('touch search')
        mobile.get_by_role('button',name='Search',exact=True).tap()
        expect(mobile.get_by_text('No matching documents. Try another search or state.',exact=True)).to_be_visible()
        assert mobile.evaluate('document.documentElement.scrollWidth <= innerWidth')
        mobile.locator('.demoable-react-app').evaluate('el=>el.scrollTop=0')
        mobile.wait_for_timeout(5100)  # Let the package's initial shortcut hint finish.
        mobile.screenshot(path='test-results/demoable-touch.png',full_page=True)
        browser.close()


def test_demo_failures_cancellation_retry_and_hidden_expiry(runtime):
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':1000})
        sign_in(page,'alice');activate(page)
        page.clock.install()
        page.route('**/demo-invoice.pdf',lambda route:route.fulfill(content_type='application/pdf',body=b'not pdf'))
        page.get_by_role('button',name='Upload demo invoice',exact=True).click()
        expect(events(page,'Upload PDF','failed')).to_have_count(1)
        page.unroute('**/demo-invoice.pdf')
        upload_select(page)
        page.route('**/api/graphql',lambda route:route.fulfill(json={'errors':[{'message':'unavailable','extensions':{'code':'QUERY_UNAVAILABLE'}}]}))
        page.get_by_role('button',name='Ask question',exact=True).click()
        expect(events(page,'Ask invoice question','failed')).to_have_count(1)
        page.unroute('**/api/graphql')
        held=[];page.route('**/api/graphql',lambda route:held.append(route))
        page.get_by_role('button',name='Ask question',exact=True).click()
        expect(events(page,'Ask invoice question','running')).to_have_count(1)
        page.get_by_label('Question',exact=True).select_option('INVOICE_VENDOR')
        expect(events(page,'Ask invoice question','cancelled')).to_have_count(1)
        for route in held: route.abort()
        page.unroute('**/api/graphql');page.get_by_label('Question',exact=True).select_option('INVOICE_TOTAL');ask(page)
        page.route('**/source',lambda route:route.fulfill(status=503,body='unavailable'))
        page.get_by_role('button',name='View total evidence',exact=True).click()
        expect(events(page,'Fetch original source','failed')).to_have_count(1)
        page.unroute('**/source');page.get_by_role('button',name='Retry source',exact=True).click()
        expect(page.get_by_test_id('source-canvas')).to_have_attribute('data-rendered','true')
        expect(events(page,'Fetch original source','succeeded')).to_have_count(1)
        expect(events(page,'Render source page','succeeded')).to_have_count(1)
        # Clock acceleration exercises package timers while hidden, without waiting a minute.
        page.get_by_role('button',name='Ask question',exact=True).click()
        expect(events(page,'Ask invoice question','succeeded')).to_have_count(2)
        page.get_by_role('button',name='Disable demo inspection',exact=True).click()
        page.clock.fast_forward(11000)
        activate(page)
        expect(events(page,'Ask invoice question','cancelled')).to_have_count(0)
        expect(events(page,'Ask invoice question','succeeded')).to_have_count(2)
        page.get_by_role('button',name='Disable demo inspection',exact=True).click()
        page.clock.fast_forward(21000);activate(page)
        expect(events(page,'Ask invoice question','succeeded')).to_have_count(0)
        expect(events(page,'Ask invoice question','failed')).to_have_count(1)
        page.get_by_role('button',name='Disable demo inspection',exact=True).click()
        page.clock.fast_forward(31000);activate(page)
        expect(page.locator('.demoable-react-event')).to_have_count(0)
        browser.close()


def test_demo_session_expiry_and_upload_abandonment(runtime):
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page()
        sign_in(page,'alice');activate(page)
        held=[];page.route('**/api/documents',lambda route:held.append(route))
        page.get_by_role('button',name='Upload demo invoice',exact=True).click()
        expect(events(page,'Upload PDF','running')).to_have_count(1)
        page.route('**/api/auth/logout',lambda route:route.fulfill(status=401,json={}))
        page.get_by_role('button',name='Sign out',exact=True).click()
        expect(events(page,'Upload PDF','cancelled')).to_have_count(1)
        expect(page.get_by_role('link',name='Sign in with Keycloak')).to_be_visible()
        for route in held: route.abort()
        page.unroute('**/api/documents');page.unroute('**/api/auth/logout')
        page.reload();activate(page)
        page.route('**/api/documents',lambda route:route.fulfill(status=401,json={}))
        page.get_by_role('button',name='Upload demo invoice',exact=True).click()
        expect(events(page,'Upload PDF','failed')).to_have_count(1)
        expect(page.get_by_role('link',name='Sign in with Keycloak')).to_be_visible()
        expect(events(page,'Upload PDF','succeeded')).to_have_count(0)
        browser.close()
