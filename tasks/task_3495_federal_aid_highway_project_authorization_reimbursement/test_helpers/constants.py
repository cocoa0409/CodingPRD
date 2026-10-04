"""Domain constants and pinned computation helpers (PRD §2.4, §2.6, §3.1-§3.9).

Every literal is copied verbatim from the PRD. This module is also the single
place where the test layer derives expected shares, federal fiscal years,
rounding, and logical-clock arithmetic so tests never re-derive them by hand.
"""
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------
CLOCK_START = "2026-09-01T00:00:00Z"

# Standard clock milestones used by fixtures (monotonically non-decreasing).
DATE_STIP_SUBMIT = "2026-10-02T00:00:00Z"      # CLOCK_START + 31 days
DATE_AUTHORIZE = "2026-10-15T00:00:00Z"        # October 2026 -> FFY 2027
DATE_OPEN_BIDS = "2026-11-06T00:00:00Z"        # DATE_AUTHORIZE + 22 days
DATE_AUDIT_FINALIZE = "2026-12-07T00:00:00Z"   # DATE_OPEN_BIDS + 31 days

# ---------------------------------------------------------------------------
# Duration windows (days) and counts (PRD §3.2, §3.4, §3.6, §3.9)
# ---------------------------------------------------------------------------
STIP_DURATION_YEARS = 4
STIP_COMMENT_PERIOD_DAYS = 30
MIN_PUBLIC_COMMENTS = 1
EIS_COMMENT_PERIOD_DAYS = 45
MIN_ADVERTISEMENT_DAYS = 21
AUDIT_FINDINGS_RESPONSE_DAYS = 30

# ---------------------------------------------------------------------------
# Funding programs and activity codes (PRD §3.1)
# ---------------------------------------------------------------------------
FUNDING_PROGRAM_CODES = ["NHPP", "STBG", "HSIP", "CMAQ", "TAP"]
ACTIVITY_CODES = [
    "ROAD_RESURFACING",
    "BRIDGE_REPLACEMENT",
    "SIGNAGE_LIGHTING",
    "GUARDRAIL_INSTALL",
    "PEDESTRIAN_CROSSING",
    "TRANSIT_EXPANSION",
]
BASE_FEDERAL_SHARE_BY_CODE = {
    "NHPP": 0.80,
    "STBG": 0.80,
    "HSIP": 0.90,
    "CMAQ": 0.80,
    "TAP": 0.80,
}

# ---------------------------------------------------------------------------
# Federal share determination constants (PRD §3.3)
# ---------------------------------------------------------------------------
INTERSTATE_SYSTEM_BUMP = 0.10
INTERSTATE_SHARE_CAP = 0.90
SAFETY_FULL_SHARE = 1.00
SAFETY_FULL_SHARE_ACTIVITIES = [
    "SIGNAGE_LIGHTING",
    "GUARDRAIL_INSTALL",
    "PEDESTRIAN_CROSSING",
]
FEDERAL_LAND_SLIDING_THRESHOLD = 0.05
FEDERAL_LAND_SHARE_CAP = 0.95

# ---------------------------------------------------------------------------
# Change orders (PRD §3.8)
# ---------------------------------------------------------------------------
OVERRUN_PARTICIPATION_CAP_PCT = 0.20

# ---------------------------------------------------------------------------
# Fixture defaults (test-layer choices, not PRD values)
# ---------------------------------------------------------------------------
DEFAULT_STATE_CODE = "CA"
DEFAULT_FFY = 2027                 # FFY containing DATE_AUTHORIZE
DEFAULT_STIP_START_FFY = 2027      # STIP spans 2027-2030
DEFAULT_APPORTIONED_CENTS = 5_000_000
DEFAULT_PROJECT_COST_CENTS = 1_500_000
DEFAULT_INITIAL_OBLIGATED_CENTS = 1_000_000
DEFAULT_DBE_GOAL_PCT = 0.10
DEFAULT_BID_AMOUNT_CENTS = 1_400_000
DEFAULT_AGREEMENT_NUMBER = "FA-0001"

# Voucher period defaults — client-supplied datetimes, half-open [start, end).
DEFAULT_PERIOD_START = "2027-01-01T00:00:00Z"
DEFAULT_PERIOD_END = "2027-02-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Rounding discipline (PRD §2.6): shares rounded half-up to 4 decimals;
# share x cents products rounded half-up to whole cents.
# ---------------------------------------------------------------------------
def round_half_up(value, places=0) -> Decimal:
    """Round a number half-up to `places` decimal places, as the PRD pins."""
    quant = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)


