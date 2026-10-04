"""Payload factories: one per entity, client-supplied fields only."""
from .constants import TEST_DEFAULTS as D

DEFAULT_INSURANCE_REF = "COI-2026-100001"


def create_shipper_payload(**overrides) -> dict:
    payload = {
        "name": D["SHIPPER_NAME"],
        "billing_state_code": D["SHIPPER_STATE"],
        "payment_terms_days": D["PAYMENT_TERMS_DAYS"],
        "quick_pay_discount_pct": D["QUICK_PAY_DISCOUNT_PCT"],
        "credit_limit_cents": D["CREDIT_LIMIT_CENTS"],
        "load_credit_limit": D["LOAD_CREDIT_LIMIT"],
    }
    payload.update(overrides)
    return payload


def create_facility_payload(state_code="TX", **overrides) -> dict:
    payload = {
        "name": D["ORIGIN_FACILITY_NAME"] if state_code == "TX" else D["DESTINATION_FACILITY_NAME"],
        "state_code": state_code,
        "dock_capacity": D["DOCK_CAPACITY"],
        "default_appointment_minutes": 60,
        "free_dwell_minutes": 120,
        "detention_rate_per_hour_cents": D["DETENTION_RATE_PER_HOUR_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_carrier_payload(mc_number="100001", **overrides) -> dict:
    payload = {
        "legal_name": D["CARRIER_LEGAL_NAME"],
        "mc_number": mc_number,
        "dot_number": D["CARRIER_DOT_NUMBER"],
        "insurance_expires_at": D["CARRIER_INSURANCE_EXPIRES_AT"],
        "insurance_liability_limit_cents": D["CARRIER_INSURANCE_LIABILITY_LIMIT_CENTS"],
        "cargo_coverage_limit_cents": D["CARRIER_CARGO_COVERAGE_LIMIT_CENTS"],
        "safety_score": D["CARRIER_SAFETY_SCORE"],
        "equipment_types": [D["DEFAULT_EQUIPMENT_TYPE"]],
    }
    payload.update(overrides)
    return payload


def attest_insurance_payload(**overrides) -> dict:
    payload = {
        "insurance_expires_at": D["CARRIER_INSURANCE_EXPIRES_AT"],
        "insurance_liability_limit_cents": D["CARRIER_INSURANCE_LIABILITY_LIMIT_CENTS"],
        "cargo_coverage_limit_cents": D["CARRIER_CARGO_COVERAGE_LIMIT_CENTS"],
        "certificate_reference": DEFAULT_INSURANCE_REF,
    }
    payload.update(overrides)
    return payload


def create_equipment_payload(carrier_id, unit_number, **overrides) -> dict:
    payload = {
        "carrier_id": carrier_id,
        "equipment_type": D["DEFAULT_EQUIPMENT_TYPE"],
        "unit_number": unit_number,
        "driver_name": "D. Okafor",
    }
    payload.update(overrides)
    return payload


def create_lane_contract_payload(shipper_id, origin_facility_id, destination_facility_id,
                                 **overrides) -> dict:
    payload = {
        "shipper_id": shipper_id,
        "origin_facility_id": origin_facility_id,
        "destination_facility_id": destination_facility_id,
        "equipment_type": D["DEFAULT_EQUIPMENT_TYPE"],
        "committed_weekly_volume": 6,
        "committed_rate_cents": 215000,
        "accessorial_allowance_cents": 25000,
        "start_date": "2026-09-01T00:00:00Z",
        "end_date": "2026-12-31T00:00:00Z",
        "contract_carrier_ids": [],
    }
    payload.update(overrides)
    return payload


def create_load_payload(shipper_id, origin_facility_id, destination_facility_id, **overrides) -> dict:
    payload = {
        "shipper_id": shipper_id,
        "origin_facility_id": origin_facility_id,
        "destination_facility_id": destination_facility_id,
        "pricing_mode": "SPOT",
        "equipment_type": D["DEFAULT_EQUIPMENT_TYPE"],
        "commodity": D["DEFAULT_COMMODITY"],
        "weight_lbs": D["DEFAULT_WEIGHT_LBS"],
        "declared_cargo_value_cents": D["DEFAULT_DECLARED_CARGO_VALUE_CENTS"],
        "distance_miles": D["DEFAULT_DISTANCE_MILES"],
        "pickup_window_start": D["DEFAULT_PICKUP_WINDOW_START"],
        "pickup_window_end": D["DEFAULT_PICKUP_WINDOW_END"],
        "delivery_deadline": D["DEFAULT_DELIVERY_DEADLINE"],
        "market_band": D["DEFAULT_MARKET_BAND"],
    }
    payload.update(overrides)
    return payload


def create_booking_payload(load_id, carrier_id, rate_quote_id, equipment_id,
                           expected_load_version, **overrides) -> dict:
    payload = {
        "load_id": load_id,
        "carrier_id": carrier_id,
        "rate_quote_id": rate_quote_id,
        "equipment_id": equipment_id,
        "expected_load_version": expected_load_version,
    }
    payload.update(overrides)
    return payload


def create_tracking_ping_payload(carrier_id, sequence, reported_status, location_code,
                                 **overrides) -> dict:
    payload = {
        "carrier_id": carrier_id,
        "sequence": sequence,
        "reported_status": reported_status,
        "location_code": location_code,
    }
    payload.update(overrides)
    return payload


def create_status_event_payload(load_id, event_type="EXCEPTION", **overrides) -> dict:
    payload = {"load_id": load_id, "event_type": event_type}
    payload.update(overrides)
    return payload


def create_claim_payload(load_id, carrier_id, claimed_amount_cents,
                         expected_carrier_version, **overrides) -> dict:
    payload = {
        "load_id": load_id,
        "carrier_id": carrier_id,
        "claimed_amount_cents": claimed_amount_cents,
        "damage_description": "Crushed pallet on the rear stack, shrink wrap torn.",
        "filed_by_role": "SHIPPER",
        "expected_carrier_version": expected_carrier_version,
    }
    payload.update(overrides)
    return payload


def create_appointment_payload(carrier_id, slot_kind, window_start, window_end, **overrides) -> dict:
    payload = {
        "slot_kind": slot_kind,
        "carrier_id": carrier_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload