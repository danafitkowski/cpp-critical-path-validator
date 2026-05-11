#!/usr/bin/env python3
"""Smoke tests for cp_validator.

Run with: python tests/test_cp_validator.py

Builds tiny synthetic XER data in memory and runs the validator against it.
"""
import os
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, '..', 'scripts'))
# Optional: pick up internal _cpp_common + sibling xer-parser layout when
# this repo is run inside the CPP suite. The bundled scripts/xer_parser.py
# is the OSS-standalone fallback.
_INT_XER = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..', 'xer-parser', 'scripts'))
_INT_COMMON = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..', '_cpp_common', 'scripts'))
if os.path.isdir(_INT_XER):
    sys.path.insert(0, _INT_XER)
if os.path.isdir(_INT_COMMON):
    sys.path.insert(0, _INT_COMMON)

from xer_parser import parse_xer  # noqa: E402
from cp_validator import (  # noqa: E402
    validate_critical_path,
    generate_dashboard,
    HARD_CONSTRAINTS,
    HARD_ABSOLUTE,
    HARD_DATE,
    SOFT_CONSTRAINTS,
    PREFERENCE_CONSTRAINTS,
    CONSTRAINT_LABELS,
    CHECK_WEIGHTS,
    _hardness_tier,
)

TAB = '\t'


def _build_xer(tasks_extra=None, preds_extra=None):
    """Build a minimal valid XER with a simple A → B → C chain."""
    task_rows = tasks_extra if tasks_extra is not None else [
        ['1', 'A', 'Activity A', '1', 'W1', 'C1', 'TK_NotStart', 'TT_Task',
         '40', '40', '0', '2026-02-01 08:00', '2026-02-07 16:00', 'Y', ''],
        ['2', 'B', 'Activity B', '1', 'W1', 'C1', 'TK_NotStart', 'TT_Task',
         '40', '40', '0', '2026-02-08 08:00', '2026-02-14 16:00', 'Y', ''],
        ['3', 'C', 'Activity C', '1', 'W1', 'C1', 'TK_NotStart', 'TT_FinMile',
         '0', '0', '0', '2026-02-15 08:00', '2026-02-15 08:00', 'Y', ''],
    ]
    pred_rows = preds_extra if preds_extra is not None else [
        ['1', '2', '1', 'PR_FS', '0'],
        ['2', '3', '2', 'PR_FS', '0'],
    ]
    lines = [
        TAB.join(['ERMHDR', '24.12', '2026-01-01', 'Project', 'admin',
                  'Test', 'db', 'Project Management', 'USD']),
        TAB.join(['%T', 'PROJECT']),
        TAB.join(['%F', 'proj_id', 'proj_short_name', 'last_recalc_date',
                  'plan_end_date', 'scd_end_date']),
        TAB.join(['%R', '1', 'TEST', '2026-01-01 00:00',
                  '2026-02-15 16:00', '2026-02-15 16:00']),
        TAB.join(['%T', 'PROJWBS']),
        TAB.join(['%F', 'wbs_id', 'parent_wbs_id', 'wbs_name',
                  'wbs_short_name', 'proj_id']),
        TAB.join(['%R', 'W1', '', 'Root', 'W1', '1']),
        TAB.join(['%T', 'CALENDAR']),
        TAB.join(['%F', 'clndr_id', 'clndr_name', 'day_hr_cnt',
                  'week_hr_cnt', 'clndr_data']),
        TAB.join(['%R', 'C1', '5-Day', '8', '40', '']),
        TAB.join(['%T', 'TASK']),
        TAB.join(['%F', 'task_id', 'task_code', 'task_name', 'proj_id',
                  'wbs_id', 'clndr_id', 'status_code', 'task_type',
                  'target_drtn_hr_cnt', 'remain_drtn_hr_cnt',
                  'total_float_hr_cnt', 'target_start_date',
                  'target_end_date', 'driving_path_flag', 'cstr_type']),
    ]
    for row in task_rows:
        lines.append(TAB.join(['%R'] + row))
    lines.append(TAB.join(['%T', 'TASKPRED']))
    lines.append(TAB.join(['%F', 'task_pred_id', 'task_id', 'pred_task_id',
                           'pred_type', 'lag_hr_cnt']))
    for row in pred_rows:
        lines.append(TAB.join(['%R'] + row))
    lines.append('%E')
    return '\r\n'.join(lines) + '\r\n'


