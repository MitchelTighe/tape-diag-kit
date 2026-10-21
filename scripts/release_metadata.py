"""Validate the release's one pinned optional dependency from wheel metadata."""
from packaging.requirements import Requirement


DTA_REQUIREMENT = 'tomli==2.3.0; python_version < "3.11" and extra == "dta"'


def optional_runtime(metadata):
    """Reject unreviewed dependency changes rather than misstate the SBOM."""
    rows = metadata.get_all('Requires-Dist', [])
    if not rows:
        if metadata.get_all('Provides-Extra', []):
            raise ValueError('unexpected runtime dependencies: extra without dependency')
        return []
    if len(rows) != 1 or metadata.get_all('Provides-Extra', []) != ['dta']:
        raise ValueError('unexpected runtime dependencies: expected only the dta extra')
    requirement = Requirement(rows[0])
    expected = Requirement(DTA_REQUIREMENT)
    if (requirement.name, str(requirement.specifier), requirement.extras, requirement.url) != (
            expected.name, str(expected.specifier), expected.extras, expected.url):
        raise ValueError('unexpected runtime dependencies: unreviewed optional package')
    # Both AND orderings express the backend's supported conditional extra.
    markers = {'python_version < "3.11" and extra == "dta"',
               'extra == "dta" and python_version < "3.11"'}
    if str(requirement.marker) not in markers:
        raise ValueError('unexpected runtime dependencies: optional marker changed')
    return [{'name': 'tomli', 'version': '2.3.0', 'extra': 'dta',
             'marker': str(expected.marker), 'scope': 'optional'}]
