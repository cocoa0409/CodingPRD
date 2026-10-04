"""Domain thresholds and default payload values pinned by the PRD."""

# The logical clock's fixed startup instant.
CLOCK_START = "2026-09-01T00:00:00Z"

# Constants that parameterise the derived-value rules.
THRESHOLDS = {
    # Cost ceiling: shelf price * ratio * (1 - buffer), floored half down.
    "TARGET_MARGIN_BUFFER_PCT": 0.12,
    # Price integrity: strict ">" against the rounded 3-decimal ratio.
    "MISMATCH_TOLERANCE_PCT": 0.052,
    # Aisle coverage: the conversion completion floor is inclusive on the passing side.
    "COVERAGE_TOLERANCE_PCT": -0.50,
    "COVERAGE_SHORTFALL_FLOOR_AISLES": 1,
    # Shelf waterfall: the base-deck allowance when one full case cannot fit.
    "BASE_DECK_ALLOWANCE_CASES": 1,
    # Defaults the denomination contract pins.
    "VARIABLE_STORE_COST_CENTS": 4,
    "FIXED_STORE_HANDLING_CENTS": 6,
}

# Pagination defaults declared for every listing endpoint.
PAGINATION_DEFAULTS = {"limit": 10, "offset": 0, "min_limit": 1, "max_limit": 100}

# Handy default payload values.
TEST_DEFAULTS = {
    "SHELF_PRICE_CENTS": 125,
    "TARGET_LANDED_COST_RATIO": 0.90,
    "STORE_SHELF_CAPACITY_SQFT": 400.0,
    "VENDOR_NAME": "Ningbo Home Goods Co",
    "COUNTRY_OF_ORIGIN": "CN",
    "PORT_CODE": "LAX",
    "DC_CODE": "DC-ATL",
    "SQFT_PER_UNIT": 0.1,
    "SHELF_PACKAGE_CAPACITY": 4.0,
    "UNITS_PER_CASE": 4,
    "BASE_LANDED_COST_CENTS": 105,
    "VARIABLE_STORE_COST_CENTS": 4,
    "FIXED_STORE_HANDLING_CENTS": 6,
}