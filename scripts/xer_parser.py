#!/usr/bin/env python3
"""
XER Parser & Generator — Canonical Primavera P6 XER Engine
==========================================================
Single source of truth for all XER file operations across all skills.

Usage:
    PARSING:
        from xer_parser import parse_xer, print_summary
        data = parse_xer('/path/to/file.xer')
        print_summary(data)

    GENERATION:
        from xer_parser import generate_xer
        generate_xer(data, '/path/to/output.xer')

    CLI:
        python xer_parser.py parse input.xer [--summary] [--json output.json]
        python xer_parser.py generate input.json output.xer
"""

import sys
import json
import os
import re
from datetime import datetime, timedelta
from collections import defaultdict, OrderedDict

# ─────────────────────────────────────────────
# SKILL VERSION
# ─────────────────────────────────────────────
# v2.0.0 — nuclear-grade upgrade (VP teardown §1):
#   * BOM-aware encoding detection (UTF-8 BOM / UTF-16 LE-BE BOM)
#   * Schedule integrity manifest (generate_xer_manifest)
#   * Baseline identification (get_baselines / contract_baseline_id)
#   * UDF type classification (get_udf_types)
#   * Schema drift detection (schema_diff)
#   * Calendar exception classification (special_workdays vs holidays)
#   * Unified validation report (validate_schedule)
#   * AACE 31R-03 compliance scoring (aace_31r_compliance)
_SKILL_VERSION = '2.0.0'

# ─────────────────────────────────────────────
# CPP COMMON MODULE IMPORT STANZA
# ─────────────────────────────────────────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_CPP_COMMON = os.path.normpath(os.path.join(_SCRIPT_DIR, '..', '..', '_cpp_common', 'scripts'))
if os.path.isdir(_CPP_COMMON) and _CPP_COMMON not in sys.path:
    sys.path.insert(0, _CPP_COMMON)

# Imports from _cpp_common are guarded so xer_parser stays useful in
# callers that don't have the common module available (e.g. embedded packaging).
try:
    from audit_trail import generate_manifest, render_manifest_block  # noqa: F401
    from validation import Finding, ValidationReport, BLOCK, WARN, INFO, PASS
    from config_profiles import get_profile
    _CPP_COMMON_AVAILABLE = True
except ImportError:
    _CPP_COMMON_AVAILABLE = False
    # Stub placeholders so the names are bound — callers who need the real ones
    # should ensure _cpp_common is on sys.path.
    generate_manifest = None
    render_manifest_block = None
    Finding = None
    ValidationReport = None
    BLOCK = 'BLOCK'
    WARN = 'WARN'
    INFO = 'INFO'
    PASS = 'PASS'
    get_profile = None

# ─────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────
__all__ = [
    # Version
    '_SKILL_VERSION',
    # Parsing
    'parse_xer', 'get_table', 'get_fields',
    # Calendar
    'parse_calendar_data', 'get_calendar_map',
    'get_work_days_between', 'duration_hours_to_days',
    # Cross-reference
    'build_wbs_map', 'build_resource_map',
    'build_predecessor_map', 'build_activity_code_map', 'build_udf_map',
    # Summary
    'generate_summary', 'print_summary',
    # V2.0 additions
    'generate_xer_manifest', 'get_baselines', 'contract_baseline_id',
    'get_udf_types', 'schema_diff', 'validate_schedule', 'aace_31r_compliance',
    # Generation
    'generate_xer',
    # MIP 3.4 half-step
    'compute_half_step_xer',
    # Constants
    'TABLE_ORDER', 'TABLE_FIELD_COUNTS', 'TABLE_FIELD_COUNTS_BY_VERSION',
    'P6_DATE_FORMAT', 'STATUS_CODES', 'NOT_STARTED_STATUS', 'ACTIVE_STATUS',
    'COMPLETE_STATUS', 'TASK_TYPES', 'MILESTONE_TASK_TYPES', 'EXCLUDED_TASK_TYPES',
    'RELATIONSHIP_TYPES', 'CONSTRAINT_TYPES',
    # Severity re-exports from _cpp_common
    'BLOCK', 'WARN', 'INFO', 'PASS',
]

# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────

# P6 24.12 canonical table order for XER generation
TABLE_ORDER = [
    'CURRTYPE', 'FINTMPL', 'OBS', 'PROJECT', 'CALENDAR',
    'SCHEDOPTIONS', 'PROJWBS', 'TASK', 'TASKPRED', 'TASKRSRC',
    'RSRC', 'RSRCRATE', 'ACTVTYPE', 'ACTVCODE', 'TASKACTV',
    'UDFTYPE', 'UDFVALUE', 'PROJPCAT', 'PCATTYPE', 'PCATVAL',
    'TASKFIN', 'TRSRCFIN', 'TASKDOC', 'PROJDOCS', 'ROLERATE',
    'ROLES', 'RSRCROLE', 'SHIFT', 'SHIFTPER', 'ACCOUNT',
    'RCATTYPE', 'RCATVAL', 'RSRCCAT', 'MEMOTYPE', 'TASKMEMO',
    'WBSMEMO', 'PROJMEMO', 'RISKTYPE', 'RISK', 'RISKTYPES'
]

# Known field counts per table, keyed by P6 schema family.
# Observed from real exports — P6 added/removed fields across major versions,
# so validation must be version-aware or warnings fire on every valid XER.
#
# TODO(schema-truth): the values below (e.g. PROJECT=71, TASK=61 for the 22/23/24
# family) disagree with SKILL.md §Field-counts which currently states 72 / 62.
# We need a fresh canonical P6 24.12 export to verify which side is correct
# before changing either; both have plausible historical lineage and guessing
# would silently break field-count validation for every consumer. Until then,
# leave this constant intact and remember the SKILL.md numbers may need to be
# fixed there (NOT here).
TABLE_FIELD_COUNTS_BY_VERSION = {
    # P6 22.x / 23.x / 24.x share the same schema for these core tables
    '24': {'PROJECT': 71, 'SCHEDOPTIONS': 25, 'PROJWBS': 26, 'TASK': 61, 'TASKPRED': 11},
    '23': {'PROJECT': 71, 'SCHEDOPTIONS': 25, 'PROJWBS': 26, 'TASK': 61, 'TASKPRED': 11},
    '22': {'PROJECT': 71, 'SCHEDOPTIONS': 25, 'PROJWBS': 26, 'TASK': 61, 'TASKPRED': 11},
    # P6 19.x / 20.x have a different schema (more fields on some tables,
    # fewer on TASKPRED, no SCHEDOPTIONS in some variants).
    '20': {'PROJECT': 82, 'TASK': 66, 'TASKPRED': 10},
    '19': {'PROJECT': 82, 'TASK': 66, 'TASKPRED': 10},
}

# Back-compat alias — points at the current/default schema family so older
# callers that reference TABLE_FIELD_COUNTS directly keep working.
TABLE_FIELD_COUNTS = TABLE_FIELD_COUNTS_BY_VERSION['24']

# P6 date format
P6_DATE_FORMAT = '%Y-%m-%d %H:%M'

# Status code mappings
STATUS_CODES = {
    'TK_NotStart': 'Not Started',
    'TK_Active': 'In Progress',
    'TK_Complete': 'Complete',
}

# Scalar status codes (for downstream skills — avoids redefining these everywhere).
NOT_STARTED_STATUS = 'TK_NotStart'
ACTIVE_STATUS = 'TK_Active'
COMPLETE_STATUS = 'TK_Complete'

# Task type mappings
TASK_TYPES = {
    'TT_Task': 'Task Dependent',
    'TT_Rsrc': 'Resource Dependent',
    'TT_Mile': 'Start Milestone',
    'TT_FinMile': 'Finish Milestone',
    'TT_LOE': 'Level of Effort',
    'TT_WBS': 'WBS Summary',
}

# Commonly-needed task_type SETS — exported to eliminate drift across skills.
# Use these instead of redefining `{'TT_Mile', 'TT_FinMile'}` locally.
MILESTONE_TASK_TYPES = frozenset({'TT_Mile', 'TT_FinMile'})
EXCLUDED_TASK_TYPES = frozenset({'TT_WBS', 'TT_LOE'})  # Excluded from CP / duration analyses

# Relationship type mappings
RELATIONSHIP_TYPES = {
    'PR_FS': 'Finish-to-Start',
    'PR_FF': 'Finish-to-Finish',
    'PR_SS': 'Start-to-Start',
    'PR_SF': 'Start-to-Finish',
}

# Constraint type mappings (P6 24.12 canonical codes)
CONSTRAINT_TYPES = {
    'CS_MSO': 'Start On',
    'CS_MEO': 'Finish On',
    'CS_MSOA': 'Start On or After',
    'CS_MSOB': 'Start On or Before',
    'CS_MEOA': 'Finish On or After',
    'CS_MEOB': 'Finish On or Before',
    'CS_ALAP': 'As Late As Possible',
    'CS_MANDSTART': 'Mandatory Start',
    'CS_MANDFIN': 'Mandatory Finish',
}


# ─────────────────────────────────────────────
# PARSING ENGINE
# ─────────────────────────────────────────────

def _detect_bom_encoding(filepath):
    """Inspect the first 4 bytes and return an encoding string if a BOM is present.

    Returns one of: 'utf-8-sig', 'utf-16', 'utf-16-le', 'utf-16-be', 'utf-32',
    or None if no BOM is detected. Python's 'utf-8-sig' and 'utf-16' codecs
    strip the BOM automatically when decoding.
    """
    try:
        with open(filepath, 'rb') as f:
            head = f.read(4)
    except OSError:
        return None
    if head.startswith(b'\xef\xbb\xbf'):
        return 'utf-8-sig'
    if head.startswith(b'\xff\xfe\x00\x00'):
        return 'utf-32-le'
    if head.startswith(b'\x00\x00\xfe\xff'):
        return 'utf-32-be'
    if head.startswith(b'\xff\xfe'):
        return 'utf-16-le'
    if head.startswith(b'\xfe\xff'):
        return 'utf-16-be'
    return None


def parse_xer(filepath, encoding=None):
    """
    Parse a Primavera P6 XER file into a structured dictionary.

    Returns:
        {
            'ermhdr': { ... header metadata ... },
            'tables': {
                'TABLE_NAME': {
                    'fields': ['field1', 'field2', ...],
                    'records': [ {field1: val1, field2: val2, ...}, ... ]
                },
                ...
            },
            'filepath': str,
            'parse_timestamp': str,
            'encoding_used': str  # e.g. 'utf-8', 'utf-8-sig', 'utf-16-le', 'cp1252'
        }
    """
    # BOM detection takes priority over the fallback list — a correctly
    # BOM-tagged file should decode first-attempt and never fall through to
    # latin-1 (which never fails but produces garbled Unicode).
    bom_encoding = _detect_bom_encoding(filepath)

    if encoding:
        encodings_to_try = [encoding]
    else:
        encodings_to_try = []
        if bom_encoding:
            encodings_to_try.append(bom_encoding)
        encodings_to_try.extend(['utf-8', 'cp1252', 'utf-16', 'latin-1'])

    raw_text = None
    encoding_used = None

    for enc in encodings_to_try:
        if enc is None:
            continue
        try:
            with open(filepath, encoding=enc) as f:
                raw_text = f.read()
            encoding_used = enc
            break
        except (UnicodeDecodeError, LookupError):
            continue

    if raw_text is None:
        raise ValueError(f"Could not decode {filepath} with any encoding: {encodings_to_try}")

    # Defensive strip — if a BOM somehow survived (e.g. caller passed a plain
    # 'utf-16' codec that leaves the BOM character), drop the leading U+FEFF.
    if raw_text and raw_text[0] == '\ufeff':
        raw_text = raw_text[1:]

    lines = raw_text.replace('\r\n', '\n').replace('\r', '\n').split('\n')

    result = {
        'ermhdr': {},
        'tables': OrderedDict(),
        'filepath': os.path.abspath(filepath),
        'filename': os.path.basename(filepath),
        'parse_timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'encoding_used': encoding_used or '',
    }

    current_table = None
    current_fields = []

    for line in lines:
        line = line.rstrip('\n').rstrip('\r')

        if not line.strip():
            continue

        # ERMHDR — file header
        if line.startswith('ERMHDR'):
            parts = line.split('\t')
            result['ermhdr'] = {
                'raw': parts,
                'version': parts[1] if len(parts) > 1 else '',
                'export_date': parts[2] if len(parts) > 2 else '',
                'user': parts[3] if len(parts) > 3 else '',
                'database': parts[4] if len(parts) > 4 else '',
                'currency': parts[5] if len(parts) > 5 else '',
            }
            continue

        # %T — Table name marker
        if line.startswith('%T'):
            parts = line.split('\t')
            current_table = parts[1].strip() if len(parts) > 1 else None
            current_fields = []
            if current_table and current_table not in result['tables']:
                result['tables'][current_table] = {
                    'fields': [],
                    'records': []
                }
            continue

        # %F — Field names
        if line.startswith('%F'):
            parts = line.split('\t')
            current_fields = [f.strip() for f in parts[1:]]
            if current_table:
                result['tables'][current_table]['fields'] = current_fields
            continue

        # %R — Data row
        if line.startswith('%R'):
            if not current_table or not current_fields:
                continue
            parts = line.split('\t')
            values = parts[1:]  # Skip the %R marker

            # Pad values if fewer than fields (empty trailing fields)
            while len(values) < len(current_fields):
                values.append('')

            record = {}
            for i, field in enumerate(current_fields):
                record[field] = values[i] if i < len(values) else ''

            result['tables'][current_table]['records'].append(record)
            continue

    return result


def get_table(data, table_name):
    """Get records for a specific table. Returns list of dicts, or empty list."""
    table = data.get('tables', {}).get(table_name, {})
    return table.get('records', [])


def get_fields(data, table_name):
    """Get field names for a specific table. Returns list of strings."""
    table = data.get('tables', {}).get(table_name, {})
    return table.get('fields', [])


# ─────────────────────────────────────────────
# CALENDAR PARSING
# ─────────────────────────────────────────────

def parse_calendar_data(clndr_data_str):
    """
    Parse the encoded clndr_data field from the CALENDAR table.
    Returns structured calendar info including work days, holidays, and exceptions.

    The clndr_data string uses a proprietary P6 encoding:
    - Parenthesized sections define day patterns
    - Work/non-work patterns for each day of the week
    - Exception dates for holidays and special days
    """
    result = {
        'work_days': [],           # list of day indices (0=Sun, 1=Mon, ..., 6=Sat)
        'work_day_names': [],      # human-readable day names
        'holidays': [],            # exception dates that are NON-working (day off)
        'special_workdays': [],    # exception dates that ARE working (day on despite being normally off)
        'exceptions': [],          # other exception entries
        'hours_per_day': None,
        'raw': clndr_data_str,
    }

    if not clndr_data_str or not clndr_data_str.strip():
        return result

    day_names = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

    # Extract standard work week pattern (P6 19.x / 23.x / 24.x format).
    # Actual P6 encoding is:
    #   (0||<dayN>()((0||<slot>(s|HH:MM|f|HH:MM)())(...)))   <- work day (1+ time slots)
    #   (0||<dayN>()())                                       <- non-work day (empty)
    # Day numbers: 1=Sunday ... 7=Saturday.
    #
    # Strategy: find the DaysOfWeek block by balanced-paren walking (the earlier
    # non-greedy regex stopped at the first `))` which is inside a day's time-slot
    # list — only ever captured 1 day). Then walk the block and classify each
    # `(0||N()...)` segment by whether it contains a time slot.
    def _balanced_block_after(text, anchor):
        """Return the contents inside the () that follow `anchor` in `text`."""
        idx = text.find(anchor)
        if idx < 0:
            return None
        # Find the `(` that starts the block we want (the one AFTER the anchor's own "()")
        # DaysOfWeek pattern is `DaysOfWeek()(...)` — we want the second `(`.
        open_idx = text.find('(', idx + len(anchor))
        # Skip over a possible empty-paren pair `()` that comes immediately
        if text[open_idx:open_idx+2] == '()':
            open_idx = text.find('(', open_idx + 2)
        if open_idx < 0:
            return None
        depth = 0
        for k in range(open_idx, len(text)):
            c = text[k]
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
                if depth == 0:
                    return text[open_idx + 1:k]
        return None

    dow_block = _balanced_block_after(clndr_data_str, 'DaysOfWeek')
    if dow_block is not None:
        # Walk the block to find each (0||N()...) day segment.
        i = 0
        while i < len(dow_block):
            m = re.match(r'\(0\|\|(\d)\(\)', dow_block[i:])
            if not m:
                i += 1
                continue
            day_num = int(m.group(1))
            start = i
            # Walk to matching close of this day segment
            depth = 0
            j = i
            while j < len(dow_block):
                ch = dow_block[j]
                if ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
                    if depth == 0:
                        j += 1
                        break
                j += 1
            day_body = dow_block[start:j]
            # A day is a work day iff it contains at least one time slot `(s|...|f|...)`.
            # P6 emits times as either `08:00` or `8:00` — accept 1 or 2 digit hour.
            if re.search(r'\(s\|\d{1,2}:\d{2}\|f\|\d{1,2}:\d{2}\)', day_body):
                day_idx = day_num - 1
                if 0 <= day_idx <= 6:
                    result['work_days'].append(day_idx)
                    result['work_day_names'].append(day_names[day_idx])
            i = j

    # Fallback: older P6 versions compact work days as bare `(d|N)` patterns.
    if not result['work_days']:
        bare_days = set(int(m) for m in re.findall(r'\(d\|(\d)\)', clndr_data_str))
        for day_idx in range(7):
            day_num = day_idx + 1
            if day_num in bare_days:
                result['work_days'].append(day_idx)
                result['work_day_names'].append(day_names[day_idx])

    # Second fallback: legacy `d|N(s|...` inline pattern (keeps compatibility
    # with any P6 variant that used the old encoding we originally targeted).
    if not result['work_days']:
        for day_idx in range(7):
            day_num = day_idx + 1
            if f'd|{day_num}(s|' in clndr_data_str:
                result['work_days'].append(day_idx)
                result['work_day_names'].append(day_names[day_idx])

    # Extract exception dates, classifying each as:
    #   - holiday        (day off:           body after d|<serial> is empty   → `()(  )`)
    #   - special workday (day forced on:    body after d|<serial> contains a time slot `(s|HH:MM|f|HH:MM)`)
    #
    # P6 exception encoding:
    #   (0||0(d|<serial>)(<body>))
    # where:
    #   - <serial> is either an integer Excel serial date or a YYYY-MM-DD string
    #   - <body> is empty `()` for a non-working exception (holiday), or
    #     contains `(0||0(s|08:00|f|16:00)())` time-slot segments for a
    #     working exception (special workday).
    exc_block = _balanced_block_after(clndr_data_str, 'Exceptions')
    if exc_block:
        # Walk the exceptions block segment-by-segment via balanced parens so
        # we can classify each `(0||0(d|<serial>)(<body>))` as working or not.
        i = 0
        while i < len(exc_block):
            # Look for start of an exception segment: (0||0(d|<serial>)(<body>))
            m = re.match(r'\(0\|\|0\(d\|([^)]+)\)', exc_block[i:])
            if not m:
                i += 1
                continue
            serial_raw = m.group(1)
            # Move past the `(d|...)` portion to where <body> begins
            j = i + m.end()
            # Skip whitespace if any
            while j < len(exc_block) and exc_block[j] in ' \t\r\n':
                j += 1
            # Expect `(` — the body's outer open paren
            body_start = j
            body_end = body_start
            if j < len(exc_block) and exc_block[j] == '(':
                depth = 0
                k = j
                while k < len(exc_block):
                    ch = exc_block[k]
                    if ch == '(':
                        depth += 1
                    elif ch == ')':
                        depth -= 1
                        if depth == 0:
                            body_end = k + 1
                            break
                    k += 1
            body_text = exc_block[body_start:body_end] if body_end > body_start else ''
            # Classify: any time slot → working exception; else → holiday
            is_special_workday = bool(re.search(
                r'\(s\|\d{1,2}:\d{2}\|f\|\d{1,2}:\d{2}\)', body_text
            ))
            # Parse the serial into an ISO date
            iso_date = _xer_exception_serial_to_iso(serial_raw)
            if iso_date:
                if is_special_workday:
                    result['special_workdays'].append(iso_date)
                else:
                    result['holidays'].append(iso_date)
            # Advance past this segment; find the closing paren of the outer
            # (0||0(d|...)(<body>)) tuple. body_end already ended on the
            # body's closing paren. One more `)` should close the outer tuple.
            seg_end = body_end
            # Advance at least one past body_end to avoid infinite loop if
            # body_end didn't advance.
            i = max(seg_end, i + 1)

    # Always apply the proven v1.0 regex-based capture across the entire
    # exceptions block. Some P6 exports nest exceptions in formats the
    # balanced-paren walker above misses (certain large-program XER exports
    # use a different opening marker on the full holiday set). Union with
    # the walker output; dedupe below. Special_workdays already captured
    # above — this fallback preserves holidays without double-classifying.
    if exc_block:
        walker_working = set(result['special_workdays'])
        # Pre-scan for serials that have a time-slot body → those are
        # special_workdays, not holidays. Pattern: `d|<serial>` followed
        # (within a few chars) by `(s|HH:MM|f|HH:MM)`.
        special_serials = set(re.findall(
            r'd\|(\d+)\)\(\(?\(?0?\|?\|?0?\(s\|\d{1,2}:\d{2}\|f\|',
            exc_block,
        ))
        # Integer Excel-serial exceptions: d|<int>
        for serial in re.findall(r'd\|(\d+)\b', exc_block):
            iso = _xer_exception_serial_to_iso(serial)
            if not iso:
                continue
            if iso in walker_working:
                continue
            if serial in special_serials:
                if iso not in result['special_workdays']:
                    result['special_workdays'].append(iso)
            else:
                result['holidays'].append(iso)
        # Legacy string exceptions: d|YYYY-MM-DD
        for iso in re.findall(r'd\|(\d{4}-\d{2}-\d{2})', exc_block):
            try:
                y = int(iso[:4])
                if 1990 <= y <= 2050 and iso not in walker_working:
                    result['holidays'].append(iso)
            except ValueError:
                continue

    # Remove duplicates and sort
    result['holidays'] = sorted(list(set(result['holidays'])))
    result['special_workdays'] = sorted(list(set(result['special_workdays'])))

    return result


