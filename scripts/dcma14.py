#!/usr/bin/env python3
"""DCMA 14-Point Schedule Assessment.

Implements the Defense Contract Management Agency 14-Point assessment plus
the BEI (Baseline Execution Index) metric and the "multiple critical paths /
CP continuity / driving-path tracer" extras called out by the VP teardown
review.

The DCMA 14 checks, measured as CPP's written definition states them
(version 1, 7 November 2026: https://criticalpathpartners.ca/dcma-14-definition.html;
a copy is in tests/fixtures/dcma_parity/DCMA_DEFINITION.md). "Ordinary" is TT_Task,
TT_Rsrc and any type that is neither a milestone nor an LOE / WBS summary:

    1. Logic          — incomplete ordinary activities and milestones with no
                        logic relationship in or out (a link to an LOE or WBS
                        summary is not logic), ≤ 5%; a start / finish milestone
                        exempt only at the network start / finish
    2. Leads          — live relationships (successor incomplete) with lag < 0;
                        none
    3. Lags           — live relationships with lag > 0, ≤ 5% (a lag over 44
                        working days is listed for information)
    4. Relationship   — live relationships that are Finish-to-Start, ≥ 90%
    5. Hard           — incomplete ordinary activities with a hard constraint in
                        the DCMA sense (PAM 200.1 s4.5: Must Start On, Must
                        Finish On, Start No Later Than, Finish No Later Than =
                        CS_MSO, CS_MEO, CS_MANDSTART, CS_MANDFIN, CS_MSOB,
                        CS_MEOB), primary or secondary, ≤ 5%
    6. High Float     — incomplete ordinary activities with a computed total
                        float > 44 working days, ≤ 5%
    7. Negative Float — the same population with total float < 0; none
    8. High Duration  — incomplete ordinary activities with an original
                        duration > 44 working days (the baseline's, when the
                        activity is in a supplied baseline), ≤ 5%
    9. Invalid Dates  — ordinary activities and milestones, complete included,
                        with an actual date on a day after the data date's day
                        or (incomplete work) a forecast (early) date on a day
                        before it; none
   10. Resources      — incomplete ordinary activities of at least one working
                        day carrying an assignment with hours or cost; 100%, on
                        every profile; not scored with no assignments at all
   11. Missed Tasks   — BASELINE ordinary activities due by the data date that
                        did not finish by their baseline finish's day (still
                        open, finished late, or no longer in the current file),
                        ≤ 5%. Needs a baseline; not scored without one or when
                        < 80% of the due activities match a current one by
                        Activity ID
   12. Critical Path Test — insert a large delay (commonly 600 working days) on
                        the critical path and confirm completion moves. Fails
                        on a logic cycle or a mandatory-constrained completion;
                        otherwise not scored until the CPM recalculation lands
   13. CPLI           — (CP length + float to the contract finish) / CP length
                        ≥ 0.95, CP length the working time from the data date to
                        the completion activity's early finish. The contract
                        finish is the baseline finish of the same activity, else
                        a deadline in the file (P6 float); with neither, not
                        scored
   14. BEI            — current ordinary activities complete as of the data date
                        / baseline ordinary activities due by it, ≥ 0.95.
                        Requires a baseline XER. The numerator is UNRESTRICTED,
                        which is why BEI can legitimately exceed 1.0.

Every result is PASS, FAIL or NOT SCORED with the counts behind it
(per_check[id]['counts']: status, num, den, value), beside the severity this
module has always reported. The nuclear and mining profiles change some
thresholds; a result graded on one says the threshold is CPP's.

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

A check whose population is empty (no incomplete work, no live relationships,
nothing due) or whose inputs are missing is NOT SCORED (severity INFO), never a
vacuous PASS, and drops out of dcma_score and dcma_max.

Standards:
    DCMA 14-Point Assessment (DCMA Defense Contract Management Agency 14-Point Schedule Assessment Procedure; DCMA-EA PAM 200.1)
    AACE 49R-06 "Identifying the Critical Path"
    NDIA PASEG (Planning and Scheduling Excellence Guide) §10
"""
import os
import sys
from datetime import datetime, timedelta
from fractions import Fraction

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
    resolve_task_calendars,
    with_resolved_calendars,
    calendar_resolution_block,
)

# Reuse the hard-constraint taxonomy from cp_validator — single source of truth.
from cp_validator import (  # noqa: E402
    HARD_ABSOLUTE, HARD_CONSTRAINTS, HARD_DATE, _hrs_to_days, _safe_float)

# The module whose clndr_data grammar #13 reads a calendar's shift times with
# (`_day_slot_tables`): cpp-cpm-engine's `cpm`. The bundled parser,
# cpp-xer-parser at the commit CI pins, does not carry the loader, so it is
# taken from the parser when the parser has it, else from the bundled
# driving-path tracer (cpp-cpm-engine's `cpm` from the path). With no engine on
# the path, the same table is read with the bundled parser's own clndr_data
# grammar (its _d7_* primitives, the engine's grammar), so #13 measures the
# same working time with or without the engine.
try:
    from xer_parser import _canonical_cpm  # noqa: E402
except ImportError:
    import types as _types
    import xer_parser as _xp

    _PARSER_SLOT_CACHE = {}

    def _parser_day_slot_tables(raw):
        """(week_slots[js_dow], exception_slots{iso-date}) decoded from a
        clndr_data blob with the bundled parser's grammar, or (None, None)
        when it carries no usable hours. The engine's _day_slot_tables, read
        the same way."""
        if raw in _PARSER_SLOT_CACHE:
            return _PARSER_SLOT_CACHE[raw]
        week = [None] * 7
        exc = {}
        dow_block = _xp._d7_block_after(raw, 'DaysOfWeek')
        if dow_block is not None:
            for seg in _xp._d7_segments_of(dow_block):
                m = _xp._D7_DAY_SEG.match(seg)
                if m:
                    week[(int(m.group(1)) - 1) % 7] = _xp._d7_slots_of(seg)
        exc_block = _xp._d7_block_after(raw, 'Exceptions')
        if exc_block is not None:
            for seg in _xp._d7_segments_of(exc_block):
                dm = _xp._D7_EXC_DATE.search(seg)
                if not dm:
                    continue
                ds = _xp._d7_serial_to_date_string(dm.group(1))
                if ds:
                    exc[ds] = _xp._d7_slots_of(seg)
        out = (week, exc) if any(w for w in week) else (None, None)
        if len(_PARSER_SLOT_CACHE) < 256:
            _PARSER_SLOT_CACHE[raw] = out
        return out

    _PARSER_GRAMMAR = _types.SimpleNamespace(_day_slot_tables=_parser_day_slot_tables)

    def _canonical_cpm():
        """cpp-cpm-engine's `cpm` module when it is importable and reads slot
        tables, else the bundled parser's grammar in its place."""
        try:
            from driving_path import _canonical_cpm as _engine
            eng = _engine()
            if hasattr(eng, '_day_slot_tables'):
                return eng
        except Exception:
            pass
        return _PARSER_GRAMMAR

# The bundled parser, cpp-xer-parser at the commit CI pins, does not carry the
# signed working-day advance that #13 CPLI measures the critical path with. It
# is taken from the parser when the parser has it, and
# tests/test_dcma14_guards.py holds the parser's to the same reading; until
# then the definition below stands in.
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


# ─────────────────────────────────────────────────────────────────────
# The one written definition (7 November 2026)
# ─────────────────────────────────────────────────────────────────────
# DCMA-14 is measured here exactly as CPP's written definition states it
# (version 1, https://criticalpathpartners.ca/dcma-14-definition.html; a copy,
# DCMA_DEFINITION.md, is in tests/fixtures/dcma_parity/). Every CPP tool that
# reports a DCMA-14 result measures the same text. The constants below mirror
# dcma_definition.json beside that copy, and tests/test_dcma_parity.py checks
# this mirror against that file and this engine against the shared parity
# fixtures.
#
# Every result is PASS, FAIL or NOT SCORED with the counts behind it
# (per_check[id]['counts']). The severity this module has always reported is
# kept beside it: PASS, a check's failing severity (WARN or BLOCK) for a FAIL,
# and INFO for NOT SCORED.
DCMA_DEFINITION_VERSION = 1

STATUS_PASS = 'PASS'
STATUS_FAIL = 'FAIL'
STATUS_NOT_SCORED = 'NOT SCORED'

# D1 activity types. Ordinary: TT_Task, TT_Rsrc and any type not listed here.
DCMA_MILESTONE_TYPES = frozenset({'TT_Mile', 'TT_FinMile'})
DCMA_EXCLUDED_TYPES = frozenset({'TT_LOE', 'TT_WBS'})

# #5 vocabulary. DCMA-EA PAM 200.1 s4.5 lists four hard constraint types:
# Must-Start-On, Must-Finish-On, Start-No-Later-Than and Finish-No-Later-Than.
# In P6 the first two are Start On / Finish On (CS_MSO, CS_MEO) and the
# mandatory pair (CS_MANDSTART, CS_MANDFIN); the last two are Start On or
# Before (CS_MSOB) and Finish On or Before (CS_MEOB). cp_validator's
# HARD_CONSTRAINTS answers a different question (can this date move?) and is
# unchanged; this set is DCMA #5's only. The legacy codes CS_MANSTART /
# CS_MANFINISH are not in xer_parser.CONSTRAINT_TYPES and are not listed.
DCMA_HARD_CONSTRAINTS = frozenset({
    'CS_MANDSTART', 'CS_MANDFIN', 'CS_MSO', 'CS_MEO', 'CS_MSOB', 'CS_MEOB'})
# #12: only P6's mandatory pair pins a date against logic.
DCMA_MANDATORY_CONSTRAINTS = frozenset({'CS_MANDSTART', 'CS_MANDFIN'})
# #13: finish constraints that make a deadline in the file when no baseline is
# supplied (with PROJECT.plan_end_date, P6 'Must Finish By').
CPLI_DEADLINE_CONSTRAINTS = frozenset({'CS_MEO', 'CS_MEOB', 'CS_MANDFIN'})

# #11: below this share of due baseline activities matching a current one by
# Activity ID, the baseline looks renumbered and a figure would be built on the
# IDs, not the work.
MISSED_TASKS_MIN_MATCH_PCT = 80.0

# #10 (2026-11-07, the written definition): every profile. The definition
# passes #10 only when every incomplete ordinary activity of at least one
# working day is resourced. config_profiles carries 100 on every profile; this
# module grades on the definition's figure and does not read the profile
# setting, and the parity test checks every profile carries the same figure.
DCMA_RESOURCES_MIN_PCT = 100.0
DCMA_RESOURCES_MIN_DURATION_DAYS = 1.0
RESOURCE_LOAD_FIELDS = ('target_qty', 'remain_qty', 'target_cost', 'remain_cost')

# #3: a lag longer than this (working days, successor's calendar) is listed
# for information; it decides nothing.
LONG_LAG_INFO_DAYS = 44

# D3: with no usable calendar, a working day is 8 hours.
FALLBACK_HOURS_PER_DAY = 8.0

# The definition's thresholds ("thresholds" in dcma_definition.json), keyed by
# the config_profiles setting that grades the same quantity. A profile whose
# setting differs grades on CPP's own threshold, and the result says so.
DEFINITION_THRESHOLDS = {
    1: (('dcma_logic_max_missing_pct', 5),),
    2: (('dcma_leads_max_count', 0),),
    3: (('dcma_lags_max_pct', 5),),
    4: (('dcma_fs_min_pct', 90),),
    5: (('dcma_hard_constraints_max_pct', 5),),
    6: (('dcma_high_float_max_days', 44), ('dcma_high_float_max_pct', 5)),
    7: (('dcma_negative_float_max_count', 0),),
    8: (('dcma_high_duration_max_days', 44), ('dcma_high_duration_max_pct', 5)),
    9: (('dcma_invalid_dates_max_count', 0),),
    11: (('dcma_missed_tasks_max_pct', 5),),
    13: (('dcma_cpli_min', 0.95),),
    14: (('bei_min', 0.95),),
}


# ─────────────────────────────────────────────────────────────────────
# Helpers — date parsing and misc
# ─────────────────────────────────────────────────────────────────────

def _parse_date(val):
    """Parse a P6 date field (YYYY-MM-DD HH:MM) into a datetime. Returns None on failure.

    Intentionally not a date-only parser: this module needs
    `datetime.datetime` for HH:MM-aware
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
    """True if t is an ordinary activity or a milestone (D1): never LOE/WBS."""
    return t.get('task_type', '') not in DCMA_EXCLUDED_TYPES


def _is_milestone(t):
    return t.get('task_type', '') in DCMA_MILESTONE_TYPES


def _is_ordinary(t):
    """D1: TT_Task, TT_Rsrc and any type that is neither a milestone nor an
    LOE / WBS summary."""
    return _is_work_task(t) and not _is_milestone(t)


def _is_complete(t):
    """D2: complete means status_code TK_Complete; everything else is not."""
    return t.get('status_code', '') == COMPLETE_STATUS


def _norm_code(code):
    """D8: an Activity ID with surrounding spaces trimmed, case ignored."""
    return str(code or '').strip().casefold()


def _code(t):
    return t.get('task_code', '') or t.get('task_id', '')


def _counts(status, num=None, den=None, value=None):
    """The uniform per-check counts block (per_check[id]['counts'])."""
    return {'status': status, 'num': num, 'den': den,
            'value': float(value) if value is not None else None}


def _ns_counts():
    return _counts(STATUS_NOT_SCORED)


def _at_most_pct(num, den, pct):
    """D7: num of den is at most pct%, tested on the counts (num x 100 against
    pct x den), never on a rounded percentage."""
    return Fraction(num) * 100 <= Fraction(str(pct)) * den


def _at_least_pct(num, den, pct):
    """D7: num of den is at least pct%, tested on the counts."""
    return Fraction(num) * 100 >= Fraction(str(pct)) * den


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


def _early_or_planned_finish(t):
    """D11's finish: the early finish, else the planned finish."""
    return (_parse_date(t.get('early_end_date', ''))
            or _parse_date(t.get('target_end_date', '')))


def _baseline_finish(bt):
    """D12: a baseline activity's finish is its planned finish
    (target_end_date), else its early finish. Read the same way by #11, #13
    and #14 (2026-11-07, the written definition: #13 read the early finish first, and
    #11 / #14 read the planned finish only)."""
    return (_parse_date(bt.get('target_end_date', ''))
            or _parse_date(bt.get('early_end_date', '')))


def _completion_tie_rank(t):
    """D11 tie order: a finish milestone, then an activity of zero original
    duration (a completion typed as a task), then anything else."""
    if t.get('task_type', '') == 'TT_FinMile':
        return 2
    raw = str(t.get('target_drtn_hr_cnt', '') or '').strip()
    try:
        return 1 if raw and float(raw) == 0 else 0
    except (TypeError, ValueError):
        return 0


def _project_finish_task(work_tasks, finish_fn):
    """(activity, instant) with the latest finish. On a tie: a finish
    milestone, then an activity of zero original duration, else the first in
    the file (D11; the zero-duration step added 2026-11-07, the written definition).

    P6 schedules routinely land the last working activity and the completion
    milestone on the same instant, and several activities can share the finish
    instant on one export. The milestone is the
    activity that carries the project's float and the completion constraint, so
    it is the one the finish-side criteria must read; a completion typed as a
    zero-duration task stands in for it.
    """
    best, best_dt = None, None
    for t in work_tasks:
        d = finish_fn(t)
        if d is None:
            continue
        if best_dt is None or d > best_dt:
            best, best_dt = t, d
        elif d == best_dt and _completion_tie_rank(t) > _completion_tie_rank(best):
            best = t
    return best, best_dt


def _completion_activity(work_tasks):
    """D11: the ordinary or milestone activity, complete or not, with the
    latest early finish (else planned finish). On a tie: a finish milestone,
    then an activity of zero original duration, else the first in the file.
    Used by #12 and #13."""
    return _project_finish_task(
        [t for t in work_tasks if _is_work_task(t)], _early_or_planned_finish)


def _d0_rank_key(rows):
    """D0's order for choosing one project among several: the latest
    last_recalc_date, then the most TASK rows in `rows`. max() over a list in
    file order keeps the first of equal keys, which is D0's last tie-break.
    D9 breaks its own ties the same way."""
    counts = {}
    for t in rows or ():
        counts[t.get('proj_id', '')] = counts.get(t.get('proj_id', ''), 0) + 1

    def _key(p):
        return (_parse_date(p.get('last_recalc_date', '')) or datetime.min,
                counts.get(p.get('proj_id', ''), 0))
    return _key


# ── Working time (D3, #13) ──────────────────────────────────────────

_WORKING_TIME_MAX_DAYS = 36600   # about 100 years: a sentinel finish is no span


def _hours_per_day(cal):
    try:
        hpd = float((cal or {}).get('hours_per_day') or 0)
    except (TypeError, ValueError):
        hpd = 0.0
    return hpd if hpd > 0 else FALLBACK_HOURS_PER_DAY


def _day_working_slots(day, cal):
    """Working (start, finish) minutes of the day on `cal`: the shifts its
    clndr_data declares (read by the canonical engine's grammar), else P6's
    internal Standard week, opening at 08:00 for the calendar's hours a day."""
    cal = cal or {}
    raw = str(cal.get('raw') or '')
    if raw and '(' in raw and not cal.get('p6_fallback') and not cal.get('parse_incomplete'):
        eng = _canonical_cpm()
        if eng is not None and hasattr(eng, '_day_slot_tables'):
            week, exc = eng._day_slot_tables(raw)
            if week is not None:
                iso = day.isoformat()
                if iso in exc:
                    return exc[iso] or []
                return week[(day.weekday() + 1) % 7] or []
    iso = day.isoformat()
    work_days = cal.get('work_days') or [1, 2, 3, 4, 5]
    working = (iso in set(cal.get('special_workdays') or [])
               or ((day.weekday() + 1) % 7 in work_days
                   and iso not in set(cal.get('holidays') or [])))
    if not working:
        return []
    return [(480, min(1440, 480 + int(round(_hours_per_day(cal) * 60))))]


def _working_days_between(d1, d2, cal):
    """Signed working time from d1 to d2 on `cal`, in working days: working
    hours divided by the calendar's hours per day (a data date at 08:00 and a
    finish at the close of the fifth working day is 5.0). None when either is
    missing or the span is unbounded (a sentinel date)."""
    if d1 is None or d2 is None:
        return None
    sign = 1
    if d2 < d1:
        d1, d2, sign = d2, d1, -1
    if (d2.date() - d1.date()).days > _WORKING_TIME_MAX_DAYS:
        return None
    minutes = 0
    day, last = d1.date(), d2.date()
    while day <= last:
        lo = d1.hour * 60 + d1.minute if day == d1.date() else 0
        hi = d2.hour * 60 + d2.minute if day == last else 1440
        if hi > lo:
            for s, f in _day_working_slots(day, cal):
                minutes += max(0, min(f, hi) - max(s, lo))
        day += timedelta(days=1)
    return sign * minutes / 60.0 / _hours_per_day(cal)


def _project_calendar(project, cal_map):
    """The project calendar (PROJECT.clndr_id), else the default calendar,
    else none (Mon-Fri, 8 hours from 08:00). Returns (calendar, how)."""
    cal_map = cal_map or {}
    for cid in ((project or {}).get('clndr_id', ''), (project or {}).get('dflt_clndr_id', '')):
        if cid and cid in cal_map:
            return cal_map[cid], 'project calendar'
    for c in cal_map.values():
        if isinstance(c, dict) and c.get('default_flag') == 'Y':
            return c, 'default calendar'
    return None, 'no calendar in the file: Mon-Fri, 8 hours a day'


# ── Relationships (D4) and cycles (#12) ─────────────────────────────

def _rel_label(p, task_map):
    pred = task_map.get(p.get('pred_task_id', ''), {})
    succ = task_map.get(p.get('task_id', ''), {})
    return f"{_code(pred) or p.get('pred_task_id', '')} > {_code(succ) or p.get('task_id', '')}"


