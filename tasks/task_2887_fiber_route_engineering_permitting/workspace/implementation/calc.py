"""Constants and calculations.

All money is an integer count of cents, all ratios integer basis points and all
permitting complexity integer centipoints.  No float ever participates: every
division below is exact integer arithmetic with an explicit half-up rounding
step, so the rounding sites -- and their position in the evaluation order --
are exactly where the PRD pins them.
"""

# ---------------------------------------------------------------------------
# enumerations
# ---------------------------------------------------------------------------

TOPOLOGY_OBJECTIVES = ("RING_CLOSURE", "SPUR", "EXPRESS_BACKBONE")
ROUTE_STATUSES = ("PLANNING", "SCOPE_LOCKED", "PERMITTING", "CONSTRUCTION_READY", "RECORDS_UPDATED")

TERRAIN_CLASSES = (
    "URBAN_PAVED", "URBAN_UNPAVED", "RURAL_SHOULDER",
    "RAIL_CROSSING", "HIGHWAY_CROSSING", "WATER_CROSSING",
)
CONSTRUCTION_METHODS = ("AERIAL", "DIRECTIONAL_BORE", "TRENCH")
ENGINEERING_STATUSES = ("DRAFT", "WALKED", "METHOD_SELECTED", "DESIGN_LOCKED")
PERMIT_DIMENSION_STATUSES = ("NOT_REQUIRED", "PENDING", "CLEARED", "BLOCKED")
AUTHORITY_TYPES = ("MUNICIPAL_ROW", "RAILROAD", "STATE_HIGHWAY", "WATERWAY")

WALKOUT_STATUSES = ("OPEN", "SUBMITTED", "ACCEPTED", "REJECTED")
WALKOUT_DECISIONS = ("ACCEPTED", "REJECTED")
POLE_OWNERS = ("ELECTRIC_UTILITY", "TELCO", "MUNICIPAL_LIGHT")
CONDITION_GRADES = ("A", "B", "C", "D")
GRADE_SEVERITY = {"NONE": 0, "A": 1, "B": 2, "C": 3, "D": 4}

POLE_APP_STATUSES = (
    "DRAFT", "SUBMITTED", "REVISION_REQUESTED", "MAKE_READY_ESTIMATED",
    "GRANTED", "DENIED", "WITHDRAWN",
)
OWNER_OUTCOMES = ("ESTIMATED", "REVISION_REQUESTED", "DENIED")
WORK_CLASSES = ("TRANSFER", "POLE_REPLACEMENT", "GUYING", "RISER", "CLEARANCE_TRIM")

PERMIT_STATUSES = ("DRAFT", "UNDER_REVIEW", "REVISION_REQUESTED", "APPROVED", "DENIED")
PERMIT_DECISIONS = ("APPROVED", "REVISION_REQUESTED", "DENIED")

MORATORIUM_CLASSES_INPUT = ("NO_OPEN_CUT", "FULL_RESTORATION")
MORATORIUM_CLASSES = ("NONE", "NO_OPEN_CUT", "FULL_RESTORATION")
MORATORIUM_SEVERITY = {"FULL_RESTORATION": 2, "NO_OPEN_CUT": 1, "NONE": 0}

DESIGN_STATUSES = ("DRAFT", "IN_REVIEW", "STAMPED", "SUPERSEDED")
ENCLOSURE_TYPES = ("HANDHOLE", "AERIAL_SNOWSHOE", "CABINET")
SPLICE_STATUSES = ("PLACED", "VOIDED")
AS_BUILT_STATUSES = ("SUBMITTED", "ACCEPTED", "REJECTED")
AS_BUILT_DECISIONS = ("ACCEPTED", "REJECTED")

FIBER_COUNTS_ALLOWED = (48, 96, 144, 240, 288, 432)

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

AUTHORITY_BY_TERRAIN = {
    "URBAN_PAVED": "MUNICIPAL_ROW",
    "URBAN_UNPAVED": "MUNICIPAL_ROW",
    "RURAL_SHOULDER": "MUNICIPAL_ROW",
    "HIGHWAY_CROSSING": "STATE_HIGHWAY",
    "RAIL_CROSSING": "RAILROAD",
    "WATER_CROSSING": "WATERWAY",
}

AUTHORITY_WEIGHT = {"MUNICIPAL_ROW": 10, "STATE_HIGHWAY": 25, "RAILROAD": 40, "WATERWAY": 50}

STATUS_FACTOR_BP = {
    "UNDER_REVIEW": 10000,
    "REVISION_REQUESTED": 15000,
    "APPROVED": 2500,
    "DENIED": 20000,
}
LIVE_INDEX_STATUSES = ("UNDER_REVIEW", "REVISION_REQUESTED", "APPROVED", "DENIED")

