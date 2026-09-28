#!/usr/bin/env python3
"""Logic continuity (Check 8) traces to where the project finishes, not to an
As Late As Possible finish milestone in the middle of the network.

Run with: python tests/test_logic_continuity_completion_anchor_2026_09_28.py

Check 8 walks predecessors back from the project's completion anchors and
reports every incomplete activity it does not reach as having "no successor
path to the project completion milestone". The anchors were every critical
finish milestone (TT_FinMile, total float <= 0), else every finish milestone.
Check 3's terminals, the critical activities with no successor that it
accepts as the end of the network, were not among them.

A simple closed chain shows what goes wrong. A concrete mix design review, a
finish milestone set As Late As Possible and tied FS into the pour, shows
zero total float: ALAP places it against its successor's start, so it carries
the pour's float, and the pour is critical. It becomes a completion anchor,
and the only one. The activity that sets the project's finish, a cure on a
24-hour calendar, has a successor (the removal of the props, FS -120 h), so
Check 3 does not count it as terminal; that successor is the network's one
open end but finishes before the project does, carries float, and is not
critical either. So nothing counts as terminal, and every activity that is
not upstream of the review reads as disconnected: 15 of the 16 incomplete
activities in the fixture below, the pour and the cure among them, logic
continuity 20 (RED), and one recommendation per activity.

The anchors now come from the network's position as well as the task type:

* the activity or activities that set the project's early finish, and the
  open ends reached from them through unfinished work, which is where the
  network ends. Only an activity tied to at least one other work activity can
  set the finish, so an unlinked activity never sets it;
* the finish milestones as before, less the gates: an As Late As Possible
  finish milestone with work after it paces that work and is not where the
  project completes. The fallback to every finish milestone still fires only
  when no finish milestone is critical, a critical gate included;
* Check 3's terminals, so the two checks agree on where the network ends.

One trade-off is kept, and pinned below: the latest finisher with logic is
taken as the end even when it is a stray dead end, because nothing separates
it from a real last activity. Check 3 still reports its missing successor.

The fixture below is that pattern on neutral data: a completed handover, an
eleven-task FS chain on a five-day calendar, three ALAP review milestones
each tied FS into a task of the chain and each after the handover, the pour
held by Start On or After, a cure on a 24-hour calendar and a last task tied
from it FS -120 h. Its stored dates, floats and driving flags were worked
through by hand from P6's scheduling rules. The guards prove a real open
end is still reported, that a schedule with a real finish milestone reads as
before, what can and cannot be the end, and that Check 3's terminal anchors
the trace in a file that carries no early dates.
"""
import os
import sys
import tempfile
import warnings as _warnings

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, '..', 'scripts'))

from xer_parser import parse_xer  # noqa: E402
from cp_validator import validate_critical_path, RATING_GREEN, RATING_AMBER  # noqa: E402

TAB = '\t'
DATA_DATE = '2027-03-01 08:00'      # a Monday morning
FINISH = '2027-04-28 17:00'         # the cure's early finish: the project's

_FIVE_DAY_SHIFT = '(0||0(s|08:00|f|12:00)())(0||1(s|13:00|f|17:00)())'
_FIVE_DAY = ('(0||CalendarData()((0||DaysOfWeek()((0||1()())'
             + ''.join(f'(0||{d}()({_FIVE_DAY_SHIFT}))' for d in range(2, 7))
             + '(0||7()())))(0||Exceptions()())))')
_TWENTY_FOUR_HOUR = ('(0||CalendarData()((0||DaysOfWeek()('
                     + ''.join(f'(0||{d}()((0||0(s|00:00|f|00:00)())))'
                               for d in range(1, 8))
                     + '))(0||Exceptions()())))')

