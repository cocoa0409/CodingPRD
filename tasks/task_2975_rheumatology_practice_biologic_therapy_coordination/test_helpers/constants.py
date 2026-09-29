"""Domain thresholds, canonical reference-data literals and instant helpers.

Every numeric constant here is stated in the PRD narratives; the canonical
reference-data literals below are the shared fixture data every composite
setup helper builds from.
"""
from datetime import datetime, timedelta, timezone

# --------------------------------------------------------------------------
# Logical clock (PRD §2.11): "Before any caller sets it, the logical clock
# reads exactly 2026-08-01T00:00:00Z".
# --------------------------------------------------------------------------
CLOCK_DEFAULT = "2026-08-01T00:00:00.000Z"


def instant(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
    millis: int = 0,
) -> str:
    """Build an ISO 8601 UTC instant with exactly three fractional digits."""
    return (
        f"{year:04d}-{month:02d}-{day:02d}T"
        f"{hour:02d}:{minute:02d}:{second:02d}.{millis:03d}Z"
    )


def parse_instant(value: str) -> datetime:
    """Parse any ISO 8601 UTC instant spelling into an aware datetime."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def to_instant(value: datetime) -> str:
    """Render an aware datetime as an ISO 8601 UTC instant with three digits."""
    utc = value.astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"


def shift_instant(value: str, **delta) -> str:
    """Return `value` shifted by a timedelta expressed in keyword units."""
    return to_instant(parse_instant(value) + timedelta(**delta))


def plus_days(value: str, days: int) -> str:
    return shift_instant(value, days=days)


def plus_minutes(value: str, minutes: int) -> str:
    return shift_instant(value, minutes=minutes)


# --------------------------------------------------------------------------
# Visit slot lengths (PRD §3.2)
# --------------------------------------------------------------------------
VISIT_SLOT_MINUTES = {"NEW": 60, "FOLLOW_UP": 30, "URGENT": 45}
CLINICIAN_CONCURRENT_VISIT_CAP = 2

# --------------------------------------------------------------------------
# Scoring ladders (PRD §3.2)
# --------------------------------------------------------------------------
CDAI_REMISSION_MAX = 2.80          # inclusive
CDAI_LOW_MAX = 10.00               # inclusive
CDAI_MODERATE_MAX = 22.00          # inclusive
DAS28_REMISSION_STRICT_MAX = 2.60  # exclusive: score < 2.60 is REMISSION
DAS28_LOW_MAX = 3.20               # inclusive
DAS28_MODERATE_MAX = 5.10          # inclusive
ESCALATION_DWELL_DAYS = 90         # inclusive

# --------------------------------------------------------------------------
# Screening currency (PRD §3.3)
# --------------------------------------------------------------------------
SCREEN_VALIDITY_DAYS = 365  # inclusive

# --------------------------------------------------------------------------
# Line of therapy (PRD §3.4)
# --------------------------------------------------------------------------
MAX_LINE_OF_THERAPY = 6
SITE_NEUTRAL_ADMIN_MINUTES_MAX = 180  # inclusive -> AMBULATORY_INFUSION_CENTER

# --------------------------------------------------------------------------
# Step therapy (PRD §3.5)
# --------------------------------------------------------------------------
STEP_THERAPY_INADEQUATE_RESPONSE_MIN_WEEKS = 12

# --------------------------------------------------------------------------
# Lab grading ladders (PRD §3.6)
# --------------------------------------------------------------------------
ALT_GRADE_UPPER_BOUNDS = {0: 40.0, 1: 120.0, 2: 200.0, 3: 400.0}
ANC_GRADE_LOWER_BOUNDS = {0: 1.5, 1: 1.0, 2: 0.5, 3: 0.2}
HOLD_TRIGGER_MIN_GRADE = 3
RESUMPTION_CLEARING_MAX_GRADE = 2

# --------------------------------------------------------------------------
# Assistance coverage tiers (PRD §3.7) — exclusive upper bounds
# --------------------------------------------------------------------------
ASSISTANCE_TIER_FULL_MAX_CENTS = 20_000     # share < 20000 -> 100 percent
ASSISTANCE_TIER_NINETY_MAX_CENTS = 100_000  # 20000 <= share < 100000 -> 90 percent
ASSISTANCE_FRACTION_FULL = 1.00
ASSISTANCE_FRACTION_NINETY = 0.90
ASSISTANCE_FRACTION_EIGHTY = 0.80

# --------------------------------------------------------------------------
# Assistance program window lengths (PRD §3.8), in whole days
# --------------------------------------------------------------------------
PROGRAM_DURATION_DAYS = {
    "MANUFACTURER_COPAY_CARD": 365,
    "FOUNDATION_GRANT": 180,
    "PATIENT_ASSISTANCE_PROGRAM": 90,
}
REAUTH_LEAD_DAYS = 30

# --------------------------------------------------------------------------
# Washout matrix (PRD §3.9), in whole days
# --------------------------------------------------------------------------
WASHOUT_DAYS = {
    "SURGERY": {"TNFI": 14, "IL6": 28, "JAKI": 7, "CD20": 180, "CTLA4": 28},
    "INFECTION": {"TNFI": 7, "IL6": 7, "JAKI": 7, "CD20": 7, "CTLA4": 7},
    "LAB_ABNORMALITY": {"TNFI": 0, "IL6": 0, "JAKI": 0, "CD20": 0, "CTLA4": 0},
    "AUTH_LAPSE": {"TNFI": 0, "IL6": 0, "JAKI": 0, "CD20": 0, "CTLA4": 0},
    "PATIENT_REQUEST": {"TNFI": 0, "IL6": 0, "JAKI": 0, "CD20": 0, "CTLA4": 0},
}

# --------------------------------------------------------------------------
# Quality report (PRD §3.9)
# --------------------------------------------------------------------------
ESCALATION_ACTION_WINDOW_DAYS = 60

# --------------------------------------------------------------------------
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# --------------------------------------------------------------------------
# Canonical reference-data literals shared by the composite fixtures.
# --------------------------------------------------------------------------
MERIDIAN_PLAN = {
    "name": "Meridian PPO",
    "pharmacy_benefit_enabled": True,
    "medical_benefit_enabled": True,
    "site_of_care_policy": "PREFER_AMBULATORY",
    "coinsurance_pct": 0.175,
    "deductible_remaining_cents": 100_000,
    "medical_facility_fee_cents": 12_500,
    "hospital_outpatient_multiplier": 1.40,
    "appeal_rounds_allowed": 2,
    "auth_validity_days": 180,
    "step_therapy_classes_required": ["TNFI"],
}

INFLIXIMAB = {
    "name": "Infliximab",
    "molecule_class": "TNFI",
    "route": "IV",
    "formulary_tier": 3,
    "acquisition_cost_cents": 250_050,
    "admin_time_minutes": 150,
    "monitoring_panel_type": "CMP",
    "monitoring_panel_interval_days": 90,
}

ADALIMUMAB = {
    "name": "Adalimumab",
    "molecule_class": "TNFI",
    "route": "SC",
    "formulary_tier": 3,
    "acquisition_cost_cents": 187_333,
    "admin_time_minutes": 0,
    "monitoring_panel_type": "CBC",
    "monitoring_panel_interval_days": 180,
}

# Derived cost-share figures for Infliximab (250050 cents) on Meridian PPO at an
# AMBULATORY_INFUSION_CENTER site (multiplier 1.00, facility fee 12500,
# deductible 100000, coinsurance 0.175). PRD §3.7 waterfall.
IFX_DOSE_1_SHARE_CENTS = 138_759
IFX_DOSE_N_SHARE_CENTS = 56_259
IFX_DOSE_1_ASSISTANCE_CENTS = 111_007   # 0.80 tier on a 138759 gross share
IFX_DOSE_1_OOP_CENTS = 27_752
IFX_DOSE_2_ASSISTANCE_CENTS = 50_633    # 0.90 tier on a 56259 gross share
IFX_DOSE_2_OOP_CENTS = 5_626

TEST_DEFAULTS = {
    "RHEUM_NPI": "1234567893",
    "NURSE_NPI": "1234567895",
    "PATIENT_MRN": "RH0001",
    "CHAIR_LABEL": "AIC-1",
    "ANNUAL_BENEFIT_CENTS": 500_000,
}
