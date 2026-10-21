"""Playwright visual checks. Run in pinned browser container, network disabled."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path('/work/artifacts/v2')
shots = root / 'screenshots'
shots.mkdir(exist_ok=True)
results = []
with sync_playwright() as pw:
    browser = pw.chromium.launch(args=['--no-sandbox'])
    for name in ('sample-host','healthy','cleaning-needed','degraded-media'):
        for width, label in ((1440,'desktop'),(390,'phone')):
            page = browser.new_page(viewport={'width':width,'height':1000 if label=='desktop' else 844}, device_scale_factor=1, color_scheme='light')
            requests = []
            failures = []
            page.on('request', lambda r: requests.append(r.url) if not r.url.startswith('file:') else None)
            page.on('pageerror', lambda error: failures.append(str(error)))
            page.goto((root/(name+'.html')).as_uri())
            page.wait_for_load_state('load')
            assert page.title() == 'tapediag · Diagnostic report'
            assert page.locator('h1').inner_text() == 'Tape system health'
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (name,label,'horizontal document overflow')
            assert not requests and not failures, (requests,failures)
            max_row_height = page.locator('tbody tr').evaluate_all('(rows)=>Math.max(0,...rows.map(r=>r.getBoundingClientRect().height))')
            assert max_row_height < 500, (name,label,'table row became excessively tall',max_row_height)
            page.screenshot(path=str(shots/(name+'-'+label+'.png')),full_page=True)
            # Also capture the first screen at readable review resolution.
            page.screenshot(path=str(shots/(name+'-'+label+'-viewport.png')))
            row={'scenario':name,'viewport':label,'width':width,'horizontal_overflow':False,'external_requests':requests,'page_errors':failures,
                 'document_height':page.evaluate('document.documentElement.scrollHeight'),'max_table_row_height':max_row_height}
            results.append(row)
            if name=='healthy':
                page.locator('#dark').check()
                page.screenshot(path=str(shots/(name+'-'+label+'-dark.png')),full_page=True)
                assert page.locator('body').evaluate('(el)=>getComputedStyle(el).backgroundColor') == 'rgb(14, 24, 34)'
                page.emulate_media(media='print')
                page.pdf(path=str(shots/(name+'-'+label+'-print.pdf')),format='A4',print_background=True)
            page.close()
    browser.close()
(root/'browser-checks.json').write_text(json.dumps(results,indent=2)+'\n')
print('Browser checks: 8/8 scenario/viewports; zero page overflow, external requests or JS errors; dark and print exercised')
