"""Independent model expectations: thresholds, caps, missingness and evidence."""
import copy
import json

import pytest

from tapediag.observations import parse_mam
from tapediag.parsers import parse_logpages, parse_library
from tapediag.scoring import MODEL, RULES, finish, score_drive, score_library
from tapediag.tapealert import parse_tapealert


@pytest.fixture
def drive(fixtures):
    return copy.deepcopy(json.loads((fixtures/'fleets/synth-alpha-20261018.json').read_text())['drives'][0])


def set_param(drive, page, name, value, unit=None):
    log = next(p for p in drive['logpages']['pages'] if p['page']==page)
    param = next((p for p in log['parameters'] if p['name']==name),None)
    if param is None:
        param={'name':name};log['parameters'].append(param)
    param.update(value=value,unit=unit,raw=str(value))


def set_mam(drive, code, value, unit=None):
    row=next(a for a in drive['mam']['attributes'] if a['id']==code)
    row['value']=value
    if unit is not None: row['unit']=unit


def alerts(drive, *flags):
    drive['tapealert']=parse_tapealert('\n'.join('Flag %d: %d'%(i,i in flags) for i in range(1,65)))
    drive['tapealert_response']=None


def reason_ids(health):
    return [r['id'] for r in health['reasons']]


def test_complete_clear_drive(drive):
    health=score_drive(drive)
    assert health=={'model':MODEL,'score':100,'grade':'A','assessment':'clear','coverage':'complete','gaps':[],'reasons':[]}


@pytest.mark.parametrize('flags,expected,ids',[
    ([4],65,['alert-critical']),([1],85,['alert-warning']),([3],85,['alert-warning']),
    ([19],90,['media-life-alert']),([4,5,6],65,['alert-critical']),
    ([4,1,19],40,['alert-critical','alert-warning','media-life-alert']),
])
def test_alert_categories_deduct_once(drive,flags,expected,ids):
    alerts(drive,*flags)
    health=score_drive(drive)
    assert health['score']==expected and reason_ids(health)==ids
    assert all(r['basis']=='heuristic' and r['source'].startswith('https://') for r in health['reasons'])


def test_response_alerts_not_double_counted(drive):
    alerts(drive,20)
    response=copy.deepcopy(drive['tapealert']);response['page']='0x12'
    drive['tapealert_response']=response
    set_param(drive,'0x0c','Cleaning required',1)
    assert reason_ids(score_drive(drive))==['alert-critical']


@pytest.mark.parametrize('page,name,value,expected,rule',[
    ('0x02','Total uncorrected errors',1,75,'uncorrected-errors'),
    ('0x03','Total uncorrected errors',10000,75,'uncorrected-errors'),
    ('0x06','Non-medium error count',1,90,'non-medium-errors'),
    ('0x0c','Cleaning required',1,85,'cleaning-request'),
    ('0x14','Hours since last cleaning',99,100,None),
    ('0x14','Hours since last cleaning',100,95,'cleaning-age'),
    ('0x14','Lifetime medium motion hours',19999,100,None),
    ('0x14','Lifetime medium motion hours',20000,95,'head-hours'),
])
def test_counter_thresholds(drive,page,name,value,expected,rule):
    set_param(drive,page,name,value)
    health=score_drive(drive)
    assert health['score']==expected
    assert reason_ids(health)==([rule] if rule else [])


def test_corrected_error_is_not_uncorrected_and_read_write_deduct_once(drive):
    set_param(drive,'0x02','Errors corrected without substantial delay',99999)
    assert score_drive(drive)['score']==100
    set_param(drive,'0x02','Total uncorrected errors',2)
    set_param(drive,'0x03','Total uncorrected errors',3)
    health=score_drive(drive)
    assert health['score']==75 and len(health['reasons'][0]['evidence'])==2


@pytest.mark.parametrize('code,value,expected',[
    ('0x0003',9999,100),('0x0003',10000,90),
    ('0x0220',999579999,100),('0x0220',1000000000,95),
])
def test_mam_usage_thresholds(drive,code,value,expected):
    # Other lifetime value set to zero for an exact independent boundary.
    if code=='0x0220':set_mam(drive,'0x0221',0)
    set_mam(drive,code,value)
    assert score_drive(drive)['score']==expected


@pytest.mark.parametrize('value,unit',[(-1,None),(True,None),(None,None),('12',None),(float('nan'),None),(4,'seconds')])
def test_invalid_counter_is_gap_never_health_evidence(drive,value,unit):
    set_param(drive,'0x02','Total uncorrected errors',value,unit)
    h=score_drive(drive)
    assert h['score']==100 and h['assessment']=='unknown' and h['coverage']=='incomplete'


@pytest.mark.parametrize('value,unit',[(255,'C'),(60,'F'),(None,'C'),(-1,'C')])
def test_temperature_unavailable_or_incompatible(drive,value,unit):
    set_param(drive,'0x0d','Current temperature',value,unit)
    h=score_drive(drive)
    assert h['score']==100 and any('temperature' in g for g in h['gaps'])


def test_temperature_over_reference(drive):
    set_param(drive,'0x0d','Current temperature',56,'C')
    assert score_drive(drive)['score']==80
    set_param(drive,'0x0d','Current temperature',55,'C')
    assert score_drive(drive)['score']==100


