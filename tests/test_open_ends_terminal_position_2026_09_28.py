#!/usr/bin/env python3
"""Open ends (Check 3) find the network's terminal by position, not by task
type.

Run with: python tests/test_open_ends_terminal_position_2026_09_28.py

Check 3 reports every critical activity with no successor as an open end on
the critical path ("has NO SUCCESSORS", Critical), except the terminal: the
activity where the network legitimately ends. The terminal was every such
activity that is a milestone (TT_Mile or TT_FinMile), whatever its date, and
every one whose early finish fell on the project's scheduled finish day. Only
when neither found anything did it fall back to the activities with the
latest early finish.

That goes wrong on a schedule converted from MS Project, with no scheduled
finish in the file and every open end carrying zero float. A finish milestone
well before the finish, with nothing after it, is taken as the terminal, which
switches the fallback off, so the real last activity (the latest early
finish, zero float, no successor) is reported as a critical open end and the
check goes RED on the wrong activity. On P6 exports the same rule excuses
constrained contract milestones with no successor, months before the finish,
as terminals.

A critical activity with no successor is now the terminal only where it
finishes with the network:

* on the day of the latest stored early finish of the incomplete work that is
  tied to other work, or with no working day between the two on its own
  calendar, in the engine's whole days (a finish at Friday's close and one at
  Monday's opening are the same instant); an activity tied to nothing is not
  part of the network and does not set its finish;
* or, as before, on the day of the project's scheduled finish.

The working-day test needs cpp-cpm-engine's `cpm` module on the path; without
it only the same day counts, and the two tests that need it are skipped.

Each missing-successor finding names where the network finishes, so where the
later end is work finishing after the completion milestone, the milestone is
the open end and the reader sees both. An activity the file stores no early
finish for cannot be placed, so it is not excused. A file with no network
finish to read (no activity tied to other work stores an early finish) keeps
the rule as it was. Logic continuity (Check 8) traces from Check 3's
terminals, so it is checked against the new rule here. This repository's
DCMA-14 #1 still exempts every finish milestone from its missing-successor
count by type, so no agreement test with it is carried.

The fixture is a neutral seven-activity chain on a five-day calendar, its
dates, floats and driving flags worked through by hand from P6's scheduling
rules: an early finish milestone with no successor, and the hand-over that
ends the network. Its "MS Project" form has no scheduled finish and makes
open-ended activities critical, as converted files do; its P6 form carries
the scheduled finish and holds the milestone to a Finish On or Before date.
"""
import os
import sys
import tempfile
import unittest
import warnings as _warnings

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, '..', 'scripts'))

from xer_parser import parse_xer, get_calendar_map  # noqa: E402
from cp_validator import (  # noqa: E402
    validate_critical_path, RATING_GREEN, RATING_RED, _finishes_with,
    _engine_date_helpers)

TAB = '\t'
DATA_DATE = '2027-03-01 08:00'      # a Monday morning
FINISH = '2027-03-29 17:00'         # the hand-over's early finish: the network's

_FIVE_DAY_SHIFT = '(0||0(s|08:00|f|12:00)())(0||1(s|13:00|f|17:00)())'
_FIVE_DAY = ('(0||CalendarData()((0||DaysOfWeek()((0||1()())'
             + ''.join(f'(0||{d}()({_FIVE_DAY_SHIFT}))' for d in range(2, 7))
             + '(0||7()())))(0||Exceptions()())))')
_SEVEN_DAY = ('(0||CalendarData()((0||DaysOfWeek()('
              + ''.join(f'(0||{d}()({_FIVE_DAY_SHIFT}))' for d in range(1, 8))
              + '))(0||Exceptions()())))')

_TASK_COLS = ['task_id', 'task_code', 'task_name', 'proj_id', 'wbs_id',
              'clndr_id', 'status_code', 'task_type', 'target_drtn_hr_cnt',
              'remain_drtn_hr_cnt', 'total_float_hr_cnt', 'act_start_date',
              'act_end_date', 'early_start_date', 'early_end_date',
              'restart_date', 'reend_date', 'late_start_date',
              'late_end_date', 'target_start_date', 'target_end_date',
              'driving_path_flag', 'cstr_type', 'cstr_date']


