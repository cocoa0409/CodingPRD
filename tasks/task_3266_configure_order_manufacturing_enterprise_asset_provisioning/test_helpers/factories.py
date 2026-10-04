"""Payload factories — one per creatable entity, input fields only."""

DEFAULTS = {
    "COMPANY_NAME": "Acme Corp",
    "ACCOUNT_TIER": "STANDARD",
    "CREDIT_LIMIT_CENTS": 10_000_000,
    "PROGRAM_NAME": "Field Engineering Fleet",
    "ASSET_TAG_PREFIX": "FE",
    "CUSTOM_IMAGE_REF": "img-std",
    "MODEL_CODE": "LAT-7440",
    "CATEGORY": "LAPTOP",
    "BASE_PRICE_CENTS": 100_000,
    "BUILD_DURATION_HOURS": 24,
    "SKU": "CPU-TEST",
    "KIND": "CPU",
    "PRICE_CENTS": 20_000,
    "LEAD_TIME_DAYS": 3,
    "STOCK_ON_HAND": 10,
    "REVISION": "A01",
    "TEMPLATE_NAME": "Standard Field Laptop",
    "PO_NUMBER": "PO-TEST",
    "QTY": 1,
    "SHIP_TO_MODE": "SINGLE_ADDRESS",
    "WAVE_LABEL": "Wave 1",
    "TIER": "NBD",
    "COVERAGE_START": "2026-09-01T00:00:00Z",
    "COVERAGE_END": "2027-09-01T00:00:00Z",
    "PROGRAM_KIND": "RECYCLE",
}


def create_account_payload(**overrides):
    payload = {
        "company_name": DEFAULTS["COMPANY_NAME"],
        "account_tier": DEFAULTS["ACCOUNT_TIER"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_program_payload(**overrides):
    payload = {
        "name": DEFAULTS["PROGRAM_NAME"],
        "asset_tag_prefix": DEFAULTS["ASSET_TAG_PREFIX"],
        "custom_image_ref": DEFAULTS["CUSTOM_IMAGE_REF"],
    }
    payload.update(overrides)
    return payload


def create_chassis_model_payload(**overrides):
    payload = {
        "model_code": DEFAULTS["MODEL_CODE"],
        "category": DEFAULTS["CATEGORY"],
        "base_price_cents": DEFAULTS["BASE_PRICE_CENTS"],
        "build_duration_hours": DEFAULTS["BUILD_DURATION_HOURS"],
    }
    payload.update(overrides)
    return payload


def create_component_payload(**overrides):
    payload = {
        "sku": DEFAULTS["SKU"],
        "kind": DEFAULTS["KIND"],
        "price_cents": DEFAULTS["PRICE_CENTS"],
        "lead_time_days": DEFAULTS["LEAD_TIME_DAYS"],
        "stock_on_hand": DEFAULTS["STOCK_ON_HAND"],
        "revision": DEFAULTS["REVISION"],
    }
    payload.update(overrides)
    return payload


def create_compatibility_rule_payload(chassis_model_id, component_id, rule_type, **overrides):
    payload = {
        "chassis_model_id": chassis_model_id,
        "component_id": component_id,
        "rule_type": rule_type,
    }
    payload.update(overrides)
    return payload


def create_template_payload(chassis_model_id, pinned_components, **overrides):
    payload = {
        "name": DEFAULTS["TEMPLATE_NAME"],
        "chassis_model_id": chassis_model_id,
        "pinned_components": pinned_components,
    }
    payload.update(overrides)
    return payload


def create_configuration_payload(account_id, chassis_model_id, component_selections, **overrides):
    payload = {
        "account_id": account_id,
        "chassis_model_id": chassis_model_id,
        "component_selections": component_selections,
    }
    payload.update(overrides)
    return payload


def create_order_payload(account_id, **overrides):
    payload = {
        "account_id": account_id,
        "po_number": DEFAULTS["PO_NUMBER"],
    }
    payload.update(overrides)
    return payload


def add_order_line_payload(configuration_id, **overrides):
    payload = {
        "configuration_id": configuration_id,
        "qty": DEFAULTS["QTY"],
        "ship_to_mode": DEFAULTS["SHIP_TO_MODE"],
    }
    payload.update(overrides)
    return payload


def create_wave_payload(destinations=None, **overrides):
    payload = {
        "wave_label": DEFAULTS["WAVE_LABEL"],
        "ship_window_start": "2026-09-02T00:00:00Z",
        "ship_window_end": "2026-09-20T00:00:00Z",
        "destinations": destinations
        or [{"employee_ref": "HQ", "address": "1 Main St", "units": 1}],
    }
    payload.update(overrides)
    return payload


def create_entitlement_payload(**overrides):
    payload = {
        "tier": DEFAULTS["TIER"],
        "coverage_start": DEFAULTS["COVERAGE_START"],
        "coverage_end": DEFAULTS["COVERAGE_END"],
    }
    payload.update(overrides)
    return payload


def create_recovery_request_payload(account_id, asset_id, **overrides):
    payload = {
        "account_id": account_id,
        "asset_id": asset_id,
        "program_kind": DEFAULTS["PROGRAM_KIND"],
    }
    payload.update(overrides)
    return payload
