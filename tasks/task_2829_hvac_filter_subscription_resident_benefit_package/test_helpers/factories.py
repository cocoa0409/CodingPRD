"""
Request-payload factories.

Every factory returns a fresh dict of PRD-legal values and accepts keyword
overrides. Cent amounts are always integers (never strings, never floats), dates
are always ``YYYY-MM-DD`` and instants always carry a trailing ``Z``.
"""

from typing import Optional

# ─── Catalog ──────────────────────────────────────────────────────────────────

def filter_sku_payload(**overrides) -> dict:
    payload = {
        "sku_code": "SKU-16251-M8",
        "size_code": "16x25x1",
        "thickness_inches": 1,
        "merv_rating": 8,
        "unit_cost_cents": 680,
        "ship_weight_oz": 14,
        "pack_quantity": 1,
    }
    payload.update(overrides)
    return payload


# ─── Property and Unit ────────────────────────────────────────────────────────

def property_payload(**overrides) -> dict:
    payload = {
        "name": "Cedar Ridge",
        "state_code": "TX",
        "billing_mode": "PM_BILLED",
        "benefit_tier": "PLUS",
        "damage_waiver_enabled": True,
        "aqg_enabled": True,
        "credit_limit_cents": 5000000,
    }
    payload.update(overrides)
    return payload


def unit_payload(**overrides) -> dict:
    payload = {
        "unit_label": "A-101",
        "hvac_system_type": "TWO_STAGE",
        "filter_slot_count": 2,
        "return_grille_count": 1,
        "nominal_size_code": "16x25x1",
    }
    payload.update(overrides)
    return payload


def suspend_payload(**overrides) -> dict:
    payload = {"suspend_reason": "PM_PAYMENT_DELINQUENT"}
    payload.update(overrides)
    return payload


def size_capture_payload(measured_size_code: str, expected_unit_version: int, **overrides) -> dict:
    payload = {
        "actual_measured_size_code": measured_size_code,
        "expected_unit_version": expected_unit_version,
    }
    payload.update(overrides)
    return payload


# ─── Resident ─────────────────────────────────────────────────────────────────

def resident_payload(**overrides) -> dict:
    payload = {
        "full_name": "Ada Reyes",
        "email": "ada.reyes@example.com",
        "household_size": 3,
        "has_pets": False,
        "smoker": False,
        "allergy_flag": False,
    }
    payload.update(overrides)
    return payload


# ─── Subscription ─────────────────────────────────────────────────────────────

def subscription_payload(resident_id: str, unit_id: str, **overrides) -> dict:
    payload = {
        "resident_id": resident_id,
        "unit_id": unit_id,
        "billing_party": "PROPERTY_MANAGER",
        "enrollment_channel": "MOVE_IN_PACKET",
        "lease_start_date": "2026-08-01",
        "lease_end_date": "2027-07-31",
    }
    payload.update(overrides)
    return payload


def cancel_payload(effective_date: str, cancel_reason: str = "Resident moved out", **overrides) -> dict:
    payload = {"effective_date": effective_date, "cancel_reason": cancel_reason}
    payload.update(overrides)
    return payload


# ─── Shipment ─────────────────────────────────────────────────────────────────

def shipment_payload(scheduled_ship_date: str, quantity: Optional[int] = None, **overrides) -> dict:
    payload = {"scheduled_ship_date": scheduled_ship_date}
    if quantity is not None:
        payload["quantity"] = quantity
    payload.update(overrides)
    return payload


def ship_payload(tracking_code: str = "TRK-A-0001", **overrides) -> dict:
    payload = {"tracking_code": tracking_code}
    payload.update(overrides)
    return payload


def deliver_payload(delivered_at: str, **overrides) -> dict:
    payload = {"delivered_at": delivered_at}
    payload.update(overrides)
    return payload


def request_return_payload(return_reason: str = "Resident moved out early", **overrides) -> dict:
    payload = {"return_reason": return_reason}
    payload.update(overrides)
    return payload


