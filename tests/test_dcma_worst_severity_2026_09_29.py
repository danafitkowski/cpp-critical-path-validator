#!/usr/bin/env python3
"""The embedded DCMA-14 report's worst severity sits at the top level of the
results, beside a headline labelled as logic health (2026-09-29).

Run with: python tests/test_dcma_worst_severity_2026_09_29.py

validate_critical_path grades logic health: its score, rating and confidence
come from the nine checks. The DCMA-14 report it embeds can say BLOCK on its
own, for example for an actual start after the data date (DCMA-14 #9), while
the nine checks read GREEN, High Confidence. That BLOCK sat at
results['dcma_14']['report']['summary']['worst_severity'], out of sight of a
reader scanning the headline. CPP's internal validator lifts it to
results['dcma_worst_severity'], with results['dcma_blocks_despite_logic_rating'],
and labels the headline's scope in results['overall_rating_scope'] and
results['overall_rating_label']. This file pins the same behaviour here: the
keys, the read-up from the report's summary, that the score and the RED-check
cap are untouched, that nothing is claimed when DCMA-14 did not run, and the
dashboard line.

The fixture is a finish-to-start chain on a Monday-to-Friday calendar: a
completed start milestone, two five-day tasks and a finish milestone. In the
BLOCK twin the first task is in progress with an actual start two months
after the data date. The open-start variant drops the start milestone, which
leaves the first task an open end on the critical path (Check 3 RED).
"""
import json
import os
import sys
import tempfile
import warnings as _warnings

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, '..', 'scripts'))

from xer_parser import parse_xer  # noqa: E402
from cp_validator import (  # noqa: E402
    RATING_AMBER, RATING_GREEN, RATING_RED, generate_dashboard,
    validate_critical_path,
)
import dcma14  # noqa: E402

TAB = '\t'
_SHIFT = '(0||0(s|08:00|f|12:00)())(0||1(s|13:00|f|17:00)())'
_CALENDAR = ('(0||CalendarData()((0||DaysOfWeek()((0||1()())'
             + ''.join('(0||%d()(%s))' % (d, _SHIFT) for d in range(2, 7))
             + '(0||7()())))(0||Exceptions()())))')
_TASK_COLS = ['task_id', 'proj_id', 'wbs_id', 'clndr_id', 'task_code',
              'task_name', 'task_type', 'status_code', 'target_drtn_hr_cnt',
              'remain_drtn_hr_cnt', 'total_float_hr_cnt', 'early_start_date',
              'early_end_date', 'late_start_date', 'late_end_date',
              'act_start_date', 'act_end_date', 'driving_path_flag',
              'cstr_type', 'cstr_date']


def _build_xer(future_actual, open_start=False):
    status = 'TK_Active' if future_actual else 'TK_NotStart'
    act_start = '2026-12-01 08:00' if future_actual else ''
    rows = [
        # id, code, type, status, dur h, ES, EF, actual start, actual finish
        ('4', 'A0', 'TT_Mile', 'TK_Complete', '0', '2026-10-02 08:00',
         '2026-10-02 08:00', '2026-10-02 08:00', '2026-10-02 08:00'),
        ('1', 'A1', 'TT_Task', status, '40', '2026-10-05 08:00',
         '2026-10-09 17:00', act_start, ''),
        ('2', 'A2', 'TT_Task', 'TK_NotStart', '40', '2026-10-12 08:00',
         '2026-10-16 17:00', '', ''),
        ('3', 'A3', 'TT_FinMile', 'TK_NotStart', '0', '2026-10-16 17:00',
         '2026-10-16 17:00', '', ''),
    ]
    lines = [
        TAB.join(['ERMHDR', '24.12', '2026-10-05', 'Project', 'admin', 'admin',
                  'dbxDatabaseNoName', 'Project Management', 'USD']),
        TAB.join(['%T', 'PROJECT']),
        TAB.join(['%F', 'proj_id', 'proj_short_name', 'clndr_id',
                  'last_recalc_date', 'scd_end_date']),
        TAB.join(['%R', '1', 'NEUTRAL', 'C1', '2026-10-05 08:00',
                  '2026-10-16 17:00']),
        TAB.join(['%T', 'CALENDAR']),
        TAB.join(['%F', 'clndr_id', 'default_flag', 'clndr_name', 'clndr_type',
                  'day_hr_cnt', 'week_hr_cnt', 'clndr_data']),
        TAB.join(['%R', 'C1', 'Y', 'Five Day', 'CA_Base', '8', '40', _CALENDAR]),
        TAB.join(['%T', 'PROJWBS']),
        TAB.join(['%F', 'wbs_id', 'proj_id', 'parent_wbs_id', 'wbs_short_name',
                  'wbs_name', 'proj_node_flag']),
        TAB.join(['%R', 'W1', '1', '', 'NEUTRAL', 'Neutral', 'Y']),
        TAB.join(['%T', 'TASK']),
        TAB.join(['%F'] + _TASK_COLS),
    ]
    if open_start:
        rows = rows[1:]
    for tid, code, ttype, st, dur, es, ef, ast, aen in rows:
        remain = '0' if st == 'TK_Complete' else dur
        lines.append(TAB.join(['%R', tid, '1', 'W1', 'C1', code,
                               'Neutral ' + code, ttype, st, dur, remain, '0',
                               es, ef, es, ef, ast, aen, 'Y', '', '']))
    lines += [
        TAB.join(['%T', 'TASKPRED']),
        TAB.join(['%F', 'task_pred_id', 'task_id', 'pred_task_id', 'proj_id',
                  'pred_proj_id', 'pred_type', 'lag_hr_cnt']),
        TAB.join(['%R', '1', '2', '1', '1', '1', 'PR_FS', '0']),
        TAB.join(['%R', '2', '3', '2', '1', '1', 'PR_FS', '0']),
    ]
    if not open_start:
        lines.append(TAB.join(['%R', '3', '1', '4', '1', '1', 'PR_FS', '0']))
    lines.append('%E')
    return '\r\n'.join(lines) + '\r\n'