def _logic_cycles(work_ids, logic_rels):
    """Strongly connected groups of activities in the logic network (an
    iterative Tarjan), each one a logic cycle; a self-link is a cycle of one.
    Returns a list of task_id lists, in file order of their first member."""
    succ = {}
    self_loops = set()
    for p in logic_rels:
        a, b = p.get('pred_task_id', ''), p.get('task_id', '')
        if a == b:
            self_loops.add(a)
        succ.setdefault(a, []).append(b)
    index, low, on_stack, stack, comps = {}, {}, set(), [], []
    counter = 0
    for root in work_ids:
        if root in index:
            continue
        work = [(root, iter(succ.get(root, ())))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            v, it = work[-1]
            descended = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on_stack.add(w)
                    work.append((w, iter(succ.get(w, ()))))
                    descended = True
                    break
                if w in on_stack and index[w] < low[v]:
                    low[v] = index[w]
            if descended:
                continue
            work.pop()
            if work:
                u = work[-1][0]
                if low[v] < low[u]:
                    low[u] = low[v]
            if low[v] == index[v]:
                comp = []
                while True:
                    x = stack.pop()
                    on_stack.discard(x)
                    comp.append(x)
                    if x == v:
                        break
                if len(comp) > 1 or v in self_loops:
                    comps.append(comp)
    order = {tid: i for i, tid in enumerate(work_ids)}
    return sorted((sorted(c, key=lambda x: order.get(x, 0)) for c in comps),
                  key=lambda c: order.get(c[0], 0))


# ─────────────────────────────────────────────────────────────────────
# Per-check implementations
# Each returns (severity, value, threshold, message, details_dict); the
# details carry 'counts' (status, num, den, value), which dcma_14_assess
# lifts to per_check[id]['counts'].
# ─────────────────────────────────────────────────────────────────────

def _check_01_logic(work_tasks, incomplete, pred_map, succ_map, profile):
    """#1 Logic — incomplete ordinary activities and incomplete milestones
    with no logic relationship in (missing predecessor) or out (missing
    successor), each counted once; at most 5%.

    `pred_map` / `succ_map` hold LOGIC relationships only (D4: both ends in
    the scored project, neither end an LOE or WBS summary). A relationship to
    an LOE gives an activity no successor (2026-11-07, the written definition: it used
    to count, so an activity tied only to a hammock passed).

    Population: the DCMA metric family is scoped to incomplete work; this check
    used to run over every work task, completed ones included, which on an
    update well into a job diluted the percentage with historic work whose
    logic no longer drives anything.

    Milestone exemption by POSITION, not by task_type (D10, the network start
    and finish): a TT_Mile with no predecessor starting at or before the
    network start, and a TT_FinMile with no successor finishing at or after the
    network finish, are not findings. Exempting every milestone by type
    exempted milestones in the middle of the network that lead from nothing or
    to nothing — the dangling starts and ends this test exists to find.

    Both the missing-predecessor and the missing-successor counts are reported
    separately in the details; the graded value is the union.
    """
    threshold = profile['dcma_logic_max_missing_pct']
    incomplete = [t for t in incomplete if _is_work_task(t) and not _is_complete(t)]
    if not incomplete:
        # The same keys as a scored run, so a caller reading the details never
        # has to ask which branch produced them. An empty population is NOT
        # SCORED, never a vacuous pass (2026-11-07, the DCMA review).
        return INFO, None, threshold, (
            'Logic NOT SCORED: the schedule has no incomplete work tasks, so '
            'there is no remaining logic to measure.'
        ), {
            'missing_count': 0, 'denominator': 0,
            'missing_pred_count': 0, 'missing_pred_pct': 0.0,
            'missing_succ_count': 0, 'missing_succ_pct': 0.0,
            'missing_pred': [], 'missing_succ': [],
            'examples': [], 'assessed': False, 'counts': _ns_counts(),
        }
    # D10: the network starts at the earliest start of any ordinary or
    # milestone activity, complete included; it finishes at the latest finish
    # of the incomplete ones.
    starts = [d for d in (_task_start(t) for t in work_tasks if _is_work_task(t)) if d]
    finishes = [d for d in (_task_finish(t) for t in incomplete) if d]
    net_start = min(starts) if starts else None
    net_finish = max(finishes) if finishes else None

    missing_pred, missing_succ = [], []
    for t in incomplete:
        tid = t['task_id']
        ttype = t.get('task_type', '')
        code = t.get('task_code', tid)
        has_pred = bool(pred_map.get(tid))
        has_succ = bool(succ_map.get(tid))
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
    ok = _at_most_pct(len(missing), denom, threshold)
    sev = PASS if ok else WARN
    return sev, pct, threshold, (
        f'{len(missing)} of {denom} incomplete activities ({pct:.1f}%) missing '
        f'predecessor or successor — {len(missing_pred)} missing a predecessor '
        f'({pct_pred:.1f}%), {len(missing_succ)} missing a successor '
        f'({pct_succ:.1f}%) (threshold ≤ {threshold}%). A relationship to a '
        f'level of effort or WBS summary is not logic.'
    # Full lists — never truncate. CPP forensic-correctness rule.
    ), {'missing_count': len(missing), 'denominator': denom,
        'missing_pred_count': len(missing_pred), 'missing_pred_pct': pct_pred,
        'missing_succ_count': len(missing_succ), 'missing_succ_pct': pct_succ,
        'missing_pred': list(missing_pred), 'missing_succ': list(missing_succ),
        'examples': list(missing), 'assessed': True,
        'counts': _counts(STATUS_PASS if ok else STATUS_FAIL, len(missing), denom, pct)}


_LIVE_NS = ('the project has no live relationships to measure (D4: a logic '
            'relationship into incomplete work; a relationship between finished '
            'activities is history and is not graded)')


def _check_02_leads(preds_all, profile, task_map=None):
    """#2 Leads — live relationships (D4: both ends in the scored project,
    neither an LOE or WBS summary, the successor incomplete) with a lag below
    0. Passes with none.

    2026-11-07, the written definition: the population was every relationship in the
    project, so a lead into finished work (history) still failed the check.
    `preds_all` is the live set."""
    threshold = profile['dcma_leads_max_count']
    if not preds_all:
        return INFO, None, threshold, (
            f'Leads NOT SCORED: {_LIVE_NS}.'
        ), {'lead_count': 0, 'live_count': 0, 'assessed': False, 'examples': [],
            'counts': _ns_counts()}
    leads = [p for p in preds_all if _safe_float(p.get('lag_hr_cnt', '0'), 0.0) < 0]
    ok = len(leads) <= threshold
    sev = PASS if ok else BLOCK
    return sev, len(leads), threshold, (
        f'{len(leads)} of {len(preds_all)} live relationships carry a negative '
        f'lag (lead) (threshold ≤ {threshold}). Leads hide true duration and '
        'violate DCMA #2.'
    # Full list — never truncate. CPP forensic-correctness rule.
    ), {'lead_count': len(leads), 'live_count': len(preds_all), 'assessed': True,
        'examples': [_rel_label(p, task_map or {}) for p in leads],
        'counts': _counts(STATUS_PASS if ok else STATUS_FAIL, len(leads),
                          len(preds_all), len(leads))}


def _check_03_lags(preds_all, profile, task_map=None, cal_map=None):
    """#3 Lags — live relationships with a lag above 0; at most 5%.

    A lag over 44 working days on the successor's calendar is listed for
    information ('long_lags'); it decides nothing."""
    threshold = profile['dcma_lags_max_pct']
    if not preds_all:
        return INFO, None, threshold, (
            f'Lags NOT SCORED: {_LIVE_NS}.'
        ), {'lag_count': 0, 'live_count': 0, 'assessed': False, 'examples': [],
            'long_lags': [], 'counts': _ns_counts()}
    task_map = task_map or {}
    lagged = [p for p in preds_all if _safe_float(p.get('lag_hr_cnt', '0'), 0.0) > 0]
    long_lags = []
    for p in lagged:
        succ = task_map.get(p.get('task_id', ''), {})
        days = _hrs_to_days(_safe_float(p.get('lag_hr_cnt', '0'), 0.0), cal_map,
                            succ.get('clndr_id', ''))
        if days > LONG_LAG_INFO_DAYS:
            long_lags.append({'relationship': _rel_label(p, task_map),
                              'lag_working_days': days})
    pct = len(lagged) / len(preds_all) * 100.0
    ok = _at_most_pct(len(lagged), len(preds_all), threshold)
    sev = PASS if ok else WARN
    tail = (f' {len(long_lags)} of them run over {LONG_LAG_INFO_DAYS} working days '
            f'on the successor\'s calendar (listed for information).') if long_lags else ''
    return sev, pct, threshold, (
        f'{len(lagged)} of {len(preds_all)} live relationships ({pct:.1f}%) have '
        f'positive lag (threshold ≤ {threshold}%).' + tail
    # Full lists — never truncate. CPP forensic-correctness rule.
    ), {'lag_count': len(lagged), 'live_count': len(preds_all), 'assessed': True,
        'examples': [_rel_label(p, task_map) for p in lagged], 'long_lags': long_lags,
        'counts': _counts(STATUS_PASS if ok else STATUS_FAIL, len(lagged),
                          len(preds_all), pct)}


def _check_04_relationship_types(preds_all, profile, task_map=None):
    """#4 Relationship Types — at least 90% of the live relationships are
    Finish-to-Start. num = the FS count, den = the live relationships."""
    threshold = profile['dcma_fs_min_pct']
    if not preds_all:
        return INFO, None, threshold, (
            f'Relationship Types NOT SCORED: {_LIVE_NS}.'
        ), {'fs_count': 0, 'live_count': 0, 'assessed': False, 'non_fs': [],
            'counts': _ns_counts()}
    fs = sum(1 for p in preds_all if p.get('pred_type', '') == 'PR_FS')
    non_fs = [f"{_rel_label(p, task_map or {})} ({p.get('pred_type', '')})"
              for p in preds_all if p.get('pred_type', '') != 'PR_FS']
    pct = fs / len(preds_all) * 100.0
    ok = _at_least_pct(fs, len(preds_all), threshold)
    sev = PASS if ok else WARN
    return sev, pct, threshold, (
        f'{fs} of {len(preds_all)} live relationships ({pct:.1f}%) are FS '
        f'(threshold ≥ {threshold}%).'
    # Full list — never truncate. CPP forensic-correctness rule.
    ), {'fs_count': fs, 'live_count': len(preds_all), 'assessed': True,
        'non_fs': non_fs,
        'counts': _counts(STATUS_PASS if ok else STATUS_FAIL, fs, len(preds_all), pct)}


def _check_05_hard_constraints(work_tasks, profile):
    """#5 Hard Constraints — incomplete ordinary activities with a hard
    constraint, primary (cstr_type) or secondary (cstr_type2); at most 5%.

    Hard means the four types DCMA-EA PAM 200.1 s4.5 lists (DCMA_HARD_CONSTRAINTS).
    Until 2026-11-07 this read cp_validator's HARD_CONSTRAINTS and missed
    CS_MSOB / CS_MEOB. 2026-11-07, the written definition: the population is the
    incomplete ORDINARY activities (it was every work task, complete work and
    milestones included); a constrained incomplete milestone is listed for
    information ('constrained_milestones') and decides nothing.
    """
    threshold = profile['dcma_hard_constraints_max_pct']
    codes = ', '.join(sorted(DCMA_HARD_CONSTRAINTS))

    def _hard(t):
        return (t.get('cstr_type', '') in DCMA_HARD_CONSTRAINTS
                or t.get('cstr_type2', '') in DCMA_HARD_CONSTRAINTS)

    pop = [t for t in work_tasks if _is_ordinary(t) and not _is_complete(t)]
    milestones = [_code(t) for t in work_tasks
                  if _is_milestone(t) and not _is_complete(t) and _hard(t)]
    if not pop:
        return INFO, None, threshold, (
            'Hard Constraints NOT SCORED: the project has no incomplete ordinary '
            'activities to measure.'
        ), {'hard_count': 0, 'assessed': False, 'examples': [],
            'constrained_milestones': milestones,
            'codes_counted': sorted(DCMA_HARD_CONSTRAINTS), 'counts': _ns_counts()}
    hard = [_code(t) for t in pop if _hard(t)]
    pct = len(hard) / len(pop) * 100.0
    ok = _at_most_pct(len(hard), len(pop), threshold)
    sev = PASS if ok else WARN
    tail = (f' {len(milestones)} incomplete milestone(s) carry one too; they are '
            f'listed for information and not counted.') if milestones else ''
    return sev, pct, threshold, (
        f'{len(hard)} of {len(pop)} incomplete activities ({pct:.1f}%) have '
        f'hard constraints (threshold ≤ {threshold}%). Counted, primary or '
        f'secondary: {codes} (Must Start On, Must Finish On, Start No Later '
        f'Than, Finish No Later Than).' + tail
    # Full lists — never truncate. CPP forensic-correctness rule.
    ), {'hard_count': len(hard), 'assessed': True, 'examples': hard,
        'constrained_milestones': milestones,
        'codes_counted': sorted(DCMA_HARD_CONSTRAINTS),
        'counts': _counts(STATUS_PASS if ok else STATUS_FAIL, len(hard), len(pop), pct)}


def _check_06_high_float(incomplete, cal_map, profile):
    """#6 High Float — incomplete ordinary activities with a computed total
    float above 44 working days (D3: the activity's own calendar); at most 5%.
    Milestones are not in the population (2026-11-07, the written definition); a blank
    float is left out and counted."""
    max_days = profile['dcma_high_float_max_days']
    threshold = profile['dcma_high_float_max_pct']
    pop = [t for t in incomplete if _is_ordinary(t) and not _is_complete(t)]
    if not pop:
        return INFO, None, threshold, (
            'High Float NOT SCORED: the schedule has no incomplete activities '
            'to measure.'
        ), {'high_float_count': 0, 'max_days': max_days, 'unknown_float_count': 0,
            'assessed': False, 'examples': [], 'counts': _ns_counts()}
    # Activities P6 left with a blank total_float carry no answer to grade. They
    # are dropped from the population and disclosed, never coerced to 0.
    known = [t for t in pop if _float_hours(t) is not None]
    unknown = len(pop) - len(known)
    if not known:
        return INFO, None, threshold, (
            f'No computed total float on any of the {len(pop)} incomplete '
            f'activities — High Float NOT SCORED. Recalculate the schedule in '
            f'P6 and re-export; do not read this as a pass.'
        ), {'high_float_count': None, 'max_days': max_days,
            'unknown_float_count': unknown, 'assessed': False, 'examples': [],
            'counts': _ns_counts()}
    high = []
    for t in known:
        tf_days = _hrs_to_days(_float_hours(t), cal_map, t.get('clndr_id', ''))
        if tf_days > max_days:
            high.append(t.get('task_code', t['task_id']))
    pct = len(high) / len(known) * 100.0
    ok = _at_most_pct(len(high), len(known), threshold)
    sev = PASS if ok else WARN
    note = (f' {unknown} incomplete activities have no computed total float and '
            f'are excluded from the population.') if unknown else ''
    return sev, pct, threshold, (
        f'{len(high)} of {len(known)} incomplete activities with computed float '
        f'({pct:.1f}%) have total float > {max_days}d (threshold ≤ {threshold}%).'
        + note
    # Full list — never truncate. CPP forensic-correctness rule.
    ), {'high_float_count': len(high), 'max_days': max_days,
        'unknown_float_count': unknown, 'assessed': True,
        'examples': list(high),
        'counts': _counts(STATUS_PASS if ok else STATUS_FAIL, len(high), len(known), pct)}


def _check_07_negative_float(incomplete, cal_map, profile):
    """#7 Negative Float — incomplete ordinary activities with a computed
    total float below 0. Passes with none.

    Blank total_float is missing data, not zero: an activity with no computed
    float cannot be shown to be negative, so it is excluded and disclosed
    rather than counted as float-zero. Milestones are not in the population
    (2026-11-07, the written definition).
    """
    threshold = profile['dcma_negative_float_max_count']
    pop = [t for t in incomplete if _is_ordinary(t) and not _is_complete(t)]
    if not pop:
        return INFO, None, threshold, (
            'Negative Float NOT SCORED: the schedule has no incomplete '
            'activities to measure.'
        ), {'neg_float_count': 0, 'unknown_float_count': 0,
            'assessed': False, 'examples': [], 'counts': _ns_counts()}
    known = [t for t in pop if _float_hours(t) is not None]
    unknown = len(pop) - len(known)
    if not known:
        return INFO, None, threshold, (
            f'No computed total float on any of the {len(pop)} incomplete '
            f'activities — Negative Float NOT SCORED. Recalculate the schedule '
            f'in P6 and re-export; do not read this as a pass.'
        ), {'neg_float_count': None, 'unknown_float_count': unknown,
            'assessed': False, 'examples': [], 'counts': _ns_counts()}
    neg = [t.get('task_code', t['task_id']) for t in known if _float_hours(t) < 0]
    ok = len(neg) <= threshold
    sev = PASS if ok else BLOCK
    note = (f' {unknown} incomplete activities have no computed total float and '
            f'are excluded from the population.') if unknown else ''
    return sev, len(neg), threshold, (
        f'{len(neg)} of {len(known)} incomplete activities with computed float '
        f'have negative total float (threshold ≤ {threshold}). Any negative float '
        'means the schedule cannot finish on time as currently logicked.'
        + note
    # Full list — never truncate. CPP forensic-correctness rule.
    ), {'neg_float_count': len(neg), 'unknown_float_count': unknown,
        'assessed': True, 'examples': list(neg),
        'counts': _counts(STATUS_PASS if ok else STATUS_FAIL, len(neg), len(known), len(neg))}


def _check_08_high_duration(incomplete, cal_map, profile, baseline_basis=None):
    """#8 High Duration — incomplete ordinary activities whose duration is
    above 44 working days; at most 5%.

    2026-11-07, the written definition: the duration is the BASELINE's original duration
    of the same activity (target_drtn_hr_cnt on the baseline activity's
    calendar) when a baseline is supplied and the activity is in it (D8: the
    Activity ID trimmed, case ignored; an ID that appears more than once in
    either file is left out of the baseline basis and read on the current
    one), else the current original duration (target_drtn_hr_cnt). It used to
    be the remaining duration. The result says how many were read on each
    basis. The pamphlet's detail-planning-window restriction is not applied.

    `baseline_basis` is {'days': {normalised ID: working days}, 'ambiguous':
    set of normalised IDs} or None without a (usable) baseline.
    """
    max_days = profile['dcma_high_duration_max_days']
    threshold = profile['dcma_high_duration_max_pct']
    pop = [t for t in incomplete if _is_ordinary(t) and not _is_complete(t)]
    if not pop:
        return INFO, None, threshold, (
            'High Duration NOT SCORED: the schedule has no incomplete '
            'non-milestone activities to measure.'
        ), {'high_duration_count': 0, 'max_days': max_days, 'assessed': False,
            'examples': [], 'counts': _ns_counts()}
    bl_days = (baseline_basis or {}).get('days') or {}
    ambiguous = (baseline_basis or {}).get('ambiguous') or set()
    long_ones, on_baseline, on_current, left_out = [], 0, 0, []
    for t in pop:
        key = _norm_code(t.get('task_code', ''))
        if baseline_basis is not None and key and key in ambiguous:
            left_out.append(_code(t))
        if baseline_basis is not None and key and key not in ambiguous and key in bl_days:
            days, basis = bl_days[key], 'baseline'
            on_baseline += 1
        else:
            days = _hrs_to_days(_safe_float(t.get('target_drtn_hr_cnt', ''), 0.0),
                                cal_map, t.get('clndr_id', ''))
            basis = 'current'
            on_current += 1
        if days > max_days:
            long_ones.append({'activity': _code(t), 'working_days': days, 'basis': basis})
    denom = len(pop)
    pct = len(long_ones) / denom * 100.0
    ok = _at_most_pct(len(long_ones), denom, threshold)
    sev = PASS if ok else WARN
    basis_txt = (f' Durations read: {on_baseline} on the baseline\'s original '
                 f'duration, {on_current} on the current original duration.')
    if left_out:
        basis_txt += (f' {len(left_out)} carry an Activity ID that appears more than '
                      f'once in a file and were read on the current duration.')
    return sev, pct, threshold, (
        f'{len(long_ones)} of {denom} non-milestone activities ({pct:.1f}%) have '
        f'an original duration > {max_days}d (threshold ≤ {threshold}%).' + basis_txt
    # Full lists — never truncate. CPP forensic-correctness rule.
    ), {'high_duration_count': len(long_ones), 'max_days': max_days,
        'assessed': True, 'examples': [x['activity'] for x in long_ones],
        'long_activities': long_ones, 'baseline_basis_count': on_baseline,
        'current_basis_count': on_current, 'ambiguous_left_out': left_out,
        'counts': _counts(STATUS_PASS if ok else STATUS_FAIL, len(long_ones), denom, pct)}


def _check_09_invalid_dates(work_tasks, data_date_dt, profile, correction=None):
    """#9 Invalid Dates — ordinary activities and milestones, complete
    included, with an invalid date (DCMA-EA PAM 200.1 section 4.9). Passes
    with none.

    Compared by CALENDAR DAY (D5, 2026-11-07, the written definition; it was to the
    minute): an actual start or actual finish on a day after the data date's
    day; or, on incomplete work, a forecast before it: not started, an early
    start or early finish on a day before the data date's day; started, an
    early finish on a day before it. The forecast dates are the EARLY dates
    (section 4.11 names the forecast finish as the early finish). A date ON the
    status date's day is valid on both sides.

    Two corrections made 2026-09-21 against the implementation before: it
    never read an early date (it tested the PLANNED finish, which is what #11
    Missed Tasks measures), and it counted
    one issue per FIELD and called the total a number of activities. Issues
    are grouped by activity; the per-field list is kept in the details.

    An incomplete activity with no early date to read cannot be shown to be
    valid or invalid (real exports carry some). It is not counted and the
    message says how many there were. NOT SCORED with no data date, or when
    there is incomplete work but none of it carries an early date.

    `correction` is the data date correction record for the project assessed
    (data_date_correction.detect, 27 September 2026), or None. This check
    reports the file as filed, so the verdict and the count never change. The
    record only adds the checker sentence to the finding and, when a move is
    owed, the latest actual and the corrected date to the details.
    """
    threshold = profile['dcma_invalid_dates_max_count']
    if data_date_dt is None:
        return INFO, None, threshold, (
            'Invalid Dates NOT SCORED: no data date on the project, so there '
            'is nothing to compare the dates to.'
        ), {'issues': [], 'assessed': False, 'counts': _ns_counts()}
    pop = [t for t in work_tasks if _is_work_task(t)]
    incomplete = [t for t in pop if not _is_complete(t)]
    if not pop:
        return INFO, None, threshold, (
            'Invalid Dates NOT SCORED: the project has no activities to measure.'
        ), {'issues': [], 'assessed': False, 'counts': _ns_counts()}
    if incomplete and not any(_parse_date(t.get('early_start_date', ''))
                              or _parse_date(t.get('early_end_date', ''))
                              for t in incomplete):
        return INFO, None, threshold, (
            f'Invalid Dates NOT SCORED: none of the {len(incomplete)} incomplete '
            f'activities carries an early start or early finish, so the forecasts '
            f'cannot be read. Recalculate the schedule in P6 and re-export.'
        ), {'issues': [], 'assessed': False, 'counts': _ns_counts()}
    dd = data_date_dt.date()
    issues = []
    invalid, forecast_bad, actual_bad, unread = [], [], [], []
    for t in pop:
        tc = t.get('task_code', t['task_id'])
        act_start = _parse_date(t.get('act_start_date', ''))
        act_end = _parse_date(t.get('act_end_date', ''))
        # Actual dates: never on a day after the status date's day.
        late_actuals = [f'{tc}:{field}>{dd}'
                        for field, v in (('act_start_date', act_start),
                                         ('act_end_date', act_end))
                        if v and v.date() > dd]
        stale_forecasts, no_forecast = [], False
        if not _is_complete(t):
            started = act_start is not None or t.get('status_code', '') == ACTIVE_STATUS
            fields = ('early_end_date',) if started else ('early_start_date', 'early_end_date')
            for field in fields:
                v = _parse_date(t.get(field, ''))
                if v is None:
                    # No forecast to read is missing data, not a valid date.
                    no_forecast = True
                elif v.date() < dd:
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
    ok = len(invalid) <= threshold
    sev = PASS if ok else BLOCK
    message = (
        f'{len(invalid)} of {len(pop)} activities with invalid dates (threshold ≤ '
        f'{threshold}): '
        f'{len(forecast_bad)} with a forecast (early) start or finish on a day '
        f'before the status date {dd}, {len(actual_bad)} with an actual start or '
        f'finish on a day after it.'
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
               'unread_forecast': list(unread), 'assessed': True,
               'counts': _counts(STATUS_PASS if ok else STATUS_FAIL, len(invalid),
                                 len(pop), len(invalid))}
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


def _check_10_resources(work_tasks, rsrc_assignments, profile, cal_map=None):
    """#10 Resources — incomplete ordinary activities with an original
    duration of at least 1 working day; each must carry a resource assignment
    with hours or cost (target_qty, remain_qty, target_cost or remain_cost
    above 0). Passes only when every one does (100%), on every profile.

    2026-11-07, the written definition: the commercial and mining profiles disabled the
    check (threshold 0: "not required by this profile") and nuclear passed it
    at 80% of every work task with any TASKRSRC row. NOT SCORED now only when
    the scored project carries no resource assignments at all (or the
    population is empty): a file that was never resource-loaded measures
    nothing. `rsrc_assignments` is the scored project's TASKRSRC rows.

    num = the resourced activities, den = the population.
    """
    threshold = DCMA_RESOURCES_MIN_PCT
    if not rsrc_assignments:
        return INFO, None, threshold, (
            'Resources NOT SCORED: the project carries no resource assignments '
            'at all, so there is no resource loading to measure.'
        ), {'loaded_count': 0, 'assessed': False, 'not_resourced': [],
            'counts': _ns_counts()}
    # An activity with a blank original duration is left out (definition #10).
    pop = [t for t in work_tasks
           if _is_ordinary(t) and not _is_complete(t)
           and str(t.get('target_drtn_hr_cnt', '') or '').strip()
           and _hrs_to_days(_safe_float(t.get('target_drtn_hr_cnt', ''), 0.0),
                            cal_map, t.get('clndr_id', '')) >= DCMA_RESOURCES_MIN_DURATION_DAYS]
    if not pop:
        return INFO, None, threshold, (
            'Resources NOT SCORED: the project has no incomplete activities of '
            'at least one working day to measure.'
        ), {'loaded_count': 0, 'assessed': False, 'not_resourced': [],
            'counts': _ns_counts()}
    loaded_ids = {r.get('task_id', '') for r in rsrc_assignments
                  if any(_safe_float(r.get(f, ''), 0.0) > 0 for f in RESOURCE_LOAD_FIELDS)}
    hits = [t for t in pop if t['task_id'] in loaded_ids]
    missing = [_code(t) for t in pop if t['task_id'] not in loaded_ids]
    pct = len(hits) / len(pop) * 100.0
    ok = _at_least_pct(len(hits), len(pop), threshold)
    sev = PASS if ok else WARN
    return sev, pct, threshold, (
        f'{len(hits)} of {len(pop)} incomplete activities of at least one working '
        f'day ({pct:.1f}%) carry a resource assignment with hours or cost '
        f'(threshold {threshold:.0f}%).'
    # Full list — never truncate. CPP forensic-correctness rule.
    ), {'loaded_count': len(hits), 'assessed': True, 'not_resourced': missing,
        'counts': _counts(STATUS_PASS if ok else STATUS_FAIL, len(hits), len(pop), pct)}


def _baseline_project_tasks(baseline_data, project, work_tasks):
    """D9: the baseline TASK rows that belong to the assessed project, the
    baseline project they came from, and how that project was matched.

    A baseline file can hold several projects, exactly as a current one can.
    The PROJECT is matched first and activity codes second: same proj_id (an
    earlier export of the same project), else same proj_short_name, else the
    baseline project sharing the most Activity IDs (D8: trimmed, case ignored)
    with the assessed one. Until 2026-09-21 checks 11 and 14 read EVERY
    baseline TASK row, so an unrelated project's rows joined the BEI
    denominator.

    A baseline file with one project is read whole, as it always was. Where
    no baseline project shares a single Activity ID, nothing is read and every
    baseline-dependent check is NOT SCORED: a figure built on an unrelated
    project's rows is worse than none.

    Returns (rows, baseline_proj_id, how): every TASK row of the chosen project
    (all types; callers select); ([], '', reason) when none is usable; (None,
    '', '') with no baseline.
    """
    if baseline_data is None:
        return None, '', ''
    rows = list(get_table(baseline_data, 'TASK'))
    projects = get_table(baseline_data, 'PROJECT')
    if len(projects) <= 1:
        return (rows, projects[0].get('proj_id', '') if projects else '',
                'only project in the baseline file')
    pid = (project or {}).get('proj_id', '')
    short = (project or {}).get('proj_short_name', '')
    # Ties (two projects with the same short name, or sharing equally many
    # Activity IDs) are broken as D0 breaks them: the latest data date, then
    # the most TASK rows, then file order (2026-11-07, the written definition; ties went
    # to the first in the file).
    d0 = _d0_rank_key(rows)
    same_short = [p for p in projects
                  if short and p.get('proj_short_name', '') == short]
    if pid and any(p.get('proj_id', '') == pid for p in projects):
        chosen, how = pid, 'same proj_id'
    elif same_short:
        chosen = max(same_short, key=d0).get('proj_id', '')
        how = 'same short name'
    else:
        codes = {_norm_code(t.get('task_code', '')) for t in work_tasks} - {''}
        shared = {}
        for t in rows:
            if _is_work_task(t) and _norm_code(t.get('task_code', '')) in codes:
                shared.setdefault(t.get('proj_id', ''), set()).add(
                    _norm_code(t.get('task_code', '')))
        if not shared:
            return [], '', ('no baseline project shares an Activity ID with '
                            'the assessed project')
        chosen = max(projects, key=lambda p: (len(shared.get(p.get('proj_id', ''), ())),)
                     + d0(p)).get('proj_id', '')
        how = 'most shared activity codes'
    return [t for t in rows if t.get('proj_id', '') == chosen], chosen, how


def _ambiguous_ids(*row_sets):
    """D8: the normalised Activity IDs that appear more than once in any one
    of the given row sets: the scored project's rows and the chosen baseline
    project's rows, never the rest of either file."""
    out = set()
    for rows in row_sets:
        seen = set()
        for t in rows or ():
            key = _norm_code(t.get('task_code', ''))
            if not key:
                continue
            if key in seen:
                out.add(key)
            seen.add(key)
    return out


def _check_11_missed_tasks(work_tasks, baseline_tasks, data_date_dt, profile,
                           ambiguous=frozenset()):
    """#11 Missed Tasks — BASELINE ordinary activities due by the data date
    that did not finish by their baseline finish; at most 5%.

    Due (D5): a baseline finish (D12: target_end_date, else early_end_date)
    at or before the data date, to the minute (a baseline finish later on the
    data date itself is not yet due). Each is matched to the current schedule by Activity ID (D8: trimmed,
    case ignored). A due activity is missed if it is no longer in the current
    schedule (deleted or renumbered), not complete, or complete with an actual
    finish on a DAY after its baseline finish's day. Complete with no actual
    finish: lateness unknown, out of both counts.

    2026-11-07, the written definition: ordinary activities only (milestones were in);
    lateness by calendar day (it was to the minute); an Activity ID that
    appears more than once in either file is ambiguous and left out of both
    counts, and the number left out is disclosed.

    NOT SCORED with no baseline (P6 rewrites an activity's planned finish as
    the schedule is updated, so the file's own planned finish cannot show a
    missed baseline finish), no data date, nothing due, or fewer than
    MISSED_TASKS_MIN_MATCH_PCT (80%) of the due activities matching the
    current schedule (the baseline looks renumbered).

    `baseline_tasks` is the matching baseline project's rows (see
    _baseline_project_tasks), or None when no baseline was supplied.
    num = missed, den = due less those whose lateness is unknown.
    """
    threshold = profile['dcma_missed_tasks_max_pct']
    if data_date_dt is None or not work_tasks:
        return INFO, None, threshold, (
            'No data date or no work tasks — Missed Tasks NOT SCORED.'
        ), {'missed_count': None, 'assessed': False, 'counts': _ns_counts()}

    if baseline_tasks is None:
        return INFO, None, threshold, (
            'Missed Tasks NOT SCORED: no baseline was supplied. P6 rewrites an '
            "activity's planned finish as the schedule is updated, so the file's "
            'own planned finish cannot show a missed baseline finish. Supply the '
            'baseline XER to assess #11.'
        ), {'missed_count': None, 'assessed': False,
            'basis': 'no baseline supplied', 'counts': _ns_counts()}

    basis = 'baseline finish'
    due, left_out = {}, []
    for bt in baseline_tasks:
        if not _is_ordinary(bt):
            continue
        te = _baseline_finish(bt)          # D12: planned finish, else early
        if te is None or te > data_date_dt:
            continue
        key = _norm_code(bt.get('task_code', ''))
        if not key:
            continue
        if key in ambiguous:
            left_out.append(_code(bt))
            continue
        due[key] = (bt, te)
    current = {}
    for t in work_tasks:
        key = _norm_code(t.get('task_code', ''))
        if key and key not in ambiguous:
            current.setdefault(key, t)
    matched = [k for k in due if k in current]
    not_in_current = [_code(due[k][0]) for k in due if k not in current]
    match_pct = (len(matched) / len(due) * 100.0) if due else None
    counts = {'due_count': len(due), 'matched_count': len(matched),
              'not_in_current_count': len(not_in_current),
              # Full lists — never truncate. CPP forensic-correctness rule.
              'not_in_current': list(not_in_current), 'match_pct': match_pct,
              'ambiguous_left_out_count': len(left_out),
              'ambiguous_left_out': list(left_out)}
    amb_txt = (f' {len(left_out)} due baseline activit'
               f'{"y carries" if len(left_out) == 1 else "ies carry"} an Activity '
               f'ID that appears more than once in a file and '
               f'{"is" if len(left_out) == 1 else "are"} left out of both counts.'
               ) if left_out else ''

    if not due:
        return INFO, None, threshold, (
            'Missed Tasks NOT SCORED: no baseline activity has a baseline '
            'finish on or before the status date, so nothing was due.' + amb_txt
        ), {'missed_count': 0, 'due_by_dd': 0, 'assessed': False,
            'basis': basis, 'counts': _ns_counts(), **counts}

    if not _at_least_pct(len(matched), len(due), MISSED_TASKS_MIN_MATCH_PCT):
        return INFO, None, threshold, (
            f'Missed Tasks NOT SCORED: only {len(matched)} of {len(due)} '
            f'baseline activities due by the status date ({match_pct:.1f}%) '
            f'match a current activity by activity ID, below the '
            f'{MISSED_TASKS_MIN_MATCH_PCT:.0f}% needed. The baseline looks '
            f'renumbered, and a figure would be built on the IDs, not the work.'
            + amb_txt
        ), {'missed_count': None, 'due_by_dd': len(due), 'assessed': False,
            'basis': basis, 'counts': _ns_counts(), **counts}

    still_open, late_finish, undetermined = [], [], []
    for key in matched:
        t = current[key]
        bt, due_dt = due[key]
        code = _code(bt)
        if not _is_complete(t):
            still_open.append(code)
            continue
        act_end = _parse_date(t.get('act_end_date', ''))
        if act_end is None:
            # Complete but no actual finish recorded — lateness cannot be
            # established from the file. Out of both counts, disclosed.
            undetermined.append(code)
        elif act_end.date() > due_dt.date():
            late_finish.append(code)
    missed = sorted(set(still_open) | set(late_finish) | set(not_in_current))
    scored_due = len(due) - len(undetermined)
    if scored_due <= 0:
        return INFO, None, threshold, (
            'Missed Tasks NOT SCORED: every due baseline activity is complete '
            'with no actual finish date, so lateness cannot be established.'
        ), {'missed_count': None, 'due_by_dd': len(due), 'assessed': False,
            'basis': basis, 'undetermined': list(undetermined),
            'counts': _ns_counts(), **counts}
    pct = len(missed) / scored_due * 100.0
    ok = _at_most_pct(len(missed), scored_due, threshold)
    sev = PASS if ok else WARN
    tail = (f' {len(undetermined)} complete activities carry no actual finish '
            f'date, so lateness could not be established for them.'
            ) if undetermined else ''
    return sev, pct, threshold, (
        f'{len(missed)} of {scored_due} baseline activities due by the status date '
        f'({pct:.1f}%) did not finish by their baseline finish — '
        f'{len(still_open)} still open, {len(late_finish)} finished late, '
        f'{len(not_in_current)} no longer in the current schedule (deleted or '
        f'renumbered) (threshold ≤ {threshold}%). {len(matched)} of {len(due)} '
        f'({match_pct:.1f}%) matched a current activity by activity ID.'
        + tail + amb_txt
    # Full lists — never truncate. CPP forensic-correctness rule.
    ), {'missed_count': len(missed), 'due_by_dd': len(due),
        'still_open_count': len(still_open), 'late_finish_count': len(late_finish),
        'undetermined_count': len(undetermined), 'assessed': True, 'basis': basis,
        'still_open': list(still_open), 'late_finish': list(late_finish),
        'undetermined': list(undetermined), 'missed': list(missed),
        'counts': _counts(STATUS_PASS if ok else STATUS_FAIL, len(missed), scored_due, pct),
        **counts}


def _check_12_critical_path_test(work_tasks, pred_map, profile, cycles=None):
    """#12 Critical Path Test — the large-delay perturbation test.

    The test inserts a large delay (commonly 600 working days; that figure is
    common practice, not one the published pamphlet states) into a
    remaining-duration activity on the critical path and confirms the project
    completion date moves out by a corresponding amount. Performing it requires
    a CPM recalculation (phase 3), which this module does not do, so it is NOT
    claimed as a pass here.

    Until then it is decided only where the answer is certain:

    • FAIL on a logic cycle (2026-11-07, the written definition). `cycles` lists the
      activity groups that close a loop in the logic network (D4); a network
      with a loop has no forward pass and no completion date to move.
    • FAIL on a completion activity (D11) pinned by CS_MANDSTART / CS_MANDFIN
      (primary or secondary): no inserted delay can push it.

    Start On / Finish On (CS_MSO / CS_MEO) are NOT that case: P6 can delay the
    early date past a Start On / Finish On one and the lateness shows as
    negative float, which DCMA-EA PAM 200.1 section 4.12 calls a pass
    (measured on real exports: P6 stores Finish On and Start On activities
    later than their constraint date, and never a mandatory one).

    A completion activity with NO PREDECESSOR is NOT SCORED with
    'no_predecessor': True in the details (2026-11-07, the DCMA review): the
    missing link is #1 Logic's finding. Anything else is NOT SCORED (INFO) and
    is excluded from the /14 denominator. It must never be cited as a formal
    DCMA #12 pass.
    """
    cycles = cycles or []
    if not work_tasks:
        return INFO, None, None, (
            'No work tasks — Critical Path Test NOT SCORED.'
        ), {'assessed': False, 'logic_cycles': [], 'counts': _ns_counts()}
    finish_task, finish_dt = _completion_activity(work_tasks)
    by_id = {t['task_id']: t for t in work_tasks}
    cycle_codes = [[_code(by_id[i]) if i in by_id else i for i in c] for c in cycles]
    det = {'logic_cycles': cycle_codes, 'assessed': True}
    reasons = []
    if cycle_codes:
        listed = '; '.join(', '.join(c) for c in cycle_codes)
        reasons.append(
            f'the logic network carries {len(cycle_codes)} logic cycle'
            f'{"s" if len(cycle_codes) != 1 else ""} (activities that lead back to '
            f'themselves: {listed}), so it has no '
            f'forward pass and no completion date for an inserted delay to move')
    if finish_task is not None:
        code = finish_task.get('task_code', finish_task['task_id'])
        cstrs = (finish_task.get('cstr_type', ''), finish_task.get('cstr_type2', ''))
        pinned = [c for c in cstrs if c in DCMA_MANDATORY_CONSTRAINTS]
        soft = [c for c in cstrs if c in HARD_DATE]
        det.update({'finish_activity': code, 'finish_date': str(finish_dt),
                    'finish_constraints': pinned, 'finish_soft_constraints': soft})
        if pinned:
            reasons.append(
                f'the project finish activity {code} is pinned by '
                f'{"/".join(pinned)}, so inserting a large delay upstream '
                f'(commonly 600 working days) cannot move the completion date')
    if reasons:
        return BLOCK, None, None, (
            'Critical Path Test FAILS: ' + '; and '.join(reasons) + '. The network '
            'cannot demonstrate a live critical path through to completion.'
        ), dict(det, counts=_counts(STATUS_FAIL))
    det['assessed'] = False
    det['counts'] = _ns_counts()
    if finish_task is None:
        return INFO, None, None, (
            'No dated activity — the project finish could not be identified, so '
            'the Critical Path Test was NOT SCORED.'
        ), det
    if not pred_map.get(finish_task['task_id']):
        det['no_predecessor'] = True
        return INFO, None, None, (
            f'Critical Path Test NOT SCORED. The project finish activity {code} '
            f'has no predecessor; that is reported under #1 Logic. An unlinked '
            f'finish does not by itself show that a delay inserted on the '
            f'critical path would not move completion; confirming the test '
            f'requires inserting a large delay, commonly 600 working days, and a '
            f'CPM recalculation, which this module does not perform.'
        ), det
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
        f'Critical Path Test NOT SCORED. The project finish activity {code} is '
        f'logic-driven and {carries}; the logic network carries no cycle. '
        f'Confirming the pass requires inserting a '
        f'large delay, commonly 600 working days, and a CPM recalculation, which '
        f'this module does not perform. '
        f'Do NOT cite this as a formal DCMA #12 pass in a contract claim or '
        f'forensic submission.'
    ), det


