#!/usr/bin/env python3
"""The blank lag calendar and the corrupt calendar record, read as P6 schedules
them (2026-10-28).

Run with: python tests/test_blank_lag_calendar_and_corrupt_calendar_2026_10_28.py

- **A blank relationship-lag calendar is the successor's.** P6 23.12.1 lays a
  lag on the successor's calendar when SCHEDOPTIONS
  sched_calendar_on_relationship_lag is blank (measured 11-Oct-2026); with no
  SCHEDOPTIONS table it uses the predecessor's. v0.6.0 read a blank as the
  predecessor's, in Check 5 and in Check 2's trace. A value P6 exports without
  the rcal_ prefix ('Successor') is read as its rcal_ token.
- **A corrupt calendar record is P6's internal Standard.** The bundled parser
  is cpp-xer-parser v0.5.0: a record with finish-first slot pairs and a
  clndr_type that is not CA_Base, CA_Rsrc or CA_Project is read Monday to
  Friday, eight hours a day, no exceptions, as P6 schedules it. v0.6.0 (parser
  v0.4.0) read it as the week it declares, so a Saturday broke a driving tie
  P6's own dates show. results['calendar_corrupt_alerts'] lists the parser's
  alert for each such record.

The tests marked [discriminating] fail on v0.6.0. The two that trace need
cpp-cpm-engine on the path and skip without it. Every fixture is built in this
file; no real export is copied.
"""
import os
import sys
import tempfile
import unittest
import warnings as _warnings

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, '..', 'scripts'))

from xer_parser import parse_xer  # noqa: E402
import driving_path  # noqa: E402
from cp_validator import _detect_schedule_options, validate_critical_path  # noqa: E402

TAB = '\t'


def _week(days, slot):
    """A DaysOfWeek blob working `days` (P6 1=Sun..7=Sat) on `slot`."""
    return ('(0||CalendarData()((0||DaysOfWeek()('
            + ''.join('(0||%d()(%s))' % (d, slot if d in days else '') for d in range(1, 8))
            + '))(0||Exceptions()())))')


_START_FIRST = '(0||0(s|08:00|f|12:00)())(0||1(s|13:00|f|17:00)())'
_FINISH_FIRST = '(0||0(f|12:00|s|08:00)())(0||1(f|17:00|s|13:00)())'
_FINISH_FIRST_TEN = '(0||0(f|12:00|s|07:00)())(0||1(f|18:00|s|13:00)())'

# (clndr_id, name, clndr_type, day_hr_cnt, blob)
_CALENDARS = [
    ('C5', 'Five Day', 'CA_Base', '8', _week(range(2, 7), _START_FIRST)),
    ('C7', 'Seven Day', 'CA_Base', '8', _week(range(1, 8), _START_FIRST)),
    # Corrupt: finish-first slots and an illegal type, declaring Monday to Saturday.
    ('CX', 'Six Day Site', 'CT_Project', '8', _week(range(2, 8), _FINISH_FIRST)),
    ('CX10', 'Six Day Long', 'CT_Project', '10', _week(range(2, 8), _FINISH_FIRST_TEN)),
]

_TASK_COLS = ['task_id', 'task_code', 'task_name', 'proj_id', 'wbs_id',
              'clndr_id', 'status_code', 'task_type', 'target_drtn_hr_cnt',
              'remain_drtn_hr_cnt', 'total_float_hr_cnt', 'early_start_date',
              'early_end_date', 'restart_date', 'reend_date',
              'late_start_date', 'late_end_date', 'target_start_date',
              'target_end_date', 'driving_path_flag', 'cstr_type', 'cstr_date']


def _row(tid, code, clndr, hrs, es, ef, ttype='TT_Task'):
    """An unstarted activity with no float: its late dates are its early ones."""
    return [tid, code, 'Neutral ' + code, '1', 'W1', clndr, 'TK_NotStart', ttype,
            str(hrs), str(hrs), '0', es, ef, es, ef, es, ef, es, ef, 'Y', '', '']


