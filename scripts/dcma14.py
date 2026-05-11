#!/usr/bin/env python3
"""DCMA 14-Point Schedule Assessment.

Implements the Defense Contract Management Agency 14-Point assessment plus
the BEI (Baseline Execution Index) metric and the "multiple critical paths /
CP continuity / driving-path tracer" extras called out by the VP teardown
review.

The DCMA 14 checks, as implemented here:

    1. Logic          — % activities missing predecessor or successor
    2. Leads          — count of negative lag_hr_cnt relationships
    3. Lags           — % of relationships with positive lag
    4. Relationship   — % Finish-to-Start (FS) relationships
    5. Hard           — % activities with hard constraint (MANDSTART/FIN, MSO, MEO)
    6. High Float     — % activities with total float > threshold (44d commercial)
    7. Negative Float — count of activities with TF < 0
    8. High Duration  — % activities with remaining duration > threshold
    9. Invalid Dates  — future actuals or past planned-not-complete (merges old #11)
   10. Resources      — % activities with TASKRSRC assignments
   11. (merged into #9)
   12. (see #10)
   13. Missed Tasks   — % activities due by data_date but not complete
   14. CPLI           — (CP length + total_float) / CP length ≥ 0.95 / 0.98

Extras (beyond the 14):

   • BEI              — (tasks completed by data_date) / (tasks baselined to
                        be complete by data_date). Requires a baseline XER.
   • Multiple CPs     — distinct critical chains (by crt_path_num or
                        by connected-component grouping).
   • CP Continuity    — detect gaps (non-critical predecessor → critical
                        successor) in the critical chain.
   • Driving-path     — walk the predecessor chain of driving activities
                        back to the data date from a given task_code.

Public API:
    dcma_14_assess(data, profile='commercial', baseline_data=None) -> dict

Standards:
    DCMA 14-Point Assessment (FAR Part 49, DFARS 234.2)
    AACE 49R-06 "Identifying the Critical Path"
    NDIA PASEG (Planning and Scheduling Excellence Guide) §10
"""
import os
import sys
from datetime import datetime, timedelta

# Make _cpp_common and xer-parser importable regardless of cwd.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_COMMON_SCRIPTS = os.path.normpath(os.path.join(_SCRIPT_DIR, '..', '..', '_cpp_common', 'scripts'))
_XER_PARSER_SCRIPTS = os.path.normpath(os.path.join(_SCRIPT_DIR, '..', '..', 'xer-parser', 'scripts'))
for _path in (_COMMON_SCRIPTS, _XER_PARSER_SCRIPTS, _SCRIPT_DIR):
    if os.path.isdir(_path) and _path not in sys.path:
        sys.path.insert(0, _path)

from validation import Finding, ValidationReport, BLOCK, WARN, INFO, PASS  # noqa: E402
from config_profiles import get_profile  # noqa: E402
from xer_parser import (  # noqa: E402
    get_table,
    get_calendar_map,
    COMPLETE_STATUS,
    ACTIVE_STATUS,
    NOT_STARTED_STATUS,
    EXCLUDED_TASK_TYPES,
    MILESTONE_TASK_TYPES,
)

# Reuse the hard-constraint taxonomy from cp_validator — single source of truth.
from cp_validator import HARD_CONSTRAINTS, _hrs_to_days, _safe_float  # noqa: E402


# ─────────────────────────────────────────────────────────────────────
# Helpers — date parsing and misc
# ─────────────────────────────────────────────────────────────────────

def _parse_date(val):
    """Parse a P6 date field (YYYY-MM-DD HH:MM) into a datetime. Returns None on failure.

    Intentionally NOT migrated to _cpp_common.utils.parse_date — that helper returns
    `datetime.date`, but this module needs `datetime.datetime` for HH:MM-aware
    arithmetic against `data_date_dt` and other datetime fields throughout DCMA-14.
    """
    if not val:
        return None
    s = str(val).strip()
    if not s:
        return None
    for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.strptime(s[:19] if fmt == '%Y-%m-%d %H:%M:%S' else s[:16] if fmt == '%Y-%m-%d %H:%M' else s[:10], fmt)
        except ValueError:
            continue
    return None


def _is_work_task(t):
    """True if t is a schedulable activity (not LOE/WBS/Hammock)."""
    return t.get('task_type', '') not in EXCLUDED_TASK_TYPES


def _pct_complete(t):
    """Physical or schedule-based % complete, 0-100."""
    # Prefer phys_complete_pct when available; fall back to duration-based.
    for key in ('phys_complete_pct', 'act_pct_complete'):
        v = _safe_float(t.get(key, ''), -1.0)
        if 0.0 <= v <= 100.0:
            return v
    # Fall back to 100 * (target - remain) / target
    target = _safe_float(t.get('target_drtn_hr_cnt', ''), 0.0)
    remain = _safe_float(t.get('remain_drtn_hr_cnt', ''), target)
    if target > 0:
        return max(0.0, min(100.0, 100.0 * (target - remain) / target))
    return 0.0


# ─────────────────────────────────────────────────────────────────────
# Per-check implementations
# Each returns (severity, value, threshold, message, details_dict)
# ─────────────────────────────────────────────────────────────────────

def _check_01_logic(work_tasks, pred_map, succ_map, profile):
    """#1 Logic — % of work activities missing predecessor or successor.

    Following the standard DCMA interpretation: start milestones (TT_Mile) are
    allowed to have no predecessor, and finish milestones (TT_FinMile) are
    allowed to have no successor. Both are legitimate anchors.
    """
    threshold = profile['dcma_logic_max_missing_pct']
    if not work_tasks:
        return PASS, 0.0, threshold, 'No work tasks (vacuous pass).', {'missing_count': 0}
    missing = []
    for t in work_tasks:
        tid = t['task_id']
        ttype = t.get('task_type', '')
        needs_pred = ttype != 'TT_FinMile'     # finish milestones can start-anchor
        needs_succ = ttype != 'TT_FinMile'     # finish milestones legitimately have no successor
        # TT_Mile (start milestone) should have a successor but may lack a predecessor
        if ttype == 'TT_Mile':
            needs_pred = False
            needs_succ = True
        missing_pred = needs_pred and tid not in pred_map
        missing_succ = needs_succ and tid not in succ_map
        if missing_pred or missing_succ:
            missing.append(t.get('task_code', tid))
    pct = len(missing) / len(work_tasks) * 100.0
    sev = PASS if pct <= threshold else WARN
    return sev, pct, threshold, (
        f'{len(missing)} of {len(work_tasks)} activities ({pct:.1f}%) missing '
        f'predecessor or successor (threshold ≤ {threshold}%).'
    # Full list — never truncate. CPP forensic-correctness rule: every
    ), {'missing_count': len(missing), 'examples': list(missing)}


def _check_02_leads(preds_all, profile):
    """#2 Leads — count of relationships with negative lag (leads). Must be 0."""
    threshold = profile['dcma_leads_max_count']
    leads = [p for p in preds_all if _safe_float(p.get('lag_hr_cnt', '0'), 0.0) < 0]
    sev = PASS if len(leads) <= threshold else BLOCK
    return sev, len(leads), threshold, (
        f'{len(leads)} negative lag(s) (leads) in the schedule (threshold ≤ {threshold}). '
        'Leads hide true duration and violate DCMA #2.'
    ), {'lead_count': len(leads)}


def _check_03_lags(preds_all, profile):
    """#3 Lags — % of relationships with positive lag."""
    threshold = profile['dcma_lags_max_pct']
    if not preds_all:
        return PASS, 0.0, threshold, 'No relationships (vacuous pass).', {'lag_count': 0}
    lagged = [p for p in preds_all if _safe_float(p.get('lag_hr_cnt', '0'), 0.0) > 0]
    pct = len(lagged) / len(preds_all) * 100.0
    sev = PASS if pct <= threshold else WARN
    return sev, pct, threshold, (
        f'{len(lagged)} of {len(preds_all)} relationships ({pct:.1f}%) have '
        f'positive lag (threshold ≤ {threshold}%).'
    ), {'lag_count': len(lagged)}


def _check_04_relationship_types(preds_all, profile):
    """#4 Relationship Types — % Finish-to-Start."""
    threshold = profile['dcma_fs_min_pct']
    if not preds_all:
        return PASS, 100.0, threshold, 'No relationships (vacuous pass).', {}
    fs = sum(1 for p in preds_all if p.get('pred_type', '') == 'PR_FS')
    pct = fs / len(preds_all) * 100.0
    sev = PASS if pct >= threshold else WARN
    return sev, pct, threshold, (
        f'{fs} of {len(preds_all)} relationships ({pct:.1f}%) are FS '
        f'(threshold ≥ {threshold}%).'
    ), {'fs_count': fs}


def _check_05_hard_constraints(work_tasks, profile):
    """#5 Hard Constraints — % of activities with hard constraint."""
    threshold = profile['dcma_hard_constraints_max_pct']
    if not work_tasks:
        return PASS, 0.0, threshold, 'No work tasks (vacuous pass).', {}
    hard = [
        t for t in work_tasks
        if (t.get('cstr_type', '') in HARD_CONSTRAINTS or
            t.get('cstr_type2', '') in HARD_CONSTRAINTS)
    ]
    pct = len(hard) / len(work_tasks) * 100.0
    sev = PASS if pct <= threshold else WARN
    return sev, pct, threshold, (
        f'{len(hard)} of {len(work_tasks)} activities ({pct:.1f}%) have '
        f'hard constraints (threshold ≤ {threshold}%).'
    ), {'hard_count': len(hard)}


def _check_06_high_float(incomplete, cal_map, profile):
    """#6 High Float — % of incomplete activities with TF > max_days."""
    max_days = profile['dcma_high_float_max_days']
    threshold = profile['dcma_high_float_max_pct']
    if not incomplete:
        return PASS, 0.0, threshold, 'No incomplete tasks (vacuous pass).', {}
    high = []
    for t in incomplete:
        tf_hrs = _safe_float(t.get('total_float_hr_cnt', ''), 0.0)
        tf_days = _hrs_to_days(tf_hrs, cal_map, t.get('clndr_id', ''))
        if tf_days > max_days:
            high.append(t.get('task_code', t['task_id']))
    pct = len(high) / len(incomplete) * 100.0
    sev = PASS if pct <= threshold else WARN
    return sev, pct, threshold, (
        f'{len(high)} of {len(incomplete)} incomplete activities ({pct:.1f}%) '
        f'have total float > {max_days}d (threshold ≤ {threshold}%).'
    ), {'high_float_count': len(high), 'max_days': max_days}


def _check_07_negative_float(incomplete, cal_map, profile):
    """#7 Negative Float — count of activities with TF < 0."""
    threshold = profile['dcma_negative_float_max_count']
    neg = []
    for t in incomplete:
        tf_hrs = _safe_float(t.get('total_float_hr_cnt', ''), 0.0)
        if tf_hrs < 0:
            neg.append(t.get('task_code', t['task_id']))
    sev = PASS if len(neg) <= threshold else BLOCK
    return sev, len(neg), threshold, (
        f'{len(neg)} activities with negative total float (threshold ≤ {threshold}). '
        'Any negative float means the schedule cannot finish on time as currently logicked.'
    # Full list — never truncate. CPP forensic-correctness rule: every
    ), {'neg_float_count': len(neg), 'examples': list(neg)}


def _check_08_high_duration(incomplete, cal_map, profile):
    """#8 High Duration — % of incomplete activities with remaining duration > max."""
    max_days = profile['dcma_high_duration_max_days']
    threshold = profile['dcma_high_duration_max_pct']
    if not incomplete:
        return PASS, 0.0, threshold, 'No incomplete tasks (vacuous pass).', {}
    long_ones = []
    for t in incomplete:
        # Skip milestones — they're zero-duration by definition.
        if t.get('task_type', '') in MILESTONE_TASK_TYPES:
            continue
        rem_hrs = _safe_float(t.get('remain_drtn_hr_cnt', ''), 0.0)
        rem_days = _hrs_to_days(rem_hrs, cal_map, t.get('clndr_id', ''))
        if rem_days > max_days:
            long_ones.append(t.get('task_code', t['task_id']))
    # Percentage is over incomplete non-milestones
    non_mile = [t for t in incomplete if t.get('task_type', '') not in MILESTONE_TASK_TYPES]
    denom = len(non_mile) or 1
    pct = len(long_ones) / denom * 100.0
    sev = PASS if pct <= threshold else WARN
    return sev, pct, threshold, (
        f'{len(long_ones)} of {denom} non-milestone activities ({pct:.1f}%) have '
        f'remaining duration > {max_days}d (threshold ≤ {threshold}%).'
    ), {'high_duration_count': len(long_ones), 'max_days': max_days}


def _check_09_invalid_dates(work_tasks, data_date_dt, profile):
    """#9 Invalid Dates — future actual (act_start/finish > data_date) OR
    past planned (target_end < data_date AND pct<100)."""
    threshold = profile['dcma_invalid_dates_max_count']
    if data_date_dt is None:
        return INFO, 0, threshold, (
            'No data date on project — cannot evaluate invalid dates.'
        ), {'issues': []}
    issues = []
    for t in work_tasks:
        tc = t.get('task_code', t['task_id'])
        # Future actual checks
        for field in ('act_start_date', 'act_end_date'):
            v = _parse_date(t.get(field, ''))
            if v and v > data_date_dt:
                issues.append(f'{tc}:{field}>{data_date_dt.date()}')
        # Past-planned-not-complete
        pct = _pct_complete(t)
        te = _parse_date(t.get('target_end_date', ''))
        if te and te < data_date_dt and pct < 100.0 and t.get('status_code', '') != COMPLETE_STATUS:
            # Only count if there's no actual_end — otherwise the activity
            # actually finished; target_end is just historical.
            if not _parse_date(t.get('act_end_date', '')):
                issues.append(f'{tc}:target_end<{data_date_dt.date()}&pct={pct:.0f}')
    sev = PASS if len(issues) <= threshold else BLOCK
    return sev, len(issues), threshold, (
        f'{len(issues)} activities with invalid dates (threshold ≤ {threshold}). '
        'Future actual dates or past-planned-not-complete dates corrupt forensic analysis.'
    # Full list — never truncate. CPP forensic-correctness rule: every
    ), {'invalid_count': len(issues), 'examples': list(issues)}


def _check_10_resources(work_tasks, rsrc_assignments, profile):
    """#10 Resources — % of activities with TASKRSRC assignments.

    When the profile has the threshold disabled (commercial default: 0), the
    check vacuously PASSES — it's marked-as-not-applicable rather than
    penalising every commercial schedule.
    """
    threshold = profile['dcma_resources_min_pct']
    if not work_tasks:
        return PASS, 0.0, threshold, 'No work tasks (vacuous pass).', {}
    assigned_ids = {r.get('task_id', '') for r in rsrc_assignments}
    hits = sum(1 for t in work_tasks if t['task_id'] in assigned_ids)
    pct = hits / len(work_tasks) * 100.0
    if threshold <= 0:
        # Profile disables this check — vacuous PASS with an informational
        # note for the scheduler.
        return PASS, pct, threshold, (
            f'Resource loading not required by profile '
            f'({pct:.1f}% loaded; threshold ≥ {threshold}%).'
        ), {'loaded_count': hits, 'disabled': True}
    sev = PASS if pct >= threshold else WARN
    return sev, pct, threshold, (
        f'{hits} of {len(work_tasks)} activities ({pct:.1f}%) have resource '
        f'assignments (threshold ≥ {threshold}%).'
    ), {'loaded_count': hits}


def _check_13_missed_tasks(work_tasks, data_date_dt, profile):
    """#13 Missed Tasks — activities that were supposed to be complete by the
    data date but aren't."""
    threshold = profile['dcma_missed_tasks_max_pct']
    if data_date_dt is None or not work_tasks:
        return INFO, 0.0, threshold, (
            'No data date or no work tasks — skipping.'
        ), {'missed_count': 0}
    # Scope: activities that had a baseline target_end_date <= data_date
    due_by_dd = []
    for t in work_tasks:
        te = _parse_date(t.get('target_end_date', ''))
        if te and te <= data_date_dt:
            due_by_dd.append(t)
    if not due_by_dd:
        return PASS, 0.0, threshold, (
            'No activities baselined to complete by data date (vacuous pass).'
        ), {'missed_count': 0}
    missed = [
        t for t in due_by_dd
        if t.get('status_code', '') != COMPLETE_STATUS
    ]
    pct = len(missed) / len(due_by_dd) * 100.0
    sev = PASS if pct <= threshold else WARN
    return sev, pct, threshold, (
        f'{len(missed)} of {len(due_by_dd)} activities due-by-data-date '
        f'({pct:.1f}%) are not complete (threshold ≤ {threshold}%).'
    ), {'missed_count': len(missed), 'due_by_dd': len(due_by_dd)}