def _check_13_cpli(work_tasks, cal_map, data_date_dt, profile, project=None,
                   baseline_tasks=None):
    """#13 Critical Path Length Index.

    CPLI = (CP length + float) / CP length, read on the completion activity
    (D11: latest early finish, else planned finish; a finish milestone
    preferred on a tie), where:
      • CP length = the WORKING TIME from the data date to its early finish on
        the project calendar, in working days: working hours divided by the
        calendar's hours per day (2026-11-07, the written definition; it counted whole
        calendar days, so a data date at 08:00 and a finish at the close of the
        fifth working day read 4, not 5)
      • float = the float to the CONTRACT finish (2026-11-07, the DCMA review):
          – with a baseline: the working time from that early finish to the
            baseline finish (D12: its planned finish, else its early finish)
            of the SAME activity (D8 Activity ID) in the matched
            baseline project, measured the same way, positive when the forecast
            is earlier. If that ID is not in the baseline, the baseline
            project's own completion activity is used and the message says so.
            basis='baseline'.
          – without a baseline, only when the file carries a deadline
            (PROJECT.plan_end_date, P6 'Must Finish By', or a CS_MEO / CS_MEOB /
            CS_MANDFIN constraint on the completion activity) or that float is
            not zero: the P6 total float of the completion activity (D3: its own
            calendar). basis='p6_float_to_deadline'.
          – otherwise NOT SCORED: with no deadline P6 computes the finish
            activity's float against its own early finish, so it is 0 by
            construction and CPLI would read 1.000.

    The float term used to be the MINIMUM float over the whole critical set,
    which capped the index at 1.0 and, on five real exports, produced a
    negative index. Reading the project finish only restores the published
    behaviour: above 1.0 when the project is ahead, below when it is behind.

    `project` is the PROJECT-table row (its calendar, and plan_end_date).
    `baseline_tasks` is the matched baseline project's rows (see
    _baseline_project_tasks), or None.
    """
    threshold = profile['dcma_cpli_min']

    def _ns(msg, **extra):
        return INFO, None, threshold, msg, dict(
            {'cpli': None, 'assessed': False, 'counts': _ns_counts()}, **extra)

    if not work_tasks or data_date_dt is None:
        return _ns('CPLI NOT SCORED: no activities or no data date — CPLI not computable.')

    finish_task, latest_ef = _completion_activity(work_tasks)
    if latest_ef is None or latest_ef <= data_date_dt:
        return _ns('CPLI NOT SCORED: the completion activity finishes at or '
                   'before the data date (or carries no finish), so there is no '
                   'critical path length — CPLI not computable.')

    cp_cal, cp_cal_how = _project_calendar(project, cal_map)
    cp_length_days = _working_days_between(data_date_dt, latest_ef, cp_cal)
    # None when the span is unbounded/unparseable (e.g. a sentinel 9999 finish
    # > ~100yr from the data date): not computable rather than a crash.
    if cp_length_days is None or cp_length_days <= 0:
        return _ns('CPLI NOT SCORED: CP length ≤ 0 or not computable '
                   '(unbounded/sentinel finish) — CPLI not computable.')

    fin_code = (finish_task or {}).get('task_code', '')

    def _graded(tf_days, basis, text, **extra):
        cpli = (cp_length_days + tf_days) / cp_length_days
        ok = Fraction(cp_length_days + tf_days) >= Fraction(str(threshold)) * Fraction(cp_length_days)
        sev = PASS if ok else BLOCK
        return sev, cpli, threshold, (
            f'CPLI = {cpli:.3f} (threshold ≥ {threshold}). CP length = '
            f'{cp_length_days:.1f}d (working time on the {cp_cal_how}) from the '
            f'status date to the forecast finish of {fin_code} ({latest_ef.date()}); '
            + text
        ), dict({'cpli': cpli, 'basis': basis, 'assessed': True,
                 'forecast_finish': str(latest_ef), 'finish_activity': fin_code,
                 'cp_length_days': cp_length_days, 'tf_days': tf_days,
                 'counts': _counts(STATUS_PASS if ok else STATUS_FAIL, value=cpli)},
                **extra)

    if baseline_tasks is not None:
        bl_work = [bt for bt in baseline_tasks if _is_work_task(bt)]

        _bl_finish = _baseline_finish    # D12: planned finish, else early
        key = _norm_code(fin_code)
        contract_task = next((bt for bt in bl_work
                              if key and _norm_code(bt.get('task_code', '')) == key
                              and _bl_finish(bt) is not None), None)
        note = ''
        if contract_task is None:
            contract_task, _ = _completion_activity(bl_work)
            if contract_task is not None:
                note = (f' The finish activity {fin_code} is not in the '
                        f'baseline, so the baseline project\'s own completion '
                        f'activity {contract_task.get("task_code", "")} is used.')
        contract_dt = _bl_finish(contract_task) if contract_task else None
        if contract_dt is None:
            return _ns('CPLI NOT SCORED: a baseline was supplied but no baseline '
                       'finish could be found for the project finish activity or the '
                       'baseline completion activity.',
                       basis='baseline', cp_length_days=cp_length_days,
                       finish_activity=fin_code)
        tf_days = _working_days_between(latest_ef, contract_dt, cp_cal)
        if tf_days is None:
            return _ns('CPLI NOT SCORED: the working time between the forecast '
                       'finish and the baseline finish could not be counted.',
                       basis='baseline', cp_length_days=cp_length_days,
                       finish_activity=fin_code)
        con_code = contract_task.get('task_code', '')
        return _graded(tf_days, 'baseline', (
            f'float to the baseline finish of {con_code} ({contract_dt.date()}) = '
            f'{tf_days:+.1f}d.' + note),
            contract_finish=str(contract_dt), contract_activity=con_code)

    # No baseline: the P6 float of the finish activity means something only
    # against a deadline in the file.
    must_finish_by = str((project or {}).get('plan_end_date', '') or '').strip()
    fin_cstrs = [c for c in ((finish_task or {}).get('cstr_type', ''),
                             (finish_task or {}).get('cstr_type2', ''))
                 if c in CPLI_DEADLINE_CONSTRAINTS]
    tf_hrs = _float_hours(finish_task) if finish_task else None
    # With no deadline in the file P6 measures the finish activity's float
    # against its own early finish, so it is 0 and CPLI would read 1.000 by
    # construction: NOT SCORED. A NON-ZERO float means P6 measured it against
    # some date even where the file names none (real exports with no Must
    # Finish By carry negative float on the finish activity), so it is used
    # and the basis says so.
    if not must_finish_by and not fin_cstrs and (tf_hrs is None or tf_hrs == 0):
        return _ns('CPLI NOT SCORED: no baseline and no deadline in the file, so '
                   'the float to completion is 0 by construction and CPLI would '
                   'read 1.000. Supply the baseline XER, or a Must Finish By date '
                   'in P6.', basis=None, cp_length_days=cp_length_days,
                   finish_activity=fin_code)
    if tf_hrs is None:
        return _ns('CPLI NOT SCORED: the project finish activity carries no '
                   'computed total float — CPLI not computable. Recalculate the '
                   'schedule in P6 and re-export.', cp_length_days=cp_length_days)
    tf_days = _hrs_to_days(tf_hrs, cal_map, (finish_task or {}).get('clndr_id', ''))
    if must_finish_by:
        date_must_finish = str(must_finish_by)
        deadline = f'Must Finish By {date_must_finish[:10]}'
    elif fin_cstrs:
        deadline = f'the {"/".join(fin_cstrs)} constraint on {fin_code}'
    else:
        deadline = ('the date P6 measured it against (the file names no Must '
                    'Finish By or finish constraint, but the float is not zero)')
    return _graded(tf_days, 'p6_float_to_deadline', (
        f'total float of the project finish activity {fin_code} = {tf_days:.1f}d '
        f'(no baseline; the P6 float is read against {deadline}).'))


