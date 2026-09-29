"""Domain constants and pure arithmetic helpers for the presort bureau API.

Every constant here is transcribed from the specification: mail-class base
rates, presort tier discounts and thresholds, container minimums, zone and
service-day derivation, verification severity thresholds, invoice fee tiers,
and the two rounding modes (floor for per-piece rates, round-half-up for
everything else).

The helpers are deliberately literal re-statements of the specified formulas so
that a test can express an expectation as either a pre-computed literal or a
formula application, whichever reads more clearly.
"""

from decimal import Decimal, ROUND_HALF_UP

# ─── Roles ────────────────────────────────────────────────────────────────

ROLE_CLIENT_CONTACT = "ClientContact"
ROLE_PRESORT_OPERATOR = "PresortOperator"
ROLE_POSTAGE_MANAGER = "PostageManager"
ROLE_ACCEPTANCE_CLERK = "AcceptanceClerk"
ROLE_BUREAU_ADMIN = "BureauAdmin"

ALL_ROLES = [
    ROLE_CLIENT_CONTACT,
    ROLE_PRESORT_OPERATOR,
    ROLE_POSTAGE_MANAGER,
    ROLE_ACCEPTANCE_CLERK,
    ROLE_BUREAU_ADMIN,
]

# ─── Logical clock ────────────────────────────────────────────────────────

# The clock reads exactly this instant before it has ever been set.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# The instant every canonical fixture chain starts from.
FIXTURE_CLOCK_UTC = "2026-08-10T09:00:00.000Z"

# ─── Enumerations ─────────────────────────────────────────────────────────

BILLING_TERMS = ["NET_15", "NET_30"]
DEFAULT_BILLING_TERMS = "NET_30"
DEFAULT_COMMINGLE_OPT_IN = True

CLIENT_STATUSES = ["ACTIVE", "SUSPENDED"]
PERMIT_ACCOUNT_STATUSES = ["ACTIVE", "HOLD", "CLOSED"]
PAYMENT_METHODS = ["PERMIT_IMPRINT", "METER", "PRECANCELED_STAMP"]
FACILITY_TYPES = ["DDU", "SCF", "NDC"]
FACILITY_STATUSES = ["OPEN", "CLOSED"]
MAIL_CLASSES = ["FIRST_CLASS", "MARKETING_MAIL", "PERIODICALS"]
PROCESSING_CATEGORIES = ["LETTERS", "FLATS"]
MAIL_JOB_STATUSES = [
    "RECEIVED",
    "HYGIENE_CLEARED",
    "POOLED",
    "PRESORTED",
    "REWORK",
    "MAILED",
    "BILLED",
    "CANCELLED",
]
BATCH_STATUSES = ["OPEN", "SORTED", "DOCUMENTED", "REWORK", "CLOSED"]
CONTAINER_TYPES = ["TRAY", "PALLET"]
SORT_LEVELS = ["MIXED_ADC", "ADC", "THREE_DIGIT", "FIVE_DIGIT"]
CONTAINER_STATUSES = ["STAGED", "DOCUMENTED", "RETURNED", "DEPOSITED"]
SHIPMENT_STATUSES = ["SCHEDULED", "IN_TRANSIT", "DEPOSITED", "CANCELLED", "NO_SHOW"]
STATEMENT_STATUSES = [
    "DRAFT",
    "SUBMITTED",
    "ACCEPTED_CLEAN",
    "ACCEPTED_WITH_ADJUSTMENT",
    "RETURNED_FOR_CORRECTION",
    "VOID",
]
FINDING_TYPES = [
    "SHORT_PAID",
    "BAD_ADDRESS_QUALITY",
    "CONTAINER_NOT_QUALIFIED",
    "MOVE_UPDATE_STALE",
    "DOC_MISMATCH",
]
FINDING_SEVERITIES = ["MINOR", "MAJOR"]
INVOICE_STATUSES = ["ISSUED", "PAID"]
PRESORT_TIERS = ["NONE", "BASIC", "THREE_DIGIT", "FIVE_DIGIT"]
VERIFY_OUTCOMES = ["ACCEPT", "RETURN"]

# Fixed reason strings the server itself writes.
SUSPENSION_REASON_REPEATED_REWORK = "REPEATED_PRESORT_REWORK"
VOID_REASON_SUPERSEDED = "SUPERSEDED_BY_NEWER_STATEMENT"

# ─── Presort tier qualification ───────────────────────────────────────────

TIER_MIN_PIECES = {"BASIC": 500, "THREE_DIGIT": 3000, "FIVE_DIGIT": 15000}

# ─── Postage rate and batch postage ───────────────────────────────────────

