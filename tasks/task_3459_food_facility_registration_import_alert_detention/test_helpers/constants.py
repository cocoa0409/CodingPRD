"""Domain constants — every value derived from PRD.md verbatim.

Sources:
- Logical clock default:           PRD §2.4 ("starts at exactly 2026-09-01T00:00:00Z")
- Prior-notice lead windows:       PRD §3.3 (8/4/4/2 h minima; 720 h max; amendment halves)
- Screening score:                 PRD §3.4 (base 10/30/60; caps 5/3; weights 8/12 vs 16/24;
                                   terms 35/10/15; SAMPLE at >= 40; cap 100)
- Reconditioning bond:             PRD §3.6 (rate 0.10 per lot, round half up per lot before
                                   summing; storage 1500 cents per whole detained day)
- Importer standing:               PRD §3.2 (PROBATION at 2 refusals or ratio >= 1/5;
                                   REVOKED at 4 refusals or ratio >= 1/2; exact rationals)
- Petition streak:                 PRD §3.7 (trailing compliant run >= 3)
- Recall thresholds:               PRD §3.9 (CLASS_I exactly 100.0/100.0; CLASS_II >= 95.0;
                                   CLASS_III >= 90.0)
- Facility registration:           PRD §3.1 (730-day period; window [expires-90d, expires+30d])
- Detention timing:                PRD §3.6 (response_deadline = detained_at + 240 h) and
                                   PRD §2.4 (auto-refusal sweep at deadline + 24 h, strict)
- Registration number:             PRD §2.5 (FFR-NNNNNN, first value FFR-000001)
- Pagination:                      PRD §2.3 (limit default 10, min 1, max 100; offset 0)
"""

from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------

CLOCK_DEFAULT_UTC = "2026-09-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Prior notice timing windows (PRD §3.3)
# ---------------------------------------------------------------------------

MIN_LEAD_HOURS = {"VESSEL": 8, "AIR": 4, "RAIL": 4, "ROAD": 2}
MAX_LEAD_HOURS = 720
AMENDMENT_MIN_DIVISOR = 2