METHOD_BASE_RATE_CENTS_PER_FOOT = {"AERIAL": 1237, "DIRECTIONAL_BORE": 4615, "TRENCH": 2845}

TERRAIN_MULTIPLIER_BP = {
    "URBAN_PAVED": 12750,
    "URBAN_UNPAVED": 10850,
    "RURAL_SHOULDER": 9250,
    "RAIL_CROSSING": 22500,
    "HIGHWAY_CROSSING": 18250,
    "WATER_CROSSING": 24750,
}

OBSTRUCTION_SURCHARGE_CENTS = 75000
STATION_BLOCK_FEET = 100

RESTORATION_RATE_CENTS_PER_FOOT = {
    "AERIAL": {"NONE": 0, "NO_OPEN_CUT": 0, "FULL_RESTORATION": 0},
    "DIRECTIONAL_BORE": {"NONE": 260, "NO_OPEN_CUT": 480, "FULL_RESTORATION": 720},
    "TRENCH": {"NONE": 940, "FULL_RESTORATION": 2150},
}

WORK_CLASS_UNIT_COST_CENTS = {
    "TRANSFER": 42500,
    "POLE_REPLACEMENT": 585000,
    "GUYING": 78000,
    "RISER": 96500,
    "CLEARANCE_TRIM": 31250,
}
WORK_CLASS_LEAD_DAYS = {
    "TRANSFER": 30,
    "POLE_REPLACEMENT": 90,
    "GUYING": 45,
    "RISER": 25,
    "CLEARANCE_TRIM": 15,
}
OWNER_MULTIPLIER_BP = {"ELECTRIC_UTILITY": 11500, "TELCO": 10000, "MUNICIPAL_LIGHT": 9500}
ADMIN_FEE_TIER_1_CEILING_CENTS = 500000
ADMIN_FEE_TIER_2_CEILING_CENTS = 2000000
ADMIN_FEE_TIER_1_BP = 1200
ADMIN_FEE_TIER_2_BP = 900
ADMIN_FEE_TIER_3_BP = 600
POLE_HANDLING_DAYS_PER_POLE = 2
MAKE_READY_DAYS_CAP = 120

REVIEW_CYCLE_DAYS = {"MUNICIPAL_ROW": 21, "RAILROAD": 90, "STATE_HIGHWAY": 45, "WATERWAY": 120}
AUTHORITY_CAP_DAYS = {"MUNICIPAL_ROW": 35, "RAILROAD": 120, "STATE_HIGHWAY": 60, "WATERWAY": 150}
REVISION_ROUND_PENALTY_DAYS = 14
EXPEDITE_FACTOR_BP = 7500
EXPEDITE_AUTHORITIES = ("MUNICIPAL_ROW", "STATE_HIGHWAY")

MIN_SPARE_RATIO_BP = 2000
MIN_SPLICE_SPACING_FEET = 250
MAX_AS_BUILT_VARIANCE_BP = 500
MIN_AUTHORIZED_BUDGET_CENTS = 1
MAKE_READY_CLEARANCE_THRESHOLD_IN = 40

BASIS_POINTS = 10000
CENTIPOINTS_PER_POINT = 100

# ---------------------------------------------------------------------------
# rounding
# ---------------------------------------------------------------------------

