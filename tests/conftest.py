import importlib.util
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture
def fixtures():
    return FIXTURES


@pytest.fixture
def sample(fixtures):
    def read(name):
        return (fixtures / "synthetic" / name).read_text()
    return read


@pytest.fixture
def report(fixtures):
    from tapediag.report import offline_report
    return offline_report(fixtures / "sample-host")


@pytest.fixture
def draft_release(tmp_path):
    """Readiness cases use a synthetic copy with injected placeholder markers."""
    root = FIXTURES.parent
    spec = importlib.util.spec_from_file_location('draft_source_selector', root / 'scripts/release_source.py')
    selector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(selector)
    draft = tmp_path / 'synthetic-release'
    for path in selector.source_files(root):
        target = draft / path.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
    # Deliberately keep only synthetic draft markers in the copied test state.
    for name, marker in [('README.md', '<OWNER_NAME>'), ('LICENSE', '<OWNER_NAME>'),
                         ('SECURITY.md', '<SECURITY_CONTACT>'),
                         ('CONTRIBUTING.md', '<VULNERABILITY_REPORT_ADDRESS>')]:
        path = draft / name
        path.write_text(path.read_text() + '\n' + marker + '\n')
    project = draft / 'pyproject.toml'
    project.write_text(project.read_text() + '\n# <OWNER_NAME>\n')
    return draft


@pytest.fixture
def dta_fixtures(fixtures):
    return fixtures / "dta"


@pytest.fixture
def dta_config(dta_fixtures):
    from tapediag.dta_config import load_config
    return load_config(dta_fixtures / "config.synthetic.toml")


@pytest.fixture
def dta_owner_config(dta_config):
    from dataclasses import replace
    owner = {"ssh": "SYNTH_OWNER", "drive": "SYNTH_OWNER_DRIVE", "device": "SYNTH_OWNER_DEVICE"}
    for action, key in (("lock", "lock_argv"), ("unlock", "unlock_argv"), ("probe", "verify_argv")):
        owner[key] = ["/opt/SYNTH/owner-adapter", action, "{drive}", "{device}", "{serial}", "{manufacturer_serial}", "{run_id}"]
    return replace(dta_config, owner=owner)
