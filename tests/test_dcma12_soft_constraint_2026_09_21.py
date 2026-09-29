"""DCMA check 12, Critical Path Test: a soft Start On / Finish On date is not
an immovable finish (2026-09-21).

DCMA-EA PAM 200.1 (October 2012), section 4.12 "Critical Path Test": an
intentional slip is introduced into the schedule, and the schedule passes if
the project completion date (or other milestone) shows "a negative total float
number or a revised Early Finish date" in direct proportion to the slip. The
test fails where completion does not respond, which the pamphlet attributes to
broken logic.

This module cannot run the test (no CPM recalculation), so it reports NOT
ASSESSED, except for one structural shortcut: a project finish that cannot
move at all. That shortcut read cp_validator's whole HARD_CONSTRAINTS set, and
the set holds two different things:

  CS_MANDSTART / CS_MANDFIN  Mandatory Start / Finish. P6 imposes the early and
                             late dates whatever the logic says.
  CS_MSO / CS_MEO            Start On / Finish On. P6 can delay the early date
                             past the imposed one; logic is protected, and the
                             lateness shows as negative float.

So a schedule whose completion milestone carries Finish On was told "inserting
a 600-day delay upstream cannot move the completion date", which is false, and
was BLOCKed for it. A Finish On completion is exactly the case section 4.12
describes as a PASS: the early finish moves and the float goes negative.

P6 exports routinely store Finish On and Start On activities with an early
date later than the constraint date, and never a mandatory one. A completion
held by a Start On or Finish On now reads NOT ASSESSED; one with no
predecessor still fails, on that rule and for that stated reason.

The three soft-constraint tests fail against the shortcut they replace. The
mandatory, unconstrained and engine tests pass before and after: they hold the
half of the shortcut that stays, and the premise the change rests on. The
engine test needs cpp-cpm-engine's `cpm` module on the path and is skipped
without it.
"""
import os
import sys
from datetime import date

import pytest

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, '..', 'scripts'))

from dcma14 import dcma_14_assess  # noqa: E402

_TASK_FIELDS = [
    'task_id', 'proj_id', 'task_code', 'task_name', 'task_type', 'status_code',
    'total_float_hr_cnt', 'clndr_id', 'cstr_type', 'cstr_date', 'cstr_type2',
    'target_start_date', 'target_end_date', 'early_start_date', 'early_end_date',
    'act_start_date', 'act_end_date', 'remain_drtn_hr_cnt', 'target_drtn_hr_cnt',
]


def _task(tid, code, ttype, start, end, cstr='', cstr_date='', hours='40'):
    return {
        'task_id': tid, 'proj_id': 'P1', 'task_code': code, 'task_name': code,
        'task_type': ttype, 'status_code': 'TK_NotStart',
        'total_float_hr_cnt': '0', 'clndr_id': 'C1',
        'cstr_type': cstr, 'cstr_date': cstr_date, 'cstr_type2': '',
        'target_start_date': start, 'target_end_date': end,
        'early_start_date': start, 'early_end_date': end,
        'act_start_date': '', 'act_end_date': '',
        'remain_drtn_hr_cnt': hours, 'target_drtn_hr_cnt': hours,
    }


def _schedule(finish_cstr):
    """A (five days) FS -> Z, the completion milestone, which carries
    `finish_cstr`. Status date Friday 24 April 2026."""
    tasks = [
        _task('T1', 'A', 'TT_Task', '2026-04-27 08:00', '2026-05-01 17:00'),
        _task('T2', 'Z', 'TT_FinMile', '2026-05-01 17:00', '2026-05-01 17:00',
              cstr=finish_cstr, cstr_date='2026-05-01 17:00' if finish_cstr else '',
              hours='0'),
    ]
    proj = {'proj_id': 'P1', 'proj_short_name': 'TEST',
            'last_recalc_date': '2026-04-24 08:00', 'clndr_id': 'C1'}
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
                     'records': [{'task_id': 'T2', 'pred_task_id': 'T1',
                                  'pred_type': 'PR_FS', 'lag_hr_cnt': '0'}]},
    }}


def _twelve(finish_cstr):
    result = dcma_14_assess(_schedule(finish_cstr), profile='commercial')
    return result, result['per_check']['DCMA-12-CriticalPathTest']


