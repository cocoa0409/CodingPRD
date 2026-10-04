"""Payload factories — one per creation endpoint, input fields only (PRD §3)."""

DEFAULTS = {
    "FARM_NAME": "Test Farm",
    "REGION": "IA",
    "PASTURE_SQFT": 21600,
    "BARN_SQFT": 180,
    "NEST_BOX_COUNT": 30,
    "DECLARED_BIRD_COUNT": 140,
    "CONTRACT_BASE_CENTS": 150,
    "CONTRACT_PREMIUM_CENTS": 90,
    "CONTRACT_START": "2026-09-01",
    "CONTRACT_END": "2027-08-31",
    "AUDIT_TYPE": "INITIAL",
    "AUDIT_SCHEDULED_FOR": "2026-09-03T00:00:00Z",
    "AUDIT_COMPLETE_AT": "2026-09-03T09:00:00Z",
    "ROUTE_DATE": "2026-09-08",
    "DRIVER_NAME": "Dale",
    "CAPACITY_CASES": 10,
    "COLLECT_AT": "2026-09-08T10:00:00Z",
    "LAID_START": "2026-09-06",
    "LAID_END": "2026-09-07",
    "PACK_SIZE": "LARGE",
    "RETAILER_NAME": "Heartland Grocers",
    "RETAILER_BANNER": "Heartland",
    "TERMS_NET_DAYS": 60,
    "WEEK_START": "2026-09-07",
    "SEASON": "AUTUMN",
    "WEATHER_SEVERITY": "NONE",
    "ACTUAL_BASE_CENTS": 165,
}


def create_farm_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["FARM_NAME"],
        "region": DEFAULTS["REGION"],
        "pasture_sqft": DEFAULTS["PASTURE_SQFT"],
        "barn_sqft": DEFAULTS["BARN_SQFT"],
        "nest_box_count": DEFAULTS["NEST_BOX_COUNT"],
        "declared_bird_count": DEFAULTS["DECLARED_BIRD_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(expected_farm_version, **overrides) -> dict:
    defaults = {
        "commodity_base_cents_per_dozen": DEFAULTS["CONTRACT_BASE_CENTS"],
        "premium_cents_per_dozen": DEFAULTS["CONTRACT_PREMIUM_CENTS"],
        "start_date": DEFAULTS["CONTRACT_START"],
        "end_date": DEFAULTS["CONTRACT_END"],
        "expected_farm_version": expected_farm_version,
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(**overrides) -> dict:
    defaults = {
        "audit_type": DEFAULTS["AUDIT_TYPE"],
        "scheduled_for": DEFAULTS["AUDIT_SCHEDULED_FOR"],
    }
    defaults.update(overrides)
    return defaults


def complete_audit_payload(outcome="PASSED", findings=None) -> dict:
    payload = {"outcome": outcome}
    if findings is not None:
        payload["findings"] = findings
    return payload


def create_incident_payload(**overrides) -> dict:
    defaults = {
        "severity": "LOW",
        "incident_type": "RECORD_KEEPING",
        "description": "minor log gap found during visit",
    }
    defaults.update(overrides)
    return defaults


def resolve_incident_payload(disposition="NONE", **overrides) -> dict:
    defaults = {"disposition": disposition}
    defaults.update(overrides)
    return defaults


def create_route_payload(**overrides) -> dict:
    defaults = {
        "route_date": DEFAULTS["ROUTE_DATE"],
        "driver_name": DEFAULTS["DRIVER_NAME"],
        "capacity_cases": DEFAULTS["CAPACITY_CASES"],
    }
    defaults.update(overrides)
    return defaults


def add_stop_payload(farm_id, stop_sequence=1, planned_cases=2) -> dict:
    return {
        "farm_id": farm_id,
        "stop_sequence": stop_sequence,
        "planned_cases": planned_cases,
    }


def collect_stop_payload(collected_cases=2, **overrides) -> dict:
    defaults = {
        "collected_cases": collected_cases,
        "laid_start_date": DEFAULTS["LAID_START"],
        "laid_end_date": DEFAULTS["LAID_END"],
    }
    defaults.update(overrides)
    return defaults


def grade_lot_payload(quality_score) -> dict:
    return {"quality_score": quality_score}


def resolve_hold_payload(disposition="RELEASE") -> dict:
    return {"disposition": disposition}


def pack_cartons_payload(carton_count, pack_size=None) -> dict:
    return {
        "carton_count": carton_count,
        "pack_size": pack_size or DEFAULTS["PACK_SIZE"],
    }


def create_retailer_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["RETAILER_NAME"],
        "banner": DEFAULTS["RETAILER_BANNER"],
        "terms_net_days": DEFAULTS["TERMS_NET_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_commitment_payload(retailer_id, farm_id, week_start, committed_dozens) -> dict:
    return {
        "retailer_id": retailer_id,
        "farm_id": farm_id,
        "week_start": week_start,
        "committed_dozens": committed_dozens,
    }


def create_forecast_payload(week_start, season=None, weather_severity=None) -> dict:
    return {
        "week_start": week_start,
        "season": season or DEFAULTS["SEASON"],
        "weather_severity": weather_severity or DEFAULTS["WEATHER_SEVERITY"],
    }


def create_settlement_payload(week_start=None) -> dict:
    return {"week_start": week_start or DEFAULTS["WEEK_START"]}


def finalize_settlement_payload(actual_base_cents=None) -> dict:
    return {
        "actual_commodity_base_cents_per_dozen": (
            actual_base_cents if actual_base_cents is not None else DEFAULTS["ACTUAL_BASE_CENTS"]
        )
    }


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