_TASK_COLS = ['task_id', 'task_code', 'task_name', 'proj_id', 'wbs_id',
              'clndr_id', 'status_code', 'task_type', 'target_drtn_hr_cnt',
              'remain_drtn_hr_cnt', 'total_float_hr_cnt', 'act_start_date',
              'act_end_date', 'early_start_date', 'early_end_date',
              'restart_date', 'reend_date', 'late_start_date',
              'late_end_date', 'target_start_date', 'target_end_date',
              'driving_path_flag', 'cstr_type', 'cstr_date', 'cstr_type2']


def _row(tid, code, name, cal, hrs, es, ef, ls, lf, tf, *, ttype='TT_Task',
         status='TK_NotStart', act=('', ''), cstr='', cstr_date='', drv='N',
         cstr2=''):
    """One TASK row in P6's export shape. A completed row carries its stamp
    (the data date) as its early and late dates and no float."""
    done = status == 'TK_Complete'
    return [tid, code, name, '1', 'W1', cal, status, ttype, str(hrs),
            '0' if done else str(hrs), '' if done else str(tf), act[0], act[1],
            es, ef, '' if done else es, '' if done else ef, ls, lf,
            act[0] or es, act[1] or ef, drv, cstr, cstr_date, cstr2]


def _milestone(tid, code, name, at, late, tf, *, cstr='CS_ALAP', drv='N',
               cstr2=''):
    return _row(tid, code, name, 'C5', 0, at, at, late, late, tf,
                ttype='TT_FinMile', cstr=cstr, drv=drv, cstr2=cstr2)


def _slab_rows():
    """The pattern, dated as P6 schedules it. The chain N110..N200 carries two
    working days of float: the pour is held to Wednesday 14 April and the
    pre-pour inspection finishes the Friday before."""
    return [
        _row('100', 'N100', 'Handover of the work area', 'C5', 40, DATA_DATE,
             DATA_DATE, DATA_DATE, DATA_DATE, '', status='TK_Complete',
             act=('2027-02-22 08:00', '2027-02-26 17:00')),
        _row('110', 'N110', 'Break out the slab', 'C5', 24, '2027-03-01 08:00',
             '2027-03-03 17:00', '2027-03-03 08:00', '2027-03-05 17:00', 16),
        _row('120', 'N120', 'Engineer site visit', 'C5', 8, '2027-03-04 08:00',
             '2027-03-04 17:00', '2027-03-08 08:00', '2027-03-08 17:00', 16),
        _row('130', 'N130', 'Shore below', 'C5', 24, '2027-03-05 08:00',
             '2027-03-09 17:00', '2027-03-09 08:00', '2027-03-11 17:00', 16),
        _row('140', 'N140', 'Set the steel', 'C5', 24, '2027-03-10 08:00',
             '2027-03-12 17:00', '2027-03-12 08:00', '2027-03-16 17:00', 16),
        _row('150', 'N150', 'Metal deck', 'C5', 8, '2027-03-15 08:00',
             '2027-03-15 17:00', '2027-03-17 08:00', '2027-03-17 17:00', 16),
        _row('160', 'N160', 'Formwork', 'C5', 40, '2027-03-16 08:00',
             '2027-03-22 17:00', '2027-03-18 08:00', '2027-03-24 17:00', 16),
        _row('170', 'N170', 'Bottom mat', 'C5', 40, '2027-03-23 08:00',
             '2027-03-29 17:00', '2027-03-25 08:00', '2027-03-31 17:00', 16),
        _row('180', 'N180', 'Top mat', 'C5', 40, '2027-03-30 08:00',
             '2027-04-05 17:00', '2027-04-01 08:00', '2027-04-07 17:00', 16),
        _row('190', 'N190', 'Embeds', 'C5', 24, '2027-04-06 08:00',
             '2027-04-08 17:00', '2027-04-08 08:00', '2027-04-12 17:00', 16),
        _row('200', 'N200', 'Pre-pour inspection', 'C5', 8, '2027-04-09 08:00',
             '2027-04-09 17:00', '2027-04-13 08:00', '2027-04-13 17:00', 16),
        _row('210', 'N210', 'Pour', 'C5', 8, '2027-04-14 08:00',
             '2027-04-14 17:00', '2027-04-14 08:00', '2027-04-14 17:00', 0,
             cstr='CS_MSOA', cstr_date='2027-04-14 08:00', drv='Y'),
        # 14 days on the 24-hour calendar; P6 holds its late finish to the
        # project finish, so it carries no float although its successor does.
        _row('220', 'N220', 'Cure', 'C24', 336, '2027-04-14 17:00', FINISH,
             '2027-04-14 17:00', FINISH, 0, drv='Y'),
        # FS -120 h on the predecessor's (24-hour) calendar: Friday 23 April
        # 17:00, so Monday 26 April 08:00 on its own five-day calendar.
        _row('230', 'N230', 'Remove the props', 'C5', 8, '2027-04-26 08:00',
             '2027-04-26 17:00', '2027-04-28 08:00', FINISH, 16),
        # ALAP: each sits at the close before its successor's early start and
        # carries that successor's float.
        _milestone('301', 'M301', 'Shoring drawings reviewed',
                   '2027-03-15 17:00', '2027-03-17 17:00', 16),
        _milestone('302', 'M302', 'Rebar drawings reviewed',
                   '2027-03-22 17:00', '2027-03-24 17:00', 16),
        _milestone('303', 'M303', 'Mix design reviewed',
                   '2027-04-13 17:00', '2027-04-13 17:00', 0, drv='Y'),
    ]


