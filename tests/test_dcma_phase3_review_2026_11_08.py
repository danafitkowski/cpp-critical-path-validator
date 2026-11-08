"""DCMA #12, the Critical Path Test: the Claude AI review of the test (8-Nov-26).

Each case is fixture p22 (A1 -> A2 -> F, A2 held by a Mandatory Start) edited
in memory. The review built three wrong passes and a contradiction:

  1. a Mandatory Finish with room before it held the test activity, the test
     skipped it and the next activity passed;
  2. a move short of the delay passed on the engine's driver names alone,
     through a side path with a lead past a pinned activity (500 of 600) and
     past an expected finish that absorbed four days (596 of 600), with a
     sentence blaming calendars;
  5. every FAIL said the completion was no longer driven by the test activity
     where the engine still named it.
"""
import copy
import os
import sys

import pytest

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, '..', 'scripts'))

import dcma14  # noqa: E402
from dcma14 import dcma_14_assess  # noqa: E402
from xer_parser import parse_xer  # noqa: E402
from critical_path_test import can_run  # noqa: E402

FX = os.path.join(SCRIPT_DIR, 'fixtures', 'dcma_parity')

needs_engine = pytest.mark.skipif(not can_run(), reason='the test cannot be run in this copy')


def _p22():
    return copy.deepcopy(parse_xer(os.path.join(FX, 'p22_mandatory_mid_path.xer')))


def _task(data, code):
    return next(t for t in data['tables']['TASK']['records'] if t['task_code'] == code)


def _twelve(data):
    return dcma_14_assess(data)['per_check']['DCMA-12-CriticalPathTest']


def _raw(data, monkeypatch):
    """#12 and the test's own result dict."""
    import critical_path_test as cpt
    got = {}
    real = cpt.run

    def wrap(*a, **k):
        r = real(*a, **k)
        got.update(r)
        return r
    monkeypatch.setattr(cpt, 'run', wrap)
    return _twelve(data), got


@needs_engine
def test_a_constraint_holding_the_test_activity_fails_and_is_not_skipped(monkeypatch):
    # A1 carries a Mandatory Finish far enough out that the 600 days fit
    # before it: its finish does not move. That is the critical path held by a
    # constraint, so #12 fails on A1; trying A2 instead used to pass.
    data = _p22()
    _task(data, 'A2')['cstr_type'] = ''
    _task(data, 'A2')['cstr_date'] = ''
    _task(data, 'A1')['cstr_type'] = 'CS_MANDFIN'
    _task(data, 'A1')['cstr_date'] = '2029-06-29 16:00'
    pc, raw = _raw(data, monkeypatch)
    assert pc['counts']['status'] == 'FAIL', pc['message']
    assert raw['test_activity'] == 'A1'
    assert raw['tried'] == ['A1']
    assert 'did not move its finish: its Mandatory Finish of 2029-06-29 16:00 holds it' in pc['message']


@needs_engine
def test_a_side_path_past_a_pinned_activity_does_not_pass_on_the_calendar_rule(monkeypatch):
    # X runs from A1 into F with a 100-day lead. With A2 pinned, the delay
    # reaches F only through X, 500 of 600 days, and the engine still names A1
    # back from F. The as-filed path did not carry it (A2 did not move): FAIL
    # at A2, its Mandatory Start, not a pass blamed on calendars.
    data = _p22()
    a2 = _task(data, 'A2')
    x = dict(a2, task_id='10005', task_code='X', task_name='X', cstr_type='', cstr_date='')
    data['tables']['TASK']['records'].append(x)
    rels = data['tables']['TASKPRED']['records']
    base = dict(rels[0])
    rels.append(dict(base, task_pred_id='20004', task_id='10005', pred_task_id='10002', pred_type='PR_FS',
                     lag_hr_cnt='-800'))
    rels.append(dict(base, task_pred_id='20005', task_id='10004', pred_task_id='10005', pred_type='PR_FS',
                     lag_hr_cnt='0'))
    pc, raw = _raw(data, monkeypatch)
    assert raw['slip_days'] == 500
    assert pc['counts']['status'] == 'FAIL', pc['message']
    assert 'first lost at A2' in pc['message']
    assert 'its Mandatory Start of 2026-06-08 08:00 holds it' in pc['message']
    assert 'set the amount' not in pc['message']