# ─────────────────────────────────────────────────────────────────────
# #14 BEI — Baseline Execution Index
# ─────────────────────────────────────────────────────────────────────

def _check_14_bei(work_tasks, baseline_tasks, data_date_dt, profile,
                  ambiguous=frozenset()):
    """#14 BEI = current ordinary activities complete as of the data date /
    baseline ordinary activities due by the data date; at least 0.95.

    Due (D5): a baseline finish at or before the data date to the minute,
    including activities no longer in the current schedule. Complete as of the
    data date (D5): complete, and its actual finish (if any) on or before the
    data date's day. Both populations are ONE project's (D0, D9).

    The NUMERATOR IS UNRESTRICTED — every current ordinary activity complete
    as of the status date counts, not only those the baseline had due by then.
    That is why BEI can exceed 1.0 when work is pulled ahead; a numerator
    restricted to the due activities caps it at 1.0 and understates it.

    2026-11-07, the written definition: ordinary activities only in both counts
    (milestones were in); an Activity ID that appears more than once in either
    file is ambiguous and is left out of both counts (D8), disclosed; the
    actual finish is compared by calendar day.

    num = complete as of the data date, den = due baseline activities.
    """
    threshold = profile['bei_min']
    if baseline_tasks is None:
        return INFO, None, threshold, (
            'BEI NOT SCORED: no baseline provided — BEI cannot be computed.'
        ), {'bei': None, 'assessed': False, 'counts': _ns_counts()}
    if data_date_dt is None:
        return INFO, None, threshold, (
            'BEI NOT SCORED: no data date — BEI cannot be computed.'
        ), {'bei': None, 'assessed': False, 'counts': _ns_counts()}

    due, due_left_out = [], []
    for bt in baseline_tasks:
        if not _is_ordinary(bt):
            continue
        te = _baseline_finish(bt)          # D12: planned finish, else early
        if te is None or te > data_date_dt:
            continue
        if _norm_code(bt.get('task_code', '')) in ambiguous:
            due_left_out.append(_code(bt))
            continue
        due.append(bt)
    if not due:
        return INFO, None, threshold, (
            'BEI NOT SCORED: no activities baselined to complete by the data '
            'date — BEI not computable.'
        ), {'bei': None, 'baselined_due': 0, 'assessed': False, 'counts': _ns_counts()}

    dd = data_date_dt.date()
    completed, done_left_out = [], []
    for ct in work_tasks:
        if not _is_ordinary(ct) or not _is_complete(ct):
            continue
        ae = _parse_date(ct.get('act_end_date', ''))
        if ae is not None and ae.date() > dd:
            # A future actual (#9) is not complete as of the status date.
            continue
        if _norm_code(ct.get('task_code', '')) in ambiguous:
            done_left_out.append(_code(ct))
            continue
        completed.append(_code(ct))

    bei = len(completed) / len(due)
    ok = Fraction(len(completed)) >= Fraction(str(threshold)) * len(due)
    sev = PASS if ok else WARN
    left_out = len(due_left_out) + len(done_left_out)
    tail = (f' {left_out} activit{"y carries" if left_out == 1 else "ies carry"} an '
            f'Activity ID that appears more than once in a file and '
            f'{"is" if left_out == 1 else "are"} left out of both counts.'
            ) if left_out else ''
    return sev, bei, threshold, (
        f'BEI = {bei:.3f} (threshold ≥ {threshold}). {len(completed)} activities are '
        f'complete as of the status date against {len(due)} with a baseline '
        f'finish on or before it.' + tail
    # Full lists — never truncate. CPP forensic-correctness rule.
    ), {'bei': bei, 'completed': len(completed), 'baselined_due': len(due),
        'assessed': True, 'completed_activities': completed,
        'due_activities': [_code(bt) for bt in due],
        'ambiguous_left_out': due_left_out + done_left_out,
        'counts': _counts(STATUS_PASS if ok else STATUS_FAIL, len(completed), len(due), bei)}


