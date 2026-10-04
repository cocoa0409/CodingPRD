"""Domain thresholds and shared fixture defaults.

Values are the constants the PRD names for its calculations and deadline
windows, plus the standard scenario defaults used by the composite fixtures.
"""
from datetime import datetime, timedelta

# ─── Calculation constants (PRD §2.9, §3.3–§3.8) ──────────────────────────
THRESHOLDS = {
    # Clinical review outcome
    "FAIL_COVERAGE_THRESHOLD": 0.80,
    "OUTCOME_SCORE_CEILING": 10.0,
    # Phantom composite score
    "PASS_THRESHOLD": 7.0,
    # Survey dose deviation bands
    "FULL_CREDIT_BAND_PCT": 5.0,
    "PARTIAL_CREDIT_BAND_PCT": 10.0,
    "ABSOLUTE_DEVIATION_LIMIT_PCT": 10.0,
    "QUALIFICATION_PROMOTION_PCT": 8.0,
    # Corrective action deadline
    "DUE_SOON_WINDOW_DAYS": 10,
    # Random site audit
    "AUDIT_MANDATORY_CYCLE_PERIOD": 5,
    "AUDIT_FAILING_SURVEY_TRIGGER": 2,
    # Registry benchmark classification
    "WITHIN_BENCHMARK_RATIO": 1.00,
    "ABOVE_BENCHMARK_RATIO": 1.35,
    # Roster aggregation
    "LAPSED_HALT_COUNT": 2,
    "PENDING_HOLD_COUNT": 3,
}

# Modality → comparison dose index constant
MODALITY_COMPARISON = {
    "MRI": 2.0,
    "CT": 2.3,
    "MAMM": 2.5,
    "PET": 3.0,
    "US": 2.2,
}

# ─── Ledger amounts ───────────────────────────────────────────────────────
REGISTRY_FEE_CENTS = 2500
RENEWAL_FEE_CENTS = 75000
SURVEY_RESUBMISSION_FEE_CENTS = 100000

# ─── Temporal offsets ─────────────────────────────────────────────────────
CYCLE_LENGTH_DAYS = 1095
CLINICAL_DEADLINE_OFFSET_DAYS = 547
DEFICIENCY_DEADLINE_OFFSET_DAYS = 45
PHANTOM_FAILURE_DEADLINE_OFFSET_DAYS = 30
RENEWAL_EXTENSION_DAYS = 90
PLAN_RESPONSE_GRACE_DAYS = 1
PLAN_REJECTION_EXTENSION_DAYS = 30
SECONDS_PER_DAY = 86400

# ─── Logical clock ────────────────────────────────────────────────────────
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"
SCENARIO_CLOCK = "2026-09-05T00:00:00Z"

# ─── Fixture defaults ─────────────────────────────────────────────────────
TEST_DEFAULTS = {
    "FACILITY_NAME": "Northgate Imaging Center",
    "STATE_CODE": "CT",
    "FACILITY_TYPE": "IMAGING_CENTER",
    "UNIT_LABEL": "CT-1",
    "MODALITY_CODE": "CT",
    "SERIAL_NUMBER": "SN-CT-0001",
    "MANUFACTURER": "Siemens",
    "MODEL_NUMBER": "SOMATOM-X1",
    "INSTALLED_ON": "2026-08-01T00:00:00Z",
    "TECH_CREDENTIAL_NUMBER": "TECH-1001",
    "TECH_NAME": "Hana Reyes",
    "PHYSICIST_CREDENTIAL_NUMBER": "PHYS-2001",
    "PHYSICIST_NAME": "Ira Sundaram",
    "TECH_EXPIRES_ON": "2027-06-30T00:00:00Z",
    "PHYSICIST_EXPIRES_ON": "2028-06-30T00:00:00Z",
    "VERIFIED_AT": "2026-09-02T00:00:00Z",
    "CYCLE_STARTED_AT": "2026-09-01T00:00:00Z",
    "SURVEY_SCHEDULED_AT": "2026-09-03T00:00:00Z",
    "SURVEY_PERFORMED_AT": "2026-09-10T00:00:00Z",
    "REFERENCE_DOSE_MGY": 2.0,
    "MEASURED_DOSE_MGY": 2.15,
    "REGISTRY_CREDIT_TOPUP": 500000,
    "PHANTOM_SERIAL_CODE": "PH-CT-9",
    "PHANTOM_ACQUIRED_AT": "2026-09-13T00:00:00Z",
    "PHANTOM_DURATION_MINUTES": 30,
}


def iso(value) -> str:
    """Render a datetime (or pass a string through) as an ISO 8601 UTC string."""
    if isinstance(value, str):
        return value
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(value: str) -> datetime:
    """Parse an ISO 8601 timestamp into an aware UTC datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def days_after(value: str, days: int) -> str:
    """Return `value` shifted forward by `days` whole days."""
    return iso(parse(value) + timedelta(days=days))


def default_clock() -> datetime:
    return parse(DEFAULT_CLOCK)


def scenario_clock() -> datetime:
    return parse(SCENARIO_CLOCK)


__all__ = [
    "THRESHOLDS", "MODALITY_COMPARISON",
    "REGISTRY_FEE_CENTS", "RENEWAL_FEE_CENTS", "SURVEY_RESUBMISSION_FEE_CENTS",
    "CYCLE_LENGTH_DAYS", "CLINICAL_DEADLINE_OFFSET_DAYS",
    "DEFICIENCY_DEADLINE_OFFSET_DAYS", "PHANTOM_FAILURE_DEADLINE_OFFSET_DAYS",
    "RENEWAL_EXTENSION_DAYS", "PLAN_RESPONSE_GRACE_DAYS",
    "PLAN_REJECTION_EXTENSION_DAYS", "SECONDS_PER_DAY",
    "DEFAULT_CLOCK", "SCENARIO_CLOCK", "TEST_DEFAULTS",
    "iso", "parse", "days_after", "default_clock", "scenario_clock",
]