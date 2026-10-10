#!/usr/bin/env python3
"""Hours convert to days on the hours a calendar's shifts work (2026-10-10),
when every working day works the same hours and CALENDAR.day_hr_cnt says
otherwise.

Run with: python tests/test_shift_hours_calendar_2026_10_10.py

P6 schedules a duration in hours against the calendar's shifts; day_hr_cnt
("Hours per Day") only converts hours to days for display. Scheduled with F9
in Primavera P6 Professional 23.12.1 on 10-Oct-2026, a Monday-Saturday
07:00-17:00 calendar declaring 8 ran a 40 h activity over four days. The
bundled parser (cpp-xer-parser v0.3.0) now gives such a calendar the shifts'
hours_per_day, and the validator reads every float, lag and duration through
it.

The fixture: a Monday-Friday calendar whose shifts work ten hours, declaring
day_hr_cnt 8. Eleven activities with 20 h of float and a critical chain at
-100 h with a 20 h lead on it. On the shifts' ten hours the eleven are 2
working days from critical, in Check 7's 1-2 day band, and the chain is -10
days with a -2 day lead. Read at the declared 8 h/day, as v0.3.1 read it, the
eleven were 2.5 days, the chain -12.5 and the lead -2.5. The same network on a
calendar declaring the ten its shifts work scores the same on every check.

The tests marked [discriminating] fail on v0.3.1.
"""
import os
import sys
import tempfile
import warnings as _warnings

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, '..', 'scripts'))

from xer_parser import parse_xer, get_calendar_map  # noqa: E402
from cp_validator import validate_critical_path  # noqa: E402

TAB = '\t'
DATA_DATE = '2026-09-21 07:00'      # a Monday morning
_TEN_HOURS = '(0||0(s|07:00|f|12:00)())(0||1(s|12:30|f|17:30)())'
_MON_FRI_TEN = ('(0||CalendarData()((0||DaysOfWeek()((0||1()())'
                + ''.join('(0||%d()(%s))' % (d, _TEN_HOURS) for d in range(2, 7))
                + '(0||7()())))(0||Exceptions()())))')

_TASK_COLS = ['task_id', 'task_code', 'task_name', 'proj_id', 'wbs_id',
              'clndr_id', 'status_code', 'task_type', 'target_drtn_hr_cnt',
              'remain_drtn_hr_cnt', 'total_float_hr_cnt', 'act_start_date',
              'act_end_date', 'early_start_date', 'early_end_date',
              'late_start_date', 'late_end_date', 'target_start_date',
              'target_end_date', 'driving_path_flag', 'cstr_type', 'cstr_date']


def _row(tid, code, ttype, hrs, tf, es, ef, *, status='TK_NotStart', drv='N'):
    done = status == 'TK_Complete'
    return [tid, code, 'Neutral ' + code, '1', 'W1', 'C', status, ttype,
            str(hrs), '0' if done else str(hrs), '' if done else str(tf),
            es if done else '', ef if done else '', es, ef, es, ef, es, ef,
            drv, '', '']


def _rows():
    rows = [
        _row('100', 'START', 'TT_Mile', 0, '', '2026-09-18 17:30',
             '2026-09-18 17:30', status='TK_Complete'),
        _row('110', 'C1', 'TT_Task', 100, -100, DATA_DATE, '2026-10-02 17:30',
             drv='Y'),
        _row('120', 'FIN', 'TT_FinMile', 0, -100, '2026-10-02 17:30',
             '2026-10-02 17:30', drv='Y'),
    ]
    rows += [_row(str(200 + i), 'N%02d' % i, 'TT_Task', 50, 20, DATA_DATE,
                  '2026-09-25 17:30') for i in range(1, 12)]
    return rows


def _rels():
    rels = [('110', '100'), ('120', '110', -20)]      # a 20 h lead into FIN
    for i in range(1, 12):
        rels += [(str(200 + i), '100'), ('120', str(200 + i))]
    return rels