def _xer_exception_serial_to_iso(serial_raw):
    """Convert a P6 exception date serial (int or YYYY-MM-DD) to an ISO date string.

    Returns '' if the value is malformed or out of the 1990–2050 sanity range.
    """
    s = serial_raw.strip()
    # Integer Excel-serial date
    if re.fullmatch(r'\d{5,6}', s):
        try:
            serial = int(s)
            # Excel/P6 epoch = 1899-12-30 (accounts for the 1900 leap-year bug)
            dt = datetime(1899, 12, 30) + timedelta(days=serial)
            if 1990 <= dt.year <= 2050:
                return dt.strftime('%Y-%m-%d')
        except (ValueError, OverflowError):
            pass
    # String date (legacy format)
    m = re.match(r'(\d{4}-\d{2}-\d{2})', s)
    if m:
        try:
            dt = datetime.strptime(m.group(1), '%Y-%m-%d')
            if 1990 <= dt.year <= 2050:
                return m.group(1)
        except ValueError:
            pass
    return ''


def get_calendar_map(data):
    """
    Build a calendar lookup: clndr_id → parsed calendar info.
    Includes hours_per_day from the CALENDAR table's day_hr_cnt field.
    """
    calendars = get_table(data, 'CALENDAR')
    cal_map = {}

    for cal in calendars:
        clndr_id = cal.get('clndr_id', '')
        parsed = parse_calendar_data(cal.get('clndr_data', ''))
        parsed['clndr_id'] = clndr_id
        parsed['clndr_name'] = cal.get('clndr_name', '')

        # Hours per day
        day_hr = cal.get('day_hr_cnt', '8')
        try:
            parsed['hours_per_day'] = float(day_hr)
        except (ValueError, TypeError):
            parsed['hours_per_day'] = 8.0

        # Hours per week
        week_hr = cal.get('week_hr_cnt', '40')
        try:
            parsed['hours_per_week'] = float(week_hr)
        except (ValueError, TypeError):
            parsed['hours_per_week'] = 40.0

        cal_map[clndr_id] = parsed

    return cal_map


def get_work_days_between(start_date, end_date, calendar_info=None):
    """
    Calculate work days between two dates using calendar info.
    Accounts for work week pattern and holiday exceptions.
    If calendar_info is None or empty, defaults to Mon-Fri with no holidays.
    """
    if not start_date or not end_date:
        return None

    try:
        if isinstance(start_date, str):
            start = datetime.strptime(start_date[:10], '%Y-%m-%d')
        else:
            start = start_date
        if isinstance(end_date, str):
            end = datetime.strptime(end_date[:10], '%Y-%m-%d')
        else:
            end = end_date
    except (ValueError, TypeError):
        return None

    # Default to Mon-Fri in P6 weekday scheme (0=Sun, 1=Mon...6=Sat)
    if calendar_info is None:
        work_days = [1, 2, 3, 4, 5]
        holidays = set()
    else:
        work_days = calendar_info.get('work_days') or [1, 2, 3, 4, 5]
        holidays = set(calendar_info.get('holidays') or [])

    count = 0
    current = start
    while current <= end:
        day_of_week = current.weekday()
        # Python weekday: Mon=0..Sun=6; P6 work_days uses Sun=0..Sat=6
        # Convert: Python Mon=0 → P6 index 1, Python Sun=6 → P6 index 0
        p6_day = (day_of_week + 1) % 7
        date_str = current.strftime('%Y-%m-%d')

        if p6_day in work_days and date_str not in holidays:
            count += 1

        current += timedelta(days=1)

    return count


def _is_work_day(dt, work_days, holidays):
    """True if dt (date/datetime) is a working day on the given calendar.

    work_days: list of P6 weekday indices (0=Sun, 1=Mon, ..., 6=Sat).
    holidays: iterable of 'YYYY-MM-DD' exception date strings (non-working).
    """
    day_of_week = dt.weekday()  # Python: Mon=0..Sun=6
    p6_day = (day_of_week + 1) % 7  # Python Mon=0 → P6 1 ; Python Sun=6 → P6 0
    date_str = dt.strftime('%Y-%m-%d')
    return (p6_day in work_days) and (date_str not in holidays)


def add_work_days(start_date, n_workdays, calendar_info=None):
    """Advance ``start_date`` by ``n_workdays`` working days on the given calendar.

    Walks the calendar day-by-day from ``start_date``, skipping non-work weekdays
    (per ``calendar_info['work_days']`` in P6 indexing — 0=Sun, 1=Mon, ..., 6=Sat)
    and exception holidays (``calendar_info['holidays']``), counting only actual
    work days. Returns when ``n_workdays`` working days have been consumed.

    This is the inverse of ``get_work_days_between`` and drives calendar-aware
    CPM forward-pass arithmetic: a 5-workday task on a Mon-Fri calendar starting
    on Monday finishes Friday — NOT Saturday (the ordinal-arithmetic bug that
    silently wrecked every TIA on a non-7-day calendar).

    Args:
        start_date: 'YYYY-MM-DD' string OR datetime/date object.
        n_workdays: float or int — fractional workdays are rounded to the nearest
            whole workday count internally (P6 CPM works on whole-day nodes).
        calendar_info: dict from get_calendar_map(). None → Mon-Fri, no holidays.

    Returns:
        A ``date`` object N working days after start_date. ``n_workdays == 0``
        returns start_date unchanged. Negative ``n_workdays`` delegates to
        ``subtract_work_days`` for symmetry.

    Raises:
        ValueError if start_date cannot be parsed.
    """
    if n_workdays is None:
        n_workdays = 0
    try:
        n = int(round(float(n_workdays)))
    except (TypeError, ValueError):
        n = 0
    if n < 0:
        return subtract_work_days(start_date, -n, calendar_info)

    # Normalize start_date → date object.
    if isinstance(start_date, str):
        try:
            current = datetime.strptime(start_date[:10], '%Y-%m-%d').date()
        except (ValueError, TypeError) as e:
            raise ValueError(f'add_work_days: cannot parse start_date={start_date!r}') from e
    elif isinstance(start_date, datetime):
        current = start_date.date()
    else:
        current = start_date  # assume date-like

    if n == 0:
        return current

    if calendar_info is None:
        work_days = [1, 2, 3, 4, 5]
        holidays = set()
    else:
        work_days = calendar_info.get('work_days') or [1, 2, 3, 4, 5]
        holidays = set(calendar_info.get('holidays') or [])

    # Guard: a calendar with zero working days would loop forever.
    if not work_days:
        return current

    # P6 CPM convention: EF = ES + duration means the task occupies N work days
    # (NOT N gaps). We step one day per iteration and decrement `remaining`
    # whenever we land on a work day. The final decrement lands us on the EF
    # date — i.e. the date of work day N.
    remaining = n
    while remaining > 0:
        current += timedelta(days=1)
        if _is_work_day(current, work_days, holidays):
            remaining -= 1
    return current


def subtract_work_days(end_date, n_workdays, calendar_info=None):
    """Walk backwards N working days from ``end_date`` on the given calendar.

    Used by the CPM backward pass: LS = LF - duration on the activity's calendar.
    A 5-workday task finishing Friday starts Monday (not the prior Sunday).

    Same arg conventions as ``add_work_days``. Negative ``n_workdays`` delegates
    forward (inverse symmetry).
    """
    if n_workdays is None:
        n_workdays = 0
    try:
        n = int(round(float(n_workdays)))
    except (TypeError, ValueError):
        n = 0
    if n < 0:
        return add_work_days(end_date, -n, calendar_info)

    if isinstance(end_date, str):
        try:
            current = datetime.strptime(end_date[:10], '%Y-%m-%d').date()
        except (ValueError, TypeError) as e:
            raise ValueError(f'subtract_work_days: cannot parse end_date={end_date!r}') from e
    elif isinstance(end_date, datetime):
        current = end_date.date()
    else:
        current = end_date

    if n == 0:
        return current

    if calendar_info is None:
        work_days = [1, 2, 3, 4, 5]
        holidays = set()
    else:
        work_days = calendar_info.get('work_days') or [1, 2, 3, 4, 5]
        holidays = set(calendar_info.get('holidays') or [])

    if not work_days:
        return current

    remaining = n
    while remaining > 0:
        current -= timedelta(days=1)
        if _is_work_day(current, work_days, holidays):
            remaining -= 1
    return current


def duration_hours_to_days(hours, calendar_info=None, default_hrs_per_day=8.0, ndigits=None):
    """Convert P6 duration in hours to workdays. Set ndigits to round; default returns raw float."""
    if not hours:
        return 0
    try:
        hrs = float(hours)
    except (ValueError, TypeError):
        return 0

    hrs_per_day = default_hrs_per_day
    if calendar_info and calendar_info.get('hours_per_day'):
        hrs_per_day = calendar_info['hours_per_day']

    if hrs_per_day <= 0:
        return 0
    result = hrs / hrs_per_day
    return round(result, ndigits) if ndigits is not None else result


# ─────────────────────────────────────────────
# CROSS-REFERENCE BUILDERS
# ─────────────────────────────────────────────

def build_wbs_map(data):
    """Build WBS lookup: wbs_id → wbs record with hierarchy path."""
    wbs_records = get_table(data, 'PROJWBS')
    wbs_map = {}

    for wbs in wbs_records:
        wbs_id = wbs.get('wbs_id', '')
        wbs_map[wbs_id] = wbs

    # Build full paths
    # Each top-level call to get_path() starts with a fresh `visited` set, and
    # the recursion only walks the parent chain (each WBS has at most ONE parent).
    # That means a repeated wbs_id within a single chain walk is a genuine cycle
    # (A→B→A) and not a legitimate revisit — so raise loudly instead of silently
    # truncating the path with an empty string.
    def get_path(wbs_id, visited=None):
        if visited is None:
            visited = set()
        if wbs_id not in wbs_map:
            return ''
        if wbs_id in visited:
            raise ValueError(
                f"Circular WBS hierarchy detected at wbs_id={wbs_id!r}; "
                f"visited={sorted(visited)}"
            )
        visited.add(wbs_id)
        wbs = wbs_map[wbs_id]
        parent_id = wbs.get('parent_wbs_id', '')
        parent_path = get_path(parent_id, visited)
        name = wbs.get('wbs_name', wbs.get('wbs_short_name', ''))
        return f"{parent_path} > {name}" if parent_path else name

    for wbs_id in wbs_map:
        wbs_map[wbs_id]['_full_path'] = get_path(wbs_id)

    return wbs_map


