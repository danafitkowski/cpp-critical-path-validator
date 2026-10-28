"""The driving path of a schedule, traced on its own dates (27 September 2026).

VENDORED COPY. This file is CPP's internal driving-path tracer as of
28-Oct-2026 (its last change, 16-Oct-2026: the minute trace), bundled so
Check 2 of the validator reads the longest path the way the internal
validator does. One change: ``_canonical_cpm`` imports cpp-cpm-engine's
``cpm`` from the path (its ``python_reference/`` folder) when no ``cpm.py``
sits beside this file, as none does in this repository. Without the engine
the trace reports that its date arithmetic is unavailable and traces nothing.
The validator runs the minute trace only (``resolution='minute'``). The
working-day trace and its slack also call ``cpm._calendar_exceptions``, which
the public engine (v2.10.14) does not have, so they need the internal engine.
Everything else, docstrings included, is the internal file's.

An unfinished activity is on the driving path when it lies on an unbroken
chain of driving relationships into the schedule's latest early finish.

* A relationship DRIVES when the date its predecessor hands on, plus the lag,
  leaves no working day before the successor's own date, counted on the
  successor's calendar (dates are read to the working day: see below). FS
  and FF leave from the predecessor's early finish, SS and SF from its
  early start (its remaining start once it has started).
  FS and SS land on the successor's early start (its remaining start once
  started); FF and SF land on its finish, which the arithmetic reads as the
  start its remaining duration implies. The lag is working time on the
  calendar P6's lag setting names.
* The chains start at EVERY unfinished activity whose early finish is the
  schedule's latest, and every driving relationship is followed, so tied
  chains all count, a tie with the data date included.
* Where a constraint or the data date sets an activity's date, no
  relationship into it drives it, and the chain starts there. A relationship
  whose drive lands AFTER the successor's stored date still holds it (the
  row is behind its own logic). No relationship into an activity whose date
  a Mandatory Start or Mandatory Finish pins drives it, not even one that
  lands on the pinned date: the constraint sets that date. Start On and
  Finish On are not pins: logic wins over them (the engine's P6-measured
  rule, v2.9.42), so they hold a date only as an early and a late bound,
  like any other constraint.
* Level of effort and WBS summary rows are never on the path, and neither is
  completed work. Under retained logic a completed activity can carry an
  unfinished predecessor's date to its successors; the chain passes THROUGH
  such a carrier to the unfinished work behind it, and the carrier itself is
  not counted. A carrier that hands unfinished work's date on at the data
  date itself ties with the data date, and the chain passes through it too
  (predecessor_drive, which the validator shares, drops a drive that ends at
  the data date; the trace does not).
* An unfinished activity that cannot slip a working day of its own without
  moving the forecast finish (``slack`` 0, below) is on the path whether or
  not a chain reaches it (``joined_by_slack``). Where the predecessor's
  calendar does not work days its successor's does, its next working day
  can land past a gap the successor's calendar leaves, and where the
  working-day reading cannot tell two instants apart no relationship
  reaches it; either way a delay to it moves the finish (review,
  27-Sep-2026).

The dates are the ones stored in the rows: as filed for a schedule read as
filed, and as update_reschedule.correct_update rewrote them for a corrected
update. No engine runs here.

WORKING-DAY RESOLUTION. Stored date-times are read to the working day, by
the rule the data date correction uses: a time before 12:00 is the opening
of its day, a time at or after 12:00 is the close of its day (the engine's
``_instant_of``). So a Friday 16:00 or 17:00 finish hands on Monday
morning, and a drive that lands part-way through the successor's first
working day counts as landing on it. "No working time" in the test above is
therefore "no working day". Phase 1 measured at the minute, with the P6
oracle's own calendar model; where the two readings part on the windows
corpus, P6's own flags agree with the working-day reading on corpus file 15,
and the other differences are artifacts of the phase 1 harness, not of P6
(review, 27-Sep-2026). Part-day remaining durations and lags are counted
(``sub_day``) so a report can say the path is traced to the working day.

TO THE MINUTE (``resolution='minute'``, 16-Oct-2026). The same rules on the
hours engine's arithmetic (``minute_date_helpers``): the latest early finish
is the latest instant, so a finish at a day's close no longer ties with a
milestone at the next day's opening, and a relationship drives when no
working time on the successor's calendar is left between where it lands and
where the successor sits (P6 measures a relationship's float in working
time). P6 finds its Longest Path this way, and three more of its rules hold
only in a minute trace:

* unfinished level-of-effort rows are walked through (``PASS_THROUGH_TYPES``;
  reported in ``passed_through``, never in ``codes``): P6 stretches a level
  of effort to the work linked to its ends, counts the link that stretched
  it as driving, and every link into it that lands on or after its own date;
* under retained logic with "lag from Actual Start", an SS link out of work
  under way is laid from the data date, and the data date, not the
  predecessor, drives the successor;
* instants are carried above zero (``_MINUTE_SHIFT``), so a schedule dated
  before 2020, the engine's epoch, is traced.

The data-date correction's written flag and the validator's cross-check
trace to the minute; the windows analysis keeps the working day. On all 327
P6 projects scheduled and not edited since, the minute trace matches P6's
flag exactly, 12,854 flagged unfinished activities of 12,854 (16-Oct-2026):
every tie it follows is one P6 flags, so the tied chains P6 seemed to leave
unflagged (phase 1, below) are ties only to the working day. A minute trace
computes no slack.

When the trace cannot be read, it says why and the caller keeps the total
float test: no unfinished activity, no early dates, no calendars (without
one every working-day test would fall to a seven-day count, and weekends
would break every chain), an unfinished activity without a calendar, or a
relationship lag counted on a calendar this trace does not walk (P6's
24-hour and project lag calendars, which the engine does not model either).

SLACK TO THE DRIVING PATH (``slack``): how many working days, on its own
calendar, each unfinished activity can slip before it would move the
forecast finish. A backward pass over the same stored dates from the latest
early finish, through the same drive arithmetic (``predecessor_drive`` and
``_carry_drive`` on the activity's dates shifted by whole working days: each
lag on its own calendar, the landing on the successor's), with no late-date
constraint and no Must Finish By, since those change float and not dates.
A link into a Mandatory Start or Finish carries no delay; a link whose drive
already lands past its successor's date leaves no working day to spare,
never fewer, as the trace reads it; an activity can always slip until its
own finish would be the latest. The driving path sits at 0, save where a
successor's calendar does not work days the path's own calendar does.
Total float less the path's lowest float gives the same number only while
all float runs to one date, as it does to a Must Finish By on one calendar
(the demo); a constraint on a chain off the path drives that chain's float
below the path's, where slack stays what it is.

SPEED. The engine walks calendars a day at a time; the trace answers the
same walks from one working-day index per calendar (``_calendar_indexes``,
``_fast_helpers``), the engine's own rules step for step and the engine
itself outside an index. On the corpus the two give the same path and the
same slack on every schedule with negative float; on a 2,900-activity
schedule the trace and its slack take about half a second.

Proof (phase 1, the spec's "Proof against P6"): on P6's own F9 of the demo at
three data dates this trace gives P6's 39 unfinished Longest Path flags, and
on the 20 fresh P6 exports with flags and negative float it contains all 767
activities P6 flags. P6's flag is the cross-check, not the source: at some
ties it marks only some of the tied chains.

The drive arithmetic (``engine_date_helpers``, ``hrs_to_days``,
``carried_instants``, ``predecessor_drive``) moved here from
critical-path-validator's cp_validator, where the stored-date check has used
it since 2026-09-15. The validator imports it back unchanged.
"""
import bisect
import importlib.util as _ilu
import os
import sys
from datetime import date as _date

_HERE = os.path.dirname(os.path.abspath(__file__))

COMPLETE_STATUS = 'TK_Complete'
ACTIVE_STATUS = 'TK_Active'
EXCLUDED_TASK_TYPES = ('TT_LOE', 'TT_WBS')
# What a minute trace (P6's Longest Path) walks through without reporting it as
# path work, and whether such a row can end the path (16-Oct-2026).
PASS_THROUGH_TYPES = ('TT_LOE',)
PASS_THROUGH_TERMINALS = False
# Constraints that PIN an activity's date against its logic. A relationship
# whose drive lands after such an activity's stored date did not set it.
# Start On and Finish On are not here: logic wins over them (engine v2.9.42,
# measured in P6).
HARD_CONSTRAINTS = frozenset({'CS_MANDSTART', 'CS_MANDFIN'})

