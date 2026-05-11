#!/usr/bin/env python3
"""
Critical Path Validator & Recommendations Engine
Analyzes P6 XER schedule data to validate critical path correctness
and generate actionable recommendations.

Usage:
    from cp_validator import validate_critical_path, generate_dashboard
    results = validate_critical_path(parsed_xer_data)
    generate_dashboard(results, '/path/to/output.html')
"""

import sys
import os
from datetime import datetime

# Make xer_parser importable: first try the sibling xer-parser skill, then fall
# back to the local directory (useful when the user has copied the parser next
# to this script).
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_XER_PARSER_SCRIPTS = os.path.normpath(os.path.join(_SCRIPT_DIR, '..', '..', 'xer-parser', 'scripts'))
_CPP_COMMON_SCRIPTS = os.path.normpath(os.path.join(_SCRIPT_DIR, '..', '..', '_cpp_common', 'scripts'))
for _path in (_XER_PARSER_SCRIPTS, _CPP_COMMON_SCRIPTS, _SCRIPT_DIR):
    if os.path.isdir(_path) and _path not in sys.path:
        sys.path.insert(0, _path)

from xer_parser import (  # noqa: E402
    get_table,
    get_calendar_map,
    build_wbs_map,
    CONSTRAINT_TYPES as CONSTRAINT_LABELS,  # canonical code→label map — single source of truth
    MILESTONE_TASK_TYPES,
    EXCLUDED_TASK_TYPES,
    COMPLETE_STATUS,
    ACTIVE_STATUS,
    NOT_STARTED_STATUS,
)


# ─────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────

# P6 24.12 constraint taxonomy — three tiers of "hardness" plus a preference tier.
#   HARD_ABSOLUTE: mandatory constraints that P6 enforces regardless of logic.
#       Float calculation treats the date as immovable; predecessors finishing
#       late do not slip the constrained activity. Most dangerous to CP logic.
#       - CS_MANDSTART : Mandatory Start
#       - CS_MANDFIN   : Mandatory Finish
#   HARD_DATE: pin the activity to a specific date. Behavior under logic conflict
#       depends on P6 scheduling options (progress override vs retained logic)
#       and version, but in practice they force the date.
#       - CS_MSO : Start On
#       - CS_MEO : Finish On
#   SOFT: bound the activity in one direction only; logic still drives the
#       opposite edge.
#       - CS_MSOA / CS_MSOB : Start On or After / Before
#       - CS_MEOA / CS_MEOB : Finish On or After / Before
#   PREFERENCE: change scheduling preference without bounding dates.
#       - CS_ALAP : As Late As Possible (forces late-date scheduling)
HARD_ABSOLUTE = {'CS_MANDSTART', 'CS_MANDFIN'}
HARD_DATE = {'CS_MSO', 'CS_MEO'}
SOFT_CONSTRAINTS = {'CS_MSOA', 'CS_MSOB', 'CS_MEOA', 'CS_MEOB'}
PREFERENCE_CONSTRAINTS = {'CS_ALAP'}

# Union alias — "is this constraint hard enough to corrupt CP logic?"
# Used by Check 2 threshold logic. Rating thresholds deliberately treat
# ABSOLUTE and DATE the same; recommendation prose differentiates them.
HARD_CONSTRAINTS = HARD_ABSOLUTE | HARD_DATE


def _hardness_tier(code):
    """Return the tier string for a P6 constraint code, or None if unknown.

    'ABSOLUTE' > 'DATE' > 'SOFT' > 'PREFERENCE' in order of impact on CP logic.
    """
    if code in HARD_ABSOLUTE:
        return 'ABSOLUTE'
    if code in HARD_DATE:
        return 'DATE'
    if code in SOFT_CONSTRAINTS:
        return 'SOFT'
    if code in PREFERENCE_CONSTRAINTS:
        return 'PREFERENCE'
    return None


# CONSTRAINT_LABELS is imported above from xer_parser.CONSTRAINT_TYPES so the
# code→label mapping stays consistent across skills. If P6 introduces a new
# constraint code, add it to xer_parser only — both skills pick it up.

# LOE_TYPES kept as an alias for back-compat (imports are the single source of
# truth — do not redefine the set here; see xer_parser.EXCLUDED_TASK_TYPES).
LOE_TYPES = EXCLUDED_TASK_TYPES

RATING_GREEN = 'GREEN'
RATING_AMBER = 'AMBER'
RATING_RED = 'RED'

# Near-critical band: activities with 0 < total_float ≤ this many hours are
# treated as "near-critical" — small float disturbances would push them onto
# the CP. 80 hours = 10 working days at 8 hr/day, the conventional threshold;
# tunable per profile/contract if a project uses a different basis.
NEAR_CRITICAL_FLOAT_MAX_HRS = 80

CHECK_WEIGHTS = {
    'cp_identification': 0.05,
    'constraint_driven': 0.17,
    'open_ends_cp': 0.20,
    'relationship_quality': 0.13,
    'lag_issues': 0.15,
    'logic_continuity': 0.10,
    'near_critical': 0.10,
    'out_of_sequence': 0.05,
    'constraint_saturation': 0.05,
}


def _safe_float(val, default=999.0):
    """Safely convert a value to float."""
    try:
        return float(val) if val and str(val).strip() else default
    except (ValueError, TypeError):
        return default


def _hrs_to_days(hrs, cal_map=None, clndr_id=None):
    """Convert hours to working days using calendar if available."""
    h = _safe_float(hrs, 0)
    hrs_per_day = 8.0
    if cal_map and clndr_id:
        cal = cal_map.get(clndr_id, {})
        hpd = cal.get('hours_per_day', 8.0)
        if hpd and hpd > 0:
            hrs_per_day = hpd
    return h / hrs_per_day if hrs_per_day > 0 else 0


def _is_loe(task):
    return task.get('task_type', '') in EXCLUDED_TASK_TYPES


def _is_complete(task):
    return task.get('status_code', '') == COMPLETE_STATUS


def _is_milestone(task):
    return task.get('task_type', '') in MILESTONE_TASK_TYPES


def _get_constraints(task):
    """Return list of constraint types on a task."""
    constraints = []
    c1 = task.get('cstr_type', '')
    c2 = task.get('cstr_type2', '')
    if c1:
        constraints.append(c1)
    if c2:
        constraints.append(c2)
    return constraints


def _has_hard_constraint(task):
    return bool(set(_get_constraints(task)) & HARD_CONSTRAINTS)


# ─────────────────────────────────────────────────────────────────────
# MAIN VALIDATION FUNCTION
# ─────────────────────────────────────────────────────────────────────

