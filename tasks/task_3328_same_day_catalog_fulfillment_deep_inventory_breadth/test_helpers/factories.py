"""Payload factories — one per entity, input fields only."""

from .constants import TEST_DEFAULTS


def create_distribution_center_payload(**overrides) -> dict:
    payload = {
        "code": TEST_DEFAULTS["CODE"],
        "region": TEST_DEFAULTS["REGION"],
        "local_zone": TEST_DEFAULTS["LOCAL_ZONE"],
        "local_cutoff_time": TEST_DEFAULTS["LOCAL_CUTOFF_TIME"],
        "utc_offset_minutes": TEST_DEFAULTS["UTC_OFFSET_MINUTES"],
        "inbound_capacity_units": TEST_DEFAULTS["INBOUND_CAPACITY_UNITS"],
        "transit_seconds": TEST_DEFAULTS["TRANSIT_SECONDS"],
    }
    payload.update(overrides)
    return payload


def create_account_payload(**overrides) -> dict:
    payload = {
        "account_name": TEST_DEFAULTS["ACCOUNT_NAME"],
        "delivery_zone": TEST_DEFAULTS["DELIVERY_ZONE"],
        "home_region": TEST_DEFAULTS["HOME_REGION"],
    }
    payload.update(overrides)
    return payload


def create_supplier_payload(**overrides) -> dict:
    payload = {
        "supplier_name": TEST_DEFAULTS["SUPPLIER_NAME"],
        "primary_attribute_name": TEST_DEFAULTS["ATTRIBUTE_NAME"],
        "primary_attribute_value": TEST_DEFAULTS["ATTRIBUTE_VALUE"],
        "long_tail_authorized": True,
        "min_stock_commitment_units": TEST_DEFAULTS["MIN_STOCK_COMMITMENT_UNITS"],
    }
    payload.update(overrides)
    return payload


def create_item_payload(**overrides) -> dict:
    payload = {
        "sku": "SKU-0001",
        "description": "Test catalog item",
        "material_spec": "18-8 stainless steel",
        "long_tail": False,
        "unit_price_cents": TEST_DEFAULTS["UNIT_PRICE_CENTS"],
        "unit_weight_kg": TEST_DEFAULTS["UNIT_WEIGHT_KG"],
        "curation_bundle_size": TEST_DEFAULTS["CURATION_BUNDLE_SIZE"],
        "curated_dimension_json": {
            "nominal_length_mm": 10,
            "nominal_width_mm": 10,
            "nominal_height_mm": 10,
            "drawing_revision": 1,
        },
    }
    payload.update(overrides)
    return payload


def create_attribute_payload(**overrides) -> dict:
    payload = {
        "attribute_name": TEST_DEFAULTS["ATTRIBUTE_NAME"],
        "attribute_value": TEST_DEFAULTS["ATTRIBUTE_VALUE"],
        "unit_of_measure": TEST_DEFAULTS["UNIT_OF_MEASURE"],
    }
    payload.update(overrides)
    return payload


def create_cross_reference_payload(**overrides) -> dict:
    payload = {
        "referenced_manufacturer": "Acme Fasteners",
        "referenced_part_number": "AC-2201",
        "compatibility_note": "direct interchange",
    }
    payload.update(overrides)
    return payload


def create_stock_payload(**overrides) -> dict:
    payload = {
        "on_hand_units": TEST_DEFAULTS["ON_HAND_UNITS"],
        "daily_demand_units": TEST_DEFAULTS["DAILY_DEMAND_UNITS"],
        "inbound_daily_units": TEST_DEFAULTS["INBOUND_DAILY_UNITS"],
    }
    payload.update(overrides)
    return payload


def create_order_payload(**overrides) -> dict:
    payload = {"lines": []}
    payload.update(overrides)
    return payload


def order_line_payload(item_id: str, quantity: int = 1) -> dict:
    return {"item_id": item_id, "quantity": quantity}


def create_return_payload(order_id: str, lines: list, **overrides) -> dict:
    payload = {"order_id": order_id, "lines": lines}
    payload.update(overrides)
    return payload


def return_line_payload(line_id: str, requested_return_units: int) -> dict:
    return {"line_id": line_id, "requested_return_units": requested_return_units}


def confirm_cutoff_payload(expected_order_version: int, service_level: str = "GROUND", **overrides) -> dict:
    payload = {
        "expected_order_version": expected_order_version,
        "service_level": service_level,
    }
    payload.update(overrides)
    return payload


def create_square_footage_request_payload(account_id: str, lines: list, **overrides) -> dict:
    payload = {"account_id": account_id, "lines": lines}
    payload.update(overrides)
    return payload


def square_footage_line_payload(cut_list_ordinal: int, requested_feet: int) -> dict:
    return {"cut_list_ordinal": cut_list_ordinal, "requested_feet": requested_feet}