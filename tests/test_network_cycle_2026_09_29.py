#!/usr/bin/env python3
"""A schedule with a logic cycle grades RED, score 0, Unreliable, with a
Critical 'Network Cycle' recommendation (2026-09-29).

Run with: python tests/test_network_cycle_2026_09_29.py

A logic cycle (A1 -> A2 -> ... -> A5 -> A1) leaves the network with no
forward pass, no finish date and no critical path. The nine checks read the
stored float, constraints and relationships and never test that the network
is acyclic; on this fixture they score above 95, in the GREEN band. So
validate_critical_path detects cycles up front (Kahn's algorithm on the
relationship graph of the work activities) and, when it finds one, sets the
score to 0, the rating to RED and the confidence to Unreliable, and adds a
Critical recommendation that names a cycle to break.

The fixture is five neutral activities on a Monday-to-Friday calendar, each
five days long with zero total float, linked finish-to-start in a ring. The
acyclic twin drops the one link that closes the ring. Which activity the
cycle is reported from depends on set order, so the tests read the chain as
a set and check it closes on itself.
"""
import os
import sys
import tempfile
import warnings as _warnings

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, '..', 'scripts'))

from xer_parser import parse_xer  # noqa: E402
from cp_validator import CHECK_WEIGHTS, validate_critical_path  # noqa: E402

TAB = '\t'
_SHIFT = '(0||0(s|08:00|f|12:00)())(0||1(s|13:00|f|17:00)())'
_CALENDAR = ('(0||CalendarData()((0||DaysOfWeek()((0||1()())'
             + ''.join('(0||%d()(%s))' % (d, _SHIFT) for d in range(2, 7))
             + '(0||7()())))(0||Exceptions()())))')

_CODES = ['A1', 'A2', 'A3', 'A4', 'A5']
_TASK_COLS = ['task_id', 'proj_id', 'wbs_id', 'clndr_id', 'task_code',
              'task_name', 'task_type', 'status_code', 'target_drtn_hr_cnt',
              'remain_drtn_hr_cnt', 'total_float_hr_cnt', 'early_start_date',
              'early_end_date', 'late_start_date', 'late_end_date',
              'driving_path_flag', 'cstr_type', 'cstr_date']
# Five working weeks from Monday 2026-10-05, one per activity.
_WEEKS = [('2026-10-05', '2026-10-09'), ('2026-10-12', '2026-10-16'),
          ('2026-10-19', '2026-10-23'), ('2026-10-26', '2026-10-30'),
          ('2026-11-02', '2026-11-06')]


def _build_xer(links):
    lines = [
        TAB.join(['ERMHDR', '24.12', '2026-10-05', 'Project', 'admin', 'admin',
                  'dbxDatabaseNoName', 'Project Management', 'USD']),
        TAB.join(['%T', 'PROJECT']),
        TAB.join(['%F', 'proj_id', 'proj_short_name', 'clndr_id',
                  'last_recalc_date', 'scd_end_date']),
        TAB.join(['%R', '1', 'NEUTRAL', 'C1', '2026-10-05 08:00',
                  '2026-11-06 17:00']),
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
    for i, (code, (start, finish)) in enumerate(zip(_CODES, _WEEKS), 1):
        es, ef = start + ' 08:00', finish + ' 17:00'
        lines.append(TAB.join(['%R', str(i), '1', 'W1', 'C1', code,
                               'Neutral ' + code, 'TT_Task', 'TK_NotStart',
                               '40', '40', '0', es, ef, es, ef, 'Y', '', '']))
    lines += [
        TAB.join(['%T', 'TASKPRED']),
        TAB.join(['%F', 'task_pred_id', 'task_id', 'pred_task_id', 'proj_id',
                  'pred_proj_id', 'pred_type', 'lag_hr_cnt']),
    ]
    for k, (pred, succ) in enumerate(links, 1):
        lines.append(TAB.join(['%R', str(k), str(succ), str(pred), '1', '1',
                               'PR_FS', '0']))
    lines.append('%E')
    return '\r\n'.join(lines) + '\r\n'


def _validate(links):
    with tempfile.NamedTemporaryFile('w', suffix='.xer', delete=False,
                                     encoding='utf-8', newline='') as f:
        f.write(_build_xer(links))
        path = f.name
    try:
        with _warnings.catch_warnings():
            _warnings.simplefilter('ignore')
            return validate_critical_path(parse_xer(path))
    finally:
        os.unlink(path)


_CHAIN = [(1, 2), (2, 3), (3, 4), (4, 5)]
RING = _validate(_CHAIN + [(5, 1)])     # A5 -> A1 closes the ring
CHAIN = _validate(_CHAIN)


def _cycle_recs(r):
    return [x for x in r['recommendations'] if x['category'] == 'Network Cycle']


def test_a_five_activity_cycle_grades_red_zero_unreliable():
    assert RING['cycle_detected'] is True
    assert RING['overall_score'] == 0, RING['overall_score']
    assert RING['overall_rating'] == 'RED', RING['overall_rating']
    assert RING['overall_confidence'] == 'Unreliable', RING['overall_confidence']


def test_the_nine_checks_alone_would_have_graded_it_green():
    """Guard on the fixture: the RED comes from the cycle, not from a check.
    The weighted score of the nine checks is in the GREEN band, and none of
    them is RED."""
    weighted = sum(RING['checks'][k]['score'] * w for k, w in CHECK_WEIGHTS.items())
    assert weighted >= 80, weighted
    assert [k for k, c in RING['checks'].items() if c['rating'] == 'RED'] == []


def test_a_critical_network_cycle_recommendation_names_the_cycle():
    recs = _cycle_recs(RING)
    assert len(recs) == 1, RING['recommendations']
    rec = recs[0]
    assert rec['priority'] == 'Critical'
    assert 'logic cycle' in rec['finding']
    assert '1 cycle(s) detected' in rec['finding'], rec['finding']
    assert rec['affected_activity'] in _CODES, rec['affected_activity']
    for code in _CODES:
        assert code in rec['finding'], (code, rec['finding'])
    assert RING['recommendations'][0]['priority'] == 'Critical'


def test_cycles_found_lists_the_closed_chain():
    assert len(RING['cycles_found']) == 1, RING['cycles_found']
    chain = RING['cycles_found'][0]
    assert len(chain) == 6 and chain[0] == chain[-1], chain
    assert set(chain) == set(_CODES), chain
    ids = RING['cycles_found_task_ids'][0]
    assert [_CODES[int(i) - 1] for i in ids] == chain, (ids, chain)


def test_without_the_closing_link_there_is_no_cycle():
    assert CHAIN['cycle_detected'] is False
    assert CHAIN['cycles_found'] == [] and CHAIN['cycles_found_task_ids'] == []
    assert _cycle_recs(CHAIN) == []
    assert CHAIN['overall_score'] > 0, CHAIN['overall_score']


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