def build_resource_map(data):
    """Build resource assignment lookup: task_id → list of resource records."""
    taskrsrc = get_table(data, 'TASKRSRC')
    rsrc = get_table(data, 'RSRC')

    # RSRC lookup by rsrc_id
    rsrc_lookup = {r.get('rsrc_id', ''): r for r in rsrc}

    # Group by task_id
    task_resources = defaultdict(list)
    for tr in taskrsrc:
        task_id = tr.get('task_id', '')
        rsrc_id = tr.get('rsrc_id', '')
        rsrc_record = rsrc_lookup.get(rsrc_id, {})
        combined = {**tr, '_rsrc_name': rsrc_record.get('rsrc_name', ''),
                    '_rsrc_short_name': rsrc_record.get('rsrc_short_name', '')}
        task_resources[task_id].append(combined)

    return dict(task_resources)


def build_predecessor_map(data):
    """Build predecessor/successor lookups from TASKPRED table."""
    preds = get_table(data, 'TASKPRED')

    predecessors = defaultdict(list)   # task_id → list of predecessor records
    successors = defaultdict(list)     # pred_task_id → list of successor records

    for p in preds:
        task_id = p.get('task_id', '')
        pred_task_id = p.get('pred_task_id', '')
        predecessors[task_id].append(p)
        successors[pred_task_id].append(p)

    return dict(predecessors), dict(successors)


def build_activity_code_map(data):
    """Build activity code lookups from ACTVTYPE, ACTVCODE, TASKACTV."""
    actvtype = get_table(data, 'ACTVTYPE')
    actvcode = get_table(data, 'ACTVCODE')
    taskactv = get_table(data, 'TASKACTV')

    # Type lookup
    type_map = {t.get('actv_code_type_id', ''): t for t in actvtype}

    # Code lookup
    code_map = {c.get('actv_code_id', ''): c for c in actvcode}

    # Task → codes
    task_codes = defaultdict(list)
    for ta in taskactv:
        task_id = ta.get('task_id', '')
        code_id = ta.get('actv_code_id', '')
        code_rec = code_map.get(code_id, {})
        type_id = code_rec.get('actv_code_type_id', '')
        type_rec = type_map.get(type_id, {})
        task_codes[task_id].append({
            'type_name': type_rec.get('actv_code_type', ''),
            'code_name': code_rec.get('short_name', ''),
            'code_desc': code_rec.get('actv_code_name', ''),
        })

    return dict(task_codes)


def build_udf_map(data):
    """Build UDF value lookup: (table_name, fk_id) → list of UDF values.

    Keyed on (table_name, fk_id) because fk_id is only unique within a table.
    TASK, PROJECT, PROJWBS, and RSRC can all have overlapping fk_id values.
    """
    udftype = get_table(data, 'UDFTYPE')
    udfvalue = get_table(data, 'UDFVALUE')

    type_map = {u.get('udf_type_id', ''): u for u in udftype}

    udf_lookup = defaultdict(list)
    for uv in udfvalue:
        fk_id = uv.get('fk_id', '')
        udf_type_id = uv.get('udf_type_id', '')
        type_rec = type_map.get(udf_type_id, {})
        table_name = type_rec.get('table_name', '')
        udf_lookup[(table_name, fk_id)].append({
            'label': type_rec.get('udf_type_label', ''),
            'name': type_rec.get('udf_type_name', ''),
            'value': uv.get('udf_text', '') or uv.get('udf_number', '') or uv.get('udf_date', ''),
        })

    return dict(udf_lookup)


# ─────────────────────────────────────────────
# SUMMARY REPORT
# ─────────────────────────────────────────────

def generate_summary(data):
    """
    Generate a comprehensive summary report from parsed XER data.
    Returns a dictionary with all key metrics.
    """
    summary = {
        'file_info': {},
        'project': {},
        'schedule_metrics': {},
        'activity_breakdown': {},
        'critical_path': {},
        'relationships': {},
        'calendars': [],
        'wbs_structure': [],
        'resources': {},
        'data_quality': {},
        'tables_found': [],
    }

    # ── File Info ──
    summary['file_info'] = {
        'filename': data.get('filename', ''),
        'filepath': data.get('filepath', ''),
        'parsed_at': data.get('parse_timestamp', ''),
        'p6_version': data.get('ermhdr', {}).get('version', ''),
        'export_date': data.get('ermhdr', {}).get('export_date', ''),
        'exported_by': data.get('ermhdr', {}).get('user', ''),
        'currency': data.get('ermhdr', {}).get('currency', ''),
    }

    # ── Tables Found ──
    for table_name, table_data in data.get('tables', {}).items():
        record_count = len(table_data.get('records', []))
        field_count = len(table_data.get('fields', []))
        summary['tables_found'].append({
            'table': table_name,
            'fields': field_count,
            'records': record_count,
        })

    # ── Project Info ──
    projects = get_table(data, 'PROJECT')
    if projects:
        proj = projects[0]  # Primary project
        summary['project'] = {
            'proj_id': proj.get('proj_id', ''),
            'project_name': proj.get('proj_short_name', ''),
            'project_long_name': proj.get('proj_long_name', '') or proj.get('proj_short_name', ''),
            'data_date': proj.get('last_recalc_date', ''),
            'plan_start': proj.get('plan_start_date', ''),
            'plan_finish': proj.get('plan_end_date', ''),
            'scheduled_finish': proj.get('scd_end_date', ''),
            'must_finish_by': proj.get('plan_end_date', ''),
            'project_count': len(projects),
        }
        if len(projects) > 1:
            summary['project']['all_projects'] = [
                {'proj_id': p.get('proj_id', ''), 'name': p.get('proj_short_name', '')}
                for p in projects
            ]

    # ── Activity Metrics ──
    tasks = get_table(data, 'TASK')
    cal_map = get_calendar_map(data)

    # Filter out LOE and WBS Summary
    real_tasks = [t for t in tasks if t.get('task_type', '') not in ('TT_LOE', 'TT_WBS')]
    milestones = [t for t in real_tasks if t.get('task_type', '') in ('TT_Mile', 'TT_FinMile')]

    total = len(real_tasks)
    complete = len([t for t in real_tasks if t.get('status_code', '') == 'TK_Complete'])
    in_progress = len([t for t in real_tasks if t.get('status_code', '') == 'TK_Active'])
    not_started = len([t for t in real_tasks if t.get('status_code', '') == 'TK_NotStart'])

    summary['schedule_metrics'] = {
        'total_activities': total,
        'total_including_loe': len(tasks),
        'loe_count': len(tasks) - len(real_tasks),
        'complete': complete,
        'in_progress': in_progress,
        'not_started': not_started,
        'percent_complete': round((complete / total * 100), 1) if total > 0 else 0,
        'milestone_count': len(milestones),
        'milestones_complete': len([m for m in milestones if m.get('status_code') == 'TK_Complete']),
        'milestones_remaining': len([m for m in milestones if m.get('status_code') != 'TK_Complete']),
    }

    # ── Activity Type Breakdown ──
    type_counts = defaultdict(int)
    for t in tasks:
        tt = t.get('task_type', 'Unknown')
        type_counts[TASK_TYPES.get(tt, tt)] += 1
    summary['activity_breakdown']['by_type'] = dict(type_counts)

    status_counts = defaultdict(int)
    for t in real_tasks:
        sc = t.get('status_code', 'Unknown')
        status_counts[STATUS_CODES.get(sc, sc)] += 1
    summary['activity_breakdown']['by_status'] = dict(status_counts)

    # ── Critical Path ──
    # Method 1: total_float_hr_cnt <= 0
    critical_by_float = [t for t in real_tasks if _is_critical_by_float(t)]
    # Method 2: driving_path_flag
    critical_by_flag = [t for t in real_tasks if t.get('driving_path_flag', '') == 'Y']
    # Method 3: crt_path_num (longest path) — nonzero integer means on the longest path
    critical_by_lp = [t for t in real_tasks if _crt_path_num_active(t)]

    summary['critical_path'] = {
        'critical_by_float_zero': len(critical_by_float),
        'critical_by_driving_flag': len(critical_by_flag),
        'critical_by_longest_path': len(critical_by_lp),
        'critical_activities': [
            {
                'task_code': t.get('task_code', ''),
                'task_name': t.get('task_name', ''),
                'status': STATUS_CODES.get(t.get('status_code', ''), t.get('status_code', '')),
                'total_float_days': duration_hours_to_days(
                    t.get('total_float_hr_cnt', '0'),
                    cal_map.get(t.get('clndr_id', ''))
                ),
                'early_start': t.get('early_start_date', ''),
                'early_finish': t.get('early_end_date', ''),
            }
            for t in critical_by_float[:50]  # Cap the summary list
        ],
        'note': '(Showing first 50 critical activities in summary. Full list available via get_table.)'
            if len(critical_by_float) > 50 else '',
    }

    # Float distribution — uses per-activity calendar hours, not hardcoded 8hr
    float_dist = {'negative': 0, 'zero': 0, '1-5': 0, '6-10': 0, '11-20': 0, '21-40': 0, '41+': 0, 'null': 0}
    for t in real_tasks:
        tf = t.get('total_float_hr_cnt', '')
        if not tf or tf == '':
            float_dist['null'] += 1
            continue
        try:
            # Use the activity's own calendar for the hr→day conversion.
            # Fall back to 8hr default only when no calendar is resolvable.
            cal = cal_map.get(t.get('clndr_id', ''))
            tf_days = duration_hours_to_days(tf, cal)
        except (ValueError, TypeError):
            float_dist['null'] += 1
            continue
        if tf_days < 0:
            float_dist['negative'] += 1
        elif tf_days == 0:
            float_dist['zero'] += 1
        elif tf_days <= 5:
            float_dist['1-5'] += 1
        elif tf_days <= 10:
            float_dist['6-10'] += 1
        elif tf_days <= 20:
            float_dist['11-20'] += 1
        elif tf_days <= 40:
            float_dist['21-40'] += 1
        else:
            float_dist['41+'] += 1
    summary['critical_path']['float_distribution'] = float_dist

    # ── Relationships ──
    preds = get_table(data, 'TASKPRED')
    rel_types = defaultdict(int)
    lags = []
    for p in preds:
        pt = p.get('pred_type', 'Unknown')
        rel_types[RELATIONSHIP_TYPES.get(pt, pt)] += 1
        lag = p.get('lag_hr_cnt', '0')
        try:
            lag_val = float(lag)
            if lag_val != 0:
                lags.append(lag_val)
        except (ValueError, TypeError):
            pass

    # Open ends
    pred_map, succ_map = build_predecessor_map(data)
    no_predecessors = [t for t in real_tasks
                       if t.get('task_id', '') not in pred_map
                       and t.get('task_type', '') not in ('TT_Mile',)]
    no_successors = [t for t in real_tasks
                     if t.get('task_id', '') not in succ_map
                     and t.get('task_type', '') not in ('TT_FinMile',)]

    summary['relationships'] = {
        'total_relationships': len(preds),
        'by_type': dict(rel_types),
        'relationships_with_lag': len(lags),
        'open_ends': {
            'no_predecessors': len(no_predecessors),
            'no_successors': len(no_successors),
            'activities_without_pred': [
                {'task_code': t.get('task_code', ''), 'task_name': t.get('task_name', '')}
                for t in no_predecessors
            ],
            'activities_without_succ': [
                {'task_code': t.get('task_code', ''), 'task_name': t.get('task_name', '')}
                for t in no_successors
            ],
        },
    }

    # ── Calendars ──
    for clndr_id, cal_info in cal_map.items():
        summary['calendars'].append({
            'clndr_id': clndr_id,
            'name': cal_info.get('clndr_name', ''),
            'hours_per_day': cal_info.get('hours_per_day', 8.0),
            'hours_per_week': cal_info.get('hours_per_week', 40.0),
            'work_days': cal_info.get('work_day_names', []),
            'holiday_count': len(cal_info.get('holidays', [])),
            'holidays': cal_info.get('holidays', []),
        })

    # ── WBS Structure ──
    wbs_map = build_wbs_map(data)
    wbs_task_counts = defaultdict(int)
    for t in real_tasks:
        wbs_id = t.get('wbs_id', '')
        wbs_task_counts[wbs_id] += 1

    for wbs_id, wbs_rec in wbs_map.items():
        summary['wbs_structure'].append({
            'wbs_id': wbs_id,
            'wbs_code': wbs_rec.get('wbs_short_name', ''),
            'wbs_name': wbs_rec.get('wbs_name', ''),
            'full_path': wbs_rec.get('_full_path', ''),
            'activity_count': wbs_task_counts.get(wbs_id, 0),
        })

    # ── Resources ──
    taskrsrc = get_table(data, 'TASKRSRC')
    rsrc = get_table(data, 'RSRC')
    summary['resources'] = {
        'resource_assignments': len(taskrsrc),
        'unique_resources': len(rsrc),
        'resource_names': [r.get('rsrc_name', '') for r in rsrc],
    }

    # ── Data Quality Flags ──
    constraints = [t for t in real_tasks if t.get('cstr_type', '').strip()]
    constraint_counts = defaultdict(int)
    for t in constraints:
        code = t.get('cstr_type', '').strip()
        label = CONSTRAINT_TYPES.get(code, code)
        constraint_counts[label] += 1
    summary['data_quality'] = {
        'activities_with_constraints': len(constraints),
        'constraint_types': dict(constraint_counts),
        'field_count_validation': _validate_field_counts(data),
        'missing_logic': {
            'no_predecessor_count': len(no_predecessors),
            'no_successor_count': len(no_successors),
        },
    }

    return summary