# (successor, predecessor, type, lag hours)
_SLAB_RELS = [
    ('110', '100', 'PR_FS', 0), ('120', '110', 'PR_FS', 0),
    ('130', '120', 'PR_FS', 0), ('140', '130', 'PR_FS', 0),
    ('150', '140', 'PR_FS', 0), ('160', '150', 'PR_FS', 0),
    ('170', '160', 'PR_FS', 0), ('180', '170', 'PR_FS', 0),
    ('190', '180', 'PR_FS', 0), ('200', '190', 'PR_FS', 0),
    ('210', '200', 'PR_FS', 0), ('220', '210', 'PR_FS', 0),
    ('230', '220', 'PR_FS', -120),
    ('301', '100', 'PR_FS', 0), ('160', '301', 'PR_FS', 0),
    ('302', '100', 'PR_FS', 0), ('170', '302', 'PR_FS', 0),
    ('303', '100', 'PR_FS', 0), ('210', '303', 'PR_FS', 0),
]


def _xer(rows, rels, *, scd_end=FINISH, plan_end=''):
    lines = [
        TAB.join(['ERMHDR', '23.12', '2027-03-01', 'Project', 'admin',
                  'Neutral', 'db', 'Project Management', 'CAD']),
        TAB.join(['%T', 'PROJECT']),
        TAB.join(['%F', 'proj_id', 'proj_short_name', 'last_recalc_date',
                  'plan_end_date', 'scd_end_date', 'clndr_id']),
        TAB.join(['%R', '1', 'NEUTRAL', DATA_DATE, plan_end, scd_end, 'C5']),
        TAB.join(['%T', 'PROJWBS']),
        TAB.join(['%F', 'wbs_id', 'parent_wbs_id', 'wbs_name',
                  'wbs_short_name', 'proj_id']),
        TAB.join(['%R', 'W1', '', 'Root', 'W1', '1']),
        TAB.join(['%T', 'CALENDAR']),
        TAB.join(['%F', 'clndr_id', 'clndr_name', 'clndr_type',
                  'day_hr_cnt', 'week_hr_cnt', 'clndr_data']),
        TAB.join(['%R', 'C5', 'Five day', 'CA_Project', '8', '40', _FIVE_DAY]),
        TAB.join(['%R', 'C24', 'Twenty-four hour, seven day', 'CA_Project',
                  '24', '168', _TWENTY_FOUR_HOUR]),
        TAB.join(['%T', 'TASK']),
        TAB.join(['%F'] + _TASK_COLS),
    ]
    lines += [TAB.join(['%R'] + r) for r in rows]
    lines += [
        TAB.join(['%T', 'TASKPRED']),
        TAB.join(['%F', 'task_pred_id', 'task_id', 'pred_task_id',
                  'pred_type', 'lag_hr_cnt']),
    ]
    lines += [TAB.join(['%R', str(i), s, p, t, str(lag)])
              for i, (s, p, t, lag) in enumerate(rels, 1)]
    lines += [
        TAB.join(['%T', 'SCHEDOPTIONS']),
        TAB.join(['%F', 'schedoptions_id', 'proj_id', 'sched_retained_logic',
                  'sched_progress_override',
                  'sched_calendar_on_relationship_lag']),
        TAB.join(['%R', '1', '1', 'Y', 'N', 'rcal_Predecessor']),
        '%E',
    ]
    return '\r\n'.join(lines) + '\r\n'


