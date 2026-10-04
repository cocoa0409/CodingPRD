"""Payload factories — one per entity, input fields only (PRD section 4)."""

DEFAULTS = {
    "COLOR_NAME": "Cerulean",
    "COLOR_HEX": "#02A4D3",
    "PIGMENT_NAME": "Phthalo Blue",
    "SUPPLIER_NAME": "PigmentCo",
    "RECEIVED_KG": 500,
    "SPEC_NAME": "Cerulean 8-box",
    "WHOLESALE_PRICE_CENTS": 1600,
    "PLANNED_BOXES": 125,
    "RUN_START": "2027-04-15T00:00:00Z",
    "RUN_END": "2027-05-20T00:00:00Z",
    "RETAILER": "MegaMart",
    "SHIP_DATE": "2027-07-15T00:00:00Z",
    "LINE_NAME": "SpaceMovie Box",
    "LICENSOR_ID": "lic-1",
    "TERM_START": "2026-09-01T00:00:00Z",
    "TERM_END": "2028-08-31T23:59:59Z",
    "ROYALTY_RATE": 0.08,
    "VENUE": "Hall A",
    "SESSION_DATE": "2026-10-17T00:00:00Z",
    "BASE_PRICE_CENTS": 2000,
    "CAMPAIGN_OPENS": "2026-09-05T00:00:00Z",
    "CAMPAIGN_CLOSES": "2026-09-20T23:59:59Z",
}


def create_color_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["COLOR_NAME"], "hex_code": DEFAULTS["COLOR_HEX"]}
    defaults.update(overrides)
    return defaults


def create_pigment_batch_payload(**overrides) -> dict:
    defaults = {
        "pigment_name": DEFAULTS["PIGMENT_NAME"],
        "supplier_name": DEFAULTS["SUPPLIER_NAME"],
        "hazard_class": "STANDARD",
        "received_quantity_kg": DEFAULTS["RECEIVED_KG"],
        "certification_mark": "ACMI_AP",
    }
    defaults.update(overrides)
    return defaults


def create_formula_payload(color_id, **overrides) -> dict:
    defaults = {
        "color_id": color_id,
        "intended_use": "CRAYON",
        "pigment_recipe": [{"pigment_name": "Phthalo Blue", "parts": 3}],
    }
    defaults.update(overrides)
    return defaults


def create_vote_campaign_payload(**overrides) -> dict:
    defaults = {
        "kind": "INTRODUCTION",
        "opens_on": DEFAULTS["CAMPAIGN_OPENS"],
        "closes_on": DEFAULTS["CAMPAIGN_CLOSES"],
    }
    defaults.update(overrides)
    return defaults


def create_spec_payload(entries, **overrides) -> dict:
    defaults = {
        "name": DEFAULTS["SPEC_NAME"],
        "kind": "RETAIL",
        "entries": entries,
        "wholesale_price_cents": DEFAULTS["WHOLESALE_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_run_payload(spec_id, batch_id, **overrides) -> dict:
    defaults = {
        "assortment_spec_id": spec_id,
        "pigment_batch_id": batch_id,
        "planned_boxes": DEFAULTS["PLANNED_BOXES"],
        "planned_start_date": DEFAULTS["RUN_START"],
        "planned_end_date": DEFAULTS["RUN_END"],
    }
    defaults.update(overrides)
    return defaults


def create_allocation_payload(spec_id, spec_version, **overrides) -> dict:
    defaults = {
        "assortment_spec_id": spec_id,
        "retailer_name": DEFAULTS["RETAILER"],
        "priority_tier": "PLATINUM",
        "requested_boxes": 10,
        "requested_ship_date": DEFAULTS["SHIP_DATE"],
        "expected_assortment_spec_version": spec_version,
    }
    defaults.update(overrides)
    return defaults


def create_licensed_line_payload(formula_id, **overrides) -> dict:
    defaults = {
        "name": DEFAULTS["LINE_NAME"],
        "licensor_user_id": DEFAULTS["LICENSOR_ID"],
        "formula_id": formula_id,
        "term_start": DEFAULTS["TERM_START"],
        "term_end": DEFAULTS["TERM_END"],
        "royalty_rate": DEFAULTS["ROYALTY_RATE"],
        "royalty_base": "GROSS",
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(**overrides) -> dict:
    defaults = {
        "venue_name": DEFAULTS["VENUE"],
        "session_date": DEFAULTS["SESSION_DATE"],
        "start_minute": 600,
        "duration_minutes": 120,
        "capacity_units": 100,
        "base_price_cents": DEFAULTS["BASE_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_ticket_payload(session_id, **overrides) -> dict:
    defaults = {"session_id": session_id, "kind": "INDIVIDUAL"}
    defaults.update(overrides)
    return defaults


def create_vote_payload(campaign_id, **overrides) -> dict:
    defaults = {"campaign_id": campaign_id, "voter_segment": "KIDS", "choice": "YES"}
    defaults.update(overrides)
    return defaults