def _is_critical_by_float(task):
    """Check if a task is critical based on total float."""
    tf = task.get('total_float_hr_cnt', '')
    if not tf or tf == '':
        return False
    try:
        return float(tf) <= 0
    except ValueError:
        return False


def _crt_path_num_active(task):
    """True when crt_path_num identifies this task as on a longest path (nonzero)."""
    v = task.get('crt_path_num', '')
    if not v:
        return False
    try:
        return int(v) > 0
    except ValueError:
        return False


def _validate_field_counts(data):
    """Check table %F field count against known values for the XER's P6 version.

    P6 field counts vary by major version — so pick the version family from the
    ERMHDR and validate against that. Unknown version → no warnings (we can't say).
    """
    version = (data.get('ermhdr', {}) or {}).get('version', '')
    major = version.split('.')[0] if version else ''
    expected_schema = TABLE_FIELD_COUNTS_BY_VERSION.get(major)

    if not expected_schema:
        return 'P6 version not in schema map — field-count validation skipped'

    issues = []
    for table_name, table_data in data.get('tables', {}).items():
        field_count = len(table_data.get('fields', []))
        if table_name in expected_schema:
            expected = expected_schema[table_name]
            if field_count != expected:
                issues.append({
                    'table': table_name,
                    'note': f'Expected {expected} fields for P6 {version}, found {field_count}',
                    'severity': 'warning',
                })
    return issues if issues else 'All field counts valid'


def print_summary(data, output_file=None):
    """Print a formatted summary report to console or file."""
    summary = generate_summary(data)

    lines = []
    lines.append('=' * 70)
    lines.append('XER FILE SUMMARY REPORT')
    lines.append('=' * 70)
    lines.append('')

    # File Info
    fi = summary['file_info']
    lines.append(f"File:           {fi['filename']}")
    lines.append(f"P6 Version:     {fi['p6_version']}")
    lines.append(f"Exported:       {fi['export_date']}")
    lines.append(f"Exported By:    {fi['exported_by']}")
    lines.append(f"Parsed At:      {fi['parsed_at']}")
    lines.append('')

    # Project
    proj = summary['project']
    lines.append(f"Project:        {proj.get('project_name', 'N/A')}")
    lines.append(f"Data Date:      {proj.get('data_date', 'N/A')}")
    lines.append(f"Plan Start:     {proj.get('plan_start', 'N/A')}")
    lines.append(f"Plan Finish:    {proj.get('plan_finish', 'N/A')}")
    lines.append(f"Sched Finish:   {proj.get('scheduled_finish', 'N/A')}")
    if proj.get('project_count', 0) > 1:
        lines.append(f"** Multi-project XER: {proj['project_count']} projects found **")
    lines.append('')

    # Tables
    lines.append('─' * 40)
    lines.append('TABLES IN FILE')
    lines.append('─' * 40)
    for t in summary['tables_found']:
        lines.append(f"  {t['table']:<20} {t['fields']:>3} fields  {t['records']:>6} records")
    lines.append('')

    # Schedule Metrics
    sm = summary['schedule_metrics']
    lines.append('─' * 40)
    lines.append('SCHEDULE METRICS')
    lines.append('─' * 40)
    lines.append(f"  Total Activities:     {sm['total_activities']} (excl. {sm['loe_count']} LOE)")
    lines.append(f"  Complete:             {sm['complete']} ({sm['percent_complete']}%)")
    lines.append(f"  In Progress:          {sm['in_progress']}")
    lines.append(f"  Not Started:          {sm['not_started']}")
    lines.append(f"  Milestones:           {sm['milestone_count']} ({sm['milestones_complete']} hit, {sm['milestones_remaining']} remaining)")
    lines.append('')

    # Critical Path
    cp = summary['critical_path']
    lines.append('─' * 40)
    lines.append('CRITICAL PATH')
    lines.append('─' * 40)
    lines.append(f"  Critical (TF ≤ 0):    {cp['critical_by_float_zero']}")
    lines.append(f"  Driving Path Flag:    {cp['critical_by_driving_flag']}")
    lines.append(f"  Longest Path:         {cp['critical_by_longest_path']}")
    lines.append('')
    fd = cp['float_distribution']
    lines.append('  Float Distribution:')
    lines.append(f"    Negative:  {fd['negative']}")
    lines.append(f"    Zero:      {fd['zero']}")
    lines.append(f"    1-5 days:  {fd['1-5']}")
    lines.append(f"    6-10 days: {fd['6-10']}")
    lines.append(f"    11-20:     {fd['11-20']}")
    lines.append(f"    21-40:     {fd['21-40']}")
    lines.append(f"    41+:       {fd['41+']}")
    lines.append(f"    Null:      {fd['null']}")
    lines.append('')

    # Relationships
    rel = summary['relationships']
    lines.append('─' * 40)
    lines.append('RELATIONSHIPS')
    lines.append('─' * 40)
    lines.append(f"  Total:                {rel['total_relationships']}")
    for rtype, count in rel['by_type'].items():
        lines.append(f"    {rtype:<20} {count}")
    lines.append(f"  With Lag:             {rel['relationships_with_lag']}")
    oe = rel['open_ends']
    lines.append(f"  No Predecessors:      {oe['no_predecessors']}")
    lines.append(f"  No Successors:        {oe['no_successors']}")
    lines.append('')

    # Calendars
    lines.append('─' * 40)
    lines.append('CALENDARS')
    lines.append('─' * 40)
    for cal in summary['calendars']:
        lines.append(f"  [{cal['clndr_id']}] {cal['name']}")
        lines.append(f"      {cal['hours_per_day']}h/day, {cal['hours_per_week']}h/week")
        lines.append(f"      Work days: {', '.join(cal['work_days']) if cal['work_days'] else 'Not parsed'}")
        lines.append(f"      Holidays: {cal['holiday_count']}")
    lines.append('')

    # Resources
    res = summary['resources']
    lines.append('─' * 40)
    lines.append('RESOURCES')
    lines.append('─' * 40)
    lines.append(f"  Unique Resources:     {res['unique_resources']}")
    lines.append(f"  Total Assignments:    {res['resource_assignments']}")
    lines.append('')

    # Data Quality
    dq = summary['data_quality']
    lines.append('─' * 40)
    lines.append('DATA QUALITY FLAGS')
    lines.append('─' * 40)
    lines.append(f"  Constrained Activities: {dq['activities_with_constraints']}")
    lines.append(f"  Missing Predecessors:   {dq['missing_logic']['no_predecessor_count']}")
    lines.append(f"  Missing Successors:     {dq['missing_logic']['no_successor_count']}")
    fv = dq['field_count_validation']
    if isinstance(fv, str):
        lines.append(f"  Field Validation:       {fv}")
    else:
        lines.append(f"  Field Validation:       {len(fv)} issues found")
        for issue in fv[:10]:
            lines.append(f"    - {issue}")
    lines.append('')
    lines.append('=' * 70)

    report_text = '\n'.join(lines)

    if output_file:
        with open(output_file, 'w') as f:
            f.write(report_text)
        print(f"Summary report saved to: {output_file}")
    else:
        print(report_text)

    return summary


# ─────────────────────────────────────────────
# V2.0 — MANIFEST / BASELINES / UDF TYPES / SCHEMA DIFF / VALIDATION
# ─────────────────────────────────────────────

