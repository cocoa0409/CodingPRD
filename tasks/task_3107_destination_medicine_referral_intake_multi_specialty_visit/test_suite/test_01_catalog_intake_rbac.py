"""Catalog, intake, and RBAC tests: services, referrals, patients, records."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_medical_record,
    assert_patient,
    assert_specialty_service,
    create_medical_record_payload,
    create_patient_payload,
    create_referral_payload,
    create_specialty_service_payload,
    get_success_data,
    setup_approved_case,
    setup_case_with_holds,
    setup_referral_in_review,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_clock_set_returns_accepted_value(api):
    """PRD §2.4: "A `PlatformAdmin` may advance it by submitting a `current_utc`
    value to the test-driving clock capability, which replies with the accepted
    `current_utc`."

    Design: Corner/endpoints/clock_default_is_2026_09_01
    """
    resp = api.set_clock("2026-09-02T00:00:00Z", TEST_USERS["platform_admin_headers"])
    data = validate_success(resp, 200)
    assert data["current_utc"] == "2026-09-02T00:00:00Z"


def test_service_create_returns_declared_defaults(api):
    """PRD §3.1: "`supports_imaging` defaults to false and gates whether
    `IMAGING`-type visits may be scheduled against the service;
    `supports_remote_products` defaults to true and gates whether
    `SECOND_OPINION` and `REMOTE_CONSULT` cases may target it."

    Design: Corner/entities/specialty_service_create_returns_defaults_and_system_fields
    """
    set_clock()
    resp = api.create_specialty_service(
        create_specialty_service_payload(code="CARD", name="Cardiology"),
        TEST_USERS["platform_admin_headers"],
    )
    svc = validate_success(resp, 201)
    assert_specialty_service(svc)
    assert svc["supports_imaging"] is False
    assert svc["supports_remote_products"] is True
    assert svc["version"] == 1


def test_referral_cascade_patient_computed_flags(api):
    """PRD §3.2: "Submission cascade-creates the `Patient` record, copying
    `full_name`, `date_of_birth`, `residence_country`, `residence_state` (null
    for international patients), and `preferred_language` onto it, and computing
    two flags: `is_international`, true exactly when `residence_country` is not
    `US`, and `requires_interpreter`, which follows the supplied
    `needs_interpreter` when present and otherwise mirrors whether
    `preferred_language` is not `en`."

    Design: Corner/entities/referral_create_cascade_creates_patient_with_computed_flags
    """
    set_clock()
    resp = api.create_referral(
        create_referral_payload(
            patient=create_patient_payload(
                full_name="Ingrid International",
                residence_country="DE",
                residence_state=None,
                preferred_language="de",
            )
        ),
        TEST_USERS["intake_coordinator_headers"],
    )
    referral = validate_success(resp, 201)
    assert referral["status"] == "SUBMITTED"

    resp = api.get_referral_patient(
        referral["id"], TEST_USERS["intake_coordinator_headers"]
    )
    patients = get_success_data(resp)
    assert isinstance(patients, list) and len(patients) == 1
    patient = patients[0]
    assert_patient(patient)
    assert patient["is_international"] is True
    assert patient["requires_interpreter"] is True


def test_referral_create_missing_patient_rejected(api):
    """PRD §2.8: "Only then does the server check request-body shape — required
    fields present, enums valid, types correct (`ERR_INVALID_REQUEST`) — and
    then entity state preconditions (`ERR_INVALID_STATE`)."

    Design: Corner/entities/referral_create_missing_patient_returns_invalid_request
    """
    set_clock()
    payload = create_referral_payload()
    del payload["patient"]
    resp = api.create_referral(payload, TEST_USERS["intake_coordinator_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_get_visit_case_unknown_id_returns_not_found(api):
    """PRD §2.9: "The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the
    first identifier that does not correspond to an existing resource, and
    later segments are never consulted."

    Design: Corner/entities/get_visit_case_unknown_id_returns_not_found
    """
    set_clock()
    resp = api.get_visit_case(NON_EXISTENT_UUID, TEST_USERS["intake_coordinator_headers"])
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_referrals_list_pagination(api):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items
    returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The
    `offset` parameter sets how many items to skip and defaults to 0."

    Design: Corner/entities/referrals_list_paginates_with_total_count_and_has_more
    """
    set_clock()
    ic = TEST_USERS["intake_coordinator_headers"]
    for name in ("A One", "B Two", "C Three"):
        resp = api.create_referral(
            create_referral_payload(patient=create_patient_payload(full_name=name)),
            ic,
        )
        assert resp.status_code == 201

    resp = api.list_referrals(ic, params={"limit": 2, "offset": 0})
    rows, meta = validate_paginated(resp)
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0

    resp = api.list_referrals(ic, params={"limit": 2, "offset": 2})
    rows, meta = validate_paginated(resp)
    assert len(rows) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False


