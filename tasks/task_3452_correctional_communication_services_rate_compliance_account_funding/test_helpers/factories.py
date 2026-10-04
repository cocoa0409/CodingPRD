"""Payload factories — one per creatable entity, input fields only.

Defaults form a coherent, cap-compliant standard environment (the same
pricing/cap geometry the test scenarios exercise: per-minute rates at or
below the jurisdiction cap, connection/message/video fees within ancillary
and connection caps, commission within the commission cap). Override any
field via **overrides.

Booking numbers and E.164 numbers are counter-unique so several inmates or
recipients can coexist inside one test without tripping uniqueness rules.
"""
import itertools

from .constants import CLOCK_DEFAULT_UTC

_booking_seq = itertools.count(1)
_e164_seq = itertools.count(1)
_owner_seq = itertools.count(1)

CAP_DEFAULTS = {
    "state_code": "ST",
    "max_per_minute_cents": 25,
    "max_connection_fee_cents": 300,
    "max_ancillary_fee_cents": 500,
    "max_deposit_fee_cents": 500,
    "max_commission_pct": 0.6,
    "refund_method": "SIMPLE_BALANCE",
    "dormancy_days": 30,
    "claim_window_days": 45,
}

FACILITY_DEFAULTS = {
    "name": "Test Facility",
    "state_code": "ST",
    "video_booth_count": 2,
    "video_turnover_minutes": 10,
    "max_session_minutes": 30,
    "visiting_open_minutes": 480,
    "visiting_close_minutes": 1200,
    "daily_session_limit_per_inmate": 2,
}

CONTRACT_DEFAULTS = {
    "commission_pct": 0.5,
    "commission_basis": "GROSS",
    "deposit_fee_cents": 25,
    "closure_fee_cents": 100,
    "effective_from": CLOCK_DEFAULT_UTC,
}

SCHEDULE_DEFAULTS = {
    "local_per_minute_cents": 18,
    "intrastate_per_minute_cents": 21,
    "interstate_per_minute_cents": 25,
    "international_per_minute_cents": 25,
    "connection_fee_cents": 200,
    "message_price_cents": 15,
    "video_session_fee_cents": 500,
}

ACCOUNT_DEFAULTS = {
    "funding_model": "PREPAID",
    "owner_name": "Test Family",
    "owner_contact": "family@example.com",
}

RECIPIENT_DEFAULTS = {
    "label": "Mom",
    "relationship_type": "FAMILY",
}


def _unique_booking_number():
    return f"B-{next(_booking_seq):04d}"


def _unique_e164():
    return f"+1555{next(_e164_seq):07d}"


def create_regulatory_cap_payload(**overrides) -> dict:
    defaults = dict(CAP_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_facility_payload(**overrides) -> dict:
    defaults = dict(FACILITY_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_contract_payload(facility_id, **overrides) -> dict:
    defaults = dict(CONTRACT_DEFAULTS)
    defaults["facility_id"] = facility_id
    defaults.update(overrides)
    return defaults


def create_rate_schedule_payload(**overrides) -> dict:
    defaults = dict(SCHEDULE_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_inmate_payload(facility_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "booking_number": _unique_booking_number(),
        "full_name": "Test Inmate",
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(facility_id, inmate_id, **overrides) -> dict:
    seq = next(_owner_seq)
    defaults = dict(ACCOUNT_DEFAULTS)
    defaults.update(
        {
            "facility_id": facility_id,
            "inmate_id": inmate_id,
            "owner_name": f"Test Family {seq}",
            "owner_contact": f"family{seq}@example.com",
        }
    )
    defaults.update(overrides)
    return defaults


def create_deposit_payload(amount_cents=1000, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_recipient_number_payload(account_id, **overrides) -> dict:
    defaults = dict(RECIPIENT_DEFAULTS)
    defaults.update({"account_id": account_id, "e164_number": _unique_e164()})
    defaults.update(overrides)
    return defaults


def create_verify_payload(verification_code, consent_to_recording=True) -> dict:
    return {
        "verification_code": verification_code,
        "consent_to_recording": consent_to_recording,
    }


def create_privilege_decision_payload(decision="VERIFY", note=None) -> dict:
    payload = {"decision": decision}
    if note is not None:
        payload["note"] = note
    return payload


def create_call_payload(account_id, inmate_id, recipient_number_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "inmate_id": inmate_id,
        "recipient_number_id": recipient_number_id,
        "call_type": "LOCAL",
    }
    defaults.update(overrides)
    return defaults


def create_video_session_payload(
    facility_id, inmate_id, account_id, scheduled_start, scheduled_end, **overrides
) -> dict:
    defaults = {
        "facility_id": facility_id,
        "inmate_id": inmate_id,
        "account_id": account_id,
        "visitor_name": "Test Visitor",
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    defaults.update(overrides)
    return defaults


def create_message_payload(account_id, inmate_id, body_text="hello", **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "inmate_id": inmate_id,
        "body_text": body_text,
    }
    defaults.update(overrides)
    return defaults


def create_review_payload(decision="APPROVE", review_note=None) -> dict:
    payload = {"decision": decision}
    if review_note is not None:
        payload["review_note"] = review_note
    return payload


def create_refund_decision_payload(decision="APPROVE", denial_reason=None) -> dict:
    payload = {"decision": decision}
    if denial_reason is not None:
        payload["denial_reason"] = denial_reason
    return payload


def create_complaint_payload(facility_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "category": "RATE_DISPUTE",
        "description": "The billed rate does not match the disclosed rate.",
    }
    defaults.update(overrides)
    return defaults


def create_cap_amendment_payload(expected_regulatory_cap_version, **overrides) -> dict:
    defaults = {"expected_regulatory_cap_version": expected_regulatory_cap_version}
    defaults.update(overrides)
    return defaults


__all__ = [
    "CAP_DEFAULTS",
    "FACILITY_DEFAULTS",
    "CONTRACT_DEFAULTS",
    "SCHEDULE_DEFAULTS",
    "ACCOUNT_DEFAULTS",
    "RECIPIENT_DEFAULTS",
    "create_regulatory_cap_payload",
    "create_facility_payload",
    "create_contract_payload",
    "create_rate_schedule_payload",
    "create_inmate_payload",
    "create_account_payload",
    "create_deposit_payload",
    "create_recipient_number_payload",
    "create_verify_payload",
    "create_privilege_decision_payload",
    "create_call_payload",
    "create_video_session_payload",
    "create_message_payload",
    "create_review_payload",
    "create_refund_decision_payload",
    "create_complaint_payload",
    "create_cap_amendment_payload",
]
