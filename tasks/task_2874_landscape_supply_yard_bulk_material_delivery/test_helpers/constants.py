"""Numeric constants and shared test defaults for the Landscape Supply Yard API."""

from __future__ import annotations

THRESHOLDS = {
    # Moisture / net sellable volume
    "MOISTURE_REFERENCE_PCT": 15.0,
    "MOISTURE_ADJUST_FLOOR": 0.80,
    "MOISTURE_ADJUST_CEIL": 1.00,
    # Order charge assembly
    "MIN_LOAD_SUBTOTAL_CENTS": 25000,
    "MIN_LOAD_FEE_CENTS": 7500,
    "VOLUME_DISCOUNT_TIERS": [
        {"lower_cents": 0, "upper_cents": 100000, "pct": 0.0},
        {"lower_cents": 100000, "upper_cents": 250000, "pct": 3.0},
        {"lower_cents": 250000, "upper_cents": None, "pct": 6.0},
    ],
    "DELIVERY_BASE_CENTS_BY_AXLE": {"SINGLE": 6500, "TANDEM": 9500, "TRI_AXLE": 13500},
    "DELIVERY_PER_MILE_CENTS": 425,
    # Truck fit / site access
    "MAX_AXLE_BY_ACCESS_CLASS": {
        "CLASS_A": "TRI_AXLE",
        "CLASS_B": "TANDEM",
        "CLASS_C": "SINGLE",
    },
    "DRIVEWAY_CAP_CUBIC_YARDS": {"CLASS_A": 999.0, "CLASS_B": 12.0, "CLASS_C": 6.0},
    "ACCESS_RANK": {"CLASS_A": 3, "CLASS_B": 2, "CLASS_C": 1},
    # Credit
    "CREDIT_HOLD_RELEASE_RATIO": 0.90,
    # Claims
    "DRIVEWAY_DEDUCTIBLE_CENTS": 15000,
    "SPILLAGE_CLEANUP_CAP_CENTS": 40000,
    # Reusable containers
    "CONTAINER_GRACE_DAYS": 30,
    "CONTAINER_LATE_DECAY_PCT_PER_WEEK": 25,
    "BAGS_PER_CONTAINER": 48,
    "CONTAINER_TYPE_BY_CATEGORY": {
        "MULCH": "PALLET",
        "AGGREGATE": "PALLET",
        "SOIL": "SUPER_SACK",
        "SALT": "SALT_TOTE",
    },
    "CONTAINER_DEPOSIT_BY_TYPE": {"PALLET": 2500, "SUPER_SACK": 6000, "SALT_TOTE": 4500},
    # Will-call yard
    "WILL_CALL_STAGING_CAPACITY": 2,
    # Truck window buffer described in the delivery-run narrative
    "TRUCK_WINDOW_BUFFER_MINUTES": 45,
}

TEST_DEFAULTS = {
    # Wide credit line so credit gating never fires unless a test asks for it.
    "GENEROUS_CREDIT_LIMIT_CENTS": 5000000,
    "MATERIAL_DENSITY_LB_PER_CUBIC_YARD": 1000.0,
    "MATERIAL_SHRINKAGE_FACTOR": 0.10,
    "MATERIAL_MOISTURE_PCT": 15.0,
    "UNIT_BAG_CUBIC_YARDS": 0.037,
    "BULK_PRICE_PER_CUBIC_YARD_CENTS": 2000,
    "BAGGED_PRICE_PER_BAG_CENTS": 899,
    "LOT_GROSS_CUBIC_YARDS": 100.0,
    "LOT_MOISTURE_PCT_AT_INTAKE": 15.0,
    "TRUCK_MAX_PAYLOAD_LB": 40000,
    "TRUCK_BED_CAPACITY_CUBIC_YARDS": 20.0,
    "DELIVERY_ADDRESS": "1400 Quarry Access Road, Bay 4",
    # Logical-clock instant the yard starts from when it has never been set.
    "BASE_CLOCK_UTC": "2026-08-01T00:00:00.000Z",
    "PRICE_EFFECTIVE_FROM": "2026-07-01T00:00:00.000Z",
}

__all__ = ["THRESHOLDS", "TEST_DEFAULTS"]
