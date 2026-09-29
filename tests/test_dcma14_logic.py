#!/usr/bin/env python3
"""DCMA-14 #1 (Logic) counts the remaining work, and excuses a milestone only
where it starts or ends the network.

Run with: python tests/test_dcma14_logic.py

DCMA-14 #1 is the share of activities missing a predecessor or a successor.
It ran over every work activity, completed ones included, so on an update
well into a job the completed work, whose logic no longer drives anything,
diluted the percentage. It also excused milestones by type: every start
milestone from needing a predecessor, and every finish milestone from needing
a successor or a predecessor, whatever its date. A milestone in the middle of
the network that leads from nothing, or to nothing, is the dangling logic
this check exists to find, and a finish milestone tied to nothing at all was
never counted.

The check now counts incomplete activities only. A start milestone with no
predecessor is excused only at or before the earliest start of all the work,
where it starts the network; a finish milestone with no successor only at or
after the latest finish of the remaining work, where it ends it. Each activity
is placed by its actual date, else its early date, else its planned date.
Completed work counts in placing the network's start, never its finish, so an
update statused past its data date is #9's finding and not a dangling end. A
finish milestone always needs a predecessor. The missing-predecessor and
missing-successor counts are reported separately; the graded value is still
their union, the rate the threshold is stated against.

Four tests are mutation guards rather than defect fixes: each pins a rule of
the check that every other test still passed without, and names the mutant
it kills.

The fixture is synthetic: a start milestone, two five-day activities and a
finish milestone, tied finish to start on a five-day calendar.
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


def _schedule(tasks, preds, data_date=DATA_DATE):
    proj = {
        'proj_id': 'P1', 'proj_short_name': 'TEST',
        'last_recalc_date': data_date,
        'plan_end_date': '2026-05-15 16:00',
        'scd_end_date': '2026-05-15 16:00',
    }
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


def _chain():
    """Start milestone → A10 → A20 → finish milestone, all FS, no lags."""
    tasks = [
        _task('T0', 'A00', 'Start', 'TT_Mile', tf='0',
              start='2026-04-27 08:00', end='2026-04-27 08:00',
              remain='0', target='0'),
        _task('T1', 'A10', 'Alpha',
              start='2026-04-27 08:00', end='2026-05-01 16:00'),
        _task('T2', 'A20', 'Bravo',
              start='2026-05-04 08:00', end='2026-05-08 16:00'),
        _task('T3', 'A30', 'Finish', 'TT_FinMile', tf='0',
              start='2026-05-11 08:00', end='2026-05-11 08:00',
              remain='0', target='0'),
    ]
    preds = [
        {'task_id': 'T1', 'pred_task_id': 'T0', 'pred_type': 'PR_FS', 'lag_hr_cnt': '0'},
        {'task_id': 'T2', 'pred_task_id': 'T1', 'pred_type': 'PR_FS', 'lag_hr_cnt': '0'},
        {'task_id': 'T3', 'pred_task_id': 'T2', 'pred_type': 'PR_FS', 'lag_hr_cnt': '0'},
    ]
    return tasks, preds


# ─────────────────────────────────────────────────────────────────────
# #1 Logic
# ─────────────────────────────────────────────────────────────────────

def test_logic_measures_incomplete_activities_only():
    """Completed work must not dilute the missing-logic percentage.

    DEFECT: the check ran over every work task including TK_Complete ones, so
    on an update well into a job the historic work sat in the denominator
    beside the remaining work. Here four completed activities with no logic
    at all are added: they must not appear in the denominator.
    """
    tasks, preds = _chain()
    # The start milestone has happened, as it must have if work is complete:
    # a completed activity cannot precede the project start milestone, and a
    # completed activity cannot finish after the status date either.
    for t in tasks:
        if t['task_code'] == 'A00':
            t['status_code'] = 'TK_Complete'
            t['target_start_date'] = t['target_end_date'] = '2026-03-02 08:00'
            t['early_start_date'] = t['early_end_date'] = '2026-03-02 08:00'
            t['act_start_date'] = t['act_end_date'] = '2026-03-02 08:00'
    for i in range(4):
        tasks.append(_task(f'TC{i}', f'C{i}', f'Done {i}', status='TK_Complete',
                           tf='0', start='2026-03-03 08:00', end='2026-03-06 16:00',
                           act_start='2026-03-03 08:00', act_end='2026-03-06 16:00',
                           remain='0'))
    result = dcma_14_assess(_schedule(tasks, preds), profile='commercial')
    det = result['per_check']['DCMA-01-Logic']['details']
    assert det['denominator'] == 3, (
        f'denominator must be the 3 incomplete activities, got '
        f'{det["denominator"]} (completed work was being counted: there are 8 '
        f'work tasks in this fixture, 5 of them complete and 4 of those with no '
        f'logic at all)')
    assert det['missing_count'] == 0, det
    assert result['per_check']['DCMA-01-Logic']['severity'] == 'PASS'


def test_logic_flags_a_midnetwork_start_milestone_with_no_predecessor():
    """Milestones are exempted by POSITION, not by task_type.

    DEFECT: every TT_Mile was exempted from the predecessor test and every
    TT_FinMile from the successor test, regardless of where it sat. Here a
    start milestone is dropped into the middle of the network with no driver:
    it must be flagged, while the genuine start anchor at the network's
    earliest start stays exempt.
    """
    tasks, preds = _chain()
    tasks.append(_task('TM', 'M50', 'Mid-network milestone', 'TT_Mile',
                       tf='0', start='2026-05-06 08:00', end='2026-05-06 08:00',
                       remain='0', target='0'))
    preds.append({'task_id': 'T3', 'pred_task_id': 'TM',
                  'pred_type': 'PR_FS', 'lag_hr_cnt': '0'})   # has a successor
    result = dcma_14_assess(_schedule(tasks, preds), profile='commercial')
    det = result['per_check']['DCMA-01-Logic']['details']
    assert 'M50' in det['missing_pred'], (
        f'a start milestone sitting mid-network with no predecessor is a '
        f'dangling start and must be flagged; missing_pred={det["missing_pred"]}')
    assert 'A00' not in det['missing_pred'], (
        'the real start anchor, at the network earliest start, stays exempt')


def test_logic_reports_predecessor_and_successor_rates_separately():
    """Both sub-rates are disclosed, not just the OR-union.

    DEFECT: a single union percentage was reported, so a reader could not tell
    whether a failure came from dangling starts or dangling ends. The graded
    value stays the union rate — that is the quantity the published ≤5% is
    stated against.
    """
    tasks, preds = _chain()
    tasks.append(_task('TX', 'X10', 'No successor', start='2026-05-04 08:00',
                       end='2026-05-05 16:00'))
    preds.append({'task_id': 'TX', 'pred_task_id': 'T1',
                  'pred_type': 'PR_FS', 'lag_hr_cnt': '0'})
    result = dcma_14_assess(_schedule(tasks, preds), profile='commercial')
    det = result['per_check']['DCMA-01-Logic']['details']
    assert det['missing_pred_count'] == 0, det
    assert det['missing_succ_count'] == 1, det
    assert 'missing_pred_pct' in det and 'missing_succ_pct' in det
    msg = result['per_check']['DCMA-01-Logic']['message']
    assert 'missing a predecessor' in msg and 'missing a successor' in msg


def test_finish_milestone_requires_predecessor():
    """A finish milestone with no predecessor must be caught by DCMA #1.

    DEFECT: every TT_FinMile was exempted from the predecessor test as well as
    the successor test, so a finish milestone tied to nothing at all was never
    counted. A finish milestone is the end of a chain and must be driven by a
    predecessor; only a start milestone at the network's start may lack one.
    """
    tasks, preds = _chain()
    # A second finish milestone hung off nothing at all.
    tasks.append(_task('T9', 'A99', 'Dangling finish', 'TT_FinMile', tf='0',
                       start='2026-05-11 08:00', end='2026-05-11 08:00',
                       remain='0', target='0'))
    result = dcma_14_assess(_schedule(tasks, preds), profile='commercial')
    logic = result['per_check']['DCMA-01-Logic']
    assert logic['value'] > 0, (
        'a TT_FinMile with no predecessor is a dangling activity and must be '
        'counted by DCMA #1; got value %s' % logic['value'])
    assert logic['severity'] != 'PASS', (
        'DCMA #1 must not PASS while a finish milestone dangles; got %s'
        % logic['severity'])


def test_logic_takes_the_network_start_from_all_the_work():
    """The network starts where the first activity started, completed work
    included, not where the remaining work starts.

    MUTANT (2026-09-29): taking the start anchor over the incomplete activities
    alone passed every other test. It excuses a start milestone with no
    predecessor that opens the REMAINING work, as if it started the project.
    Here the project started in March, and a milestone that resumes the work
    has no predecessor: it must be counted.

    The finish anchor is taken over the remaining work instead; see
    test_logic_takes_the_network_finish_from_the_remaining_work.
    """
    tasks, preds = _chain()
    for t in tasks:
        if t['task_code'] == 'A00':
            t['status_code'] = 'TK_Complete'
            t['target_start_date'] = t['target_end_date'] = '2026-03-02 08:00'
            t['early_start_date'] = t['early_end_date'] = '2026-03-02 08:00'
            t['act_start_date'] = t['act_end_date'] = '2026-03-02 08:00'
    # Opens the remaining work, tied forward only.
    tasks.append(_task('TR', 'R00', 'Resume works', 'TT_Mile', tf='0',
                       start='2026-04-27 08:00', end='2026-04-27 08:00',
                       remain='0', target='0'))
    preds.append({'task_id': 'T1', 'pred_task_id': 'TR',
                  'pred_type': 'PR_FS', 'lag_hr_cnt': '0'})
    result = dcma_14_assess(_schedule(tasks, preds), profile='commercial')
    det = result['per_check']['DCMA-01-Logic']['details']
    assert det['missing_pred'] == ['R00'], (
        f'the network started in March, so a start milestone that opens the '
        f'remaining work with no predecessor is a dangling start; '
        f'missing_pred={det["missing_pred"]}')


def test_logic_does_not_excuse_a_milestone_it_cannot_place():
    """A milestone the file gives no date is not excused on either side.

    MUTANT (2026-09-29): both exemptions need a date, but reading a missing
    date as at the network's start or finish passed every other test. That
    excuses exactly the milestones whose position cannot be read. Here a start
    milestone and a finish milestone carry no dates at all, each tied on one
    side only: each must be counted on the other.
    """
    tasks, preds = _chain()
    tasks.append(_task('TU', 'U10', 'Undated start', 'TT_Mile', tf='0',
                       start='', end='', remain='0', target='0'))
    tasks.append(_task('TV', 'U20', 'Undated finish', 'TT_FinMile', tf='0',
                       start='', end='', remain='0', target='0'))
    preds.append({'task_id': 'T1', 'pred_task_id': 'TU',
                  'pred_type': 'PR_FS', 'lag_hr_cnt': '0'})   # a successor only
    preds.append({'task_id': 'TV', 'pred_task_id': 'T2',
                  'pred_type': 'PR_FS', 'lag_hr_cnt': '0'})   # a predecessor only
    result = dcma_14_assess(_schedule(tasks, preds), profile='commercial')
    det = result['per_check']['DCMA-01-Logic']['details']
    assert det['missing_pred'] == ['U10'], det
    assert det['missing_succ'] == ['U20'], det


def test_logic_counts_an_activity_missing_both_once():
    """An activity with neither a predecessor nor a successor is one activity
    missing logic, not two.

    MUTANT (2026-09-29): in every other test each activity misses one side
    only, so adding the two lists together instead of taking their union
    passed, and an orphan would count twice against the threshold.
    """
    tasks, preds = _chain()
    tasks.append(_task('TO', 'O10', 'Orphan', start='2026-05-04 08:00',
                       end='2026-05-05 16:00'))
    check = dcma_14_assess(_schedule(tasks, preds),
                           profile='commercial')['per_check']['DCMA-01-Logic']
    det = check['details']
    assert det['missing_pred'] == det['missing_succ'] == ['O10'], det
    assert (det['missing_count'], det['examples']) == (1, ['O10']), det
    assert check['value'] == 20.0, (
        f'one of the five incomplete activities is missing logic, 20%; got '
        f'{check["value"]}')


def test_logic_places_completed_work_by_its_actual_dates():
    """Completed work is placed by its actual dates, not by the early dates a
    P6 export stamps on it.

    MUTANT (2026-09-29): reading the early start before the actual start passed
    every other test. A P6 export stamps a completed activity's early dates at
    the data date, so the network would seem to start there, and a start
    milestone at the data date with no predecessor would be excused. Here the
    start milestone was finished in March: the network starts there.

    _task_finish reads in the same order, but only the remaining work feeds
    the finish anchor and the finish test, and an incomplete activity carries
    no actual finish, so the order does not arise there.
    """
    data_date = '2026-04-27 08:00'
    tasks, preds = _chain()
    for t in tasks:
        if t['task_code'] == 'A00':
            t['status_code'] = 'TK_Complete'
            t['act_start_date'] = t['act_end_date'] = '2026-03-02 08:00'
            t['target_start_date'] = t['target_end_date'] = '2026-03-02 08:00'
            t['early_start_date'] = t['early_end_date'] = data_date
    tasks.append(_task('TR', 'R00', 'Resume works', 'TT_Mile', tf='0',
                       start=data_date, end=data_date, remain='0', target='0'))
    preds.append({'task_id': 'T1', 'pred_task_id': 'TR',
                  'pred_type': 'PR_FS', 'lag_hr_cnt': '0'})
    result = dcma_14_assess(_schedule(tasks, preds, data_date=data_date),
                            profile='commercial')
    det = result['per_check']['DCMA-01-Logic']['details']
    assert det['missing_pred'] == ['R00'], (
        f'the start milestone finished in March, so the milestone that resumes '
        f'the work at the data date is a dangling start; '
        f'missing_pred={det["missing_pred"]}')


def test_logic_takes_the_network_finish_from_the_remaining_work():
    """The network finishes where the remaining work finishes. A completed
    activity's finish never moves it.

    DEFECT (2026-09-29): the finish anchor was taken over the whole work set,
    completed activities included. On a schedule rescheduled to its data date
    that changes nothing, because no completed activity finishes after the
    remaining work. On an update statused past its data date it does: an
    actual finish later than the remaining work's early finish (#9 reports
    it) moved the network finish past the completion milestone, and the
    milestone was counted as a dangling end. Here the data date is 10 April,
    Alpha finished on the 22nd, and the remaining work still runs to the
    17th: the completion milestone is where the network finishes, and #9,
    not #1, holds the finding.
    """
    data_date = '2026-04-10 08:00'
    tasks, preds = _chain()
    for t in tasks:
        if t['task_code'] == 'A00':
            t.update(status_code='TK_Complete', act_start_date='2026-03-02 08:00',
                     act_end_date='2026-03-02 08:00')
        if t['task_code'] == 'A10':
            t.update(status_code='TK_Complete', remain_drtn_hr_cnt='0',
                     act_start_date='2026-04-13 08:00', act_end_date='2026-04-22 16:00')
        if t['task_code'] == 'A20':
            t.update(early_start_date='2026-04-13 08:00', early_end_date='2026-04-17 16:00')
        if t['task_code'] == 'A30':
            t.update(early_start_date='2026-04-17 16:00', early_end_date='2026-04-17 16:00')
    result = dcma_14_assess(_schedule(tasks, preds, data_date=data_date),
                            profile='commercial')
    det = result['per_check']['DCMA-01-Logic']['details']
    assert det['missing_succ'] == [], (
        f'the completion milestone ends the remaining work, so an actual finish '
        f'past the data date must not make it a dangling end; '
        f'missing_succ={det["missing_succ"]}')
    assert result['per_check']['DCMA-09-InvalidDates']['severity'] == 'BLOCK', (
        'the actual finish after the data date is #9\'s finding')


def test_logic_details_carry_every_key_when_no_work_is_incomplete():
    """A schedule with no incomplete work passes with the same details as any
    other: every count and rate at zero and both lists empty.

    DEFECT (2026-09-29): the vacuous pass returned the counts only, so a caller
    reading `missing_pred` or `missing_succ` on a finished as-built schedule
    got a KeyError.
    """
    tasks, preds = _chain()
    usual = set(dcma_14_assess(_schedule(tasks, preds), profile='commercial')
                ['per_check']['DCMA-01-Logic']['details'])
    for t in tasks:
        t['status_code'] = 'TK_Complete'
        t['act_start_date'] = t['early_start_date']
        t['act_end_date'] = t['early_end_date']
        t['remain_drtn_hr_cnt'] = '0'
    check = dcma_14_assess(_schedule(tasks, preds, data_date='2026-05-12 00:00'),
                           profile='commercial')['per_check']['DCMA-01-Logic']
    det = check['details']
    assert (check['severity'], check['value']) == ('PASS', 0.0), check
    assert set(det) == usual, f'missing keys: {sorted(usual - set(det))}'
    assert det['missing_pred'] == det['missing_succ'] == det['examples'] == []
    assert (det['missing_count'], det['denominator']) == (0, 0), det
    assert det['missing_pred_pct'] == det['missing_succ_pct'] == 0.0, det


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
