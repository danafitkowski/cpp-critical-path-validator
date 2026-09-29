#!/usr/bin/env python3
"""Regression guards for the DCMA-14 metric definitions (2026-08-25).

Every test in this file is DISCRIMINATING: it fails against the behaviour it
replaces. The defect each one pins is named in its docstring.

Four further tests at the bottom are LOCK tests, not defect fixes: they pin
behaviour that another DCMA-14 implementation got wrong and this module
already had right. They pass both before and after and are labelled as such.

The #1 Logic tests are in tests/test_dcma14_logic.py.
"""
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, '..', 'scripts'))

from dcma14 import dcma_14_assess  # noqa: E402

DATA_DATE = '2026-04-24 00:00'

_TASK_FIELDS = [
    'task_id', 'proj_id', 'task_code', 'task_name', 'task_type', 'status_code',
    'total_float_hr_cnt', 'clndr_id', 'crt_path_num', 'cstr_type', 'cstr_type2',
    'target_start_date', 'target_end_date', 'early_start_date', 'early_end_date',
    'act_start_date', 'act_end_date', 'remain_drtn_hr_cnt', 'target_drtn_hr_cnt',
]


def _task(task_id, code, name, ttype='TT_Task', status='TK_NotStart', tf='0',
          start='2026-04-27 08:00', end='2026-05-01 16:00', act_start='',
          act_end='', cstr='', cstr2='', remain='40', target='40',
          crt_path_num='1'):
    """One TASK row shaped like a real P6 export (hours, TK_/TT_/CS_ codes)."""
    return {
        'task_id': task_id, 'proj_id': 'P1', 'task_code': code,
        'task_name': name, 'task_type': ttype, 'status_code': status,
        'total_float_hr_cnt': tf, 'clndr_id': 'C1',
        'crt_path_num': crt_path_num, 'cstr_type': cstr, 'cstr_type2': cstr2,
        'target_start_date': start, 'target_end_date': end,
        'early_start_date': start, 'early_end_date': end,
        'act_start_date': act_start, 'act_end_date': act_end,
        'remain_drtn_hr_cnt': remain, 'target_drtn_hr_cnt': target,
    }


def _schedule(tasks, preds, data_date=DATA_DATE, project_extra=None):
    proj = {
        'proj_id': 'P1', 'proj_short_name': 'TEST',
        'last_recalc_date': data_date,
        'plan_end_date': '2026-05-15 16:00',
        'scd_end_date': '2026-05-15 16:00',
        'critical_drtn_hr_cnt': '0',
    }
    proj.update(project_extra or {})
    return {
        'tables': {
            'PROJECT': {'fields': list(proj), 'records': [proj]},
            'CALENDAR': {
                'fields': ['clndr_id', 'clndr_name', 'day_hr_cnt', 'week_hr_cnt',
                           'default_flag', 'clndr_type', 'clndr_data'],
                'records': [{
                    'clndr_id': 'C1', 'clndr_name': '5-Day', 'day_hr_cnt': '8',
                    'week_hr_cnt': '40', 'default_flag': 'Y',
                    'clndr_type': 'CA_Base', 'clndr_data': '',
                }],
            },
            'TASK': {'fields': list(_TASK_FIELDS), 'records': tasks},
            'TASKPRED': {
                'fields': ['task_id', 'pred_task_id', 'pred_type', 'lag_hr_cnt'],
                'records': preds,
            },
            'TASKRSRC': {
                'fields': ['task_id', 'rsrc_id'],
                'records': [{'task_id': t['task_id'], 'rsrc_id': 'R1'} for t in tasks],
            },
        },
    }


