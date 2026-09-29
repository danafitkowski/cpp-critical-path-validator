#!/usr/bin/env python3
"""Guards on the DCMA-14 module's shape: the published numbering, no free
points, the working-day arithmetic behind CPLI, and the in-project
relationship set.

Run with: python tests/test_dcma14_guards.py

Most of these read the source rather than run it: they pin a spelling that a
regression would have to change, and say why the spelling matters. The two
that run code pin the working-day advance CPLI measures the critical path
with, and its refusal to compute on a sentinel finish date.
"""
import os
import pathlib
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, '..', 'scripts'))

SCRIPTS = pathlib.Path(SCRIPT_DIR).resolve().parent / 'scripts'
CPV = (SCRIPTS / 'cp_validator.py').read_text(encoding='utf-8')
DCMA = (SCRIPTS / 'dcma14.py').read_text(encoding='utf-8')


def test_cpli_no_crash_on_unbounded_finish_date():
    """A CP finish more than a hundred years out is a sentinel date, not a
    schedule window. work_day_delta refuses it with None, and CPLI must report
    not-computable rather than fail on `None <= 0`."""
    from dcma14 import _check_13_cpli
    cp_tasks = [{'task_id': 'A', 'task_code': 'A',
                 'early_end_date': '2200-01-01',  # >100yr from the data date
                 'total_float_hr_cnt': '0', 'clndr_id': 'C1'}]
    rating, value, threshold, note, extra = _check_13_cpli(
        cp_tasks, {}, datetime(2026, 1, 1), {'dcma_cpli_min': 0.95})
    assert extra['cpli'] is None, (
        'an uncomputable CP length (work_day_delta None) must return CPLI '
        'not-computable, not crash with TypeError on None <= 0')
    assert rating == 'INFO'


def test_work_day_delta_counts_working_days_on_the_calendar():
    """The working-day advance CPLI divides by: the half-open interval
    (earlier, later], so Friday to Monday on a five-day week is one working
    day whatever the clock times, the same day is zero, and the reverse
    direction is negative. A holiday on the calendar is not counted, and a
    missing date gives None."""
    from dcma14 import work_day_delta
    five_day = {'work_days': [1, 2, 3, 4, 5], 'holidays': []}
    fri, mon = datetime(2026, 4, 24, 17), datetime(2026, 4, 27, 8)
    assert work_day_delta(fri, mon, five_day) == 1
    assert work_day_delta(mon, fri, five_day) == -1
    assert work_day_delta(mon, mon, five_day) == 0
    assert work_day_delta(datetime(2026, 4, 27, 8), datetime(2026, 4, 27, 17), five_day) == 0
    # ten working days across two weekends
    assert work_day_delta(datetime(2026, 4, 24), datetime(2026, 5, 8), five_day) == 10
    # a holiday inside the span is not a working day
    with_holiday = {'work_days': [1, 2, 3, 4, 5], 'holidays': ['2026-05-01']}
    assert work_day_delta(datetime(2026, 4, 24), datetime(2026, 5, 8), with_holiday) == 9
    # a worked exception (a Saturday the calendar works) is one
    worked_saturday = {'work_days': [1, 2, 3, 4, 5], 'holidays': [],
                       'special_workdays': ['2026-04-25']}
    assert work_day_delta(fri, mon, worked_saturday) == 2
    # an explicit holiday wins over an explicit worked exception
    both = {'work_days': [1, 2, 3, 4, 5], 'holidays': ['2026-04-25'],
            'special_workdays': ['2026-04-25']}
    assert work_day_delta(fri, mon, both) == 1
    # strings are read on their date; a missing date is None
    assert work_day_delta('2026-04-24 17:00', '2026-04-27 08:00', five_day) == 1
    assert work_day_delta('', mon, five_day) is None
    assert work_day_delta(mon, None, five_day) is None


def test_cp_continuity_accepts_a_floated_merge_input():
    """A critical activity fed by the critical chain and by a floated
    predecessor is continuous: the floated input is an ordinary merge, not a
    break. The previous reading called every incomplete non-critical
    predecessor of a critical activity a gap, so every merge point reported a
    discontinuity."""
    from dcma14 import _cp_continuity
    task_map = {
        'A': {'task_id': 'A', 'task_code': 'A', 'status_code': 'TK_NotStart',
              'total_float_hr_cnt': '0', 'driving_path_flag': 'Y'},
        'D': {'task_id': 'D', 'task_code': 'D', 'status_code': 'TK_NotStart',
              'total_float_hr_cnt': '80', 'driving_path_flag': 'N'},
        'G': {'task_id': 'G', 'task_code': 'G', 'status_code': 'TK_NotStart',
              'total_float_hr_cnt': '0', 'driving_path_flag': 'Y'},
    }
    cp_tasks = [task_map['A'], task_map['G']]
    pred_map = {'G': [{'pred_task_id': 'A', 'pred_type': 'PR_FS'},
                      {'pred_task_id': 'D', 'pred_type': 'PR_FS'}]}
    out = _cp_continuity(cp_tasks, pred_map, task_map)
    assert out == {'continuous': True, 'gaps': [], 'cp_activities_checked': 2}, out


