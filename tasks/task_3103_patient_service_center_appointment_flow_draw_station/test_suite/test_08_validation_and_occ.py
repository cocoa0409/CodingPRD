"""Validation ladder, RBAC refusals, and optimistic concurrency on order-scoped writes."""
import pytest

from test_helpers import (
    validate_success, validate_error, api_client, INTAKE, TEST_USERS,
    ApiErrorId, NON_EXISTENT_UUID, make_patient_headers, make_phlebotomist_headers,
    create_estimate_payload, assert_version_incremented,
)
from test_helpers.fixtures import (
    setup_eligible_order, setup_center_and_plan, setup_cancelled_order,
    setup_windowed_assigned_specimen, setup_windowed_compromised_specimen,
    new_center, new_patient, new_order,
    resolve_insurance, book, check_in, call_patient, get_order, get_appointment,
    new_phlebotomist, new_courier_run, set_clock, new_tube_requirement,
)
from test_helpers.test_users import UNKNOWN_ROLE_HEADERS, NO_AUTH_HEADERS


def test_a_request_carrying_no_role_header_is_refused_before_anything_else(api):
    """PRD §2.1: "A request missing either header, or naming a role the server
    does not recognize, is rejected with `ERR_MISSING_AUTH` (HTTP 401)."
    PRD §2.11: "**Authentication.** The two headers must be present and the role
    recognized; otherwise `ERR_MISSING_AUTH` (HTTP 401)."

    Design: Corner/errors/unauthenticated_call_without_a_role_header_is_rejected_at_priority_1
    """
    response = api.get_service_center(NON_EXISTENT_UUID, headers=NO_AUTH_HEADERS)
    validate_error(response, ApiErrorId.ERR_MISSING_AUTH.value, expected_status=401)


def test_an_unrecognized_role_is_refused_at_the_authentication_step(api):
    """PRD §2.1: "A request missing either header, or naming a role the server
    does not recognize, is rejected with `ERR_MISSING_AUTH` (HTTP 401)."

    Design: Corner/errors/unauthenticated_call_without_a_role_header_is_rejected_at_priority_1
    """
    validate_error(api.get_service_center(NON_EXISTENT_UUID, headers=UNKNOWN_ROLE_HEADERS),
                   ApiErrorId.ERR_MISSING_AUTH.value, expected_status=401)


def test_a_patient_cannot_assign_a_courier_run_to_their_own_specimen(api):
    """PRD §2.1: "each operation is also gated by role, and an authenticated
    principal attempting an operation outside its permitted set is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.11: "**Authorization.** The calling role must be permitted for the
    operation; otherwise `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/errors/path_dimension_assignment_cannot_be_performed_by_a_patient
    """
    data = setup_eligible_order()
    phleb = new_phlebotomist(data["center"]["id"], credential="RN")
    specimen = validate_success(api_client.create_specimen({
        "test_order_id": data["order"]["id"], "tube_code": "EDTA_LAVENDER",
        "volume_ml": 4.0, "order_of_draw": 1, "special_handling_codes": [],
    }, make_phlebotomist_headers(phleb["id"])), 201)
    run = new_courier_run(data["center"]["id"], "2026-09-01T18:00:00Z")

    response = api_client.assign_courier(
        specimen["id"], run["id"], make_patient_headers(data["patient"]["id"]))
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)

    assert api_client.get_specimen(
        specimen["id"], TEST_USERS["lab_liaison_headers"]).json()["data"]["status"] == "UNASSIGNED"
    assert api_client.get_courier_run(
        run["id"], TEST_USERS["lab_liaison_headers"]).json()["data"]["committed_specimen_count"] == 0


def test_a_phlebotomist_cannot_book_an_appointment(api):
    """PRD §2.11: "**Authorization.** The calling role must be permitted for the
    operation; otherwise `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: "POST | `/psc/appointments` | Book an appointment | IntakeCoordinator,
    Patient, LabSystem"

    Design: Corner/rbac/a_phlebotomist_cannot_book_an_appointment
    """
    data = setup_eligible_order()
    phleb = new_phlebotomist(data["center"]["id"], credential="RN")

    response = api_client.create_appointment({
        "service_center_id": data["center"]["id"], "test_order_id": data["order"]["id"],
        "scheduled_start_utc": "2026-09-01T14:00:00Z", "slot_span": 1,
        "source": "BOOKED", "expected_test_order_version": data["order"]["version"],
    }, make_phlebotomist_headers(phleb["id"]))
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)

    listed = api_client.list_appointments(
        INTAKE, params={"service_center_id": data["center"]["id"]}).json()["data"]
    assert listed == []