@needs_engine
def test_an_expected_finish_that_absorbs_part_of_the_delay_is_named(monkeypatch):
    # Under Use Expected Finish Dates, A2's expected finish sets its remaining
    # work once the delay pushes it past that date: F moves 596 of 600. That
    # is not the calendars: FAIL at A2, its expected finish.
    data = _p22()
    _task(data, 'A2')['cstr_type'] = ''
    _task(data, 'A2')['cstr_date'] = ''
    _task(data, 'A2')['expect_end_date'] = '2026-06-11 16:00'
    pc, raw = _raw(data, monkeypatch)
    assert 0 < raw['slip_days'] < 599
    assert pc['counts']['status'] == 'FAIL', pc['message']
    assert 'first lost at A2' in pc['message']
    assert 'its expected finish sets its finish' in pc['message']
    assert 'set the amount' not in pc['message']


@needs_engine
def test_a_failure_does_not_contradict_the_engine_on_the_driver(monkeypatch):
    # In p22 the engine still names A1 as the driver back from F (a Mandatory
    # Start that holds an activity keeps its predecessor's name): the FAIL
    # names the Mandatory Start and does not say F is no longer driven by A1.
    pc, raw = _raw(_p22(), monkeypatch)
    assert pc['counts']['status'] == 'FAIL'
    assert raw['named_back'] is True
    assert raw['carried_to_completion'] is False
    assert 'no longer driven by' not in pc['message']
    assert 'its Mandatory Start of 2026-06-08 08:00 holds it' in pc['message']


@needs_engine
def test_an_activity_passed_over_for_its_start_link_is_named(monkeypatch):
    # A1 drives A2 only through its start: the delay goes on A2, and the
    # result says A1 was passed over.
    data = _p22()
    _task(data, 'A2')['cstr_type'] = ''
    _task(data, 'A2')['cstr_date'] = ''
    for r in data['tables']['TASKPRED']['records']:
        if r['task_id'] == '10003':
            r['pred_type'] = 'PR_SS'
    pc, raw = _raw(data, monkeypatch)
    assert pc['counts']['status'] == 'PASS', pc['message']
    assert raw['test_activity'] == 'A2'
    assert raw['passed_over'] == ['A1']
    assert 'A1 drives the path only through its start (Start-to-Start) and was passed over' in pc['message']


def test_a_constraint_is_named_only_where_the_activity_sits_on_its_date():
    from critical_path_test import _constraints_at
    node = {'early_start_dt': '2027-03-01 08:00', 'early_finish_dt': '2027-03-05 16:00'}
    soft = {'cstr_type': 'CS_MSOA', 'cstr_date': '2026-06-08 08:00'}
    assert _constraints_at(soft, node) == []
    held = {'cstr_type': 'CS_MANDSTART', 'cstr_date': '2027-03-01 08:00'}
    assert _constraints_at(held, node) == ['Mandatory Start of 2027-03-01 08:00']
    fin = {'cstr_type': 'CS_MSOA', 'cstr_date': '2026-01-01 08:00',
           'cstr_type2': 'CS_MANDFIN', 'cstr_date2': '2027-03-05 16:00'}
    assert _constraints_at(fin, node) == ['Mandatory Finish of 2027-03-05 16:00']


def test_the_test_is_not_run_where_12_is_decided_without_it(monkeypatch):
    # A pinned completion fails and a completion with no predecessor is not
    # scored before the test is read: neither recalculation is made.
    import critical_path_test as cpt
    calls = []
    monkeypatch.setattr(cpt, 'run', lambda *a, **k: calls.append(1) or {'ran': False, 'reason': 'x'})
    assert _twelve(parse_xer(os.path.join(FX, 'p5_mandatory.xer')))['counts']['status'] == 'FAIL'
    data = _p22()
    data['tables']['TASKPRED']['records'] = [r for r in data['tables']['TASKPRED']['records']
                                             if r['task_id'] != '10004']
    pc = _twelve(data)
    assert pc['counts']['status'] == 'NOT SCORED'
    assert pc['details'].get('no_predecessor') is True
    assert calls == []


@needs_engine
def test_a_child_that_returns_nothing_is_reported_as_such(monkeypatch):
    import critical_path_test as cpt
    monkeypatch.setattr(cpt, 'IN_PROCESS_ACTIVITIES', 0)
    monkeypatch.setattr(cpt, '_CHILD_CODE', 'import sys' + chr(10) + 'sys.stdout.write("x")')
    pc = _twelve(_p22())
    assert pc['details'].get('test_run') is False
    assert 'returned no result' in pc['details'].get('test_not_run_reason', '')


@needs_engine
def test_no_delayed_run_is_started_without_a_second_left(monkeypatch):
    import critical_path_test as cpt
    monkeypatch.setattr(cpt, 'TEST_SECONDS_LIMIT', 0.0)
    pc = _twelve(_p22())
    assert pc['details'].get('test_run') is False
    assert 'before a delayed recalculation could be made' in pc['details'].get('test_not_run_reason', '')
