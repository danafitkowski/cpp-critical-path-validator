#!/usr/bin/env python3
"""A blank TASK.clndr_id is the project calendar, in the nine checks as well
as in DCMA-14.

Run with: python tests/test_blank_task_calendar_2026_09_29.py

MPXJ writes TASK.clndr_id as an empty string for every MS Project task with
no task-level calendar, and sets PROJECT.clndr_id to the project calendar.
The validator looked the blank id up as it stood and found no calendar, so:

* ``_hrs_to_days`` read the activity's float, and a lag when the activity at
  its other end had no calendar either, at a flat 8 h/day whatever the project
  calendar says (and the LPM cross-check its duration, where that runs);
* Check 3's finish test compared the activity's finish with the network's
  without a working week, so a finish at Friday's close and a network finish
  at Monday's opening fell on different days.

``validate_critical_path`` now takes every row through
``xer_parser.resolve_task_calendars`` first. Both fixtures run on a Mon-Fri
10 h/day project calendar (TEN), with an 8 h/day calendar first in the table
that the blank rows must NOT land on.

The float fixture: eleven activities with 20 h of float, and a critical
chain at -100 h with a 20 h lead on it. On TEN the eleven are 2 working days
from critical, in Check 7's 1-2 day band, and more than ten there is RED; the
critical chain is -10 days and the lead -2. Read at 8 h/day the eleven are
2.5 days, in the 3-5 day band (AMBER), the chain -12.5 and the lead -2.5.

The two-ends fixture (Check 3): two chains end the network, one closing
Friday evening and a start milestone opening Monday morning. No working time
separates them on TEN, so both are terminals. That test needs
cpp-cpm-engine's ``cpm`` module on the path, and is skipped without it.
"""
import os
import sys
import tempfile
import unittest
import warnings as _warnings

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, '..', 'scripts'))

from xer_parser import parse_xer  # noqa: E402
from cp_validator import (  # noqa: E402
    validate_critical_path, generate_dashboard, RATING_GREEN,
    _engine_date_helpers)

TAB = '\t'
CAL = '<cal>'                       # stands for the calendar each row carries
DATA_DATE = '2026-09-21 07:00'      # a Monday morning

_TEN_HOURS = '(0||0(s|07:00|f|12:00)())(0||1(s|12:30|f|17:30)())'
_EIGHT_HOURS = '(0||0(s|08:00|f|12:00)())(0||1(s|13:00|f|17:00)())'


def _mon_fri(shift):
    return ('(0||CalendarData()((0||DaysOfWeek()((0||1()())'
            + ''.join('(0||%d()(%s))' % (d, shift) for d in range(2, 7))
            + '(0||7()())))(0||Exceptions()())))')


_TASK_COLS = ['task_id', 'task_code', 'task_name', 'proj_id', 'wbs_id',
              'clndr_id', 'status_code', 'task_type', 'target_drtn_hr_cnt',
              'remain_drtn_hr_cnt', 'total_float_hr_cnt', 'act_start_date',
              'act_end_date', 'early_start_date', 'early_end_date',
              'late_start_date', 'late_end_date', 'target_start_date',
              'target_end_date', 'driving_path_flag', 'cstr_type', 'cstr_date']


def _needs_engine():
    """Skip a test that needs the engine's working-day arithmetic."""
    if _engine_date_helpers() is None:
        raise unittest.SkipTest(
            "cpp-cpm-engine's cpm module is not importable, so only the same "
            "day counts as finishing with the network")


def _row(tid, code, ttype, hrs, tf, es, ef, *, status='TK_NotStart', drv='N'):
    done = status == 'TK_Complete'
    return [tid, code, 'Neutral ' + code, '1', 'W1', CAL, status, ttype,
            str(hrs), '0' if done else str(hrs), '' if done else str(tf),
            es if done else '', ef if done else '', es, ef, es, ef, es, ef,
            drv, '', '']


