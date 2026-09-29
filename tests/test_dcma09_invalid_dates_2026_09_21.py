"""DCMA check 9, Invalid Dates, against its published definition (2026-09-21).

DCMA-EA PAM 200.1 (October 2012), section 4.9 "Invalid Dates": incomplete
tasks with a forecast start or finish date prior to the status date, and tasks
with an actual start or finish date beyond it, are invalid; a forecast date on
or after the status date is valid, an actual date on or before it is valid, and
"There should not be any invalid dates in the schedule." Section 4.11 names the
forecast finish: it is the early finish date.

Before this file the check never read an early date. It tested the PLANNED
finish (target_end_date), so a stale forecast sitting before the data date
passed, while a properly updated late activity failed because its planned
finish was historical, which is what check 11 (Missed Tasks) measures. It also
counted one issue per FIELD and reported the total as a number of activities.
Read against real exports, open activities were flagged on a historical
planned finish while not-started activities with an early start before the
data date, and in-progress ones with an early finish before it, were never
looked at.

Seven tests fail against the check they replace. The other two
(test_completed_work_has_no_forecast_left_to_assess and
test_dates_on_the_status_date_are_valid_on_both_sides) pass before and after:
they hold the two edges an over-correction would break.
"""
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, '..', 'scripts'))

from dcma14 import dcma_14_assess  # noqa: E402

# Monday. Every date below is read against this status date.
DATA_DATE = '2026-01-12 08:00'

_TASK_FIELDS = [
    'task_id', 'proj_id', 'task_code', 'task_name', 'task_type', 'status_code',
    'total_float_hr_cnt', 'clndr_id', 'cstr_type', 'cstr_type2',
    'target_start_date', 'target_end_date', 'early_start_date', 'early_end_date',
    'act_start_date', 'act_end_date', 'remain_drtn_hr_cnt', 'target_drtn_hr_cnt',
]


def _task(code, status='TK_NotStart', early=('2026-01-19 08:00', '2026-01-23 17:00'),
          planned=('2026-01-19 08:00', '2026-01-23 17:00'), actual=('', ''),
          remain='40'):
    """One TASK row shaped like a P6 export. `early`, `planned` and `actual`
    are (start, finish) pairs."""
    return {
        'task_id': 'T' + code, 'proj_id': 'P1', 'task_code': code,
        'task_name': 'Activity ' + code, 'task_type': 'TT_Task',
        'status_code': status, 'total_float_hr_cnt': '0', 'clndr_id': 'C1',
        'cstr_type': '', 'cstr_type2': '',
        'target_start_date': planned[0], 'target_end_date': planned[1],
        'early_start_date': early[0], 'early_end_date': early[1],
        'act_start_date': actual[0], 'act_end_date': actual[1],
        'remain_drtn_hr_cnt': remain, 'target_drtn_hr_cnt': '40',
    }


def _schedule(tasks):
    proj = {'proj_id': 'P1', 'proj_short_name': 'TEST',
            'last_recalc_date': DATA_DATE, 'clndr_id': 'C1'}
    return {'tables': {
        'PROJECT': {'fields': list(proj), 'records': [proj]},
        'CALENDAR': {
            'fields': ['clndr_id', 'clndr_name', 'day_hr_cnt', 'week_hr_cnt',
                       'default_flag', 'clndr_type', 'clndr_data'],
            'records': [{'clndr_id': 'C1', 'clndr_name': '5-Day', 'day_hr_cnt': '8',
                         'week_hr_cnt': '40', 'default_flag': 'Y',
                         'clndr_type': 'CA_Base', 'clndr_data': ''}]},
        'TASK': {'fields': list(_TASK_FIELDS), 'records': tasks},
        'TASKPRED': {'fields': ['task_id', 'pred_task_id', 'pred_type', 'lag_hr_cnt'],
                     'records': []},
    }}


def _nine(tasks):
    return dcma_14_assess(_schedule(tasks), profile='commercial')[
        'per_check']['DCMA-09-InvalidDates']