def _parse_synth(xer_text):
    with tempfile.NamedTemporaryFile('w', suffix='.xer', delete=False, encoding='utf-8') as f:
        f.write(xer_text)
        path = f.name
    try:
        return parse_xer(path)
    finally:
        os.unlink(path)


def test_constraint_taxonomy():
    """Tiered constraint sets should match P6 24.12 canonical codes."""
    assert HARD_ABSOLUTE == {'CS_MANDSTART', 'CS_MANDFIN'}
    assert HARD_DATE == {'CS_MSO', 'CS_MEO'}
    assert HARD_CONSTRAINTS == HARD_ABSOLUTE | HARD_DATE
    assert SOFT_CONSTRAINTS == {'CS_MSOA', 'CS_MSOB', 'CS_MEOA', 'CS_MEOB'}
    assert PREFERENCE_CONSTRAINTS == {'CS_ALAP'}
    # Cross-tier exclusivity
    assert HARD_ABSOLUTE.isdisjoint(HARD_DATE)
    assert HARD_CONSTRAINTS.isdisjoint(SOFT_CONSTRAINTS)
    assert HARD_CONSTRAINTS.isdisjoint(PREFERENCE_CONSTRAINTS)
    # Dead codes removed
    assert 'CS_MFOA' not in HARD_CONSTRAINTS  # not a real P6 code
    assert 'CS_FNET' not in SOFT_CONSTRAINTS  # MSP code, not P6
    # Labels still resolve
    assert CONSTRAINT_LABELS['CS_MSO'] == 'Start On'
    assert CONSTRAINT_LABELS['CS_MANDFIN'] == 'Mandatory Finish'


def test_hardness_tier_helper():
    assert _hardness_tier('CS_MANDSTART') == 'ABSOLUTE'
    assert _hardness_tier('CS_MANDFIN') == 'ABSOLUTE'
    assert _hardness_tier('CS_MSO') == 'DATE'
    assert _hardness_tier('CS_MEO') == 'DATE'
    assert _hardness_tier('CS_MSOA') == 'SOFT'
    assert _hardness_tier('CS_ALAP') == 'PREFERENCE'
    assert _hardness_tier('CS_BOGUS') is None
    assert _hardness_tier('') is None


def test_mandatory_constraint_gets_absolute_recommendation():
    """CS_MANDSTART on a CP activity produces the 'overrides logic' prose."""
    tasks = [
        ['1', 'A', 'A', '1', 'W1', 'C1', 'TK_NotStart', 'TT_Task',
         '40', '40', '0', '2026-02-01 08:00', '2026-02-07 16:00', 'Y', 'CS_MANDSTART'],
        ['2', 'B', 'B', '1', 'W1', 'C1', 'TK_NotStart', 'TT_FinMile',
         '0', '0', '0', '2026-02-10 08:00', '2026-02-10 08:00', 'Y', ''],
    ]
    preds = [['1', '2', '1', 'PR_FS', '0']]
    data = _parse_synth(_build_xer(tasks, preds))
    results = validate_critical_path(data)
    recs = [r for r in results['recommendations'] if r['category'] == 'Constraint-Driven CP']
    assert recs, 'expected at least one Constraint-Driven CP recommendation'
    r = recs[0]
    assert 'OVERRIDES network logic' in r['recommendation']
    assert 'Mandatory (overrides logic)' in r['finding']


def test_date_constraint_gets_date_recommendation():
    """CS_MSO produces the 'pins the activity to a specific date' prose."""
    tasks = [
        ['1', 'A', 'A', '1', 'W1', 'C1', 'TK_NotStart', 'TT_Task',
         '40', '40', '0', '2026-02-01 08:00', '2026-02-07 16:00', 'Y', 'CS_MSO'],
        ['2', 'B', 'B', '1', 'W1', 'C1', 'TK_NotStart', 'TT_FinMile',
         '0', '0', '0', '2026-02-10 08:00', '2026-02-10 08:00', 'Y', ''],
    ]
    preds = [['1', '2', '1', 'PR_FS', '0']]
    data = _parse_synth(_build_xer(tasks, preds))
    results = validate_critical_path(data)
    recs = [r for r in results['recommendations'] if r['category'] == 'Constraint-Driven CP']
    assert recs
    r = recs[0]
    assert 'pins the activity to a specific date' in r['recommendation']
    assert 'Hard date pin' in r['finding']
    # Must NOT use the mandatory prose
    assert 'OVERRIDES network logic' not in r['recommendation']