def _start():
    """Complete before the data date, so it is nobody's open end."""
    return _row('100', 'START', 'TT_Mile', 0, '', '2026-09-18 17:30',
                '2026-09-18 17:30', status='TK_Complete')


def _float_rows():
    rows = [
        _start(),
        _row('110', 'C1', 'TT_Task', 100, -100, DATA_DATE, '2026-10-02 17:30',
             drv='Y'),
        _row('120', 'FIN', 'TT_FinMile', 0, -100, '2026-10-02 17:30',
             '2026-10-02 17:30', drv='Y'),
    ]
    rows += [_row(str(200 + i), 'N%02d' % i, 'TT_Task', 50, 20, DATA_DATE,
                  '2026-09-25 17:30') for i in range(1, 12)]
    return rows


def _float_rels():
    rels = [('110', '100'), ('120', '110', -20)]      # a 20 h lead into FIN
    for i in range(1, 12):
        rels += [(str(200 + i), '100'), ('120', str(200 + i))]
    return rels


def _two_ends_rows():
    """The commissioning closes Friday evening; the owner's move-in, a start
    milestone, opens Monday morning and sets the network finish."""
    return [
        _start(),
        _row('110', 'F110', 'TT_Task', 50, 0, DATA_DATE, '2026-09-25 17:30',
             drv='Y'),
        _row('150', 'F150', 'TT_Task', 50, 0, '2026-09-28 07:00',
             '2026-10-02 17:30', drv='Y'),
        _row('160', 'F160', 'TT_Task', 50, 0, '2026-09-28 07:00',
             '2026-10-02 17:30'),
        _row('170', 'F170', 'TT_Mile', 0, 0, '2026-10-05 07:00',
             '2026-10-05 07:00', drv='Y'),
    ]


_TWO_ENDS_RELS = [('110', '100'), ('150', '110'), ('160', '110'),
                  ('170', '150')]