PRED_TYPE_MAP = {'PR_FS': 'FS', 'PR_FF': 'FF', 'PR_SS': 'SS', 'PR_SF': 'SF'}

# P6's relationship lag calendar setting (SCHEDOPTIONS
# sched_calendar_on_relationship_lag) as the calendar the trace walks lags on.
LAG_CALENDAR_ROLES = {
    'rcal_Predecessor': 'predecessor', 'rcal_Successor': 'successor',
    'rcal_Project': 'project', 'rcal_24Hour': '24hour', 'rcal_24hour': '24hour',
    'Predecessor': 'predecessor', 'Successor': 'successor',
    'pred': 'predecessor', 'succ': 'successor',
    'predecessor': 'predecessor', 'successor': 'successor',
    'project': 'project', '24hour': '24hour',
}
# Lag calendars the trace does not walk, and the reason it gives.
_UNWALKED_LAG_CALENDARS = {
    '24hour': 'its relationship lags count on a 24-hour calendar, which this trace '
              'does not walk',
    'project': "its relationship lags count on the project's default calendar, which "
               'this trace does not walk',
}


# ─────────────────────────────────────────────────────────────────────
# The canonical engine's date arithmetic
# ─────────────────────────────────────────────────────────────────────

def _canonical_cpm():
    """The canonical engine module, never time-impact-analysis's cpm shim.

    The shim re-exports the public API only and lacks the private date
    helpers below. Whichever of the two comes first on sys.path wins a bare
    ``import cpm``, so the canonical file beside this one is loaded by path
    (the path explorer's rule), reusing it when it is already loaded."""
    mod = sys.modules.get('_cpp_common_cpm_canonical')
    if mod is not None:
        return mod
    cached = sys.modules.get('cpm')
    if cached is not None and hasattr(cached, '_snap_fwd') and hasattr(cached, '_unexpired_lag'):
        return cached
    if not os.path.isfile(os.path.join(_HERE, 'cpm.py')):
        # Vendored copy (see the module docstring): cpp-cpm-engine's cpm from
        # the path; an ImportError leaves the callers' "unavailable".
        import cpm
        return cpm
    spec = _ilu.spec_from_file_location('_cpp_common_cpm_canonical',
                                        os.path.join(_HERE, 'cpm.py'))
    mod = _ilu.module_from_spec(spec)
    sys.modules['_cpp_common_cpm_canonical'] = mod
    spec.loader.exec_module(mod)
    return mod


def engine_date_helpers():
    """The canonical engine's date arithmetic, or None when the engine is not
    importable (callers degrade: the validator skips its stored-date walk,
    the tracer reports the path as not traced)."""
    try:
        cpm = _canonical_cpm()
        return {
            'date_to_num': cpm.date_to_num, 'num_to_date': cpm.num_to_date,
            'instant_of': cpm._instant_of, 'snap_fwd': cpm._snap_fwd,
            'lag_from_instant': cpm._lag_from_instant,
            'retreat_workdays': cpm._retreat_workdays,
            'count_workdays': cpm._count_work_days_between,
            'unexpired_lag': cpm._unexpired_lag,
        }
    except Exception:  # pragma: no cover - defensive
        return None


# Minutes (whole days) the minute instants are carried up by, so every date
# after 1820 counts above zero (minute_date_helpers).
_MINUTE_SHIFT = 200 * 365 * 1440


def minute_date_helpers():
    """The hours engine's arithmetic, in minutes, in the shape
    ``engine_date_helpers`` gives, for ``trace(resolution='minute')``; None
    when the engine is not importable (16-Oct-2026).

    An instant is minutes since the engine epoch (cpm_minutes.parse_instant),
    so a finish at 16:00 and the next day's 08:00 opening are two instants,
    where the working-day reading makes them one. A lag or a remaining
    duration is P6's own hours in minutes (``amount``), walked on the calendar
    as the hours pass walks it (cpm_hours: ``lag_fwd`` adds working minutes,
    ``unexpired`` takes off the working minutes the data date has used). P6
    finds its Longest Path at this resolution: the latest early finish to the
    minute, and a relationship drives when its date lands on the successor's
    to the minute.

    The trace reads an instant of 0 or less as "no date". The engine's epoch
    is 1 January 2020, so every earlier date counts below zero: these
    instants are carried ``_MINUTE_SHIFT`` minutes (whole days) up, and each
    calendar walk takes the shift off and puts it back, so a schedule dated
    before 2020 is traced like any other."""
    try:
        cpm = _canonical_cpm()
        cm = cpm._hours_sibling('cpm_minutes')
        cm.set_slot_decoder(cpm._day_slot_tables)
    except Exception:  # pragma: no cover - defensive
        return None
    cals = {}

    def wc(cal):
        hit = cals.get(id(cal))
        if hit is None or hit[0] is not cal:
            hit = (cal, cm.WorkCalendar(cal or {}))
            cals[id(cal)] = hit
        return hit[1]

    sh = _MINUTE_SHIFT

    def instant_of(s):
        t = cm.parse_instant(s)
        return t + sh if t is not None else 0

    def num_to_date(t):
        return cm.format_instant(t - sh)

    def snap_fwd(t, cal, **_):
        return wc(cal).next_work(t - sh) + sh if t > 0 else t

    def lag_from_instant(t, lag, lag_cal, **_):
        return t if t <= 0 or not lag else wc(lag_cal).add(t - sh, lag) + sh

    def retreat(end, minutes, cal, **_):
        return wc(cal).sub(end - sh, minutes) + sh if end > 0 else end

    def unexpired_lag(actual, lag, lag_cal, dd):
        if lag <= 0:
            return 0
        if actual <= 0 or dd <= 0 or actual >= dd:
            return lag
        return max(0, lag - wc(lag_cal).between(actual - sh, dd - sh))

    def amount(hrs, cal_map=None, clndr_id=None):
        return int(round(_float0(hrs) * 60))

    def reaches(drive, at, cal):
        # P6 measures a relationship's float in working time: a link drives
        # when no working time on the successor's calendar is left between
        # where it lands and where the successor sits, so a close and the next
        # opening are one landing for a milestone or work with none left.
        return drive >= at or wc(cal).between(drive - sh, at - sh) <= 0

    return {
        'resolution': 'minute', 'amount': amount,
        'date_to_num': instant_of, 'num_to_date': num_to_date,
        'instant_of': instant_of, 'snap_fwd': snap_fwd,
        'lag_from_instant': lag_from_instant, 'retreat_workdays': retreat,
        'count_workdays': None, 'unexpired_lag': unexpired_lag,
        'reaches': reaches,
    }


def _amount(helpers):
    """How a stored hour count becomes a duration or lag for these helpers:
    working days (hrs_to_days) for the engine's day arithmetic, minutes for
    ``minute_date_helpers``."""
    return helpers.get('amount') or hrs_to_days


def _float0(val):
    """cp_validator._safe_float(val, 0): blank or unreadable is 0."""
    try:
        return float(val) if val and str(val).strip() else 0.0
    except (ValueError, TypeError):
        return 0.0


def hrs_to_days(hrs, cal_map=None, clndr_id=None):
    """Convert hours to working days using calendar if available."""
    h = _float0(hrs)
    hrs_per_day = 8.0
    if cal_map and clndr_id:
        cal = cal_map.get(clndr_id, {})
        hpd = cal.get('hours_per_day', 8.0)
        if hpd and hpd > 0:
            hrs_per_day = hpd
    return h / hrs_per_day if hrs_per_day > 0 else 0


def _is_complete(task):
    return task.get('status_code', '') == COMPLETE_STATUS