def _chain(finish_tf='0', finish_cstr='', mid_tf='0'):
    """Start milestone → A10 → A20 → finish milestone, all FS, no lags."""
    tasks = [
        _task('T0', 'A00', 'Start', 'TT_Mile', tf='0',
              start='2026-04-27 08:00', end='2026-04-27 08:00',
              remain='0', target='0'),
        _task('T1', 'A10', 'Alpha', tf=mid_tf,
              start='2026-04-27 08:00', end='2026-05-01 16:00'),
        _task('T2', 'A20', 'Bravo', tf=mid_tf,
              start='2026-05-04 08:00', end='2026-05-08 16:00'),
        _task('T3', 'A30', 'Finish', 'TT_FinMile', tf=finish_tf,
              start='2026-05-11 08:00', end='2026-05-11 08:00',
              cstr=finish_cstr, remain='0', target='0'),
    ]
    preds = [
        {'task_id': 'T1', 'pred_task_id': 'T0', 'pred_type': 'PR_FS', 'lag_hr_cnt': '0'},
        {'task_id': 'T2', 'pred_task_id': 'T1', 'pred_type': 'PR_FS', 'lag_hr_cnt': '0'},
        {'task_id': 'T3', 'pred_task_id': 'T2', 'pred_type': 'PR_FS', 'lag_hr_cnt': '0'},
    ]
    return tasks, preds


# ─────────────────────────────────────────────────────────────────────
# #13 CPLI
# ─────────────────────────────────────────────────────────────────────

def test_cpli_can_exceed_one_when_the_project_is_ahead():
    """CPLI must be able to report margin.

    DEFECT: CPLI took the MINIMUM float over `cp_tasks`, and cp_tasks was
    itself defined as incomplete activities with float ≤ 0, so the float term
    was non-positive by construction and CPLI ≤ 1.0 always, so it could never
    report margin. Here the project finish carries +40h (5 working
    days) of float on an 11-working-day critical path, so CPLI must read
    16/11 ≈ 1.455. The old code found no cp_tasks at all and returned
    not-computable.
    """
    tasks, preds = _chain(finish_tf='40', mid_tf='40')
    result = dcma_14_assess(_schedule(tasks, preds), profile='commercial')
    cpli = result['cpli']
    det = result['per_check']['DCMA-13-CPLI']['details']
    assert cpli is not None, 'CPLI must be computable on a schedule with float'
    assert det['cp_length_days'] == 11
    assert det['tf_days'] == 5.0
    assert abs(cpli - (16.0 / 11.0)) < 0.005, f'expected CPLI≈1.455, got {cpli}'
    assert cpli > 1.0, 'CPLI must be able to exceed 1.0 when work is ahead'


def test_cpli_is_not_dominated_by_the_deepest_negative_activity():
    """CPLI reads the project finish's float, not the worst float anywhere.

    DEFECT: taking the minimum float over the whole critical set let one
    deeply negative activity dominate and produced NEGATIVE critical-path-length
    indices — a quantity with no meaning that went into reports as a number.
    Here an interior activity
    sits at -800h (-100 wd) while the project finish is at -8h (-1 wd): the
    published index is (11-1)/11 ≈ 0.909, whereas the minimum-float form gives
    (11-100)/11 ≈ -8.09.
    """
    tasks, preds = _chain(finish_tf='-8')
    for t in tasks:
        if t['task_code'] == 'A20':
            t['total_float_hr_cnt'] = '-800'
    result = dcma_14_assess(_schedule(tasks, preds), profile='commercial')
    cpli = result['cpli']
    assert cpli > 0, f'CPLI must never be negative; got {cpli}'
    assert abs(cpli - (10.0 / 11.0)) < 0.005, f'expected CPLI≈0.909, got {cpli}'


# ─────────────────────────────────────────────────────────────────────
# #14 BEI
# ─────────────────────────────────────────────────────────────────────

