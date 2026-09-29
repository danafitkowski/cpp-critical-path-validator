# Changelog

All notable changes to `cpp-critical-path-validator` are documented here. Versioning follows [Semantic Versioning](https://semver.org).

---

## Unreleased

The validator gives the embedded DCMA-14 report's worst severity at the top level of its
results, beside a headline now labelled as logic health, as CPP's internal validator
does. The bundled parser files are `cpp-xer-parser` v0.2.1's, whose report carries the
summary this reads. No existing result moves: the change adds keys and a dashboard line.

### Added

- **`results['dcma_worst_severity']`**, always present: the worst severity in the
  embedded DCMA-14 report (`BLOCK`, `WARN`, `INFO` or `PASS`), read from its summary, or
  `None` where DCMA-14 did not run. Where it ran,
  **`results['dcma_blocks_despite_logic_rating']`** is `True` when that severity is
  `BLOCK`. The headline score, rating and confidence grade logic health from the nine
  checks, and the DCMA-14 report can say BLOCK on its own, for example for an actual
  start after the data date (#9). That BLOCK was only in the embedded report's findings,
  and the bundled `validation.py` gave the report no summary to read it from. On a
  four-activity chain whose first task has an actual start two months past the data
  date, the headline reads 96.3, GREEN, High Confidence, and `dcma_worst_severity` now
  reads BLOCK. It is a read-up, not a re-derivation: the score, the RED-check cap and the
  embedded report are unchanged.
- **`results['overall_rating_scope']`** (`'logic_health'`) and
  **`results['overall_rating_label']`** (`'Logic Health'`), always present, say what the
  headline grades, so that it is not read as a DCMA-14 verdict.
- The dashboard shows the DCMA-14 recommendation under the gauge (Must Fix, Warn, Info or
  Pass) and, for Must Fix, says the score grades logic health only. Nothing is shown when
  DCMA-14 did not run.

  The new keys and the read-up are AST-identical to CPP's internal validator; the
  dashboard line is this repository's own, as the two dashboards differ. The v0.3.0
  entry that said `dcma_worst_severity` was not ported now says this release ports it.
  `tests/test_dcma_worst_severity_2026_09_29.py` has 12 synthetic tests. Against v0.3.0,
  9 of them fail; with the new validator but v0.3.0's `validation.py`, 7 fail. Of 11
  mutants of the port, 10 are killed. The survivor drops a guard against a summary with
  no worst severity, which the bundled report cannot produce: an empty report's is PASS.
  CI runs the file under pytest and directly. The suite is 218 tests.

### Changed

- **The bundled parser files are re-vendored** from `cpp-xer-parser` at its release
  [`v0.2.1`](https://github.com/danafitkowski/cpp-xer-parser/releases/tag/v0.2.1),
  commit `ca39d88`. `validation.py` gains the report `summary` (the count at each
  severity, the total and `worst_severity`), the `worst_severity` property and `count()`
  with no argument; nothing it produced before moves. `xer_parser.py` and
  `config_profiles.py` are byte-identical to v0.2.0's, so `XER_SHA256` is unchanged and
  `XER_PIN` moves to the new commit. The README names the release and says the two
  support files come from it too.

---

## v0.3.0 — 2026-09-29

The second release of the day. A blank activity calendar id is read as the project
calendar; the bundled parser is `cpp-xer-parser` v0.2.0, which decodes finish-first
calendars; and four scoring rules come over from CPP's internal validator: a logic cycle
grades RED, Check 2 is RED where there is no critical path, a RED check caps the overall
rating, and Check 5 converts a lag on the calendar P6 measures it on. The README's
examples run, and what it says about the public engine is corrected.

**Results a caller may see move.** No function signature changed, but results did, each
from wrong to right:

- `overall_score`, `overall_rating` and `overall_confidence`: a schedule with a logic
  cycle reads 0, RED, Unreliable, and a schedule with any RED check can no longer read
  GREEN or High Confidence (the score itself is unchanged by the cap).
- `checks.constraint_driven` is RED 0 where there is no critical path; it was GREEN 100.
- `checks.lag_issues` and its recommendations read a lag in the working days of the
  predecessor's calendar unless the file names the successor's.
- Float, duration and lag on an activity with a blank calendar id are read on the
  project calendar, and DCMA-14 #13 and Check 3's working-day test read a finish-first
  calendar as the week it declares.
- `dcma_14.calendar_resolution` no longer has a `note` key.

New keys are listed under Added.

### Fixed

- **A blank activity calendar id is read as the project calendar.** MPXJ, converting
  an MS Project file, writes `TASK.clndr_id` empty for every task without a task-level
  calendar, and MS Project schedules such a task on the project calendar. The
  validator found no calendar for the blank id. It read the activity's float and
  duration, and a lag when the activity at its other end had no calendar either, at a
  flat 8 h/day whatever the project calendar says. With cpp-cpm-engine present, Check 3
  also compared the activity's finish with the network's without a working week. On a
  10 h/day project calendar, 20 h of float read as 2.5 working days instead of 2, and
  a finish at Friday's close was not matched with a network finish at Monday's
  opening. Checks 1, 3, 5 and 7, and DCMA-14 #6, #8 and #13, could therefore read the
  same schedule differently depending on whether its calendar ids were written out.

  `validate_critical_path` and `dcma_14_assess` now take every row through the bundled
  parser's `resolve_task_calendars` first: the activity's own calendar, else the
  project's (`PROJECT.clndr_id`), else the calendar flagged `default_flag = 'Y'`. The
  parsed data is not modified. This lifts the two known limits v0.2.0 recorded for a
  blank task calendar, in Check 3 and in DCMA-14.
- **A finish-first calendar reads as the week it declares.** P6 writes a working time
  slot start-first, `(s|08:00|f|16:00)`, or finish-first, `(f|16:00|s|08:00)`, and
  the order belongs to the calendar. The bundled parser read start-first slots only,
  so a finish-first calendar decoded to no working days, which the working-day
  arithmetic counts as Monday to Friday, and its worked exception days were filed as
  holidays. DCMA-14 #13 measures the critical path in working days on the project
  calendar: on a finish-first seven-day calendar a Monday-to-Monday critical path read
  as 5 working days instead of 7, and CPLI was computed on that length. With
  cpp-cpm-engine present, Check 3's working-day finish test was handed the same empty
  week. The bundled parser now decodes both orders (see Changed).
  `tests/test_dcma14_finish_first_calendar_2026_09_29.py` has 5 tests on synthetic
  calendars; 4 of them fail against the previous parser, and CI runs the file under
  pytest and directly. The suite is 189 tests.
- **A schedule with a logic cycle grades RED.** A cycle (A1 → A2 → … → A1) leaves the
  network with no forward pass, no finish date and no critical path. The nine checks
  read the stored float, constraints and relationships and never tested that the
  network is acyclic, so a cyclic schedule was scored like any other: a five-activity
  ring at zero float scored 96.3, GREEN, High Confidence. `validate_critical_path` now looks
  for cycles before the checks run (Kahn's algorithm on the relationships between work
  activities, whatever their type) and, where it finds one, sets the score to 0, the
  rating to RED and the confidence to Unreliable, and adds a Critical **Network
  Cycle** recommendation naming the first cycle found. The checks still run.
- **Check 2 is RED when the schedule has no critical path.** With no activity at zero
  or negative total float, Check 2 (constraint-driven criticality) cannot be assessed,
  and it fell through to its "none of the critical path is constrained" branch: GREEN,
  100. It is now RED, 0, and its note says a schedule with no critical path is a logic
  defect to look into (a cycle, missing logic, or float everywhere). A chain with 50
  days of float on every incomplete activity scored 93.6, GREEN, High Confidence,
  although Check 1 already rated it RED for having no critical path; it now scores
  76.6, AMBER, Moderate Confidence.
- **A RED check caps the overall rating.** The overall score is a weighted average, so
  a single RED check could sit under a GREEN, High Confidence headline: a chain whose
  start milestone is an open end on the critical path (Check 3 RED) scored 82.3 and
  read GREEN. Any RED check now caps the rating at AMBER and the confidence at Moderate
  Confidence. The score itself is not changed, and the two bands below 60 are already
  at or under the cap.
- **Check 5 converts a lag on the calendar P6 measures it on.** P6 walks a lag on the
  calendar that `SCHEDOPTIONS.sched_calendar_on_relationship_lag` names, the
  predecessor's by P6's default (and when the table is absent or the field blank).
  Check 5 always divided lag hours by the successor's hours per day, so where the two
  activities sit on different calendars a lag read in the wrong working days: -40 h
  from a 10 h/day predecessor to an 8 h/day successor read -5.0 days instead of -4.0,
  and whether a lag counts as excessive (over 10 days) could flip. Check 5 now reads
  the setting for the selected project (else the table's first row), converts on that
  activity's calendar, and falls back to the other activity's, then to 8 h/day, as
  before. A token cpp-cpm-engine does not walk a lag on (the project or the 24-hour
  calendar) falls back to the successor's, as the engine does.

  These four rules are ported from CPP's internal validator: the cycle detection and
  override, the Check 2 branch, the cap and Check 5's conversion are AST-identical to
  it. The SCHEDOPTIONS reader is a reduced copy of its decode that reads the lag
  setting only; the token resolver in it is AST-identical.
  `tests/test_network_cycle_2026_09_29.py` (5 tests) and
  `tests/test_scoring_rules_and_lag_calendar_2026_09_29.py` (12 tests), all synthetic,
  run under pytest and directly in CI. Against the previous code 4 of the 5 cycle tests
  fail; the scoring file cannot import the new SCHEDOPTIONS reader, and with the reader
  shimmed in 7 of its 12 tests fail. 17 mutants of the four rules are each killed. The
  suite is 206 tests. Not ported in this release: the internal version's
  `dcma_worst_severity`, which needs a report summary the bundled `validation.py` did not
  produce. v0.3.1 ports it.
- **The README's examples run, and it says what the public engine does.** Three of the
  README's four Python examples raised when run. The quick start printed
  `results['cp_confidence_score']` and `results['cp_confidence_band']`, keys
  `validate_critical_path` does not return (`KeyError`). The score is `overall_score`,
  the band `overall_confidence` and its colour `overall_rating`, and the CP Confidence
  Score section now names all three. The custom-profile example passed a threshold
  dict to `dcma_14_assess`, but the bundled `config_profiles.get_profile` looks a
  profile up by name (`TypeError`). The example now picks a bundled profile by name,
  and the text says how to add one. The driving-path tracer example read
  `step['task_code']`, `step['total_float_days']` and `step['rel_type']`, but
  `trace_driving_path` returns plain activity codes (`TypeError`). The example prints
  the chain, and the section says what the tracer returns and where it stops.

  The "Integration with the CPP forensic suite" section said that with
  `cpp-cpm-engine` on the path, Check 2 also runs an LPM-confirmed false-critical-path
  detection. That needs `compute_lpm`, which the public engine's
  `python_reference/cpm.py` does not have (its header says it was stripped), so the
  cross-check never runs from this repository and `checks.constraint_driven.lpm_error`
  records the failed import. The driver-chain narrative needs a
  `driver_chain_narrative` module this repository does not ship, so from this
  repository `results['driver_chain_narrative']` is always an error block. The section
  now says that Check 3's working-day finish test is the only thing that uses the
  public engine, and names the two outputs that need code not published here. The CI
  step that fetches the engine no longer names the LPM cross-check either. The tracer
  section also says where the walk stops, including its 200-predecessor cap, and the
  score bands say the band is set before the score is rounded. No validator code
  changed.
- **The same claims are corrected outside the README.** SECURITY.md said the LPM
  cross-check is unavailable only when the `cpm` module is absent. It needs
  `compute_lpm`, which the public engine does not have, so from this repository it
  does not run with the engine either, and both places in the policy now say so. The
  `validate_critical_path` docstring promised one driver-chain narrative per critical
  activity; it now says when the block holds narratives, and that from this
  repository it is an error block. The `_engine_date_helpers` docstring no longer
  points to the LPM cross-check. The docstring and skip message of
  `test_lpm_confirmed_false_cp_in_check2` no longer call the cross-check "documented
  as optional" or say CI proves its wiring. `scripts/config_profiles.py` said a
  caller could pass a profile dict to `dcma_14_assess`, which raises `TypeError`, and
  that the threshold keys are documented in the dcma14.py header, which names none.
  It now says a profile is passed by name and how to add one, and its BEI comment
  reads #14, as `dcma14` scores it. The file is identical to `cpp-xer-parser`'s copy
  again, which took the same text at
  [`bdc6699`](https://github.com/danafitkowski/cpp-xer-parser/commit/bdc66995826c82dc1691977cdf40b8219a8eaea9).
  Docstrings, comments and one skip message only; the scripts' code is unchanged
  apart from docstrings.

### Added

- **`results['cycle_detected']`, `results['cycles_found']` and
  `results['cycles_found_task_ids']`**, always present: whether the relationships
  contain a cycle, and one closed chain per cycle found, as activity codes and as task
  ids. Where any check is RED, **`results['overall_rating_capped_by_red']`** (`True`)
  and **`results['red_checks']`** (the RED checks' keys) say the headline was capped.
- **`results['schedule_options']`**, always present: the relationship-lag calendar
  Check 5 converted on (`relationship_lag_calendar`, the SCHEDOPTIONS token or P6's
  default), `lag_calendar_role` (`predecessor` or `successor`) and
  `relationship_lag_calendar_source`, which says how it was determined. The keys are
  the ones CPP's internal validator reports under the same name; its scheduling-mode
  and Must Finish By keys are not read here.
- **`results['calendar_resolution']`**, always present. It lists which blank ids were
  resolved and onto which calendar, and every activity with no usable calendar: a
  blank id with nothing to fall back on, or a calendar the file does not declare,
  which is reported and never replaced. `results['dcma_14']['calendar_resolution']`
  carries the same block for the activities DCMA-14 assessed.
- An activity with no usable calendar draws a High **Activity Calendar**
  recommendation, a dashboard section listing every such activity, and DCMA-14's
  `DCMA-Ext-TaskCalendar` warning, which stays outside the score. Where blank ids
  were resolved, the dashboard header names the calendar they were scheduled on.
- **`tests/test_readme_examples.py`** runs every Python example in the README that
  calls `validate_critical_path`, `dcma_14_assess` or `trace_driving_path`, in the
  README's order and in one namespace, against a synthetic schedule written to a
  temporary folder, and fails on any exception. It failed on the old README with the
  three errors above. Two guards stop it passing on nothing: each of the three
  functions must have an example, and every activity an example names must have a
  driving chain in the fixture. CI runs it under pytest and directly. Three tests,
  taking the suite from 181 to 184.

### Changed

- **The bundled parser is re-vendored** from `cpp-xer-parser` at its release
  [`v0.2.0`](https://github.com/danafitkowski/cpp-xer-parser/releases/tag/v0.2.0),
  commit `33e8063` (this section first re-vendored it at `b5a2038`). `XER_PIN` and
  `XER_SHA256` move together, and the README names the release. `validation.py` and
  `config_profiles.py` were already identical to v0.2.0's. What arrives with it:
  - `resolve_task_calendars`, `with_resolved_calendars` and
    `calendar_resolution_block`, first vendored at `b5a2038`. The bundled
    `validate_schedule` now also reports activity calendars (BLOCK
    `XER-TASK-CALENDAR-UNRESOLVED`, INFO `XER-TASK-CALENDAR-FALLBACK`), and
    `generate_summary` converts float on the resolved calendar. A file whose TASK rows
    carry no calendar, and which names no project or default calendar, now draws that
    BLOCK, and `aace_31r_compliance` scores it accordingly.
  - The calendar decode that reads finish-first time slots; see Fixed.
  - For code that imports the bundled parser itself: `get_work_days_between`,
    `add_work_days` and `subtract_work_days` honour worked exception days and read
    dates on their calendar day, `generate_xer` collapses a tab or line break inside a
    value to a space, and `generate_summary` counts LOE and WBS summary rows apart and
    lists every critical activity. The validator calls none of these. The parser's
    [CHANGELOG](https://github.com/danafitkowski/cpp-xer-parser/blob/v0.2.0/CHANGELOG.md)
    lists every change in the release.
- `dcma14.py` no longer carries the stand-in resolver it used while the bundled parser
  had none, so the `calendar_resolution` block no longer has the `note` key that
  stand-in added. The `work_day_delta` stand-in stays.
- **Tests:** 41 new, all synthetic, taking the suite from 165 at v0.2.0 to 206.
  `test_blank_task_calendar_2026_09_29.py` covers Checks 1, 3, 5 and 7, the disclosure
  and the dashboard for a blank calendar id, and
  `test_dcma14_blank_task_calendar_2026_09_26.py` covers DCMA-14 (16 between them);
  `test_readme_examples.py` runs the README (3);
  `test_dcma14_finish_first_calendar_2026_09_29.py` covers the finish-first week (5);
  `test_network_cycle_2026_09_29.py` covers cycles (5); and
  `test_scoring_rules_and_lag_calendar_2026_09_29.py` covers Check 2 with no critical
  path, the RED cap and the lag calendar (12). With cpp-cpm-engine at `CPM_ENGINE_PIN`
  on the path, 205 pass and one skips; without it, 200 pass and 6 skip.

---

## v0.2.0 — 2026-09-29

The first release since v0.1.0: corrections to the build, to public claims, to the
bundled parser's output, to how Checks 3 and 8 find where the project finishes, and to
the DCMA-14 assessment, which now follows the published numbering and scores only what
it measured. No logic-health check has been added; the Critical Path Test, DCMA #12,
is now assessed where the file decides it.

**Breaking for DCMA-14 callers:** the `per_check` ids from #11 on, the meaning of
`dcma_score`, the key BEI is reported under (`DCMA-14-BEI`, no longer `BEI`) and the
CPLI detail keys all changed. See the first entries under Changed.

### Fixed

- **Logic continuity (Check 8) traces to where the project finishes.** Check 8 walks
  predecessors back from the project's completion anchors and reports every
  incomplete activity it does not reach as having no path to completion. The anchors
  were the critical finish milestones (`TT_FinMile`), or every finish milestone when
  none was critical, and nothing else. Two shapes of schedule read most or all of a
  connected network as disconnected, logic continuity RED 20 with one recommendation
  per activity:
  - *A network that ends in an ordinary task.* Check 3 accepted that task as the end
    of the network and listed it in `terminal_milestones`, while Check 8, which
    anchored only on finish milestones, reported the work leading to it as
    disconnected. Check 8 now takes Check 3's terminals as anchors, so the two checks
    agree.
  - *A chain behind an As Late As Possible finish milestone.* ALAP places a finish
    milestone against its successor's early start, so one with work after it carries
    that work's float and reads critical ahead of critical work. When it was the only
    critical finish milestone it became the only anchor, and if the activity that sets
    the project finish has a successor that floats (a negative lag, an SS or FF tie),
    everything not upstream of the milestone read as disconnected. Such a milestone is
    now a gate: it paces the work after it and no longer counts as a finish milestone.

  The trace also starts from where the network ends: the incomplete activity or
  activities with the latest stored early finish among those tied to at least one
  other work activity, and the open ends reached from them through unfinished work.
  Only linked work can set the finish, so an unlinked activity dated late never sets
  it. These anchors only add to the others, so a schedule with a real finish
  milestone, and no work with logic finishing after it, reads as before. The fallback
  to every finish milestone still fires only when no finish milestone is critical, a
  critical gate included, and a critical finish milestone anchors the trace wherever
  it sits, as before. An activity with no logic can still anchor the trace as a finish
  milestone under that fallback, or as a Check 3 terminal where it finishes with the
  network (see the next entry), and Check 3 then reports its missing predecessor.

  The one case that now reports more is a gate whose successors lead nowhere: the
  gate, and any work whose only way forward runs through it, had counted as connected
  because the gate itself was an anchor, and are now reported as disconnected. One
  trade-off is kept by design: the latest finisher with logic is taken as the end even
  when it is a stray dead end, because nothing separates it from a real last activity.
  Check 3 reads the end the same way: the stray is its terminal, floating or not, and
  Check 3 reports the earlier activity with no successor and names the stray as where
  the network finishes.

- **Open ends (Check 3) find the terminal by position, not task type.** Check 3 excuses
  the terminal, the critical activity with no successor where the network ends, from
  its open-end count. Every critical milestone with no successor counted as a terminal
  whatever its date, and any one of them switched off the fallback to the latest early
  finish. On a schedule converted from MS Project (no scheduled finish, every open end
  critical) a finish milestone well before the finish became the terminal, and the
  real last activity was reported as a critical open end. On P6 exports, Finish On or
  Before contract milestones with no successor were excused months before the finish.

  A critical activity with no successor is now the terminal only where it finishes
  with the network: on the day of the stored early finish of the activities that set
  the finish (the ones Check 8 anchors on), or with no working day between the two on
  its own calendar, or on the project's scheduled finish day as before. An activity
  the file stores no early finish for cannot be placed and is not excused. A file with
  no network finish to read (no activity tied to other work stores an early finish)
  keeps the old rule. Because Check 8 now takes Check 3's terminals as anchors, the
  rule also decides what Check 8 anchors on: a start milestone or an unlinked activity
  that leads nowhere before the finish is not taken as where the network ends.

  Known limits:
  - The working-day test takes cpp-cpm-engine's `cpm` module when it is on the path,
    as Check 2's LPM cross-check does, and `checks.open_ends_cp.finish_match` says
    which test ran. Without the engine only the same day counts, so an activity that
    finishes at one working day's close is not matched with a network that finishes
    at the next working day's opening, and is reported as an open end.
  - The bundled parser does not read a blank task calendar as the project calendar,
    so an activity with no calendar of its own is compared without one, and its
    Friday-evening finish is not matched with a Monday-morning one.
  - By design, a critical finish milestone anchors Check 8 wherever it sits, so a
    sectional completion counts as a completion. An early critical finish milestone
    with no successor (MS Project conversions carry them) therefore also anchors the
    work that leads only to it, while Check 3 reports it as a critical open end.
  - DCMA-14 #1 now excuses a finish milestone by position too (see its entry below),
    so on the schedules above both checks count the early milestone, and both excuse
    a completion milestone that floats at the finish (see the next entry). The two
    tests still differ. DCMA-14 #1 excuses only a finish milestone, critical or not,
    and only at or after the latest finish of the remaining work, to the minute, an
    activity tied to nothing included. It therefore still counts any other activity that ends
    the network, and a finish milestone that Check 3 takes as finishing with the
    network earlier the same day, across a non-working gap, or before a later activity
    tied to nothing.

- **Open ends (Check 3) take a floating activity at the network finish as the
  terminal.** Check 3 looked for the terminal only among the critical activities.
  Where everything floats, because the project's Must Finish By is later than its
  early finish and every late date is computed against it, or because the file has no
  float written, the completion milestone was never the terminal: it drew a 'High'
  "has no successors" finding while DCMA-14 #1 excused it as the finish milestone at
  the network finish.

  Every incomplete activity with no successor is now a candidate wherever the network
  finish can be read. A non-critical one must be tied to at least one other work
  activity, the rule Check 8 reads the finish by: an activity with no logic is not
  part of the network, and Check 8 takes Check 3's terminals as anchors. It must also
  finish with the network itself, on the same day or with no working day between. The
  project's scheduled finish still counts for a critical activity only: for work tied
  to other work it adds nothing but a date the file did not move with the network. A
  file with no network finish to read looks only at critical activities, as before.
  Where the latest finisher with logic is work after the completion milestone, that
  work is the terminal floating or not, and the milestone is the open end.

- **DCMA-14 #1 (Logic) counts the remaining work and excuses a milestone by position,
  not task type.** #1 is the share of activities missing a predecessor or a
  successor. It ran over every work activity, completed ones included, so on an
  update well into a job the finished work, whose logic no longer drives anything,
  diluted the percentage. It also excused milestones by type: every start milestone
  from needing a predecessor, and every finish milestone from needing a successor or
  a predecessor, whatever its date. A milestone in the middle of the network that
  leads from nothing, or to nothing, is the dangling logic #1 exists to find, and a
  finish milestone tied to nothing at all was never counted.

  #1 now counts incomplete activities only, as #6, #7 and #8 already did. A start
  milestone with no predecessor is excused only at or before the earliest start of
  all the work, and a finish milestone with no successor only at or after the latest
  finish of the remaining work. Each activity is placed by its actual date, else its
  early date, else its planned date, and one with no date is not excused. Completed
  work counts in placing the network's start, never its finish: on an update statused
  past its data date, an actual finish later than the remaining work is #9's finding
  and does not make the completion milestone a dangling end. A finish milestone
  always needs a predecessor. The check's details
  now list the activities missing a predecessor and those missing a successor
  separately (`missing_pred`, `missing_succ`), with their counts, their rates and the
  `denominator`, and its message gives both counts. A schedule with no incomplete
  work passes with the same details, every count and rate at zero and both lists
  empty. `missing_count` and `examples` still hold the union, and the union rate is
  still the value graded against the threshold. On a progressed schedule the rate
  can move either way: completed activities no longer count, and the remaining work
  is the whole denominator.

- **CI is green again.** The last four runs (2026-05-16, 2026-08-19, 2026-08-22 and
  2026-08-23) each failed on exactly one step, the `xer_parser.py` drift check, in
  the single matrix job that step is gated to. Every test step passed in every job
  in all four. The drift was real, but it was not a defect in this repo: the check
  compared the vendored file against whatever `cpp-xer-parser`'s `main` happened to
  be at the time, so an upstream edit could fail every build here. As of the last
  red run the outstanding difference was 13 lines replaced by 25 across 7 hunks, all
  of it comment and docstring text about the half-step generator plus one
  attribution string inside `compute_half_step_xer`, which nothing in this repo
  calls. A comparison against a moving branch is also not reproducible: re-running
  the old workflow today does not give the answer it gave in May.
  `scripts/xer_parser.py` was re-vendored byte for byte from
  `cpp-xer-parser` at [`5fc6c5e`](https://github.com/danafitkowski/cpp-xer-parser/commit/5fc6c5e034f4d740040c5655763612b320068743)
  (the pin has since moved to `a8edac6`; see below),
  and the hard check verifies the bundled copy against a recorded SHA-256 with no
  network access at all, so it is deterministic and cannot flake. A second, advisory
  step cross-checks the pin against GitHub and reports when upstream has moved past
  it, and is written so that it can never fail the build. The re-vendored text is
  also the better citation: it pinpoints the half-step to AACE 29R-03 §2.3.D.2,
  "Bifurcation: Creating a Progress-Only Half-Step Update".
- **`generate_xer` writes the `%E` end-of-file marker.** Every genuine Primavera P6
  export ends with a `%E` line, and the generator in the bundled
  `scripts/xer_parser.py` never wrote one. P6 tolerates the omission, so this is
  format fidelity rather than a known import failure, but a generated file that
  drops a marker every real export carries is not round-trip faithful, and a stricter
  reader may reject it. The reader skips any line that is not `%T`, `%F` or `%R`, so
  the marker never comes back as a table. The change was first made to the vendored
  copy by hand on 2026-09-22. It is the same change as upstream
  [`9d63173`](https://github.com/danafitkowski/cpp-xer-parser/commit/9d63173758da993f02685a535c82e0956a8183bd),
  and the re-vendor below replaced the hand edit with the upstream file.
- **The vendored parser is back on its pin, and CI is green again.** The hand edit
  above changed `scripts/xer_parser.py` without bumping `XER_PIN` and `XER_SHA256`, so
  the push of 2026-09-22 failed the offline pin check, in the one matrix job that step
  is gated to, with every test step green. On 2026-09-26 the file was re-vendored byte
  for byte from `cpp-xer-parser` at
  [`a8edac6`](https://github.com/danafitkowski/cpp-xer-parser/commit/a8edac6f2ef19f6cddb02dee51dc320f99f6ba38),
  which carries the same `%E` fix, and the pin now records that commit and its
  SHA-256. The one other upstream change it brings is
  [`389ee14`](https://github.com/danafitkowski/cpp-xer-parser/commit/389ee1432fab848ec26219eb5e9a472a09e85739).
  The parser's docstring no longer calls it the canonical P6 XER engine and the single
  source of truth for every XER operation. Its optional imports are split, so the
  `validation` and `config_profiles` modules this repository ships now bind although
  `audit_trail` does not ship here. On a plain clone `validate_schedule` raised
  `RuntimeError` before and now runs. `aace_31r_compliance` got past the import but
  then raised `AttributeError`: it calls `ValidationReport.count`, which upstream added
  to its own `validation.py` in the same commit. The next entry brings that file over,
  and both functions now run. The README's provenance line kept naming `5fc6c5e`
  after the re-vendor; it now names `a8edac6`.
- **`aace_31r_compliance` runs on a plain clone.** `scripts/validation.py` is now
  vendored byte for byte from `cpp-xer-parser` at
  [`a8edac6`](https://github.com/danafitkowski/cpp-xer-parser/commit/a8edac6f2ef19f6cddb02dee51dc320f99f6ba38),
  the commit `scripts/xer_parser.py` is pinned to. The bundled copy was upstream's
  from before
  [`389ee14`](https://github.com/danafitkowski/cpp-xer-parser/commit/389ee1432fab848ec26219eb5e9a472a09e85739),
  so the re-vendor brings exactly that commit's change: the `count(severity)` method
  the parser's structure score calls, with its docstring, and one module docstring
  sentence naming the two parser functions the subset serves.
  `scripts/config_profiles.py` already matched upstream at `a8edac6`. On a plain clone
  `validate_schedule` and `aace_31r_compliance` now both run, and a new test pins it
  (see Added).
- **DCMA-14 #1 to #4 read only the project's own relationships.** A relationship with
  one end in another project of the same export counted as this project's logic (`or`
  where `and` was meant), which inflated the relationship set of a multi-project file
  for #2, #3 and #4 and gave #1 a predecessor or successor that belongs to another
  project.
- **DCMA-14 #6, #7 and #13 read a blank total float as missing data.** High Float and
  Negative Float read a blank `total_float_hr_cnt` as 0, so they passed silently on a
  file carrying no float at all, while the critical set read it as 999, so such
  activities silently left the set and CPLI came back not computable with no reason
  given. Such activities are now dropped from those populations and their count
  disclosed; a file with no computed float on any incomplete activity reads NOT
  ASSESSED on all three. The critical set also honours
  `PROJECT.critical_drtn_hr_cnt`, P6's own "critical when total float is less than or
  equal to" setting, instead of a hard-coded zero.
- **DCMA-14 #9 reads the forecast dates the standard names.** Section 4.9 of DCMA-EA
  PAM 200.1 counts an incomplete activity with a forecast (early) start or finish
  before the status date, and any activity with an actual date after it. The check
  never read an early date: it tested the planned finish, which is #11's business, so
  open activities were flagged for a historical planned finish while stale forecasts
  passed. It also counted one issue per field and called the total a number of
  activities. Issues are now grouped by activity, the forecast and actual counts are
  reported separately, a started activity is read on its forecast finish only, and an
  activity with no early date to read is disclosed rather than counted.
- **DCMA-14 #10 is "Not scored" when a profile disables it.** With the threshold at 0
  it returned PASS, a point for a criterion nothing had measured. It is INFO now and
  stays out of the score. The three bundled profiles all set a threshold, so on them
  it is scored as before.
- **DCMA-14 #11 counts late finishes and reads the baseline.** Missed Tasks counted
  only the activities still open at the status date, so one that finished after its
  due date was invisible. It now counts a due activity that is still open OR finished
  late, takes its due dates from the baseline when one is supplied (matched on activity
  code, since task ids are renumbered on every export), and says which basis it used.
- **DCMA-14 #12, the Critical Path Test, has a criterion of its own.** Slot 12 was an
  echo of #10. The published test needs a 600-day insertion and a CPM recalculation,
  which this module does not perform, so it never claims a pass: it fails where the
  file decides the failure, a project finish held by a Mandatory Start or Mandatory
  Finish or with no predecessor at all, and reads NOT ASSESSED otherwise. A Start On or
  Finish On date is not a pin: P6 can move the early date past it and shows the
  lateness as negative float, which section 4.12 counts as a pass.
- **DCMA-14 #13, CPLI, can exceed 1.0, and an activity that is not the project finish
  no longer drives it below zero.** The float term was the minimum float over the
  critical set, and the critical set was the activities at float ≤ 0, so the index
  could not exceed 1.0 by construction, and one deeply negative activity anywhere on
  the critical set could drive it below zero. It now takes the float of the project finish
  activity, as published, and measures the critical path in working days on the
  project calendar from the status date to the project finish, not in wall-clock hours
  divided by hours per day, which counted every night and weekend.
- **DCMA-14 #14, BEI, is unrestricted and one project's.** The numerator counted only
  the baseline-due activities that were complete, a subset of the denominator, so BEI
  was capped at 1.0 and could never show work pulled ahead. It now counts every
  activity complete as of the status date, as published. It and #11 read the assessed
  project's rows and the matching baseline project's (same id, else same short name,
  else the project sharing the most activity codes), not every row in either file.
- **The critical-path continuity extension (`DCMA-Ext-CPContinuity`) no longer reports
  a floated merge input as a break.** A critical activity may take non-critical
  predecessors alongside the critical chain; the previous reading called every
  incomplete non-critical predecessor a gap, so every merge point reported a
  discontinuity. A break is now a critical activity that has incomplete predecessors
  and none of them on the critical path. Each gap carries the predecessor's status,
  driving flag, total float and tie type, and the result counts the activities checked
  (`cp_activities_checked`).
- **The AACE badge no longer advertises retracted Recommended Practices.** The README
  badge rendered `AACE: 49R-06 | 24R-03 | 67R-11` while the AACE alignment section
  below it explained that the 24R-03 and 67R-11 rows had been removed as wrongly
  described. The badge now cites 49R-06 only.
- **The `status: stable` badge is gone.** It was a hand-written shields.io literal
  that stayed green through four consecutive red CI runs. The README now carries the
  live GitHub Actions badge, which cannot disagree with the build, plus a version
  badge.
- **SECURITY.md no longer claims production expert-witness use.** Its opening line
  said the validator "is used in production forensic delay analyses, EOT submissions,
  and expert-witness reports". That work runs on a larger internal validator. The
  policy now states the standard this repo holds itself to without claiming the
  deployment, and stops calling `cpp-xer-parser` the canonical parser. CONTRIBUTING.md
  carried the same claim twice ("This validator is used in court-filed forensic
  schedule reports", "The validator is used in court") and is corrected the same way.

### Changed

- **DCMA-14 follows the published numbering, and its score is out of the criteria it
  assessed.** This changes the `per_check` keys and the meaning of `dcma_score`. The
  fourteen were numbered here with two cross-reference echoes: `DCMA-11-InvalidDatesFuture`
  repeated #9's verdict and `DCMA-12-ResourceCoverage` repeated #10's, so a passing #9
  or #10 scored twice, a failing one was reported twice, and a clean file read 14 of 14
  with two points measured once; Missed Tasks sat at #13, CPLI at #14, and BEI was
  reported outside the fourteen under the key `BEI`. The registry now runs #1 to #14 as
  DCMA-EA PAM 200.1 orders them, ending `DCMA-11-MissedTasks`,
  `DCMA-12-CriticalPathTest`, `DCMA-13-CPLI` and `DCMA-14-BEI`. A criterion the file
  cannot support is INFO, left out of both the numerator and the denominator and named
  in the new `dcma_not_assessed`: BEI with no baseline, the Critical Path Test where
  nothing structural decides it, the float-dependent criteria on a file with no computed
  float, Resources under a profile that disables its threshold. `dcma_score` counts the
  criteria passed and the new `dcma_max` the criteria assessed, so a report reads "x of
  y assessed" and never "x / 14" with two criteria counted twice.
  `render_dcma_scorecard_html` prints that, lists what was not assessed, and colours
  the score by the share of assessed criteria passed. The result also names the
  project it graded (`proj_id`, `project_name`, `data_date`), the baseline project its
  checks 11 and 14 read (`baseline_proj_id`, `baseline_project_match`), and a
  `calendar_resolution` block; `validate_critical_path` carries all of them into
  `results['dcma_14']`. The details of #13 name the project finish activity and its
  float as `finish_activity` and `tf_days`; `tf_days_min`, the minimum float over the
  critical set, went with the rule that read it (see Fixed).

  Known limits: the bundled parser resolves no blank task calendar onto the project
  calendar, so `calendar_resolution` is empty and says so, and an activity with no
  calendar of its own is read at 8 h/day in #6, #8 and #13; and #9's finding carries no
  data date correction sentence, which needs a module this repository does not ship.
  The working-day advance #13 measures the critical path with is defined in
  `dcma14.py` until the bundled parser carries it: it counts the calendar's worked
  weekdays, holidays off and worked exceptions on, reads dates on their calendar day,
  and refuses a span beyond a hundred years as a sentinel finish. A parser that carries
  `work_day_delta` is used instead, and `tests/test_dcma14_guards.py` holds it to the
  same reading.
- **`dcma_14_assess` takes `proj_id`, and `validate_critical_path` passes the project
  it selected**, so the embedded DCMA block describes the same project as the report's
  title and population on a multi-project export. Left out, the assessment picks the
  project with the latest data date (ties by activity count) instead of the one with
  the most activities: a baseline copy or an older snapshot in the same file routinely
  carries more rows than the live schedule. An id the file does not carry raises
  `ValueError` rather than grading an empty population.
- **`finish_milestones_found` in Check 8's result** counts the finish milestones and
  Check 3's terminals among the anchors. It counted the finish milestones the trace
  started from (every one when none was critical); gates are no longer counted, and
  Check 3's terminals now are.
- **Check 3's findings on critical activities with no successor** end with a sentence
  naming where the network finishes, when the file has a network finish to read, for
  example `The network finishes at 'F160 - Hand over to the owner' (2027-03-29 17:00).`
- **Check 3's note** (`checks.open_ends_cp.note`) ends with the same sentence whenever
  an activity is missing a successor and the file has a network finish to read. The
  findings off the critical path keep their wording, so the sentence appears once
  rather than on each of them.
- **CI fetches cpp-cpm-engine at a recorded commit** (`CPM_ENGINE_PIN` in
  `.github/workflows/test.yml`) instead of its `main`, as it already pins the vendored
  parser: Check 3's working-day test calls two functions private to the engine.

### Added

- **`dcma_max`, `dcma_not_assessed`, `proj_id`, `project_name`, `data_date`,
  `baseline_proj_id`, `baseline_project_match` and `calendar_resolution` in the DCMA-14
  result**, and the `proj_id` argument of `dcma_14_assess` (see Changed).
- **`tests/test_dcma14_published_standard.py`**, 14 tests on synthetic data: CPLI can
  exceed 1.0 and is not dominated by the deepest negative activity, BEI's unrestricted
  numerator, Missed Tasks counting late finishes and reading the baseline, the Critical
  Path Test failing on a mandatory pin and never claiming a pass, one failure costing
  exactly one point, blank float reported as not assessed, the project's own critical
  threshold, and four lock tests: remaining duration in #8, a target of zero in #9, no
  magnitude gate in #3, the profile floor in #13.
- **`tests/test_dcma09_invalid_dates_2026_09_21.py`**, 9 tests on #9 against section
  4.9 of DCMA-EA PAM 200.1: stale forecasts, an updated late activity, one activity
  counted once, started work read on its forecast finish, completed work, dates on
  the status date, missing forecasts disclosed, and the message.
- **`tests/test_dcma12_soft_constraint_2026_09_21.py`**, 6 tests on #12: Finish On and
  Start On completions not assessed, a completion with no predecessor failing for
  that reason, a mandatory finish failing, an unconstrained one, and the premise run
  on cpp-cpm-engine, skipped without it.
- **`tests/test_project_scope_2026_09_21.py`**, 11 tests: the validator and its DCMA
  block grade the same project, `project_index` reaching the block, the latest-data-date
  rule and `proj_id`, checks 11 and 14 reading the matching baseline project, and the
  invariant that an unrelated project in either file changes no figure of the selected
  one.
- **`tests/test_dcma14_guards.py`**, 9 tests: the published registry, the in-project
  relationship set, CPLI in working days, the working-day advance itself (holidays,
  worked exceptions, clock times), the sentinel-finish guard, the continuity
  extension's merge and break cases, Check 2's no-critical-path guard, and no
  low-contrast text in the scorecard. CI runs it under pytest and directly.
- `tests/test_dcma14.py` is re-pinned to the published numbering and the assessed
  denominator, with two more tests (13 in all).
- **`completion_anchors` and `gate_milestones` in Check 8's result**: the task codes
  the trace started from, and the As Late As Possible finish milestones set aside as
  gates.
- **`finish_match` in Check 3's result**: `working-day` when cpp-cpm-engine's day
  arithmetic was used to match finishes with the network, `same-day` when it was not
  available.
- **`tests/test_logic_continuity_completion_anchor_2026_09_28.py`**, 20 tests on
  synthetic data: the ALAP pattern, dated by hand from P6's scheduling rules, a
  dangling branch that is still reported, the gate under the every-finish-milestone
  fallback, a schedule with a real finish milestone that reads as before, what can and
  cannot be the end (an unlinked activity, a schedule with no logic, a critical gate,
  finished work, a level of effort after a milestone and a tie to one, ALAP as the
  secondary constraint, no stored early dates, a tie from the last task to itself, and
  the trade-off above), a chain with no early dates that ends in an ordinary task, and
  Check 3 taking a floating finish milestone as its terminal, as DCMA-14 #1 does. CI
  runs it under pytest and directly.
- **`tests/test_open_ends_floating_finish_2026_09_28.py`**, 16 tests on synthetic data,
  a chain that floats against a Must Finish By, dated by hand from P6's scheduling
  rules:
  - its completion milestone is the terminal, and the early finish milestone is still
    reported, as DCMA-14 #1 counts it;
  - DCMA-14 #1 still counts a task and a start milestone that end the network;
  - the note names the network finish;
  - a stale scheduled finish, and a file with no float written;
  - work finishing on the last day, and closing the working day before the finish,
    is at the finish, and work a working day short is an open end;
  - an activity tied to nothing, and one tied only to a level of effort, is not the
    end;
  - Check 8 anchors on every terminal, and a file with no early dates reads as
    before;
  - an incomplete start milestone is counted as missing a predecessor, and a complete
    one is not.

  One needs cpp-cpm-engine's `cpm` module and is skipped without it. CI runs it under
  pytest and directly.
- **`tests/test_open_ends_terminal_position_2026_09_28.py`**, 20 tests on synthetic
  data: the early finish milestone and the contract milestone that used to be
  excused, the working-day match on the activity's own calendar, unlinked and undated
  activities, the finding text, the trade-off, a real finish milestone and a file with
  no early dates that read as before, Check 8 not anchoring on a start milestone that
  leads nowhere, DCMA-14 #1 excusing the same finish milestone as Check 3, an engine
  without the day arithmetic leaving the same-day test, and `finish_match`. Two need
  cpp-cpm-engine's `cpm` module and are skipped without it. CI runs it under pytest
  and directly.
- **`tests/test_bundled_validation_runs.py`**, 3 tests on synthetic data, after
  upstream's test of the same name: the bundled `validation.py` and
  `config_profiles.py` bind, and are the copies in `scripts/`; `validate_schedule`
  returns a report with no BLOCK finding on a sound schedule; and
  `aace_31r_compliance` scores 100 less 20 per BLOCK finding and 5 per WARN finding,
  on that schedule and on one whose WBS is too shallow, which draws a BLOCK. The last
  test fails on the previous `validation.py`. CI runs it under pytest and directly.
- **`tests/test_dcma14_logic.py`**, 10 tests on synthetic data for DCMA-14 #1: completed
  work left out of the denominator, a start milestone in the middle of the network
  counted while the one that starts it is excused, the missing-predecessor and
  missing-successor counts reported separately, a finish milestone with no
  predecessor counted, the details of a schedule with no incomplete work, and the
  completion milestone of an update statused past its data date not counted as a
  dangling end. Each of those six fails on the code before its fix. The other four are mutation
  guards, each failing on a mutant the rest of the suite let through: the network's
  start taken over all the work, an undated milestone never excused, an activity
  missing both sides counted once, and completed work placed by its actual dates.
  CI runs it under pytest and directly.
- **A "Scope and status" section in the README**, recording that this is a public
  subset of a larger internal validator and recording the vendored parser's exact
  provenance.
- **Two citation-guard tests.** `test_no_badge_advertises_a_retracted_rp` pins the
  badge defect above so it cannot recur, and the guard now folds the shields.io `--`
  hyphen escape before matching. That fold is why the bad badge was invisible: every
  pattern is written `24R-03`, and a badge spells it `24R--03`.

---

## v0.1.0 — 2026-05-10

Initial public release. Companion to [`cpp-cpm-engine`](https://github.com/danafitkowski/cpp-cpm-engine) and [`cpp-xer-parser`](https://github.com/danafitkowski/cpp-xer-parser).

### Features

- **Nine-check critical path validator** (`validate_critical_path`):
  1. Critical path identification (TF ≤ 0, driving flag, longest path)
  2. Constraint-driven criticality (four-tier taxonomy: HARD_ABSOLUTE / HARD_DATE / SOFT / PREFERENCE)
  3. Open ends on incomplete activities (missing predecessors / successors)
  4. Relationship quality (FS/FF/SS/SF distribution, dangerous types on CP)
  5. Lag analysis (negative lags, excessive lags, lags on CP)
  6. Out-of-sequence progress detection
  7. Near-critical path analysis (TF 1–10 days, banded)
  8. Logic continuity to project completion milestone
  9. Constraint saturation (schedule-wide)
- **CP Confidence Score** — weighted across all 9 checks (weights sum to 1.00), reported as 0–100 with band thresholds at 80 / 60 / 40.
- **HTML dashboard output** (`generate_dashboard`) — self-contained dashboard with RAG status grid, CP activities table, near-critical table, recommendations table, and open-ends table.
- **DCMA 14-Point Assessment** (`dcma_14_assess`) — full DCMA implementation following DCMA-EA PAM 200.1 (the 14 metrics' actual home; this entry originally said "FAR Part 49, DFARS 234.2", which do not define them), AACE 49R-06, and NDIA PASEG. Returns a structured report with per-check severity, value, threshold, message, and details.
- **Three profiles bundled**: `commercial`, `nuclear`, `mining`. External users can clone and mutate any profile dict.
- **Driving path tracer** (`trace_driving_path`) — walks driving-predecessor chains for any activity.
- **Multiple critical path detection** — identifies when the schedule has more than one distinct CP.
- **CP continuity check** — flags gaps in the critical-path activity sequence.
- **BEI (Baseline Execution Index)** — NDIA PASEG §10 extension, requires baseline XER.
- **CPLI (Critical Path Length Index)** — DCMA #14 with full schedule-finish vs project-finish-date arithmetic.

### Testing

- Three test files cover the validator (`test_cp_validator.py`), DCMA-14 (`test_dcma14.py`), and forensic-correctness regressions (`test_cp_forensic.py`).
- All test fixtures are fully synthetic — every XER referenced in the test suite is built in-memory at test time. No real client data ships with the repo.

### Bundled subset modules

- `scripts/xer_parser.py` is bundled (mirrored from `cpp-xer-parser`) so the validator stands alone without separately installing the parser.
- `scripts/validation.py` and `scripts/config_profiles.py` are minimal standalone subsets of the full CPP internal modules — sufficient for the validator to run end-to-end. Inside the CPP forensic suite, the full versions take precedence (sys.path resolution in tests).

### Engine compatibility

Tested against `cpp-cpm-engine` v2.9.x (current as of 2026-05-16: v2.9.11+). Check 2's LPM cross-check requires the `compute_lpm` symbol from the engine on `PYTHONPATH`; the validator gracefully degrades when the engine or that specific symbol is absent (the LPM-confirmed-false-CP detection becomes a no-op and the corresponding test is skipped with reason). All other checks run stand-alone with zero third-party dependencies. Forward compatibility with future 2.x engine lines is intended; the optional LPM-confirmation API surface is the canonical interface contract.

Note on CI coverage: the public CI clones `cpp-cpm-engine` and places its `python_reference/` on `PYTHONPATH`, which proves the import wiring works. The OSS `python_reference/cpm.py` is an explicitly-stripped subset that does not currently expose `compute_lpm` (it omits surfaces beyond what the JS-Python crossval needs). The full LPM-confirmation contract is exercised inside the CPP internal `_cpp_common` tree where `compute_lpm` is bundled. Once `cpp-cpm-engine`'s OSS python_reference is expanded to include `compute_lpm`, the public CI will exercise the full contract automatically — no validator change required, the test will stop skipping.

The bundled `scripts/xer_parser.py` mirrors `cpp-xer-parser` v0.1.x, verified in CI. See Unreleased for how that check works now.

### Companion repos

- **[cpp-cpm-engine](https://github.com/danafitkowski/cpp-cpm-engine)** — The forensically-defensible CPM engine. Used by Check 2's LPM-confirmed-false-CP detection when available.
- **[cpp-xer-parser](https://github.com/danafitkowski/cpp-xer-parser)** — The XER parser this skill consumes.
