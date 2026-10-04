"""Case intake corners: initial state, the triage edge, request-shape and
existence failures on create, pagination of the docket, and the error
envelope shape."""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_reemployment_case,
    case_payload,
    create_case,
    create_employer,
    create_member,
    make_service_member_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_MEMBER_ID = "00000000-0000-4000-8000-000000000001"
UNKNOWN_EMPLOYER_ID = "00000000-0000-4000-8000-000000000002"


def test_case_created_in_intake_initial_state(api: ApiClient):
    """PRD §3.1: "A new case enters in `INTAKE` status."
    PRD §2.5: "`version` (integer): a system-managed counter that increments by exactly 1 on every mutation of the resource, and that anchors the optimistic concurrency rules of §2.6."

    Design: Corner/state_machines/case_created_in_intake_initial_state
    """
    set_clock(api)
    employer = create_employer(api)
    member = create_member(api)
    case = create_case(api, member["id"], employer["id"],
                       description="Refused reinstatement", application_submitted_at="2026-04-20T00:00:00Z")
    assert_reemployment_case(case)
    assert case["status"] == "INTAKE"
    assert case["open_round_count"] == 0
    assert case["documentation_complete"] is False
    assert case["version"] == 1
    assert case["escalated_at"] is None
    assert case["closed_at"] is None
    assert case["assigned_ombudsman_id"] is None


def test_case_triage_valid_transition(api: ApiClient, coordinator_headers: dict):
    """PRD §3.1: "A `ProgramCoordinator` then moves it `INTAKE → TRIAGE` for screening."
    PRD §2.5: "`version` (integer): a system-managed counter that increments by exactly 1 on every mutation of the resource, and that anchors the optimistic concurrency rules of §2.6."

    Design: Corner/state_machines/case_triage_valid_transition
    """
    set_clock(api)
    employer = create_employer(api)
    member = create_member(api)
    case = create_case(api, member["id"], employer["id"])
    assert case["version"] == 1

    response = api.transition_case(case["id"], {"to_status": "TRIAGE"}, coordinator_headers)
    triaged = validate_success(response)
    assert triaged["status"] == "TRIAGE"
    assert triaged["version"] == 2, f"the triage mutation increments version 1 -> 2, got {triaged['version']}"
    assert_reemployment_case(triaged)


def test_case_create_missing_employer_id_returns_invalid_request(api: ApiClient, coordinator_headers: dict):
    """PRD §2.7: "Third, request shape: required fields present, enum members valid, the system-reserved `AUDIT` note category refused on input, and intervals whose end is not strictly after their start, all failing with `ERR_INVALID_REQUEST`."
    PRD §2.7: "Shape checks deliberately precede existence checks, because a field that is absent cannot be resolved to any entity at all."

    Design: Corner/entities/case_create_missing_employer_id_returns_invalid_request
    """
    set_clock(api)
    member = create_member(api)
    payload = case_payload(member["id"], "unused-employer", description="Missing employer")
    del payload["employer_id"]
    response = api.create_case(payload, make_service_member_headers(member["id"]))
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    listing, meta = validate_paginated(api.list_cases(coordinator_headers, params={"member_id": member["id"]}))
    assert listing == [] and meta["total_count"] == 0, "nothing may be persisted by a shape-rejected filing"


