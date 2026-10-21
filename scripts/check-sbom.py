"""Validate CycloneDX 1.6 using local upstream schemas, with no network resolver."""
import argparse
import json
from pathlib import Path

from jsonschema import Draft7Validator
from referencing import Registry, Resource

from release_metadata import DTA_REQUIREMENT


def validate_inventory(value):
    """Check reviewed optional dependency edges separately from build inventory."""
    optional = [c for c in value['components'] if c['scope'] == 'optional']
    assert len(optional) <= 1, 'unexpected optional dependencies'
    for component in optional:
        assert (component['name'], component['version'], component['bom-ref'], component['purl']) == (
            'tomli', '2.3.0', 'pkg:pypi/tomli@2.3.0', 'pkg:pypi/tomli@2.3.0'), 'optional package identity'
        assert component['properties'] == [
            {'name': 'tapediag:extra', 'value': 'dta'},
            {'name': 'tapediag:pep508-marker', 'value': DTA_REQUIREMENT.split('; ', 1)[1]}], 'optional dependency condition'
    assert all(c['scope'] in {'optional', 'excluded'} for c in value['components']), 'unexpected required runtime component'
    refs = [c['bom-ref'] for c in optional]
    assert value['dependencies'] == [
        {'ref': value['metadata']['component']['bom-ref'], 'dependsOn': refs}
    ] + [{'ref': ref, 'dependsOn': []} for ref in refs], 'runtime dependency graph'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--schema-dir', type=Path, required=True)
    parser.add_argument('sbom', type=Path)
    args = parser.parse_args()
    registry = Registry()
    for path in sorted(args.schema_dir.glob('*.schema.json')):
        content = json.loads(path.read_text())
        resource = Resource.from_contents(content)
        registry = registry.with_resource(content['$id'], resource)
    schema = json.loads((args.schema_dir / 'bom-1.6.schema.json').read_text())
    Draft7Validator.check_schema(schema)
    value = json.loads(args.sbom.read_text())
    Draft7Validator(schema, registry=registry).validate(value)
    assert value['bomFormat'] == 'CycloneDX' and value['specVersion'] == '1.6'
    validate_inventory(value)
    print('CycloneDX 1.6 upstream schema and runtime/build separation: PASS (%d components)' % len(value['components']))


if __name__ == '__main__':
    main()
