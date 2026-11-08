"""DCMA phase 3 (8 November 2026): #12, the Critical Path Test, run as the
pamphlet describes it (critical_path_test.py, definition #12).

The schedule is recalculated by CPP's CPM engine as filed and again with 600
working days added to the test activity (the unfinished ordinary activity on
the completion's driving path nearest the data date); the completion must move
by the delay. Without the engine the test is not run and #12 is decided only
where the answer is certain, as before.
"""
import os
import sys

import pytest

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, '..', 'scripts'))

import dcma14  # noqa: E402
from dcma14 import dcma_14_assess  # noqa: E402
from xer_parser import parse_xer  # noqa: E402

FX = os.path.join(SCRIPT_DIR, 'fixtures', 'dcma_parity')

from critical_path_test import can_run  # noqa: E402

# The test runs where CPP's CPM engine imports and this copy of the validator
# builds the recalculation network (the public repository does not).
HAVE_ENGINE = can_run()

needs_engine = pytest.mark.skipif(not HAVE_ENGINE, reason='the test cannot be run in this copy')


def _twelve(name):
    pc = dcma_14_assess(parse_xer(os.path.join(FX, name)))['per_check']['DCMA-12-CriticalPathTest']
    return pc


@needs_engine
def test_a_logic_driven_path_carries_the_delay_to_completion():
    pc = _twelve('p10_late_no_baseline.xer')
    assert pc['counts']['status'] == 'PASS', pc['message']
    det = pc['details']
    assert det['test_run'] is True
    assert det['test_activity'] == 'R1'
    assert det['delay_days'] == 600
    assert abs(det['slip_days'] - 600) <= 1
    assert det['driving_path'][-1] == 'F'


@needs_engine
def test_a_mandatory_start_part_way_along_stops_the_delay():
    pc = _twelve('p22_mandatory_mid_path.xer')
    assert pc['counts']['status'] == 'FAIL', pc['message']
    assert pc['details']['test_activity'] == 'A1'
    assert pc['details']['slip_days'] < 599
    assert 'moved the completion activity F by only' in pc['message']
    # where it is lost, and what holds it: the Mandatory Start, not the
    # predecessor that carried the whole delay to it
    assert 'first lost at A2' in pc['message']
    assert 'its Mandatory Start of 2026-06-08 08:00 holds it' in pc['message']


def test_the_certain_failures_need_no_recalculation():
    # a cycle and a pinned completion fail with or without the engine
    assert _twelve('p4_cycle.xer')['counts']['status'] == 'FAIL'
    assert _twelve('p5_mandatory.xer')['counts']['status'] == 'FAIL'


def test_a_finished_completion_is_not_tested():
    pc = _twelve('p7_as_built.xer')
    assert pc['counts']['status'] == 'NOT SCORED'
    assert 'complete' in pc['message']


def test_without_the_engine_the_test_is_not_run_and_says_so(monkeypatch):
    # A copy without cpm.py (the public repository) cannot recalculate: #12
    # falls back to the certain cases and names why the test did not run.
    monkeypatch.setitem(sys.modules, 'cpm', None)
    pc = _twelve('p10_late_no_baseline.xer')
    assert pc['counts']['status'] == 'NOT SCORED'
    assert pc['details'].get('test_run') is False
    assert 'CPM engine is not available' in pc['details'].get('test_not_run_reason', '')
    # and a pinned completion still fails
    assert _twelve('p5_mandatory.xer')['counts']['status'] == 'FAIL'


def test_a_copy_that_cannot_build_the_network_does_not_run_the_test(monkeypatch):
    # The public repository's cp_validator has no driver-chain network: there
    # the test is not run even with the public engine beside it, and says so
    # (8-Nov-26: its CI read 'the network could not be built (AttributeError)').
    # A stand-in engine, so the engine is not what stops the test here.
    import types
    stub = types.ModuleType('cpm')
    stub.compute_cpm = lambda *a, **k: {}
    monkeypatch.setitem(sys.modules, 'cpm', stub)
    import cp_validator
    monkeypatch.delattr(cp_validator, '_driver_chain_network', raising=False)
    pc = _twelve('p10_late_no_baseline.xer')
    assert pc['counts']['status'] == 'NOT SCORED'
    assert pc['details'].get('test_run') is False
    assert 'does not build the network' in pc['details'].get('test_not_run_reason', '')


