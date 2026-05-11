#!/usr/bin/env python3
"""DCMA 14-Point assessment tests.

Run with: python tests/test_dcma14.py

Builds tiny synthetic XER-shaped data in memory and runs the DCMA 14
assessment against it. These tests lock in:
  - Clean-schedule pass (/14 = 14)
  - Individual-check detection (neg float, missing logic, invalid dates)
  - CPLI computation
  - BEI (both skipped and computed)
  - Profile strictness (nuclear tighter than commercial)
  - Multiple critical paths identification
  - Driving-path tracer
"""
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# In the public OSS layout, xer_parser.py + validation.py + config_profiles.py
# are all bundled under ../scripts. CPP-internal layout adds _cpp_common.
sys.path.insert(0, os.path.join(SCRIPT_DIR, '..', 'scripts'))
_INT_COMMON = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..', '_cpp_common', 'scripts'))
_INT_XER = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..', 'xer-parser', 'scripts'))
if os.path.isdir(_INT_COMMON):
    sys.path.insert(0, _INT_COMMON)
if os.path.isdir(_INT_XER):
    sys.path.insert(0, _INT_XER)

from dcma14 import dcma_14_assess, trace_driving_path  # noqa: E402


# ─────────────────────────────────────────────────────────────────────
# Synthetic data builders
# ─────────────────────────────────────────────────────────────────────

def _base_calendar():
    return {
        'fields': ['clndr_id', 'clndr_name', 'day_hr_cnt', 'week_hr_cnt',
                   'default_flag', 'clndr_type', 'clndr_data'],
        'records': [{
            'clndr_id': 'C1', 'clndr_name': '5-Day', 'day_hr_cnt': '8',
            'week_hr_cnt': '40', 'default_flag': 'Y', 'clndr_type': 'CA_Base',
            'clndr_data': '',
        }],
    }


def _base_project(data_date='2026-04-24 00:00', plan_end='2026-05-15 16:00'):
    return {
        'fields': ['proj_id', 'proj_short_name', 'last_recalc_date',
                   'plan_end_date', 'scd_end_date'],
        'records': [{
            'proj_id': 'P1', 'proj_short_name': 'TEST',
            'last_recalc_date': data_date,
            'plan_end_date': plan_end,
            'scd_end_date': plan_end,
        }],
    }


