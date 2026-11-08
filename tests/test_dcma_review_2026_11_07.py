#!/usr/bin/env python3
"""DCMA-14 review (7 November 2026): five validator defects found by a
three-reviewer audit and fixed.

  #5  Hard Constraints counts the four hard types DCMA-EA PAM 200.1 s4.5 lists:
      Must Start On / Must Finish On (CS_MSO, CS_MEO, and P6's mandatory
      CS_MANDSTART / CS_MANDFIN) and Start No Later Than / Finish No Later Than
      (CS_MSOB, CS_MEOB in P6). It used to miss the last two.
  Vacuous passes: a check whose population is empty is NOT ASSESSED (INFO),
      never PASS, so it drops out of dcma_score and dcma_max.
  #11 Missed Tasks needs a baseline, reads the BASELINE due set, counts a due
      baseline activity missing from the current file as missed, and is not
      assessed when fewer than 80% of the due activities match.
  #12 an unlinked project finish is NOT ASSESSED (it is #1's finding); a
      mandatory pin still fails.
  #13 CPLI reads the float to the contract finish: the baseline finish of the
      same activity, or a deadline in the file; with neither it is not
      assessed (the float to completion is 0 by construction).

Every test below failed on the code before this change. The same rules are
in CPP's written DCMA-14 definition (tests/fixtures/dcma_parity/DCMA_DEFINITION.md).
"""
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, '..', 'scripts'))
sys.path.insert(0, SCRIPT_DIR)

from config_profiles import get_profile  # noqa: E402
import dcma14  # noqa: E402
from dcma14 import dcma_14_assess, _check_05_hard_constraints  # noqa: E402
from test_dcma14_published_standard import _task, _schedule, _chain  # noqa: E402

PROF = get_profile('commercial')


def _ten(cstr_at=None, cstr2_at=None):
    """Ten incomplete activities in one FS chain; optionally one constrained."""
    tasks, preds = [], []
    for i in range(10):
        t = _task(f'T{i}', f'A{i:02d}', f'Act {i}', tf='0',
                  start='2026-04-27 08:00', end='2026-05-01 16:00')
        if cstr_at == i:
            t['cstr_type'] = 'CS_MEOB'
        if cstr2_at == i:
            t['cstr_type2'] = 'CS_MSOB'
        tasks.append(t)
        if i:
            preds.append({'task_id': f'T{i}', 'pred_task_id': f'T{i - 1}',
                          'pred_type': 'PR_FS', 'lag_hr_cnt': '0'})
    return tasks, preds


def _complete(t, act_end=None):
    t['status_code'] = 'TK_Complete'
    t['act_start_date'] = t['early_start_date']
    t['act_end_date'] = act_end or t['early_end_date']
    t['remain_drtn_hr_cnt'] = '0'


def _assessed_ids(result):
    return {cid for cid, v in result['per_check'].items() if v['severity'] != 'INFO'}


def _assert_not_assessed(result, cid):
    check = result['per_check'][cid]
    assert check['severity'] == 'INFO', (cid, check['severity'], check['message'])
    assert check['value'] is None, (cid, check['value'])
    assert check['details'].get('assessed') is False, (cid, check['details'])
    # 2026-11-07, the written definition: the message says NOT SCORED, the definition's word (it said NOT ASSESSED).
    assert 'NOT SCORED' in check['message'], (cid, check['message'])
    assert cid in result['dcma_not_assessed'], cid
    assert result['dcma_max'] == len(_assessed_ids(result))


# ─────────────────────────────────────────────────────────────────────
# #5 Hard Constraints: the DCMA vocabulary
# ─────────────────────────────────────────────────────────────────────

def test_05_one_finish_on_or_before_of_ten_reads_ten_percent():
    tasks, preds = _ten(cstr_at=3)
    check = dcma_14_assess(_schedule(tasks, preds))['per_check']['DCMA-05-Hard']
    assert abs(check['value'] - 10.0) < 1e-9, check
    assert check['severity'] == 'WARN', check


