"""Rendered presentation acceptance: contrast, native controls, focus and small screens."""
from playwright.sync_api import sync_playwright, expect
from test_ingestion_browser import sign_in


def test_dark_workspace_accessibility(runtime):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width':1440,'height':1000}, reduced_motion='reduce')
        sign_in(page, 'alice')
        assert page.locator('html').evaluate('el => getComputedStyle(el).colorScheme') == 'dark'
        for width in (1440, 375):
            page.set_viewport_size({'width':width,'height':1000})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            for selector in ('button', 'input[type=search]', 'select', 'input[type=file]'):
                for control in page.locator(selector).all():
                    if control.is_visible():
                        assert control.bounding_box()['height'] >= 40
            search = page.get_by_label('Search documents', exact=True)
            check_contrast(page)
            search.focus()
            assert search.evaluate('el => getComputedStyle(el).outlineStyle') != 'none'
            assert search.evaluate(CONTRAST.replace('style.color','style.outlineColor'),None) >= 3
            assert search.evaluate(CONTRAST.replace('style.color','style.borderTopColor'),None) >= 3
            for button in page.get_by_role('button').all():
                assert button.evaluate('el => getComputedStyle(el).transitionDuration') == '0s'
        page.emulate_media(reduced_motion='no-preference')
        durations=page.get_by_role('button',name='Search',exact=True).evaluate('el=>getComputedStyle(el).transitionDuration').split(',')
        assert all(0 < float(value.strip().removesuffix('s')) <= .18 for value in durations)
        browser.close()

# Computed colors are measured against the nearest painted ancestor, including
# native inputs and pseudo-element placeholders, rather than hardcoded tokens.
CONTRAST = r'''(el, pseudo) => {
 const rgba = s => (s.match(/[\d.]+/g)||[]).map(Number);
 const luminance = rgb => rgb.slice(0,3).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4}).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0);
 const style=getComputedStyle(el,pseudo||null), fg=rgba(style.color);
 let node=el, bg;
 while(node) {bg=rgba(getComputedStyle(node).backgroundColor);if(bg.length===3||bg[3]===1)break;node=node.parentElement;}
 if(!node)bg=[255,255,255];
 const a=luminance(fg),b=luminance(bg);
 return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
}'''


def check_contrast(page):
    for element in page.locator('h1,h2,h3,h4,p,label,dt,dd,strong,summary,a,button,select,input[type=search],.state-badge,.account span,.local-badge,.eyebrow').all():
        if element.is_visible() and (element.inner_text().strip() or element.evaluate("el=>el.tagName==='INPUT'")):
            ratio=element.evaluate(CONTRAST, None)
            assert ratio >= 4.5, (element.inner_text()[:100],ratio)
    search=page.get_by_label('Search documents',exact=True)
    if search.is_visible():
        assert search.evaluate(CONTRAST,'::placeholder') >= 4.5


def test_rendered_states_contrast_disclosures_and_evidence(runtime):
    from test_ingestion_browser import ROOT
    with sync_playwright() as p:
        browser=p.chromium.launch()
        page=browser.new_page(viewport={'width':1440,'height':1000})
        page.goto('http://127.0.0.1:3000')
        check_contrast(page)
        page.screenshot(path='test-results/polish-signed-out.png',full_page=True)
        sign_in(page,'alice')
        page.get_by_label('PDF document',exact=True).set_input_files(ROOT/'fixtures/invoice/invoice.pdf')
        page.get_by_role('button',name='Upload PDF',exact=True).click()
        page.get_by_role('button',name='Open uploaded document',exact=True).click()
        expect(page.get_by_label('PDF document',exact=True)).not_to_be_visible()
        page.get_by_text('Upload a PDF',exact=True).focus();page.keyboard.press('Enter')
        expect(page.get_by_label('PDF document',exact=True)).to_be_visible()
        page.keyboard.press('Enter')
        page.get_by_role('button',name='Ask question',exact=True).click()
        page.get_by_role('button',name='View total evidence',exact=True).click()
        expect(page.get_by_test_id('source-canvas')).to_have_attribute('data-rendered','true')
        for width in (1440,375):
            page.set_viewport_size({'width':width,'height':1000})
            check_contrast(page)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            source=page.get_by_role('region',name='Original PDF page; scroll to inspect the full page',exact=True)
            source.focus();page.keyboard.press('End')
            page.wait_for_function('el=>el.scrollTop+el.clientHeight >= el.scrollHeight-2',arg=source.element_handle())
            page.keyboard.press('Home')
            page.wait_for_function('el=>el.scrollTop === 0',arg=source.element_handle())
            disclosure=page.get_by_text('Extraction & provenance',exact=True)
            disclosure.focus();page.keyboard.press('Enter')
            expect(page.get_by_test_id('evidence-details')).to_be_visible()
            check_contrast(page)
            page.keyboard.press('Enter')
            page.screenshot(path=f'test-results/polish-evidence-{width}.png',full_page=True)
        page.get_by_role('button',name='Back to documents',exact=True).click()
        page.get_by_label('Search documents',exact=True).fill('no-matching-polish-document')
        page.get_by_role('button',name='Search',exact=True).click()
        expect(page.get_by_text('No matching documents. Try another search or state.',exact=True)).to_be_visible()
        check_contrast(page)
        page.screenshot(path='test-results/polish-empty.png',full_page=True)
        page.route('**/api/documents?*',lambda route:route.fulfill(status=503,json={'error':{'code':'DEPENDENCY_UNAVAILABLE'}}))
        page.get_by_role('button',name='Search',exact=True).click()
        expect(page.get_by_role('alert').filter(has_text='Document collection unavailable')).to_be_visible()
        check_contrast(page)
        page.screenshot(path='test-results/polish-error.png',full_page=True)
        page.unroute('**/api/documents?*')
        held=[]
        page.route('**/api/documents?*',lambda route:held.append(route))
        page.get_by_role('button',name='Retry documents',exact=True).click()
        expect(page.get_by_text('Loading documents…',exact=True)).to_be_visible()
        check_contrast(page)
        page.screenshot(path='test-results/polish-loading.png',full_page=True)
        page.unroute('**/api/documents?*')

        browser.close()


def test_long_metadata_statuses_and_upload_disclosure(runtime):
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page(viewport={'width':375,'height':812})
        sign_in(page,'alice')
        documents=[{'id':state+'-'+('a'*100),'filename':'Long filename '+('document-'*24)+'.pdf','state':state,'error_code':'UNKNOWN_FIXTURE_DOCUMENT' if state=='failed' else None,'created_at':'2026-10-05T01:02:03+00:00','byte_length':5242880} for state in ('ready','processing','failed')]
        page.route('**/api/documents?*',lambda route:route.fulfill(json={'documents':documents,'total':3,'page':1,'total_pages':1}))
        page.get_by_role('button',name='Search',exact=True).click()
        expect(page.get_by_role('listitem')).to_have_count(3)
        for summary in page.get_by_text('Upload details',exact=True).all():
            summary.focus();page.keyboard.press('Enter')
        check_contrast(page)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path='test-results/polish-long-metadata.png',full_page=True)
        page.get_by_text('Upload a PDF',exact=True).focus();page.keyboard.press('Enter')
        expect(page.get_by_label('PDF document',exact=True)).not_to_be_visible()
        page.keyboard.press('Enter')
        expect(page.get_by_label('PDF document',exact=True)).to_be_visible()
        browser.close()