def test_bei_numerator_is_unrestricted_and_can_exceed_one():
    """BEI = tasks completed / tasks baselined due — numerator unrestricted.

    DEFECT: the numerator iterated only the baseline-due subset, so it was a
    subset of the denominator and BEI was capped at 1.0 and could never signal
    ahead-of-plan execution. Here the baseline had one
    activity due; two are actually finished, so BEI = 2.0. The old form
    returned 1.0.
    """
    base_tasks, preds = _chain()
    for t in base_tasks:
        if t['task_code'] == 'A10':
            t['target_end_date'] = '2026-04-20 16:00'   # baseline-due
    baseline = _schedule(base_tasks, preds)

    cur_tasks, preds2 = _chain()
    for t in cur_tasks:
        if t['task_code'] == 'A10':
            t['target_end_date'] = '2026-04-20 16:00'
        if t['task_code'] in ('A10', 'A20'):
            t['status_code'] = 'TK_Complete'
            t['act_start_date'] = '2026-04-06 08:00'
            t['act_end_date'] = '2026-04-17 16:00'
            t['remain_drtn_hr_cnt'] = '0'
    current = _schedule(cur_tasks, preds2)

    result = dcma_14_assess(current, profile='commercial', baseline_data=baseline)
    det = result['per_check']['DCMA-14-BEI']['details']
    assert det['baselined_due'] == 1, det
    assert det['completed'] == 2, (
        'the numerator counts every activity complete as of the status date, '
        'not only the baseline-due ones')
    assert abs(result['bei'] - 2.0) < 1e-9, f'expected BEI=2.0, got {result["bei"]}'


# ─────────────────────────────────────────────────────────────────────
# #11 Missed Tasks
# ─────────────────────────────────────────────────────────────────────

def test_missed_tasks_counts_activities_that_finished_late():
    """A late completion is a missed task.

    DEFECT: the check counted only activities still OPEN at the status date, so
    anything that finished after its planned finish was invisible, and an update
    on which most of the due activities finished late could read as a PASS.
    Here one
    of two due activities finished eight days late: 50% must be counted, not 0%.
    """
    tasks, preds = _chain()
    for t in tasks:
        if t['task_code'] == 'A10':
            t['target_end_date'] = '2026-04-10 16:00'
            t['status_code'] = 'TK_Complete'
            t['act_start_date'] = '2026-04-01 08:00'
            t['act_end_date'] = '2026-04-20 16:00'    # ten working days late
            t['remain_drtn_hr_cnt'] = '0'
        if t['task_code'] == 'A20':
            t['target_end_date'] = '2026-04-10 16:00'
            t['status_code'] = 'TK_Complete'
            t['act_start_date'] = '2026-04-01 08:00'
            t['act_end_date'] = '2026-04-09 16:00'    # on time
            t['remain_drtn_hr_cnt'] = '0'
    result = dcma_14_assess(_schedule(tasks, preds), profile='commercial')
    check = result['per_check']['DCMA-11-MissedTasks']
    det = check['details']
    assert det['due_by_dd'] == 2, det
    assert det['still_open_count'] == 0, det
    assert det['late_finish_count'] == 1, (
        'an activity that finished after its due date is a missed task')
    assert abs(check['value'] - 50.0) < 1e-9, check
    assert check['severity'] == 'WARN', (
        '50% missed is far above the 5% commercial threshold')


def test_missed_tasks_uses_the_baseline_finish_when_a_baseline_is_supplied():
    """Due dates come from the baseline, matched on task_code.

    DEFECT: `baseline_data` was passed into the assessment but consumed only by
    BEI; Missed Tasks always used the CURRENT schedule's own Planned Finish, so
    a schedule whose planned dates had been dragged forward reported nothing
    missed. Matching is on task_code because P6 renumbers task_id on every
    export.
    """
    base_tasks, bpreds = _chain()
    for t in base_tasks:
        if t['task_code'] == 'A10':
            t['target_end_date'] = '2026-04-10 16:00'   # baseline said 10 Apr
    baseline = _schedule(base_tasks, bpreds)

    cur_tasks, cpreds = _chain()
    for t in cur_tasks:
        if t['task_code'] == 'A10':
            t['target_end_date'] = '2026-06-30 16:00'   # dragged past the status date
    current = _schedule(cur_tasks, cpreds)

    with_bl = dcma_14_assess(current, profile='commercial', baseline_data=baseline)
    det = with_bl['per_check']['DCMA-11-MissedTasks']['details']
    assert det['basis'] == 'baseline finish', det
    assert det['due_by_dd'] == 1, (
        'A10 was due 2026-04-10 on the baseline and must still be counted as due')
    assert det['still_open_count'] == 1, det

    without_bl = dcma_14_assess(current, profile='commercial')
    assert without_bl['per_check']['DCMA-11-MissedTasks']['details']['due_by_dd'] == 0, (
        'without a baseline the dragged current Planned Finish hides it — which '
        'is exactly why the baseline must be used when it is available')


