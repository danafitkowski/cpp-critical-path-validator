"""One project per report, in every figure (2026-09-21).

DCMA-EA PAM 200.1 (October 2012), section 4.0: the 14 Point Schedule Metrics
identify problem areas "with a contractor's IMS", one schedule. Every metric
is a count over THAT schedule's tasks: section 4.7 Negative Float divides "the
total number of tasks with negative float by the number of incomplete tasks";
section 4.11 Missed Tasks counts tasks whose "baseline finish date [is] on or
before the status date"; section 3.1.2.4 BEI "compares the cumulative number
of tasks completed to the cumulative number of tasks with a baseline finish
date on or before the current reporting period".

A P6 export can hold several projects (a baseline copy beside the live
schedule is the usual case). Two
defects let another project's rows into the figures:

  * validate_critical_path picks its project by TASK-row count (or index) and
    then handed the WHOLE file to dcma_14_assess, which picks by latest data
    date. The two rules disagree on real multi-project files, so the
    embedded DCMA block described a different project from the report's
    title, data date and activity population.

  * check 14 (BEI) iterated every current and every baseline TASK row with no
    project scope, and check 11 (Missed Tasks) read every baseline row the
    same way. A completed activity in an unrelated project raised BEI from
    0.0 to 1.0, and an unrelated baseline row reusing an activity code moved
    a due date.

The project is now selected once. dcma_14_assess takes it as `proj_id` (left
out, a direct caller gets the latest-data-date rule as before), names the
project it assessed in its result, and checks 11 and 14 read the selected
project's rows and the MATCHING baseline project's rows: same proj_id, else
same short name, else the baseline project sharing the most activity codes.
"""
import copy
import os
import sys
import warnings

import pytest

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, '..', 'scripts'))

from dcma14 import dcma_14_assess  # noqa: E402
from cp_validator import validate_critical_path  # noqa: E402

_TASK_FIELDS = [
    'task_id', 'proj_id', 'wbs_id', 'task_code', 'task_name', 'task_type',
    'status_code', 'total_float_hr_cnt', 'clndr_id', 'cstr_type', 'cstr_type2',
    'target_start_date', 'target_end_date', 'early_start_date', 'early_end_date',
    'act_start_date', 'act_end_date', 'remain_drtn_hr_cnt', 'target_drtn_hr_cnt',
    'driving_path_flag',
]


def _task(tid, code, proj, status='TK_NotStart', tf='0',
          start='2026-01-19 08:00', end='2026-01-23 17:00', planned_end=None,
          act_start='', act_end='', ttype='TT_Task', cstr=''):
    return {
        'task_id': tid, 'proj_id': proj, 'wbs_id': 'W' + proj, 'task_code': code,
        'task_name': 'Activity ' + code, 'task_type': ttype, 'status_code': status,
        'total_float_hr_cnt': tf, 'clndr_id': 'C1', 'cstr_type': cstr,
        'cstr_type2': '', 'target_start_date': start,
        'target_end_date': planned_end or end,
        'early_start_date': start, 'early_end_date': end,
        'act_start_date': act_start, 'act_end_date': act_end,
        'remain_drtn_hr_cnt': '0' if status == 'TK_Complete' else '40',
        'target_drtn_hr_cnt': '40', 'driving_path_flag': 'N',
    }


def _project(pid, short, data_date):
    return {'proj_id': pid, 'proj_short_name': short,
            'last_recalc_date': data_date, 'clndr_id': 'C1'}


def _data(projects, tasks, preds=(), rsrc=()):
    return {'tables': {
        'PROJECT': {'fields': list(projects[0]), 'records': list(projects)},
        'CALENDAR': {
            'fields': ['clndr_id', 'clndr_name', 'day_hr_cnt', 'week_hr_cnt',
                       'default_flag', 'clndr_type', 'clndr_data'],
            'records': [{'clndr_id': 'C1', 'clndr_name': '5-Day', 'day_hr_cnt': '8',
                         'week_hr_cnt': '40', 'default_flag': 'Y',
                         'clndr_type': 'CA_Base', 'clndr_data': ''}]},
        'TASK': {'fields': list(_TASK_FIELDS), 'records': list(tasks)},
        'TASKPRED': {'fields': ['task_pred_id', 'task_id', 'pred_task_id',
                                'pred_type', 'lag_hr_cnt'],
                     'records': list(preds)},
        'TASKRSRC': {'fields': ['task_id', 'rsrc_id'], 'records': list(rsrc)},
    }}


def _pred(n, succ, pred, lag='0'):
    return {'task_pred_id': str(n), 'task_id': succ, 'pred_task_id': pred,
            'pred_type': 'PR_FS', 'lag_hr_cnt': lag}


