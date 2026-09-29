#!/usr/bin/env python3
"""Open ends (Check 3): the finish milestone is the terminal where it finishes
with the network, whether or not it floats.

Run with: python tests/test_open_ends_floating_finish_2026_09_28.py

Check 3 excuses the terminal, the activity where the network legitimately
ends, from its missing-successor count. It finds the terminal by position
(the day of the network's latest early finish, or no working day between on
the activity's own calendar, or the scheduled finish day), but it looked for
one only among the critical activities.

A project with a Must Finish By later than its early finish floats
throughout: P6 computes every late date against the Must Finish By, so the
completion milestone carries float and is not critical. It was never the
terminal, so it drew a 'High' "has no successors" finding while DCMA-14 #1
excused it as the finish milestone at the network finish. A file with no
float written at all did the same.

Every incomplete activity with no successor is now the terminal where it
finishes with the network, critical or not. A non-critical one also has to
be tied to other work: an activity with no logic is not part of the network,
the rule logic continuity (Check 8) reads the finish by, and Check 8 folds
Check 3's terminals into its completion anchors. A file with no network
finish to read keeps the old rule, which looks only at critical activities.

A floating activity is read against the network's own finish only: a
scheduled finish the file did not move with the network would excuse it
where the network does not end. Check 3's note names where the network
finishes whenever an activity is missing a successor, so where the latest
finisher is work after the completion milestone, the reader sees which of
the two ends to tie in; each critical finding names it too, as before.

Nothing is exempt from the missing-predecessor count: an incomplete start
milestone with no predecessor is an open end, so the start milestone has to
be complete. DCMA-14 #1 excuses a start milestone at the network start; this
check does not, on purpose.

The working-day test needs cpp-cpm-engine's `cpm` module on the path;
without it only the same day counts, and the one test that needs it is
skipped.

The fixture is a neutral chain on a five-day calendar, its dates, floats and
driving flags worked through by hand from P6's scheduling rules under a Must
Finish By three working weeks after the early finish: an early finish
milestone with no successor, and the practical completion milestone that
ends the network.
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
    validate_critical_path, _engine_date_helpers)

TAB = '\t'
DATA_DATE = '2027-03-01 08:00'      # a Monday morning
FINISH = '2027-03-29 17:00'         # the early finish of the network
MUST_FINISH_BY = '2027-04-19 17:00'  # fifteen working days later

_FIVE_DAY_SHIFT = '(0||0(s|08:00|f|12:00)())(0||1(s|13:00|f|17:00)())'
_FIVE_DAY = ('(0||CalendarData()((0||DaysOfWeek()((0||1()())'
             + ''.join(f'(0||{d}()({_FIVE_DAY_SHIFT}))' for d in range(2, 7))
             + '(0||7()())))(0||Exceptions()())))')

_TASK_COLS = ['task_id', 'task_code', 'task_name', 'proj_id', 'wbs_id',
              'clndr_id', 'status_code', 'task_type', 'target_drtn_hr_cnt',
              'remain_drtn_hr_cnt', 'total_float_hr_cnt', 'act_start_date',
              'act_end_date', 'early_start_date', 'early_end_date',
              'restart_date', 'reend_date', 'late_start_date',
              'late_end_date', 'target_start_date', 'target_end_date',
              'driving_path_flag', 'cstr_type', 'cstr_date']


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


def _milestone(tid, code, name, at, late, tf, *, ttype='TT_FinMile', drv='N'):
    return _row(tid, code, name, 0, at, at, late, late, tf, ttype=ttype, drv=drv)


def _rows():
    """The chain as P6 dates it against the Must Finish By. Every activity on
    the longest path carries the fifteen days (120 hours) between the early
    finish and the Must Finish By; the foundations milestone has no successor,
    so its late finish is the Must Finish By and it carries 31 days."""
    return [
        _row('100', 'F100', 'Site handover', 40, DATA_DATE, DATA_DATE,
             DATA_DATE, DATA_DATE, '', status='TK_Complete',
             act=('2027-02-22 08:00', '2027-02-26 17:00')),
        _row('110', 'F110', 'Excavate', 24, '2027-03-01 08:00',
             '2027-03-03 17:00', '2027-03-22 08:00', '2027-03-24 17:00', 120,
             drv='Y'),
        _row('120', 'F120', 'Pour the footings', 16, '2027-03-04 08:00',
             '2027-03-05 17:00', '2027-03-25 08:00', '2027-03-26 17:00', 120,
             drv='Y'),
        # nothing after it, three weeks before the network ends
        _milestone('130', 'F130', 'Foundations complete', '2027-03-05 17:00',
                   MUST_FINISH_BY, 248),
        _row('140', 'F140', 'Erect the frame', 80, '2027-03-08 08:00',
             '2027-03-19 17:00', '2027-03-29 08:00', '2027-04-09 17:00', 120,
             drv='Y'),
        _row('150', 'F150', 'Close in', 40, '2027-03-22 08:00',
             '2027-03-26 17:00', '2027-04-12 08:00', '2027-04-16 17:00', 120,
             drv='Y'),
        _row('160', 'F160', 'Hand over to the owner', 8, '2027-03-29 08:00',
             FINISH, '2027-04-19 08:00', MUST_FINISH_BY, 120, drv='Y'),
        # where the network ends; it floats with the rest
        _milestone('170', 'F170', 'Practical completion', FINISH,
                   MUST_FINISH_BY, 120, drv='Y'),
    ]


# (successor, predecessor, type, lag hours)
_RELS = [
    ('110', '100', 'PR_FS', 0), ('120', '110', 'PR_FS', 0),
    ('130', '120', 'PR_FS', 0), ('140', '120', 'PR_FS', 0),
    ('150', '140', 'PR_FS', 0), ('160', '150', 'PR_FS', 0),
    ('170', '160', 'PR_FS', 0),
]


def _xer(rows, rels, *, scd_end=FINISH, plan_end=MUST_FINISH_BY):
    lines = [
        TAB.join(['ERMHDR', '23.12', '2027-03-01', 'Project', 'admin',
                  'Neutral', 'db', 'Project Management', 'CAD']),
        TAB.join(['%T', 'PROJECT']),
        TAB.join(['%F', 'proj_id', 'proj_short_name', 'last_recalc_date',
                  'plan_end_date', 'scd_end_date', 'clndr_id']),
        TAB.join(['%R', '1', 'NEUTRAL', DATA_DATE, plan_end, scd_end, 'C5']),
        TAB.join(['%T', 'PROJWBS']),
        TAB.join(['%F', 'wbs_id', 'parent_wbs_id', 'wbs_name',
                  'wbs_short_name', 'proj_id']),
        TAB.join(['%R', 'W1', '', 'Root', 'W1', '1']),
        TAB.join(['%T', 'CALENDAR']),
        TAB.join(['%F', 'clndr_id', 'clndr_name', 'clndr_type',
                  'day_hr_cnt', 'week_hr_cnt', 'clndr_data']),
        TAB.join(['%R', 'C5', 'Five day', 'CA_Project', '8', '40', _FIVE_DAY]),
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
        TAB.join(['%R', '1', '1', 'Y', 'N', 'N', 'rcal_Predecessor']),
        '%E',
    ]
    return '\r\n'.join(lines) + '\r\n'


def _validate(rows=None, rels=None, **kw):
    with tempfile.NamedTemporaryFile('w', suffix='.xer', delete=False,
                                     encoding='utf-8') as f:
        f.write(_xer(_rows() if rows is None else rows,
                     _RELS if rels is None else rels, **kw))
        path = f.name
    try:
        with _warnings.catch_warnings():
            _warnings.simplefilter('ignore')
            return validate_critical_path(parse_xer(path))
    finally:
        os.unlink(path)


def _needs_engine():
    """Skip a test that needs the engine's working-day arithmetic."""
    if _engine_date_helpers() is None:
        raise unittest.SkipTest(
            "cpp-cpm-engine's cpm module is not importable, so only the same "
            "day counts as finishing with the network")