def _profile_threshold_note(check_no, prof, profile_key):
    """A result graded on a profile whose threshold differs from the
    definition's names the profile and says the threshold is CPP's, derived
    from the DCMA check. Returns (message suffix, details block) or ('', None)."""
    pairs = DEFINITION_THRESHOLDS.get(check_no) or ()
    differs = [(key, prof.get(key), dcma) for key, dcma in pairs
               if prof.get(key) is not None and float(prof.get(key)) != float(dcma)]
    if not differs:
        return '', None
    name = prof.get('name', profile_key)
    cpp = ', '.join(f'{prof.get(k)}' for k, _, _ in differs)
    dcma = ', '.join(f'{d}' for _, _, d in differs)
    return (f' Graded on the {name} profile ({profile_key}): the threshold '
            f'({cpp}) is CPP\'s, derived from DCMA check #{check_no} ({dcma}).'), {
        'profile': profile_key, 'profile_name': name,
        'cpp_thresholds': {k: v for k, v, _ in differs},
        'dcma_thresholds': {k: d for k, _, d in differs}}


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
        baseline_data: optional parsed XER baseline (#8's baseline basis,
            #11, #13 and #14).
        proj_id: the PROJECT.proj_id to assess. A caller that has already
            selected a project passes it so that one selection runs through
            every check, narrative and figure — cp_validator selects by TASK-row
            count or by an explicit index, and used to hand the whole file over,
            so the embedded block could describe a different project from the
            report's own title and population (the two rules disagree on real
            multi-project exports). Left out, the
            latest-data-date rule below picks, as it always did. An id the file
            does not carry raises ValueError rather than assessing nothing.

    Returns:
        dict: {
            'profile':                str,
            'proj_id':                str — the project assessed,
            'project_name':           str — its PROJECT.proj_short_name,
            'data_date':              str — its PROJECT.last_recalc_date,
            'projects_in_file':       int — PROJECT rows in the file,
            'project_selection':      str — which project was scored and why
                                      (D0),
            'baseline_proj_id':       str — the baseline project read for
                                      checks 8, 11, 13 and 14 ('' when none),
            'baseline_project_match': str — how it was matched (D9),
            'baseline_used':          bool — False when no baseline was
                                      supplied or none of its projects could
                                      be used,
            'definition_version':     int — the written definition's version,
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
            'per_check':              {check_id: {severity, value, threshold,
                                      message, details, counts}}; counts is
                                      {status: PASS|FAIL|NOT SCORED, num, den,
                                      value} as the parity fixtures define them,
            'calendar_resolution':    xer_parser.calendar_resolution_block for
                                      the activities assessed: blank calendar
                                      ids resolved onto the project or default
                                      calendar, and any with no usable calendar
                                      (those also raise DCMA-Ext-TaskCalendar),
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
    # without a task calendar. Until 2026-09-26 the blank id reached
    # _hrs_to_days, which reads it as a flat 8 h/day, so on a 10 h/day project
    # calendar the same schedule scored 8/11 with blank ids and 10/11 with
    # explicit ones (High Float #6 and High Duration #8 counted 400 h as 50
    # working days, not 40; the CPLI float #13 is read the same way). Resolved
    # ONCE here, as cp_validator has done since 2026-09-18. The parsed data is
    # not modified; result['calendar_resolution'] lists what resolved.
    task_cals = resolve_task_calendars(data)
    tasks_all = with_resolved_calendars(get_table(data, 'TASK'), task_cals)
    preds_all = get_table(data, 'TASKPRED')
    projects = get_table(data, 'PROJECT')
    rsrc_assignments = get_table(data, 'TASKRSRC')
    cal_map = get_calendar_map(data)

    # ── D0 Pick the target project: the caller's, else the only one, else the
    # LATEST data date, ties by the most TASK rows, then file order ──
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
    selection = ''
    if proj_id is not None:
        if not any(p.get('proj_id', '') == proj_id for p in projects):
            raise ValueError(
                'proj_id %r is not a PROJECT in this file (it carries %s). '
                'Assessing it would grade an empty population.'
                % (proj_id, ', '.join(repr(p.get('proj_id', '')) for p in projects) or 'none'))
        target_pid = proj_id
        selection = 'chosen by the caller'
    elif projects and len(projects) > 1:
        # max() keeps the first of equal ranks: file order breaks the last tie.
        target_pid = max(projects, key=_d0_rank_key(tasks_all)).get('proj_id', '')
        selection = ('the latest data date (last_recalc_date), ties broken by the '
                     'most TASK rows, then file order')
    else:
        target_pid = projects[0].get('proj_id', '') if projects else ''
        selection = 'the only project in the file'

    # D0: a file with ONE PROJECT row is read whole, whatever project ID its
    # activities carry (2026-11-07, the written definition). Real exports can
    # file a few TASK rows under a proj_id no PROJECT row names; filtering on
    # proj_id dropped them. With several projects, only the scored one's.
    single_project = len(projects) <= 1
    if target_pid and not single_project:
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
    # D4 (2026-11-07, the written definition). Logic relationships: both ends in the
    # scored project, neither end an LOE or WBS summary (#1, #12). Live
    # relationships: logic relationships whose successor is incomplete
    # (#2 to #4); a relationship between finished activities is history.
    logic_rels = [p for p in preds_for_project
                  if _is_work_task(task_map[p['task_id']])
                  and _is_work_task(task_map[p['pred_task_id']])]
    live_rels = [p for p in logic_rels if not _is_complete(task_map[p['task_id']])]
    logic_pred_map, logic_succ_map = {}, {}
    for p in logic_rels:
        logic_pred_map.setdefault(p['task_id'], []).append(p)
        logic_succ_map.setdefault(p['pred_task_id'], []).append(p)

    work_tasks = [t for t in tasks if _is_work_task(t)]
    incomplete = [t for t in work_tasks if not _is_complete(t)]
    # D0: the resource assignments on the scored project's activities only.
    rsrc_for_project = [r for r in rsrc_assignments if r.get('task_id', '') in task_map]

    # D9: the baseline rows checks 8, 11, 13 and 14 read are the MATCHING
    # baseline project's, not every row in the baseline file.
    baseline_rows, baseline_pid, baseline_match = _baseline_project_tasks(
        baseline_data, project, work_tasks)
    baseline_unusable = baseline_rows is not None and not baseline_rows
    # D8: an Activity ID that appears more than once in either project is
    # ambiguous (left out of #8's baseline basis and of #11 and #14).
    ambiguous = _ambiguous_ids(tasks, baseline_rows) if baseline_rows else set()
    baseline_basis = None
    if baseline_rows:
        bl_cals = resolve_task_calendars(baseline_data)
        bl_cal_map = get_calendar_map(baseline_data)
        bl_days = {}
        for bt in with_resolved_calendars(baseline_rows, bl_cals):
            if not _is_work_task(bt):
                continue
            key = _norm_code(bt.get('task_code', ''))
            if key and key not in ambiguous:
                bl_days[key] = _hrs_to_days(_safe_float(bt.get('target_drtn_hr_cnt', ''), 0.0),
                                            bl_cal_map, bt.get('clndr_id', ''))
        baseline_basis = {'days': bl_days, 'ambiguous': ambiguous}

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
    # D14: a blank data date is the project's planned start, and one on a day
    # before a later planned start is lifted to it, as P6 does. parse_xer
    # applies it (xer_parser._fill_blank_data_dates) and lists each fill in
    # data['data_date_filled']; the fill for the scored project is disclosed
    # in the result and in #9, which reads the data date.
    data_date_filled = next(
        (dict(f) for f in (data.get('data_date_filled') or [])
         if isinstance(f, dict) and f.get('proj_id', '') == project.get('proj_id', '')),
        None)

    # Data date correction (27 September 2026). An update statused past its
    # data date is graded here as filed, and #9 still fails on it; its finding
    # names the latest actual and the date the CPP analysis tools move the data
    # date to. detect() reads the project graded above and changes nothing.
    # Guarded: without the module (this repository does not bundle it) #9 is
    # as it was.
    try:
        from data_date_correction import detect as _ddc_detect
        ddc_record = _ddc_detect(data, proj_id=target_pid)
    except ImportError:
        ddc_record = None

    # ── Run each check ──
    per_check = {}
    check_results = []

    def _run(cid, name, ref, result):
        check_results.append((cid, name, ref) + tuple(result))

    def _no_usable_baseline(label, threshold, **extra):
        # D9: a baseline file none of whose projects shares an Activity ID with
        # the scored project is not used; every baseline-dependent check is
        # NOT SCORED and says why.
        return INFO, None, threshold, (
            f'{label} NOT SCORED: a baseline was supplied but not used: '
            f'{baseline_match}.'
        ), dict({'assessed': False, 'basis': 'baseline not used',
                 'counts': _ns_counts()}, **extra)

    _run('DCMA-01-Logic', 'Logic', 'DCMA 14-Point #1',
         _check_01_logic(work_tasks, incomplete, logic_pred_map, logic_succ_map, prof))
    _run('DCMA-02-Leads', 'Leads', 'DCMA 14-Point #2',
         _check_02_leads(live_rels, prof, task_map))
    _run('DCMA-03-Lags', 'Lags', 'DCMA 14-Point #3',
         _check_03_lags(live_rels, prof, task_map, cal_map))
    _run('DCMA-04-Relationship', 'Relationship Types', 'DCMA 14-Point #4',
         _check_04_relationship_types(live_rels, prof, task_map))
    _run('DCMA-05-Hard', 'Hard Constraints', 'DCMA 14-Point #5',
         _check_05_hard_constraints(work_tasks, prof))
    _run('DCMA-06-HighFloat', 'High Float', 'DCMA 14-Point #6',
         _check_06_high_float(incomplete, cal_map, prof))
    _run('DCMA-07-NegFloat', 'Negative Float', 'DCMA 14-Point #7',
         _check_07_negative_float(incomplete, cal_map, prof))
    _run('DCMA-08-HighDuration', 'High Duration', 'DCMA 14-Point #8',
         _check_08_high_duration(incomplete, cal_map, prof, baseline_basis=baseline_basis))
    _run('DCMA-09-InvalidDates', 'Invalid Dates', 'DCMA 14-Point #9',
         _check_09_invalid_dates(work_tasks, data_date_dt, prof, correction=ddc_record))
    _run('DCMA-10-Resources', 'Resources', 'DCMA 14-Point #10',
         _check_10_resources(work_tasks, rsrc_for_project, prof, cal_map))
    if baseline_unusable:
        _run('DCMA-11-MissedTasks', 'Missed Tasks', 'DCMA 14-Point #11',
             _no_usable_baseline('Missed Tasks', prof['dcma_missed_tasks_max_pct'],
                                 missed_count=None))
    else:
        _run('DCMA-11-MissedTasks', 'Missed Tasks', 'DCMA 14-Point #11',
             _check_11_missed_tasks(work_tasks, baseline_rows, data_date_dt, prof,
                                    ambiguous=ambiguous))
    cycles = _logic_cycles([t['task_id'] for t in work_tasks], logic_rels)
    _run('DCMA-12-CriticalPathTest', 'Critical Path Test', 'DCMA 14-Point #12',
         _check_12_critical_path_test(work_tasks, logic_pred_map, prof, cycles=cycles))
    if baseline_unusable:
        _run('DCMA-13-CPLI', 'Critical Path Length Index', 'DCMA 14-Point #13',
             _no_usable_baseline('CPLI', prof['dcma_cpli_min'], cpli=None))
    else:
        _run('DCMA-13-CPLI', 'Critical Path Length Index', 'DCMA 14-Point #13',
             _check_13_cpli(work_tasks, cal_map, data_date_dt, prof, project,
                            baseline_tasks=baseline_rows))
    if baseline_unusable:
        _run('DCMA-14-BEI', 'Baseline Execution Index', 'DCMA 14-Point #14',
             _no_usable_baseline('BEI', prof['bei_min'], bei=None))
    else:
        _run('DCMA-14-BEI', 'Baseline Execution Index', 'DCMA 14-Point #14',
             _check_14_bei(work_tasks, baseline_rows, data_date_dt, prof,
                           ambiguous=ambiguous))
    cpli_value = check_results[12][7].get('cpli')
    bei_value = check_results[13][7].get('bei')

    # ── Fold into the report and score ──
    # NO criterion is hard-coded to pass. A criterion that could not be
    # evaluated on this file (INFO — e.g. BEI with no baseline supplied, or the
    # Critical Path Test where the finish is not structurally pinned) is
    # NOT SCORED: excluded from BOTH the numerator and the denominator and named
    # in dcma_not_assessed, so the score is out of what was actually measured
    # rather than out of a nominal 14 padded with free points.
    passed_count = 0
    assessed_count = 0
    not_assessed = []
    for check_id, name, ref, sev, val, thr, msg, det in check_results:
        check_no = int(check_id.split('-')[1])
        counts = det.pop('counts', None)
        if counts is None:
            counts = _counts(STATUS_NOT_SCORED if sev == INFO else
                             STATUS_PASS if sev == PASS else STATUS_FAIL)
        if check_no == 9 and data_date_filled:
            date_filed = data_date_filled.get('filed_data_date')
            date_read = str(data_date_filled.get('last_recalc_date') or '')
            msg += (f' The data date read is the project\'s planned start, '
                    f'{date_read[:10]}: the file\'s own '
                    + (f'data date, {date_filed[:10]}, falls on an earlier day, and P6 lifts '
                       f'it to the planned start.' if date_filed else
                       'data date is blank, and P6 starts from the planned start.'))
            det['data_date_filled'] = data_date_filled
        if sev != INFO:
            note, note_det = _profile_threshold_note(check_no, prof, profile)
            if note:
                msg = msg + note
                det['profile_threshold'] = note_det
        per_check[check_id] = {
            'severity': sev,
            'value': val,
            'threshold': thr,
            'message': msg,
            'details': det,
            'counts': counts,
        }
        report.add(Finding(
            severity=sev, check_id=check_id,
            message=msg, reference=ref,
            evidence={'value': val, 'threshold': thr, 'counts': counts, **det},
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
        and (single_project or not target_pid or r.get('proj_id', '') == target_pid))
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
        # D14: how the data date was filled or lifted from the planned start
        # ({proj_id, last_recalc_date, filled_from, filed_data_date when one
        # was filed}), or None when the file's own data date was read.
        'data_date_filled': data_date_filled,
        # D0: a file with several projects names the one scored and why.
        'projects_in_file': len(projects),
        'project_selection': (
            f'{project.get("proj_short_name", "") or target_pid} (proj_id '
            f'{target_pid}), one of {len(projects)} projects in the file, chosen '
            f'by {selection}' if len(projects) > 1 else selection),
        'baseline_proj_id': baseline_pid,
        'baseline_project_match': baseline_match,
        # D9: False when a baseline was supplied but no project in it could be
        # used (every baseline-dependent check is then NOT SCORED).
        'baseline_used': bool(baseline_rows),
        'definition_version': DCMA_DEFINITION_VERSION,
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
        # The written definition's result (PASS, FAIL or NOT SCORED) with the
        # counts behind it, beside the severity.
        counts = c.get('counts') or {}
        result_str = counts.get('status', '')
        if counts.get('num') is not None and counts.get('den') is not None:
            result_str += f" ({counts['num']} of {counts['den']})"
        val_str = f'{val:.2f}' if isinstance(val, float) else (str(val) if val is not None else '—')
        thr_str = f'{thr:.2f}' if isinstance(thr, float) else (str(thr) if thr is not None else '—')
        rows.append(
            f'<tr>'
            f'<td style="font-family:monospace; font-size:0.75rem;">{_esc(cid)}</td>'
            f'<td><span style="color:{_sev_color(sev)}; font-weight:700;">{_esc(sev)}</span></td>'
            f'<td>{_esc(result_str)}</td>'
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
        f'Not scored on this file: {_esc(", ".join(not_assessed))}</div>'
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
                <div style="font-size:0.75rem; color:#94a3b8;">Criteria passed, of those scored</div>
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
                <th style="padding:6px 10px; text-align:left;">Result</th>
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