def _needs_engine():
    """Skip a test that needs the engine's working-day arithmetic."""
    if _engine_date_helpers() is None:
        raise unittest.SkipTest(
            "cpp-cpm-engine's cpm module is not importable, so only the same "
            "day counts as finishing with the network")


def _row(tid, code, name, hrs, es, ef, ls, lf, tf, *, ttype='TT_Task',
         status='TK_NotStart', act=('', ''), cstr='', cstr_date='', drv='N'):
    """One TASK row in P6's export shape on the five-day calendar. A completed
    row carries its stamp (the data date) as its early and late dates and no
    float."""
    done = status == 'TK_Complete'
    return [tid, code, name, '1', 'W1', 'C5', status, ttype, str(hrs),
            '0' if done else str(hrs), '' if done else str(tf), act[0], act[1],
            es, ef, '' if done else es, '' if done else ef, ls, lf,
            act[0] or es, act[1] or ef, drv, cstr, cstr_date]


def _milestone(tid, code, name, at, tf, *, ttype='TT_FinMile', late=None,
               cstr='', cstr_date='', drv='N'):
    late = at if late is None else late
    return _row(tid, code, name, 0, at, at, late, late, tf, ttype=ttype,
                cstr=cstr, cstr_date=cstr_date, drv=drv)


def _rows(foundations_cstr=('', '')):
    """The chain as P6 dates it. Every activity carries zero float: the
    foundations milestone because it has no successor and open-ended
    activities are critical (or because a Finish On or Before holds it), the
    rest because they are the longest path to the hand-over."""
    return [
        _row('100', 'F100', 'Site handover', 40, DATA_DATE, DATA_DATE,
             DATA_DATE, DATA_DATE, '', status='TK_Complete',
             act=('2027-02-22 08:00', '2027-02-26 17:00')),
        _row('110', 'F110', 'Excavate', 24, '2027-03-01 08:00',
             '2027-03-03 17:00', '2027-03-01 08:00', '2027-03-03 17:00', 0,
             drv='Y'),
        _row('120', 'F120', 'Pour the footings', 16, '2027-03-04 08:00',
             '2027-03-05 17:00', '2027-03-04 08:00', '2027-03-05 17:00', 0,
             drv='Y'),
        # nothing after it, three weeks before the network ends
        _milestone('130', 'F130', 'Foundations complete', '2027-03-05 17:00', 0,
                   cstr=foundations_cstr[0], cstr_date=foundations_cstr[1]),
        _row('140', 'F140', 'Erect the frame', 80, '2027-03-08 08:00',
             '2027-03-19 17:00', '2027-03-08 08:00', '2027-03-19 17:00', 0,
             drv='Y'),
        _row('150', 'F150', 'Close in', 40, '2027-03-22 08:00',
             '2027-03-26 17:00', '2027-03-22 08:00', '2027-03-26 17:00', 0,
             drv='Y'),
        # the latest early finish, nothing after it
        _row('160', 'F160', 'Hand over to the owner', 8, '2027-03-29 08:00',
             FINISH, '2027-03-29 08:00', FINISH, 0, drv='Y'),
    ]


# (successor, predecessor, type, lag hours)
_RELS = [
    ('110', '100', 'PR_FS', 0), ('120', '110', 'PR_FS', 0),
    ('130', '120', 'PR_FS', 0), ('140', '120', 'PR_FS', 0),
    ('150', '140', 'PR_FS', 0), ('160', '150', 'PR_FS', 0),
]

_CONTRACT_DATE = ('CS_MEOB', '2027-03-05 17:00')   # Finish On or Before


