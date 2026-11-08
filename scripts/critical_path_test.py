"""DCMA #12, the Critical Path Test, run as the pamphlet describes it.

DCMA-EA PAM 200.1 #12: insert a large delay (commonly 600 working days) on an
incomplete task on the critical path, recalculate, and check that the project
completion moves by the same amount. A critical path that is logic-driven end
to end passes; one broken by a constraint, an open end or a missing link does
not carry the delay through, and fails.

The schedule is recalculated by CPP's CPM engine (_cpp_common/scripts/cpm.py,
crossvalidated against P6 Professional's own F9) on the network the validator
already builds for it (cp_validator._driver_chain_network) with the file's own
scheduling options (tia_builder._detect_schedule_options). Twice: as filed, and
with the delay added to the test activity's remaining duration.

The test activity (DCMA definition #12): walk the completion activity's driving
predecessors back through the recalculated network; it is the incomplete
ordinary activity on that driving path nearest the data date whose finish
drives the next activity along it (a duration delay moves a finish, so it
cannot pass along a Start-to-Start link). Where the delay cannot be inserted
on it (its finish set by an expected finish or its resources), the next one
along is tried, up to MAX_TRIES. The completion's move is measured as working
time on the test activity's own calendar, the calendar the 600 working days
were added on.

Without the engine (a public copy of this repository, which does not ship it)
the test is not run and #12 is decided only where the answer is certain, as
before; the result says which.
"""
import copy
from datetime import datetime

DELAY_WORKING_DAYS = 600
# The completion must move by the delay, less up to one working day for the
# rounding of lags and part days across calendars.
SLIP_TOLERANCE_DAYS = 1.0
# How many activities along the driving path are tried when a delay cannot be
# inserted on one (its finish set by an expected finish or its resources).
MAX_TRIES = 3
# The test runs the engine twice on the whole network. Real schedules of about
# 3,000 activities take 10 to 15 seconds; past this size the run is not made,
# so no tool that calls it can stall (8-Nov-26), and the result says why.
MAX_NETWORK_ACTIVITIES = 5000
# The as-filed recalculation's time past which the delayed one is not made.
BASE_RUN_SECONDS_LIMIT = 20.0
# The whole test's time: past it the delayed recalculations are stopped.
TEST_SECONDS_LIMIT = 60.0
# Up to this size the recalculations run in this process: a real schedule of
# this size takes a few seconds, and the test suites call it hundreds of times.
# Above it each one runs in a child process that is stopped at the time limit,
# so a network the engine is slow on cannot hold up the tool that asked (8-Nov-
# 26: floats of thousands of days took the as-filed run of a 3,000-activity
# synthetic file to 112 seconds, and a limit read only after the run had
# finished could not stop it).
IN_PROCESS_ACTIVITIES = 500

# The child: one compute_cpm call, handing back only what the test reads.
_CHILD_CODE = """
import pickle, sys
where, acts, rels, kwargs = pickle.load(sys.stdin.buffer)
sys.path.insert(0, where)
import cpm
try:
    res = cpm.compute_cpm(acts, rels, **kwargs)
    keep = ('early_finish_dt', 'ef_date', 'driving_predecessor')
    out = ('ok', {'nodes': {c: {k: n.get(k) for k in keep}
                            for c, n in (res.get('nodes') or {}).items()}})
except ValueError as exc:
    out = ('ValueError', str(exc))
sys.stdout.buffer.write(pickle.dumps(out, protocol=pickle.HIGHEST_PROTOCOL))
"""


class _TooSlow(Exception):
    """A recalculation run in a child process passed its time limit and was stopped."""


