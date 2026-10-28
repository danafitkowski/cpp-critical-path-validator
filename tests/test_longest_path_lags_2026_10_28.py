#!/usr/bin/env python3
"""Check 2's longest path lays lags and SS/FF overlaps (2026-10-28).

Run with: python tests/test_longest_path_lags_2026_10_28.py

Check 2 flags a zero-float activity that is not on the longest path as critical
by float alone. It rebuilt the longest path with cpm.compute_lpm, which lays no
lag. On a schedule whose critical path runs through start-to-start overlaps with
lags, the lag-free path ended on another chain, and Check 2 raised Critical
findings on activities P6 has on its Longest Path. Check 2 now reads the longest
path from the driving path traced on the file's stored dates, to the minute
(scripts/driving_path.py, CPP's internal tracer, vendored), and keeps
compute_lpm for a file the trace cannot read.

The public engine has no compute_lpm, so from this repository the cross-check
did not run at all before; it runs now wherever cpp-cpm-engine is on the path.
The tests that trace need the engine and are skipped without it. The canonical
version of the first four is CPP's internal test of the same name.
"""
import os
import sys
import tempfile
import types
import unittest
import warnings as _warnings

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, '..', 'scripts'))

from xer_parser import parse_xer  # noqa: E402
import cp_validator  # noqa: E402
import driving_path  # noqa: E402
from cp_validator import validate_critical_path  # noqa: E402

TAB = '\t'
_MONFRI_BLOB = (
    '(0||CalendarData()((0||DaysOfWeek()((0||1()())'
    + ''.join(
        '(0||%d()((0||0(s|08:00|f|12:00)())(0||1(s|13:00|f|17:00)())))' % d
        for d in range(2, 7))
    + '(0||7()())))(0||Exceptions()())))'
)
_TASK_COLS = ['task_id', 'task_code', 'task_name', 'proj_id', 'wbs_id',
              'clndr_id', 'status_code', 'task_type', 'target_drtn_hr_cnt',
              'remain_drtn_hr_cnt', 'total_float_hr_cnt', 'early_start_date',
              'early_end_date', 'restart_date', 'reend_date',
              'late_start_date', 'late_end_date', 'target_start_date',
              'target_end_date', 'driving_path_flag', 'cstr_type', 'cstr_date']


def _needs_engine():
    """Skip a test that traces: the trace needs cpp-cpm-engine's calendar arithmetic."""
    if driving_path.minute_date_helpers() is None:
        raise unittest.SkipTest(
            "cpp-cpm-engine's cpm module is not importable, so the driving path "
            "cannot be traced")


def _row(tid, code, hrs, es, ef, ls, lf, tf, ttype='TT_Task', cstr=('', '')):
    return [tid, code, 'Neutral ' + code, '1', 'W1', 'C1', 'TK_NotStart', ttype, str(hrs), str(hrs), str(tf),
            es, ef, es, ef, ls, lf, es, ef, 'Y' if float(tf) <= 0 and not cstr[0] else 'N', cstr[0], cstr[1]]


# Monday-to-Friday, data date Mon 31-Aug-2026. S (1 d) starts three overlapped trades and a side run:
#   E1 (20 d)  -SS 10 / FF 0->  E2 (20 d)  -SS 10 / FF 0->  E3 (20 d)  -> F (finish)
#   X (35 d) -> F, five days of float.
# With its lags the trade chain is the longest (F on Mon 26-Oct); stripped of them it is 21 days against X's 36.
_TASKS = [
    _row('1', 'S', 8, '2026-08-31 08:00', '2026-08-31 17:00', '2026-08-31 08:00', '2026-08-31 17:00', 0),
    _row('2', 'E1', 160, '2026-09-01 08:00', '2026-09-28 17:00', '2026-09-01 08:00', '2026-09-28 17:00', 0),
    _row('3', 'E2', 160, '2026-09-15 08:00', '2026-10-12 17:00', '2026-09-15 08:00', '2026-10-12 17:00', 0),
    _row('4', 'E3', 160, '2026-09-29 08:00', '2026-10-26 17:00', '2026-09-29 08:00', '2026-10-26 17:00', 0),
    _row('5', 'X', 280, '2026-09-01 08:00', '2026-10-19 17:00', '2026-09-08 08:00', '2026-10-26 17:00', 40),
    _row('6', 'F', 0, '2026-10-26 17:00', '2026-10-26 17:00', '2026-10-26 17:00', '2026-10-26 17:00', 0,
         ttype='TT_FinMile'),
]
# (task_id, pred_task_id, type, lag hours)
_RELS = [('2', '1', 'PR_FS', 0), ('3', '2', 'PR_SS', 80), ('3', '2', 'PR_FF', 0),
         ('4', '3', 'PR_SS', 80), ('4', '3', 'PR_FF', 0), ('6', '4', 'PR_FS', 0),
         ('5', '1', 'PR_FS', 0), ('6', '5', 'PR_FS', 0)]
