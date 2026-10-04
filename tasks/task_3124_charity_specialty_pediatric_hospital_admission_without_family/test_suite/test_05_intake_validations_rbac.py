"""Application intake: creation fields, defaults, computed fields, validation
ladder, no-means-test, capacity, and role-based access control."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_application_payload,
    create_program,
    create_referral_source,
    create_referral_source_payload,
    set_clock,
    setup_accepted_application,
    setup_application_with_accept_quorum,
    setup_hospital_with_program,
    setup_submitted_application,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Corner/entities
# ---------------------------------------------------------------------------

def test_application_get_unknown_id_returns_application_not_found(api, intake_headers):
    """PRD §2.8: "Existence failures surface as the entity-specific 404 error (`ERR_HOSPITAL_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_CLINIC_NOT_FOUND`, `ERR_SCREENING_NOT_FOUND`, `ERR_FUND_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_BILLING_ACCOUNT_NOT_FOUND`, `ERR_CARE_PLAN_NOT_FOUND`, `ERR_STAGE_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, `ERR_REFERRAL_SOURCE_NOT_FOUND`, or `ERR_POLICY_NOT_FOUND`)."

    Design: Corner/entities/application_get_unknown_id_returns_application_not_found
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api.get_application(NON_EXISTENT_UUID, intake_headers)
    error = validate_error(
        resp, ApiErrorId.ERR_APPLICATION_NOT_FOUND.value, expected_status=404,
    )
    assert isinstance(error.get("message"), str) and error["message"]


def test_application_create_missing_required_field_returns_invalid_request(
        api, intake_headers):
    """PRD §2.8: "Malformed request bodies (a missing required field, a type mismatch, or an out-of-enum value) fail with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/application_create_missing_required_field_returns_invalid_request
    """
    set_clock("2026-09-01T00:00:00Z")
    _, program, source, _ = setup_submitted_application(
        patient_full_name="Kid Warmup",
    )
    payload = create_application_payload(source["id"], program["id"])
    del payload["condition_category"]
    resp = api.create_application(payload, intake_headers)
    error = validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)
    assert error["error_id"] != ApiErrorId.ERR_CONDITION_OUT_OF_SCOPE.value

    remaining, _ = validate_paginated(api.list_applications(intake_headers))
    assert len(remaining) == 1  # only the warmup application exists


def test_application_create_omitting_family_ability_defaults_declined(api):
    """PRD §2.10: "First, the `family_ability_to_pay` field on a patient application is recorded for statistical purposes only and must never be consulted by any acceptance logic; it defaults to `DECLINED_TO_STATE` when the caller does not supply it."

    Design: Corner/entities/application_create_omitting_family_ability_defaults_declined
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, application = setup_submitted_application(
        patient_full_name="Kid Default",
    )
    assert application["family_ability_to_pay"] == "DECLINED_TO_STATE"
    assert application["status"] == "SUBMITTED"
    assert application["review_round"] == 1


def test_application_computed_age_and_international_flags(api):
    """PRD §3.2: "Two fields are derived at creation and never change afterward: `is_international`, which is true exactly when the referral source's `country_code` is not `US`, and `age_at_submission_months`, the floor of the span between the patient's date of birth and the submission date in whole months, computed against the logical clock."

    Design: Corner/entities/application_computed_age_and_international_flags
    """
    set_clock("2026-09-01T00:00:00Z")
    hospital, program, rs_us = setup_hospital_with_program(
        program_overrides={"accepts_international": True},
    )
    rs_mx = create_referral_source(
        source_type="INTERNATIONAL_PARTNER", display_name="Partner MX",
        contact_email="mx@example.org", country_code="MX",
    )
    from test_helpers import create_application
    a_us = create_application(
        rs_us["id"], program["id"], patient_full_name="Kid US",
        patient_date_of_birth="2020-01-15T00:00:00Z",
    )
    a_mx = create_application(
        rs_mx["id"], program["id"], patient_full_name="Kid MX",
        patient_date_of_birth="2020-01-15T00:00:00Z",
        home_latitude=19.4, home_longitude=-99.1,
    )
    assert a_us["age_at_submission_months"] == 79
    assert a_us["is_international"] is False
    assert a_mx["age_at_submission_months"] == 79
    assert a_mx["is_international"] is True


def test_application_create_client_supplied_system_fields_are_ignored(api, intake_headers):
    """PRD §3.2: "New applications start in `SUBMITTED` with `review_round` at 1."

    Design: Corner/entities/application_create_client_supplied_system_fields_are_ignored_input
    """
    set_clock("2026-09-01T00:00:00Z")
    _, program, source = setup_hospital_with_program()
    payload = create_application_payload(
        source["id"], program["id"], patient_full_name="Kid Sneaky",
    )
    payload["status"] = "ACCEPTED"
    payload["version"] = 99
    payload["review_round"] = 7
    resp = api.create_application(payload, intake_headers)
    application = validate_success(resp, expected_status=201)
    assert application["status"] == "SUBMITTED"
    assert application["review_round"] == 1
    assert application["version"] == 1


def test_program_create_out_of_enum_category_returns_invalid_request(api, admin_headers):
    """PRD §2.8: "Malformed request bodies (a missing required field, a type mismatch, or an out-of-enum value) fail with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/program_create_out_of_enum_category_returns_invalid_request
    """
    set_clock("2026-09-01T00:00:00Z")
    from test_helpers import create_hospital, create_program_payload
    hospital = create_hospital()
    payload = create_program_payload(category="CARDIOLOGY")
    resp = api.create_program(hospital["id"], payload, admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)

    programs, _ = validate_paginated(api.list_programs(hospital["id"], admin_headers))
    assert programs == []


def test_application_create_body_fks_checked_in_declared_order(api, intake_headers):
    """PRD §2.8: "Body-supplied foreign keys are validated after path identifiers, in the endpoint's declared input order — on application creation, `referral_source_id` is checked before `program_id`, which is checked before `screening_id`."

    Design: Corner/entities/application_create_body_fks_checked_in_declared_order
    """
    set_clock("2026-09-01T00:00:00Z")
    source = create_referral_source()
    unknown_source = "00000000-0000-4000-8000-000000000001"
    unknown_program = "00000000-0000-4000-8000-000000000002"

    both = api.create_application(
        create_application_payload(unknown_source, unknown_program), intake_headers,
    )
    validate_error(both, ApiErrorId.ERR_REFERRAL_SOURCE_NOT_FOUND.value,
                   expected_status=404)

    only_program = api.create_application(
        create_application_payload(source["id"], unknown_program), intake_headers,
    )
    validate_error(only_program, ApiErrorId.ERR_PROGRAM_NOT_FOUND.value,
                   expected_status=404)


def test_application_review_immutable_no_update_endpoint(api, reviewer1_headers):
    """PRD §2.5: "One deliberate exception: the `ApplicationReview` event log is append-only and carries only `id` and `created_at` — both `updated_at` and `version` are absent from review events, because an event, once written, never changes."

    Design: Corner/entities/application_review_immutable_no_update_endpoint
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, application = setup_submitted_application(patient_full_name="Kid Log")
    open_review = __import__("test_helpers").open_review
    open_review(application["id"])

    events, _ = validate_paginated(api.list_reviews(application["id"], reviewer1_headers))
    assert len(events) == 1
    event = events[0]
    assert event["action"] == "OPEN_ROUND"
    assert event["round_number"] == 1
    assert event["reviewer_user_id"] == "rcm-1"
    assert "version" not in event
    assert "updated_at" not in event


# ---------------------------------------------------------------------------
# Corner/validations
# ---------------------------------------------------------------------------