def amendment_min_lead_hours(transport_mode: str) -> int:
    """Amendment variant minimum lead: half the mode minimum, rounded up (PRD §3.3).

    VESSEL -> 4, AIR -> 2, RAIL -> 2, ROAD -> 1.
    """
    base = MIN_LEAD_HOURS[transport_mode]
    return -(-base // AMENDMENT_MIN_DIVISOR)  # ceil division


# ---------------------------------------------------------------------------
# Entry screening score (PRD §3.4) — pure integer arithmetic, no rounding
# ---------------------------------------------------------------------------

SCREENING_BASE_POINTS = {"LOW": 10, "STANDARD": 30, "HIGH": 60}
VC_CAP = 5
RC_CAP = 3
VC_WEIGHT_BASE = 8
RC_WEIGHT_BASE = 12
VC_WEIGHT_HISTORY = 16
RC_WEIGHT_HISTORY = 24
ALERT_TERM = 35
AMEND_TERM = 10
PROBATION_TERM = 15
SAMPLE_THRESHOLD = 40
SCORE_CAP = 100


def compute_screening_score(
    product_risk_class: str,
    facility_violation_count: int,
    importer_refusal_count: int,
    importer_standing: str,
    is_amendment_pn: bool,
    alert_scope_match: bool,
) -> dict:
    """Recompute the PRD §3.4 screening score exactly as specified.

    Returns {"score", "variant", "probation_adjustment", "decision"} where the
    decision is DETAIN on an active-alert scope match (regardless of score),
    SAMPLE at score >= 40, RELEASE below 40.
    """
    base = SCREENING_BASE_POINTS[product_risk_class]
    vc = min(facility_violation_count, VC_CAP)
    rc = min(importer_refusal_count, RC_CAP)
    if facility_violation_count == 0 and importer_refusal_count == 0:
        variant = "BASE"
        history = VC_WEIGHT_BASE * vc + RC_WEIGHT_BASE * rc
    else:
        variant = "HISTORY_WEIGHTED"
        history = VC_WEIGHT_HISTORY * vc + RC_WEIGHT_HISTORY * rc
    alert_term = ALERT_TERM if alert_scope_match else 0
    amend_term = AMEND_TERM if is_amendment_pn else 0
    probation = PROBATION_TERM if importer_standing == "PROBATION" else 0
    score = min(SCORE_CAP, base + history + alert_term + amend_term + probation)
    if alert_scope_match:
        decision = "DETAIN"
    elif score >= SAMPLE_THRESHOLD:
        decision = "SAMPLE"
    else:
        decision = "RELEASE"
    return {
        "score": score,
        "variant": variant,
        "probation_adjustment": probation,
        "decision": decision,
    }


# ---------------------------------------------------------------------------
# Reconditioning bond (PRD §3.6) — round half up per lot BEFORE summing
# ---------------------------------------------------------------------------

BOND_RATE = Decimal("0.10")
STORAGE_DAILY_CENTS = 1500


def round_half_up_cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_bond_amount_cents(lots, days_detained: int = 0) -> int:
    """PRD §3.6 pinned order: per-lot round half up, then sum, then add storage."""
    bond_from_lots = sum(
        round_half_up_cents(Decimal(lot["quantity"] * lot["unit_value_cents"]) * BOND_RATE)
        for lot in lots
    )
    return bond_from_lots + days_detained * STORAGE_DAILY_CENTS


# ---------------------------------------------------------------------------
# Importer standing (PRD §3.2) — exact rational ratio comparisons
# ---------------------------------------------------------------------------

PROBATION_REFUSALS = 2
REVOKED_REFUSALS = 4


def compute_standing(refusal_count: int, terminal_entry_count: int) -> str:
    """PRD §3.2 pinned order. ratio = refusal_count / max(1, terminal_entry_count);
    the 1/2 test is refusal_count*2 >= max(1, terminal), the 1/5 test is
    refusal_count*5 >= max(1, terminal) — no float rounding."""
    denom = max(1, terminal_entry_count)
    if refusal_count >= REVOKED_REFUSALS or refusal_count * 2 >= denom:
        return "REVOKED"
    if refusal_count >= PROBATION_REFUSALS or refusal_count * 5 >= denom:
        return "PROBATION"
    return "GOOD_STANDING"


# ---------------------------------------------------------------------------
# Petition compliance streak (PRD §3.7)
# ---------------------------------------------------------------------------

REQUIRED_STREAK = 3

# ---------------------------------------------------------------------------
# Recall effectiveness (PRD §3.9) — 1 decimal place, round half up
# ---------------------------------------------------------------------------

CLASS_II_MIN_EFFECTIVENESS_PCT = 95.0
CLASS_III_MIN_EFFECTIVENESS_PCT = 90.0
CLASS_I_REQUIRED_PCT = 100.0  # CLASS_I needs effectiveness AND contact both 100.0


def _round_half_up_1dp(numerator: int, denominator: int) -> float:
    value = Decimal(100 * numerator) / Decimal(denominator)
    return float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def compute_effectiveness_pct(
    quantity_distributed: int,
    quantity_recovered: int,
    quantity_corrected: int,
    quantity_destroyed: int,
) -> float:
    accounted = quantity_recovered + quantity_corrected + quantity_destroyed
    return _round_half_up_1dp(accounted, quantity_distributed)


def compute_consignee_contact_pct(consignees_contacted: int, consignees_total: int) -> float:
    if consignees_total == 0:
        return 0.0
    return _round_half_up_1dp(consignees_contacted, consignees_total)


# ---------------------------------------------------------------------------
# Facility registration (PRD §3.1) and detention timing (PRD §3.6, §2.4)
# ---------------------------------------------------------------------------

REGISTRATION_PERIOD_DAYS = 730
RENEWAL_OPEN_DAYS_BEFORE = 90
RENEWAL_GRACE_DAYS_AFTER = 30

RESPONSE_DEADLINE_HOURS = 240
SWEEP_GRACE_HOURS = 24

# Derived instants for a facility registered at the default clock:
#   expires_at            = 2026-09-01T00:00:00Z + 730 d = 2028-08-31T00:00:00Z
#   renewal window opens  = expires_at - 90 d           = 2028-06-02T00:00:00Z
#   renewal grace ends    = expires_at + 30 d           = 2028-09-30T00:00:00Z
DEFAULT_EXPIRES_AT = "2028-08-31T00:00:00Z"
DEFAULT_RENEWAL_WINDOW_OPEN = "2028-06-02T00:00:00Z"
DEFAULT_RENEWAL_GRACE_END = "2028-09-30T00:00:00Z"
# A detention opened at the default clock gets response_deadline_at 2026-09-11T00:00:00Z
DEFAULT_DETENTION_DEADLINE = "2026-09-11T00:00:00Z"

# ---------------------------------------------------------------------------
# Registration number sequence (PRD §2.5)
# ---------------------------------------------------------------------------

REGISTRATION_NUMBER_PREFIX = "FFR-"
FIRST_REGISTRATION_NUMBER = "FFR-000001"

# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Opaque operator identifiers (PRD §2.1: the five non-entity-backed roles use
# opaque X-User-ID values; the server records but never resolves them)
# ---------------------------------------------------------------------------

PLATFORM_ADMIN_ID = "pa-1"
ENTRY_REVIEWER_ONE_ID = "er-1"
ENTRY_REVIEWER_TWO_ID = "er-2"
COMPLIANCE_OFFICER_ONE_ID = "co-1"
COMPLIANCE_OFFICER_TWO_ID = "co-2"
FIELD_INSPECTOR_ONE_ID = "fi-1"
FIELD_INSPECTOR_TWO_ID = "fi-2"
RECALL_COORDINATOR_ONE_ID = "rc-1"
RECALL_COORDINATOR_TWO_ID = "rc-2"

# ---------------------------------------------------------------------------
# Whole-second ISO-8601 helpers (PRD §3.1: "whole-second timestamp comparisons")
# ---------------------------------------------------------------------------


def _parse_utc(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _format_utc(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_add_days(ts: str, days: int) -> str:
    return _format_utc(_parse_utc(ts) + timedelta(days=days))


def iso_add_hours(ts: str, hours: float) -> str:
    return _format_utc(_parse_utc(ts) + timedelta(hours=hours))


# ---------------------------------------------------------------------------
# Fixture defaults consistent with the default logical clock
# (48 h VESSEL lead satisfies the 8 h minimum and the 720 h maximum)
# ---------------------------------------------------------------------------

DEFAULT_Arrival_ETA = "2026-09-03T00:00:00Z"
DEFAULT_ANALYSIS_DATE = "2026-09-01"
DEFAULT_INSPECTION_START = "2026-09-05T09:00:00Z"
DEFAULT_INSPECTION_END = "2026-09-05T17:00:00Z"
