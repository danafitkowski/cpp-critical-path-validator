"""
validation.py — minimal Finding / ValidationReport types

Public, standalone subset of the validation primitives used by cp_validator
and dcma14. The full version lives inside the Critical Path Partners
internal `_cpp_common` module and carries additional plumbing for the
forensic-suite-wide audit trail. This subset is sufficient for the OSS
critical-path-validator, and for `xer_parser.validate_schedule` and
`xer_parser.aace_31r_compliance`, to run end-to-end from a plain clone.

The four severity sentinels (BLOCK / WARN / INFO / PASS) are plain strings —
matching the public-API contract of the full version — so any code that
imports them, compares against them, or includes them in serialized output
will behave identically.

`ValidationReport.to_dict()` carries the full version's `summary` block: the
number of findings at each severity, the total, and `worst_severity`, the
worst severity present (BLOCK > WARN > INFO > PASS; PASS for an empty
report). A caller that reads `to_dict()['summary']['worst_severity']` gets
the same answer from either version. Two differences remain, both kept so
that output this subset already produced does not move: `to_dict()` also
carries this subset's `counts` key, and it lists findings in the order they
were added, where the full version sorts them worst first.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ─────────────────────────────────────────────────────────────────────
# Severity sentinels
# Public-API contract: these are strings. Compare with ==, not `is`.
# ─────────────────────────────────────────────────────────────────────
BLOCK = 'BLOCK'   # Forensic-correctness blocker. Findings at this level fail the suite.
WARN  = 'WARN'    # Caution-level finding. The schedule may still be usable.
INFO  = 'INFO'    # Informational note. No corrective action implied.
PASS  = 'PASS'    # Check passed. No finding to report.

_VALID_SEVERITIES = (BLOCK, WARN, INFO, PASS)

# Rank of each severity, worst highest. `ValidationReport.worst_severity`
# reads the worst finding by this order.
_SEVERITY_ORDER = {BLOCK: 3, WARN: 2, INFO: 1, PASS: 0}


@dataclass
class Finding:
    """A single validation finding produced by a check.

    Attributes
    ----------
    severity   : one of BLOCK / WARN / INFO / PASS
    check_id   : stable identifier for the check (e.g. 'DCMA-01-Logic')
    message    : human-readable description
    reference  : citation string (e.g. 'DCMA 14-Point #1', 'AACE 49R-06')
    evidence   : structured supporting data (key/value, e.g. {'value': ..., 'threshold': ...})
    """
    severity: str
    check_id: str
    message: str
    reference: str = ''
    evidence: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.severity not in _VALID_SEVERITIES:
            raise ValueError(
                f"Finding.severity must be one of {_VALID_SEVERITIES}; got {self.severity!r}"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            'severity': self.severity,
            'check_id': self.check_id,
            'message': self.message,
            'reference': self.reference,
            'evidence': dict(self.evidence),
        }


@dataclass
class ValidationReport:
    """An ordered list of Finding instances plus a subject and context.

    Attributes
    ----------
    subject : free-form report title (e.g. 'DCMA 14-Point Assessment [commercial]')
    context : free-form metadata (profile name, schedule identifiers, etc.)
    findings: ordered list of Finding instances (insertion order preserved)
    """
    subject: str = ''
    context: Dict[str, Any] = field(default_factory=dict)
    findings: List[Finding] = field(default_factory=list)

    def add(self, finding: Finding) -> None:
        """Append a Finding to the report."""
        if not isinstance(finding, Finding):
            raise TypeError(f"add() expects a Finding instance; got {type(finding).__name__}")
        self.findings.append(finding)

    def by_severity(self, severity: str) -> List[Finding]:
        """Return findings filtered to one severity level."""
        return [f for f in self.findings if f.severity == severity]

    def count(self, severity=None):
        """Return the number of findings at one severity level, or the
        number of all findings when no severity is given.

        Carried alongside `counts()` because callers use both shapes:
        `xer_parser.aace_31r_compliance` scores a schedule by calling
        `count(BLOCK)` and `count(WARN)` directly, so a subset without this
        method makes that function raise AttributeError on a plain clone.
        `count()` with no argument is the `total` in `to_dict()['summary']`,
        as in the full version.
        """
        if severity is None:
            return len(self.findings)
        return sum(1 for f in self.findings if f.severity == severity)

    @property
    def worst_severity(self):
        """Highest severity present, or PASS if none."""
        if not self.findings:
            return PASS
        return max(self.findings, key=lambda f: _SEVERITY_ORDER[f.severity]).severity

    def counts(self) -> Dict[str, int]:
        """Return a dict of severity → count over all findings."""
        out = {sev: 0 for sev in _VALID_SEVERITIES}
        for f in self.findings:
            out[f.severity] = out.get(f.severity, 0) + 1
        return out

    def has_blocking(self) -> bool:
        """True if any finding is BLOCK severity."""
        return any(f.severity == BLOCK for f in self.findings)

    def to_dict(self) -> Dict[str, Any]:
        """Return the report as a JSON-safe dict.

        `summary` has the full version's keys and values: the count at each
        severity, `total`, and `worst_severity`. `findings` are in the order
        they were added (the full version sorts them worst first), and
        `counts` is kept for callers of earlier releases.
        """
        return {
            'subject': self.subject,
            'context': dict(self.context),
            'summary': {
                'block': self.count(BLOCK),
                'warn': self.count(WARN),
                'info': self.count(INFO),
                'pass': self.count(PASS),
                'total': self.count(),
                'worst_severity': self.worst_severity,
            },
            'findings': [f.to_dict() for f in self.findings],
            'counts': self.counts(),
        }


__all__ = [
    'BLOCK', 'WARN', 'INFO', 'PASS',
    'Finding', 'ValidationReport',
]