def return_payload(returned_at: str, **overrides) -> dict:
    payload = {"returned_at": returned_at}
    payload.update(overrides)
    return payload


# ─── Telemetry and surveys ────────────────────────────────────────────────────

def runtime_reading_payload(
    window_start: str,
    window_end: str,
    runtime_minutes: int,
    static_pressure_delta_pa: int,
    source: str = "SMART_THERMOSTAT",
    **overrides,
) -> dict:
    payload = {
        "window_start": window_start,
        "window_end": window_end,
        "runtime_minutes": runtime_minutes,
        "static_pressure_delta_pa": static_pressure_delta_pa,
        "source": source,
    }
    payload.update(overrides)
    return payload


def renewal_survey_payload(
    installed_last_shipment: bool = False,
    filters_on_hand_count: int = 0,
    self_reported_change_date: Optional[str] = None,
    **overrides,
) -> dict:
    payload = {
        "installed_last_shipment": installed_last_shipment,
        "filters_on_hand_count": filters_on_hand_count,
    }
    if self_reported_change_date is not None:
        payload["self_reported_change_date"] = self_reported_change_date
    payload.update(overrides)
    return payload


def non_install_evaluation_payload(detection_method: str, evaluated_through_date: str, **overrides) -> dict:
    payload = {
        "detection_method": detection_method,
        "evaluated_through_date": evaluated_through_date,
    }
    payload.update(overrides)
    return payload


def remediate_payload(remediation_note: str = "Filters installed and photographed", **overrides) -> dict:
    payload = {"remediation_note": remediation_note}
    payload.update(overrides)
    return payload


# ─── Claim ────────────────────────────────────────────────────────────────────

def claim_payload(
    subscription_id: str,
    claim_type: str = "DAMAGE_WAIVER",
    incident_date: str = "2026-08-05",
    requested_amount_cents: int = 40000,
    description: str = "Blower housing destroyed",
    **overrides,
) -> dict:
    payload = {
        "subscription_id": subscription_id,
        "claim_type": claim_type,
        "incident_date": incident_date,
        "requested_amount_cents": requested_amount_cents,
        "description": description,
    }
    payload.update(overrides)
    return payload


def request_info_payload(question: str = "Please attach the repair invoice", **overrides) -> dict:
    payload = {"question": question}
    payload.update(overrides)
    return payload


def resubmit_payload(description: str = "Invoice attached as requested", **overrides) -> dict:
    payload = {"description": description}
    payload.update(overrides)
    return payload


def decide_payload(decision: str, decision_note: str = "Adjudicated on the evidence", **overrides) -> dict:
    payload = {"decision": decision, "decision_note": decision_note}
    payload.update(overrides)
    return payload


def reverse_payment_payload(reversal_reason: str = "Duplicate disbursement", **overrides) -> dict:
    payload = {"reversal_reason": reversal_reason}
    payload.update(overrides)
    return payload


def withdraw_payload(withdraw_reason: str = "Resident withdrew the claim", **overrides) -> dict:
    payload = {"withdraw_reason": withdraw_reason}
    payload.update(overrides)
    return payload


# ─── Transfer ─────────────────────────────────────────────────────────────────

def transfer_payload(
    subscription_id: str,
    to_unit_id: str,
    effective_date: str,
    expected_subscription_version: int,
    **overrides,
) -> dict:
    payload = {
        "subscription_id": subscription_id,
        "to_unit_id": to_unit_id,
        "effective_date": effective_date,
        "expected_subscription_version": expected_subscription_version,
    }
    payload.update(overrides)
    return payload


def reject_transfer_payload(rejection_reason: str = "Unit reassigned", **overrides) -> dict:
    payload = {"rejection_reason": rejection_reason}
    payload.update(overrides)
    return payload


# ─── Logical clock ────────────────────────────────────────────────────────────

def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