def test_05_secondary_start_on_or_before_is_counted():
    tasks, preds = _ten(cstr2_at=7)
    check = dcma_14_assess(_schedule(tasks, preds))['per_check']['DCMA-05-Hard']
    assert abs(check['value'] - 10.0) < 1e-9, check
    assert check['details']['hard_count'] == 1


def test_05_vocabulary_and_message_name_the_codes():
    assert getattr(dcma14, 'DCMA_HARD_CONSTRAINTS', None) == {'CS_MANDSTART', 'CS_MANDFIN', 'CS_MSO',
                                     'CS_MEO', 'CS_MSOB', 'CS_MEOB'}
    tasks, preds = _ten()
    msg = dcma_14_assess(_schedule(tasks, preds))['per_check']['DCMA-05-Hard']['message']
    for code in sorted(dcma14.DCMA_HARD_CONSTRAINTS):
        assert code in msg, (code, msg)


def test_05_cp_validator_hard_set_is_unchanged():
    from cp_validator import HARD_CONSTRAINTS
    assert HARD_CONSTRAINTS == {'CS_MANDSTART', 'CS_MANDFIN', 'CS_MSO', 'CS_MEO'}


# ─────────────────────────────────────────────────────────────────────
# Vacuous passes are NOT ASSESSED
# ─────────────────────────────────────────────────────────────────────

def test_finished_schedule_logic_float_duration_are_not_assessed():
    tasks, preds = _chain()
    for t in tasks:
        _complete(t)
    result = dcma_14_assess(_schedule(tasks, preds, data_date='2026-05-12 00:00'))
    for cid in ('DCMA-01-Logic', 'DCMA-06-HighFloat', 'DCMA-07-NegFloat',
                'DCMA-08-HighDuration'):
        _assert_not_assessed(result, cid)


def test_no_relationships_leads_lags_types_are_not_assessed():
    tasks, _ = _chain()
    result = dcma_14_assess(_schedule(tasks, []))
    for cid in ('DCMA-02-Leads', 'DCMA-03-Lags', 'DCMA-04-Relationship'):
        _assert_not_assessed(result, cid)


def test_no_work_tasks_hard_constraints_not_assessed():
    sev, val, _thr, msg, det = _check_05_hard_constraints([], PROF)
    assert (sev, val) == ('INFO', None)
    # 2026-11-07, the written definition: the message says NOT SCORED, the definition's word (it said NOT ASSESSED).
    assert det['assessed'] is False and 'NOT SCORED' in msg


def test_only_milestones_open_high_duration_not_assessed_and_never_of_one():
    tasks, preds = _chain()
    for t in tasks:
        if t['task_type'] == 'TT_Task':
            _complete(t, act_end='2026-04-23 16:00')
            t['act_start_date'] = '2026-04-20 08:00'
    result = dcma_14_assess(_schedule(tasks, preds))
    _assert_not_assessed(result, 'DCMA-08-HighDuration')
    assert 'of 1 ' not in result['per_check']['DCMA-08-HighDuration']['message']


def test_nothing_due_by_the_status_date_missed_tasks_not_assessed():
    tasks, preds = _chain()
    baseline = _schedule(_chain()[0], preds)
    result = dcma_14_assess(_schedule(tasks, preds), baseline_data=baseline)
    _assert_not_assessed(result, 'DCMA-11-MissedTasks')


# ─────────────────────────────────────────────────────────────────────
# #11 Missed Tasks
# ─────────────────────────────────────────────────────────────────────

def _five_due(current_codes):
    """A baseline with B1..B5 due on 10 April; the current file carries
    `current_codes` of them, every one complete on time."""
    base = [_task(f'B{i}', f'B{i}', f'Due {i}', start='2026-04-06 08:00',
                  end='2026-04-10 16:00') for i in range(1, 6)]
    cur = []
    for i in range(1, 6):
        code = f'B{i}'
        if code in current_codes:
            t = _task(f'C{i}', code, f'Due {i}', start='2026-04-06 08:00',
                      end='2026-04-10 16:00')
            _complete(t)
            cur.append(t)
    # an open activity after the data date keeps the file live
    cur.append(_task('CZ', 'Z', 'Later', start='2026-04-27 08:00',
                     end='2026-05-01 16:00'))
    return _schedule(base, []), _schedule(cur, [])


def test_11_without_a_baseline_is_not_assessed():
    tasks, preds = _chain()
    tasks[1]['target_end_date'] = '2026-04-10 16:00'   # a planned finish before DD
    result = dcma_14_assess(_schedule(tasks, preds))
    _assert_not_assessed(result, 'DCMA-11-MissedTasks')
    msg = result['per_check']['DCMA-11-MissedTasks']['message']
    assert 'no baseline' in msg.lower() and 'planned finish' in msg.lower(), msg


def test_11_a_due_activity_deleted_from_the_current_file_is_missed():
    baseline, current = _five_due({'B1', 'B2', 'B3', 'B4'})
    check = dcma_14_assess(current, baseline_data=baseline)['per_check']['DCMA-11-MissedTasks']
    det = check['details']
    assert check['severity'] == 'WARN', check
    assert abs(check['value'] - 20.0) < 1e-9, check
    assert det['not_in_current'] == ['B5'], det
    assert (det['due_count'], det['matched_count'], det['not_in_current_count']) == (5, 4, 1)
    assert abs(det['match_pct'] - 80.0) < 1e-9
    assert det['missed_count'] == 1 and det['assessed'] is True


def test_11_fewer_than_eighty_percent_matched_is_not_assessed():
    assert getattr(dcma14, 'MISSED_TASKS_MIN_MATCH_PCT', None) == 80.0
    baseline, current = _five_due({'B1', 'B2', 'B3'})
    result = dcma_14_assess(current, baseline_data=baseline)
    _assert_not_assessed(result, 'DCMA-11-MissedTasks')
    det = result['per_check']['DCMA-11-MissedTasks']['details']
    assert (det['due_count'], det['matched_count']) == (5, 3), det
    assert sorted(det['not_in_current']) == ['B4', 'B5']


# ─────────────────────────────────────────────────────────────────────
# #13 CPLI
# ─────────────────────────────────────────────────────────────────────

def _baseline_with_finish(finish_end, code='A30'):
    btasks, bpreds = _chain()
    btasks[3]['task_code'] = code
    btasks[3]['early_end_date'] = btasks[3]['target_end_date'] = finish_end
    return _schedule(btasks, bpreds)


def test_13_forecast_later_than_the_baseline_finish_reads_below_one():
    tasks, preds = _chain(finish_tf='0')      # P6 float 0: the old rule read 1.000
    result = dcma_14_assess(_schedule(tasks, preds),
                            baseline_data=_baseline_with_finish('2026-05-04 08:00'))
    check = result['per_check']['DCMA-13-CPLI']
    det = check['details']
    assert det['basis'] == 'baseline', det
    assert det['cp_length_days'] == 11 and det['tf_days'] == -5, det
    assert abs(check['value'] - 6.0 / 11.0) < 1e-9, check
    assert check['severity'] == 'BLOCK'
    assert det['contract_activity'] == 'A30' and det['finish_activity'] == 'A30'
    assert det['contract_finish'].startswith('2026-05-04')
    assert det['forecast_finish'].startswith('2026-05-11')


def test_13_forecast_earlier_than_the_baseline_finish_reads_above_one():
    tasks, preds = _chain(finish_tf='0')
    result = dcma_14_assess(_schedule(tasks, preds),
                            baseline_data=_baseline_with_finish('2026-05-18 08:00'))
    check = result['per_check']['DCMA-13-CPLI']
    assert check['details']['tf_days'] == 5
    assert abs(check['value'] - 16.0 / 11.0) < 1e-9, check
    assert check['severity'] == 'PASS'