def test_basic_validation_clean_schedule():
    """A clean 3-activity chain should produce GREEN ratings and populate a CP."""
    data = _parse_synth(_build_xer())
    results = validate_critical_path(data)
    assert results['total_activities'] == 3
    assert len(results['critical_path_activities']) >= 2  # A and B at TF=0
    assert 'cp_identification' in results['checks']
    assert 'score' in results['checks']['cp_identification']
    assert results['overall_score'] > 0


def test_hard_constraint_on_cp_raises_alarm():
    """A CS_MANDSTART on a CP activity should be flagged by CHECK 2."""
    tasks = [
        ['1', 'A', 'A', '1', 'W1', 'C1', 'TK_NotStart', 'TT_Task',
         '40', '40', '0', '2026-02-01 08:00', '2026-02-07 16:00', 'Y', 'CS_MANDSTART'],
        ['2', 'B', 'B', '1', 'W1', 'C1', 'TK_NotStart', 'TT_FinMile',
         '0', '0', '0', '2026-02-10 08:00', '2026-02-10 08:00', 'Y', ''],
    ]
    preds = [['1', '2', '1', 'PR_FS', '0']]
    data = _parse_synth(_build_xer(tasks, preds))
    results = validate_critical_path(data)
    cstr_check = results['checks']['constraint_driven']
    assert cstr_check['cp_constrained'] >= 1
    # Must have a recommendation about the hard constraint
    has_constraint_rec = any(
        r['category'] == 'Constraint-Driven CP'
        for r in results['recommendations']
    )
    assert has_constraint_rec


def test_soft_constraint_not_flagged_as_hard():
    """CS_MSOA is soft and must not be counted in cp_constrained."""
    tasks = [
        ['1', 'A', 'A', '1', 'W1', 'C1', 'TK_NotStart', 'TT_Task',
         '40', '40', '0', '2026-02-01 08:00', '2026-02-07 16:00', 'Y', 'CS_MSOA'],
        ['2', 'B', 'B', '1', 'W1', 'C1', 'TK_NotStart', 'TT_FinMile',
         '0', '0', '0', '2026-02-10 08:00', '2026-02-10 08:00', 'Y', ''],
    ]
    preds = [['1', '2', '1', 'PR_FS', '0']]
    data = _parse_synth(_build_xer(tasks, preds))
    results = validate_critical_path(data)
    assert results['checks']['constraint_driven']['cp_constrained'] == 0


def test_constraint_breakdown_uses_readable_labels():
    tasks = [
        ['1', 'A', 'A', '1', 'W1', 'C1', 'TK_NotStart', 'TT_Task',
         '40', '40', '0', '2026-02-01 08:00', '2026-02-07 16:00', 'Y', 'CS_MSO'],
        ['2', 'B', 'B', '1', 'W1', 'C1', 'TK_NotStart', 'TT_FinMile',
         '0', '0', '0', '2026-02-10 08:00', '2026-02-10 08:00', 'Y', 'CS_MEO'],
    ]
    preds = [['1', '2', '1', 'PR_FS', '0']]
    data = _parse_synth(_build_xer(tasks, preds))
    results = validate_critical_path(data)
    breakdown = results['checks']['constraint_driven']['constraint_breakdown']
    assert 'Start On' in breakdown
    assert 'Finish On' in breakdown
    assert 'CS_MSO' not in breakdown  # raw codes should not appear


def test_cp_identification_is_scored():
    """Check 1 must contribute to the weighted overall score."""
    assert 'cp_identification' in CHECK_WEIGHTS
    assert CHECK_WEIGHTS['cp_identification'] > 0
    # Sum of all weights should be ~1.0
    total_weight = sum(CHECK_WEIGHTS.values())
    assert abs(total_weight - 1.0) < 0.001, f'CHECK_WEIGHTS sum to {total_weight}, not 1.0'


def test_all_9_checks_contribute_to_rating():
    """Every rendered check must have a score and weight — no drift allowed.

    Dashboard shows 9 checks; CHECK_WEIGHTS must cover all 9 so a red rating
    on any one of them can move the overall confidence number. This guards
    against the 'constraint_saturation had no score' class of bug.
    """
    expected = {
        'cp_identification', 'constraint_driven', 'open_ends_cp',
        'relationship_quality', 'lag_issues', 'logic_continuity',
        'near_critical', 'out_of_sequence', 'constraint_saturation',
    }
    assert set(CHECK_WEIGHTS.keys()) == expected, \
        f'CHECK_WEIGHTS mismatch. Missing: {expected - set(CHECK_WEIGHTS)}, Extra: {set(CHECK_WEIGHTS) - expected}'