def test_a_forecast_before_the_status_date_is_invalid_whatever_the_planned_finish():
    """PAM 200.1 section 4.9: an incomplete task with a forecast start/finish
    date prior to the status date is invalid.

    A has not started. Its early start and early finish are Monday 5 January,
    a week before the 12 January status date, so nobody rescheduled it. Its
    planned finish is 30 January, in the future. The old check read only the
    planned finish and passed it with a count of 0.
    """
    nine = _nine([
        _task('A', early=('2026-01-05 08:00', '2026-01-05 17:00'),
              planned=('2026-01-26 08:00', '2026-01-30 17:00')),
        _task('Z'),
    ])
    assert nine['severity'] == 'BLOCK', nine
    assert nine['value'] == 1
    det = nine['details']
    assert det['examples'] == ['A']
    assert det['forecast_count'] == 1 and det['actual_count'] == 0
    # both forecast dates are stale: two issues, still one activity
    assert det['issue_count'] == 2, det


def test_an_updated_late_activity_is_valid_and_its_planned_finish_is_check_11():
    """PAM 200.1 section 4.9 gives the valid case in so many words: with the
    status date at 8/1/09 "the forecast date should be on or after 8/1/09".

    A was planned to finish on 5 January and has not started. The scheduler
    did the right thing and moved its forecast to the status date: early start
    12 January 08:00, early finish 12 January 17:00. Nothing about its dates is
    invalid. That it missed its planned finish is a Missed Task, section 4.11,
    and check 11 must be the one that reports it. The old check 9 blocked the
    schedule for it.
    """
    result = dcma_14_assess(_schedule([
        _task('A', early=('2026-01-12 08:00', '2026-01-12 17:00'),
              planned=('2026-01-05 08:00', '2026-01-05 17:00')),
        _task('Z'),
    ]), profile='commercial')
    nine = result['per_check']['DCMA-09-InvalidDates']
    assert nine['severity'] == 'PASS', nine
    assert nine['value'] == 0
    eleven = result['per_check']['DCMA-11-MissedTasks']['details']
    assert eleven['still_open'] == ['A'], (
        'the historical planned finish belongs to check 11: %r' % (eleven,))


def test_one_activity_with_two_future_actuals_counts_once():
    """PAM 200.1 section 4.9 counts TASKS: a task with an actual start or
    finish date beyond the status date.

    A is complete with an actual start of 13 January and an actual finish of
    14 January, both after the 12 January status date. That is one activity
    with invalid dates. The old check reported "2 activities".
    """
    nine = _nine([
        _task('A', status='TK_Complete', remain='0',
              early=('2026-01-13 08:00', '2026-01-14 17:00'),
              actual=('2026-01-13 08:00', '2026-01-14 17:00')),
        _task('Z'),
    ])
    assert nine['severity'] == 'BLOCK'
    assert nine['value'] == 1, nine['message']
    assert nine['message'].startswith('1 activities with invalid dates'), nine['message']
    det = nine['details']
    assert det['invalid_count'] == 1
    assert det['issue_count'] == 2
    assert det['forecast_count'] == 0 and det['actual_count'] == 1
    assert det['examples'] == ['A']


def test_an_activity_with_a_forecast_and_an_actual_issue_still_counts_once():
    """One task, one count, however many of its four dates are wrong.

    A is in progress. Its actual start is 14 January, after the status date,
    and its early finish is 9 January, before it. It appears under both
    headings and once in the total.
    """
    nine = _nine([
        _task('A', status='TK_Active', remain='16',
              early=('2026-01-08 08:00', '2026-01-09 17:00'),
              actual=('2026-01-14 08:00', '')),
        _task('Z'),
    ])
    det = nine['details']
    assert det.get('issues') == ['A:act_start_date>2026-01-12',
                                 'A:early_end_date<2026-01-12'], det
    assert nine['value'] == 1
    assert det['forecast_count'] == 1 and det['actual_count'] == 1
    assert det['issue_count'] == 2


