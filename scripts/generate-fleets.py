"""Deterministic fictional LTO-7/8/9 fleets with 48-slot libraries and history.

No observed device identifiers, sites, operator details or customer data.
All fixture values are invented; formats derive from public sources in SCORING.md.
"""
import copy
import json
from pathlib import Path

from tapediag.dashboard import render_dashboard
from tapediag.observations import parse_inquiry, parse_mam, library_checks
from tapediag.parsers import parse_drive_status, parse_library, parse_logpages
from tapediag.report import offline_report
from tapediag.tapealert import parse_tapealert
from tapediag.v2 import enrich
from tapediag.v3 import migrate, refresh

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'fixtures/fleets'
ART = ROOT/'artifacts/v3'
OUT.mkdir(exist_ok=True)
ART.mkdir(exist_ok=True)
base = enrich(offline_report(ROOT/'fixtures/scenarios/healthy'), directory=ROOT/'fixtures/scenarios/healthy')
all_reports = []
for fleet_index, fleet in enumerate(('SYNTH-ALPHA','SYNTH-BRAVO','SYNTH-CHARLIE')):
    history = []
    for day in (16,17,18):
        report = migrate(base, fleet_id=fleet, captured_at='2026-10-%02dT12:00:00Z'%day)
        report['drives'] = []
        for index,generation in enumerate((7,8,9)):
            drive = copy.deepcopy(migrate(base)['drives'][0])
            drive.update(device='/dev/sg%d'%(index+9),asset_id='SYNTH-%s-LTO%d'%(fleet.split('-')[1],generation),identity_basis='synthetic-serial')
            serial = drive['asset_id']
            drive['inquiry'] = parse_inquiry('Vendor identification: SYNTH\nProduct identification: Ultrium LTO-%d\nProduct revision level: S%03d\nSCSI_SERIAL=%s\nSCSI_IDENT_LUN_NAA=SYNTH-WWN-%s-%d\n'%(generation,generation,serial,fleet.split('-')[1],generation))
            density = {7:'0x5c',8:'0x5e',9:'0x60'}[generation]
            drive['drive_status'] = parse_drive_status('Vendor identification: SYNTH\nProduct identification: Ultrium LTO-%d\nProduct revision level: S%03d\nDensity code %s\nDevice is ready\n'%(generation,generation,density))
            degraded = fleet_index==1 and index==1
            failing = fleet_index==2 and index==2
            phase = day-16
            load_count = 240 + phase*4 + index*70
            if degraded: load_count = 9800 + phase*200
            if failing: load_count = 11000 + phase*50
            drive['mam'] = parse_mam('Load count: %d\nTotal MiB written in medium life: %d\nTotal MiB read in medium life: %d\nTotal MiB written in current/last load: 180000\nTotal MiB read in current/last load: 120000\nMedium serial number: SYNTH-MEDIUM-%s-%d\n'%(load_count,650000000 if failing else 600000+phase*180000,410000000 if failing else 300000+phase*120000,fleet.split('-')[1],generation))
            flags = [21] if degraded and phase>0 else [3,4,5,20] if failing and phase>0 else []
            drive['tapealert'] = parse_tapealert('\n'.join('Flag %d: %d'%(f,int(f in flags)) for f in range(1,65)))
            # Detailed, realistic decoded counters, not fabricated performance measurements.
            errors = phase*7 if failing else 0
            pages = '''Write error counters log page [0x02]:
  Errors corrected without substantial delay = 12
  Total uncorrected errors = %d
Read error counters log page [0x03]:
  Errors corrected without substantial delay = 24
  Total uncorrected errors = %d
Non-medium error log page [0x06]:
  Non-medium error count = %d
Sequential-access device log page [0x0c]:
  Data bytes received with WRITE commands = 180000000000
  Data bytes read with READ commands = 120000000000
  Cleaning required = %d
Temperature log page [0x0d]:
  Current temperature = %d C
  Reference temperature = 55 C
Device statistics log page [0x14]:
  Lifetime volume loads = %d
  Lifetime cleaning operations = 18
  Lifetime power on hours = 24000 hours
  Lifetime medium motion hours = %d hours
  Hours since last cleaning = %d hours
Volume statistics log page [0x17]:
  Volume lifetime loads = %d
  Total used native capacity = 900000 MiB
'''%(errors,errors*2,phase if failing else 0,int(21 in flags or 20 in flags),61 if failing and phase==2 else 34,12000+phase*3,22000 if failing else 6000,120 if degraded and phase else 18,load_count)
            drive['logpages'] = parse_logpages(pages)
            drive['tapealert_response'] = None
            if fleet_index==2 and index==0 and phase==2:
                drive['mam'] = None  # Empty drive/unsupported MAM: unknown, never healthy by omission.
            report['drives'].append(drive)
        library = copy.deepcopy(report['libraries'][0])
        library.update(device='/dev/sg20',asset_id='library:/dev/sg20',identity_basis='device-path')
        lines = ['Storage Changer /dev/sg20:3 Drives, 48 Slots (4 Import/Export)']
        for i in range(3):
            lines.append('Data Transfer Element %d:Full (Storage Element %d Loaded):VolumeTag=SYN%03dL%d'%(i,i+1,i+1,i+7))
        for i in range(1,49):
            ie = ' IMPORT/EXPORT' if i>44 else ''
            full = 4<=i<=38
            tag = 'SYN%03dL8'%i if full else ''
            if fleet_index==1 and day==18 and i==5: tag='SYN004L8' # conflicting barcode
            if fleet_index==2 and day==18 and i==10: continue # deliberate truncated audit
            lines.append('Storage Element %d%s:%s%s'%(i,ie,'Full' if full else 'Empty', ':VolumeTag='+tag if tag else ''))
        library['status'] = parse_library('\n'.join(lines))
        library['checks'] = library_checks(library['status'])
        report['libraries'] = [library]
        # Replace inherited one-drive inventory/topology, never infer physical associations.
        report['inventory']['devices'] = []
        for i,drive in enumerate(report['drives']):
            report['inventory']['devices'].append({'kind':'drive','address':'9:0:%d:0'%(i+1),'vendor':'SYNTH','model':drive['inquiry']['product'],'revision':drive['inquiry']['revision'],'device':'/dev/st%d'%i,'generic_device':drive['device'],'nonrewinding_device':'/dev/nst%d'%i})
        report['inventory']['devices'].append({'kind':'changer','address':'9:0:8:0','vendor':'SYNTH','model':'Mid-size 48-slot library','revision':'S001','device':'/dev/sch0','generic_device':'/dev/sg20','nonrewinding_device':None})
        report['topology'] = None
        report['provenance']['source'] = 'Original deterministic synthetic v3 fleet; scripts/generate-fleets.py'
        report['provenance']['references'] = ['https://www.t10.org/ftp/t10/document.05/05-213r3.pdf','https://www.t10.org/ftp/t10/document.08/08-066r0.pdf']
        report['ltfs'] = None
        report['itdt'] = None
        refresh(report)
        filename = fleet.lower()+'-202610%02d.json'%day
        (OUT/filename).write_text(json.dumps(report,indent=2)+'\n')
        all_reports.append(report)
        history.append(report)
    (ART/(fleet.lower()+'.html')).write_text(render_dashboard(history))
(ART/'fleet-dashboard.html').write_text(render_dashboard(all_reports))
(ART/'empty-dashboard.html').write_text(render_dashboard())
# The browser regression checks need an undated legacy migration too. Generate
# it here so a clean source distribution does not depend on inherited artifacts.
(ART/'first-report.html').write_text(render_dashboard([migrate(base, fleet_id='SYNTH-FIRST-REPORT')]))
print('Generated 3 synthetic fleets × 3 dated reports; 9 LTO-7/8/9 drives and 3 libraries (48 slots each).')
print('Latest fleet minima: '+', '.join('%s=%s'%(r['fleet_id'],r['health']['score']) for r in all_reports if r['captured_at'].startswith('2026-10-18')))