def _xer(tasks, rels, lag_calendar=None):
    """``lag_calendar`` None writes no SCHEDOPTIONS table; '' writes the field blank."""
    lines = [
        TAB.join(['ERMHDR', '24.12', '2026-10-28', 'Project', 'admin', 'Neutral', 'db',
                  'Project Management', 'CAD']),
        TAB.join(['%T', 'PROJECT']),
        TAB.join(['%F', 'proj_id', 'proj_short_name', 'last_recalc_date', 'plan_end_date',
                  'scd_end_date', 'clndr_id']),
        TAB.join(['%R', '1', 'NEUTRAL', '2026-08-31 08:00', '', '2026-09-10 17:00', 'C5']),
        TAB.join(['%T', 'PROJWBS']),
        TAB.join(['%F', 'wbs_id', 'parent_wbs_id', 'wbs_name', 'wbs_short_name', 'proj_id']),
        TAB.join(['%R', 'W1', '', 'Root', 'W1', '1']),
        TAB.join(['%T', 'CALENDAR']),
        TAB.join(['%F', 'clndr_id', 'clndr_name', 'clndr_type', 'day_hr_cnt', 'week_hr_cnt',
                  'clndr_data']),
    ]
    used = {row[5] for row in tasks} | {'C5'}   # C5 is the project calendar
    lines += [TAB.join(['%R', cid, name, ctype, hrs, '40', blob])
              for cid, name, ctype, hrs, blob in _CALENDARS if cid in used]
    lines += [TAB.join(['%T', 'TASK']), TAB.join(['%F'] + _TASK_COLS)]
    lines += [TAB.join(['%R'] + row) for row in tasks]
    lines += [
        TAB.join(['%T', 'TASKPRED']),
        TAB.join(['%F', 'task_pred_id', 'task_id', 'pred_task_id', 'pred_type', 'lag_hr_cnt']),
    ]
    lines += [TAB.join(['%R', str(i), s, p, 'PR_FS', str(lag)])
              for i, (s, p, lag) in enumerate(rels, 1)]
    if lag_calendar is not None:
        lines += [
            TAB.join(['%T', 'SCHEDOPTIONS']),
            TAB.join(['%F', 'schedoptions_id', 'proj_id', 'sched_retained_logic',
                      'sched_progress_override', 'sched_calendar_on_relationship_lag',
                      'sched_lag_early_start_flag']),
            TAB.join(['%R', '1', '1', 'Y', 'N', lag_calendar, 'Y']),
        ]
    lines.append('%E')
    return '\r\n'.join(lines) + '\r\n'


def _validate(xer_text):
    with tempfile.NamedTemporaryFile('w', suffix='.xer', delete=False, encoding='utf-8',
                                     newline='') as f:
        f.write(xer_text)
        path = f.name
    try:
        with _warnings.catch_warnings():
            _warnings.simplefilter('ignore')
            return validate_critical_path(parse_xer(path))
    finally:
        os.unlink(path)


def _needs_engine():
    """Skip a test that traces: the trace needs cpp-cpm-engine's calendar arithmetic."""
    if driving_path.minute_date_helpers() is None:
        raise unittest.SkipTest(
            "cpp-cpm-engine's cpm module is not importable, so the driving path "
            "cannot be traced")


def _options(lag_calendar):
    rows = [] if lag_calendar is None else [
        {'proj_id': '1', 'sched_calendar_on_relationship_lag': lag_calendar}]
    return _detect_schedule_options({'tables': {'SCHEDOPTIONS': {'records': rows}}}, '1')


# ── the relationship-lag calendar setting ────────────────────────────────