def _terminals(results):
    return sorted(results['terminal_milestones'])


def _no_successor_findings(results):
    """Check 3's missing-successor findings off the critical path."""
    return sorted(r['affected_activity'] for r in results['recommendations']
                  if r['category'] == 'Open Ends'
                  and 'no successors' in r['finding'])


def _finding(results, code):
    return next(r['finding'] for r in results['recommendations']
                if r['category'] == 'Open Ends' and r['affected_activity'] == code
                and 'no successors' in r['finding'])


def _open_ends(results):
    return results['checks']['open_ends_cp']


def _open_end_successors(results):
    """Every activity Check 3 counts as missing a successor."""
    return sorted(e['task_code'] for e in results['open_ends']['no_succ']
                  if not e['is_terminal'])


def _dcma_missing_succ(results):
    return sorted(results['dcma_14']['per_check']['DCMA-01-Logic']['details']
                  ['missing_succ'])


def _continuity(results):
    return results['checks']['logic_continuity']


def _disconnected(results):
    return sorted(d['task_code'] for d in _continuity(results)['disconnected_activities'])


# ─────────────────────────────────────────── the fixture is what it says it is

def test_the_fixture_is_the_pattern_as_p6_dates_it():
    r = _validate()
    # everything floats against the Must Finish By: no critical activity
    assert r['critical_path_activities'] == []