def _xer(rows, rels, *, scd_end='', open_critical='Y'):
    lines = [
        TAB.join(['ERMHDR', '23.12', '2027-03-01', 'Project', 'admin',
                  'Neutral', 'db', 'Project Management', 'CAD']),
        TAB.join(['%T', 'PROJECT']),
        TAB.join(['%F', 'proj_id', 'proj_short_name', 'last_recalc_date',
                  'plan_end_date', 'scd_end_date', 'clndr_id']),
        TAB.join(['%R', '1', 'NEUTRAL', DATA_DATE, '', scd_end, 'C5']),
        TAB.join(['%T', 'PROJWBS']),
        TAB.join(['%F', 'wbs_id', 'parent_wbs_id', 'wbs_name',
                  'wbs_short_name', 'proj_id']),
        TAB.join(['%R', 'W1', '', 'Root', 'W1', '1']),
        TAB.join(['%T', 'CALENDAR']),
        TAB.join(['%F', 'clndr_id', 'clndr_name', 'clndr_type',
                  'day_hr_cnt', 'week_hr_cnt', 'clndr_data']),
        TAB.join(['%R', 'C5', 'Five day', 'CA_Project', '8', '40', _FIVE_DAY]),
        TAB.join(['%R', 'C7', 'Seven day', 'CA_Project', '8', '56', _SEVEN_DAY]),
        TAB.join(['%T', 'TASK']),
        TAB.join(['%F'] + _TASK_COLS),
    ]
    lines += [TAB.join(['%R'] + r) for r in rows]
    lines += [
        TAB.join(['%T', 'TASKPRED']),
        TAB.join(['%F', 'task_pred_id', 'task_id', 'pred_task_id',
                  'pred_type', 'lag_hr_cnt']),
    ]
    lines += [TAB.join(['%R', str(i), s, p, t, str(lag)])
              for i, (s, p, t, lag) in enumerate(rels, 1)]
    lines += [
        TAB.join(['%T', 'SCHEDOPTIONS']),
        TAB.join(['%F', 'schedoptions_id', 'proj_id', 'sched_retained_logic',
                  'sched_progress_override', 'sched_open_critical_flag',
                  'sched_calendar_on_relationship_lag']),
        TAB.join(['%R', '1', '1', 'Y', 'N', open_critical, 'rcal_Predecessor']),
        '%E',
    ]
    return '\r\n'.join(lines) + '\r\n'


def _parsed(rows, rels, **kw):
    with tempfile.NamedTemporaryFile('w', suffix='.xer', delete=False,
                                     encoding='utf-8') as f:
        f.write(_xer(rows, rels, **kw))
        path = f.name
    try:
        with _warnings.catch_warnings():
            _warnings.simplefilter('ignore')
            return parse_xer(path)
    finally:
        os.unlink(path)


def _validate(rows, rels, **kw):
    with _warnings.catch_warnings():
        _warnings.simplefilter('ignore')
        return validate_critical_path(_parsed(rows, rels, **kw))


def _ms_project_form(rows=None, rels=None):
    """No scheduled finish in the file; open-ended activities critical."""
    return _validate(_rows() if rows is None else rows,
                     _RELS if rels is None else rels)


def _p6_form(rows=None, rels=None, scd_end=FINISH):
    """The scheduled finish in the file; the milestone held by its date."""
    return _validate(_rows(_CONTRACT_DATE) if rows is None else rows,
                     _RELS if rels is None else rels,
                     scd_end=scd_end, open_critical='N')


def _terminals(results):
    return sorted(results['terminal_milestones'])


def _no_successor_findings(results):
    """The critical open ends Check 3 names on the successor side."""
    return sorted(r['affected_activity'] for r in results['recommendations']
                  if r['category'] == 'Open Ends on CP'
                  and 'NO SUCCESSORS' in r['finding'])


def _finding(results, code):
    """Check 3's missing-successor finding on one critical activity."""
    return next(r['finding'] for r in results['recommendations']
                if r['category'] == 'Open Ends on CP'
                and r['affected_activity'] == code
                and 'NO SUCCESSORS' in r['finding'])


def _open_ends(results):
    return results['checks']['open_ends_cp']


# tied to nothing, held a week past the hand-over; open-ended, so critical,
# and the latest early finish in the file
_UNLINKED = _row('900', 'F900', 'Temporary works removed', 16,
                 '2027-04-05 08:00', '2027-04-06 17:00', '2027-04-05 08:00',
                 '2027-04-06 17:00', 0, cstr='CS_MSOA',
                 cstr_date='2027-04-05 08:00')


# ─────────────────────────────────────────── the fixture is what it says it is

def test_the_fixture_is_the_pattern_as_p6_dates_it():
    for r in (_ms_project_form(), _p6_form()):
        assert sorted(a['task_code'] for a in r['critical_path_activities']) == [
            'F110', 'F120', 'F130', 'F140', 'F150', 'F160']


# ─────────────────────────────── the reported case: the last activity flagged

def test_the_last_activity_is_the_terminal_not_an_early_finish_milestone():
    r = _ms_project_form()
    assert _terminals(r) == ['F160']
    # the milestone that goes nowhere is the open end, not the hand-over
    assert _no_successor_findings(r) == ['F130']
    oe = _open_ends(r)
    assert (oe['cp_no_pred'], oe['cp_no_succ']) == (0, 1)
    assert oe['rating'] == RATING_RED


def test_an_early_contract_milestone_with_no_successor_is_an_open_end():
    # on P6's own export the hand-over matches the scheduled finish, and the
    # Finish On or Before milestone three weeks earlier was excused by type
    r = _p6_form()
    assert _terminals(r) == ['F160']
    assert _no_successor_findings(r) == ['F130']
    assert _open_ends(r)['rating'] == RATING_RED


# ───────────────────────────────────────── finishing with the network finish

def _two_ends_rows():
    """Two chains end the network: the services commissioning closes Friday
    evening, the owner's move-in (a start milestone) opens Monday morning. No
    working time separates them on the five-day calendar, so P6 gives the
    commissioning zero float against the finish."""
    rows = [x for x in _rows() if x[1] in ('F100', 'F110', 'F120', 'F140')]
    return rows + [
        _row('150', 'F150', 'Close in', 40, '2027-03-22 08:00',
             '2027-03-26 17:00', '2027-03-22 08:00', '2027-03-26 17:00', 0,
             drv='Y'),
        _row('160', 'F160', 'Commission the services', 40, '2027-03-22 08:00',
             '2027-03-26 17:00', '2027-03-22 08:00', '2027-03-26 17:00', 0),
        _milestone('170', 'F170', 'Owner move-in', '2027-03-29 08:00', 0,
                   ttype='TT_Mile', drv='Y'),
    ]


_TWO_ENDS_RELS = [
    ('110', '100', 'PR_FS', 0), ('120', '110', 'PR_FS', 0),
    ('140', '120', 'PR_FS', 0), ('150', '140', 'PR_FS', 0),
    ('160', '140', 'PR_FS', 0), ('170', '150', 'PR_FS', 0),
]


def test_an_activity_closing_the_working_day_before_the_finish_is_at_the_finish():
    _needs_engine()
    r = _p6_form(_two_ends_rows(), _TWO_ENDS_RELS, scd_end='2027-03-29 08:00')
    # Friday 17:00 and Monday 08:00 are the same working instant
    assert _terminals(r) == ['F160', 'F170']
    assert _no_successor_findings(r) == []
    assert _open_ends(r)['rating'] == RATING_GREEN


def _calendars():
    return get_calendar_map(_parsed([], []))


def _ends(early_finish, calendar='C5'):
    return {'early_end_date': early_finish, 'clndr_id': calendar}


def test_the_same_day_counts():
    # an 11:00 finish on the day the network finishes at 17:00: the engine
    # reads the first as the day's opening and the second as its close, so
    # the day decides
    assert _finishes_with(_ends('2027-03-29 11:00'), FINISH, _calendars(),
                          _engine_date_helpers())


