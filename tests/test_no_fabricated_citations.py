"""No citation in this repo may say what its document does not say.

This repo is public and its README is the face of the work. On 2026-08-23 the
"AACE alignment" table carried three defects at once, none of which any check
could see because the estate's citation guard scans a different tree:

  - AACE 24R-03 cited for "constraint-driven criticality (S4)". 24R-03 is
    "Developing Activity Logic", it has NO numbered sections, and nothing in
    this repo cites it.
  - AACE 67R-11 given the title "Forensic Schedule Analysis Competency".
    Its real title is "Contract Risk Allocation".
  - The DCMA 14-Point metrics attributed to "FAR Part 49, DFARS 234.2".
    Their home is DCMA-EA PAM 200.1.

Facts are encoded here rather than read from a reference file because this
repo ships standalone. Verified against AACE's published tables of contents,
recorded in the private estate's reference notes, 2026-08-19 sweep.

The guard scans upward from its own location, so it covers whatever this repo
grows into with no path configuration, and pytest runs it in CI on every push.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]

# (pattern, why it is wrong). A pattern here must be wrong in ANY context;
# meta-lines that negate the claim are exempted below.
FORBIDDEN = [
    (r"24R-03[^\n]{0,60}(?:§|s\.|section)\s*\d",
     "24R-03 (Developing Activity Logic) has no numbered sections; a pinpoint is fabricated"),
    (r"(?i)24R-03[^\n]{0,80}(?:classification|criticalit|health|quality)",
     "24R-03 is Developing Activity Logic, not a classification/criticality/health standard"),
    (r"(?i)67R-11[^\n]{0,80}(?:forensic|competency)",
     "67R-11 is Contract Risk Allocation, not a forensic-competency document"),
    (r"(?i)(?:FAR\s+Part\s+49|DFARS\s+234)[^\n]{0,80}(?:14.Point|DCMA)"
     r"|(?:14.Point|DCMA)[^\n]{0,80}(?:FAR\s+Part\s+49|DFARS\s+234)",
     "the 14 metrics come from DCMA-EA PAM 200.1, not FAR Part 49 / DFARS 234.2"),
    (r"49R-06[^\n]{0,40}(?:§|s\.|section)\s*\d",
     "49R-06 has no numbered sections; cite a named heading (e.g. \"Longest Path\")"),
]

# A line that NEGATES the claim is documenting the ban, not committing it.
META = re.compile(
    r"(?i)\bnot\b|\bno numbered sections\b|\bwrong\b|\bfabricat|\bdo not define\b"
    r"|\bactual home\b|\boriginally said\b|\brows were\b|\bpreviously attributed\b")

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv"}


def _files():
    for p in ROOT.rglob("*"):
        if p.suffix.lower() not in (".py", ".md", ".html", ".txt", ".yml", ".yaml"):
            continue
        if any(part in SKIP_DIRS for part in p.relative_to(ROOT).parts):
            continue
        if p.name == pathlib.Path(__file__).name:
            continue
        yield p


def test_the_scan_actually_reaches_files():
    """A skip rule that swallows the repo silences the whole guard."""
    seen = list(_files())
    assert len(seen) > 5, (
        "scan reached only %d files; check SKIP_DIRS against ROOT=%s"
        % (len(seen), ROOT))


def test_no_fabricated_or_misattributed_citations():
    bad = []
    for p in _files():
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if META.search(line):
                continue
            for pat, why in FORBIDDEN:
                if re.search(pat, line):
                    bad.append("%s:%d [%s]\n    %s"
                               % (p.relative_to(ROOT), i, why, line.strip()[:140]))
    assert not bad, ("citation defect(s):\n" + "\n".join(bad))


def test_the_guard_actually_fires():
    """A guard that cannot match reports clean. These are the literal strings
    that were live in README.md when this guard was written."""
    planted = [
        "| AACE Recommended Practice 24R-03 | Schedule classification, constraint-driven criticality (§4) |",
        "| AACE Recommended Practice 67R-11 | Forensic Schedule Analysis Competency |",
        "| DCMA 14-Point Assessment | Federal contract schedule health (FAR Part 49, DFARS 234.2) |",
        "per AACE 49R-06 §3 the longest path governs",
    ]
    for sample in planted:
        assert not META.search(sample), "meta exemption swallows a real defect: %s" % sample
        assert any(re.search(p, sample) for p, _ in FORBIDDEN), \
            "no pattern matches its own sample: %s" % sample

    ok = [
        "AACE Recommended Practice 49R-06 | Identifying the Critical Path (LPM / TFM / MFP)",
        "DCMA 14-Point Assessment | The 14 schedule-quality metrics (DCMA-EA PAM 200.1)",
        "24R-03 is \"Developing Activity Logic\" and has no numbered sections",
        "NDIA PASEG | Baseline Execution Index",
    ]
    for sample in ok:
        hit = [w for p, w in FORBIDDEN if re.search(p, sample) and not META.search(sample)]
        assert not hit, "guard flags a correct line: %s (%s)" % (sample, hit)