def _validate(data, **kw):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        return validate_critical_path(data, **kw)


# ───────────────────────────────── D13: the validator and its DCMA block

def _old_and_new():
    """OLD: two activities at zero float, data date 5 January.
    NEW: one activity at -8 h, data date 12 January.
    Most rows -> OLD. Latest data date -> NEW."""
    return _data(
        [_project('OLD', 'OLD', '2026-01-05 08:00'),
         _project('NEW', 'NEW', '2026-01-12 08:00')],
        [_task('1', 'O1', 'OLD'), _task('2', 'O2', 'OLD'),
         _task('3', 'N1', 'NEW', tf='-8')],
        [_pred(1, '2', '1')])


def test_the_embedded_dcma_block_describes_the_project_the_report_names():
    """PAM 200.1 section 4.7: negative float is counted over the incomplete
    tasks of the schedule under assessment.

    The report is about OLD: 2 activities, neither with negative float, so its
    embedded check 7 must read 0 and PASS, on OLD's 5 January status date.
    Before the fix the block was computed on NEW and said "1 activities with
    negative total float", BLOCK, inside a report titled OLD.
    """
    v = _validate(_old_and_new())
    assert v['project_name'] == 'OLD' and v['total_activities'] == 2
    block = v['dcma_14']
    seven = block['per_check']['DCMA-07-NegFloat']
    assert seven['value'] == 0 and seven['severity'] == 'PASS', seven['message']
    assert 'status date 2026-01-05' in block['per_check']['DCMA-09-InvalidDates']['message']
    # ... and the block names the project it graded
    assert block.get('proj_id') == 'OLD', block.get('proj_id')
    assert block['project_name'] == 'OLD'
    assert block['data_date'] == '2026-01-05 08:00'


def test_project_index_reaches_the_dcma_block_too():
    """The same section 4.7 count, for the caller who asks for the second
    project: the report and its DCMA block both move to NEW, where one
    activity carries -8 h."""
    v = _validate(_old_and_new(), project_index=1)
    assert v['project_name'] == 'NEW'
    assert v['dcma_14']['per_check']['DCMA-07-NegFloat']['value'] == 1
    assert v['dcma_14']['proj_id'] == 'NEW'


def test_a_direct_caller_keeps_the_latest_data_date_rule_and_is_told_the_pick():
    """No proj_id: today's rule, the live schedule is the one with the latest
    data date (NEW, 1 negative-float activity per section 4.7). The result now
    names the project, so a caller can see which one was graded."""
    result = dcma_14_assess(_old_and_new())
    assert result['per_check']['DCMA-07-NegFloat']['value'] == 1
    assert result.get('proj_id') == 'NEW' and result['project_name'] == 'NEW'
    assert result['data_date'] == '2026-01-12 08:00'


def test_an_explicit_project_is_honoured_and_an_unknown_one_is_refused():
    """Section 4.7 over OLD's two tasks: 0. An id the file does not hold must
    not come back as a clean, empty assessment."""
    result = dcma_14_assess(_old_and_new(), proj_id='OLD')
    assert result['proj_id'] == 'OLD'
    assert result['per_check']['DCMA-07-NegFloat']['value'] == 0
    with pytest.raises(ValueError, match='NOPE'):
        dcma_14_assess(_old_and_new(), proj_id='NOPE')


# ───────────────────────────────── D14: check 14 and check 11 populations

DD = '2026-01-12 08:00'


def test_bei_ignores_a_completed_activity_in_an_unrelated_project():
    """PAM 200.1 section 3.1.2.4: BEI = tasks completed / tasks with a baseline
    finish on or before the reporting period, for the schedule under
    assessment.

    P has one activity, A, baselined to finish 5 January, before the 12
    January status date, and not started: BEI = 0 / 1 = 0.0. The export also
    holds project Q (older data date, so P stays selected) with one completed
    activity. Q's completion is not P's throughput: BEI must stay 0.0. Before
    the fix it read 1 / 1 = 1.0 and passed.
    """
    baseline = _data([_project('P', 'P', '2026-01-05 08:00')],
                     [_task('1', 'A', 'P', start='2026-01-05 08:00',
                            end='2026-01-05 17:00')])
    current = _data([_project('P', 'P', DD)],
                    [_task('1', 'A', 'P', planned_end='2026-01-05 17:00')])
    alone = dcma_14_assess(current, baseline_data=baseline)
    assert alone['bei'] == 0.0

    current['tables']['PROJECT']['records'].append(_project('Q', 'OTHER', '2026-01-01 08:00'))
    current['tables']['TASK']['records'].append(
        _task('99', 'Q1', 'Q', status='TK_Complete', act_start='2026-01-02 08:00',
              act_end='2026-01-02 17:00'))
    mixed = dcma_14_assess(current, baseline_data=baseline)
    assert mixed['bei'] == 0.0, mixed['per_check']['DCMA-14-BEI']['message']
    assert mixed['per_check']['DCMA-14-BEI']['details']['completed'] == 0
    assert mixed['proj_id'] == 'P'


