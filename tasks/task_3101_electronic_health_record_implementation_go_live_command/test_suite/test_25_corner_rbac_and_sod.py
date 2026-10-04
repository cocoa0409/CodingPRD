"""RBAC denials and the segregation-of-duties pair."""

import pytest

from test_helpers import (
    build_user_headers,
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    get_success_data,
    get_program,
    get_staff,
    setup_program,
    setup_program_and_facility,
    setup_program_facility_department,
    create_credentialed_trainer_payload,
    create_proficiency_exam_payload,
    create_staff_payload,
    make_credentialed_trainer_headers,
    make_headers_for_role,
    DIRECTOR,
    ANALYST,
    BUILD_ANALYST,
    TRAINING,
    CONVERSION,
    RECONCILER,
    TEST_LEAD,
)


# ===========================================================================
# c_role_outside_endpoint_roles_returns_unauthorized
# ===========================================================================

def test_an_unlisted_role_cannot_open_a_program(api, training_headers):
    """PRD §2.1: "each operation is bound to a permitted set of roles; a caller
    whose `X-User-Role` is not authorized for the requested operation receives
    `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "The authorized roles column below names the roles permitted to invoke
    the operation; a caller authenticated under any other role receives
    `ERR_UNAUTHORIZED`."

    Design: Corner/errors/c_role_outside_endpoint_roles_returns_unauthorized
    """
    from test_helpers import set_clock

    set_clock()
    refused = api_client.create_ehr_implementation(
        {
            "program_name": "Forbidden Program",
            "vendor_release": "2026.2",
            "go_live_target_utc": "2026-12-01T00:00:00Z",
        },
        training_headers,
    )
    validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


def test_the_unauthorized_program_creation_persists_nothing(api, training_headers):
    """PRD §2.1: "a caller whose `X-User-Role` is not authorized for the requested
    operation receives `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.1: "An `ImplementationDirector` opens a program by naming it."

    Design: Corner/errors/c_role_outside_endpoint_roles_returns_unauthorized
    """
    from test_helpers import set_clock, validate_paginated

    set_clock()
    api_client.create_ehr_implementation(
        {
            "program_name": "Forbidden Program",
            "vendor_release": "2026.2",
            "go_live_target_utc": "2026-12-01T00:00:00Z",
        },
        training_headers,
    )
    rows, meta = validate_paginated(api_client.list_ehr_implementations(DIRECTOR))
    assert meta["total_count"] == 0


# ===========================================================================
# c_ehr_implementation_get_with_unknown_id_returns_404
# ===========================================================================

def test_reading_an_unallocated_program_reports_the_entity_specific_not_found(api, director_headers):
    """PRD §2.8: "A conversion batch requested beneath a facility that does not
    exist yields `ERR_FACILITY_NOT_FOUND` (HTTP 404) before the system ever
    considers the batch id; a message requested beneath a channel that does not
    exist yields `ERR_CHANNEL_NOT_FOUND` (HTTP 404)."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."

    Design: Corner/errors/c_ehr_implementation_get_with_unknown_id_returns_404
    """
    from test_helpers import set_clock

    set_clock()
    response = api_client.get_ehr_implementation(
        "00000000-0000-4000-8000-000000000000", director_headers
    )
    validate_error(response, ApiErrorId.ERR_EHR_IMPLEMENTATION_NOT_FOUND, expected_status=404)
    assert response.json()["data"]["error_id"] and response.json()["data"]["message"]


def test_the_not_found_envelope_carries_the_error_response_shape(api, director_headers):
    """PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/errors/c_ehr_implementation_get_with_unknown_id_returns_404
    """
    from test_helpers import set_clock

    set_clock()
    response = api_client.get_ehr_implementation(
        "00000000-0000-4000-8000-000000000000", director_headers
    )
    body = response.json()
    assert body["response_type"] == "error"
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}


# ===========================================================================
# c_build_analyst_cannot_issue_credentials
# ===========================================================================