def validate_critical_path(data, project_index=0, profile='commercial',
                            baseline_data=None, jurisdiction='US-FED'):
    """
    Run all critical path validation checks on parsed XER data.

    Args:
        data: Parsed XER data object from xer_parser.parse_xer()
        project_index: Which project to analyze (0 = first/primary)
        profile: DCMA threshold profile — 'commercial' (default), 'nuclear', 'mining'
        baseline_data: Optional parsed XER baseline (for DCMA BEI computation)
        jurisdiction: passed through to driver_chain_narrative manifest
            ('US-FED' / 'US-CA' / 'UK' / 'ON' / etc.). Default 'US-FED'.

    Returns:
        dict with all findings, scores, recommendations, a `dcma_14` block,
        and a `driver_chain_narrative` block (one narrative per critical
        activity, walking driving predecessors back to project start per
        AACE RP 49R-06 §6).
    """
    tasks_all = get_table(data, 'TASK')
    preds_all = get_table(data, 'TASKPRED')
    projects = get_table(data, 'PROJECT')
    cal_map = get_calendar_map(data)
    wbs_map = build_wbs_map(data)

    # Filter to target project if multi-project XER
    if projects and len(projects) > 1:
        # Find the non-dummy project (has activities)
        proj_task_counts = {}
        for t in tasks_all:
            pid = t.get('proj_id', '')
            proj_task_counts[pid] = proj_task_counts.get(pid, 0) + 1
        # Pick project with most tasks, or use index
        sorted_projs = sorted(proj_task_counts.items(), key=lambda x: -x[1])
        if sorted_projs:
            target_proj_id = sorted_projs[project_index][0]
        else:
            target_proj_id = projects[project_index]['proj_id']
    elif projects:
        target_proj_id = projects[0]['proj_id']
    else:
        target_proj_id = None

    if target_proj_id:
        tasks = [t for t in tasks_all if t.get('proj_id', '') == target_proj_id]
        project = next((p for p in projects if p.get('proj_id', '') == target_proj_id), projects[0] if projects else {})
    else:
        tasks = tasks_all
        project = projects[0] if projects else {}

    # Build task lookup
    task_map = {t['task_id']: t for t in tasks}
    all_task_ids = set(task_map.keys())

    # Build predecessor/successor maps (from full pred list, filtered to our tasks)
    preds = [p for p in preds_all if p.get('task_id', '') in all_task_ids]
    has_pred = set()
    has_succ = set()
    pred_map = {}  # task_id -> list of predecessor records
    succ_map = {}  # task_id -> list of successor records

    for p in preds:
        tid = p.get('task_id', '')
        pid = p.get('pred_task_id', '')
        has_pred.add(tid)
        has_succ.add(pid)
        pred_map.setdefault(tid, []).append(p)
        succ_map.setdefault(pid, []).append(p)

    # Filter out LOE/WBS
    work_tasks = [t for t in tasks if not _is_loe(t)]
    incomplete_tasks = [t for t in work_tasks if not _is_complete(t)]
    complete_tasks = [t for t in work_tasks if _is_complete(t)]
    active_tasks = [t for t in work_tasks if t.get('status_code', '') == ACTIVE_STATUS]
    not_started = [t for t in work_tasks if t.get('status_code', '') == NOT_STARTED_STATUS]

    # Project info
    proj_name = project.get('proj_short_name', 'Unknown')
    data_date = project.get('last_recalc_date', '')

    results = {
        'project_name': proj_name,
        'data_date': data_date,
        'analysis_timestamp': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'total_activities': len(work_tasks),
        'complete': len(complete_tasks),
        'in_progress': len(active_tasks),
        'not_started': len(not_started),
        'incomplete': len(incomplete_tasks),
        'checks': {},
        'recommendations': [],
        'critical_path_activities': [],
        'near_critical_activities': [],
        'open_ends': {'no_pred': [], 'no_succ': []},
        'overall_score': 0,
        'overall_rating': RATING_RED,
        'overall_confidence': 'Unreliable',
    }

    # ── CHECK 1: Critical Path Identification ──────────────────────
    # Note: TF ≤ 0 reflects P6's pre-computed driving-path flag. This is the
    # standard convention for CP membership, but a defensive validator could
    # also verify the activity is on the longest path from project start to
    # project finish via graph traversal. We currently rely on P6's calculation
    # — if the calculation is wrong (constraints, retained logic, etc.) the
    # downstream checks (constraint_driven, open_ends_cp, etc.) flag the
    # likely cause.
    cp_activities = []
    for t in incomplete_tasks:
        tf_hrs = t.get('total_float_hr_cnt', '')
        tf = _safe_float(tf_hrs, 999)
        if tf <= 0:
            clndr_id = t.get('clndr_id', '')
            tf_days = _hrs_to_days(tf_hrs, cal_map, clndr_id)
            constraints = _get_constraints(t)
            has_hard = bool(set(constraints) & HARD_CONSTRAINTS)

            # Get relationships on this activity
            act_preds = pred_map.get(t['task_id'], [])
            act_succs = succ_map.get(t['task_id'], [])

            wbs_info = wbs_map.get(t.get('wbs_id', ''), {})
            wbs_path = wbs_info.get('_full_path', '')

            cp_activities.append({
                'task_id': t['task_id'],
                'task_code': t.get('task_code', ''),
                'task_name': t.get('task_name', ''),
                'task_type': t.get('task_type', ''),
                'status': t.get('status_code', ''),
                'total_float_days': tf_days,
                'constraints': constraints,
                'has_hard_constraint': has_hard,
                'has_predecessor': t['task_id'] in has_pred,
                'has_successor': t['task_id'] in has_succ,
                'pred_count': len(act_preds),
                'succ_count': len(act_succs),
                'wbs_path': wbs_path,
                'driving_flag': t.get('driving_path_flag', ''),
                # P6's longest-path flag is `crt_path_num` — a nonzero integer
                # identifies the task as on the longest path. There is no field
                # named `longest_path` in the TASK table.
                'longest_path': t.get('crt_path_num', ''),
            })

    results['critical_path_activities'] = cp_activities
    cp_count = len(cp_activities)
    cp_pct = (cp_count / len(incomplete_tasks) * 100) if incomplete_tasks else 0
    cp_task_ids = {a['task_id'] for a in cp_activities}

    if cp_count == 0:
        cp_id_rating = RATING_RED
        cp_id_score = 0
        cp_id_note = 'No critical path activities found. Schedule has no activities with TF ≤ 0. This typically means constraints or open ends are preventing proper CP calculation.'
    elif cp_pct < 3:
        cp_id_rating = RATING_AMBER
        cp_id_score = 55
        cp_id_note = f'{cp_count} critical activities ({cp_pct:.1f}% of {len(incomplete_tasks)} incomplete). CP is unusually short — may indicate constraint suppression.'
    elif cp_pct > 40:
        cp_id_rating = RATING_AMBER
        cp_id_score = 55
        cp_id_note = f'{cp_count} critical activities ({cp_pct:.1f}% of {len(incomplete_tasks)} incomplete). Excessive criticality — too many activities at zero float, possibly due to constraints or logic issues.'
    else:
        cp_id_rating = RATING_GREEN
        cp_id_score = 100
        cp_id_note = f'{cp_count} critical activities ({cp_pct:.1f}% of {len(incomplete_tasks)} incomplete). Reasonable CP length.'

    results['checks']['cp_identification'] = {
        'name': 'Critical Path Identification',
        'rating': cp_id_rating,
        'score': cp_id_score,
        'note': cp_id_note,
        'cp_count': cp_count,
        'cp_pct': round(cp_pct, 1),
        'incomplete_count': len(incomplete_tasks),
    }

    # ── CHECK 2: Constraint-Driven Criticality ─────────────────────
    cp_constrained = [a for a in cp_activities if a['has_hard_constraint']]
    cp_constrained_pct = (len(cp_constrained) / cp_count * 100) if cp_count else 0

    # Schedule-wide constraint analysis
    all_constrained = [t for t in incomplete_tasks if _has_hard_constraint(t)]
    all_constrained_pct = (len(all_constrained) / len(incomplete_tasks) * 100) if incomplete_tasks else 0

    # Constraint type breakdown (labels preferred over raw codes for readability)
    cstr_breakdown = {}
    for t in incomplete_tasks:
        for c in _get_constraints(t):
            label = CONSTRAINT_LABELS.get(c, c)
            cstr_breakdown[label] = cstr_breakdown.get(label, 0) + 1

    if cp_constrained_pct > 50:
        cstr_rating = RATING_RED
        cstr_score = 30
        cstr_note = f'{len(cp_constrained)}/{cp_count} CP activities ({cp_constrained_pct:.0f}%) have hard constraints. Critical path is likely ARTIFICIAL — driven by date constraints rather than logic.'
    elif cp_constrained_pct > 25:
        cstr_rating = RATING_AMBER
        cstr_score = 60
        cstr_note = f'{len(cp_constrained)}/{cp_count} CP activities ({cp_constrained_pct:.0f}%) have hard constraints. CP is partially constraint-driven — review whether constraints are necessary.'
    elif cp_constrained_pct > 0:
        cstr_rating = RATING_AMBER
        cstr_score = 75
        cstr_note = f'{len(cp_constrained)}/{cp_count} CP activities ({cp_constrained_pct:.0f}%) have hard constraints. Minor constraint influence on CP.'
    else:
        cstr_rating = RATING_GREEN
        cstr_score = 100
        cstr_note = 'No hard constraints on critical path activities. CP is logic-driven.'

    # Differentiate recommendation prose by hardness tier so the scheduler
    # knows whether they're removing a Mandatory (overrides logic) or a
    # Start-On/Finish-On (pins a date). Severity of action differs.
    for a in cp_constrained:
        tiers = {_hardness_tier(c) for c in a['constraints']}
        tiers.discard(None)
        labels = ', '.join(CONSTRAINT_LABELS.get(c, c) for c in a['constraints'])
        if 'ABSOLUTE' in tiers:
            rec_text = (
                'Mandatory constraint OVERRIDES network logic — P6 schedules '
                'to this date regardless of predecessor completion. Remove '
                'unless the date is contractually bonded (e.g. liquidated '
                'damages or mandatory handover). If it must stay, document '
                'the contractual source.'
            )
            tier_note = 'Mandatory (overrides logic)'
        elif 'DATE' in tiers:
            rec_text = (
                'Start-On / Finish-On pins the activity to a specific date. '
                'Review whether contractually required; if not, delete the '
                'constraint and let the network logic drive the date.'
            )
            tier_note = 'Hard date pin'
        else:
            rec_text = (
                'Soft/preference constraint is currently acting as a hard '
                'driver on the CP. Verify it represents a real external '
                'bound; otherwise remove or relax it.'
            )
            tier_note = 'Soft acting hard'
        results['recommendations'].append({
            'priority': 'Critical',
            'category': 'Constraint-Driven CP',
            'finding': f"Activity '{a['task_code']} - {a['task_name']}' is critical with constraint(s): {labels} [{tier_note}]",
            'recommendation': rec_text,
            'affected_activity': a['task_code'],
        })

    # ── LPM-confirmation: math-grounded false-CP detection ────────────────────
    # Build lightweight activity/relationship lists for compute_lpm.
    # We use the P6-precomputed total_float_hr_cnt as the TFM source (not a
    # freshly-recomputed TF) because P6's TF reflects constraint-pinned dates and
    # retained-logic/out-of-sequence effects that the engine would re-derive
    # differently. The LPM DP is pure duration accumulation (AACE 49R-06) —
    # constraints are invisible to it — so comparing P6-TF against LPM membership
    # gives the strongest forensic signal for constraint-driven false-CP.
    #
    # duration_days = remain_drtn_hr_cnt / hours_per_day on the activity's calendar
    # (fall back to 8 h/d when the calendar is missing; LPM is duration-only, so
    # coarse arithmetic still gives the right divergence set).
    _lpm_acts = []
    for t in work_tasks:
        cid = t.get('clndr_id', '')
        cal = cal_map.get(cid, {}) if cid else {}
        hpd = cal.get('hours_per_day', 8.0) or 8.0
        remain_hrs = _safe_float(t.get('remain_drtn_hr_cnt', 0), 0)
        dur = remain_hrs / hpd
        _lpm_acts.append({
            'code': t['task_id'],
            'duration_days': dur,
            'is_complete': _is_complete(t),
        })

    _PRED_TYPE_MAP = {'PR_FS': 'FS', 'PR_FF': 'FF', 'PR_SS': 'SS', 'PR_SF': 'SF'}
    _lpm_rels = []
    _all_lpm_codes = {a['code'] for a in _lpm_acts}
    for p in preds_all:
        fc = p.get('pred_task_id', '')
        tc = p.get('task_id', '')
        if fc not in _all_lpm_codes or tc not in _all_lpm_codes:
            continue
        _lpm_rels.append({
            'from_code': fc,
            'to_code': tc,
            'type': _PRED_TYPE_MAP.get(p.get('pred_type', ''), 'FS'),
            'lag_days': 0.0,  # LPM ignores lag per AACE 49R-06
        })

    try:
        from cpm import compute_lpm as _compute_lpm  # noqa: E402  (already on sys.path)
        _lpm_result = _compute_lpm(_lpm_acts, _lpm_rels)
        _lpm_codes_set = set(_lpm_result['codes'])

        # P6 TFM: activities flagged as critical by P6 (total_float_hr_cnt ≤ 0),
        # filtered to incomplete work tasks — matches the Check 1 cp_activities list.
        _p6_tfm_ids = {a['task_id'] for a in cp_activities}  # already TF≤0 incomplete

        # only_TFM: in P6 TFM but NOT on LPM. These are the math-grounded
        # false-CP candidates (AACE 49R-06).
        _lpm_confirmed_false_cp = sorted(
            tid for tid in _p6_tfm_ids if tid not in _lpm_codes_set
        )
        _lpm_error = None
    except Exception as _e:
        _lpm_confirmed_false_cp = []
        _lpm_error = str(_e)

    # Add LPM-confirmed false-CP recommendations (one per activity).
    for tid in _lpm_confirmed_false_cp:
        t = task_map.get(tid, {})
        tcode = t.get('task_code', tid)
        tname = t.get('task_name', '')
        results['recommendations'].append({
            'priority': 'Critical',
            'category': 'Constraint-Driven CP',
            'finding': (
                f"Activity '{tcode} - {tname}' is on TFM (TF=0) but NOT on "
                f"LPM (longest path). LPM-confirmed constraint-driven false-CP "
                f"candidate per AACE 49R-06."
            ),
            'recommendation': (
                'This activity has zero total float per P6 scheduling (TFM), '
                'but it is NOT on the project\'s longest duration path (LPM). '
                'The discrepancy is math-grounded evidence that a constraint — '
                'hard date, mandatory, retained logic, or out-of-sequence '
                'progress — is artificially forcing zero float rather than '
                'true network logic. Investigate and remove the constraint if '
                'it is not contractually required.'
            ),
            'affected_activity': tcode,
        })

    results['checks']['constraint_driven'] = {
        'name': 'Constraint-Driven Criticality',
        'rating': cstr_rating,
        'score': cstr_score,
        'note': cstr_note,
        'cp_constrained': len(cp_constrained),
        'cp_total': cp_count,
        'cp_constrained_pct': round(cp_constrained_pct, 1),
        'schedule_constrained': len(all_constrained),
        'schedule_constrained_pct': round(all_constrained_pct, 1),
        'constraint_breakdown': cstr_breakdown,
        'lpm_confirmed_false_cp': _lpm_confirmed_false_cp,
        'lpm_error': _lpm_error,
    }

    # ── CHECK 3: Open Ends ─────────────────────────────────────────
    no_pred = []
    no_succ = []
    cp_no_pred = []
    cp_no_succ = []

    # Identify terminal milestone(s) — the last CP activity with no successor
    # is legitimate if it's a finish milestone at the end of the network.
    # Find the CP activity with the latest early finish and no successor.
    terminal_ids = set()
    cp_no_succ_candidates = [
        a for a in cp_activities if not a['has_successor']
    ]
    if cp_no_succ_candidates:
        # The P6 field for scheduled finish is `scd_end_date` (not sched_end_date).
        sched_finish = project.get('scd_end_date', '') or project.get('plan_end_date', '')
        for cand in cp_no_succ_candidates:
            t = task_map.get(cand['task_id'], {})
            ef = t.get('early_end_date', '')
            is_finish_mile = t.get('task_type', '') in MILESTONE_TASK_TYPES
            # Terminal if: finish milestone, or its early finish matches
            # the project scheduled finish (it IS the project end)
            if is_finish_mile:
                terminal_ids.add(cand['task_id'])
            elif ef and sched_finish and ef[:10] == sched_finish[:10]:
                terminal_ids.add(cand['task_id'])
        # Multi-finish projects can legitimately have several CP activities at the
        # network's terminal end-date — all of them are terminals, not just one.
        # If exactly one CP activity has no successor we already classified it
        # above (or via the `is_finish_mile` / sched_finish branches); fall back
        # here only when no candidate matched the named-finish heuristics, in
        # which case every candidate sharing the latest early-finish is treated
        # as a project terminal.
        if cp_no_succ_candidates and not terminal_ids:
            latest_ef = ''
            for cand in cp_no_succ_candidates:
                t = task_map.get(cand['task_id'], {})
                ef = (t.get('early_end_date', '') or '')[:10]
                if ef and ef > latest_ef:
                    latest_ef = ef
            if latest_ef:
                for cand in cp_no_succ_candidates:
                    t = task_map.get(cand['task_id'], {})
                    ef = (t.get('early_end_date', '') or '')[:10]
                    if ef == latest_ef:
                        terminal_ids.add(cand['task_id'])
            elif len(cp_no_succ_candidates) == 1:
                # Single candidate, no usable EF — treat as terminal anyway.
                terminal_ids.add(cp_no_succ_candidates[0]['task_id'])

    for t in incomplete_tasks:
        tid = t['task_id']
        is_cp = tid in cp_task_ids
        if tid not in has_pred and not _is_loe(t):
            entry = {
                'task_id': tid,
                'task_code': t.get('task_code', ''),
                'task_name': t.get('task_name', ''),
                'status': t.get('status_code', ''),
                'is_critical': is_cp,
            }
            no_pred.append(entry)
            if is_cp:
                cp_no_pred.append(entry)

        if tid not in has_succ and not _is_loe(t):
            # Skip terminal milestones — last CP activity with no successor is correct
            is_terminal = tid in terminal_ids
            entry = {
                'task_id': tid,
                'task_code': t.get('task_code', ''),
                'task_name': t.get('task_name', ''),
                'status': t.get('status_code', ''),
                'is_critical': is_cp,
                'is_terminal': is_terminal,
            }
            no_succ.append(entry)
            if is_cp and not is_terminal:
                cp_no_succ.append(entry)

    results['open_ends'] = {'no_pred': no_pred, 'no_succ': no_succ}
    results['terminal_milestones'] = [task_map.get(tid, {}).get('task_code', '') for tid in terminal_ids]

    # For schedule-wide count, exclude terminal milestones from the total
    non_terminal_no_succ = [e for e in no_succ if not e.get('is_terminal', False)]
    open_end_total = len(no_pred) + len(non_terminal_no_succ)
    cp_open_ends = len(cp_no_pred) + len(cp_no_succ)

    if cp_open_ends > 0:
        oe_rating = RATING_RED
        oe_score = max(0, 40 - cp_open_ends * 10)
        oe_note = f'{cp_open_ends} open end(s) ON the critical path ({len(cp_no_pred)} missing pred, {len(cp_no_succ)} missing succ). CP logic is BROKEN.'
    elif open_end_total > len(incomplete_tasks) * 0.15:
        oe_rating = RATING_AMBER
        oe_score = 60
        oe_note = f'{open_end_total} open ends on incomplete activities ({len(no_pred)} missing pred, {len(non_terminal_no_succ)} missing succ). None on CP but high count schedule-wide.'
    elif open_end_total > 0:
        oe_rating = RATING_AMBER
        oe_score = 80
        oe_note = f'{open_end_total} open ends ({len(no_pred)} missing pred, {len(non_terminal_no_succ)} missing succ). None on CP.'
    else:
        oe_rating = RATING_GREEN
        oe_score = 100
        oe_note = 'No open ends on incomplete activities. Full logic network.'

    for entry in cp_no_pred:
        results['recommendations'].append({
            'priority': 'Critical',
            'category': 'Open Ends on CP',
            'finding': f"Critical activity '{entry['task_code']} - {entry['task_name']}' has NO PREDECESSORS.",
            'recommendation': 'Add a logical predecessor. Without one, this activity floats freely and may create false criticality.',
            'affected_activity': entry['task_code'],
        })

    for entry in cp_no_succ:
        results['recommendations'].append({
            'priority': 'Critical',
            'category': 'Open Ends on CP',
            'finding': f"Critical activity '{entry['task_code']} - {entry['task_name']}' has NO SUCCESSORS.",
            'recommendation': 'Add a logical successor connecting to the project completion milestone. Without one, critical path cannot flow through this activity correctly.',
            'affected_activity': entry['task_code'],
        })

    # Priority asymmetry is intentional:
    # - Missing successor (no_succ) => 'High'. The backward pass computes late
    #   dates by walking successors; an activity with no successor has its late
    #   finish anchored to the project calendar instead of downstream demand,
    #   which inflates its float and can also mask true criticality.
    # - Missing predecessor (no_pred) => 'Medium'. A missing predecessor is
    #   often anchored by a constraint or the data date, so the activity still
    #   gets a realistic early start. Less corrosive to CP calculation.
    # Do not collapse to symmetric without verifying the underlying float-calc
    # asymmetry has been accounted for elsewhere.
    for entry in no_pred:
        if not entry['is_critical']:
            results['recommendations'].append({
                'priority': 'Medium',
                'category': 'Open Ends',
                'finding': f"Activity '{entry['task_code']} - {entry['task_name']}' has no predecessors.",
                'recommendation': 'Add a logical predecessor to connect this activity to the network.',
                'affected_activity': entry['task_code'],
            })

    for entry in no_succ:
        if not entry['is_critical'] and not entry.get('is_terminal', False):
            results['recommendations'].append({
                'priority': 'High',
                'category': 'Open Ends',
                'finding': f"Activity '{entry['task_code']} - {entry['task_name']}' has no successors.",
                'recommendation': 'Add a logical successor. Missing successors prevent the scheduler from properly calculating float.',
                'affected_activity': entry['task_code'],
            })

    results['checks']['open_ends_cp'] = {
        'name': 'Open Ends (CP Focus)',
        'rating': oe_rating,
        'score': oe_score,
        'note': oe_note,
        'cp_no_pred': len(cp_no_pred),
        'cp_no_succ': len(cp_no_succ),
        'total_no_pred': len(no_pred),
        'total_no_succ': len(non_terminal_no_succ),
        'terminal_milestones': list(terminal_ids),
    }

    # ── CHECK 4: Relationship Quality ──────────────────────────────
    rel_types = {'PR_FS': 0, 'PR_FF': 0, 'PR_SS': 0, 'PR_SF': 0}
    cp_rel_types = {'PR_FS': 0, 'PR_FF': 0, 'PR_SS': 0, 'PR_SF': 0}
    # cp_task_ids was built earlier right after cp_activities is populated.

    for p in preds:
        rt = p.get('pred_type', 'PR_FS')
        rel_types[rt] = rel_types.get(rt, 0) + 1
        tid = p.get('task_id', '')
        pid = p.get('pred_task_id', '')
        # Both endpoints must be on the CP for the relationship to drive the CP.
        # An off-CP→on-CP feeder edge does not "drive" the critical path; counting
        # it as a CP relationship inflates the FF/SS/SF tally and produces false
        # positives in the relationship-quality rating.
        if tid in cp_task_ids and pid in cp_task_ids:
            cp_rel_types[rt] = cp_rel_types.get(rt, 0) + 1

    total_rels = sum(rel_types.values())
    fs_pct = (rel_types['PR_FS'] / total_rels * 100) if total_rels else 0
    ff_ss_on_cp = cp_rel_types.get('PR_FF', 0) + cp_rel_types.get('PR_SS', 0) + cp_rel_types.get('PR_SF', 0)
    cp_total_rels = sum(cp_rel_types.values())

    # Avg relationships per activity
    avg_rels = total_rels / len(work_tasks) if work_tasks else 0

    if ff_ss_on_cp > cp_total_rels * 0.5 and cp_total_rels > 0:
        rq_rating = RATING_RED
        rq_score = 30
        rq_note = f'Critical path is driven primarily by FF/SS/SF relationships ({ff_ss_on_cp}/{cp_total_rels}). CP may not represent true construction sequence.'
    elif ff_ss_on_cp > 0:
        rq_rating = RATING_AMBER
        rq_score = 70
        rq_note = f'{ff_ss_on_cp} FF/SS/SF relationships touch the CP ({cp_total_rels} total CP relationships). Verify these represent real construction logic.'
    else:
        rq_rating = RATING_GREEN
        rq_score = 95
        rq_note = f'CP relationships are predominantly FS ({cp_rel_types["PR_FS"]}/{cp_total_rels}). Clean logic.'

    if fs_pct < 80 and total_rels > 0:
        results['recommendations'].append({
            'priority': 'Medium',
            'category': 'Relationship Quality',
            'finding': f'FS relationships are only {fs_pct:.0f}% of all relationships. Non-FS types: FF={rel_types["PR_FF"]}, SS={rel_types["PR_SS"]}, SF={rel_types["PR_SF"]}.',
            'recommendation': 'Review FF/SS/SF relationships. Ensure each has a valid construction reason. Consider adding parallel FS links for schedule robustness.',
            'affected_activity': 'Schedule-wide',
        })

    results['checks']['relationship_quality'] = {
        'name': 'Relationship Quality',
        'rating': rq_rating,
        'score': rq_score,
        'note': rq_note,
        'rel_types': rel_types,
        'cp_rel_types': cp_rel_types,
        'fs_pct': round(fs_pct, 1),
        'avg_rels_per_activity': round(avg_rels, 1),
    }

    # ── CHECK 5: Lag Analysis ──────────────────────────────────────
    total_lags = 0
    neg_lags = 0
    excessive_lags = 0  # > 10 days
    cp_lags = 0
    cp_neg_lags = 0
    lag_details = []

    for p in preds:
        lag_hrs = _safe_float(p.get('lag_hr_cnt', '0'), 0)
        if lag_hrs != 0:
            total_lags += 1
            tid = p.get('task_id', '')
            pid = p.get('pred_task_id', '')
            on_cp = tid in cp_task_ids or pid in cp_task_ids

            # P6 computes lag on the successor's calendar (hours are scheduled
            # against the successor's workday), so use the successor's clndr_id
            # for the hrs→days conversion. Falls back to predecessor's calendar,
            # then to the 8hr default.
            succ_task = task_map.get(tid, {})
            succ_clndr = succ_task.get('clndr_id', '')
            if not succ_clndr:
                succ_clndr = task_map.get(pid, {}).get('clndr_id', '')
            lag_days = _hrs_to_days(lag_hrs, cal_map, succ_clndr)

            if lag_hrs < 0:
                neg_lags += 1
                if on_cp:
                    cp_neg_lags += 1
                    t_info = task_map.get(tid, {})
                    p_info = task_map.get(pid, {})
                    lag_details.append({
                        'pred_code': p_info.get('task_code', ''),
                        'succ_code': t_info.get('task_code', ''),
                        'pred_name': p_info.get('task_name', ''),
                        'succ_name': t_info.get('task_name', ''),
                        'lag_days': round(lag_days, 1),
                        'rel_type': p.get('pred_type', ''),
                    })

            if abs(lag_days) > 10:
                excessive_lags += 1

            if on_cp:
                cp_lags += 1

    if cp_neg_lags > 0:
        lag_rating = RATING_RED
        lag_score = max(0, 40 - cp_neg_lags * 15)
        lag_note = f'{cp_neg_lags} negative lag(s) (leads) on the critical path. Schedule is artificially compressed — true CP duration is longer than shown.'
    elif neg_lags > total_lags * 0.3 and neg_lags > 5:
        lag_rating = RATING_AMBER
        lag_score = 60
        lag_note = f'{neg_lags} negative lags schedule-wide (none on CP). High lead count suggests scheduling shortcuts.'
    elif neg_lags > 0:
        lag_rating = RATING_AMBER
        lag_score = 80
        lag_note = f'{neg_lags} negative lag(s) schedule-wide, {total_lags} total lags. None on CP.'
    else:
        lag_rating = RATING_GREEN
        lag_score = 95
        lag_note = f'{total_lags} lags in schedule, no negative lags. Clean.'

    for ld in lag_details:
        results['recommendations'].append({
            'priority': 'Critical',
            'category': 'Negative Lags on CP',
            'finding': f"Negative lag ({ld['lag_days']}d) on CP: {ld['pred_code']} → {ld['succ_code']} ({ld['rel_type']})",
            'recommendation': "Remove the negative lag. If work truly overlaps, model it with SS+lag or separate the activities. Negative lags hide true duration from the scheduler.",
            'affected_activity': f"{ld['pred_code']} / {ld['succ_code']}",
        })

    if neg_lags > 10 and cp_neg_lags == 0:
        results['recommendations'].append({
            'priority': 'High',
            'category': 'Negative Lags',
            'finding': f'{neg_lags} negative lags schedule-wide. While none are on the CP currently, any logic change could promote them to the CP.',
            'recommendation': 'Systematically review and eliminate negative lags. Replace with proper SS/FF relationships or split activities to model overlap correctly.',
            'affected_activity': 'Schedule-wide',
        })

    results['checks']['lag_issues'] = {
        'name': 'Lag Analysis',
        'rating': lag_rating,
        'score': lag_score,
        'note': lag_note,
        'total_lags': total_lags,
        'neg_lags': neg_lags,
        'excessive_lags': excessive_lags,
        'cp_lags': cp_lags,
        'cp_neg_lags': cp_neg_lags,
    }

    # ── CHECK 6: Out-of-Sequence Progress ──────────────────────────
    # A task is out-of-sequence if it has started/progressed while an FS or
    # SS predecessor has not yet started (or, for FS specifically, has not
    # completed). Both relationship types count — an SS-predecessor that hasn't
    # even begun but its successor has is the same out-of-sequence signal.
    oos_activities = []
    seen_oos = set()  # dedupe (task, pred) pairs
    for t in active_tasks:
        tid = t['task_id']
        t_preds = pred_map.get(tid, [])
        for p in t_preds:
            rtype = p.get('pred_type', '')
            pred_task = task_map.get(p.get('pred_task_id', ''))
            if not pred_task:
                continue
            pred_status = pred_task.get('status_code', '')
            violated = False
            if rtype == 'PR_FS' and pred_status != COMPLETE_STATUS:
                violated = True
            elif rtype == 'PR_SS' and pred_status == NOT_STARTED_STATUS:
                violated = True
            if violated:
                key = (tid, pred_task['task_id'])
                if key in seen_oos:
                    continue
                seen_oos.add(key)
                oos_activities.append({
                    'task_code': t.get('task_code', ''),
                    'task_name': t.get('task_name', ''),
                    'pred_code': pred_task.get('task_code', ''),
                    'pred_name': pred_task.get('task_name', ''),
                    'pred_status': pred_status,
                    'rel_type': rtype,
                    'is_critical': tid in cp_task_ids,
                })

    oos_on_cp = [o for o in oos_activities if o['is_critical']]

    if oos_on_cp:
        oos_rating = RATING_RED
        oos_score = 30
        oos_note = f'{len(oos_on_cp)} out-of-sequence activities ON the critical path. CP calculation is unreliable under retained logic.'
    elif len(oos_activities) > len(active_tasks) * 0.2 and len(oos_activities) > 3:
        oos_rating = RATING_AMBER
        oos_score = 60
        oos_note = f'{len(oos_activities)} out-of-sequence activities (none on CP). High OOS count may indicate schedule is not reflecting field reality.'
    elif oos_activities:
        oos_rating = RATING_AMBER
        oos_score = 80
        oos_note = f'{len(oos_activities)} out-of-sequence activity(ies). Minor impact.'
    else:
        oos_rating = RATING_GREEN
        oos_score = 100
        oos_note = 'No out-of-sequence progress detected. Schedule reflects field execution order.'

    # CPP forensic-correctness rule: never truncate findings without disclosure.
    # Emit the full list so every out-of-sequence pair is available to downstream consumers
    # (report generator, JSON export, etc.).
    results['checks']['out_of_sequence'] = {
        'name': 'Out-of-Sequence Progress',
        'rating': oos_rating,
        'score': oos_score,
        'note': oos_note,
        'oos_count': len(oos_activities),
        'oos_on_cp': len(oos_on_cp),
        'oos_details': oos_activities,  # full list — no silent truncation
    }

    # ── CHECK 7: Near-Critical Path ────────────────────────────────
    near_critical = []
    nc_bands = {'1-2d': 0, '3-5d': 0, '6-10d': 0}

    for t in incomplete_tasks:
        tf_hrs = t.get('total_float_hr_cnt', '')
        tf = _safe_float(tf_hrs, 999)
        if 0 < tf <= NEAR_CRITICAL_FLOAT_MAX_HRS:
            clndr_id = t.get('clndr_id', '')
            tf_days = _hrs_to_days(tf_hrs, cal_map, clndr_id)
            near_critical.append({
                'task_code': t.get('task_code', ''),
                'task_name': t.get('task_name', ''),
                'total_float_days': round(tf_days, 1),
                'status': t.get('status_code', ''),
                'task_type': t.get('task_type', ''),
            })
            if tf_days <= 2:
                nc_bands['1-2d'] += 1
            elif tf_days <= 5:
                nc_bands['3-5d'] += 1
            else:
                nc_bands['6-10d'] += 1

    results['near_critical_activities'] = near_critical
    nc_count = len(near_critical)
    nc_pct = (nc_count / len(incomplete_tasks) * 100) if incomplete_tasks else 0

    if nc_bands['1-2d'] > 10:
        nc_rating = RATING_RED
        nc_score = 40
        nc_note = f'{nc_bands["1-2d"]} activities within 1-2 days of criticality. Schedule is extremely fragile — minor delays will create new critical paths.'
    elif nc_count > len(incomplete_tasks) * 0.3:
        nc_rating = RATING_AMBER
        nc_score = 55
        nc_note = f'{nc_count} near-critical activities ({nc_pct:.0f}% of incomplete). Schedule has limited float buffer.'
    elif nc_count > 0:
        nc_rating = RATING_AMBER if nc_bands['1-2d'] > 3 else RATING_GREEN
        nc_score = 80 if nc_bands['1-2d'] > 3 else 90
        nc_note = f'{nc_count} near-critical activities. Bands: 1-2d={nc_bands["1-2d"]}, 3-5d={nc_bands["3-5d"]}, 6-10d={nc_bands["6-10d"]}.'
    else:
        nc_rating = RATING_GREEN
        nc_score = 100
        nc_note = 'No near-critical activities. Healthy float distribution.'

    results['checks']['near_critical'] = {
        'name': 'Near-Critical Path',
        'rating': nc_rating,
        'score': nc_score,
        'note': nc_note,
        'nc_count': nc_count,
        'nc_pct': round(nc_pct, 1),
        'bands': nc_bands,
    }

    # ── CHECK 8: Logic Continuity to Completion ────────────────────
    # Find the project completion milestone(s). P6 has a single finish-milestone
    # type (TT_FinMile); TT_Mile is a start milestone. Don't widen to
    # MILESTONE_TASK_TYPES here or we'd treat every start milestone as a
    # completion anchor.
    finish_milestones = set()
    for t in work_tasks:
        if t.get('task_type', '') == 'TT_FinMile' and t['task_id'] in cp_task_ids:
            finish_milestones.add(t['task_id'])

    # If no critical finish milestones, find any finish milestone
    if not finish_milestones:
        for t in work_tasks:
            if t.get('task_type', '') == 'TT_FinMile':
                finish_milestones.add(t['task_id'])

    # Trace successor chains to find disconnected activities
    # BFS from each finish milestone backwards
    connected_to_finish = set()
    if finish_milestones:
        queue = list(finish_milestones)
        while queue:
            current = queue.pop(0)
            if current in connected_to_finish:
                continue
            connected_to_finish.add(current)
            # Get predecessors of current
            for p in pred_map.get(current, []):
                pid = p.get('pred_task_id', '')
                if pid and pid not in connected_to_finish and pid in all_task_ids:
                    queue.append(pid)

    disconnected = []
    for t in incomplete_tasks:
        if t['task_id'] not in connected_to_finish and not _is_loe(t):
            disconnected.append({
                'task_code': t.get('task_code', ''),
                'task_name': t.get('task_name', ''),
                'status': t.get('status_code', ''),
                'is_critical': t['task_id'] in cp_task_ids,
            })

    disc_count = len(disconnected)
    disc_on_cp = len([d for d in disconnected if d['is_critical']])

    if disc_on_cp > 0:
        lc_rating = RATING_RED
        lc_score = 20
        lc_note = f'{disc_on_cp} critical activities have NO logic path to a completion milestone. CP is disconnected from project finish.'
    elif disc_count > len(incomplete_tasks) * 0.1:
        lc_rating = RATING_AMBER
        lc_score = 60
        lc_note = f'{disc_count} incomplete activities have no logic path to any completion milestone. Work is happening outside the logic network.'
    elif disc_count > 0:
        lc_rating = RATING_AMBER
        lc_score = 80
        lc_note = f'{disc_count} incomplete activity(ies) disconnected from completion. Minor logic gap.'
    else:
        lc_rating = RATING_GREEN
        lc_score = 100
        lc_note = 'All incomplete activities have a logic path to the project completion milestone.'

    # CPP forensic-correctness rule: never truncate findings without disclosure.
    # Emit the full list of disconnected activities — every one corresponds to a concrete
    # logic gap the scheduler needs to fix.
    results['checks']['logic_continuity'] = {
        'name': 'Logic Continuity to Completion',
        'rating': lc_rating,
        'score': lc_score,
        'note': lc_note,
        'disconnected_count': disc_count,
        'disconnected_on_cp': disc_on_cp,
        'disconnected_activities': disconnected,  # full list — no silent truncation
        'finish_milestones_found': len(finish_milestones),
    }

    for d in disconnected:
        pri = 'Critical' if d['is_critical'] else 'High'
        results['recommendations'].append({
            'priority': pri,
            'category': 'Logic Continuity',
            'finding': f"Activity '{d['task_code']} - {d['task_name']}' has no successor path to the project completion milestone.",
            'recommendation': 'Add successor logic connecting this activity (directly or through chain) to the project finish milestone.',
            'affected_activity': d['task_code'],
        })

    # ── CHECK 9: Constraint Saturation (Schedule-Wide) ─────────────
    # Already computed in CHECK 2, just add the schedule-wide perspective.
    # Score maps to rating: GREEN=100, AMBER=60, RED=30. Weighted into overall.
    if all_constrained_pct > 20:
        cs_rating = RATING_RED
        cs_score = 30
        cs_note = f'{len(all_constrained)} of {len(incomplete_tasks)} incomplete activities ({all_constrained_pct:.0f}%) have hard constraints. Schedule is DATE-DRIVEN, not logic-driven.'
    elif all_constrained_pct > 5:
        cs_rating = RATING_AMBER
        cs_score = 60
        cs_note = f'{len(all_constrained)} of {len(incomplete_tasks)} incomplete activities ({all_constrained_pct:.0f}%) have hard constraints. Above DCMA 5% threshold.'
    else:
        cs_rating = RATING_GREEN
        cs_score = 100
        cs_note = f'{len(all_constrained)} of {len(incomplete_tasks)} incomplete activities ({all_constrained_pct:.0f}%) have hard constraints. Within acceptable limits.'

    results['checks']['constraint_saturation'] = {
        'name': 'Constraint Saturation',
        'rating': cs_rating,
        'score': cs_score,
        'note': cs_note,
        'constrained_count': len(all_constrained),
        'constrained_pct': round(all_constrained_pct, 1),
        'breakdown': cstr_breakdown,
    }

    if all_constrained_pct > 5:
        results['recommendations'].append({
            'priority': 'High',
            'category': 'Constraint Saturation',
            'finding': f'{all_constrained_pct:.0f}% of incomplete activities have hard constraints (DCMA threshold: 5%).',
            'recommendation': 'Audit all hard constraints. Remove any that are not contractually required. Replace with logic-driven relationships where possible.',
            'affected_activity': 'Schedule-wide',
        })

    # ── CALCULATE OVERALL SCORE ────────────────────────────────────
    scored_checks = {
        'cp_identification': results['checks']['cp_identification']['score'],
        'constraint_driven': results['checks']['constraint_driven']['score'],
        'open_ends_cp': results['checks']['open_ends_cp']['score'],
        'relationship_quality': results['checks']['relationship_quality']['score'],
        'lag_issues': results['checks']['lag_issues']['score'],
        'logic_continuity': results['checks']['logic_continuity']['score'],
        'near_critical': results['checks']['near_critical']['score'],
        'out_of_sequence': results['checks']['out_of_sequence']['score'],
        'constraint_saturation': results['checks']['constraint_saturation']['score'],
    }

    overall = sum(scored_checks[k] * CHECK_WEIGHTS[k] for k in CHECK_WEIGHTS)
    results['overall_score'] = round(overall, 1)

    if overall >= 80:
        results['overall_rating'] = RATING_GREEN
        results['overall_confidence'] = 'High Confidence'
    elif overall >= 60:
        results['overall_rating'] = RATING_AMBER
        results['overall_confidence'] = 'Moderate Confidence'
    elif overall >= 40:
        results['overall_rating'] = RATING_AMBER
        results['overall_confidence'] = 'Low Confidence'
    else:
        results['overall_rating'] = RATING_RED
        results['overall_confidence'] = 'Unreliable'

    # Sort recommendations by priority
    priority_order = {'Critical': 0, 'High': 1, 'Medium': 2, 'Low': 3}
    results['recommendations'].sort(key=lambda r: priority_order.get(r['priority'], 99))

    # ── DCMA 14-Point assessment ───────────────────────────────────
    # Wired into the primary validation output as a top-level key.
    # Any import/runtime failure is caught so the 9-check validator still
    # succeeds even if the DCMA module has an issue — forensic users depend
    # on the legacy output.
    try:
        from dcma14 import dcma_14_assess
        dcma_result = dcma_14_assess(data, profile=profile, baseline_data=baseline_data)
        # Convert the ValidationReport to a dict so the whole results blob is
        # JSON-serializable (dashboard writes JSON alongside HTML).
        results['dcma_14'] = {
            'profile': dcma_result['profile'],
            'profile_name': dcma_result.get('profile_name', dcma_result['profile']),
            'dcma_score': dcma_result['dcma_score'],
            'cpli': dcma_result['cpli'],
            'bei': dcma_result['bei'],
            'critical_paths': dcma_result['critical_paths'],
            'multiple_critical_paths': dcma_result['multiple_critical_paths'],
            'cp_continuity': dcma_result['cp_continuity'],
            'per_check': dcma_result['per_check'],
            'report': dcma_result['report'].to_dict(),
        }
    except Exception as e:  # pragma: no cover - defensive
        results['dcma_14'] = {
            'error': f'DCMA 14 assessment unavailable: {type(e).__name__}: {e}',
        }

    # ── DRIVER-CHAIN NARRATIVE (AACE 49R-06 §6) ──────────────────────
    # For each critical activity, walk driving predecessors back to project
    # start and emit a natural-language explanation. Reuses the (_lpm_acts,
    # _lpm_rels) lists built for Check 2's LPM cross-check so the same
    # network is fed into both the LPM divergence math and the narrative
    # composer — single source of truth.
    #
    # Enrichment: the narrative composer classifies each activity into
    # logic_driven / constraint_driven / false_cp by reading
    # ``node.constraints`` and comparing tf<=0 against an LPM cross-check.
    # The base ``compute_cpm`` result strips constraint data and computes
    # its own TF (which may diverge from P6's pre-computed total_float_hr_cnt
    # when activities have zero duration). We post-enrich the result's
    # ``nodes`` dict with:
    #   - ``constraints``: list of P6 constraint codes from cstr_type/cstr_type2
    #   - ``tf``: overridden to P6's pre-computed TF in days so the narrative
    #     classifier sees the same "is critical?" answer as Check 1's CP table
    #     and Check 2's LPM-confirmed false-CP list.
    # This keeps the four views — Check 1 (P6 TFM), Check 2 (LPM cross-check),
    # driver_chain_narrative (per-activity prose), and the LPM math itself —
    # in lockstep on what counts as critical and what counts as false-CP.
    #
    # Defensive: any failure (cycle, missing compute_cpm, etc.) drops a
    # diagnostic block into the result so a downstream renderer can still
    # surface the gap without blowing up the validator.
    try:
        from cpm import compute_cpm as _compute_cpm  # noqa: E402
        from driver_chain_narrative import build_driver_chain_narrative  # noqa: E402

        # Build target_codes from already-classified P6 CP activities so the
        # narrative list matches Check 1's CP table exactly. We map task_id
        # (LPM uses task_id as 'code') back via the cp_activities entries.
        _target_codes = [a['task_id'] for a in cp_activities]

        # data_date passes through so PROJECT_START sentinel narratives can
        # mention the actual data-date when an activity is its own origin.
        _dd_str = ''
        if data_date:
            # Normalise to YYYY-MM-DD; P6 dates can include time.
            _dd_str = str(data_date)[:10]

        _cpm_result = _compute_cpm(
            _lpm_acts, _lpm_rels, data_date=_dd_str, cal_map=cal_map)

        # Post-enrich nodes with constraint codes + P6 TF so the narrative
        # classifier mirrors Check 1's CP table exactly.
        for _tid, _node in _cpm_result.get('nodes', {}).items():
            _t = task_map.get(_tid, {})
            _node['constraints'] = _get_constraints(_t)
            # Override TF with P6's pre-computed total_float_hr_cnt (in days)
            # so target codes with P6 TF<=0 are seen as critical by the
            # composer regardless of how compute_cpm recomputed it.
            _cid = _t.get('clndr_id', '')
            _hrs = _safe_float(_t.get('total_float_hr_cnt', 0), 999)
            _node['tf'] = _hrs_to_days(_hrs, cal_map, _cid)

        _dcn = build_driver_chain_narrative(
            _cpm_result,
            target_codes=_target_codes,
            jurisdiction=jurisdiction,
            max_depth=10,
        )

        # Enrich each narrative with the user-facing task_code + task_name so
        # the dashboard doesn't need a second lookup against task_map.
        for n in _dcn.get('narratives', []):
            tid = n.get('code') or ''
            t = task_map.get(tid, {})
            n['task_code'] = t.get('task_code', '') or n.get('name') or tid
            n['task_name'] = t.get('task_name', '') or n.get('name') or ''

        results['driver_chain_narrative'] = _dcn
    except Exception as e:  # pragma: no cover - defensive
        results['driver_chain_narrative'] = {
            'error': (f'Driver-chain narrative unavailable: '
                      f'{type(e).__name__}: {e}'),
            'narratives': [],
            'manifest': {},
        }

    return results


