"""Regression (2026-09-29): DCMA-14 #13 counts a finish-first seven-day week as
seven working days.

P6 writes a working time slot start-first, ``(s|06:00|f|12:00)``, or
finish-first, ``(f|12:00|s|06:00)``, and the order belongs to the calendar.
The parser this repository bundled before cpp-xer-parser v0.2.0 recognised
start-first slots only, so a finish-first calendar decoded to an empty week
(``work_days == []``). #13 CPLI measures the critical path in working days on
the project calendar, and an empty week is counted as Monday to Friday: on a
seven-day calendar a Monday-to-Monday critical path read as 5 working days
instead of 7, and every CPLI on such a calendar was computed on the wrong
length.

The fixture: a seven-day, 12 h/day project calendar written finish-first,

    START  ->  A  84 h  ->  FIN   (FIN's total float -12 h = -1 day)

with the data date on Monday 2026-10-05 and FIN on the following Monday,
2026-10-12. On a seven-day week the critical path is 7 working days long and
CPLI = (7 - 1) / 7. The old parser gave 5 days and (5 - 1) / 5. The same
schedule written start-first is the control: both orders must read alike.
Every calendar string is built in this file; no real export is copied.
"""
import os
import sys
import tempfile
import warnings as _warnings

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, '..', 'scripts'))

from xer_parser import get_calendar_map, parse_xer  # noqa: E402
from dcma14 import dcma_14_assess  # noqa: E402

TAB = '\t'
_FINISH_FIRST = '(0||0(f|12:00|s|06:00)())(0||1(f|18:00|s|12:00)())'
_START_FIRST = '(0||0(s|06:00|f|12:00)())(0||1(s|12:00|f|18:00)())'

# Wednesday 2026-10-07 on the 1899-12-30 serial epoch.
_WED_2026_10_07 = 46302


def _seven_day(shift, holiday=None):
    exceptions = '(0||Exceptions()())'
    if holiday is not None:
        exceptions = '(0||Exceptions()((0||0(d|%d)())))' % holiday
    return ('(0||CalendarData()((0||DaysOfWeek()('
            + ''.join('(0||%d()(%s))' % (d, shift) for d in range(1, 8))
            + '))' + exceptions + '))')


_TASK_COLS = ['task_id', 'task_code', 'task_name', 'proj_id', 'wbs_id',
              'clndr_id', 'status_code', 'task_type', 'target_drtn_hr_cnt',
              'remain_drtn_hr_cnt', 'total_float_hr_cnt', 'early_start_date',
              'early_end_date', 'late_start_date', 'late_end_date',
              'target_start_date', 'target_end_date', 'driving_path_flag',
              'cstr_type', 'cstr_date']


def _task(tid, code, ttype, hrs, tf, es, ef):
    return [tid, code, 'Neutral ' + code, '1', 'W1', 'SEVEN', 'TK_NotStart',
            ttype, str(hrs), str(hrs), str(tf), es, ef, es, ef, es, ef, 'Y', '', '']


def _build_xer(shift, holiday=None):
    rows = [
        _task('1', 'START', 'TT_Mile', 0, -12, '2026-10-05 06:00', '2026-10-05 06:00'),
        _task('2', 'A', 'TT_Task', 84, -12, '2026-10-06 06:00', '2026-10-12 18:00'),
        _task('3', 'FIN', 'TT_FinMile', 0, -12, '2026-10-12 18:00', '2026-10-12 18:00'),
    ]
    lines = [
        TAB.join(['ERMHDR', '20.12', '2026-10-05', 'Project', 'admin', 'admin',
                  'dbxDatabaseNoName', 'Project Management', 'USD']),
        TAB.join(['%T', 'PROJECT']),
        TAB.join(['%F', 'proj_id', 'proj_short_name', 'last_recalc_date',
                  'plan_end_date', 'scd_end_date', 'clndr_id']),
        TAB.join(['%R', '1', 'NEUTRAL', '2026-10-05 06:00', '',
                  '2026-10-12 18:00', 'SEVEN']),
        TAB.join(['%T', 'PROJWBS']),
        TAB.join(['%F', 'wbs_id', 'parent_wbs_id', 'wbs_name',
                  'wbs_short_name', 'proj_id']),
        TAB.join(['%R', 'W1', '', 'Root', 'W1', '1']),
        TAB.join(['%T', 'CALENDAR']),
        TAB.join(['%F', 'clndr_id', 'default_flag', 'clndr_name', 'clndr_type',
                  'day_hr_cnt', 'week_hr_cnt', 'clndr_data']),
        TAB.join(['%R', 'SEVEN', 'Y', 'Seven Day', 'CA_Base', '12', '84',
                  _seven_day(shift, holiday)]),
        TAB.join(['%T', 'TASK']),
        TAB.join(['%F'] + _TASK_COLS),
    ]
    lines += [TAB.join(['%R'] + r) for r in rows]
    lines += [
        TAB.join(['%T', 'TASKPRED']),
        TAB.join(['%F', 'task_pred_id', 'task_id', 'pred_task_id',
                  'pred_type', 'lag_hr_cnt']),
        TAB.join(['%R', '1', '2', '1', 'PR_FS', '0']),
        TAB.join(['%R', '2', '3', '2', 'PR_FS', '0']),
        '%E',
    ]
    return '\r\n'.join(lines) + '\r\n'