def _clean_schedule():
    """A 4-activity clean chain: T0 (start milestone) → A (FS) B (FS) C-milestone, TF=0.

    All relationships FS, no lags, no constraints, no future actuals,
    resource assignments present. Includes a start milestone so no
    activity has a missing predecessor.
    """
    data_date = '2026-04-24 00:00'
    return {
        'tables': {
            'PROJECT': _base_project(data_date),
            'CALENDAR': _base_calendar(),
            'TASK': {
                'fields': ['task_id', 'proj_id', 'task_code', 'task_name',
                           'task_type', 'status_code', 'total_float_hr_cnt',
                           'clndr_id', 'crt_path_num', 'cstr_type', 'cstr_type2',
                           'target_start_date', 'target_end_date',
                           'early_start_date', 'early_end_date',
                           'remain_drtn_hr_cnt', 'target_drtn_hr_cnt'],
                'records': [
                    {'task_id': 'T0', 'proj_id': 'P1', 'task_code': 'A00',
                     'task_name': 'Start', 'task_type': 'TT_Mile',
                     'status_code': 'TK_NotStart', 'total_float_hr_cnt': '0',
                     'clndr_id': 'C1', 'crt_path_num': '1', 'cstr_type': '',
                     'cstr_type2': '', 'target_start_date': '2026-04-27 08:00',
                     'target_end_date': '2026-04-27 08:00',
                     'early_start_date': '2026-04-27 08:00',
                     'early_end_date': '2026-04-27 08:00',
                     'remain_drtn_hr_cnt': '0', 'target_drtn_hr_cnt': '0'},
                    {'task_id': 'T1', 'proj_id': 'P1', 'task_code': 'A10',
                     'task_name': 'Alpha', 'task_type': 'TT_Task',
                     'status_code': 'TK_NotStart', 'total_float_hr_cnt': '0',
                     'clndr_id': 'C1', 'crt_path_num': '1', 'cstr_type': '',
                     'cstr_type2': '', 'target_start_date': '2026-04-27 08:00',
                     'target_end_date': '2026-05-01 16:00',
                     'early_start_date': '2026-04-27 08:00',
                     'early_end_date': '2026-05-01 16:00',
                     'remain_drtn_hr_cnt': '40', 'target_drtn_hr_cnt': '40'},
                    {'task_id': 'T2', 'proj_id': 'P1', 'task_code': 'A20',
                     'task_name': 'Bravo', 'task_type': 'TT_Task',
                     'status_code': 'TK_NotStart', 'total_float_hr_cnt': '0',
                     'clndr_id': 'C1', 'crt_path_num': '1', 'cstr_type': '',
                     'cstr_type2': '', 'target_start_date': '2026-05-04 08:00',
                     'target_end_date': '2026-05-08 16:00',
                     'early_start_date': '2026-05-04 08:00',
                     'early_end_date': '2026-05-08 16:00',
                     'remain_drtn_hr_cnt': '40', 'target_drtn_hr_cnt': '40'},
                    {'task_id': 'T3', 'proj_id': 'P1', 'task_code': 'A30',
                     'task_name': 'Finish', 'task_type': 'TT_FinMile',
                     'status_code': 'TK_NotStart', 'total_float_hr_cnt': '0',
                     'clndr_id': 'C1', 'crt_path_num': '1', 'cstr_type': '',
                     'cstr_type2': '', 'target_start_date': '2026-05-11 08:00',
                     'target_end_date': '2026-05-11 08:00',
                     'early_start_date': '2026-05-11 08:00',
                     'early_end_date': '2026-05-11 08:00',
                     'remain_drtn_hr_cnt': '0', 'target_drtn_hr_cnt': '0'},
                ],
            },
            'TASKPRED': {
                'fields': ['task_id', 'pred_task_id', 'pred_type', 'lag_hr_cnt'],
                'records': [
                    {'task_id': 'T1', 'pred_task_id': 'T0',
                     'pred_type': 'PR_FS', 'lag_hr_cnt': '0'},
                    {'task_id': 'T2', 'pred_task_id': 'T1',
                     'pred_type': 'PR_FS', 'lag_hr_cnt': '0'},
                    {'task_id': 'T3', 'pred_task_id': 'T2',
                     'pred_type': 'PR_FS', 'lag_hr_cnt': '0'},
                ],
            },
            'TASKRSRC': {
                'fields': ['task_id', 'rsrc_id'],
                'records': [
                    {'task_id': 'T0', 'rsrc_id': 'R1'},
                    {'task_id': 'T1', 'rsrc_id': 'R1'},
                    {'task_id': 'T2', 'rsrc_id': 'R1'},
                    {'task_id': 'T3', 'rsrc_id': 'R1'},
                ],
            },
        },
    }


# ─────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────

def test_dcma_14_clean_schedule_scores_14():
    """A clean 3-activity chain should pass all 14 checks."""
    data = _clean_schedule()
    result = dcma_14_assess(data, profile='commercial')
    assert result['dcma_score'] == 14, (
        f'Clean schedule should score 14/14, got {result["dcma_score"]}. '
        f'Per-check: ' + '; '.join(
            f'{k}={v["severity"]}' for k, v in result['per_check'].items()
            if v['severity'] != 'PASS'
        )
    )
    assert result['cpli'] is not None
    assert result['cpli'] >= 0.95