@needs_engine
def test_the_completion_itself_is_never_the_test_activity():
    # Only the completion is unfinished: there is no critical task to delay.
    import copy
    data = parse_xer(os.path.join(FX, 'p10_late_no_baseline.xer'))
    data = copy.deepcopy(data)
    for t in data['tables']['TASK']['records']:
        if t.get('task_code') == 'R1':
            t['status_code'] = 'TK_Complete'
            t['act_start_date'] = '2026-05-25 08:00'
            t['act_end_date'] = '2026-05-29 16:00'
            t['remain_drtn_hr_cnt'] = '0'
    pc = dcma_14_assess(data)['per_check']['DCMA-12-CriticalPathTest']
    assert pc['counts']['status'] == 'NOT SCORED', pc['message']
    assert pc['details'].get('test_activity') is None


@needs_engine
def test_a_start_to_start_link_does_not_make_a_false_failure(tmp_path, monkeypatch):
    """A duration delay moves an activity's finish, so it cannot pass along a
    Start-to-Start link. R1 drives R2 only through its start: the test skips
    R1 and inserts the delay on R2, whose finish drives the completion, and
    passes (8-Nov-26: real schedules read 579 of 600 when R1 was used)."""
    monkeypatch.setenv('DCMA_PARITY_OUT', str(tmp_path))
    sys.path.insert(0, FX)
    import importlib
    import make_dcma_parity as m
    importlib.reload(m)
    b = m._builder('PAR-SS', m.DD)
    b.add_task('S', 'Start', 'W1', m.PAST, 0, task_type='TT_Mile', status='TK_Complete')
    b.add_task('R1', 'R1', 'W1', m.DD, 5)
    b.add_task('R2', 'R2', 'W1', m.DD, 10)
    b.add_task('F', 'Completion', 'W1', m._finish(m.DD, 10), 0, task_type='TT_FinMile')
    b.link('S', 'R1')
    b.link('R1', 'R2', pred_type='PR_SS')
    b.link('R2', 'F')
    m._write(m._build(b), 'ss.xer')
    pc = dcma_14_assess(parse_xer(os.path.join(str(tmp_path), 'ss.xer')))['per_check']['DCMA-12-CriticalPathTest']
    assert pc['counts']['status'] == 'PASS', pc['message']
    assert pc['details']['test_activity'] == 'R2'


@needs_engine
def test_a_large_network_is_recalculated_in_a_child_process_with_the_same_answer(monkeypatch):
    """Above IN_PROCESS_ACTIVITIES each recalculation runs in a child process
    that can be stopped at the time limit; the answer is the one the engine
    gives in process (8-Nov-26: twelve real schedules of 734 to 2,938
    activities read the same both ways)."""
    import critical_path_test as cpt
    monkeypatch.setattr(cpt, 'IN_PROCESS_ACTIVITIES', 10 ** 9)
    here = _twelve('p10_late_no_baseline.xer')
    monkeypatch.setattr(cpt, 'IN_PROCESS_ACTIVITIES', 0)
    child = _twelve('p10_late_no_baseline.xer')
    assert child['counts']['status'] == here['counts']['status'] == 'PASS'
    assert child['message'] == here['message']
    assert child['details'] == here['details']


@needs_engine
def test_a_recalculation_that_does_not_finish_in_time_is_stopped(monkeypatch):
    """A limit read after the run cannot stop it (a 3,000-activity synthetic
    file's as-filed run took 112 seconds): the child is stopped at the limit
    and #12 says the test was not run, and why."""
    import time
    import critical_path_test as cpt
    monkeypatch.setattr(cpt, 'IN_PROCESS_ACTIVITIES', 0)
    monkeypatch.setattr(cpt, 'BASE_RUN_SECONDS_LIMIT', 1.0)
    monkeypatch.setattr(cpt, '_CHILD_CODE', 'import time' + chr(10) + 'time.sleep(60)' + chr(10) + cpt._CHILD_CODE)
    t0 = time.time()
    pc = _twelve('p10_late_no_baseline.xer')
    assert time.time() - t0 < 15
    assert pc['counts']['status'] == 'NOT SCORED'
    assert pc['details'].get('test_run') is False
    assert 'did not finish within 1 seconds' in pc['details'].get('test_not_run_reason', '')
