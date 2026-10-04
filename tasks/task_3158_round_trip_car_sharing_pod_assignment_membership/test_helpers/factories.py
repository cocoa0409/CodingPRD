"""Payload factories — one per entity, input fields only.

Optional fields are omitted from the default payload so the server-side default
applies; pass them explicitly via ``**overrides`` when a test needs them.
"""

DEFAULTS = {
    "MEMBER_NAME": "Test Member",
    "MEMBER_KIND": "INDIVIDUAL",
    "POD_NAME": "Test Pod",
    "POD_SITE_TYPE": "CAMPUS",
    "POD_CAPACITY": 4,
    "FUEL_FLOOR_CAMPUS": 20,
    "VEHICLE_MODEL": "Prius",
    "VEHICLE_SEATS": 5,
    "RESERVED_HOURS": 4,
    "RESERVATION_START": "2026-09-05T09:00:00Z",
    "RESERVATION_END": "2026-09-05T13:00:00Z",
    "WINDOW_START": "2026-09-13T09:00:00Z",
    "WINDOW_END": "2026-09-13T11:00:00Z",
    "BUNDLE_START": "2026-09-12T02:00:00Z",
    "BUNDLE_END": "2026-09-12T06:00:00Z",
}

_vin_counter = {"n": 0}


def unique_vin() -> str:
    """A distinct VIN per call — the column is unique across all vehicles."""
    _vin_counter["n"] += 1
    return f"VIN3158{_vin_counter['n']:05d}"


def unique_email() -> str:
    _vin_counter["n"] += 1
    return f"member{_vin_counter['n']}@example.com"


# ─── Member ───────────────────────────────────────────
def member_registration_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["MEMBER_NAME"],
        "email": unique_email(),
        "kind": DEFAULTS["MEMBER_KIND"],
    }
    payload.update(overrides)
    return payload


def driving_record_report_payload(**overrides) -> dict:
    payload = {"license_state": "CA", "license_years_held": 8}
    payload.update(overrides)
    return payload


def report_decision_payload(decision="CLEAR", **overrides) -> dict:
    payload = {"report_decision": decision}
    payload.update(overrides)
    return payload


def application_decision_payload(decision="APPROVE", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def wallet_adjustment_payload(amount_cents, reason="ADJUSTMENT", **overrides) -> dict:
    payload = {"amount_cents": amount_cents, "reason": reason}
    payload.update(overrides)
    return payload


# ─── Account ──────────────────────────────────────────
def account_payload(primary_member_id, **overrides) -> dict:
    payload = {
        "name": "Test University",
        "type": "UNIVERSITY",
        "primary_member_id": primary_member_id,
        "billing_email": "billing@example.edu",
    }
    payload.update(overrides)
    return payload


# ─── Membership ───────────────────────────────────────
def membership_payload(member_id, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "tier": "STANDARD",
        "primary_flag": True,
    }
    payload.update(overrides)
    return payload


def tier_restore_entitlement_payload(tier="PLUS", reason="GOODWILL", **overrides) -> dict:
    payload = {"tier": tier, "reason": reason}
    payload.update(overrides)
    return payload


# ─── Pod ──────────────────────────────────────────────
def pod_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["POD_NAME"],
        "site_type": DEFAULTS["POD_SITE_TYPE"],
        "capacity": DEFAULTS["POD_CAPACITY"],
        "fuel_floor_pct": DEFAULTS["FUEL_FLOOR_CAMPUS"],
    }
    payload.update(overrides)
    return payload


def reclassify_pod_payload(site_type, **overrides) -> dict:
    payload = {"site_type": site_type}
    payload.update(overrides)
    return payload


# ─── Vehicle ──────────────────────────────────────────
def vehicle_payload(pod_id, **overrides) -> dict:
    payload = {
        "pod_id": pod_id,
        "vin": unique_vin(),
        "model": DEFAULTS["VEHICLE_MODEL"],
        "capacity_seats": DEFAULTS["VEHICLE_SEATS"],
    }
    payload.update(overrides)
    return payload


def availability_event_payload(event, **overrides) -> dict:
    payload = {"event": event}
    payload.update(overrides)
    return payload


# ─── Shift bundle ─────────────────────────────────────
def shift_bundle_payload(source_pod_id, dest_pod_id, monthly_pods, expected_pod_version, **overrides) -> dict:
    payload = {
        "source_pod_id": source_pod_id,
        "dest_pod_id": dest_pod_id,
        "scheduled_start": DEFAULTS["BUNDLE_START"],
        "scheduled_end": DEFAULTS["BUNDLE_END"],
        "monthly_pods": list(monthly_pods),
        "expected_pod_version_profile": expected_pod_version,
    }
    payload.update(overrides)
    return payload


