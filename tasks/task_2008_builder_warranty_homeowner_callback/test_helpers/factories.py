"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "HOMEOWNER_NAME": "Pat Hale",
    "HOMEOWNER_EMAIL": "pat@example.com",
    "LOT_NUMBER": "L-100",
    "COMMUNITY_NAME": "Cedar Ridge",
    "SALE_PRICE_CENTS": 40_000_000,
    "CLOSING_DATE": "2026-06-01",
    "WARRANTY_PROGRAM": "STANDARD",
    "ITEM_CATEGORY": "PLUMBING",
    "SEVERITY": "STANDARD",
    "DESCRIPTION": "Kitchen supply line leak",
    "COMPANY_NAME": "FlowRight Plumbing",
    "TRADE": "PLUMBING",
    "CONTACT_EMAIL": "dispatch@flowright.example.com",
    "WINDOW_START": "2026-08-10T09:00:00Z",
    "WINDOW_END": "2026-08-10T11:00:00Z",
    "ESTIMATED_COST_CENTS": 150_000,
    "DEFECT_RESPONSIBILITY": "SUBCONTRACTOR",
    "CLAIMED_AMOUNT_CENTS": 900_000,
    "DENIAL_REASON_CODE": "HOMEOWNER_CAUSED",
    "EDUCATION_PACKET_CODE": "EDU-CAULK-01",
}


def create_homeowner_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["HOMEOWNER_NAME"],
        "email": DEFAULTS["HOMEOWNER_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_home_payload(homeowner_id, **overrides) -> dict:
    defaults = {
        "homeowner_id": homeowner_id,
        "lot_number": DEFAULTS["LOT_NUMBER"],
        "community_name": DEFAULTS["COMMUNITY_NAME"],
        "sale_price_cents": DEFAULTS["SALE_PRICE_CENTS"],
        "closing_date": DEFAULTS["CLOSING_DATE"],
        "warranty_program": DEFAULTS["WARRANTY_PROGRAM"],
    }
    defaults.update(overrides)
    return defaults


def create_service_request_payload(home_id, **overrides) -> dict:
    defaults = {
        "home_id": home_id,
        "item_category": DEFAULTS["ITEM_CATEGORY"],
        "severity": DEFAULTS["SEVERITY"],
        "description": DEFAULTS["DESCRIPTION"],
    }
    defaults.update(overrides)
    return defaults


def assess_warrantable_payload(**overrides) -> dict:
    defaults = {"warrantable": True}
    defaults.update(overrides)
    return defaults


def assess_denial_payload(**overrides) -> dict:
    defaults = {
        "warrantable": False,
        "denial_reason_code": DEFAULTS["DENIAL_REASON_CODE"],
        "education_packet_code": DEFAULTS["EDUCATION_PACKET_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_trade_partner_payload(**overrides) -> dict:
    defaults = {
        "company_name": DEFAULTS["COMPANY_NAME"],
        "trade": DEFAULTS["TRADE"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(service_request_id, trade_partner_id, **overrides) -> dict:
    defaults = {
        "service_request_id": service_request_id,
        "trade_partner_id": trade_partner_id,
        "window_start": DEFAULTS["WINDOW_START"],
        "window_end": DEFAULTS["WINDOW_END"],
        "estimated_cost_cents": DEFAULTS["ESTIMATED_COST_CENTS"],
        "defect_responsibility": DEFAULTS["DEFECT_RESPONSIBILITY"],
    }
    defaults.update(overrides)
    return defaults


def create_chargeback_payload(work_order_id, **overrides) -> dict:
    defaults = {"work_order_id": work_order_id}
    defaults.update(overrides)
    return defaults


def create_administrator_claim_payload(service_request_id, **overrides) -> dict:
    defaults = {
        "service_request_id": service_request_id,
        "claimed_amount_cents": DEFAULTS["CLAIMED_AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults
