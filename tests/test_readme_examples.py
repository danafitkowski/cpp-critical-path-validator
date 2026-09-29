#!/usr/bin/env python3
"""The Python examples in README.md run.

Run with: python tests/test_readme_examples.py

Every ```python block in README.md that calls validate_critical_path,
dcma_14_assess or trace_driving_path is run against a synthetic schedule, in
the order the README gives them and in one namespace, the way a reader pastes
them into one session: the custom-profile and tracer examples use the `data`
an earlier example parsed. Each XER path in a block is replaced by the
fixture, written to a temporary folder, and each HTML path by a file in that
folder. A block that raises fails the test, which gives the README line that
raised and the exception.

Three of the four examples raised before this test existed:

* the quick start printed results['cp_confidence_score'] and
  results['cp_confidence_band'], keys validate_critical_path does not return
  (KeyError). The score is overall_score, the band overall_confidence and its
  colour overall_rating;
* the custom-profile example passed a threshold dict to dcma_14_assess, whose
  bundled get_profile looks a profile up by name (TypeError);
* the tracer read step['task_code'], step['total_float_days'] and
  step['rel_type'] from the plain activity codes trace_driving_path returns
  (TypeError).
"""
import contextlib
import io
import os
import re
import sys
import tempfile
import textwrap
import traceback

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(SCRIPT_DIR, '..'))
README = os.path.join(REPO, 'README.md')
sys.path.insert(0, os.path.join(REPO, 'scripts'))

from xer_parser import parse_xer  # noqa: E402
from dcma14 import trace_driving_path  # noqa: E402

ENTRY_POINTS = ('validate_critical_path', 'dcma_14_assess', 'trace_driving_path')

_FENCE = re.compile(r'^([ \t]*)```python[ \t]*\n(.*?)^\1```[ \t]*$', re.M | re.S)
_HEADING = re.compile(r'^#{2,3} +(.+?) *$', re.M)
_CALL = re.compile(r'\b(%s)\s*\(' % '|'.join(ENTRY_POINTS))
_XER_PATH = re.compile(r'''(['"])[^'"\n]*\.xer\1''')
_HTML_PATH = re.compile(r'''(['"])([^'"\n]*\.html)\1''')
_TASK_CODE = re.compile(r'''\btask_code\s*=\s*(['"])([^'"\n]+)\1''')


def readme_examples():
    """(heading, line, source) for each ```python block that calls an entry
    point, in README order: the section the block sits under, the README line
    its code starts on, and the code, dedented where the fence is indented."""
    with open(README, encoding='utf-8') as f:
        text = f.read()
    examples = []
    for m in _FENCE.finditer(text):
        source = textwrap.dedent(m.group(2))
        if _CALL.search(source):
            headings = _HEADING.findall(text, 0, m.start())
            examples.append((headings[-1] if headings else 'README.md',
                             text.count('\n', 0, m.start(2)) + 1, source))
    return examples


# ─────────────────────────────────────────────────────────────── the fixture
# Mon-Fri, 08:00-12:00 and 13:00-17:00. A1050.20 is the code the tracer
# example names: it is driven by A1010.10, which is driven by the completed
# A1000, so the tracer has a chain of three to return.

TAB = '\t'
DATA_DATE = '2026-09-21 07:00'      # a Monday morning

_SHIFT = '(0||0(s|08:00|f|12:00)())(0||1(s|13:00|f|17:00)())'
_CLNDR_DATA = ('(0||CalendarData()((0||DaysOfWeek()((0||1()())'
               + ''.join('(0||%d()(%s))' % (d, _SHIFT) for d in range(2, 7))
               + '(0||7()())))(0||Exceptions()())))')

_TASK_COLS = ['task_id', 'task_code', 'task_name', 'proj_id', 'wbs_id',
              'clndr_id', 'status_code', 'task_type', 'target_drtn_hr_cnt',
              'remain_drtn_hr_cnt', 'total_float_hr_cnt', 'act_start_date',
              'act_end_date', 'early_start_date', 'early_end_date',
              'late_start_date', 'late_end_date', 'target_start_date',
              'target_end_date', 'driving_path_flag', 'cstr_type', 'cstr_date']


def _task(tid, code, name, ttype, hours, tf, start, finish, late=None, *,
          status='TK_NotStart', driving='N'):
    done = status == 'TK_Complete'
    late_start, late_finish = late or (start, finish)
    return [tid, code, name, '1', 'W1', 'STD', status, ttype, str(hours),
            '0' if done else str(hours), '' if done else str(tf),
            start if done else '', finish if done else '', start, finish,
            late_start, late_finish, start, finish, driving, '', '']


_TASKS = [
    _task('100', 'A1000', 'Notice to proceed', 'TT_Mile', 0, 0,
          '2026-09-18 17:00', '2026-09-18 17:00', status='TK_Complete'),
    _task('110', 'A1010.10', 'Excavation', 'TT_Task', 40, 0,
          '2026-09-21 08:00', '2026-09-25 17:00', driving='Y'),
    _task('120', 'A1050.20', 'Foundations', 'TT_Task', 40, 0,
          '2026-09-28 08:00', '2026-10-02 17:00', driving='Y'),
    _task('130', 'A1060', 'Site services', 'TT_Task', 16, 24,
          '2026-09-28 08:00', '2026-09-29 17:00',
          late=('2026-10-01 08:00', '2026-10-02 17:00')),
    _task('140', 'A1090', 'Substantial completion', 'TT_FinMile', 0, 0,
          '2026-10-02 17:00', '2026-10-02 17:00', driving='Y'),
]
_RELATIONSHIPS = [('110', '100'), ('120', '110'), ('130', '110'),
                  ('140', '120'), ('140', '130')]     # (successor, predecessor)


def fixture_xer():
    lines = [
        TAB.join(['ERMHDR', '20.12', '2026-09-21', 'Project', 'admin', 'admin',
                  'dbxDatabaseNoName', 'Project Management', 'USD']),
        TAB.join(['%T', 'PROJECT']),
        TAB.join(['%F', 'proj_id', 'proj_short_name', 'last_recalc_date',
                  'plan_end_date', 'scd_end_date', 'clndr_id']),
        TAB.join(['%R', '1', 'EXAMPLE', DATA_DATE, '', '2026-10-02 17:00',
                  'STD']),
        TAB.join(['%T', 'PROJWBS']),
        TAB.join(['%F', 'wbs_id', 'parent_wbs_id', 'wbs_name',
                  'wbs_short_name', 'proj_id']),
        TAB.join(['%R', 'W1', '', 'Example', 'W1', '1']),
        TAB.join(['%T', 'CALENDAR']),
        TAB.join(['%F', 'clndr_id', 'default_flag', 'clndr_name', 'clndr_type',
                  'day_hr_cnt', 'week_hr_cnt', 'clndr_data']),
        TAB.join(['%R', 'STD', 'Y', 'Standard', 'CA_Base', '8', '40',
                  _CLNDR_DATA]),
        TAB.join(['%T', 'TASK']),
        TAB.join(['%F'] + _TASK_COLS),
    ]
    lines += [TAB.join(['%R'] + row) for row in _TASKS]
    lines += [
        TAB.join(['%T', 'TASKPRED']),
        TAB.join(['%F', 'task_pred_id', 'task_id', 'pred_task_id',
                  'pred_type', 'lag_hr_cnt']),
    ]
    lines += [TAB.join(['%R', str(i), succ, pred, 'PR_FS', '0'])
              for i, (succ, pred) in enumerate(_RELATIONSHIPS, 1)]
    lines.append('%E')
    return '\r\n'.join(lines) + '\r\n'


def _write_fixture(folder):
    path = os.path.join(folder, 'example.xer')
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(fixture_xer())
    return path


# ──────────────────────────────────────────────────────────── the runner

def _failure(exc, label, heading, first_line, source):
    """The README line that raised, and what it raised."""
    frames = [fr for fr in traceback.extract_tb(exc.__traceback__)
              if fr.filename == label]
    if not frames:
        return 'README.md:%d ("%s"): %s: %s' % (
            first_line, heading, type(exc).__name__, exc)
    lineno = frames[-1].lineno
    return 'README.md:%d ("%s"): %s\n    %s: %s' % (
        first_line + lineno - 1, heading,
        source.splitlines()[lineno - 1].strip(), type(exc).__name__, exc)


def run_examples(examples, folder):
    """Run the examples in order in one namespace, against the fixture written
    into `folder`, which also takes every file an example writes. Returns one
    line per example that raised."""
    xer = _write_fixture(folder)
    namespace = {'__name__': '__readme__'}
    failures = []
    saved_path = sys.path[:]
    try:
        for n, (heading, first_line, source) in enumerate(examples, 1):
            code = _XER_PATH.sub(lambda m: repr(xer), source)
            code = _HTML_PATH.sub(
                lambda m: repr(os.path.join(folder, os.path.basename(m.group(2)))),
                code)
            label = '<README.md example %d>' % n
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    exec(compile(code, label, 'exec'), namespace)
            except Exception as exc:
                failures.append(_failure(exc, label, heading, first_line, source))
    finally:
        sys.path[:] = saved_path
    return failures


# ─────────────────────────────────────────────────────────────── the tests

def test_the_readme_has_an_example_for_each_entry_point():
    """Were the fences to change shape, the run below would find no example
    and pass by running nothing."""
    called = set()
    for _, _, source in readme_examples():
        called.update(_CALL.findall(source))
    assert called == set(ENTRY_POINTS), (
        'no README example calls %s' % ', '.join(sorted(set(ENTRY_POINTS) - called)))


def test_every_activity_an_example_names_has_a_chain_in_the_fixture():
    """trace_driving_path returns an empty list for a code the file does not
    carry, and an example looping over nothing cannot fail."""
    named = [code for _, _, source in readme_examples()
             for _, code in _TASK_CODE.findall(source)]
    assert named, 'no README example names an activity'
    with tempfile.TemporaryDirectory() as folder:
        data = parse_xer(_write_fixture(folder))
    for code in named:
        chain = trace_driving_path(data, code)
        assert len(chain) > 1 and chain[-1] == code, (
            'the fixture gives %s no driving chain (%r): add it, with a '
            'predecessor, to _TASKS' % (code, chain))


def test_every_readme_example_runs():
    examples = readme_examples()
    with tempfile.TemporaryDirectory() as folder:
        failures = run_examples(examples, folder)
    assert not failures, '%d of %d README examples raised:\n%s' % (
        len(failures), len(examples), '\n'.join(failures))


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
