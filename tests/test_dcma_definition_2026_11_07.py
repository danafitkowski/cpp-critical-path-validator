#!/usr/bin/env python3
"""CPP's written DCMA-14 definition (7 November 2026): rules the shared
parity fixtures do not reach on their own. The definition is at
https://criticalpathpartners.ca/dcma-14-definition.html (a copy is in
tests/fixtures/dcma_parity/); tests/test_dcma_parity.py runs the fixtures.

  D0  several projects in a file: latest data date, then the most TASK rows,
      then file order; the result names the project scored.
  D8  an Activity ID repeated in the CURRENT file is left out of #11 and #14.
  D9  a baseline file none of whose projects shares an Activity ID is not
      used: #11, #13 and #14 are NOT SCORED and say why; #8 reads the current
      duration.
  #3  a lag over 44 working days is listed for information only.
  #10 every profile passes only at 100%.
  Profiles: a result graded on nuclear or mining names the profile and says
      the threshold is CPP's, derived from the DCMA check.

Clarified in the definition the same day:
  D11 on a tie: a finish milestone, then an activity of zero original
      duration, else the first in the file.
  #1  a milestone's exemption covers only the missing side named.
  #12 the pin reads the primary or the secondary constraint.
  D9  ties broken as D0 breaks them.
  #10 a blank original duration is left out of the population.

Clarified later the same day:
  D12 a baseline activity's finish is its planned finish, else its early
      finish, for #11, #13 and #14.
"""
import copy
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, '..', 'scripts'))
sys.path.insert(0, SCRIPT_DIR)

from dcma14 import dcma_14_assess  # noqa: E402
from test_dcma14_published_standard import _task, _schedule, _chain  # noqa: E402


def _loaded(data, qty='40'):
    """Give every TASKRSRC row hours."""
    for r in data['tables']['TASKRSRC']['records']:
        r['target_qty'] = qty
    data['tables']['TASKRSRC']['fields'] = ['task_id', 'rsrc_id', 'target_qty']
    return data


def _two_projects(rows_a, rows_b, date_a, date_b):
    """Projects A then B in one file, each a copy of _chain() with
    `rows_*` extra unlinked activities."""
    tasks, preds = [], []
    for pid, extra in (('A', rows_a), ('B', rows_b)):
        t, p = _chain()
        for row in t:
            row['task_id'] = pid + row['task_id']
            row['proj_id'] = pid
        for rel in p:
            rel['task_id'] = pid + rel['task_id']
            rel['pred_task_id'] = pid + rel['pred_task_id']
        for i in range(extra):
            t.append(dict(_task(f'{pid}X{i}', f'X{i}', 'Extra'), proj_id=pid))
        tasks += t
        preds += p
    data = _schedule(tasks, preds)
    proj = data['tables']['PROJECT']['records'][0]
    a = dict(proj, proj_id='A', proj_short_name='PA', last_recalc_date=date_a)
    b = dict(proj, proj_id='B', proj_short_name='PB', last_recalc_date=date_b)
    data['tables']['PROJECT']['records'] = [a, b]
    return data


def test_d0_ties_on_the_data_date_go_to_the_most_task_rows():
    data = _two_projects(0, 2, '2026-04-24 00:00', '2026-04-24 00:00')
    result = dcma_14_assess(data)
    assert result['proj_id'] == 'B'
    assert result['projects_in_file'] == 2
    assert result['project_selection'].startswith('PB (proj_id B), one of 2 projects')


def test_d0_a_full_tie_goes_to_the_first_project_in_the_file():
    data = _two_projects(1, 1, '2026-04-24 00:00', '2026-04-24 00:00')
    assert dcma_14_assess(data)['proj_id'] == 'A'


def test_d0_the_latest_data_date_wins_over_more_rows():
    data = _two_projects(5, 0, '2026-04-17 00:00', '2026-04-24 00:00')
    assert dcma_14_assess(data)['proj_id'] == 'B'


def _due_pair():
    """A baseline with A10 and A20 due on 10 April; the current file has both
    complete on time."""
    base = [_task('T1', 'A10', 'Due', start='2026-04-06 08:00', end='2026-04-10 16:00'),
            _task('T2', 'A20', 'Due', start='2026-04-06 08:00', end='2026-04-10 16:00')]
    cur = copy.deepcopy(base)
    for t in cur:
        t['status_code'] = 'TK_Complete'
        t['act_start_date'], t['act_end_date'] = t['early_start_date'], t['early_end_date']
    cur.append(_task('TZ', 'Z', 'Later', start='2026-04-27 08:00', end='2026-05-01 16:00'))
    return base, cur


def test_d8_an_id_repeated_in_the_current_file_is_left_out_of_11_and_14():
    base, cur = _due_pair()
    cur.append(dict(cur[0], task_id='T1b'))          # A10 twice in the current file
    result = dcma_14_assess(_schedule(cur, []), baseline_data=_schedule(base, []))
    eleven = result['per_check']['DCMA-11-MissedTasks']
    fourteen = result['per_check']['DCMA-14-BEI']
    assert eleven['counts'] == {'status': 'PASS', 'num': 0, 'den': 1, 'value': 0.0}, eleven
    assert eleven['details']['ambiguous_left_out'] == ['A10']
    assert 'appears more than once' in eleven['message']
    assert (fourteen['counts']['num'], fourteen['counts']['den']) == (1, 1), fourteen
    assert sorted(fourteen['details']['ambiguous_left_out']) == ['A10', 'A10', 'A10']


def test_d8_ids_match_trimmed_and_case_ignored():
    base, cur = _due_pair()
    cur[0]['task_code'] = ' a10 '
    eleven = dcma_14_assess(_schedule(cur, []), baseline_data=_schedule(base, [])
                            )['per_check']['DCMA-11-MissedTasks']
    assert (eleven['counts']['num'], eleven['counts']['den']) == (0, 2), eleven
    assert eleven['details']['not_in_current'] == []


def test_d9_a_baseline_sharing_no_id_is_not_used():
    tasks, preds = _chain()
    current = _schedule(tasks, preds)
    other = []
    for i in range(3):
        other.append(dict(_task(f'Q{i}', f'Q{i}', 'Other', start='2026-04-06 08:00',
                                end='2026-04-10 16:00'), proj_id='Q'))
    base = _schedule(other, [])
    base['tables']['PROJECT']['records'] = [
        dict(base['tables']['PROJECT']['records'][0], proj_id='Q', proj_short_name='QQ'),
        dict(base['tables']['PROJECT']['records'][0], proj_id='R', proj_short_name='RR')]
    result = dcma_14_assess(current, baseline_data=base)
    assert result['baseline_used'] is False
    for cid in ('DCMA-11-MissedTasks', 'DCMA-13-CPLI', 'DCMA-14-BEI'):
        pc = result['per_check'][cid]
        assert pc['counts']['status'] == 'NOT SCORED', (cid, pc)
        assert 'no baseline project shares an Activity ID' in pc['message'], pc['message']
    eight = result['per_check']['DCMA-08-HighDuration']
    assert eight['details']['baseline_basis_count'] == 0
    assert eight['details']['current_basis_count'] == len(
        [t for t in tasks if t['task_type'] == 'TT_Task'])


def test_3_a_long_lag_is_listed_for_information_only():
    tasks, preds = _chain()
    preds[1]['lag_hr_cnt'] = '400'                     # 50 working days
    three = dcma_14_assess(_schedule(tasks, preds))['per_check']['DCMA-03-Lags']
    assert three['details']['long_lags'] == [
        {'relationship': 'A10 > A20', 'lag_working_days': 50.0}]
    assert (three['counts']['num'], three['counts']['den']) == (1, 3)


def test_10_every_profile_passes_only_at_one_hundred_percent():
    tasks, preds = _chain()
    data = _loaded(_schedule(tasks, preds))
    data['tables']['TASKRSRC']['records'] = [
        r for r in data['tables']['TASKRSRC']['records'] if r['task_id'] != 'T2']
    for profile in ('commercial', 'nuclear', 'mining'):
        ten = dcma_14_assess(data, profile=profile)['per_check']['DCMA-10-Resources']
        assert ten['threshold'] == 100.0, (profile, ten)
        assert ten['counts'] == {'status': 'FAIL', 'num': 1, 'den': 2, 'value': 50.0}, (profile, ten)
        assert 'CPP\'s' not in ten['message'], ten['message']


def test_10_a_project_with_no_assignments_is_not_scored():
    tasks, preds = _chain()
    data = _schedule(tasks, preds)
    data['tables']['TASKRSRC']['records'] = []
    ten = dcma_14_assess(data)['per_check']['DCMA-10-Resources']
    assert ten['counts']['status'] == 'NOT SCORED'
    assert 'no resource assignments' in ten['message']


def test_a_nuclear_result_names_the_profile_and_says_the_threshold_is_cpps():
    tasks, preds = _chain()
    result = dcma_14_assess(_loaded(_schedule(tasks, preds)), profile='nuclear')
    one = result['per_check']['DCMA-01-Logic']
    assert one['threshold'] == 1.0                  # CPP's nuclear profile (as CPP's own engines)
    assert "is CPP's, derived from DCMA check #1 (5)" in one['message'], one['message']
    assert 'Nuclear' in one['message']
    assert one['details']['profile_threshold']['dcma_thresholds'] == {
        'dcma_logic_max_missing_pct': 5}
    # #2 is 0 on every profile: DCMA's own threshold, no note
    assert "CPP's" not in result['per_check']['DCMA-02-Leads']['message']


def test_the_commercial_profile_carries_no_profile_note():
    tasks, preds = _chain()
    result = dcma_14_assess(_loaded(_schedule(tasks, preds)), profile='commercial')
    for cid, pc in result['per_check'].items():
        assert "CPP's" not in pc['message'], (cid, pc['message'])
        assert 'profile_threshold' not in pc['details'], cid


# ── Clarifications (tie-breaks, either constraint, blank duration) ───

def _pinned_tie(order):
    """_chain() plus a 5-day task ending with the completion, and a
    zero-duration TT_Task completion carrying CS_MANDFIN, in `order`; the
    finish milestone is removed so the two tie on the latest early finish."""
    tasks, preds = _chain()
    tasks = [t for t in tasks if t['task_code'] != 'A30']
    preds = [p for p in preds if p['task_id'] != 'T3']
    work = _task('T5', 'W5', 'Last work', start='2026-05-04 08:00', end='2026-05-08 16:00')
    done = _task('T6', 'DONE', 'Complete (typed as a task)', start='2026-05-08 16:00',
                 end='2026-05-08 16:00', remain='0', target='0', cstr='CS_MANDFIN')
    tasks += [work, done] if order == 'work first' else [done, work]
    preds += [{'task_id': 'T5', 'pred_task_id': 'T1', 'pred_type': 'PR_FS', 'lag_hr_cnt': '0'},
              {'task_id': 'T6', 'pred_task_id': 'T5', 'pred_type': 'PR_FS', 'lag_hr_cnt': '0'}]
    return _schedule(tasks, preds)


def test_d11_a_tie_prefers_a_zero_duration_completion_over_file_order():
    for order in ('work first', 'done first'):
        twelve = dcma_14_assess(_pinned_tie(order))['per_check']['DCMA-12-CriticalPathTest']
        assert twelve['details']['finish_activity'] == 'DONE', (order, twelve['details'])
        assert twelve['counts']['status'] == 'FAIL', (order, twelve['message'])


def test_d11_a_finish_milestone_still_wins_a_tie():
    tasks, preds = _chain()
    tasks.insert(0, _task('T9', 'ZERO', 'Zero task', start='2026-05-11 08:00',
                          end='2026-05-11 08:00', remain='0', target='0'))
    preds.append({'task_id': 'T9', 'pred_task_id': 'T2', 'pred_type': 'PR_FS', 'lag_hr_cnt': '0'})
    twelve = dcma_14_assess(_schedule(tasks, preds))['per_check']['DCMA-12-CriticalPathTest']
    assert twelve['details']['finish_activity'] == 'A30', twelve['details']