def _carry_drive(p, pt, succ, carried, cal_map, helpers, lag_role,
                 data_date_inst=0, ss_lag_from='early_start'):
    """The instant one predecessor link ``p`` (from ``pt``) hands the
    COMPLETED activity ``succ`` under retained logic; ``carried_instants``
    keeps the latest over all its links. 0 when it hands on nothing.

    This is the loop body ``carried_instants`` has had since 2026-09-23,
    lifted out unchanged so the driving-path trace can ask which link a
    carried date came from."""
    _no_alerts = []
    if _is_complete(pt) and data_date_inst > 0:
        # FA: a completed predecessor hands on its stamp plus the
        # unexpired part of the lag, as into any successor (INFERRED
        # for a completed-to-completed link; the engine does the same).
        start_side = PRED_TYPE_MAP.get(p.get('pred_type', ''), 'FS') in ('SS', 'SF')
        act = helpers['instant_of'](pt.get('act_start_date', '') if start_side
                                    else pt.get('act_end_date', ''))
        if act <= 0:
            act = helpers['instant_of'](pt.get('act_end_date', ''))
        lag_cid = (pt.get('clndr_id', '') if lag_role == 'predecessor'
                   else succ.get('clndr_id', ''))
        lag_cal = cal_map.get(lag_cid) if cal_map else None
        lag = _amount(helpers)(p.get('lag_hr_cnt', 0), cal_map, lag_cid)
        return helpers['lag_from_instant'](
            max(data_date_inst, carried.get(pt.get('task_id', ''), 0)),
            helpers['unexpired_lag'](act, lag, lag_cal, data_date_inst),
            lag_cal, alerts=_no_alerts, ctx='carried')
    if _is_complete(pt):
        return carried.get(pt.get('task_id', ''), 0)
    start_side = PRED_TYPE_MAP.get(p.get('pred_type', ''), 'FS') in ('SS', 'SF')
    pt_active = pt.get('status_code', '') == ACTIVE_STATUS
    if start_side:
        src = (pt.get('restart_date', '') if pt_active
               else pt.get('early_start_date', ''))
    else:
        src = pt.get('early_end_date', '')
    src = helpers['instant_of'](src)
    if src <= 0:
        return 0
    lag_cid = (pt.get('clndr_id', '') if lag_role == 'predecessor'
               else succ.get('clndr_id', ''))
    lag_cal = cal_map.get(lag_cid) if cal_map else None
    lag = _amount(helpers)(p.get('lag_hr_cnt', 0), cal_map, lag_cid)
    if start_side and pt_active and (pt.get('act_start_date') or '').strip():
        # SSL measured (P6 probe 2026-09-23): off a STARTED
        # predecessor P6 lays no lag into completed work; it
        # carries the anchor itself (engine: the pass-through
        # loop and _ss_anchor_for).
        lag = 0
        if (PRED_TYPE_MAP.get(p.get('pred_type', ''), 'FS') == 'SS'
                and ss_lag_from == 'actual_start' and data_date_inst > 0):
            src = data_date_inst
    return helpers['lag_from_instant'](
        src, lag, lag_cal, alerts=_no_alerts, ctx='carried')


def carried_instants(tasks, pred_map, task_map, cal_map, helpers, lag_role,
                     data_date_inst=0, ss_lag_from='early_start'):
    """Retained logic: the instant each COMPLETED activity carries from
    unfinished work to its successors, by task_id (0 when it carries none).

    P6 schedules a completed activity like any other with zero remaining
    duration, so one completed out of sequence holds its unfinished
    predecessors' controlling date and hands it on (engine v2.9.46, the
    retained-logic pass-through). Measured on a P6 23.12 project: a finish
    milestone due 18 March 2027 FF into an activity completed in August 2026,
    whose two successors P6 started 19 March 2027. The date is the latest
    drive into the completed activity - an incomplete predecessor's stored
    finish, or its start for SS/SF (the restart of a started one), plus that
    link's lag, applied as on any link (measured in P6, 2026-09-23) except
    for an SS or SF link off a STARTED predecessor, which P6 carries with no
    lag at all: the restart itself, or the data date (`data_date_inst`) for
    SS under "lag from Actual Start" (`ss_lag_from`); off a completed
    predecessor, its stamp (the data date or its own carried instant) plus
    the unexpired part of the lag (rule FA; without a data date, its carried
    instant as it is). It is read from
    the predecessors' stored dates, not from the completed row's own early
    dates: P6 stamps those with the carried date on a fresh export, but a
    file rebuilt without rescheduling can hold anything there. Completed
    activities are walked in logic order without recursion; those on or
    behind a loop among completed activities have no logic order and are
    settled by repeating the walk over them until nothing moves.
    """
    done = {t.get('task_id', ''): t for t in tasks if _is_complete(t)}
    indeg = {tid: 0 for tid in done}
    succs = {}
    for tid in done:
        for p in pred_map.get(tid, []):
            pid = p.get('pred_task_id', '')
            if pid in done:
                indeg[tid] += 1
                succs.setdefault(pid, []).append(tid)
    order = [tid for tid, n in indeg.items() if n == 0]
    i = 0
    while i < len(order):
        for s in succs.get(order[i], ()):
            indeg[s] -= 1
            if indeg[s] == 0:
                order.append(s)
        i += 1
    looped = [tid for tid, n in indeg.items() if n > 0]
    carried = {}

    def _into(tid):
        best = 0
        for p in pred_map.get(tid, []):
            pt = task_map.get(p.get('pred_task_id', ''))
            if pt is None:
                continue
            inst = _carry_drive(p, pt, done[tid], carried, cal_map, helpers,
                                lag_role, data_date_inst, ss_lag_from)
            if inst > best:
                best = inst
        return best

    for tid in order + looped:
        carried[tid] = _into(tid)
    # Values only rise, so the repetition settles on the same answer whatever
    # order the file lists them - unless a loop among completed activities
    # carries unexpired lag, which would add it on every pass. P6 schedules
    # no loop at all, so the repetition stops after one pass per looped
    # activity, which is as far as any date can travel round one.
    moved = bool(looped)
    passes = 0
    while moved and passes <= len(looped):
        passes += 1
        moved = False
        for tid in looped:
            inst = _into(tid)
            if inst > carried[tid]:
                carried[tid] = inst
                moved = True
    return carried


