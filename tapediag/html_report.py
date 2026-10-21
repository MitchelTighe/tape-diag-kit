"""Offline, escaped, self-contained HTML. No remote assets or active scripts."""
from html import escape
import json

from .health import summarize
from .observations import library_checks, response_from_page
from .validation import validate_report

CSS = """
:root{color-scheme:light dark;--bg:#f2f5f8;--card:#fff;--ink:#182a3b;--muted:#526578;--line:#d7e1ea;--accent:#006c70;--subtle:#e8f3f3;--warn:#785200;--fail:#a52c3e;--pass:#167044}
@media(prefers-color-scheme:dark){:root{--bg:#0e1822;--card:#172633;--ink:#e6eff6;--muted:#a9bdcd;--line:#314858;--accent:#72d7ce;--subtle:#203a43;--warn:#f3c76f;--fail:#ff9aa8;--pass:#83dbab}}
body:has(#light:checked){color-scheme:light;--bg:#f2f5f8;--card:#fff;--ink:#182a3b;--muted:#526578;--line:#d7e1ea;--accent:#006c70;--subtle:#e8f3f3;--warn:#785200;--fail:#a52c3e;--pass:#167044}
body:has(#dark:checked){color-scheme:dark;--bg:#0e1822;--card:#172633;--ink:#e6eff6;--muted:#a9bdcd;--line:#314858;--accent:#72d7ce;--subtle:#203a43;--warn:#f3c76f;--fail:#ff9aa8;--pass:#83dbab}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 system-ui,sans-serif}main,.toolbar{max-width:1160px;margin:auto;padding:24px}a{color:var(--accent);text-underline-offset:3px;overflow-wrap:anywhere}a:focus-visible,input:focus-visible,summary:focus-visible{outline:3px solid var(--accent);outline-offset:4px}.toolbar{display:flex;gap:16px;justify-content:space-between;align-items:center;padding-bottom:0}.brand{font-size:14px;letter-spacing:.12em;font-weight:750}.toolbar fieldset{border:1px solid var(--line);border-radius:9px;font-size:13px;padding:4px 12px}.toolbar legend{padding:0 4px}.toolbar label{white-space:nowrap;margin-right:8px}h1{font-size:clamp(32px,5vw,48px);line-height:1.15;letter-spacing:-.035em;margin:12px 0}h2{font-size:25px;line-height:1.3;margin:0 0 12px}h3{font-size:18px;margin:22px 0 10px}p{margin:8px 0}.muted,small{color:var(--muted)}.eyebrow{color:var(--accent);font-size:12px;font-weight:750;letter-spacing:.14em;text-transform:uppercase}.hero{padding:20px 0 28px}.summary{display:grid;grid-template-columns:1.25fr 2fr;gap:22px;margin:20px 0 30px}.card,section{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:26px;margin-bottom:24px;min-width:0}.summary .card{margin:0}.score{font-size:68px;font-weight:750;line-height:1.15;letter-spacing:-.06em}.score small{font-size:19px;font-weight:450;letter-spacing:0}.badge{display:inline-block;padding:3px 10px;border-radius:6px;background:var(--subtle);font-size:12px;font-weight:750;text-transform:uppercase;letter-spacing:.06em}.pass{color:var(--pass)}.warn,.warning{color:var(--warn)}.fail,.critical{color:var(--fail)}.metrics{display:flex;gap:36px;flex-wrap:wrap;margin-top:16px}.metric strong{display:block;font-size:32px;line-height:1.2}.metric span{font-size:13px;color:var(--muted)}nav{display:flex;gap:20px;flex-wrap:wrap;font-size:14px;margin:16px 0 28px}.device-head{display:flex;justify-content:space-between;align-items:center;gap:12px}.device-head code{font-size:15px;color:var(--accent)}.facts{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:18px 0}.facts div{background:var(--bg);border-radius:8px;padding:12px;overflow-wrap:anywhere}.facts dt{font-size:12px;color:var(--muted)}.facts dd{margin:3px 0 0;font-weight:650}.table-wrap{overflow-x:auto;max-width:100%;border:1px solid var(--line);border-radius:8px;margin:12px 0}table{width:100%;border-collapse:collapse;font-size:14px;text-align:left}th{background:var(--subtle);font-size:12px;color:var(--muted)}th,td{padding:12px 14px;border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere}tbody tr:last-child td{border:0}td:first-child{min-width:120px}td:last-child{min-width:160px}code,pre{font:13px/1.6 ui-monospace,monospace}pre{overflow:auto;padding:16px;background:var(--bg);border-radius:8px;white-space:pre-wrap;overflow-wrap:anywhere}ul{padding-left:22px}li{margin:6px 0}.callout{border-left:3px solid var(--accent);padding:10px 16px;background:var(--subtle);border-radius:0 7px 7px 0}.rule{margin:9px 0}.rule strong{font-size:14px}summary{cursor:pointer;color:var(--accent);font-weight:650;padding:8px 0}footer{color:var(--muted);font-size:13px;padding:6px 0 35px}section{scroll-margin-top:18px}.empty{color:var(--muted);font-size:14px}
@media(max-width:650px){main,.toolbar{padding:16px}.toolbar{align-items:flex-start;gap:10px}.brand{font-size:12px}.toolbar fieldset{font-size:11px;padding:3px 7px}.toolbar label{margin-right:2px}.summary{grid-template-columns:1fr;gap:14px}.card,section{padding:18px;border-radius:11px}.facts{grid-template-columns:1fr 1fr}.metrics{gap:26px}.device-head{align-items:flex-start;flex-direction:column}h2{font-size:22px}th,td{padding:10px}.table-wrap{overflow:visible}table,tbody,tr,td{display:block;width:100%}thead{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap}tbody tr{padding:8px 0;border-bottom:1px solid var(--line)}tbody tr:last-child{border-bottom:0}td,td:first-child,td:last-child{min-width:0;border:0;padding:6px 12px;display:grid;grid-template-columns:minmax(86px,.7fr) minmax(0,1.3fr);gap:10px;line-height:1.5}td:before{content:attr(data-label);color:var(--muted);font-size:12px;font-weight:600}.hero{padding-bottom:12px}nav{gap:14px}.score{font-size:58px}}
@media print{body,body:has(#light:checked),body:has(#dark:checked){color-scheme:light;--bg:#fff;--card:#fff;--ink:#000;--muted:#444;--line:#bbb;--accent:#174c50;--subtle:#f2f2f2;--warn:#624400;--fail:#8c1020;--pass:#14542c}.toolbar,nav{display:none}main{max-width:none;padding:0}.card,section{box-shadow:none;border-radius:0;padding:16px;break-inside:auto}h2,h3{break-after:avoid}.table-wrap{overflow:visible}table{display:table;font-size:11px}thead{display:table-header-group;position:static;width:auto;height:auto;clip-path:none;white-space:normal}tbody{display:table-row-group}tr,tbody tr{display:table-row}td,td:first-child,td:last-child{display:table-cell;width:auto}td:before{display:none}th,td{min-width:0!important;padding:6px}details{display:block}footer{font-size:10px}a{color:#174c50;text-decoration:none}.summary{grid-template-columns:1fr 2fr}pre{white-space:pre-wrap}}
"""


