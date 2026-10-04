"""Segregation of duties: which role owns which act, and what that forbids."""

from test_helpers import (
    ApiErrorId,
    factories,
    get_success_data,
    setup_grooming_booking,
    setup_visit_with_certificate,
    validate_error,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
VET = TEST_USERS["veterinary_staff_headers"]
GROOMER = TEST_USERS["grooming_staff_headers"]
VACCINATION = TEST_USERS["vaccination_staff_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
ANY = TEST_USERS["any_headers"]


def test_screening_a_booking_belongs_to_the_grooming_staff_and_not_to_the_veterinarian(api):
    """The screening act is refused to another role and admitted to its owner.

    PRD §2.1: "Screening a grooming booking is a `GroomingStaff` duty, but
    confirming that booking onto a bay is a `StoreManager` duty, and the two must
    not collapse into one actor."
    PRD §2.1: "A request whose acting role is not permitted for the operation it
    targets is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
    PRD §3.2: "Screening is a `GroomingStaff` act against a booking in
    `REQUESTED`"

    Design: Corner/RBAC/grooming_staff_cannot_screen_a_non_grooming_booking
    """
    world = setup_grooming_booking(api, pet=("Rune", "CANINE", "Whippet", 10.5))
    store_id = world["store"]["id"]
    booking = world["booking"]
    payload = factories.screening_payload(
        health_condition_points=0,
        aggression_acknowledged=True,
        expected_pet_version=world["pet"]["version"],
    )

    refused = api.screen_booking(store_id, booking["id"], payload, VET)
    validate_error(refused, ApiErrorId.INSUFFICIENT_PERMISSIONS.value, 403)

    admitted = api.screen_booking(store_id, booking["id"], payload, GROOMER)
    assert admitted.status_code == 200, admitted.text
    assert get_success_data(admitted)["status"] == "SCREENED"


def test_submitting_a_state_report_belongs_to_the_compliance_officer_not_the_issuing_actor(api):
    """The actor who issues the certificate cannot also report it.

    PRD §2.1: "Registration of a walk-in visit and issuance of the resulting
    certificate belong to `VaccinationStaff`, while submitting the state report
    for that certificate belongs to `ComplianceOfficer`."
    PRD §2.1: "A request whose acting role is not permitted for the operation it
    targets is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
    PRD §3.7: "Submission moves the visit to `REPORTED`, sets
    `state_report_status` to `SUBMITTED`"

    Design: Corner/RBAC/reporting_submission_is_restricted_to_the_compliance_officer
    """
    world = setup_visit_with_certificate(api, state_code="CA")
    store_id = world["store"]["id"]
    visit = world["visit"]
    payload = {"expected_visit_version": visit["version"]}

    refused = api.submit_state_report(store_id, visit["id"], payload, VACCINATION)
    validate_error(refused, ApiErrorId.INSUFFICIENT_PERMISSIONS.value, 403)

    admitted = api.submit_state_report(store_id, visit["id"], payload, COMPLIANCE)
    assert admitted.status_code == 200, admitted.text
    submitted = get_success_data(admitted)
    assert submitted["status"] == "REPORTED"
    assert submitted["state_report_status"] == "SUBMITTED"


def test_the_platform_administrator_is_not_a_superset_of_the_operational_roles(api):
    """The store estate and the clock belong to the administrator; booking does not.

    PRD §2.1: "The logical clock, the store estate and the breed handling rules
    belong to `PlatformAdmin` alone."
    PRD §2.1: "A request whose acting role is not permitted for the operation it
    targets is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
    PRD §2.1: "The name `Any` is itself a role in the enumeration and denotes
    read-only access to the surface the API exposes publicly"

    Design: Corner/RBAC/platform_admin_cannot_book_or_screen
    """
    world = setup_grooming_booking(api, pet=("Tiko", "CANINE", "Poodle", 6.8))
    store_id = world["store"]["id"]
    bay = get_success_data(api.get_store_service_bay(store_id, world["bay"]["id"], ADMIN))

    refused = api.create_booking(
        store_id,
        factories.booking_payload(
            bay_id=bay["id"],
            pet_id=world["pet"]["id"],
            service_type="GROOMING",
            starts_at="2026-07-01T09:00:00Z",
            ends_at="2026-07-01T10:00:00Z",
            expected_pet_version=world["pet"]["version"],
        ),
        ADMIN,
    )
    validate_error(refused, ApiErrorId.INSUFFICIENT_PERMISSIONS.value, 403)

    # The refusal is scoped to the write surface: the read still succeeds.
    assert api.get_store(store_id, ADMIN).status_code == 200
    admitted = api.create_booking(
        store_id,
        factories.booking_payload(
            bay_id=bay["id"],
            pet_id=world["pet"]["id"],
            service_type="GROOMING",
            starts_at="2026-08-01T09:00:00Z",
            ends_at="2026-08-01T10:00:00Z",
            expected_pet_version=world["pet"]["version"],
        ),
        GROOMER,
    )
    assert admitted.status_code == 201, admitted.text