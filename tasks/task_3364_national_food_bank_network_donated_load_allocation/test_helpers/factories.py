"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "MEMBER_NAME": "Harvest Hope Food Bank",
    "STATE_CODE": "SC",
    "POPULATION": 180_000,
    "STORAGE_CAPACITY": 90_000,
    "REFRIGERATED_CAPACITY": 20_000,
    "TRANSPORT_ABILITY": "REGIONAL",
    "DONOR_NAME": "Midwest Mills Co",
    "COMMITTED_LBS": 500_000,
    "POOL_CENTS": 500_000,
    "LOAD_WEIGHT_LBS": 40_000,
    "LOT_CODE": "LOT-TEST",
    "ORIGIN_ZIP": "44101",
    "DISTANCE_MILES": 620,
    "SHARES_OFFERED": 400,
    "AFFECTED_LBS": 1_000,
    "EXPECTED_WEEKLY_LBS": 1_200,
}


def create_member_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["MEMBER_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
        "food_insecure_population": DEFAULTS["POPULATION"],
        "storage_capacity_lbs": DEFAULTS["STORAGE_CAPACITY"],
        "refrigerated_capacity_lbs": DEFAULTS["REFRIGERATED_CAPACITY"],
        "transport_ability": DEFAULTS["TRANSPORT_ABILITY"],
    }
    payload.update(overrides)
    return payload


def create_donor_agreement_payload(**overrides) -> dict:
    payload = {
        "donor_name": DEFAULTS["DONOR_NAME"],
        "donor_type": "MANUFACTURER",
        "product_category": "DRY_GOODS",
        "committed_lbs": DEFAULTS["COMMITTED_LBS"],
        "freight_subsidy_pool_cents": DEFAULTS["POOL_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_load_payload(donor_agreement_id: str, **overrides) -> dict:
    payload = {
        "donor_agreement_id": donor_agreement_id,
        "product_category": "DRY_GOODS",
        "storage_type": "DRY",
        "weight_lbs": DEFAULTS["LOAD_WEIGHT_LBS"],
        "lot_code": DEFAULTS["LOT_CODE"],
        "origin_zip": DEFAULTS["ORIGIN_ZIP"],
        "destination_region": "MIDWEST",
        "distance_miles": DEFAULTS["DISTANCE_MILES"],
    }
    payload.update(overrides)
    return payload


def create_bid_payload(member_id: str, expected_load_version: int, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "shares_offered": DEFAULTS["SHARES_OFFERED"],
        "preference_rank": 1,
        "can_self_transport": False,
        "expected_load_version": expected_load_version,
    }
    payload.update(overrides)
    return payload


def create_share_grant_payload(member_id: str, expected_member_version: int, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "epoch": "2026-09",
        "expected_member_version": expected_member_version,
    }
    payload.update(overrides)
    return payload


def create_recall_payload(donor_agreement_id: str, **overrides) -> dict:
    payload = {
        "donor_agreement_id": donor_agreement_id,
        "lot_code": DEFAULTS["LOT_CODE"],
        "product_category": "DRY_GOODS",
        "affected_lbs": DEFAULTS["AFFECTED_LBS"],
    }
    payload.update(overrides)
    return payload


def create_audit_payload(member_id: str, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "audit_type": "COMPREHENSIVE",
        "storage_score": 85,
        "distribution_score": 85,
        "reporting_score": 85,
    }
    payload.update(overrides)
    return payload


def create_store_program_payload(member_id: str, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "store_name": "Kroger Dublin",
        "store_chain": "Kroger",
        "pickup_frequency": "WEEKLY",
        "expected_weekly_lbs": DEFAULTS["EXPECTED_WEEKLY_LBS"],
    }
    payload.update(overrides)
    return payload


def create_pickup_payload(scheduled_date: str, window_start: str, window_end: str) -> dict:
    return {
        "scheduled_date": scheduled_date,
        "window_start": window_start,
        "window_end": window_end,
    }


def create_freight_decision_payload(decision: str = "COVERED", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_dispatch_payload(delivery_window_start: str, delivery_window_end: str) -> dict:
    return {
        "delivery_window_start": delivery_window_start,
        "delivery_window_end": delivery_window_end,
    }