def generate_xer_manifest(data, xer_path=None, **manifest_kwargs):
    """Generate a nuclear-grade manifest for a parsed XER.

    Wraps the common `generate_manifest()` with XER-specific fields:
      - P6 version (from ERMHDR)
      - ERMHDR raw line (tab-joined) as 'extra.ermhdr'
      - Table counts (in 'extra.table_counts')
      - Source file SHA-256 + size (from audit_trail)
      - xer-parser skill version

    Args:
        data: parsed XER dict from parse_xer()
        xer_path: optional path to the source XER file (used for input sha256)
        **manifest_kwargs: additional kwargs forwarded to generate_manifest()
            (skill_name, operator, parameters, extra, ...)

    Returns:
        dict — manifest in the common schema, with XER-specific extras merged.

    Raises:
        RuntimeError: if _cpp_common is not importable
    """
    if generate_manifest is None:
        raise RuntimeError('_cpp_common is not on sys.path; cannot build manifest')

    ermhdr = data.get('ermhdr', {}) or {}
    raw = ermhdr.get('raw') or []
    ermhdr_raw_str = '\t'.join(raw) if isinstance(raw, list) else str(raw or '')

    # Table-level counts (record and field counts per table)
    table_counts = {}
    for table_name, table_data in (data.get('tables', {}) or {}).items():
        table_counts[table_name] = {
            'records': len(table_data.get('records', [])),
            'fields': len(table_data.get('fields', [])),
        }

    # Build the XER-specific extra block
    xer_extra = {
        'p6_version': ermhdr.get('version', ''),
        'p6_export_date': ermhdr.get('export_date', ''),
        'p6_exported_by': ermhdr.get('user', ''),
        'p6_currency': ermhdr.get('currency', ''),
        'ermhdr_raw': ermhdr_raw_str,
        'ermhdr_field_count': str(len(raw) if isinstance(raw, list) else 0),
        'table_count': str(len(data.get('tables', {}) or {})),
        'table_counts': table_counts,
        'encoding_used': data.get('encoding_used', ''),
        'xer_parser_version': _SKILL_VERSION,
    }

    # Merge caller-supplied extras
    merged_extra = dict(manifest_kwargs.pop('extra', {}) or {})
    merged_extra.update(xer_extra)

    # Default skill_name and input_files if caller didn't provide them
    skill_name = manifest_kwargs.pop('skill_name', 'xer-parser')
    input_files = manifest_kwargs.pop('input_files', None)
    if input_files is None and xer_path:
        input_files = [('xer', xer_path)]
    elif input_files is None and data.get('filepath'):
        input_files = [('xer', data['filepath'])]
    else:
        input_files = input_files or []

    skill_dir = manifest_kwargs.pop(
        'skill_dir',
        os.path.normpath(os.path.join(_SCRIPT_DIR, '..'))
    )

    manifest = generate_manifest(
        skill_name=skill_name,
        skill_dir=skill_dir,
        input_files=input_files,
        extra=merged_extra,
        **manifest_kwargs,
    )
    return manifest


def get_baselines(data):
    """Identify baseline schedules in the XER.

    P6 stores baselines either in a dedicated BASELINE table (newer versions)
    or as separate PROJECT records with bl_type/sum_base_proj_id flags. When
    neither exists, the single PROJECT record itself is the (only) baseline.

    Returns:
        list of dicts, each with:
            proj_id:     P6 project id
            short_name:  proj_short_name (or equivalent)
            bl_type:     bl_type code if present ('', 'BL_Project', 'BL_Primary', ...)
            data_date:   last_recalc_date / fin_dt
            source:      'BASELINE' | 'PROJECT' | 'PROJECT_SINGLE'
    """
    baselines = []

    # Path 1 — dedicated BASELINE table
    bl_records = get_table(data, 'BASELINE')
    for bl in bl_records:
        baselines.append({
            'proj_id': bl.get('base_proj_id', '') or bl.get('proj_id', ''),
            'short_name': bl.get('bl_name', '') or bl.get('proj_short_name', ''),
            'bl_type': bl.get('bl_type', '') or '',
            'data_date': bl.get('fin_dt', '') or bl.get('last_recalc_date', ''),
            'source': 'BASELINE',
        })

    # Path 2 — baseline projects tagged in PROJECT table (bl_type / sum_base_proj_id / base_type_id)
    projects = get_table(data, 'PROJECT')
    tagged = [
        p for p in projects
        if (p.get('bl_type', '') or p.get('base_type_id', '') or p.get('sum_base_proj_id', '')).strip()
    ]
    for p in tagged:
        # Skip duplicates already added via BASELINE table
        pid = p.get('proj_id', '')
        if any(b['proj_id'] == pid and b['source'] == 'BASELINE' for b in baselines):
            continue
        baselines.append({
            'proj_id': pid,
            'short_name': p.get('proj_short_name', ''),
            'bl_type': p.get('bl_type', '') or p.get('base_type_id', '') or '',
            'data_date': p.get('last_recalc_date', ''),
            'source': 'PROJECT',
        })

    # Path 3 — no baseline markers anywhere: the single PROJECT record IS the baseline
    if not baselines and projects:
        p = projects[0]
        baselines.append({
            'proj_id': p.get('proj_id', ''),
            'short_name': p.get('proj_short_name', ''),
            'bl_type': '',
            'data_date': p.get('last_recalc_date', ''),
            'source': 'PROJECT_SINGLE',
        })

    return baselines


def contract_baseline_id(data):
    """Return the proj_id of the contract baseline, or '' if none identifiable.

    The "contract baseline" is, in order of preference:
      1. The baseline tagged bl_type == 'BL_Project' (Primavera's canonical tag)
      2. The baseline tagged bl_type == 'BL_Primary'
      3. The earliest baseline by data_date
      4. The first baseline in get_baselines()
      5. '' if there are no baselines / no projects
    """
    baselines = get_baselines(data)
    if not baselines:
        return ''

    # Preferred tag wins
    for preferred in ('BL_Project', 'BL_Primary'):
        for b in baselines:
            if b.get('bl_type') == preferred:
                return b.get('proj_id', '')

    # Earliest by data_date (empty strings sort first — use a sentinel)
    def _sort_key(b):
        dd = (b.get('data_date') or '').strip()
        return (dd == '', dd)  # non-empty dates first, then lexical order

    sorted_bls = sorted(baselines, key=_sort_key)
    return sorted_bls[0].get('proj_id', '') if sorted_bls else ''


def get_udf_types(data):
    """Return full UDFTYPE records with a lookup-friendly shape.

    Existing `build_udf_map()` returns UDF *values* keyed by (table, fk_id) —
    this function exposes the UDF *type metadata* so callers can ask
    "what UDFs are defined, on which tables, of what data type?"

    Returns:
        list of dicts, each with:
            udf_type_id
            table_name       (TASK / PROJECT / PROJWBS / RSRC / ...)
            udf_type_name    (internal name, e.g. 'task_note')
            udf_type_label   (human label, e.g. 'Task Note')
            logical_data_type (FT_TEXT / FT_INT / FT_STATICTYPE / FT_DOUBLE / FT_DATE / ...)
            super_flag       (indicator field flag if present)
    """
    udftypes = get_table(data, 'UDFTYPE')
    out = []
    for u in udftypes:
        out.append({
            'udf_type_id': u.get('udf_type_id', ''),
            'table_name': u.get('table_name', ''),
            'udf_type_name': u.get('udf_type_name', ''),
            'udf_type_label': u.get('udf_type_label', ''),
            'logical_data_type': u.get('logical_data_type', '')
                or u.get('udf_type_logical_type', '')
                or u.get('udf_type', ''),
            'super_flag': u.get('super_flag', ''),
        })
    return out


def schema_diff(data_a, data_b):
    """Compare parsed-XER schemas across two XERs.

    Useful for spotting schema drift between P6 versions or baseline vs update.

    Args:
        data_a: parsed XER (the 'before' / baseline)
        data_b: parsed XER (the 'after' / current)

    Returns:
        {
            'tables_added':   [table names in B but not A],
            'tables_removed': [table names in A but not B],
            'fields_added':   {table_name: [fields in B but not A]},
            'fields_removed': {table_name: [fields in A but not B]},
            'record_count_delta': {table_name: int_delta_b_minus_a},
        }
    """
    tables_a = (data_a.get('tables', {}) or {})
    tables_b = (data_b.get('tables', {}) or {})

    names_a = set(tables_a.keys())
    names_b = set(tables_b.keys())

    added = sorted(names_b - names_a)
    removed = sorted(names_a - names_b)

    fields_added = {}
    fields_removed = {}
    record_delta = {}

    for name in names_a | names_b:
        fa = set((tables_a.get(name) or {}).get('fields', []) or [])
        fb = set((tables_b.get(name) or {}).get('fields', []) or [])
        added_fields = sorted(fb - fa)
        removed_fields = sorted(fa - fb)
        if added_fields:
            fields_added[name] = added_fields
        if removed_fields:
            fields_removed[name] = removed_fields
        # Record delta
        ra = len((tables_a.get(name) or {}).get('records', []) or [])
        rb = len((tables_b.get(name) or {}).get('records', []) or [])
        if ra != rb:
            record_delta[name] = rb - ra

    return {
        'tables_added': added,
        'tables_removed': removed,
        'fields_added': fields_added,
        'fields_removed': fields_removed,
        'record_count_delta': record_delta,
    }