# ─────────────────────── the reported case: the completion milestone flagged

def test_a_finish_milestone_floating_against_a_must_finish_by_is_the_terminal():
    r = _validate()
    assert _terminals(r) == ['F170']
    # the milestone that goes nowhere is the open end, not the completion
    assert _no_successor_findings(r) == ['F130']
    assert _open_ends(r)['total_no_succ'] == 1


def test_check_3_counts_the_missing_successors_dcma_14_counts():
    r = _validate()
    assert _open_end_successors(r) == _dcma_missing_succ(r) == ['F130']


def test_the_check_names_where_the_network_finishes():
    # once, in the check's note, rather than on every finding off the
    # critical path; the finding itself reads as it always did
    r = _validate()
    assert _open_ends(r)['note'].endswith(
        "The network finishes at 'F160 - Hand over to the owner', "
        "'F170 - Practical completion' (2027-03-29 17:00).")
    assert _finding(r, 'F130') == (
        "Activity 'F130 - Foundations complete' has no successors.")


def test_a_stale_scheduled_finish_does_not_excuse_a_floating_activity():
    # a scheduled finish left at an earlier date (the file was not
    # rescheduled after the finish moved) is not where the network ends: a
    # floating activity finishing on it is still an open end. A critical one
    # keeps the scheduled-finish rule it always had
    r = _validate(scd_end='2027-03-05 17:00')
    assert _terminals(r) == ['F170']
    assert _no_successor_findings(r) == ['F130']


def test_a_file_with_no_float_written_reads_the_same():
    # a blank total float is no float: nothing is critical, and the position
    # of the completion milestone still makes it the terminal
    rows = _rows()
    for row in rows:
        row[10] = ''
    r = _validate(rows)
    assert r['critical_path_activities'] == []
    assert _terminals(r) == ['F170']
    assert _no_successor_findings(r) == ['F130']


# ────────────────────────── finishing with the network, float or no float

def _clear_the_site():
    """Half a day after the close-in, finishing at noon on the last day with
    nothing after it: its late finish is the Must Finish By, so it carries
    four hours more float than the chain."""
    return _row('165', 'F165', 'Clear the site', 4, '2027-03-29 08:00',
                '2027-03-29 12:00', '2027-04-19 13:00', MUST_FINISH_BY, 124)


def test_work_finishing_on_the_last_day_is_at_the_finish():
    r = _validate(_rows() + [_clear_the_site()], _RELS + [('165', '150', 'PR_FS', 0)])
    assert _terminals(r) == ['F165', 'F170']
    assert _no_successor_findings(r) == ['F130']


