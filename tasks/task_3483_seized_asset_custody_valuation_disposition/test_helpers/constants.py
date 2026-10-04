"""Domain thresholds and pinned numeric constants stated by the PRD.

Every value below is stated verbatim in PRD prose:
- §2.4  logical clock default 2026-09-01T00:00:00Z
- §2.6  round half up: add half of the ten-thousand divisor (5,000), then floor
- §3.3  condition factors, capitalization rate, carrying rates, retention floor,
        six-month provisional projection
- §3.4  interlocutory ratio (30 percent) and three-month projection
- §3.6  tiered marginal auction fee
- §3.5  appeal limit of one
- §3.7  equitable-share minimum of 10,000 cents
- §3.8  depreciation basis points, 60 percent cap, 30-day dispute window
"""

from datetime import datetime
from typing import Dict, List, Optional

# ─── Logical clock (PRD §2.4) ────────────────────────────────────────────────

CLOCK_EPOCH = "2026-09-01T00:00:00Z"

# The same startup clock reading rendered in the format PRD §2.5 pins on the
# system fields: "`created_at` (string): an ISO 8601 UTC timestamp with three
# fractional digits, stamped at creation."  §2.4 defines the instant ("Time
# inside this API is defined by a server-side logical clock, never by
# wall-clock time"); §2.5 defines its serialization for created_at/updated_at.
CLOCK_EPOCH_SYSTEM_STAMP = "2026-09-01T00:00:00.000Z"

# ─── Valuation: condition adjustment and capitalization (PRD §3.3) ───────────

CAPITALIZATION_BPS = 3300

CONDITION_FACTOR_BPS: Dict[str, int] = {
    "EXCELLENT": 10000,
    "GOOD": 9000,
    "FAIR": 7500,
    "POOR": 5000,
    "SALVAGE": 2500,
}

# ─── Retention estimates (PRD §3.3) ──────────────────────────────────────────

PROVISIONAL_PROJECTION_MONTHS = 6
RETENTION_VALUE_FLOOR_CENTS = 500_000

MONTHLY_CARRYING_COST_CENTS: Dict[str, int] = {
    "REAL_PROPERTY": 150_000,
    "BUSINESS": 400_000,
    "VEHICLE": 25_000,
    "VESSEL": 60_000,
    "AIRCRAFT": 120_000,
    "PERSONAL_PROPERTY": 8_000,
    "FINANCIAL_INSTRUMENT": 2_000,
}

# ─── Interlocutory eligibility (PRD §3.4) ────────────────────────────────────

ISR_PROJECTION_MONTHS = 3
INTERLOCUTORY_RATIO_THRESHOLD_PCT = 30

# ─── Auction fee schedule (PRD §3.6) ─────────────────────────────────────────

TIER1_CAP_CENTS = 1_000_000
TIER1_BPS = 1000
TIER2_CAP_CENTS = 4_000_000
TIER2_BPS = 700
TIER3_BPS = 400

# ─── Liens and appeals (PRD §3.5) ────────────────────────────────────────────

APPEAL_LIMIT = 1

# ─── Equitable sharing (PRD §3.7) ────────────────────────────────────────────

EQUITABLE_SHARE_MIN_CENTS = 10_000

# ─── Depreciation and disputes (PRD §3.8) ────────────────────────────────────

GRADE_RANK: Dict[str, int] = {
    "EXCELLENT": 5,
    "GOOD": 4,
    "FAIR": 3,
    "POOR": 2,
    "SALVAGE": 1,
}
DEPRECIATION_PER_GRADE_STEP_BPS = 800
DEPRECIATION_PER_MONTH_BPS = 50
DEPRECIATION_CAP_BPS = 6000
DISPUTE_WINDOW_DAYS = 30


# ─── Calculation helpers (derive expected values exactly as the PRD pins) ────

