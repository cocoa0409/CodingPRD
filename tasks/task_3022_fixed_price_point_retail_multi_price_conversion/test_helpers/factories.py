"""Payload factories: one per entity, input fields only."""

from .constants import TEST_DEFAULTS


def create_price_point_payload(label="DOLLAR_25", shelf_price_cents=None, target_landed_cost_ratio=None, **overrides):
    payload = {
        "label": label,
        "shelf_price_cents": TEST_DEFAULTS["SHELF_PRICE_CENTS"] if shelf_price_cents is None else shelf_price_cents,
        "target_landed_cost_ratio": (
            TEST_DEFAULTS["TARGET_LANDED_COST_RATIO"] if target_landed_cost_ratio is None
            else target_landed_cost_ratio
        ),
    }
    payload.update(overrides)
    return payload


def create_vendor_payload(vendor_name=None, country_of_origin=None, import_flag=True, **overrides):
    payload = {
        "vendor_name": TEST_DEFAULTS["VENDOR_NAME"] if vendor_name is None else vendor_name,
        "country_of_origin": TEST_DEFAULTS["COUNTRY_OF_ORIGIN"] if country_of_origin is None else country_of_origin,
        "import_flag": import_flag,
    }
    payload.update(overrides)
    return payload


def create_store_payload(store_number="1927", shelf_facing_capacity_sqft=None, **overrides):
    payload = {
        "store_number": store_number,
        "shelf_facing_capacity_sqft": (
            TEST_DEFAULTS["STORE_SHELF_CAPACITY_SQFT"] if shelf_facing_capacity_sqft is None
            else shelf_facing_capacity_sqft
        ),
    }
    payload.update(overrides)
    return payload


def create_item_payload(sku, sourcing_vendor_id, **overrides):
    payload = {
        "sku": sku,
        "description": f"Item {sku}",
        "unit_retail_cents": TEST_DEFAULTS["SHELF_PRICE_CENTS"],
        "commodity_class": "KITCHEN",
        "season_code": "HARVEST_2026",
        "sqft_per_unit": TEST_DEFAULTS["SQFT_PER_UNIT"],
        "shelf_package_capacity": TEST_DEFAULTS["SHELF_PACKAGE_CAPACITY"],
        "units_per_case": TEST_DEFAULTS["UNITS_PER_CASE"],
        "base_landed_cost_cents": TEST_DEFAULTS["BASE_LANDED_COST_CENTS"],
        "fixed_store_handling_cents": TEST_DEFAULTS["FIXED_STORE_HANDLING_CENTS"],
        "variable_store_cost_cents": TEST_DEFAULTS["VARIABLE_STORE_COST_CENTS"],
        "sourcing_vendor_id": sourcing_vendor_id,
    }
    payload.update(overrides)
    return payload


def create_container_payload(vendor_id, container_number="MSCU7654321", total_freight_cents=0, **overrides):
    payload = {
        "vendor_id": vendor_id,
        "container_number": container_number,
        "port_code": TEST_DEFAULTS["PORT_CODE"],
        "dc_code": TEST_DEFAULTS["DC_CODE"],
        "total_freight_cents": total_freight_cents,
    }
    payload.update(overrides)
    return payload


def create_allocation_line_payload(container_id, store_id, item_id, sequence=1, requested_units=40, **overrides):
    payload = {
        "container_id": container_id,
        "store_id": store_id,
        "item_id": item_id,
        "sequence": sequence,
        "requested_units": requested_units,
    }
    payload.update(overrides)
    return payload


def create_pack_program_payload(vendor_id, price_point_id, quoted_landed_cost_cents=100, **overrides):
    payload = {
        "vendor_id": vendor_id,
        "price_point_id": price_point_id,
        "pack_qty": 6,
        "case_pack_qty": 48,
        "formulation_code": "LOW_SUDS_V3",
        "quoted_landed_cost_cents": quoted_landed_cost_cents,
    }
    payload.update(overrides)
    return payload


def create_season_window_payload(season_code="HARVEST_2026", opens_on=None, closes_on=None, **overrides):
    payload = {
        "season_code": season_code,
        "opens_on": opens_on or "2026-09-01T00:00:00Z",
        "closes_on": closes_on or "2026-11-30T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_aisle_reset_payload(store_id, price_point_id, season_window_id, aisle_code="A11",
                               starts_at="2026-09-02T00:00:00Z", ends_at="2026-09-08T00:00:00Z",
                               allocated_shelf_sqft=50.0, seasonal_changeover=True, **overrides):
    payload = {
        "store_id": store_id,
        "price_point_id": price_point_id,
        "season_window_id": season_window_id,
        "aisle_code": aisle_code,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "allocated_shelf_sqft": allocated_shelf_sqft,
        "seasonal_changeover": seasonal_changeover,
    }
    payload.update(overrides)
    return payload


def create_audit_payload(store_id, price_point_id, observed_item_count=80, mismatched_item_count=5,
                         audited_at="2026-09-03T00:00:00Z", **overrides):
    payload = {
        "store_id": store_id,
        "price_point_id": price_point_id,
        "audited_at": audited_at,
        "observed_item_count": observed_item_count,
        "mismatched_item_count": mismatched_item_count,
    }
    payload.update(overrides)
    return payload


def create_conversion_project_payload(store_id, from_price_point_id, to_price_point_id,
                                      expected_store_version, **overrides):
    payload = {
        "store_id": store_id,
        "from_price_point_id": from_price_point_id,
        "to_price_point_id": to_price_point_id,
        "expected_store_version": expected_store_version,
    }
    payload.update(overrides)
    return payload


def create_multi_price_issue_payload(store_id, from_price_point_id, item_ids, to_price_point_id, **overrides):
    payload = {
        "store_id": store_id,
        "from_price_point_id": from_price_point_id,
        "item_ids": list(item_ids),
        "to_price_point_id": to_price_point_id,
    }
    payload.update(overrides)
    return payload


def landed_cost_payload(method="VENDOR_PRICE_CHANGE", applied_amount_cents=0, container_id=None, **overrides):
    payload = {"method": method, "applied_amount_cents": applied_amount_cents}
    if container_id is not None:
        payload["container_id"] = container_id
    payload.update(overrides)
    return payload