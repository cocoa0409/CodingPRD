"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "CATEGORY_NAME": "Vacuums",
    "REFRESH_CYCLE_MONTHS": 24,
    "MARKET_SHARE_PCT": 50,
    "MEMBER_INTEREST_PCT": 50,
    "FISCAL_YEAR": 2026,
    "BUDGET_CENTS": 500000,
    "PROTOCOL_CODE": "PROTO-01",
    "REPEAT_MIN": 1,
    "PERF_WEIGHT": 60,
    "RELIABILITY_WEIGHT": 30,
    "MODEL_LABEL": "ModelX",
    "REQUIRED_UNITS": 1,
    "BUYER_ALIAS": "alias-1",
    "RETAILER_NAME": "BigBox Retail",
    "RECEIPT_DOC_REF": "RCPT-1",
    "UNIT_PRICE_CENTS": 1000,
    "QTY": 1,
    "TAX_RATE_BP": 0,
    "SHIPPING_CENTS": 0,
    "METRIC_CODE": "WASH",
    "VALUE_NUM": 90,
    "FIELD_START": "2026-09-01T00:00:00Z",
    "FIELD_END": "2026-09-05T00:00:00Z",
    "MIN_RESPONSES": 1,
    "EMBARGO_UNTIL": "2026-09-01T00:00:00Z",
    "VERSION_NOTE": "v1",
    "SEVERITY": "MAJOR",
    "DESCRIPTION_TEXT": "finding narrative",
    "HAZARD_FLAG": False,
    "EMAIL": "member@example.com",
    "FULL_NAME": "Test Member",
    "PLAN_TIER": "DIGITAL",
    "TERM_START": "2026-09-01T00:00:00Z",
    "TERM_END": "2027-09-01T00:00:00Z",
    "MANUFACTURER_NAME": "Acme",
    "BODY_TEXT": "We dispute the method.",
}


def create_product_category_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CATEGORY_NAME"],
        "refresh_cycle_months": DEFAULTS["REFRESH_CYCLE_MONTHS"],
        "market_share_pct": DEFAULTS["MARKET_SHARE_PCT"],
        "member_interest_pct": DEFAULTS["MEMBER_INTEREST_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_test_program_payload(category_id, **overrides) -> dict:
    defaults = {
        "category_id": category_id,
        "fiscal_year": DEFAULTS["FISCAL_YEAR"],
        "budget_cents": DEFAULTS["BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_lab_protocol_payload(category_id, **overrides) -> dict:
    defaults = {
        "category_id": category_id,
        "protocol_code": DEFAULTS["PROTOCOL_CODE"],
        "measurement_repeat_min": DEFAULTS["REPEAT_MIN"],
        "perf_weight_pct": DEFAULTS["PERF_WEIGHT"],
        "reliability_weight_pct": DEFAULTS["RELIABILITY_WEIGHT"],
    }
    defaults.update(overrides)
    return defaults


def create_test_sample_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "model_label": DEFAULTS["MODEL_LABEL"],
        "required_units": DEFAULTS["REQUIRED_UNITS"],
    }
    defaults.update(overrides)
    return defaults


def create_po_line_payload(sample_id, **overrides) -> dict:
    defaults = {
        "sample_id": sample_id,
        "unit_price_cents": DEFAULTS["UNIT_PRICE_CENTS"],
        "qty": DEFAULTS["QTY"],
        "tax_rate_bp": DEFAULTS["TAX_RATE_BP"],
    }
    defaults.update(overrides)
    return defaults


def create_purchase_order_payload(program_id, lines, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "buyer_alias": DEFAULTS["BUYER_ALIAS"],
        "retailer_name": DEFAULTS["RETAILER_NAME"],
        "receipt_doc_ref": DEFAULTS["RECEIPT_DOC_REF"],
        "shipping_cents": DEFAULTS["SHIPPING_CENTS"],
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_measurement_payload(sample_id, **overrides) -> dict:
    defaults = {
        "sample_id": sample_id,
        "unit_index": 1,
        "metric_code": DEFAULTS["METRIC_CODE"],
        "value_num": DEFAULTS["VALUE_NUM"],
    }
    defaults.update(overrides)
    return defaults


def create_survey_wave_payload(category_id, **overrides) -> dict:
    defaults = {
        "category_id": category_id,
        "field_start": DEFAULTS["FIELD_START"],
        "field_end": DEFAULTS["FIELD_END"],
        "min_responses": DEFAULTS["MIN_RESPONSES"],
    }
    defaults.update(overrides)
    return defaults


def create_rating_publication_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "embargo_until": DEFAULTS["EMBARGO_UNTIL"],
        "version_note": DEFAULTS["VERSION_NOTE"],
    }
    defaults.update(overrides)
    return defaults


def create_safety_finding_payload(program_id, sample_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "sample_id": sample_id,
        "severity": DEFAULTS["SEVERITY"],
        "description_text": DEFAULTS["DESCRIPTION_TEXT"],
        "hazard_flag": DEFAULTS["HAZARD_FLAG"],
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    defaults = {
        "email": DEFAULTS["EMAIL"],
        "full_name": DEFAULTS["FULL_NAME"],
    }
    defaults.update(overrides)
    return defaults