def test_patient_get_returns_copied_identity(api):
    """PRD §3.2: "Submission cascade-creates the `Patient` record, copying
    `full_name`, `date_of_birth`, `residence_country`, `residence_state` (null
    for international patients), and `preferred_language` onto it, and
    computing two flags: `is_international`, true exactly when
    `residence_country` is not `US`, and `requires_interpreter`, which follows
    the supplied `needs_interpreter` when present and otherwise mirrors
    whether `preferred_language` is not `en`."

    Design: Corner/entities/patient_read_only_surface_no_update_endpoints
    """
    set_clock()
    resp = api.create_referral(
        create_referral_payload(
            patient=create_patient_payload(
                full_name="Ingrid International",
                residence_country="DE",
                residence_state=None,
                preferred_language="de",
            )
        ),
        TEST_USERS["intake_coordinator_headers"],
    )
    referral = validate_success(resp, 201)
    patients = get_success_data(
        api.get_referral_patient(referral["id"], TEST_USERS["intake_coordinator_headers"])
    )
    patient_id = patients[0]["id"]
    resp = api.get_patient(patient_id, TEST_USERS["intake_coordinator_headers"])
    patient = validate_success(resp, 200)
    assert patient["full_name"] == "Ingrid International"
    assert patient["residence_country"] == "DE"


def test_referral_initial_state_is_submitted(api):
    """PRD §3.2: "The referral itself is born `SUBMITTED`, and its `status`
    then walks a single linear pipeline with one branch: `SUBMITTED` →
    `RECORDS_PENDING` → `IN_REVIEW` → `REVIEWED` → `CLOSED`, with `DECLINED`
    as a terminal diversion reachable from `IN_REVIEW`."

    Design: Corner/state_machines/referral_initial_state_is_submitted
    """
    set_clock()
    resp = api.create_referral(
        create_referral_payload(), TEST_USERS["intake_coordinator_headers"]
    )
    referral = validate_success(resp, 201)
    assert referral["status"] == "SUBMITTED"
    resp = api.get_referral(referral["id"], TEST_USERS["intake_coordinator_headers"])
    assert validate_success(resp, 200)["status"] == "SUBMITTED"


def test_submit_review_without_verified_record_rejected(api):
    """PRD §3.2: "Submitting with zero verified records is rejected with
    `ERR_NO_VERIFIED_RECORDS`; submitting from any state other than
    `RECORDS_PENDING` is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/submit_review_without_verified_record_rejected
    """
    set_clock()
    ic = TEST_USERS["intake_coordinator_headers"]
    referral = get_success_data(api.create_referral(create_referral_payload(), ic))
    record = get_success_data(
        api.create_medical_record(referral["id"], create_medical_record_payload(), ic)
    )
    assert record["status"] == "RECEIVED"
    resp = api.submit_review(referral["id"], ic)
    validate_error(resp, ApiErrorId.ERR_NO_VERIFIED_RECORDS)
    referral_after = get_success_data(api.get_referral(referral["id"], ic))
    assert referral_after["status"] == "RECORDS_PENDING"


