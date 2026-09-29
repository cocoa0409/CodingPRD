"""Payload factories — one per entity, input fields only.

Money is always emitted as a JSON integer number of cents, never a string.
Instant-bearing fields are always emitted as full ISO 8601 UTC instants, never
as a bare calendar date.
"""

from .constants import PREREG_CLOSE_AT, PREREG_OPEN_AT


def campaign_payload(**overrides) -> dict:
    payload = {
        "name": "Fiberhood 2026",
        "city": "Aurora",
        "prereg_window_open_at": PREREG_OPEN_AT,
        "prereg_window_close_at": PREREG_CLOSE_AT,
        "default_threshold_pct": 10.0,
        "deposit_amount_cents": 1000,
    }
    payload.update(overrides)
    return payload


def build_zone_payload(campaign_id: str, **overrides) -> dict:
    payload = {
        "campaign_id": campaign_id,
        "name": "Zone Alpha",
        "zone_code": "A1",
        "household_count": 10,
    }
    payload.update(overrides)
    return payload


def service_address_payload(build_zone_id: str, **overrides) -> dict:
    payload = {
        "build_zone_id": build_zone_id,
        "street_address": "1 Elm St",
        "dwelling_type": "SINGLE_FAMILY",
        "unit_count": 1,
        "distance_to_node_m": 100,
    }
    payload.update(overrides)
    return payload


def mdu_address_payload(build_zone_id: str, **overrides) -> dict:
    payload = {
        "build_zone_id": build_zone_id,
        "street_address": "500 Birch Tower",
        "dwelling_type": "MDU",
        "unit_count": 24,
        "distance_to_node_m": 80,
    }
    payload.update(overrides)
    return payload


def account_payload(**overrides) -> dict:
    payload = {
        "full_name": "Ann Reyes",
        "email": "ann@example.com",
        "phone": "+13035550101",
        "account_type": "RESIDENT",
    }
    payload.update(overrides)
    return payload


def owner_account_payload(**overrides) -> dict:
    payload = {
        "full_name": "Birch Tower LLC",
        "email": "owner@birch.example.com",
        "phone": "+13035550199",
        "account_type": "PROPERTY_OWNER",
    }
    payload.update(overrides)
    return payload


def serviceability_payload(serviceability: str = "SERVICEABLE", **overrides) -> dict:
    payload = {"serviceability": serviceability}
    payload.update(overrides)
    return payload


def unserved_exception_payload(action: str, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def mdu_agreement_payload(
    service_address_id: str, owner_account_id: str, **overrides
) -> dict:
    payload = {
        "service_address_id": service_address_id,
        "owner_account_id": owner_account_id,
        "access_fee_cents": 250000,
        "expires_at": "2026-12-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def mdu_offer_payload(access_fee_cents: int = 250000, **overrides) -> dict:
    payload = {"access_fee_cents": access_fee_cents}
    payload.update(overrides)
    return payload


def owner_response_payload(response: str, **overrides) -> dict:
    payload = {"response": response}
    payload.update(overrides)
    return payload


def permit_application_payload(build_zone_id: str, **overrides) -> dict:
    payload = {
        "build_zone_id": build_zone_id,
        "permit_type": "ROW",
        "valid_days": 120,
        "max_resubmissions": 2,
    }
    payload.update(overrides)
    return payload


def permit_decision_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def pole_attachment_request_payload(build_zone_id: str, **overrides) -> dict:
    payload = {
        "build_zone_id": build_zone_id,
        "utility_owner": "Aurora Power",
        "pole_count": 12,
    }
    payload.update(overrides)
    return payload


def pole_survey_payload(make_ready_cost_cents: int = 45600, **overrides) -> dict:
    payload = {"make_ready_cost_cents": make_ready_cost_cents}
    payload.update(overrides)
    return payload


def pole_decision_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def preorder_payload(
    build_zone_id: str,
    service_address_id: str,
    account_id: str,
    expected_build_zone_version: int,
    **overrides,
) -> dict:
    payload = {
        "build_zone_id": build_zone_id,
        "service_address_id": service_address_id,
        "account_id": account_id,
        "plan_tier": "BASIC_300",
        "tendered_deposit_cents": 1000,
        "expected_build_zone_version": expected_build_zone_version,
    }
    payload.update(overrides)
    return payload


def conversion_payload(drop_method: str = "BURY", **overrides) -> dict:
    payload = {"drop_method": drop_method}
    payload.update(overrides)
    return payload


def install_crew_payload(**overrides) -> dict:
    payload = {"name": "Bury Crew 1", "crew_type": "BURY"}
    payload.update(overrides)
    return payload


def install_appointment_payload(
    preorder_id: str,
    crew_id: str,
    window_start_at: str,
    window_end_at: str,
    expected_crew_version: int,
    appointment_type: str = "DROP_BURY",
    **overrides,
) -> dict:
    payload = {
        "preorder_id": preorder_id,
        "crew_id": crew_id,
        "appointment_type": appointment_type,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
        "expected_crew_version": expected_crew_version,
    }
    payload.update(overrides)
    return payload


def appointment_outcome_payload(outcome: str, **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def damage_claim_payload(
    install_appointment_id: str,
    service_address_id: str,
    claimant_account_id: str,
    **overrides,
) -> dict:
    payload = {
        "install_appointment_id": install_appointment_id,
        "service_address_id": service_address_id,
        "claimant_account_id": claimant_account_id,
        "damage_type": "LAWN",
        "claimed_amount_cents": 150000,
    }
    payload.update(overrides)
    return payload


def claim_decision_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def fallback_option_payload(campaign_id: str, **overrides) -> dict:
    payload = {
        "campaign_id": campaign_id,
        "technology": "FIXED_WIRELESS",
        "min_downstream_mbps": 300,
        "monthly_price_cents": 7000,
        "max_serviceable_distance_m": 5000,
        "priority_rank": 1,
    }
    payload.update(overrides)
    return payload


def fallback_offer_payload(
    account_id: str, expires_at: str = "2026-12-01T00:00:00Z", **overrides
) -> dict:
    payload = {"account_id": account_id, "expires_at": expires_at}
    payload.update(overrides)
    return payload


def fallback_offer_response_payload(response: str, **overrides) -> dict:
    payload = {"response": response}
    payload.update(overrides)
    return payload


def threshold_payload(threshold_pct: float, **overrides) -> dict:
    payload = {"threshold_pct": threshold_pct}
    payload.update(overrides)
    return payload


def suspension_payload(action: str, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload
