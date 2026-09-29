#!/usr/bin/env python3
"""Three scoring rules and the relationship-lag calendar (2026-09-29).

Run with: python tests/test_scoring_rules_and_lag_calendar_2026_09_29.py

- **Check 2 with no critical path.** A schedule with no activity at zero or
  negative total float has no critical path, and Check 2 (constraint-driven
  criticality) cannot be assessed. It fell through to its "0% of the CP
  constrained" branch and scored GREEN 100. It is now RED 0, with a note
  saying why: a schedule with no critical path is itself a logic defect.
- **A RED check caps the overall rating.** The overall score is a weighted
  average, so one RED check can sit under a GREEN "High Confidence"
  headline. Any RED check now caps the rating at AMBER and the confidence at
  "Moderate Confidence"; the score itself is unchanged, and
  ``overall_rating_capped_by_red`` and ``red_checks`` say it happened.
- **Check 5 converts a lag on the calendar P6 measures it on.** That is the
  calendar SCHEDOPTIONS.sched_calendar_on_relationship_lag names, the
  predecessor's by P6's default. Check 5 always used the successor's, so on
  a schedule mixing calendars a lag read in the wrong working days.
  ``results['schedule_options']`` says which calendar was used and why.

Every fixture is built in this file: neutral activities on Monday-to-Friday
calendars of 8 h and 10 h a day.
"""
import os
import sys
import tempfile
import warnings as _warnings

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, '..', 'scripts'))

from xer_parser import parse_xer  # noqa: E402
from cp_validator import _detect_schedule_options, validate_critical_path  # noqa: E402

TAB = '\t'


def _calendar(start, finish):
    shift = '(0||0(s|%s|f|12:00)())(0||1(s|12:30|f|%s)())' % (start, finish)
    return ('(0||CalendarData()((0||DaysOfWeek()((0||1()())'
            + ''.join('(0||%d()(%s))' % (d, shift) for d in range(2, 7))
            + '(0||7()())))(0||Exceptions()())))')


_TASK_COLS = ['task_id', 'proj_id', 'wbs_id', 'clndr_id', 'task_code',
              'task_name', 'task_type', 'status_code', 'target_drtn_hr_cnt',
              'remain_drtn_hr_cnt', 'total_float_hr_cnt', 'early_start_date',
              'early_end_date', 'late_start_date', 'late_end_date',
              'act_start_date', 'act_end_date', 'driving_path_flag',
              'cstr_type', 'cstr_date']


def _row(tid, code, ttype, status, clndr, hrs, tf, es, ef, act=('', '')):
    return [tid, '1', 'W1', clndr, code, 'Neutral ' + code, ttype, status,
            str(hrs), '0' if status == 'TK_Complete' else str(hrs), str(tf),
            es, ef, es, ef, act[0], act[1], 'Y' if tf == 0 else 'N', '', '']


def _build_xer(rows, links, schedoptions=None):
    lines = [
        TAB.join(['ERMHDR', '24.12', '2026-10-05', 'Project', 'admin', 'admin',
                  'dbxDatabaseNoName', 'Project Management', 'USD']),
        TAB.join(['%T', 'PROJECT']),
        TAB.join(['%F', 'proj_id', 'proj_short_name', 'clndr_id',
                  'last_recalc_date', 'scd_end_date']),
        TAB.join(['%R', '1', 'NEUTRAL', 'EIGHT', '2026-10-05 08:00',
                  '2026-10-30 17:00']),
        TAB.join(['%T', 'CALENDAR']),
        TAB.join(['%F', 'clndr_id', 'default_flag', 'clndr_name', 'clndr_type',
                  'day_hr_cnt', 'week_hr_cnt', 'clndr_data']),
        TAB.join(['%R', 'EIGHT', 'Y', 'Eight Hour', 'CA_Base', '8', '40',
                  _calendar('08:00', '16:30')]),
        TAB.join(['%R', 'TEN', 'N', 'Ten Hour', 'CA_Base', '10', '50',
                  _calendar('07:00', '17:30')]),
    ]
    if schedoptions is not None:
        lines += [TAB.join(['%T', 'SCHEDOPTIONS']),
                  TAB.join(['%F', 'schedoptions_id', 'proj_id',
                            'sched_calendar_on_relationship_lag']),
                  TAB.join(['%R', '1', '1', schedoptions])]
    lines += [
        TAB.join(['%T', 'PROJWBS']),
        TAB.join(['%F', 'wbs_id', 'proj_id', 'parent_wbs_id', 'wbs_short_name',
                  'wbs_name', 'proj_node_flag']),
        TAB.join(['%R', 'W1', '1', '', 'NEUTRAL', 'Neutral', 'Y']),
        TAB.join(['%T', 'TASK']),
        TAB.join(['%F'] + _TASK_COLS),
    ]
    lines += [TAB.join(['%R'] + r) for r in rows]
    lines += [
        TAB.join(['%T', 'TASKPRED']),
        TAB.join(['%F', 'task_pred_id', 'task_id', 'pred_task_id', 'proj_id',
                  'pred_proj_id', 'pred_type', 'lag_hr_cnt']),
    ]
    for k, (pred, succ, lag) in enumerate(links, 1):
        lines.append(TAB.join(['%R', str(k), succ, pred, '1', '1', 'PR_FS',
                               str(lag)]))
    lines.append('%E')
    return '\r\n'.join(lines) + '\r\n'


