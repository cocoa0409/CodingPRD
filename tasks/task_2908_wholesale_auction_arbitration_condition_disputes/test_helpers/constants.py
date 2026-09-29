"""Domain thresholds, rates and pure arithmetic helpers taken from the PRD."""
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

# --- The logical clock ---------------------------------------------------------
# "Before any caller sets it, the logical clock reads exactly its startup default
#  of 2026-08-01T00:00:00Z".  All datetimes crossing the API carry exactly three
#  fractional-second digits.
CLOCK_DEFAULT = "2026-08-01T00:00:00.000Z"

# --- Post-sale inspection ------------------------------------------------------
PSI_FEE_CENTS = {"STANDARD": 12500, "PREMIUM": 27500}
PSI_WINDOW_HOURS = 72

# --- Negotiation ---------------------------------------------------------------
ROUND_RESPONSE_HOURS = 48
ROUND_COOLDOWN_HOURS = 2
MAX_NEGOTIATION_ROUNDS = 3
DEFAULT_SELLER_RESPONSE_HOURS = 24
INTAKE_GRACE_HOURS = 48

# --- Transport cost bands ------------------------------------------------------
TRANSPORT_DISPATCH_FEE_CENTS = 8500
TRANSPORT_BAND1_MILES = 100
TRANSPORT_BAND1_RATE = 185
TRANSPORT_BAND2_MILES = 400
TRANSPORT_BAND2_RATE = 155
TRANSPORT_BAND3_RATE = 130

# --- Transport allocation profiles: (buyer_bps, seller_bps) --------------------
ALLOCATION_PROFILES = {
    ("UNWIND", "SELLER"): (0, 10000),
    ("UNWIND", "BUYER"): (10000, 0),
    ("UNWIND", "NONE"): (5000, 5000),
    ("REPAIR_ALLOWANCE", "SELLER"): (2000, 7000),
    ("REPAIR_ALLOWANCE", "BUYER"): (2000, 7000),
    ("REPAIR_ALLOWANCE", "NONE"): (2000, 7000),
    ("CLAIM_DENIED", "SELLER"): (10000, 0),
    ("CLAIM_DENIED", "BUYER"): (10000, 0),
    ("CLAIM_DENIED", "NONE"): (10000, 0),
    ("FRIVOLOUS_DENIED", "SELLER"): (10000, 0),
    ("FRIVOLOUS_DENIED", "BUYER"): (10000, 0),
    ("FRIVOLOUS_DENIED", "NONE"): (10000, 0),
}

# --- Award formula -------------------------------------------------------------
SEVERITY_MULTIPLIER_BPS = {"GREEN": 10000, "YELLOW": 8500, "RED": 6000}
MILEAGE_RATE_CENTS_PER_MILE = 45

# --- Frivolous fee ladder ------------------------------------------------------
FRIVOLOUS_FEE_BASE_CENTS = 25000
FRIVOLOUS_FEE_CAP_CENTS = 60000
FRIVOLOUS_SUSPENSION_COUNT = 3

# --- Seller scorecard ----------------------------------------------------------
ROLLING_WINDOW_DAYS = 90
MIN_SCORECARD_SALES = 4
TIER_WATCH_BPS = 800
TIER_PROBATION_BPS = 1500
TIER_BLOCK_BPS = 2500

BPS_WHOLE = 10000

# --- Operator identities (opaque roles) ---------------------------------------
ADMIN_USER_ID = "admin-01"
CLERK_USER_ID = "clerk-01"
ARB_INTAKE_USER_ID = "arb-intake-01"
ARB_DECIDE_USER_ID = "arb-decide-02"
INSPECTOR_USER_ID = "insp-01"

# --- Canonical policy presets used across the suite ---------------------------
MECHANICAL_POLICY = {
    "defect_class": "MECHANICAL",
    "window_hours": 48,
    "mileage_limit": 250,
    "min_claim_amount_cents": 60000,
    "requires_third_party_verification": False,
    "max_allowance_bps": 2000,
    "psi_extension_hours": 96,
    "psi_clean_waives_rights": True,
}

FRAME_DAMAGE_POLICY = {
    "defect_class": "FRAME_DAMAGE",
    "window_hours": 168,
    "mileage_limit": 1000,
    "min_claim_amount_cents": 50000,
    "requires_third_party_verification": True,
    "max_allowance_bps": 3000,
    "psi_extension_hours": 72,
    "psi_clean_waives_rights": False,
}

