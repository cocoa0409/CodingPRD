"""Every calculation rule of the specification, in exact integer arithmetic.

No float ever touches a money figure: rates are integer mills, money is integer
cents, and the percentage figures are Decimals quantized exactly once.
"""

from decimal import Decimal

from util import quantize, round_half_up_div

# --------------------------------------------------------------- constants ---
TIER_MIN_PIECES = (("FIVE_DIGIT", 15000), ("THREE_DIGIT", 3000), ("BASIC", 500))
TIER_DISCOUNT_BP = {"NONE": 0, "BASIC": 800, "THREE_DIGIT": 1500, "FIVE_DIGIT": 2200}
BASE_RATE_CENTS_PER_PIECE = {"FIRST_CLASS": 64, "MARKETING_MAIL": 32, "PERIODICALS": 28}

MOVE_UPDATE_MAX_AGE_DAYS = 95
MIN_ADDRESS_QUALITY_PCT = Decimal("95.00")

TRAY_MIN_PIECES_DEEP = 150
TRAY_MIN_PIECES_SHALLOW = 1
PALLET_MIN_PIECES = 250

CLASS_DAY_ADDER = {"FIRST_CLASS": 0, "MARKETING_MAIL": 2, "PERIODICALS": 1}
FACILITY_ZONE_DAYS = {"DDU": (1, 1), "SCF": (2, 2), "NDC": (4, 3)}
UNSERVED_ZONE_DAYS = (8, 5)

MAJOR_THRESHOLD_BP = 500
SEVERITY_SURCHARGE_BP = {"MINOR": 2500, "MAJOR": 10000}

ZONE_WEIGHT = {1: 1, 2: 2, 4: 3, 8: 5}

MIN_SERVICE_FEE_CENTS = 2500
VOLUME_DISCOUNT_TIERS = ((25000, 1200), (5000, 500), (0, 0))

REWORK_SUSPEND_THRESHOLD = 2
REWORK_SUSPENSION_REASON = "REPEATED_PRESORT_REWORK"
SUPERSEDED_VOID_REASON = "SUPERSEDED_BY_NEWER_STATEMENT"


# ------------------------------------------- presort_tier_qualification ---

def presort_tier(piece_count):
    for name, minimum in TIER_MIN_PIECES:
        if piece_count >= minimum:
            return name
    return "NONE"


# ---------------------------------------- commingled_postage_assessment ---

def rate_mills(mail_class, tier, ship_bp):
    """floor(base * 1000 * (10000 - tier_bp) * (10000 - ship_bp) / 100000000).

    The whole numerator is exact integer arithmetic and is floored exactly once.
    """
    base = BASE_RATE_CENTS_PER_PIECE[mail_class]
    tier_bp = TIER_DISCOUNT_BP[tier]
    numerator = base * 1000 * (10000 - tier_bp) * (10000 - ship_bp)
    return numerator // 100000000


def postage_cents(piece_count, rate):
    """Mills -> cents exactly once, over the whole piece count, round half up."""
    return round_half_up_div(piece_count * rate, 1000)


def assess_postage(mail_class, piece_count, ship_bp):
    """Returns (tier, rate_mills_per_piece, postage_cents)."""
    tier = presort_tier(piece_count)
    rate = rate_mills(mail_class, tier, ship_bp)
    return tier, rate, postage_cents(piece_count, rate)


# ------------------------------------------------ pro_rata_cost_allocation ---

def allocate_pool(members, pool_cents):
    """Floor-plus-remainder split of `pool_cents` over attached members.

    `members` is a list of (key, contributed_piece_count, created_seq) tuples.
    Returns {key: allocated_cents}; the allocations sum to pool_cents exactly.
    """
    if not members:
        return {}
    denominator = sum(item[1] for item in members)
    if denominator <= 0:
        return {item[0]: 0 for item in members}
    floors = {}
    for key, contributed, _seq in members:
        floors[key] = (pool_cents * contributed) // denominator
    remainder = pool_cents - sum(floors.values())
    order = sorted(members, key=lambda item: (-item[1], item[2]))
    for item in order[: max(remainder, 0)]:
        floors[item[0]] += 1
    return floors