def _current_p():
    """P at 12 January: A open (its current planned finish dragged to 30
    January), B complete on 8 January at 16:00."""
    return _data([_project('P', 'P', DD)], [
        _task('1', 'A', 'P', planned_end='2026-01-30 17:00'),
        _task('2', 'B', 'P', status='TK_Complete', act_start='2026-01-05 08:00',
              act_end='2026-01-08 16:00', start='2026-01-05 08:00',
              end='2026-01-08 16:00'),
    ], [_pred(1, '1', '2')])


def _baseline_with_an_unrelated_project(bl_pid, bl_short):
    """P's baseline (A due 9 January, B due 8 January, both before the status
    date) and, AFTER it in the file, unrelated project R: it reuses activity
    code A with a planned finish of 31 March, and has three more activities
    due on 2 January."""
    rows = [
        _task('11', 'A', bl_pid, start='2026-01-05 08:00', end='2026-01-09 17:00'),
        _task('12', 'B', bl_pid, start='2026-01-05 08:00', end='2026-01-08 17:00'),
        _task('21', 'A', 'R', start='2026-03-02 08:00', end='2026-03-31 17:00'),
    ] + [_task(str(30 + i), 'X%d' % i, 'R', start='2026-01-02 08:00',
               end='2026-01-02 17:00') for i in range(3)]
    return _data([_project(bl_pid, bl_short, '2026-01-05 08:00'),
                  _project('R', 'RELATED-TO-NOTHING', '2026-02-02 08:00')], rows)


@pytest.mark.parametrize('bl_pid, bl_short, tier', [
    ('P', 'P-AS-BASELINED', 'same proj_id'),
    ('7001', 'P', 'same short name'),
    ('7001', 'P - B1', 'most shared activity codes'),
])
def test_checks_11_and_14_read_the_matching_baseline_project(bl_pid, bl_short, tier):
    """PAM 200.1 sections 4.11 and 3.1.2.4 both count tasks "with a baseline
    finish date on or before" the status date, of the schedule under
    assessment. The project is matched first, the activity code second.

    P's own baseline has two activities due by 12 January: A (9 January) and B
    (8 January).
      check 14  completed in P = 1 (B)  ->  BEI = 1 / 2 = 0.5
      check 11  A is still open, B finished 8 January 16:00 against a due
                8 January 17:00  ->  1 of 2 missed = 50.0 %
    Before the fix every baseline row was read: R's three 2 January rows made
    the BEI denominator 5 (BEI 0.2), and R's row for code A, read last, moved
    A's due date to 31 March, so check 11 saw 1 due, 0 missed = 0.0 % PASS.

    Matching tier under test: see the parameter. R's later data date is there
    so that a "latest data date" pick on the baseline file would be wrong.
    """
    result = dcma_14_assess(_current_p(),
                            baseline_data=_baseline_with_an_unrelated_project(bl_pid, bl_short))
    bei = result['per_check']['DCMA-14-BEI']['details']
    assert bei['baselined_due'] == 2, (tier, bei)
    assert bei['completed'] == 1
    assert result['bei'] == 0.5
    eleven = result['per_check']['DCMA-11-MissedTasks']
    assert eleven['details']['due_by_dd'] == 2, (tier, eleven['details'])
    assert eleven['details']['still_open'] == ['A']
    assert eleven['details']['late_finish'] == []
    assert eleven['value'] == 50.0
    # the block says which baseline project it read, and how it was matched
    assert result['baseline_proj_id'] == bl_pid
    assert result['baseline_project_match'] == tier


def test_a_single_project_baseline_is_used_as_it_always_was():
    """One project in the baseline file: nothing to match, whatever its id or
    name. Same arithmetic as above, BEI 1 / 2 = 0.5 (section 3.1.2.4)."""
    baseline = _baseline_with_an_unrelated_project('7001', 'SOMETHING ELSE')
    baseline['tables']['PROJECT']['records'] = baseline['tables']['PROJECT']['records'][:1]
    baseline['tables']['TASK']['records'] = [
        t for t in baseline['tables']['TASK']['records'] if t['proj_id'] == '7001']
    result = dcma_14_assess(_current_p(), baseline_data=baseline)
    assert result['bei'] == 0.5
    assert result['baseline_proj_id'] == '7001'
    assert result['baseline_project_match'] == 'only project in the baseline file'


# ───────────────────────────────── the invariant

