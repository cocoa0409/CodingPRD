"""Payload factories — one per creatable resource, input fields only.

Defaults mirror the canonical happy-path values used across the test design:
an equipment distributor billing 14,000 cents/hour, a TOURNAMENT mower at
7,500,000 cents, etc. Every factory accepts **overrides so tests control
exactly the fields under assertion.
"""

DEFAULTS = {
    "DISTRIBUTOR_NAME": "GreenFair Distribution",
    "TERRITORY_CODES": ["CA", "NV"],
    "CHANNEL": "EQUIPMENT",
    "MIN_PARTS_STOCK_VALUE_CENTS": 0,
    "LABOR_RATE_CENTS": 14000,
    "ANNUAL_CLAIM_CAP_CENTS": 50000000,
    "TECHNICIAN_FULL_NAME": "Tess Torque",
    "COURSE_NAME": "Bent Pine CC",
    "TURF_PROFILE": "BENTGRASS",
    "CUT_QUALITY_STANDARD": "CLUB",
    "CREDIT_LIMIT_CENTS": 50000000,
    "MODEL_CODE": "RM-5010H",
    "MODEL_CATEGORY": "MOWER",
    "MODEL_TIER": "TOURNAMENT",
    "LIST_PRICE_CENTS": 7500000,
    "ELIGIBLE_TURF_TYPES": ["BENTGRASS", "POA_ANNUA", "MIXED"],
    "FACTORY_WARRANTY_MONTHS": 24,
    "WARRANTY_LABOR_HOURLY_CAP_CENTS": 9500,
    "PARTS_SUPPORT_YEARS": 10,
    "PART_SKU": "P1-BEDKNIFE",
    "PART_NAME": "Bedknife 11-blade",
    "PART_UNIT_COST_CENTS": 12000,
    "PART_MIN_STOCK_QTY": 4,
    "ORDER_TYPE": "STOCK",
    "CYCLE_MONTHS": 36,
    "LEASE_START_DATE": "2027-03-01",
    "EXTERNAL_SERIAL": "OLD-001",
    "APPRAISAL_HOURS": 2200,
    "CONDITION_GRADE": "B",
    "POLICY": "BOOK",
    "LABOR_HOURS": 4,
    "PARTS_COST_CENTS": 22000,
    "ACREAGE": 120,
    "ZONE_COUNT": 22,
}


def create_distributor_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["DISTRIBUTOR_NAME"],
        "territory_codes": list(DEFAULTS["TERRITORY_CODES"]),
        "channel": DEFAULTS["CHANNEL"],
        "min_parts_stock_value_cents": DEFAULTS["MIN_PARTS_STOCK_VALUE_CENTS"],
        "labor_rate_cents": DEFAULTS["LABOR_RATE_CENTS"],
        "annual_claim_cap_cents": DEFAULTS["ANNUAL_CLAIM_CAP_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    defaults = {"full_name": DEFAULTS["TECHNICIAN_FULL_NAME"]}
    defaults.update(overrides)
    return defaults


def certify_technician_payload(**overrides) -> dict:
    defaults = {"level": "MASTER", "expires_at": "2028-06-01T00:00:00Z"}
    defaults.update(overrides)
    return defaults


def create_course_payload(assigned_distributor_id, **overrides) -> dict:
    defaults = {
        "name": DEFAULTS["COURSE_NAME"],
        "turf_profile": DEFAULTS["TURF_PROFILE"],
        "cut_quality_standard": DEFAULTS["CUT_QUALITY_STANDARD"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
        "assigned_distributor_id": assigned_distributor_id,
    }
    defaults.update(overrides)
    return defaults


def create_model_payload(**overrides) -> dict:
    defaults = {
        "model_code": DEFAULTS["MODEL_CODE"],
        "category": DEFAULTS["MODEL_CATEGORY"],
        "tier": DEFAULTS["MODEL_TIER"],
        "list_price_cents": DEFAULTS["LIST_PRICE_CENTS"],
        "eligible_turf_types": list(DEFAULTS["ELIGIBLE_TURF_TYPES"]),
        "factory_warranty_months": DEFAULTS["FACTORY_WARRANTY_MONTHS"],
        "warranty_labor_hourly_cap_cents": DEFAULTS["WARRANTY_LABOR_HOURLY_CAP_CENTS"],
        "parts_support_years": DEFAULTS["PARTS_SUPPORT_YEARS"],
    }
    defaults.update(overrides)
    return defaults


def create_part_payload(primary_model_id, **overrides) -> dict:
    defaults = {
        "sku": DEFAULTS["PART_SKU"],
        "name": DEFAULTS["PART_NAME"],
        "primary_model_id": primary_model_id,
        "unit_cost_cents": DEFAULTS["PART_UNIT_COST_CENTS"],
        "min_stock_qty": DEFAULTS["PART_MIN_STOCK_QTY"],
    }
    defaults.update(overrides)
    return defaults


def create_parts_order_payload(lines, **overrides) -> dict:
    """lines: array of { part_id, qty }."""
    defaults = {"order_type": DEFAULTS["ORDER_TYPE"], "lines": lines}
    defaults.update(overrides)
    return defaults


def create_lease_payload(course_id, lines, **overrides) -> dict:
    """lines: array of { model_id, qty }."""
    defaults = {
        "course_id": course_id,
        "cycle_months": DEFAULTS["CYCLE_MONTHS"],
        "start_date": DEFAULTS["LEASE_START_DATE"],
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_appraisal_payload(lease_id, model_id, **overrides) -> dict:
    defaults = {
        "lease_id": lease_id,
        "model_id": model_id,
        "external_serial": DEFAULTS["EXTERNAL_SERIAL"],
        "hours": DEFAULTS["APPRAISAL_HOURS"],
        "condition_grade": DEFAULTS["CONDITION_GRADE"],
        "policy": DEFAULTS["POLICY"],
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(lease_unit_id, technician_id, **overrides) -> dict:
    defaults = {
        "lease_unit_id": lease_unit_id,
        "technician_id": technician_id,
        "labor_hours": DEFAULTS["LABOR_HOURS"],
        "parts_cost_cents": DEFAULTS["PARTS_COST_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_irrigation_project_payload(course_id, **overrides) -> dict:
    defaults = {
        "course_id": course_id,
        "acreage": DEFAULTS["ACREAGE"],
        "zone_count": DEFAULTS["ZONE_COUNT"],
    }
    defaults.update(overrides)
    return defaults