def _parse(xer_text):
    with tempfile.NamedTemporaryFile('w', suffix='.xer', delete=False,
                                     encoding='utf-8') as f:
        f.write(xer_text)
        path = f.name
    try:
        with _warnings.catch_warnings():
            _warnings.simplefilter('ignore')
            return parse_xer(path)
    finally:
        os.unlink(path)


def _cpli(data):
    with _warnings.catch_warnings():
        _warnings.simplefilter('ignore')
        return dcma_14_assess(data)['per_check']['DCMA-13-CPLI']


FINISH_FIRST = _parse(_build_xer(_FINISH_FIRST))
START_FIRST = _parse(_build_xer(_START_FIRST))


def test_the_serial_is_the_date_named():
    from datetime import date, timedelta
    assert date(1899, 12, 30) + timedelta(days=_WED_2026_10_07) == date(2026, 10, 7)


def test_the_finish_first_calendar_decodes_to_a_seven_day_week():
    """The defect at its source: this was [], which is counted as Mon-Fri."""
    cal = get_calendar_map(FINISH_FIRST)['SEVEN']
    assert cal['work_days'] == [0, 1, 2, 3, 4, 5, 6], cal['work_days']


def test_cpli_counts_seven_working_days_a_week():
    c = _cpli(FINISH_FIRST)
    assert c['details']['cp_length_days'] == 7, c['details']   # was 5
    assert abs(c['details']['tf_days'] - (-1.0)) < 1e-9, c['details']
    assert abs(c['value'] - 6 / 7) < 1e-9, c['value']            # was 0.8


def test_both_slot_orders_read_alike():
    """Control: the start-first twin of the same schedule, which the old
    parser already read correctly, gives the same #13."""
    assert get_calendar_map(START_FIRST)['SEVEN']['work_days'] == [0, 1, 2, 3, 4, 5, 6]
    ff, sf = _cpli(FINISH_FIRST), _cpli(START_FIRST)
    assert (ff['severity'], ff['value'], ff['details']) == (sf['severity'], sf['value'], sf['details'])


def test_a_holiday_inside_the_window_is_a_day_off():
    """An empty-body exception is a holiday: Wednesday comes off the seven."""
    data = _parse(_build_xer(_FINISH_FIRST, holiday=_WED_2026_10_07))
    assert '2026-10-07' in get_calendar_map(data)['SEVEN']['holidays']
    assert _cpli(data)['details']['cp_length_days'] == 6


if __name__ == '__main__':
    tests = [
        test_the_serial_is_the_date_named,
        test_the_finish_first_calendar_decodes_to_a_seven_day_week,
        test_cpli_counts_seven_working_days_a_week,
        test_both_slot_orders_read_alike,
        test_a_holiday_inside_the_window_is_a_day_off,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f'PASS  {t.__name__}')
        except AssertionError as e:
            failed += 1
            print(f'FAIL  {t.__name__}: {e}')
    print(f'\n{len(tests) - failed}/{len(tests)} passed')
    sys.exit(1 if failed else 0)
