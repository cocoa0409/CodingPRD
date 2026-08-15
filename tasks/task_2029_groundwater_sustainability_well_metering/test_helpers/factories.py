"""Payload factories — one per entity, input fields only (PRD §3/§4)."""

DEFAULTS = {
    "HOLDER_NAME": "Test Pumper",
    "ACCOUNT_TYPE": "AGRICULTURAL",
    "BASE_ALLOCATION_AF": 100.000,
    "WELL_TYPE": "PRODUCTION",
    "LOCATION_DESCRIPTION": "Parcel 1",
    "WATER_YEAR": 2026,
    "MONTH": 6,
    "REPORTED_AF": 10.000,
    "QUANTITY_AF": 10.000,
    "UNIT_PRICE_CENTS": 9000,
    "EFFECTIVE_START_DATE": "2026-08-01",
    "EFFECTIVE_END_DATE": "2026-10-01",
    "MEASURED_AT": "2026-07-15T08:00:00Z",
    "DEPTH_TO_WATER_FT": 90.0,
    "COLLECTOR_NAME": "Field Tech",
    "PENALTY_REASON": "LATE_REPORT",
    "APPEAL_GROUNDS": "disputed charge",
}


def create_account_payload(**overrides) -> dict:
    payload = {
        "holder_name": DEFAULTS["HOLDER_NAME"],
        "account_type": DEFAULTS["ACCOUNT_TYPE"],
        "base_allocation_af": DEFAULTS["BASE_ALLOCATION_AF"],
    }
    payload.update(overrides)
    return payload


def create_well_payload(account_id, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "well_type": DEFAULTS["WELL_TYPE"],
        "location_description": DEFAULTS["LOCATION_DESCRIPTION"],
    }
    payload.update(overrides)
    return payload


def create_extraction_report_payload(well_id, **overrides) -> dict:
    payload = {
        "well_id": well_id,
        "water_year": DEFAULTS["WATER_YEAR"],
        "month": DEFAULTS["MONTH"],
        "reported_af": DEFAULTS["REPORTED_AF"],
    }
    payload.update(overrides)
    return payload


def create_transfer_order_payload(seller_account_id, buyer_account_id, **overrides) -> dict:
    payload = {
        "seller_account_id": seller_account_id,
        "buyer_account_id": buyer_account_id,
        "quantity_af": DEFAULTS["QUANTITY_AF"],
        "unit_price_cents": DEFAULTS["UNIT_PRICE_CENTS"],
        "effective_start_date": DEFAULTS["EFFECTIVE_START_DATE"],
        "effective_end_date": DEFAULTS["EFFECTIVE_END_DATE"],
    }
    payload.update(overrides)
    return payload


def create_monitoring_reading_payload(well_id, **overrides) -> dict:
    payload = {
        "well_id": well_id,
        "measured_at": DEFAULTS["MEASURED_AT"],
        "depth_to_water_ft": DEFAULTS["DEPTH_TO_WATER_FT"],
        "collector_name": DEFAULTS["COLLECTOR_NAME"],
    }
    payload.update(overrides)
    return payload


def create_penalty_assessment_payload(account_id, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "reason": DEFAULTS["PENALTY_REASON"],
        "water_year": DEFAULTS["WATER_YEAR"],
    }
    payload.update(overrides)
    return payload


def create_annual_state_report_payload(**overrides) -> dict:
    payload = {"water_year": DEFAULTS["WATER_YEAR"]}
    payload.update(overrides)
    return payload


def close_water_year_payload(**overrides) -> dict:
    payload = {"water_year": DEFAULTS["WATER_YEAR"]}
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
