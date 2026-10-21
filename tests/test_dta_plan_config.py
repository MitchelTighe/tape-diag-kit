import copy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from tapediag.dta_config import Refusal, load_config, parse_config
from tapediag.dta_engine import Engine
from tapediag.dta_plan import build_plan, plan_json, render_plan, switch_requests
from tapediag.dta_transport import Authorization


def raw_config(dta_fixtures):
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    return tomllib.loads((dta_fixtures / "config.synthetic.toml").read_text())


def test_example_plans_without_site_data():
    config = load_config(Path(__file__).resolve().parents[1] / "config.example.toml")
    plan = render_plan(config, "SYNTH-EXAMPLE")
    assert "REPLACE_DRIVE_SERIAL" in plan
    assert "REPLACE_LIBRARY.invalid" in plan
    assert "ENV%3ADTA_LIBRARY_PASSWORD" in plan


@pytest.mark.parametrize("path,value", [
    (("schema",), 2), (("schema",), True), (("drive", "serial"), "SYNTH;touch file"),
    (("drive", "serial"), "$(command)"), (("drive", "serial"), "`command`"),
    (("drive", "test_barcode"), "SYNTH\nBAD"), (("drive", "wwpns"), []),
    (("drive", "wwpns"), ["SYNTH-WWPN"]), (("drive", "wwpns"), ["00:00:00:00:00:00:00:01"] * 2),
    (("library", "url"), "http://SYNTH.invalid"), (("library", "url"), "https://SYNTH.invalid/gf/"),
    (("library", "url"), "https://SYNTH.invalid?credential=SYNTH"),
    (("library", "url"), "https://SYNTH@SYNTH.invalid"),
    (("library", "url"), "https://SYNTH.invalid:0"),
    (("library", "url"), "https://SYNTH.invalid:99999"),
    (("library", "url"), "https://SYNTH.invalid\n"),
    (("drive", "manufacturer_serial"), "SYNTH;bad"),
    (("drive", "manufacturer_serial"), "Unavailable"),
    (("drive", "serial"), "Unknown"),
    (("drive", "test_barcode"), "NO_BARCODE"),
    (("library", "username_env"), "DTA;BAD"), (("library", "password_env"), "literal lowercase"),
    (("library", "drive_offset"), True), (("library", "drive_offset"), -1),
    (("library", "home_slot"), 1000001), (("library", "partition"), "SYNTH&bad"),
    (("mover", "itdt"), "itdt"), (("mover", "itdt"), "/opt/../bad"),
    (("mover", "device"), "/dev/st0"), (("mover", "device"), "/dev/IBMtape0"),
    (("mover", "device"), "/dev/tape/by-id/SYNTH"), (("mover", "ssh"), "-oProxyCommand=SYNTH"),
    (("mover", "version"), "9.x"), (("mover", "version"), "10.0.0"),
    (("mover", "work_dir"), "/"), (("mover", "work_dir"), "/var/tmp"),
    (("mover", "work_dir"), "/var/tmp/../SYNTH"), (("mover", "work_dir"), "/var/tmp/SYNTH/"),
    (("mover", "timeout_seconds"), 59), (("mover", "timeout_seconds"), 14401),
    (("switches",), []), (("switches", 0, "ssh"), "SYNTH;bad"),
    (("switches", 0, "ports"), ["0,1"]), (("switches", 0, "ports"), ["1/1"]),
    (("switches", 0, "diagnostic_zones"), []),
    (("switches", 0, "removals"), []),
    (("switches", 0, "removals"), [{"zone": "SYNTH_PROD_A", "member": "SYNTH_A;SYNTH_B"}]),
    (("switches", 0, "removals"), [{"zone": "SYNTH_DIAG_A", "member": "SYNTH_DRIVE_A"}]),
    (("switches", 1, "fabric"), "SYNTH_FABRIC_A"),
    (("switches", 1, "ssh"), "SYNTH_SWITCH_A"),
])
def test_unsafe_config_rejected(dta_fixtures, path, value):
    data = raw_config(dta_fixtures)
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(Refusal):
        parse_config(data)


@pytest.mark.parametrize("section", [None, "drive", "library", "mover"])
def test_unknown_config_key_rejected(dta_fixtures, section):
    data = raw_config(dta_fixtures)
    target = data if section is None else data[section]
    target["password_literal"] = "SYNTH-NOT-A-CREDENTIAL"
    with pytest.raises(Refusal):
        parse_config(data)


def test_dry_run_exact_commands_and_safe_rollback_order(dta_config):
    text = render_plan(dta_config, "SYNTH-PLAN")
    assert text.index("ROLLBACK COMMANDS") < text.index("FORWARD PLAN:")
    assert text.index("Rollback for mount") < text.index("Rollback for isolate.SYNTH_A")
    assert text.index('zoneadd "SYNTH_PROD_A", "SYNTH_DRIVE_A"') < text.index('zoneremove "SYNTH_PROD_A", "SYNTH_DRIVE_A"')
    assert "sourceID=SLOT&sourceNumber=7&destinationID=DRIVE&destinationNumber=1" in text
    assert "sourceID=DRIVE&sourceNumber=1&destinationID=SLOT&destinationNumber=7" in text
    assert "inventory.xml?progress\n" in text
    assert "getMoveResult" in text and "getMoveResults" not in text
    assert "standardtest -forcedataoverwrite" in text
    assert "-LP /var/tmp/SYNTH_DTA/SYNTH-PLAN/logs -R /var/tmp/SYNTH_DTA/SYNTH-PLAN/results" in text
    assert text.count('cfgenable "SYNTH_CFG_A" -f') == 3  # rollback + isolation + restoration
    assert "BEFORE READ SSH SYNTH_MOVER :: /opt/SYNTH/itdt -version" in text
    assert "AFTER READ SSH SYNTH_SWITCH_A :: cfgshow" in text


def test_full_dry_run_engine_invokes_no_transport_or_store(dta_config):
    class ExplodingTransport:
        def execute(self, request):
            pytest.fail("dry run invoked a transport")
    lines = []
    engine = Engine(dta_config, "SYNTH-DRY", ExplodingTransport(), Authorization(dta_config), emit=lines.append)
    text = engine.dry_run()
    assert lines == [text.rstrip()]
    assert "[preflight]" in text and "[bundle]" in text
    assert len(plan_json(dta_config, "SYNTH-DRY")["steps"]) == 15


def test_plan_fingerprint_and_zoning_reversal(dta_config):
    assert dta_config.fingerprint == copy.deepcopy(dta_config).fingerprint
    assert replace(dta_config, barcode="SYNTH-OTHER").fingerprint != dta_config.fingerprint
    switch = dta_config.switches[0]
    forward, rollback = switch_requests(switch), switch_requests(switch, True)
    assert forward[0].argv == ("zoneremove", "SYNTH_PROD_A", "SYNTH_DRIVE_A")
    assert rollback[0].argv == ("zoneadd", "SYNTH_PROD_A", "SYNTH_DRIVE_A")
    assert forward[1:] == rollback[1:]
    assert forward[1].argv == ("cfgsave", "-f")
    assert forward[2].argv == ("cfgenable", "SYNTH_CFG_A", "-f")
    assert not any("erase" in r.argv for step in build_plan(dta_config, "SYNTH-X") for r in step.requests)