def test_dcma_14_catches_negative_float():
    """Negative float on any task triggers DCMA-07 BLOCK."""
    data = _clean_schedule()
    # Knock T1 into negative float
    data['tables']['TASK']['records'][0]['total_float_hr_cnt'] = '-40'
    result = dcma_14_assess(data, profile='commercial')
    check = result['per_check']['DCMA-07-NegFloat']
    assert check['severity'] == 'BLOCK', (
        f'DCMA-07 should BLOCK on negative float, got {check["severity"]}')
    assert check['value'] >= 1
    assert result['dcma_score'] < 14


def test_dcma_14_catches_missing_logic():
    """An activity with no predecessor AND no successor breaks DCMA-01."""
    data = _clean_schedule()
    # Add an orphan task: no preds, no succs
    data['tables']['TASK']['records'].append({
        'task_id': 'ORPHAN', 'proj_id': 'P1', 'task_code': 'ORPH',
        'task_name': 'Orphan', 'task_type': 'TT_Task',
        'status_code': 'TK_NotStart', 'total_float_hr_cnt': '80',
        'clndr_id': 'C1', 'crt_path_num': '0', 'cstr_type': '',
        'cstr_type2': '', 'target_start_date': '2026-05-01 08:00',
        'target_end_date': '2026-05-05 16:00',
        'early_start_date': '2026-05-01 08:00',
        'early_end_date': '2026-05-05 16:00',
        'remain_drtn_hr_cnt': '40', 'target_drtn_hr_cnt': '40',
    })
    # Add another four orphans so the missing-logic percentage exceeds the
    # commercial 5% threshold (4 orphans / 7 tasks = 57%).
    for i in range(4):
        data['tables']['TASK']['records'].append({
            'task_id': f'ORPH{i}', 'proj_id': 'P1', 'task_code': f'O{i}',
            'task_name': f'Orph {i}', 'task_type': 'TT_Task',
            'status_code': 'TK_NotStart', 'total_float_hr_cnt': '80',
            'clndr_id': 'C1', 'crt_path_num': '0', 'cstr_type': '',
            'cstr_type2': '', 'target_start_date': '2026-05-01 08:00',
            'target_end_date': '2026-05-05 16:00',
            'early_start_date': '2026-05-01 08:00',
            'early_end_date': '2026-05-05 16:00',
            'remain_drtn_hr_cnt': '40', 'target_drtn_hr_cnt': '40',
        })
    result = dcma_14_assess(data, profile='commercial')
    check = result['per_check']['DCMA-01-Logic']
    assert check['severity'] == 'WARN', (
        f'DCMA-01 should WARN on missing logic, got {check["severity"]} '
        f'(value={check["value"]}, threshold={check["threshold"]})')


def test_dcma_14_catches_future_actual():
    """Future actual_start beyond data date triggers DCMA-09 BLOCK."""
    data = _clean_schedule()
    # Give T1 an actual_start date IN THE FUTURE (after data date 2026-04-24)
    data['tables']['TASK']['records'][0]['act_start_date'] = '2026-12-01 08:00'
    # Must also register the field name in the fields list
    if 'act_start_date' not in data['tables']['TASK']['fields']:
        data['tables']['TASK']['fields'].append('act_start_date')
    result = dcma_14_assess(data, profile='commercial')
    check = result['per_check']['DCMA-09-InvalidDates']
    assert check['severity'] == 'BLOCK', (
        f'DCMA-09 should BLOCK on future actual, got {check["severity"]}')
    assert check['value'] >= 1


def test_dcma_14_catches_past_planned_not_complete():
    """Activity with target_end in the past but not complete triggers DCMA-09."""
    data = _clean_schedule()
    # Change T1's target_end to the past AND mark it not complete
    data['tables']['TASK']['records'][0]['target_end_date'] = '2026-01-15 16:00'
    # Status stays TK_NotStart, so it's past-planned-not-complete
    result = dcma_14_assess(data, profile='commercial')
    check = result['per_check']['DCMA-09-InvalidDates']
    assert check['severity'] == 'BLOCK', (
        f'DCMA-09 should BLOCK on past-planned-not-complete, got {check["severity"]} '
        f'(value={check["value"]})')
    assert check['value'] >= 1


