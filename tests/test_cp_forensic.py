"""
Forensic audit test — cp_validator silent-bug regression suite.

These tests lock in fixes to silent arithmetic bugs that quietly
produced wrong lag-day numbers on non-8hr-per-day calendars.

Specifically locks in:
  - BUG: Lag hours → days conversion was hardcoded at 8.0 hr/day.
    For 10hr and 24hr calendars, every negative-lag finding on the
    CP had the wrong "days" value.
"""

import sys, os, tempfile

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.normpath(os.path.join(_TESTS_DIR, '..', 'scripts'))
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from cp_validator import validate_critical_path


def run_test(name, fn):
    try:
        fn()
        print(f"ok  {name}")
        return True
    except AssertionError as e:
        print(f"FAIL {name}: {e}")
        return False
    except Exception as e:
        print(f"ERR  {name}: {type(e).__name__}: {e}")
        return False


def _build_data(lag_hrs, hours_per_day=8.0):
    """Build minimal XER data with one negative-lag relationship on the CP.

    Both predecessor and successor are critical (TF=0). Calendar has the
    given hours_per_day. Lag on the relationship is `lag_hrs` hours.
    """
    return {
        'tables': {
            'PROJECT': {
                'fields': ['proj_id', 'proj_short_name', 'last_recalc_date', 'plan_end_date'],
                'records': [{'proj_id': 'P1', 'proj_short_name': 'TEST',
                             'last_recalc_date': '2026-04-23', 'plan_end_date': '2026-05-01'}],
            },
            'CALENDAR': {
                'fields': ['clndr_id', 'clndr_name', 'day_hr_cnt', 'week_hr_cnt',
                           'default_flag', 'clndr_type', 'clndr_data'],
                'records': [{
                    'clndr_id': 'C1', 'clndr_name': 'TestCal',
                    'day_hr_cnt': str(hours_per_day),
                    'week_hr_cnt': str(hours_per_day * 5),
                    'default_flag': 'Y',
                    'clndr_type': 'CA_Base',
                    'clndr_data': '',
                }],
            },
            'TASK': {
                'fields': ['task_id', 'proj_id', 'task_code', 'task_name',
                           'task_type', 'status_code', 'total_float_hr_cnt',
                           'clndr_id', 'crt_path_num', 'cstr_type', 'cstr_type2',
                           'driving_path_flag', 'early_end_date'],
                'records': [
                    {'task_id': 'T1', 'proj_id': 'P1', 'task_code': 'A10',
                     'task_name': 'Pred', 'task_type': 'TT_Task',
                     'status_code': 'TK_NotStart', 'total_float_hr_cnt': '0',
                     'clndr_id': 'C1', 'crt_path_num': '1', 'cstr_type': '',
                     'cstr_type2': '', 'driving_path_flag': '',
                     'early_end_date': ''},
                    {'task_id': 'T2', 'proj_id': 'P1', 'task_code': 'A20',
                     'task_name': 'Succ', 'task_type': 'TT_Task',
                     'status_code': 'TK_NotStart', 'total_float_hr_cnt': '0',
                     'clndr_id': 'C1', 'crt_path_num': '1', 'cstr_type': '',
                     'cstr_type2': '', 'driving_path_flag': '',
                     'early_end_date': ''},
                ],
            },
            'TASKPRED': {
                'fields': ['task_id', 'pred_task_id', 'pred_type', 'lag_hr_cnt'],
                'records': [
                    {'task_id': 'T2', 'pred_task_id': 'T1',
                     'pred_type': 'PR_FS', 'lag_hr_cnt': str(lag_hrs)},
                ],
            },
        }
    }


def test_lag_days_8hr_calendar():
    """8hr calendar: -40hr lag → -5d (unchanged from old behavior)."""
    data = _build_data(lag_hrs=-40, hours_per_day=8.0)
    r = validate_critical_path(data)
    # cp_neg_lags should be 1, with lag_days = -5.0
    lag_recs = [rec for rec in r['recommendations']
                if rec['category'] == 'Negative Lags on CP']
    assert len(lag_recs) == 1, f"Expected 1 neg-lag rec, got {len(lag_recs)}"
    assert '-5.0d' in lag_recs[0]['finding'], \
        f"Expected -5.0d in finding, got: {lag_recs[0]['finding']}"


def test_lag_days_10hr_calendar():
    """10hr calendar: -40hr lag → -4d, NOT -5d (was the bug)."""
    data = _build_data(lag_hrs=-40, hours_per_day=10.0)
    r = validate_critical_path(data)
    lag_recs = [rec for rec in r['recommendations']
                if rec['category'] == 'Negative Lags on CP']
    assert len(lag_recs) == 1
    # -40 hrs on 10hr/day calendar = -4 days, not -5
    assert '-4.0d' in lag_recs[0]['finding'], \
        f"Expected -4.0d on 10hr calendar, got: {lag_recs[0]['finding']}"


def test_lag_days_24hr_calendar():
    """24hr calendar (continuous utility work): -48hr lag → -2d, NOT -6d."""
    data = _build_data(lag_hrs=-48, hours_per_day=24.0)
    r = validate_critical_path(data)
    lag_recs = [rec for rec in r['recommendations']
                if rec['category'] == 'Negative Lags on CP']
    assert len(lag_recs) == 1
    # -48 hrs on 24hr/day calendar = -2 days, not -6
    assert '-2.0d' in lag_recs[0]['finding'], \
        f"Expected -2.0d on 24hr calendar, got: {lag_recs[0]['finding']}"


def test_excessive_lag_threshold_respects_calendar():
    """'Excessive' (> 10 days) should be calendar-aware.

    On 24hr calendar, a 96-hour lag is 4 days (not excessive),
    not 12 days (incorrectly excessive under the old hardcoded 8hr).
    """
    data = _build_data(lag_hrs=96, hours_per_day=24.0)
    r = validate_critical_path(data)
    # 96hr on 24hr calendar = 4 days — NOT excessive (<= 10d)
    assert r['checks']['lag_issues']['excessive_lags'] == 0, \
        f"96hr on 24hr calendar shouldn't be excessive, got {r['checks']['lag_issues']['excessive_lags']}"


def test_no_calendar_falls_back_to_8hr_default():
    """If the successor's calendar isn't in cal_map, fall back to 8hr default."""
    # Build data where task references a non-existent clndr_id
    data = _build_data(lag_hrs=-40, hours_per_day=8.0)
    # Point the tasks' clndr_id at a calendar that doesn't exist
    for t in data['tables']['TASK']['records']:
        t['clndr_id'] = 'GHOST'
    r = validate_critical_path(data)
    lag_recs = [rec for rec in r['recommendations']
                if rec['category'] == 'Negative Lags on CP']
    assert len(lag_recs) == 1
    # Falls back to 8hr → -40/8 = -5
    assert '-5.0d' in lag_recs[0]['finding'], \
        f"Expected -5.0d on fallback, got: {lag_recs[0]['finding']}"


# ── Runner ──────────────────────────

def main():
    tests = [
        test_lag_days_8hr_calendar,
        test_lag_days_10hr_calendar,
        test_lag_days_24hr_calendar,
        test_excessive_lag_threshold_respects_calendar,
        test_no_calendar_falls_back_to_8hr_default,
    ]
    passed = sum(run_test(t.__name__, t) for t in tests)
    print(f"\n{passed} / {len(tests)} passed")
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    sys.exit(main())