def test_a_center_supervisor_cannot_declare_a_specimen_compromised(api):
    """PRD §2.11: "**Authorization.** The calling role must be permitted for the
    operation; otherwise `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: "POST | `/psc/specimens/{specimenId}/compromise` | Mark a specimen
    compromised | LabLiaison"

    Design: Corner/rbac/a_center_supervisor_cannot_declare_a_specimen_compromised
    """
    data = setup_windowed_assigned_specimen()
    headers = TEST_USERS["lab_liaison_headers"]

    response = api_client.compromise_specimen(
        data["specimen"]["id"], "HEMOLYZED", TEST_USERS["supervisor_headers"])
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)

    assert api_client.get_specimen(data["specimen"]["id"], headers).json()["data"]["status"] == "ASSIGNED"
    assert api_client.get_courier_run(
        data["courier_run"]["id"], headers).json()["data"]["committed_specimen_count"] == 1


def test_an_out_of_enum_collection_mode_is_refused_at_intake(api):
    """PRD §3.1: "It declares the work to be done through `test_panel` — one of
    `CMP`, `CBC`, `LIPID`, `A1C`, `TSH`, `PT_INR`, `FERRITIN`, `HCG_QUAL`,
    `LACTATE`, or `GTT` — and through `collection_mode`, one of `SELF_SERVICE`,
    `STANDARD`, `PEDIATRIC`, or `DIFFICULT_DRAW`."
    PRD §2.11: "A malformed request — a missing required field, an unknown field,
    or a value outside its declared enum or numeric range — is rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/errors/an_out_of_enum_collection_mode_is_rejected_at_intake
    """
    data = setup_eligible_order()
    response = api_client.create_test_order({
        "service_center_id": data["center"]["id"], "patient_id": data["patient"]["id"],
        "ordering_provider_npi": "1700111228", "test_panel": "CMP",
        "collection_mode": "TINY_POKE", "list_price_cents": 5000,
        "is_fasting_required": False, "fasting_hours_required": 0,
        "patient_last_food_utc": "2026-09-01T12:00:00Z", "icd10_codes": [],
        "insurance_plan_id": data["plan_id"],
    }, INTAKE)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)

    listed = api_client.list_test_orders(
        INTAKE, params={"patient_id": data["patient"]["id"]}).json()["data"]
    assert len(listed) == 1, "the rejected intake must not have been stored"


def test_rejecting_a_specimen_whose_tube_grid_row_is_absent_is_refused(api):
    """PRD §3.7: "It requires a tube requirement whose panel and tube code match
    the specimen's — otherwise it fails with `ERR_TUBE_REQUIREMENT_MISSING`
    (HTTP 400)."

    Design: Corner/errors/a_panel_with_no_matching_tube_requirement_is_rejected_at_rejection_time
    """
    data = setup_windowed_compromised_specimen(compromise_reason="CLOTTED")
    headers = TEST_USERS["lab_liaison_headers"]
    grid = api_client.list_tube_requirements(
        headers, params={"tube_code": data["specimen"]["tube_code"]}).json()["data"]
    for row in grid:
        api_client.delete_tube_requirement(row["id"], headers)

    response = api_client.reject_specimen(data["specimen"]["id"], headers)
    validate_error(response, ApiErrorId.ERR_TUBE_REQUIREMENT_MISSING.value, expected_status=400)

    assert api_client.get_specimen(
        data["specimen"]["id"], headers).json()["data"]["status"] == "COMPROMISED"


def test_an_unknown_specimen_id_reads_back_as_a_specimen_not_found(api):
    """PRD §2.11: "The failures are `ERR_SERVICE_CENTER_NOT_FOUND` (HTTP 404),
    `ERR_PATIENT_NOT_FOUND` (HTTP 400), `ERR_TEST_ORDER_NOT_FOUND` (HTTP 400),
    `ERR_APPOINTMENT_NOT_FOUND` (HTTP 404), `ERR_SPECIMEN_NOT_FOUND` (HTTP 404),
    and `ERR_COURIER_RUN_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/specimen_get_with_an_unknown_id_returns_specimen_not_found
    """
    response = api_client.get_specimen(NON_EXISTENT_UUID, TEST_USERS["lab_liaison_headers"])
    validate_error(response, ApiErrorId.ERR_SPECIMEN_NOT_FOUND.value, expected_status=404)



