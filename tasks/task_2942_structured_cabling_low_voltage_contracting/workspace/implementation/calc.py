"""The pinned calculations of PRD 3.2, 3.4, 3.5, 3.7, 3.8 and 3.9.

Every constant here is quoted from the PRD narrative; every rounding is
round-half-up on exact decimal arithmetic (PRD 2.6).
"""

from decimal import Decimal

from store import D, r2, r4, rcents

# ---- pinned constants ----------------------------------------------------
PI = Decimal("3.141592653589793")

COPPER_CATEGORIES = ("CAT5E", "CAT6", "CAT6A", "COAX_RG6")
FIBER_CATEGORIES = ("OM4_MMF", "OS2_SMF")
CATEGORIES = ("CAT5E", "CAT6", "CAT6A", "OM4_MMF", "OS2_SMF", "COAX_RG6")
JACKET_RATINGS = ("CM", "CMR", "CMP", "LSZH")
PLENUM_RATINGS = ("CMP", "LSZH")
APPLICATIONS = ("DATA_HORIZONTAL", "BACKBONE", "WAP", "CAMERA",
                "ACCESS_CONTROL", "AV_DISTRIBUTION")
PATHWAY_TYPES = ("CABLE_TRAY", "EMT_CONDUIT", "INNERDUCT", "J_HOOK")

PATCH_CORD_DERATE = Decimal("1.2")
COPPER_PERMANENT_LIMIT_M = Decimal("90.00")
COPPER_CHANNEL_LIMIT_M = Decimal("100.00")
FIBER_PERMANENT_FRACTION = Decimal("0.9")

TRAY_FILL_PCT = 50
FILL_PCT_ONE_CABLE = 53
FILL_PCT_TWO_CABLES = 31
FILL_PCT_THREE_PLUS = 40
BEND_DERATE_PCT = 2
BEND_FREE_COUNT = 2
MIN_FILL_PCT = 25

SEPARATION_FIBER_MM = 0
SEPARATION_SHIELDED_MM = 25
SEPARATION_UNSHIELDED_MM = 50

IL_FIXED_DB = Decimal("0.40")
IL_PER_METRE_DB = Decimal("0.19")
MARGINAL_BAND_DB = Decimal("0.5")

LABOR_CENTS_PER_TERMINATED_END = 4750
TERMINATED_ENDS_PER_LINK = 2
LINK_LABOR_CENTS = LABOR_CENTS_PER_TERMINATED_END * TERMINATED_ENDS_PER_LINK

MAC_MINIMUM_HOURS = Decimal("1")
MAC_LABOR_RATE_CENTS_PER_HOUR = Decimal("9600")
MAC_TIER_MID_THRESHOLD_CENTS = 50000
MAC_TIER_HIGH_THRESHOLD_CENTS = 150000
MAC_DISCOUNT_LOW_PCT = Decimal("0")
MAC_DISCOUNT_MID_PCT = Decimal("5")
MAC_DISCOUNT_HIGH_PCT = Decimal("10")
MAC_EXPEDITE_PCT = Decimal("15")
MAC_ROOM_CREW_CAPACITY = 2
MAC_CHANGEOVER_MINUTES = 30

WARRANTY_BASE_YEARS = {"STANDARD_15Y": 15, "EXTENDED_25Y": 25}
WARRANTY_REWORK_ATTEMPT_THRESHOLD = 3
WARRANTY_REWORK_PENALTY_YEARS = 5
WARRANTY_FLOOR_YEARS = 10

OCCUPANCY_READINESS_PCT = Decimal("90.00")
WARRANTY_ELIGIBLE_PCT = Decimal("100.00")

BONDING_MAX_AWG = 6
GROUND_RESISTANCE_MAX_MILLIOHMS = Decimal("5000")


# ---- 3.4 cable geometry --------------------------------------------------
def cross_section_area_sq_mm(outer_diameter_mm):
    """Area of a circle of the given outside diameter, 2dp (PRD 3.4)."""
    radius = D(outer_diameter_mm) / Decimal(2)
    return r2(PI * radius * radius)


# ---- 3.4 the two length variants ----------------------------------------
def permanent_link_length_m(horizontal_length_m, consolidation_point_stub_m):
    return r2(D(horizontal_length_m) + D(consolidation_point_stub_m))


def channel_length_m(permanent_link_len, patch_cord_allowance_m):
    """Built from the ALREADY ROUNDED permanent-link figure (PRD 2.6, 3.4)."""
    return r2(D(permanent_link_len) + D(patch_cord_allowance_m) * PATCH_CORD_DERATE)


def length_limits(cable_type):
    """(permanent_link_limit, channel_limit) for a cable type's category."""
    if cable_type["category"] in FIBER_CATEGORIES:
        channel = D(cable_type["max_channel_length_m"])
        return r2(channel * FIBER_PERMANENT_FRACTION), channel
    return COPPER_PERMANENT_LIMIT_M, COPPER_CHANNEL_LIMIT_M


def permanent_link_limit_m(cable_type):
    return length_limits(cable_type)[0]


def channel_limit_m(cable_type):
    return length_limits(cable_type)[1]


