"""Recovery casework: eligibility, recovery planning, referrals and case closure."""
from test_helpers import (
    ApiErrorId,
    create_referral_payload,
    raise_referral,
    resolve_referral,
    set_clock,
    setup_casework_scenario,
    setup_funded_casework_scenario,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
    write_recovery_plan,
)


def test_closed_case_reopens_instead_of_duplicating(api):
    """PRD §3.6: "`CLOSED` is not terminal for a case: a subsequent eligibility verification by
    the assigned caseworker moves it to `REOPENED`."

    PRD §3.6: "A case that has already been `CLOSED` can be reopened by the same operation: it
    moves to `REOPENED` with an `eligibility_status` of `PENDING`, which is the path taken when
    a client who had been settled suffers a second loss and needs a new assistance request."

    Design: Difficulty/non_linear_state_machine/client_case_reopen_cycle
    """
    bundle = setup_casework_scenario()
    case_id = bundle["case_id"]

    case = validate_success(api.get_client_case(case_id, bundle["caseworker_headers"]))
    plan = write_recovery_plan(case_id, case["version"])
    assert plan["recovery_plan_revision"] == 1

    referral = raise_referral(case_id, agency_code="SALVATION_ARMY",
                              assistance_type="HOUSING", estimated_value_cents=12000)
    # PRD §3.6: "`COMPLETE` moves an `ACCEPTED` referral to `COMPLETED`."
    resolve_referral(referral["id"], "ACCEPT")
    resolved = resolve_referral(referral["id"], "COMPLETE")
    assert resolved["status"] == "COMPLETED"

    set_clock("2026-10-05T00:00:00Z")
    closed = validate_success(api.get_client_case(case_id, bundle["caseworker_headers"]))
    assert closed["status"] == "CLOSED"
    assert closed["recovery_plan_revision"] == 1

    reopened = validate_success(api.verify_eligibility(
        case_id, {"eligibility_status": "VERIFIED"}, bundle["caseworker_headers"]))
    assert reopened["status"] == "REOPENED"
    assert reopened["id"] == case_id, "the cycle returns to the same case row"


def test_reopened_case_accepts_a_second_recovery_plan_revision(api):
    """PRD §3.6: "The write moves the case to `RECOVERY_PLANNING`, sets
    `recovery_plan_revision` to 1 if the case was entering recovery planning for the first time
    and increments it by one if the case was already in `RECOVERY_PLANNING` or `REOPENED`."

    PRD §3.6: "from there a new recovery plan revision returns it to `RECOVERY_PLANNING` once
    eligibility is `VERIFIED`."

    Design: Difficulty/non_linear_state_machine/client_case_reopen_cycle
    """
    bundle = setup_casework_scenario()
    case_id = bundle["case_id"]

    case = validate_success(api.get_client_case(case_id, bundle["caseworker_headers"]))
    write_recovery_plan(case_id, case["version"])

    referral = raise_referral(case_id, agency_code="SALVATION_ARMY",
                              assistance_type="HOUSING", estimated_value_cents=12000)
    # PRD §3.6: "`COMPLETE` moves an `ACCEPTED` referral to `COMPLETED`."
    resolve_referral(referral["id"], "ACCEPT")
    resolve_referral(referral["id"], "COMPLETE")
    set_clock("2026-10-05T00:00:00Z")

    validate_success(api.get_client_case(case_id, bundle["caseworker_headers"]))
    reopened = validate_success(api.verify_eligibility(
        case_id, {"eligibility_status": "VERIFIED"}, bundle["caseworker_headers"]))
    assert reopened["status"] == "REOPENED"

    settled = validate_success(api.verify_eligibility(
        case_id, {"eligibility_status": "VERIFIED"}, bundle["caseworker_headers"]))
    assert settled["eligibility_status"] == "VERIFIED"

    revised = validate_success(api.write_recovery_plan(
        case_id,
        {"expected_client_case_version": settled["version"],
         "recovery_plan_summary": "Second disaster wave recovery plan"},
        bundle["caseworker_headers"]), 201)
    assert revised["status"] == "RECOVERY_PLANNING"
    assert revised["recovery_plan_revision"] == 2


