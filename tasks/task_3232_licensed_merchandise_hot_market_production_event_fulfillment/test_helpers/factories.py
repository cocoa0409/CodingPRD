"""Payload factories - one per entity, input fields only."""

DEFAULTS = {
    "LICENSOR_NAME": "National Basketball League",
    "LEAGUE_CODE": "NBL",
    "ROYALTY_RATE_PCT": 0.1,
    "MINIMUM_GUARANTEE_CENTS": 100000,
    "TEAM_CODE": "ATL",
    "DESIGN_NAME": "Test Design",
    "GARMENT_SKU": "TRACTOR",
    "DEMAND_QTY": 5000,
    "UNIT_COST_CENTS": 900,
    "WIN_PROBABILITY_PCT": 0.5,
    "DESTINATION_CODE": "ECOM-ATL-1",
    "RUSH_SLA_HOURS": 24,
    "DETECTED_AT": "2026-09-01T00:00:00Z",
    "VENUE_CODE": "ATL_POPUP",
    "ONLINE_LISTING_ID": "UNVERIFIED-LIST-1",
}


def create_licensor_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["LICENSOR_NAME"],
        "league_code": DEFAULTS["LEAGUE_CODE"],
        "royalty_rate_pct": DEFAULTS["ROYALTY_RATE_PCT"],
        "minimum_guarantee_cents": DEFAULTS["MINIMUM_GUARANTEE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_design_payload(licensor_id, **overrides) -> dict:
    payload = {
        "licensor_id": licensor_id,
        "team_code": DEFAULTS["TEAM_CODE"],
        "garment_sku": DEFAULTS["GARMENT_SKU"],
        "design_name": DEFAULTS["DESIGN_NAME"],
    }
    payload.update(overrides)
    return payload


def create_production_order_payload(licensor_id, design_id, **overrides) -> dict:
    payload = {
        "licensor_id": licensor_id,
        "design_id": design_id,
        "team_code": DEFAULTS["TEAM_CODE"],
        "trigger_type": "STANDARD",
        "expected_demand_qty": DEFAULTS["DEMAND_QTY"],
        "unit_cost_cents": DEFAULTS["UNIT_COST_CENTS"],
    }
    payload.update(overrides)
    return payload


def author_layers_payload(expected_production_order_version, layers, **overrides) -> dict:
    payload = {
        "expected_production_order_version": expected_production_order_version,
        "layers": layers,
    }
    payload.update(overrides)
    return payload


def layer_spec(print_type="BASE", quantity=20, **overrides) -> dict:
    spec = {"print_type": print_type, "quantity": quantity}
    spec.update(overrides)
    return spec


def create_print_capacity_payload(**overrides) -> dict:
    payload = {
        "city_code": "ATL",
        "print_type": "BASE",
        "window_start": "2026-09-01T01:00:00Z",
        "window_end": "2026-09-02T01:00:00Z",
        "capacity_qty": 40,
        "rush_sla_hours": DEFAULTS["RUSH_SLA_HOURS"],
    }
    payload.update(overrides)
    return payload


def reserve_capacity_payload(print_capacity_id, **overrides) -> dict:
    payload = {
        "print_capacity_id": print_capacity_id,
        "quantity": 20,
        "needed_by": "2026-09-02T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_fulfillment_order_payload(production_order_id, **overrides) -> dict:
    payload = {
        "production_order_id": production_order_id,
        "channel": "ECOM",
        "destination_code": DEFAULTS["DESTINATION_CODE"],
        "quantity": 20,
    }
    payload.update(overrides)
    return payload


def create_counterfeit_report_payload(licensor_id, **overrides) -> dict:
    payload = {
        "licensor_id": licensor_id,
        "venue_code": DEFAULTS["VENUE_CODE"],
        "online_listing_id": DEFAULTS["ONLINE_LISTING_ID"],
        "unit_count": 100,
        "detected_at": DEFAULTS["DETECTED_AT"],
    }
    payload.update(overrides)
    return payload