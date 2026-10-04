"""Payload factories — one per entity, input fields only."""
from .constants import (
    DEFAULT_DWELL_CAPACITY_MINUTES,
    DEFAULT_LOAD_BAYS_TOTAL,
    DEFAULT_WAIVER_TERM_DAYS,
)

DEFAULTS = {
    "STORE_NAME": "Ozark Flagship",
    "STATE_CODE": "MO",
    "DEALER_LICENSE_NO": "MO-DLR-4417",
    "MEMBER_EMAIL": "member@example.com",
    "MEMBER_FULL_NAME": "Test Member",
    "STOCK_NO": "BU-9001",
    "MODEL_NAME": "Angler 190",
    "HULL_ID_NO": "HIN9001AA000",
    "AGENT_USER_ID": "clerk_4471",
    "UNDERWRITER_USER_ID": "uw_2201",
    "REMITTANCE_WINDOW_START": "2026-09-01T00:00:00Z",
    "REMITTANCE_WINDOW_END": "2026-09-30T00:00:00Z",
}


def create_store_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["STORE_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
        "dealer_license_no": DEFAULTS["DEALER_LICENSE_NO"],
        "dwell_capacity_minutes": DEFAULT_DWELL_CAPACITY_MINUTES,
        "load_bays_total": DEFAULT_LOAD_BAYS_TOTAL,
    }
    payload.update(overrides)
    return payload


def create_member_payload(**overrides) -> dict:
    payload = {
        "email": DEFAULTS["MEMBER_EMAIL"],
        "full_name": DEFAULTS["MEMBER_FULL_NAME"],
        "donation_opt_in": False,
    }
    payload.update(overrides)
    return payload


def create_attraction_payload(**overrides) -> dict:
    payload = {
        "attraction_type": "AQUARIUM",
        "capacity_units": 40,
        "dwell_cost_minutes": 30,
    }
    payload.update(overrides)
    return payload


def create_waiver_payload(member_id: str, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "activity_scope": "ARCHERY_RANGE",
        "signed_at_utc": "2026-08-01T00:00:00Z",
        "waiver_term_days": DEFAULT_WAIVER_TERM_DAYS,
    }
    payload.update(overrides)
    return payload


def create_session_payload(attraction_id: str, member_id: str, **overrides) -> dict:
    payload = {
        "attraction_id": attraction_id,
        "member_id": member_id,
        "session_kind": "GENERAL_ADMISSION",
        "party_size": 2,
        "slot_start_utc": "2026-11-01T10:00:00Z",
        "slot_end_utc": "2026-11-01T11:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_boat_unit_payload(**overrides) -> dict:
    payload = {
        "stock_no": DEFAULTS["STOCK_NO"],
        "model_name": DEFAULTS["MODEL_NAME"],
        "unit_price_cents": 9_000_000,
        "motor_price_cents": 1_800_000,
        "trailer_price_cents": 350_000,
        "unit_condition": "NEW",
        "hull_id_no": DEFAULTS["HULL_ID_NO"],
    }
    payload.update(overrides)
    return payload


def create_appraisal_payload(member_id: str, boat_unit_id: str, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "boat_unit_id": boat_unit_id,
        "offer_amount_cents": 50_000,
    }
    payload.update(overrides)
    return payload


def create_title_filing_payload(boat_unit_id: str, **overrides) -> dict:
    payload = {
        "boat_unit_id": boat_unit_id,
        "filing_kind": "BOAT_TITLE",
        "state_code": DEFAULTS["STATE_CODE"],
    }
    payload.update(overrides)
    return payload


def create_deal_payload(member_id: str, boat_unit_id: str, **overrides) -> dict:
    payload = {"member_id": member_id, "boat_unit_id": boat_unit_id}
    payload.update(overrides)
    return payload


def create_service_order_payload(boat_unit_id: str, **overrides) -> dict:
    payload = {
        "boat_unit_id": boat_unit_id,
        "order_kind": "RIGGING",
        "promised_lead_days": 5,
    }
    payload.update(overrides)
    return payload


def create_service_intake_payload(member_id: str, service_order_id: str, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "service_order_id": service_order_id,
        "intake_kind": "OUTFITTING",
        "specimen_quantity": 1,
        "quoted_lead_days": 20,
        "deposit_cents": 5_000,
    }
    payload.update(overrides)
    return payload


def create_permit_sale_payload(member_id: str, batch_id: str, batch_version: int,
                               **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "permit_type": "FISHING",
        "residency_class": "RESIDENT",
        "term_days": 7,
        "land_access_units": 0,
        "agent_user_id": DEFAULTS["AGENT_USER_ID"],
        "permit_remit_batch_id": batch_id,
        "expected_remit_batch_version": batch_version,
    }
    payload.update(overrides)
    return payload


def create_remit_batch_payload(**overrides) -> dict:
    payload = {
        "window_start_utc": DEFAULTS["REMITTANCE_WINDOW_START"],
        "window_end_utc": DEFAULTS["REMITTANCE_WINDOW_END"],
    }
    payload.update(overrides)
    return payload


def create_club_card_application_payload(member_id: str, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "card_product": "REWARDS",
        "donation_match_bps": 2_000,
        "underwriter_user_id": DEFAULTS["UNDERWRITER_USER_ID"],
    }
    payload.update(overrides)
    return payload


def create_point_event_payload(member_id: str, **overrides) -> dict:
    payload = {"member_id": member_id, "event_kind": "AWARD", "points_delta": 100}
    payload.update(overrides)
    return payload


def create_event_offering_payload(**overrides) -> dict:
    payload = {
        "offering_kind": "SEMINAR",
        "title": "Cold Water Safety",
        "starts_at_utc": "2026-10-01T10:00:00Z",
        "ends_at_utc": "2026-10-01T11:00:00Z",
        "registration_cap": 30,
    }
    payload.update(overrides)
    return payload


def create_event_registration_payload(member_id: str, **overrides) -> dict:
    payload = {"member_id": member_id, "seats": 2}
    payload.update(overrides)
    return payload


def create_bay_booking_payload(member_id: str, service_order_id: str, **overrides) -> dict:
    payload = {
        "bay_no": 1,
        "member_id": member_id,
        "service_order_id": service_order_id,
        "booked_start_utc": "2026-12-01T09:00:00Z",
        "booked_end_utc": "2026-12-01T10:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_order_fulfillment_payload(member_id: str, pre_service_order_id: str,
                                     booking_id: str, booking_version: int,
                                     **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "order_kind": "OVERSIZE_CARRYOUT",
        "pre_service_order_id": pre_service_order_id,
        "booking_id": booking_id,
        "expected_booking_version": booking_version,
    }
    payload.update(overrides)
    return payload


def create_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}