def predecessor_drive(task, task_preds, task_map, cal_map, helpers, lag_role,
                      schedule_mode='retained_logic', carried=None,
                      data_date_inst=0, ss_lag_from='early_start'):
    """The latest instant this activity's predecessors drive it to, computed
    from the PREDECESSORS' OWN STORED dates (actuals for completed ones,
    stored early / remaining dates otherwise), with the lag as working time on
    the lag calendar and the result snapped onto this activity's calendar.
    0 when nothing drives it.

    The engine's rule, fed P6's numbers rather than its own, so it is
    independent of any engine defect. One walk serves both readers below: the
    stored-date check, which asks what a row's start should be and passes
    every predecessor, and the data-date heuristic, which asks whether a
    COMPLETED predecessor's lag holds a row and passes only those. The
    heuristic had no such walk until 2026-09-21: it looked only at whether a
    predecessor was incomplete, so a completed predecessor's lag was invisible
    to it and a row it legitimately held read as proof of a later data date.
    The driving-path trace passes ONE link at a time and compares the result
    with the activity's stored start.

    Under retained logic it applies the engine's two v2.9.46 rules too, on the
    same stored numbers. A completed predecessor also hands on the instant it
    carries from unfinished work (`carried`, from `carried_instants`, which
    the callers build under retained logic only) without the lag, which
    counts from its actual dates, and hands it to a started successor's
    restart as well, though its actual dates never drive one. An SS or SF
    link off a STARTED predecessor lays only the part of its lag the
    predecessor has not already used up by the data date (`data_date_inst`),
    from its restart: the lag less the working days of the lag calendar from
    its actual start to the data date, none elapsed for a future actual
    start, a lead laying nothing (the engine's `_unexpired_lag`). Until
    2026-09-23 this walk had none of these, and then read the SS link by
    SS_U, max(actual start + lag, restart), which is the same date only while
    the restart sits at the data date; with the restart held later it flagged
    the successors P6 had just scheduled as dates no schedule run could
    produce. The actual start is read as the instant P6 stored (an afternoon
    start counts from the close of its day), as the engine now reads it.
    Under "Calculate start-to-start lag from: Actual Start" (`ss_lag_from`,
    SCHEDOPTIONS sched_lag_early_start_flag = N) an SS link off a started
    predecessor is laid from the DATA DATE rather than the restart, and SF
    links ignore the option (measured in P6 23.12 on 2026-09-23; the
    engine's _ss_anchor_for).

    With a data date (`data_date_inst`) a COMPLETED predecessor drives as the
    engine's rule FA has it, in either mode: from its own stamp - the data
    date, or the date it carries - plus only the part of the lag its actual
    date had not used up by the data date. So an actual finish recorded AFTER
    the data date drives nothing (P6 ignores it; measured in P6 23.12 on six
    probe projects, and the real-file successor P6 started off its other,
    unfinished predecessor read as not producible here until 2026-09-23), a
    lag off it runs from the data date, a lag still running at the data date
    is laid on the carried date, and the same drive holds a started
    successor's restart. Without a data date the older walk stands: actual
    date plus the whole lag, the carried date without it, and no restart.

    Under progress override P6 resumes a STARTED activity's remaining work
    without waiting on the links into its start: FS and SS drive nothing
    there, and the restart sits at the later of the data date and the actual
    start (`_stored_date_consistency` supplies that anchor). FF and SF still
    drive it, because they bound its finish, and P6 schedules the remaining
    work back from there. Measured on a P6 23.12 probe scheduled under
    progress override on 2026-09-23: the started successors of FS links
    resumed at the data date, those of FF links where the predecessor's
    finish less their remaining duration put them; SS and SF follow by the
    same split, with no discriminating instance. The engine ignores every
    predecessor there, FF included, which is an open engine question. Until
    2026-09-23 every link drove a started activity under progress override,
    as under retained logic, and the FS successors P6 had resumed at the data
    date read as dates no schedule run could produce.
    """
    retained = schedule_mode == 'retained_logic'
    active = task.get('status_code', '') == ACTIVE_STATUS
    start_free = active and schedule_mode == 'progress_override'
    cid = task.get('clndr_id', '')
    cal = cal_map.get(cid) if cal_map else None
    rem_days = _amount(helpers)(task.get('remain_drtn_hr_cnt', 0), cal_map, cid)
    _no_alerts = []
    drive = 0
    for p in task_preds:
        pt = task_map.get(p.get('pred_task_id', ''))
        if pt is None:
            continue
        pcid = pt.get('clndr_id', '')
        done = _is_complete(pt)
        pt_active = pt.get('status_code', '') == ACTIVE_STATUS
        if done:
            fin = helpers['instant_of'](pt.get('act_end_date', ''))
            start = helpers['instant_of'](pt.get('act_start_date', ''))
        else:
            fin = helpers['instant_of'](pt.get('early_end_date', ''))
            start = helpers['instant_of'](
                pt.get('restart_date', '') if pt_active
                else pt.get('early_start_date', ''))
        lag_cid = pcid if lag_role == 'predecessor' else cid
        lag_cal = cal_map.get(lag_cid) if cal_map else None
        lag = _amount(helpers)(p.get('lag_hr_cnt', 0), cal_map, lag_cid)
        rtype = PRED_TYPE_MAP.get(p.get('pred_type', ''), 'FS')
        if start_free and rtype in ('FS', 'SS'):
            continue   # progress override: started work does not wait on its start
        anchor = start if rtype in ('SS', 'SF') else fin
        inst = (helpers['lag_from_instant'](anchor, lag, lag_cal,
                                            alerts=_no_alerts, ctx='drive')
                if anchor > 0 else 0)
        if (retained and rtype in ('SS', 'SF') and pt_active and start > 0
                and (pt.get('act_start_date') or '').strip()):
            _ss_src = (data_date_inst if (rtype == 'SS' and ss_lag_from == 'actual_start'
                                          and data_date_inst > 0) else start)
            inst = helpers['lag_from_instant'](
                _ss_src, helpers['unexpired_lag'](
                    helpers['instant_of'](pt.get('act_start_date', '')),
                    lag, lag_cal, data_date_inst),
                lag_cal, alerts=_no_alerts, ctx='drive')
        if done and data_date_inst > 0:
            # FA (engine _done_drive, 2026-09-23): completed work drives from
            # its own stamp - the data date, or the later date it carries -
            # plus only the part of the lag its actual date had not used up
            # by the data date; an actual date after the data date uses up
            # none and drives nothing itself. A drive that ends at the data
            # date adds nothing to the floor the caller applies, and for a
            # started successor it is this same drive that holds the restart.
            act = anchor if anchor > 0 else fin
            stamp = max(data_date_inst, (carried or {}).get(pt.get('task_id', ''), 0))
            inst = helpers['lag_from_instant'](
                stamp, helpers['unexpired_lag'](act, lag, lag_cal, data_date_inst),
                lag_cal, alerts=_no_alerts, ctx='drive')
            if inst <= data_date_inst:
                continue
        elif done:
            pt_carried = (carried or {}).get(pt.get('task_id', ''), 0)
            if pt_carried > inst:
                inst = pt_carried
            elif active:
                continue   # finished work never drives a started successor's restart
        if inst <= 0:
            continue
        if rtype in ('FS', 'SS'):
            cand = helpers['snap_fwd'](inst, cal, alerts=_no_alerts, ctx='drive')
        else:
            cand = helpers['retreat_workdays'](
                helpers['snap_fwd'](inst, cal, alerts=_no_alerts, ctx='drive'),
                rem_days, cal, alerts=_no_alerts, ctx='drive')
        if cand > drive:
            drive = cand
    return drive


# ─────────────────────────────────────────────────────────────────────
# The trace
# ─────────────────────────────────────────────────────────────────────

def stored_start(task, cal_map, helpers):
    """The instant an unfinished activity's work begins, as the stored-date
    check reads it: its remaining start once started, its early start
    otherwise, on its own calendar (a start stored inside or at the close of
    a working day, and any zero-duration row, snapped to where work begins).
    0 when the row carries no such date."""
    active = task.get('status_code', '') == ACTIVE_STATUS
    raw = ((task.get('restart_date') if active else task.get('early_start_date')) or '').strip()
    observed = helpers['instant_of'](raw)
    if observed <= 0:
        return 0
    cid = task.get('clndr_id', '')
    cal = cal_map.get(cid) if cal_map else None
    rem_days = _amount(helpers)(task.get('remain_drtn_hr_cnt', 0), cal_map, cid)
    if helpers.get('resolution') == 'minute':
        # To the minute: work stored to start at a close starts at the next
        # opening; a zero-duration row stays at the instant stored (a finish
        # milestone sits at a close, and is landed on there).
        return helpers['snap_fwd'](observed, cal) if rem_days else observed
    if rem_days == 0 or observed != helpers['date_to_num'](raw):
        observed = helpers['snap_fwd'](observed, cal, alerts=[], ctx='stored start')
    return observed


def _hard_constrained(task):
    return bool({(task.get('cstr_type') or '').strip(),
                 (task.get('cstr_type2') or '').strip()} & HARD_CONSTRAINTS)


def _task_code(t):
    return (t.get('task_code') or '').strip() or t.get('task_id', '')


def _part_day(hours, cal):
    """True when a stored hour count is not a whole number of working days on
    the calendar (8 h a day without one)."""
    h = _float0(hours)
    if not h:
        return False
    hpd = (cal or {}).get('hours_per_day') or 8.0
    days = h / hpd
    return abs(days - round(days)) > 1e-6


