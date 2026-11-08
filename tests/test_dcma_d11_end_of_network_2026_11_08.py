"""D11 on a tie (8-Nov-26): the end of the network first (an activity no logic relationship leads from), then a
finish milestone, then an activity of zero original duration, else the first in the file.

Found on a real schedule: two finish milestones shared the project's finish and the first in the file fed the
second (Finish-to-Finish). File order took the first, so the Critical Path Test followed the path into a milestone
that is not the project's end, while P6's longest path ends at the second."""
from __future__ import annotations

import copy
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'scripts'))

from dcma14 import _completion_activity, dcma_14_assess  # noqa: E402
from xer_parser import parse_xer  # noqa: E402

FX = os.path.join(HERE, 'fixtures', 'dcma_parity')


def _t(tid, code, finish, task_type='TT_FinMile', dur='0'):
    return {'task_id': tid, 'task_code': code, 'task_type': task_type, 'early_end_date': finish,
            'target_drtn_hr_cnt': dur, 'status_code': 'TK_NotStart'}


def test_the_end_of_the_network_wins_a_tie_whatever_the_file_order():
    e1, e2 = _t('1', 'E1', '2029-06-13 16:00'), _t('2', 'E2', '2029-06-13 16:00')
    leads = {'1'}                                  # E1 -> E2
    assert _completion_activity([e1, e2], leads)[0]['task_code'] == 'E2'
    assert _completion_activity([e2, e1], leads)[0]['task_code'] == 'E2'


def test_without_a_link_between_them_the_old_order_stands():
    e1, e2 = _t('1', 'E1', '2029-06-13 16:00'), _t('2', 'E2', '2029-06-13 16:00')
    assert _completion_activity([e1, e2], set())[0]['task_code'] == 'E1'
    assert _completion_activity([e1, e2])[0]['task_code'] == 'E1'          # relationships not given


def test_the_end_of_the_network_comes_before_the_milestone_type():
    task = _t('1', 'T', '2029-06-13 16:00', task_type='TT_Task', dur='8')
    mile = _t('2', 'M', '2029-06-13 16:00')
    assert _completion_activity([mile, task], {'2'})[0]['task_code'] == 'T'
    assert _completion_activity([mile, task], set())[0]['task_code'] == 'M'


def test_a_later_finish_still_wins_outright():
    early = _t('1', 'A', '2029-06-12 16:00')
    late = _t('2', 'B', '2029-06-13 16:00')
    assert _completion_activity([early, late], {'2'})[0]['task_code'] == 'B'


def test_the_shared_fixture_reads_the_pinned_end_of_the_network():
    data = parse_xer(os.path.join(FX, 'p25_tied_completion.xer'))
    pc = dcma_14_assess(data)['per_check']['DCMA-12-CriticalPathTest']
    assert pc['counts']['status'] == 'FAIL', pc['message']
    assert 'E2' in pc['message'] and 'E1' not in pc['message'], pc['message']


def test_the_baseline_reads_its_own_relationships():
    # #13 with a baseline whose completion is not the current one's ID: the baseline's own completion activity is
    # read, and a tie there goes to the baseline's end of network.
    cur = copy.deepcopy(parse_xer(os.path.join(FX, 'p25_tied_completion.xer')))
    base = copy.deepcopy(cur)
    for t in base['tables']['TASK']['records']:
        if t['task_code'] in ('E1', 'E2'):
            t['task_code'] = 'B' + t['task_code']
            t['cstr_type'] = ''
            t['cstr_date'] = ''
    for t in cur['tables']['TASK']['records']:
        if t['task_code'] == 'E2':
            t['cstr_type'] = ''
            t['cstr_date'] = ''
    pc = dcma_14_assess(cur, baseline_data=base)['per_check']['DCMA-13-CPLI']
    assert 'BE2' in pc['message'], pc['message']


def test_13_reads_the_deadline_on_an_activity_tied_with_the_completion():
    # p26: the Finish On or Before sits on E1, which feeds the completion F on the same instant. F is the
    # completion (D11); the deadline on E1 is the project's: CPLI 0.5, measured as working time to its date.
    data = parse_xer(os.path.join(FX, 'p26_tied_deadline.xer'))
    pc = dcma_14_assess(data)['per_check']['DCMA-13-CPLI']
    assert pc['counts']['status'] == 'FAIL' and abs(pc['value'] - 0.5) < 1e-9, pc['message']
    assert 'on E1' in pc['message'] and 'of F' in pc['message'], pc['message']


# The review of the tie (Claude AI, 8-Nov-26).
def test_a_finished_out_of_sequence_successor_does_not_end_the_claim():
    from dcma14 import _with_successor
    f = _t('1', 'F', '2029-06-13 16:00')
    d = _t('2', 'D', '2029-06-13 16:00', task_type='TT_Task', dur='40')
    h = dict(_t('3', 'H', '2029-01-01 16:00', task_type='TT_Task', dur='8'), status_code='TK_Complete')
    by_id = {x['task_id']: x for x in (f, d, h)}
    leads = _with_successor([{'pred_task_id': '1', 'task_id': '3'}], by_id)
    assert leads == set()
    assert _completion_activity([d, f], leads)[0]['task_code'] == 'F'


def test_an_unfinished_tied_activity_comes_before_a_finished_one():
    done = dict(_t('1', 'C', '2029-06-13 16:00', task_type='TT_Task', dur='8'), status_code='TK_Complete')
    mile = _t('2', 'M', '2029-06-13 16:00')
    assert _completion_activity([done, mile], {'2'})[0]['task_code'] == 'M'


def test_13_does_not_read_a_deadline_on_a_parallel_tied_milestone():
    data = parse_xer(os.path.join(FX, 'p28_parallel_deadline.xer'))
    pc = dcma_14_assess(data)['per_check']['DCMA-13-CPLI']
    assert pc['counts']['status'] == 'NOT SCORED', pc['message']
    assert 'on M' not in pc['message'], pc['message']
