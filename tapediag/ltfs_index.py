"""Bounded, offline LTFS full-index checks (SNIA 2.4/2.5); see docs/LTFS-INDEX.md."""
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile
import unicodedata
from urllib.parse import unquote
import xml.etree.ElementTree as ET
from xml.parsers import expat


U64 = 2 ** 64 - 1
TIMES = {'creationtime', 'changetime', 'modifytime', 'accesstime', 'backuptime', 'updatetime'}
REQUIRED_TIMES = {'creationtime', 'changetime', 'modifytime'}


@dataclass(frozen=True)
class Limits:
    max_bytes: int = 64 * 1024 ** 3
    max_elements: int = 500_000_000
    max_depth: int = 256
    max_attributes: int = 16
    max_token_bytes: int = 1024 * 1024
    max_text_chars: int = 1024 * 1024
    max_findings: int = 1000
    max_disk_bytes: int = 8 * 1024 ** 3


class IndexRefusal(ValueError):
    """A curated, stable code; never contains input text or local paths."""


class GuardedReader:
    """Preflight each bounded chunk before iterparse sees it.

    Expat callbacks reject declarations/structure/text limits; an event-gap cap
    bounds unfinished tokens (including comments and attributes) inside Expat.
    XML is UTF-8 only, as required by LTFS. No external entity is resolved.
    """
    def __init__(self, source, limits):
        self.source, self.limits = source, limits
        self.total = self.elements = self.depth = self.gap = self.text = 0
        self.done = False
        self.parser = expat.ParserCreate('UTF-8')
        self.parser.StartElementHandler = self.start
        self.parser.EndElementHandler = self.end
        self.parser.CharacterDataHandler = self.data
        self.parser.CommentHandler = self.token
        self.parser.ProcessingInstructionHandler = self.token
        self.parser.StartDoctypeDeclHandler = self.declaration
        self.parser.EntityDeclHandler = self.declaration
        self.parser.ExternalEntityRefHandler = self.declaration
        self.parser.XmlDeclHandler = self.xml_decl

    def event(self):
        self.gap = 0

    def token(self, *values):
        if sum(len(value.encode('utf-8')) for value in values) > self.limits.max_token_bytes:
            raise IndexRefusal('LTFS_LIMIT_TOKEN: XML token limit exceeded')
        self.event()

    def declaration(self, *args):
        raise IndexRefusal('LTFS_XML_DECLARATION: DTD/entity declarations refused')

    def xml_decl(self, version, encoding, standalone):
        if version != '1.0' or (encoding and encoding.upper() != 'UTF-8'):
            raise IndexRefusal('LTFS_XML_ENCODING: XML 1.0 UTF-8 required')
        self.event()

    def start(self, tag, attrs):
        self.event()
        self.text = 0
        self.depth += 1
        self.elements += 1
        if self.depth > self.limits.max_depth:
            raise IndexRefusal('LTFS_LIMIT_DEPTH: element nesting limit exceeded')
        if self.elements > self.limits.max_elements:
            raise IndexRefusal('LTFS_LIMIT_ELEMENTS: element count limit exceeded')
        if len(attrs) > self.limits.max_attributes:
            raise IndexRefusal('LTFS_LIMIT_ATTRIBUTES: attribute count limit exceeded')
        if len(tag.encode('utf-8')) + sum(len(k.encode('utf-8')) + len(v.encode('utf-8')) for k, v in attrs.items()) > self.limits.max_token_bytes:
            raise IndexRefusal('LTFS_LIMIT_TOKEN: XML token limit exceeded')

    def end(self, tag):
        self.event()
        self.text = 0
        self.depth -= 1

    def data(self, value):
        self.event()
        self.text += len(value)
        if self.text > self.limits.max_text_chars:
            raise IndexRefusal('LTFS_LIMIT_TEXT: text limit exceeded')

    def read(self, size=-1):
        if self.done:
            return b''
        chunk = self.source.read(min(16384, size) if size >= 0 else 16384)
        self.total += len(chunk)
        if self.total > self.limits.max_bytes:
            raise IndexRefusal('LTFS_LIMIT_BYTES: input byte limit exceeded')
        if b'\x00' in chunk:
            raise IndexRefusal('LTFS_XML_ENCODING: NUL/non-UTF-8 input refused')
        self.gap += len(chunk)
        if self.gap > self.limits.max_token_bytes + 16384:
            raise IndexRefusal('LTFS_LIMIT_TOKEN: unfinished XML token limit exceeded')
        self.parser.Parse(chunk, not chunk)
        self.done = not chunk
        return chunk


def _number(value, minimum=0):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,20}', value):
        return None
    number = int(value)
    return number if minimum <= number <= U64 else None


