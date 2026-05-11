"""
validation.py — minimal Finding / ValidationReport types

Public, standalone subset of the validation primitives used by cp_validator
and dcma14. The full version lives inside the Critical Path Partners
internal `_cpp_common` module and carries additional plumbing for the
forensic-suite-wide audit trail. This subset is sufficient for the OSS
critical-path-validator to run end-to-end.

The four severity sentinels (BLOCK / WARN / INFO / PASS) are plain strings —
matching the public-API contract of the full version — so any code that
imports them, compares against them, or includes them in serialized output
will behave identically.
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


@dataclass
class Finding:
    """A single validation finding produced by a check.

    Attributes
    ----------
    severity   : one of BLOCK / WARN / INFO / PASS
    check_id   : stable identifier for the check (e.g. 'DCMA-01-Logic')
    message    : human-readable description
    reference  : citation string (e.g. 'DCMA 14-Point #1', 'AACE 49R-06 §4')
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
        return {
            'subject': self.subject,
            'context': dict(self.context),
            'findings': [f.to_dict() for f in self.findings],
            'counts': self.counts(),
        }


__all__ = [
    'BLOCK', 'WARN', 'INFO', 'PASS',
    'Finding', 'ValidationReport',
]
