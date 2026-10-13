#!/usr/bin/env python3
"""The data date and the empty calendar record, read as P6 schedules them
(2026-10-13), through the bundled parser (cpp-xer-parser v0.4.0).

Run with: python tests/test_p6_rules_2026_10_13.py

- An EMPTY calendar record (no clndr_data) is P6's internal Standard, Monday
  to Friday, eight hours a day, whatever day_hr_cnt declares: measured on
  Primavera P6 Professional 23.12.1's own F9, records declaring 10, 6 and
  24 hours ran the same 08:00-16:00 days. The fixture's network sits on an
  empty record declaring 10: its eleven activities with 20 h of float are 2.5
  working days from critical, not 2, and the chain at -100 h is -12.5 days,
  not -10, exactly as on an empty record declaring 8.
- A blank PROJECT.last_recalc_date is the planned start, and a filed data
  date on an earlier day than the planned start is lifted to it, as P6 lifts
  it when it opens the project. The results' data_date is the date P6
  schedules from, and data_date_source says where it came from.

The tests marked [discriminating] fail on v0.4.0. The other data-date test
fails there too, only because data_date_source is new.
"""
import os
import sys
import tempfile
import warnings as _warnings

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, '..', 'scripts'))

from xer_parser import parse_xer  # noqa: E402
from cp_validator import validate_critical_path  # noqa: E402

TAB = '\t'
DATA_DATE = '2026-09-21 08:00'      # a Monday morning

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
        _row('100', 'START', 'TT_Mile', 0, '', '2026-09-18 16:00',
             '2026-09-18 16:00', status='TK_Complete'),
        _row('110', 'C1', 'TT_Task', 100, -100, DATA_DATE, '2026-10-05 12:00',
             drv='Y'),
        _row('120', 'FIN', 'TT_FinMile', 0, -100, '2026-10-05 12:00',
             '2026-10-05 12:00', drv='Y'),
    ]
    rows += [_row(str(200 + i), 'N%02d' % i, 'TT_Task', 50, 20, DATA_DATE,
                  '2026-09-28 10:00') for i in range(1, 12)]
    return rows


def _rels():
    rels = [('110', '100'), ('120', '110')]
    for i in range(1, 12):
        rels += [(str(200 + i), '100'), ('120', str(200 + i))]
    return rels


def _xer(day_hr_cnt, *, data_date=DATA_DATE, plan_start=''):
    lines = [
        TAB.join(['ERMHDR', '20.12', '2026-09-21', 'Project', 'admin', 'admin',
                  'dbxDatabaseNoName', 'Project Management', 'USD']),
        TAB.join(['%T', 'PROJECT']),
        TAB.join(['%F', 'proj_id', 'proj_short_name', 'last_recalc_date',
                  'plan_start_date', 'plan_end_date', 'scd_end_date', 'clndr_id']),
        TAB.join(['%R', '1', 'NEUTRAL', data_date, plan_start, '', '', 'C']),
        TAB.join(['%T', 'PROJWBS']),
        TAB.join(['%F', 'wbs_id', 'parent_wbs_id', 'wbs_name',
                  'wbs_short_name', 'proj_id']),
        TAB.join(['%R', 'W1', '', 'Root', 'W1', '1']),
        TAB.join(['%T', 'CALENDAR']),
        TAB.join(['%F', 'clndr_id', 'default_flag', 'clndr_name', 'clndr_type',
                  'day_hr_cnt', 'week_hr_cnt', 'clndr_data']),
        # an EMPTY record: no clndr_data
        TAB.join(['%R', 'C', 'Y', 'Empty Record', 'CA_Base', day_hr_cnt,
                  str(float(day_hr_cnt) * 5), '']),
        TAB.join(['%T', 'TASK']),
        TAB.join(['%F'] + _TASK_COLS),
    ]
    lines += [TAB.join(['%R'] + r) for r in _rows()]
    lines += [
        TAB.join(['%T', 'TASKPRED']),
        TAB.join(['%F', 'task_pred_id', 'task_id', 'pred_task_id',
                  'pred_type', 'lag_hr_cnt']),
    ]
    lines += [TAB.join(['%R', str(i), rel[0], rel[1], 'PR_FS', '0'])
              for i, rel in enumerate(_rels(), 1)]
    lines.append('%E')
    return '\r\n'.join(lines) + '\r\n'


def _validate(day_hr_cnt, **kw):
    with tempfile.NamedTemporaryFile('w', suffix='.xer', delete=False,
                                     encoding='utf-8') as f:
        f.write(_xer(day_hr_cnt, **kw))
        path = f.name
    try:
        with _warnings.catch_warnings():
            _warnings.simplefilter('ignore')
            return validate_critical_path(parse_xer(path))
    finally:
        os.unlink(path)


def _cp_float(results, code):
    return next(a['total_float_days'] for a in results['critical_path_activities']
                if a['task_code'] == code)


def _near_critical_days(results):
    return sorted({a['total_float_days'] for a in results['near_critical_activities']})


def _scores(results):
    return {k: v.get('score') for k, v in results['checks'].items()}


DECLARED_10 = _validate('10')
DECLARED_8 = _validate('8')


def test_an_empty_record_declaring_ten_converts_at_eight():
    """[discriminating]"""
    assert _cp_float(DECLARED_10, 'C1') == -12.5               # was -10.0
    assert _near_critical_days(DECLARED_10) == [2.5]           # was 2.0


def test_an_empty_record_scores_the_same_whatever_it_declares():
    """[discriminating]"""
    assert _scores(DECLARED_10) == _scores(DECLARED_8)
    for key in ('overall_score', 'overall_rating', 'overall_confidence'):
        assert DECLARED_10[key] == DECLARED_8[key], key


def test_a_data_date_filed_on_or_after_the_planned_start_is_the_files_own():
    r = _validate('8', plan_start='2026-09-14 08:00')
    assert r['data_date'] == DATA_DATE
    assert r['data_date_source'] == 'PROJECT.last_recalc_date'


def test_a_blank_data_date_is_the_planned_start_and_says_so():
    """[discriminating]"""
    r = _validate('8', data_date='', plan_start=DATA_DATE)
    assert r['data_date'] == DATA_DATE
    assert r['data_date_source'] == (
        'PROJECT.plan_start_date (blank PROJECT.last_recalc_date, read as P6 schedules it)')


def test_a_data_date_on_an_earlier_day_is_lifted_to_the_planned_start_and_says_so():
    """[discriminating]"""
    r = _validate('8', data_date='2026-09-18 08:00', plan_start=DATA_DATE)
    assert r['data_date'] == DATA_DATE
    assert r['data_date_source'].startswith('PROJECT.plan_start_date')
    assert '2026-09-18 08:00' in r['data_date_source']
    assert 'blank' not in r['data_date_source']


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