def share_times_cents(share, cents: int) -> int:
    """round_half_up(cents * share, 0) -> int cents (PRD §2.6)."""
    return int(round_half_up(Decimal(str(cents)) * Decimal(str(share)), 0))


def expected_provisional_share(program_code: str) -> float:
    """Statutory-base variant: exactly the program base share (PRD §3.3)."""
    return float(round_half_up(BASE_FEDERAL_SHARE_BY_CODE[program_code], 4))


def expected_determined_share(
    program_code: str,
    is_interstate_system: bool,
    activity_code: str,
    state_federal_land_pct: float,
) -> float:
    """Adjusted-full variant with the pinned branch order (PRD §3.3):
    interstate bump first, safety override second, land sliding scale third."""
    base = Decimal(str(BASE_FEDERAL_SHARE_BY_CODE[program_code]))
    if is_interstate_system:
        bumped = base + Decimal(str(INTERSTATE_SYSTEM_BUMP))
        base = min(Decimal(str(INTERSTATE_SHARE_CAP)), bumped)
    if program_code == "HSIP" and activity_code in SAFETY_FULL_SHARE_ACTIVITIES:
        share = Decimal(str(SAFETY_FULL_SHARE))
    else:
        land = Decimal(str(state_federal_land_pct))
        if land > Decimal(str(FEDERAL_LAND_SLIDING_THRESHOLD)):
            cap = Decimal(str(FEDERAL_LAND_SHARE_CAP))
            base = min(cap, base + (cap - base) * land)
        share = base
    return float(share.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def expected_provisional_estimate_cents(
    total_estimated_cost_cents: int, program_code: str
) -> int:
    """round_half_up(cost * provisional share) — feeds the fiscal check."""
    return share_times_cents(
        expected_provisional_share(program_code), total_estimated_cost_cents
    )


def expected_voucher_reimbursable(
    share,
    approved_line_amounts_cents,
    remaining_obligation_cents: int,
) -> int:
    """Per-line round_half_up, then sum, clamped to the remaining obligation
    (PRD §3.7 voucher reimbursement)."""
    per_line_sum = sum(share_times_cents(share, c) for c in approved_line_amounts_cents)
    return min(per_line_sum, remaining_obligation_cents)


def expected_change_order_participation(
    delta_cost_cents: int,
    federal_share_pct,
    initial_obligated_cents: int,
    cumulative_participation_cents: int = 0,
) -> int:
    """Cap-clamped change-order participation (PRD §3.8, steps 1-4)."""
    eligible = share_times_cents(federal_share_pct, delta_cost_cents)
    cap = share_times_cents(OVERRUN_PARTICIPATION_CAP_PCT, initial_obligated_cents)
    room = cap - cumulative_participation_cents
    return max(0, min(eligible, room))


def expected_final_eligible_share_cents(
    approved_eligible_total_cents: int, ineligible_amount_cents: int, federal_share_pct
) -> int:
    """Audit finalize: max(0, round_half_up((eligible - ineligible) * share))
    (PRD §3.9)."""
    diff = approved_eligible_total_cents - ineligible_amount_cents
    if diff <= 0:
        return 0
    return share_times_cents(federal_share_pct, diff)


def expected_repayment_due_cents(
    reimbursed_cents: int, final_eligible_federal_share_cents: int
) -> int:
    """max(0, reimbursed - final_eligible) (PRD §3.9)."""
    return max(0, reimbursed_cents - final_eligible_federal_share_cents)


# ---------------------------------------------------------------------------
# Clock / calendar helpers
# ---------------------------------------------------------------------------
def _parse_iso(iso_ts: str) -> datetime:
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


def _render_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def federal_fiscal_year(iso_ts: str) -> int:
    """FFY rule (PRD §2.4): Oct-Dec of year Y -> FFY Y+1; Jan-Sep of Y -> FFY Y."""
    dt = _parse_iso(iso_ts)
    return dt.year + 1 if dt.month >= 10 else dt.year


def iso_plus_days(iso_ts: str, days: int) -> str:
    """Return the clock string `days` after `iso_ts` (fraction-free rendering)."""
    return _render_iso(_parse_iso(iso_ts) + timedelta(days=days))


def max_iso(a: str, b: str) -> str:
    """Later of two ISO-8601 UTC clock strings (lexicographic == chronological
    for the fraction-free Z format used by the logical clock)."""
    return a if a >= b else b