def _recalc(compute_cpm, acts, rels, kwargs, seconds, in_child):
    """compute_cpm(acts, rels, **kwargs); in a child process, stopped after
    `seconds` (raises _TooSlow). Raises ValueError as compute_cpm does."""
    if not in_child:
        return compute_cpm(acts, rels, **kwargs)
    import os
    import pickle
    import subprocess
    import sys
    import cpm
    payload = pickle.dumps((os.path.dirname(os.path.abspath(cpm.__file__)), acts, rels, kwargs),
                           protocol=pickle.HIGHEST_PROTOCOL)
    try:
        proc = subprocess.run([sys.executable, '-I', '-c', _CHILD_CODE], input=payload,
                              capture_output=True, timeout=max(1.0, seconds),
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except subprocess.TimeoutExpired:
        raise _TooSlow()
    if proc.returncode != 0:
        tail = (proc.stderr or b'').decode('utf-8', 'replace').strip().splitlines()
        raise RuntimeError(tail[-1] if tail else 'exit code %d' % proc.returncode)
    kind, value = pickle.loads(proc.stdout)
    if kind == 'ValueError':
        raise ValueError(value)
    return value


def _can_run_in_child(acts, rels, kwargs):
    """A child process can take this network: there is an interpreter to start
    and the network pickles (it is plain data; anything else runs in process)."""
    import pickle
    import sys
    if not sys.executable:
        return False
    try:
        pickle.dumps((acts, rels, kwargs), protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        return False
    return True
# P6's names for the constraints, for the sentence that says where a delay is lost.
CONSTRAINT_NAMES = {
    'CS_MANDSTART': 'Mandatory Start', 'CS_MANDFIN': 'Mandatory Finish',
    'CS_MSO': 'Start On', 'CS_MEO': 'Finish On',
    'CS_MSOA': 'Start On or After', 'CS_MEOA': 'Finish On or After',
    'CS_MSOB': 'Start On or Before', 'CS_MEOB': 'Finish On or Before',
    'CS_ALAP': 'As Late As Possible',
}


def _constraints_of(task):
    """The constraints filed on a task, as P6 names them with their dates."""
    out = []
    for kind, date in (('cstr_type', 'cstr_date'), ('cstr_type2', 'cstr_date2')):
        ctype = (task.get(kind) or '').strip()
        if not ctype:
            continue
        name = CONSTRAINT_NAMES.get(ctype, ctype)
        when = (task.get(date) or '').strip()
        out.append('%s of %s' % (name, when) if when else name)
    return out


def _shift_working_days(dt, n, cal):
    """dt ('YYYY-MM-DD HH:MM') moved by n working days on cal, keeping its time."""
    try:
        from cpm import add_work_days
    except Exception:
        return None
    s = str(dt or '').strip()
    if len(s) < 10:
        return None
    day = add_work_days(s[:10], n, cal)
    return (str(day)[:10] + s[10:]) if day else None


def _parse(dt):
    s = str(dt or '').strip()
    for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(s[:16] if fmt.endswith('%M') else s[:10], fmt)
        except ValueError:
            continue
    return None


def run(data, proj_id, work_tasks, preds, task_map, cal_map, completion_task,
        is_ordinary, is_complete, working_days_between):
    """Run the test. Returns a dict:

    ``{'ran': False, 'reason': ...}`` when the engine is not available or the
    network cannot be recalculated; otherwise ``{'ran': True, 'status':
    'PASS' | 'FAIL' | 'NS', 'message', 'test_activity', 'slip_days',
    'delay_days', ...}``.

    ``is_ordinary``, ``is_complete`` and ``working_days_between`` are the DCMA
    engine's own (dcma14), passed in so this module reads activities exactly as
    the definition does.
    """
    try:
        from cpm import compute_cpm
        import cp_validator as cv
    except Exception as exc:  # the engine is not part of this installation
        return {'ran': False, 'reason': 'the CPM engine is not available here (%s)'
                % (exc.__class__.__name__,)}
    try:
        opts = cv._detect_schedule_options(data, proj_id)
        net = cv._driver_chain_network(
            work_tasks, preds, task_map, cal_map, opts.get('lag_calendar_role') or 'predecessor',
            assignments=cv._assignment_counts(data), rsrc_assignments=cv._rd_assignments(data))
    except Exception as exc:
        return {'ran': False, 'reason': 'the network could not be built for a recalculation (%s)'
                % (exc.__class__.__name__,)}
    kwargs = dict(
        data_date=str((next((p for p in (data.get('tables', {}).get('PROJECT', {}).get('records') or [])
                             if p.get('proj_id', '') == proj_id), {}) or {}).get('last_recalc_date', '') or ''),
        cal_map=cal_map,
        schedule_mode=opts['schedule_mode'],
        relationship_lag_calendar=opts['relationship_lag_calendar'],
        ss_lag_from=opts.get('ss_lag_from', 'early_start'),
        project_finish=opts.get('project_finish', ''),
        use_expected_finish=opts.get('use_expected_finish', False),
        use_external_dates=opts.get('use_external_dates', True),
        float_type=opts.get('float_type', 'FT_FF'),
        open_critical=opts.get('open_critical', False),
        multiple_float_paths=opts.get('multiple_float_paths', False),
        float_path_end=opts.get('float_path_end'),
        project_calendar=opts.get('lag_project_calendar', ''),
    )
    acts, rels, id_to_code = net['activities'], net['relationships'], net['id_to_code']
    if len(acts) > MAX_NETWORK_ACTIVITIES:
        return {'ran': False, 'reason': ('the network has %d activities, more than the %d the test is run on '
                                         'in the time this tool allows' % (len(acts), MAX_NETWORK_ACTIVITIES))}
    import time as _time
    _t0 = _time.time()
    in_child = len(acts) > IN_PROCESS_ACTIVITIES and _can_run_in_child(acts, rels, kwargs)
    try:
        base = _recalc(compute_cpm, acts, rels, kwargs, BASE_RUN_SECONDS_LIMIT, in_child)
    except ValueError as exc:
        return {'ran': False, 'reason': 'the schedule could not be recalculated (%s)' % exc}
    except _TooSlow:
        return {'ran': False, 'reason': ('the recalculation as filed did not finish within %.0f seconds, so the '
                                         'test is not run in the time this tool allows' % BASE_RUN_SECONDS_LIMIT)}
    except RuntimeError as exc:
        return {'ran': False, 'reason': 'the schedule could not be recalculated (%s)' % exc}
    _base_seconds = _time.time() - _t0
    if _base_seconds > BASE_RUN_SECONDS_LIMIT:
        # The delayed run takes as long again or longer (its dates reach years
        # further); past this the test is not finished, and says so.
        return {'ran': False, 'reason': ('the recalculation as filed took %.0f seconds, so the delayed one '
                                         'is not run in the time this tool allows' % _base_seconds)}

    comp_code = id_to_code.get(completion_task.get('task_id', ''), '')
    nodes = base.get('nodes') or {}
    if comp_code not in nodes:
        return {'ran': False, 'reason': 'the completion activity is not in the recalculated network'}
    by_code = {id_to_code.get(t.get('task_id', ''), ''): t for t in work_tasks}

    # The completion's driving path, back from the completion.
    chain, seen, code = [], set(), comp_code
    while code and code in nodes and code not in seen:
        seen.add(code)
        chain.append(code)
        dp = nodes[code].get('driving_predecessor') or {}
        code = dp.get('code')
    start_driver = (nodes[chain[-1]].get('driving_predecessor') or {}).get('type', '')
    # The completion itself is not the test activity: delaying it moves it
    # trivially, which shows nothing about the path that drives it.
    # The delay is added to the test activity's remaining duration, which
    # moves its FINISH, so its link to the next activity on the driving path
    # must be one its finish drives (Finish-to-Start or Finish-to-Finish). An
    # activity that drives the path only through its start (Start-to-Start)
    # would not pass a duration delay on, and its "failure" would say nothing
    # about the schedule (8-Nov-26: real schedules read 579 of 600 that way).
    next_on_path = {chain[i]: chain[i - 1] for i in range(1, len(chain))}

    def _finish_driven(c):
        nxt = next_on_path.get(c)
        kind = ((nodes.get(nxt) or {}).get('driving_predecessor') or {}).get('type', '') if nxt else ''
        return kind in ('FS', 'FF')

    def _open_ordinary(c):
        return c != comp_code and c in by_code and is_ordinary(by_code[c]) and not is_complete(by_code[c])

    candidates = [c for c in chain if _open_ordinary(c) and _finish_driven(c)]
    if not candidates and any(_open_ordinary(c) for c in chain):
        return {'ran': True, 'status': 'NS', 'test_activity': None, 'delay_days': DELAY_WORKING_DAYS,
                'slip_days': None, 'driving_path': list(reversed(chain)),
                'message': ('Critical Path Test NOT SCORED for the completion activity %s: every '
                            'unfinished activity on its driving path drives the next one through its '
                            'start (Start-to-Start), so a delay added to a duration would not be '
                            'carried along it.' % comp_code)}
    if not candidates:
        if start_driver == 'CONSTRAINT':
            return {'ran': True, 'status': 'FAIL', 'test_activity': None, 'delay_days': DELAY_WORKING_DAYS,
                    'slip_days': 0.0, 'driving_path': list(reversed(chain)),
                    'message': ('Critical Path Test FAILS: no unfinished work drives the completion '
                                'activity %s; it is held by a constraint, so a delay inserted on the '
                                'critical path cannot move it.' % comp_code)}
        return {'ran': True, 'status': 'NS', 'test_activity': None, 'delay_days': DELAY_WORKING_DAYS,
                'slip_days': None, 'driving_path': list(reversed(chain)),
                'message': ('Critical Path Test NOT SCORED: no unfinished ordinary activity drives the '
                            'completion activity %s, so there is no critical task to delay.' % comp_code)}
    path = list(reversed(chain))
    date_before = _parse(nodes[comp_code].get('early_finish_dt') or nodes[comp_code].get('ef_date'))
    if date_before is None:
        return {'ran': False, 'reason': 'the recalculation gave the completion no early finish'}
    after, test_code, test_cal, tried = None, None, None, []
    # Nearest the data date first. Where the delay cannot be inserted on an
    # activity (its finish set by an expected finish P6 honours, or by its
    # resources), its finish does not move: the next one along is tried, up
    # to MAX_TRIES (8-Nov-26: an activity with an expected finish under "Use
    # Expected Finish Dates" took no delay at all).
    for cand in list(reversed(candidates))[:MAX_TRIES]:
        task = by_code[cand]
        cal = cal_map.get(task.get('clndr_id', ''), {}) or {}
        hpd = float(cal.get('hours_per_day') or 8.0) or 8.0
        delayed = copy.deepcopy(acts)
        for a in delayed:
            if a.get('code') != cand:
                continue
            a['remaining_hours'] = float(a.get('remaining_hours') or 0.0) + DELAY_WORKING_DAYS * hpd
            a['duration_days'] = float(a.get('duration_days') or 0.0) + DELAY_WORKING_DAYS
            a['remaining_hours_days'] = float(a.get('remaining_hours_days') or 0.0) + DELAY_WORKING_DAYS
            if a.get('remaining_duration') not in (None, ''):
                a['remaining_duration'] = float(a.get('remaining_duration') or 0.0) + DELAY_WORKING_DAYS
            # An expected finish P6 honours sets the finish: it moves with the delay.
            if a.get('expected_finish'):
                moved = _shift_working_days(a['expected_finish'], DELAY_WORKING_DAYS, cal)
                if moved:
                    a['expected_finish'] = moved
            break
        try:
            run_after = _recalc(compute_cpm, delayed, rels, kwargs,
                                TEST_SECONDS_LIMIT - (_time.time() - _t0), in_child)
        except ValueError as exc:
            return {'ran': False, 'reason': 'the delayed schedule could not be recalculated (%s)' % exc}
        except _TooSlow:
            return {'ran': False, 'reason': ('the delayed recalculation did not finish within the %.0f seconds '
                                             'the test is allowed' % TEST_SECONDS_LIMIT)}
        except RuntimeError as exc:
            return {'ran': False, 'reason': 'the delayed schedule could not be recalculated (%s)' % exc}
        t_before = _parse(nodes[cand].get('early_finish_dt') or nodes[cand].get('ef_date'))
        t_node = (run_after.get('nodes') or {}).get(cand) or {}
        t_after = _parse(t_node.get('early_finish_dt') or t_node.get('ef_date'))
        own = working_days_between(t_before, t_after, cal) if (t_before and t_after) else None
        tried.append(cand)
        if own is not None and own >= DELAY_WORKING_DAYS - SLIP_TOLERANCE_DAYS:
            after, test_code, test_cal = run_after, cand, cal
            break
    if after is None:
        return {'ran': True, 'status': 'NS', 'test_activity': None, 'delay_days': DELAY_WORKING_DAYS,
                'slip_days': None, 'driving_path': path, 'tried': tried,
                'message': ('Critical Path Test NOT SCORED: a delay could not be inserted on the unfinished '
                            'activities nearest the data date on the completion\'s driving path (%s): their '
                            'finishes are set by an expected finish or their resources, not their durations.'
                            % ', '.join(tried))}

    after_nodes = after.get('nodes') or {}
    node_after = after_nodes.get(comp_code) or {}
    date_after = _parse(node_after.get('early_finish_dt') or node_after.get('ef_date'))
    if date_after is None:
        return {'ran': False, 'reason': 'the recalculation gave the completion no early finish'}
    slip = working_days_between(date_before, date_after, test_cal)
    if slip is None:
        return {'ran': False, 'reason': 'the completion\'s move could not be measured in working time'}
    slip = round(slip, 2)
    # Is the completion still driven, through the delayed run's driving
    # predecessors, back to the delayed activity? Then the path carries the
    # delay, and a move short of 600 working days is the calendars on the way
    # (a seasonal or shorter-week calendar works fewer days in the later
    # period), not a break in the logic.
    reached, seen2, c2 = False, set(), comp_code
    while c2 and c2 in after_nodes and c2 not in seen2:
        if c2 == test_code:
            reached = True
            break
        seen2.add(c2)
        c2 = (after_nodes[c2].get('driving_predecessor') or {}).get('code')
    full = slip >= DELAY_WORKING_DAYS - SLIP_TOLERANCE_DAYS
    ok = full or (reached and slip > 0)
    lead = ('a delay of %d working days inserted on %s (the unfinished activity on the completion\'s '
            'driving path nearest the data date whose finish drives that path%s)'
            % (DELAY_WORKING_DAYS, test_code,
               '' if test_code == tried[0] else '; %s took no delay' % ', '.join(tried[:-1])))
    if full:
        msg = ('Critical Path Test PASSES: %s moved the completion activity %s by %s working days, from %s '
               'to %s. The critical path carries a delay through to completion.'
               % (lead, comp_code, '{:g}'.format(slip),
                  date_before.strftime('%Y-%m-%d %H:%M'), date_after.strftime('%Y-%m-%d %H:%M')))
    elif ok:
        msg = ('Critical Path Test PASSES: %s moved the completion activity %s by %s working days (from %s '
               'to %s), and the completion is still driven back through %s: the logic carries the delay '
               'through, and the calendars on the path, which work a different number of days in the later '
               'period, set the amount.'
               % (lead, comp_code, '{:g}'.format(slip), date_before.strftime('%Y-%m-%d %H:%M'),
                  date_after.strftime('%Y-%m-%d %H:%M'), test_code))
    else:
        # Where the delay is lost: the first activity after the test activity
        # on the as-filed driving path that moved by less than the delay, and
        # what drives it in the delayed run.
        lost_at, lost_slip, held_by = None, None, ''
        prev = test_code
        for c in path[path.index(test_code) + 1:]:
            b0 = _parse(nodes[c].get('early_finish_dt') or nodes[c].get('ef_date'))
            a_node = after_nodes.get(c) or {}
            a0 = _parse(a_node.get('early_finish_dt') or a_node.get('ef_date'))
            sl = working_days_between(b0, a0, test_cal) if (b0 and a0) else None
            if sl is not None and sl < DELAY_WORKING_DAYS - SLIP_TOLERANCE_DAYS:
                lost_at, lost_slip = c, round(sl, 2)
                dp = a_node.get('driving_predecessor') or {}
                cstrs = _constraints_of(by_code.get(c) or {})
                # What holds it. The engine names a constraint as the driver
                # only where the constraint pushes the work later; a Mandatory
                # Start or Finish that pulls it back keeps the predecessor's
                # name although that predecessor carried the whole delay
                # (8-Nov-26, scenario 03: CST-02020's Mandatory Start of
                # 28-Sep-26 read "now driven by CST-02019"). So: where the
                # named driver is the path's own previous activity, which
                # moved by the delay, or a constraint, the task's constraint
                # is named; otherwise the new driver is.
                if cstrs and (not dp or dp.get('type') == 'CONSTRAINT' or dp.get('code') == prev):
                    held_by = ': its %s holds it' % ' and '.join(cstrs)
                elif dp.get('code'):
                    held_by = ' and is now driven by %s' % dp['code']
                elif dp.get('type'):
                    held_by = ' and is now held by the %s' % dp['type'].replace('_', ' ').lower()
                break
            prev = c
        where = ''
        if lost_at:
            where = ('; the delay is first lost at %s, which moved by %s working days%s'
                     % (lost_at, '{:g}'.format(lost_slip), held_by))
        msg = ('Critical Path Test FAILS: %s moved the completion activity %s by only %s working days%s, and '
               'the completion is no longer driven by %s. Something on that path (a constraint, a broken or '
               'lagged link) does not carry the delay through to completion.'
               % (lead, comp_code, '{:g}'.format(slip), where, test_code))
    return {'ran': True, 'status': 'PASS' if ok else 'FAIL', 'test_activity': test_code,
            'completion_activity': comp_code, 'delay_days': DELAY_WORKING_DAYS, 'slip_days': slip,
            'finish_before': date_before.strftime('%Y-%m-%d %H:%M'),
            'finish_after': date_after.strftime('%Y-%m-%d %H:%M'),
            'carried_to_completion': reached, 'tried': tried,
            'driving_path': path, 'message': msg}
