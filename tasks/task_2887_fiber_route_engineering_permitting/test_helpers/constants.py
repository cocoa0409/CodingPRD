"""Calculation constants and thresholds declared by the PRD.

Every number here is copied from the PRD narrative.  Money is an integer count
of cents, ratios are integer basis points and complexity is integer centipoints;
nothing in this module is a float.
"""

from __future__ import annotations

from typing import Dict

# A syntactically well-formed UUID that is never minted by the server, used for
# not-found probes.
ABSENT_UUID = "00000000-0000-4000-8000-000000000000"

# The logical clock's value before any client has set it.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

BASIS_POINTS_DENOMINATOR = 10000
CENTIPOINTS_PER_POINT = 100


# --- terrain -> permitting authority -------------------------------------
TERRAIN_TO_AUTHORITY: Dict[str, str] = {
    "URBAN_PAVED": "MUNICIPAL_ROW",
    "URBAN_UNPAVED": "MUNICIPAL_ROW",
    "RURAL_SHOULDER": "MUNICIPAL_ROW",
    "HIGHWAY_CROSSING": "STATE_HIGHWAY",
    "RAIL_CROSSING": "RAILROAD",
    "WATER_CROSSING": "WATERWAY",
}

# --- authority weights in whole points ------------------------------------
AUTHORITY_WEIGHTS: Dict[str, int] = {
    "MUNICIPAL_ROW": 10,
    "STATE_HIGHWAY": 25,
    "RAILROAD": 40,
    "WATERWAY": 50,
}

# --- live-index status factors in basis points ----------------------------
PERMIT_STATUS_FACTORS_BP: Dict[str, int] = {
    "UNDER_REVIEW": 10000,
    "REVISION_REQUESTED": 15000,
    "APPROVED": 2500,
    "DENIED": 20000,
}

# --- construction cost inputs ---------------------------------------------
BASE_RATE_CENTS_PER_FOOT: Dict[str, int] = {
    "AERIAL": 1237,
    "DIRECTIONAL_BORE": 4615,
    "TRENCH": 2845,
}

TERRAIN_MULTIPLIER_BP: Dict[str, int] = {
    "URBAN_PAVED": 12750,
    "URBAN_UNPAVED": 10850,
    "RURAL_SHOULDER": 9250,
    "RAIL_CROSSING": 22500,
    "HIGHWAY_CROSSING": 18250,
    "WATER_CROSSING": 24750,
}

STATION_BLOCK_FEET = 100
OBSTRUCTION_SURCHARGE_CENTS = 75000

# --- restoration rates in cents per foot, keyed (method, moratorium_class) -
RESTORATION_RATE_CENTS_PER_FOOT: Dict[str, Dict[str, int]] = {
    "AERIAL": {"NONE": 0, "NO_OPEN_CUT": 0, "FULL_RESTORATION": 0},
    "DIRECTIONAL_BORE": {"NONE": 260, "NO_OPEN_CUT": 480, "FULL_RESTORATION": 720},
    # The TRENCH / NO_OPEN_CUT combination does not exist: the open-cut
    # prohibition rejects the selection before any restoration is computed.
    "TRENCH": {"NONE": 940, "FULL_RESTORATION": 2150},
}

# --- make-ready pricing ---------------------------------------------------
MAKE_READY_UNIT_COST_CENTS: Dict[str, int] = {
    "TRANSFER": 42500,
    "POLE_REPLACEMENT": 585000,
    "GUYING": 78000,
    "RISER": 96500,
    "CLEARANCE_TRIM": 31250,
}

MAKE_READY_LEAD_DAYS: Dict[str, int] = {
    "TRANSFER": 30,
    "POLE_REPLACEMENT": 90,
    "GUYING": 45,
    "RISER": 25,
    "CLEARANCE_TRIM": 15,
}

POLE_OWNER_MULTIPLIER_BP: Dict[str, int] = {
    "ELECTRIC_UTILITY": 11500,
    "TELCO": 10000,
    "MUNICIPAL_LIGHT": 9500,
}