def test_a_blank_setting_is_the_successor_calendar():
    # [discriminating] v0.6.0 read it as rcal_Predecessor.
    so = _options('')
    assert so['relationship_lag_calendar'] == 'rcal_Successor'
    assert so['lag_calendar_role'] == 'successor'
    assert so['relationship_lag_calendar_source'] == (
        'SCHEDOPTIONS sched_calendar_on_relationship_lag blank; P6 schedules a '
        'blank lag calendar on the successor calendar (rcal_Successor), '
        'measured 11-Oct-2026')
    assert _options('   ')['relationship_lag_calendar'] == 'rcal_Successor'


def test_no_table_is_still_the_predecessor_calendar():
    so = _options(None)
    assert so['relationship_lag_calendar'] == 'rcal_Predecessor'
    assert so['lag_calendar_role'] == 'predecessor'
    assert 'absent' in so['relationship_lag_calendar_source']


def test_successor_as_p6_exports_it_is_read_as_rcal_successor():
    # [discriminating] v0.6.0 handed 'Successor' on raw.
    so = _options('Successor')
    assert so['relationship_lag_calendar'] == 'rcal_Successor'
    assert so['lag_calendar_role'] == 'successor'
    assert so['relationship_lag_calendar_source'] == (
        'SCHEDOPTIONS sched_calendar_on_relationship_lag=Successor '
        '(as P6 exports it; read as rcal_Successor)')


def test_a_named_setting_is_read_as_written():
    for token, role in (('rcal_Predecessor', 'predecessor'), ('rcal_Successor', 'successor')):
        so = _options(token)
        assert so['relationship_lag_calendar'] == token
        assert so['lag_calendar_role'] == role
        assert so['relationship_lag_calendar_source'] == (
            'SCHEDOPTIONS sched_calendar_on_relationship_lag=%s' % token)


# A on the seven-day calendar finishes Friday 4 Sep 17:00; B, on the five-day
# calendar, follows FS with a 16 h lag. On B's calendar the lag runs Monday and
# Tuesday, and B starts Wednesday 9 Sep, as stored. On A's it runs the weekend
# and B could start Monday, two days early: the link would not drive.
_LAG_TASKS = [
    _row('1', 'S', 'C5', 8, '2026-08-31 08:00', '2026-08-31 17:00'),
    _row('2', 'A', 'C7', 32, '2026-09-01 08:00', '2026-09-04 17:00'),
    _row('3', 'B', 'C5', 16, '2026-09-09 08:00', '2026-09-10 17:00'),
    _row('4', 'F', 'C5', 0, '2026-09-10 17:00', '2026-09-10 17:00', ttype='TT_FinMile'),
]
_LAG_RELS = [('2', '1', 0), ('3', '2', 16), ('4', '3', 0)]


def test_a_blank_setting_traces_the_lag_on_the_successor_calendar():
    # [discriminating] v0.6.0 walked the lag on A's calendar, broke the path at
    # A -> B and flagged S and A as critical by float alone.
    _needs_engine()
    results = _validate(_xer(_LAG_TASKS, _LAG_RELS, lag_calendar=''))
    cd = results['checks']['constraint_driven']
    assert cd['lpm_basis'] == 'traced', cd['lpm_trace_reason']
    assert cd['lpm_confirmed_false_cp'] == [], cd['lpm_confirmed_false_cp']
    assert results['schedule_options']['lag_calendar_role'] == 'successor'


def test_the_predecessor_setting_still_breaks_that_link():
    """The same file under rcal_Predecessor: the link does not drive, so S and
    A are off the longest path. Shows the fixture tells the two walks apart."""
    _needs_engine()
    cd = _validate(_xer(_LAG_TASKS, _LAG_RELS, lag_calendar='rcal_Predecessor'))[
        'checks']['constraint_driven']
    assert cd['lpm_basis'] == 'traced', cd['lpm_trace_reason']
    assert sorted(cd['lpm_confirmed_false_cp']) == ['1', '2'], cd['lpm_confirmed_false_cp']


# ── a corrupt calendar record ────────────────────────────────────────────