# ─────────────────────────────────────────────────────────────────────
# #12 Critical Path Test
# ─────────────────────────────────────────────────────────────────────

def test_critical_path_test_fails_when_the_project_finish_is_pinned():
    """A finish pinned by a MANDATORY constraint cannot move, so #12 fails.

    DEFECT: dcma14.py had no #12 at all — slot 12 was a 'Resource Coverage'
    cross-reference echo of #10 that repeated its verdict. Inserting a
    600-day delay upstream of a finish that P6 holds whatever the logic says
    cannot move it, which is the failure the published test exists to expose.

    FIXTURE CHANGED 2026-09-21, CS_MEO -> CS_MANDFIN. This test used to pin the
    finish with Finish On and require a BLOCK. Finish On is not a pin: P6 can
    delay the early finish past it and shows the lateness as negative float,
    which DCMA-EA PAM 200.1 section 4.12 counts as a pass, so that assertion
    held a false statement in place. The mandatory case is what this test
    pins; the soft case is pinned as NOT ASSESSED in
    test_dcma12_soft_constraint_2026_09_21.py.
    """
    tasks, preds = _chain(finish_cstr='CS_MANDFIN')
    result = dcma_14_assess(_schedule(tasks, preds), profile='commercial')
    check = result['per_check']['DCMA-12-CriticalPathTest']
    assert check['severity'] == 'BLOCK', (
        f'a CS_MANDFIN-pinned project finish must fail #12; got {check["severity"]}')
    assert check['details']['finish_constraints'] == ['CS_MANDFIN'], check['details']
    assert 'DCMA-12-CriticalPathTest' not in result['dcma_not_assessed'], (
        'a structural failure IS an assessment — it must count against the score')


def test_critical_path_test_never_claims_a_pass_without_recalculation():
    """#12 is INFO (not assessed) when no structural failure is decidable.

    The published test needs a 600-day insertion and a CPM recalculation, which
    this module does not perform. The honest outcomes are BLOCK (structural
    failure) or NOT ASSESSED — never PASS. The slot-12 echo returned the #10
    severity and was scored again as if it were a criterion of its own.
    """
    tasks, preds = _chain()
    result = dcma_14_assess(_schedule(tasks, preds), profile='commercial')
    check = result['per_check']['DCMA-12-CriticalPathTest']
    assert check['severity'] == 'INFO', check
    assert 'DCMA-12-CriticalPathTest' in result['dcma_not_assessed']
    assert 'NOT ASSESSED' in check['message']


# ─────────────────────────────────────────────────────────────────────
# Scoring — no free points
# ─────────────────────────────────────────────────────────────────────

