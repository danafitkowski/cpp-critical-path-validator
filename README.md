# cpp-critical-path-validator

[![license: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![python: 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![tests](https://github.com/danafitkowski/cpp-critical-path-validator/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/danafitkowski/cpp-critical-path-validator/actions/workflows/test.yml)
[![version: 0.3.0](https://img.shields.io/badge/version-0.3.0-blue.svg)](CHANGELOG.md)
[![AACE: 49R--06](https://img.shields.io/badge/AACE-49R--06-orange.svg)](#aace-alignment)

Critical path validation, logic health assessment, and optimization recommendations for Primavera P6 schedules — plus a full DCMA 14-Point Assessment.

Maintained by [Critical Path Partners](https://criticalpathpartners.ca) — a forensic-scheduling consultancy.

Companion to [`cpp-cpm-engine`](https://github.com/danafitkowski/cpp-cpm-engine) and [`cpp-xer-parser`](https://github.com/danafitkowski/cpp-xer-parser).

---

## Scope and status

This is v0.3.0, and it is a public subset. Critical Path Partners maintains a larger internal validator; what this repository publishes is the nine-check core, the DCMA 14-Point assessment, the driving-path tracer and the HTML dashboard. It does not carry every check or output the internal version has.

Nothing here is a stub. The code in `scripts/` is the code that runs, the tests in `tests/` are the tests that guard it, and CI runs them on three operating systems across Python 3.10 to 3.12. What this repository is not is a mirror of the internal tool, so a report produced by Critical Path Partners should not be assumed to have come from this file set.

`scripts/xer_parser.py` is vendored byte for byte from [`cpp-xer-parser`](https://github.com/danafitkowski/cpp-xer-parser) at release [`v0.2.0`](https://github.com/danafitkowski/cpp-xer-parser/releases/tag/v0.2.0) (commit [`33e8063`](https://github.com/danafitkowski/cpp-xer-parser/commit/33e8063e9b0d912ae425edd1c38802116ee9d951)), so the validator stands alone with no install step. CI verifies the vendored copy against that pinned commit on every push, and separately reports, without failing the build, when upstream has moved past it.

---

## What it does

This validator answers the question every scheduler and every claims expert eventually asks: **is this critical path actually correct, or is it artificial?**

It runs nine independent checks on a Primavera P6 schedule:

| # | Check                              | What it catches                                                             |
|---|------------------------------------|-----------------------------------------------------------------------------|
| 1 | Critical path identification       | Are CP activities reasonable in count and % of incomplete work?             |
| 2 | Constraint-driven criticality      | Hard constraints overriding network logic — the #1 source of false CP.      |
| 3 | Open ends                          | Missing predecessor / successor on incomplete activities.                   |
| 4 | Relationship quality               | FF / SS on CP without an FS backbone (fragile CP).                          |
| 5 | Lag analysis                       | Negative lags (leads) on CP that mask true duration.                        |
| 6 | Out-of-sequence progress           | In-progress activities ahead of their predecessors.                         |
| 7 | Near-critical fragility            | Activities with TF 1–10 days that could become the new CP with minor slip.  |
| 8 | Logic continuity                   | Activities that contribute work but have no logic path to project finish.  |
| 9 | Constraint saturation              | Schedule-wide hard-constraint density vs DCMA 5% threshold.                 |

Plus a **CP Confidence Score** (0–100, weighted across all 9 checks), an **HTML dashboard**, a **DCMA 14-Point Assessment** with all 14 checks, and a **driving-path tracer**.

---

## Why this validator

The critical path is the single most consequential output of any schedule. Bid pricing depends on it. EOT entitlement turns on it. Forensic claims live or die on it.

And yet — in the field — far too many critical paths are *artificial*: forced by hard constraints, broken by open ends, made fragile by negative lags, or unconnected to the project finish milestone. A scheduler who relies on the CP without first auditing whether the CP is real is making a load-bearing decision on unverified ground.

The checks in this validator come out of court-filed forensic schedule analysis, so the audit is rigorous. Every finding is structured, cited (DCMA-EA PAM 200.1, AACE 49R-06), and includes the full list of affected activities, never truncated.

---

## Install

```bash
git clone https://github.com/danafitkowski/cpp-critical-path-validator
cd cpp-critical-path-validator
# No external runtime dependencies. Just put scripts/ on your sys.path.
```

Pure Python 3.10+. The repo bundles its own copy of `xer_parser.py` plus minimal `validation.py` / `config_profiles.py` stubs, so it stands alone without separately installing companion repos.

---

## Quick start

```python
import sys
sys.path.insert(0, 'scripts')

from xer_parser import parse_xer
from cp_validator import validate_critical_path, generate_dashboard

# Parse the schedule
data = parse_xer('path/to/your.xer')

# Run all 9 checks
results = validate_critical_path(data)

# Generate the HTML dashboard
generate_dashboard(results, 'cp_validation_report.html')

# Or interrogate the results dict directly
print(f"CP Confidence Score: {results['overall_score']}/100")
print(f"CP Confidence Band:  {results['overall_confidence']} ({results['overall_rating']})")

for check_name, check_data in results['checks'].items():
    print(f"  {check_name}: {check_data['rating']} — {check_data['note']}")
```

---

## DCMA 14-Point Assessment

A separate, well-defined check suite with established federal-contract heritage.

```python
from xer_parser import parse_xer
from dcma14 import dcma_14_assess

data = parse_xer('current.xer')
baseline = parse_xer('baseline.xer')  # optional; required for BEI

report = dcma_14_assess(
    data,
    baseline_data=baseline,
    profile='commercial',   # or 'nuclear' or 'mining'
)

print(f"DCMA Score: {report['dcma_score']} of {report['dcma_max']} assessed")
print(f"Not assessed: {report['dcma_not_assessed']}")
print(f"CPLI: {report['cpli']}")
print(f"BEI:  {report['bei']}")

for check_id, check in report['per_check'].items():
    print(f"  {check_id}: {check['severity']} — {check['message']}")
```

The check ids follow the numbering of DCMA-EA PAM 200.1, ending `DCMA-11-MissedTasks`,
`DCMA-12-CriticalPathTest`, `DCMA-13-CPLI` and `DCMA-14-BEI`. The score is out of the
criteria the file could support: one that cannot be evaluated (BEI with no baseline, the
Critical Path Test where nothing structural decides it, the float-dependent criteria on
a file with no computed float) is reported INFO, left out of both numbers and listed in
`dcma_not_assessed`; it never scores.

Three profiles bundle out of the box:

| Profile      | Use case                                            |
|--------------|-----------------------------------------------------|
| `commercial` | Generic commercial-construction defaults            |
| `nuclear`    | Tightened thresholds for nuclear / heavy energy     |
| `mining`     | Relaxed thresholds for resource-driven mining work  |

`dcma_14_assess` takes one of these names. It does not take a threshold dict: the
bundled `config_profiles.get_profile` looks the profile up by name, and a dict raises
`TypeError`. `get_profile` returns a copy of a profile's thresholds for reading:

```python
from config_profiles import get_profile, list_profiles

print(list_profiles())    # the profile names dcma_14_assess takes
print(get_profile('nuclear')['dcma_high_duration_max_days'])
report = dcma_14_assess(data, profile='nuclear')
```

To grade against other thresholds, add a profile to `_PROFILES` in
`scripts/config_profiles.py`, with every key the bundled profiles have, and pass its
name.

---

## Blank activity calendars

A schedule converted from MS Project (by MPXJ, for example) leaves `TASK.clndr_id` blank for every task without a task-level calendar. A blank id means the project calendar, and the validator reads it that way: before any check runs, each activity takes its own calendar, else the project's (`PROJECT.clndr_id`), else the calendar flagged `default_flag = 'Y'`. The parsed data is not modified.

`results['calendar_resolution']` says what happened, and `results['dcma_14']['calendar_resolution']` says the same for the activities DCMA-14 assessed. It gives the count of blank ids resolved, the calendar they were resolved onto, and every activity left with no usable calendar. An activity is left without one when its id is blank and the file names no project or default calendar, or when it names a calendar the file does not declare. Such activities draw a High "Activity Calendar" recommendation and a dashboard section that lists them, because their float and duration can only be read at a flat 8 h/day.

---

## Driving path tracer

```python
from dcma14 import trace_driving_path

# Walk back from an activity through its driving predecessors
chain = trace_driving_path(data, task_code='A1050.20')
print(' -> '.join(chain))
```

`trace_driving_path` returns a list of activity codes: the earliest driver it reached
first and the activity you named last, or an empty list when the file has no activity
with that code. At each step it follows the relationship marked driving (`driving` or
`driving_path_flag` set to `Y` on the TASKPRED row) and, where none is, the predecessor
that finishes latest, whatever the relationship type or lag. It stops after the first
predecessor that is complete or finishes before the data date; where it finds no
predecessor to follow (none left, none with a finish date, or one already in the
chain); and after 200 predecessors, so a longer chain comes back without its earliest
part. It returns codes only, with no float or relationship type.

---

## Constraint taxonomy

Critical-path-validator distinguishes four tiers of constraint behavior:

| Tier             | Codes                                | Behavior                                                                |
|------------------|--------------------------------------|-------------------------------------------------------------------------|
| HARD_ABSOLUTE    | `CS_MANDSTART`, `CS_MANDFIN`         | P6 enforces the date regardless of network logic.                       |
| HARD_DATE        | `CS_MSO`, `CS_MEO`                   | Pins the activity to a specific date; predecessor slips don't move it.  |
| SOFT             | `CS_MSOA`, `CS_MSOB`, `CS_MEOA`, `CS_MEOB` | Bounds the activity in one direction; logic drives the other edge. |
| PREFERENCE       | `CS_ALAP`                            | Changes scheduling preference (late-date scheduling); no date bound.    |

Recommendations are tier-specific so schedulers know whether they are removing a Mandatory (overrides logic) or a Start-On (pins a date).

---

## CP Confidence Score

Weighted average across all 9 checks (weights sum to 1.00):

| Check                                 | Weight |
|---------------------------------------|--------|
| Critical path identification          |   5%   |
| Constraint-driven criticality on CP   |  17%   |
| Open ends on CP                       |  20%   |
| Relationship quality on CP            |  13%   |
| Lag issues on CP                      |  15%   |
| Logic continuity                      |  10%   |
| Near-critical fragility               |  10%   |
| Out-of-sequence                       |   5%   |
| Constraint saturation (schedule-wide) |   5%   |

Score bands. `validate_critical_path` returns the score as `results['overall_score']`,
rounded to one decimal, the band as `results['overall_confidence']` and its colour as
`results['overall_rating']`. The band is set on the unrounded score, so a score that
rounds up to a band's lower edge stays in the band below it.

| Score          | `overall_confidence`  | `overall_rating` | Meaning                                            |
|----------------|-----------------------|------------------|----------------------------------------------------|
| 80 or more     | `High Confidence`     | `GREEN`          | CP is logic-driven and reliable.                   |
| 60 to under 80 | `Moderate Confidence` | `AMBER`          | CP has issues but is directionally correct.        |
| 40 to under 60 | `Low Confidence`      | `AMBER`          | CP needs significant corrections.                  |
| under 40       | `Unreliable`          | `RED`            | CP is artificial; do not rely on it for planning.  |

Two rules sit on top of the bands:

- **A logic cycle.** A schedule whose relationships loop back on themselves has no
  forward pass and no critical path, whatever its stored float says. The validator
  looks for cycles before any check runs. Where it finds one, `results['cycle_detected']`
  is `True`, `results['cycles_found']` lists the cycles found, each as a closed chain
  of activity codes (`cycles_found_task_ids` as task ids), the score is 0, the band `Unreliable`
  and the rating `RED`, and a Critical "Network Cycle" recommendation names a cycle to
  break. The nine checks still run, for triage.
- **A RED check caps the headline.** The score is a weighted average, so one RED check
  can sit under a GREEN average. Where any check is RED, the rating cannot be `GREEN`
  (it reads `AMBER`) and `High Confidence` reads `Moderate Confidence`. The score is
  left as computed; `results['overall_rating_capped_by_red']` is `True` and
  `results['red_checks']` names the RED checks. The two bands below 60 are unchanged.

---

## AACE alignment

The validator cites:

| Reference                      | What it covers                                                   |
|--------------------------------|------------------------------------------------------------------|
| AACE Recommended Practice 49R-06 | Identifying the Critical Path (LPM / TFM / MFP)                |
| DCMA 14-Point Assessment         | The 14 schedule-quality metrics (DCMA-EA PAM 200.1)            |
| NDIA PASEG                       | Baseline Execution Index                                         |

Earlier revisions of this table also listed AACE 24R-03 and AACE 67R-11 with
descriptions that were wrong: 24R-03 is "Developing Activity Logic", has no
numbered sections, and is not a criticality standard; 67R-11 is "Contract Risk
Allocation", not a forensic-competency document. Nothing in this repo cites
either, so both rows were removed. The DCMA row previously misattributed the
14 metrics to federal acquisition regulations; their actual home is
DCMA-EA PAM 200.1.

---

## Running the tests

```bash
python tests/test_cp_validator.py     # validator core
python tests/test_dcma14.py           # DCMA 14-Point
python tests/test_cp_forensic.py      # forensic-correctness regressions
```

Or with pytest:

```bash
pip install pytest
pytest tests/
```

All tests build their XER fixtures synthetically in memory; no real client XER files ship with the repo.

---

## Integration with the CPP forensic suite

CP validation is the first thing Critical Path Partners runs on a new XER, checking whether the CP is real before any forensic delay analysis, time impact analysis, or claims-package work begins. That job is done by the internal validator described under [Scope and status](#scope-and-status); this repository publishes its nine-check core so anyone can run the same checks, without the two outputs described below.

When `cpp-cpm-engine` is on the same `sys.path` (its `python_reference/` folder), Check 3 uses the engine's working-day arithmetic to decide which activities finish with the network: a finish at one working day's close and one at the next working day's opening count as the same instant on the activity's calendar. Without the engine, Check 3 matches finishes by day only. `checks.open_ends_cp.finish_match` says which of the two Check 3 ran (`working-day` or `same-day`). CI runs against the engine commit recorded as `CPM_ENGINE_PIN` in `.github/workflows/test.yml`. Check 3's finish test is the only thing in the validator that uses the public engine.

Two outputs need code that neither this repository nor the public engine provides, so they do not run from a clone of this repository, with the public engine or without it:

- **Check 2's LPM cross-check**, which compares the critical path the schedule reports with an independently computed longest path, needs a `compute_lpm` function in the engine's `cpm` module. The public engine's `python_reference/cpm.py` does not have one; its header says it was stripped. Check 2 still runs its constraint-driven analysis, `checks.constraint_driven.lpm_confirmed_false_cp` stays empty, and `checks.constraint_driven.lpm_error` gives the reason: with the public engine it begins "cannot import name 'compute_lpm' from 'cpm'", and without the engine it reads "No module named 'cpm'".
- **The driver-chain narrative** needs a `driver_chain_narrative` module, which this repository does not ship. `results['driver_chain_narrative']` is an error block instead (an `error` naming the missing module, with empty `narratives` and `manifest`), and the dashboard's Driver-Chain Narratives section shows that error where the narratives would be.

---

## License

MIT — see [LICENSE](LICENSE).

You may use this validator in commercial forensic consulting, in academic research, in your own scheduling product, in court-filed expert reports. Just keep the copyright notice.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Bug reports and pull requests are welcome.

---

## Companion repositories

- **[cpp-cpm-engine](https://github.com/danafitkowski/cpp-cpm-engine)** — The forensically-defensible CPM engine.
- **[cpp-xer-parser](https://github.com/danafitkowski/cpp-xer-parser)** — The XER parser this validator consumes.

---

## Strategic note

Critical Path Partners is a forensic-scheduling consultancy. We open-source the foundational tooling because every academic, every solo forensic, every contractor's internal scheduler now has a reason to install CPP and a citation pathway. The math is a commodity; the workflow and discipline are not.

If you ship something built on this validator, we'd like to hear about it: [criticalpathpartners.ca](https://criticalpathpartners.ca).