def test_a_build_analyst_cannot_issue_a_go_live_credential(api, build_analyst_headers, training_headers):
    """PRD §2.1: "each operation is bound to a permitted set of roles; a caller
    whose `X-User-Role` is not authorized for the requested operation receives
    `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "Beyond authentication, each operation is bound to a permitted set of roles; a caller whose `X-User-Role` is not authorized for the requested operation receives `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "The authorized roles column below names the roles permitted to invoke the operation; a caller authenticated under any other role receives `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/c_build_analyst_cannot_issue_credentials
    """
    prog, fac, dept = setup_program_facility_department()
    staff = get_success_data(api_client.create_staff(
        prog["id"],
        create_staff_payload(fac["id"], dept["id"], full_name="Fiona Blake"),
        training_headers,
    ))

    refused = api_client.issue_credential(staff["id"], build_analyst_headers)
    validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


def test_the_refused_credential_issuance_leaves_the_staffer_registered(api, build_analyst_headers, training_headers):
    """PRD §3.4: "A newly registered person starts in `REGISTERED` status with
    `accumulated_training_hours` at 0."
    PRD §2.1: "Beyond authentication, each operation is bound to a permitted set of roles; a caller whose `X-User-Role` is not authorized for the requested operation receives `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "The authorized roles column below names the roles permitted to invoke the operation; a caller authenticated under any other role receives `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/c_build_analyst_cannot_issue_credentials
    """
    prog, fac, dept = setup_program_facility_department()
    staff = get_success_data(api_client.create_staff(
        prog["id"],
        create_staff_payload(fac["id"], dept["id"], full_name="Fiona Blake"),
        training_headers,
    ))
    api_client.issue_credential(staff["id"], build_analyst_headers)

    read = get_staff(staff["id"], training_headers)
    assert read["status"] == "REGISTERED"


# ===========================================================================
# c_implementation_analyst_cannot_advance_epoch
# ===========================================================================

def test_the_read_only_analyst_cannot_advance_the_ops_run_epoch(api, analyst_headers):
    """PRD §2.6: "The program carries an integer `current_epoch_index` that
    begins at 0 and is advanced by exactly one each time the epoch-advance
    capability is exercised by an `ImplementationDirector`; no other operation
    changes it."
    PRD §2.1: "a caller whose `X-User-Role` is not authorized for the requested
    operation receives `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/c_implementation_analyst_cannot_advance_epoch
    """
    prog = setup_program()

    refused = api_client.advance_epoch(prog["id"], analyst_headers)
    validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


def test_the_refused_epoch_advance_leaves_the_counter_at_zero(api, analyst_headers, director_headers):
    """PRD §2.6: "The program carries an integer `current_epoch_index` that
    begins at 0".
    PRD §2.1: "Beyond authentication, each operation is bound to a permitted set of roles; a caller whose `X-User-Role` is not authorized for the requested operation receives `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "The authorized roles column below names the roles permitted to invoke the operation; a caller authenticated under any other role receives `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/c_implementation_analyst_cannot_advance_epoch
    """
    prog = setup_program()
    api_client.advance_epoch(prog["id"], analyst_headers)

    read = get_program(prog["id"], director_headers)
    assert read["current_epoch_index"] == 0


# ===========================================================================
# c_credentialed_trainer_cannot_certify_trainer_records
# ===========================================================================

def test_a_credentialed_trainer_cannot_certify_a_trainer_record(api, training_headers):
    """PRD §2.1: "each operation is bound to a permitted set of roles; a caller
    whose `X-User-Role` is not authorized for the requested operation receives
    `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "Beyond authentication, each operation is bound to a permitted set of roles; a caller whose `X-User-Role` is not authorized for the requested operation receives `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "The authorized roles column below names the roles permitted to invoke the operation; a caller authenticated under any other role receives `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/c_credentialed_trainer_cannot_certify_trainer_records
    """
    prog, fac, dept = setup_program_facility_department()
    staff = get_success_data(api_client.create_staff(
        prog["id"],
        create_staff_payload(fac["id"], dept["id"], full_name="Gita Shah"),
        training_headers,
    ))
    trainer = get_success_data(api_client.create_credentialed_trainer(
        staff["id"],
        create_credentialed_trainer_payload(staff["version"], observation_hours=8),
        training_headers,
    ))

    refused = api_client.certify_trainer(
        trainer["id"], make_credentialed_trainer_headers(trainer["id"])
    )
    validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