def _check_14_cpli(cp_tasks, cal_map, data_date_dt, profile, project=None):
    """#14 Critical Path Length Index.

    CPLI = (CP length + total_float) / CP length, where:
      • CP length = working days from data_date to the latest early-finish on CP
      • total_float = total float (days) of the most-critical activity
                      (lowest TF, including negative)

    CPLI >= 1.00 means the schedule is on or ahead; <1.00 means behind. The
    DCMA acceptable floor is 0.95 commercial, 0.98 nuclear.

    `project` is the PROJECT-table row for the schedule (used to pick the
    default calendar for the working-day conversion of CP length). Optional
    for back-compat — falls back to wall-clock days if not provided, but
    callers should pass it to get the calendar-correct value.
    """
    threshold = profile['dcma_cpli_min']
    if not cp_tasks or data_date_dt is None:
        return INFO, None, threshold, (
            'No CP activities or no data date — cannot compute CPLI.'
        ), {'cpli': None}

    # Find latest early-finish on the CP
    latest_ef = None
    for t in cp_tasks:
        ef = _parse_date(t.get('early_end_date', ''))
        if ef and (latest_ef is None or ef > latest_ef):
            latest_ef = ef
    if latest_ef is None:
        # Fall back to target_end_date as the last-known finish
        for t in cp_tasks:
            te = _parse_date(t.get('target_end_date', ''))
            if te and (latest_ef is None or te > latest_ef):
                latest_ef = te
    if latest_ef is None or latest_ef <= data_date_dt:
        return INFO, None, threshold, (
            'Cannot determine CP end date — CPLI not computable.'
        ), {'cpli': None}

    # CP length in WORKING days (calendar-aware), not wall-clock days. Using
    # wall-clock inflates the denominator by counting weekends/holidays the
    # CP cannot actually be worked on, which artificially boosts CPLI by
    # ~28% on 5-day calendars. Convert hours→days through the project's
    # default calendar so the result matches what schedulers see in P6.
    cp_length_hours = (latest_ef - data_date_dt).total_seconds() / 3600.0
    default_clndr_id = (project or {}).get('clndr_id', '') or (project or {}).get('dflt_clndr_id', '')
    cp_length_days = _hrs_to_days(cp_length_hours, cal_map, default_clndr_id)
    if cp_length_days <= 0:
        return INFO, None, threshold, (
            'CP length ≤ 0 — CPLI not computable.'
        ), {'cpli': None}

    # Total float of the most-critical activity (lowest TF, calendar-aware days)
    tf_days_min = None
    for t in cp_tasks:
        tf_hrs = _safe_float(t.get('total_float_hr_cnt', ''), 0.0)
        tf_days = _hrs_to_days(tf_hrs, cal_map, t.get('clndr_id', ''))
        if tf_days_min is None or tf_days < tf_days_min:
            tf_days_min = tf_days
    tf_days_min = tf_days_min if tf_days_min is not None else 0.0

    cpli = (cp_length_days + tf_days_min) / cp_length_days
    sev = PASS if cpli >= threshold else BLOCK
    return sev, cpli, threshold, (
        f'CPLI = {cpli:.3f} (threshold ≥ {threshold}). CP length = {cp_length_days:.1f}d, '
        f'total float of most-critical activity = {tf_days_min:.1f}d.'
    ), {'cpli': cpli, 'cp_length_days': cp_length_days, 'tf_days_min': tf_days_min}


# ─────────────────────────────────────────────────────────────────────
# BEI — Baseline Execution Index
# ─────────────────────────────────────────────────────────────────────

def _compute_bei(current_data, baseline_data, data_date_dt, profile):
    """BEI = tasks completed by data_date / tasks baselined to be complete by data_date.

    Requires a baseline dataset. If no baseline, returns None with an INFO severity.
    """
    threshold = profile['bei_min']
    if baseline_data is None:
        return INFO, None, threshold, (
            'No baseline provided — BEI cannot be computed.'
        ), {'bei': None}
    if data_date_dt is None:
        return INFO, None, threshold, (
            'No data date — BEI cannot be computed.'
        ), {'bei': None}

    baseline_tasks = [t for t in get_table(baseline_data, 'TASK') if _is_work_task(t)]
    current_tasks = [t for t in get_table(current_data, 'TASK') if _is_work_task(t)]

    # Activities baselined to be complete by the data date
    bl_due = {}
    for bt in baseline_tasks:
        te = _parse_date(bt.get('target_end_date', ''))
        if te and te <= data_date_dt:
            code = bt.get('task_code', bt.get('task_id', ''))
            bl_due[code] = bt
    if not bl_due:
        return INFO, None, threshold, (
            'No activities baselined to complete by data date — BEI not computable.'
        ), {'bei': None, 'baselined_due': 0}

    # Current status of those same activities (match by task_code)
    completed = 0
    for code in bl_due:
        ct = next((t for t in current_tasks if t.get('task_code', '') == code), None)
        if ct is not None and ct.get('status_code', '') == COMPLETE_STATUS:
            completed += 1

    bei = completed / len(bl_due)
    sev = PASS if bei >= threshold else WARN
    return sev, bei, threshold, (
        f'BEI = {bei:.3f} (threshold ≥ {threshold}). {completed} of {len(bl_due)} '
        f'baselined-to-be-complete activities are actually complete.'
    ), {'bei': bei, 'completed': completed, 'baselined_due': len(bl_due)}