def test_no_criterion_is_hard_coded_to_pass():
    """Failing one criterion costs exactly one point; nothing is free.

    DEFECT: the two echo rows at #11 and #12 repeated #9's and #10's verdicts,
    so a clean file read 14 of 14 with two points measured once, and a
    failing #9 or #10 cost two points.
    """
    tasks, preds = _chain()
    clean = dcma_14_assess(_schedule(tasks, preds), profile='commercial')

    dirty_tasks, dirty_preds = _chain()
    dirty_preds.append({'task_id': 'T2', 'pred_task_id': 'T1',
                        'pred_type': 'PR_FS', 'lag_hr_cnt': '-8'})  # a lead
    dirty = dcma_14_assess(_schedule(dirty_tasks, dirty_preds), profile='commercial')

    assert dirty['per_check']['DCMA-02-Leads']['severity'] == 'BLOCK'
    assert dirty['dcma_max'] == clean['dcma_max'], (
        'the denominator must not move when a criterion fails')
    assert dirty['dcma_score'] == clean['dcma_score'] - 1, (
        f'one failure must cost exactly one point: '
        f'{clean["dcma_score"]} → {dirty["dcma_score"]}')
    # And the passed count is exactly the number of PASS rows — no padding.
    passes = sum(1 for v in dirty['per_check'].values() if v['severity'] == 'PASS')
    assert dirty['dcma_score'] == passes


# ─────────────────────────────────────────────────────────────────────
# Blank total float, and P6's own critical threshold
# ─────────────────────────────────────────────────────────────────────

def test_blank_total_float_is_reported_not_assessed():
    """A blank total_float is missing data, never 0 and never 999.

    DEFECT: this module coerced blank float to 999 (emptying the critical set
    and silently making CPLI not-computable); coercing it to 0 instead makes
    every incomplete activity critical and hands High Float and Negative Float
    a silent PASS. Exports carry a blank total_float on incomplete work, and on
    some it is blank on every incomplete activity. The honest answer on such a
    file is NOT ASSESSED for the float-dependent criteria.
    """
    tasks, preds = _chain()
    for t in tasks:
        t['total_float_hr_cnt'] = ''
    result = dcma_14_assess(_schedule(tasks, preds), profile='commercial')
    six = result['per_check']['DCMA-06-HighFloat']
    seven = result['per_check']['DCMA-07-NegFloat']
    thirteen = result['per_check']['DCMA-13-CPLI']
    assert six['severity'] == 'INFO', (
        f'High Float must not PASS on a file with no computed float; got '
        f'{six["severity"]}')
    assert seven['severity'] == 'INFO', (
        f'Negative Float must not PASS on a file with no computed float; got '
        f'{seven["severity"]}')
    assert thirteen['severity'] == 'INFO'
    for cid in ('DCMA-06-HighFloat', 'DCMA-07-NegFloat', 'DCMA-13-CPLI'):
        assert cid in result['dcma_not_assessed']
    assert six['details']['unknown_float_count'] == 4
    assert result['dcma_score'] <= result['dcma_max']


def test_critical_set_honours_project_critical_drtn_hr_cnt():
    """P6's own critical threshold, not a hardcoded TF ≤ 0.

    DEFECT: PROJECT.critical_drtn_hr_cnt was never read. A project that sets it
    to 9 hours flags an activity critical at total float ≤ 9h, so on such a
    schedule the hardcoded filter drops activities P6 calls critical.
    """
    tasks, preds = _chain()
    for t in tasks:
        if t['task_code'] in ('A10', 'A20'):
            t['total_float_hr_cnt'] = '8'      # one hour inside P6's threshold
            t['crt_path_num'] = '1'
    sched = _schedule(tasks, preds, project_extra={'critical_drtn_hr_cnt': '9'})
    result = dcma_14_assess(sched, profile='commercial')
    on_cp = {code for path in result['critical_paths'] for code in path}
    assert {'A10', 'A20'} <= on_cp, (
        f'activities at total float 8h are critical when the project sets '
        f'critical_drtn_hr_cnt = 9; critical_paths={result["critical_paths"]}')

    strict = dcma_14_assess(_schedule(tasks, preds), profile='commercial')
    strict_cp = {code for path in strict['critical_paths'] for code in path}
    assert 'A10' not in strict_cp, (
        'with the P6 default of 0 those same activities are not critical — the '
        'threshold has to come from the file')


# ─────────────────────────────────────────────────────────────────────
# LOCK TESTS — behaviour another DCMA-14 implementation got wrong that is
# CORRECT here. These pass both before and after the 2026-08-25 fixes. They
# are not evidence of a fix; they exist so that defect is never copied into
# this module.
# ─────────────────────────────────────────────────────────────────────