def trace(tasks, preds, cal_map, *, lag_role='predecessor',
          schedule_mode='retained_logic', ss_lag_from='early_start',
          data_date='', resolution='day'):
    """The driving path of one project's rows, and each unfinished activity's
    slack to it.

    Args:
        tasks: the project's TASK rows (dicts as xer_parser returns them),
            each with its calendar resolved (a blank clndr_id is the project
            calendar: xer_parser.with_resolved_calendars).
        preds: TASKPRED rows; links to rows not in ``tasks`` are ignored.
        cal_map: xer_parser.get_calendar_map of the file.
        lag_role: the calendar relationship lags are walked on: 'predecessor'
            or 'successor', or '24hour' / 'project' (P6's other two
            settings), which the trace does not walk: a schedule with a lag
            under either is not traced.
        schedule_mode, ss_lag_from: the file's SCHEDOPTIONS as
            tia_builder._detect_schedule_options resolves them
            (``schedule_mode``, ``ss_lag_from``).
        data_date: PROJECT.last_recalc_date as the run reads it (the
            corrected date for a corrected update), time of day included.
        resolution: 'day' (the default, the windows analysis's reading: see
            WORKING-DAY RESOLUTION above) or 'minute' (16-Oct-2026): the same
            rules on the hours engine's arithmetic (``minute_date_helpers``),
            P6's own resolution for its Longest Path flag. A minute trace
            computes no slack, so it joins nothing by slack and returns
            ``slack`` empty.

    Returns:
        {'traced': bool, 'codes': [...], 'terminals': [...],
         'latest_finish': 'YYYY-MM-DD HH:MM' as stored, 'carriers': [...],
         'slack': {code: working days}, 'sub_day': {'durations': n,
         'lags': n}, 'reason': ''}
        ``codes`` are the task codes of the unfinished activities on the
        path; ``carriers`` the completed activities the chains pass through;
        ``slack`` how far every unfinished activity with early dates can slip,
        in working days on its own calendar, before it moves the forecast
        finish (see the module docstring); ``sub_day`` how many unfinished
        activities have a remaining duration, and how many relationships a
        lag, that is not a whole number of working days. When the path cannot
        be traced ``traced`` is False, ``codes`` and ``slack`` are empty and
        ``reason`` says why, in words that follow "because".
    """
    out = {'traced': False, 'codes': [], 'terminals': [], 'latest_finish': '',
           'carriers': [], 'passed_through': [], 'joined_by_slack': [], 'slack': {},
           'sub_day': {'durations': 0, 'lags': 0}, 'reason': ''}
    minutes = resolution == 'minute'
    helpers = minute_date_helpers() if minutes else engine_date_helpers()
    if helpers is None:
        out['reason'] = 'the engine date arithmetic is unavailable'
        return out
    # To the minute, unfinished level-of-effort rows are walked through
    # (PASS_THROUGH_TYPES): P6's Longest Path runs through them. They are
    # never reported as path work (``codes``), only in ``passed_through``.
    passing = PASS_THROUGH_TYPES if minutes else ()
    work = [t for t in tasks if t.get('task_type', '') not in EXCLUDED_TASK_TYPES
            or (t.get('task_type', '') in passing and not _is_complete(t))]
    task_map = {t.get('task_id', ''): t for t in work}
    open_rows = [t for t in work if not _is_complete(t)]
    if not any(t.get('task_type', '') not in passing for t in open_rows):
        out['reason'] = 'no unfinished activities'
        return out
    finishes = []
    for t in open_rows:
        if t.get('task_type', '') in passing and not PASS_THROUGH_TERMINALS:
            continue
        f = helpers['instant_of']((t.get('early_end_date') or '').strip())
        if f > 0:
            finishes.append((f, t))
    if not finishes:
        out['reason'] = 'its unfinished activities carry no early dates'
        return out
    # Without calendars every working-day test falls to a seven-day count and
    # weekends break every chain: no trace, rather than a broken one.
    if not cal_map:
        out['reason'] = 'the file has no calendars'
        return out
    missing = [t for t in open_rows if (t.get('clndr_id') or '') not in cal_map]
    if missing:
        out['reason'] = '{} of its unfinished activities {} no calendar'.format(
            len(missing), 'has' if len(missing) == 1 else 'have')
        return out

    pred_map = {}
    for p in preds or []:
        if p.get('task_id', '') in task_map and p.get('pred_task_id', '') in task_map:
            pred_map.setdefault(p.get('task_id', ''), []).append(p)
    role = LAG_CALENDAR_ROLES.get(str(lag_role or 'predecessor').strip(), lag_role)
    if role not in ('predecessor', 'successor'):
        if any(_float0(p.get('lag_hr_cnt')) for links in pred_map.values() for p in links):
            out['reason'] = _UNWALKED_LAG_CALENDARS.get(
                role, f'its relationship lag calendar setting ({lag_role}) is not one this '
                      'trace walks')
            return out
        role = 'predecessor'   # no lag anywhere: the setting changes nothing
    lag_role = role

    last = max(f for f, _ in finishes)
    terminals = [t for f, t in finishes if f == last]
    # Every terminal finishes on the same working day; the forecast finish is
    # the latest of them as stored, whatever order the file lists them in.
    out['latest_finish'] = max((t.get('early_end_date') or '').strip() for t in terminals)

    dd_inst = helpers['instant_of']((data_date or '').strip()) if data_date else 0
    # The engine's calendar walks answered from working-day indexes, exact
    # twins inside their range (review, 27-Sep-2026: the walks, day by day
    # with a date string per day, were most of the trace's and the slack's
    # time on calendars with holidays). The minute calendars cache their days.
    index_of = None
    if not minutes:
        first_day = min([v for v in [dd_inst] + [f for f, _ in finishes]
                         + [helpers['instant_of']((t.get(k) or '').strip())
                            for t in work for k in ('early_start_date', 'act_start_date',
                                                    'act_end_date')] if v > 0] or [last])
        index_of = _calendar_indexes(first_day - 400, last + 800)
        helpers = _fast_helpers(helpers, index_of)
    retained = schedule_mode == 'retained_logic'
    carried = (carried_instants(work, pred_map, task_map, cal_map, helpers, lag_role,
                                dd_inst, ss_lag_from)
               if retained else {})
    fed = (_fed_at_the_data_date(pred_map, task_map, carried, cal_map, helpers, lag_role,
                                 dd_inst, ss_lag_from)
           if retained and dd_inst > 0 else set())

    def _ties_at_the_data_date(succ, p, pt, observed):
        """A completed predecessor that carries unfinished work's date to the
        data date itself hands that date on, tied with the data date's.
        predecessor_drive (shared with the validator) drops a drive that ends
        at the data date, since it adds nothing to the validator's floor; for
        the trace it is a tie to follow (review, 27-Sep-2026)."""
        if pt.get('task_id', '') not in fed:
            return False
        rtype = PRED_TYPE_MAP.get(p.get('pred_type', ''), 'FS')
        lag_cid = (pt.get('clndr_id', '') if lag_role == 'predecessor'
                   else succ.get('clndr_id', ''))
        lag_cal = cal_map.get(lag_cid)
        act = helpers['instant_of']((pt.get('act_start_date') if rtype in ('SS', 'SF')
                                     else pt.get('act_end_date')) or '')
        if helpers['unexpired_lag'](act, _amount(helpers)(p.get('lag_hr_cnt', 0), cal_map, lag_cid),
                                    lag_cal, dd_inst) > 0:
            return False   # a lag still running lands past the data date: no tie
        cid = succ.get('clndr_id', '')
        cal = cal_map.get(cid)
        cand = helpers['snap_fwd'](dd_inst, cal, alerts=[], ctx='tie')
        if rtype in ('FF', 'SF'):
            cand = helpers['retreat_workdays'](
                cand, _amount(helpers)(succ.get('remain_drtn_hr_cnt', 0), cal_map, cid), cal,
                alerts=[], ctx='tie')
        if minutes:
            return helpers['reaches'](cand, observed, cal) and helpers['reaches'](observed, cand, cal)
        return cand == observed

    def _drives_open(succ, p, observed):
        # A Mandatory Start or Finish sets its activity's date whatever the
        # logic says: no relationship into it drives it, even one that lands
        # on its date (review, 27-Sep-2026: that tie put its predecessor on
        # the path with slack to spare).
        if _hard_constrained(succ):
            return False
        if (minutes and schedule_mode == 'retained_logic' and ss_lag_from == 'actual_start'
                and PRED_TYPE_MAP.get(p.get('pred_type', ''), 'FS') == 'SS'):
            pt = task_map[p.get('pred_task_id', '')]
            if (pt.get('status_code', '') == ACTIVE_STATUS
                    and (pt.get('act_start_date') or '').strip()):
                # Under "lag from Actual Start" an SS link out of work under
                # way is laid from the data date (predecessor_drive), and P6
                # counts the data date, not the predecessor, as what drives
                # the successor: its Longest Path starts at the successor
                # (one P6 project, SSL2, 16-Oct-2026).
                return False
        d = predecessor_drive(succ, [p], task_map, cal_map, helpers, lag_role,
                              schedule_mode, carried, dd_inst, ss_lag_from)
        if d <= 0:
            pt = task_map[p.get('pred_task_id', '')]
            return _is_complete(pt) and _ties_at_the_data_date(succ, p, pt, observed)
        if minutes:
            return helpers['reaches'](d, observed, cal_map.get(succ.get('clndr_id', '')))
        return d >= observed

    on_path = set()
    through = set()
    stack = [t.get('task_id', '') for t in terminals]
    seen_carriers = set()
    while stack:
        tid = stack.pop()
        if tid in on_path:
            continue
        succ = task_map[tid]
        on_path.add(tid)
        observed = stored_start(succ, cal_map, helpers)
        if observed <= 0:
            continue
        for p in pred_map.get(tid, []):
            pid = p.get('pred_task_id', '')
            pt = task_map[pid]
            if not _drives_open(succ, p, observed):
                continue
            if not _is_complete(pt):
                if pid not in on_path:
                    stack.append(pid)
                continue
            # A completed predecessor drives only through a date it carries
            # from unfinished work (retained logic); follow the carry back. At
            # the data date itself only a carrier that unfinished work feeds
            # there is followed: the data date alone stamps every other one.
            carriers = [pid]
            while carriers:
                cid_ = carriers.pop()
                c_at = carried.get(cid_, 0)
                if (cid_ in seen_carriers or c_at < dd_inst
                        or (c_at == dd_inst and cid_ not in fed) or c_at <= 0):
                    continue
                seen_carriers.add(cid_)
                through.add(cid_)
                crow = task_map[cid_]
                for cp in pred_map.get(cid_, []):
                    cpt = task_map[cp.get('pred_task_id', '')]
                    got = _carry_drive(cp, cpt, crow, carried, cal_map, helpers,
                                       lag_role, dd_inst, ss_lag_from)
                    if got != carried[cid_]:
                        continue
                    if _is_complete(cpt):
                        carriers.append(cp.get('pred_task_id', ''))
                    elif cp.get('pred_task_id', '') not in on_path:
                        stack.append(cp.get('pred_task_id', ''))
    slack = ({} if minutes else
             _slack_to_path(work, task_map, pred_map, cal_map, helpers, lag_role,
                            schedule_mode, ss_lag_from, dd_inst, carried, last, index_of))
    # An activity that cannot slip a working day without moving the finish is
    # on the path, chain or no chain: where the working-day reading cannot
    # tell two instants apart (a finish at one calendar's close, the forecast
    # finish at another's), no relationship reaches it, yet any delay to it
    # moves the finish. So the box never counts an activity with no slack as
    # off the path (review, 27-Sep-2026).
    joined = sorted(tid for tid, v in slack.items() if v <= 0 and tid not in on_path)
    on_path.update(joined)
    out['traced'] = True
    out['codes'] = sorted(_task_code(task_map[t]) for t in on_path
                          if task_map[t].get('task_type', '') not in passing)
    out['passed_through'] = sorted(_task_code(task_map[t]) for t in on_path
                                   if task_map[t].get('task_type', '') in passing)
    out['terminals'] = sorted(_task_code(t) for t in terminals)
    out['carriers'] = sorted(_task_code(task_map[t]) for t in through)
    out['joined_by_slack'] = sorted(_task_code(task_map[t]) for t in joined)
    out['slack'] = {_task_code(task_map[tid]): v for tid, v in slack.items()}
    out['sub_day'] = {
        'durations': sum(1 for t in open_rows
                         if _part_day(t.get('remain_drtn_hr_cnt'),
                                      cal_map.get(t.get('clndr_id', '')))),
        'lags': sum(1 for links in pred_map.values() for p in links
                    if _part_day(p.get('lag_hr_cnt'), cal_map.get(
                        task_map[p['pred_task_id']].get('clndr_id', '')
                        if lag_role == 'predecessor'
                        else task_map[p['task_id']].get('clndr_id', '')))),
    }
    return out