def test_referral_information_request_reopens_the_same_referral(api):
    """PRD §3.6: "`REQUEST_INFORMATION` sends an `ACCEPTED` referral back to `SUBMITTED` and
    puts it through the duplication check again the next time it is resolved."

    Design: Difficulty/non_linear_state_machine/referral_information_request_cycle
    """
    bundle = setup_casework_scenario()
    referral = raise_referral(bundle["case_id"], agency_code="SALVATION_ARMY",
                              assistance_type="HOUSING", estimated_value_cents=12000)

    accepted = resolve_referral(referral["id"], "ACCEPT")
    assert accepted["status"] == "ACCEPTED"

    returned = resolve_referral(referral["id"], "REQUEST_INFORMATION")
    assert returned["status"] == "SUBMITTED", "the cycle closes back onto SUBMITTED"

    reaccepted = resolve_referral(referral["id"], "ACCEPT")
    assert reaccepted["status"] == "ACCEPTED"


def test_referral_cycle_never_creates_a_second_row(api):
    """PRD §3.6: "When the raise succeeds, the referral is created in `SUBMITTED` status,
    attached to the case through its `client_case_id`, with a `duplication_check_result` of
    `CLEAR` or `PARTIAL_OVERLAP`, and the case moves to `REFERRED`."

    Design: Difficulty/non_linear_state_machine/referral_information_request_cycle
    """
    bundle = setup_casework_scenario()
    referral = raise_referral(bundle["case_id"], agency_code="SALVATION_ARMY",
                              assistance_type="HOUSING", estimated_value_cents=12000)

    resolve_referral(referral["id"], "ACCEPT")
    resolve_referral(referral["id"], "REQUEST_INFORMATION")
    resolve_referral(referral["id"], "ACCEPT")

    data, _meta = validate_paginated(
        api.list_case_referrals(bundle["case_id"], bundle["caseworker_headers"]))
    assert len(data) == 1
    assert data[0]["id"] == referral["id"]
    assert data[0]["status"] == "ACCEPTED"


