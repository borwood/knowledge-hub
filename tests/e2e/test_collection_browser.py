"""actual browser discovery, inquiry and history context."""
import uuid
from playwright.sync_api import sync_playwright, expect
from test_ingestion_browser import sign_in
from conftest import seed, cleanup


def search(page, value):
    page.get_by_label('Search documents', exact=True).fill(value)
    page.get_by_role('button', name='Search', exact=True).click()


def test_bounded_discovery_keyboard_history_and_refresh(runtime):
    marker = 'browse-' + uuid.uuid4().hex
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width':375,'height':812})
        sign_in(page, 'alice')
        try:
            seed(runtime, marker, 25)
            requests=[]
            page.on('request',lambda req: requests.append(req.url) if '/api/documents' in req.url and req.method=='GET' else None)
            search(page, marker)
            rows=page.get_by_role('list',name='Documents, newest first').get_by_role('listitem')
            expect(rows).to_have_count(10)
            expect(page.get_by_text('25 results · Page 1 of 3',exact=True)).to_be_visible()
            page.get_by_role('button',name='Next page',exact=True).focus();page.keyboard.press('Enter')
            expect(page.get_by_text('25 results · Page 2 of 3',exact=True)).to_be_visible()
            opener=page.get_by_role('button',name='Open document '+marker+'-0014',exact=True)
            opener.focus();scroll=page.evaluate('scrollY');page.keyboard.press('Enter')
            expect(page.get_by_role('region',name='Document inquiry')).to_contain_text(marker+'-0014')
            expect(page.get_by_text('This document is failed (TEST_FAILURE). Questions require a ready document.',exact=True)).to_be_visible()
            expect(page.get_by_role('button',name='Ask question',exact=True)).to_have_count(0)
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            page.get_by_role('button',name='Back to documents',exact=True).click()
            expect(page.get_by_text('25 results · Page 2 of 3',exact=True)).to_be_visible()
            expect(opener).to_be_focused()
            assert abs(page.evaluate('scrollY')-scroll) < 2
            opener.press('Enter');page.go_back()
            expect(opener).to_be_focused()
            page.go_forward()
            expect(page.get_by_role('region',name='Document inquiry')).to_contain_text(marker+'-0014')
            page.reload()
            expect(page.get_by_label('Search documents',exact=True)).to_have_value('')
            expect(page.get_by_role('region',name='Document inquiry')).to_have_count(0)
            assert all('?' in url for url in requests if url.split('?')[0].endswith('/documents'))
            search(page, marker+'-0000')
            expect(rows).to_have_count(1)
            page.get_by_role('button',name='Open document '+marker+'-0000',exact=True).click()
            expect(page.get_by_label('Question',exact=True)).to_be_visible()
            expect(page.get_by_label('Ready invoice',exact=True)).to_have_count(0)
            assert page.url == 'http://127.0.0.1:3000/'
            assert page.evaluate('Object.keys(localStorage)') == []
            page.screenshot(path='test-results/discovery-inquiry-mobile.png',full_page=True)
        finally:
            cleanup(runtime,marker)
            browser.close()


