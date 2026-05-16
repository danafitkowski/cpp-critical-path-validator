# Security Policy

`cpp-critical-path-validator` is used in production forensic delay analyses, EOT submissions, and expert-witness reports. Security defects — particularly any defect that could mislead a court — are treated as release-blocking.

Thank you for taking the time to report.

---

## Supported versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | Yes                |
| < 0.1   | No                 |

The validator ships as `cpp-critical-path-validator` on GitHub. The most recent published version is always the supported reference; back-ports of security fixes to prior 0.1.x point releases are made on a best-effort basis.

---

## Reporting a vulnerability

Do **not** open a public GitHub issue for a suspected vulnerability.

Email `hello@criticalpathpartners.ca` with **the word `SECURITY` in the subject line**. Include:

- A description of the issue
- A minimal reproduction (validator version, Python version, OS, snippet, input)
- The forensic / operational impact you believe it has
- Whether you intend to publicly disclose, and on what timeline

You should expect an initial acknowledgement **within 72 hours**. A confirmed vulnerability will receive a triage plan within 7 days and a fix or mitigation timeline shortly after.

We will credit reporters in the release notes unless you ask to remain anonymous.

---

## What we consider a vulnerability

- **Forensic-correctness math bug that could mislead a court.** Wrong critical-path identification, wrong CPLI / BEI / float-saturation computations, wrong constraint-driven-criticality classifications, missing or mis-fired LPM-confirmed-false-CP detections, DCMA-14 thresholds applied to the wrong profile, missing or wrong Daubert disclosures. The validator's whole value proposition is courtroom defensibility — these defects rank above conventional security bugs.
- **Information disclosure.** Leakage of XER paths or contents through error messages, leakage of customer-supplied schedule data through caches or logs, file-enumeration through user input on the CLI.
- **Denial of service.** Malformed XER inputs that exhaust memory or CPU, regex catastrophic-backtracking attacks against alert messages, infinite loops in the driving-path tracer on cyclic logic.
- **Supply-chain attack vectors.** The validator ships **zero third-party runtime dependencies** in production — a vendored or transitive dependency appearing in CI is itself a finding. Build-time arbitrary code execution, post-install scripts, CI secret exfiltration are in scope. Drift between the bundled `scripts/xer_parser.py` and the canonical upstream in `cpp-xer-parser` (detected by the drift CI check) is also a finding.

---

## What we do NOT consider a vulnerability

- **Performance degradation that does not affect correctness.** "It got 12% slower on a 50,000-activity XER" is not a security issue. Open a normal performance bug.
- **Style / lint issues.** Including pyflakes, black, and "best practice" complaints.
- **Citations that "could be worded better."** Citation defects are handled through the regular issue template, not the security channel. Wrong, mis-attributed, or fabricated citations *are* release-blocking, but they are not security vulnerabilities.
- **The optional LPM cross-check unavailable when `cpm` module is absent.** The validator gracefully degrades; the no-engine path is the documented behavior, not a security issue.
- **Theoretical attacks** with no demonstrated reproduction against a current release.

---

## Disclosure policy

We follow a **90-day coordinated-disclosure timeline**:

1. **Day 0** — report received, reporter acknowledged within 72 hours.
2. **Day 0-7** — triage, severity assignment, fix plan.
3. **Day 7-60** — fix developed, tested against the full validator test suite plus any new regression test the reporter supplies.
4. **Day 60-90** — release coordinated with the reporter. Both sides agree a public-disclosure date.
5. **Day 90** — public disclosure (CHANGELOG entry, GitHub Security Advisory, optional CVE) regardless of whether all downstream consumers have upgraded. The validator is open-source; closed downstream consumers are responsible for their own patch windows.

If the issue is being actively exploited in the wild, we will compress the timeline and ship as soon as a fix is verified.

---

## No bug-bounty program

We do not currently run a paid bug-bounty program. We will credit reporters in the release notes and on the project README. If your employer requires a bounty as a condition of disclosure, please email anyway and we can discuss.

---

## Scope

In scope:

- `cpp-critical-path-validator` source on GitHub
- The bundled `scripts/cp_validator.py`, `scripts/dcma14.py`, `scripts/validation.py`, and `scripts/config_profiles.py`
- The bundled `scripts/xer_parser.py` mirror, where the issue is a divergence from the canonical upstream (also report upstream against `cpp-xer-parser`)
- `criticalpathpartners.ca` website to the extent it advertises validator behavior

Out of scope:

- Third-party clones, forks, or re-distributions
- The optional LPM cross-check feature when `cpm` module from `cpp-cpm-engine` is not on `sys.path` — this is documented graceful-degradation behavior
- The closed CPP forensic skill suite — these have their own security channel; email `hello@criticalpathpartners.ca` and we will route.

---

*Last updated: 2026-05-16.*