def test_13_finish_code_not_in_baseline_uses_the_baseline_completion():
    tasks, preds = _chain(finish_tf='0')
    result = dcma_14_assess(_schedule(tasks, preds),
                            baseline_data=_baseline_with_finish('2026-05-18 08:00', code='Z99'))
    check = result['per_check']['DCMA-13-CPLI']
    assert check['details']['contract_activity'] == 'Z99', check['details']
    assert 'Z99' in check['message'] and 'not in the baseline' in check['message']
    assert abs(check['value'] - 16.0 / 11.0) < 1e-9


def test_13_no_baseline_no_deadline_is_not_assessed():
    tasks, preds = _chain(finish_tf='0')
    result = dcma_14_assess(_schedule(tasks, preds, project_extra={'plan_end_date': ''}))
    _assert_not_assessed(result, 'DCMA-13-CPLI')
    assert result['cpli'] is None
    assert '1.000' in result['per_check']['DCMA-13-CPLI']['message']


def test_13_no_baseline_no_deadline_but_negative_float_uses_p6_float():
    # Real exports carry negative float on the finish activity with no Must
    # Finish By and no finish constraint (P6 measured it against some date).
    # That is a real behind-schedule signal, not a 1.000 by construction.
    tasks, preds = _chain(finish_tf='-80')
    result = dcma_14_assess(_schedule(tasks, preds, project_extra={'plan_end_date': ''}))
    pc = result['per_check']['DCMA-13-CPLI']
    assert pc['severity'] != 'INFO', pc['message']
    assert pc['value'] < 1.0
    assert 'float is not zero' in pc['message']


def test_13_no_baseline_must_finish_by_is_read_as_working_time():
    # A named deadline is read as the working time from the forecast finish to
    # its date on the project calendar, the unit of the critical path length.
    # Must Finish By five working days before the finish -> float -5 -> 6/11.
    tasks, preds = _chain(finish_tf='-40', mid_tf='-40')
    check = dcma_14_assess(_schedule(tasks, preds, project_extra={'plan_end_date': '2026-05-01 16:00'})
                           )['per_check']['DCMA-13-CPLI']
    assert check['details']['basis'] == 'deadline_working_time', check['details']
    assert abs(check['value'] - 6.0 / 11.0) < 1e-9, check


def test_13_no_baseline_finish_constraint_is_a_deadline():
    tasks, preds = _chain(finish_tf='-40', mid_tf='-40', finish_cstr='CS_MEOB')
    check = dcma_14_assess(_schedule(tasks, preds, project_extra={'plan_end_date': ''})
                           )['per_check']['DCMA-13-CPLI']
    assert check['details']['basis'] == 'p6_float_to_deadline', check['details']
    assert abs(check['value'] - 6.0 / 11.0) < 1e-9, check


# ─────────────────────────────────────────────────────────────────────
# #12 Critical Path Test
# ─────────────────────────────────────────────────────────────────────

def test_12_unlinked_finish_is_not_assessed_and_names_logic():
    tasks, preds = _chain()
    preds = [p for p in preds if p['task_id'] != 'T3']
    result = dcma_14_assess(_schedule(tasks, preds))
    check = result['per_check']['DCMA-12-CriticalPathTest']
    assert check['severity'] == 'INFO', check
    assert check['details']['no_predecessor'] is True
    assert check['details']['assessed'] is False
    assert '#1' in check['message'], check['message']
    assert 'DCMA-12-CriticalPathTest' in result['dcma_not_assessed']


def test_12_mandatory_pin_still_blocks_with_the_practice_wording():
    tasks, preds = _chain(finish_cstr='CS_MANDFIN')
    check = dcma_14_assess(_schedule(tasks, preds))['per_check']['DCMA-12-CriticalPathTest']
    assert check['severity'] == 'BLOCK', check
    assert 'commonly 600 working days' in check['message'], check['message']
