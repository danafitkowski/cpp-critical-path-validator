"""DCMA review, round 2 (7 November 2026): what the second review found
in the validator after the first round of fixes, pinned.

1. D0 chooses the project on the data dates AS FILED. The parser fills a
   blank data date (and lifts an early one) to the planned start in place,
   and ranking on the changed date chose a project the dashboard and Lens do
   not: in fixtures/dcma_round2/d0_before_fill.xer, 9001 has a blank data
   date and a planned start of 1 December; 9002 is filed at 1 June. D0 picks
   9002; ranking on the filled date picked 9001.
2. A file with one PROJECT row is read whole by the critical path report too
   (D0): on parity fixture p9 the report counted 4 activities while its own
   DCMA block counted 5.
3. A duration that is not a number is no duration: #8 leaves it out, as it
   leaves out a blank one (fixtures/dcma_round2/invalid_duration.xer, four
   'unknown' durations, read PASS 0 of 4).
"""
import os
import sys
import warnings

import pytest

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, '..', 'scripts'))

import dcma14  # noqa: E402
from dcma14 import dcma_14_assess, _readable_hours  # noqa: E402
from xer_parser import parse_xer  # noqa: E402
from cp_validator import validate_critical_path  # noqa: E402

FX = os.path.join(SCRIPT_DIR, 'fixtures', 'dcma_round2')
PARITY = os.path.join(SCRIPT_DIR, 'fixtures', 'dcma_parity')


def _validate(data, **kw):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        return validate_critical_path(data, **kw)


def test_d0_chooses_on_the_filed_data_dates():
    data = parse_xer(os.path.join(FX, 'd0_before_fill.xer'))
    # the parser did fill 9001's blank data date from its planned start
    assert any(e['proj_id'] == '9001' for e in data['data_date_filled'])
    result = dcma_14_assess(data)
    assert result['proj_id'] == '9002'
    report = _validate(data)
    assert report['dcma_14']['proj_id'] == '9002'
    assert report['project_name'] == result['project_name']


def test_without_the_parsers_record_the_rows_are_read_as_they_stand():
    key = dcma14._d0_rank_key([], None)
    a = {'proj_id': 'A', 'last_recalc_date': '2026-06-01 08:00'}
    b = {'proj_id': 'B', 'last_recalc_date': '2026-12-01 08:00'}
    assert max([a, b], key=key) is b


@pytest.mark.skipif(not os.path.isfile(os.path.join(PARITY, 'p9_data_date.xer')),
                    reason='shared parity fixtures not found')
def test_a_single_project_report_reads_the_file_whole():
    data = parse_xer(os.path.join(PARITY, 'p9_data_date.xer'))
    report = _validate(data)
    nine = report['dcma_14']['per_check']['DCMA-09-InvalidDates']['counts']
    assert report['total_activities'] == 5
    assert nine['den'] == 5


def test_an_unreadable_duration_is_left_out_of_8():
    data = parse_xer(os.path.join(FX, 'invalid_duration.xer'))
    eight = dcma_14_assess(data)['per_check']['DCMA-08-HighDuration']
    assert eight['counts']['status'] == 'NOT SCORED'
    assert 'readable original duration' in eight['message']


@pytest.mark.parametrize('cell,hours', [
    ('40', 40.0), (' 8.5 ', 8.5), ('0', 0.0), ('', None), (None, None),
    ('unknown', None), ('nan', None), ('inf', None), ('1,000', None),
])
def test_readable_hours(cell, hours):
    assert _readable_hours(cell) == hours


# ── Round 2, the other review's findings ───────────────────────────────────

def test_a_duplicated_id_with_a_blank_duration_is_disclosed_once():
    """#8: an activity whose Activity ID is ambiguous AND whose duration is
    blank was listed both as 'read on the current duration' and as 'left out
    for no duration'. It was never read, so it is disclosed only as blank."""
    from config_profiles import get_profile
    tasks = [
        {'task_id': '1', 'task_code': 'X1', 'task_type': 'TT_Task', 'status_code': 'TK_NotStart',
         'target_drtn_hr_cnt': '', 'clndr_id': ''},
        {'task_id': '2', 'task_code': 'X2', 'task_type': 'TT_Task', 'status_code': 'TK_NotStart',
         'target_drtn_hr_cnt': '40', 'clndr_id': ''},
    ]
    sev, pct, thr, msg, det = dcma14._check_08_high_duration(
        tasks, {}, get_profile('commercial'), baseline_basis={'days': {}, 'ambiguous': {'X1'}})
    assert det['blank_duration_left_out'] == ['X1']
    assert det['ambiguous_left_out'] == []
    assert det['counts']['den'] == 1
