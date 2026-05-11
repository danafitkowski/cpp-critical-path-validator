# cpp-critical-path-validator

[![license: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![python: 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![status: stable](https://img.shields.io/badge/status-stable-brightgreen.svg)](CHANGELOG.md)
[![AACE: 49R--06 / 24R--03 / 67R--11](https://img.shields.io/badge/AACE-49R--06%20%7C%2024R--03%20%7C%2067R--11-orange.svg)](#aace-alignment)

Critical path validation, logic health assessment, and optimization recommendations for Primavera P6 schedules — plus a full DCMA 14-Point Assessment.

Maintained by [Critical Path Partners](https://criticalpathpartners.ca) — a forensic-scheduling consultancy.

Companion to [`cpp-cpm-engine`](https://github.com/danafitkowski/cpp-cpm-engine) and [`cpp-xer-parser`](https://github.com/danafitkowski/cpp-xer-parser).

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

This validator was built to drive court-filed forensic schedule analysis, so the audit is rigorous. Every finding is structured, cited (DCMA, AACE 49R-06, AACE 24R-03), and includes the full list of affected activities — never truncated.

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
print(f"CP Confidence Score: {results['cp_confidence_score']}/100")
print(f"CP Confidence Band:  {results['cp_confidence_band']}")

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

print(f"DCMA Score: {report['dcma_score']}/14")
print(f"CPLI: {report['cpli']}")
print(f"BEI:  {report['bei']}")

for check_id, check in report['per_check'].items():
    print(f"  {check_id}: {check['severity']} — {check['message']}")
```

Three profiles bundle out of the box:

| Profile      | Use case                                            |
|--------------|-----------------------------------------------------|
| `commercial` | Generic commercial-construction defaults            |
| `nuclear`    | Tightened thresholds for nuclear / heavy energy     |
| `mining`     | Relaxed thresholds for resource-driven mining work  |

Clone and mutate the dict to add your own:

```python
from config_profiles import get_profile

custom = get_profile('commercial')
custom['name'] = 'My Custom Profile'
custom['dcma_high_float_max_days'] = 30
report = dcma_14_assess(data, profile=custom)  # accepts dict or string
```

---

## Driving path tracer

```python
from dcma14 import trace_driving_path

# Walk the driving-predecessor chain for a CP activity back to project start
chain = trace_driving_path(data, task_code='A1050.20')
for step in chain:
    print(f"  {step['task_code']}  TF={step['total_float_days']}  drives via {step['rel_type']}")
```

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

Score bands:

| Score    | Band                  | Meaning                                                          |
|----------|-----------------------|------------------------------------------------------------------|
|  80–100  | High confidence       | CP is logic-driven and reliable.                                 |
|  60–79   | Moderate confidence   | CP has issues but is directionally correct.                      |
|  40–59   | Low confidence        | CP needs significant corrections.                                |
|   0–39   | Unreliable            | CP is artificial; do not rely on it for planning.                |

---

## AACE alignment

The validator cites:

| Reference                      | What it covers                                                   |
|--------------------------------|------------------------------------------------------------------|
| AACE Recommended Practice 49R-06 | Identifying the Critical Path (LPM / TFM / MFP)                |
| AACE Recommended Practice 24R-03 | Schedule classification, constraint-driven criticality (§4)    |
| AACE Recommended Practice 67R-11 | Forensic Schedule Analysis Competency                          |
| DCMA 14-Point Assessment         | Federal contract schedule health (FAR Part 49, DFARS 234.2)    |
| NDIA PASEG §10                   | Baseline Execution Index extension                             |

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

Inside the Critical Path Partners internal forensic suite, this validator is the first thing to run on any new XER. It checks whether the CP is real before any forensic delay analysis, time impact analysis, or claims package work begins. When `cpp-cpm-engine` is on the same `sys.path`, the validator's Check 2 also runs an LPM-confirmed-false-CP detection that cross-validates the schedule's reported critical path against an independently-computed LPM result.

When the engine is not available, the validator gracefully degrades (Check 2 still runs the constraint-driven analysis; the LPM cross-check is skipped).

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