def test_started_work_is_assessed_on_its_forecast_finish_not_its_start():
    """A started activity has an actual start, not a forecast one, so section
    4.9 leaves only its forecast finish to assess.

    In-progress activities routinely carry an early start before the data
    date, because the early start of started work sits at or near its actual
    start. Reading that as a stale forecast would fail every one of them.

    A started on 5 January and forecasts its finish on 16 January: valid.
    B started on 5 January and still forecasts its finish on 9 January, three
    days before the status date: invalid.
    """
    nine = _nine([
        _task('A', status='TK_Active', remain='40',
              early=('2026-01-05 08:00', '2026-01-16 17:00'),
              actual=('2026-01-05 08:00', '')),
        _task('B', status='TK_Active', remain='8',
              early=('2026-01-05 08:00', '2026-01-09 17:00'),
              actual=('2026-01-05 08:00', '')),
    ])
    assert nine['value'] == 1, nine
    assert nine['details']['examples'] == ['B']
    assert nine['details']['issues'] == ['B:early_end_date<2026-01-12'], nine['details']


def test_completed_work_has_no_forecast_left_to_assess():
    """Section 4.9 assesses the forecast dates of INCOMPLETE tasks. A finished
    on 9 January with every date in the past; nothing about it is invalid."""
    nine = _nine([
        _task('A', status='TK_Complete', remain='0',
              early=('2026-01-05 08:00', '2026-01-09 17:00'),
              planned=('2026-01-05 08:00', '2026-01-09 17:00'),
              actual=('2026-01-05 08:00', '2026-01-09 17:00')),
        _task('Z'),
    ])
    assert nine['severity'] == 'PASS', nine
    assert nine['value'] == 0


def test_dates_on_the_status_date_are_valid_on_both_sides():
    """Section 4.9: a forecast "on or after" the status date is valid and an
    actual "on or before" it is valid, so the status date itself is valid for
    both. A finished at the status date instant; B forecasts its start at it.
    """
    nine = _nine([
        _task('A', status='TK_Complete', remain='0',
              early=('2026-01-05 08:00', '2026-01-12 08:00'),
              actual=('2026-01-05 08:00', '2026-01-12 08:00')),
        _task('B', early=('2026-01-12 08:00', '2026-01-16 17:00')),
    ])
    assert nine['severity'] == 'PASS', nine
    assert nine['value'] == 0


def test_an_activity_with_no_forecast_to_read_is_disclosed_not_counted():
    """Missing data is not a valid date and not an invalid one.

    A has not started and its export carries no early start or early finish.
    Section 4.9 cannot be applied to it, so it is left out of the count and the
    message says so. The old check never read these fields, so it had nothing
    to disclose.
    """
    nine = _nine([_task('A', early=('', '')), _task('Z')])
    assert nine['details'].get('unread_forecast') == ['A'], nine['details']
    assert nine['details']['unread_forecast_count'] == 1
    assert nine['value'] == 0 and nine['severity'] == 'PASS'
    assert ('1 incomplete activities carry no early start or finish to read, so '
            'their forecast dates were not assessed.') in nine['message'], nine['message']
    # ... and nothing is said when every forecast could be read
    clean = _nine([_task('A'), _task('Z')])
    assert clean['details']['unread_forecast_count'] == 0
    assert 'not assessed' not in clean['message']


def test_the_message_says_what_was_counted():
    """The figure is a number of activities, split by which rule each broke;
    planned finishes are not part of it."""
    nine = _nine([
        _task('A', early=('2026-01-05 08:00', '2026-01-05 17:00')),
        _task('B', status='TK_Complete', remain='0',
              early=('2026-01-13 08:00', '2026-01-14 17:00'),
              actual=('2026-01-13 08:00', '2026-01-14 17:00')),
    ])
    msg = nine['message']
    assert msg.startswith('2 activities with invalid dates (threshold ≤ 0)'), msg
    assert '1 with a forecast (early) start or finish before the status date' in msg, msg
    assert '1 with an actual start or finish after it' in msg, msg
    assert 'past-planned' not in msg, msg
    assert '#11 Missed Tasks' in msg, msg