def _validate(rows, links, schedoptions=None):
    with tempfile.NamedTemporaryFile('w', suffix='.xer', delete=False,
                                     encoding='utf-8', newline='') as f:
        f.write(_build_xer(rows, links, schedoptions))
        path = f.name
    try:
        with _warnings.catch_warnings():
            _warnings.simplefilter('ignore')
            return validate_critical_path(parse_xer(path))
    finally:
        os.unlink(path)


# A complete start milestone, three work activities and a finish milestone,
# one week each, all on the 8 h calendar. `tf` hours of total float on the
# incomplete activities; `start_complete=False` leaves the start milestone
# open, an open end on the critical path when tf is 0.
def _chain(tf, start_complete=True):
    status = 'TK_Complete' if start_complete else 'TK_NotStart'
    act = ('2026-10-05 08:00', '2026-10-05 08:00') if start_complete else ('', '')
    rows = [_row('1', 'START', 'TT_Mile', status, 'EIGHT', 0, 0 if start_complete else tf,
                 '2026-10-05 08:00', '2026-10-05 08:00', act)]
    weeks = [('2026-10-05', '2026-10-09'), ('2026-10-12', '2026-10-16'),
             ('2026-10-19', '2026-10-23')]
    for i, (s, f) in enumerate(weeks, 2):
        rows.append(_row(str(i), 'A%d' % (i - 1), 'TT_Task', 'TK_NotStart', 'EIGHT',
                         40, tf, s + ' 08:00', f + ' 16:30'))
    rows.append(_row('5', 'FIN', 'TT_FinMile', 'TK_NotStart', 'EIGHT', 0, tf,
                     '2026-10-23 16:30', '2026-10-23 16:30'))
    links = [('1', '2', 0), ('2', '3', 0), ('3', '4', 0), ('4', '5', 0)]
    return rows, links


# ── Check 2 with no critical path ────────────────────────────────────────

NO_CP = _validate(*_chain(tf=400))


def test_no_critical_path_makes_check_2_red():
    c2 = NO_CP['checks']['constraint_driven']
    assert NO_CP['checks']['cp_identification']['cp_count'] == 0
    assert (c2['rating'], c2['score']) == ('RED', 0), (c2['rating'], c2['score'])
    assert c2['note'].startswith('No critical path identified.'), c2['note']


def test_no_critical_path_cannot_grade_green():
    assert NO_CP['overall_rating'] != 'GREEN', NO_CP['overall_rating']
    assert NO_CP['overall_confidence'] != 'High Confidence'
    assert 'constraint_driven' in NO_CP['red_checks'], NO_CP.get('red_checks')


def test_a_critical_path_keeps_check_2_on_its_constraint_reading():
    """Guard: with a critical path and no constraints Check 2 is GREEN."""
    r = _validate(*_chain(tf=0))
    c2 = r['checks']['constraint_driven']
    assert (c2['rating'], c2['score']) == ('GREEN', 100), (c2['rating'], c2['score'])


# ── A RED check caps the overall rating ──────────────────────────────────

OPEN_START = _validate(*_chain(tf=0, start_complete=False))
CLEAN = _validate(*_chain(tf=0))


def test_a_red_check_caps_a_green_score_at_amber():
    """The open start milestone is an open end on the critical path, so
    Check 3 is RED; the weighted score is still in the GREEN band."""
    r = OPEN_START
    assert r['checks']['open_ends_cp']['rating'] == 'RED'
    assert r['overall_score'] >= 80, r['overall_score']
    assert r['overall_rating'] == 'AMBER', r['overall_rating']
    assert r['overall_confidence'] == 'Moderate Confidence', r['overall_confidence']
    assert r['overall_rating_capped_by_red'] is True
    assert r['red_checks'] == ['open_ends_cp'], r['red_checks']


def test_the_cap_leaves_the_score_alone():
    """The score is the weighted average of the nine checks either way."""
    from cp_validator import CHECK_WEIGHTS
    r = OPEN_START
    weighted = sum(r['checks'][k]['score'] * w for k, w in CHECK_WEIGHTS.items())
    assert r['overall_score'] == round(weighted, 1), (r['overall_score'], weighted)