def _unrelated_project_rows():
    """Project U, smaller and older than P so that both selection rules keep
    P, and carrying one of everything that would move a P figure if it leaked:
    negative float, a completion, a future actual, a hard constraint, a lead,
    a resource assignment, and P's own activity codes."""
    tasks = [
        _task('901', 'A', 'U', tf='-80', cstr='CS_MANDFIN'),
        _task('902', 'B', 'U', status='TK_Complete', act_start='2026-01-02 08:00',
              act_end='2026-03-01 17:00'),
    ]
    preds = [_pred(900, '901', '902', lag='-16')]
    rsrc = [{'task_id': '901', 'rsrc_id': 'R1'}]
    return _project('U', 'UNRELATED', '2026-01-02 08:00'), tasks, preds, rsrc


def _with_unrelated(data):
    out = copy.deepcopy(data)
    proj, tasks, preds, rsrc = _unrelated_project_rows()
    out['tables']['PROJECT']['records'].append(proj)
    out['tables']['TASK']['records'].extend(tasks)
    out['tables']['TASKPRED']['records'].extend(preds)
    out['tables']['TASKRSRC']['records'].extend(rsrc)
    return out


def _p_with_a_third_activity():
    data = _current_p()
    data['tables']['TASK']['records'].append(
        _task('3', 'C', 'P', ttype='TT_FinMile', start='2026-01-23 17:00',
              end='2026-01-23 17:00'))
    data['tables']['TASKPRED']['records'].append(_pred(2, '3', '1'))
    return data


def _baselines():
    """(P's baseline with unrelated project R beside it, P's baseline alone)."""
    mixed = _baseline_with_an_unrelated_project('P', 'P')
    clean = copy.deepcopy(mixed)
    clean['tables']['PROJECT']['records'] = clean['tables']['PROJECT']['records'][:1]
    clean['tables']['TASK']['records'] = [
        t for t in clean['tables']['TASK']['records'] if t['proj_id'] == 'P']
    return mixed, clean


def _comparable(result):
    """Everything dcma_14_assess measures, in a form two runs can be compared
    on (the ValidationReport object becomes its dict)."""
    out = {k: v for k, v in result.items() if k != 'report'}
    out['report'] = result['report'].to_dict()
    return out


def test_adding_an_unrelated_project_changes_no_metric_of_the_selected_one():
    """Section 4.0: the metrics describe one IMS. Put an unrelated project in
    the current export and another in the baseline export, and every figure,
    message, register and score for P must come back identical: all fourteen
    checks, CPLI, BEI, the critical paths and the continuity result.

    Before the fix BEI moved (1 / 2 = 0.5 became 1 / 5 = 0.2: R's three rows
    joined the denominator; U's completion is dated after the status date, so
    the numerator held) and check 11's due count fell from 2 to 1.
    """
    current = _p_with_a_third_activity()
    baseline, clean_baseline = _baselines()

    alone = _comparable(dcma_14_assess(current, baseline_data=clean_baseline))
    mixed = _comparable(dcma_14_assess(_with_unrelated(current), baseline_data=baseline))
    assert alone['bei'] == 0.5
    assert mixed['bei'] == 0.5, mixed['per_check']['DCMA-14-BEI']['message']
    # the one thing that may differ is how the baseline project was found
    for block in (alone, mixed):
        block.pop('baseline_project_match')
    assert mixed == alone


def test_the_whole_validator_report_is_invariant_too():
    """The same invariant one level up: the report for P, its nine logic-health
    checks, its counts and its embedded DCMA block (BEI 1 / 2 = 0.5, section
    3.1.2.4) are the same whether or not project U rides along in the export
    and project R in the baseline. Before the fix the embedded BEI read
    1 / 5 = 0.2."""
    current = _p_with_a_third_activity()
    baseline, clean_baseline = _baselines()

    def _stable(v):
        block = dict(v['dcma_14'])
        block.pop('baseline_project_match', None)
        return {
            'project_name': v['project_name'], 'data_date': v['data_date'],
            'counts': (v['total_activities'], v['complete'], v['in_progress'],
                       v['not_started'], v['incomplete']),
            'overall': (v['overall_score'], v['overall_rating']),
            'checks': v['checks'],
            'critical_path': [a['task_code'] for a in v['critical_path_activities']],
            'dcma_14': block,
        }

    alone = _stable(_validate(current, baseline_data=clean_baseline))
    mixed = _stable(_validate(_with_unrelated(current), baseline_data=baseline))
    assert alone['project_name'] == 'P' and alone['counts'][0] == 3
    assert alone['dcma_14']['bei'] == 0.5
    assert mixed['dcma_14']['bei'] == 0.5
    assert mixed == alone
