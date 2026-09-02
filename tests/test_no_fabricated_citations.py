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

# Recommended Practices this repo has retracted. They may be DISCUSSED (the
# "AACE alignment" section explains why both rows were removed) but they may
# never be ADVERTISED in a badge, because a badge is a bare claim in the
# first screen with no room for the retraction that follows.
RETRACTED_RPS = {
    "24R-03": "Developing Activity Logic; row removed from the AACE alignment table",
    "67R-11": "Contract Risk Allocation; row removed from the AACE alignment table",
}

BADGE = re.compile(r"img\.shields\.io/badge/", re.I)

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv"}


def _normalize(line):
    """Fold the shields.io hyphen escape before matching.

    A badge encodes a literal ``-`` as ``--``, so the citation ``24R-03``
    reaches the file as ``24R--03`` in both the alt text and the URL. Every
    pattern below is written with single hyphens, so without this fold a
    citation defect goes invisible the moment it is put in a badge. That is
    exactly how ``AACE: 49R--06 | 24R--03 | 67R--11`` sat in the README
    badge row for months while the body three screens down retracted two of
    the three.
    """
    return re.sub(r"(?<=\w)--(?=\w)", "-", line)


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
            norm = _normalize(line)
            if META.search(norm):
                continue
            for pat, why in FORBIDDEN:
                if re.search(pat, norm):
                    # Report the line as it appears in the file, not folded,
                    # so the reader can find it with a plain search.
                    bad.append("%s:%d [%s]\n    %s"
                               % (p.relative_to(ROOT), i, why, line.strip()[:140]))
    assert not bad, ("citation defect(s):\n" + "\n".join(bad))


def test_no_badge_advertises_a_retracted_rp():
    """A badge may not cite a Recommended Practice the README retracts.

    The README badge row rendered ``AACE: 49R-06 | 24R-03 | 67R-11`` while
    the "AACE alignment" section explained that 24R-03 and 67R-11 had been
    removed because their descriptions were wrong and nothing in the repo
    cites either. The correction reached the table and never reached the
    badge above it, and it stood that way from 2026-08-23. This guard is
    deliberately scoped to badge lines: the prose that performs the
    retraction has to be free to name both RPs.
    """
    bad = []
    for p in _files():
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if not BADGE.search(line):
                continue
            norm = _normalize(line)
            for rp, why in RETRACTED_RPS.items():
                if rp in norm:
                    bad.append("%s:%d advertises retracted %s (%s)\n    %s"
                               % (p.relative_to(ROOT), i, rp, why,
                                  line.strip()[:140]))
    assert not bad, ("badge advertises retracted RP(s):\n" + "\n".join(bad))


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


def test_the_shields_escape_fold_actually_fires():
    """Without the fold, putting a defect in a badge hides it completely."""
    escaped = ("[![AACE](https://img.shields.io/badge/AACE-24R--03%20"
               "schedule%20classification-orange.svg)](#aace-alignment)")
    assert not any(re.search(p, escaped) for p, _ in FORBIDDEN), (
        "sample no longer needs the fold; it matches raw, so it proves nothing")
    assert any(re.search(p, _normalize(escaped)) for p, _ in FORBIDDEN), (
        "the shields.io `--` fold does not expose a defect it should expose")

    # And the fold must not invent matches in ordinary prose.
    assert _normalize("a well-known schedule -- as everyone agrees") == \
        "a well-known schedule -- as everyone agrees"


def test_the_retracted_badge_guard_actually_fires():
    """The literal badge that was live in README.md, and the two shapes that
    must stay legal."""
    planted = ("[![AACE: 49R--06 / 24R--03 / 67R--11]"
               "(https://img.shields.io/badge/AACE-49R--06%20%7C%2024R--03%20"
               "%7C%2067R--11-orange.svg)](#aace-alignment)")
    assert BADGE.search(planted), "sample is not recognised as a badge line"
    assert any(rp in _normalize(planted) for rp in RETRACTED_RPS), \
        "the retracted-RP badge guard cannot match the badge it was written for"

    # A badge citing only the RP the repo still stands behind is fine.
    kept = ("[![AACE: 49R--06](https://img.shields.io/badge/AACE-49R--06"
            "-orange.svg)](#aace-alignment)")
    assert BADGE.search(kept)
    assert not any(rp in _normalize(kept) for rp in RETRACTED_RPS), \
        "guard rejects a badge that cites only 49R-06"

    # Prose naming a retracted RP is not a badge and must not be caught.
    prose = ("descriptions that were wrong: 24R-03 is \"Developing Activity "
             "Logic\", has no numbered sections")
    assert not BADGE.search(prose), \
        "the retraction prose is being treated as a badge"