def test_no_red_check_no_cap():
    """Guard: the same schedule with its start milestone complete has no RED
    check, grades GREEN, and carries neither cap key."""
    assert [k for k, c in CLEAN['checks'].items() if c['rating'] == 'RED'] == []
    assert CLEAN['overall_rating'] == 'GREEN', CLEAN['overall_rating']
    assert CLEAN['overall_confidence'] == 'High Confidence'
    assert 'overall_rating_capped_by_red' not in CLEAN
    assert 'red_checks' not in CLEAN


# ── Check 5: the relationship-lag calendar ───────────────────────────────

# P on the 10 h calendar, S on the 8 h one, both critical; a lag between them.
def _mixed(lag):
    rows = [
        _row('1', 'START', 'TT_Mile', 'TK_Complete', 'EIGHT', 0, 0,
             '2026-10-05 08:00', '2026-10-05 08:00',
             ('2026-10-05 08:00', '2026-10-05 08:00')),
        _row('2', 'P', 'TT_Task', 'TK_NotStart', 'TEN', 50, 0,
             '2026-10-05 07:00', '2026-10-09 17:30'),
        _row('3', 'S', 'TT_Task', 'TK_NotStart', 'EIGHT', 40, 0,
             '2026-10-12 08:00', '2026-10-16 16:30'),
        _row('4', 'FIN', 'TT_FinMile', 'TK_NotStart', 'EIGHT', 0, 0,
             '2026-10-16 16:30', '2026-10-16 16:30'),
    ]
    links = [('1', '2', 0), ('2', '3', lag), ('3', '4', 0)]
    return rows, links


def _lead_finding(r):
    found = [x['finding'] for x in r['recommendations']
             if x['finding'].startswith('Negative lag')]
    assert len(found) == 1, r['recommendations']
    return found[0]


def test_by_default_a_lag_is_read_on_the_predecessor_calendar():
    """No SCHEDOPTIONS table: P6's default, the predecessor's calendar.
    -40 h on P's 10 h day is -4 working days (it read -5.0 at 8 h/day)."""
    r = _validate(*_mixed(-40))
    assert '(-4.0d)' in _lead_finding(r), _lead_finding(r)
    so = r['schedule_options']
    assert so['lag_calendar_role'] == 'predecessor'
    assert so['relationship_lag_calendar'] == 'rcal_Predecessor'
    assert 'absent' in so['relationship_lag_calendar_source']


def test_the_file_can_name_the_successor_calendar():
    r = _validate(*_mixed(-40), schedoptions='rcal_Successor')
    assert '(-5.0d)' in _lead_finding(r), _lead_finding(r)
    assert r['schedule_options']['lag_calendar_role'] == 'successor'
    assert r['schedule_options']['relationship_lag_calendar_source'] == (
        'SCHEDOPTIONS sched_calendar_on_relationship_lag=rcal_Successor')


def test_a_blank_setting_is_the_predecessor_default():
    r = _validate(*_mixed(-40), schedoptions='')
    assert '(-4.0d)' in _lead_finding(r), _lead_finding(r)
    assert 'blank' in r['schedule_options']['relationship_lag_calendar_source']


def test_an_excessive_lag_is_judged_in_the_right_working_days():
    """90 h is 9 working days on P's 10 h calendar, inside Check 5's
    10-day limit, and 11.25 on S's 8 h one, over it."""
    assert _validate(*_mixed(90))['checks']['lag_issues']['excessive_lags'] == 0
    assert _validate(*_mixed(90), schedoptions='rcal_Successor')[
        'checks']['lag_issues']['excessive_lags'] == 1


def test_the_setting_is_read_from_the_project_row():
    data = {'tables': {'SCHEDOPTIONS': {'records': [
        {'proj_id': '7', 'sched_calendar_on_relationship_lag': 'rcal_Predecessor'},
        {'proj_id': '9', 'sched_calendar_on_relationship_lag': 'rcal_Successor'},
    ]}}}
    assert _detect_schedule_options(data, '9')['lag_calendar_role'] == 'successor'
    assert _detect_schedule_options(data, '7')['lag_calendar_role'] == 'predecessor'
    # No row for the project: the table's first row.
    assert _detect_schedule_options(data, '8')['lag_calendar_role'] == 'predecessor'


def test_a_calendar_the_engine_does_not_walk_falls_back_to_the_successor():
    """The project and 24-hour calendars are not calendars cpp-cpm-engine
    walks a lag on; like the engine, the reading falls back to the
    successor's."""
    for token in ('rcal_Project', 'rcal_24Hour'):
        data = {'tables': {'SCHEDOPTIONS': {'records': [
            {'proj_id': '1', 'sched_calendar_on_relationship_lag': token}]}}}
        opts = _detect_schedule_options(data, '1')
        assert opts['relationship_lag_calendar'] == token
        assert opts['lag_calendar_role'] == 'successor', (token, opts)


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