# ─────────────────────────────────────────────────────────────────────
# Multiple critical paths, CP continuity, driving-path tracer
# ─────────────────────────────────────────────────────────────────────

def _identify_critical_paths(cp_tasks, pred_map, task_map):
    """Group CP activities into distinct critical paths.

    Strategy:
      1. Prefer P6's own `crt_path_num` flag when multiple distinct values
         exist (>0). Each distinct value is one longest-path chain.
      2. Otherwise, fall back to connected-component grouping within the CP
         edge subgraph.
    Each group is then linearized into a chain by walking from its earliest
    start to its latest finish via the predecessor chain.

    Returns: list of lists, each inner list is task_codes in driving order.
    """
    if not cp_tasks:
        return []

    # Bucket by crt_path_num if multiple nonzero values are present
    buckets_by_flag = {}
    for t in cp_tasks:
        flag = str(t.get('crt_path_num', '') or '').strip()
        if flag and flag != '0':
            buckets_by_flag.setdefault(flag, []).append(t)
    use_flag = len(buckets_by_flag) >= 2

    if use_flag:
        groups = list(buckets_by_flag.values())
    else:
        # Connected-component grouping over the CP edges
        cp_ids = {t['task_id'] for t in cp_tasks}
        adjacency = {tid: set() for tid in cp_ids}
        for succ_id, preds_list in pred_map.items():
            if succ_id not in cp_ids:
                continue
            for p in preds_list:
                pid = p.get('pred_task_id', '')
                if pid in cp_ids:
                    adjacency[succ_id].add(pid)
                    adjacency[pid].add(succ_id)
        visited = set()
        groups = []
        for tid in cp_ids:
            if tid in visited:
                continue
            comp = []
            stack = [tid]
            while stack:
                cur = stack.pop()
                if cur in visited:
                    continue
                visited.add(cur)
                comp.append(task_map[cur])
                for neighbor in adjacency[cur]:
                    if neighbor not in visited:
                        stack.append(neighbor)
            groups.append(comp)

    # Linearize each group: sort by early_start_date, then task_code
    result = []
    for grp in groups:
        def _sort_key(t):
            es = _parse_date(t.get('early_start_date', '')) or _parse_date(t.get('target_start_date', ''))
            return (es or datetime.max, t.get('task_code', ''))
        grp_sorted = sorted(grp, key=_sort_key)
        result.append([t.get('task_code', t['task_id']) for t in grp_sorted])
    # Sort path list by starting task code for deterministic output
    result.sort(key=lambda p: p[0] if p else '')
    return result


def _cp_continuity(cp_tasks, pred_map, task_map):
    """Detect gaps in the critical path.

    A "gap" is an activity whose critical successor has a non-critical
    predecessor that is not complete. We look at it from the successor side:
    for each CP activity, if any of its predecessors is (a) incomplete and
    (b) not on the CP, the chain has a break.

    Returns: {'continuous': bool, 'gaps': [{'cp_task': code, 'gap_pred': code}, ...]}
    """
    cp_ids = {t['task_id'] for t in cp_tasks}
    gaps = []
    for t in cp_tasks:
        tid = t['task_id']
        for p in pred_map.get(tid, []):
            pid = p.get('pred_task_id', '')
            if not pid or pid in cp_ids:
                continue
            pred_task = task_map.get(pid)
            if pred_task is None:
                continue
            if pred_task.get('status_code', '') == COMPLETE_STATUS:
                continue
            gaps.append({
                'cp_task': t.get('task_code', tid),
                'gap_pred': pred_task.get('task_code', pid),
                'gap_pred_status': pred_task.get('status_code', ''),
                'rel_type': p.get('pred_type', ''),
            })
    return {'continuous': not gaps, 'gaps': gaps}


def trace_driving_path(data, task_code, data_date=None):
    """Walk the predecessor chain of driving activities back to the data date.

    Starting at the task_code given, follow the predecessor with
    driving_path_flag == 'Y' (or the predecessor whose finish drives the
    successor's start, when the flag isn't set). Stop when:
      - no driving predecessor found, or
      - the predecessor is complete / before the data date.

    Returns: list of task_codes in driving order (source → target).
    """
    tasks = get_table(data, 'TASK')
    preds = get_table(data, 'TASKPRED')
    task_by_code = {t.get('task_code', ''): t for t in tasks}
    task_by_id = {t['task_id']: t for t in tasks}
    pred_map = {}
    for p in preds:
        pred_map.setdefault(p.get('task_id', ''), []).append(p)

    data_date_dt = _parse_date(data_date) if isinstance(data_date, str) else data_date
    if data_date_dt is None:
        project_rec = (get_table(data, 'PROJECT') or [{}])[0]
        data_date_dt = _parse_date(project_rec.get('last_recalc_date', ''))

    if task_code not in task_by_code:
        return []

    chain = [task_code]
    visited_ids = {task_by_code[task_code]['task_id']}
    current = task_by_code[task_code]
    max_steps = 200  # safety valve
    for _ in range(max_steps):
        tid = current['task_id']
        p_list = pred_map.get(tid, [])
        if not p_list:
            break
        # Prefer pred flagged driving on the relationship
        driver = None
        for p in p_list:
            if p.get('driving', '') == 'Y' or p.get('driving_path_flag', '') == 'Y':
                driver = p
                break
        if driver is None:
            # Fall back: pick the predecessor with the latest early_end_date
            latest_ef = None
            for p in p_list:
                ptask = task_by_id.get(p.get('pred_task_id', ''))
                if ptask is None:
                    continue
                ef = _parse_date(ptask.get('early_end_date', '')) \
                    or _parse_date(ptask.get('act_end_date', '')) \
                    or _parse_date(ptask.get('target_end_date', ''))
                if ef and (latest_ef is None or ef > latest_ef):
                    latest_ef = ef
                    driver = p
        if driver is None:
            break
        pid = driver.get('pred_task_id', '')
        if not pid or pid in visited_ids:
            break
        visited_ids.add(pid)
        pred_task = task_by_id.get(pid)
        if pred_task is None:
            break
        chain.append(pred_task.get('task_code', pid))
        # Stop at the data date
        if pred_task.get('status_code', '') == COMPLETE_STATUS:
            break
        ef = _parse_date(pred_task.get('early_end_date', '')) \
            or _parse_date(pred_task.get('act_end_date', ''))
        if data_date_dt and ef and ef < data_date_dt:
            break
        current = pred_task
    # Return in driving order (earliest predecessor first)
    return list(reversed(chain))


