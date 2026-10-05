"""browser acceptance: real canvas, independent citations and clearing."""
from playwright.sync_api import sync_playwright, expect
from test_ingestion_browser import sign_in, ROOT

def test_answers_and_source_canvas(runtime):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 375, 'height': 812})
        page.goto('http://127.0.0.1:3000')
        expect(page.locator('header')).to_contain_text('From document to answer')
        page.get_by_text('Service status & developer details', exact=True).click()
        expect(page.locator('footer')).to_contain_text('Ask a supported invoice question')
        expect(page.get_by_role('link',name='GraphQL explorer')).to_have_count(0)
        page.get_by_role('link',name='GraphQL health',exact=True).click()
        assert page.locator('body').inner_text().find('objectStore') >= 0
        assert 'INVALID_REQUEST' not in page.locator('body').inner_text()
        sign_in(page, 'alice')
        page.get_by_label('PDF document', exact=True).set_input_files(ROOT / 'fixtures/invoice/invoice.pdf')
        with page.expect_response(lambda r: r.url.endswith('/api/documents') and r.request.method == 'POST') as response:
            page.get_by_role('button', name='Upload PDF', exact=True).click()
        doc = response.value.json()
        page.get_by_role('button', name='Open uploaded document', exact=True).click()
        page.get_by_role('button', name='Ask question', exact=True).click()
        expect(page.get_by_test_id('answer-text')).to_have_text('USD 125.00')
        for name in ('total', 'currency'):
            page.get_by_role('button', name=f'View {name} evidence', exact=True).focus()
            page.keyboard.press('Enter')
            expect(page.get_by_test_id('source-canvas')).to_have_attribute('data-rendered', 'true')
            expect(page.get_by_test_id('source-highlight')).to_be_visible()
            page.get_by_text('Extraction & provenance', exact=True).click()
            expect(page.get_by_test_id('evidence-details')).to_be_visible()
            expect(page.get_by_test_id('evidence-details')).to_contain_text(name)
        page.get_by_label('Question', exact=True).select_option('INVOICE_VENDOR')
        expect(page.get_by_test_id('answer-text')).to_have_count(0)
        page.get_by_role('button', name='Ask question', exact=True).click()
        expect(page.get_by_test_id('answer-text')).to_have_text('Juniper Example Supplies')
        page.get_by_role('button', name='View vendor evidence', exact=True).click()
        expect(page.get_by_test_id('source-canvas')).to_have_attribute('data-rendered', 'true')
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        page.get_by_role('region',name='Invoice questions',exact=True).screenshot(path='test-results/questions-mobile.png')
        page.screenshot(path='test-results/answers-mobile.png', full_page=True)
        browser.close()
