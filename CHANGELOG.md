# Changelog

All notable changes to `cpp-critical-path-validator` are documented here. Versioning follows [Semantic Versioning](https://semver.org).

---

## Unreleased

Changes on `main` since the v0.1.0 tag. These are corrections to the build and to
public claims, not new validator features.

### Fixed

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
  `scripts/xer_parser.py` is now re-vendored byte for byte from
  `cpp-xer-parser` at [`5fc6c5e`](https://github.com/danafitkowski/cpp-xer-parser/commit/5fc6c5e034f4d740040c5655763612b320068743),
  and the hard check verifies the bundled copy against a recorded SHA-256 with no
  network access at all, so it is deterministic and cannot flake. A second, advisory
  step cross-checks the pin against GitHub and reports when upstream has moved past
  it, and is written so that it can never fail the build. The re-vendored text is
  also the better citation: it pinpoints the half-step to AACE 29R-03 §2.3.D.2,
  "Bifurcation: Creating a Progress-Only Half-Step Update".
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

### Added

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
