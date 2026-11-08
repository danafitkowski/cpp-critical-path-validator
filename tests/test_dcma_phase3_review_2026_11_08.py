"""DCMA #12, the Critical Path Test: the review of the test (8-Nov-26).

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
    assert 'its start moved by 600 working days, but its expected finish re-sized its remaining work' in pc['message']
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
def test_an_activity_that_drives_the_path_through_its_start_takes_a_start_delay(monkeypatch):
    # A1 drives A2 only through its start. The duration delay goes on A2 and
    # passes; then A1 takes a start delay, so the stretch it covers is tested
    # too (review of the test, 8-Nov-26: it was named, not tested).
    data = _drop_a2_pin(_p22())
    for r in data['tables']['TASKPRED']['records']:
        if r['task_id'] == '10003':
            r['pred_type'] = 'PR_SS'
    pc, raw = _raw(data, monkeypatch)
    assert pc['counts']['status'] == 'PASS', pc['message']
    assert raw['test_activity'] == 'A1' and raw['start_delay'] is True
    assert raw['duration_test'] == {'test_activity': 'A2', 'slip_days': 600.0}
    assert raw['tried'] == ['A2', 'A1'] and raw['passed_over'] == []
    assert 'a start delay of 600 working days inserted on A1' in pc['message']
    assert 'A duration delay of 600 working days on A2, further along the path' in pc['message']


@needs_engine
def test_a_mandatory_start_after_a_start_link_is_found_by_the_start_delay(monkeypatch):
    # A2's Mandatory Start sat just past a Start-to-Start link; the
    # duration delay on A2 passed and the pin was never exercised.
    data = _p22()
    for r in data['tables']['TASKPRED']['records']:
        if r['task_id'] == '10003':
            r['pred_type'] = 'PR_SS'
    _task(data, 'A2')['cstr_date'] = '2026-06-01 08:00'
    pc, raw = _raw(data, monkeypatch)
    assert pc['counts']['status'] == 'FAIL', pc['message']
    assert raw['test_activity'] == 'A1' and raw['start_delay'] is True
    assert 'first lost at A2' in pc['message']
    assert 'its Mandatory Start of 2026-06-01 08:00 holds it' in pc['message']


@needs_engine
def test_a_path_carried_only_by_start_links_is_tested_by_a_start_delay(monkeypatch):
    # Every unfinished activity drives the next through its start: this was
    # NOT SCORED; the start delay on the nearest one now tests the path.
    data = _drop_a2_pin(_p22())
    for r in data['tables']['TASKPRED']['records']:
        if r['task_id'] in ('10003', '10004'):
            r['pred_type'] = 'PR_SS'
    pc, raw = _raw(data, monkeypatch)
    assert pc['counts']['status'] == 'PASS', pc['message']
    assert raw['test_activity'] == 'A1' and raw['start_delay'] is True
    assert raw['slip_days'] == 600


@needs_engine
def test_a_started_activity_on_a_start_link_is_named_as_not_tested(monkeypatch):
    # A start that has happened cannot be delayed: the stretch is named.
    data = _drop_a2_pin(_p22())
    for r in data['tables']['TASKPRED']['records']:
        if r['task_id'] == '10003':
            r['pred_type'] = 'PR_SS'
    a1 = _task(data, 'A1')
    a1.update(status_code='TK_Active', act_start_date='2026-05-28 08:00')
    pc, raw = _raw(data, monkeypatch)
    assert pc['counts']['status'] == 'PASS', pc['message']
    assert raw['test_activity'] == 'A2'
    assert ('A start delay could not be inserted on A1, which drives the path through its start, so that '
            'stretch is not tested: it has started') in pc['message']


def _with_path(data, code, task_id, pred_id, hours='40'):
    a2 = _task(data, 'A2')
    data['tables']['TASK']['records'].append(dict(a2, task_id=task_id, task_code=code, task_name=code,
                                                  cstr_type='', cstr_date='', remain_drtn_hr_cnt=hours,
                                                  target_drtn_hr_cnt=hours))
    rels = data['tables']['TASKPRED']['records']
    b = dict(rels[0])
    rels.append(dict(b, task_pred_id='3' + task_id, task_id=task_id, pred_task_id=pred_id, pred_type='PR_FS'))
    rels.append(dict(b, task_pred_id='4' + task_id, task_id='10004', pred_task_id=task_id, pred_type='PR_FS'))
    return data


@needs_engine
def test_an_equal_path_the_delay_did_not_reach_is_named(monkeypatch):
    # one insertion tests one path. Y runs from the start milestone
    # into F at the same total float: named as not tested.
    data = _with_path(_drop_a2_pin(_p22()), 'Y', '10007', '10001', hours='80')
    pc, raw = _raw(data, monkeypatch)
    assert pc['counts']['status'] == 'PASS', pc['message']
    assert raw['untested_paths'] == ['Y']
    assert ('The completion is also driven, at the same total float, through Y, which the delay did not '
            'reach; that path is not tested.') in pc['message']


@needs_engine
def test_an_equal_path_the_delay_reached_is_not_named(monkeypatch):
    # X runs from A1 into F beside A2: the delay on A1 reaches it as well.
    data = _with_path(_drop_a2_pin(_p22()), 'X', '10005', '10002')
    pc, raw = _raw(data, monkeypatch)
    assert pc['counts']['status'] == 'PASS', pc['message']
    assert raw['parallel_paths'] == ['X'] and raw['untested_paths'] == []
    assert 'not tested' not in pc['message']


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


# ── The check of these fixes (8-Nov-26) ──

def _drop_a2_pin(data):
    _task(data, 'A2')['cstr_type'] = ''
    _task(data, 'A2')['cstr_date'] = ''
    return data


@needs_engine
def test_a_blank_activity_calendar_takes_the_project_calendar_and_the_first_try(monkeypatch):
    # the verdict alone cannot show the calendar was resolved; the
    # tried list can. A1 has no calendar on a 10-hour project calendar.
    data = _drop_a2_pin(_p22())
    for c in data['tables']['CALENDAR']['records']:
        c['clndr_data'] = c['clndr_data'].replace('s|08:00|f|16:00', 's|07:00|f|17:00')
        c['day_hr_cnt'] = '10'
    _task(data, 'A1')['clndr_id'] = ''
    pc, raw = _raw(data, monkeypatch)
    assert pc['counts']['status'] == 'PASS', pc['message']
    assert raw['tried'] == ['A1'] and raw['skipped'] == []
    assert raw['slip_days'] == 600


@needs_engine
def test_a_mandatory_finish_on_a_weekend_holds_the_test_activity(monkeypatch):
    # a Saturday Mandatory Finish holds the Friday close; a literal date
    # compare missed it, A1 was skipped and A2 passed.
    data = _drop_a2_pin(_p22())
    _task(data, 'A1')['cstr_type'] = 'CS_MANDFIN'
    _task(data, 'A1')['cstr_date'] = '2029-06-30 16:00'
    pc, raw = _raw(data, monkeypatch)
    assert pc['counts']['status'] == 'FAIL', pc['message']
    assert raw['tried'] == ['A1']
    assert 'its Mandatory Finish of 2029-06-30 16:00 holds it' in pc['message']


@needs_engine
def test_a_constraint_that_absorbs_part_of_the_delay_fails_with_the_move_measured(monkeypatch):
    # A1's Mandatory Finish sat later than its logic; the gap absorbed
    # 260 of the 600 days. A1 was skipped as not moving and A2 passed.
    data = _drop_a2_pin(_p22())
    _task(data, 'A1')['cstr_type'] = 'CS_MANDFIN'
    _task(data, 'A1')['cstr_date'] = '2027-06-04 16:00'
    pc, raw = _raw(data, monkeypatch)
    assert pc['counts']['status'] == 'FAIL', pc['message']
    assert raw['tried'] == ['A1']
    assert raw['slip_days'] == 340
    assert 'moved its finish by only 340 working days: its Mandatory Finish of 2027-06-04 16:00' in pc['message']


def _seasonal(changed):
    data = _drop_a2_pin(_p22())
    a2 = _task(data, 'A2')
    a2['clndr_id'] = '9999'
    cal = data['tables']['CALENDAR']['records'][0]
    exc = ''.join('(0||%d(d|%d)())' % (i, 46181 + i) for i in range(210))  # 8-Jun-26 to 3-Jan-27
    data['tables']['CALENDAR']['records'].append(
        dict(cal, clndr_id='9999',
             clndr_data=cal['clndr_data'].replace('Exceptions()()', 'Exceptions()(' + exc + ')')))
    data['tables']['SCHEDOPTIONS']['records'][0]['sched_calendar_on_relationship_lag'] = 'rcal_Successor'
    rels = data['tables']['TASKPRED']['records']
    rels[-1]['lag_hr_cnt'] = '-800'
    if changed:
        data['tables']['TASK']['records'].append(dict(a2, task_id='10005', task_code='X', task_name='X',
                                                      clndr_id='7023', expect_end_date='2026-08-03 16:00'))
        b = rels[0]
        rels.extend([dict(b, task_pred_id='30001', pred_task_id='10002', task_id='10005'),
                     dict(b, task_pred_id='30002', pred_task_id='10005', task_id='10004')])
    return data


@needs_engine
def test_a_seasonal_path_passes_on_the_calendar_rule_and_names_the_lead(monkeypatch):
    pc, raw = _raw(_seasonal(False), monkeypatch)
    assert pc['counts']['status'] == 'PASS', pc['message']
    assert raw['slip_days'] == 450
    assert 'the calendars and leads on the path' in pc['message']


@needs_engine
def test_an_expected_finish_on_the_new_driving_path_is_not_blamed_on_calendars(monkeypatch):
    # F's driver changes to X, whose expected finish re-sizes 41 days;
    # the calendar rule checked only the old path and passed it.
    pc, raw = _raw(_seasonal(True), monkeypatch)
    assert pc['counts']['status'] == 'FAIL', pc['message']
    assert 'set the amount' not in pc['message']
    assert 'first lost at F' in pc['message']
    assert 'is now driven by X, whose expected finish re-sized its remaining work' in pc['message']


@needs_engine
def test_a_full_move_along_another_path_names_what_held_the_filed_path(monkeypatch):
    # X ties A2 into F; A2 is pinned and the delay reaches F
    # through X by the full 600. A PASS, which names A2 and its pin.
    data = _p22()
    a2 = _task(data, 'A2')
    data['tables']['TASK']['records'].append(dict(a2, task_id='10005', task_code='X', task_name='X',
                                                  cstr_type='', cstr_date=''))
    rels = data['tables']['TASKPRED']['records']
    base = dict(rels[0])
    rels.append(dict(base, task_pred_id='20004', task_id='10005', pred_task_id='10002', lag_hr_cnt='0'))
    rels.append(dict(base, task_pred_id='20005', task_id='10004', pred_task_id='10005', lag_hr_cnt='0'))
    pc, raw = _raw(data, monkeypatch)
    assert pc['counts']['status'] == 'PASS', pc['message']
    assert raw['stayed'] == ['A2']
    assert ('The delay reached the completion along another path: on the as-filed driving path, A2 (its '
            'Mandatory Start of 2026-06-08 08:00 holds it) did not move.') in pc['message']


@needs_engine
def test_a_finish_that_does_not_take_the_delay_for_no_named_reason_is_not_scored(monkeypatch):
    # an unexplained absorption is the finding the test exists for;
    # it is not skipped for the next activity. Here the delayed run is made to
    # leave A1's finish where it was.
    import critical_path_test as cpt
    data = _drop_a2_pin(_p22())
    real = cpt._recalc
    calls = []
    kept = {}

    def frozen(compute_cpm, acts, rels, kwargs, seconds, in_child):
        res = real(compute_cpm, acts, rels, kwargs, seconds, in_child)
        calls.append(1)
        if len(calls) == 1:
            kept['ef'] = res['nodes']['A1'].get('early_finish_dt')
        else:
            res['nodes']['A1']['early_finish_dt'] = kept['ef']
        return res
    monkeypatch.setattr(cpt, '_recalc', frozen)
    pc = _twelve(data)
    assert pc['counts']['status'] == 'NOT SCORED', pc['message']
    assert 'did not move its finish by the delay' in pc['message']
    assert 'the recalculation cannot say why' in pc['message']
    assert len(calls) == 2


@needs_engine
def test_the_p6_longest_path_flag_off_the_tested_path_is_disclosed(monkeypatch):
    # the file carries the P6 answer too.
    data = _drop_a2_pin(_p22())
    _task(data, 'A1')['driving_path_flag'] = 'N'
    pc, raw = _raw(data, monkeypatch)
    assert pc['counts']['status'] == 'PASS'
    assert raw['p6_off_path'] == 1
    assert ("own longest-path flag in the file marks 1 of the 3 activities on this path, from A1 to the "
            "completion, as off its longest path") in pc['message']


# ── The final review (8-Nov-26) ──

@needs_engine
def test_a_start_a_mandatory_start_holds_cannot_take_the_start_delay(monkeypatch):
    # A1 drives A2 through its start and is pinned by a Mandatory Start
    # on its date; the inserted Start On or After overrode the pin and passed.
    data = _drop_a2_pin(_p22())
    for r in data['tables']['TASKPRED']['records']:
        if r['task_id'] == '10003':
            r['pred_type'] = 'PR_SS'
    _task(data, 'A1')['cstr_type'] = 'CS_MANDSTART'
    _task(data, 'A1')['cstr_date'] = '2026-06-08 08:00'
    pc, raw = _raw(data, monkeypatch)
    assert pc['counts']['status'] == 'FAIL', pc['message']
    assert raw['test_activity'] == 'A1' and raw['lost_at'] == 'A1'
    assert 'its Mandatory Start of 2026-06-08 08:00 holds its start' in pc['message']


def test_a_duration_delay_is_held_only_by_a_finish_constraint():
    # a start constraint cannot hold a duration delay, which moves a
    # finish; the duration test reads finish constraints only.
    from critical_path_test import _constraints_at, _constraints_of
    task = {'cstr_type': 'CS_MSOA', 'cstr_date': '2027-03-01 08:00',
            'cstr_type2': 'CS_MANDFIN', 'cstr_date2': '2027-03-05 16:00'}
    node = {'early_start_dt': '2027-03-01 08:00', 'early_finish_dt': '2027-03-05 16:00'}
    assert _constraints_at(task, node, kinds='finish') == ['Mandatory Finish of 2027-03-05 16:00']
    assert _constraints_at(task, node, kinds='start') == ['Start On or After of 2027-03-01 08:00']
    assert _constraints_of(task, 'finish') == ['Mandatory Finish of 2027-03-05 16:00']


@needs_engine
def test_a_failure_names_where_the_delay_is_lost_for_the_register(monkeypatch):
    # a handed-in FAIL listed no activity; the result carries it.
    pc, raw = _raw(_p22(), monkeypatch)
    assert raw['status'] == 'FAIL' and raw['lost_at'] == 'A2'


def test_a_named_deadline_needs_no_exported_float():
    # a blank float on the completion left a schedule with
    # a deadline NOT SCORED; the deadline's working time needs no P6 float.
    data = copy.deepcopy(parse_xer(os.path.join(FX, 'p19_calendar_mix.xer')))
    for t in data['tables']['TASK']['records']:
        if t['task_code'] == 'F':
            t['total_float_hr_cnt'] = ''
    pc = dcma_14_assess(data)['per_check']['DCMA-13-CPLI']
    assert pc['counts']['status'] == 'FAIL', pc['message']
    assert abs(pc['value'] - 0.5) < 1e-6


def test_a_finished_completion_is_not_said_to_fail_12():
    # #13 on a finished, pinned completion said "#12 fails it instead"
    # beside a NOT SCORED #12.
    res = dcma_14_assess(parse_xer(os.path.join(FX, 'p16_as_built_mandatory.xer')))['per_check']
    assert res['DCMA-12-CriticalPathTest']['counts']['status'] == 'NOT SCORED'
    assert res['DCMA-13-CPLI']['counts']['status'] == 'NOT SCORED'
    assert '#12 fails it' not in res['DCMA-13-CPLI']['message']


# ── The second round of the final review (8-Nov-26) ──

def _ss_a1(data):
    for r in data['tables']['TASKPRED']['records']:
        if r['task_id'] == '10003':
            r['pred_type'] = 'PR_SS'
    return data


@needs_engine
def test_a_soft_start_constraint_does_not_block_the_start_delay(monkeypatch):
    # Every start constraint was read as a hold: a Start On or After at the
    # data date FAILED with no recalculation. Only a primary Mandatory Start on
    # its date holds a start (fixtures p23 and p24 pin both sides).
    data = _ss_a1(_drop_a2_pin(_p22()))
    _task(data, 'A1')['cstr_type'] = 'CS_MSOA'
    _task(data, 'A1')['cstr_date'] = '2026-06-01 08:00'
    pc, raw = _raw(data, monkeypatch)
    assert pc['counts']['status'] == 'PASS', pc['message']
    assert raw['start_delay'] is True and raw['slip_days'] == 600


@needs_engine
def test_a_mandatory_start_before_the_data_date_does_not_hold_the_start(monkeypatch):
    # P6 starts the work at the data date (probes of 13-Oct-26), so the start
    # delay is inserted and judged by the move.
    data = _ss_a1(_drop_a2_pin(_p22()))
    _task(data, 'A1')['cstr_type'] = 'CS_MANDSTART'
    _task(data, 'A1')['cstr_date'] = '2026-05-15 08:00'
    pc, raw = _raw(data, monkeypatch)
    assert pc['counts']['status'] == 'PASS', pc['message']


@needs_engine
def test_a_pinned_start_reports_no_measured_move(monkeypatch):
    data = _ss_a1(_drop_a2_pin(_p22()))
    _task(data, 'A1')['cstr_type'] = 'CS_MANDSTART'
    _task(data, 'A1')['cstr_date'] = '2026-06-08 08:00'
    pc, raw = _raw(data, monkeypatch)
    assert pc['counts']['status'] == 'FAIL'
    assert raw['slip_days'] is None


@needs_engine
def test_a_start_that_does_not_take_the_delay_for_no_named_reason_is_not_scored(monkeypatch):
    # As a finish in the duration test: the start delayed run is made to leave
    # A1's start where it was.
    import critical_path_test as cpt
    data = _ss_a1(_drop_a2_pin(_p22()))
    real = cpt._recalc
    calls = []
    kept = {}

    def frozen(compute_cpm, acts, rels, kwargs, seconds, in_child):
        res = real(compute_cpm, acts, rels, kwargs, seconds, in_child)
        calls.append(1)
        if len(calls) == 1:
            kept['es'] = res['nodes']['A1'].get('early_start_dt')
        elif any((a.get('constraint') or a.get('constraint2') or {}).get('type') == 'CS_MSOA'
                 for a in acts if a.get('code') == 'A1'):
            res['nodes']['A1']['early_start_dt'] = kept['es']
        return res
    monkeypatch.setattr(cpt, '_recalc', frozen)
    pc = _twelve(data)
    assert pc['counts']['status'] == 'NOT SCORED', pc['message']
    assert 'did not move its start by the delay' in pc['message']


@needs_engine
def test_the_recalculation_uses_the_lifted_data_date(monkeypatch, tmp_path):
    # D14: a data date on a day before a later planned start is lifted to it;
    # the parser writes the lifted date into the project record the test reads.
    import critical_path_test as cpt
    src = os.path.join(FX, 'p10_late_no_baseline.xer')
    text = open(src, encoding='utf-8').read().replace('2026-06-01 08:00', '2026-05-01 08:00', 1)
    f = tmp_path / 'lift.xer'
    f.write_text(text, encoding='utf-8')
    seen = []
    real = cpt._recalc

    def spy(compute_cpm, acts, rels, kwargs, seconds, in_child):
        seen.append(kwargs.get('data_date'))
        return real(compute_cpm, acts, rels, kwargs, seconds, in_child)
    monkeypatch.setattr(cpt, '_recalc', spy)
    data = parse_xer(str(f))
    lifted = data['tables']['PROJECT']['records'][0]['last_recalc_date']
    assert lifted == data['tables']['PROJECT']['records'][0]['plan_start_date'] != '2026-05-01 08:00'
    _twelve(data)
    assert seen and set(seen) == {lifted}


# #13 gives the health report's reasons: a blank float is blank, not zero; a
# finished completion says it is complete.
def _thirteen(data):
    return dcma_14_assess(data)['per_check']['DCMA-13-CPLI']


def test_13_a_blank_float_with_no_deadline_is_called_blank_not_zero():
    data = copy.deepcopy(parse_xer(os.path.join(FX, 'p19_calendar_mix.xer')))
    f = _task(data, 'F')
    for k in ('total_float_hr_cnt', 'cstr_type', 'cstr_date', 'cstr_type2', 'cstr_date2'):
        f[k] = ''
    for p in data['tables']['PROJECT']['records']:
        p['plan_end_date'] = ''
    check = _thirteen(data)
    assert check['value'] is None, check
    assert 'carries no exported total float' in check['message'], check['message']
    assert 'by construction' not in check['message'], check['message']


def test_13_a_finished_completion_says_it_is_complete():
    data = parse_xer(os.path.join(FX, 'p16_as_built_mandatory.xer'))
    check = _thirteen(data)
    assert check['value'] is None, check
    assert 'is complete, so there is no remaining critical path' in check['message'], check['message']
