"""Regression: DCMA-14 reads a blank TASK.clndr_id as the project calendar, as
P6 and MS Project schedule it.

MPXJ writes TASK.clndr_id blank for every MS Project task with no task-level
calendar. Until the bundled parser carried ``resolve_task_calendars``,
``dcma14.dcma_14_assess`` read the raw TASK rows, and ``_hrs_to_days`` turns a
blank id into a flat 8 h/day whatever the project calendar says. On an 8 h/day
project nothing moves; on any other project calendar the High Float (#6) and
High Duration (#8) day counts, and the CPLI float (#13), were wrong.
Measured on the fixture below with the parser this repository bundled
before: 8 of 12 assessed with blank ids against 10 of 12 with explicit ids,
High Float 25 % against 0 % and High Duration 100 % against 0 %.

The fixture: a Mon-Fri 10 h/day project calendar (TEN), with an 8 h/day
calendar first in the table that the blank rows must NOT land on, and

    START  ->  A  400 h remaining, 400 h total float  ->  FIN
    START  ->  B  440 h remaining,   0 h total float  ->  FIN

On TEN, A is 40 working days of duration and float and B is exactly 44 days,
all inside DCMA's > 44 day limits: High Float 0 %, High Duration 0 %. Read at
8 h/day, A is 50 and 50 and B is 55: High Float 1 of 4 (25 %), High Duration
2 of 2 (100 %), both over the 5 % threshold.
"""
import os
import sys
import tempfile
import warnings as _warnings

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, '..', 'scripts'))

from xer_parser import parse_xer  # noqa: E402
from dcma14 import dcma_14_assess  # noqa: E402

TAB = '\t'
_TEN_HOURS = '(0||0(s|07:00|f|12:00)())(0||1(s|12:30|f|17:30)())'
_EIGHT_HOURS = '(0||0(s|08:00|f|12:00)())(0||1(s|13:00|f|17:00)())'


def _mon_fri(shift):
    return ('(0||CalendarData()((0||DaysOfWeek()((0||1()())'
            + ''.join('(0||%d()(%s))' % (d, shift) for d in range(2, 7))
            + '(0||7()())))(0||Exceptions()())))')


_TASK_COLS = ['task_id', 'task_code', 'task_name', 'proj_id', 'wbs_id',
              'clndr_id', 'status_code', 'task_type', 'target_drtn_hr_cnt',
              'remain_drtn_hr_cnt', 'total_float_hr_cnt', 'early_start_date',
              'early_end_date', 'late_start_date', 'late_end_date',
              'target_start_date', 'target_end_date', 'driving_path_flag',
              'cstr_type', 'cstr_date']


def _task(tid, code, ttype, hrs, tf, es, ef, clndr):
    return [tid, code, 'Neutral ' + code, '1', 'W1', clndr, 'TK_NotStart',
            ttype, str(hrs), str(hrs), str(tf), es, ef, es, ef, es, ef, 'N', '', '']


def _build_xer(*, task_clndr, project_clndr='TEN', ten_default='N'):
    rows = [
        _task('1', 'START', 'TT_Mile', 0, 0, '2026-09-21 07:00', '2026-09-21 07:00', task_clndr),
        _task('2', 'A', 'TT_Task', 400, 400, '2026-09-21 07:00', '2026-11-13 17:30', task_clndr),
        _task('3', 'B', 'TT_Task', 440, 0, '2026-09-21 07:00', '2026-11-19 17:30', task_clndr),
        _task('4', 'FIN', 'TT_FinMile', 0, 0, '2026-11-19 17:30', '2026-11-19 17:30', task_clndr),
    ]
    lines = [
        TAB.join(['ERMHDR', '20.12', '2026-09-21', 'Project', 'admin', 'admin',
                  'dbxDatabaseNoName', 'Project Management', 'USD']),
        TAB.join(['%T', 'PROJECT']),
        TAB.join(['%F', 'proj_id', 'proj_short_name', 'last_recalc_date',
                  'plan_end_date', 'scd_end_date', 'clndr_id']),
        TAB.join(['%R', '1', 'NEUTRAL', '2026-09-21 07:00', '',
                  '2026-11-19 17:30', project_clndr]),
        TAB.join(['%T', 'PROJWBS']),
        TAB.join(['%F', 'wbs_id', 'parent_wbs_id', 'wbs_name',
                  'wbs_short_name', 'proj_id']),
        TAB.join(['%R', 'W1', '', 'Root', 'W1', '1']),
        TAB.join(['%T', 'CALENDAR']),
        TAB.join(['%F', 'clndr_id', 'default_flag', 'clndr_name', 'clndr_type',
                  'day_hr_cnt', 'week_hr_cnt', 'clndr_data']),
        TAB.join(['%R', 'EIGHT', 'N', 'Eight Hour', 'CA_Base', '8', '40',
                  _mon_fri(_EIGHT_HOURS)]),
        TAB.join(['%R', 'TEN', ten_default, 'Ten Hour', 'CA_Base', '10', '50',
                  _mon_fri(_TEN_HOURS)]),
        TAB.join(['%T', 'TASK']),
        TAB.join(['%F'] + _TASK_COLS),
    ]
    lines += [TAB.join(['%R'] + r) for r in rows]
    lines += [
        TAB.join(['%T', 'TASKPRED']),
        TAB.join(['%F', 'task_pred_id', 'task_id', 'pred_task_id',
                  'pred_type', 'lag_hr_cnt']),
        TAB.join(['%R', '1', '2', '1', 'PR_FS', '0']),
        TAB.join(['%R', '2', '3', '1', 'PR_FS', '0']),
        TAB.join(['%R', '3', '4', '2', 'PR_FS', '0']),
        TAB.join(['%R', '4', '4', '3', 'PR_FS', '0']),
        '%E',
    ]
    return '\r\n'.join(lines) + '\r\n'


