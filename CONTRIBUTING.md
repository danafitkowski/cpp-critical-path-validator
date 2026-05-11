# Contributing to `cpp-critical-path-validator`

Thank you for considering a contribution. This validator is used in court-filed forensic schedule reports. Contributions are welcome and the bar is high.

---

## Quick rules

1. **Every commit must pass the existing tests.**
   ```bash
   python tests/test_cp_validator.py
   python tests/test_dcma14.py
   python tests/test_cp_forensic.py
   ```
   Or with pytest:
   ```bash
   pip install pytest
   pytest tests/
   ```

2. **Run all tests before opening a PR.** CI runs the same suite on Ubuntu, macOS, and Windows across Python 3.10, 3.11, and 3.12.

3. **No real client XER files in tests.** Every fixture must be built synthetically in memory at test time. We deliberately ship no client data with this repo.

---

## Forensic-correctness rules

The validator is used in court. Sloppy contributions ship as evidence.

### No data truncation in user-facing output

The validator returns findings as structured `Finding` instances inside a `ValidationReport`. Every list inside `evidence` (e.g. open-ends list, out-of-sequence list, constraint-driven CP list) must be emitted in full. No `[:30]`, no "top 10", no "+ N more". A judge or opposing expert reading the report has to see every affected activity, not a sample.

There is a regression test in `test_cp_validator.py` that locks this rule in. New checks must follow the same discipline.

### Citation discipline

- Every reference string in a `Finding.reference` field must cite a real, verifiable source: a DCMA item number, an AACE Recommended Practice section, a federal regulation, or a court decision. No fabricated case names. No invented section numbers.
- AACE 29R-03 Windows analysis is correctly labeled MIP 3.3 (not MIP 3.7, which is the additive-prospective TIA). This validator does not run Windows analysis but the constraint surface of cp_validator can confuse the two; double-check before adding citations to that area.

### Constraint taxonomy discipline

The four-tier constraint taxonomy (HARD_ABSOLUTE / HARD_DATE / SOFT / PREFERENCE) maps to specific P6 24.12 constraint codes. Any change to the taxonomy must update the recommendation prose to match the new tier semantics. A scheduler removing a Mandatory constraint reads different advice than one removing a Start-On.

### Score-weights discipline

The CP Confidence Score weights sum to exactly 1.00. Any change to `CHECK_WEIGHTS` must preserve this. A drifted-sum CP score is a Daubert vulnerability.

---

## Pull-request checklist

- [ ] All existing tests pass on Python 3.10 / 3.11 / 3.12.
- [ ] New behavior is covered by a synthetic test fixture.
- [ ] No real client data appears in the diff.
- [ ] CHANGELOG describes the change.
- [ ] If you changed `CHECK_WEIGHTS`, the sum is still 1.00.
- [ ] If you added a citation, it is verifiable in a primary source.

---

## Style

- 4-space indentation. No tabs.
- Comments explain *why*, not *what*.
- Pure functions where possible.

---

## Reporting bugs

Open an issue at https://github.com/danafitkowski/cpp-critical-path-validator/issues.

A good bug report includes:

1. The synthetic XER fixture that reproduces the issue (please redact any client data before sharing).
2. The expected check rating / score / recommendation.
3. The observed output.
4. Python version (`python --version`).
5. Operating system.

Forensic-correctness bugs (wrong score, missing finding, fabricated citation, silent truncation) are treated as critical.

---

## License

By contributing, you agree your contribution will be licensed under the MIT license that covers the project.

---

## Code of conduct

Be technically rigorous. Cite primary sources. Verify before asserting. Be courteous in code review.