def test_logic_continuity_anchors_on_every_terminal():
    # Check 8 folds Check 3's terminals into its completion anchors: work
    # that ends with the network is not reported as cut off from it
    r = _validate(_rows() + [_clear_the_site()], _RELS + [('165', '150', 'PR_FS', 0)])
    lc = _continuity(r)
    assert set(_terminals(r)) <= set(lc['completion_anchors'])
    assert 'F165' not in _disconnected(r)


def test_dcma_14_still_counts_a_task_that_ends_the_network():
    # DCMA-14 #1 excuses only a finish milestone, at the latest finish of all
    # the work: the site clearance is Check 3's terminal and still missing a
    # successor there
    r = _validate(_rows() + [_clear_the_site()], _RELS + [('165', '150', 'PR_FS', 0)])
    assert _open_end_successors(r) == ['F130']
    assert _dcma_missing_succ(r) == ['F130', 'F165']


def _no_float(code, name, hrs, es, ef, *, ttype='TT_Task'):
    """A row as a file with no float written carries it: early dates only."""
    return _row(code[1:], code, name, hrs, es, ef, '', '', '', ttype=ttype)


def _two_ends_rows(services_finish='2027-03-26 17:00', services_hrs=40):
    """Two chains end the network in a file with no float written: the
    services commissioning closes on a Friday evening (or earlier), and the
    owner's move-in, a start milestone, opens the Monday morning after the
    close-in. Nothing is critical."""
    return [
        _row('100', 'F100', 'Site handover', 40, DATA_DATE, DATA_DATE,
             DATA_DATE, DATA_DATE, '', status='TK_Complete',
             act=('2027-02-22 08:00', '2027-02-26 17:00')),
        _no_float('F110', 'Excavate', 24, '2027-03-01 08:00', '2027-03-03 17:00'),
        _no_float('F120', 'Pour the footings', 16, '2027-03-04 08:00',
                  '2027-03-05 17:00'),
        _no_float('F130', 'Foundations complete', 0, '2027-03-05 17:00',
                  '2027-03-05 17:00', ttype='TT_FinMile'),
        _no_float('F140', 'Erect the frame', 80, '2027-03-08 08:00',
                  '2027-03-19 17:00'),
        _no_float('F150', 'Close in', 40, '2027-03-22 08:00', '2027-03-26 17:00'),
        _no_float('F160', 'Commission the services', services_hrs,
                  '2027-03-22 08:00', services_finish),
        _no_float('F170', 'Owner move-in', 0, '2027-03-29 08:00',
                  '2027-03-29 08:00', ttype='TT_Mile'),
    ]


_TWO_ENDS_RELS = [
    ('110', '100', 'PR_FS', 0), ('120', '110', 'PR_FS', 0),
    ('130', '120', 'PR_FS', 0), ('140', '120', 'PR_FS', 0),
    ('150', '140', 'PR_FS', 0), ('160', '140', 'PR_FS', 0),
    ('170', '150', 'PR_FS', 0),
]


def test_work_closing_the_working_day_before_the_finish_is_at_the_finish():
    # Friday 17:00 and Monday 08:00 are the same working instant on the
    # five-day calendar, so the commissioning ends with the move-in; the
    # move-in, a start milestone, is where the network ends. DCMA-14 #1,
    # which excuses only a finish milestone, counts both
    _needs_engine()
    r = _validate(_two_ends_rows(), _TWO_ENDS_RELS, scd_end='2027-03-29 08:00',
                  plan_end='')
    assert r['critical_path_activities'] == []
    assert _terminals(r) == ['F160', 'F170']
    assert _no_successor_findings(r) == ['F130']
    assert _dcma_missing_succ(r) == ['F130', 'F160', 'F170']


def test_a_working_day_between_leaves_it_an_open_end():
    # closing on Thursday, the commissioning is a working day short of the
    # finish: it is an open end
    r = _validate(_two_ends_rows('2027-03-25 17:00', 32), _TWO_ENDS_RELS,
                  scd_end='2027-03-29 08:00', plan_end='')
    assert _terminals(r) == ['F170']
    assert _no_successor_findings(r) == ['F130', 'F160']