def rhu(product: int, divisor: int = 10000) -> int:
    """Round half up for non-negative integers (PRD §2.6): augment the product
    by half the divisor, then floor-divide."""
    return (product + divisor // 2) // divisor


def condition_adjusted_value(raw_value_cents: int, grade: str) -> int:
    """Non-income valuation: raw x condition factor, rounded half up (§3.3)."""
    return rhu(raw_value_cents * CONDITION_FACTOR_BPS[grade])


def income_capitalized_value(annual_net_revenues_cents: List[int]) -> int:
    """INCOME_APPROACH: capitalize each year at 3,300 bps, round each year half
    up, THEN sum the three rounded products (§3.3 pinned rounding order)."""
    return sum(rhu(rev * CAPITALIZATION_BPS) for rev in annual_net_revenues_cents)


def auction_fee(gross_proceeds_cents: int) -> int:
    """Tiered marginal fee: 10% on the first 1,000,000 cents, 7% on the next
    4,000,000, 4% on the remainder; each bracket rounded half up (§3.6)."""
    b1 = min(gross_proceeds_cents, TIER1_CAP_CENTS)
    f1 = rhu(b1 * TIER1_BPS)
    rem1 = gross_proceeds_cents - b1
    b2 = min(rem1, TIER2_CAP_CENTS)
    f2 = rhu(b2 * TIER2_BPS)
    b3 = rem1 - b2
    f3 = rhu(b3 * TIER3_BPS)
    return f1 + f2 + f3


def projected_burden(asset_type: str, accumulated_net_holding_cost_cents: int) -> int:
    """accumulated + 3 months of carrying cost at the asset type's rate (§3.4)."""
    return (
        accumulated_net_holding_cost_cents
        + ISR_PROJECTION_MONTHS * MONTHLY_CARRYING_COST_CENTS[asset_type]
    )


def is_interlocutory_eligible(
    asset_type: str, accumulated_net_holding_cost_cents: int, appraised_value_cents: int
) -> bool:
    """Integer comparison, inclusive boundary: burden x 100 >= 30 x value (§3.4)."""
    return (
        projected_burden(asset_type, accumulated_net_holding_cost_cents) * 100
        >= INTERLOCUTORY_RATIO_THRESHOLD_PCT * appraised_value_cents
    )


def provisional_net_retention_value(
    asset_type: str, latest_submitted_adjusted_cents: Optional[int],
    latest_accepted_adjusted_cents: Optional[int],
    accumulated_net_holding_cost_cents: int,
) -> Optional[int]:
    """PROVISIONAL variant (§3.3): latest SUBMITTED base if any, else latest
    ACCEPTED; burden includes the six-month carrying-cost projection."""
    if latest_submitted_adjusted_cents is None and latest_accepted_adjusted_cents is None:
        return None
    base = (
        latest_submitted_adjusted_cents
        if latest_submitted_adjusted_cents is not None
        else latest_accepted_adjusted_cents
    )
    burden = (
        accumulated_net_holding_cost_cents
        + PROVISIONAL_PROJECTION_MONTHS * MONTHLY_CARRYING_COST_CENTS[asset_type]
    )
    return base - burden


def final_net_retention_value(
    latest_accepted_adjusted_cents: Optional[int],
    accumulated_net_holding_cost_cents: int,
) -> Optional[int]:
    """FINAL variant (§3.3): ACCEPTED base only, posted net costs only."""
    if latest_accepted_adjusted_cents is None:
        return None
    return latest_accepted_adjusted_cents - accumulated_net_holding_cost_cents


def full_months_held(seized_on: str, now: str) -> int:
    """Whole calendar months from seized_on to now (§3.8): year/month delta,
    minus one when the current day-of-month is earlier than the seizure day's."""
    seized = _parse_iso(seized_on)
    current = _parse_iso(now)
    months = (current.year - seized.year) * 12 + (current.month - seized.month)
    if current.day < seized.day:
        months -= 1
    return months


def expected_depreciation(
    appraised_value_cents: Optional[int],
    seizure_condition_grade: str,
    return_condition_grade: str,
    seized_on: str,
    now: str,
) -> int:
    """depreciation_on_return (§3.8): zero when never appraised; otherwise the
    grade-step plus months-held fraction of appraised value, capped at 60%."""
    if appraised_value_cents is None:
        return 0
    steps_down = max(
        0, GRADE_RANK[seizure_condition_grade] - GRADE_RANK[return_condition_grade]
    )
    months = full_months_held(seized_on, now)
    fraction_bps = min(
        DEPRECIATION_CAP_BPS,
        DEPRECIATION_PER_GRADE_STEP_BPS * steps_down
        + DEPRECIATION_PER_MONTH_BPS * months,
    )
    return rhu(appraised_value_cents * fraction_bps)


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ─── Canonical payload defaults (all timestamps >= the clock epoch) ──────────

TEST_DEFAULTS = {
    "SEIZED_ON": CLOCK_EPOCH,
    "WINDOW_START": "2026-09-01T08:00:00Z",
    "WINDOW_END": "2026-09-02T08:00:00Z",
    "SLOT_START": "2026-09-06T10:00:00Z",
    "SLOT_END": "2026-09-06T12:00:00Z",
    "JUDICIAL_DISTRICT": "S.D.N.Y.",
    "LEAD_AGENCY_CODE": "DEA",
    "AUCTIONEER_REF": "auc-default",
    "PAYEE_REF": "STATE-POLICE-01",
}

__all__ = [
    "CLOCK_EPOCH",
    "CLOCK_EPOCH_SYSTEM_STAMP",
    "CAPITALIZATION_BPS",
    "CONDITION_FACTOR_BPS",
    "PROVISIONAL_PROJECTION_MONTHS",
    "RETENTION_VALUE_FLOOR_CENTS",
    "MONTHLY_CARRYING_COST_CENTS",
    "ISR_PROJECTION_MONTHS",
    "INTERLOCUTORY_RATIO_THRESHOLD_PCT",
    "TIER1_CAP_CENTS",
    "TIER1_BPS",
    "TIER2_CAP_CENTS",
    "TIER2_BPS",
    "TIER3_BPS",
    "APPEAL_LIMIT",
    "EQUITABLE_SHARE_MIN_CENTS",
    "GRADE_RANK",
    "DEPRECIATION_PER_GRADE_STEP_BPS",
    "DEPRECIATION_PER_MONTH_BPS",
    "DEPRECIATION_CAP_BPS",
    "DISPUTE_WINDOW_DAYS",
    "rhu",
    "condition_adjusted_value",
    "income_capitalized_value",
    "auction_fee",
    "projected_burden",
    "is_interlocutory_eligible",
    "provisional_net_retention_value",
    "final_net_retention_value",
    "full_months_held",
    "expected_depreciation",
    "TEST_DEFAULTS",
]
