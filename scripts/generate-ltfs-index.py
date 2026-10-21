#!/usr/bin/env python3
"""Generate original synthetic LTFS 2.4/2.5 full indexes; no tape access."""
import argparse
from pathlib import Path
from xml.sax.saxutils import escape


STAMP = '2026-01-02T03:04:05.000000000Z'
UUID = '00000000-0000-4000-8000-000000000132'
CASES = ('minimal', 'overlap', 'shared', 'sparse', 'bad-extents', 'duplicate-names', 'deep', 'huge')


def metadata(uid, name):
    return ('<fileuid>%d</fileuid><name>%s</name><readonly>false</readonly>' % (uid, escape(name))
            + ''.join('<%s>%s</%s>' % (tag, STAMP, tag) for tag in
                      ('creationtime', 'changetime', 'modifytime', 'accesstime', 'backuptime')))


def extent(offset=0, count=8, block=10, byteoffset=0, partition='b'):
    return ('<extent><partition>%s</partition><startblock>%d</startblock>'
            '<byteoffset>%d</byteoffset><bytecount>%d</bytecount><fileoffset>%d</fileoffset></extent>'
            % (partition, block, byteoffset, count, offset))


def file_xml(uid, name, length=8, extents=None, extra=''):
    return ('<file>' + metadata(uid, name) + '<length>%d</length>' % length
            + ('<extentinfo>' + extents + '</extentinfo>' if extents is not None else '')
            + extra + '</file>')


def generate(destination, case='minimal', files=2_000_000, depth=140):
    """Write incrementally, including the huge case; no list of files in memory."""
    highest = files + 1 if case == 'huge' else depth + 1 if case == 'deep' else 3 if case in ('shared', 'duplicate-names') else 2
    with Path(destination).open('w', encoding='utf-8') as out:
        out.write('<?xml version="1.0" encoding="UTF-8"?><ltfsindex version="2.5.0">'
                  '<creator>tapediag synthetic fixture generator</creator><volumeuuid>' + UUID
                  + '</volumeuuid><generationnumber>1</generationnumber><updatetime>' + STAMP
                  + '</updatetime><location><partition>b</partition><startblock>100</startblock></location>'
                  '<allowpolicyupdate>false</allowpolicyupdate><highestfileuid>%d</highestfileuid>' % highest
                  + '<directory>' + metadata(1, 'SYNTHETIC') + '<contents>')
        if case == 'huge':
            for i in range(files):
                # >2 GB at two million files; exercises extents and bounded metadata.
                out.write(file_xml(i + 2, 'synthetic-%09d' % i, extents=extent(block=i + 101),
                                   extra='<extendedattributes><xattr><key>synthetic.padding</key><value>'
                                   + 'x' * 512 + '</value></xattr></extendedattributes>'))
        elif case == 'deep':
            for i in range(depth):
                out.write('<directory>' + metadata(i + 2, 'level-%d' % i) + '<contents>')
            out.write('</contents></directory>' * depth)
        elif case == 'overlap':
            out.write(file_xml(2, 'overlap', 16, extent() + extent(offset=4, block=20)))
        elif case == 'shared':
            out.write(file_xml(2, 'one', extents=extent()))
            out.write(file_xml(3, 'two', extents=extent()))
        elif case == 'sparse':
            out.write(file_xml(2, 'sparse', 32, extent(offset=8) + extent(offset=24, block=20)))
        elif case == 'bad-extents':
            out.write(file_xml(2, 'bad', 8, extent(count=0) + extent(offset=-1) + extent(offset=8)))
        elif case == 'duplicate-names':
            out.write(file_xml(2, 'duplicate', 0))
            out.write(file_xml(3, 'duplicate', 0))
        else:
            out.write(file_xml(2, 'empty', 0))
        out.write('</contents></directory></ltfsindex>')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--case', choices=CASES, default='minimal')
    parser.add_argument('--files', type=int, default=2_000_000)
    parser.add_argument('--depth', type=int, default=140)
    args = parser.parse_args()
    if args.files < 1 or args.depth < 1:
        parser.error('files and depth must be positive')
    generate(args.output, args.case, args.files, args.depth)