def test_no_working_day_between_counts_on_the_activity_s_own_calendar():
    _needs_engine()
    cals, helpers = _calendars(), _engine_date_helpers()
    monday = '2027-03-29 08:00'
    assert _finishes_with(_ends('2027-03-26 17:00'), monday, cals, helpers)
    # Friday is a working day between Thursday's close and Monday's opening
    assert not _finishes_with(_ends('2027-03-25 17:00'), monday, cals, helpers)
    # on a seven-day calendar the weekend is working time
    assert not _finishes_with(_ends('2027-03-26 17:00', 'C7'), monday, cals,
                              helpers)


def test_without_the_engine_only_the_day_counts():
    cals = _calendars()
    assert _finishes_with(_ends('2027-03-29 11:00'), FINISH, cals, None)
    assert not _finishes_with(_ends('2027-03-26 17:00'), '2027-03-29 08:00',
                              cals, None)


def test_a_missing_date_never_counts():
    cals, helpers = _calendars(), _engine_date_helpers()
    assert not _finishes_with(_ends(''), FINISH, cals, helpers)
    assert not _finishes_with(_ends(FINISH), '', cals, helpers)


def test_an_activity_tied_to_nothing_does_not_move_the_network_finish():
    r = _ms_project_form(_rows() + [_UNLINKED])
    assert _terminals(r) == ['F160']
    assert _no_successor_findings(r) == ['F130', 'F900']


def test_an_activity_with_no_early_finish_is_not_the_terminal():
    rows = _rows(_CONTRACT_DATE) + [
        # a completion milestone the file stores no dates for: its position
        # cannot be read, so it is not excused
        _milestone('180', 'F180', 'Substantial performance', '', 0),
    ]
    r = _p6_form(rows, _RELS + [('180', '150', 'PR_FS', 0)])
    assert _terminals(r) == ['F160']
    assert _no_successor_findings(r) == ['F130', 'F180']


def test_an_early_milestone_is_not_excused_when_nothing_finishes_with_the_network():
    # a level of effort runs to the hand-over's finish, so the hand-over has a
    # successor and no critical activity without one finishes with the
    # network. The early milestone is still the open end: its type does not
    # excuse it
    rows = _rows() + [
        _row('190', 'F190', 'Site supervision', 168, '2027-03-01 08:00', FINISH,
             '2027-03-01 08:00', FINISH, '', ttype='TT_LOE'),
    ]
    rels = _RELS + [('190', '110', 'PR_SS', 0), ('190', '160', 'PR_FF', 0)]
    r = _ms_project_form(rows, rels)
    assert _terminals(r) == []
    assert _no_successor_findings(r) == ['F130']


def test_the_open_end_finding_names_where_the_network_finishes():
    assert _finding(_ms_project_form(), 'F130') == (
        "Critical activity 'F130 - Foundations complete' has NO SUCCESSORS. "
        "The network finishes at 'F160 - Hand over to the owner' "
        "(2027-03-29 17:00).")


def test_a_completion_milestone_before_later_work_is_the_open_end():
    # the trade-off of reading the end by position: work that finishes after
    # the completion milestone, with no successor, is where the network
    # ends. The milestone is then the open end, and its finding names that
    # work, so the reader can see which of the two ends to tie in
    rows = _finish_milestone_rows() + [
        _row('550', 'F550', 'Touch-up painting', 32, '2027-03-29 08:00',
             '2027-04-01 17:00', '2027-03-29 08:00', '2027-04-01 17:00', 0),
    ]
    rels = _RELS + [('140', '130', 'PR_FS', 0), ('170', '160', 'PR_FS', 0),
                    ('550', '150', 'PR_FS', 0)]
    r = _ms_project_form(rows, rels)
    assert _terminals(r) == ['F550']
    assert _no_successor_findings(r) == ['F170']
    assert _finding(r, 'F170').endswith(
        "The network finishes at 'F550 - Touch-up painting' (2027-04-01 17:00).")


# ──────────────────────────────────────────────────────────── as before