def validate_schedule(data, profile='commercial', subject=None):
    """Unified XER validation using the Finding/ValidationReport framework.

    Replaces the old `_validate_field_counts` style of ad-hoc issue lists
    with severity-graded findings in a single report.

    Checks performed:
      - File field-count validation (WARN on version-specific mismatch)
      - AACE 31R-03 §3.1: at least one PROJECT record (BLOCK if zero)
      - AACE 31R-03 §3.3: at least one CALENDAR record (BLOCK if zero)
      - AACE 31R-03 §3.4: WBS depth within profile range (BLOCK if below min, WARN if above max)
      - AACE 31R-03 §3.5: activity count within profile range (WARN outside)
      - AACE 31R-03 §3.6: TASKPRED relationships present when tasks exist (BLOCK otherwise)
      - AACE 53R-06 §4.2: holiday list empty on calendar named "...with holidays..." (WARN)
      - INFO: multi-project XER
      - INFO: unusual encoding used for decoding

    Args:
        data: parsed XER dict
        profile: 'commercial' | 'nuclear' | 'mining' (from config_profiles)
        subject: optional subject string for the report (defaults to filename)

    Returns:
        ValidationReport
    """
    if ValidationReport is None or Finding is None or get_profile is None:
        raise RuntimeError('_cpp_common is not on sys.path; cannot build ValidationReport')

    prof = get_profile(profile)
    subject = subject or data.get('filename') or data.get('filepath') or '<in-memory XER>'
    report = ValidationReport(subject=subject, context={'profile': profile})

    # ── File field-count validation ────────────────────────────────
    version = (data.get('ermhdr', {}) or {}).get('version', '')
    major = version.split('.')[0] if version else ''
    expected_schema = TABLE_FIELD_COUNTS_BY_VERSION.get(major)
    if expected_schema:
        for table_name, table_data in (data.get('tables', {}) or {}).items():
            field_count = len(table_data.get('fields', []) or [])
            if table_name in expected_schema:
                expected = expected_schema[table_name]
                if field_count != expected:
                    report.add(Finding(
                        severity=WARN,
                        check_id='XER-FIELD-COUNT',
                        message=f'{table_name} has {field_count} fields; expected {expected} for P6 {version}',
                        evidence={'table': table_name, 'expected': expected, 'found': field_count, 'p6_version': version},
                        reference='AACE 53R-06 §4.1 / P6 schema',
                    ))
    else:
        report.add(Finding(
            severity=INFO,
            check_id='XER-FIELD-COUNT-SKIPPED',
            message=f'P6 version {version!r} not in schema map — field-count check skipped',
            evidence={'p6_version': version},
            reference='AACE 53R-06 §4.1',
        ))

    # ── PROJECT record count ────────────────────────────────
    projects = get_table(data, 'PROJECT')
    if len(projects) == 0:
        report.add(Finding(
            severity=BLOCK,
            check_id='AACE-31R-03-PROJECT-MISSING',
            message='No PROJECT records found in the XER — file is not a valid schedule',
            evidence={'project_count': 0},
            reference='AACE 31R-03 §3.1',
        ))
    elif len(projects) > 1:
        report.add(Finding(
            severity=INFO,
            check_id='XER-MULTI-PROJECT',
            message=f'Multi-project XER — {len(projects)} PROJECT records found',
            evidence={'project_count': len(projects),
                      'project_ids': [p.get('proj_id', '') for p in projects]},
            reference='AACE 31R-03 §3.1',
        ))

    # ── CALENDAR record count ────────────────────────────────
    calendars = get_table(data, 'CALENDAR')
    if len(calendars) == 0:
        report.add(Finding(
            severity=BLOCK,
            check_id='AACE-31R-03-CALENDAR-MISSING',
            message='No CALENDAR records found in the XER — activity durations cannot be computed',
            evidence={'calendar_count': 0},
            reference='AACE 31R-03 §3.3',
        ))

    # ── WBS depth ────────────────────────────────
    wbs_map = build_wbs_map(data)
    wbs_depths = []
    for wbs_id, wbs in wbs_map.items():
        path = wbs.get('_full_path', '') or ''
        depth = len([seg for seg in path.split(' > ') if seg])
        wbs_depths.append(depth)
    max_wbs_depth = max(wbs_depths) if wbs_depths else 0
    wbs_min = prof.get('wbs_depth_min', 3)
    wbs_max = prof.get('wbs_depth_max', 6)
    if wbs_map:
        if max_wbs_depth < wbs_min:
            report.add(Finding(
                severity=BLOCK,
                check_id='AACE-31R-03-WBS-DEPTH-LOW',
                message=f'WBS is too shallow — max depth {max_wbs_depth} < {wbs_min} ({profile} profile minimum)',
                evidence={'max_wbs_depth': max_wbs_depth, 'min_required': wbs_min, 'profile': profile},
                reference='AACE 31R-03 §3.4',
            ))
        elif max_wbs_depth > wbs_max:
            report.add(Finding(
                severity=WARN,
                check_id='AACE-31R-03-WBS-DEPTH-HIGH',
                message=f'WBS is unusually deep — max depth {max_wbs_depth} > {wbs_max} ({profile} profile maximum)',
                evidence={'max_wbs_depth': max_wbs_depth, 'max_allowed': wbs_max, 'profile': profile},
                reference='AACE 31R-03 §3.4',
            ))

    # ── Activity count ────────────────────────────────
    tasks = get_table(data, 'TASK')
    real_tasks = [t for t in tasks if t.get('task_type', '') not in ('TT_LOE', 'TT_WBS')]
    act_count = len(real_tasks)
    act_min = prof.get('activity_count_min', 50)
    act_max = prof.get('activity_count_max', 10000)
    if act_count < act_min:
        report.add(Finding(
            severity=WARN,
            check_id='AACE-31R-03-ACTIVITY-COUNT-LOW',
            message=f'Activity count {act_count} is below {profile} profile minimum of {act_min}',
            evidence={'activity_count': act_count, 'min': act_min, 'profile': profile},
            reference='AACE 31R-03 §3.5',
        ))
    elif act_count > act_max:
        report.add(Finding(
            severity=WARN,
            check_id='AACE-31R-03-ACTIVITY-COUNT-HIGH',
            message=f'Activity count {act_count} exceeds {profile} profile maximum of {act_max}',
            evidence={'activity_count': act_count, 'max': act_max, 'profile': profile},
            reference='AACE 31R-03 §3.5',
        ))

    # ── TASKPRED presence when tasks exist ────────────────────────────────
    # AACE 31R-03 §3.6 / DCMA 14-Point #1: every non-summary, non-milestone
    # activity must participate in at least one logic tie. Milestones and
    # LOE/WBS rows are excluded because:
    #   - LOE / WBS-summary rows are roll-ups, not work items;
    #   - milestones are zero-duration markers and a milestone-only schedule
    #     can be valid without ties.
    # The previous logic globbed TASKPRED count instead of checking whether
    # the *real work* tasks were actually wired in — meaning a 1000-LOE/WBS
    # network with zero TASKPRED slipped through, and a real-tasks network
    # could pass when the only TASKPRED rows tied milestones, never the work.
    taskpred = get_table(data, 'TASKPRED')
    non_summary_tasks = [
        t for t in tasks
        if t.get('task_type', '') not in ('TT_LOE', 'TT_WBS', 'TT_Mile', 'TT_FinMile')
    ]
    non_summary_task_ids = {t.get('task_id', '') for t in non_summary_tasks}
    # A TASKPRED row counts iff either endpoint is a real work task.
    real_taskpred_rows = [
        p for p in taskpred
        if p.get('task_id', '') in non_summary_task_ids
        or p.get('pred_task_id', '') in non_summary_task_ids
    ]
    if non_summary_tasks and not real_taskpred_rows:
        report.add(Finding(
            severity=BLOCK,
            check_id='AACE-31R-03-NO-TASKPRED',
            message=(
                f'Schedule has {len(non_summary_tasks)} non-summary, non-milestone '
                f'activities but zero TASKPRED relationships tie any of them — no work logic exists'
            ),
            evidence={
                'non_summary_task_count': len(non_summary_tasks),
                'total_taskpred_count': len(taskpred),
                'real_work_taskpred_count': 0,
            },
            reference='AACE 31R-03 §3.6 / DCMA 14-Point #1',
        ))

    # ── Calendar-with-holidays sanity ────────────────────────────────
    cal_map = get_calendar_map(data)
    for cid, cal in cal_map.items():
        name = (cal.get('clndr_name') or '').lower()
        if 'holiday' in name and 'no holiday' not in name:
            if not cal.get('holidays'):
                report.add(Finding(
                    severity=WARN,
                    check_id='XER-CALENDAR-HOLIDAYS-EMPTY',
                    message=f"Calendar {cal.get('clndr_name')!r} is named 'with holidays' but has zero holidays parsed",
                    evidence={'clndr_id': cid, 'clndr_name': cal.get('clndr_name', '')},
                    reference='AACE 53R-06 §4.2',
                ))

    # ── Encoding info ────────────────────────────────
    enc = (data.get('encoding_used') or '').lower()
    if enc and enc not in ('utf-8', 'utf-8-sig', 'cp1252'):
        report.add(Finding(
            severity=INFO,
            check_id='XER-ENCODING-UNUSUAL',
            message=f'XER was decoded with unusual encoding {enc!r}',
            evidence={'encoding_used': enc},
            reference='AACE 53R-06 §4.1',
        ))

    return report


def aace_31r_compliance(data, profile='commercial'):
    """AACE 31R-03 compliance score (0–100) for an XER schedule.

    Scoring:
      - Start at 100
      - Subtract 20 per BLOCK finding (serious structural defect)
      - Subtract 5 per WARN finding
      - INFO and PASS findings do not subtract
    Grade bands: A=90+, B=80+, C=70+, D=60+, F<60
    Score clamped to [0, 100].

    Returns:
        {
            'score_100': int,
            'grade': 'A' | 'B' | 'C' | 'D' | 'F',
            'findings': ValidationReport,
        }
    """
    if ValidationReport is None:
        raise RuntimeError('_cpp_common is not on sys.path; cannot build ValidationReport')

    report = validate_schedule(data, profile=profile)

    score = 100
    score -= 20 * report.count(BLOCK)
    score -= 5 * report.count(WARN)
    if score < 0:
        score = 0
    if score > 100:
        score = 100

    if score >= 90:
        grade = 'A'
    elif score >= 80:
        grade = 'B'
    elif score >= 70:
        grade = 'C'
    elif score >= 60:
        grade = 'D'
    else:
        grade = 'F'

    return {
        'score_100': score,
        'grade': grade,
        'findings': report,
    }


# ─────────────────────────────────────────────
# XER GENERATION ENGINE
# ─────────────────────────────────────────────

def generate_xer(data, output_path, p6_version='24.12', currency='CAD',
                 module='Project Management', start_time='08:00',
                 end_time='16:00', hrs_per_day=8, hrs_per_week=40,
                 user='admin', user_full_name='Claude Agent',
                 database='dbxDatabaseNoName', export_scope='Project',
                 encoding='utf-8'):
    """
    Generate a valid Primavera P6 XER file from structured data.

    data format:
        Same structure as parse_xer output, or:
        {
            'tables': {
                'TABLE_NAME': {
                    'fields': [...],
                    'records': [{...}, ...]
                }
            }
        }

    When an 'ermhdr' block is present in `data` it is preserved verbatim.
    Otherwise the 9-field P6 header is synthesised from the kwargs.

    Tables are written in P6 24.12 canonical order with CRLF line endings.
    Encoding defaults to utf-8 (pass 'cp1252' for strict legacy P6 compatibility).
    """
    lines = []

    # ERMHDR — prefer the raw header from the source if available.
    # Minimum 5 fields is the smallest form seen in the wild (ERMHDR, version,
    # date, + 2 metadata). Real P6 headers range from 5 to 9 fields depending
    # on version. Preserve whatever the source had.
    raw_ermhdr = data.get('ermhdr', {}).get('raw')
    if raw_ermhdr and isinstance(raw_ermhdr, list) and len(raw_ermhdr) >= 5:
        lines.append('\t'.join(raw_ermhdr))
    else:
        export_date = datetime.now().strftime(P6_DATE_FORMAT)
        ermhdr_parts = [
            'ERMHDR', p6_version, export_date, export_scope,
            user, user_full_name, database, module, currency,
        ]
        lines.append('\t'.join(ermhdr_parts))

    # Write tables in canonical order
    tables = data.get('tables', {})

    # First write tables in canonical order, then any remaining
    written = set()
    for table_name in TABLE_ORDER:
        if table_name in tables:
            _write_table(lines, table_name, tables[table_name])
            written.add(table_name)

    # Any remaining tables not in canonical order
    for table_name in tables:
        if table_name not in written:
            _write_table(lines, table_name, tables[table_name])

    # Write with CRLF line endings
    output_text = '\r\n'.join(lines) + '\r\n'

    with open(output_path, 'w', encoding=encoding, newline='') as f:
        f.write(output_text)

    return output_path


