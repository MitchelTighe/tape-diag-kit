"""Offline CycloneDX 1.6 inventory of the wheel and its build container.

Runtime dependencies come from wheel METADATA, build Python packages from
importlib.metadata, and OS packages from dpkg-query. No upload or CVE scan.
"""
import argparse
from email.parser import BytesParser
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import re
import subprocess
import uuid
import zipfile

from release_metadata import optional_runtime


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(dist, image):
    if re.fullmatch(r'[0-9a-f]{64}', image):
        image = 'sha256:' + image
    if not re.fullmatch(r'(?:[a-z0-9./:_-]+@)?sha256:[0-9a-f]{64}', image):
        raise ValueError('BUILD_IMAGE must be an immutable sha256 image ID or digest')
    wheels = list(dist.glob('*.whl'))
    if len(wheels) != 1:
        raise ValueError('expected exactly one wheel')
    wheel = wheels[0]
    with zipfile.ZipFile(wheel) as archive:
        names = [n for n in archive.namelist() if n.endswith('.dist-info/METADATA')]
        if len(names) != 1:
            raise ValueError('expected one wheel METADATA')
        metadata = BytesParser().parsebytes(archive.read(names[0]))
    optional = optional_runtime(metadata)
    component = {'type': 'application', 'bom-ref': 'pkg:pypi/tapediag@' + metadata['Version'],
                 'name': metadata['Name'], 'version': metadata['Version'], 'scope': 'required',
                 'purl': 'pkg:pypi/tapediag@' + metadata['Version'],
                 'licenses': [{'license': {'id': metadata['License-Expression']}}],
                 'hashes': [{'alg': 'SHA-256', 'content': digest(wheel)}]}
    components = []
    optional_refs = []
    for package in optional:
        ref = 'pkg:pypi/%s@%s' % (package['name'], package['version'])
        optional_refs.append(ref)
        components.append({'type': 'library', 'bom-ref': ref, 'purl': ref,
                           'name': package['name'], 'version': package['version'], 'scope': 'optional',
                           'properties': [{'name': 'tapediag:extra', 'value': package['extra']},
                                          {'name': 'tapediag:pep508-marker', 'value': package['marker']}]})
    for package in importlib.metadata.distributions():
        name = re.sub(r'[-_.]+', '-', package.metadata['Name']).lower()
        # Installed project is represented by the hashed wheel above.
        if name == 'tapediag':
            continue
        components.append({'type': 'library', 'bom-ref': 'build-python:' + name,
                           'name': name, 'version': package.version, 'scope': 'excluded',
                           'purl': 'pkg:pypi/%s@%s' % (name, package.version),
                           'properties': [{'name': 'tapediag:role', 'value': 'build-environment'}]})
    rows = subprocess.run(['dpkg-query', '-W', '-f=${Package}\t${Version}\t${Architecture}\n'],
                          check=True, capture_output=True, text=True).stdout.splitlines()
    for row in rows:
        name, version, architecture = row.split('\t')
        components.append({'type': 'library', 'bom-ref': 'build-os:' + name,
                           'name': name, 'version': version, 'scope': 'excluded',
                           'properties': [{'name': 'tapediag:role', 'value': 'container-os'},
                                          {'name': 'tapediag:architecture', 'value': architecture}]})
    components.append({'type': 'container', 'bom-ref': image, 'name': 'tapediag-build-container',
                       'version': image, 'scope': 'excluded'})
    components.append({'type': 'platform', 'bom-ref': 'build-interpreter', 'name': 'CPython',
                       'version': platform.python_version(), 'scope': 'excluded'})
    artifacts = {p.name: digest(p) for p in sorted(dist.iterdir())
                 if p.name.endswith(('.whl', '.tar.gz'))}
    identity = json.dumps({'artifacts': artifacts, 'image': image}, sort_keys=True)
    return {'bomFormat': 'CycloneDX', 'specVersion': '1.6', 'version': 1,
            'serialNumber': 'urn:uuid:' + str(uuid.uuid5(uuid.NAMESPACE_URL, identity)),
            'metadata': {'component': component,
                         'tools': {'components': [{'type': 'application', 'name': 'tapediag-offline-sbom', 'version': '1.0.0'}]},
                         'properties': [{'name': 'tapediag:inventory-scope', 'value': 'Wheel runtime plus separate build-container inventory; not a vulnerability scan'},
                                        {'name': 'tapediag:artifact-sha256', 'value': json.dumps(artifacts, sort_keys=True)}]},
            'components': sorted(components, key=lambda x: x['bom-ref']),
            'dependencies': [{'ref': component['bom-ref'], 'dependsOn': optional_refs}] +
                            [{'ref': ref, 'dependsOn': []} for ref in optional_refs]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist', type=Path, required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = inventory(args.dist, args.image)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print('SBOM: %d components; 0 base runtime dependencies; %d conditional optional dependencies' %
          (len(result['components']), sum(c['scope'] == 'optional' for c in result['components'])))


if __name__ == '__main__':
    main()