def test_dcma_14_cpli_computation():
    """CPLI = (CP length + tf) / CP length. With TF=0 and nonzero CP length → CPLI=1.0."""
    data = _clean_schedule()
    result = dcma_14_assess(data, profile='commercial')
    cpli = result['cpli']
    assert cpli is not None, 'CPLI should be computed on a clean schedule'
    # With 0 float and positive CP length, CPLI should be exactly 1.0
    assert abs(cpli - 1.0) < 0.001, f'Expected CPLI≈1.0, got {cpli}'


def test_dcma_14_bei_skipped_without_baseline():
    """Without a baseline, BEI is None and the finding is INFO."""
    data = _clean_schedule()
    result = dcma_14_assess(data, profile='commercial', baseline_data=None)
    assert result['bei'] is None
    bei_check = result['per_check']['BEI']
    assert bei_check['severity'] == 'INFO'
    assert bei_check['value'] is None


def test_dcma_14_bei_computed_with_baseline():
    """With a baseline that has activities due by data_date, BEI is computed."""
    # Baseline: both A10 and A20 were planned to be complete by 2026-04-24
    baseline = _clean_schedule()
    for r in baseline['tables']['TASK']['records']:
        if r['task_code'] in ('A10', 'A20'):
            r['target_end_date'] = '2026-04-20 16:00'  # before data_date
    # Current: A10 is complete, A20 is still not_start (so BEI = 1/2 = 0.5).
    # Lookup by task_code — index-based access was brittle because index 0
    # is A00 (start milestone) in _clean_schedule(), not A10.
    current = _clean_schedule()
    for r in current['tables']['TASK']['records']:
        if r['task_code'] in ('A10', 'A20'):
            r['target_end_date'] = '2026-04-20 16:00'
        if r['task_code'] == 'A10':
            r['status_code'] = 'TK_Complete'
    result = dcma_14_assess(current, profile='commercial', baseline_data=baseline)
    bei = result['bei']
    assert bei is not None, 'BEI should be computed when baseline supplied'
    assert abs(bei - 0.5) < 0.001, f'Expected BEI=0.5, got {bei}'


def test_dcma_14_nuclear_stricter_than_commercial():
    """A schedule at the edge of commercial thresholds fails nuclear."""
    # Build a schedule with exactly 3% lags — passes commercial (5%) but should
    # come out stricter or equal under nuclear (2%). Easier: a schedule with
    # a mandatory constraint on 3% of tasks (passes commercial, fails nuclear).
    data = _clean_schedule()
    # Set one hard constraint → 1/3 = 33% constrained. Fails both, but the
    # point is that nuclear's threshold is lower. Let's add 100 clean tasks
    # and then 3 with hard constraints: 3/103 ≈ 2.9%.
    base_tasks = data['tables']['TASK']['records']
    pred_records = data['tables']['TASKPRED']['records']
    # Instead: compare directly — build a schedule with lag_count = 3%
    # of rels; commercial (5%) passes, nuclear (2%) warns.
    # Extend relationship set to 100 FS rels, 3 of which have +8hr lag.
    for i in range(100):
        pred_records.append({
            'task_id': 'T2', 'pred_task_id': 'T1',
            'pred_type': 'PR_FS', 'lag_hr_cnt': '8' if i < 3 else '0',
        })
    commercial = dcma_14_assess(data, profile='commercial')
    nuclear = dcma_14_assess(data, profile='nuclear')
    # Nuclear score must be <= commercial on a schedule where nuclear is stricter.
    assert nuclear['dcma_score'] <= commercial['dcma_score'], (
        f'Nuclear should be at least as strict as commercial '
        f'({nuclear["dcma_score"]} vs {commercial["dcma_score"]})'
    )
    # CPLI threshold is also tighter on nuclear.
    nuc_cpli_check = nuclear['per_check']['DCMA-14-CPLI']
    com_cpli_check = commercial['per_check']['DCMA-14-CPLI']
    assert nuc_cpli_check['threshold'] > com_cpli_check['threshold'], (
        'Nuclear CPLI threshold should be higher than commercial')