def _validate(rows, rels, **kw):
    with tempfile.NamedTemporaryFile('w', suffix='.xer', delete=False,
                                     encoding='utf-8') as f:
        f.write(_xer(rows, rels, **kw))
        path = f.name
    try:
        with _warnings.catch_warnings():
            _warnings.simplefilter('ignore')
            return validate_critical_path(parse_xer(path))
    finally:
        os.unlink(path)


def _continuity(results):
    return results['checks']['logic_continuity']


def _disconnected(results):
    return sorted(d['task_code'] for d in _continuity(results)['disconnected_activities'])


def _continuity_findings(results):
    return [r for r in results['recommendations'] if r['category'] == 'Logic Continuity']


# ─────────────────────────────────────────── the fixture is what it says it is

def test_the_fixture_is_the_pattern_as_p6_dates_it():
    r = _validate(_slab_rows(), _SLAB_RELS)
    # critical: the review ahead of the pour (by ALAP), the pour, the cure
    assert sorted(a['task_code'] for a in r['critical_path_activities']) == [
        'M303', 'N210', 'N220']
    # no critical activity lacks a successor, so Check 3 finds no terminal
    assert r['terminal_milestones'] == []


# ───────────────────────────────────────────────────────── the closed chain

def test_a_closed_chain_behind_an_alap_review_reads_connected():
    r = _validate(_slab_rows(), _SLAB_RELS)
    lc = _continuity(r)
    assert _disconnected(r) == []
    assert lc['disconnected_on_cp'] == 0
    assert (lc['rating'], lc['score']) == (RATING_GREEN, 100)
    assert _continuity_findings(r) == []


def test_the_anchors_are_where_the_project_finishes():
    lc = _continuity(_validate(_slab_rows(), _SLAB_RELS))
    # the cure sets the finish; the props removal is the open end after it
    assert lc['completion_anchors'] == ['N220', 'N230']
    # it counts finish milestones and Check 3 terminals: none here
    assert lc['finish_milestones_found'] == 0
    # the three reviews pace the work after them; none is the completion
    assert lc['gate_milestones'] == ['M301', 'M302', 'M303']


# ─────────────────────────────────────────── a real gap is still reported

def test_a_dangling_branch_is_still_disconnected():
    rows = _slab_rows() + [
        # hangs off the shoring with no successor: no path to the finish
        _row('400', 'X400', 'Temporary works removed', 'C5', 8,
             '2027-03-10 08:00', '2027-03-10 17:00', '2027-04-28 08:00',
             FINISH, 280),
        # feeds only X400, so it has no path to the finish either
        _row('410', 'Y410', 'Order the temporary works', 'C5', 8,
             '2027-03-01 08:00', '2027-03-01 17:00', '2027-04-27 08:00',
             '2027-04-27 17:00', 328),
    ]
    rels = _SLAB_RELS + [('400', '130', 'PR_FS', 0), ('400', '410', 'PR_FS', 0),
                         ('410', '100', 'PR_FS', 0)]
    r = _validate(rows, rels)
    lc = _continuity(r)
    assert _disconnected(r) == ['X400', 'Y410']
    assert lc['disconnected_on_cp'] == 0
    assert lc['rating'] == RATING_AMBER
    assert sorted(f['affected_activity'] for f in _continuity_findings(r)) == [
        'X400', 'Y410']


# ─────────────────── the fallback to every finish milestone, gates set aside

_FALLBACK_FINISH = '2027-03-05 17:00'
_MUST_FINISH_BY = '2027-03-26 17:00'   # three weeks late: nothing is critical


def _fallback_rows(gate_cstr='CS_ALAP', with_branch=True, branch_ttype='TT_Task'):
    """Every activity floats against a Must Finish By, so no finish milestone
    is critical and Check 8 falls back to every finish milestone. G530 is a
    review milestone; X540, after it, leads nowhere."""
    rows = [
        _row('500', 'A500', 'Handover', 'C5', 40, DATA_DATE, DATA_DATE,
             DATA_DATE, DATA_DATE, '', status='TK_Complete',
             act=('2027-02-22 08:00', '2027-02-26 17:00')),
        _row('510', 'B510', 'Install', 'C5', 40, '2027-03-01 08:00',
             _FALLBACK_FINISH, '2027-03-22 08:00', _MUST_FINISH_BY, 120),
        _milestone('590', 'FIN', 'Works complete', _FALLBACK_FINISH,
                   _MUST_FINISH_BY, 120, cstr=''),
        _row('520', 'P520', 'Prepare the submittal', 'C5', 8,
             '2027-03-01 08:00', '2027-03-01 17:00', '2027-03-25 08:00',
             '2027-03-25 17:00', 152),
        _milestone('530', 'G530', 'Submittal reviewed', '2027-03-01 17:00',
                   '2027-03-25 17:00', 152, cstr=gate_cstr),
    ]
    if with_branch:
        rows.append(_row('540', 'X540', 'Install the sample', 'C5', 8,
                         '2027-03-02 08:00', '2027-03-02 17:00',
                         '2027-03-26 08:00', _MUST_FINISH_BY, 152,
                         ttype=branch_ttype))
    return rows


def _fallback_rels(with_branch=True):
    rels = [('510', '500', 'PR_FS', 0), ('590', '510', 'PR_FS', 0),
            ('520', '500', 'PR_FS', 0), ('530', '520', 'PR_FS', 0)]
    if with_branch:
        rels.append(('540', '530', 'PR_FS', 0))
    return rels


def _fallback(**kw):
    return _validate(_fallback_rows(**kw), _fallback_rels(kw.get('with_branch', True)),
                     scd_end=_FALLBACK_FINISH, plan_end=_MUST_FINISH_BY)


def test_an_alap_gate_that_leads_nowhere_connects_nothing():
    r = _fallback()
    assert r['critical_path_activities'] == []
    # G530 is not a completion anchor, so neither it nor what feeds it
    # reaches the finish; only B510 and FIN do
    assert _disconnected(r) == ['G530', 'P520', 'X540']
    lc = _continuity(r)
    assert lc['gate_milestones'] == ['G530']
    assert lc['completion_anchors'] == ['B510', 'FIN']
    assert lc['finish_milestones_found'] == 1


def test_a_finish_milestone_not_set_alap_keeps_its_anchor():
    # the change is confined to ALAP milestones: without the constraint the
    # fallback still anchors on G530, as before
    r = _fallback(gate_cstr='')
    assert _disconnected(r) == ['X540']
    assert _continuity(r)['gate_milestones'] == []


def test_an_alap_finish_milestone_with_no_work_after_it_keeps_its_anchor():
    # an ALAP finish milestone with nothing after it is where its chain
    # completes, not a gate
    r = _fallback(with_branch=False)
    assert _disconnected(r) == []
    assert _continuity(r)['gate_milestones'] == []


# ─────────────────────── a schedule with a real finish milestone, as before

def test_a_real_finish_milestone_reads_as_before():
    rows = _slab_rows() + [
        _milestone('240', 'N240', 'Transfer works complete', FINISH, FINISH,
                   0, cstr='', drv='Y'),
    ]
    rels = _SLAB_RELS + [('240', '220', 'PR_FS', 0), ('240', '230', 'PR_FS', 0)]
    r = _validate(rows, rels)
    lc = _continuity(r)
    assert r['terminal_milestones'] == ['N240']
    assert _disconnected(r) == []
    assert (lc['rating'], lc['score']) == (RATING_GREEN, 100)
    # the milestone, and the cure that finishes at the same instant
    assert lc['completion_anchors'] == ['N220', 'N240']
    assert lc['finish_milestones_found'] == 1


# ───────────────────────────────────────── what can and cannot be the end

def _unlinked(tid, code, finish):
    """An activity with no relationship at all, finishing at `finish`. No
    float was computed for it (blank), so it is not critical."""
    start = finish[:10] + ' 08:00'
    return _row(tid, code, 'Unlinked activity', 'C5', 8, start, finish, start,
                finish, '')


def _without_early_dates(rows):
    for r in rows:
        r[13] = r[14] = r[15] = r[16] = ''      # early start and finish, restart, re-end
    return rows


def test_an_unlinked_activity_is_never_the_end():
    # Z500 has no relationship and finishes a week after the cure. It is
    # reported, and the chain still anchors on the cure: the latest finish is
    # read over the activities tied to at least one other activity.
    rows = _slab_rows() + [_unlinked('500', 'Z500', '2027-05-05 17:00')]
    r = _validate(rows, _SLAB_RELS, scd_end='2027-05-05 17:00')
    assert _disconnected(r) == ['Z500']
    assert _continuity(r)['completion_anchors'] == ['N220', 'N230']


def test_a_schedule_without_logic_never_reads_connected():
    rows = [_unlinked(str(600 + i), f'U{i}', '2027-03-05 17:00') for i in range(6)]
    r = _validate(rows, [], scd_end='2027-03-05 17:00')
    lc = _continuity(r)
    assert _disconnected(r) == ['U0', 'U1', 'U2', 'U3', 'U4', 'U5']
    assert lc['completion_anchors'] == []
    assert lc['rating'] == RATING_AMBER


def test_a_critical_gate_keeps_the_every_finish_milestone_fallback_off():
    # D600, a plain finish milestone off the shoring with nothing after it,
    # is a dead end. The fallback to every finish milestone is for schedules
    # with no critical finish milestone, and M303 is one (a gate, but
    # critical), so the fallback stays off and D600 is reported, as it was
    # before gates were set aside.
    rows = _slab_rows() + [
        _milestone('600', 'D600', 'Shoring signed off', '2027-03-09 17:00',
                   FINISH, 288, cstr=''),
    ]
    r = _validate(rows, _SLAB_RELS + [('600', '130', 'PR_FS', 0)])
    assert _disconnected(r) == ['D600']
    assert _continuity(r)['finish_milestones_found'] == 0


def test_finished_work_after_the_finish_anchors_nothing():
    # C700 is complete although the cure it follows has not started (out of
    # sequence). U710, unfinished, feeds only C700. Finished work is not where
    # the remaining work ends, so U710 has no path to the finish.
    rows = _slab_rows() + [
        _row('700', 'C700', 'Early strip test', 'C5', 8, DATA_DATE, DATA_DATE,
             DATA_DATE, DATA_DATE, '', status='TK_Complete',
             act=('2027-02-24 08:00', '2027-02-24 17:00')),
        _row('710', 'U710', 'Prepare the strip test', 'C5', 8,
             '2027-03-01 08:00', '2027-03-01 17:00', '2027-04-27 08:00',
             '2027-04-27 17:00', 328),
    ]
    rels = _SLAB_RELS + [('700', '220', 'PR_SS', 0), ('700', '710', 'PR_FS', 0),
                         ('710', '100', 'PR_FS', 0)]
    assert _disconnected(_validate(rows, rels)) == ['U710']