# window_hours / mileage_limit omitted => unlimited on both axes
TITLE_BRANDED_POLICY = {
    "defect_class": "TITLE_BRANDED",
    "min_claim_amount_cents": 0,
    "requires_third_party_verification": True,
    "max_allowance_bps": 0,
    "psi_extension_hours": 0,
    "psi_clean_waives_rights": False,
}

TITLE_MISSING_POLICY = {
    "defect_class": "TITLE_MISSING",
    "min_claim_amount_cents": 0,
    "requires_third_party_verification": False,
    "max_allowance_bps": 0,
    "psi_extension_hours": 0,
    "psi_clean_waives_rights": False,
}

MILEAGE_POLICY = {
    "defect_class": "MILEAGE_DISCREPANCY",
    "window_hours": 720,
    "mileage_limit": 500,
    "min_claim_amount_cents": 0,
    "requires_third_party_verification": False,
    "max_allowance_bps": 5000,
    "psi_extension_hours": 24,
    "psi_clean_waives_rights": False,
}

TEST_DEFAULTS = {
    "SALE_PRICE_CENTS": 1450000,
    "ANNOUNCED_ODOMETER_MILES": 84000,
    "HAMMER_TIME_UTC": CLOCK_DEFAULT,
    "SELLER_NAME": "Ridgeline Motors",
    "BUYER_NAME": "Harbor Auto Group",
    "SELLER_LICENSE": "SL-1001",
    "BUYER_LICENSE": "BL-2001",
}


# --- Pure arithmetic helpers ---------------------------------------------------


def round_half_up(value) -> int:
    """Round to a whole number, halves away from zero, as the PRD requires."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def bps_of(amount: int, bps: int) -> int:
    """amount * bps / 10000 rounded half up to whole cents."""
    return round_half_up(Decimal(amount) * Decimal(bps) / Decimal(BPS_WHOLE))


def leg_cost_cents(miles: int) -> int:
    """Dispatch fee plus the three marginal distance bands."""
    band1 = min(miles, TRANSPORT_BAND1_MILES)
    band2 = min(max(miles - TRANSPORT_BAND1_MILES, 0), TRANSPORT_BAND2_MILES)
    band3 = max(miles - (TRANSPORT_BAND1_MILES + TRANSPORT_BAND2_MILES), 0)
    return (
        TRANSPORT_DISPATCH_FEE_CENTS
        + TRANSPORT_BAND1_RATE * band1
        + TRANSPORT_BAND2_RATE * band2
        + TRANSPORT_BAND3_RATE * band3
    )


def allocate_transport(miles_list, outcome: str, fault_party: str) -> dict:
    """Per-leg rounding then summation, exactly as the PRD specifies."""
    buyer_bps, seller_bps = ALLOCATION_PROFILES[(outcome, fault_party)]
    total = buyer_share = seller_share = auction_share = 0
    for miles in miles_list:
        cost = leg_cost_cents(miles)
        b = bps_of(cost, buyer_bps)
        s = bps_of(cost, seller_bps)
        total += cost
        buyer_share += b
        seller_share += s
        auction_share += cost - b - s
    return {
        "transport_total_cents": total,
        "transport_buyer_share_cents": buyer_share,
        "transport_seller_share_cents": seller_share,
        "transport_auction_share_cents": auction_share,
    }


def allowance_cap_cents(sale_price_cents: int, max_allowance_bps: int) -> int:
    return bps_of(sale_price_cents, max_allowance_bps)


def frivolous_fee_cents(prior_frivolous_count: int) -> int:
    return min(
        FRIVOLOUS_FEE_BASE_CENTS * (1 + prior_frivolous_count),
        FRIVOLOUS_FEE_CAP_CENTS,
    )


# --- Instant helpers ----------------------------------------------------------


def parse_instant(value: str) -> datetime:
    """Parse any ISO 8601 UTC instant the service may emit or accept."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def iso(dt: datetime) -> str:
    """Render an instant in the PRD's canonical three-fractional-digit form."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def shift(instant: str, hours: float = 0, seconds: float = 0, days: float = 0) -> str:
    """Return `instant` moved by the supplied offset, in canonical form."""
    return iso(parse_instant(instant) + timedelta(hours=hours, seconds=seconds, days=days))


def instants_equal(actual, expected) -> bool:
    """Compare two instants by value, tolerating fractional-digit width."""
    if actual is None or expected is None:
        return actual is expected or actual == expected
    return parse_instant(actual) == parse_instant(expected)