_OPTIONS = ('Y', 'N', 'rcal_Predecessor', 'Y')   # retained logic, progress override, lag calendar, SS lag from ES


def _xer(tasks=_TASKS, rels=_RELS, options=_OPTIONS):
    lines = [
        TAB.join(['ERMHDR', '24.12', '2026-10-28', 'Project', 'admin', 'Neutral', 'db', 'Project Management',
                  'CAD']),
        TAB.join(['%T', 'PROJECT']),
        TAB.join(['%F', 'proj_id', 'proj_short_name', 'last_recalc_date', 'plan_end_date', 'scd_end_date',
                  'clndr_id']),
        TAB.join(['%R', '1', 'NEUTRAL', '2026-08-31 08:00', '', '2026-10-26 17:00', 'C1']),
        TAB.join(['%T', 'PROJWBS']),
        TAB.join(['%F', 'wbs_id', 'parent_wbs_id', 'wbs_name', 'wbs_short_name', 'proj_id']),
        TAB.join(['%R', 'W1', '', 'Root', 'W1', '1']),
        TAB.join(['%T', 'CALENDAR']),
        TAB.join(['%F', 'clndr_id', 'clndr_name', 'clndr_type', 'day_hr_cnt', 'week_hr_cnt', 'clndr_data']),
        TAB.join(['%R', 'C1', 'Five Day', 'CA_Base', '8', '40', _MONFRI_BLOB]),
        TAB.join(['%T', 'TASK']),
        TAB.join(['%F'] + _TASK_COLS),
    ]
    lines += [TAB.join(['%R'] + row) for row in tasks]
    lines += [
        TAB.join(['%T', 'TASKPRED']),
        TAB.join(['%F', 'task_pred_id', 'task_id', 'pred_task_id', 'pred_type', 'lag_hr_cnt']),
    ]
    lines += [TAB.join(['%R', str(i), s, p, t, str(lag)]) for i, (s, p, t, lag) in enumerate(rels, 1)]
    lines += [
        TAB.join(['%T', 'SCHEDOPTIONS']),
        TAB.join(['%F', 'schedoptions_id', 'proj_id', 'sched_retained_logic', 'sched_progress_override',
                  'sched_calendar_on_relationship_lag', 'sched_lag_early_start_flag']),
        TAB.join(['%R', '1', '1'] + list(options)),
        '%E',
    ]
    return '\r\n'.join(lines) + '\r\n'


def _validate(xer_text):
    with tempfile.NamedTemporaryFile('w', suffix='.xer', delete=False, encoding='utf-8') as f:
        f.write(xer_text)
        path = f.name
    try:
        with _warnings.catch_warnings():
            _warnings.simplefilter('ignore')
            return validate_critical_path(parse_xer(path))
    finally:
        os.unlink(path)


class _Patched:
    """Set one module attribute, or one sys.modules entry, for the length of a with-block."""

    def __init__(self, obj, name, value):
        self.obj, self.name, self.value = obj, name, value
        self.is_dict = isinstance(obj, dict)

    def __enter__(self):
        if self.is_dict:
            self.had = self.name in self.obj
            self.old = self.obj.get(self.name)
            self.obj[self.name] = self.value
        else:
            self.had = hasattr(self.obj, self.name)
            self.old = getattr(self.obj, self.name, None)
            setattr(self.obj, self.name, self.value)
        return self.value

    def __exit__(self, *exc):
        if self.is_dict:
            if self.had:
                self.obj[self.name] = self.old
            else:
                self.obj.pop(self.name, None)
        elif self.had:
            setattr(self.obj, self.name, self.old)
        else:
            delattr(self.obj, self.name)
        return False


def _narrative_stub(calls, takes_longest_path=True):
    """A driver_chain_narrative module that records what the validator hands it."""
    mod = types.ModuleType('driver_chain_narrative')
    if takes_longest_path:
        def build_driver_chain_narrative(cpm_result, target_codes=None, jurisdiction='US-FED', max_depth=10,
                                         longest_path_codes=None):
            calls.append({'target_codes': target_codes, 'longest_path_codes': longest_path_codes})
            return {'narratives': [], 'manifest': {'stub': True}}
    else:
        def build_driver_chain_narrative(cpm_result, target_codes=None, jurisdiction='US-FED', max_depth=10):
            calls.append({'target_codes': target_codes})
            return {'narratives': [], 'manifest': {'stub': True}}
    mod.build_driver_chain_narrative = build_driver_chain_narrative
    return mod


def test_the_overlapped_trades_are_on_the_longest_path():
    _needs_engine()
    results = _validate(_xer())
    cd = results['checks']['constraint_driven']
    assert cd['lpm_basis'] == 'traced' and cd['lpm_trace_reason'] == ''
    assert cd['lpm_confirmed_false_cp'] == []
    assert cd['lpm_error'] is None
    assert cd['rating'] == 'GREEN' and cd['score'] == 100
    assert 'diverge' not in cd['note']
    assert not [r for r in results['recommendations'] if r['category'] == 'Constraint-Driven CP']