def test_constraint_saturation_is_scored_and_weighted():
    """A schedule with high constraint density must reduce the overall score."""
    # Build two tasks both with hard constraints → 100% saturation → RED
    tasks = [
        ['1', 'A', 'A', '1', 'W1', 'C1', 'TK_NotStart', 'TT_Task',
         '40', '40', '0', '2026-02-01 08:00', '2026-02-07 16:00', 'Y', 'CS_MANDSTART'],
        ['2', 'B', 'B', '1', 'W1', 'C1', 'TK_NotStart', 'TT_FinMile',
         '0', '0', '0', '2026-02-10 08:00', '2026-02-10 08:00', 'Y', 'CS_MANDFIN'],
    ]
    preds = [['1', '2', '1', 'PR_FS', '0']]
    data = _parse_synth(_build_xer(tasks, preds))
    results = validate_critical_path(data)
    cs = results['checks']['constraint_saturation']
    assert 'score' in cs, 'constraint_saturation must carry a score'
    assert cs['rating'] == 'RED'
    assert cs['score'] == 30


def test_constraint_labels_imported_not_duplicated():
    """CONSTRAINT_LABELS must be the same object as xer_parser.CONSTRAINT_TYPES."""
    from xer_parser import CONSTRAINT_TYPES as PARSER_LABELS
    assert CONSTRAINT_LABELS is PARSER_LABELS, \
        'CONSTRAINT_LABELS should be imported from xer_parser, not duplicated locally'


def test_open_end_priority_asymmetry():
    """Missing successor = High, missing predecessor = Medium. Documented asymmetry."""
    tasks = [
        # A: no predecessor (but not critical — give it a big float)
        ['1', 'A', 'A', '1', 'W1', 'C1', 'TK_NotStart', 'TT_Task',
         '40', '40', '160', '2026-02-01 08:00', '2026-02-07 16:00', 'N', ''],
        # B: a critical activity with both predecessor (A via FS) and a successor
        ['2', 'B', 'B', '1', 'W1', 'C1', 'TK_NotStart', 'TT_Task',
         '40', '40', '0', '2026-02-08 08:00', '2026-02-14 16:00', 'Y', ''],
        # C: finish milestone — terminal, not counted as open end
        ['3', 'C', 'C', '1', 'W1', 'C1', 'TK_NotStart', 'TT_FinMile',
         '0', '0', '0', '2026-02-15 08:00', '2026-02-15 08:00', 'Y', ''],
        # D: orphan activity with no predecessor AND no successor, not critical
        ['4', 'D', 'D', '1', 'W1', 'C1', 'TK_NotStart', 'TT_Task',
         '40', '40', '160', '2026-03-01 08:00', '2026-03-07 16:00', 'N', ''],
    ]
    preds = [
        ['1', '2', '1', 'PR_FS', '0'],
        ['2', '3', '2', 'PR_FS', '0'],
    ]
    data = _parse_synth(_build_xer(tasks, preds))
    results = validate_critical_path(data)
    # D has no pred AND no succ → expect Medium for pred, High for succ
    rec_by_finding = {}
    for r in results['recommendations']:
        rec_by_finding.setdefault(r['category'], []).append(r)
    open_end_recs = rec_by_finding.get('Open Ends', [])
    has_medium_pred = any(r['priority'] == 'Medium' and 'predecessor' in r['finding'].lower()
                          for r in open_end_recs)
    has_high_succ = any(r['priority'] == 'High' and 'successor' in r['finding'].lower()
                        for r in open_end_recs)
    assert has_medium_pred, 'Missing predecessor should be priority Medium'
    assert has_high_succ, 'Missing successor should be priority High'


def test_dashboard_generates():
    data = _parse_synth(_build_xer())
    results = validate_critical_path(data)
    out = tempfile.mktemp(suffix='.html')
    try:
        generate_dashboard(results, out)
        assert os.path.exists(out)
        assert os.path.getsize(out) > 2000  # non-trivial HTML
        with open(out, encoding='utf-8') as f:
            content = f.read()
        assert 'Critical Path Validation Report' in content
        assert 'CP Confidence Score' in content
    finally:
        if os.path.exists(out):
            os.unlink(out)


def test_empty_data_date_renders_gracefully():
    data = _parse_synth(_build_xer())
    results = validate_critical_path(data)
    results['data_date'] = ''  # force empty
    out = tempfile.mktemp(suffix='.html')
    try:
        generate_dashboard(results, out)
        with open(out, encoding='utf-8') as f:
            content = f.read()
        assert '(not set)' in content
    finally:
        if os.path.exists(out):
            os.unlink(out)