def test_case_create_with_unknown_enum_issue_type_returns_invalid_request(api: ApiClient, coordinator_headers: dict):
    """PRD §3.1: "a primary `issue_type` of `REEMPLOYMENT`, `BENEFITS`, `PENSION`, `DISCRIMINATION`, or `RETALIATION`"
    PRD §2.7: "Third, request shape: required fields present, enum members valid, the system-reserved `AUDIT` note category refused on input, and intervals whose end is not strictly after their start, all failing with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/case_create_with_unknown_enum_issue_type_returns_invalid_request
    """
    set_clock(api)
    employer = create_employer(api)
    member = create_member(api)
    response = api.create_case(
        case_payload(member["id"], employer["id"], issue_type="HARASSMENT", description="Bad enum"),
        make_service_member_headers(member["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    listing, meta = validate_paginated(api.list_cases(coordinator_headers, params={"member_id": member["id"]}))
    assert listing == [] and meta["total_count"] == 0, "nothing may be persisted by an enum-rejected filing"


def test_case_create_status_and_version_input_ignored(api: ApiClient):
    """PRD §3.1: "A new case enters in `INTAKE` status."
    PRD §2.6: "No other endpoint takes a version field of any kind; requests to any other operation must not include one."
    PRD §2.5: "`version` (integer): a system-managed counter that increments by exactly 1 on every mutation of the resource, and that anchors the optimistic concurrency rules of §2.6."

    Design: Corner/entities/case_create_status_and_version_input_ignored
    """
    set_clock(api)
    employer = create_employer(api)
    member = create_member(api)
    forged = case_payload(member["id"], employer["id"], description="Forged status attempt")
    forged["status"] = "RESOLVED_INFORMAL"
    forged["version"] = 99
    response = api.create_case(forged, make_service_member_headers(member["id"]))
    case = validate_success(response, 201)
    assert_reemployment_case(case)
    assert case["status"] == "INTAKE", "client-supplied status is not an input field and must not be honored"
    assert case["version"] == 1, "client-supplied version is not an input field and must not be honored"
    assert case["assigned_ombudsman_id"] is None
    assert case["open_round_count"] == 0


def test_case_create_body_foreign_keys_checked_in_input_order(api: ApiClient, coordinator_headers: dict):
    """PRD §2.7: "Fourth, existence: path identifiers are validated left to right, and body foreign keys are validated in the endpoint's declared input order — `member_id` before `employer_id`, and so on — each miss producing the corresponding 404 error."
    PRD §2.10: "body foreign keys on creation payloads resolve in the endpoint's declared input order, so a case filed with both an unknown member and an unknown employer reports `ERR_MEMBER_NOT_FOUND` first."

    Design: Corner/entities/case_create_body_foreign_keys_checked_in_input_order
    """
    set_clock(api)
    member = create_member(api)

    both_unknown = api.create_case(
        case_payload(UNKNOWN_MEMBER_ID, UNKNOWN_EMPLOYER_ID, description="Both FKs unknown"),
        make_service_member_headers(member["id"]),
    )
    error_data = validate_error(both_unknown, ApiErrorId.ERR_MEMBER_NOT_FOUND)
    assert error_data["error_id"] != "ERR_EMPLOYER_NOT_FOUND", "member_id is validated before employer_id"

    employer_unknown = api.create_case(
        case_payload(member["id"], UNKNOWN_EMPLOYER_ID, description="Employer unknown"),
        make_service_member_headers(member["id"]),
    )
    validate_error(employer_unknown, ApiErrorId.ERR_EMPLOYER_NOT_FOUND)

    listing, meta = validate_paginated(api.list_cases(coordinator_headers))
    assert listing == [] and meta["total_count"] == 0


def test_cases_list_paginates_with_total_count_and_has_more(api: ApiClient, coordinator_headers: dict):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0."
    PRD §2.3: "Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."
    PRD §3.1: "Coordinators and ombudsmen browse the docket through a paginated case listing that can be narrowed by `member_id`, `employer_id`, `assigned_ombudsman_id`, `status`, the employer's `sector`, or `issue_type`."

    Design: Corner/entities/cases_list_paginates_with_total_count_and_has_more
    """
    set_clock(api)
    employer = create_employer(api)
    member = create_member(api)
    for issue_type, description in (("REEMPLOYMENT", "Case A"), ("BENEFITS", "Case B"), ("PENSION", "Case C")):
        create_case(api, member["id"], employer["id"], issue_type=issue_type, description=description)

    page_one, meta_one = validate_paginated(
        api.list_cases(coordinator_headers, params={"member_id": member["id"], "limit": 2, "offset": 0})
    )
    assert len(page_one) == 2
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert meta_one["limit"] == 2 and meta_one["offset"] == 0

    page_two, meta_two = validate_paginated(
        api.list_cases(coordinator_headers, params={"member_id": member["id"], "limit": 2, "offset": 2})
    )
    assert len(page_two) == 1
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False

    everything, meta_all = validate_paginated(api.list_cases(coordinator_headers))
    assert len(everything) == 3 and meta_all["total_count"] == 3
    assert meta_all["limit"] == 10 and meta_all["offset"] == 0

    pension_only, meta_pension = validate_paginated(
        api.list_cases(coordinator_headers, params={"issue_type": "PENSION"})
    )
    assert len(pension_only) == 1 and pension_only[0]["description"] == "Case C"
    assert meta_pension["total_count"] == 1


def test_case_get_unknown_id_returns_case_not_found(api: ApiClient, coordinator_headers: dict):
    """PRD §2.10: "Each resource family has its own miss error — `ERR_MEMBER_NOT_FOUND`, `ERR_EMPLOYER_NOT_FOUND`, `ERR_OMBUDSMAN_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_ROUND_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND`, and `ERR_AWARD_NOT_FOUND` — so the response always names the kind of thing that could not be found."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."

    Design: Corner/entities/case_get_unknown_id_returns_case_not_found
    """
    set_clock(api)
    response = api.get_case(NON_EXISTENT_UUID, coordinator_headers)
    error_data = validate_error(response, ApiErrorId.ERR_CASE_NOT_FOUND)
    assert response.status_code == 404
    assert error_data["message"].strip(), "the error carries a human-readable message"


def test_immediate_visibility_after_create_and_error_envelope_shape(api: ApiClient, coordinator_headers: dict):
    """PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."
    PRD §2.5: "`created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created."

    Design: Corner/consistency_model/immediate_visibility_after_create_and_error_envelope_shape
    """
    set_clock(api)
    employer = create_employer(api)
    member = create_member(api)
    case = create_case(api, member["id"], employer["id"])

    reread = validate_success(api.get_case(case["id"], make_service_member_headers(member["id"])))
    assert reread["status"] == "INTAKE", "an immediate re-read agrees with the create response"
    assert reread == case, "the re-read carries exactly the created representation with no delay or staleness"

    missing = api.get_case(NON_EXISTENT_UUID, coordinator_headers)
    body = missing.json()
    assert body["response_type"] == "error"
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}
    error_data = validate_error(missing, ApiErrorId.ERR_CASE_NOT_FOUND)
    assert error_data["error_id"] == "ERR_CASE_NOT_FOUND"
    assert error_data["message"].strip()