# ─────────────────────────────────────────────────────────────────────
# MAIN ASSESSMENT FUNCTION
# ─────────────────────────────────────────────────────────────────────

# Check registry — each entry is (id, name, reference, counts_toward_14_score)
# The 14 official DCMA checks that count toward the /14 score are tagged True.
_CHECK_REGISTRY = [
    ('DCMA-01-Logic', 'Logic', 'DCMA 14-Point #1', True),
    ('DCMA-02-Leads', 'Leads', 'DCMA 14-Point #2', True),
    ('DCMA-03-Lags', 'Lags', 'DCMA 14-Point #3', True),
    ('DCMA-04-Relationship', 'Relationship Types', 'DCMA 14-Point #4', True),
    ('DCMA-05-Hard', 'Hard Constraints', 'DCMA 14-Point #5', True),
    ('DCMA-06-HighFloat', 'High Float', 'DCMA 14-Point #6', True),
    ('DCMA-07-NegFloat', 'Negative Float', 'DCMA 14-Point #7', True),
    ('DCMA-08-HighDuration', 'High Duration', 'DCMA 14-Point #8', True),
    ('DCMA-09-InvalidDates', 'Invalid Dates', 'DCMA 14-Point #9', True),
    ('DCMA-10-Resources', 'Resources', 'DCMA 14-Point #10', True),
    ('DCMA-11-InvalidDatesFuture', 'Future Actuals', 'DCMA 14-Point #11 (merged into #9)', True),
    ('DCMA-12-ResourceCoverage', 'Resource Coverage', 'DCMA 14-Point #12 (same as #10)', True),
    ('DCMA-13-MissedTasks', 'Missed Tasks', 'DCMA 14-Point #13', True),
    ('DCMA-14-CPLI', 'Critical Path Length Index', 'DCMA 14-Point #14', True),
]