def test_a_finish_on_completion_is_not_a_structural_failure():
    """PAM 200.1 section 4.12 passes a schedule whose completion shows negative
    float or a revised early finish in proportion to the inserted slip. Under
    Finish On (CS_MEO) P6 does both: the early finish moves with the logic and
    the float goes negative against the imposed date. It cannot be failed
    without running the test, and this module does not run it.

    The old shortcut returned BLOCK with "pinned by CS_MEO, so inserting a
    600-day delay upstream cannot move the completion date".
    """
    result, twelve = _twelve('CS_MEO')
    assert twelve['severity'] == 'INFO', twelve
    assert 'DCMA-12-CriticalPathTest' in result['dcma_not_assessed']
    assert 'NOT ASSESSED' in twelve['message']
    assert 'cannot move' not in twelve['message'], twelve['message']
    assert twelve['details']['finish_constraints'] == []
    assert twelve['details']['finish_soft_constraints'] == ['CS_MEO']
    assert twelve['details']['assessed'] is False
    # the reader is told the constraint was seen and why it decides nothing
    assert 'CS_MEO' in twelve['message'] and 'Finish On' in twelve['message']


def test_a_start_on_completion_is_not_a_structural_failure_either():
    """Section 4.12 again, for Start On (CS_MSO): P6 can delay the early start
    past the imposed date, so an upstream slip still reaches completion."""
    result, twelve = _twelve('CS_MSO')
    assert twelve['severity'] == 'INFO', twelve
    assert twelve['details']['finish_soft_constraints'] == ['CS_MSO']
    assert 'Start On' in twelve['message']


def test_a_start_on_completion_with_no_predecessor_fails_for_that_reason():
    """Section 4.12 attributes a failure to missing predecessors or successors
    where they are needed. A completion activity with no predecessor cannot be
    reached by any upstream slip, and that rule is untouched. What changes is
    the stated reason: the old shortcut ran first and said "pinned by CS_MSO",
    which is not why the test fails.
    """
    data = _schedule('CS_MSO')
    data['tables']['TASKPRED']['records'] = []
    twelve = dcma_14_assess(data, profile='commercial')[
        'per_check']['DCMA-12-CriticalPathTest']
    assert twelve['severity'] == 'BLOCK'
    assert 'has no predecessor' in twelve['message'], twelve['message']
    assert 'pinned by' not in twelve['message']
    assert twelve['details']['no_predecessor'] is True
    assert twelve['details']['finish_soft_constraints'] == ['CS_MSO']


def test_a_mandatory_finish_still_fails_structurally():
    """Section 4.12 fails a schedule whose completion does not respond to the
    inserted slip. Mandatory Start and Mandatory Finish impose the early and
    late dates whatever the logic says, so that completion cannot respond, and
    the failure is decidable from the file. This half of the shortcut stays.
    """
    for cstr in ('CS_MANDFIN', 'CS_MANDSTART'):
        result, twelve = _twelve(cstr)
        assert twelve['severity'] == 'BLOCK', (cstr, twelve)
        assert twelve['details']['finish_constraints'] == [cstr]
        assert 'DCMA-12-CriticalPathTest' not in result['dcma_not_assessed']
        assert 'cannot move the completion date' in twelve['message']


def test_an_unconstrained_completion_reads_as_before():
    """No constraint, logic-driven: NOT ASSESSED, and no soft constraint is
    named because there is none."""
    result, twelve = _twelve('')
    assert twelve['severity'] == 'INFO'
    assert twelve['details'].get('finish_soft_constraints', []) == []
    assert 'Finish On' not in twelve['message']


def test_the_engine_moves_a_finish_on_completion_by_the_inserted_delay():
    """The premise, run rather than asserted: section 4.12's own test on the
    CPM engine. A (1 working day, Monday 5 January 2026) FS -> Z, a
    finish milestone with Finish On at the day A finishes. Stretch A to 601
    working days: completion must move out by 600 working days, which on a
    Monday-to-Friday calendar with no holidays is 120 weeks = 840 calendar
    days. "Cannot move the completion date" is false for Finish On.
    """
    cpm = pytest.importorskip('cpm', reason="cpp-cpm-engine's cpm module is not on the path")
    compute_cpm = cpm.compute_cpm
    cal = {'C1': {'work_days': [1, 2, 3, 4, 5], 'hours_per_day': 8, 'holidays': []}}

    def _finish(a_days):
        acts = [
            {'code': 'A', 'duration_days': a_days, 'clndr_id': 'C1'},
            {'code': 'Z', 'duration_days': 0, 'clndr_id': 'C1',
             'task_type': 'TT_FinMile',
             'constraint': {'type': 'CS_MEO', 'date': '2026-01-05'}},
        ]
        rels = [{'from_code': 'A', 'to_code': 'Z', 'type': 'FS', 'lag_days': 0}]
        out = compute_cpm(acts, rels, data_date='2026-01-05', cal_map=cal)
        return date.fromisoformat(out['project_finish'][:10])

    assert (_finish(601) - _finish(1)).days == 840