def _key(number):
    # SQLite's INTEGER is signed 64 bit; fixed-width decimal preserves ordering
    # over uint64 offsets and products of uint64 blocks and block sizes.
    return '%040d' % number


class Validator:
    def __init__(self, db, limits, block_size):
        self.db, self.limits, self.block_size = db, limits, block_size
        self.counts = Counter()
        self.findings = []
        self.files = self.directories = self.extents = self.serial = self.highest = 0
        self.metadata_result = {}
        db.execute('PRAGMA page_size=4096')
        db.execute('PRAGMA max_page_count=%d' % max(1, limits.max_disk_bytes // 4096))
        db.executescript('''
            PRAGMA journal_mode=OFF;
            PRAGMA synchronous=OFF;
            PRAGMA cache_size=-4096;
            PRAGMA temp_store=FILE;
            CREATE TABLE uids (uid TEXT PRIMARY KEY) WITHOUT ROWID;
            CREATE TABLE names (parent INTEGER, name TEXT, PRIMARY KEY(parent,name)) WITHOUT ROWID;
            CREATE TABLE extents (owner INTEGER, lo TEXT, hi TEXT, partition TEXT, physical_lo TEXT, physical_hi TEXT);
            CREATE INDEX logical ON extents(owner,lo);
            CREATE INDEX physical ON extents(partition,physical_lo);
        ''')

    def finding(self, code, severity='error', item=0):
        self.counts[code] += 1
        if len(self.findings) < self.limits.max_findings:
            self.findings.append({'code': code, 'severity': severity, 'entry': item})

    def integer(self, fields, name, item, minimum=0, code='LTFS_INTEGER'):
        value = _number(fields.get(name), minimum)
        if value is None:
            self.finding(code, item=item)
        return value

    def location(self, value):
        if not isinstance(value, dict):
            self.finding('LTFS_LOCATION')
            return None
        part, block = value.get('partition'), _number(value.get('startblock'))
        if not isinstance(part, str) or not re.fullmatch('[a-z]', part) or block is None:
            self.finding('LTFS_LOCATION')
            return None
        return part, block

    def extent(self, fields, owner):
        self.extents += 1
        values = [self.integer(fields, k, owner, 1 if k == 'bytecount' else 0, 'LTFS_EXTENT_VALUE')
                  for k in ('startblock', 'byteoffset', 'bytecount', 'fileoffset')]
        part = fields.get('partition', '')
        if not isinstance(part, str) or not re.fullmatch('[a-z]', part):
            self.finding('LTFS_EXTENT_PARTITION', item=owner)
            return
        if any(value is None for value in values):
            return
        block, offset, count, logical = values
        if self.block_size is not None and offset >= self.block_size:
            self.finding('LTFS_BYTEOFFSET', item=owner)
            return
        physical = block * self.block_size + offset if self.block_size is not None else 0
        self.db.execute('INSERT INTO extents VALUES (?,?,?,?,?,?)',
                        (owner, _key(logical), _key(logical + count), part,
                         _key(physical), _key(physical + count)))

    def entry(self, frame):
        fields, item, tag = frame['fields'], frame['id'], frame['tag']
        uid = self.integer(fields, 'fileuid', item, 2 if tag == 'file' else 1, 'LTFS_UID')
        if uid is not None:
            self.highest = max(self.highest, uid)
            if frame['parent_id'] == 0 and uid != 1:
                self.finding('LTFS_ROOT_UID', item=item)
            try:
                self.db.execute('INSERT INTO uids VALUES (?)', (_key(uid),))
            except sqlite3.IntegrityError:
                self.finding('LTFS_UID_DUPLICATE', item=item)
        name = fields.get('name')
        if isinstance(name, str):
            if not name or len(name) > 255 or unicodedata.normalize('NFC', name) != name:
                self.finding('LTFS_NAME', item=item)
            try:
                self.db.execute('INSERT INTO names VALUES (?,?)', (frame['parent_id'], name))
            except sqlite3.IntegrityError:
                self.finding('LTFS_NAME_DUPLICATE', item=item)
        else:
            self.finding('LTFS_NAME', item=item)
        for required in REQUIRED_TIMES | {'readonly'}:
            if required not in fields:
                self.finding('LTFS_REQUIRED', item=item)
        if tag == 'directory':
            self.directories += 1
            if 'contents' not in fields:
                self.finding('LTFS_REQUIRED', item=item)
            return
        self.files += 1
        size = self.integer(fields, 'length', item, code='LTFS_FILE_LENGTH')
        if 'symlink' in fields:
            if 'extentinfo' in fields:
                self.finding('LTFS_SYMLINK_EXTENTS', item=item)
            return
        end = 0
        sparse = False
        for lo, hi in self.db.execute('SELECT lo,hi FROM extents WHERE owner=? ORDER BY lo', (item,)):
            lo, hi = int(lo), int(hi)
            if lo < end:
                self.finding('LTFS_EXTENT_OVERLAP', item=item)
            if lo > end:
                sparse = True
            if size is not None and hi > size:
                self.finding('LTFS_EXTENT_PAST_EOF', item=item)
            end = max(end, hi)
        if size is not None and (sparse or end < size):
            self.finding('LTFS_SPARSE', 'info', item)

    def metadata(self, fields):
        for required in ('creator', 'volumeuuid', 'generationnumber', 'updatetime', 'location',
                         'allowpolicyupdate', 'highestfileuid', 'directory'):
            if required not in fields:
                self.finding('LTFS_REQUIRED')
        uuid = fields.get('volumeuuid', '')
        if not isinstance(uuid, str) or not re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', uuid):
            self.finding('LTFS_UUID')
        generation = self.integer(fields, 'generationnumber', 0, 1, 'LTFS_GENERATION')
        highest = self.integer(fields, 'highestfileuid', 0, code='LTFS_HIGHEST_UID')
        if highest not in (None, 0, self.highest):
            self.finding('LTFS_HIGHEST_UID')
        location = self.location(fields.get('location'))
        self.metadata_result = {'volumeuuid': uuid, 'generationnumber': generation, 'location': location,
                                'previousgenerationlocation': None}
        for pointer in ('previousgenerationlocation', 'previousincrementallocation'):
            if pointer in fields:
                previous = self.location(fields[pointer])
                if pointer == 'previousgenerationlocation':
                    self.metadata_result[pointer] = previous
                if previous and location and previous[0] == location[0] and previous[1] >= location[1]:
                    self.finding('LTFS_PREVIOUS_LOCATION')
        # A lone index cannot establish the referenced generation or tape layout.
        self.finding('LTFS_CHAIN_UNVERIFIED', 'info')

    def parse(self, source):
        stack = []
        for event, element in ET.iterparse(source, events=('start', 'end')):
            tag = element.tag
            if event == 'start':
                if not stack:
                    if tag != 'ltfsindex' or element.get('version') not in ('2.4.0', '2.5.0'):
                        raise IndexRefusal('LTFS_INDEX_TYPE: expected a full LTFS 2.4.0/2.5.0 index')
                parent = stack[-1]['tag'] if stack else None
                allowed_parents = {'file': {'contents'}, 'directory': {'ltfsindex', 'contents'},
                                   'contents': {'directory'}, 'extentinfo': {'file'}, 'extent': {'extentinfo'}}
                if tag in allowed_parents and parent not in allowed_parents[tag]:
                    raise IndexRefusal('LTFS_STRUCTURE: misplaced index element')
                self.serial += tag in ('file', 'directory')
                parent_id = next((f['id'] for f in reversed(stack) if f['tag'] == 'directory'), 0)
                stack.append({'tag': tag, 'element': element, 'fields': {}, 'bytes': 0, 'id': self.serial,
                              'parent_id': parent_id})
                continue
            frame = stack.pop()
            fields, item = frame['fields'], frame['id']
            value = element.text or ''
            if tag in TIMES:
                try:
                    if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{9}Z', value):
                        raise ValueError()
                    datetime.fromisoformat(value[:19])
                except ValueError:
                    self.finding('LTFS_TIMESTAMP', item=item)
            if tag in ('readonly', 'allowpolicyupdate', 'openforwrite') and value not in ('true', 'false'):
                self.finding('LTFS_BOOLEAN', item=item)
            if tag == 'name':
                encoded = element.get('percentencoded', 'false')
                if encoded not in ('true', 'false') or '/' in value or ':' in value:
                    self.finding('LTFS_NAME', item=item)
                if encoded == 'true':
                    try:
                        if re.search(r'%(?![0-9a-fA-F]{2})', value):
                            raise ValueError()
                        value = unquote(value, encoding='utf-8', errors='strict')
                    except (ValueError, UnicodeError):
                        self.finding('LTFS_NAME', item=item)
            if tag == 'extent':
                owner = next(f['id'] for f in reversed(stack) if f['tag'] == 'file')
                self.extent(fields, owner)
            elif tag in ('file', 'directory'):
                self.entry(frame)
            elif tag == 'ltfsindex':
                self.metadata(fields)
            if stack:
                parent_fields = stack[-1]['fields']
                repeated = (stack[-1]['tag'], tag) in {('contents', 'file'), ('contents', 'directory'),
                           ('extentinfo', 'extent'), ('extendedattributes', 'xattr'), ('indexpartitioncriteria', 'name')}
                if not repeated:
                    if tag in parent_fields:
                        self.finding('LTFS_ELEMENT_DUPLICATE', item=item)
                    if len(parent_fields) >= 128:
                        raise IndexRefusal('LTFS_LIMIT_CHILDREN: distinct child limit exceeded')
                    stack[-1]['bytes'] += len(value.encode('utf-8'))
                    if stack[-1]['bytes'] > self.limits.max_token_bytes:
                        raise IndexRefusal('LTFS_LIMIT_METADATA: retained metadata limit exceeded')
                    parent_fields[tag] = fields if tag in ('location', 'previousgenerationlocation', 'previousincrementallocation') else value
                stack[-1]['element'].remove(element)
            element.clear()
        if self.block_size is None:
            self.finding('LTFS_BLOCK_SIZE_UNVERIFIED', 'info')
        else:
            part, end = None, 0
            for partition, lo, hi, owner in self.db.execute('SELECT partition,physical_lo,physical_hi,owner FROM extents ORDER BY partition,physical_lo'):
                lo, hi = int(lo), int(hi)
                if partition != part:
                    part, end = partition, 0
                if lo < end:
                    self.finding('LTFS_SHARED_EXTENT', 'info', owner)
                end = max(end, hi)
        errors = sum(n for code, n in self.counts.items() if code not in
                     {'LTFS_SPARSE', 'LTFS_SHARED_EXTENT', 'LTFS_BLOCK_SIZE_UNVERIFIED', 'LTFS_CHAIN_UNVERIFIED'})
        return {'document_type': 'ltfs-index', 'schema_version': '1.0', 'valid': not errors,
                'index': self.metadata_result,
                'files': self.files, 'directories': self.directories, 'extents': self.extents,
                'errors': errors, 'finding_counts': dict(sorted(self.counts.items())),
                'findings': self.findings, 'findings_truncated': sum(self.counts.values()) > len(self.findings)}


def validate_index(path, *, block_size=None, limits=None, scratch_dir=None, previous_index=None):
    """Validate a regular UTF-8 file; disk-backed global state is always removed."""
    limits = limits or Limits()
    if any(not isinstance(value, int) or value < 1 for value in vars(limits).values()):
        raise ValueError('LTFS_LIMIT_CONFIG: limits must be positive integers')
    if block_size is not None and (not isinstance(block_size, int) or not 1 <= block_size <= U64):
        raise ValueError('LTFS_BLOCK_SIZE: block size must be a positive uint64 from the LTFS label')
    path = Path(path)
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            raise IndexRefusal('LTFS_INPUT: regular file required')
        # O_NONBLOCK avoids blocking if a regular input is replaced by a FIFO.
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise IndexRefusal('LTFS_INPUT: regular file required')
            with tempfile.TemporaryDirectory(prefix='ltfs-index-', dir=scratch_dir) as temporary:
                db = sqlite3.connect(str(Path(temporary) / 'state.sqlite'))
                try:
                    result = Validator(db, limits, block_size).parse(GuardedReader(source, limits))
                finally:
                    db.close()
    except (ET.ParseError, expat.ExpatError, UnicodeError):
        raise IndexRefusal('LTFS_XML: malformed UTF-8 XML') from None
    except sqlite3.Error:
        raise IndexRefusal('LTFS_SCRATCH: scratch database unavailable or disk limit exceeded') from None
    except OSError:
        raise IndexRefusal('LTFS_IO: local input/scratch unavailable (paths withheld)') from None
    if previous_index is not None:
        previous = validate_index(previous_index, block_size=block_size, limits=limits, scratch_dir=scratch_dir)
        current, old = result['index'], previous['index']
        codes = []
        if not previous['valid']:
            codes.append('LTFS_PREVIOUS_INVALID')
        if current['volumeuuid'].lower() != old['volumeuuid'].lower():
            codes.append('LTFS_PREVIOUS_UUID')
        if current['previousgenerationlocation'] != old['location']:
            codes.append('LTFS_PREVIOUS_TARGET')
        if (current['generationnumber'] is not None and old['generationnumber'] is not None
                and old['generationnumber'] > current['generationnumber']):
            codes.append('LTFS_PREVIOUS_GENERATION')
        for code in codes:
            result['finding_counts'][code] = result['finding_counts'].get(code, 0) + 1
            result['errors'] += 1
            if len(result['findings']) < limits.max_findings:
                result['findings'].append({'code': code, 'severity': 'error', 'entry': 0})
        result['valid'] = result['errors'] == 0
        result['findings_truncated'] = sum(result['finding_counts'].values()) > len(result['findings'])
    return result