def _xer(day_hr_cnt):
    lines = [
        TAB.join(['ERMHDR', '20.12', '2026-09-21', 'Project', 'admin', 'admin',
                  'dbxDatabaseNoName', 'Project Management', 'USD']),
        TAB.join(['%T', 'PROJECT']),
        TAB.join(['%F', 'proj_id', 'proj_short_name', 'last_recalc_date',
                  'plan_end_date', 'scd_end_date', 'clndr_id']),
        TAB.join(['%R', '1', 'NEUTRAL', DATA_DATE, '', '', 'C']),
        TAB.join(['%T', 'PROJWBS']),
        TAB.join(['%F', 'wbs_id', 'parent_wbs_id', 'wbs_name',
                  'wbs_short_name', 'proj_id']),
        TAB.join(['%R', 'W1', '', 'Root', 'W1', '1']),
        TAB.join(['%T', 'CALENDAR']),
        TAB.join(['%F', 'clndr_id', 'default_flag', 'clndr_name', 'clndr_type',
                  'day_hr_cnt', 'week_hr_cnt', 'clndr_data']),
        TAB.join(['%R', 'C', 'Y', 'Ten Hour Shifts', 'CA_Base', day_hr_cnt, '50',
                  _MON_FRI_TEN]),
        TAB.join(['%T', 'TASK']),
        TAB.join(['%F'] + _TASK_COLS),
    ]
    lines += [TAB.join(['%R'] + r) for r in _rows()]
    lines += [
        TAB.join(['%T', 'TASKPRED']),
        TAB.join(['%F', 'task_pred_id', 'task_id', 'pred_task_id',
                  'pred_type', 'lag_hr_cnt']),
    ]
    lines += [TAB.join(['%R', str(i), rel[0], rel[1], 'PR_FS',
                        str(rel[2] if len(rel) > 2 else 0)])
              for i, rel in enumerate(_rels(), 1)]
    lines.append('%E')
    return '\r\n'.join(lines) + '\r\n'


def _parse(day_hr_cnt):
    with tempfile.NamedTemporaryFile('w', suffix='.xer', delete=False,
                                     encoding='utf-8') as f:
        f.write(_xer(day_hr_cnt))
        path = f.name
    try:
        return parse_xer(path)
    finally:
        os.unlink(path)


def _validate(day_hr_cnt):
    with _warnings.catch_warnings():
        _warnings.simplefilter('ignore')
        return validate_critical_path(_parse(day_hr_cnt))


def _cp_float(results, code):
    return next(a['total_float_days'] for a in results['critical_path_activities']
                if a['task_code'] == code)


def _near_critical_days(results):
    return sorted({a['total_float_days'] for a in results['near_critical_activities']})


def _lead(results):
    return next(r['finding'] for r in results['recommendations']
                if r['category'] == 'Negative Lags on CP')


def _scores(results):
    return {k: v.get('score') for k, v in results['checks'].items()}


DECLARED_8 = _validate('8')
DECLARED_10 = _validate('10')


def test_the_calendar_converts_on_the_ten_hours_its_shifts_work():
    """[discriminating]"""
    with _warnings.catch_warnings():
        _warnings.simplefilter('ignore')
        cal = get_calendar_map(_parse('8'))['C']
    assert cal['hours_per_day'] == 10.0
    assert cal['declared_hours_per_day'] == 8.0


def test_float_and_lag_read_in_days_of_ten_hours():
    """[discriminating]"""
    assert _cp_float(DECLARED_8, 'C1') == -10.0               # was -12.5
    assert _near_critical_days(DECLARED_8) == [2.0]           # was 2.5
    assert _lead(DECLARED_8).startswith('Negative lag (-2.0d) on CP: C1')   # was -2.5d
    assert DECLARED_8['checks']['near_critical']['bands']['1-2d'] == 11     # was 0


def test_every_check_scores_as_on_a_calendar_declaring_its_shifts():
    """[discriminating]"""
    assert _scores(DECLARED_8) == _scores(DECLARED_10)
    for key in ('overall_score', 'overall_rating', 'overall_confidence'):
        assert DECLARED_8[key] == DECLARED_10[key], key


def test_a_calendar_declaring_its_shifts_is_unchanged():
    assert _cp_float(DECLARED_10, 'C1') == -10.0
    assert _near_critical_days(DECLARED_10) == [2.0]
    with _warnings.catch_warnings():
        _warnings.simplefilter('ignore')
        cal = get_calendar_map(_parse('10'))['C']
    assert cal['hours_per_day'] == 10.0
    assert 'declared_hours_per_day' not in cal


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
