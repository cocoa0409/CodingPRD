"""Payload factories — one per entity, input fields only."""
import itertools

_seq = itertools.count(1)


def _next() -> int:
    return next(_seq)


DEFAULTS = {
    "LEGAL_NAME": "Test Host",
    "ADDRESS": "1 Test Rd",
    "STATE_CODE": "TX",
    "CATEGORY": "FARM",
    "MEMBER_NAME": "Test Member",
    "MEMBER_STATE": "TX",
    "PLAN_TIER": "PLUS",
    "SITE_LABEL": "S1",
    "SITE_LENGTH": 40,
    "VEHICLE_LENGTH": 30,
    "ARRIVAL_DATE": "2026-06-20",
    "NIGHTS": 2,
    "PARTY_SIZE": 1,
}


def create_host_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "legal_name": f"{DEFAULTS['LEGAL_NAME']} {n}",
        "category": DEFAULTS["CATEGORY"],
        "address_line1": DEFAULTS["ADDRESS"],
        "state_code": DEFAULTS["STATE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_parking_site_payload(**overrides) -> dict:
    defaults = {
        "site_label": DEFAULTS["SITE_LABEL"],
        "site_class": "BACK_IN",
        "max_vehicle_length_feet": DEFAULTS["SITE_LENGTH"],
        "has_electric": False,
        "electric_service_code": "NONE",
        "blocks_sites": "",
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "email": f"member{n}@example.com",
        "full_name": f"{DEFAULTS['MEMBER_NAME']} {n}",
        "plan_tier": DEFAULTS["PLAN_TIER"],
        "home_state_code": DEFAULTS["MEMBER_STATE"],
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(**overrides) -> dict:
    defaults = {
        "vehicle_class": "CLASS_C",
        "length_feet": DEFAULTS["VEHICLE_LENGTH"],
        "self_contained": True,
        "inspection_state_code": DEFAULTS["MEMBER_STATE"],
    }
    defaults.update(overrides)
    return defaults


def create_window_payload(host_id, **overrides) -> dict:
    defaults = {
        "host_id": host_id,
        "kind": "EVENT",
        "label": "Test Window",
        "start_date": "2026-06-01",
        "end_date": "2026-06-30",
        "capacity_override": 20,
        "reserved_sites": 15,
    }
    defaults.update(overrides)
    return defaults


def create_stay_request_payload(host_id, member_id, vehicle_id, **overrides) -> dict:
    defaults = {
        "host_id": host_id,
        "member_id": member_id,
        "vehicle_id": vehicle_id,
        "arrival_date": DEFAULTS["ARRIVAL_DATE"],
        "nights": DEFAULTS["NIGHTS"],
        "party_size": DEFAULTS["PARTY_SIZE"],
        "electric_request_code": "NONE",
        "request_depth": 0,
        "same_day_hold": False,
    }
    defaults.update(overrides)
    return defaults


def create_review_payload(**overrides) -> dict:
    defaults = {
        "rating": 5,
        "public_note": "A perfectly ordinary note.",
        "advance_notice_hours": 240,
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(member_id, host_id, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "host_id": host_id,
        "severity": "MAJOR",
        "narrative": "The rig discharged waste onto the pad.",
    }
    defaults.update(overrides)
    return defaults


def create_patronization_payload(host_id, member_id, stay_request_id,
                                 expected_request_version, **overrides) -> dict:
    defaults = {
        "host_id": host_id,
        "member_id": member_id,
        "stay_request_id": stay_request_id,
        "receipt_cents": 10000,
        "purchase_kind": "TASTING",
        "expected_request_version": expected_request_version,
    }
    defaults.update(overrides)
    return defaults


def create_disposition_payload(**overrides) -> dict:
    defaults = {
        "action": "UPHOLD",
        "decided_by_display_name": "Review Panel",
        "requested_decision": "UPHOLD",
    }
    defaults.update(overrides)
    return defaults


def create_host_decision_payload(expected_host_version, **overrides) -> dict:
    defaults = {
        "action": "APPROVE",
        "reason": "declared",
        "expected_host_version": expected_host_version,
    }
    defaults.update(overrides)
    return defaults


def create_stay_decision_payload(expected_host_version, **overrides) -> dict:
    defaults = {
        "decision": "CONFIRM",
        "expected_host_version": expected_host_version,
    }
    defaults.update(overrides)
    return defaults