# Administrative fee tiers keyed on the pre-fee subtotal, never on the total.
ADMIN_FEE_TIER_1_CEILING_CENTS = 500000  # strictly below -> 1200 bp
ADMIN_FEE_TIER_2_CEILING_CENTS = 2000000  # strictly below -> 900 bp
ADMIN_FEE_TIER_1_BP = 1200
ADMIN_FEE_TIER_2_BP = 900
ADMIN_FEE_TIER_3_BP = 600

MAKE_READY_DAYS_PER_POLE = 2
MAKE_READY_DAYS_CAP = 120

# --- permit review schedule ----------------------------------------------
AUTHORITY_BASE_REVIEW_DAYS: Dict[str, int] = {
    "MUNICIPAL_ROW": 21,
    "STATE_HIGHWAY": 45,
    "RAILROAD": 90,
    "WATERWAY": 120,
}

AUTHORITY_REVIEW_DAY_CAP: Dict[str, int] = {
    "MUNICIPAL_ROW": 35,
    "STATE_HIGHWAY": 60,
    "RAILROAD": 120,
    "WATERWAY": 150,
}

REVISION_PENALTY_DAYS = 14
EXPEDITE_MULTIPLIER_BP = 7500
EXPEDITE_ELIGIBLE_TOPOLOGY = "RING_CLOSURE"
EXPEDITE_ELIGIBLE_AUTHORITIES = ("MUNICIPAL_ROW", "STATE_HIGHWAY")

# --- fiber / design ------------------------------------------------------
MANUFACTURED_FIBER_COUNTS = (48, 96, 144, 240, 288, 432)
SPLICE_SPACING_MIN_FEET = 250
SPARE_RATIO_MIN_BP = 2000

# --- pole condition ------------------------------------------------------
MAKE_READY_CLEARANCE_THRESHOLD_IN = 40
MAKE_READY_GRADES = ("C", "D")
GRADE_SEVERITY_ORDER = ("NONE", "A", "B", "C", "D")

# --- as-built ------------------------------------------------------------
AS_BUILT_VARIANCE_CAP_BP = 500

# --- pagination ---------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


THRESHOLDS: Dict[str, int] = {
    "make_ready_clearance_threshold_in": MAKE_READY_CLEARANCE_THRESHOLD_IN,
    "admin_fee_tier_1_ceiling_cents": ADMIN_FEE_TIER_1_CEILING_CENTS,
    "admin_fee_tier_2_ceiling_cents": ADMIN_FEE_TIER_2_CEILING_CENTS,
    "make_ready_days_cap": MAKE_READY_DAYS_CAP,
    "splice_spacing_min_feet": SPLICE_SPACING_MIN_FEET,
    "spare_ratio_min_bp": SPARE_RATIO_MIN_BP,
    "as_built_variance_cap_bp": AS_BUILT_VARIANCE_CAP_BP,
    "obstruction_surcharge_cents": OBSTRUCTION_SURCHARGE_CENTS,
    "station_block_feet": STATION_BLOCK_FEET,
    "revision_penalty_days": REVISION_PENALTY_DAYS,
    "expedite_multiplier_bp": EXPEDITE_MULTIPLIER_BP,
}


TEST_DEFAULTS: Dict[str, object] = {
    "route_name": "Harbor Loop",
    "topology_objective": "RING_CLOSURE",
    "target_in_service_date": "2027-03-01",
    "budget_authorized_cents": 250000000,
    "street_name": "Dock Street",
    "municipality_code": "MUN-014",
    "length_feet": 400,
    "terrain_class": "URBAN_PAVED",
    "planned_work_start_on": "2026-09-15",
    "planned_work_end_on": "2026-09-20",
    "walked_on": "2026-08-11",
    "pole_tag": "P-001",
    "pole_owner": "TELCO",
    "condition_grade": "B",
    "available_vertical_clearance_in": 45,
    "existing_attachment_count": 2,
    "authority_type": "MUNICIPAL_ROW",
    "authority_name": "Harbor City Right-of-Way Office",
    "work_window_start_on": "2026-09-15",
    "work_window_end_on": "2026-09-20",
    "fiber_count_allocated": 288,
    "express_fiber_count": 48,
    "enclosure_type": "HANDHOLE",
    "records_system_reference": "NRS-2026-0001",
}