def test_the_narrative_is_handed_the_same_path():
    """The narrative's false-CP label reads the traced path, as task_ids (its network is keyed by them)."""
    _needs_engine()
    calls = []
    with _Patched(sys.modules, 'driver_chain_narrative', _narrative_stub(calls)):
        dcn = _validate(_xer())['driver_chain_narrative']
    assert 'error' not in dcn, dcn
    assert len(calls) == 1
    assert calls[0]['longest_path_codes'] == {'1', '2', '3', '4', '6'}      # S, E1, E2, E3, F; not X


def test_a_narrative_without_the_argument_still_runs():
    """A narrative module older than 28-Oct-2026 takes no longest_path_codes and computes its own."""
    _needs_engine()
    calls = []
    with _Patched(sys.modules, 'driver_chain_narrative', _narrative_stub(calls, takes_longest_path=False)):
        dcn = _validate(_xer())['driver_chain_narrative']
    assert 'error' not in dcn, dcn
    assert dcn['manifest'] == {'stub': True}
    assert len(calls) == 1


def test_zero_float_held_by_a_constraint_off_the_path_is_still_flagged():
    """Y (5 d) feeds the finish with a Finish On or Before at its own early finish: zero float, no driving
    relationship to the finish. The traced path leaves it out, and Check 2 names its constraint."""
    _needs_engine()
    y = _row('7', 'Y', 40, '2026-09-01 08:00', '2026-09-07 17:00', '2026-09-01 08:00', '2026-09-07 17:00', 0,
             cstr=('CS_MEOB', '2026-09-07 17:00'))
    results = _validate(_xer(_TASKS + [y], _RELS + [('7', '1', 'PR_FS', 0), ('6', '7', 'PR_FS', 0)]))
    cd = results['checks']['constraint_driven']
    assert cd['lpm_basis'] == 'traced'
    assert cd['lpm_confirmed_false_cp'] == ['7']
    assert cd['rating'] != 'GREEN' and cd['score'] < 100
    assert '1 zero-float activity diverges' in cd['note'] and 'LPM' not in cd['note']
    recs = [r for r in results['recommendations']
            if r['category'] == 'Constraint-Driven CP' and r.get('affected_activity') == 'Y']
    assert recs and 'Finish On or Before' in recs[0]['finding']
    assert not any('lag or overlap link' in r['finding'] for r in results['recommendations'])


def test_without_stored_early_dates_the_duration_only_path_runs_and_says_so():
    _needs_engine()
    rows = [list(r) for r in _TASKS]
    for r in rows:
        for i in (11, 12, 13, 14):      # early start / finish, restart / reend
            r[i] = ''
    cd = _validate(_xer(rows))['checks']['constraint_driven']
    assert cd['lpm_basis'] == 'duration-only'
    assert 'early dates' in cd['lpm_trace_reason']


def test_without_the_engine_the_trace_says_why():
    with _Patched(driving_path, 'minute_date_helpers', lambda: None):
        cd = _validate(_xer())['checks']['constraint_driven']
    assert cd['lpm_basis'] == 'duration-only'
    assert cd['lpm_trace_reason'] == 'the engine date arithmetic is unavailable'


def test_a_trace_that_fails_falls_back_and_says_why():
    def _boom(*a, **k):
        raise RuntimeError('boom')
    with _Patched(cp_validator, '_trace_schedule', _boom):
        cd = _validate(_xer())['checks']['constraint_driven']
    assert cd['lpm_basis'] == 'duration-only'
    assert cd['lpm_trace_reason'] == 'the trace failed (boom)'


def test_the_trace_is_handed_the_files_scheduling_options():
    """The trace schedules as the file does: progress override and "lag from Actual Start" read from
    SCHEDOPTIONS, as the internal validator reads them, and reported in schedule_options."""
    seen = []

    def _spy(data, proj_id, **kw):
        seen.append(kw)
        return {'traced': False, 'reason': 'spied'}
    with _Patched(cp_validator, '_trace_schedule', _spy):
        default = _validate(_xer())
        other = _validate(_xer(options=('N', 'Y', 'rcal_Successor', 'N')))
    assert [kw['resolution'] for kw in seen] == ['minute', 'minute']
    assert seen[0]['options']['schedule_mode'] == 'retained_logic'
    assert seen[0]['options']['ss_lag_from'] == 'early_start'
    assert seen[1]['options']['schedule_mode'] == 'progress_override'
    assert seen[1]['options']['ss_lag_from'] == 'actual_start'
    assert seen[1]['options']['lag_calendar_role'] == 'successor'
    assert default['schedule_options']['schedule_mode_source'] == 'SCHEDOPTIONS sched_retained_logic=Y'
    assert other['schedule_options']['schedule_mode_source'] == 'SCHEDOPTIONS sched_progress_override=Y'
    assert other['schedule_options']['ss_lag_from_source'] == 'SCHEDOPTIONS sched_lag_early_start_flag=N'
    assert other['checks']['constraint_driven']['lpm_trace_reason'] == 'spied'


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
