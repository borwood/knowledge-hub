"""a real Chromium browser observes the UI contract."""
import os
import httpx
from conftest import wait_ready

from playwright.sync_api import sync_playwright, expect


def test_loading_ready_unavailable_and_keyboard():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        # Hold the request until the browser has visibly rendered loading.
        pending = []
        page.route('**/api/health', lambda route: pending.append(route))
        page.goto(os.getenv('HUB_WEB_URL', 'http://127.0.0.1:3000'))
        expect(page.get_by_role('heading', name='Knowledge Hub', exact=True)).to_be_visible()
        page.get_by_text('Service status & developer details', exact=True).click()
        expect(page.get_by_role('status')).to_contain_text('Checking connection')
        page.wait_for_timeout(100)
        assert pending, 'Browser must actually request readiness'
        pending[0].fulfill(status=200, json={'status': 'ready'})
        page.unroute('**/api/health')
        page.route('**/api/health', lambda route: route.fulfill(status=200, json={'status': 'ready'}))
        expect(page.get_by_role('status')).to_contain_text('Ready for local development')
        page.get_by_role('button', name='Check connection').focus()
        page.keyboard.press('Enter')
        expect(page.get_by_role('button', name='Check connection')).to_be_focused()
        assert page.get_by_role('button', name='Check connection').evaluate(
            'el => getComputedStyle(el).outlineStyle') != 'none'
        page.route('**/api/health', lambda route: route.fulfill(status=503, json={'status': 'unavailable'}))
        page.get_by_role('button', name='Check connection').click()
        expect(page.get_by_role('status')).to_contain_text('Connection unavailable')
        expect(page.get_by_text('Ask a supported invoice question and follow each citation to its source page. All sample values and confidence scores are synthetic.')).to_be_visible()
        browser.close()


def test_real_dependency_loss_and_browser_recovery(runtime):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1280, 'height': 1000})
        page.goto('http://127.0.0.1:3000')
        page.get_by_text('Service status & developer details', exact=True).click()
        expect(page.get_by_role('status')).to_contain_text('Ready for local development', timeout=15000)
        expect(page.get_by_role('row', name='SQLite ready', exact=True)).to_be_visible()
        expect(page.get_by_role('row', name='SeaweedFS (S3) ready', exact=True)).to_be_visible()
        try:
            runtime('stop', 'storage')
            response = httpx.get('http://127.0.0.1:8000/health/ready', timeout=8)
            assert response.status_code == 503
            assert response.json()['dependencies'] == {'sqlite': 'ready', 'object_store': 'unavailable'}
            assert httpx.get('http://127.0.0.1:8000/health/live').status_code == 200
            page.get_by_role('button', name='Check connection').click()
            expect(page.get_by_role('status')).to_contain_text('Connection unavailable', timeout=15000)
            expect(page.get_by_role('row', name='SeaweedFS (S3) unavailable', exact=True)).to_be_visible()
        finally:
            runtime('start', 'storage')
            wait_ready()
        page.get_by_role('button', name='Check connection').click()
        expect(page.get_by_role('status')).to_contain_text('Ready for local development', timeout=15000)
        page.screenshot(path='test-results/foundation-desktop.png', full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        page.screenshot(path='test-results/foundation-mobile.png', full_page=True)
        browser.close()