def test_status_constants_imported_not_duplicated():
    """COMPLETE_STATUS/ACTIVE_STATUS/NOT_STARTED_STATUS come from xer_parser."""
    import xer_parser as xp
    from cp_validator import (
        COMPLETE_STATUS as CP_COMPLETE,
        ACTIVE_STATUS as CP_ACTIVE,
        NOT_STARTED_STATUS as CP_NOT_STARTED,
    )
    assert CP_COMPLETE is xp.COMPLETE_STATUS
    assert CP_ACTIVE is xp.ACTIVE_STATUS
    assert CP_NOT_STARTED is xp.NOT_STARTED_STATUS
    assert CP_COMPLETE == 'TK_Complete'
    assert CP_ACTIVE == 'TK_Active'
    assert CP_NOT_STARTED == 'TK_NotStart'


def test_task_type_sets_imported_from_xer_parser():
    """MILESTONE_TASK_TYPES and EXCLUDED_TASK_TYPES come from xer_parser."""
    import xer_parser as xp
    from cp_validator import (
        MILESTONE_TASK_TYPES as CP_MILES,
        EXCLUDED_TASK_TYPES as CP_EXCL,
        LOE_TYPES,
    )
    assert CP_MILES is xp.MILESTONE_TASK_TYPES
    assert CP_EXCL is xp.EXCLUDED_TASK_TYPES
    # LOE_TYPES is a back-compat alias for EXCLUDED_TASK_TYPES, not a separate copy.
    assert LOE_TYPES is xp.EXCLUDED_TASK_TYPES


def test_lpm_confirmed_false_cp_in_check2():
    """Check 2 must surface LPM-confirmed false-CP candidates.

    Scenario: activity A has TF=0 (P6 pre-computed, set via total_float_hr_cnt=0)
    but is on a short parallel branch, not the longest path. Activity C is the
    true CP terminal. The LPM divergence should flag A as only_TFM and Check 2
    must carry 'lpm_confirmed_false_cp' with A's task_id.

    We achieve this by:
      - Two chains ending at milestone D:
          A(0h remain) → D     ← A has TF=0 in XER but zero duration
          B(40h) → C(40h) → D  ← B+C is the longest path
      - All activities get total_float_hr_cnt=0 so TFM flags all.
      - LPM will flag B, C, D on the longest path (80h total) but NOT A (0h branch).

    Skip condition: the LPM cross-check requires the sibling `cpp-cpm-engine`
    package (`cpm` module) on sys.path. The README documents it as optional —
    the validator gracefully degrades when the engine is unavailable. CI here
    runs the validator stand-alone, so if `cpm` isn't importable we skip
    rather than fail (the validator's no-engine fallback is exercised by
    other tests, and the LPM-confirmation contract is exercised inside the
    internal _deploy tree where `cpm` IS bundled).
    """
    try:
        import cpm  # noqa: F401
    except ImportError:
        import pytest as _pytest
        _pytest.skip(
            "cpp-cpm-engine (`cpm` module) not on sys.path — LPM cross-check "
            "is documented as optional; stand-alone OSS CI cannot exercise it"
        )
    tasks = [
        # task_id, task_code, task_name, proj_id, wbs_id, clndr_id,
        # status_code, task_type, target_drtn_hr_cnt, remain_drtn_hr_cnt,
        # total_float_hr_cnt, target_start_date, target_end_date,
        # driving_path_flag, cstr_type
        ['1', 'A', 'Activity A', '1', 'W1', 'C1', 'TK_NotStart', 'TT_Task',
         '0', '0', '0', '2026-02-01 08:00', '2026-02-01 08:00', 'Y', ''],
        ['2', 'B', 'Activity B', '1', 'W1', 'C1', 'TK_NotStart', 'TT_Task',
         '40', '40', '0', '2026-02-01 08:00', '2026-02-07 16:00', 'Y', ''],
        ['3', 'C', 'Activity C', '1', 'W1', 'C1', 'TK_NotStart', 'TT_Task',
         '40', '40', '0', '2026-02-08 08:00', '2026-02-14 16:00', 'Y', ''],
        ['4', 'D', 'Milestone D', '1', 'W1', 'C1', 'TK_NotStart', 'TT_FinMile',
         '0', '0', '0', '2026-02-14 16:00', '2026-02-14 16:00', 'Y', ''],
    ]
    preds = [
        ['1', '4', '1', 'PR_FS', '0'],   # A → D
        ['2', '3', '2', 'PR_FS', '0'],   # B → C
        ['3', '4', '3', 'PR_FS', '0'],   # C → D
    ]
    data = _parse_synth(_build_xer(tasks, preds))
    results = validate_critical_path(data)

    cstr_check = results['checks']['constraint_driven']

    # lpm_confirmed_false_cp key must exist
    assert 'lpm_confirmed_false_cp' in cstr_check, (
        'constraint_driven check must carry lpm_confirmed_false_cp key'
    )

    # A (task_id='1') should be in the confirmed list because it has TF=0
    # but is not on the longest path (B→C→D = 80h, A is 0h).
    confirmed = cstr_check['lpm_confirmed_false_cp']
    assert '1' in confirmed, (
        f'Expected task_id "1" (Activity A) in lpm_confirmed_false_cp. '
        f'Got: {confirmed}'
    )

    # A recommendation for A must use the LPM-confirmation language.
    lpm_recs = [
        r for r in results['recommendations']
        if 'LPM-confirmed' in r.get('finding', '')
    ]
    assert lpm_recs, (
        'Expected at least one recommendation with "LPM-confirmed" in finding'
    )
    # The recommendation must reference AACE 49R-06
    assert any('AACE 49R-06' in r['finding'] for r in lpm_recs), (
        'LPM-confirmed recommendation must cite AACE 49R-06'
    )