# ─────────────────────────────────────────────────────────────────────
# Slack to the driving path: the backward pass
# ─────────────────────────────────────────────────────────────────────

# Working days: a bound further out than this in either direction bounds
# nothing (about twenty years of working days).
_SHIFT_LIMIT = 5000


def _max_shift(ok, guess, lo_lim=-_SHIFT_LIMIT, hi_lim=_SHIFT_LIMIT):
    """The largest whole k in [lo_lim, hi_lim] for which ``ok(k)`` holds,
    ``ok`` being true up to some k and false beyond it, searched outward from
    ``guess`` and then halved down. None when ``ok`` still holds at
    ``hi_lim`` (the bound is out of reach) or fails even at ``lo_lim``."""
    g = max(lo_lim, min(hi_lim, int(guess)))
    if ok(g):
        lo, step = g, 1
        while True:
            hi = lo + step
            if hi >= hi_lim:
                if ok(hi_lim):
                    return None
                hi = hi_lim
                break
            if not ok(hi):
                break
            lo, step = hi, step * 2
    else:
        hi, step = g, 1
        while True:
            lo = hi - step
            if lo <= lo_lim:
                if not ok(lo_lim):
                    return None
                lo = lo_lim
                break
            if ok(lo):
                break
            hi, step = lo, step * 2
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if ok(mid):
            lo = mid
        else:
            hi = mid
    return lo


def _day_numbers(date_strings, epoch):
    """Day numbers of the exception dates that cpm._is_work_day would match:
    exactly 'YYYY-MM-DD' (its strftime form); anything else never matches."""
    out = set()
    for s in date_strings or ():
        if not isinstance(s, str) or len(s) != 10:
            continue
        try:
            d = _date(int(s[0:4]), int(s[5:7]), int(s[8:10]))
        except ValueError:
            continue
        if d.strftime('%Y-%m-%d') == s:
            out.add(d.toordinal() - epoch)
    return out


def _calendar_indexes(lo, hi):
    """index_of(calendar_info) -> its _WorkDays over [lo, hi], built on first
    use and kept for the trace, or None without a calendar."""
    cpm = _canonical_cpm()
    built = {}

    def index_of(cal):
        if not cal:
            return None
        key = id(cal)
        if key not in built:
            built[key] = (_WorkDays(cal, lo, hi, cpm), cal)   # hold cal: its id stays its own
        return built[key][0]
    return index_of


def _fast_helpers(helpers, index_of):
    """``helpers`` with the calendar walks the drive arithmetic makes
    (``snap_fwd``, ``retreat_workdays``, ``lag_from_instant``,
    ``unexpired_lag``) answered from
    the working-day indexes: the engine's own rules, step for step, and the
    engine itself for anything outside an index or without a calendar."""
    cpm = _canonical_cpm()
    half_up = cpm._round_half_up
    eng_snap = helpers['snap_fwd']
    eng_retreat = helpers['retreat_workdays']
    eng_lag = helpers['lag_from_instant']
    eng_unexpired = helpers['unexpired_lag']

    def snap_fwd(num, calendar_info, *, alerts, ctx):
        w = index_of(calendar_info) if num > 0 else None
        if w is None:
            return eng_snap(num, calendar_info, alerts=alerts, ctx=ctx)
        return w.advance(num, 0)

    def retreat_workdays(end_num, n_days, calendar_info, *, alerts, ctx):
        w = index_of(calendar_info) if end_num > 0 else None
        if w is None:
            return eng_retreat(end_num, n_days, calendar_info, alerts=alerts, ctx=ctx)
        n = half_up(n_days)
        # subtract_work_days: n == 0 snaps back to a working day
        return w.snap_bwd(end_num) if n == 0 else w.advance(end_num, -n)

    def lag_from_instant(instant, lag, lag_cal, *, alerts, ctx):
        w = index_of(lag_cal) if instant > 0 else None
        if w is None:
            return eng_lag(instant, lag, lag_cal, alerts=alerts, ctx=ctx)
        n = half_up(lag)
        if n == 0:
            return instant
        if n > 0:
            return w.close_of(w.advance(w.advance(instant, 0), n))
        return w.advance(instant, n)

    def unexpired_lag(actual_instant, lag, lag_cal, dd_num):
        # cpm._unexpired_lag: the lag less the working days of the lag
        # calendar from the actual date to the data date, never below zero.
        w = index_of(lag_cal)
        if (lag <= 0 or actual_instant <= 0 or dd_num <= 0 or actual_instant >= dd_num
                or w is None or not w._inside(actual_instant - 1, dd_num - 1)):
            return eng_unexpired(actual_instant, lag, lag_cal, dd_num)
        return max(0, lag - w.count(actual_instant - 1, dd_num - 1))

    fast = dict(helpers)
    fast.update(snap_fwd=snap_fwd, retreat_workdays=retreat_workdays,
                lag_from_instant=lag_from_instant, unexpired_lag=unexpired_lag)
    return fast