def test_a_dead_end_tied_only_to_a_level_of_effort_is_not_the_end():
    # the final clean hangs off the site supervision, a level of effort,
    # and is held to the last day. A tie to a level of effort is not logic,
    # so it is not part of the network: it is reported, and logic continuity
    # does not take it as an anchor
    rows = _rows() + [
        _row('190', 'F190', 'Site supervision', 0, '2027-03-01 08:00', FINISH,
             '2027-03-01 08:00', FINISH, '', ttype='TT_LOE'),
        _row('195', 'F195', 'Final clean', 8, '2027-03-29 08:00', FINISH,
             '2027-04-19 08:00', MUST_FINISH_BY, 120, cstr='CS_MSOA',
             cstr_date='2027-03-29 08:00'),
    ]
    rels = _RELS + [('190', '110', 'PR_SS', 0), ('190', '160', 'PR_FF', 0),
                    ('195', '190', 'PR_SS', 0)]
    r = _validate(rows, rels)
    assert _terminals(r) == ['F170']
    assert _no_successor_findings(r) == ['F130', 'F195']
    assert 'F195' in _disconnected(r)


# ───────────────────────────────────────── what is still an open end

def test_an_activity_tied_to_nothing_is_not_the_end_on_the_last_day():
    # held to start on the last day and tied to nothing: it finishes with the
    # network but is not part of it, so its missing successor is reported and
    # logic continuity does not take it as an anchor
    unlinked = _row('900', 'F900', 'Temporary works removed', 8,
                    '2027-03-29 08:00', FINISH, '2027-04-19 08:00',
                    MUST_FINISH_BY, 120, cstr='CS_MSOA',
                    cstr_date='2027-03-29 08:00')
    r = _validate(_rows() + [unlinked])
    assert _terminals(r) == ['F170']
    assert _no_successor_findings(r) == ['F130', 'F900']
    assert 'F900' in _disconnected(r)


def test_with_no_early_dates_in_the_file_the_rule_is_as_before():
    # no position to read: only a critical activity can be the terminal, as
    # before, so the floating completion milestone is still reported
    rows = _rows()
    for row in rows:
        row[13] = row[14] = row[15] = row[16] = ''   # early and remaining dates
    r = _validate(rows)
    assert _terminals(r) == []
    assert _no_successor_findings(r) == ['F130', 'F170']


# ─────────────────────── nothing is exempt from the missing-predecessor count

def test_an_incomplete_start_milestone_is_an_open_end():
    # the start milestone has to be complete: not started, with nothing
    # before it, it is counted, although DCMA-14 #1 excuses it as the start
    # of the network
    rows = [
        _milestone('100', 'F100', 'Notice to proceed', DATA_DATE,
                   '2027-03-22 08:00', 120, ttype='TT_Mile', drv='Y'),
    ] + _rows()[1:]
    r = _validate(rows)
    assert [e['task_code'] for e in r['open_ends']['no_pred']] == ['F100']
    assert _open_ends(r)['total_no_pred'] == 1
    assert any(x['category'] == 'Open Ends' and x['affected_activity'] == 'F100'
               and 'no predecessors' in x['finding']
               for x in r['recommendations'])
    assert 'F100' not in (r['dcma_14']['per_check']['DCMA-01-Logic']['details']
                          ['missing_pred'])


def test_a_complete_start_milestone_is_not_an_open_end():
    # the same milestone, complete: nothing is missing a predecessor, and the
    # only open end left is the foundations milestone's missing successor
    rows = [
        _row('100', 'F100', 'Notice to proceed', 0, DATA_DATE, DATA_DATE,
             DATA_DATE, DATA_DATE, '', ttype='TT_Mile', status='TK_Complete',
             act=('2027-02-26 17:00', '2027-02-26 17:00')),
    ] + _rows()[1:]
    r = _validate(rows)
    assert r['open_ends']['no_pred'] == []
    oe = _open_ends(r)
    assert (oe['total_no_pred'], oe['total_no_succ']) == (0, 1)


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
