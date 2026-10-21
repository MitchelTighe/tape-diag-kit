"""Pinned Playwright offline rendering and behavioral checks; no web server.

Run in Containerfile.browser (Playwright 1.55.0) with --network=none.
Output belongs in task scratch via --output /out. All inputs synthetic.
"""
import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

p=argparse.ArgumentParser()
p.add_argument('--output',type=Path,required=True)
args=p.parse_args()
args.output.mkdir(parents=True,exist_ok=True)
ROOT=Path(__file__).resolve().parents[1]
rows=[]
print("Starting pinned Playwright offline checks",flush=True)
with sync_playwright() as playwright:
    browser=playwright.chromium.launch(args=['--no-sandbox'])
    for scenario in ('synth-alpha','synth-bravo','synth-charlie','fleet-dashboard'):
        for label,width,height in (('desktop',1440,1000),('phone',390,844)):
            print("Rendering "+scenario+" / "+label,flush=True)
            context=browser.new_context(viewport={'width':width,'height':height},device_scale_factor=1)
            page=context.new_page()
            errors=[];remote=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('console',lambda msg:errors.append(msg.text) if msg.type=='error' else None)
            page.on('request',lambda req:remote.append(req.url) if req.url.startswith(('http:','https:')) else None)
            page.goto((ROOT/'artifacts/v3'/(scenario+'.html')).as_uri(),wait_until='load')
            total=12 if scenario=='fleet-dashboard' else 4
            expect(page.locator('.asset-card')).to_have_count(total)
            assert not page.locator('#status').evaluate("n=>n.classList.contains('error')"),page.locator('#status').inner_text()
            scores=page.locator('.asset-card').evaluate_all('nodes=>nodes.map(n=>Number(n.dataset.score))')
            assert scores==sorted(scores)
            assert page.locator('.spark').first.get_attribute('aria-label').startswith('Dated scores:')
            assert page.locator('#report-count').inner_text()==('9' if total==12 else '3')
            page.screenshot(path=str(args.output/(scenario+'-'+label+'.png')),full_page=True)
            page.screenshot(path=str(args.output/(scenario+'-'+label+'-viewport.png')))
            overflow=page.evaluate('document.documentElement.scrollWidth > window.innerWidth')
            assert not overflow
            if scenario=='fleet-dashboard':
                if label=='phone':page.locator('#filters > summary').click()
                page.select_option('#fleet','SYNTH-BRAVO');expect(page.locator('.asset-card')).to_have_count(4)
                page.select_option('#kind','drive');expect(page.locator('.asset-card')).to_have_count(3)
                page.select_option('#assessment','attention');expect(page.locator('.asset-card')).to_have_count(1)
                assert 'LTO8' in page.locator('.asset-card').get_attribute('data-asset-id')
                page.fill('#search','no-such-synthetic-asset');expect(page.locator('.asset-card')).to_have_count(0)
                expect(page.locator('.empty')).to_have_text('No assets match these filters.')
                page.fill('#search','');page.select_option('#assessment','');page.select_option('#kind','');page.select_option('#fleet','')
                page.select_option('#sort','best')
                scores=page.locator('.asset-card').evaluate_all('nodes=>nodes.map(n=>Number(n.dataset.score))');assert scores==sorted(scores,reverse=True)
                page.select_option('#sort','worst')
                page.locator('.asset-card').filter(has_text='Library inventory').first.locator('summary').filter(has_text='Inventory ·').click()
                expect(page.locator('table.inventory:visible').first.locator('tbody tr')).to_have_count(51)
                # Keyboard controls, print CSS and dark color scheme are exercised.
                page.locator('#search').focus();page.keyboard.type('LTO-9');expect(page.locator('.asset-card')).to_have_count(3)
                page.fill('#search','')
                page.emulate_media(color_scheme='dark')
                page.screenshot(path=str(args.output/(scenario+'-'+label+'-dark.png')),full_page=True)
                page.emulate_media(color_scheme='light',media='print')
                assert page.locator('#filters').evaluate("n=>getComputedStyle(n).display")=='none'
                page.pdf(path=str(args.output/(scenario+'-'+label+'-print.pdf')),format='A4',print_background=True)
                page.emulate_media(media='screen')
            assert not errors,errors
            assert not remote,remote
            rows.append({'scenario':scenario,'viewport':label,'width':width,'cards':total,'overflow':overflow,'js_errors':errors,'external_requests':remote})
            context.close()
    # Empty dashboard: local multi-file import, deduplication and malformed-file rejection.
    page=browser.new_page(viewport={'width':390,'height':844})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto((ROOT/'artifacts/v3/empty-dashboard.html').as_uri())
    expect(page.locator('.asset-card')).to_have_count(0)
    paths=sorted((ROOT/'fixtures/fleets').glob('*.json'))
    page.set_input_files('#files',[str(p) for p in paths])
    expect(page.locator('.asset-card')).to_have_count(12)
    assert page.locator('#report-count').inner_text()=='9'
    page.set_input_files('#files',str(paths[0]));expect(page.locator('#status')).to_contain_text('0 new report(s)')
    cases=[('malformed.json','{invalid'),('legacy.json',json.dumps({'schema_version':'2.0'})),
        ('unknown-version.json',json.dumps({'schema_version':'9.0'}))]
    report=json.loads(paths[0].read_text());report['drives'][0]['health']['score']=1
    cases.append(('bad-score.json',json.dumps(report)))
    for name,text in cases:
        page.set_input_files('#files',{'name':name,'mimeType':'application/json','buffer':text.encode()})
        expect(page.locator('#status')).to_have_class('status error')
        expect(page.locator('.asset-card')).to_have_count(12)
    page.set_input_files('#files',{'name':'oversized.json','mimeType':'application/json','buffer':b' '*(16*1024*1024+1)})
    expect(page.locator('#status')).to_contain_text('16 MiB')
    # User-controlled strings stay literal. A new valid report with script/HTML-looking labels.
    report=json.loads(paths[0].read_text());report['fleet_id']='SYNTH-ESCAPE';report['drives'][0]['inquiry']['product']='</script><img src=x onerror=alert(1)>'
    page.set_input_files('#files',{'name':'escaped.json','mimeType':'application/json','buffer':json.dumps(report).encode()})
    expect(page.locator('.asset-card')).to_have_count(16)
    expect(page.locator('img')).to_have_count(0)
    assert any('</script><img' in text for text in page.locator('h3').all_text_contents())
    assert not errors,errors
    # Undated legacy migration does not fabricate a chronological trend.
    page.goto((ROOT/'artifacts/v3/first-report.html').as_uri())
    expect(page.locator('.asset-card')).to_have_count(2)
    assert 'No dated score trend' in page.locator('.spark').first.get_attribute('aria-label')
    browser.close()
(args.output/'browser-checks.json').write_text(json.dumps({'viewports':rows,'behavior_checks':['sort','fleet/type/evidence/search filters','empty state','inventory expansion','keyboard search','dark','print','multi-file import','duplicate import','malformed/version/score/size rejection','HTML injection containment','undated trends'],'status':'PASS'},indent=2)+'\n')
print('Browser checks: 8/8 scenario/viewports; zero overflow, JS errors or external requests. Offline file loading, filters, sorting, inventory, dark, print and rejection checks passed.')