def test_condition_out_of_scope_category_mismatch(api, intake_headers):
    """PRD §3.2: "First, condition scope: the application's `condition_category` must equal the applied program's `category`, and a `condition_category` of `OTHER` is never in scope for any program — violations are rejected with `ERR_CONDITION_OUT_OF_SCOPE` (HTTP 422)."

    Design: Corner/validations/condition_out_of_scope_category_mismatch
    """
    set_clock("2026-09-01T00:00:00Z")
    _, program, source = setup_hospital_with_program()
    payload = create_application_payload(
        source["id"], program["id"], patient_full_name="Kid WrongCat",
        condition_category="BURN",
    )
    resp = api.create_application(payload, intake_headers)
    validate_error(resp, ApiErrorId.ERR_CONDITION_OUT_OF_SCOPE.value, expected_status=422)

    applications, _ = validate_paginated(api.list_applications(intake_headers))
    assert applications == []


def test_condition_category_other_never_in_scope(api, intake_headers):
    """PRD §3.2: "First, condition scope: the application's `condition_category` must equal the applied program's `category`, and a `condition_category` of `OTHER` is never in scope for any program — violations are rejected with `ERR_CONDITION_OUT_OF_SCOPE` (HTTP 422)."

    Design: Corner/validations/condition_category_other_never_in_scope
    """
    set_clock("2026-09-01T00:00:00Z")
    _, program, source = setup_hospital_with_program()
    payload = create_application_payload(
        source["id"], program["id"], patient_full_name="Kid Other",
        condition_category="OTHER",
    )
    resp = api.create_application(payload, intake_headers)
    validate_error(resp, ApiErrorId.ERR_CONDITION_OUT_OF_SCOPE.value, expected_status=422)


def test_age_eligibility_exclusive_upper_bound_rejected(api, intake_headers):
    """PRD §3.2: "Second, age eligibility: the patient's `age_at_submission_months` must be at least the program's `min_age_months` and strictly less than its `max_age_months`, otherwise `ERR_AGE_INELIGIBLE` (HTTP 422)."

    Design: Corner/validations/age_eligibility_exclusive_upper_bound
    """
    set_clock("2026-09-01T00:00:00Z")
    _, program, source = setup_hospital_with_program(
        program_overrides={"max_age_months": 192},
    )
    payload = create_application_payload(
        source["id"], program["id"], patient_full_name="Kid TooOld",
        patient_date_of_birth="2010-09-01T00:00:00Z",  # exactly 192 months
    )
    resp = api.create_application(payload, intake_headers)
    validate_error(resp, ApiErrorId.ERR_AGE_INELIGIBLE.value, expected_status=422)


def test_age_eligibility_one_month_younger_accepted(api, intake_headers):
    """PRD §3.1: "Programs declare an age window: `min_age_months` (at least 0) is the youngest patient, in whole months at application submission, the program will consider, and `max_age_months` is an exclusive upper bound — the patient must be strictly younger than `max_age_months`, and `max_age_months` must be greater than `min_age_months`."

    Design: Corner/validations/age_eligibility_exclusive_upper_bound
    """
    set_clock("2026-09-01T00:00:00Z")
    _, program, source = setup_hospital_with_program(
        program_overrides={"max_age_months": 192},
    )
    payload = create_application_payload(
        source["id"], program["id"], patient_full_name="Kid JustYoung",
        patient_date_of_birth="2010-10-01T00:00:00Z",  # 191 months
    )
    resp = api.create_application(payload, intake_headers)
    application = validate_success(resp, expected_status=201)
    assert application["status"] == "SUBMITTED"
    assert application["age_at_submission_months"] == 191


def test_international_application_to_domestic_only_program(api, intake_headers):
    """PRD §3.2: "Third, international routing: an application whose `is_international` is true may only target a program with `accepts_international` true, otherwise `ERR_INTERNATIONAL_NOT_ACCEPTED` (HTTP 422)."

    Design: Corner/validations/international_application_to_domestic_only_program
    """
    set_clock("2026-09-01T00:00:00Z")
    hospital, _, _ = setup_hospital_with_program()
    p_dom = create_program(hospital["id"], accepts_international=False)
    rs_mx = create_referral_source(
        source_type="INTERNATIONAL_PARTNER", display_name="Partner MX",
        contact_email="mx@example.org", country_code="MX",
    )
    payload = create_application_payload(
        rs_mx["id"], p_dom["id"], patient_full_name="Kid MX Dom",
        home_latitude=19.4, home_longitude=-99.1,
    )
    resp = api.create_application(payload, intake_headers)
    validate_error(resp, ApiErrorId.ERR_INTERNATIONAL_NOT_ACCEPTED.value,
                   expected_status=422)


def test_international_application_to_accepting_program_succeeds(api, intake_headers):
    """PRD §3.1: "The `accepts_international` flag (default false) records whether the program takes international referrals"

    Design: Corner/validations/international_application_to_domestic_only_program
    """
    set_clock("2026-09-01T00:00:00Z")
    hospital, _, _ = setup_hospital_with_program()
    p_intl = create_program(hospital["id"], accepts_international=True)
    rs_mx = create_referral_source(
        source_type="INTERNATIONAL_PARTNER", display_name="Partner MX",
        contact_email="mx@example.org", country_code="MX",
    )
    payload = create_application_payload(
        rs_mx["id"], p_intl["id"], patient_full_name="Kid MX Intl",
        home_latitude=19.4, home_longitude=-99.1,
    )
    resp = api.create_application(payload, intake_headers)
    application = validate_success(resp, expected_status=201)
    assert application["status"] == "SUBMITTED"
    assert application["is_international"] is True


def test_acceptance_never_consults_family_ability_to_pay(api, admin_headers):
    """PRD §3.2: "the optional `family_ability_to_pay` records one of `UNABLE`, `PARTIAL`, `ABLE`, or `DECLINED_TO_STATE` — purely statistical, never consulted by acceptance."

    Design: Corner/validations/acceptance_never_consults_family_ability_to_pay
    """
    set_clock("2026-09-01T00:00:00Z")
    hospital, program, source = setup_hospital_with_program()
    from test_helpers import (
        cast_vote, create_application, decide, open_review,
    )
    a_unable = create_application(
        source["id"], program["id"], patient_full_name="Kid Unable",
        family_ability_to_pay="UNABLE",
    )
    open_review(a_unable["id"])
    cast_vote(a_unable["id"], vote="ACCEPT", vote_weight=2, reviewer="rcm-1")
    cast_vote(a_unable["id"], vote="ACCEPT", vote_weight=1, reviewer="rcm-2")
    a_able = create_application(
        source["id"], program["id"], patient_full_name="Kid Able",
        family_ability_to_pay="ABLE",
    )
    open_review(a_able["id"])
    cast_vote(a_able["id"], vote="ACCEPT", vote_weight=2, reviewer="rcm-1")
    cast_vote(a_able["id"], vote="ACCEPT", vote_weight=1, reviewer="rcm-2")

    decided_unable = decide(a_unable["id"], decision="ACCEPT",
                            decision_reason="means-blind", reviewer="rcm-3")
    decided_able = decide(a_able["id"], decision="ACCEPT",
                          decision_reason="means-blind", reviewer="rcm-3")
    assert decided_unable["status"] == "ACCEPTED"
    assert decided_able["status"] == "ACCEPTED"
    assert decided_unable["family_ability_to_pay"] == "UNABLE"
    assert decided_able["family_ability_to_pay"] == "ABLE"

    hospital_after = validate_success(api.get_hospital(hospital["id"], admin_headers))
    assert hospital_after["admissions_ytd"] == 2


def test_hospital_capacity_boundary_fifth_acceptance_fails(api, reviewer3_headers,
                                                           admin_headers):
    """PRD §3.3: "An `ACCEPT` additionally requires the hospital's `admissions_ytd` to be strictly below its `annual_capacity` — evaluated on the pre-increment value — otherwise `ERR_HOSPITAL_CAPACITY_REACHED` (HTTP 409)"

    Design: Corner/validations/hospital_capacity_boundary_fifth_acceptance_fails
    """
    set_clock("2026-09-01T00:00:00Z")
    hospital, program, source = setup_hospital_with_program(
        hospital_overrides={"annual_capacity": 1},
    )
    from test_helpers import (
        cast_vote, create_application, decide, get_application, open_review,
    )
    a1 = create_application(source["id"], program["id"], patient_full_name="Kid First")
    open_review(a1["id"])
    cast_vote(a1["id"], vote="ACCEPT", vote_weight=2, reviewer="rcm-1")
    cast_vote(a1["id"], vote="ACCEPT", vote_weight=1, reviewer="rcm-2")
    decide(a1["id"], decision="ACCEPT", decision_reason="fills capacity", reviewer="rcm-3")

    a2 = create_application(source["id"], program["id"], patient_full_name="Kid Second")
    open_review(a2["id"])
    cast_vote(a2["id"], vote="ACCEPT", vote_weight=2, reviewer="rcm-1")
    cast_vote(a2["id"], vote="ACCEPT", vote_weight=1, reviewer="rcm-2")
    current = get_application(a2["id"])
    resp = api.decide_application(
        a2["id"],
        {"decision": "ACCEPT", "decision_reason": "over capacity",
         "expected_application_version": current["version"]},
        reviewer3_headers,
    )
    validate_error(resp, ApiErrorId.ERR_HOSPITAL_CAPACITY_REACHED.value,
                   expected_status=409)
    assert get_application(a2["id"])["status"] == "PENDING_REVIEW"
    hospital_after = validate_success(api.get_hospital(hospital["id"], admin_headers))
    assert hospital_after["admissions_ytd"] == 1


# ---------------------------------------------------------------------------
# Corner/rbac
# ---------------------------------------------------------------------------

def test_review_committee_cannot_submit_applications(api, reviewer1_headers,
                                                     intake_headers):
    """PRD §2.1: "Once headers are validated, the role is checked against the endpoint's authorization list; an authenticated caller whose role is not permitted for the endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/review_committee_cannot_submit_applications
    """
    set_clock("2026-09-01T00:00:00Z")
    _, program, source = setup_hospital_with_program()
    resp = api.create_application(
        create_application_payload(source["id"], program["id"],
                                   patient_full_name="Kid RBAC"),
        reviewer1_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value,
                   expected_status=403)
    applications, _ = validate_paginated(api.list_applications(intake_headers))
    assert applications == []


def test_billing_specialist_cannot_decide_applications(api, billing_headers):
    """PRD §2.1: "Once headers are validated, the role is checked against the endpoint's authorization list; an authenticated caller whose role is not permitted for the endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/billing_specialist_cannot_decide_applications
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, _, application = setup_application_with_accept_quorum(
        patient_full_name="Kid RBAC2",
    )
    from test_helpers import get_application
    current = get_application(application["id"])
    resp = api.decide_application(
        application["id"],
        {"decision": "ACCEPT", "decision_reason": "billing tries",
         "expected_application_version": current["version"]},
        billing_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value,
                   expected_status=403)
    assert get_application(application["id"])["status"] == "PENDING_REVIEW"


def test_missing_auth_headers_rejected_before_any_business_check(api):
    """PRD §2.1: "A request missing either header, or carrying an empty value for either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/rbac/missing_auth_headers_rejected_before_any_business_check
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api._request("GET", "/charity-care/hospitals", headers={
        "Content-Type": "application/json",
    })
    validate_error(
        resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
        expected_status=400,
    )


