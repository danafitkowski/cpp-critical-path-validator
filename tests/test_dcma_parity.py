#!/usr/bin/env python3
"""DCMA parity (7 November 2026): the validator against the shared fixtures of
CPP's written DCMA-14 definition.

The definition (version 1) is at
https://criticalpathpartners.ca/dcma-14-definition.html; a copy,
DCMA_DEFINITION.md, and its constants, dcma_definition.json, are in
tests/fixtures/dcma_parity/ with the fixtures: synthetic schedules and
expected.json, the results that text gives, worked out by hand. Every CPP tool
that reports a DCMA-14 result is tested against the same files. This
repository scores every check, so every listed check is compared: status,
and the numerator and denominator where the fixture lists them (#13 on its
CPLI value, to 0.01). One case per (fixture, check), so a failure names both.

The constants scripts/dcma14.py mirrors from dcma_definition.json are checked
against that file at the bottom.
"""
import json
import os
import sys

import pytest

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, '..', 'scripts'))

import dcma14  # noqa: E402
from dcma14 import dcma_14_assess  # noqa: E402
from xer_parser import parse_xer  # noqa: E402

# #12's 600-day test runs where CPP's CPM engine imports and this copy of the
# validator builds the recalculation network (this repository does not, even
# with the public engine beside it).
from critical_path_test import can_run as _cpt_can_run  # noqa: E402
HAVE_ENGINE = _cpt_can_run()

FIXTURES = os.path.join(SCRIPT_DIR, 'fixtures', 'dcma_parity')
DEFINITION_JSON = os.path.join(FIXTURES, 'dcma_definition.json')
EXPECTED_JSON = os.path.join(FIXTURES, 'expected.json')

CHECK_IDS = {
    1: 'DCMA-01-Logic', 2: 'DCMA-02-Leads', 3: 'DCMA-03-Lags',
    4: 'DCMA-04-Relationship', 5: 'DCMA-05-Hard', 6: 'DCMA-06-HighFloat',
    7: 'DCMA-07-NegFloat', 8: 'DCMA-08-HighDuration', 9: 'DCMA-09-InvalidDates',
    10: 'DCMA-10-Resources', 11: 'DCMA-11-MissedTasks',
    12: 'DCMA-12-CriticalPathTest', 13: 'DCMA-13-CPLI', 14: 'DCMA-14-BEI',
}
STATUS = {'PASS': 'PASS', 'FAIL': 'FAIL', 'NS': 'NOT SCORED'}

with open(EXPECTED_JSON, encoding='utf-8') as _fh:
    EXPECTED = json.load(_fh)
CASES = [(name, int(n)) for name, fx in EXPECTED.items() for n in fx['checks']]
_RESULTS = {}


def _result(name):
    """dcma_14_assess on one fixture pair, run once per fixture."""
    if name not in _RESULTS:
        fx = EXPECTED[name]
        current = parse_xer(os.path.join(FIXTURES, fx['current']))
        baseline = (parse_xer(os.path.join(FIXTURES, fx['baseline']))
                    if fx.get('baseline') else None)
        _RESULTS[name] = dcma_14_assess(current, baseline_data=baseline)
    return _RESULTS[name]


def test_every_fixture_file_is_present():
    for fx in EXPECTED.values():
        for key in ('current', 'baseline'):
            if fx.get(key):
                assert os.path.isfile(os.path.join(FIXTURES, fx[key])), fx[key]
    assert len(CASES) >= 40, CASES


@pytest.mark.parametrize('fixture,check', CASES,
                         ids=['%s-#%d' % c for c in CASES])
def test_parity(fixture, check):
    want = EXPECTED[fixture]['checks'][str(check)]
    pc = _result(fixture)['per_check'][CHECK_IDS[check]]
    got = pc['counts']
    where = f'{fixture} #{check}: {pc["message"]}'
    expect = want['status']
    # A #12 result the 600-day test decides (by: 'test') needs the test, which
    # this repository cannot run; here it is NOT SCORED.
    if want.get('by') == 'test' and not HAVE_ENGINE:
        expect = 'NS'
    assert got['status'] == STATUS[expect], (got, where)
    for key in ('num', 'den'):
        if key in want:
            assert got[key] == want[key], (key, got, want, where)
    if 'value' in want:
        assert got['value'] is not None and abs(got['value'] - want['value']) <= 0.01, (
            got, want, where)


@pytest.mark.parametrize('fixture', sorted(EXPECTED))
def test_every_check_carries_counts_that_agree_with_its_severity(fixture):
    """Every check of every fixture, listed or not: the counts block is there,
    its status agrees with the severity (INFO is NOT SCORED, PASS is PASS,
    WARN/BLOCK is FAIL), and the score is passed / scored."""
    result = _result(fixture)
    passed = scored = 0
    for cid in CHECK_IDS.values():
        pc = result['per_check'][cid]
        c = pc['counts']
        assert set(c) == {'status', 'num', 'den', 'value'}, (cid, c)
        sev = pc['severity']
        want = 'NOT SCORED' if sev == 'INFO' else 'PASS' if sev == 'PASS' else 'FAIL'
        assert c['status'] == want, (cid, sev, c)
        if c['status'] == 'NOT SCORED':
            assert (c['num'], c['den'], c['value']) == (None, None, None), (cid, c)
        else:
            scored += 1
            passed += c['status'] == 'PASS'
    assert (result['dcma_score'], result['dcma_max']) == (passed, scored)


