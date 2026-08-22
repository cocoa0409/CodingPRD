"""Payload factories — one per write endpoint, input fields only."""

from .constants import TEST_DEFAULTS

_COUNTER = {"n": 0}


def _next() -> int:
    _COUNTER["n"] += 1
    return _COUNTER["n"]


def agency_payload(**overrides) -> dict:
    payload = {
        "name": f"Test Partner Agency {_next()}",
        "county": TEST_DEFAULTS["AGENCY_COUNTY"],
        "quarterly_voucher_quota": TEST_DEFAULTS["QUOTA"],
    }
    payload.update(overrides)
    return payload


def client_payload(agency_id: str, **overrides) -> dict:
    payload = {
        "agency_id": agency_id,
        "household_size": TEST_DEFAULTS["HOUSEHOLD_SIZE"],
        "county": TEST_DEFAULTS["CLIENT_COUNTY"],
        "has_infant": False,
    }
    payload.update(overrides)
    return payload


def truck_payload(**overrides) -> dict:
    payload = {
        "label": f"BOX-{_next()}",
        "capacity_cubic_feet": TEST_DEFAULTS["TRUCK_CAPACITY_CF"],
        "home_county": "CENTRAL",
        "crew_minimum": TEST_DEFAULTS["CREW_MINIMUM"],
    }
    payload.update(overrides)
    return payload


def volunteer_payload(**overrides) -> dict:
    payload = {
        "name": f"Test Volunteer {_next()}",
        "county": "CENTRAL",
        "lift_certified": True,
    }
    payload.update(overrides)
    return payload


def referral_payload(client_id: str, agency_id: str, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "agency_id": agency_id,
        "requested_categories": ["BED"],
        "urgency": "ROUTINE",
        "home_visit_completed": True,
        "bed_bug_attestation": True,
    }
    payload.update(overrides)
    return payload


def voucher_line_payload(category: str, quantity_requested: int = 1,
                         min_condition: str = "B") -> dict:
    return {
        "category": category,
        "quantity_requested": quantity_requested,
        "min_condition": min_condition,
    }


def voucher_payload(referral_id: str, lines=None, **overrides) -> dict:
    payload = {
        "referral_id": referral_id,
        "lines": lines if lines is not None else [voucher_line_payload("BED")],
    }
    payload.update(overrides)
    return payload


def donation_item_payload(category: str, declared_condition: str = "B",
                          soft_surface: bool = False,
                          cubic_feet: float = 30.0) -> dict:
    return {
        "category": category,
        "declared_condition": declared_condition,
        "soft_surface": soft_surface,
        "cubic_feet": cubic_feet,
    }


def donation_offer_payload(items=None, **overrides) -> dict:
    payload = {
        "donor_name": f"Test Donor {_next()}",
        "donor_phone": "555-0100",
        "pickup_county": "CENTRAL",
        "pickup_window_start": TEST_DEFAULTS["PICKUP_WINDOW_START"],
        "pickup_window_end": TEST_DEFAULTS["PICKUP_WINDOW_END"],
        "items": items if items is not None else [donation_item_payload("BED")],
    }
    payload.update(overrides)
    return payload


def inspection_payload(item_id: str, graded_condition: str = "B",
                       live_pest_observed: bool = False) -> dict:
    return {
        "item_id": item_id,
        "graded_condition": graded_condition,
        "live_pest_observed": live_pest_observed,
    }


def delivery_run_payload(truck_id: str, **overrides) -> dict:
    payload = {
        "truck_id": truck_id,
        "service_date": TEST_DEFAULTS["RUN_SERVICE_DATE"],
        "window_start": TEST_DEFAULTS["RUN_WINDOW_START"],
        "window_end": TEST_DEFAULTS["RUN_WINDOW_END"],
        "county": "CENTRAL",
    }
    payload.update(overrides)
    return payload


def delivery_stop_payload(voucher_id: str, sequence: int,
                          expected_run_version: int) -> dict:
    return {
        "voucher_id": voucher_id,
        "sequence": sequence,
        "expected_run_version": expected_run_version,
    }


def crew_assignment_payload(volunteer_id: str, role_on_crew: str = "DRIVER") -> dict:
    return {"volunteer_id": volunteer_id, "role_on_crew": role_on_crew}


def allocate_payload(expected_voucher_version: int) -> dict:
    return {"expected_voucher_version": expected_voucher_version}


def fee_settlement_payload(action: str, amount_cents=None) -> dict:
    payload = {"action": action}
    if amount_cents is not None:
        payload["amount_cents"] = amount_cents
    return payload


def stop_outcome_payload(outcome: str, pest_observed_at_residence=None) -> dict:
    payload = {"outcome": outcome}
    if pest_observed_at_residence is not None:
        payload["pest_observed_at_residence"] = pest_observed_at_residence
    return payload


def review_payload(decision: str, note=None) -> dict:
    payload = {"decision": decision}
    if note is not None:
        payload["note"] = note
    return payload


def run_cycle_payload(advance_quota_epoch=None) -> dict:
    payload = {}
    if advance_quota_epoch is not None:
        payload["advance_quota_epoch"] = advance_quota_epoch
    return payload