def test_the_refused_certification_leaves_the_record_pending(api, training_headers):
    """PRD §3.4: "The record begins in `PENDING_OBSERVATION`."
    PRD §2.1: "Beyond authentication, each operation is bound to a permitted set of roles; a caller whose `X-User-Role` is not authorized for the requested operation receives `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "The authorized roles column below names the roles permitted to invoke the operation; a caller authenticated under any other role receives `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/c_credentialed_trainer_cannot_certify_trainer_records
    """
    prog, fac, dept = setup_program_facility_department()
    staff = get_success_data(api_client.create_staff(
        prog["id"],
        create_staff_payload(fac["id"], dept["id"], full_name="Gita Shah"),
        training_headers,
    ))
    trainer = get_success_data(api_client.create_credentialed_trainer(
        staff["id"],
        create_credentialed_trainer_payload(staff["version"], observation_hours=8),
        training_headers,
    ))
    api_client.certify_trainer(trainer["id"], make_credentialed_trainer_headers(trainer["id"]))

    read = validate_success(api_client.get_credentialed_trainer(trainer["id"], training_headers), 200)
    assert read["status"] == "PENDING_OBSERVATION"


# ===========================================================================
# c_conversion_analyst_cannot_reconcile_orders
# ===========================================================================

def test_the_analyst_who_converted_the_order_cannot_reconcile_it(api, conversion_headers):
    """PRD §2.1: "each operation is bound to a permitted set of roles; a caller
    whose `X-User-Role` is not authorized for the requested operation receives
    `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "Beyond authentication, each operation is bound to a permitted set of roles; a caller whose `X-User-Role` is not authorized for the requested operation receives `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "The authorized roles column below names the roles permitted to invoke the operation; a caller authenticated under any other role receives `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/c_conversion_analyst_cannot_reconcile_orders
    """
    prog, fac = setup_program_and_facility()
    order = get_success_data(api_client.create_patient_order(
        fac["id"],
        {"patient_mrn": "MRN-8200", "order_type": "LAB",
         "encounter_utc": "2026-08-30T00:00:00Z", "legacy_charge_cents": 10000},
        conversion_headers,
    ))

    refused = api_client.reconcile_order(order["id"], conversion_headers)
    validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


def test_the_refused_reconciliation_leaves_the_order_converted(api, conversion_headers, analyst_headers):
    """PRD §3.7: "The order starts in clinical state `CONVERTED` and billing state
    `UNPOSTED`".
    PRD §2.1: "Beyond authentication, each operation is bound to a permitted set of roles; a caller whose `X-User-Role` is not authorized for the requested operation receives `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "The authorized roles column below names the roles permitted to invoke the operation; a caller authenticated under any other role receives `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/c_conversion_analyst_cannot_reconcile_orders
    """
    prog, fac = setup_program_and_facility()
    order = get_success_data(api_client.create_patient_order(
        fac["id"],
        {"patient_mrn": "MRN-8200", "order_type": "LAB",
         "encounter_utc": "2026-08-30T00:00:00Z", "legacy_charge_cents": 10000},
        conversion_headers,
    ))
    api_client.reconcile_order(order["id"], conversion_headers)

    read = validate_success(api_client.get_patient_order(order["id"], analyst_headers), 200)
    assert read["clinical_state"] == "CONVERTED"


# ===========================================================================
# c_trainer_cannot_both_proctor_result_and_certify
# ===========================================================================