def test_p9_discloses_the_data_date_it_read():
    """p9's data date is blank, so P6 (and parse_xer) read the planned start;
    the result and #9, which compares against it, say so. Its activity filed
    under a project ID no PROJECT row carries is read (one project, read
    whole)."""
    result = _result('p9_data_date')
    assert result['data_date_filled']['filled_from'] == 'plan_start_date', result['data_date_filled']
    assert result['data_date'] == result['data_date_filled']['last_recalc_date']
    nine = result['per_check']['DCMA-09-InvalidDates']
    assert "data date read is the project's planned start" in nine['message'], nine['message']
    assert result['projects_in_file'] == 1


def test_the_scorecard_shows_each_result_with_its_counts():
    html = dcma14.render_dcma_scorecard_html(_result('p2_activities'))
    assert 'FAIL (2 of 10)' in html          # #5
    assert 'NOT SCORED' in html              # #12
    assert 'Not scored on this file' in html


# ─────────────────────────────────────────────────────────────────────
# The constants dcma14 mirrors from dcma_definition.json
# ─────────────────────────────────────────────────────────────────────

def _definition():
    with open(DEFINITION_JSON, encoding='utf-8') as fh:
        return json.load(fh)


def test_the_mirrored_constants_match_the_definition_file():
    d = _definition()
    assert dcma14.DCMA_DEFINITION_VERSION == d['version']
    assert set(dcma14.DCMA_MILESTONE_TYPES) == set(d['milestone_types'])
    assert set(dcma14.DCMA_EXCLUDED_TYPES) == set(d['excluded_types'])
    assert dcma14.COMPLETE_STATUS == d['complete_status']
    assert set(dcma14.DCMA_HARD_CONSTRAINTS) == set(d['hard_constraints'])
    assert set(dcma14.DCMA_MANDATORY_CONSTRAINTS) == set(d['mandatory_constraints'])
    assert set(dcma14.CPLI_DEADLINE_CONSTRAINTS) == set(d['deadline_constraints'])
    assert dcma14.FALLBACK_HOURS_PER_DAY == d['fallback_hours_per_day']
    th = d['thresholds']
    assert dcma14.MISSED_TASKS_MIN_MATCH_PCT == th['11']['min_match_pct']
    assert dcma14.DCMA_RESOURCES_MIN_PCT == th['10']['min_pct']
    assert dcma14.DCMA_RESOURCES_MIN_DURATION_DAYS == th['10']['min_duration_working_days']
    assert dcma14.LONG_LAG_INFO_DAYS == th['3']['info_lag_working_days']
    mirrored = {n: dict(pairs) for n, pairs in dcma14.DEFINITION_THRESHOLDS.items()}
    assert mirrored[1]['dcma_logic_max_missing_pct'] == th['1']['max_pct']
    assert mirrored[2]['dcma_leads_max_count'] == th['2']['max_count']
    assert mirrored[3]['dcma_lags_max_pct'] == th['3']['max_pct']
    assert mirrored[4]['dcma_fs_min_pct'] == th['4']['min_fs_pct']
    assert mirrored[5]['dcma_hard_constraints_max_pct'] == th['5']['max_pct']
    assert mirrored[6]['dcma_high_float_max_pct'] == th['6']['max_pct']
    assert mirrored[6]['dcma_high_float_max_days'] == th['6']['float_working_days']
    assert mirrored[7]['dcma_negative_float_max_count'] == th['7']['max_count']
    assert mirrored[8]['dcma_high_duration_max_pct'] == th['8']['max_pct']
    assert mirrored[8]['dcma_high_duration_max_days'] == th['8']['duration_working_days']
    assert mirrored[9]['dcma_invalid_dates_max_count'] == th['9']['max_count']
    assert mirrored[11]['dcma_missed_tasks_max_pct'] == th['11']['max_pct']
    assert mirrored[13]['dcma_cpli_min'] == th['13']['min_index']
    assert mirrored[14]['bei_min'] == th['14']['min_index']


def test_the_commercial_profile_grades_on_the_definitions_thresholds():
    """The default profile is DCMA's: every threshold dcma14 reads from it
    equals the definition's (#10 is not read from the profile at all)."""
    from config_profiles import get_profile
    prof = get_profile('commercial')
    for n, pairs in dcma14.DEFINITION_THRESHOLDS.items():
        for key, value in pairs:
            assert float(prof[key]) == float(value), (n, key, prof[key], value)


def test_every_profile_carries_the_definitions_resources_threshold():
    """#10 passes only at 100% on every profile. dcma14 grades on
    DCMA_RESOURCES_MIN_PCT; a profile that drifted from it would mislead any
    other reader of config_profiles."""
    from config_profiles import get_profile, list_profiles
    for name in list_profiles():
        assert float(get_profile(name)['dcma_resources_min_pct']) == dcma14.DCMA_RESOURCES_MIN_PCT, name