# ─── Reservation ──────────────────────────────────────
def reservation_payload(member_id, pod_id, vehicle_id, expected_vehicle_version, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "pod_id": pod_id,
        "vehicle_id": vehicle_id,
        "start_at": DEFAULTS["RESERVATION_START"],
        "end_at": DEFAULTS["RESERVATION_END"],
        "reserved_hours": DEFAULTS["RESERVED_HOURS"],
        "expected_vehicle_version": expected_vehicle_version,
    }
    payload.update(overrides)
    return payload


def return_payload(returned_pod_id, returned_odometer_miles, returned_fuel_level_pct,
                   contamination_level=0, **overrides) -> dict:
    payload = {
        "returned_pod_id": returned_pod_id,
        "returned_odometer_miles": returned_odometer_miles,
        "returned_fuel_level_pct": returned_fuel_level_pct,
        "contamination_level": contamination_level,
    }
    payload.update(overrides)
    return payload


# ─── Incident ─────────────────────────────────────────
def incident_payload(reservation_id, vehicle_id, member_id, **overrides) -> dict:
    payload = {
        "reservation_id": reservation_id,
        "vehicle_id": vehicle_id,
        "member_id": member_id,
        "incident_type": "DAMAGE",
    }
    payload.update(overrides)
    return payload


def party_split_payload(expected_incident_version, **overrides) -> dict:
    payload = {"expected_incident_version": expected_incident_version}
    payload.update(overrides)
    return payload


def waive_fee_payload(reason="GOODWILL", **overrides) -> dict:
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


# ─── Maintenance order ────────────────────────────────
def maintenance_order_payload(vehicle_id, reason="TYRE_ROTATION", blocking=True, **overrides) -> dict:
    payload = {
        "vehicle_id": vehicle_id,
        "reason": reason,
        "blocking": blocking,
        "scheduled_start": DEFAULTS["WINDOW_START"],
        "scheduled_end": DEFAULTS["WINDOW_END"],
    }
    payload.update(overrides)
    return payload


def incident_maintenance_order_payload(pod_id, reason="COLLISION_REPAIR", blocking=True, **overrides) -> dict:
    payload = {
        "pod_id": pod_id,
        "reason": reason,
        "blocking": blocking,
        "scheduled_start": DEFAULTS["WINDOW_START"],
        "scheduled_end": DEFAULTS["WINDOW_END"],
    }
    payload.update(overrides)
    return payload


def cancel_maintenance_order_payload(reason="CUSTOMER_IMPACT", **overrides) -> dict:
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


# ─── Access event ─────────────────────────────────────
def access_event_payload(reservation_id, member_id, method="APP", **overrides) -> dict:
    payload = {"reservation_id": reservation_id, "member_id": member_id, "method": method}
    payload.update(overrides)
    return payload


# ─── Fuel card ────────────────────────────────────────
def fuel_transaction_payload(reservation_id, vehicle_id, amount_cents=5000, gallons_hundredths=1200, **overrides) -> dict:
    payload = {
        "reservation_id": reservation_id,
        "vehicle_id": vehicle_id,
        "amount_cents": amount_cents,
        "gallons_hundredths": gallons_hundredths,
    }
    payload.update(overrides)
    return payload


# ─── Community signal ─────────────────────────────────
def community_signal_payload(pod_id, signal_type="CAMPUS", message="Operational signal", **overrides) -> dict:
    payload = {"pod_id": pod_id, "signal_type": signal_type, "message": message}
    payload.update(overrides)
    return payload


# ─── Test-driving ─────────────────────────────────────
def citation_issue_payload(recoverable_signer_address="0xAAA1", signer_address="0xAAA1",
                           expires_at="2027-01-01T00:00:00Z", **overrides) -> dict:
    payload = {
        "recoverable_signer_address": recoverable_signer_address,
        "signer_address": signer_address,
        "expires_at": expires_at,
    }
    payload.update(overrides)
    return payload


def citation_validate_payload(signature="0xDEADBEEF", **overrides) -> dict:
    payload = {"signature": signature}
    payload.update(overrides)
    return payload


def payment_simulation_payload(membership_id, outcome="SETTLED", **overrides) -> dict:
    payload = {"membership_id": membership_id, "outcome": outcome}
    payload.update(overrides)
    return payload