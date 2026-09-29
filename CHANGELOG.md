# Changelog

All notable changes to `cpp-critical-path-validator` are documented here. Versioning follows [Semantic Versioning](https://semver.org).

---

## Unreleased

Changes on `main` since the v0.1.0 tag: corrections to the build, to public claims,
to the bundled parser's output, to how Checks 3 and 8 find where the project
finishes, and to what DCMA-14 #1 counts. No check has been added.

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
    and only at or after the latest finish of all the work, to the minute, an activity
    tied to nothing included. It therefore still counts any other activity that ends
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
  finish of all the work, completed work included in both. Each activity is placed by
  its actual date, else its early date, else its planned date, and one with no date
  is not excused. A finish milestone always needs a predecessor. The check's details
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
- **`tests/test_dcma14_logic.py`**, 9 tests on synthetic data for DCMA-14 #1: completed
  work left out of the denominator, a start milestone in the middle of the network
  counted while the one that starts it is excused, the missing-predecessor and
  missing-successor counts reported separately, a finish milestone with no
  predecessor counted, and the details of a schedule with no incomplete work. Each
  of those five fails on the code before its fix. The other four are mutation
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