def _fed_at_the_data_date(pred_map, task_map, carried, cal_map, helpers, lag_role, dd_inst,
                          ss_lag_from):
    """The completed activities that carry unfinished work's date to the data
    date itself (retained logic): an unfinished predecessor hands one exactly
    the data date, or a completed one of these hands it on. The data date
    stamps every completed activity; only these carry a tie with it."""
    succ_links = {}
    for links in pred_map.values():
        for p in links:
            succ_links.setdefault(p.get('pred_task_id', ''), []).append(p)
    stack = []
    for tid, links in pred_map.items():
        row = task_map[tid]
        if not _is_complete(row) or carried.get(tid, 0) != dd_inst:
            continue
        if any(not _is_complete(task_map[p.get('pred_task_id', '')])
               and _carry_drive(p, task_map[p.get('pred_task_id', '')], row, carried, cal_map,
                                helpers, lag_role, dd_inst, ss_lag_from) == dd_inst
               for p in links):
            stack.append(tid)
    fed = set()
    while stack:
        cid_ = stack.pop()
        if cid_ in fed:
            continue
        fed.add(cid_)
        for p in succ_links.get(cid_, ()):
            sid = p.get('task_id', '')
            srow = task_map[sid]
            if (sid not in fed and _is_complete(srow) and carried.get(sid, 0) == dd_inst
                    and _carry_drive(p, task_map[cid_], srow, carried, cal_map, helpers,
                                     lag_role, dd_inst, ss_lag_from) == dd_inst):
                stack.append(sid)
    return fed


class _WorkDays:
    """One calendar's working days as sorted day numbers over [lo, hi]: the
    engine's own day walks (add_work_days, subtract_work_days,
    _count_work_days_between, _boundary_to_instant) answered by bisection
    inside the range, and by the engine itself outside it. The backward pass
    shifts every activity many times, and the engine walks day by day on any
    calendar with holidays."""

    def __init__(self, cal, lo, hi, cpm):
        self.cal, self.lo, self.hi, self.cpm = cal, lo, hi, cpm
        # cpm._is_work_day, day by day, without its date string per day: an
        # exception date (always 'YYYY-MM-DD', as the engine compares it)
        # becomes its day number once; a holiday wins, then a special
        # workday, then the weekly pattern (P6 weekday numbers, 0 = Sunday).
        wd, hol, spw = cpm._calendar_exceptions(cal)
        ep = cpm._epoch_ordinal()
        hol_n, spw_n = _day_numbers(hol, ep), _day_numbers(spw, ep)
        first = _date.fromordinal(lo + ep).weekday()   # Python: Monday = 0
        self.days = [n for i, n in enumerate(range(lo, hi + 1))
                     if n not in hol_n and (n in spw_n or (first + i + 1) % 7 in wd)]

    def _inside(self, a, b=None):
        if not self.days or not self.lo <= a <= self.hi:
            return False
        return b is None or self.lo <= b <= self.hi

    def advance(self, n, k):
        """add_work_days / subtract_work_days by k (k=0 snaps forward)."""
        d = self.days
        if d and self.lo <= n <= self.hi:
            if k == 0:
                i = bisect.bisect_left(d, n)
            elif k > 0:
                i = bisect.bisect_right(d, n) + k - 1
            else:
                i = bisect.bisect_left(d, n) + k
            if 0 <= i < len(d):
                return d[i]
        return self.cpm._advance_workdays(n, k, self.cal, alerts=[], ctx='slack')

    def snap_fwd(self, n):
        return self.advance(n, 0)

    def snap_bwd(self, n):
        d = self.days
        if self._inside(n):
            i = bisect.bisect_right(d, n) - 1
            if 0 <= i < len(d):
                return d[i]
        return self.cpm._snap_bwd(n, self.cal, alerts=[], ctx='slack')

    def count(self, a, b):
        """_count_work_days_between: working days in (a, b], signed."""
        if self._inside(a, b):
            return bisect.bisect_right(self.days, b) - bisect.bisect_right(self.days, a)
        return self.cpm._count_work_days_between(a, b, self.cal)

    def close_of(self, boundary):
        """_boundary_to_instant: the close of the last working day before a
        working-day boundary."""
        return self.advance(boundary, -1) + 1


