"""Composite setup helpers.

Every interesting claim in this contract needs the system in a state that takes
several calls to reach: an active centre with a member, a pet whose incident
history has already been applied, a screening recorded against a booking, an
examination completed so its prescription is authorized, a clinic open with a
certificate issued. These helpers build that state through the public API and
return the created resources so tests can focus on the behaviour under
assertion.

Setup calls go through ``get_success_data`` so a broken precondition fails with
a clear "Setup failed" message rather than a confusing assertion mismatch.

Two conventions run through the file:

* ``expected_*_version`` inputs are always fed from the version the preceding
  response reported, never from an earlier snapshot — the contract's
  optimistic-concurrency rule rejects anything else with ``ERR_STALE_VERSION``.
* Composite helpers accept ``**overrides`` for the values a claim needs to
  control (capacity, tax rate, weights, claim amounts) and default everything
  else.
"""

import uuid
from typing import Any, Dict, List, Optional, Tuple

import requests as requests_Response

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
VET = TEST_USERS["veterinary_staff_headers"]
GROOMER = TEST_USERS["grooming_staff_headers"]
VACCINATION = TEST_USERS["vaccination_staff_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
PHARMACY = TEST_USERS["pharmacy_staff_headers"]
TRAINER = TEST_USERS["training_staff_headers"]
ANY = TEST_USERS["any_headers"]

# Instant used by most workflows: a Monday inside a 09:00-17:00 clinic window.
MONDAY = "2026-09-21T09:00:00Z"


# ── Clock ────────────────────────────────────────────────────────────────────

def set_clock(api, to_iso8601: str) -> Dict[str, Any]:
    """Move the logical clock. Returns {current_utc, highest_set_utc}."""
    return get_success_data(api.set_clock(to_iso8601, ADMIN))


# ── Tier 0: leaves ───────────────────────────────────────────────────────────

def create_store(
    api,
    store_code: str = "ST-0001",
    city: str = "Sacramento",
    state_code: str = "CA",
    service_bay_count: int = 2,
    hospital_capacity: int = 4,
) -> Dict[str, Any]:
    """Register a pet care center. Returns the Store row."""
    resp = api.create_store(
        factories.store_payload(
            store_code=store_code,
            city=city,
            state_code=state_code,
            service_bay_count=service_bay_count,
            hospital_capacity=hospital_capacity,
        ),
        ADMIN,
    )
    return get_success_data(resp, 201)


def read_store(api, store_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_store(store_id, ANY))


def create_member(
    api,
    store_id: str,
    full_name: str = "Test Member",
    email: Optional[str] = None,
    state_code: str = "CA",
) -> Dict[str, Any]:
    # PRD §2.13 makes a member email globally unique ("a duplicate email anywhere
    # in the system"). A shared literal would collide the moment a test builds a
    # second centre, so a fresh address is minted when the caller does not name one.
    if email is None:
        email = "member-%s@example.com" % uuid.uuid4().hex[:12]
    resp = api.create_member(
        factories.member_payload(
            home_store_id=store_id, full_name=full_name, email=email, state_code=state_code
        ),
        MANAGER,
    )
    return get_success_data(resp, 201)


def read_member(api, member_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_member(member_id, ANY))


def create_pet(
    api,
    member_id: str,
    name: str = "Test Pet",
    species: str = "CANINE",
    breed: str = "Mixed Unknown",
    weight_kg: float = 12.0,
) -> Dict[str, Any]:
    resp = api.create_pet(
        factories.pet_payload(
            member_id=member_id, name=name, species=species, breed=breed, weight_kg=weight_kg
        ),
        GROOMER,
    )
    return get_success_data(resp, 201)


def read_pet(api, pet_id: str) -> Dict[str, Any]:
    """The finalized on-read reconciliation of the pet's rabies expiry."""
    return get_success_data(api.get_pet(pet_id, ANY))


def create_breed_rule(
    api,
    breed: str = "Mixed Unknown",
    species: str = "CANINE",
    risk_points: int = 0,
    handling_tier: str = "STANDARD",
    allowed_for_grooming: bool = True,
) -> Dict[str, Any]:
    resp = api.create_breed_rule(
        factories.breed_rule_payload(
            breed=breed,
            species=species,
            risk_points=risk_points,
            handling_tier=handling_tier,
            allowed_for_grooming=allowed_for_grooming,
        ),
        ADMIN,
    )
    return get_success_data(resp, 201)


def create_bay(api, store_id: str, bay_code: str = "GROOMING") -> Dict[str, Any]:
    resp = api.create_service_bay(store_id, factories.service_bay_payload(bay_code), MANAGER)
    return get_success_data(resp, 201)


def disable_bay(api, store_id: str, bay: Dict[str, Any]) -> Dict[str, Any]:
    """Permanently take an idle service bay out of the schedule."""
    payload = {"expected_bay_version": bay["version"]}
    resp = api.disable_service_bay(store_id, bay["id"], payload, MANAGER)
    return get_success_data(resp)


def create_clinic(
    api,
    store_id: str,
    clinic_date: str = "2026-09-21T00:00:00Z",
    open_time: str = MONDAY,
    close_time: str = "2026-09-21T17:00:00Z",
) -> Dict[str, Any]:
    resp = api.create_clinic(
        store_id,
        factories.clinic_payload(clinic_date=clinic_date, open_time=open_time, close_time=close_time),
        VACCINATION,
    )
    return get_success_data(resp, 201)


def open_clinic(api, store_id: str, clinic: Dict[str, Any]) -> Dict[str, Any]:
    resp = api.open_walk_ins(
        store_id, clinic["id"], {"expected_clinic_version": clinic["version"]}, VACCINATION
    )
    return get_success_data(resp)


def create_visit(
    api,
    store_id: str,
    clinic_id: str,
    pet_id: str,
    vaccine_type: str = "RABIES",
    prior_rabies_vaccination_date: Optional[str] = None,
) -> Dict[str, Any]:
    payload = factories.visit_payload(
        clinic_id=clinic_id, pet_id=pet_id, vaccine_type=vaccine_type
    )
    if prior_rabies_vaccination_date is not None:
        payload["prior_rabies_vaccination_date"] = prior_rabies_vaccination_date
    resp = api.create_visit(store_id, payload, VACCINATION)
    return get_success_data(resp, 201)


def issue_certificate(api, store_id: str, visit: Dict[str, Any]) -> Dict[str, Any]:
    resp = api.issue_certificate(
        store_id, visit["id"], {"expected_visit_version": visit["version"]}, VACCINATION
    )
    return get_success_data(resp)


def submit_state_report(api, store_id: str, visit: Dict[str, Any]) -> Dict[str, Any]:
    resp = api.submit_state_report(
        store_id, visit["id"], {"expected_visit_version": visit["version"]}, COMPLIANCE
    )
    return get_success_data(resp)


def read_visit(api, visit_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_visit(visit_id, ANY))


def read_visit_certificate(api, visit_id: str) -> List[Dict[str, Any]]:
    return get_success_data(api.get_visit_rabies_certificate(visit_id, ANY))


# ── Bookings ─────────────────────────────────────────────────────────────────

def create_booking(
    api,
    store_id: str,
    bay_id: str,
    pet_id: str,
    pet_version: int,
    service_type: str = "GROOMING",
    starts_at: str = "2026-06-05T09:00:00Z",
    ends_at: str = "2026-06-05T10:00:00Z",
) -> Dict[str, Any]:
    resp = api.create_booking(
        store_id,
        factories.booking_payload(
            bay_id=bay_id,
            pet_id=pet_id,
            service_type=service_type,
            starts_at=starts_at,
            ends_at=ends_at,
            expected_pet_version=pet_version,
        ),
        GROOMER,
    )
    return get_success_data(resp, 201)


def read_booking(api, booking_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_booking(booking_id, ANY))


def screen_booking(
    api,
    store_id: str,
    booking: Dict[str, Any],
    pet_version: int,
    health_condition_points: int = 0,
    aggression_acknowledged: bool = False,
) -> Dict[str, Any]:
    resp = api.screen_booking(
        store_id,
        booking["id"],
        factories.screening_payload(
            health_condition_points=health_condition_points,
            aggression_acknowledged=aggression_acknowledged,
            expected_pet_version=pet_version,
        ),
        GROOMER,
    )
    return get_success_data(resp)


def confirm_booking(api, store_id: str, booking: Dict[str, Any]) -> Dict[str, Any]:
    """Confirm using the booking's own echoes of the booking and pet versions."""
    payload = {
        "expected_booking_version": booking["version"],
        "expected_pet_version": booking["pet_version"],
    }
    resp = api.confirm_bay(store_id, booking["id"], payload, MANAGER)
    return get_success_data(resp)


def start_service(api, store_id: str, booking: Dict[str, Any]) -> Dict[str, Any]:
    resp = api.start_service(
        store_id, booking["id"], {"expected_booking_version": booking["version"]}, GROOMER
    )
    return get_success_data(resp)


def complete_service(api, store_id: str, booking: Dict[str, Any]) -> Dict[str, Any]:
    resp = api.complete_service(
        store_id, booking["id"], {"expected_booking_version": booking["version"]}, GROOMER
    )
    return get_success_data(resp)


def cancel_booking(api, store_id: str, booking: Dict[str, Any]) -> Dict[str, Any]:
    resp = api.cancel_booking(
        store_id, booking["id"], {"expected_booking_version": booking["version"]}, GROOMER
    )
    return get_success_data(resp)


# ── Encounters, prescriptions and the pharmacy counter ───────────────────────

def create_encounter(
    api,
    store_id: str,
    pet_id: str,
    clinician_name: str = "Dr. Test Vet",
    scheduled_at: str = "2026-06-02T09:00:00Z",
    booking_id: Optional[str] = None,
    chief_complaint: Optional[str] = None,
) -> Dict[str, Any]:
    payload = factories.encounter_payload(
        pet_id=pet_id, clinician_name=clinician_name, scheduled_at=scheduled_at
    )
    if booking_id is not None:
        payload["booking_id"] = booking_id
    if chief_complaint is not None:
        payload["chief_complaint"] = chief_complaint
    resp = api.create_encounter(store_id, payload, VET)
    return get_success_data(resp, 201)


def read_encounter(api, encounter_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_encounter(encounter_id, ANY))


def check_in(api, store_id: str, encounter: Dict[str, Any]) -> Dict[str, Any]:
    resp = api.check_in_encounter(
        store_id, encounter["id"], {"expected_encounter_version": encounter["version"]}, VET
    )
    return get_success_data(resp)


def start_exam(api, store_id: str, encounter: Dict[str, Any]) -> Dict[str, Any]:
    resp = api.start_exam(
        store_id, encounter["id"], {"expected_encounter_version": encounter["version"]}, VET
    )
    return get_success_data(resp)


def complete_exam(api, store_id: str, encounter: Dict[str, Any]) -> Dict[str, Any]:
    resp = api.complete_exam(
        store_id, encounter["id"], {"expected_encounter_version": encounter["version"]}, VET
    )
    return get_success_data(resp)


def create_prescription(
    api,
    store_id: str,
    pet_id: str,
    encounter_id: str,
    item_type: str = "MEDICATION",
    item_name: str = "Test Medication",
    sku: str = "SKU-TEST-01",
    unit_price_cents: int = 1500,
    quantity: int = 2,
) -> Dict[str, Any]:
    resp = api.create_prescription(
        store_id,
        factories.prescription_payload(
            pet_id=pet_id,
            encounter_id=encounter_id,
            item_type=item_type,
            item_name=item_name,
            sku=sku,
            unit_price_cents=unit_price_cents,
            quantity=quantity,
        ),
        VET,
    )
    return get_success_data(resp, 201)


def read_prescription(api, authorization_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_prescription(authorization_id, ANY))


def revoke_prescription(api, store_id: str, authorization: Dict[str, Any]) -> requests_Response:
    """Revoke a prescription, rejecting its outstanding pharmacy orders.

    Returns the raw response so a claim can assert either the success or the
    refusal without re-deriving the payload.
    """
    payload = {"expected_authorization_version": authorization["version"]}
    return api.revoke_prescription(store_id, authorization["id"], payload, VET)


def raise_pharmacy_order(
    api, store_id: str, authorization: Dict[str, Any], requested_quantity: int
) -> Dict[str, Any]:
    resp = api.create_pharmacy_order(
        store_id,
        factories.pharmacy_order_payload(
            authorization_id=authorization["id"],
            requested_quantity=requested_quantity,
            expected_authorization_version=authorization["version"],
        ),
        PHARMACY,
    )
    return get_success_data(resp, 201)


def dispense_order(api, store_id: str, order: Dict[str, Any]) -> Dict[str, Any]:
    resp = api.dispense_pharmacy_order(
        store_id, order["id"], {"expected_order_version": order["version"]}, PHARMACY
    )
    return get_success_data(resp)


def reject_order(api, store_id: str, order: Dict[str, Any]) -> Dict[str, Any]:
    resp = api.reject_pharmacy_order(
        store_id, order["id"], {"expected_order_version": order["version"]}, PHARMACY
    )
    return get_success_data(resp)


def read_pharmacy_order(api, order_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_pharmacy_order(order_id, ANY))


def read_charge_summary(api, store_id: str, encounter_id: str) -> Dict[str, Any]:
    """The finalized on-read reconciliation of the encounter charge."""
    return get_success_data(api.get_charge_summary(store_id, encounter_id, ANY))


def create_cross_sell(
    api, store_id: str, authorization_id: str, pet_id: str, pet_version: int, sku: str = "SKU-TEST-01"
) -> Dict[str, Any]:
    resp = api.create_cross_sell(
        store_id,
        factories.cross_sell_payload(
            authorization_id=authorization_id,
            pet_id=pet_id,
            sku=sku,
            expected_pet_version=pet_version,
        ),
        PHARMACY,
    )
    return get_success_data(resp, 201)


def redeem_cross_sell(
    api, store_id: str, cross_sell: Dict[str, Any], credit_redeemed_cents: int
) -> Dict[str, Any]:
    resp = api.redeem_cross_sell(
        store_id,
        cross_sell["id"],
        {
            "expected_cross_sell_version": cross_sell["version"],
            "credit_redeemed_cents": credit_redeemed_cents,
        },
        PHARMACY,
    )
    return get_success_data(resp)


def fetch_store_cross_sells(api, store_id: str) -> List[Dict[str, Any]]:
    return get_success_data(api.list_cross_sells(ANY, {"store_id": store_id, "limit": 100}))


# ── Incidents and claims ─────────────────────────────────────────────────────

def create_incident(
    api,
    store_id: str,
    booking_id: str,
    pet_id: str,
    severity: str = "MODERATE",
    incident_type: str = "PET_INJURY",
    claim_amount_cents: int = 25000,
    override_reason: Optional[str] = None,
) -> Dict[str, Any]:
    payload = factories.incident_payload(
        booking_id=booking_id,
        pet_id=pet_id,
        severity=severity,
        incident_type=incident_type,
        claim_amount_cents=claim_amount_cents,
    )
    if override_reason is not None:
        payload["override_reason"] = override_reason
    resp = api.create_incident(store_id, payload, GROOMER)
    return get_success_data(resp, 201)


def begin_review(api, store_id: str, incident: Dict[str, Any]) -> Dict[str, Any]:
    resp = api.begin_review(
        store_id, incident["id"], {"expected_incident_version": incident["version"]}, MANAGER
    )
    return get_success_data(resp)


def approve_claim(
    api,
    store_id: str,
    incident: Dict[str, Any],
    override_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Approve a reviewed claim.

    A claim amount above the store state's cap requires a non-empty
    ``override_reason``, which is supplied with the approval rather than with the
    report.
    """
    payload: Dict[str, Any] = {"expected_incident_version": incident["version"]}
    if override_reason is not None:
        payload["override_reason"] = override_reason
    resp = api.approve_claim(store_id, incident["id"], payload, MANAGER)
    return get_success_data(resp)


def deny_claim(api, store_id: str, incident: Dict[str, Any]) -> Dict[str, Any]:
    resp = api.deny_claim(
        store_id, incident["id"], {"expected_incident_version": incident["version"]}, MANAGER
    )
    return get_success_data(resp)


def read_incident(api, incident_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_incident(incident_id, ANY))


# ── Packages, cycles and enrolments ──────────────────────────────────────────

def create_package(
    api,
    store_id: str,
    member_id: str,
    tier: str = "PLUS",
    member_state_code: str = "CA",
    state_sales_tax_rate: float = 0.07,
    billing_cycle_count: int = 1,
    monthly_fee_cents: int = 0,
) -> Dict[str, Any]:
    resp = api.create_package(
        store_id,
        member_id,
        factories.package_payload(
            tier=tier,
            member_state_code=member_state_code,
            state_sales_tax_rate=state_sales_tax_rate,
            billing_cycle_count=billing_cycle_count,
            monthly_fee_cents=monthly_fee_cents,
        ),
        MANAGER,
    )
    return get_success_data(resp, 201)


def read_package(api, package_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_package(package_id, ANY))


def advance_cycle(
    api,
    store_id: str,
    member_id: str,
    package: Dict[str, Any],
    grooming_visits_consumed: int = 0,
    vet_visits_consumed: int = 0,
    vaccine_visits_consumed: int = 0,
) -> Dict[str, Any]:
    resp = api.advance_billing_cycle(
        store_id,
        member_id,
        package["id"],
        factories.billing_cycle_payload(
            expected_package_version=package["version"],
            grooming_visits_consumed=grooming_visits_consumed,
            vet_visits_consumed=vet_visits_consumed,
            vaccine_visits_consumed=vaccine_visits_consumed,
        ),
        MANAGER,
    )
    return get_success_data(resp)


def pause_package(api, store_id: str, member_id: str, package: Dict[str, Any]) -> Dict[str, Any]:
    resp = api.pause_package(
        store_id, member_id, package["id"], {"expected_package_version": package["version"]}, MANAGER
    )
    return get_success_data(resp)


def resume_package(api, store_id: str, member_id: str, package: Dict[str, Any]) -> Dict[str, Any]:
    resp = api.resume_package(
        store_id, member_id, package["id"], {"expected_package_version": package["version"]}, MANAGER
    )
    return get_success_data(resp)


def cancel_package(api, store_id: str, member_id: str, package: Dict[str, Any]) -> Dict[str, Any]:
    resp = api.cancel_package(
        store_id, member_id, package["id"], {"expected_package_version": package["version"]}, MANAGER
    )
    return get_success_data(resp)


def fetch_package_cycles(api, package_id: str) -> List[Dict[str, Any]]:
    return get_success_data(
        api.list_package_billing_cycles(package_id, ANY, {"limit": 100})
    )


def fetch_member_packages(api, member_id: str) -> List[Dict[str, Any]]:
    return get_success_data(api.list_member_packages(member_id, ANY, {"limit": 100}))


def create_enrollment(
    api,
    store_id: str,
    package_id: str,
    pet_id: str,
    class_code: str = "PUPPY-101",
    courses_required: int = 1,
) -> Dict[str, Any]:
    resp = api.create_enrollment(
        store_id,
        factories.enrollment_payload(
            package_id=package_id,
            pet_id=pet_id,
            class_code=class_code,
            courses_required=courses_required,
        ),
        TRAINER,
    )
    return get_success_data(resp, 201)


def begin_course(api, store_id: str, enrollment: Dict[str, Any]) -> Dict[str, Any]:
    resp = api.begin_course(
        store_id, enrollment["id"], {"expected_enrollment_version": enrollment["version"]}, TRAINER
    )
    return get_success_data(resp)


def read_enrollment(api, enrollment_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_enrollment(enrollment_id, ANY))


# ── Posture controls ─────────────────────────────────────────────────────────

def restrict_store(api, store_id: str, store_version: int) -> Dict[str, Any]:
    resp = api.restrict_store(store_id, {"expected_store_version": store_version}, ADMIN)
    return get_success_data(resp)


def lift_restriction(api, store_id: str, store_version: int) -> Dict[str, Any]:
    resp = api.lift_posture_restriction(store_id, {"expected_store_version": store_version}, ADMIN)
    return get_success_data(resp)


def freeze_hospital(api, store_id: str, store_version: int) -> Dict[str, Any]:
    resp = api.freeze_hospital(store_id, {"expected_store_version": store_version}, ADMIN)
    return get_success_data(resp)


def reopen_hospital(api, store_id: str, store_version: int) -> Dict[str, Any]:
    resp = api.reopen_hospital(store_id, {"expected_store_version": store_version}, ADMIN)
    return get_success_data(resp)


def bump_occupancy(api, store_id: str, store_version: int, magnitude: int) -> Dict[str, Any]:
    resp = api.bump_occupancy(
        store_id, {"expected_store_version": store_version, "magnitude": magnitude}, ADMIN
    )
    return get_success_data(resp)


# ── Tier 1/2: centre + member (+ pet) ────────────────────────────────────────

def build_center(
    api,
    store_code: str = "ST-0001",
    state_code: str = "CA",
    service_bay_count: int = 2,
    hospital_capacity: int = 4,
    member_full_name: str = "Test Member",
    member_email: Optional[str] = None,
    pet: Optional[Tuple[str, str, str, float]] = None,
) -> Dict[str, Any]:
    """A centre with one member and, when ``pet`` is given, one pet.

    ``pet`` is ``(name, species, breed, weight_kg)``. Returns a dict carrying
    ``store``, ``member``, ``pet`` and the shared header sets. Left unset, the
    member's ``email`` is minted fresh, because PRD §2.13 makes a member email
    globally unique and a shared literal would collide on the second centre.
    """
    store = create_store(
        api,
        store_code=store_code,
        state_code=state_code,
        service_bay_count=service_bay_count,
        hospital_capacity=hospital_capacity,
    )
    member = create_member(
        api,
        store["id"],
        full_name=member_full_name,
        email=member_email,
        state_code=state_code,
    )
    world: Dict[str, Any] = {"store": store, "member": member, "pet": None}
    if pet is not None:
        name, species, breed, weight_kg = pet
        world["pet"] = create_pet(
            api, member["id"], name=name, species=species, breed=breed, weight_kg=weight_kg
        )
    return world


def build_center_with_grooming_bay(api, **kwargs) -> Dict[str, Any]:
    """A centre, a member, a pet and one GROOMING bay."""
    world = build_center(api, **kwargs)
    world["bay"] = create_bay(api, world["store"]["id"], "GROOMING")
    return world


# ── Tier 3: booking lifecycle ────────────────────────────────────────────────

def setup_grooming_booking(
    api,
    store_code: str = "ST-0001",
    state_code: str = "CA",
    hospital_capacity: int = 4,
    pet: Optional[Tuple[str, str, str, float]] = None,
    starts_at: str = "2026-06-05T09:00:00Z",
    ends_at: str = "2026-06-05T10:00:00Z",
) -> Dict[str, Any]:
    """Centre + member + pet + GROOMING bay + a REQUESTED grooming booking."""
    world = build_center(
        api,
        store_code=store_code,
        state_code=state_code,
        hospital_capacity=hospital_capacity,
        pet=pet or ("Ash", "CANINE", "Whippet", 12.5),
    )
    world["bay"] = create_bay(api, world["store"]["id"], "GROOMING")
    world["booking"] = create_booking(
        api,
        world["store"]["id"],
        world["bay"]["id"],
        world["pet"]["id"],
        world["pet"]["version"],
        service_type="GROOMING",
        starts_at=starts_at,
        ends_at=ends_at,
    )
    return world


def setup_screened_booking(
    api,
    health_condition_points: int = 0,
    aggression_acknowledged: bool = True,
    **kwargs,
) -> Dict[str, Any]:
    """As ``setup_grooming_booking``, screened, so the booking sits in SCREENED."""
    world = setup_grooming_booking(api, **kwargs)
    world["booking"] = screen_booking(
        api,
        world["store"]["id"],
        world["booking"],
        world["pet"]["version"],
        health_condition_points=health_condition_points,
        aggression_acknowledged=aggression_acknowledged,
    )
    return world


def setup_confirmed_booking(api, **kwargs) -> Dict[str, Any]:
    """Grooming booking driven all the way to BAY_CONFIRMED."""
    world = setup_screened_booking(api, **kwargs)
    world["booking"] = confirm_booking(api, world["store"]["id"], world["booking"])
    return world


def setup_in_service_booking(api, **kwargs) -> Dict[str, Any]:
    """Grooming booking driven to IN_SERVICE."""
    world = setup_confirmed_booking(api, **kwargs)
    world["booking"] = start_service(api, world["store"]["id"], world["booking"])
    return world


def setup_completed_grooming_booking(api, **kwargs) -> Dict[str, Any]:
    """Grooming booking driven to COMPLETED — the precondition for a claim."""
    world = setup_in_service_booking(api, **kwargs)
    world["booking"] = complete_service(api, world["store"]["id"], world["booking"])
    return world


def setup_incident_under_review(
    api,
    severity: str = "MODERATE",
    incident_type: str = "PET_INJURY",
    claim_amount_cents: int = 25000,
    override_reason: Optional[str] = None,
    state_code: str = "CA",
    **kwargs,
) -> Dict[str, Any]:
    """A completed grooming booking plus an incident already moved into review."""
    world = setup_completed_grooming_booking(api, state_code=state_code, **kwargs)
    world["incident"] = create_incident(
        api,
        world["store"]["id"],
        world["booking"]["id"],
        world["pet"]["id"],
        severity=severity,
        incident_type=incident_type,
        claim_amount_cents=claim_amount_cents,
        override_reason=override_reason,
    )
    world["incident"] = begin_review(api, world["store"]["id"], world["incident"])
    return world


# ── Tier 3: hospital encounter lifecycle ─────────────────────────────────────

def setup_encounter(
    api,
    store_code: str = "ST-0001",
    state_code: str = "CA",
    hospital_capacity: int = 4,
    pet: Optional[Tuple[str, str, str, float]] = None,
    scheduled_at: str = "2026-06-02T09:00:00Z",
) -> Dict[str, Any]:
    """Centre + member + pet + one SCHEDULED veterinary encounter."""
    world = build_center(
        api,
        store_code=store_code,
        state_code=state_code,
        hospital_capacity=hospital_capacity,
        pet=pet or ("Biscuit", "CANINE", "Labrador Retriever", 28.0),
    )
    world["encounter"] = create_encounter(
        api, world["store"]["id"], world["pet"]["id"], scheduled_at=scheduled_at
    )
    return world


def setup_encounter_checked_in(api, **kwargs) -> Dict[str, Any]:
    world = setup_encounter(api, **kwargs)
    world["encounter"] = check_in(api, world["store"]["id"], world["encounter"])
    world["store"] = read_store(api, world["store"]["id"])
    return world


def setup_encounter_in_exam(
    api, prescription: Optional[Dict[str, Any]] = None, **kwargs
) -> Dict[str, Any]:
    """Checked-in encounter moved into the exam room.

    When ``prescription`` is supplied its factory arguments are captured here,
    but the prescription itself is raised by ``setup_completed_exam`` *after*
    this helper has driven the encounter into ``IN_EXAM``. PRD §3.5 requires a
    prescription to cite an encounter that "must have reached `IN_EXAM` or
    beyond", so raising it any earlier is refused with
    ``ERR_UNDERLYING_EXAM_REQUIRED``.
    """
    world = setup_encounter_checked_in(api, **kwargs)
    store_id = world["store"]["id"]
    if prescription:
        world["prescription_args"] = prescription
    world["encounter"] = start_exam(api, store_id, world["encounter"])
    return world


def setup_completed_exam(
    api, prescription: Optional[Dict[str, Any]] = None, **kwargs
) -> Dict[str, Any]:
    """Encounter driven to COMPLETED, so any prescription raised is AUTHORIZED.

    The prescription is raised once the encounter sits in ``IN_EXAM`` (PRD §3.5)
    and before the exam completes, so the completion transition has a
    ``PENDING_EXAM`` row to authorize.
    """
    world = setup_encounter_in_exam(api, prescription=prescription, **kwargs)
    store_id = world["store"]["id"]
    if "prescription_args" in world:
        world["prescription"] = create_prescription(
            api, store_id, world["pet"]["id"], world["encounter"]["id"],
            **world["prescription_args"],
        )
    world["encounter"] = complete_exam(api, store_id, world["encounter"])
    if "prescription" in world:
        world["prescription"] = read_prescription(api, world["prescription"]["id"])
    world["store"] = read_store(api, store_id)
    return world


def setup_authorized_prescription(
    api,
    item_type: str = "MEDICATION",
    unit_price_cents: int = 1500,
    quantity: int = 2,
    **kwargs,
) -> Dict[str, Any]:
    """A completed exam plus the prescription it authorized."""
    world = setup_completed_exam(
        api,
        prescription={
            "item_type": item_type,
            "unit_price_cents": unit_price_cents,
            "quantity": quantity,
        },
        **kwargs,
    )
    return world


def setup_authorized_pharmacy_order(
    api,
    item_type: str = "MEDICATION",
    unit_price_cents: int = 1500,
    quantity: int = 3,
    requested_quantity: Optional[int] = None,
    **kwargs,
) -> Dict[str, Any]:
    """An authorized prescription plus a handoff raised against it.

    The handoff is raised after the exam completes, so the prescription is
    AUTHORIZED and the order is released to the counter.
    """
    world = setup_authorized_prescription(
        api, item_type=item_type, unit_price_cents=unit_price_cents, quantity=quantity, **kwargs
    )
    world["order"] = raise_pharmacy_order(
        api,
        world["store"]["id"],
        world["prescription"],
        requested_quantity if requested_quantity is not None else quantity,
    )
    return world


# ── Tier 3: clinic and certificate lifecycle ─────────────────────────────────

def setup_open_clinic(
    api,
    store_code: str = "ST-0001",
    state_code: str = "CA",
    hospital_capacity: int = 4,
    clinic_date: str = "2026-09-21T00:00:00Z",
    open_time: str = MONDAY,
    close_time: str = "2026-09-21T17:00:00Z",
    pet: Optional[Tuple[str, str, str, float]] = None,
) -> Dict[str, Any]:
    """A centre whose walk-in clinic is OPEN, ready for a visit.

    The logical clock is moved to the clinic's own ``open_time`` first, because a
    clinic may only be opened on its own ``clinic_date`` and a certificate may
    only be issued while the clock lies inside the open-to-close window.
    """
    set_clock(api, open_time)
    world = build_center(
        api,
        store_code=store_code,
        state_code=state_code,
        hospital_capacity=hospital_capacity,
        pet=pet or ("Juniper", "CANINE", "Beagle", 11.0),
    )
    world["clinic"] = create_clinic(
        api, world["store"]["id"], clinic_date=clinic_date, open_time=open_time, close_time=close_time
    )
    world["clinic"] = open_clinic(api, world["store"]["id"], world["clinic"])
    return world


def setup_clinic_visit(
    api, vaccine_type: str = "RABIES", prior_rabies_vaccination_date: Optional[str] = None, **kwargs
) -> Dict[str, Any]:
    """An OPEN clinic plus one registered walk-in visit."""
    world = setup_open_clinic(api, **kwargs)
    world["visit"] = create_visit(
        api,
        world["store"]["id"],
        world["clinic"]["id"],
        world["pet"]["id"],
        vaccine_type=vaccine_type,
        prior_rabies_vaccination_date=prior_rabies_vaccination_date,
    )
    return world


def setup_visit_with_certificate(api, **kwargs) -> Dict[str, Any]:
    """A walk-in visit whose rabies certificate has been issued."""
    world = setup_clinic_visit(api, **kwargs)
    world["visit"] = issue_certificate(api, world["store"]["id"], world["visit"])
    return world


# ── Tier 3: packages ─────────────────────────────────────────────────────────

def setup_member_with_package(
    api,
    tier: str = "PLUS",
    state_code: str = "CA",
    state_sales_tax_rate: float = 0.07,
    billing_cycle_count: int = 1,
    monthly_fee_cents: int = 0,
    store_code: str = "ST-0001",
    hospital_capacity: int = 4,
) -> Dict[str, Any]:
    """A centre, a member, and one service package subscribed at ``tier``."""
    world = build_center(
        api,
        store_code=store_code,
        state_code=state_code,
        hospital_capacity=hospital_capacity,
        pet=("Gizmo", "CANINE", "Poodle", 7.4),
    )
    world["package"] = create_package(
        api,
        world["store"]["id"],
        world["member"]["id"],
        tier=tier,
        member_state_code=state_code,
        state_sales_tax_rate=state_sales_tax_rate,
        billing_cycle_count=billing_cycle_count,
        monthly_fee_cents=monthly_fee_cents,
    )
    return world


def setup_package_with_enrollment(
    api,
    tier: str = "PLUS",
    courses_required: int = 3,
    state_code: str = "NY",
    **kwargs,
) -> Dict[str, Any]:
    """A package plus one training enrolment awaiting acknowledgement."""
    world = setup_member_with_package(api, tier=tier, state_code=state_code, **kwargs)
    world["enrollment"] = create_enrollment(
        api,
        world["store"]["id"],
        world["package"]["id"],
        world["pet"]["id"],
        courses_required=courses_required,
    )
    return world


# ── Tier 4: accumulation / threshold targeting ───────────────────────────────

def saturate_store_occupancy(api, store_id: str, store_version: int, magnitude: int) -> Dict[str, Any]:
    """Move ``magnitude`` SCHEDULED encounters into CHECKED_IN in one call.

    The bump endpoint re-runs the posture recalculation, so this is the
    supported way to drive a store to RESTRICTED or FROZEN from an empty
    occupied count.
    """
    return bump_occupancy(api, store_id, store_version, magnitude)


def setup_store_at_capacity(
    api,
    store_code: str = "ST-0001",
    state_code: str = "CA",
    hospital_capacity: int = 1,
    encounter_count: int = 1,
) -> Dict[str, Any]:
    """A centre holding ``encounter_count`` SCHEDULED encounters.

    With ``hospital_capacity`` 1 and one scheduled encounter the store's
    occupancy already equals its capacity, which is the precondition the
    posture-override rules state.
    """
    world = build_center(
        api,
        store_code=store_code,
        state_code=state_code,
        hospital_capacity=hospital_capacity,
        pet=("Kite", "CANINE", "Saluki", 22.0),
    )
    encounters = []
    for index in range(encounter_count):
        encounters.append(
            create_encounter(
                api,
                world["store"]["id"],
                world["pet"]["id"],
                scheduled_at=f"2026-06-2{index % 9}T09:00:00Z",
            )
        )
    world["encounters"] = encounters
    world["store"] = read_store(api, world["store"]["id"])
    return world


def saturate_to_capacity(api, store_id: str, hospital_capacity: int = 1) -> Dict[str, Any]:
    """Add SCHEDULED encounters until occupancy reaches the store's capacity.

    The posture-override rules require a store's occupancy to be at or above its
    capacity before it may be escalated to RESTRICTED; with a capacity of 1 a
    single scheduled encounter satisfies that.
    """
    world = {"store": read_store(api, store_id)}
    for index in range(hospital_capacity):
        create_encounter(
            api,
            store_id,
            _first_pet_of_store(api, store_id),
            scheduled_at=f"2026-08-1{index % 9}T09:00:00Z",
        )
    world["store"] = read_store(api, store_id)
    world["version"] = world["store"]["version"]
    return world


def _first_pet_of_store(api, store_id: str) -> str:
    members = get_success_data(api.list_members(ANY, {"limit": 100}))
    for member in members:
        pets = get_success_data(api.list_member_pets(member["id"], ANY, {"limit": 100}))
        if pets:
            return pets[0]["id"]
    raise AssertionError(f"Setup failed: no pet found for store {store_id}")


# ── Tier 4: posture targeting ────────────────────────────────────────────────

def setup_store_posture_restricted(
    api,
    store_code: str = "ST-0001",
    state_code: str = "CA",
    hospital_capacity: int = 2,
    bay_code: str = "GROOMING",
) -> Dict[str, Any]:
    """A store escalated to RESTRICTED, with one bay.

    The escalation precondition is that occupancy already be at or above
    capacity, so the store is built with exactly ``hospital_capacity`` SCHEDULED
    encounters before the restriction is requested. The bays of the store are
    frozen by the escalation.
    """
    world = setup_store_at_capacity(
        api,
        store_code=store_code,
        state_code=state_code,
        hospital_capacity=hospital_capacity,
        encounter_count=hospital_capacity,
    )
    store_id = world["store"]["id"]
    world["bay"] = create_bay(api, store_id, bay_code)
    world["store"] = restrict_store(api, store_id, world["store"]["version"])
    return world


def setup_store_posture_frozen(
    api,
    store_code: str = "ST-0001",
    state_code: str = "CA",
    bay_code: str = "GROOMING",
) -> Dict[str, Any]:
    """A store driven to FROZEN by an occupancy surge.

    One SCHEDULED encounter against a capacity of one already puts
    ``hospital_occupancy`` at capacity; moving it into CHECKED_IN with the
    occupancy bump raises the occupied ratio to 1.0, which resolves the posture
    to FROZEN. The bays of the store are frozen by the escalation.
    """
    world = setup_store_at_capacity(
        api, store_code=store_code, state_code=state_code, hospital_capacity=1, encounter_count=1
    )
    store_id = world["store"]["id"]
    world["bay"] = create_bay(api, store_id, bay_code)
    world["store"] = bump_occupancy(api, store_id, world["store"]["version"], 1)
    return world


def setup_bay_with_two_grooming_bookings(
    api, store_code: str = "ST-0001", state_code: str = "CA"
) -> Dict[str, Any]:
    """One GROOMING bay holding two bookings at different lifecycle points.

    The first booking is left at BAY_CONFIRMED and the second is driven to
    IN_SERVICE, so a single parent-store freeze exercises both conditional
    branches of the bay's own freeze cascade. The store is built with capacity one
    and a single SCHEDULED encounter, so one occupancy bump escalates it to
    FROZEN.
    """
    world = setup_store_at_capacity(
        api, store_code=store_code, state_code=state_code, hospital_capacity=1, encounter_count=1
    )
    store_id = world["store"]["id"]
    bay = create_bay(api, store_id, "GROOMING")
    first_pet = create_pet(api, world["member"]["id"], name="Iggy", breed="Pug", weight_kg=8.0)
    first = create_booking(
        api, store_id, bay["id"], first_pet["id"], first_pet["version"],
        service_type="GROOMING", starts_at="2026-06-16T09:00:00Z", ends_at="2026-06-16T10:00:00Z",
    )
    first = screen_booking(api, store_id, first, first_pet["version"], aggression_acknowledged=True)
    first = confirm_booking(api, store_id, first)

    second_pet = create_pet(api, world["member"]["id"], name="Juno", breed="Pug", weight_kg=8.4)
    second = create_booking(
        api, store_id, bay["id"], second_pet["id"], second_pet["version"],
        service_type="GROOMING", starts_at="2026-06-16T11:00:00Z", ends_at="2026-06-16T12:00:00Z",
    )
    second = screen_booking(api, store_id, second, second_pet["version"], aggression_acknowledged=True)
    second = confirm_booking(api, store_id, second)
    second = start_service(api, store_id, second)

    world["bay"] = bay
    world["confirmed"] = first
    world["in_service"] = second
    world["store"] = read_store(api, store_id)
    return world


def setup_bay_frozen_then_thawed(
    api, store_code: str = "ST-0001", state_code: str = "CA"
) -> Dict[str, Any]:
    """A bay cycled ACTIVE to FROZEN and back through the parent store's posture.

    The store is escalated to RESTRICTED with two SCHEDULED encounters against a
    capacity of two, which freezes its bay; one encounter is then moved into
    CHECKED_IN, dropping the occupied ratio to 0.5 and resolving the posture back
    to OPEN, which thaws the bay. Returns the world with ``frozen_bay`` (the bay
    as it stood while frozen), ``bay`` (the bay after the thaw) and ``store``
    (the store after the thaw).
    """
    world = setup_store_posture_restricted(
        api, store_code=store_code, state_code=state_code, hospital_capacity=2, bay_code="GROOMING"
    )
    store_id = world["store"]["id"]
    world["frozen_bay"] = get_success_data(
        api.get_store_service_bay(store_id, world["bay"]["id"], ADMIN)
    )
    assert world["store"]["hospital_posture"] == "RESTRICTED", (
        f"Setup failed: expected RESTRICTED, got {world['store']['hospital_posture']}"
    )
    world["store"] = bump_occupancy(api, store_id, world["store"]["version"], 1)
    world["bay"] = get_success_data(
        api.get_store_service_bay(store_id, world["bay"]["id"], ADMIN)
    )
    return world


def setup_store_with_priced_prescription(
    api, credit_rate: float = 0.10, **kwargs
) -> Dict[str, Any]:
    """A completed exam whose prescription carries a known frozen price.

    Returns the world plus ``gross_cents`` and ``expected_credit_cents`` so a
    cross-sell claim can name the exact credit the grant should produce.
    """
    world = setup_authorized_prescription(
        api, item_type="TREATMENT", unit_price_cents=3000, quantity=2, **kwargs
    )
    world["gross_cents"] = world["prescription"]["price_at_authorization_cents"]
    world["expected_credit_cents"] = round(world["gross_cents"] * credit_rate, 2)
    return world