def _assess(xer_text):
    with tempfile.NamedTemporaryFile('w', suffix='.xer', delete=False,
                                     encoding='utf-8') as f:
        f.write(xer_text)
        path = f.name
    try:
        with _warnings.catch_warnings():
            _warnings.simplefilter('ignore')
            return dcma_14_assess(parse_xer(path))
    finally:
        os.unlink(path)


EXPLICIT = _assess(_build_xer(task_clndr='TEN'))
BLANK = _assess(_build_xer(task_clndr=''))


def _checks(result):
    return {k: (v['severity'], v['value']) for k, v in result['per_check'].items()}


def _calendar_findings(result):
    return [f for f in result['report'].findings if f.check_id == 'DCMA-Ext-TaskCalendar']


def test_explicit_fixture_is_the_p6_answer():
    """The fixture measures what the docstring says it does."""
    assert EXPLICIT['per_check']['DCMA-06-HighFloat']['value'] == 0.0
    assert EXPLICIT['per_check']['DCMA-08-HighDuration']['value'] == 0.0


def test_blank_ids_are_read_on_the_project_calendar_not_at_8_hours_a_day():
    assert BLANK['per_check']['DCMA-06-HighFloat']['value'] == 0.0      # was 25.0
    assert BLANK['per_check']['DCMA-08-HighDuration']['value'] == 0.0   # was 100.0


def test_every_check_scores_the_same_as_with_explicit_ids():
    assert _checks(BLANK) == _checks(EXPLICIT)
    assert (BLANK['dcma_score'], BLANK['dcma_max']) == (EXPLICIT['dcma_score'], EXPLICIT['dcma_max'])


def test_the_resolution_is_disclosed_not_warned():
    res = BLANK['calendar_resolution']
    assert res['resolved_by_fallback_count'] == 4
    assert res['fallback_calendars'] == [
        {'clndr_id': 'TEN', 'clndr_name': 'Ten Hour', 'tier': 'project', 'task_count': 4}]
    assert res['unresolved_count'] == 0
    assert _calendar_findings(BLANK) == []


def test_explicit_calendars_add_nothing():
    assert EXPLICIT['calendar_resolution']['resolved_by_fallback_count'] == 0
    assert EXPLICIT['calendar_resolution']['unresolved_count'] == 0
    assert _calendar_findings(EXPLICIT) == []


def test_the_default_flag_calendar_is_used_when_the_project_names_none():
    r = _assess(_build_xer(task_clndr='', project_clndr='', ten_default='Y'))
    assert r['calendar_resolution']['fallback_calendars'][0]['tier'] == 'default'
    assert _checks(r) == _checks(EXPLICIT)


def test_no_usable_calendar_is_a_visible_warning_not_a_silent_8_hour_day():
    r = _assess(_build_xer(task_clndr='', project_clndr=''))
    res = r['calendar_resolution']
    assert res['unresolved_count'] == 4
    assert {u['reason'] for u in res['unresolved']} == {'blank'}
    found = _calendar_findings(r)
    assert len(found) == 1 and found[0].severity == 'WARN'
    assert '4 ' in found[0].message and '8 h/day' in found[0].message
    assert found[0].evidence['unresolved'] == res['unresolved']
    # The score still counts: the warning is outside it, like the other extensions.
    assert r['dcma_max'] == EXPLICIT['dcma_max']