def _xer(rows, rels, *, task_clndr, project_clndr='TEN', ten_default='N',
         scd_end=''):
    lines = [
        TAB.join(['ERMHDR', '20.12', '2026-09-21', 'Project', 'admin', 'admin',
                  'dbxDatabaseNoName', 'Project Management', 'USD']),
        TAB.join(['%T', 'PROJECT']),
        TAB.join(['%F', 'proj_id', 'proj_short_name', 'last_recalc_date',
                  'plan_end_date', 'scd_end_date', 'clndr_id']),
        TAB.join(['%R', '1', 'NEUTRAL', DATA_DATE, '', scd_end, project_clndr]),
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
    lines += [TAB.join(['%R'] + [task_clndr if v == CAL else v for v in r])
              for r in rows]
    lines += [
        TAB.join(['%T', 'TASKPRED']),
        TAB.join(['%F', 'task_pred_id', 'task_id', 'pred_task_id',
                  'pred_type', 'lag_hr_cnt']),
    ]
    lines += [TAB.join(['%R', str(i), rel[0], rel[1], 'PR_FS',
                        str(rel[2] if len(rel) > 2 else 0)])
              for i, rel in enumerate(rels, 1)]
    lines.append('%E')
    return '\r\n'.join(lines) + '\r\n'


def _validate(xer_text):
    with tempfile.NamedTemporaryFile('w', suffix='.xer', delete=False,
                                     encoding='utf-8') as f:
        f.write(xer_text)
        path = f.name
    try:
        with _warnings.catch_warnings():
            _warnings.simplefilter('ignore')
            return validate_critical_path(parse_xer(path))
    finally:
        os.unlink(path)


def _floats(task_clndr, **kw):
    return _validate(_xer(_float_rows(), _float_rels(), task_clndr=task_clndr,
                          **kw))


def _two_ends(task_clndr):
    return _validate(_xer(_two_ends_rows(), _TWO_ENDS_RELS,
                          task_clndr=task_clndr, scd_end='2026-10-05 07:00'))


def _dashboard_html(results):
    fd, path = tempfile.mkstemp(suffix='.html')
    os.close(fd)
    try:
        generate_dashboard(results, path)
        with open(path, encoding='utf-8') as f:
            return f.read()
    finally:
        os.unlink(path)


def _cp_float(results, code):
    return next(a['total_float_days'] for a in results['critical_path_activities']
                if a['task_code'] == code)


def _near_critical_days(results):
    return sorted({a['total_float_days'] for a in results['near_critical_activities']})


def _scores(results):
    return {k: v.get('score') for k, v in results['checks'].items()}


def _lead(results):
    """The lead on the critical chain, as Check 5 reports it."""
    return next(r['finding'] for r in results['recommendations']
                if r['category'] == 'Negative Lags on CP')


def _calendar_section(html):
    """The dashboard's list of activities without a usable calendar, and
    nothing else: every activity code also appears in the other tables."""
    start = html.index('Activities Without a Usable Calendar')
    return html[start:html.index('<!-- Gauge -->', start)]


def _calendar_recs(results):
    return [r for r in results['recommendations']
            if r['category'] == 'Activity Calendar']


EXPLICIT = _floats('TEN')
BLANK = _floats('')
_NO_CALENDAR = None


def _no_calendar():
    """Blank ids, and nothing in the file to resolve them onto."""
    global _NO_CALENDAR
    if _NO_CALENDAR is None:
        _NO_CALENDAR = _floats('', project_clndr='')
    return _NO_CALENDAR


# ─────────────────────────────────────── the fixture is what it says it is

def test_explicit_fixture_is_the_p6_answer():
    assert _cp_float(EXPLICIT, 'C1') == -10.0
    assert _near_critical_days(EXPLICIT) == [2.0]
    assert _lead(EXPLICIT).startswith('Negative lag (-2.0d) on CP: C1')
    nc = EXPLICIT['checks']['near_critical']
    assert nc['bands']['1-2d'] == 11 and nc['score'] == 40


# ─────────────────────────────────────────── blank ids, project calendar

def test_blank_ids_convert_float_on_the_project_calendar_not_at_8_hours_a_day():
    assert _cp_float(BLANK, 'C1') == -10.0              # was -12.5
    assert _near_critical_days(BLANK) == [2.0]          # was 2.5
    assert _lead(BLANK).startswith('Negative lag (-2.0d)')   # was -2.5d
    assert BLANK['checks']['near_critical']['bands']['1-2d'] == 11   # was 0


def test_every_check_scores_the_same_as_with_explicit_ids():
    assert _scores(BLANK) == _scores(EXPLICIT)          # Check 7 was 55, not 40
    for key in ('overall_score', 'overall_rating', 'overall_confidence'):
        assert BLANK[key] == EXPLICIT[key], key
    dcma = BLANK['dcma_14']
    assert (dcma['dcma_score'], dcma['dcma_max']) == (
        EXPLICIT['dcma_14']['dcma_score'], EXPLICIT['dcma_14']['dcma_max'])


def test_a_friday_finish_is_at_a_monday_network_finish_on_a_blank_id():
    _needs_engine()
    explicit, blank = _two_ends('TEN'), _two_ends('')
    for r in (explicit, blank):
        assert sorted(r['terminal_milestones']) == ['F160', 'F170']
        assert r['checks']['open_ends_cp']['rating'] == RATING_GREEN
        assert not [x for x in r['recommendations']
                    if x['category'] == 'Open Ends on CP']


def test_default_flag_calendar_is_used_when_the_project_names_none():
    r = _floats('', project_clndr='', ten_default='Y')
    assert _cp_float(r, 'C1') == -10.0
    assert _scores(r) == _scores(EXPLICIT)
    assert [c['tier'] for c in r['calendar_resolution']['fallback_calendars']] == ['default']
    assert r['calendar_resolution']['unresolved_count'] == 0


# ─────────────────────────────────────────────────────── the disclosure

def test_resolved_fallback_is_disclosed_not_warned():
    res = BLANK['calendar_resolution']
    assert res['resolved_by_fallback_count'] == 14
    assert res['unresolved_count'] == 0
    assert res['fallback_calendars'] == [
        {'clndr_id': 'TEN', 'clndr_name': 'Ten Hour', 'tier': 'project',
         'task_count': 14}]
    assert _calendar_recs(BLANK) == []
    assert BLANK['dcma_14']['calendar_resolution'] == res
    html = _dashboard_html(BLANK)
    assert 'Calendar basis' in html and 'Ten Hour' in html
    assert 'Activities Without a Usable Calendar' not in html


def test_explicit_calendars_add_nothing_to_the_report():
    res = EXPLICIT['calendar_resolution']
    assert res['resolved_by_fallback_count'] == 0 and res['unresolved_count'] == 0
    assert _calendar_recs(EXPLICIT) == []
    html = _dashboard_html(EXPLICIT)
    assert 'Calendar basis' not in html
    assert 'Activities Without a Usable Calendar' not in html


def test_no_fallback_calendar_is_a_visible_warning_not_a_silent_8_hour_day():
    r = _no_calendar()
    res = r['calendar_resolution']
    assert res['unresolved_count'] == 14
    assert [u['task_code'] for u in res['unresolved']] == (
        ['START', 'C1', 'FIN'] + ['N%02d' % i for i in range(1, 12)])
    assert {u['reason'] for u in res['unresolved']} == {'blank'}
    recs = _calendar_recs(r)
    assert len(recs) == 1 and recs[0]['priority'] == 'High'
    assert recs[0]['finding'].startswith('14 activities have no usable calendar: 14 ')
    assert '8 h/day' in recs[0]['finding']
    assert recs[0]['affected_activity'] == 'START'
    assert [f['check_id'] for f in r['dcma_14']['report']['findings']
            if f['check_id'] == 'DCMA-Ext-TaskCalendar'] == ['DCMA-Ext-TaskCalendar']
    html = _dashboard_html(r)
    assert 'Activities Without a Usable Calendar (14)' in html
    section = _calendar_section(html)
    assert 'a flat 8 h/day' in section
    for code in ['START', 'C1', 'FIN'] + ['N%02d' % i for i in range(1, 12)]:
        assert '>%s<' % code in section, code
    # the readings are still the 8 h/day ones, now labelled as such
    assert _cp_float(r, 'C1') == -12.5
    assert _lead(r).startswith('Negative lag (-2.5d)')


def test_a_calendar_the_file_does_not_declare_is_reported_not_replaced():
    rows = _float_rows()
    rows[1] = ['GONE' if v == CAL else v for v in rows[1]]      # C1
    r = _validate(_xer(rows, _float_rels(), task_clndr='TEN'))
    res = r['calendar_resolution']
    assert res['unresolved'] == [{'task_code': 'C1', 'task_name': 'Neutral C1',
                                  'clndr_id': 'GONE', 'reason': 'undeclared'}]
    assert res['resolved_by_fallback_count'] == 0
    finding = _calendar_recs(r)[0]['finding']
    assert finding.startswith('1 activity has no usable calendar: 0 with a blank')
    assert '1 naming a calendar the file does not declare' in finding
    section = _calendar_section(_dashboard_html(r))
    assert '>C1<' in section and '>GONE<' in section
    assert 'names a calendar the file does not declare' in section


if __name__ == '__main__':
    tests = [f for name, f in list(globals().items())
             if name.startswith('test_') and callable(f)]
    failed = skipped = 0
    for t in tests:
        try:
            t()
            print(f'ok  {t.__name__}')
        except unittest.SkipTest as e:
            print(f'skip {t.__name__}: {e}')
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
    note = f' ({skipped} skipped)' if skipped else ''
    print(f'{len(tests) - skipped} / {len(tests)} passed{note}')