def test_verify_on_terminal_record_rejected(api):
    """PRD §3.2: "A `CaseReviewer` may verify or reject a record that is
    currently `RECEIVED`; acting on a record in any other state yields
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/verify_on_terminal_record_rejected
    """
    set_clock()
    referral, record = setup_referral_in_review()
    assert record["status"] == "VERIFIED"
    resp = api.verify_medical_record(
        referral["id"], record["id"], TEST_USERS["case_reviewer_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_case_reviewer_cannot_create_referral(api):
    """PRD §2.1: "Once the headers are present, the role is checked against the
    permission matrix; an authenticated user attempting an operation outside
    their role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §4: POST /referrals is authorized for IntakeCoordinator only.

    Design: Corner/rbac/case_reviewer_cannot_create_referral
    """
    set_clock()
    resp = api.create_referral(
        create_referral_payload(), TEST_USERS["case_reviewer_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_financial_counselor_cannot_record_reviews(api):
    """PRD §2.1: "Once the headers are present, the role is checked against the
    permission matrix; an authenticated user attempting an operation outside
    their role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §4: POST /visit-cases/{id}/reviews is authorized for CaseReviewer only.

    Design: Corner/rbac/financial_counselor_cannot_record_reviews
    """
    set_clock()
    card = get_success_data(
        api.create_specialty_service(
            create_specialty_service_payload(code="CARD", name="Cardiology"),
            TEST_USERS["platform_admin_headers"],
        )
    )
    neur = get_success_data(
        api.create_specialty_service(
            create_specialty_service_payload(code="NEUR", name="Neurology"),
            TEST_USERS["platform_admin_headers"],
        )
    )
    referral, _rec = setup_referral_in_review()
    ic = TEST_USERS["intake_coordinator_headers"]
    case = get_success_data(
        api.create_visit_case(
            {
                "referral_id": referral["id"],
                "case_type": "DESTINATION",
                "care_team_specialty_ids": [card["id"], neur["id"]],
            },
            ic,
        )
    )
    resp = api.create_case_review(
        case["id"],
        {"outcome": "APPROVE", "notes": "fc attempt"},
        TEST_USERS["financial_counselor_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_intake_coordinator_cannot_waive_deposit(api):
    """PRD §2.1: "an authenticated user attempting an operation outside their
    role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §4: POST /visit-cases/{id}/financial-clearance/waive is authorized for
    FinancialCounselor only.

    Design: Corner/rbac/intake_coordinator_cannot_waive_deposit
    """
    set_clock()
    ctx = setup_approved_case()
    resp = api.waive_clearance(
        ctx["case"]["id"], TEST_USERS["intake_coordinator_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_logistics_coordinator_cannot_confirm_slots(api):
    """PRD §2.1: "an authenticated user attempting an operation outside their
    role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §4: POST /slots/{id}/confirm is authorized for IntakeCoordinator only.

    Design: Corner/rbac/logistics_coordinator_cannot_confirm_slots
    """
    set_clock()
    ctx = setup_case_with_holds([{"start_min": 540, "end_min": 600}])
    slot_id = ctx["slots"][0]["id"]
    resp = api.confirm_slot(slot_id, TEST_USERS["logistics_coordinator_headers"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_all_roles_can_read_shared_get_endpoints(api):
    """PRD §4: GET /referrals/{id} lists PlatformAdmin, IntakeCoordinator,
    CaseReviewer, FinancialCounselor, and LogisticsCoordinator as authorized
    roles.

    Design: Corner/rbac/all_roles_can_read_shared_get_endpoints
    """
    set_clock()
    referral = get_success_data(
        api.create_referral(
            create_referral_payload(), TEST_USERS["intake_coordinator_headers"]
        )
    )
    resp_lc = api.get_referral(
        referral["id"], TEST_USERS["logistics_coordinator_headers"]
    )
    resp_fc = api.get_referral(
        referral["id"], TEST_USERS["financial_counselor_headers"]
    )
    assert validate_success(resp_lc, 200)["id"] == referral["id"]
    assert validate_success(resp_fc, 200)["id"] == referral["id"]