BASE_RATE_CENTS_PER_PIECE = {
    "FIRST_CLASS": 64,
    "MARKETING_MAIL": 32,
    "PERIODICALS": 28,
}
TIER_DISCOUNT_BP = {"NONE": 0, "BASIC": 800, "THREE_DIGIT": 1500, "FIVE_DIGIT": 2200}
BP_DENOMINATOR = 10000
MILLS_PER_CENT = 1000

# ─── Address hygiene ──────────────────────────────────────────────────────

MOVE_UPDATE_MAX_AGE_DAYS = 95
MIN_ADDRESS_QUALITY_PCT = 95.00

# ─── Container qualification ──────────────────────────────────────────────

TRAY_MIN_PIECES_DEEP = 150
TRAY_MIN_PIECES_SHALLOW = 1
PALLET_MIN_PIECES = 250
DEEP_SORT_LEVELS = ["THREE_DIGIT", "FIVE_DIGIT"]
SHALLOW_SORT_LEVELS = ["ADC", "MIXED_ADC"]

# ─── Zone, base days and class day adder ──────────────────────────────────

SERVED_ZONE_BY_FACILITY_TYPE = {"DDU": 1, "SCF": 2, "NDC": 4}
SERVED_BASE_DAYS_BY_FACILITY_TYPE = {"DDU": 1, "SCF": 2, "NDC": 3}
UNSERVED_ZONE = 8
UNSERVED_BASE_DAYS = 5
CLASS_DAY_ADDER = {"FIRST_CLASS": 0, "MARKETING_MAIL": 2, "PERIODICALS": 1}
ZONE_WEIGHT = {1: 1, 2: 2, 4: 3, 8: 5}

# ─── Verification findings ────────────────────────────────────────────────

MAJOR_THRESHOLD_BP = 500
SEVERITY_SURCHARGE_BP = {"MINOR": 2500, "MAJOR": 10000}
SURCHARGE_DIVISOR = 10_000_000

# ─── Invoicing ────────────────────────────────────────────────────────────

MIN_SERVICE_FEE_CENTS = 2500
# (min_billed_pieces, discount_bp); highest satisfied minimum wins.
VOLUME_DISCOUNT_TIERS = [(0, 0), (5000, 500), (25000, 1200)]

# ─── Pagination ───────────────────────────────────────────────────────────

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
MIN_OFFSET = 0

# ─── Common-field shapes ──────────────────────────────────────────────────

# Resources that carry the full identity set.
FULL_COMMON_FIELDS = ("id", "created_at", "updated_at", "version")
# The two append-only history records carry only these two.
APPEND_ONLY_COMMON_FIELDS = ("id", "created_at")
APPEND_ONLY_ENTITIES = ("AddressHygieneRun", "VerificationFinding")


# ─── Rounding primitives ──────────────────────────────────────────────────


def round_half_up(value, places: int = 0):
    """Round half up to ``places`` decimals; a value on the halfway mark goes
    away from zero to the larger magnitude."""
    quantum = Decimal(1).scaleb(-places)
    result = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    return int(result) if places == 0 else float(result)


def floor_div(numerator: int, denominator: int) -> int:
    """Integer floor of an exact rational."""
    return numerator // denominator


# ─── Derived-figure helpers ───────────────────────────────────────────────


def expected_tier(total_piece_count: int) -> str:
    """The presort tier a pooled volume qualifies for; thresholds inclusive."""
    if total_piece_count >= TIER_MIN_PIECES["FIVE_DIGIT"]:
        return "FIVE_DIGIT"
    if total_piece_count >= TIER_MIN_PIECES["THREE_DIGIT"]:
        return "THREE_DIGIT"
    if total_piece_count >= TIER_MIN_PIECES["BASIC"]:
        return "BASIC"
    return "NONE"


def expected_rate_mills(mail_class: str, tier: str, drop_ship_discount_bp: int) -> int:
    """base_cents * 1000 * (10000 - tier_bp) * (10000 - ship_bp) / 1e8, floored
    exactly once at the very end."""
    numerator = (
        BASE_RATE_CENTS_PER_PIECE[mail_class]
        * MILLS_PER_CENT
        * (BP_DENOMINATOR - TIER_DISCOUNT_BP[tier])
        * (BP_DENOMINATOR - drop_ship_discount_bp)
    )
    return floor_div(numerator, BP_DENOMINATOR * BP_DENOMINATOR)


def expected_batch_postage_cents(total_piece_count: int, rate_mills: int) -> int:
    """Mills converted to cents exactly once over the whole pooled volume."""
    return round_half_up(Decimal(total_piece_count * rate_mills) / MILLS_PER_CENT)