def test_no_hardcoded_status_or_task_type_literals_in_source():
    """Guard against reintroducing hardcoded 'TK_*' / 'TT_Mile' / 'TT_FinMile'
    literals. These must flow through the imported constants so schemas stay
    in sync with xer_parser.
    """
    import os
    src_path = os.path.join(SCRIPT_DIR, '..', 'scripts', 'cp_validator.py')
    with open(src_path, encoding='utf-8') as f:
        src = f.read()
    # These quoted literals must NOT appear outside of the tiered-constraint
    # code sets at the top of the file (those are real P6 codes, not status
    # or task-type strings, so they can't collide). We scan simply.
    # Strings we do not want to see in any runtime code path:
    banned = ["'TK_Complete'", "'TK_Active'", "'TK_NotStart'"]
    for needle in banned:
        assert needle not in src, (
            f'Found hardcoded {needle} in cp_validator.py — use the '
            f'imported *_STATUS constant instead')
    # Task-type tuple literal should not be rebuilt inline; use MILESTONE_TASK_TYPES
    assert "('TT_Mile', 'TT_FinMile')" not in src, (
        "Inline milestone tuple literal found — use MILESTONE_TASK_TYPES")
    assert "('TT_FinMile', 'TT_Mile')" not in src
    # LOE_TYPES should not be locally rebuilt as a set literal.
    assert "LOE_TYPES = {'TT_LOE', 'TT_WBS'}" not in src, (
        "Local LOE_TYPES set literal found — alias EXCLUDED_TASK_TYPES instead")