def test_dcma_14_multiple_critical_paths_identified():
    """Two distinct critical chains (different crt_path_num) are reported separately."""
    data = _clean_schedule()
    # Add two more critical tasks forming a second chain (B10 → B20)
    extra_tasks = [
        {'task_id': 'T4', 'proj_id': 'P1', 'task_code': 'B10',
         'task_name': 'Beta Start', 'task_type': 'TT_Task',
         'status_code': 'TK_NotStart', 'total_float_hr_cnt': '0',
         'clndr_id': 'C1', 'crt_path_num': '2', 'cstr_type': '',
         'cstr_type2': '', 'target_start_date': '2026-04-27 08:00',
         'target_end_date': '2026-05-01 16:00',
         'early_start_date': '2026-04-27 08:00',
         'early_end_date': '2026-05-01 16:00',
         'remain_drtn_hr_cnt': '40', 'target_drtn_hr_cnt': '40'},
        {'task_id': 'T5', 'proj_id': 'P1', 'task_code': 'B20',
         'task_name': 'Beta End', 'task_type': 'TT_Task',
         'status_code': 'TK_NotStart', 'total_float_hr_cnt': '0',
         'clndr_id': 'C1', 'crt_path_num': '2', 'cstr_type': '',
         'cstr_type2': '', 'target_start_date': '2026-05-04 08:00',
         'target_end_date': '2026-05-08 16:00',
         'early_start_date': '2026-05-04 08:00',
         'early_end_date': '2026-05-08 16:00',
         'remain_drtn_hr_cnt': '40', 'target_drtn_hr_cnt': '40'},
    ]
    data['tables']['TASK']['records'].extend(extra_tasks)
    data['tables']['TASKPRED']['records'].append({
        'task_id': 'T5', 'pred_task_id': 'T4', 'pred_type': 'PR_FS',
        'lag_hr_cnt': '0',
    })
    # Connect B20 to the finish milestone so it isn't orphaned
    data['tables']['TASKPRED']['records'].append({
        'task_id': 'T3', 'pred_task_id': 'T5', 'pred_type': 'PR_FS',
        'lag_hr_cnt': '0',
    })
    result = dcma_14_assess(data, profile='commercial')
    assert result['multiple_critical_paths'], (
        f'Expected multiple_critical_paths=True, got False. '
        f'critical_paths={result["critical_paths"]}')
    assert len(result['critical_paths']) >= 2


def test_dcma_14_driving_path_tracer():
    """Given a task_code, trace_driving_path walks pred chain back to data date."""
    data = _clean_schedule()
    # From A30 (the finish), the driving chain should be A10 → A20 → A30.
    chain = trace_driving_path(data, 'A30')
    # At minimum, the chain should include A30 and some predecessors
    assert chain, f'Expected non-empty driving chain, got {chain}'
    assert 'A30' in chain, f'Target task_code should be in chain: {chain}'
    # Should include A20 (immediate pred) and potentially A10 (further back)
    assert 'A20' in chain, (
        f'Expected A20 in chain — A30\'s direct pred. Got {chain}')


# ─────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────

def main():
    tests = [
        test_dcma_14_clean_schedule_scores_14,
        test_dcma_14_catches_negative_float,
        test_dcma_14_catches_missing_logic,
        test_dcma_14_catches_future_actual,
        test_dcma_14_catches_past_planned_not_complete,
        test_dcma_14_cpli_computation,
        test_dcma_14_bei_skipped_without_baseline,
        test_dcma_14_bei_computed_with_baseline,
        test_dcma_14_nuclear_stricter_than_commercial,
        test_dcma_14_multiple_critical_paths_identified,
        test_dcma_14_driving_path_tracer,
    ]
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
        return 1
    print(f'{len(tests)} / {len(tests)} passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