def expected_standalone_estimate(mail_class: str, piece_count: int) -> dict:
    """The standalone estimate prices one job's own accepted pieces with the
    drop-ship discount forced to zero."""
    tier = expected_tier(piece_count)
    rate = expected_rate_mills(mail_class, tier, 0)
    return {
        "piece_count": piece_count,
        "standalone_tier": tier,
        "standalone_rate_mills_per_piece": rate,
        "standalone_postage_cents": expected_batch_postage_cents(piece_count, rate),
    }


def expected_pro_rata(pool_cents: int, contributions) -> list:
    """Floor-plus-remainder split of a pool of whole cents.

    ``contributions`` is an ordered sequence of (key, contributed_piece_count)
    in ``created_at`` ascending order. Returns [(key, allocated_cents), ...] in
    that same input order. Remainder cents go to members ordered by
    contributed_piece_count descending then created_at ascending.
    """
    denominator = sum(c for _, c in contributions)
    floors = {k: floor_div(pool_cents * c, denominator) for k, c in contributions}
    remainder = pool_cents - sum(floors.values())
    ordering = sorted(
        enumerate(contributions), key=lambda pair: (-pair[1][1], pair[0])
    )
    for _, (key, _c) in ordering[:remainder]:
        floors[key] += 1
    return [(k, floors[k]) for k, _ in contributions]


def expected_share_basis_pct(contributed: int, denominator: int) -> float:
    """contributed * 100 / denominator, round half up to four decimals."""
    return round_half_up(Decimal(contributed * 100) / Decimal(denominator), 4)


def expected_address_quality_pct(cass_matched: int, submitted: int) -> float:
    """cass_matched * 100 / submitted, round half up to two decimals."""
    return round_half_up(Decimal(cass_matched * 100) / Decimal(submitted), 2)


def expected_container_qualifies(container_type: str, sort_level: str, piece_count: int) -> bool:
    """Inclusive minimum by container type and sortation depth."""
    if container_type == "PALLET":
        minimum = PALLET_MIN_PIECES
    elif sort_level in DEEP_SORT_LEVELS:
        minimum = TRAY_MIN_PIECES_DEEP
    else:
        minimum = TRAY_MIN_PIECES_SHALLOW
    return piece_count >= minimum


def expected_zone_and_days(
    facility_type: str, served_zip3_list, destination_zip3: str, mail_class: str
) -> tuple:
    """(zone, committed_days) from exact string membership in the served list."""
    if destination_zip3 in served_zip3_list:
        zone = SERVED_ZONE_BY_FACILITY_TYPE[facility_type]
        base_days = SERVED_BASE_DAYS_BY_FACILITY_TYPE[facility_type]
    else:
        zone = UNSERVED_ZONE
        base_days = UNSERVED_BASE_DAYS
    return zone, base_days + CLASS_DAY_ADDER[mail_class]


def expected_placard_id(facility_code: str, destination_zip3: str, sequence_index: int) -> str:
    """<facility_code>-<destination_zip3>-<sequence_index>."""
    return f"{facility_code}-{destination_zip3}-{sequence_index}"


def expected_finding_severity(cumulative_affected: int, statement_piece_count: int) -> str:
    """MAJOR once the cumulative affected count reaches the major threshold."""
    if cumulative_affected * BP_DENOMINATOR >= statement_piece_count * MAJOR_THRESHOLD_BP:
        return "MAJOR"
    return "MINOR"


def expected_surcharge_cents(affected: int, rate_mills: int, severity: str) -> int:
    """affected * rate_mills * severity_bp / 10_000_000, round half up."""
    numerator = affected * rate_mills * SEVERITY_SURCHARGE_BP[severity]
    return round_half_up(Decimal(numerator) / SURCHARGE_DIVISOR)


def expected_volume_discount_bp(billed_piece_count: int) -> int:
    """Highest satisfied volume threshold wins."""
    discount = 0
    for minimum, bp in VOLUME_DISCOUNT_TIERS:
        if billed_piece_count >= minimum:
            discount = bp
    return discount


def expected_service_fee_cents(billed_piece_count: int, rate_per_thousand_cents: int) -> int:
    """Ceiling on thousands first, discount factor next, minimum floor last."""
    thousands = -(-billed_piece_count // 1000)
    gross = thousands * rate_per_thousand_cents
    discount_bp = expected_volume_discount_bp(billed_piece_count)
    discounted = round_half_up(
        Decimal(gross * (BP_DENOMINATOR - discount_bp)) / BP_DENOMINATOR
    )
    return max(MIN_SERVICE_FEE_CENTS, discounted)


def expected_weighted_index(pairs) -> float:
    """pairs is a sequence of (weight, on_time); returns the round-half-up
    two-decimal percentage of on-time weight, or None on an empty population."""
    denominator = sum(w for w, _ in pairs)
    if denominator == 0:
        return None
    numerator = sum(w for w, on_time in pairs if on_time)
    return round_half_up(Decimal(numerator * 100) / Decimal(denominator), 2)