def test_lock_high_duration_uses_remaining_duration():
    """#8 measures REMAINING duration, not original.

    An implementation that filters on target_drtn_hr_cnt (P6 Original
    Duration) gets this wrong; dcma14.py reads remain_drtn_hr_cnt, which is the
    standard reading — #8 exists because remaining work longer than two months
    cannot be statused. The difference can flip the verdict: a procurement
    activity with an original duration of 45 working days and 6 remaining is
    not a high-duration activity.
    """
    tasks, preds = _chain()
    for t in tasks:
        if t['task_code'] == 'A10':
            t['status_code'] = 'TK_Active'
            t['act_start_date'] = '2026-04-06 08:00'
            t['target_drtn_hr_cnt'] = '400'   # 50 working days originally
            t['remain_drtn_hr_cnt'] = '48'    # 6 working days left
    result = dcma_14_assess(_schedule(tasks, preds), profile='commercial')
    check = result['per_check']['DCMA-08-HighDuration']
    assert check['details']['high_duration_count'] == 0, (
        'an activity with 6 remaining working days is not a high-duration '
        'activity, whatever its original duration was')
    assert check['severity'] == 'PASS'


def test_lock_invalid_dates_target_is_zero():
    """#9 tolerates no invalid dates at all.

    An implementation that compares a PERCENTAGE against a 5% threshold passes
    schedules carrying future actuals. dcma14.py compares a raw count against
    0, which is the published target.
    """
    tasks, preds = _chain()
    for t in tasks:
        if t['task_code'] == 'A10':
            t['act_start_date'] = '2026-12-01 08:00'   # after the status date
    result = dcma_14_assess(_schedule(tasks, preds), profile='commercial')
    check = result['per_check']['DCMA-09-InvalidDates']
    assert check['threshold'] == 0, (
        f'the invalid-dates target is zero, not a percentage; got '
        f'{check["threshold"]}')
    assert check['value'] == 1
    assert check['severity'] == 'BLOCK', (
        'one future actual in four activities (25%) must not pass')

    # ASSERTION STRENGTHENED 2026-08-25. Everything above is satisfied by a 5%
    # PERCENTAGE rule too, because one invalid date in four activities is 25%
    # and fails that as well. The docstring promised "neither must one in a
    # thousand" but no such fixture existed, so an adversarial pass planted a
    # 5% grading rule with `threshold` left at 0 and the whole file stayed
    # green.
    #
    # One invalid date in 40 activities is 2.5%. A percentage rule PASSES it; a
    # count-against-zero rule BLOCKS it. That is the whole difference.
    wide_tasks, wide_preds = _chain()
    for n in range(40):
        wide_tasks.append(_task(f'W{n}', f'W{n:03d}', f'Wide {n}', tf='80',
                                start='2026-04-27 08:00', end='2026-05-01 16:00'))
        wide_preds.append({'task_id': f'W{n}', 'pred_task_id': 'T1',
                           'pred_type': 'PR_FS', 'lag_hr_cnt': '0'})
        wide_preds.append({'task_id': 'T3', 'pred_task_id': f'W{n}',
                           'pred_type': 'PR_FS', 'lag_hr_cnt': '0'})
    for t in wide_tasks:
        if t['task_code'] == 'W000':
            t['act_start_date'] = '2026-12-01 08:00'   # after the status date
    wide = dcma_14_assess(_schedule(wide_tasks, wide_preds), profile='commercial')
    wcheck = wide['per_check']['DCMA-09-InvalidDates']
    pct = 100.0 * wcheck['value'] / len(wide_tasks)
    assert wcheck['value'] == 1, f'expected exactly one invalid date, got {wcheck["value"]}'
    assert pct < 5.0, f'fixture must sit UNDER a 5% tolerance to discriminate; got {pct:.1f}%'
    assert wcheck['severity'] == 'BLOCK', (
        f'one invalid date in {len(wide_tasks)} activities is {pct:.1f}%, which a '
        f'percentage rule would pass. The published target is ZERO, so it must '
        f'BLOCK; got {wcheck["severity"]}')