@pytest.mark.parametrize('field',['tapealert','logpages','mam'])
def test_missing_observation_never_clear(drive,field):
    drive[field]=None
    h=score_drive(drive)
    assert h['score']==100 and h['coverage']=='incomplete' and h['assessment']=='unknown'


def test_duplicate_counter_or_mam_is_not_assumed_authoritative(drive):
    page=next(p for p in drive['logpages']['pages'] if p['page']=='0x02')
    page['parameters'].append(copy.deepcopy(page['parameters'][-1]))
    drive['mam']['attributes'].append(copy.deepcopy(drive['mam']['attributes'][0]))
    h=score_drive(drive)
    assert len(h['gaps'])==2 and h['assessment']=='unknown'


def test_mam_unit_mismatch_and_partial_data_gaps(drive):
    set_mam(drive,'0x0220',1000000000,'GB')
    set_mam(drive,'0x0003',10000,'hours')
    h=score_drive(drive)
    assert h['score']==100 and len(h['gaps'])==2


def test_subpage_is_not_main_page(drive):
    for page in drive['logpages']['pages']:page['subpage']='0x01'
    assert score_drive(drive)['assessment']=='unknown'


def test_cleaning_raw_decoded_lines(drive):
    page=next(p for p in drive['logpages']['pages'] if p['page']=='0x0c')
    page['parameters']=[];page['raw_lines']=['Cleaning action required']
    assert 'cleaning-request' in reason_ids(score_drive(drive))
    page['raw_lines']=['Cleaning action not required (or completed)']
    assert score_drive(drive)['coverage']=='complete'


def test_collection_errors_scoped_per_asset(drive):
    errors=[{'section':'capture','device':'/dev/sg99','message':'synthetic unavailable'}]
    assert score_drive(drive,errors)['score']==100
    errors[0]['device']=None
    assert score_drive(drive,errors)['score']==90


@pytest.mark.parametrize('score,grade',[(100,'A'),(90,'A'),(89,'B'),(75,'B'),(74,'C'),(60,'C'),(59,'D'),(40,'D'),(39,'F'),(0,'F')])
def test_grade_boundaries(score,grade,monkeypatch):
    monkeypatch.setattr('tapediag.scoring.RULES',[{'id':'synthetic','deduction':100-score}])
    assert finish({'synthetic':['synthetic']},[])['grade']==grade


def test_score_floors_at_zero(drive):
    alerts(drive,4,1,19)
    set_param(drive,'0x02','Total uncorrected errors',1)
    set_param(drive,'0x06','Non-medium error count',1)
    set_param(drive,'0x0d','Current temperature',60,'C')
    set_mam(drive,'0x0003',10000)
    assert score_drive(drive)['score']==0


@pytest.mark.parametrize('text,score,rules',[
    ('Storage Changer /dev/sg20:1 Drives, 1 Slots\nData Transfer Element 0:Full (Storage Element 1 Loaded):VolumeTag=SYN001L8\nStorage Element 1:Empty',100,[]),
    ('Storage Changer /dev/sg20:0 Drives, 2 Slots\nStorage Element 1:Full:VolumeTag=SYN001L8\nStorage Element 2:Full:VolumeTag=SYN001L8',80,['library-consistency']),
    ('Storage Changer /dev/sg20:1 Drives, 2 Slots\nData Transfer Element 0:Empty',85,['library-coverage']),
])
def test_library_rules_and_normal_empty_source(text,score,rules):
    h=score_library({'device':'/dev/sg20','status':parse_library(text)})
    assert h['score']==score and reason_ids(h)==rules
    assert h['coverage']=='incomplete' # door/sensor/exception limitations always visible


def test_missing_library_and_scoped_errors():
    h=score_library({'device':'/dev/sg20','status':None},[{'device':'/dev/sg20'}])
    assert h['score']==75 and reason_ids(h)==['library-coverage','collection-errors']


def test_rule_ids_and_documentation_are_complete(fixtures):
    assert len({r['id'] for r in RULES})==len(RULES)
    docs=(fixtures.parent/'docs/SCORING.md').read_text()
    for r in RULES:
        assert r['id'] in docs and r['source'] in docs
        assert r['accessed']=='2026-10-18' and r['basis']=='heuristic'


def test_public_sg_logs_labels_and_no_page_header(drive):
    drive['logpages']['pages']=[p for p in drive['logpages']['pages'] if p['page'] not in ('0x14','0x0c')]
    from tapediag.parsers import parse_logpages
    drive['logpages']['pages'].extend(parse_logpages('Device statistics (ssc-3 and adc)\n  Lifetime media motion (head) hours: 22000\n  Media motion (head) hours since last successful cleaning operation: 100\n','0x14')['pages'])
    drive['logpages']['pages'].extend(parse_logpages('Sequential access device page (ssc-3)\n  Cleaning action required (or in progress)\n','0x0c')['pages'])
    h=score_drive(drive)
    assert h['score']==75 and h['coverage']=='complete'
    assert reason_ids(h)==['cleaning-request','cleaning-age','head-hours']


def test_large_integer_counter_does_not_overflow_float_conversion(drive):
    set_param(drive,'0x02','Total uncorrected errors',10**400)
    assert score_drive(drive)['score']==75
