"""Payload factories — one per resource, input fields only.

Defaults are chosen so a factory call produces a valid request on its own;
callers override only the fields the claim under test depends on.
"""

from typing import Any, Dict, Optional


# ── Centres, members and pets ────────────────────────────────────────────────

def store_payload(
    store_code: str = "ST-0001",
    city: str = "Sacramento",
    state_code: str = "CA",
    service_bay_count: int = 2,
    hospital_capacity: int = 4,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "store_code": store_code,
        "city": city,
        "state_code": state_code,
        "service_bay_count": service_bay_count,
        "hospital_capacity": hospital_capacity,
    }
    payload.update(overrides)
    return payload


def member_payload(
    home_store_id: str,
    full_name: str = "Test Member",
    email: str = "member@example.com",
    state_code: str = "CA",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "full_name": full_name,
        "email": email,
        "state_code": state_code,
        "home_store_id": home_store_id,
    }
    payload.update(overrides)
    return payload


def pet_payload(
    member_id: str,
    name: str = "Test Pet",
    species: str = "CANINE",
    breed: str = "Mixed Unknown",
    weight_kg: float = 12.0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "member_id": member_id,
        "name": name,
        "species": species,
        "breed": breed,
        "weight_kg": weight_kg,
    }
    payload.update(overrides)
    return payload


def breed_rule_payload(
    breed: str = "Mixed Unknown",
    species: str = "CANINE",
    risk_points: int = 0,
    handling_tier: str = "STANDARD",
    allowed_for_grooming: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "breed": breed,
        "species": species,
        "risk_points": risk_points,
        "handling_tier": handling_tier,
        "allowed_for_grooming": allowed_for_grooming,
    }
    payload.update(overrides)
    return payload


def service_bay_payload(bay_code: str = "GROOMING", **overrides: Any) -> Dict[str, Any]:
    payload = {"bay_code": bay_code}
    payload.update(overrides)
    return payload


# ── Bookings and screening ───────────────────────────────────────────────────

def booking_payload(
    bay_id: str,
    pet_id: str,
    service_type: str = "GROOMING",
    starts_at: str = "2026-06-05T09:00:00Z",
    ends_at: str = "2026-06-05T10:00:00Z",
    expected_pet_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "bay_id": bay_id,
        "pet_id": pet_id,
        "service_type": service_type,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    if expected_pet_version is not None:
        payload["expected_pet_version"] = expected_pet_version
    payload.update(overrides)
    return payload


def screening_payload(
    health_condition_points: int = 0,
    aggression_acknowledged: bool = False,
    expected_pet_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "health_condition_points": health_condition_points,
        "aggression_acknowledged": aggression_acknowledged,
    }
    if expected_pet_version is not None:
        payload["expected_pet_version"] = expected_pet_version
    payload.update(overrides)
    return payload


# ── Encounters and prescriptions ─────────────────────────────────────────────

def encounter_payload(
    pet_id: str,
    clinician_name: str = "Dr. Test Vet",
    scheduled_at: str = "2026-06-02T09:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "pet_id": pet_id,
        "clinician_name": clinician_name,
        "scheduled_at": scheduled_at,
    }
    payload.update(overrides)
    return payload


def prescription_payload(
    pet_id: str,
    encounter_id: str,
    item_type: str = "MEDICATION",
    item_name: str = "Test Medication",
    sku: str = "SKU-TEST-01",
    unit_price_cents: int = 1500,
    quantity: int = 2,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "pet_id": pet_id,
        "encounter_id": encounter_id,
        "item_type": item_type,
        "item_name": item_name,
        "sku": sku,
        "unit_price_cents": unit_price_cents,
        "quantity": quantity,
    }
    payload.update(overrides)
    return payload


def pharmacy_order_payload(
    authorization_id: str,
    requested_quantity: int = 1,
    expected_authorization_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "authorization_id": authorization_id,
        "requested_quantity": requested_quantity,
    }
    if expected_authorization_version is not None:
        payload["expected_authorization_version"] = expected_authorization_version
    payload.update(overrides)
    return payload


def cross_sell_payload(
    authorization_id: str,
    pet_id: str,
    sku: str = "SKU-TEST-01",
    expected_pet_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "authorization_id": authorization_id,
        "pet_id": pet_id,
        "sku": sku,
    }
    if expected_pet_version is not None:
        payload["expected_pet_version"] = expected_pet_version
    payload.update(overrides)
    return payload


# ── Vaccination clinics and visits ───────────────────────────────────────────

def clinic_payload(
    clinic_date: str = "2026-09-21T00:00:00Z",
    open_time: str = "2026-09-21T09:00:00Z",
    close_time: str = "2026-09-21T17:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "clinic_date": clinic_date,
        "open_time": open_time,
        "close_time": close_time,
    }
    payload.update(overrides)
    return payload


def visit_payload(
    clinic_id: str,
    pet_id: str,
    vaccine_type: str = "RABIES",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "clinic_id": clinic_id,
        "pet_id": pet_id,
        "vaccine_type": vaccine_type,
    }
    payload.update(overrides)
    return payload


# ── Incidents and claims ─────────────────────────────────────────────────────

def incident_payload(
    booking_id: str,
    pet_id: str,
    severity: str = "MODERATE",
    incident_type: str = "PET_INJURY",
    claim_amount_cents: int = 25000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "booking_id": booking_id,
        "pet_id": pet_id,
        "severity": severity,
        "incident_type": incident_type,
        "claim_amount_cents": claim_amount_cents,
    }
    payload.update(overrides)
    return payload


# ── Packages, cycles and enrolments ──────────────────────────────────────────

def package_payload(
    tier: str = "PLUS",
    member_state_code: str = "CA",
    state_sales_tax_rate: float = 0.07,
    billing_cycle_count: int = 1,
    monthly_fee_cents: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "tier": tier,
        "member_state_code": member_state_code,
        "state_sales_tax_rate": state_sales_tax_rate,
        "billing_cycle_count": billing_cycle_count,
        "monthly_fee_cents": monthly_fee_cents,
    }
    payload.update(overrides)
    return payload


def billing_cycle_payload(
    expected_package_version: Optional[int] = None,
    grooming_visits_consumed: int = 0,
    vet_visits_consumed: int = 0,
    vaccine_visits_consumed: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "grooming_visits_consumed": grooming_visits_consumed,
        "vet_visits_consumed": vet_visits_consumed,
        "vaccine_visits_consumed": vaccine_visits_consumed,
    }
    if expected_package_version is not None:
        payload["expected_package_version"] = expected_package_version
    payload.update(overrides)
    return payload


def enrollment_payload(
    package_id: str,
    pet_id: str,
    class_code: str = "PUPPY-101",
    courses_required: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "package_id": package_id,
        "pet_id": pet_id,
        "class_code": class_code,
        "courses_required": courses_required,
    }
    payload.update(overrides)
    return payload