def _finish_milestone_rows(foundations_cstr=('', '')):
    return _rows(foundations_cstr) + [
        _milestone('170', 'F170', 'Practical completion', FINISH, 0, drv='Y'),
    ]


def test_a_real_finish_milestone_reads_as_before():
    # the foundations milestone feeds the frame; the network ends at a
    # finish milestone after the hand-over
    rels = _RELS + [('140', '130', 'PR_FS', 0), ('170', '160', 'PR_FS', 0)]
    for r in (_ms_project_form(_finish_milestone_rows(), rels),
              _p6_form(_finish_milestone_rows(), rels)):
        assert _terminals(r) == ['F170']
        oe = _open_ends(r)
        assert (oe['rating'], oe['score']) == (RATING_GREEN, 100)
        lc = r['checks']['logic_continuity']
        assert (lc['rating'], lc['disconnected_count']) == (RATING_GREEN, 0)


def test_with_no_early_dates_in_the_file_the_rule_is_as_before():
    # no position to read: every critical milestone with no successor is
    # still taken as a terminal
    rows = [
        _row('100', 'F100', 'Site handover', 40, DATA_DATE, DATA_DATE,
             DATA_DATE, DATA_DATE, '', status='TK_Complete',
             act=('2027-02-22 08:00', '2027-02-26 17:00')),
        _row('110', 'F110', 'Excavate', 24, '', '', '', '', 0),
        _milestone('130', 'F130', 'Foundations complete', '', 0),
        _row('160', 'F160', 'Hand over to the owner', 8, '', '', '', '', 0),
        _milestone('170', 'F170', 'Practical completion', '', 0),
    ]
    rels = [('110', '100', 'PR_FS', 0), ('130', '110', 'PR_FS', 0),
            ('160', '110', 'PR_FS', 0), ('170', '160', 'PR_FS', 0)]
    r = _ms_project_form(rows, rels)
    assert _terminals(r) == ['F130', 'F170']
    assert _no_successor_findings(r) == []


def test_the_scheduled_finish_day_still_counts_as_before():
    # P6 writes the scheduled finish at the latest early finish of all the
    # work, here the activity tied to nothing. On that day it is still
    # excused as a terminal, as before, and still reported for its missing
    # predecessor
    r = _validate(_rows() + [_UNLINKED], _RELS, scd_end='2027-04-06 17:00')
    assert _terminals(r) == ['F160', 'F900']
    assert _no_successor_findings(r) == ['F130']
    assert 'F900' in {x['affected_activity'] for x in r['recommendations']
                      if x['category'] == 'Open Ends on CP'
                      and 'NO PREDECESSORS' in x['finding']}


# ─────────────────────────────────────────── logic continuity reads it the same

def test_logic_continuity_reads_an_early_dead_end_as_disconnected():
    # a start milestone signs off the footings and leads nowhere. Logic
    # continuity traces from Check 3's terminals, so it used to count the
    # sign-off as a completion and the inspection behind it as connected
    rows = [x for x in _rows() if x[1] != 'F130'] + [
        _row('125', 'F125', 'Inspect the footings', 8, '2027-03-08 08:00',
             '2027-03-08 17:00', '2027-03-08 08:00', '2027-03-08 17:00', 0),
        _milestone('130', 'F130', 'Footings signed off', '2027-03-09 08:00', 0,
                   ttype='TT_Mile'),
    ]
    rels = [x for x in _RELS if x[0] != '130'] + [
        ('125', '120', 'PR_FS', 0), ('130', '125', 'PR_FS', 0)]
    r = _ms_project_form(rows, rels)
    assert _terminals(r) == ['F160']
    assert _no_successor_findings(r) == ['F130']
    lc = r['checks']['logic_continuity']
    assert sorted(d['task_code'] for d in lc['disconnected_activities']) == [
        'F125', 'F130']
    assert lc['rating'] == RATING_RED
    # every terminal is still a completion anchor
    assert set(_terminals(r)) <= set(lc['completion_anchors'])


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