def _write_table(lines, table_name, table_data):
    """Write a single table's %T, %F, and %R lines.

    Asserts row/field-count parity per row before emitting %R — a mismatch
    causes a blank import grid in P6 (see SKILL.md §3). Because each value
    is sourced by .get(field, '') against the canonical fields list, the two
    counts can only diverge if the fields list itself is empty/None or
    mutated mid-loop, but the explicit assertion makes the contract loud and
    fails fast instead of producing a silently broken XER.
    """
    fields = table_data.get('fields', [])
    records = table_data.get('records', [])

    if not fields:
        return

    # %T line
    lines.append(f'%T\t{table_name}')

    # %F line
    lines.append('%F\t' + '\t'.join(fields))

    # %R lines
    for record in records:
        values = []
        for field in fields:
            val = record.get(field, '')
            if val is None:
                val = ''
            values.append(str(val))
        if len(values) != len(fields):
            raise ValueError(
                f"Field count mismatch in table {table_name!r}: "
                f"row has {len(values)} values but %F declared {len(fields)} fields. "
                f"This would produce a blank grid in P6 on import."
            )
        lines.append('%R\t' + '\t'.join(values))


# ─────────────────────────────────────────────
# MIP 3.4 HALF-STEP XER GENERATOR
# ─────────────────────────────────────────────

#: Progress-only fields copied from updated → base in the MIP 3.4 half-step.
#: These capture what actually happened without carrying forward any logic
#: revisions the contractor made between updates.
_HALF_STEP_PROGRESS_FIELDS = [
    'act_start_date',       # actual start (recorded when work began)
    'act_end_date',         # actual finish (recorded when work completed)
    'remain_drtn_hr_cnt',   # remaining duration in hours
    'phys_complete_pct',    # physical percent complete
    'status_code',          # TK_NotStart / TK_Active / TK_Complete
]

#: Early-date fields that are ONLY copied when updated is TK_Complete and
#: base is not — anchors completed activities to their actual positions so the
#: forward pass of a CPM re-run lands the completion correctly.
_HALF_STEP_COMPLETION_ANCHOR_FIELDS = [
    'early_start_date',
    'early_end_date',
]

#: Fields that MUST NOT be copied even if they appear in updated. These carry
#: the contractor's logic-revision intent, which the half-step purposely strips.
_HALF_STEP_FORBIDDEN_FIELDS = frozenset({
    'target_drtn_hr_cnt',   # original planned duration — preserve base intent
    'task_name',
    'task_type',
    'wbs_id',
    'clndr_id',
})


def compute_half_step_xer(base_xer_path, updated_xer_path, output_xer_path):
    """Generate an AACE 29R-03 MIP 3.4 half-step XER from two sequential schedule updates.

    AACE 29R-03 MIP 3.4 — Modelled / Additive / Multiple Base — Contemporaneous
    Split: start with the period-START schedule (base), apply ONLY the progress
    fields (actual dates, remaining duration, percent complete, status) from the
    next update, and output a "half-step" schedule.  The result isolates the
    *progress impact* from the *logic-revision impact*: anything that moves in
    the half-step moved because work didn't happen as planned; anything that
    moves between the half-step and the full update moved because the contractor
    revised logic or scope mid-period.

    SmartPM and Plannex ship this as their flagship feature; CPP cpm-engine v2.2
    closes the gap.

    Methodology disclosures
    -----------------------
    * Progress fields are matched by ``task_code`` — the user-visible activity ID.
      This is the stable cross-update key in P6; ``task_id`` is a surrogate that
      changes if the contractor re-exports from a rebuilt project.
    * Logic (TASKPRED rows) is preserved verbatim from the BASE schedule.
      Any logic changes the contractor made in the update are NOT reflected.
    * Resource assignments (TASKRSRC, RSRC, RSRCRATE) are out of scope for v1
      and are preserved from the base unchanged.
    * Activities present in the updated XER but absent from the base are NOT
      added to the half-step — per MIP 3.4, the half-step shows base-logic +
      actual-progress only.  Their task codes are logged in
      ``unmatched_in_updated`` for the analyst's awareness; these are typically
      activities the contractor added in the update (scope adds, splits, etc.).
    * ``early_start_date`` / ``early_end_date`` are copied ONLY when the updated
      task is TK_Complete and the base task is not, to anchor completed activities
      so a CPM re-run places them correctly.  For in-progress and not-started
      activities the scheduler's forward-pass dates are left for the CPM engine
      to recompute from base logic + applied progress.
    * This function does NOT copy ``target_drtn_hr_cnt`` (original planned
      duration — preserving base intent), nor any structural fields
      (task_name, task_type, wbs_id, clndr_id).

    Args:
        base_xer_path (str): Path to the period-START schedule XER.
        updated_xer_path (str): Path to the next-period update XER.
        output_xer_path (str): Destination path for the half-step XER.

    Returns:
        dict: Summary of what was done::

            {
                'matched_count': int,           # tasks matched by task_code
                'unmatched_in_base': [...],     # task_codes in base but not updated (kept as-is)
                'unmatched_in_updated': [...],  # task_codes in updated but not base (NOT added)
                'progressed_count': int,        # tasks that received non-empty progress fields
                'output_path': str,
            }

        ``unmatched_in_updated`` is forensically important: these are activities
        the contractor added in the revision period.  They belong to the
        logic-revision layer, not the progress layer.

    Attribution:
        AACE 29R-03 MIP 3.4 "Modelled / Additive / Multiple Base — Contemporaneous
        Split"; CPP cpm-engine v2.2 half-step generator.
    """
    import copy

    # ── 1. Parse both XERs ──────────────────────────────────────
    base_data = parse_xer(base_xer_path)
    updated_data = parse_xer(updated_xer_path)

    # ── 2. Build task_code → record maps ────────────────────────
    base_tasks = get_table(base_data, 'TASK')
    updated_tasks = get_table(updated_data, 'TASK')

    updated_by_code = {t.get('task_code', ''): t for t in updated_tasks
                       if t.get('task_code', '')}

    base_codes = {t.get('task_code', '') for t in base_tasks if t.get('task_code', '')}
    updated_codes = set(updated_by_code.keys())

    unmatched_in_base = sorted(base_codes - updated_codes)
    unmatched_in_updated = sorted(updated_codes - base_codes)

    # ── 3. Deep-copy base data (all tables preserved intact) ─────
    half_step_data = copy.deepcopy(base_data)

    # ── 4. Apply progress fields to matched TASK records ─────────
    matched_count = 0
    progressed_count = 0

    half_step_tasks = get_table(half_step_data, 'TASK')
    for task in half_step_tasks:
        code = task.get('task_code', '')
        if not code or code not in updated_by_code:
            # Not matched — keep as-is (base state: not-started, base duration)
            continue

        matched_count += 1
        upd = updated_by_code[code]

        # Determine completion state of both sides for the anchor-field logic
        upd_status = upd.get('status_code', '')
        base_status = task.get('status_code', '')
        upd_complete = (upd_status == COMPLETE_STATUS)
        base_not_complete = (base_status != COMPLETE_STATUS)

        # Track whether any progress was applied — defined as: at least one
        # field value from updated differs from the base value AND is non-empty.
        # Copying TK_NotStart onto a TK_NotStart base task is not progress.
        applied_any = False

        # Apply core progress fields.
        # A field counts as "progress applied" when the updated value is
        # non-empty AND different from the base value.  Copying an identical
        # value (e.g. TK_NotStart → TK_NotStart) is not real progress and
        # must not increment progressed_count.
        for field in _HALF_STEP_PROGRESS_FIELDS:
            val = upd.get(field, '')
            base_val = task.get(field, '')
            if val and val != base_val:
                task[field] = val
                applied_any = True

        # Apply completion-anchor early dates only when updated is TK_Complete
        # and base is not — so a CPM re-run can anchor completed work.
        if upd_complete and base_not_complete:
            for field in _HALF_STEP_COMPLETION_ANCHOR_FIELDS:
                val = upd.get(field, '')
                if val:
                    task[field] = val
                    # Don't set applied_any for anchor fields alone — the status
                    # copy above already sets applied_any when TK_Complete is copied.

        if applied_any:
            progressed_count += 1

    # ── 5. Inject MIP 3.4 attribution into PROJECT row ───────────
    # Write a note into the proj_url or web_site field (commonly unused in
    # construction schedules, round-trips cleanly through P6 import).
    attribution_text = (
        'Half-step XER produced by CPP cpm-engine v2.2 per AACE 29R-03 MIP 3.4.'
    )
    project_records = get_table(half_step_data, 'PROJECT')
    for proj in project_records:
        # Use proj_url if the field exists in this XER's PROJECT fields; fall
        # back to web_site.  If neither is present, skip (don't corrupt the row).
        proj_fields = half_step_data['tables'].get('PROJECT', {}).get('fields', [])
        if 'proj_url' in proj_fields:
            proj['proj_url'] = attribution_text
        elif 'web_site' in proj_fields:
            proj['web_site'] = attribution_text
        # If neither field is present the attribution lives only in the docstring.

    # ── 6. Write the half-step XER ───────────────────────────────
    generate_xer(half_step_data, output_xer_path)

    return {
        'matched_count': matched_count,
        'unmatched_in_base': unmatched_in_base,
        'unmatched_in_updated': unmatched_in_updated,
        'progressed_count': progressed_count,
        'output_path': str(output_xer_path),
    }


# ─────────────────────────────────────────────
# CLI INTERFACE
# ─────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]

    if command == 'parse':
        if len(sys.argv) < 3:
            print("Usage: xer_parser.py parse <file.xer> [--summary] [--json output.json]")
            sys.exit(1)

        filepath = sys.argv[2]
        data = parse_xer(filepath)

        if '--summary' in sys.argv:
            print_summary(data)

        if '--json' in sys.argv:
            json_idx = sys.argv.index('--json')
            if json_idx + 1 < len(sys.argv):
                json_path = sys.argv[json_idx + 1]
                # Custom serializer for summary
                summary = generate_summary(data)
                with open(json_path, 'w') as f:
                    json.dump(summary, f, indent=2, default=str)
                print(f"JSON summary saved to: {json_path}")

        if '--summary' not in sys.argv and '--json' not in sys.argv:
            # Default: print basic info
            print(f"Parsed: {data['filename']}")
            print(f"Tables: {list(data['tables'].keys())}")
            for tname, tdata in data['tables'].items():
                print(f"  {tname}: {len(tdata['records'])} records")

    elif command == 'generate':
        if len(sys.argv) < 4:
            print("Usage: xer_parser.py generate <input.json> <output.xer>")
            sys.exit(1)

        json_path = sys.argv[2]
        output_path = sys.argv[3]

        with open(json_path) as f:
            data = json.load(f)

        generate_xer(data, output_path)
        print(f"XER file generated: {output_path}")

    else:
        print(f"Unknown command: {command}")
        print("Commands: parse, generate")
        sys.exit(1)


if __name__ == '__main__':
    main()
