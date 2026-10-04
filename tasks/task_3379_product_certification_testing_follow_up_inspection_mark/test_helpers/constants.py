"""Domain constants and pure calculators for the Product Certification Followup API.

Every numeric threshold below is taken from a rule the PRD states in prose
(test outcome band and fee rules in section 3.2/3.4, conformity scoring and
inspection intervals in section 3.6, label quotas in section 3.7, the notice
cooling-off in section 3.9, the scheduling gap in section 3.6). The calculator
helpers mirror those PRD formulas exactly so tests can derive expected values
instead of hard-coding them.
"""

import calendar
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, List, Optional, Tuple

__all__ = [
    "ROLE_CERTIFICATION_BODY_ADMIN",
    "ROLE_MANUFACTURER_REP",
    "ROLE_TEST_ENGINEER",
    "ROLE_CERTIFICATION_REVIEWER",
    "ROLE_FACTORY_INSPECTOR",
    "ROLE_COMPLIANCE_OFFICER",
    "ROLE_AHJ_AUTHORITY",
    "ALL_ROLES",
    "BASE_CLOCK_ISO",
    "CONDITIONAL_BAND_PCT",
    "DAMAGED_FEE_MULTIPLIER",
    "SMALL_CLIENT_DISCOUNT",
    "RETEST_SURCHARGE_PCT",
    "PENALTY_CRITICAL",
    "PENALTY_MAJOR",
    "PENALTY_MINOR",
    "PROBATION_THRESHOLD",
    "CONFORMITY_WINDOW_MONTHS",
    "CONFORMITY_BASE_SCORE",
    "INTERVAL_HIGH_MONTHS",
    "INTERVAL_MID_MONTHS",
    "INTERVAL_PROBATION_MONTHS",
    "INTERVAL_MID_SCORE_FLOOR",
    "INTERVAL_HIGH_SCORE_FLOOR",
    "STANDARD_HARD_CAP",
    "PROBATION_HARD_CAP",
    "MIN_LOT",
    "STANDARD_QUOTA_RATE",
    "PROBATION_QUOTA_RATE",
    "MIN_INSPECTION_GAP_DAYS",
    "NOTICE_PERIOD_DAYS",
    "round_half_up",
    "parse_instant",
    "format_instant",
    "add_calendar_months",
    "add_days",
    "conditional_band_floor",
    "determine_test_outcome",
    "compute_fee_snapshot_cents",
    "compute_authorized_quantity",
    "compute_conformity_score",
    "derive_inspection_interval_months",
    "expected_serial_prefix",
]

# ── Role names (PRD section 2.1) ───────────────────────────────────────────

ROLE_CERTIFICATION_BODY_ADMIN = "CertificationBodyAdmin"
ROLE_MANUFACTURER_REP = "ManufacturerRep"
ROLE_TEST_ENGINEER = "TestEngineer"
ROLE_CERTIFICATION_REVIEWER = "CertificationReviewer"
ROLE_FACTORY_INSPECTOR = "FactoryInspector"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_AHJ_AUTHORITY = "AHJAuthority"

ALL_ROLES = (
    ROLE_CERTIFICATION_BODY_ADMIN,
    ROLE_MANUFACTURER_REP,
    ROLE_TEST_ENGINEER,
    ROLE_CERTIFICATION_REVIEWER,
    ROLE_FACTORY_INSPECTOR,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_AHJ_AUTHORITY,
)

# ── Logical clock (PRD section 2.5) ────────────────────────────────────────

# The startup reading of the logical clock; it never falls back to wall-clock.
BASE_CLOCK_ISO = "2026-09-01T00:00:00Z"

# ── Test outcome determination (PRD section 3.2) ───────────────────────────

CONDITIONAL_BAND_PCT = 0.95

# ── Project fee calculation (PRD section 3.4) ──────────────────────────────

DAMAGED_FEE_MULTIPLIER = 1.25
SMALL_CLIENT_DISCOUNT = 0.10
RETEST_SURCHARGE_PCT = 0.5

# ── Factory conformity scoring (PRD section 3.6) ───────────────────────────

PENALTY_CRITICAL = 40
PENALTY_MAJOR = 15
PENALTY_MINOR = 5
PROBATION_THRESHOLD = 70
CONFORMITY_WINDOW_MONTHS = 24
CONFORMITY_BASE_SCORE = 100

# Inspection interval tiers (PRD section 3.6).
INTERVAL_PROBATION_MONTHS = 3
INTERVAL_MID_MONTHS = 6
INTERVAL_HIGH_MONTHS = 12
INTERVAL_MID_SCORE_FLOOR = 70
INTERVAL_HIGH_SCORE_FLOOR = 90

# ── Label quota allocation (PRD section 3.7) ───────────────────────────────

STANDARD_HARD_CAP = 100000
PROBATION_HARD_CAP = 500
MIN_LOT = 100
STANDARD_QUOTA_RATE = "1.10"
PROBATION_QUOTA_RATE = "0.25"

# ── Scheduling and notice timing (PRD sections 3.6, 3.9) ───────────────────

MIN_INSPECTION_GAP_DAYS = 25
NOTICE_PERIOD_DAYS = 14


# ── Rounding and calendar helpers ──────────────────────────────────────────

def round_half_up(value, places: int = 0):
    """Round half away from zero to ``places`` decimal places.

    Returns an ``int`` when ``places`` is 0 (whole cents, whole labels) and a
    ``float`` otherwise (two-decimal margins and conformity scores).
    """
    quantum = Decimal(1).scaleb(-places)
    result = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    if places == 0:
        return int(result)
    return float(result)