def test_cp_continuity_reports_a_break_with_its_evidence():
    """A critical activity reached only from off-path work is a break, and the
    gap carries the predecessor's status, driving flag, float and tie type so
    the evidence shows its own work. An activity with no predecessor at all is
    a chain start, not a break."""
    from dcma14 import _cp_continuity
    task_map = {
        'A': {'task_id': 'A', 'task_code': 'A', 'status_code': 'TK_NotStart',
              'total_float_hr_cnt': '0', 'driving_path_flag': 'Y'},
        'D': {'task_id': 'D', 'task_code': 'D', 'status_code': 'TK_Active',
              'total_float_hr_cnt': '80', 'driving_path_flag': 'N'},
        'G': {'task_id': 'G', 'task_code': 'G', 'status_code': 'TK_NotStart',
              'total_float_hr_cnt': '0', 'driving_path_flag': 'Y'},
    }
    cp_tasks = [task_map['A'], task_map['G']]
    pred_map = {'G': [{'pred_task_id': 'D', 'pred_type': 'PR_SS'}]}
    out = _cp_continuity(cp_tasks, pred_map, task_map)
    assert out['continuous'] is False
    assert out['cp_activities_checked'] == 2
    assert out['gaps'] == [{
        'cp_task': 'G', 'gap_pred': 'D', 'gap_pred_status': 'TK_Active',
        'gap_pred_driving': 'N', 'gap_pred_total_float_hr': '80',
        'rel_type': 'PR_SS'}], out['gaps']


def test_check2_guards_no_critical_path():
    assert 'if cp_count == 0:' in CPV, (
        'Check 2 must special-case cp_count==0 (no CP) instead of falling '
        'through to the 0%-constrained GREEN branch and inflating the score.')


def test_no_low_contrast_slate_text_in_the_scorecard():
    assert '#64748b' not in DCMA, (
        'low-contrast #64748b text in the DCMA scorecard; use #94a3b8 on the '
        'dark background')


def test_cpli_uses_working_day_length():
    assert 'work_day_delta(data_date_dt, latest_ef' in DCMA, (
        'CPLI CP length must use work_day_delta (working days), not '
        'wall-clock hours/8.')
    assert '(latest_ef - data_date_dt).total_seconds()' not in DCMA, (
        'CPLI still computes wall-clock hours for CP length')


def test_preds_for_project_requires_both_endpoints_in_project():
    assert ("p.get('task_id', '') in task_map and "
            "p.get('pred_task_id', '') in task_map") in DCMA, (
        'preds_for_project must require BOTH endpoints in-project (and), not '
        'either (or), to exclude cross-project links from DCMA #1/#2/#3/#4.')


def test_dcma_registry_has_no_free_passes():
    """No echo rows, no unconditional increment, the published numbering.

    The registry used to assign #11 to a "Future Actuals" echo of #9 and #12
    to a "Resource Coverage" echo of #10, each repeating the other's verdict
    and scoring it again, so the Critical Path Test was absent and Missed
    Tasks, CPLI and BEI sat off their published numbers.
    """
    assert "'DCMA-11-InvalidDatesFuture'" not in DCMA, (
        'DCMA #11 is Missed Tasks, not a "Future Actuals" echo of #9')
    assert "'DCMA-12-ResourceCoverage'" not in DCMA, (
        'DCMA #12 is the Critical Path Test, not a resource echo of #10')
    for cid in ("'DCMA-11-MissedTasks'", "'DCMA-12-CriticalPathTest'",
                "'DCMA-13-CPLI'", "'DCMA-14-BEI'"):
        assert cid in DCMA, f'{cid} missing — published DCMA numbering required'


if __name__ == '__main__':
    tests = [f for name, f in list(globals().items())
             if name.startswith('test_') and callable(f)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f'ok  {t.__name__}')
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
    print(f'{len(tests)} / {len(tests)} passed')
