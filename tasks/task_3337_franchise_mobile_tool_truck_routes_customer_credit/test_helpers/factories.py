"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "LEGAL_NAME": "Route 3337 Franchising LLC",
    "SECOND_LEGAL_NAME": "Second Franchisee LLC",
    "ROUTE_CODE": "R1",
    "ROUTE_TIER": "A",
    "ZIP_CODES": ["75001"],
    "VISIT_WEEKDAY": 1,
    "TRUCK_LABEL": "T-01",
    "INVENTORY_INVESTED_CENTS": 100_000,
    "MIX_PLAN": "DIAGNOSTIC_WEIGHTED",
    "TERRITORY_MODEL": "FRANCHISEE_ASSUMED",
    "SHOP_NAME": "Northside Diesel",
    "STREET_LINE": "12 Elm",
    "ZIP_CODE": "75001",
    "FULL_NAME": "Dana Reyes",
    "CREDIT_LINE_LIMIT_CENTS": 100_000,
    "MONTHS_IN_TRADE": 100,
    "SKU": "P1",
    "PRODUCT_NAME": "Torque Wrench",
    "CATEGORY": "POWER_TOOLS",
    "UNIT_COST_CENTS": 12_000,
    "RETAIL_PRICE_CENTS": 15_000,
    "DEFAULT_WARRANTY_MONTHS": 12,
    "REQUESTED_LIMIT_CENTS": 50_000,
    "TERM_MONTHS": 12,
    "PAYMENT_AMOUNT_CENTS": 20_000,
}


def franchisee_payload(**overrides) -> dict:
    payload = {"legal_name": DEFAULTS["LEGAL_NAME"]}
    payload.update(overrides)
    return payload


def training_payload(action, training_points, **overrides) -> dict:
    payload = {"action": action, "training_points": training_points}
    payload.update(overrides)
    return payload


def route_payload(**overrides) -> dict:
    payload = {
        "route_code": DEFAULTS["ROUTE_CODE"],
        "route_tier": DEFAULTS["ROUTE_TIER"],
        "zip_codes": list(DEFAULTS["ZIP_CODES"]),
        "visit_weekday": DEFAULTS["VISIT_WEEKDAY"],
        "truck_label": DEFAULTS["TRUCK_LABEL"],
        "inventory_invested_cents": DEFAULTS["INVENTORY_INVESTED_CENTS"],
        "mix_plan": DEFAULTS["MIX_PLAN"],
        "territory_model": DEFAULTS["TERRITORY_MODEL"],
    }
    payload.update(overrides)
    return payload


def shop_payload(**overrides) -> dict:
    payload = {
        "shop_name": DEFAULTS["SHOP_NAME"],
        "street_line": DEFAULTS["STREET_LINE"],
        "zip_code": DEFAULTS["ZIP_CODE"],
    }
    payload.update(overrides)
    return payload


def technician_payload(shop_id, **overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["FULL_NAME"],
        "current_shop_location_id": shop_id,
        "credit_line_limit_cents": DEFAULTS["CREDIT_LINE_LIMIT_CENTS"],
        "months_in_trade": DEFAULTS["MONTHS_IN_TRADE"],
        "employment_verified": True,
    }
    payload.update(overrides)
    return payload


def product_payload(**overrides) -> dict:
    payload = {
        "sku": DEFAULTS["SKU"],
        "product_name": DEFAULTS["PRODUCT_NAME"],
        "category": DEFAULTS["CATEGORY"],
        "unit_cost_cents": DEFAULTS["UNIT_COST_CENTS"],
        "retail_price_cents": DEFAULTS["RETAIL_PRICE_CENTS"],
        "default_warranty_months": DEFAULTS["DEFAULT_WARRANTY_MONTHS"],
        "is_new_launch": False,
    }
    payload.update(overrides)
    return payload


def credit_application_payload(technician_id, **overrides) -> dict:
    payload = {
        "technician_id": technician_id,
        "requested_limit_cents": DEFAULTS["REQUESTED_LIMIT_CENTS"],
        "requested_kind": "REVOLVING",
        "employment_verified": True,
        "months_in_trade": DEFAULTS["MONTHS_IN_TRADE"],
        "prior_delinquency_count": 0,
        "decision_source": "FRANCHISEE",
    }
    payload.update(overrides)
    return payload


def payment_payload(expected_week_start, **overrides) -> dict:
    payload = {
        "amount_cents": DEFAULTS["PAYMENT_AMOUNT_CENTS"],
        "collection_source": "TRUCK_COLLECTION",
        "expected_week_start": expected_week_start,
    }
    payload.update(overrides)
    return payload


def sales_order_line(product_id, quantity=1, unit_price_cents=None, warranty_months=12,
                     warranty_type="FORCE1000"):
    return {
        "product_id": product_id,
        "quantity": quantity,
        "unit_price_cents": (DEFAULTS["RETAIL_PRICE_CENTS"] if unit_price_cents is None
                             else unit_price_cents),
        "warranty_terms": {"type": warranty_type, "months": warranty_months},
    }


def sales_order_payload(technician_id, credit_account_id, lines, **overrides) -> dict:
    payload = {
        "technician_id": technician_id,
        "credit_account_id": credit_account_id,
        "mix_profile": DEFAULTS["MIX_PLAN"],
        "lines": lines,
    }
    payload.update(overrides)
    return payload


def warranty_claim_payload(idempotency_key, **overrides) -> dict:
    payload = {
        "line_index": 0,
        "claim_kind": "CLAIM",
        "idempotency_key": idempotency_key,
    }
    payload.update(overrides)
    return payload


def inventory_position_payload(product_id, on_hand_qty, **overrides) -> dict:
    payload = {"product_id": product_id, "on_hand_qty": on_hand_qty}
    payload.update(overrides)
    return payload


def product_order_payload(requested_lines, **overrides) -> dict:
    payload = {
        "mix_profile": DEFAULTS["MIX_PLAN"],
        "investment_ceiling_cents": 60_000,
        "requested_lines": requested_lines,
    }
    payload.update(overrides)
    return payload


def requested_line(product_id, requested_qty):
    return {"product_id": product_id, "requested_qty": requested_qty}


def pledge_payload(credit_account_id, pledged_lines, expected_product_order_version):
    return {
        "credit_account_id": credit_account_id,
        "pledged_lines": pledged_lines,
        "expected_product_order_version": expected_product_order_version,
    }


def pledged_line(product_id, qty):
    return {"product_id": product_id, "qty": qty}