def share_basis_pct(contributed, denominator):
    """contributed * 100 / denominator, round half up to four decimals."""
    if denominator <= 0:
        return None
    return quantize(contributed * 100, denominator, 4)


# ----------------------------------------------- address_hygiene_metrics ---

def address_quality_pct(cass_matched_count, submitted_piece_count):
    return quantize(cass_matched_count * 100, submitted_piece_count, 2)


def move_update_compliant(move_update_age_days):
    return move_update_age_days <= MOVE_UPDATE_MAX_AGE_DAYS


# --------------------------------------------------- container_qualification ---

def container_min_pieces(container_type, sort_level):
    if container_type == "PALLET":
        return PALLET_MIN_PIECES
    if sort_level in ("THREE_DIGIT", "FIVE_DIGIT"):
        return TRAY_MIN_PIECES_DEEP
    return TRAY_MIN_PIECES_SHALLOW


def container_qualifies(container_type, sort_level, piece_count):
    return piece_count >= container_min_pieces(container_type, sort_level)


# ------------------------------------------- zone_and_service_commitment ---

def zone_and_days(facility, destination_zip3, mail_class):
    if destination_zip3 in facility["served_zip3_list"]:
        zone, base_days = FACILITY_ZONE_DAYS[facility["facility_type"]]
    else:
        zone, base_days = UNSERVED_ZONE_DAYS
    return zone, base_days + CLASS_DAY_ADDER[mail_class]


# ------------------------------------------------- verification_adjustment ---

def walk_findings(findings, statement_piece_count, rate):
    """Cumulative, order-sensitive severity + per-finding surcharge.

    `findings` must already be in created_at ascending order. Returns a list of
    (severity, surcharge_cents) aligned with the input order.
    """
    results = []
    cumulative = 0
    for finding in findings:
        cumulative += finding["affected_piece_count"]
        if cumulative * 10000 >= statement_piece_count * MAJOR_THRESHOLD_BP:
            severity = "MAJOR"
        else:
            severity = "MINOR"
        bp = SEVERITY_SURCHARGE_BP[severity]
        surcharge = round_half_up_div(
            finding["affected_piece_count"] * rate * bp, 10000000
        )
        results.append((severity, surcharge))
    return results


# ------------------------------------------------ client_service_level_index ---

def service_level_indexes(records):
    """Returns (zone_weighted_index, piece_weighted_index, count, on_time_count)."""
    if not records:
        return None, None, 0, 0
    zone_num = 0
    zone_den = 0
    piece_num = 0
    piece_den = 0
    on_time_count = 0
    for record in records:
        weight = ZONE_WEIGHT[record["zone"]]
        zone_den += weight
        piece_den += record["piece_count"]
        if record["on_time"]:
            zone_num += weight
            piece_num += record["piece_count"]
            on_time_count += 1
    zone_index = quantize(zone_num * 100, zone_den, 2) if zone_den else None
    piece_index = quantize(piece_num * 100, piece_den, 2) if piece_den else None
    return zone_index, piece_index, len(records), on_time_count


# --------------------------------------------------- client_invoice_charges ---

def volume_discount_bp(billed_piece_count):
    for minimum, discount in VOLUME_DISCOUNT_TIERS:
        if billed_piece_count >= minimum:
            return discount
    return 0


def service_fee_cents(billed_piece_count, rate_per_thousand_cents):
    thousands = -(-billed_piece_count // 1000)  # ceiling over integers
    discount_bp = volume_discount_bp(billed_piece_count)
    gross = thousands * rate_per_thousand_cents
    discounted = round_half_up_div(gross * (10000 - discount_bp), 10000)
    return max(MIN_SERVICE_FEE_CENTS, discounted)