def div_round_half_up(numerator, denominator):
    """Exact integer division rounded half up, away from zero on a tie."""
    if denominator < 0:
        numerator, denominator = -numerator, -denominator
    if numerator >= 0:
        return (2 * numerator + denominator) // (2 * denominator)
    return -((2 * (-numerator) + denominator) // (2 * denominator))


def div_ceil(numerator, denominator):
    return -((-numerator) // denominator)


# ---------------------------------------------------------------------------
# segment cost variants
# ---------------------------------------------------------------------------

def preliminary_cost_cents(length_feet, method, terrain_class):
    base = METHOD_BASE_RATE_CENTS_PER_FOOT[method]
    terrain_bp = TERRAIN_MULTIPLIER_BP[terrain_class]
    return div_round_half_up(length_feet * base * terrain_bp, BASIS_POINTS)


def bid_ready_construction_subtotal(length_feet, method, terrain_class):
    """Station-block pricing: each block is rounded BEFORE summation."""
    base = METHOD_BASE_RATE_CENTS_PER_FOOT[method]
    terrain_bp = TERRAIN_MULTIPLIER_BP[terrain_class]
    full_blocks = length_feet // STATION_BLOCK_FEET
    remainder_feet = length_feet % STATION_BLOCK_FEET
    block_cost = div_round_half_up(STATION_BLOCK_FEET * base * terrain_bp, BASIS_POINTS)
    remainder_cost = div_round_half_up(remainder_feet * base * terrain_bp, BASIS_POINTS)
    return full_blocks * block_cost + remainder_cost


def bid_ready_cost_cents(length_feet, method, terrain_class, obstruction_count,
                         restoration_cost_cents, granted_make_ready_cents):
    subtotal = bid_ready_construction_subtotal(length_feet, method, terrain_class)
    surcharge = OBSTRUCTION_SURCHARGE_CENTS * obstruction_count
    return subtotal + surcharge + restoration_cost_cents + granted_make_ready_cents


def restoration_cost_cents(length_feet, method, moratorium_class):
    rate = RESTORATION_RATE_CENTS_PER_FOOT[method].get(moratorium_class)
    if rate is None:
        # TRENCH x NO_OPEN_CUT never reaches this point: the open-cut
        # prohibition rejects the selection first.
        rate = 0
    return length_feet * rate


# ---------------------------------------------------------------------------
# permitting complexity
# ---------------------------------------------------------------------------

def planned_complexity_index(terrain_classes, segment_count):
    weight_sum = 0
    for terrain in terrain_classes:
        weight_sum += AUTHORITY_WEIGHT[AUTHORITY_BY_TERRAIN[terrain]]
    return div_round_half_up(weight_sum * CENTIPOINTS_PER_POINT, segment_count)


def live_complexity_index(permit_rows, segment_count):
    """Round each permit's term to whole centipoints FIRST, then sum."""
    terms = []
    for authority_type, status in permit_rows:
        numerator = AUTHORITY_WEIGHT[authority_type] * STATUS_FACTOR_BP[status] * CENTIPOINTS_PER_POINT
        terms.append(div_round_half_up(numerator, BASIS_POINTS))
    if not terms:
        return 0
    return div_round_half_up(sum(terms), segment_count)


# ---------------------------------------------------------------------------
# make-ready cost and schedule
# ---------------------------------------------------------------------------

def make_ready_item_figures(work_class, quantity, pole_owner):
    unit_cost = WORK_CLASS_UNIT_COST_CENTS[work_class]
    lead_days = WORK_CLASS_LEAD_DAYS[work_class]
    owner_bp = OWNER_MULTIPLIER_BP[pole_owner]
    extended = div_round_half_up(quantity * unit_cost * owner_bp, BASIS_POINTS)
    return unit_cost, extended, lead_days


def admin_fee_bp(subtotal_cents):
    if subtotal_cents < ADMIN_FEE_TIER_1_CEILING_CENTS:
        return ADMIN_FEE_TIER_1_BP
    if subtotal_cents < ADMIN_FEE_TIER_2_CEILING_CENTS:
        return ADMIN_FEE_TIER_2_BP
    return ADMIN_FEE_TIER_3_BP


def admin_fee_cents(subtotal_cents, fee_bp):
    return div_round_half_up(subtotal_cents * fee_bp, BASIS_POINTS)


def make_ready_days(lead_days_values, pole_count):
    longest = max(lead_days_values) if lead_days_values else 0
    total = longest + POLE_HANDLING_DAYS_PER_POLE * pole_count
    return min(total, MAKE_READY_DAYS_CAP)


# ---------------------------------------------------------------------------
# permit review schedule
# ---------------------------------------------------------------------------

def review_days(authority_type, revision_round, topology_objective):
    base_days = REVIEW_CYCLE_DAYS[authority_type]
    penalty = REVISION_ROUND_PENALTY_DAYS * revision_round
    raw_days = base_days + penalty
    expedite_eligible = (
        topology_objective == "RING_CLOSURE" and authority_type in EXPEDITE_AUTHORITIES
    )
    if expedite_eligible:
        effective = div_ceil(raw_days * EXPEDITE_FACTOR_BP, BASIS_POINTS)
    else:
        effective = raw_days
    return min(effective, AUTHORITY_CAP_DAYS[authority_type])


# ---------------------------------------------------------------------------
# design fibre allocation
# ---------------------------------------------------------------------------

def spare_ratio_bp(reserve_fiber_count, fiber_count_allocated):
    return div_round_half_up(reserve_fiber_count * BASIS_POINTS, fiber_count_allocated)


# ---------------------------------------------------------------------------
# as-built variance
# ---------------------------------------------------------------------------

def length_variance_bp(as_built_length_feet, design_total_length_feet):
    if design_total_length_feet == 0:
        return 0
    delta = abs(as_built_length_feet - design_total_length_feet)
    return div_round_half_up(delta * BASIS_POINTS, design_total_length_feet)