def test_referring_physician_identity_must_match_referral_source(api):
    """PRD §2.1: "In particular, a `ReferringPhysician` submitting a patient application must supply a `referral_source_id` equal to the caller's own `X-User-ID`."

    Design: Corner/rbac/referring_physician_identity_must_match_referral_source
    """
    set_clock("2026-09-01T00:00:00Z")
    _, program, rs1 = setup_hospital_with_program()
    rs2 = create_referral_source(display_name="Dr. Two", contact_email="two@example.org")
    from test_helpers import make_referring_physician_headers
    physician = make_referring_physician_headers(rs1["id"])

    spoofed = api.create_application(
        create_application_payload(rs2["id"], program["id"],
                                   patient_full_name="Kid Spoof"),
        physician,
    )
    validate_error(spoofed, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value,
                   expected_status=403)

    genuine = api.create_application(
        create_application_payload(rs1["id"], program["id"],
                                   patient_full_name="Kid Genuine"),
        physician,
    )
    application = validate_success(genuine, expected_status=201)
    assert application["status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# Corner/errors
# ---------------------------------------------------------------------------

def test_error_decide_stale_version_is_412_not_409(api, reviewer3_headers,
                                                   admin_headers):
    """PRD §2.7: "If the application's current `version` has advanced since then — because a vote, a resubmission, or another state-changing operation legitimately moved it — the decision is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/errors/error_decide_stale_version_is_412_not_409
    """
    set_clock("2026-09-01T00:00:00Z")
    hospital, _, _, application = setup_application_with_accept_quorum(
        patient_full_name="Kid OCC",
    )
    # Decider carries the creation version (1); the application is now at 4.
    resp = api.decide_application(
        application["id"],
        {"decision": "ACCEPT", "decision_reason": "stale view",
         "expected_application_version": application["version"]},
        reviewer3_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)

    from test_helpers import get_application
    assert get_application(application["id"])["status"] == "PENDING_REVIEW"
    hospital_after = validate_success(api.get_hospital(hospital["id"], admin_headers))
    assert hospital_after["admissions_ytd"] == 0


def test_error_commit_allocation_stale_fund_version(api, philanthropy_headers):
    """PRD §2.7: "The allocation-commit operation likewise requires a non-optional `expected_fund_version` matching the parent `PhilanthropicFund`'s current `version`; a mismatch — for instance because another commit or release has legitimately moved the fund's `allocated_cents` and `available_cents` — is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/errors/error_commit_allocation_stale_fund_version
    """
    set_clock("2026-09-01T00:00:00Z")
    hospital, _, _ = setup_hospital_with_program()
    from test_helpers import create_allocation, create_fund, get_fund
    fund = create_fund(total_committed_cents=100000)
    al1 = create_allocation(fund["id"], hospital["id"], amount_cents=40000)
    al2 = create_allocation(fund["id"], hospital["id"], amount_cents=5000)

    validate_success(api.commit_allocation(al1["id"], fund["version"], philanthropy_headers))

    stale = api.commit_allocation(al2["id"], fund["version"], philanthropy_headers)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)

    committed = validate_success(api.commit_allocation(
        al2["id"], fund["version"] + 1, philanthropy_headers,
    ))
    assert committed["status"] == "COMMITTED"
    fund_after = get_fund(fund["id"])
    assert fund_after["allocated_cents"] == 45000
    assert fund_after["available_cents"] == 55000


def test_error_envelope_shape_on_every_failure(api, care_headers):
    """PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."

    Design: Corner/errors/error_envelope_shape_on_every_failure
    """
    set_clock("2026-09-01T00:00:00Z")
    from test_helpers import create_hospital_payload
    resp = api.create_hospital(create_hospital_payload(), care_headers)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value,
                   expected_status=403)
    body = resp.json()
    assert body["response_type"] == "error"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]
    assert body["meta"]["api_request_id"]
    assert body["meta"]["api_request_timestamp"]


# ---------------------------------------------------------------------------
# Corner/entities (listing) + Corner/endpoints (filtered list)
# ---------------------------------------------------------------------------

