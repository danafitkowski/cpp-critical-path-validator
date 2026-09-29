#!/usr/bin/env python3
"""The bundled parser's two validation entry points run on a plain clone.

Run with: python tests/test_bundled_validation_runs.py

`scripts/xer_parser.py` is vendored from cpp-xer-parser and pinned in CI. Its
`validate_schedule` and `aace_31r_compliance` build their report from the
`validation.py` and `config_profiles.py` that ship next to it in scripts/.
The structure score in `aace_31r_compliance` calls
`ValidationReport.count(severity)`, which upstream added to its own
`validation.py` in 389ee14, the same commit whose parser changes reached this
repository when the parser was re-vendored at a8edac6. This repository's
`validation.py` stayed at the copy from before 389ee14, so on a plain clone
`validate_schedule` ran and `aace_31r_compliance` raised AttributeError.

Modelled on upstream's tests/test_bundled_validation_runs.py, these pin the
bundled modules together:

  - the two shipped modules bind, and they are the copies in scripts/;
  - `validate_schedule` returns a report on a sound synthetic schedule;
  - `aace_31r_compliance` returns the score its own findings give.
"""
import os
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BUNDLED = os.path.normpath(os.path.join(SCRIPT_DIR, '..', 'scripts'))
sys.path.insert(0, BUNDLED)

import xer_parser  # noqa: E402
from xer_parser import (  # noqa: E402
    parse_xer,
    validate_schedule,
    aace_31r_compliance,
    BLOCK,
    WARN,
)

TAB = '\t'

# Monday to Friday, 08:00 to 16:00, in the clndr_data form P6 writes.
_SHIFT = '(0||0(s|08:00|f|16:00)())'
_FIVE_DAY = ('(0||CalendarData()((0||DaysOfWeek()((0||1()())'
             + ''.join(f'(0||{d}()({_SHIFT}))' for d in range(2, 7))
             + '(0||7()())))(0||Exceptions()())))')


def _synthetic_xer(wbs_levels=3):
    """A three-activity chain in the shape of test_cp_validator's _build_xer.

    The work sits `wbs_levels` deep in the WBS. One level is below the
    minimum depth the parser applies for the commercial profile, which is a
    BLOCK finding; three levels is not.
    """
    wbs_rows = []
    parent = ''
    for level in range(1, wbs_levels + 1):
        wbs_id = f'W{level}'
        wbs_rows.append([wbs_id, parent, f'Level {level}', wbs_id, '1'])
        parent = wbs_id
    task_rows = [
        ['1', 'A', 'Activity A', '1', parent, 'C1', 'TK_NotStart', 'TT_Task',
         '40', '40', '0', '2026-03-02 08:00', '2026-03-06 16:00', 'Y', ''],
        ['2', 'B', 'Activity B', '1', parent, 'C1', 'TK_NotStart', 'TT_Task',
         '40', '40', '0', '2026-03-09 08:00', '2026-03-13 16:00', 'Y', ''],
        ['3', 'C', 'Activity C', '1', parent, 'C1', 'TK_NotStart', 'TT_FinMile',
         '0', '0', '0', '2026-03-13 16:00', '2026-03-13 16:00', 'Y', ''],
    ]
    pred_rows = [
        ['1', '2', '1', 'PR_FS', '0'],
        ['2', '3', '2', 'PR_FS', '0'],
    ]
    lines = [
        TAB.join(['ERMHDR', '24.12', '2026-03-02', 'Project', 'admin',
                  'Test', 'db', 'Project Management', 'USD']),
        TAB.join(['%T', 'PROJECT']),
        TAB.join(['%F', 'proj_id', 'proj_short_name', 'last_recalc_date',
                  'plan_end_date', 'scd_end_date']),
        TAB.join(['%R', '1', 'TEST', '2026-03-02 08:00',
                  '2026-03-13 16:00', '2026-03-13 16:00']),
        TAB.join(['%T', 'PROJWBS']),
        TAB.join(['%F', 'wbs_id', 'parent_wbs_id', 'wbs_name',
                  'wbs_short_name', 'proj_id']),
    ]
    lines += [TAB.join(['%R'] + row) for row in wbs_rows]
    lines += [
        TAB.join(['%T', 'CALENDAR']),
        TAB.join(['%F', 'clndr_id', 'clndr_name', 'day_hr_cnt',
                  'week_hr_cnt', 'clndr_data']),
        TAB.join(['%R', 'C1', '5-Day', '8', '40', _FIVE_DAY]),
        TAB.join(['%T', 'TASK']),
        TAB.join(['%F', 'task_id', 'task_code', 'task_name', 'proj_id',
                  'wbs_id', 'clndr_id', 'status_code', 'task_type',
                  'target_drtn_hr_cnt', 'remain_drtn_hr_cnt',
                  'total_float_hr_cnt', 'target_start_date',
                  'target_end_date', 'driving_path_flag', 'cstr_type']),
    ]
    lines += [TAB.join(['%R'] + row) for row in task_rows]
    lines += [
        TAB.join(['%T', 'TASKPRED']),
        TAB.join(['%F', 'task_pred_id', 'task_id', 'pred_task_id',
                  'pred_type', 'lag_hr_cnt']),
    ]
    lines += [TAB.join(['%R'] + row) for row in pred_rows]
    lines.append('%E')
    return '\r\n'.join(lines) + '\r\n'