def dcma_14_assess(data, profile='commercial', baseline_data=None):
    """Run the full DCMA 14-Point assessment on parsed XER data.

    Args:
        data: parsed XER dict (from xer_parser.parse_xer or equivalent).
        profile: 'commercial' (default), 'nuclear', 'mining'.
        baseline_data: optional parsed XER baseline for BEI computation.

    Returns:
        dict: {
            'profile':                str,
            'report':                 ValidationReport,
            'dcma_score':             int (0-14),
            'cpli':                   float or None,
            'bei':                    float or None,
            'critical_paths':         list[list[task_code]],
            'multiple_critical_paths': bool,
            'cp_continuity':          {'continuous': bool, 'gaps': [...]},
            'per_check':              {check_id: {severity, value, threshold, message}},
        }
    """
    prof = get_profile(profile)
    report = ValidationReport(
        subject=f'DCMA 14-Point Assessment [{profile}]',
        context={'profile': profile, 'profile_name': prof.get('name', profile)},
    )

    # ── Extract tables ──
    tasks_all = get_table(data, 'TASK')
    preds_all = get_table(data, 'TASKPRED')
    projects = get_table(data, 'PROJECT')
    rsrc_assignments = get_table(data, 'TASKRSRC')
    cal_map = get_calendar_map(data)

    # ── Pick target project (first with tasks, mirroring cp_validator logic) ──
    if projects and len(projects) > 1:
        proj_counts = {}
        for t in tasks_all:
            proj_counts[t.get('proj_id', '')] = proj_counts.get(t.get('proj_id', ''), 0) + 1
        target_pid = max(proj_counts, key=proj_counts.get) if proj_counts else projects[0].get('proj_id', '')
    else:
        target_pid = projects[0].get('proj_id', '') if projects else ''

    if target_pid:
        tasks = [t for t in tasks_all if t.get('proj_id', '') == target_pid]
    else:
        tasks = tasks_all
    project = next((p for p in projects if p.get('proj_id', '') == target_pid), (projects[0] if projects else {}))

    task_map = {t['task_id']: t for t in tasks}
    pred_map = {}
    succ_map = {}
    preds_for_project = [p for p in preds_all if p.get('task_id', '') in task_map or p.get('pred_task_id', '') in task_map]
    for p in preds_for_project:
        pred_map.setdefault(p.get('task_id', ''), []).append(p)
        succ_map.setdefault(p.get('pred_task_id', ''), []).append(p)

    work_tasks = [t for t in tasks if _is_work_task(t)]
    incomplete = [t for t in work_tasks if t.get('status_code', '') != COMPLETE_STATUS]
    cp_tasks = [
        t for t in incomplete
        if _safe_float(t.get('total_float_hr_cnt', ''), 999) <= 0
    ]

    data_date_dt = _parse_date(project.get('last_recalc_date', ''))

    # ── Run each check ──
    per_check = {}
    check_results = []

    sev, val, thr, msg, det = _check_01_logic(work_tasks, pred_map, succ_map, prof)
    check_results.append(('DCMA-01-Logic', 'Logic', 'DCMA 14-Point #1', sev, val, thr, msg, det))

    sev, val, thr, msg, det = _check_02_leads(preds_for_project, prof)
    check_results.append(('DCMA-02-Leads', 'Leads', 'DCMA 14-Point #2', sev, val, thr, msg, det))

    sev, val, thr, msg, det = _check_03_lags(preds_for_project, prof)
    check_results.append(('DCMA-03-Lags', 'Lags', 'DCMA 14-Point #3', sev, val, thr, msg, det))

    sev, val, thr, msg, det = _check_04_relationship_types(preds_for_project, prof)
    check_results.append(('DCMA-04-Relationship', 'Relationship Types', 'DCMA 14-Point #4', sev, val, thr, msg, det))

    sev, val, thr, msg, det = _check_05_hard_constraints(work_tasks, prof)
    check_results.append(('DCMA-05-Hard', 'Hard Constraints', 'DCMA 14-Point #5', sev, val, thr, msg, det))

    sev, val, thr, msg, det = _check_06_high_float(incomplete, cal_map, prof)
    check_results.append(('DCMA-06-HighFloat', 'High Float', 'DCMA 14-Point #6', sev, val, thr, msg, det))

    sev, val, thr, msg, det = _check_07_negative_float(incomplete, cal_map, prof)
    check_results.append(('DCMA-07-NegFloat', 'Negative Float', 'DCMA 14-Point #7', sev, val, thr, msg, det))

    sev, val, thr, msg, det = _check_08_high_duration(incomplete, cal_map, prof)
    check_results.append(('DCMA-08-HighDuration', 'High Duration', 'DCMA 14-Point #8', sev, val, thr, msg, det))

    sev, val, thr, msg, det = _check_09_invalid_dates(work_tasks, data_date_dt, prof)
    check_results.append(('DCMA-09-InvalidDates', 'Invalid Dates', 'DCMA 14-Point #9', sev, val, thr, msg, det))
    # #11 is merged into #9 per DCMA interpretation — echo the same result.
    check_results.append(('DCMA-11-InvalidDatesFuture', 'Future Actuals (merged #11)',
                          'DCMA 14-Point #11 (merged into #9)', sev, val, thr,
                          'Future-actual dates covered by DCMA #9 in this implementation.',
                          det))

    sev, val, thr, msg, det = _check_10_resources(work_tasks, rsrc_assignments, prof)
    check_results.append(('DCMA-10-Resources', 'Resources', 'DCMA 14-Point #10', sev, val, thr, msg, det))
    # #12 is the resource-coverage aspect — echo #10 outcome.
    check_results.append(('DCMA-12-ResourceCoverage', 'Resource Coverage (merged #12)',
                          'DCMA 14-Point #12 (same as #10)', sev, val, thr,
                          'Resource coverage aspect covered by DCMA #10 in this implementation.',
                          det))

    sev, val, thr, msg, det = _check_13_missed_tasks(work_tasks, data_date_dt, prof)
    check_results.append(('DCMA-13-MissedTasks', 'Missed Tasks', 'DCMA 14-Point #13', sev, val, thr, msg, det))

    sev, val, thr, msg, det = _check_14_cpli(cp_tasks, cal_map, data_date_dt, prof, project)
    cpli_value = det.get('cpli')
    check_results.append(('DCMA-14-CPLI', 'Critical Path Length Index', 'DCMA 14-Point #14', sev, val, thr, msg, det))

    # ── Fold into the report and compute the /14 score ──
    passed_count = 0
    for check_id, name, ref, sev, val, thr, msg, det in check_results:
        per_check[check_id] = {
            'severity': sev,
            'value': val,
            'threshold': thr,
            'message': msg,
            'details': det,
        }
        report.add(Finding(
            severity=sev, check_id=check_id,
            message=msg, reference=ref,
            evidence={
                'value': val, 'threshold': thr, **det
            },
        ))
        if sev == PASS:
            passed_count += 1
    # Score is out of 14 — each check contributes 1 if PASS, 0 otherwise.
    # Since we have 14 check_results entries (the registry has 14), this lines up.
    dcma_score = passed_count

    # ── BEI (extra) ──
    sev, val, thr, msg, det = _compute_bei(data, baseline_data, data_date_dt, prof)
    bei_value = det.get('bei')
    per_check['BEI'] = {
        'severity': sev, 'value': val, 'threshold': thr, 'message': msg, 'details': det,
    }
    report.add(Finding(
        severity=sev, check_id='BEI',
        message=msg, reference='NDIA PASEG §10 / DCMA extension',
        evidence={'value': val, 'threshold': thr, **det},
    ))

    # ── Multiple critical paths ──
    crit_paths = _identify_critical_paths(cp_tasks, pred_map, task_map)
    multiple_cp = len(crit_paths) > 1
    if multiple_cp:
        report.add(Finding(
            severity=INFO, check_id='DCMA-Ext-MultipleCP',
            message=f'{len(crit_paths)} distinct critical paths identified.',
            reference='AACE 49R-06 §4',
            evidence={'path_count': len(crit_paths), 'paths': crit_paths},
        ))

    # ── CP continuity ──
    continuity = _cp_continuity(cp_tasks, pred_map, task_map)
    if continuity['gaps']:
        report.add(Finding(
            severity=WARN, check_id='DCMA-Ext-CPContinuity',
            message=f'Critical path has {len(continuity["gaps"])} continuity gap(s).',
            reference='AACE 49R-06 §4.3',
            # Full list — never truncate. CPP forensic-correctness rule: every
            evidence={'gaps': list(continuity['gaps'])},
        ))
    else:
        report.add(Finding(
            severity=PASS, check_id='DCMA-Ext-CPContinuity',
            message='Critical path is continuous (no gaps detected).',
            reference='AACE 49R-06 §4.3',
        ))

    return {
        'profile': profile,
        'profile_name': prof.get('name', profile),
        'report': report,
        'dcma_score': dcma_score,
        'cpli': cpli_value,
        'bei': bei_value,
        'critical_paths': crit_paths,
        'multiple_critical_paths': multiple_cp,
        'cp_continuity': continuity,
        'per_check': per_check,
    }


# ─────────────────────────────────────────────────────────────────────
# Dashboard rendering helper — called from cp_validator.generate_dashboard
# ─────────────────────────────────────────────────────────────────────

def render_dcma_scorecard_html(assessment):
    """Render the DCMA 14 scorecard as an HTML fragment suitable for embedding."""
    if not assessment:
        return ''
    score = assessment.get('dcma_score', 0)
    cpli = assessment.get('cpli')
    bei = assessment.get('bei')
    profile_name = assessment.get('profile_name', assessment.get('profile', 'commercial'))
    per_check = assessment.get('per_check', {})

    def _sev_color(sev):
        return {'PASS': '#22c55e', 'INFO': '#3b82f6', 'WARN': '#f59e0b', 'BLOCK': '#ef4444'}.get(sev, '#6b7280')

    def _esc(s):
        return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    # CPP forensic-correctness rule: never truncate findings without disclosure. Render every
    # check in the per_check dict, not just the canonical 14.
    rows = []
    for cid in sorted(per_check.keys()):
        c = per_check[cid]
        sev = c.get('severity', 'INFO')
        val = c.get('value')
        thr = c.get('threshold')
        msg = c.get('message', '')
        val_str = f'{val:.2f}' if isinstance(val, float) else (str(val) if val is not None else '—')
        thr_str = f'{thr:.2f}' if isinstance(thr, float) else (str(thr) if thr is not None else '—')
        rows.append(
            f'<tr>'
            f'<td style="font-family:monospace; font-size:0.75rem;">{_esc(cid)}</td>'
            f'<td><span style="color:{_sev_color(sev)}; font-weight:700;">{_esc(sev)}</span></td>'
            f'<td style="text-align:right;">{_esc(val_str)}</td>'
            f'<td style="text-align:right; color:#64748b;">{_esc(thr_str)}</td>'
            f'<td>{_esc(msg)}</td>'
            f'</tr>'
        )

    score_color = '#22c55e' if score >= 13 else ('#f59e0b' if score >= 10 else '#ef4444')
    cpli_str = f'{cpli:.3f}' if isinstance(cpli, (int, float)) else '—'
    bei_str = f'{bei:.3f}' if isinstance(bei, (int, float)) else '—'
    paths = assessment.get('critical_paths', [])
    multi = assessment.get('multiple_critical_paths', False)

    html = f'''
    <div class="dcma-scorecard" style="margin:24px 0; padding:16px; background:#0f172a; border-radius:8px; border-left:4px solid {score_color};">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
            <div>
                <div style="font-size:1.1rem; font-weight:700; color:#f1f5f9;">DCMA 14-Point Scorecard</div>
                <div style="font-size:0.8rem; color:#94a3b8;">Profile: {_esc(profile_name)}</div>
            </div>
            <div style="text-align:right;">
                <div style="font-size:2rem; font-weight:700; color:{score_color};">{score}/14</div>
                <div style="font-size:0.75rem; color:#94a3b8;">Checks passed</div>
            </div>
        </div>
        <div style="display:flex; gap:24px; margin-bottom:12px; flex-wrap:wrap;">
            <div><span style="color:#94a3b8; font-size:0.75rem;">CPLI:</span> <span style="font-weight:700; color:#f1f5f9;">{cpli_str}</span></div>
            <div><span style="color:#94a3b8; font-size:0.75rem;">BEI:</span> <span style="font-weight:700; color:#f1f5f9;">{bei_str}</span></div>
            <div><span style="color:#94a3b8; font-size:0.75rem;">Critical Paths:</span> <span style="font-weight:700; color:#f1f5f9;">{len(paths)}{' (multiple)' if multi else ''}</span></div>
        </div>
        <table style="width:100%; border-collapse:collapse; font-size:0.8rem;">
            <thead><tr style="background:#1e293b; color:#94a3b8;">
                <th style="padding:6px 10px; text-align:left;">Check</th>
                <th style="padding:6px 10px; text-align:left;">Severity</th>
                <th style="padding:6px 10px; text-align:right;">Value</th>
                <th style="padding:6px 10px; text-align:right;">Threshold</th>
                <th style="padding:6px 10px; text-align:left;">Message</th>
            </tr></thead>
            <tbody style="color:#cbd5e1;">
                {''.join(rows)}
            </tbody>
        </table>
    </div>
    '''
    return html