def test_collection_scale_filter_empty_failure_and_latest_request(runtime):
    marker = 'scale-' + uuid.uuid4().hex
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page()
        sign_in(page,'alice')
        try:
            seed(runtime,marker,1000)
            search(page,marker)
            rows=page.get_by_role('list',name='Documents, newest first').get_by_role('listitem')
            expect(rows).to_have_count(10)
            expect(page.get_by_text('1000 results · Page 1 of 100',exact=True)).to_be_visible()
            page.get_by_label('Ingestion state',exact=True).select_option('processing')
            expect(page.get_by_text('333 results · Page 1 of 34',exact=True)).to_be_visible()
            page.get_by_role('button',name='Open document '+marker+'-0997',exact=True).click()
            expect(page.get_by_text('This document is processing. Questions require a ready document.',exact=True)).to_be_visible()
            page.get_by_role('button',name='Back to documents',exact=True).click()
            page.get_by_label('Ingestion state',exact=True).select_option('')
            search(page,marker+'-0000')
            expect(rows).to_have_count(1)
            search(page,marker+'-absent')
            expect(page.get_by_text('No matching documents. Try another search or state.',exact=True)).to_be_visible()
            page.route('**/api/documents?*',lambda route:route.fulfill(status=503,json={'error':{'code':'DEPENDENCY_UNAVAILABLE'}}))
            search(page,marker)
            expect(page.get_by_role('alert').filter(has_text='Document collection unavailable')).to_be_visible()
            page.unroute('**/api/documents?*');page.get_by_role('button',name='Retry documents',exact=True).click()
            expect(rows).to_have_count(10)
            held=[]
            page.route('**/api/documents?*',lambda route:held.append((route,route.fetch())) if 'q=slow' in route.request.url else route.continue_())
            search(page,'slow')
            expect(page.get_by_text('Loading documents…',exact=True)).to_be_visible()
            page.wait_for_timeout(100);assert len(held)==1
            search(page,marker+'-0000');expect(rows).to_have_count(1)
            route,response=held.pop();route.fulfill(response=response)
            page.wait_for_timeout(100);expect(rows).to_have_count(1)
            page.unroute('**/api/documents?*')
            # Empty collection state is distinct from a filtered no-match state.
            page.route('**/api/documents?*',lambda route:route.fulfill(json={'documents':[],'total':0,'page':1,'page_size':10,'total_pages':0}))
            search(page,'');expect(page.get_by_text('No documents yet. Upload a PDF to get started.',exact=True)).to_be_visible()
            page.unroute('**/api/documents?*')
            search(page,marker+'-0000');expect(rows).to_have_count(1)
            page.route('**/api/documents/'+marker+'-0000',lambda route:held.append((route,route.fetch())))
            page.get_by_role('button',name='Open document '+marker+'-0000',exact=True).click()
            expect(page.get_by_text('Loading document…',exact=True)).to_be_visible()
            page.wait_for_timeout(100);assert len(held)==1
            page.route('**/api/auth/logout',lambda route:route.fulfill(status=401,json={}))
            page.get_by_role('button',name='Sign out',exact=True).click()
            route,response=held.pop();route.fulfill(response=response)
            expect(page.get_by_role('link',name='Sign in with Keycloak')).to_be_visible()
            page.go_back();page.go_forward()
            expect(page.get_by_role('region',name='Document inquiry')).to_have_count(0)
            expect(rows).to_have_count(0)
        finally:
            cleanup(runtime,marker);browser.close()


def test_late_json_collection_and_detail_do_not_replace_newer_or_expired_state(runtime):
    marker='json-'+uuid.uuid4().hex
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page()
        sign_in(page,'alice')
        try:
            seed(runtime,marker,25)
            # Delay JSON completion after actual authenticated HTTP completion. Aborting fetch
            # alone cannot protect this boundary; the UI must check its generation again.
            page.evaluate('''() => {
              const original=window.fetch;
              window.fetch=async (...args)=>{
                const response=await original(...args), url=String(args[0]);
                if(window.holdJson && url.includes(window.holdJson)){
                  const json=response.json.bind(response);
                  response.json=async()=>{const value=await json();await new Promise(resolve=>window.releaseJson=resolve);return value;};
                }
                return response;
              };
            }''')
            page.evaluate("window.holdJson='q=late-json'")
            search(page,'late-json')
            page.wait_for_function("typeof window.releaseJson === 'function'")
            search(page,marker+'-0000')
            rows=page.get_by_role('list',name='Documents, newest first').get_by_role('listitem')
            expect(rows).to_have_count(1)
            page.evaluate('window.releaseJson()')
            page.wait_for_timeout(100);expect(rows).to_have_count(1)
            page.evaluate("(id)=>{window.holdJson='/api/documents/'+id;window.releaseJson=null;}",marker+'-0000')
            page.get_by_role('button',name='Open document '+marker+'-0000',exact=True).click()
            page.wait_for_function("typeof window.releaseJson === 'function'")
            page.get_by_role('button',name='Back to documents',exact=True).click()
            expect(rows).to_have_count(1)
            page.evaluate('window.releaseJson()');page.wait_for_timeout(100)
            expect(page.get_by_role('region',name='Document inquiry')).to_have_count(0)
            # A late collection body after an observed 401 cannot restore protected rows.
            page.evaluate("window.holdJson='q=late-expiry';window.releaseJson=null")
            search(page,'late-expiry')
            page.wait_for_function("typeof window.releaseJson === 'function'")
            page.route('**/api/auth/me',lambda route:route.fulfill(status=401,json={}))
            page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
            expect(page.get_by_role('link',name='Sign in with Keycloak')).to_be_visible()
            page.evaluate('window.releaseJson()');page.wait_for_timeout(100)
            expect(rows).to_have_count(0)
        finally:
            cleanup(runtime,marker);browser.close()