def test_longest_path_reads_crt_path_num_not_hallucinated_field():
    """cp_validator reads P6's `crt_path_num` (the real longest-path flag),
    NOT a hallucinated `longest_path` TASK field."""
    import os
    src_path = os.path.join(SCRIPT_DIR, '..', 'scripts', 'cp_validator.py')
    with open(src_path, encoding='utf-8') as f:
        src = f.read()
    assert "t.get('crt_path_num'" in src, (
        'longest-path lookup should call t.get(\'crt_path_num\', ...)')
    assert "t.get('longest_path'" not in src, (
        'P6 has no TASK field named `longest_path` — should be `crt_path_num`')

    # And when we run the validator on a task with crt_path_num set, that
    # value flows through to the CP activity record.
    tasks = [
        ['1', 'A', 'A', '1', 'W1', 'C1', 'TK_NotStart', 'TT_Task',
         '40', '40', '0', '2026-02-01 08:00', '2026-02-07 16:00', 'Y', ''],
        ['2', 'B', 'B', '1', 'W1', 'C1', 'TK_NotStart', 'TT_FinMile',
         '0', '0', '0', '2026-02-10 08:00', '2026-02-10 08:00', 'Y', ''],
    ]
    preds = [['1', '2', '1', 'PR_FS', '0']]
    # We need to inject crt_path_num. Build a custom XER with that field.
    lines = [
        TAB.join(['ERMHDR', '24.12', '2026-01-01', 'Project', 'admin',
                  'Test', 'db', 'Project Management', 'USD']),
        TAB.join(['%T', 'PROJECT']),
        TAB.join(['%F', 'proj_id', 'proj_short_name', 'last_recalc_date',
                  'plan_end_date', 'scd_end_date']),
        TAB.join(['%R', '1', 'TEST', '2026-01-01 00:00',
                  '2026-02-15 16:00', '2026-02-15 16:00']),
        TAB.join(['%T', 'PROJWBS']),
        TAB.join(['%F', 'wbs_id', 'parent_wbs_id', 'wbs_name',
                  'wbs_short_name', 'proj_id']),
        TAB.join(['%R', 'W1', '', 'Root', 'W1', '1']),
        TAB.join(['%T', 'CALENDAR']),
        TAB.join(['%F', 'clndr_id', 'clndr_name', 'day_hr_cnt',
                  'week_hr_cnt', 'clndr_data']),
        TAB.join(['%R', 'C1', '5-Day', '8', '40', '']),
        TAB.join(['%T', 'TASK']),
        TAB.join(['%F', 'task_id', 'task_code', 'task_name', 'proj_id',
                  'wbs_id', 'clndr_id', 'status_code', 'task_type',
                  'target_drtn_hr_cnt', 'remain_drtn_hr_cnt',
                  'total_float_hr_cnt', 'target_start_date',
                  'target_end_date', 'driving_path_flag', 'cstr_type',
                  'crt_path_num']),
        TAB.join(['%R', '1', 'A', 'A', '1', 'W1', 'C1', 'TK_NotStart',
                  'TT_Task', '40', '40', '0', '2026-02-01 08:00',
                  '2026-02-07 16:00', 'Y', '', '1']),
        TAB.join(['%R', '2', 'B', 'B', '1', 'W1', 'C1', 'TK_NotStart',
                  'TT_FinMile', '0', '0', '0', '2026-02-10 08:00',
                  '2026-02-10 08:00', 'Y', '', '1']),
        TAB.join(['%T', 'TASKPRED']),
        TAB.join(['%F', 'task_pred_id', 'task_id', 'pred_task_id',
                  'pred_type', 'lag_hr_cnt']),
        TAB.join(['%R', '1', '2', '1', 'PR_FS', '0']),
        '%E',
    ]
    xer_text = '\r\n'.join(lines) + '\r\n'
    data = _parse_synth(xer_text)
    results = validate_critical_path(data)
    assert results['critical_path_activities'], 'expected CP activities'
    # At least one CP activity should have a nonempty longest_path value (the
    # crt_path_num we set = '1').
    lp_values = [a['longest_path'] for a in results['critical_path_activities']]
    assert '1' in lp_values, f'expected crt_path_num to flow into longest_path, got {lp_values}'


def test_oos_details_not_silently_truncated():
    """CPP forensic-correctness rule: never truncate findings without disclosure. When we have
    25 OOS pairs, all 25 must appear in oos_details (no [:20] cap)."""
    # Build: activity 0 active, with 25 SS-predecessors that have never started.
    # That produces 25 OOS pairs on activity 0.
    N = 25
    task_rows = []
    # Central active task (id 100)
    task_rows.append(['100', 'X', 'Central active', '1', 'W1', 'C1',
                      'TK_Active', 'TT_Task', '40', '40', '0',
                      '2026-02-01 08:00', '2026-02-07 16:00', 'Y', ''])
    # N predecessors, not started
    for i in range(1, N + 1):
        task_rows.append([str(i), f'P{i}', f'Pred {i}', '1', 'W1', 'C1',
                          'TK_NotStart', 'TT_Task', '40', '40', '80',
                          '2026-02-01 08:00', '2026-02-07 16:00', 'N', ''])
    # Terminal milestone
    task_rows.append(['999', 'F', 'Finish', '1', 'W1', 'C1',
                      'TK_NotStart', 'TT_FinMile', '0', '0', '0',
                      '2026-02-10 08:00', '2026-02-10 08:00', 'Y', ''])
    # Preds: each P_i → X as SS
    pred_rows = []
    for i in range(1, N + 1):
        pred_rows.append([str(i), '100', str(i), 'PR_SS', '0'])
    # Finish successor
    pred_rows.append([str(N + 1), '999', '100', 'PR_FS', '0'])
    data = _parse_synth(_build_xer(task_rows, pred_rows))
    results = validate_critical_path(data)
    oos = results['checks']['out_of_sequence']
    assert oos['oos_count'] == N, f'expected {N} OOS pairs, got {oos["oos_count"]}'
    assert len(oos['oos_details']) == N, (
        f'oos_details should carry all {N} pairs (no silent [:20] cap); '
        f'got {len(oos["oos_details"])}')