def _parse(xer_text):
    with tempfile.NamedTemporaryFile('w', suffix='.xer', delete=False,
                                     encoding='utf-8', newline='') as f:
        f.write(xer_text)
        path = f.name
    try:
        return parse_xer(path)
    finally:
        os.unlink(path)


def test_the_shipped_validation_modules_bind_from_scripts():
    """validation.py and config_profiles.py ship in scripts/ and must bind.

    The parser puts a sibling _cpp_common/scripts ahead of its own directory
    when one exists, so this also checks that every module under test is the
    copy in this repository's scripts/. Otherwise the tests below could pass
    on modules a plain clone does not have.
    """
    assert xer_parser._VALIDATION_AVAILABLE is True, (
        'the parser did not bind validation.py and config_profiles.py')
    for name in ('xer_parser', 'validation', 'config_profiles'):
        where = os.path.dirname(os.path.abspath(sys.modules[name].__file__))
        assert os.path.samefile(where, BUNDLED), (
            f'{name} was imported from {where}, not from scripts/; these '
            f'tests must run on the copies a plain clone ships')


def test_validate_schedule_runs_on_a_plain_clone():
    """A sound schedule gets a report back, with no BLOCK finding."""
    report = validate_schedule(_parse(_synthetic_xer()), profile='commercial')

    assert isinstance(report, xer_parser.ValidationReport)
    blocks = report.by_severity(BLOCK)
    assert not blocks, (
        f'a sound schedule drew BLOCK findings: {[f.message for f in blocks]}')
    # The fixture's tables are abbreviated, which draws field-count warnings,
    # so a report with no WARN at all means the checks did not run.
    assert report.by_severity(WARN), 'no WARN findings: the checks did not run'


def test_aace_31r_compliance_scores_a_plain_clone_from_its_findings():
    """The structure score runs, and equals 100 less 20 per BLOCK finding and
    5 per WARN finding, held to 0-100.

    The expectation counts with counts(), so it does not lean on the
    count(severity) method the score itself calls. The one-level WBS draws a
    BLOCK, so both terms of the score are exercised.
    """
    for wbs_levels, blocks in ((3, []), (1, ['XER-WBS-DEPTH-LOW'])):
        result = aace_31r_compliance(_parse(_synthetic_xer(wbs_levels)),
                                     profile='commercial')
        report = result['findings']
        assert [f.check_id for f in report.by_severity(BLOCK)] == blocks, (
            f'{wbs_levels}-level WBS: BLOCK findings '
            f'{[f.check_id for f in report.by_severity(BLOCK)]}, '
            f'expected {blocks}')
        counts = report.counts()
        assert counts[WARN] > 0, f'{wbs_levels}-level WBS: no WARN findings'
        expected = max(0, min(100, 100 - 20 * counts[BLOCK] - 5 * counts[WARN]))
        assert result['score_100'] == expected, (
            f'{wbs_levels}-level WBS: score {result["score_100"]}, expected '
            f'{expected} from {counts[BLOCK]} BLOCK and {counts[WARN]} WARN')
        assert result['grade'] in ('A', 'B', 'C', 'D', 'F')


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