def test_first_approval_is_refused_while_the_case_is_unverified(api):
    """PRD §3.7: "the case must be eligible before it can begin. The first call requires the
    case's `eligibility_status` to be `VERIFIED` and moves the request from `SUBMITTED` to
    `ELIGIBILITY_VERIFIED`."

    Design: Difficulty/cross_entity_state_dependency/assistance_first_approval_requires_verified_case
    """
    bundle = setup_funded_casework_scenario(eligibility_status=None)

    case = validate_success(api.get_client_case(bundle["case_id"], bundle["caseworker_headers"]))
    assert case["eligibility_status"] == "PENDING"

    resp = api.approve_assistance_request(bundle["request_id"], bundle["finance_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_first_approval_succeeds_once_eligibility_is_verified(api):
    """PRD §3.7: "The first call requires the case's `eligibility_status` to be `VERIFIED` and
    moves the request from `SUBMITTED` to `ELIGIBILITY_VERIFIED`, computing
    `duplication_offset_cents` and `approved_amount_cents`."

    Design: Difficulty/cross_entity_state_dependency/assistance_first_approval_requires_verified_case
    """
    bundle = setup_funded_casework_scenario(
        requested_amount_cents=20000, assistance_type="TRANSPORTATION",
        eligibility_status=None)
    caseworker = bundle["caseworker_headers"]
    finance = bundle["finance_headers"]

    validate_error(
        api.approve_assistance_request(bundle["request_id"], finance),
        ApiErrorId.ERR_INVALID_STATE)

    validate_success(api.verify_eligibility(
        bundle["case_id"], {"eligibility_status": "VERIFIED"}, caseworker))

    verified = validate_success(
        api.approve_assistance_request(bundle["request_id"], finance))
    assert verified["status"] == "ELIGIBILITY_VERIFIED"
    assert verified["approved_amount_cents"] == 20000


def test_referral_to_an_unauthorized_agency_is_refused(api):
    """PRD §3.6: "The `agency_code` must appear in the `authorized_agency_codes` of the region
    the client resides in; an unauthorized agency is refused with `ERR_AGENCY_NOT_AUTHORIZED` at
    HTTP status 409."

    Design: Corner/validations/referral_agency_not_authorized_for_client_region
    """
    bundle = setup_casework_scenario(
        region_overrides={"authorized_agency_codes": ["SALVATION_ARMY"]})
    caseworker = bundle["caseworker_headers"]

    resp = api.create_referral(
        bundle["case_id"],
        create_referral_payload(agency_code="FEMA", assistance_type="HOUSING",
                                estimated_value_cents=8000),
        caseworker)
    validate_error(resp, ApiErrorId.ERR_AGENCY_NOT_AUTHORIZED)

    accepted = validate_success(api.create_referral(
        bundle["case_id"],
        create_referral_payload(agency_code="SALVATION_ARMY", assistance_type="HOUSING",
                                estimated_value_cents=8000),
        caseworker), 201)
    assert accepted["status"] == "SUBMITTED"


def test_duplicate_referral_for_the_same_agency_and_type_is_blocked(api):
    """PRD §3.6: "a case may not hold two live referrals to the same agency for the same kind of
    help: if a non-cancelled referral with the same `agency_code` and `assistance_type` already
    exists for the case, the raise is refused with `ERR_DUPLICATION_BLOCKED` at HTTP status 409."

    Design: Corner/validations/duplicate_referral_same_agency_and_type_blocked
    """
    bundle = setup_casework_scenario(
        region_overrides={"authorized_agency_codes": ["SALVATION_ARMY", "LOCAL_HOUSING"]})
    caseworker = bundle["caseworker_headers"]

    raise_referral(bundle["case_id"], agency_code="SALVATION_ARMY",
                   assistance_type="HOUSING", estimated_value_cents=8000)

    resp = api.create_referral(
        bundle["case_id"],
        create_referral_payload(agency_code="SALVATION_ARMY", assistance_type="HOUSING",
                                estimated_value_cents=6000),
        caseworker)
    validate_error(resp, ApiErrorId.ERR_DUPLICATION_BLOCKED)

    other_type = validate_success(api.create_referral(
        bundle["case_id"],
        create_referral_payload(agency_code="SALVATION_ARMY", assistance_type="FOOD",
                                estimated_value_cents=6000),
        caseworker), 201)
    assert other_type["status"] == "SUBMITTED"


def test_completed_referral_rejects_a_late_resolution(api):
    """PRD §3.6: "The referral's status vocabulary is `SUBMITTED`, `ACCEPTED`, `DECLINED`,
    `COMPLETED` or `CANCELLED`, of which `COMPLETED` and `CANCELLED` are terminal."

    PRD §2.4: "`CLOSED` is terminal and rejects every further transition with
    `ERR_ALREADY_TERMINAL` at HTTP status 409."

    Design: Corner/state_machines/referral_resolve_from_completed_rejected
    """
    bundle = setup_casework_scenario()
    referral = raise_referral(bundle["case_id"], agency_code="SALVATION_ARMY",
                              assistance_type="HOUSING", estimated_value_cents=9000)

    resolve_referral(referral["id"], "ACCEPT")
    completed = resolve_referral(referral["id"], "COMPLETE")
    assert completed["status"] == "COMPLETED"

    resp = api.resolve_referral(referral["id"], "DECLINE", bundle["caseworker_headers"])
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_ALREADY_TERMINAL, ApiErrorId.ERR_INVALID_STATE])

    rows, _meta = validate_paginated(
        api.list_case_referrals(bundle["case_id"], bundle["caseworker_headers"]))
    still = [row for row in rows if row["id"] == referral["id"]]
    assert len(still) == 1
    assert still[0]["status"] == "COMPLETED", "a terminal referral stays terminal"


def test_case_read_exposes_the_written_recovery_plan(api):
    """PRD §4: "Read a client case with eligibility, recovery plan revision and entitlement"

    PRD §3.6: "The write moves the case to `RECOVERY_PLANNING`, sets
    `recovery_plan_revision` to 1 if the case was entering recovery planning for the first time."

    Design: Corner/endpoints/client_case_retrieval_exposes_recovery_plan_revision
    """
    bundle = setup_casework_scenario()
    case = validate_success(api.get_client_case(bundle["case_id"], bundle["caseworker_headers"]))

    written = write_recovery_plan(
        bundle["case_id"], case["version"], recovery_plan_summary="Initial recovery plan")
    assert written["recovery_plan_revision"] == 1

    read = validate_success(api.get_client_case(bundle["case_id"], bundle["caseworker_headers"]))
    assert read["recovery_plan_revision"] == 1
    assert read["recovery_plan_summary"] == "Initial recovery plan"
    assert read["status"] == "RECOVERY_PLANNING"