def test_applications_list_paginates_and_filters(api, intake_headers):
    """PRD §2.3: "The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and accepts a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0."

    Design: Corner/entities/applications_list_paginates_and_filters
    """
    set_clock("2026-09-01T00:00:00Z")
    _, program, source = setup_hospital_with_program()
    from test_helpers import create_application
    create_application(source["id"], program["id"], patient_full_name="Kid A")
    create_application(source["id"], program["id"], patient_full_name="Kid B",
                       patient_date_of_birth="2019-06-01T00:00:00Z")
    create_application(source["id"], program["id"], patient_full_name="Kid C",
                       patient_date_of_birth="2021-03-01T00:00:00Z")

    page1, meta1 = validate_paginated(
        api.list_applications(intake_headers, params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_applications(intake_headers, params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    submitted, _ = validate_paginated(
        api.list_applications(intake_headers, params={"status": "SUBMITTED"})
    )
    assert len(submitted) == 3
    accepted, _ = validate_paginated(
        api.list_applications(intake_headers, params={"status": "ACCEPTED"})
    )
    assert accepted == []


def test_referral_source_reverse_reachability_filtered_list(api, intake_headers):
    """PRD §4: "| GET | `/charity-care/applications` | List applications (filterable by `program_id`, `referral_source_id`, `screening_id`, `status`, `condition_category`) | NetworkAdmin, IntakeCoordinator, ReviewCommitteeMember, BillingSpecialist, CareCoordinator, OutreachPlanner, PhilanthropyOfficer |"

    Design: Corner/endpoints/referral_source_reverse_reachability_filtered_list
    """
    set_clock("2026-09-01T00:00:00Z")
    _, program, rs1 = setup_hospital_with_program(
        source_overrides={"display_name": "Dr. One", "contact_email": "one@example.org"},
    )
    rs2 = create_referral_source(display_name="Dr. Two", contact_email="two@example.org")
    from test_helpers import create_application
    create_application(rs1["id"], program["id"], patient_full_name="Kid R1a")
    create_application(rs1["id"], program["id"], patient_full_name="Kid R1b",
                       patient_date_of_birth="2020-02-01T00:00:00Z")
    create_application(rs2["id"], program["id"], patient_full_name="Kid R2",
                       patient_date_of_birth="2020-03-01T00:00:00Z")

    rows, _ = validate_paginated(
        api.list_applications(intake_headers, params={"referral_source_id": rs1["id"]})
    )
    assert len(rows) == 2
    assert all(row["referral_source_id"] == rs1["id"] for row in rows)

    rows2, _ = validate_paginated(
        api.list_applications(intake_headers, params={"referral_source_id": rs2["id"]})
    )
    assert len(rows2) == 1


# ---------------------------------------------------------------------------
# Corner/entities (creation round-trips)
# ---------------------------------------------------------------------------

def test_hospital_create_returns_all_declared_fields_and_defaults(api, admin_headers):
    """PRD §3.1: "Every hospital declares an `annual_capacity` — the maximum number of new admissions it will accept in a calendar year, at least 1 — and begins life with `admissions_ytd` at 0 and `status` set to `OPEN`."

    Design: Corner/entities/hospital_create_returns_all_declared_fields_and_defaults
    """
    set_clock("2026-09-01T00:00:00Z")
    from test_helpers import create_hospital_payload
    resp = api.create_hospital(create_hospital_payload(), admin_headers)
    body = resp.json()
    hospital = validate_success(resp, expected_status=201)
    assert body["response_type"] == "object"
    assert hospital["status"] == "OPEN"
    assert hospital["admissions_ytd"] == 0
    assert hospital["version"] == 1
    assert hospital["id"]
    assert hospital["created_at"] == "2026-09-01T00:00:00.000Z"
    assert hospital["updated_at"]


def test_program_get_round_trips_stored_configuration(api, admin_headers, intake_headers):
    """PRD §3.1: "A program's `category` is one of `ORTHOPEDIC`, `BURN`, `CLEFT_CRANIOFACIAL`, `SPINAL_CORD`, or `NEUROMUSCULAR`, and this category later governs which patient conditions the program may admit."

    Design: Corner/entities/program_get_round_trips_stored_configuration
    """
    set_clock("2026-09-01T00:00:00Z")
    from test_helpers import create_hospital, create_program_payload
    hospital = create_hospital()
    created = validate_success(api.create_program(
        hospital["id"],
        create_program_payload(category="SPINAL_CORD", accepts_international=True,
                               min_age_months=12, max_age_months=216,
                               staged_care_required=False),
        admin_headers,
    ), expected_status=201)
    program = validate_success(api.get_program(created["id"], intake_headers))
    assert program["category"] == "SPINAL_CORD"
    assert program["accepts_international"] is True
    assert program["min_age_months"] == 12
    assert program["max_age_months"] == 216
    assert program["staged_care_required"] is False
    assert program["status"] == "ACTIVE"
    assert program["hospital_id"] == hospital["id"]