def test_1_a_start_milestone_with_no_successor_is_still_a_finding():
    tasks, preds = _chain()
    preds = [p for p in preds if p['pred_task_id'] != 'T0']   # A00 drives nothing now
    one = dcma_14_assess(_schedule(tasks, preds))['per_check']['DCMA-01-Logic']
    assert one['details']['missing_succ'] == ['A00'], one['details']
    assert 'A00' not in one['details']['missing_pred']        # at the network start


def test_12_a_secondary_mandatory_constraint_pins_the_completion():
    tasks, preds = _chain()
    tasks[3]['cstr_type2'] = 'CS_MANDFIN'
    twelve = dcma_14_assess(_schedule(tasks, preds))['per_check']['DCMA-12-CriticalPathTest']
    assert twelve['counts']['status'] == 'FAIL', twelve['message']
    assert twelve['details']['finish_constraints'] == ['CS_MANDFIN']


def test_d9_two_projects_with_the_same_short_name_tie_as_d0():
    """The baseline file carries two projects named like the current one; the
    later data date is chosen though it is listed second."""
    tasks, preds = _chain()
    current = _schedule(tasks, preds)
    older = [dict(t, proj_id='OLD', task_id='O' + t['task_id']) for t in _chain()[0]]
    newer = [dict(t, proj_id='NEW', task_id='N' + t['task_id']) for t in _chain()[0]]
    base = _schedule(older + newer, [])
    proj = base['tables']['PROJECT']['records'][0]
    base['tables']['PROJECT']['records'] = [
        dict(proj, proj_id='OLD', last_recalc_date='2026-03-01 00:00'),
        dict(proj, proj_id='NEW', last_recalc_date='2026-04-01 00:00')]
    result = dcma_14_assess(current, baseline_data=base)
    assert (result['baseline_proj_id'], result['baseline_project_match']) == (
        'NEW', 'same short name')


def test_10_a_blank_original_duration_is_left_out():
    tasks, preds = _chain()
    data = _loaded(_schedule(tasks, preds))
    tasks[2]['target_drtn_hr_cnt'] = ''                       # A20
    data['tables']['TASKRSRC']['records'] = [
        r for r in data['tables']['TASKRSRC']['records'] if r['task_id'] != 'T2']
    ten = dcma_14_assess(data)['per_check']['DCMA-10-Resources']
    assert ten['counts'] == {'status': 'PASS', 'num': 1, 'den': 1, 'value': 100.0}, ten


# ── Clarification: the baseline finish ──────────────────────────────

def test_d12_13_reads_the_baselines_planned_finish_before_its_early_finish():
    """The baseline's completion carries a planned finish of 4 May and an
    early finish of 18 May: #13 reads 4 May (the forecast, 11 May, is five
    working days late). It read the early finish first, which said five
    days early."""
    tasks, preds = _chain(finish_tf='0')
    btasks, bpreds = _chain()
    btasks[3]['target_end_date'] = '2026-05-04 08:00'
    btasks[3]['early_end_date'] = '2026-05-18 08:00'
    thirteen = dcma_14_assess(_schedule(tasks, preds), baseline_data=_schedule(btasks, bpreds)
                              )['per_check']['DCMA-13-CPLI']
    assert thirteen['details']['contract_finish'].startswith('2026-05-04'), thirteen['details']
    assert thirteen['details']['tf_days'] == -5
    assert abs(thirteen['counts']['value'] - 6.0 / 11.0) < 1e-9


def test_d12_a_blank_planned_finish_falls_back_to_the_early_finish():
    """A baseline activity with no planned finish is due on its early
    finish, in #11 and #14 alike."""
    base, cur = _due_pair()
    base[1]['target_end_date'] = ''                 # A20: early finish 10 Apr only
    cur[1]['status_code'] = 'TK_NotStart'           # and still open
    cur[1]['act_start_date'] = cur[1]['act_end_date'] = ''
    result = dcma_14_assess(_schedule(cur, []), baseline_data=_schedule(base, []))
    eleven = result['per_check']['DCMA-11-MissedTasks']
    fourteen = result['per_check']['DCMA-14-BEI']
    assert (eleven['counts']['num'], eleven['counts']['den']) == (1, 2), eleven
    assert eleven['details']['still_open'] == ['A20']
    assert (fourteen['counts']['num'], fourteen['counts']['den']) == (1, 2), fourteen