def test_disconnected_activities_not_silently_truncated():
    """CPP forensic-correctness rule: disconnected_activities must list every finding, no [:30] cap."""
    # Build: one finish milestone, then many activities with no successors.
    # Each disconnected activity becomes a finding.
    N = 40
    task_rows = []
    # Finish milestone
    task_rows.append(['999', 'F', 'Finish', '1', 'W1', 'C1',
                      'TK_NotStart', 'TT_FinMile', '0', '0', '0',
                      '2026-02-10 08:00', '2026-02-10 08:00', 'Y', ''])
    # Activity connected to finish
    task_rows.append(['1', 'CONN', 'Connected', '1', 'W1', 'C1',
                      'TK_NotStart', 'TT_Task', '40', '40', '0',
                      '2026-02-01 08:00', '2026-02-07 16:00', 'Y', ''])
    # N disconnected activities (no successor to finish)
    for i in range(2, N + 2):
        task_rows.append([str(i), f'D{i}', f'Disc {i}', '1', 'W1', 'C1',
                          'TK_NotStart', 'TT_Task', '40', '40', '160',
                          '2026-03-01 08:00', '2026-03-07 16:00', 'N', ''])
    pred_rows = [['1', '999', '1', 'PR_FS', '0']]
    data = _parse_synth(_build_xer(task_rows, pred_rows))
    results = validate_critical_path(data)
    lc = results['checks']['logic_continuity']
    # Every disconnected activity must appear — no silent truncation at 30
    assert lc['disconnected_count'] >= N, (
        f'expected >= {N} disconnected, got {lc["disconnected_count"]}')
    assert len(lc['disconnected_activities']) == lc['disconnected_count'], (
        f'disconnected_activities should have all {lc["disconnected_count"]} '
        f'entries (no silent [:30] cap); got {len(lc["disconnected_activities"])}')


def test_oos_detects_ss_violation():
    """An SS predecessor that hasn't started while successor is active is OOS."""
    tasks = [
        # A is not started, B is active — SS relationship violated
        ['1', 'A', 'A', '1', 'W1', 'C1', 'TK_NotStart', 'TT_Task',
         '40', '40', '0', '2026-02-01 08:00', '2026-02-07 16:00', 'Y', ''],
        ['2', 'B', 'B', '1', 'W1', 'C1', 'TK_Active', 'TT_Task',
         '40', '40', '0', '2026-02-01 08:00', '2026-02-07 16:00', 'Y', ''],
        ['3', 'C', 'C', '1', 'W1', 'C1', 'TK_NotStart', 'TT_FinMile',
         '0', '0', '0', '2026-02-10 08:00', '2026-02-10 08:00', 'Y', ''],
    ]
    preds = [
        ['1', '2', '1', 'PR_SS', '0'],   # B starts with A — violated
        ['2', '3', '2', 'PR_FS', '0'],
    ]
    data = _parse_synth(_build_xer(tasks, preds))
    results = validate_critical_path(data)
    oos = results['checks']['out_of_sequence']
    assert oos['oos_count'] >= 1


if __name__ == '__main__':
    tests = [
        test_constraint_taxonomy,
        test_hardness_tier_helper,
        test_basic_validation_clean_schedule,
        test_hard_constraint_on_cp_raises_alarm,
        test_soft_constraint_not_flagged_as_hard,
        test_mandatory_constraint_gets_absolute_recommendation,
        test_date_constraint_gets_date_recommendation,
        test_constraint_breakdown_uses_readable_labels,
        test_cp_identification_is_scored,
        test_all_9_checks_contribute_to_rating,
        test_constraint_saturation_is_scored_and_weighted,
        test_constraint_labels_imported_not_duplicated,
        test_status_constants_imported_not_duplicated,
        test_task_type_sets_imported_from_xer_parser,
        test_no_hardcoded_status_or_task_type_literals_in_source,
        test_longest_path_reads_crt_path_num_not_hallucinated_field,
        test_oos_details_not_silently_truncated,
        test_disconnected_activities_not_silently_truncated,
        test_open_end_priority_asymmetry,
        test_dashboard_generates,
        test_empty_data_date_renders_gracefully,
        test_oos_detects_ss_violation,
    ]
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
