#!/usr/bin/env python3
"""DCMA 14-Point assessment tests.

Run with: python tests/test_dcma14.py

Builds tiny synthetic XER-shaped data in memory and runs the DCMA 14
assessment against it. These tests lock in:
  - Clean-schedule pass (every ASSESSED criterion passes)
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
sys.path.insert(0, os.path.join(SCRIPT_DIR, '..', 'scripts'))

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

def test_dcma_14_clean_schedule_passes_every_assessable_check():
    """A clean chain passes every criterion the file can support.

    ASSERTION CHANGED. This used to assert `dcma_score == 14` on a schedule
    with no baseline attached. That was only reachable because #11 and #12 were
    cross-reference echoes of #9 and #10, two points measured once, and
    because BEI sat outside the fourteen. Both were wrong: the published order
    is #11 Missed Tasks, #12 Critical Path Test, #13 CPLI, #14 BEI, and BEI
    cannot be computed at all without a baseline. The honest result on this
    fixture is 12 passed of 12 ASSESSED, with the Critical Path Test and BEI
    named as not assessed. Resources (#10) is scored here:
    the bundled commercial profile sets an 80% floor and this fixture loads
    every activity. Under a profile that disables the threshold it reads
    INFO — Not scored — and leaves both the numerator and the denominator.
    """
    data = _clean_schedule()
    result = dcma_14_assess(data, profile='commercial')
    unhappy = '; '.join(
        f'{k}={v["severity"]}' for k, v in result['per_check'].items()
        if v['severity'] not in ('PASS', 'INFO'))
    assert result['dcma_score'] == result['dcma_max'], (
        f'Clean schedule should pass every assessed criterion, got '
        f'{result["dcma_score"]}/{result["dcma_max"]}. Failing: {unhappy}')
    assert result['dcma_max'] == 12, (
        f'12 of the 14 are assessable on this fixture (no baseline → no BEI; '
        f'the Critical Path Test needs a CPM recalculation), '
        f'got {result["dcma_max"]}')
    assert sorted(result['dcma_not_assessed']) == [
        'DCMA-12-CriticalPathTest', 'DCMA-14-BEI'], (
        f'not-assessed criteria must be named, got '
        f'{result["dcma_not_assessed"]}')
    assert result['cpli'] is not None
    assert result['cpli'] >= 0.95


def test_dcma_14_catches_negative_float():
    """Negative float on any task triggers DCMA-07 BLOCK and costs a point.

    ASSERTION CHANGED 2026-08-25. The score check used to read
    `dcma_score < 14`. This fixture's dcma_max is 12, so the score can never
    reach 14 and that assertion was true for every possible outcome, including
    one where negative float cost nothing at all. Its two siblings in this file
    were re-pinned to dcma_max when the max stopped being 14; this one was
    missed.

    It now measures the deduction against the SAME schedule without the defect,
    so the assertion fails if DCMA-07 stops costing a point.
    """
    clean = dcma_14_assess(_clean_schedule(), profile='commercial')
    data = _clean_schedule()
    # Knock T1 into negative float
    data['tables']['TASK']['records'][0]['total_float_hr_cnt'] = '-40'
    result = dcma_14_assess(data, profile='commercial')
    check = result['per_check']['DCMA-07-NegFloat']
    assert check['severity'] == 'BLOCK', (
        f'DCMA-07 should BLOCK on negative float, got {check["severity"]}')
    assert check['value'] >= 1
    assert result['dcma_score'] < result['dcma_max'], (
        f'negative float must cost a criterion, got '
        f'{result["dcma_score"]}/{result["dcma_max"]}')
    assert result['dcma_score'] == clean['dcma_score'] - 1, (
        f'exactly one criterion should be lost to negative float: clean scored '
        f'{clean["dcma_score"]}/{clean["dcma_max"]}, this scored '
        f'{result["dcma_score"]}/{result["dcma_max"]}')


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
    """A planned finish in the past on open work is a Missed Task (#11), not an
    Invalid Date (#9).

    ASSERTIONS CHANGED 2026-09-21. This test used to require DCMA-09 to BLOCK
    here. DCMA-EA PAM 200.1 section 4.9 defines an invalid date as a FORECAST
    (early) date before the status date or an actual date after it; section
    4.11 is the one that reads the planned/baseline finish. Derivation on this
    fixture, status date 2026-04-24:

      #9   the first activity forecasts 2026-04-27 08:00 for both its early
           start and early finish, after the status date, and carries no
           actuals: 0 invalid -> PASS. Only its planned finish was moved.
      #11  no baseline, so the due date is the current planned finish. One
           activity is due by the status date (planned finish 2026-01-15) and
           it is still open: 1 of 1 = 100% against the 5% threshold -> WARN.
    """
    data = _clean_schedule()
    # Move the first activity's planned finish into the past; it stays
    # TK_NotStart with its forecast dates untouched.
    data['tables']['TASK']['records'][0]['target_end_date'] = '2026-01-15 16:00'
    result = dcma_14_assess(data, profile='commercial')
    nine = result['per_check']['DCMA-09-InvalidDates']
    assert nine['severity'] == 'PASS', (
        f'a historical planned finish is not an invalid date, got '
        f'{nine["severity"]} (value={nine["value"]})')
    assert nine['value'] == 0
    eleven = result['per_check']['DCMA-11-MissedTasks']
    assert eleven['severity'] == 'WARN', eleven
    assert eleven['details']['still_open'] == ['A00'], eleven['details']
    assert abs(eleven['value'] - 100.0) < 1e-9


def test_dcma_14_merged_echo_not_double_counted_as_block():
    """A single invalid-date defect must contribute exactly ONE BLOCK to the
    report — not two.

    The echo row DCMA-11-InvalidDatesFuture repeated #9's verdict, so one
    future actual was reported as two BLOCKs and cost two points. In the
    published DCMA order #11 is Missed Tasks and #12 is the Critical Path
    Test, and there is no echo row at all.
    """
    data = _clean_schedule()
    # One future actual on one activity → exactly one underlying invalid-date defect.
    data['tables']['TASK']['records'][0]['act_start_date'] = '2026-12-01 08:00'
    if 'act_start_date' not in data['tables']['TASK']['fields']:
        data['tables']['TASK']['fields'].append('act_start_date')
    result = dcma_14_assess(data, profile='commercial')

    # DCMA-09 is the real BLOCK.
    nine = result['per_check']['DCMA-09-InvalidDates']
    assert nine['severity'] == 'BLOCK', (
        f'DCMA-09 should BLOCK on the invalid date, got {nine["severity"]}')

    # There is no echo of #9 anywhere in the output: #11 is Missed Tasks.
    assert 'DCMA-11-InvalidDatesFuture' not in result['per_check'], (
        'DCMA #11 is Missed Tasks in the published standard, not a "Future '
        'Actuals" echo of #9')
    assert 'DCMA-11-MissedTasks' in result['per_check']
    for cid, row in result['per_check'].items():
        assert 'merged_into' not in row, (
            f'{cid} is still recorded as a merged echo; every one of the 14 is '
            f'an independent criterion')

    # The report summary must count exactly ONE BLOCK for the one underlying
    # defect — the heart of the overstatement fix.
    blocks = result['report'].count('BLOCK')
    assert blocks == 1, (
        f'A single invalid-date defect must yield exactly one BLOCK in the '
        f'report, not {blocks} (merged echo must not double-count).')
    block_ids = [f['check_id'] for f in result['report'].to_dict()['findings']
                 if f['severity'] == 'BLOCK']
    assert block_ids == ['DCMA-09-InvalidDates'], (
        f'The only BLOCK row must be DCMA-09; got {block_ids}')

    # All fourteen criteria are present (never truncated).
    ids = set(result['per_check'])
    for n, name in ((11, 'MissedTasks'), (12, 'CriticalPathTest'),
                    (13, 'CPLI'), (14, 'BEI')):
        assert f'DCMA-{n}-{name}' in ids, (
            f'DCMA #{n} must be {name} per the published order; per_check has '
            f'{sorted(ids)}')


def test_dcma_14_registry_follows_published_numbering():
    """#11 Missed Tasks, #12 Critical Path Test, #13 CPLI, #14 BEI — and no
    criterion is handed a point it did not earn.

    The row DCMA-12-ResourceCoverage was a renumbering artifact: it displaced
    the Critical Path Test and repeated #10's verdict, so one criterion counted
    twice. What is asserted here is the published numbering, and that the
    score is exactly the number of criteria that passed.
    """
    data = _clean_schedule()
    result = dcma_14_assess(data, profile='commercial')
    assert 'DCMA-12-ResourceCoverage' not in result['per_check'], (
        'DCMA #12 is the Critical Path Test, not a resource echo of #10')
    assert result['per_check']['DCMA-12-CriticalPathTest']['severity'] in (
        'INFO', 'BLOCK'), (
        'the Critical Path Test either fails structurally or is not assessed — '
        'it must never report a pass without a CPM recalculation')
    # Score arithmetic: passed + failed == assessed, and nothing outside that.
    sevs = [v['severity'] for v in result['per_check'].values()]
    assessed = sum(1 for s in sevs if s != 'INFO')
    passed = sum(1 for s in sevs if s == 'PASS')
    assert result['dcma_max'] == assessed, (
        f'dcma_max must equal the number of non-INFO criteria ({assessed}), '
        f'got {result["dcma_max"]}')
    assert result['dcma_score'] == passed, (
        f'dcma_score must equal the number of PASS criteria ({passed}), got '
        f'{result["dcma_score"]}')
    assert result['dcma_score'] <= result['dcma_max'] <= 14


def test_dcma_14_cpli_computation():
    """CPLI = (CP length + total float) / CP length, in WORKING days.

    Two cases pin both the formula and the working-day CP-length conversion. A
    TF=0 case alone is blind to CP-length errors (it yields 1.0 for ANY length),
    so we also assert the CP length value (11 working days — a wall-clock
    denominator would inflate it) and a behind-schedule case where CPLI genuinely
    depends on the length.
    """
    # ── Case 1: TF=0 → CPLI exactly 1.0; CP length is 11 working days ──
    # KEYS CHANGED: the check id is DCMA-13-CPLI (published #13, not #14) and
    # the float term is `tf_days` — the total float of the PROJECT FINISH
    # activity. It used to be `tf_days_min`, the minimum float across the whole
    # critical set, which capped CPLI at 1.0 by construction and printed
    # negative values when one deeply negative activity dominated the minimum.
    data = _clean_schedule()
    result = dcma_14_assess(data, profile='commercial')
    cpli = result['cpli']
    det = result['per_check']['DCMA-13-CPLI']['details']
    assert cpli is not None, 'CPLI should be computed on a clean schedule'
    assert abs(cpli - 1.0) < 0.001, f'Expected CPLI≈1.0, got {cpli}'
    # Independent check on the denominator — catches the wall-clock-vs-working-day
    # bug the code comments claim to fix (a 10-wd CP across two weeks must NOT read ~41).
    assert det['cp_length_days'] == 11, (
        f"CP length must be 11 working days (data_date 2026-04-24 → CP end "
        f"2026-05-08 on a 5-day calendar), got {det['cp_length_days']}")
    assert det['tf_days'] == 0.0

    # ── Case 2: behind schedule (TF = -40h = -5 working days) → CPLI < 1, BLOCK ──
    # CPLI = (11 + (-5)) / 11 = 6/11 ≈ 0.545. This DEPENDS on the CP length, so a
    # mis-computed length changes it — the TF=0 case could not detect that.
    behind = _clean_schedule()
    for r in behind['tables']['TASK']['records']:
        r['total_float_hr_cnt'] = '-40'
    result2 = dcma_14_assess(behind, profile='commercial')
    cpli2 = result2['cpli']
    pc2 = result2['per_check']['DCMA-13-CPLI']
    assert pc2['details']['tf_days'] == -5.0
    assert pc2['details']['cp_length_days'] == 11
    assert abs(cpli2 - (6.0 / 11.0)) < 0.005, f'Expected CPLI≈0.545, got {cpli2}'
    assert cpli2 < 1.0
    assert pc2['severity'] == 'BLOCK'  # below the 0.95 commercial floor


def test_dcma_14_bei_skipped_without_baseline():
    """Without a baseline, BEI is None and the finding is INFO."""
    data = _clean_schedule()
    result = dcma_14_assess(data, profile='commercial', baseline_data=None)
    assert result['bei'] is None
    bei_check = result['per_check']['DCMA-14-BEI']
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
    nuc_cpli_check = nuclear['per_check']['DCMA-13-CPLI']
    com_cpli_check = commercial['per_check']['DCMA-13-CPLI']
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
        test_dcma_14_clean_schedule_passes_every_assessable_check,
        test_dcma_14_catches_negative_float,
        test_dcma_14_catches_missing_logic,
        test_dcma_14_catches_future_actual,
        test_dcma_14_catches_past_planned_not_complete,
        test_dcma_14_merged_echo_not_double_counted_as_block,
        test_dcma_14_registry_follows_published_numbering,
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
