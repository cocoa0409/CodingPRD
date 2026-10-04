"""Domain constants for the SMR Licensing API.

Numeric thresholds and default values named in the PRD's calculation and
validation narratives: the EPZ sizing coefficients and clamp bounds, the
vendor qualification defect threshold, the escalation range cap, and the
withdrawal-penalty tier boundaries.
"""

# ── EPZ sizing (PRD §3.1) ──────────────────────────────────────────────────

EPZ = {
    # Deterministic variant: source term fraction scaled by this factor.
    "DETERMINISTIC_SCALE": 10.0,
    # Dose term: this coefficient times sqrt(site_boundary_miles).
    "DOSE_COEFF": 2.0,
    # Margin term: this coefficient times (1 - source_term_fraction).
    "MARGIN_COEFF": 5.0,
    # Floor applied to the dose-based sum and to the conservative selection.
    "MIN_EPZ": 0.5,
    # Hard cap on the conservative selection.
    "MAX_EPZ": 10.0,
    # Smallest legal site_boundary_miles.
    "MIN_SITE_BOUNDARY_MILES": 0.25,
}

# ── Vendor qualification (PRD §3.4) ────────────────────────────────────────

QUALIFICATION = {
    # defects_found at or above this count on a CONDITIONALLY_QUALIFIED record
    # yields the UNQUALIFIED variant.
    "QUALIFIED_DEFECTS_THRESHOLD": 3,
    # Two non-superseded audits of one vendor must sit at least this many
    # days apart; an overlap strictly inside this window is rejected.
    "AUDIT_OVERLAP_DAYS": 14,
}

# ── Escalation (PRD §3.5) ──────────────────────────────────────────────────

ESCALATION = {
    # overrun_usd must be > 0 and at most this multiple of participant share.
    "MAX_OVERRUN_MULTIPLE": 3,
}

# ── Withdrawal penalty tiers (PRD §3.5) ────────────────────────────────────

# Ordered ascending by min_days; max_days None means open-ended.
WITHDRAWAL_TIERS = [
    {"min_days": 0, "max_days": 30, "rate": 0.0},
    {"min_days": 30, "max_days": 180, "rate": 0.1},
    {"min_days": 180, "max_days": None, "rate": 0.25},
]

# ── Logical clock (PRD §2.5) ───────────────────────────────────────────────

# The instant the logical clock reports on a fresh deployment, before any
# administrative set call.
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"

# ── Shared test defaults ───────────────────────────────────────────────────

TEST_DEFAULTS = {
    "REACTOR_MODEL": "SMR-160",
    "TARGET_POWER_MWT": 300,
    "PLANT_NET_CAPACITY_MW": 100,
    "SOURCE_TERM_FRACTION": 0.5,
    "SITE_BOUNDARY_MILES": 1.0,
    "PRICE_PER_MWH_USD": 55.0,
}
