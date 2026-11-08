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

Without the engine, or in a copy of the validator that does not build that
network (the public repository, even with the public engine beside it), the
test is not run and #12 is decided only where the answer is certain, as
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
# Up to this size the recalculations run in this process: the test suites call
# it hundreds of times on small networks. Above it each one runs in a child
# process that is stopped at the time limit, so a network the engine is slow
# on cannot hold up the tool that asked (8-Nov-26: floats of thousands of days
# took the as-filed run of a 3,000-activity synthetic file to 112 seconds, and
# a limit read only after the run had finished could not stop it). At that
# file's rate (about 37 ms an activity) four in-process runs of 100 activities
# stay well inside the test's 60 seconds; 500 did not (Claude AI review of the
# test, 8-Nov-26).
IN_PROCESS_ACTIVITIES = 100

# The child: one compute_cpm call, handing back only what the test reads.
_CHILD_CODE = """
import pickle, sys
where, acts, rels, kwargs = pickle.load(sys.stdin.buffer)
sys.path.insert(0, where)
import cpm
try:
    res = cpm.compute_cpm(acts, rels, **kwargs)
    keep = ('early_finish_dt', 'ef_date', 'early_start_dt', 'es_date', 'driving_predecessor',
            'expected_finish_applied')
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
    try:
        kind, value = pickle.loads(proc.stdout)
    except Exception:
        raise RuntimeError('the recalculation process returned no result')
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


_START_CONSTRAINTS = ('CS_MANDSTART', 'CS_MSO', 'CS_MSOA', 'CS_MSOB')
_FINISH_CONSTRAINTS = ('CS_MANDFIN', 'CS_MEO', 'CS_MEOA', 'CS_MEOB')
LINK_NAMES = {'FS': 'Finish-to-Start', 'SS': 'Start-to-Start', 'FF': 'Finish-to-Finish',
              'SF': 'Start-to-Finish'}


def _constraints_at(task, node, same_time=None):
    """The constraints filed on a task that its recalculated dates sit on: a
    start constraint whose date is the day of the recalculated early start, a
    finish constraint whose date is the day of the recalculated early finish,
    as P6 names them with their dates. A constraint whose date the activity is
    not on does not hold it, so it is not named (Claude AI review of the test,
    8-Nov-26: a Start On or After it merely carried was named as holding it).

    ``same_time(a, b)``, where given, also counts a constraint dated on a
    non-working day as sitting on the working time next to it: no working time
    lies between them (Codex check of the review fixes, 8-Nov-26: a Mandatory
    Finish on a Saturday holds the Friday close, and a literal date compare
    missed it)."""
    es = _parse(node.get('early_start_dt') or node.get('es_date'))
    ef = _parse(node.get('early_finish_dt') or node.get('ef_date'))
    out = []
    for kind, date in (('cstr_type', 'cstr_date'), ('cstr_type2', 'cstr_date2')):
        ctype = (task.get(kind) or '').strip()
        when_s = (task.get(date) or '').strip()
        when = _parse(when_s)
        if not ctype or when is None:
            continue
        on = (es if ctype in _START_CONSTRAINTS else ef if ctype in _FINISH_CONSTRAINTS else None)
        if on is None:
            continue
        if on.date() == when.date() or (same_time is not None and same_time(on, when)):
            out.append('%s of %s' % (CONSTRAINT_NAMES.get(ctype, ctype), when_s))
    return out


def _constraints_of(task):
    """Every constraint filed on a task, as P6 names them with their dates."""
    out = []
    for kind, date in (('cstr_type', 'cstr_date'), ('cstr_type2', 'cstr_date2')):
        ctype = (task.get(kind) or '').strip()
        if ctype:
            when = (task.get(date) or '').strip()
            out.append('%s of %s' % (CONSTRAINT_NAMES.get(ctype, ctype), when) if when
                       else CONSTRAINT_NAMES.get(ctype, ctype))
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


NETWORK_BUILDERS = ('_detect_schedule_options', '_driver_chain_network', '_assignment_counts',
                    '_rd_assignments')


def can_build_network(cv=None):
    """This copy of the validator builds the network the recalculation needs
    (the public repository's cp_validator does not: there the test is not run,
    even with the engine installed beside it)."""
    if cv is None:
        try:
            import cp_validator as cv
        except Exception:
            return False
    return all(hasattr(cv, name) for name in NETWORK_BUILDERS)


def can_run():
    """The test can run here: the CPM engine imports and the network can be built."""
    try:
        import cpm  # noqa: F401
    except Exception:
        return False
    return can_build_network()


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
    if not can_build_network(cv):
        return {'ran': False, 'reason': ('this copy of the validator does not build the network a '
                                         'recalculation needs')}
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
                'message': ('Critical Path Test NOT SCORED: no unfinished ordinary activity (one with a '
                            'duration; an activity of zero duration counts as a milestone) drives the '
                            'completion activity %s, so there is no critical task to delay.' % comp_code)}
    path = list(reversed(chain))
    date_before = _parse(nodes[comp_code].get('early_finish_dt') or nodes[comp_code].get('ef_date'))
    if date_before is None:
        return {'ran': False, 'reason': 'the recalculation gave the completion no early finish'}
    act_by_code = {a.get('code'): a for a in acts}

    def _cal_of(c):
        cid = (act_by_code.get(c) or {}).get('clndr_id') or (by_code.get(c) or {}).get('clndr_id') or ''
        return cid, (cal_map.get(cid, {}) or {})

    def _ef(node):
        return _parse((node or {}).get('early_finish_dt') or (node or {}).get('ef_date'))

    def _same_time(cal):
        def same(a, b):
            lo, hi = (a, b) if a <= b else (b, a)
            w = working_days_between(lo, hi, cal)
            return w is not None and abs(w) < 0.5
        return same

    def _held(c, node):
        return _constraints_at(by_code.get(c) or {}, node or {}, _same_time(_cal_of(c)[1]))

    # Activities nearer the data date that drive the path only through their
    # start were passed over; the result names them (Claude AI review of the
    # test, 8-Nov-26: the stretch they cover is not tested).
    first = path.index(candidates[-1])
    passed_over = [c for c in path[:first] if _open_ordinary(c) and not _finish_driven(c)]
    after, test_code, test_cal, tried, skipped = None, None, None, [], []
    # Nearest the data date first. Where the delay cannot be inserted on an
    # activity because its finish is set by an expected finish P6 honours, or
    # by its resources, its finish does not move: the next one along is tried,
    # up to MAX_TRIES (8-Nov-26: an activity with an expected finish under
    # "Use Expected Finish Dates" took no delay at all). Where a constraint
    # holds its finish (a Mandatory Finish with room before it), the critical
    # path is held there and the test FAILS: it is not skipped (Claude AI
    # review of the test, 8-Nov-26: the next one along then passed).
    for cand in list(reversed(candidates))[:MAX_TRIES]:
        task = by_code[cand]
        _cid, cal = _cal_of(cand)
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
        left = TEST_SECONDS_LIMIT - (_time.time() - _t0)
        if left < 1.0:
            return {'ran': False, 'reason': ('the test used the %.0f seconds it is allowed before a delayed '
                                             'recalculation could be made' % TEST_SECONDS_LIMIT)}
        try:
            run_after = _recalc(compute_cpm, delayed, rels, kwargs, left, in_child)
        except ValueError as exc:
            return {'ran': False, 'reason': 'the delayed schedule could not be recalculated (%s)' % exc}
        except _TooSlow:
            return {'ran': False, 'reason': ('the delayed recalculation did not finish within the %.0f seconds '
                                             'the test is allowed' % TEST_SECONDS_LIMIT)}
        except RuntimeError as exc:
            return {'ran': False, 'reason': 'the delayed schedule could not be recalculated (%s)' % exc}
        if _time.time() - _t0 > TEST_SECONDS_LIMIT:
            return {'ran': False, 'reason': ('the delayed recalculation did not finish within the %.0f seconds '
                                             'the test is allowed' % TEST_SECONDS_LIMIT)}
        t_node = (run_after.get('nodes') or {}).get(cand) or {}
        t_before, t_after = _ef(nodes[cand]), _ef(t_node)
        own = working_days_between(t_before, t_after, cal) if (t_before and t_after) else None
        tried.append(cand)
        if own is not None and own >= DELAY_WORKING_DAYS - SLIP_TOLERANCE_DAYS:
            after, test_code, test_cal = run_after, cand, cal
            break
        # A constraint holds it where its recalculated date sits on the
        # constraint (as filed or delayed, a weekend date counting as the
        # working time beside it), or where the engine names a constraint as
        # its driver: a Mandatory Finish later than the logic made a gap that
        # absorbed part of the delay (Codex check of the review fixes, 8-Nov-
        # 26: A1 took 340 of 600, was skipped, and A2 passed).
        same = _same_time(cal)
        held = (_constraints_at(task, t_node, same) or _constraints_at(task, nodes[cand], same)
                or (_constraints_of(task) if ((t_node.get('driving_predecessor') or {}).get('type') == 'CONSTRAINT'
                                              or (nodes[cand].get('driving_predecessor') or {}).get('type')
                                              == 'CONSTRAINT') else []))
        if held:
            c_after = _ef((run_after.get('nodes') or {}).get(comp_code))
            c_slip = working_days_between(date_before, c_after, cal) if c_after else None
            took = ('did not move its finish' if own is None or own <= 0 else
                    'moved its finish by only %s working days' % '{:g}'.format(round(own, 2)))
            return {'ran': True, 'status': 'FAIL', 'test_activity': cand, 'completion_activity': comp_code,
                    'delay_days': DELAY_WORKING_DAYS,
                    'slip_days': round(c_slip, 2) if c_slip is not None else None, 'tried': tried,
                    'driving_path': path,
                    'message': ("Critical Path Test FAILS: recalculated on the CPP CPM engine, a delay of %d "
                                "working days inserted on %s (the unfinished activity on the completion's "
                                "driving path nearest the data date whose finish drives that path%s) %s: its "
                                "%s holds it, so a constraint, not logic, holds the critical path there and "
                                "the delay does not reach the completion activity %s%s."
                                % (DELAY_WORKING_DAYS, cand, _lead_notes(passed_over, skipped), took,
                                   ' and '.join(held), comp_code,
                                   '' if c_slip is None else
                                   ', which moved by %s working days' % '{:g}'.format(round(c_slip, 2))))}
        if t_node.get('expected_finish_applied'):
            why = 'its expected finish sets its finish'
        elif (act_by_code.get(cand) or {}).get('resource_assignments'):
            why = 'its resources set its finish'
        else:
            # A finish that does not take the delay for no reason the test can
            # name is the finding the test exists for: it is not skipped
            # (Claude AI check of the review fixes, 8-Nov-26).
            moved = '' if own is None else ', moving by %s working days' % '{:g}'.format(round(own, 2))
            return {'ran': True, 'status': 'NS', 'test_activity': cand, 'delay_days': DELAY_WORKING_DAYS,
                    'slip_days': None, 'driving_path': path, 'tried': tried,
                    'message': ("Critical Path Test NOT SCORED: a delay of %d working days inserted on %s (the "
                                "unfinished activity on the completion's driving path nearest the data date "
                                "whose finish drives that path%s) did not move its finish by the delay%s, and "
                                "no constraint, expected finish or resource sets it; the recalculation cannot "
                                "say why, so the test is not scored."
                                % (DELAY_WORKING_DAYS, cand, _lead_notes(passed_over, skipped), moved))}
        skipped.append((cand, why))
    if after is None:
        return {'ran': True, 'status': 'NS', 'test_activity': None, 'delay_days': DELAY_WORKING_DAYS,
                'slip_days': None, 'driving_path': path, 'tried': tried,
                'message': ("Critical Path Test NOT SCORED: a delay could not be inserted on the unfinished "
                            "activities nearest the data date on the completion's driving path (%s)."
                            % '; '.join('%s: %s' % s for s in skipped))}

    after_nodes = after.get('nodes') or {}
    node_after = after_nodes.get(comp_code) or {}
    date_after = _ef(node_after)
    if date_after is None:
        return {'ran': False, 'reason': 'the recalculation gave the completion no early finish'}
    slip = working_days_between(date_before, date_after, test_cal)
    if slip is None:
        return {'ran': False, 'reason': "the completion's move could not be measured in working time"}
    slip = round(slip, 2)
    downstream = path[path.index(test_code) + 1:]
    # Does the engine still name the test activity at the head of the
    # completion's driving chain in the delayed run?
    named_back, seen2, c2, new_chain = False, set(), comp_code, []
    while c2 and c2 in after_nodes and c2 not in seen2:
        if c2 == test_code:
            named_back = True
            break
        seen2.add(c2)
        new_chain.append(c2)
        c2 = (after_nodes[c2].get('driving_predecessor') or {}).get('code')
    # A move short of the delay passes only when the logic demonstrably carried
    # it and the calendars can account for the rest (Claude AI review of the
    # test, 8-Nov-26, which built two wrong passes on the name alone: a side
    # path with a lead carried 500 days past a pinned activity, and an expected
    # finish part-way along absorbed four). So: the engine still names the
    # test activity back from the completion; every activity after it on the
    # as-filed driving path moved later (the engine keeps a predecessor's name
    # on an activity a Mandatory Start holds, so the name alone is not enough);
    # none of them had its finish set by an expected finish; and the path
    # crosses another calendar or carries a lag, without which the calendars
    # cannot make the move shorter.
    test_cid = _cal_of(test_code)[0]

    def _moved(c):
        b, a = _ef(nodes.get(c)), _ef(after_nodes.get(c))
        return bool(b and a and a > b)

    stayed = [c for c in downstream if not _moved(c)]
    moved_all = not stayed
    # The as-filed path and the delayed driving chain both: where the chain
    # changed, an expected finish or a constraint on the new one absorbs the
    # delay just as well (Codex check of the review fixes, 8-Nov-26: a new
    # driver's expected finish re-sized 41 days and the shortfall was blamed
    # on calendars).
    both = list(dict.fromkeys(downstream + (new_chain if named_back else [])))
    no_expected = not any((after_nodes.get(c) or {}).get('expected_finish_applied') for c in both)
    no_hold = not any(_held(c, after_nodes.get(c)) for c in both)
    calendars_differ = any(_cal_of(c)[0] != test_cid for c in both)
    lags = ([float(((nodes.get(c) or {}).get('driving_predecessor') or {}).get('lag_days') or 0) for c in downstream]
            + [float(((after_nodes.get(c) or {}).get('driving_predecessor') or {}).get('lag_days') or 0)
               for c in (new_chain if named_back else [])])
    lagged = any(lags)
    carried = named_back and moved_all and no_expected and no_hold and (calendars_differ or lagged)
    lag_word = ('lags and leads' if any(x > 0 for x in lags) and any(x < 0 for x in lags)
                else 'leads' if any(x < 0 for x in lags) else 'lags')
    # P6's own longest-path flag (TASK.driving_path_flag): where the file uses
    # it and marks activities on the tested path as off P6's longest path, P6
    # drives the completion through another path; say so (Claude AI check of
    # the review fixes, 8-Nov-26: on two real files every activity on the
    # tested path read N).
    segment = [test_code] + downstream
    p6_note, p6_off = '', 0
    if any((t.get('driving_path_flag') or '').strip() == 'Y' for t in work_tasks):
        p6_off = sum(1 for c in segment if ((by_code.get(c) or {}).get('driving_path_flag') or '').strip() == 'N')
        if p6_off:
            p6_note = (" P6's own longest-path flag in the file marks %d of the %d activities on this path, from "
                       "%s to the completion, as off its longest path: P6 drives the completion through another "
                       "path, and this result is the CPP engine's." % (p6_off, len(segment), test_code))
    full = slip >= DELAY_WORKING_DAYS - SLIP_TOLERANCE_DAYS
    ok = full or (carried and slip > 0)
    lead = ("recalculated on the CPP CPM engine, a delay of %d working days inserted on %s (the unfinished "
            "activity on the completion's driving path nearest the data date whose finish drives that path%s)"
            % (DELAY_WORKING_DAYS, test_code, _lead_notes(passed_over, skipped)))
    filed = _parse(completion_task.get('early_end_date'))
    filed_gap = working_days_between(filed, date_before, test_cal) if filed else None
    filed_note = ''
    if filed_gap is not None and abs(filed_gap) > SLIP_TOLERANCE_DAYS:
        # The test runs on CPP's recalculation; where it does not put the
        # completion where the file does, say so (Claude AI review of the
        # test, 8-Nov-26).
        filed_note = (" As filed, the recalculation puts the completion activity at %s; the file shows %s."
                      % (date_before.strftime('%Y-%m-%d %H:%M'), filed.strftime('%Y-%m-%d %H:%M')))
    notes = filed_note + p6_note
    if full and stayed:
        # The completion moved by the delay, but along another path: an
        # activity on the as-filed driving path did not move (Claude AI check
        # of the review fixes, 8-Nov-26). The pamphlet's test passes; the
        # result does not hide what held the as-filed path.
        parts = []
        for c in stayed:
            cs = _held(c, after_nodes.get(c))
            parts.append(c + (' (its %s holds it)' % ' and '.join(cs) if cs else ''))
        msg = ('Critical Path Test PASSES: %s moved the completion activity %s by %s working days, from %s '
               'to %s. The delay reached the completion along another path: on the as-filed driving path, %s '
               'did not move.%s'
               % (lead, comp_code, '{:g}'.format(slip), date_before.strftime('%Y-%m-%d %H:%M'),
                  date_after.strftime('%Y-%m-%d %H:%M'), ', '.join(parts), notes))
    elif full:
        msg = ('Critical Path Test PASSES: %s moved the completion activity %s by %s working days, from %s '
               'to %s. The critical path carries a delay through to completion.%s'
               % (lead, comp_code, '{:g}'.format(slip),
                  date_before.strftime('%Y-%m-%d %H:%M'), date_after.strftime('%Y-%m-%d %H:%M'), notes))
    elif ok:
        msg = ('Critical Path Test PASSES: %s moved the completion activity %s by %s working days (from %s '
               'to %s). Every activity after %s on the driving path moved later, none is held by a '
               'constraint or set by an expected finish, and the completion is still driven back through '
               '%s: the logic carries the delay through, and the %s on the path, which work a different '
               'number of days in the later period, set the amount.%s'
               % (lead, comp_code, '{:g}'.format(slip), date_before.strftime('%Y-%m-%d %H:%M'),
                  date_after.strftime('%Y-%m-%d %H:%M'), test_code, test_code,
                  ('calendars and ' + lag_word) if (calendars_differ and lagged) else
                  ('calendars' if calendars_differ else lag_word), notes))
    else:
        # Where the delay is lost: the first activity after the test activity
        # on the as-filed driving path that moved by less than the delay and
        # did not move, sits on its constraint's date, had its finish set by an
        # expected finish, or is now driven by something other than the
        # path's previous activity (a calendar-shortened activity upstream of
        # a driver switch is not the loss: Claude AI check of the review
        # fixes, 8-Nov-26); failing those, the first that moved by less than
        # the delay. Then what holds it.
        lost_at, lost_slip, held_by, first_short = None, None, '', None
        prev = test_code
        for c in downstream:
            b0, a_node = _ef(nodes.get(c)), after_nodes.get(c) or {}
            a0 = _ef(a_node)
            sl = working_days_between(b0, a0, test_cal) if (b0 and a0) else None
            if sl is not None and sl < DELAY_WORKING_DAYS - SLIP_TOLERANCE_DAYS:
                ndp = a_node.get('driving_predecessor') or {}
                switched = (ndp.get('code') and ndp.get('code') != prev) or ndp.get('type') == 'CONSTRAINT'
                stuck = (a0 <= b0 or a_node.get('expected_finish_applied')
                         or _held(c, a_node) or switched)
                if first_short is None:
                    first_short = (c, round(sl, 2), prev)
                if stuck:
                    lost_at, lost_slip = c, round(sl, 2)
                    break
            prev = c
        if lost_at is None and first_short is not None:
            lost_at, lost_slip, prev = first_short
        if lost_at:
            a_node = after_nodes.get(lost_at) or {}
            dp = a_node.get('driving_predecessor') or {}
            cstrs = _held(lost_at, a_node)
            if cstrs:
                held_by = ': its %s holds it' % ' and '.join(cstrs)
            elif a_node.get('expected_finish_applied'):
                s0 = _parse((nodes.get(lost_at) or {}).get('early_start_dt') or (nodes.get(lost_at) or {}).get('es_date'))
                s1 = _parse(a_node.get('early_start_dt') or a_node.get('es_date'))
                s_mv = working_days_between(s0, s1, test_cal) if (s0 and s1) else None
                held_by = (': its expected finish sets its finish' if s_mv is None else
                           ': its start moved by %s working days, but its expected finish re-sized its remaining '
                           'work' % '{:g}'.format(round(s_mv, 2)))
            elif dp.get('code') and dp.get('code') != prev:
                drv = dp['code']
                dcs = _held(drv, after_nodes.get(drv))
                xf = (after_nodes.get(drv) or {}).get('expected_finish_applied')
                held_by = (' and is now driven by %s%s'
                           % (drv, ', whose %s holds it' % ' and '.join(dcs) if dcs else
                              (', whose expected finish re-sized its remaining work' if xf else '')))
            elif dp.get('code'):
                held_by = (' and is still driven by %s through a %s link'
                           % (dp['code'], LINK_NAMES.get(dp.get('type'), dp.get('type') or 'logic')))
            elif dp.get('type'):
                held_by = ' and is now held by the %s' % dp['type'].replace('_', ' ').lower()
        where = ''
        if lost_at:
            where = ('; the delay is first lost at %s, which moved by %s working days%s'
                     % (lost_at, '{:g}'.format(lost_slip), held_by))
        tail = '' if named_back else ', and the completion is no longer driven by %s' % test_code
        msg = ('Critical Path Test FAILS: %s moved the completion activity %s by only %s working days%s%s. '
               'Something on that path (a constraint, an expected finish, a broken or lagged link) does not '
               'carry the delay through to completion.%s'
               % (lead, comp_code, '{:g}'.format(slip), where, tail, notes))
    return {'ran': True, 'status': 'PASS' if ok else 'FAIL', 'test_activity': test_code,
            'completion_activity': comp_code, 'delay_days': DELAY_WORKING_DAYS, 'slip_days': slip,
            'finish_before': date_before.strftime('%Y-%m-%d %H:%M'),
            'finish_after': date_after.strftime('%Y-%m-%d %H:%M'),
            'finish_filed': filed.strftime('%Y-%m-%d %H:%M') if filed else None,
            'p6_off_path': p6_off, 'stayed': stayed,
            'named_back': named_back, 'carried_to_completion': bool(full or carried),
            'tried': tried, 'skipped': skipped, 'passed_over': passed_over,
            'driving_path': path, 'message': msg}


def _lead_notes(passed_over, skipped):
    """The clauses the lead sentence adds: activities nearer the data date that
    drive the path only through their start, and activities that took no delay."""
    out = ''
    if passed_over:
        one = len(passed_over) == 1
        out += ('; %s %s the path only through %s start (Start-to-Start) and %s passed over'
                % (', '.join(passed_over), 'drives' if one else 'drive', 'its' if one else 'their',
                   'was' if one else 'were'))
    for code, why in skipped:
        out += '; %s took no delay (%s)' % (code, why)
    return out