def _slack_to_path(work, task_map, pred_map, cal_map, helpers, lag_role, schedule_mode,
                   ss_lag_from, dd_inst, carried, latest, index_of):
    """Slack to the driving path of every unfinished activity with early
    dates, in working days on its own calendar: {task_id: whole days}.
    ``index_of`` gives a calendar's working-day index (_calendar_indexes).

    A backward pass over the stored dates in reverse logic order. Each
    activity's slack is the largest whole number of its own working days it
    can be shifted by (its start and finish together) such that
      * its finish is no later than the latest early finish, and
      * for each successor link, the drive the trace's own arithmetic
        computes from the shifted dates lands no later than the successor's
        late start: its stored start shifted by its own slack. A link whose
        drive already lands past that stored start (the row is behind its own
        logic) is measured from where it lands, so it leaves no working day
        to spare and never fewer, as the trace reads it.
    A link into a Mandatory Start or Finish carries no delay. Under retained
    logic a completed successor passes delay through: the latest date it can
    carry without moving its own successors bounds the links into it. An SS
    link off a started predecessor laid from the data date ("lag from Actual
    Start") does not move with the predecessor and bounds nothing. No
    late-date constraint and no Must Finish By takes part."""
    retained = schedule_mode == 'retained_logic'
    succ_map = {}
    for links in pred_map.values():
        for p in links:
            succ_map.setdefault(p.get('pred_task_id', ''), []).append(p)

    raw = {}
    for t in work:
        if _is_complete(t):
            continue
        f = helpers['instant_of']((t.get('early_end_date') or '').strip())
        s = stored_start(t, cal_map, helpers)
        cid = t.get('clndr_id', '')
        if f <= 0 or s <= 0 or cid not in cal_map:
            continue
        raw[t.get('task_id', '')] = (s, f, cid)
    if not raw:
        return {}
    base = {}
    for tid, (s, f, cid) in raw.items():
        w = index_of(cal_map[cid])
        base[tid] = (s, w.snap_fwd(s), f, w.snap_fwd(f), w)

    shifts = {}

    def shifted(t, k):
        """t's row moved k working days on its own calendar, start and finish
        together, carrying only what the drive arithmetic reads (kept, since
        each of an activity's links asks for much the same shifts)."""
        if k == 0:
            return t
        key = (t.get('task_id', ''), k)
        row = shifts.get(key)
        if row is None:
            s, sb, f, fb, w = base[key[0]]
            row = {f_: t.get(f_, '') for f_ in ('task_id', 'status_code', 'clndr_id',
                                                 'act_start_date', 'act_end_date',
                                                 'remain_drtn_hr_cnt')}
            row['early_start_date'] = row['restart_date'] = helpers['num_to_date'](
                w.advance(sb, k))
            row['early_end_date'] = helpers['num_to_date'](w.close_of(w.advance(fb, k)))
            shifts[key] = row
        return row

    def late_start(sid, slack):
        s, sb, f, fb, w = base[sid]
        return s if slack == 0 else w.advance(sb, slack)

    def into_open(succ, link, prow, carried_map):
        return predecessor_drive(succ, [link], {prow.get('task_id', ''): prow}, cal_map,
                                 helpers, lag_role, schedule_mode, carried_map, dd_inst,
                                 ss_lag_from)

    def into_done(done_row, link, prow, carried_map):
        return _carry_drive(link, prow, done_row, carried_map, cal_map, helpers, lag_role,
                            dd_inst, ss_lag_from)

    def anchored_on_the_data_date(prow, link):
        return (retained and dd_inst > 0 and ss_lag_from == 'actual_start'
                and PRED_TYPE_MAP.get(link.get('pred_type', ''), 'FS') == 'SS'
                and prow.get('status_code', '') == ACTIVE_STATUS
                and (prow.get('act_start_date') or '').strip())

    def bound(succ_id, drive_now):
        """The latest a drive into this unfinished successor may land: its late
        start, or, for a drive already past its stored start, the drive
        itself moved on by the successor's slack."""
        ls = late_start(succ_id, slack[succ_id])
        if drive_now > base[succ_id][0]:
            w = base[succ_id][4]
            ls = max(ls, drive_now if slack[succ_id] == 0
                     else w.advance(drive_now, slack[succ_id]))
        return ls

    # Completed rows matter only where they can carry unfinished work's dates:
    # those reached from an unfinished activity through completed successors.
    carriers = set()
    if retained:
        frontier = [p.get('task_id', '') for tid in raw for p in succ_map.get(tid, [])
                    if _is_complete(task_map[p.get('task_id', '')])]
        while frontier:
            cid_ = frontier.pop()
            if cid_ in carriers:
                continue
            carriers.add(cid_)
            frontier += [p.get('task_id', '') for p in succ_map.get(cid_, [])
                         if _is_complete(task_map[p.get('task_id', '')])]

    # Reverse logic order: every successor before its predecessors. Rows on
    # or behind a loop (no logic order) come last, with what is known.
    outdeg = {tid: len(succ_map.get(tid, [])) for tid in task_map}
    order = [tid for tid, n in outdeg.items() if n == 0]
    i = 0
    while i < len(order):
        for p in pred_map.get(order[i], []):
            pid = p.get('pred_task_id', '')
            outdeg[pid] -= 1
            if outdeg[pid] == 0:
                order.append(pid)
        i += 1
    order += sorted(tid for tid, n in outdeg.items() if n > 0)

    slack = {}
    latest_carry = {}
    hi_inst = latest + 2 * _SHIFT_LIMIT
    for tid in order:
        t = task_map[tid]
        if _is_complete(t):
            if tid not in carriers:
                continue
            best = None
            now = carried.get(tid, 0)
            for p in succ_map.get(tid, []):
                sid = p.get('task_id', '')
                s_row = task_map[sid]
                if _is_complete(s_row):
                    cap = latest_carry.get(sid)
                    if cap is None:
                        continue
                    ok = (lambda y, s_row=s_row, p=p, cap=cap, t=t, tid=tid:
                          into_done(s_row, p, t, {tid: y}) <= cap)
                else:
                    if sid not in slack or _hard_constrained(s_row):
                        continue
                    cap = bound(sid, into_open(s_row, p, t, {tid: now}))
                    ok = (lambda y, s_row=s_row, p=p, cap=cap, t=t, tid=tid:
                          into_open(s_row, p, t, {tid: y}) <= cap)
                y = _max_shift(ok, max(now, dd_inst, cap), lo_lim=0, hi_lim=hi_inst)
                if y is not None:
                    best = y if best is None else min(best, y)
            if best is not None:
                latest_carry[tid] = best
            continue
        if tid not in base:
            continue
        s0, sb, f0, fb, w = base[tid]
        seed = w.advance(w.snap_bwd(latest - 1), 1)
        k = _max_shift(lambda k, f0=f0, fb=fb, w=w:
                       (f0 if k == 0 else w.close_of(w.advance(fb, k))) <= latest,
                       w.count(fb, seed))
        bounds = [k if k is not None else 0]
        for p in succ_map.get(tid, []):
            sid = p.get('task_id', '')
            s_row = task_map[sid]
            if anchored_on_the_data_date(t, p):
                continue
            if _is_complete(s_row):
                cap = latest_carry.get(sid)
                if not retained or cap is None:
                    continue
                now = into_done(s_row, p, t, carried)
                if now <= 0:
                    continue
                ok = (lambda k, s_row=s_row, p=p, cap=cap, t=t:
                      into_done(s_row, p, shifted(t, k), carried) <= cap)
                guess = w.count(now, cap) if cap > 0 else 0
            else:
                if sid not in slack or _hard_constrained(s_row):
                    continue
                now = into_open(s_row, p, t, carried)
                if now <= 0:
                    continue
                cap = bound(sid, now)
                ok = (lambda k, s_row=s_row, p=p, cap=cap, t=t:
                      into_open(s_row, p, shifted(t, k), carried) <= cap)
                guess = base[sid][4].count(now, cap)
            k = _max_shift(ok, guess)
            if k is not None:
                bounds.append(k)
        slack[tid] = min(bounds)
    return slack


def _lag_token(data, proj_id, options):
    """The file's relationship lag calendar setting, raw: the options' own
    token when given, else SCHEDOPTIONS', else P6's default. P6 23.12.1 lays a
    blank setting on the successor calendar and a file with no SCHEDOPTIONS
    table on the predecessor calendar (measured 11-Oct-2026, as
    tia_builder._detect_schedule_options reads them)."""
    tok = (options or {}).get('relationship_lag_calendar')
    if tok:
        return str(tok).strip()
    from xer_parser import get_table
    rows = get_table(data, 'SCHEDOPTIONS') or []
    if not rows:
        return 'rcal_Predecessor'
    row = next((r for r in rows if r.get('proj_id', '') == proj_id), rows[0])
    return (row.get('sched_calendar_on_relationship_lag') or '').strip() or 'rcal_Successor'


def trace_schedule(data, proj_id, *, options=None, cal_map=None, resolution='day'):
    """``trace`` on one project of a parsed XER (xer_parser.parse_xer).

    ``options`` is tia_builder._detect_schedule_options(data, proj_id), or
    None for P6's defaults (retained logic, the predecessor's calendar for
    lags, start-to-start lag from the early start); the result says which
    (``options_source``). Either way a lag calendar the trace does not walk
    (P6's 24-hour or project setting, read from the options' raw token or the
    file's own SCHEDOPTIONS) stops the trace when the file has a lag.
    ``cal_map`` is the file's xer_parser.get_calendar_map when the caller
    already has it (decoding a file's calendars can take a second on a file
    with hundreds of them); None decodes it here. ``resolution`` is trace's:
    'minute' for P6's Longest Path flag (16-Oct-2026)."""
    from xer_parser import (get_table, get_calendar_map, resolve_task_calendars,
                            with_resolved_calendars)
    tasks = [t for t in with_resolved_calendars(get_table(data, 'TASK') or [],
                                                resolve_task_calendars(data))
             if t.get('proj_id', '') == proj_id]
    ids = {t.get('task_id', '') for t in tasks}
    preds = [p for p in (get_table(data, 'TASKPRED') or [])
             if p.get('task_id', '') in ids and p.get('pred_task_id', '') in ids]
    proj = next((p for p in (get_table(data, 'PROJECT') or [])
                 if p.get('proj_id', '') == proj_id), {}) or {}
    opts = options or {}
    role = LAG_CALENDAR_ROLES.get(_lag_token(data, proj_id, options))
    if role in ('predecessor', 'successor'):
        role = opts.get('lag_calendar_role') or 'predecessor'
    res = trace(tasks, preds, cal_map if cal_map is not None else (get_calendar_map(data) or {}),
                lag_role=role or opts.get('lag_calendar_role') or 'predecessor',
                schedule_mode=opts.get('schedule_mode') or 'retained_logic',
                ss_lag_from=opts.get('ss_lag_from') or 'early_start',
                data_date=(proj.get('last_recalc_date') or '').strip(),
                resolution=resolution)
    res['options_source'] = ('SCHEDOPTIONS' if options else
                             "P6's defaults (retained logic, predecessor lag "
                             'calendar, SS lag from early start)')
    return res
