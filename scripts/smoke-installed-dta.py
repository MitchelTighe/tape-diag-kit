"""Installed console-entry-point checks from outside the source checkout."""
import json
from pathlib import Path
import subprocess
import tempfile

import tapediag.dta

ROOT = Path(__file__).resolve().parents[1]
assert ROOT not in Path(tapediag.dta.__file__).resolve().parents, "DTA imported source instead of installed wheel"
checks = 0


def command(argv, expected=0, include_stderr=False):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL)
    assert result.returncode == expected, (argv, result.returncode, result.stdout[-500:], result.stderr[-500:])
    return result.stdout + result.stderr if include_stderr else result.stdout


assert "--apply" in command(["dta", "--help"])
checks += 1
for name, count in (("config.synthetic.toml", 15), ("config.owner.synthetic.toml", 17)):
    config = ROOT / "fixtures/dta" / name
    plan = json.loads(command(["dta", "--config", str(config), "--run-id", "SYNTH-INSTALLED", "--json"]))
    assert plan["mode"] == "plan" and plan["remote_requests"] == plan["hardware_writes"] == 0
    assert len(plan["steps"]) == count
    assert plan["steps"][-1]["key"] == "bundle"
    checks += 1
with tempfile.TemporaryDirectory(prefix="dta-installed-") as temporary:
    destination = Path(temporary) / "run"
    common = ["dta", "--config", str(ROOT / "fixtures/dta/config.synthetic.toml"), "--apply", "--output", str(destination)]
    assert "interactive terminal" in command(common + ["--simulate", str(ROOT / "fixtures/dta")], expected=2)
    assert not destination.exists()
    checks += 1
    assert "placeholder/synthetic" in command(common, expected=2)
    assert not destination.exists()
    checks += 1
assert "parse-only" in command(["tapediag", "itdt", "--execute"], expected=2, include_stderr=True)
checks += 1
print("Installed-wheel DTA smoke: {}/6 passed (help, both plans, terminal gate, placeholder gate, legacy ITDT refusal)".format(checks))