def test_a_finish_milestone_with_only_a_level_of_effort_after_it_is_no_gate():
    # a level of effort is not work: G530 with only a hammock after it is
    # where its chain completes, so it keeps its anchor
    r = _fallback(branch_ttype='TT_LOE')
    assert _continuity(r)['gate_milestones'] == []
    assert _disconnected(r) == []


def test_alap_as_the_secondary_constraint_makes_a_gate():
    rows = [r for r in _slab_rows() if r[1] != 'M303'] + [
        _milestone('303', 'M303', 'Mix design reviewed', '2027-04-13 17:00',
                   '2027-04-13 17:00', 0, cstr='', cstr2='CS_ALAP', drv='Y'),
    ]
    r = _validate(rows, _SLAB_RELS)
    assert _continuity(r)['gate_milestones'] == ['M301', 'M302', 'M303']
    assert _disconnected(r) == []


def test_no_stored_early_dates_means_no_finish_setter():
    # without early dates the finish cannot be read by position: the anchors
    # are the finish milestones and Check 3's terminals, as before
    rows = _without_early_dates(_fallback_rows())
    r = _validate(rows, _fallback_rels(), scd_end=_FALLBACK_FINISH,
                  plan_end=_MUST_FINISH_BY)
    assert _continuity(r)['completion_anchors'] == ['FIN']
    assert _disconnected(r) == ['G530', 'P520', 'X540']


def test_the_latest_finisher_with_logic_is_taken_as_the_end():
    # A trade-off, stated rather than hidden. S550 follows B510 and finishes
    # after the finish milestone with no successor. By position it is where
    # the network ends, so Check 8 anchors on it: no rule separates it from a
    # real last activity without losing those. Check 3 still reports its
    # missing successor.
    rows = _fallback_rows() + [
        _row('550', 'S550', 'Stray punch list', 'C5', 40, '2027-03-08 08:00',
             '2027-03-12 17:00', '2027-03-22 08:00', _MUST_FINISH_BY, 80),
    ]
    r = _validate(rows, _fallback_rels() + [('550', '510', 'PR_FS', 0)],
                  scd_end='2027-03-12 17:00', plan_end=_MUST_FINISH_BY)
    assert 'S550' in _continuity(r)['completion_anchors']
    assert _disconnected(r) == ['G530', 'P520', 'X540']
    assert 'S550' in {e['task_code'] for e in r['open_ends']['no_succ']}


# ──────────────────── Check 3's terminal anchors a file with no early dates

def test_check_3s_terminal_is_an_anchor_when_the_file_has_no_early_dates():
    # With no early dates there is no finish-setter anchor, and a chain that
    # ends in an ordinary task has no finish milestone. Check 3 accepts the
    # last task as the end of the network; without its terminals Check 8 had
    # no anchor at all and reported every activity, each of them critical,
    # as disconnected.
    rows = [
        _row('600', 'A600', 'Excavate', 'C5', 40, '', '', '', '', 0, drv='Y'),
        _row('610', 'A610', 'Form and pour', 'C5', 40, '', '', '', '', 0,
             drv='Y'),
        _row('620', 'A620', 'Backfill', 'C5', 40, '', '', '', '', 0, drv='Y'),
    ]
    rels = [('610', '600', 'PR_FS', 0), ('620', '610', 'PR_FS', 0)]
    r = _validate(rows, rels)
    lc = _continuity(r)
    assert r['terminal_milestones'] == ['A620']
    assert _disconnected(r) == []
    assert (lc['rating'], lc['score']) == (RATING_GREEN, 100)
    assert lc['completion_anchors'] == ['A620']
    assert lc['finish_milestones_found'] == 1


if __name__ == '__main__':
    tests = [f for name, f in list(globals().items())
             if name.startswith('test_') and callable(f)]
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
