# Changelog

All notable changes to `cpp-critical-path-validator` are documented here. Versioning follows [Semantic Versioning](https://semver.org).

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
- **DCMA 14-Point Assessment** (`dcma_14_assess`) — full DCMA implementation following FAR Part 49, DFARS 234.2, AACE 49R-06, and NDIA PASEG §10. Returns a structured report with per-check severity, value, threshold, message, and details.
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

Tested against `cpp-cpm-engine` v2.9.x (current as of 2026-05-16: v2.9.11+). Check 2's LPM cross-check requires `cpp-cpm-engine` on `PYTHONPATH`; the validator gracefully degrades when the engine is absent (the LPM-confirmed-false-CP detection becomes a no-op and the test for it is skipped). All other checks run stand-alone with zero third-party dependencies. Forward compatibility with future 2.x engine lines is intended; the optional LPM-confirmation API surface is the canonical interface contract.

The bundled `scripts/xer_parser.py` mirrors `cpp-xer-parser` v0.1.x. A CI drift check fails the build if the mirrored copy diverges from the upstream canonical copy; re-vendor when intentional changes are needed.

### Companion repos

- **[cpp-cpm-engine](https://github.com/danafitkowski/cpp-cpm-engine)** — The forensically-defensible CPM engine. Used by Check 2's LPM-confirmed-false-CP detection when available.
- **[cpp-xer-parser](https://github.com/danafitkowski/cpp-xer-parser)** — The XER parser this skill consumes.