def _validate(future_actual, open_start=False):
    with tempfile.NamedTemporaryFile('w', suffix='.xer', delete=False,
                                     encoding='utf-8', newline='') as f:
        f.write(_build_xer(future_actual, open_start))
        path = f.name
    try:
        with _warnings.catch_warnings():
            _warnings.simplefilter('ignore')
            return validate_critical_path(parse_xer(path))
    finally:
        os.unlink(path)


def _validate_without_dcma(future_actual, open_start=False):
    """The same run with DCMA-14 failing, as it does when the module raises."""
    def _boom(*a, **k):
        raise RuntimeError('simulated DCMA-14 failure')
    saved = dcma14.dcma_14_assess
    dcma14.dcma_14_assess = _boom
    try:
        return _validate(future_actual, open_start)
    finally:
        dcma14.dcma_14_assess = saved


BLOCKED = _validate(future_actual=True)
CLEAN = _validate(future_actual=False)
OPEN_START = _validate(future_actual=True, open_start=True)


def _embedded_worst(r):
    return r['dcma_14']['report']['summary']['worst_severity']


def test_the_headline_is_labelled_logic_health():
    for r in (BLOCKED, CLEAN, OPEN_START):
        assert r['overall_rating_scope'] == 'logic_health'
        assert r['overall_rating_label'] == 'Logic Health'
        assert 'dcma_worst_severity' in r


def test_an_embedded_dcma_block_surfaces_at_the_top_level():
    assert _embedded_worst(BLOCKED) == 'BLOCK', _embedded_worst(BLOCKED)
    per_check = BLOCKED['dcma_14']['per_check']
    assert any(c.get('severity') == 'BLOCK' for c in per_check.values())
    assert BLOCKED['dcma_worst_severity'] == 'BLOCK'
    assert BLOCKED['dcma_blocks_despite_logic_rating'] is True


def test_the_logic_health_headline_reads_green_over_the_block():
    """The case the lift exists for: DCMA-14 says BLOCK while the
    logic-health headline reads GREEN, High Confidence."""
    assert (BLOCKED['overall_rating'], BLOCKED['overall_confidence']) == (
        RATING_GREEN, 'High Confidence'), (
        BLOCKED['overall_rating'], BLOCKED['overall_score'])


def test_the_top_level_value_is_the_reports_summary():
    for r in (BLOCKED, CLEAN, OPEN_START):
        assert r['dcma_worst_severity'] == _embedded_worst(r)
        assert r['dcma_blocks_despite_logic_rating'] is (
            _embedded_worst(r) in ('BLOCK', 'RED'))


def test_a_schedule_without_a_dcma_block_is_not_flagged():
    assert CLEAN['dcma_worst_severity'] != 'BLOCK', CLEAN['dcma_worst_severity']
    assert CLEAN['dcma_blocks_despite_logic_rating'] is False


def test_the_score_is_not_touched():
    """The lift reads the DCMA-14 summary and changes nothing it grades."""
    for args, r in (((True,), BLOCKED), ((False,), CLEAN),
                    ((True, True), OPEN_START)):
        bare = _validate_without_dcma(*args)
        assert 'error' in bare['dcma_14'], bare['dcma_14']
        assert (bare['overall_score'], bare['overall_rating'],
                bare['overall_confidence']) == (
            r['overall_score'], r['overall_rating'], r['overall_confidence'])


def test_nothing_is_claimed_when_dcma_did_not_run():
    bare = _validate_without_dcma(True)
    assert bare['dcma_worst_severity'] is None
    assert 'dcma_blocks_despite_logic_rating' not in bare
    assert bare['overall_rating_scope'] == 'logic_health'


def test_a_red_check_still_caps_the_headline():
    """The RED-check cap is unchanged by the lift: with the start open, Check 3
    is RED and the headline is capped, and DCMA-14's BLOCK is still lifted."""
    assert OPEN_START['checks']['open_ends_cp']['rating'] == RATING_RED
    assert OPEN_START['overall_rating'] == RATING_AMBER
    assert OPEN_START['overall_rating_capped_by_red'] is True
    assert OPEN_START['dcma_worst_severity'] == 'BLOCK'
    assert OPEN_START['dcma_blocks_despite_logic_rating'] is True


def test_the_results_stay_json_serialisable():
    out = json.loads(json.dumps(BLOCKED, default=str))
    assert out['dcma_worst_severity'] == 'BLOCK'


def _dashboard(results):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'report.html')
        generate_dashboard(results, path)
        with open(path, encoding='utf-8') as f:
            return f.read()


def test_the_dashboard_shows_a_dcma_block_under_the_gauge():
    html = _dashboard(BLOCKED)
    assert 'DCMA-14 recommendation:' in html
    gauge = html[html.index('CP Confidence Score</div>'):]
    line = gauge[:gauge.index('</div>', gauge.index('DCMA-14 recommendation:'))]
    assert 'Must Fix' in line and 'grades logic health only' in line, line


def test_the_dashboard_says_nothing_when_dcma_did_not_run():
    html = _dashboard(_validate_without_dcma(True))
    assert 'DCMA-14 recommendation:' not in html


def test_the_dashboard_adds_no_warning_without_a_block():
    html = _dashboard(CLEAN)
    assert 'DCMA-14 recommendation:' in html
    assert 'grades logic health only' not in html


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