# ─────────────────────────────────────────────────────────────────────
# DASHBOARD GENERATOR
# ─────────────────────────────────────────────────────────────────────

def generate_dashboard(results, output_path):
    """Generate an HTML dashboard from validation results."""

    def _rating_color(rating):
        return {'GREEN': '#22c55e', 'AMBER': '#f59e0b', 'RED': '#ef4444'}.get(rating, '#6b7280')

    def _rating_bg(rating):
        return {'GREEN': 'rgba(34,197,94,0.12)', 'AMBER': 'rgba(245,158,11,0.12)', 'RED': 'rgba(239,68,68,0.12)'}.get(rating, 'rgba(107,114,128,0.1)')

    def _priority_color(pri):
        return {'Critical': '#ef4444', 'High': '#f59e0b', 'Medium': '#3b82f6', 'Low': '#6b7280'}.get(pri, '#6b7280')

    def _escape(s):
        return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

    checks = results['checks']

    # Build check cards
    check_cards = ''
    check_order = [
        'cp_identification', 'constraint_driven', 'open_ends_cp',
        'relationship_quality', 'lag_issues', 'out_of_sequence',
        'near_critical', 'logic_continuity', 'constraint_saturation',
    ]
    for key in check_order:
        if key not in checks:
            continue
        c = checks[key]
        rating = c.get('rating', 'GREEN')
        check_cards += f'''
        <div class="check-card" style="border-left: 4px solid {_rating_color(rating)}; background: {_rating_bg(rating)};">
            <div class="check-header">
                <span class="check-name">{_escape(c['name'])}</span>
                <span class="check-badge" style="background: {_rating_color(rating)};">{rating}</span>
            </div>
            <div class="check-note">{_escape(c['note'])}</div>
        </div>'''

    # Build CP activities table
    cp_rows = ''
    for a in results['critical_path_activities']:
        cstr_str = ', '.join(a['constraints']) if a['constraints'] else '—'
        cstr_class = 'flag-red' if a['has_hard_constraint'] else ''
        pred_flag = '' if a['has_predecessor'] else '<span class="flag-red">NO PRED</span>'
        succ_flag = '' if a['has_successor'] else '<span class="flag-red">NO SUCC</span>'
        cp_rows += f'''
        <tr>
            <td>{_escape(a['task_code'])}</td>
            <td>{_escape(a['task_name'])}</td>
            <td>{a['total_float_days']:.1f}d</td>
            <td class="{cstr_class}">{_escape(cstr_str)}</td>
            <td>{pred_flag} {succ_flag}</td>
            <td>{_escape(a['status'])}</td>
        </tr>'''

    # Build near-critical table
    nc_rows = ''
    for a in sorted(results['near_critical_activities'], key=lambda x: x['total_float_days']):
        nc_rows += f'''
        <tr>
            <td>{_escape(a['task_code'])}</td>
            <td>{_escape(a['task_name'])}</td>
            <td>{a['total_float_days']:.1f}d</td>
            <td>{_escape(a['status'])}</td>
        </tr>'''

    # Build recommendations table
    rec_rows = ''
    for r in results['recommendations']:
        rec_rows += f'''
        <tr>
            <td><span class="pri-badge" style="background: {_priority_color(r['priority'])};">{_escape(r['priority'])}</span></td>
            <td>{_escape(r['category'])}</td>
            <td>{_escape(r['finding'])}</td>
            <td>{_escape(r['recommendation'])}</td>
            <td>{_escape(r['affected_activity'])}</td>
        </tr>'''

    # Build open ends table
    oe_rows = ''
    for entry in results['open_ends']['no_pred']:
        cp_flag = '<span class="flag-red">ON CP</span>' if entry.get('is_critical') else ''
        oe_rows += f'''
        <tr>
            <td>{_escape(entry['task_code'])}</td>
            <td>{_escape(entry['task_name'])}</td>
            <td><span class="flag-amber">Missing Predecessor</span></td>
            <td>{_escape(entry['status'])}</td>
            <td>{cp_flag}</td>
        </tr>'''
    for entry in results['open_ends']['no_succ']:
        cp_flag = '<span class="flag-red">ON CP</span>' if entry.get('is_critical') else ''
        oe_rows += f'''
        <tr>
            <td>{_escape(entry['task_code'])}</td>
            <td>{_escape(entry['task_name'])}</td>
            <td><span class="flag-amber">Missing Successor</span></td>
            <td>{_escape(entry['status'])}</td>
            <td>{cp_flag}</td>
        </tr>'''

    # Optional DCMA 14 scorecard — rendered only if the dcma_14 block is present.
    dcma_html = ''
    dcma_block = results.get('dcma_14')
    if dcma_block and 'error' not in dcma_block:
        try:
            from dcma14 import render_dcma_scorecard_html
            dcma_html = render_dcma_scorecard_html(dcma_block)
        except Exception:
            dcma_html = ''

    # Optional Driver-Chain Narrative section — one card per critical activity
    # explaining WHY it is on the critical path. Rendered after the CP table.
    dcn_html = ''
    dcn_block = results.get('driver_chain_narrative') or {}
    dcn_narratives = dcn_block.get('narratives') or []
    if dcn_narratives:
        # Citation footers are rendered per-card; collect unique cites for a
        # consolidated footer note.
        _reason_badge_color = {
            'logic_driven': '#3b82f6',       # navy/blue — logic
            'constraint_driven': '#f59e0b',  # amber — constraint
            'false_cp': '#ef4444',           # red — false CP
        }
        _reason_label = {
            'logic_driven': 'LOGIC-DRIVEN',
            'constraint_driven': 'CONSTRAINT-DRIVEN',
            'false_cp': 'FALSE CP',
        }
        cards = ''
        for n in dcn_narratives:
            reason = n.get('criticality_reason', 'logic_driven')
            badge_color = _reason_badge_color.get(reason, '#3b82f6')
            badge_label = _reason_label.get(reason, reason.upper())
            code = n.get('task_code') or n.get('code') or ''
            name = n.get('task_name') or n.get('name') or ''
            chain = n.get('chain') or []
            chain_html = ' &rarr; '.join(_escape(c) for c in chain) if chain else '&mdash;'
            narrative_text = n.get('narrative') or ''
            cites = n.get('aace_citations') or []
            cites_html = ' &middot; '.join(_escape(c) for c in cites) if cites else ''
            heading = _escape(code)
            if name and name != code:
                heading = f'{_escape(code)} <span style="color:#94a3b8;font-weight:400;">{_escape(name)}</span>'
            cards += f'''
            <div class="dcn-card" style="border-left: 4px solid {badge_color}; background: rgba(148,163,184,0.04); padding: 14px 16px; border-radius: 8px; margin-bottom: 12px;">
                <div class="dcn-header" style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; flex-wrap:wrap; gap:8px;">
                    <h3 style="font-size: 0.95rem; font-weight: 700; color: #f1f5f9; margin:0;">{heading}</h3>
                    <span class="dcn-badge" style="background: {badge_color}; color: #fff; padding: 2px 10px; border-radius: 4px; font-size: 0.7rem; font-weight: 700; letter-spacing: 0.5px;">{_escape(badge_label)}</span>
                </div>
                <div class="dcn-chain" style="font-family: 'JetBrains Mono', Consolas, monospace; font-size: 0.78rem; color: #cbd5e1; background: #0f172a; padding: 6px 10px; border-radius: 4px; margin-bottom: 8px; overflow-x: auto; white-space: nowrap;">{chain_html}</div>
                <div class="dcn-narrative" style="font-size: 0.85rem; color: #e2e8f0; line-height: 1.55; margin-bottom: 6px;">{_escape(narrative_text)}</div>
                <div class="dcn-cite" style="font-size: 0.7rem; color: #64748b; font-style: italic;">{cites_html}</div>
            </div>'''
        # Caveat footer (verbatim from driver_chain_narrative manifest)
        manifest = dcn_block.get('manifest') or {}
        caveat = manifest.get('narrative_caveat', '')
        caveat_html = ''
        if caveat:
            caveat_html = f'<div style="font-size: 0.72rem; color: #64748b; font-style: italic; margin-top: 8px; padding: 8px 12px; background: rgba(15,23,42,0.5); border-radius: 4px;">{_escape(caveat)}</div>'
        dcn_html = f'''
    <!-- Driver-Chain Narratives -->
    <div class="section-title">Driver-Chain Narratives ({len(dcn_narratives)})</div>
    <div>{cards}</div>
    {caveat_html}
    '''
    elif dcn_block.get('error'):
        dcn_html = f'''
    <!-- Driver-Chain Narratives -->
    <div class="section-title">Driver-Chain Narratives</div>
    <div style="font-size:0.8rem;color:#64748b;padding:8px 12px;background:rgba(15,23,42,0.5);border-radius:4px;">{_escape(dcn_block.get('error',''))}</div>
    '''

    # Gauge SVG
    score = results['overall_score']
    gauge_color = _rating_color(results['overall_rating'])
    gauge_angle = (score / 100) * 180
    # SVG arc for gauge
    import math
    start_x = 50 + 40 * math.cos(math.radians(180))
    start_y = 55 + 40 * math.sin(math.radians(180))
    end_angle = 180 - gauge_angle
    end_x = 50 + 40 * math.cos(math.radians(end_angle))
    end_y = 55 - 40 * math.sin(math.radians(end_angle))
    large_arc = 1 if gauge_angle > 180 else 0

    gauge_svg = f'''
    <svg viewBox="0 0 100 65" class="gauge-svg">
        <path d="M 10 55 A 40 40 0 0 1 90 55" fill="none" stroke="#1e293b" stroke-width="8" stroke-linecap="round"/>
        <path d="M {start_x:.1f} {start_y:.1f} A 40 40 0 {large_arc} 1 {end_x:.1f} {end_y:.1f}" fill="none" stroke="{gauge_color}" stroke-width="8" stroke-linecap="round"/>
        <text x="50" y="52" text-anchor="middle" fill="{gauge_color}" font-size="18" font-weight="700">{score:.0f}</text>
        <text x="50" y="63" text-anchor="middle" fill="#94a3b8" font-size="5.5">{_escape(results['overall_confidence'])}</text>
    </svg>'''

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Critical Path Validation — {_escape(results['project_name'])}</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; background: #0a0f1a; color: #e2e8f0; padding: 24px; line-height: 1.5; }}
    .container {{ max-width: 1400px; margin: 0 auto; }}

    /* Header */
    .header {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 32px; flex-wrap: wrap; gap: 16px; }}
    .header-left h1 {{ font-size: 1.5rem; font-weight: 700; color: #f1f5f9; margin-bottom: 4px; }}
    .header-left .subtitle {{ color: #94a3b8; font-size: 0.85rem; }}
    .header-right {{ text-align: right; }}
    .header-right .meta {{ color: #94a3b8; font-size: 0.8rem; }}

    /* Gauge */
    .gauge-container {{ text-align: center; margin-bottom: 32px; }}
    .gauge-svg {{ width: 220px; height: 150px; }}
    .gauge-label {{ color: #94a3b8; font-size: 0.85rem; margin-top: 4px; }}

    /* Check Cards */
    .checks-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(380px, 1fr)); gap: 12px; margin-bottom: 32px; }}
    .check-card {{ padding: 14px 16px; border-radius: 8px; }}
    .check-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }}
    .check-name {{ font-weight: 600; font-size: 0.9rem; color: #f1f5f9; }}
    .check-badge {{ padding: 2px 10px; border-radius: 4px; font-size: 0.7rem; font-weight: 700; color: #fff; text-transform: uppercase; letter-spacing: 0.5px; }}
    .check-note {{ font-size: 0.8rem; color: #cbd5e1; }}

    /* Section Headers */
    .section-title {{ font-size: 1.1rem; font-weight: 700; color: #f1f5f9; margin: 28px 0 12px; padding-bottom: 6px; border-bottom: 1px solid #1e293b; }}

    /* Tables */
    .table-wrap {{ overflow-x: auto; margin-bottom: 24px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.8rem; }}
    th {{ background: #1e293b; color: #94a3b8; padding: 8px 10px; text-align: left; font-weight: 600; text-transform: uppercase; font-size: 0.7rem; letter-spacing: 0.5px; position: sticky; top: 0; }}
    td {{ padding: 7px 10px; border-bottom: 1px solid #1e293b; color: #cbd5e1; }}
    tr:hover td {{ background: rgba(148,163,184,0.05); }}

    /* Flags */
    .flag-red {{ color: #ef4444; font-weight: 600; font-size: 0.75rem; }}
    .flag-amber {{ color: #f59e0b; font-weight: 600; font-size: 0.75rem; }}
    .pri-badge {{ padding: 2px 8px; border-radius: 4px; font-size: 0.7rem; font-weight: 700; color: #fff; }}

    /* Stats bar */
    .stats-bar {{ display: flex; gap: 24px; flex-wrap: wrap; margin-bottom: 24px; padding: 16px; background: #111827; border-radius: 8px; }}
    .stat {{ text-align: center; }}
    .stat-value {{ font-size: 1.4rem; font-weight: 700; color: #f1f5f9; }}
    .stat-label {{ font-size: 0.7rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; }}

    /* Print */
    @media print {{
        body {{ background: #fff; color: #1e293b; padding: 12px; }}
        .check-card {{ border: 1px solid #e2e8f0; }}
        th {{ background: #f1f5f9; color: #475569; }}
        td {{ border-bottom-color: #e2e8f0; color: #334155; }}
        .stats-bar {{ background: #f8fafc; }}
    }}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <div class="header-left">
            <h1>Critical Path Validation Report</h1>
            <div class="subtitle">{_escape(results['project_name'])}</div>
        </div>
        <div class="header-right">
            <div class="meta">Data Date: {_escape(results['data_date']) if results['data_date'] else '(not set)'}</div>
            <div class="meta">Analyzed: {_escape(results['analysis_timestamp'])}</div>
        </div>
    </div>

    <!-- Stats Bar -->
    <div class="stats-bar">
        <div class="stat"><div class="stat-value">{results['total_activities']}</div><div class="stat-label">Total Activities</div></div>
        <div class="stat"><div class="stat-value">{results['complete']}</div><div class="stat-label">Complete</div></div>
        <div class="stat"><div class="stat-value">{results['in_progress']}</div><div class="stat-label">In Progress</div></div>
        <div class="stat"><div class="stat-value">{results['not_started']}</div><div class="stat-label">Not Started</div></div>
        <div class="stat"><div class="stat-value">{len(results['critical_path_activities'])}</div><div class="stat-label">Critical</div></div>
        <div class="stat"><div class="stat-value">{len(results['near_critical_activities'])}</div><div class="stat-label">Near-Critical</div></div>
        <div class="stat"><div class="stat-value">{len(results['recommendations'])}</div><div class="stat-label">Recommendations</div></div>
    </div>

    <!-- Gauge -->
    <div class="gauge-container">
        {gauge_svg}
        <div class="gauge-label">CP Confidence Score</div>
    </div>

    <!-- Check Results -->
    <div class="section-title">Validation Check Results</div>
    <div class="checks-grid">{check_cards}</div>

    <!-- DCMA 14 Scorecard -->
    {dcma_html}

    <!-- Critical Path Activities -->
    <div class="section-title">Critical Path Activities ({len(results['critical_path_activities'])})</div>
    <div class="table-wrap">
        <table>
            <thead><tr><th>Code</th><th>Activity Name</th><th>Total Float</th><th>Constraints</th><th>Logic Flags</th><th>Status</th></tr></thead>
            <tbody>{cp_rows if cp_rows else '<tr><td colspan="6" style="text-align:center; color:#64748b;">No critical path activities found</td></tr>'}</tbody>
        </table>
    </div>

    {dcn_html}

    <!-- Near-Critical Activities -->
    <div class="section-title">Near-Critical Activities — TF 1-10 Days ({len(results['near_critical_activities'])})</div>
    <div class="table-wrap">
        <table>
            <thead><tr><th>Code</th><th>Activity Name</th><th>Total Float</th><th>Status</th></tr></thead>
            <tbody>{nc_rows if nc_rows else '<tr><td colspan="4" style="text-align:center; color:#64748b;">No near-critical activities</td></tr>'}</tbody>
        </table>
    </div>

    <!-- Recommendations -->
    <div class="section-title">Recommendations ({len(results['recommendations'])})</div>
    <div class="table-wrap">
        <table>
            <thead><tr><th>Priority</th><th>Category</th><th>Finding</th><th>Recommendation</th><th>Activity</th></tr></thead>
            <tbody>{rec_rows if rec_rows else '<tr><td colspan="5" style="text-align:center; color:#64748b;">No recommendations — schedule is clean</td></tr>'}</tbody>
        </table>
    </div>

    <!-- Open Ends -->
    <div class="section-title">Open Ends — Incomplete Activities ({len(results['open_ends']['no_pred']) + len(results['open_ends']['no_succ'])})</div>
    <div class="table-wrap">
        <table>
            <thead><tr><th>Code</th><th>Activity Name</th><th>Issue</th><th>Status</th><th>On CP?</th></tr></thead>
            <tbody>{oe_rows if oe_rows else '<tr><td colspan="5" style="text-align:center; color:#64748b;">No open ends on incomplete activities</td></tr>'}</tbody>
        </table>
    </div>

    <div style="text-align:center; color:#475569; font-size:0.7rem; margin-top:32px; padding-top:16px; border-top:1px solid #1e293b;">
        Critical Path Validator — Generated by Critical Path Partners Schedule Intelligence Suite
    </div>
</div>
</body>
</html>'''

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    return output_path


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def _cli():
    import argparse
    import os
    import sys
    import json as _json

    _HERE = os.path.dirname(os.path.abspath(__file__))
    _XER_PARSER = os.path.normpath(os.path.join(_HERE, '..', '..', 'xer-parser', 'scripts'))
    if os.path.isdir(_XER_PARSER) and _XER_PARSER not in sys.path:
        sys.path.insert(0, _XER_PARSER)
    from xer_parser import parse_xer  # noqa: E402

    p = argparse.ArgumentParser(description='Validate critical path logic in a P6 XER file.')
    p.add_argument('xer', help='Path to XER file')
    p.add_argument('-o', '--output', default=None,
                   help='HTML dashboard path (default: cp_validation_<project>.html)')
    p.add_argument('--project-index', type=int, default=0,
                   help='Which project inside a multi-project XER (default: 0)')
    p.add_argument('--json', default=None, help='Also write raw results to this JSON path')
    p.add_argument('--print-rating', action='store_true',
                   help='Only print the overall rating to stdout (for scripting)')
    args = p.parse_args()

    data = parse_xer(args.xer)
    results = validate_critical_path(data, project_index=args.project_index)

    rating = results.get('overall_rating', 'unknown')
    score = results.get('overall_score')

    if args.print_rating:
        print(rating)
        return

    output_path = args.output
    if not output_path:
        proj = os.path.splitext(os.path.basename(args.xer))[0]
        output_path = f'cp_validation_{proj}.html'
    generate_dashboard(results, output_path)
    print(f'Dashboard: {output_path}')

    if args.json:
        with open(args.json, 'w', encoding='utf-8') as f:
            _json.dump(results, f, indent=2, default=str)
        print(f'Results JSON: {args.json}')

    score_txt = f' (score={score})' if score is not None else ''
    print(f'Rating: {rating}{score_txt}')


if __name__ == '__main__':
    _cli()