def _trainer_record_for(staff_id, application_code="CLN", certification_level="STANDARD",
                        observation_hours=8):
    """Start a second trainer record against the staff member's fresh version.

    PRD §3.4: "supplying ... the staff version guard described in §2.7, which
    also increments the staff member's `version` by one." A record started on a
    version the staff member has already moved past is a `ERR_STALE_VERSION`
    request, so the guard must be re-read before this create.
    """
    refreshed = get_staff(staff_id, TRAINING)
    return get_success_data(api_client.create_credentialed_trainer(
        staff_id,
        create_credentialed_trainer_payload(
            refreshed["version"], application_code=application_code,
            certification_level=certification_level, observation_hours=observation_hours,
        ),
        TRAINING,
    ))


def test_a_principal_who_proctored_an_exam_cannot_certify_that_staff_member(api, training_headers):
    """PRD §2.10: "A caller whose `X-User-ID` has already recorded the result of
    a proficiency exam may not also certify that same staff member as a
    credentialed trainer; and a caller who approved a go/no-go decision may not
    also resolve the test defect linked to that decision."
    PRD §2.11: "And because the segregation check sits ahead of the
    trainer-credential check, a self-dealing certifier surfaces as
    `ERR_SOD_VIOLATION` even when their credential is also defective."

    Design: Corner/rbac/c_trainer_cannot_both_proctor_result_and_certify
    """
    prog, fac, dept = setup_program_facility_department()
    staff = get_success_data(api_client.create_staff(
        prog["id"],
        create_staff_payload(fac["id"], dept["id"], full_name="Hana Ito"),
        training_headers,
    ))
    trainer = get_success_data(api_client.create_credentialed_trainer(
        staff["id"],
        create_credentialed_trainer_payload(staff["version"], observation_hours=8),
        training_headers,
    ))
    get_success_data(api_client.certify_trainer(trainer["id"], training_headers))
    exam = get_success_data(api_client.schedule_exam(
        staff["id"], create_proficiency_exam_payload(trainer["id"]), training_headers
    ))
    second = _trainer_record_for(
        staff["id"], application_code="CLN-ADV",
        certification_level="ADVANCED", observation_hours=12,
    )

    recorded = validate_success(
        api_client.record_exam_result(
            exam["id"], {"exam_score": 90}, make_credentialed_trainer_headers(trainer["id"])
        ),
        200,
    )
    assert recorded["status"] == "COMPLETED_PASS"

    self_dealing_headers = make_headers_for_role("TrainingCoordinator", trainer["id"])
    refused = api_client.certify_trainer(second["id"], self_dealing_headers)
    validate_error(refused, ApiErrorId.ERR_SOD_VIOLATION, expected_status=403)


def test_the_self_dealt_second_trainer_record_is_never_certified(api, training_headers):
    """PRD §2.10: "Two paired activities must not be performed by the same
    principal."
    PRD §3.4: "The record begins in `PENDING_OBSERVATION`."

    Design: Corner/rbac/c_trainer_cannot_both_proctor_result_and_certify
    """
    prog, fac, dept = setup_program_facility_department()
    staff = get_success_data(api_client.create_staff(
        prog["id"],
        create_staff_payload(fac["id"], dept["id"], full_name="Hana Ito"),
        training_headers,
    ))
    trainer = get_success_data(api_client.create_credentialed_trainer(
        staff["id"],
        create_credentialed_trainer_payload(staff["version"], observation_hours=8),
        training_headers,
    ))
    get_success_data(api_client.certify_trainer(trainer["id"], training_headers))
    exam = get_success_data(api_client.schedule_exam(
        staff["id"], create_proficiency_exam_payload(trainer["id"]), training_headers
    ))
    second = _trainer_record_for(
        staff["id"], application_code="CLN-ADV",
        certification_level="ADVANCED", observation_hours=12,
    )
    get_success_data(api_client.record_exam_result(
        exam["id"], {"exam_score": 90}, make_credentialed_trainer_headers(trainer["id"])
    ))
    api_client.certify_trainer(
        second["id"], make_headers_for_role("TrainingCoordinator", trainer["id"])
    )

    read = validate_success(
        api_client.get_credentialed_trainer(second["id"], training_headers), 200
    )
    assert read["status"] == "PENDING_OBSERVATION"