def test_a_missing_required_insurance_plan_id_is_a_malformed_request(api):
    """PRD §3.1: "the payer is named with `insurance_plan_id`"
    PRD §2.11: "A malformed request — a missing required field, an unknown field,
    or a value outside its declared enum or numeric range — is rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/test_order_create_missing_insurance_plan_id_returns_invalid_request
    """
    data = setup_eligible_order()
    response = api_client.create_test_order({
        "service_center_id": data["center"]["id"], "patient_id": data["patient"]["id"],
        "ordering_provider_npi": "1700111222", "test_panel": "CMP",
        "collection_mode": "STANDARD", "patient_last_food_utc": "2026-09-01T12:00:00Z",
        "icd10_codes": [],
    }, INTAKE)
    error_id = response.json()["data"]["error_id"]
    assert response.status_code == 400
    assert error_id == ApiErrorId.ERR_INVALID_REQUEST.value
    assert error_id != ApiErrorId.ERR_INSURANCE_PLAN_NOT_FOUND.value


def test_a_duplicate_mrn_is_refused_and_does_not_register_a_second_patient(api):
    """PRD §3.1: "Registering a patient requires `full_name`, `birth_date`, and a
    unique `mrn`; a second registration presenting an `mrn` already on file is
    rejected with `ERR_DUPLICATE_MRN` (HTTP 400)"

    Design: Corner/entities/patient_create_rejects_a_duplicate_mrn
    """
    first = new_patient(full_name="Ada Nguyen", mrn="MRN-3103-001")
    response = api_client.create_patient({
        "full_name": "Ada N Ng", "birth_date": "1990-04-02T00:00:00Z",
        "mrn": "MRN-3103-001",
    }, INTAKE)
    validate_error(response, ApiErrorId.ERR_DUPLICATE_MRN.value, expected_status=400)

    listed = api_client.list_patients(INTAKE).json()["data"]
    assert len(listed) == 1
    assert listed[0]["id"] == first["id"]


