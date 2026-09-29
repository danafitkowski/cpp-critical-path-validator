#!/usr/bin/env python3
"""DCMA 14-Point Schedule Assessment.

Implements the Defense Contract Management Agency 14-Point assessment plus
the BEI (Baseline Execution Index) metric and the "multiple critical paths /
CP continuity / driving-path tracer" extras called out by the VP teardown
review.

The DCMA 14 checks, as implemented here:

    1. Logic          — % incomplete activities missing predecessor or successor
    2. Leads          — count of negative lag_hr_cnt relationships
    3. Lags           — % of relationships with positive lag
    4. Relationship   — % Finish-to-Start (FS) relationships
    5. Hard           — % activities with hard constraint (MANDSTART/FIN, MSO, MEO)
    6. High Float     — % activities with total float > threshold (44d commercial)
    7. Negative Float — count of activities with TF < 0
    8. High Duration  — % activities with remaining duration > threshold
    9. Invalid Dates  — count of activities with a forecast (early) date before
                        the status date or an actual date after it
   10. Resources      — % activities with TASKRSRC assignments
   11. Missed Tasks   — % activities due by the status date that did not finish
                        by their due date (still open OR finished late)
   12. Critical Path Test — the 600-day perturbation test
   13. CPLI           — (CP length + total_float) / CP length ≥ 0.95 / 0.98
   14. BEI            — tasks completed as of the status date / tasks with a
                        baseline finish on or before the status date. Requires a
                        baseline XER. The numerator is UNRESTRICTED, which is
                        why BEI can legitimately exceed 1.0.

This is the PUBLISHED DCMA numbering (#11 Missed Tasks, #12 Critical Path Test,
#13 CPLI, #14 BEI). It was previously renumbered here: #11 and #12 were
cross-reference echoes of #9 and #10 that repeated their verdicts, so a passing
#9 or #10 scored twice and a failing one was reported twice, the Critical Path
Test was absent, and Missed Tasks/CPLI/BEI sat one or two slots off the
standard.

Extras (beyond the 14):

   • Multiple CPs     — distinct critical chains (by crt_path_num or
                        by connected-component grouping).
   • CP Continuity    — detect gaps (non-critical predecessor → critical
                        successor) in the critical chain.
   • Driving-path     — walk the predecessor chain of driving activities
                        back to the data date from a given task_code.

Public API:
    dcma_14_assess(data, profile='commercial', baseline_data=None,
                   proj_id=None) -> dict

Standards:
    DCMA 14-Point Assessment (DCMA Defense Contract Management Agency 14-Point Schedule Assessment Procedure; DCMA-EA PAM 200.1)
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
    CONSTRAINT_TYPES,
    COMPLETE_STATUS,
    ACTIVE_STATUS,
    NOT_STARTED_STATUS,
    EXCLUDED_TASK_TYPES,
    MILESTONE_TASK_TYPES,
)

# Reuse the hard-constraint taxonomy from cp_validator — single source of truth.
from cp_validator import (  # noqa: E402
    HARD_ABSOLUTE, HARD_CONSTRAINTS, HARD_DATE, _hrs_to_days, _safe_float)

# The bundled parser, cpp-xer-parser at the commit CI pins, carries neither the
# signed working-day advance that #13 CPLI measures the critical path with nor
# the blank-calendar resolution of the assessment. Each is taken from the
# parser when it has it, and tests/test_dcma14_guards.py holds the parser's
# to the same reading; until then the definitions below stand in.
try:
    from xer_parser import work_day_delta  # noqa: E402
except ImportError:
    def _is_work_day(dt, work_days, holidays, special_workdays):
        """True if dt is a working day on the calendar: an explicit holiday
        wins (the day is off), then an explicit worked exception (the day is
        on), otherwise the weekly pattern decides."""
        day = dt.strftime('%Y-%m-%d')
        if day in holidays:
            return False
        if day in special_workdays:
            return True
        # Python Mon=0..Sun=6 -> P6 Sun=0..Sat=6
        return (dt.weekday() + 1) % 7 in work_days

    def work_day_delta(d1, d2, calendar_info=None):
        """Signed working-day advance from d1 to d2 on the given calendar: the
        working days in the half-open interval (earlier, later], 0 on the same
        calendar day, positive when d2 is later, negative when it is earlier.
        A Friday-to-Monday move on a five-day week is 1 whatever the clock
        times, since dates are read on their calendar day. A holiday is off, a
        worked exception (special_workdays) is on, and otherwise the weekly
        pattern decides. Returns None if either date is missing or
        unparseable, or if the span is beyond about a hundred years, a
        sentinel finish rather than a schedule window. calendar_info defaults
        to Monday to Friday with no exceptions.
        """
        if not d1 or not d2:
            return None

        def _coerce(d):
            if isinstance(d, str):
                try:
                    d = datetime.strptime(d[:10], '%Y-%m-%d')
                except (ValueError, TypeError):
                    return None
            if not isinstance(d, datetime):
                return datetime(d.year, d.month, d.day)
            return d.replace(hour=0, minute=0, second=0, microsecond=0)

        a, b = _coerce(d1), _coerce(d2)
        if a is None or b is None:
            return None
        if a == b:
            return 0
        earlier, later, sign = (a, b, 1) if b > a else (b, a, -1)
        if (later - earlier).days > 366 * 100:
            return None
        cal = calendar_info or {}
        work_days = cal.get('work_days') or [1, 2, 3, 4, 5]
        holidays = set(cal.get('holidays') or [])
        special = set(cal.get('special_workdays') or [])
        count = 0
        current = earlier + timedelta(days=1)   # (earlier, later]
        while current <= later:
            if _is_work_day(current, work_days, holidays, special):
                count += 1
            current += timedelta(days=1)
        return sign * count

try:
    from xer_parser import (  # noqa: E402
        resolve_task_calendars, with_resolved_calendars, calendar_resolution_block)
except ImportError:
    _NO_RESOLUTION = ('the bundled parser does not resolve a blank task calendar '
                      'onto the project calendar; an activity with no calendar '
                      'of its own is read at 8 h/day in checks #6, #8 and #13')

    def resolve_task_calendars(data):
        """No resolution: the bundled parser cannot place a blank clndr_id."""
        return {}

    def with_resolved_calendars(tasks, task_cals):
        """The tasks as parsed; nothing was resolved."""
        return tasks

    def calendar_resolution_block(task_cals, keep=None):
        """An empty block that says why it is empty."""
        return {'resolved_by_fallback_count': 0, 'fallback_calendars': [],
                'unresolved_count': 0, 'unresolved': [],
                'note': _NO_RESOLUTION}


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


def _float_hours(t):
    """TASK.total_float_hr_cnt as hours, or None when P6 wrote no value.

    A blank total_float is MISSING DATA, not a number. Exports carry a blank
    total_float_hr_cnt on incomplete work, and on some it is blank on every
    incomplete activity. Coercing the blank invents an answer, and the two
    obvious coercions fail in opposite directions: 999 empties the critical
    set and makes CPLI silently not-computable, while 0 makes every incomplete
    activity critical and hands High Float and Negative Float a silent PASS on
    a file carrying no float at all. Returning None lets each caller drop the
    activity from its population and DISCLOSE the count instead of scoring
    it.
    """
    raw = t.get('total_float_hr_cnt', '')
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _task_start(t):
    """Best available start instant: actual, else early, else planned."""
    return (_parse_date(t.get('act_start_date', ''))
            or _parse_date(t.get('early_start_date', ''))
            or _parse_date(t.get('target_start_date', '')))


def _task_finish(t):
    """Best available finish instant: actual, else early, else planned."""
    return (_parse_date(t.get('act_end_date', ''))
            or _parse_date(t.get('early_end_date', ''))
            or _parse_date(t.get('target_end_date', '')))


def _project_finish_task(work_tasks, finish_fn):
    """(activity, instant) that defines project completion — the latest finish,
    with a finish milestone preferred on a tie.

    P6 schedules routinely land the last working activity and the completion
    milestone on the same instant, and several activities can share the finish
    instant on one export. The milestone is the
    activity that carries the project's float and the completion constraint, so
    it is the one the finish-side criteria must read.
    """
    best, best_dt = None, None
    for t in work_tasks:
        d = finish_fn(t)
        if d is None:
            continue
        if best_dt is None or d > best_dt:
            best, best_dt = t, d
        elif (d == best_dt and t.get('task_type', '') == 'TT_FinMile'
              and best.get('task_type', '') != 'TT_FinMile'):
            best = t
    return best, best_dt


# ─────────────────────────────────────────────────────────────────────
# Per-check implementations
# Each returns (severity, value, threshold, message, details_dict)
# ─────────────────────────────────────────────────────────────────────

def _check_01_logic(work_tasks, incomplete, pred_map, succ_map, profile):
    """#1 Logic — % of INCOMPLETE activities missing a predecessor or successor.

    Two corrections against the previous implementation:

    • Population. The DCMA metric family is scoped to incomplete work; this
      check used to run over every work task, completed ones included. On an
      update well into a job that put the completed work in the denominator
      beside the remaining work, diluting the percentage with historic work
      whose logic no longer drives anything.

    • Milestone exemption by POSITION, not by task_type. A start milestone may
      legitimately have no predecessor only where it IS the start of the
      network; a finish milestone may legitimately have no successor only where
      it IS the end. Exempting every TT_Mile / TT_FinMile by type exempted
      milestones in the middle of the network that lead from nothing or to
      nothing — the dangling starts and ends this test exists to find. Every
      TT_FinMile was also exempted from the predecessor test, so one tied to
      nothing at all was never counted; it now needs a predecessor like any
      other activity.

    Both the missing-predecessor and the missing-successor rates are reported
    separately in the details; the graded value stays the union rate, which is
    the quantity the published ≤5% is stated against.
    """
    threshold = profile['dcma_logic_max_missing_pct']
    if not incomplete:
        # The same keys as a scored run, so a caller reading the details never
        # has to ask which branch produced them.
        return PASS, 0.0, threshold, 'No incomplete work tasks (vacuous pass).', {
            'missing_count': 0, 'denominator': 0,
            'missing_pred_count': 0, 'missing_pred_pct': 0.0,
            'missing_succ_count': 0, 'missing_succ_pct': 0.0,
            'missing_pred': [], 'missing_succ': [],
            'examples': [],
        }
    # The network starts where the first activity started, completed work
    # included, not where the remaining work starts. It finishes where the
    # remaining work finishes: on a schedule rescheduled to its data date no
    # completed activity finishes later, and on an update statused past its
    # data date a late actual finish is #9's finding, not a reason to count
    # the completion milestone as a dangling end.
    starts = [d for d in (_task_start(t) for t in work_tasks) if d]
    finishes = [d for d in (_task_finish(t) for t in incomplete) if d]
    net_start = min(starts) if starts else None
    net_finish = max(finishes) if finishes else None

    missing_pred, missing_succ = [], []
    for t in incomplete:
        tid = t['task_id']
        ttype = t.get('task_type', '')
        code = t.get('task_code', tid)
        has_pred = tid in pred_map
        has_succ = tid in succ_map
        ts, tf = _task_start(t), _task_finish(t)
        pred_exempt = (ttype == 'TT_Mile' and net_start is not None
                       and ts is not None and ts <= net_start)
        succ_exempt = (ttype == 'TT_FinMile' and net_finish is not None
                       and tf is not None and tf >= net_finish)
        if not has_pred and not pred_exempt:
            missing_pred.append(code)
        if not has_succ and not succ_exempt:
            missing_succ.append(code)
    missing = sorted(set(missing_pred) | set(missing_succ))
    denom = len(incomplete)
    pct = len(missing) / denom * 100.0
    pct_pred = len(missing_pred) / denom * 100.0
    pct_succ = len(missing_succ) / denom * 100.0
    sev = PASS if pct <= threshold else WARN
    return sev, pct, threshold, (
        f'{len(missing)} of {denom} incomplete activities ({pct:.1f}%) missing '
        f'predecessor or successor — {len(missing_pred)} missing a predecessor '
        f'({pct_pred:.1f}%), {len(missing_succ)} missing a successor '
        f'({pct_succ:.1f}%) (threshold ≤ {threshold}%).'
    # Full lists — never truncate. CPP forensic-correctness rule: every
    # activity is listed.
    ), {'missing_count': len(missing), 'denominator': denom,
        'missing_pred_count': len(missing_pred), 'missing_pred_pct': pct_pred,
        'missing_succ_count': len(missing_succ), 'missing_succ_pct': pct_succ,
        'missing_pred': list(missing_pred), 'missing_succ': list(missing_succ),
        'examples': list(missing)}


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
    # Activities P6 left with a blank total_float carry no answer to grade. They
    # are dropped from the population and disclosed, never coerced to 0.
    known = [t for t in incomplete if _float_hours(t) is not None]
    unknown = len(incomplete) - len(known)
    if not known:
        return INFO, None, threshold, (
            f'No computed total float on any of the {len(incomplete)} incomplete '
            f'activities — High Float NOT ASSESSED. Recalculate the schedule in '
            f'P6 and re-export; do not read this as a pass.'
        ), {'high_float_count': None, 'max_days': max_days,
            'unknown_float_count': unknown, 'assessed': False}
    high = []
    for t in known:
        tf_days = _hrs_to_days(_float_hours(t), cal_map, t.get('clndr_id', ''))
        if tf_days > max_days:
            high.append(t.get('task_code', t['task_id']))
    pct = len(high) / len(known) * 100.0
    sev = PASS if pct <= threshold else WARN
    note = (f' {unknown} incomplete activities have no computed total float and '
            f'are excluded from the population.') if unknown else ''
    return sev, pct, threshold, (
        f'{len(high)} of {len(known)} incomplete activities with computed float '
        f'({pct:.1f}%) have total float > {max_days}d (threshold ≤ {threshold}%).'
        + note
    ), {'high_float_count': len(high), 'max_days': max_days,
        'unknown_float_count': unknown, 'assessed': True,
        'examples': list(high)}


def _check_07_negative_float(incomplete, cal_map, profile):
    """#7 Negative Float — count of activities with TF < 0.

    Blank total_float is missing data, not zero: an activity with no computed
    float cannot be shown to be negative, so it is excluded and disclosed
    rather than counted as float-zero.
    """
    threshold = profile['dcma_negative_float_max_count']
    known = [t for t in incomplete if _float_hours(t) is not None]
    unknown = len(incomplete) - len(known)
    if incomplete and not known:
        return INFO, None, threshold, (
            f'No computed total float on any of the {len(incomplete)} incomplete '
            f'activities — Negative Float NOT ASSESSED. Recalculate the schedule '
            f'in P6 and re-export; do not read this as a pass.'
        ), {'neg_float_count': None, 'unknown_float_count': unknown,
            'assessed': False, 'examples': []}
    neg = [t.get('task_code', t['task_id']) for t in known if _float_hours(t) < 0]
    sev = PASS if len(neg) <= threshold else BLOCK
    note = (f' {unknown} incomplete activities have no computed total float and '
            f'are excluded from the population.') if unknown else ''
    return sev, len(neg), threshold, (
        f'{len(neg)} activities with negative total float (threshold ≤ {threshold}). '
        'Any negative float means the schedule cannot finish on time as currently logicked.'
        + note
    # Full list — never truncate. CPP forensic-correctness rule.
    ), {'neg_float_count': len(neg), 'unknown_float_count': unknown,
        'assessed': True, 'examples': list(neg)}


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


def _check_09_invalid_dates(work_tasks, data_date_dt, profile, correction=None):
    """#9 Invalid Dates — activities with a forecast date before the status
    date, or an actual date after it (DCMA-EA PAM 200.1 section 4.9).

    The forecast dates are the EARLY dates (section 4.11 names the forecast
    finish as the early finish), and only what has not happened yet is a
    forecast: a not-started activity is read on its early start and early
    finish, a started one on its early finish alone, a completed one on
    neither. Actual dates are read on every activity that carries them. A date
    ON the status date is valid on both sides (the pamphlet's "on or after" for
    a forecast, "on or before" for an actual).

    Two corrections against the previous implementation:

    • It never read an early date. It tested the PLANNED finish
      (target_end_date), which is what #11 Missed Tasks measures, so open
      activities were flagged on a historical planned finish while
      not-started activities with an early start before the data date, and
      in-progress ones with an early finish before it, were never looked at.
      The early start of started work is deliberately not read: it sits at
      the actual start, so on in-progress work it is routinely before the
      data date.

    • It counted one issue per FIELD and called the total a number of
      activities, so one activity with a future actual start and a future
      actual finish read "2 activities". Issues are grouped by activity before
      counting; the per-field list is kept in the details.

    An incomplete activity with no early date to read cannot be shown to be
    valid or invalid. It is not counted and the message says how many there
    were; the verdict rests on the dates that could be read.

    `correction` is the data date correction record for the project assessed
    (data_date_correction.detect; that module is not part of this repository,
    so it is None here), or None. This check
    reports the file as filed, so the verdict and the count never change. The
    record only adds a sentence to the finding (the latest actual, the
    activities forecast to start before it, the corrected data date, and any
    actual dated after the file's export) and, when a move is owed, the latest
    actual and the corrected date to the details.
    """
    threshold = profile['dcma_invalid_dates_max_count']
    if data_date_dt is None:
        return INFO, 0, threshold, (
            'No data date on project — cannot evaluate invalid dates.'
        ), {'issues': []}
    dd = data_date_dt.date()
    issues = []
    invalid, forecast_bad, actual_bad, unread = [], [], [], []
    for t in work_tasks:
        tc = t.get('task_code', t['task_id'])
        status = t.get('status_code', '')
        act_start = _parse_date(t.get('act_start_date', ''))
        act_end = _parse_date(t.get('act_end_date', ''))
        # Actual dates: never after the status date.
        late_actuals = [f'{tc}:{field}>{dd}'
                        for field, v in (('act_start_date', act_start),
                                         ('act_end_date', act_end))
                        if v and v > data_date_dt]
        # Forecast dates: never before it, and only an end of the activity
        # that has not happened yet is a forecast.
        started = act_start is not None or status in (ACTIVE_STATUS, COMPLETE_STATUS)
        finished = act_end is not None or status == COMPLETE_STATUS
        stale_forecasts, no_forecast = [], False
        for field, happened in (('early_start_date', started),
                                ('early_end_date', finished)):
            if happened:
                continue
            v = _parse_date(t.get(field, ''))
            if v is None:
                # No forecast to read is missing data, not a valid date.
                no_forecast = True
            elif v < data_date_dt:
                stale_forecasts.append(f'{tc}:{field}<{dd}')
        if no_forecast:
            unread.append(tc)
        if late_actuals:
            actual_bad.append(tc)
        if stale_forecasts:
            forecast_bad.append(tc)
        if late_actuals or stale_forecasts:
            invalid.append(tc)
            issues.extend(late_actuals + stale_forecasts)
    both = len(set(forecast_bad) & set(actual_bad))
    sev = PASS if len(invalid) <= threshold else BLOCK
    message = (
        f'{len(invalid)} activities with invalid dates (threshold ≤ {threshold}): '
        f'{len(forecast_bad)} with a forecast (early) start or finish before the '
        f'status date {dd}, {len(actual_bad)} with an actual start or finish '
        f'after it.'
        + (f' {both} of them carry both and are counted once.' if both else '')
        + (f' {len(unread)} incomplete activities carry no early start or '
           f'finish to read, so their forecast dates were not assessed.'
           if unread else '')
        + ' A missed planned or baseline finish is not an invalid date; it is '
          'counted under #11 Missed Tasks.')
    # Full lists — never truncate. CPP forensic-correctness rule.
    details = {'invalid_count': len(invalid), 'forecast_count': len(forecast_bad),
               'actual_count': len(actual_bad), 'issue_count': len(issues),
               'unread_forecast_count': len(unread),
               'examples': list(invalid), 'issues': list(issues),
               'unread_forecast': list(unread)}
    if correction:
        from data_date_correction import checker_sentence
        sentence = checker_sentence(correction)
        if sentence:
            message = message + ' ' + sentence
        if correction.get('needs_move'):
            details['latest_actual'] = correction['set_by']['date']
            details['latest_actual_activity'] = correction['set_by']['task_code']
            details['corrected_data_date'] = correction['corrected_data_date']
            details['pushed_count'] = correction['pushed_count']
    return sev, len(invalid), threshold, message, details


def _check_10_resources(work_tasks, rsrc_assignments, profile):
    """#10 Resources — % of activities with TASKRSRC assignments.

    When the profile disables the threshold (commercial default: 0), the check
    is NOT SCORED. It used to return PASS, which awarded a point on every
    commercial schedule without measuring anything and inflated the score by
    one. Anything unscorable says "Not scored" with the reason, never a fake
    pass. INFO is excluded from both dcma_score and dcma_max, so a disabled
    criterion now moves neither.
    """
    threshold = profile['dcma_resources_min_pct']
    if not work_tasks:
        return INFO, 0.0, threshold, (
            'Not scored: the schedule carries no work activities to measure.'
        ), {}
    assigned_ids = {r.get('task_id', '') for r in rsrc_assignments}
    hits = sum(1 for t in work_tasks if t['task_id'] in assigned_ids)
    pct = hits / len(work_tasks) * 100.0
    if threshold <= 0:
        return INFO, pct, threshold, (
            f'Not scored: resource loading is not required by this profile '
            f'(threshold ≥ {threshold}%). Measured anyway for information: '
            f'{hits} of {len(work_tasks)} activities ({pct:.1f}%) carry a '
            f'resource assignment.'
        ), {'loaded_count': hits, 'disabled': True}
    sev = PASS if pct >= threshold else WARN
    return sev, pct, threshold, (
        f'{hits} of {len(work_tasks)} activities ({pct:.1f}%) have resource '
        f'assignments (threshold ≥ {threshold}%).'
    ), {'loaded_count': hits}


def _baseline_project_tasks(baseline_data, project, work_tasks):
    """The baseline work tasks that belong to the assessed project, the
    baseline project they came from, and how that project was matched.

    A baseline file can hold several projects, exactly as a current one can.
    The PROJECT is matched first and activity codes second: same proj_id (an
    earlier export of the same project), else same proj_short_name, else the
    baseline project sharing the most activity codes with the assessed one.
    Checks 11 and 14 used to read EVERY baseline TASK row, so an unrelated
    project's rows joined the BEI denominator and a reused activity code moved
    a Missed Tasks due date.

    A baseline file with one project is read whole, as it always was. Where
    no baseline project shares a single activity code, nothing is read: a
    figure built on an unrelated project's rows is worse than none.

    Returns (tasks, baseline_proj_id, how); (None, '', '') with no baseline.
    """
    if baseline_data is None:
        return None, '', ''
    rows = [t for t in get_table(baseline_data, 'TASK') if _is_work_task(t)]
    projects = get_table(baseline_data, 'PROJECT')
    if len(projects) <= 1:
        return (rows, projects[0].get('proj_id', '') if projects else '',
                'only project in the baseline file')
    pid = (project or {}).get('proj_id', '')
    short = (project or {}).get('proj_short_name', '')
    same_short = [p.get('proj_id', '') for p in projects
                  if short and p.get('proj_short_name', '') == short]
    if pid and any(p.get('proj_id', '') == pid for p in projects):
        chosen, how = pid, 'same proj_id'
    elif same_short:
        chosen, how = same_short[0], 'same short name'
    else:
        codes = {t.get('task_code', '') for t in work_tasks}
        shared = {}
        for t in rows:
            if t.get('task_code', '') in codes:
                shared[t.get('proj_id', '')] = shared.get(t.get('proj_id', ''), 0) + 1
        if not shared:
            return [], '', ('no baseline project shares an activity code with '
                            'the assessed project')
        # ties go to the project listed first in the file
        chosen = max((p.get('proj_id', '') for p in projects),
                     key=lambda p: shared.get(p, 0))
        how = 'most shared activity codes'
    return [t for t in rows if t.get('proj_id', '') == chosen], chosen, how


def _check_11_missed_tasks(work_tasks, baseline_tasks, data_date_dt, profile):
    """#11 Missed Tasks — activities due by the status date that did not finish
    by their due date.

    A task is missed if it was due by the status date and EITHER it is still
    open OR it finished after its due date. The previous implementation counted
    only the still-open ones, so a late completion was invisible, and an
    update on which most of the due activities had finished late could read
    as a PASS. This is the metric that is supposed to show execution
    slipping.

    Due dates come from the BASELINE when a baseline is supplied (matched on
    task_code — task_id is renumbered on every P6 export). Without a baseline
    the current schedule's own Planned Finish is used and the basis is
    disclosed in the message.

    `baseline_tasks` is the MATCHING baseline project's work tasks (see
    _baseline_project_tasks), or None when no baseline was supplied.
    """
    threshold = profile['dcma_missed_tasks_max_pct']
    if data_date_dt is None or not work_tasks:
        return INFO, None, threshold, (
            'No data date or no work tasks — Missed Tasks NOT ASSESSED.'
        ), {'missed_count': None, 'assessed': False}

    if baseline_tasks is not None:
        basis = 'baseline finish'
        due_dates = {}
        for bt in baseline_tasks:
            te = _parse_date(bt.get('target_end_date', ''))
            if te:
                due_dates[bt.get('task_code', bt.get('task_id', ''))] = te
        due_for = lambda t: due_dates.get(t.get('task_code', t.get('task_id', '')))  # noqa: E731
    else:
        basis = "the current schedule's Planned Finish (no baseline supplied)"
        due_for = lambda t: _parse_date(t.get('target_end_date', ''))  # noqa: E731

    due_by_dd = []
    for t in work_tasks:
        due = due_for(t)
        if due and due <= data_date_dt:
            due_by_dd.append((t, due))
    if not due_by_dd:
        return PASS, 0.0, threshold, (
            f'No activities due to complete by the status date on {basis} '
            f'(vacuous pass).'
        ), {'missed_count': 0, 'due_by_dd': 0, 'assessed': True, 'basis': basis}

    still_open, late_finish, undetermined = [], [], []
    for t, due in due_by_dd:
        code = t.get('task_code', t['task_id'])
        if t.get('status_code', '') != COMPLETE_STATUS:
            still_open.append(code)
            continue
        act_end = _parse_date(t.get('act_end_date', ''))
        if act_end is None:
            # Complete but no actual finish recorded — lateness cannot be
            # established from the file. Disclosed, not silently counted.
            undetermined.append(code)
        elif act_end > due:
            late_finish.append(code)
    missed = sorted(set(still_open) | set(late_finish))
    pct = len(missed) / len(due_by_dd) * 100.0
    sev = PASS if pct <= threshold else WARN
    tail = (f' {len(undetermined)} complete activities carry no actual finish '
            f'date, so lateness could not be established for them.'
            ) if undetermined else ''
    return sev, pct, threshold, (
        f'{len(missed)} of {len(due_by_dd)} activities due by the status date on '
        f'{basis} ({pct:.1f}%) did not finish by their due date — '
        f'{len(still_open)} still open, {len(late_finish)} finished late '
        f'(threshold ≤ {threshold}%).' + tail
    # Full lists — never truncate. CPP forensic-correctness rule.
    ), {'missed_count': len(missed), 'due_by_dd': len(due_by_dd),
        'still_open_count': len(still_open), 'late_finish_count': len(late_finish),
        'undetermined_count': len(undetermined), 'assessed': True, 'basis': basis,
        'still_open': list(still_open), 'late_finish': list(late_finish),
        'undetermined': list(undetermined)}


def _check_12_critical_path_test(work_tasks, pred_map, profile):
    """#12 Critical Path Test — the 600-day perturbation test.

    The published test inserts a very large delay (600 days) into a
    remaining-duration activity on the critical path and confirms the project
    completion date moves out by a corresponding amount. Performing it requires
    a CPM recalculation, which this module does not do, so it is NOT claimed as
    a pass here.

    What IS decidable from the file alone is the failure this test exists to
    expose: a project finish that cannot move. If the finish activity is pinned
    by a MANDATORY constraint (CS_MANDSTART / CS_MANDFIN — the HARD_ABSOLUTE
    tier of cp_validator's constraint vocabulary), or has no predecessor at
    all, then no inserted delay can push it and the test fails
    deterministically.

    Start On / Finish On (CS_MSO / CS_MEO, the HARD_DATE tier) are NOT that
    case, and this shortcut used to treat them as if they were: it read the
    whole HARD_CONSTRAINTS set and told a schedule with a Finish On completion
    milestone that a 600-day delay "cannot move the completion date". P6
    imposes a mandatory date whatever the logic says, but it can delay the
    early date past a Start On / Finish On one, and the lateness shows as
    negative float — which is what DCMA-EA PAM 200.1 section 4.12 calls a pass.
    P6 exports routinely store Finish On and Start On activities later than
    their constraint date, and never a mandatory one; a completion held by a
    Start On or Finish On now reads NOT ASSESSED, and one with no predecessor
    still fails, on that rule. The CPM engine (cpp-cpm-engine) treats them as
    soft too. The hardness taxonomy answers "does this constraint distort
    float?" (check 5); it does not answer "can this date move?", and the
    result is never inferred from it.

    Anything else is reported as NOT ASSESSED (INFO) and is excluded from the
    /14 denominator. It must never be cited as a formal DCMA #12 pass.
    """
    if not work_tasks:
        return INFO, None, None, (
            'No work tasks — Critical Path Test NOT ASSESSED.'
        ), {'assessed': False}
    finish_task, finish_dt = _project_finish_task(work_tasks, _task_finish)
    if finish_task is None:
        return INFO, None, None, (
            'No dated activity — the project finish could not be identified, so '
            'the Critical Path Test was NOT ASSESSED.'
        ), {'assessed': False}
    code = finish_task.get('task_code', finish_task['task_id'])
    cstrs = (finish_task.get('cstr_type', ''), finish_task.get('cstr_type2', ''))
    # Only a mandatory date is immovable; a Start On / Finish On date is named
    # in the result and decides nothing.
    pinned = [c for c in cstrs if c in HARD_ABSOLUTE]
    soft = [c for c in cstrs if c in HARD_DATE]
    det = {'finish_activity': code, 'finish_date': str(finish_dt),
           'finish_constraints': pinned, 'finish_soft_constraints': soft,
           'assessed': True}
    if pinned:
        return BLOCK, None, None, (
            f'Critical Path Test FAILS: the project finish activity {code} is '
            f'pinned by {"/".join(pinned)}, so inserting a 600-day delay upstream '
            f'cannot move the completion date. The network cannot demonstrate a '
            f'live critical path through to completion.'
        ), det
    if finish_task['task_id'] not in pred_map:
        det['no_predecessor'] = True
        return BLOCK, None, None, (
            f'Critical Path Test FAILS: the project finish activity {code} has no '
            f'predecessor, so no upstream delay can drive it and the completion '
            f'date is not logic-driven.'
        ), det
    det['assessed'] = False
    if soft:
        labels = '/'.join(CONSTRAINT_TYPES.get(c, c) for c in soft)
        carries = (f'carries {"/".join(soft)} ({labels}), which P6 does not hold '
                   f'against logic: an upstream delay can still move its early '
                   f'dates past the imposed date and shows as negative float, so '
                   f'it is not a structural failure')
    else:
        carries = ('carries no hard constraint, so it is not a structural '
                   'failure')
    return INFO, None, None, (
        f'Critical Path Test NOT ASSESSED. The project finish activity {code} is '
        f'logic-driven and {carries}; confirming the pass requires the 600-day '
        f'insertion and a CPM recalculation, which this module does not perform. '
        f'Do NOT cite this as a formal DCMA #12 pass in a contract claim or '
        f'forensic submission.'
    ), det


def _check_13_cpli(work_tasks, cal_map, data_date_dt, profile, project=None):
    """#13 Critical Path Length Index.

    CPLI = (CP length + total float) / CP length, where:
      • CP length = working days from the status date to the project finish
      • total float = the total float of THE PROJECT FINISH activity

    The float term used to be the MINIMUM float over the whole critical set,
    and the critical set was defined as incomplete activities with float ≤ 0.
    Both together made the index unable to exceed 1.0 by construction: the
    minimum of a set of non-positive numbers is non-positive, and where one
    deeply negative activity dominated the minimum it produced a negative
    critical-path-length index, a quantity with no meaning. Taking the project
    finish's own float restores the published behaviour: above 1.0 when the
    project is ahead, below when it is behind.

    `project` is the PROJECT-table row (used to pick the default calendar for
    the working-day conversion of CP length).
    """
    threshold = profile['dcma_cpli_min']
    if not work_tasks or data_date_dt is None:
        return INFO, None, threshold, (
            'No activities or no data date — CPLI not computable.'
        ), {'cpli': None}

    # Project finish = latest early finish across the schedule (finish milestone
    # preferred on a tie — it is the activity that carries the project float).
    finish_task, latest_ef = _project_finish_task(
        work_tasks, lambda t: _parse_date(t.get('early_end_date', '')))
    if latest_ef is None:
        # Fall back to target_end_date as the last-known finish
        finish_task, latest_ef = _project_finish_task(
            work_tasks, lambda t: _parse_date(t.get('target_end_date', '')))
    if latest_ef is None or latest_ef <= data_date_dt:
        return INFO, None, threshold, (
            'Cannot determine CP end date — CPLI not computable.'
        ), {'cpli': None}

    # CP length in WORKING days (calendar-aware), NOT wall-clock days. The old
    # code took (latest_ef - data_date).total_seconds()/3600 — wall-clock hours,
    # counting every night and weekend — then divided by hours/day, inflating the
    # denominator (~+40% on a 5-day calendar: a 10-working-day CP spanning two
    # calendar weeks read as ~42 "days"). work_day_delta walks the project
    # calendar so the result matches the working-day CP length P6 reports.
    default_clndr_id = (project or {}).get('clndr_id', '') or (project or {}).get('dflt_clndr_id', '')
    _cp_cal = (cal_map or {}).get(default_clndr_id)
    cp_length_days = work_day_delta(data_date_dt, latest_ef, _cp_cal)
    # work_day_delta returns None when the span is unbounded/unparseable (e.g. a
    # sentinel 9999 finish > ~100yr from the data date). Treat that as
    # not-computable rather than crashing on `None <= 0`.
    if cp_length_days is None or cp_length_days <= 0:
        return INFO, None, threshold, (
            'CP length ≤ 0 or not computable (unbounded/sentinel finish) — '
            'CPLI not computable.'
        ), {'cpli': None}

    tf_hrs = _float_hours(finish_task) if finish_task else None
    if tf_hrs is None:
        return INFO, None, threshold, (
            'The project finish activity carries no computed total float — CPLI '
            'not computable. Recalculate the schedule in P6 and re-export.'
        ), {'cpli': None, 'cp_length_days': cp_length_days}
    tf_days = _hrs_to_days(tf_hrs, cal_map, (finish_task or {}).get('clndr_id', ''))

    cpli = (cp_length_days + tf_days) / cp_length_days
    sev = PASS if cpli >= threshold else BLOCK
    fin_code = (finish_task or {}).get('task_code', '')
    return sev, cpli, threshold, (
        f'CPLI = {cpli:.3f} (threshold ≥ {threshold}). CP length = {cp_length_days:.1f}d, '
        f'total float of the project finish activity {fin_code} = {tf_days:.1f}d.'
    ), {'cpli': cpli, 'cp_length_days': cp_length_days, 'tf_days': tf_days,
        'finish_activity': fin_code}


# ─────────────────────────────────────────────────────────────────────
# #14 BEI — Baseline Execution Index
# ─────────────────────────────────────────────────────────────────────

def _check_14_bei(work_tasks, baseline_tasks, data_date_dt, profile):
    """#14 BEI = tasks completed as of the status date / tasks with a baseline
    finish on or before the status date.

    Both populations are ONE project's: `work_tasks` is the assessed project's
    work tasks and `baseline_tasks` the matching baseline project's (see
    _baseline_project_tasks; None when no baseline was supplied). This check
    used to be handed the two whole files and iterate every TASK row in each,
    so in a multi-project export a completion in an unrelated project counted
    as this project's throughput: one not-started activity, BEI 0/1 = 0.0,
    read 1/1 = 1.0 and passed once an unrelated completed activity sat in the
    same file.

    The NUMERATOR IS UNRESTRICTED — every activity actually complete as of the
    status date counts, not only those the baseline had due by then. That is
    precisely why BEI can exceed 1.0 when work is pulled ahead. The previous
    implementation iterated the baseline-due subset for the numerator, so the
    numerator was a subset of the denominator and the index was capped at 1.0:
    it understated throughput and could never signal ahead-of-plan execution.

    Requires a baseline dataset. If no baseline, returns None with an INFO
    severity (NOT ASSESSED, excluded from the /14 denominator).
    """
    threshold = profile['bei_min']
    if baseline_tasks is None:
        return INFO, None, threshold, (
            'No baseline provided — BEI cannot be computed.'
        ), {'bei': None}
    if data_date_dt is None:
        return INFO, None, threshold, (
            'No data date — BEI cannot be computed.'
        ), {'bei': None}

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

    # Numerator: ALL activities actually complete as of the status date —
    # unrestricted, not intersected with bl_due. An activity whose actual finish
    # post-dates the status date is a future actual (DCMA #9) and is not yet
    # complete as of that date, so it does not count.
    completed = 0
    for ct in work_tasks:
        if ct.get('status_code', '') != COMPLETE_STATUS:
            continue
        ae = _parse_date(ct.get('act_end_date', ''))
        if ae is not None and ae > data_date_dt:
            continue
        completed += 1

    bei = completed / len(bl_due)
    sev = PASS if bei >= threshold else WARN
    return sev, bei, threshold, (
        f'BEI = {bei:.3f} (threshold ≥ {threshold}). {completed} activities are '
        f'complete as of the status date against {len(bl_due)} with a baseline '
        f'finish on or before it.'
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
    """Detect genuine breaks in the critical path chain.

    Continuity means every critical activity except a chain start is fed by
    at least one predecessor that is ITSELF on the critical path.

    A critical activity may legitimately merge several non-critical, floated
    predecessors. Those are ordinary merge inputs, not breaks. The previous
    definition — "any incomplete non-critical predecessor is a gap" — flagged
    every one of them, so a normal merge point reported as a discontinuity
    (false positive, fixed 2026-09-03). On an A-C-E-G-H critical path where G
    also takes D (total float 8hr, driving_path_flag N) and F (80hr, N), it
    reported 2 gaps at G<-D and G<-F while the longest path ran unbroken
    through E. The emitted gap objects carried no driving flag, no float and
    no longest-path marker, which is the tell: the check could not have been
    filtering on driving-ness because it never captured it. Those fields are
    now recorded on every gap so the evidence shows its own work.

    A real break is a critical activity that HAS incomplete predecessors but
    none of them on the critical path: the chain reaches it only from off-path
    work, so the critical path is not continuous through it. An activity with
    no predecessors at all is a chain start, not a break (an unintended one is
    an open end, which DCMA-01 owns).

    Returns: {'continuous': bool, 'gaps': [{'cp_task': code, 'gap_pred': code,
              'gap_pred_status': str, 'gap_pred_driving': str,
              'gap_pred_total_float_hr': str, 'rel_type': str}, ...],
              'cp_activities_checked': int}
    """
    cp_ids = {t['task_id'] for t in cp_tasks}
    gaps = []
    for t in cp_tasks:
        tid = t['task_id']
        preds = [p for p in pred_map.get(tid, []) if p.get('pred_task_id', '')]
        if not preds:
            # Chain start. Not a continuity break.
            continue
        if any(p.get('pred_task_id', '') in cp_ids for p in preds):
            # Fed by the critical chain itself — continuous through here.
            continue
        for p in preds:
            pid = p.get('pred_task_id', '')
            pred_task = task_map.get(pid)
            if pred_task is None:
                continue
            if pred_task.get('status_code', '') == COMPLETE_STATUS:
                continue
            gaps.append({
                'cp_task': t.get('task_code', tid),
                'gap_pred': pred_task.get('task_code', pid),
                'gap_pred_status': pred_task.get('status_code', ''),
                'gap_pred_driving': pred_task.get('driving_path_flag', ''),
                'gap_pred_total_float_hr': pred_task.get('total_float_hr_cnt', ''),
                'rel_type': p.get('pred_type', ''),
            })
    return {
        'continuous': not gaps,
        'gaps': gaps,
        'cp_activities_checked': len(cp_tasks),
    }


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

# Check registry — each entry is (id, name, reference), in the PUBLISHED DCMA
# order. All fourteen are independently assessed; none is an alias of another
# and none is hard-coded to pass.
#
# This list previously assigned #11 to a "Future Actuals" echo of #9 and #12 to
# a "Resource Coverage" echo of #10, each repeating the other's verdict and
# scoring it again, and pushed Missed Tasks to #13, CPLI to #14 and BEI outside
# the fourteen entirely. That dropped the Critical Path Test, counted two
# criteria twice, and made "DCMA #13" from this module mean something
# different from "#13" in the published standard.
_CHECK_REGISTRY = [
    ('DCMA-01-Logic', 'Logic', 'DCMA 14-Point #1'),
    ('DCMA-02-Leads', 'Leads', 'DCMA 14-Point #2'),
    ('DCMA-03-Lags', 'Lags', 'DCMA 14-Point #3'),
    ('DCMA-04-Relationship', 'Relationship Types', 'DCMA 14-Point #4'),
    ('DCMA-05-Hard', 'Hard Constraints', 'DCMA 14-Point #5'),
    ('DCMA-06-HighFloat', 'High Float', 'DCMA 14-Point #6'),
    ('DCMA-07-NegFloat', 'Negative Float', 'DCMA 14-Point #7'),
    ('DCMA-08-HighDuration', 'High Duration', 'DCMA 14-Point #8'),
    ('DCMA-09-InvalidDates', 'Invalid Dates', 'DCMA 14-Point #9'),
    ('DCMA-10-Resources', 'Resources', 'DCMA 14-Point #10'),
    ('DCMA-11-MissedTasks', 'Missed Tasks', 'DCMA 14-Point #11'),
    ('DCMA-12-CriticalPathTest', 'Critical Path Test', 'DCMA 14-Point #12'),
    ('DCMA-13-CPLI', 'Critical Path Length Index', 'DCMA 14-Point #13'),
    ('DCMA-14-BEI', 'Baseline Execution Index', 'DCMA 14-Point #14'),
]


def dcma_14_assess(data, profile='commercial', baseline_data=None, proj_id=None):
    """Run the full DCMA 14-Point assessment on parsed XER data.

    Args:
        data: parsed XER dict (from xer_parser.parse_xer or equivalent).
        profile: 'commercial' (default), 'nuclear', 'mining'.
        baseline_data: optional parsed XER baseline for BEI computation.
        proj_id: the PROJECT.proj_id to assess. A caller that has already
            selected a project passes it so that one selection runs through
            every check, narrative and figure — cp_validator selects by TASK-row
            count or by an explicit index, and used to hand the whole file over,
            so the embedded block could describe a different project from the
            report's own title and population; the two rules disagree on real
            multi-project exports. Left out, the latest-data-date rule below
            picks, as it always did. An id the file does not carry raises
            ValueError rather than assessing nothing.

    Returns:
        dict: {
            'profile':                str,
            'proj_id':                str — the project assessed,
            'project_name':           str — its PROJECT.proj_short_name,
            'data_date':              str — its PROJECT.last_recalc_date,
            'baseline_proj_id':       str — the baseline project read for
                                      checks 11 and 14 ('' when none),
            'baseline_project_match': str — how it was matched,
            'report':                 ValidationReport,
            'dcma_score':             int — criteria PASSED,
            'dcma_max':               int — criteria actually ASSESSED (≤14);
                                      the score is out of this, not out of a
                                      nominal 14,
            'dcma_not_assessed':      list[check_id] that could not be evaluated
                                      on this file,
            'cpli':                   float or None,
            'bei':                    float or None,
            'critical_paths':         list[list[task_code]],
            'multiple_critical_paths': bool,
            'cp_continuity':          {'continuous': bool, 'gaps': [...]},
            'per_check':              {check_id: {severity, value, threshold, message}},
            'calendar_resolution':    the calendar resolution block for the
                                      activities assessed: blank calendar ids
                                      resolved onto the project or default
                                      calendar, and any with no usable calendar
                                      (those also raise DCMA-Ext-TaskCalendar);
                                      empty, with a note, when the bundled
                                      parser cannot resolve them,
        }
    """
    prof = get_profile(profile)
    report = ValidationReport(
        subject=f'DCMA 14-Point Assessment [{profile}]',
        context={'profile': profile, 'profile_name': prof.get('name', profile)},
    )

    # ── Extract tables ──
    # A blank TASK.clndr_id is the project calendar (PROJECT.clndr_id, else the
    # default_flag=Y calendar): MPXJ writes it blank for every MS Project task
    # without a task calendar. A blank id that reaches _hrs_to_days is read as
    # a flat 8 h/day, so on a 10 h/day project calendar High Float #6, High
    # Duration #8 and the CPLI float #13 count 400 h as 50 working days, not
    # 40. Resolved ONCE here when the parser can do it (see the fallbacks at
    # the top of this module). The parsed data is not modified;
    # result['calendar_resolution'] lists what resolved.
    task_cals = resolve_task_calendars(data)
    tasks_all = with_resolved_calendars(get_table(data, 'TASK'), task_cals)
    preds_all = get_table(data, 'TASKPRED')
    projects = get_table(data, 'PROJECT')
    rsrc_assignments = get_table(data, 'TASKRSRC')
    cal_map = get_calendar_map(data)

    # ── Pick the target project: the caller's, else LATEST data date, ties by
    # TASK-row count ──
    #
    # A caller that has already selected a project passes proj_id, and that
    # selection is the one every check below runs on.
    #
    # This was most-TASK-rows. The two criteria disagree on real multi-project
    # exports, and most-rows picks the staler project: a baseline copy or an
    # older snapshot routinely carries more rows than the live schedule.
    #
    # A DCMA-14 assessment grades the LIVE schedule. A baseline copy or an older
    # monthly snapshot in the same file is not it, and is routinely the LARGER
    # of the two because a baseline carries the full unbuilt scope.
    if proj_id is not None:
        if not any(p.get('proj_id', '') == proj_id for p in projects):
            raise ValueError(
                'proj_id %r is not a PROJECT in this file (it carries %s). '
                'Assessing it would grade an empty population.'
                % (proj_id, ', '.join(repr(p.get('proj_id', '')) for p in projects) or 'none'))
        target_pid = proj_id
    elif projects and len(projects) > 1:
        proj_counts = {}
        for t in tasks_all:
            proj_counts[t.get('proj_id', '')] = proj_counts.get(t.get('proj_id', ''), 0) + 1

        def _rank(p):
            pid = p.get('proj_id', '')
            return (str(p.get('last_recalc_date', '') or ''), proj_counts.get(pid, 0))

        target_pid = max(projects, key=_rank).get('proj_id', '')
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
    # Both endpoints must be in the target project — a relationship with one end
    # in ANOTHER project is a cross-project link, not this project's internal
    # logic, and counting it inflates the DCMA #2/#3/#4 relationship set in
    # multi-project XERs. (Single-project XERs are unaffected: all tasks are in
    # task_map, so `and` and `or` coincide.)
    preds_for_project = [p for p in preds_all if p.get('task_id', '') in task_map and p.get('pred_task_id', '') in task_map]
    for p in preds_for_project:
        pred_map.setdefault(p.get('task_id', ''), []).append(p)
        succ_map.setdefault(p.get('pred_task_id', ''), []).append(p)

    work_tasks = [t for t in tasks if _is_work_task(t)]
    incomplete = [t for t in work_tasks if t.get('status_code', '') != COMPLETE_STATUS]
    # The baseline rows checks 11 and 14 read: the MATCHING baseline project's,
    # not every row in the baseline file.
    baseline_tasks, baseline_pid, baseline_match = _baseline_project_tasks(
        baseline_data, project, work_tasks)
    # P6's OWN critical threshold, not a hardcoded zero. PROJECT.critical_drtn_hr_cnt
    # is the "activities are critical when total float is less than or equal to N
    # hours" setting; a project that sets it to, say, 9 hours flags TF <= 9h as
    # critical, so a TF <= 0 filter measures a different set than the source
    # file declares. Blank/absent means P6's default of 0.
    critical_float_hrs = _safe_float(project.get('critical_drtn_hr_cnt', ''), 0.0)
    # A blank total_float is missing data, not a value — see _float_hours. It is
    # excluded from the critical set rather than coerced (999 excluded it
    # silently; 0 would have made every such activity critical).
    cp_tasks = [
        t for t in incomplete
        if _float_hours(t) is not None and _float_hours(t) <= critical_float_hrs
    ]

    data_date_dt = _parse_date(project.get('last_recalc_date', ''))

    # Data date correction. An update statused past its data date is graded
    # here as filed, and #9 still fails on it. Where the optional
    # data_date_correction module is on the path, its detect() reads the
    # project graded above, changes nothing, and adds a sentence to #9's
    # finding naming the latest actual and the corrected data date. This
    # repository does not ship the module, so the record is None here.
    try:
        from data_date_correction import detect as _ddc_detect
        ddc_record = _ddc_detect(data, proj_id=target_pid)
    except ImportError:
        ddc_record = None

    # ── Run each check ──
    per_check = {}
    check_results = []

    sev, val, thr, msg, det = _check_01_logic(work_tasks, incomplete, pred_map, succ_map, prof)
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

    sev, val, thr, msg, det = _check_09_invalid_dates(work_tasks, data_date_dt, prof,
                                                      correction=ddc_record)
    check_results.append(('DCMA-09-InvalidDates', 'Invalid Dates', 'DCMA 14-Point #9', sev, val, thr, msg, det))

    sev, val, thr, msg, det = _check_10_resources(work_tasks, rsrc_assignments, prof)
    check_results.append(('DCMA-10-Resources', 'Resources', 'DCMA 14-Point #10', sev, val, thr, msg, det))

    sev, val, thr, msg, det = _check_11_missed_tasks(work_tasks, baseline_tasks, data_date_dt, prof)
    check_results.append(('DCMA-11-MissedTasks', 'Missed Tasks', 'DCMA 14-Point #11', sev, val, thr, msg, det))

    sev, val, thr, msg, det = _check_12_critical_path_test(work_tasks, pred_map, prof)
    check_results.append(('DCMA-12-CriticalPathTest', 'Critical Path Test', 'DCMA 14-Point #12', sev, val, thr, msg, det))

    sev, val, thr, msg, det = _check_13_cpli(work_tasks, cal_map, data_date_dt, prof, project)
    cpli_value = det.get('cpli')
    check_results.append(('DCMA-13-CPLI', 'Critical Path Length Index', 'DCMA 14-Point #13', sev, val, thr, msg, det))

    sev, val, thr, msg, det = _check_14_bei(work_tasks, baseline_tasks, data_date_dt, prof)
    bei_value = det.get('bei')
    check_results.append(('DCMA-14-BEI', 'Baseline Execution Index', 'DCMA 14-Point #14', sev, val, thr, msg, det))

    # ── Fold into the report and score ──
    # NO criterion is hard-coded to pass. A criterion that could not be
    # evaluated on this file (INFO — e.g. BEI with no baseline supplied, or the
    # Critical Path Test where the finish is not structurally pinned) is
    # excluded from BOTH the numerator and the denominator and named in
    # dcma_not_assessed, so the score is out of what was actually measured
    # rather than out of a nominal 14.
    passed_count = 0
    assessed_count = 0
    not_assessed = []
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
            evidence={'value': val, 'threshold': thr, **det},
        ))
        if sev == INFO:
            not_assessed.append(check_id)
            continue
        assessed_count += 1
        if sev == PASS:
            passed_count += 1
    dcma_score = passed_count
    dcma_max = assessed_count

    # ── Task calendars (outside the score, like the other extensions) ──
    # Blank ids resolved onto the project or default calendar are disclosed in
    # the block, not warned: that is the calendar P6 schedules them on. An
    # activity with no usable calendar at all is warned, because its float and
    # duration fell to 8 h/day in #6, #8 and #13.
    work_ids = {t.get('task_id', '') for t in work_tasks}
    calendar_resolution = calendar_resolution_block(
        task_cals, keep=lambda r: r.get('task_id', '') in work_ids
        and (not target_pid or r.get('proj_id', '') == target_pid))
    if calendar_resolution['unresolved_count']:
        _n = calendar_resolution['unresolved_count']
        _n_blank = sum(1 for u in calendar_resolution['unresolved'] if u['reason'] == 'blank')
        report.add(Finding(
            severity=WARN, check_id='DCMA-Ext-TaskCalendar',
            message=(
                f'{_n} activit{"y has" if _n == 1 else "ies have"} no usable calendar '
                f'({_n_blank} with a blank calendar id and no project or default calendar '
                f'in the file, {_n - _n_blank} naming a calendar the file does not '
                f'declare): their float and duration were read at 8 h/day in checks #6, '
                f'#8 and #13, which may not be the week they are scheduled on. Assign a '
                f'calendar in the source schedule and re-export.'),
            reference='P6 activity calendar (TASK.clndr_id)',
            # Full list — never truncate. CPP forensic-correctness rule.
            evidence={'unresolved': list(calendar_resolution['unresolved'])},
        ))

    # ── Multiple critical paths ──
    crit_paths = _identify_critical_paths(cp_tasks, pred_map, task_map)
    multiple_cp = len(crit_paths) > 1
    if multiple_cp:
        report.add(Finding(
            severity=INFO, check_id='DCMA-Ext-MultipleCP',
            message=f'{len(crit_paths)} distinct critical paths identified.',
            reference='AACE 49R-06',
            evidence={'path_count': len(crit_paths), 'paths': crit_paths},
        ))

    # ── CP continuity ──
    continuity = _cp_continuity(cp_tasks, pred_map, task_map)
    if continuity['gaps']:
        report.add(Finding(
            severity=WARN, check_id='DCMA-Ext-CPContinuity',
            message=f'Critical path has {len(continuity["gaps"])} continuity gap(s).',
            reference='AACE 49R-06',
            # Full list — never truncate. CPP forensic-correctness rule.
            evidence={'gaps': list(continuity['gaps'])},
        ))
    else:
        report.add(Finding(
            severity=PASS, check_id='DCMA-Ext-CPContinuity',
            message='Critical path is continuous (no gaps detected).',
            reference='AACE 49R-06',
        ))

    return {
        'profile': profile,
        'profile_name': prof.get('name', profile),
        # Which project every figure above was measured on, so a report that
        # embeds this block can be checked against its own title and population.
        'proj_id': target_pid,
        'project_name': project.get('proj_short_name', ''),
        'data_date': project.get('last_recalc_date', ''),
        'baseline_proj_id': baseline_pid,
        'baseline_project_match': baseline_match,
        'report': report,
        'dcma_score': dcma_score,
        'dcma_max': dcma_max,
        'dcma_not_assessed': not_assessed,
        'cpli': cpli_value,
        'bei': bei_value,
        'critical_paths': crit_paths,
        'multiple_critical_paths': multiple_cp,
        'cp_continuity': continuity,
        'per_check': per_check,
        # Blank TASK.clndr_id resolution for the activities assessed: what fell
        # back to the project / default calendar, and what has none.
        'calendar_resolution': calendar_resolution,
    }


# ─────────────────────────────────────────────────────────────────────
# Dashboard rendering helper — called from cp_validator.generate_dashboard
# ─────────────────────────────────────────────────────────────────────

def render_dcma_scorecard_html(assessment):
    """Render the DCMA 14 scorecard as an HTML fragment suitable for embedding."""
    if not assessment:
        return ''
    score = assessment.get('dcma_score', 0)
    dcma_max = assessment.get('dcma_max', 14)
    not_assessed = assessment.get('dcma_not_assessed', []) or []
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
            f'<td style="text-align:right; color:#94a3b8;">{_esc(thr_str)}</td>'
            f'<td>{_esc(msg)}</td>'
            f'</tr>'
        )

    # Graded on the share of ASSESSED criteria passed, so a file on which fewer
    # criteria could be evaluated is not marked down for the ones that could not.
    ratio = (score / dcma_max) if dcma_max else 1.0
    score_color = '#22c55e' if ratio >= 0.9 else ('#f59e0b' if ratio >= 0.7 else '#ef4444')
    cpli_str = f'{cpli:.3f}' if isinstance(cpli, (int, float)) else '—'
    bei_str = f'{bei:.3f}' if isinstance(bei, (int, float)) else '—'
    paths = assessment.get('critical_paths', [])
    multi = assessment.get('multiple_critical_paths', False)

    not_assessed_html = (
        f'<div style="font-size:0.75rem; color:#94a3b8; margin-bottom:12px;">'
        f'Not assessed on this file: {_esc(", ".join(not_assessed))}</div>'
        if not_assessed else '')
    html = f'''
    <div class="dcma-scorecard" style="margin:24px 0; padding:16px; background:#0f172a; border-radius:8px; border-left:4px solid {score_color};">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
            <div>
                <div style="font-size:1.1rem; font-weight:700; color:#f1f5f9;">DCMA 14-Point Scorecard</div>
                <div style="font-size:0.8rem; color:#94a3b8;">Profile: {_esc(profile_name)}</div>
            </div>
            <div style="text-align:right;">
                <div style="font-size:2rem; font-weight:700; color:{score_color};">{score}/{dcma_max}</div>
                <div style="font-size:0.75rem; color:#94a3b8;">Criteria passed, of those assessed</div>
            </div>
        </div>
        <div style="display:flex; gap:24px; margin-bottom:12px; flex-wrap:wrap;">
            <div><span style="color:#94a3b8; font-size:0.75rem;">CPLI:</span> <span style="font-weight:700; color:#f1f5f9;">{cpli_str}</span></div>
            <div><span style="color:#94a3b8; font-size:0.75rem;">BEI:</span> <span style="font-weight:700; color:#f1f5f9;">{bei_str}</span></div>
            <div><span style="color:#94a3b8; font-size:0.75rem;">Critical Paths:</span> <span style="font-weight:700; color:#f1f5f9;">{len(paths)}{' (multiple)' if multi else ''}</span></div>
        </div>
        {not_assessed_html}
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