# ---- 3.5 fill ------------------------------------------------------------
def allowed_fill_pct(pathway_type, resulting_cable_count, bend_count):
    """Whole-number code allowance for a resulting cable count (PRD 3.5).

    The tier table is deliberately NOT monotone: two cables allow 31 percent
    while three or more allow 40.
    """
    if pathway_type == "CABLE_TRAY":
        base = TRAY_FILL_PCT
    elif resulting_cable_count <= 1:
        base = FILL_PCT_ONE_CABLE
    elif resulting_cable_count == 2:
        base = FILL_PCT_TWO_CABLES
    else:
        base = FILL_PCT_THREE_PLUS
    extra_bends = int(bend_count) - BEND_FREE_COUNT
    if extra_bends < 0:
        extra_bends = 0
    result = base - BEND_DERATE_PCT * extra_bends
    if result < MIN_FILL_PCT:
        result = MIN_FILL_PCT
    return int(result)


def segment_allowed_fill_pct(segment, resulting_count=None):
    """A segment's stored allowed_fill_pct: the allowance for one more cable."""
    if resulting_count is None:
        resulting_count = segment["occupying_route_count"] + 1
    return allowed_fill_pct(segment["pathway_type"], resulting_count,
                            segment["bend_count"])


def allowed_fill_area_sq_mm(usable_area_sq_mm, pct):
    return r2(D(usable_area_sq_mm) * D(pct) / Decimal(100))


def fill_ratio(fill_area_used_sq_mm, usable_area_sq_mm):
    """Used area over usable area, four decimal places (PRD 2.6, 3.5)."""
    usable = D(usable_area_sq_mm)
    if usable == 0:
        return r4(0)
    return r4(D(fill_area_used_sq_mm) / usable)


def required_separation_mm(cable_type):
    if cable_type["category"] in FIBER_CATEGORIES:
        return SEPARATION_FIBER_MM
    if cable_type.get("shielded"):
        return SEPARATION_SHIELDED_MM
    return SEPARATION_UNSHIELDED_MM


# ---- 3.2 rack units -----------------------------------------------------
def span_ru(start_ru, end_ru):
    """Closed inclusive interval: highest unit less lowest, plus one."""
    return int(end_ru) - int(start_ru) + 1


def ru_intervals_conflict(a_start, a_end, b_start, b_end):
    """Two closed intervals conflict when they share even one rack unit."""
    return int(a_start) <= int(b_end) and int(a_end) >= int(b_start)


# ---- 3.7 test grading ---------------------------------------------------
def insertion_loss_budget_db(graded_length_m):
    return r2(IL_FIXED_DB + IL_PER_METRE_DB * D(graded_length_m))


def worst_margin_db(next_margin_db, return_loss_margin_db):
    left = D(next_margin_db)
    right = D(return_loss_margin_db)
    return left if left <= right else right


def grade_test(graded_length, graded_limit, insertion_loss, budget, worst_margin):
    """Four tests in order, first match winning (PRD 3.7)."""
    if D(graded_length) > D(graded_limit):
        return "FAIL", "LENGTH_LIMIT"
    if D(insertion_loss) > D(budget):
        return "FAIL", "INSERTION_LOSS"
    if D(worst_margin) < Decimal("0.0"):
        return "FAIL", "MARGIN"
    if D(worst_margin) < MARGINAL_BAND_DB:
        return "PASS_ASTERISK", None
    return "PASS", None


# ---- 3.7 money and completeness ----------------------------------------
def material_cost_cents(cost_per_meter_cents, channel_len):
    """Rounded to whole cents at THIS point, per link, never once at the end."""
    return rcents(D(cost_per_meter_cents) * D(channel_len))


def link_cost_contribution_cents(cost_per_meter_cents, channel_len):
    return material_cost_cents(cost_per_meter_cents, channel_len) + LINK_LABOR_CENTS


def completeness_pct(numerator, total):
    """Exactly 0.00 when the denominator is zero (PRD 3.7)."""
    if not total:
        return r2(0)
    return r2(Decimal(100) * D(numerator) / D(total))


# ---- 3.8 moves-adds-changes billing ------------------------------------
def mac_billing(labor_hours, expedite_requested):
    """The pinned six-step run; the tier is keyed on the SUBTOTAL (PRD 3.8)."""
    hours = D(labor_hours)
    billable_hours = hours if hours > MAC_MINIMUM_HOURS else MAC_MINIMUM_HOURS
    subtotal = rcents(billable_hours * MAC_LABOR_RATE_CENTS_PER_HOUR)
    if subtotal < MAC_TIER_MID_THRESHOLD_CENTS:
        discount_pct = MAC_DISCOUNT_LOW_PCT
    elif subtotal < MAC_TIER_HIGH_THRESHOLD_CENTS:
        discount_pct = MAC_DISCOUNT_MID_PCT
    else:
        discount_pct = MAC_DISCOUNT_HIGH_PCT
    discount = rcents(D(subtotal) * discount_pct / Decimal(100))
    post_discount = subtotal - discount
    if expedite_requested:
        expedite = rcents(D(post_discount) * MAC_EXPEDITE_PCT / Decimal(100))
    else:
        expedite = 0
    return post_discount + expedite


# ---- 3.9 warranty term -------------------------------------------------
def coverage_years(manufacturer_program, rework_link_count):
    """Base term less five years per rework link, floored at ten AFTER the penalty."""
    base = WARRANTY_BASE_YEARS[manufacturer_program]
    term = base - WARRANTY_REWORK_PENALTY_YEARS * int(rework_link_count)
    if term < WARRANTY_FLOOR_YEARS:
        term = WARRANTY_FLOOR_YEARS
    return int(term)