def test_tube_requirement_minimum_volume_must_not_exceed_the_nominal_fill(api):
    """PRD §3.1: "The pediatric floor must satisfy a strict lower bound and an
    inclusive upper bound: it is strictly greater than zero and no greater than
    `required_volume_ml`."
    PRD §2.11: "A malformed request — a missing required field, an unknown field,
    or a value outside its declared enum or numeric range — is rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/tube_requirement_create_rejects_a_min_volume_above_the_nominal_volume
    """
    response = api_client.create_tube_requirement({
        "test_panel": "CBC", "tube_code": "SODIUM_HEPARIN_GREEN",
        "required_volume_ml": 5.0, "min_volume_ml": 6.0, "order_of_draw": 3,
        "stability_minutes": 240, "max_urgency_hours": 24, "special_handling_codes": [],
    }, TEST_USERS["lab_liaison_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)

    rows = api_client.list_tube_requirements(
        TEST_USERS["lab_liaison_headers"],
        params={"test_panel": "CBC"}).json()["data"]
    assert rows == []


def test_center_defaults_are_applied_when_the_optional_fields_are_omitted(api):
    """PRD §2.9: "Three further fields are optional at creation: `slot_minutes`
    defaults to 15, `pediatric_capable` defaults to false, and `draw_hold_minutes`
    defaults to 30. A new center begins with `ops_run_index` at 0 and
    `staffed_minutes_available` at 0"

    Design: Corner/entities/center_create_defaults_apply_and_posture_starts_open
    """
    body = api_client.create_service_center({
        "name": "Aurora Draw Station", "state_code": "TX",
        "timezone_offset_minutes": -300, "station_count": 2,
        "open_local_minutes": 480, "close_local_minutes": 1020,
    }, TEST_USERS["supervisor_headers"])
    assert body.status_code == 201
    center = body.json()["data"]
    assert body.json()["response_type"] == "object"
    assert center["slot_minutes"] == 15
    assert center["draw_hold_minutes"] == 30
    assert center["pediatric_capable"] is False
    assert center["ops_run_index"] == 0
    assert center["version"] == 1


def test_a_stale_expected_order_version_is_refused_on_appointment_create(api):
    """PRD §2.8: "When the supplied `expected_test_order_version` does not equal
    the order's current `version`, the operation is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.8: "The rejection exists to stop a client from writing against a
    snapshot of the order that another writer has since advanced"

    Design: Corner/cross_cutting_complexity_layers/a_stale_expected_test_order_version_on_appointment_create_is_refused
    """
    data = setup_eligible_order()
    seen = data["order"]["version"]

    response = api_client.create_appointment({
        "service_center_id": data["center"]["id"], "test_order_id": data["order"]["id"],
        "scheduled_start_utc": "2026-09-01T14:00:00Z", "slot_span": 1,
        "source": "BOOKED", "expected_test_order_version": seen - 1,
    }, INTAKE)
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)

    listed = api_client.list_appointments(
        INTAKE, params={"test_order_id": data["order"]["id"]}).json()["data"]
    assert listed == []
    assert get_order(data["order"]["id"])["version"] == seen


def test_a_fresh_expected_order_version_is_accepted_and_the_replay_is_refused(api):
    """PRD §2.8: "Booking a regular appointment against an order requires the
    same `expected_test_order_version` field."
    PRD §3.3: "A successful booking advances the order's `version` by one"

    Design: Corner/cross_cutting_complexity_layers/appointment_create_with_the_expected_version_succeeds_and_bumps_the_order
    """
    data = setup_eligible_order()
    seen = data["order"]["version"]

    appointment = validate_success(api_client.create_appointment({
        "service_center_id": data["center"]["id"], "test_order_id": data["order"]["id"],
        "scheduled_start_utc": "2026-09-01T14:00:00Z", "slot_span": 1,
        "source": "BOOKED", "expected_test_order_version": seen,
    }, INTAKE), 201)
    assert appointment["version"] == 1
    assert_version_incremented(get_order(data["order"]["id"])["version"], seen)

    replay = api_client.create_appointment({
        "service_center_id": data["center"]["id"], "test_order_id": data["order"]["id"],
        "scheduled_start_utc": "2026-09-01T14:30:00Z", "slot_span": 1,
        "source": "BOOKED", "expected_test_order_version": seen,
    }, INTAKE)
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)


def test_one_estimate_write_walks_the_order_balance_to_a_stale_appointment_write(api):
    """PRD §3.5: "Collecting an estimate writes to the order in a short cascade:
    the estimate row is created with its variant and its gross, discount, and
    net; the order's `patient_responsibility_cents` takes the estimate's net and
    its `self_pay_discount_cents` takes the gross minus the net; the order's
    `balance_remaining_cents` is reset to the leftover of the responsibility over
    `prepay_collected_cents`, floored at zero; and the order's `version` advances
    by one."
    PRD §3.5: "That last increment is consequential — it is precisely what
    invalidates an appointment write still carrying the
    `expected_test_order_version` the client read before the estimate was
    collected."

    Design: Difficulty/transitive_cascade/estimate_chain_order_balance_to_occ_rejection_depth4
    """
    data = setup_eligible_order()
    seen = data["order"]["version"]

    estimate = validate_success(api.create_estimate(
        data["order"]["id"],
        create_estimate_payload("ATTENDED_COLLECTED", seen), INTAKE), 201)
    assert estimate["net_patient_cents"] == 4000

    order = get_order(data["order"]["id"])
    assert order["patient_responsibility_cents"] == 4000
    assert order["balance_remaining_cents"] == 4000
    assert order["prepay_collected_cents"] == 0
    assert_version_incremented(order["version"], seen)

    response = api_client.create_appointment({
        "service_center_id": data["center"]["id"], "test_order_id": data["order"]["id"],
        "scheduled_start_utc": "2026-09-01T14:00:00Z", "slot_span": 1,
        "source": "BOOKED", "expected_test_order_version": seen,
    }, INTAKE)
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)
    listed = api_client.list_appointments(
        INTAKE, params={"test_order_id": data["order"]["id"]}).json()["data"]
    assert listed == []