def parse_instant(iso: str) -> datetime:
    """Parse an ISO 8601 UTC instant (with or without fractional digits)."""
    text = iso.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def format_instant(moment: datetime) -> str:
    """Render an aware datetime as ``YYYY-MM-DDTHH:MM:SSZ`` (UTC)."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def add_calendar_months(iso: str, months: int) -> str:
    """Add calendar months to an ISO instant (PRD 2.9 calendar arithmetic)."""
    moment = parse_instant(iso)
    month_index = moment.month - 1 + months
    year = moment.year + month_index // 12
    month = month_index % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return format_instant(moment.replace(year=year, month=month, day=day))


def add_days(iso: str, days: int) -> str:
    """Add whole days to an ISO instant."""
    return format_instant(parse_instant(iso) + timedelta(days=days))


# ── PRD calculation mirrors ────────────────────────────────────────────────

def conditional_band_floor(pass_threshold) -> float:
    """The CONDITIONAL band floor: threshold * 0.95, rounded half-up to 2 dp."""
    return round_half_up(Decimal(str(pass_threshold)) * Decimal(str(CONDITIONAL_BAND_PCT)), 2)


def determine_test_outcome(
    measured_value,
    pass_threshold,
    condition: str = "INTACT",
    mandatory: bool = False,
    safety_critical: bool = False,
) -> Tuple[str, float]:
    """Compute ``(outcome, margin)`` exactly as PRD section 3.2 specifies.

    Raw outcome from the threshold and the 0.95 band floor; then the two
    overrides in order: DAMAGED caps PASS to CONDITIONAL, and a CONDITIONAL on
    a mandatory safety-critical protocol becomes FAIL.
    """
    threshold = Decimal(str(pass_threshold))
    measured = Decimal(str(measured_value))
    floor = Decimal(str(conditional_band_floor(pass_threshold)))
    if measured >= threshold:
        raw = "PASS"
    elif measured >= floor:
        raw = "CONDITIONAL"
    else:
        raw = "FAIL"
    if raw == "PASS" and condition == "DAMAGED":
        outcome = "CONDITIONAL"
    elif raw == "CONDITIONAL" and mandatory and safety_critical:
        outcome = "FAIL"
    else:
        outcome = raw
    margin = round_half_up(measured - threshold, 2)
    return outcome, margin


def compute_fee_snapshot_cents(
    lines: Iterable[Tuple[int, str]],
    annual_revenue_tier: str = "SMALL",
    retest_count: int = 0,
) -> int:
    """Program fee snapshot per PRD section 3.4, with the pinned rounding order.

    ``lines`` is an iterable of ``(base_fee_cents, sample_condition)`` pairs -
    one per pinned-standard protocol that has a latest result. Each line is
    multiplied by 1.25 when its carrying sample is DAMAGED and rounded half-up
    to whole cents BEFORE summation; the SMALL-tier 10% discount applies to the
    rounded subtotal; the retest surcharge is 0.5 * retest_count of the
    after-discount amount, rounded half-up.
    """
    rounded_lines: List[int] = []
    for base_fee_cents, condition in lines:
        line = Decimal(str(base_fee_cents))
        if condition == "DAMAGED":
            line *= Decimal(str(DAMAGED_FEE_MULTIPLIER))
        rounded_lines.append(int(line.quantize(Decimal("1"), rounding=ROUND_HALF_UP)))
    subtotal = sum(rounded_lines)
    if annual_revenue_tier == "SMALL":
        after_discount = int(
            (Decimal(subtotal) * (Decimal(1) - Decimal(str(SMALL_CLIENT_DISCOUNT)))).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
    else:
        after_discount = subtotal
    surcharge = int(
        (Decimal(after_discount) * Decimal(str(RETEST_SURCHARGE_PCT)) * Decimal(retest_count)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    return after_discount + surcharge


def compute_authorized_quantity(declared_annual_volume: int, quota_variant: str) -> int:
    """Authorized label count per PRD section 3.7.

    STANDARD_QUOTA: floor(volume * 1.10) capped at 100000.
    PROBATION_QUOTA: floor(volume * 0.25) hard-capped at 500.
    Both variants then floor to a multiple of 100 with a minimum lot of 100.
    """
    volume = Decimal(str(declared_annual_volume))
    if quota_variant == "PROBATION_QUOTA":
        raw = min(int(volume * Decimal(PROBATION_QUOTA_RATE)), PROBATION_HARD_CAP)
    else:
        raw = min(int(volume * Decimal(STANDARD_QUOTA_RATE)), STANDARD_HARD_CAP)
    return max(MIN_LOT, (raw // MIN_LOT) * MIN_LOT)


def compute_conformity_score(severities: Iterable[str]) -> float:
    """Conformity score per PRD section 3.6: 100 minus penalties, floored at 0."""
    penalties = {"CRITICAL": PENALTY_CRITICAL, "MAJOR": PENALTY_MAJOR, "MINOR": PENALTY_MINOR}
    total = sum(penalties[s] for s in severities)
    return round_half_up(max(0, CONFORMITY_BASE_SCORE - total), 2)


def derive_inspection_interval_months(conformity_regime: str, conformity_score) -> int:
    """Inspection interval per PRD section 3.6 (score, then regime, then interval)."""
    score = float(conformity_score)
    if conformity_regime == "PROBATION" or score < INTERVAL_MID_SCORE_FLOOR:
        return INTERVAL_PROBATION_MONTHS
    if score < INTERVAL_HIGH_SCORE_FLOOR:
        return INTERVAL_MID_MONTHS
    return INTERVAL_HIGH_MONTHS


def expected_serial_prefix(listing_number: str, label_type: str) -> str:
    """serial_prefix is listing_number + '-' + the first letter of label_type."""
    return f"{listing_number}-{label_type[0]}"