def e(value):
    return escape(str(value), quote=True)


def table(headers, rows):
    return '<div class="table-wrap" tabindex="0" role="region" aria-label="%s"><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (
        e(headers[0] + " table"), "".join('<th scope="col">' + e(h) + '</th>' for h in headers),
        "".join('<tr>' + "".join('<td data-label="' + e(label) + '">' + e(v if v is not None else 'Unobserved') + '</td>' for label, v in zip(headers, row)) + '</tr>' for row in rows))


def explanation(page, name):
    if page in ("0x02", "0x03"):
        if "uncorrected" in name.lower():
            return "Errors the drive could not correct. Historical total; compare trends before attributing a current fault."
        return "Cumulative error or recovery counter. Corrected errors alone do not prove failed media."
    return {"0x06": "Non-medium errors can involve drive or interface faults; this total does not isolate a cause.",
            "0x0c": "Sequential-access activity as reported by the drive; units remain as captured.",
            "0x0d": "Compare current and drive-reported reference temperature. Missing/255 values are unavailable.",
            "0x0e": "Lifetime cycle counts; thresholds vary by device. No universal retirement limit is applied.",
            "0x12": "TapeAlert response flags in the drive profile; these may differ from latched page 2Eh observations.",
            "0x14": "Lifetime drive activity statistics; not a failure prediction.",
            "0x17": "Volume usage/capacity from the standard SSC page; not vendor capacity page 30h/31h."}.get(page, "Decoded observation; unknown fields retain their original labels.")