def test_lock_lags_has_no_magnitude_gate():
    """#3 is the ≤5%-of-relationships test only.

    An implementation that adds a second gate failing any individual lag above
    44 working days fails schedules that pass the published test. dcma14.py
    applies no magnitude gate, which matches the published #3.
    """
    tasks, preds = _chain()
    # One 60-working-day lag among 100 relationships = 1% lagged: passes the
    # published test outright, and there is no separate magnitude gate to fail.
    preds[2]['lag_hr_cnt'] = '480'
    for _ in range(97):
        preds.append({'task_id': 'T2', 'pred_task_id': 'T1',
                      'pred_type': 'PR_FS', 'lag_hr_cnt': '0'})
    result = dcma_14_assess(_schedule(tasks, preds), profile='commercial')
    check = result['per_check']['DCMA-03-Lags']
    assert check['value'] <= 5.0
    assert check['severity'] == 'PASS', (
        f'#3 is a percentage test only; a single long lag must not fail it. '
        f'{check["message"]}')


def test_lock_cpli_commercial_floor_is_095():
    """#13's commercial floor is 0.95, not 1.0, and it must GRADE by it.

    An implementation that grades CPLI against 1.0 marks a schedule at 0.97,
    compliant under DCMA, as failing. dcma14.py takes the floor from the
    profile (0.95 commercial, 0.98 nuclear), which matches the published
    thresholds.

    ASSERTION STRENGTHENED 2026-08-25. This used to check only the reported
    `threshold` value and never the verdict, so an implementation that reported
    0.95 while grading against 1.0 passed it. An adversarial pass planted
    exactly that and the whole file stayed green.

    A CPLI of 0.977 is the discriminating case: compliant under the commercial
    0.95 floor, non-compliant under nuclear's 0.98, and failing under a 1.0
    floor. Only an implementation grading by the profile floor gets
    all three of these right.
    """
    tasks, preds = _chain()
    com = dcma_14_assess(_schedule(tasks, preds), profile='commercial')
    nuc = dcma_14_assess(_schedule(tasks, preds), profile='nuclear')
    assert com['per_check']['DCMA-13-CPLI']['threshold'] == 0.95
    assert nuc['per_check']['DCMA-13-CPLI']['threshold'] == 0.98

    # CPLI 0.977 — inside the band where the two profiles must disagree.
    tasks, preds = _chain(finish_tf='-2', mid_tf='-2')
    com = dcma_14_assess(_schedule(tasks, preds), profile='commercial')['per_check']['DCMA-13-CPLI']
    nuc = dcma_14_assess(_schedule(tasks, preds), profile='nuclear')['per_check']['DCMA-13-CPLI']
    assert 0.95 < com['value'] < 0.98, (
        f'fixture no longer lands between the two floors; got {com["value"]}')
    assert com['severity'] == 'PASS', (
        f'CPLI {com["value"]:.3f} clears the commercial floor of 0.95 and must '
        f'PASS; grading it against 1.0 is the defect this test locks out. Got '
        f'{com["severity"]}')
    assert nuc['severity'] == 'BLOCK', (
        f'CPLI {nuc["value"]:.3f} is below the nuclear floor of 0.98 and must '
        f'BLOCK; got {nuc["severity"]}')

    # And just above the commercial floor, it still passes.
    tasks, preds = _chain(finish_tf='-4', mid_tf='-4')
    near = dcma_14_assess(_schedule(tasks, preds), profile='commercial')['per_check']['DCMA-13-CPLI']
    assert near['value'] >= 0.95 and near['severity'] == 'PASS', (
        f'CPLI {near["value"]:.4f} sits just above the 0.95 floor and must '
        f'PASS; got {near["severity"]}')