# A and B on the corrupt calendar: A finishes Friday 4 Sep 17:00 and B, FS 0,
# starts Monday 7 Sep, as P6 schedules the record (Monday to Friday). Read as
# the Monday-to-Saturday week it declares, B could start Saturday and the link
# would not drive.
_CORRUPT_TASKS = [
    _row('1', 'S', 'C5', 8, '2026-08-31 08:00', '2026-08-31 17:00'),
    _row('2', 'A', 'CX', 32, '2026-09-01 08:00', '2026-09-04 17:00'),
    _row('3', 'B', 'CX', 16, '2026-09-07 08:00', '2026-09-08 17:00'),
    _row('4', 'F', 'CX', 0, '2026-09-08 17:00', '2026-09-08 17:00', ttype='TT_FinMile'),
]
_CORRUPT_RELS = [('2', '1', 0), ('3', '2', 0), ('4', '3', 0)]


def test_a_corrupt_calendar_is_traced_monday_to_friday():
    # [discriminating] v0.6.0 read the record Monday to Saturday, broke the
    # path at A -> B and flagged S and A.
    _needs_engine()
    results = _validate(_xer(_CORRUPT_TASKS, _CORRUPT_RELS, lag_calendar='rcal_Predecessor'))
    cd = results['checks']['constraint_driven']
    assert cd['lpm_basis'] == 'traced', cd['lpm_trace_reason']
    assert cd['lpm_confirmed_false_cp'] == [], cd['lpm_confirmed_false_cp']


def test_the_corrupt_record_is_reported():
    # [discriminating] results['calendar_corrupt_alerts'] is new.
    results = _validate(_xer(_CORRUPT_TASKS, _CORRUPT_RELS, lag_calendar='rcal_Predecessor'))
    alerts = results['calendar_corrupt_alerts']
    assert len(alerts) == 1, alerts
    assert alerts[0]['context'] == 'calendar-corrupt-p6-fallback'
    assert alerts[0]['message'].startswith('FORENSIC FINDING: calendar CX (Six Day Site)')
    assert _validate(_xer(_LAG_TASKS, _LAG_RELS, lag_calendar=''))[
        'calendar_corrupt_alerts'] == []


def test_a_lag_on_a_corrupt_calendar_is_read_at_eight_hours():
    # [discriminating] The record declares, and its shifts work, ten hours a
    # day; P6 schedules it at eight. -40 h is -5 working days, not -4.
    tasks = [
        _row('1', 'S', 'C5', 8, '2026-08-31 08:00', '2026-08-31 17:00'),
        _row('2', 'P', 'CX10', 40, '2026-09-01 08:00', '2026-09-07 17:00'),
        _row('3', 'Q', 'CX10', 40, '2026-09-02 08:00', '2026-09-08 17:00'),
        _row('4', 'F', 'CX10', 0, '2026-09-08 17:00', '2026-09-08 17:00', ttype='TT_FinMile'),
    ]
    rels = [('2', '1', 0), ('3', '2', -40), ('4', '3', 0)]
    results = _validate(_xer(tasks, rels))   # no SCHEDOPTIONS: the predecessor's calendar
    found = [r['finding'] for r in results['recommendations']
             if r['finding'].startswith('Negative lag')]
    assert len(found) == 1, results['recommendations']
    assert '(-5.0d)' in found[0], found[0]


if __name__ == '__main__':
    tests = [f for name, f in list(globals().items())
             if name.startswith('test_') and callable(f)]
    failed = skipped = 0
    for t in tests:
        try:
            t()
            print(f'ok  {t.__name__}')
        except unittest.SkipTest as e:
            print(f'SKIP {t.__name__}: {e}')
            skipped += 1
        except AssertionError as e:
            print(f'FAIL {t.__name__}: {e}')
            failed += 1
        except Exception as e:
            print(f'FAIL {t.__name__}: {type(e).__name__}: {e}')
            failed += 1
    print('')
    if failed:
        print(f'{failed} / {len(tests)} failures')
        sys.exit(1)
    print(f'{len(tests) - skipped} / {len(tests)} passed, {skipped} skipped')