def render_html(report):
    validate_report(report)
    if report.get("document_type") == "guided":
        raise ValueError("HTML requires a diagnostic report")
    health = summarize(report)  # Do not trust a saved precomputed score.
    active = sum(len((d.get("tapealert") or {}).get("active_flags", [])) for d in report['drives'])
    out = ['<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">',
           '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">',
           '<meta name="color-scheme" content="light dark"><title>tapediag · Diagnostic report</title><style>' + CSS + '</style></head><body>',
           '<div class="toolbar"><div class="brand">▤ TAPEDIAG <span class="muted">/ REPORT</span></div><fieldset><legend>Appearance</legend><label><input id="auto" type="radio" name="theme" checked> Auto</label><label><input id="light" type="radio" name="theme"> Light</label><label><input id="dark" type="radio" name="theme"> Dark</label></fieldset></div>',
           '<main><header class="hero"><div class="eyebrow">Read-only diagnostics · ' + e(report['mode']) + '</div><h1>Tape system health</h1><p class="muted">A transparent snapshot of drive signals, cartridge counters and library status.</p></header>',
           '<div class="summary"><div class="card"><span class="badge ' + health['status'] + '">' + e(health['status']) + ' · triage</span><div class="score">' + str(health['score']) + '<small> / 100</small></div><p>Observation score</p><p class="muted">Coverage: ' + e(health['coverage']) + '. A score is not a hardware-health guarantee.</p></div>',
           '<div class="card"><div class="eyebrow">Collection overview</div><div class="metrics">' + ''.join('<div class="metric"><strong>' + str(n) + '</strong><span>' + label + '</span></div>' for n,label in ((len(report['drives']),'Drives'),(len(report['libraries']),'Changers'),(active,'Active alerts'),(len(report['errors']),'Errors'))) + '</div><p class="callout">Review alerts and collection gaps before using the score to prioritize investigation. No maintenance actions are performed.</p></div></div>',
           '<nav aria-label="Report sections"><a href="#health">Score rules</a><a href="#drives">Drives</a><a href="#changers">Changers</a><a href="#errors">Collection errors</a><a href="#provenance">Provenance</a></nav>',
           '<section id="health"><h2>Why this score</h2><p class="muted">Start at 100; deduct each matching rule once across this report, with a floor of 0. Weights are toolkit policy.</p>']
    for r in health['matches']:
        out.append('<div class="rule"><strong>−' + str(r['deduction']) + ' · ' + e(r['condition']) + '</strong><p class="muted">' + e('; '.join(r['evidence'])) + '</p></div>')
    if not health['matches']:
        out.append('<p class="pass">No deduction rules matched the available observations.</p>')
    if health['gaps']:
        out.append('<h3>Coverage gaps</h3><ul>' + ''.join('<li>' + e(g) + '</li>' for g in health['gaps']) + '</ul>')
    out.append('<details><summary>All scoring rules and references</summary><ul>' + ''.join('<li>' + e(r['condition']) + ' (−' + str(r['deduction']) + ') · <a href="' + e(r['source']) + '">public reference</a></li>' for r in health['rules']) + '</ul></details></section><div id="drives">')
    for index, drive in enumerate(report['drives'], 1):
        status = drive.get('drive_status') or {}
        inquiry = drive.get('inquiry') or {}
        facts = [('Model', status.get('product')),('Firmware', status.get('revision')),('Readiness', 'Ready' if status.get('ready') is True else 'Not ready' if status.get('ready') is False else None),('Density', status.get('density_description')),('Serial', inquiry.get('serial')),('Write protection', 'On' if status.get('write_protect') is True else 'Off' if status.get('write_protect') is False else None)]
        out.append('<section><div class="device-head"><h2>Drive ' + str(index) + '</h2><code>' + e(drive['device']) + '</code></div><dl class="facts">' + ''.join('<div><dt>' + e(k) + '</dt><dd>' + e(v if v is not None else 'Unobserved') + '</dd></div>' for k,v in facts) + '</dl><h3>TapeAlert flags</h3>')
        alerts = drive.get('tapealert') or {}
        flags = alerts.get('active_flags', [])
        out.append(table(['Flag / severity', 'Signal', 'Recommended action'], [(str(f['flag']) + ' · ' + f['severity'],f['name'],f['action']) for f in flags]) if flags else '<p class="empty">No active flags observed. Observed ' + str(len(alerts.get('observed_flags', []))) + ' of 64 flags.</p>')
        out.append('<h3>Log-page counters</h3>')
        pages = (drive.get('logpages') or {}).get('pages', [])
        if not pages:
            out.append('<p class="empty">No log pages observed.</p>')
        for page in pages:
            if not page['parameters'] and not page['raw_lines']:
                continue
            out.append('<details open><summary>' + e(page['page'] + ' · ' + page['name']) + '</summary>')
            if page['page'] == '0x12':
                response = response_from_page(page) or {}
                flags12 = response.get('active_flags', [])
                out.append('<p class="muted">Drive response observations, kept separately from latched page 2Eh.</p>')
                out.append(table(['Flag / severity','Signal','Recommended action'],[(str(f['flag'])+' · '+f['severity'],f['name'],f['action']) for f in flags12]) if flags12 else '<p class="empty">No active response flags observed. Observed '+str(len(response.get('observed_flags',[])))+' of 64 flags.</p>')
                out.append('<details><summary>Decoded response text</summary><pre>'+e('\n'.join(page['raw_lines']+[p['name']+': '+p['raw'] for p in page['parameters']]))+'</pre></details></details>')
                continue
            if page['parameters']:
                out.append(table(['Counter', 'Value', 'Meaning'], [(p['name'],str(p['value']) + (' ' + p['unit'] if p['unit'] else '') if p['value'] is not None else None,explanation(page['page'],p['name'])) for p in page['parameters']]))
            if page['raw_lines']:
                out.append('<pre>' + e('\n'.join(page['raw_lines'])) + '</pre>')
            out.append('</details>')
        mam = drive.get('mam') or {}
        out.append('<h3>Cartridge memory</h3>')
        out.append(table(['Attribute', 'Value', 'Unit'], [(a['id']+' · '+a['name'],a['value'],a['unit'] or '—') for a in mam.get('attributes',[])]) if mam.get('attributes') else '<p class="empty">MAM attributes unobserved. Media may be absent or unsupported.</p>')
        if inquiry.get('identifiers'):
            out.append('<h3>Device identification</h3>' + table(['Type','Identifier'], [(a['type'],a['value']) for a in inquiry['identifiers']]))
        warnings = list(status.get('warnings',[])) + list((drive.get('logpages') or {}).get('warnings',[])) + list(alerts.get('warnings',[])) + list(mam.get('warnings',[])) + list(inquiry.get('warnings',[]))
        if warnings:
            out.append('<h3>Observation notes</h3><ul>' + ''.join('<li>'+e(w)+'</li>' for w in warnings)+'</ul>')
        out.append('</section>')
    out.append('</div><div id="changers">')
    for index, library in enumerate(report['libraries'],1):
        out.append('<section><div class="device-head"><h2>Changer ' + str(index) + '</h2><code>' + e(library['device']) + '</code></div>')
        status = library.get('status')
        if status:
            out.append(table(['Element','Occupancy','Barcode','Source slot'], [(kind+' '+str(row['element']),'Full' if row['full'] else 'Empty',row['barcode'],row['source_slot']) for kind in ('drives','slots','ie_ports') for row in status[kind]]))
            out.append('<h3>Consistency observations</h3><ul>' + ''.join('<li>' + e(c['severity'].upper() + ': ' + c['message']) + '</li>' for c in library_checks(status)) + '</ul>')
            if status['warnings']:
                out.append('<ul>' + ''.join('<li>' + e(w) + '</li>' for w in status['warnings']) + '</ul>')
        else:
            out.append('<p class="empty">Changer status unobserved.</p>')
        out.append('</section>')
    out.append('</div><section id="errors"><h2>Collection errors</h2>')
    out.append(table(['Section','Device','Error'],[(r['section'],r['device'],r['message']) for r in report['errors']]) if report['errors'] else '<p class="pass">No collection errors recorded.</p>')
    out.append('</section><footer id="provenance"><strong>tapediag ' + e(report['tool_version']) + ' · schema ' + e(report['schema_version']) + '</strong><p>' + e((report.get('provenance') or {}).get('source','Saved v1 observations')) + '. Self-contained report; no external assets, scripts, analytics or network requests.</p><p>Public format references: <a href="https://github.com/hreinecke/sg3_utils/blob/master/doc/sg_logs.8">sg3_utils</a> · <a href="https://www.t10.org/ftp/t10/document.05/05-154r2.pdf">SSC TapeAlert proposal</a> · <a href="https://github.com/mtx-org/mtx/blob/master/mtx/mtx.1">mtx status</a>. Snapshot counters alone cannot establish a present fault or a drive-to-changer association.</p><details><summary>Collection command provenance</summary><pre>' + e(json.dumps(report['commands'],indent=2)) + '</pre></details></footer></main></body></html>')
    return ''.join(out)
