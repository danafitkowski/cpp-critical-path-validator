"""
config_profiles.py — minimal DCMA-14 / cp_validator threshold profiles

Public, standalone subset of the profile registry used by cp_validator and
dcma14. The full version lives inside the Critical Path Partners internal
`_cpp_common` module and additionally drives forensic-delay-analysis,
schedule-risk-analysis, and time-impact-analysis. This subset covers the
threshold keys consumed by the DCMA-14 check suite.

Three profiles ship out of the box:
  - `commercial` — generic commercial-construction defaults
  - `nuclear`    — tightened thresholds suitable for nuclear / heavy energy
                    where regulator scrutiny is high
  - `mining`     — slightly relaxed thresholds for resource-driven mining
                    schedules where some DCMA assumptions don't translate

External users can clone any profile dict, mutate, and pass it directly to
the validator (e.g. via the `profile` parameter on `dcma_14_assess`).

The threshold keys are documented in the dcma14.py header — each `_check_NN_*`
function reads one or two keys from the profile dict by name.
"""

from typing import Dict


# ─────────────────────────────────────────────────────────────────────
# Profile registry
# ─────────────────────────────────────────────────────────────────────

_COMMERCIAL: Dict[str, object] = {
    'name': 'Commercial Construction',
    # DCMA 14-Point thresholds
    'dcma_logic_max_missing_pct':       5.0,   # #1  Logic
    'dcma_leads_max_count':             0,     # #2  Leads (negative lags)
    'dcma_lags_max_pct':                5.0,   # #3  Lags
    'dcma_fs_min_pct':                  90.0,  # #4  FS Relationship %
    'dcma_hard_constraints_max_pct':    5.0,   # #5  Hard Constraints
    'dcma_high_float_max_days':         44,    # #6  High Float threshold
    'dcma_high_float_max_pct':          5.0,
    'dcma_negative_float_max_count':    0,     # #7  Negative Float
    'dcma_high_duration_max_days':      44,    # #8  High Duration threshold
    'dcma_high_duration_max_pct':       5.0,
    'dcma_invalid_dates_max_count':     0,     # #9  Invalid Dates / Future Actuals
    'dcma_resources_min_pct':           80.0,  # #10 Resources
    'dcma_missed_tasks_max_pct':        5.0,   # #13 Missed Tasks
    'dcma_cpli_min':                    0.95,  # #14 CPLI
    'bei_min':                          0.95,  # BEI extension
}

_NUCLEAR: Dict[str, object] = {
    'name': 'Nuclear / Heavy Energy',
    'dcma_logic_max_missing_pct':       2.0,
    'dcma_leads_max_count':             0,
    'dcma_lags_max_pct':                3.0,
    'dcma_fs_min_pct':                  95.0,
    'dcma_hard_constraints_max_pct':    3.0,
    'dcma_high_float_max_days':         44,
    'dcma_high_float_max_pct':          3.0,
    'dcma_negative_float_max_count':    0,
    'dcma_high_duration_max_days':      30,
    'dcma_high_duration_max_pct':       3.0,
    'dcma_invalid_dates_max_count':     0,
    'dcma_resources_min_pct':           90.0,
    'dcma_missed_tasks_max_pct':        3.0,
    'dcma_cpli_min':                    0.98,
    'bei_min':                          0.98,
}

_MINING: Dict[str, object] = {
    'name': 'Mining / Resource-Driven',
    'dcma_logic_max_missing_pct':       8.0,
    'dcma_leads_max_count':             0,
    'dcma_lags_max_pct':                8.0,
    'dcma_fs_min_pct':                  85.0,
    'dcma_hard_constraints_max_pct':    8.0,
    'dcma_high_float_max_days':         60,
    'dcma_high_float_max_pct':          8.0,
    'dcma_negative_float_max_count':    0,
    'dcma_high_duration_max_days':      60,
    'dcma_high_duration_max_pct':       8.0,
    'dcma_invalid_dates_max_count':     0,
    'dcma_resources_min_pct':           70.0,
    'dcma_missed_tasks_max_pct':        8.0,
    'dcma_cpli_min':                    0.90,
    'bei_min':                          0.90,
}

_PROFILES: Dict[str, Dict[str, object]] = {
    'commercial': _COMMERCIAL,
    'nuclear':    _NUCLEAR,
    'mining':     _MINING,
}


def get_profile(name: str) -> Dict[str, object]:
    """Return the threshold dict for a named profile.

    Parameters
    ----------
    name : 'commercial' | 'nuclear' | 'mining'

    Returns
    -------
    dict
        A shallow copy of the registered profile. Callers may mutate the
        return value without affecting the registry.

    Raises
    ------
    ValueError
        If `name` is not a registered profile.
    """
    if name not in _PROFILES:
        valid = sorted(_PROFILES)
        raise ValueError(f"Unknown profile {name!r}; valid: {valid}")
    # Return a copy so callers can safely mutate.
    return dict(_PROFILES[name])


def list_profiles() -> Dict[str, str]:
    """Return {profile_id: human_name} over all registered profiles."""
    return {pid: prof.get('name', pid) for pid, prof in _PROFILES.items()}


__all__ = ['get_profile', 'list_profiles']
