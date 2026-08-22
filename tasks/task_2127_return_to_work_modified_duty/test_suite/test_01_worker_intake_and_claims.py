"""Registering injured workers, opening their claims, and the request-screening
ladder that guards every endpoint."""
from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUID,
    assert_employee,
    create_claim_payload,
    create_employee_payload,
    fixtures,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_employee_headers,
    validate_error,
    validate_success,
)


def test_registering_a_worker_returns_the_full_record(api, program_admin_headers):
    """PRD §3.1: "A program administrator opens the file on an injured worker by registering an `Employee` with their `full_name`, the employer-assigned payroll number `employee_number`, the `department_code` they belong to, the average weekly earnings before the injury as `pre_injury_weekly_wage_cents` in whole cents, the contracted `pre_injury_weekly_hours`, and the health-benefit tier `benefit_tier`, which is one of `TIER_A`, `TIER_B` or `TIER_C`."
    PRD §3.1: "A newly registered worker starts with `open_claim_count` at zero"
    PRD §3.1: "The optional `employment_status` may be supplied as `ACTIVE`, `ON_LEAVE` or `SEPARATED` and defaults to `ACTIVE` when omitted."

    Design: Corner/entities/employee_create_returns_201_with_every_declared_field
    """
    fixtures.reset_clock()
    payload = create_employee_payload()
    data = validate_success(api.create_employee(payload, program_admin_headers), 201)

    assert_employee(data)
    assert data["employee_number"] == "EMP-2201"
    assert data["pre_injury_weekly_wage_cents"] == 120_000
    assert data["employment_status"] == "ACTIVE", "employment_status defaults to ACTIVE"
    assert data["open_claim_count"] == 0, "a newly registered worker starts with no open claims"
    assert data["version"] == 1, "version starts at 1"


def test_worker_system_fields_are_server_minted(api, program_admin_headers):
    """PRD §2.4: "Every resource carries a server-minted `id` in UUID form. Identifiers never carry a type prefix, and a client may not supply an `id` on creation."
    PRD §2.4: "Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits, stamped from the logical clock at the moment the row is written."
    PRD §2.4: "`version`, an integer that starts at 1 and increases by exactly 1 on every mutation of that row"

    Design: Corner/entities/employee_system_fields_are_server_minted
    """
    fixtures.reset_clock()
    data = validate_success(
        api.create_employee(create_employee_payload(), program_admin_headers), 201
    )

    assert is_valid_uuid(data["id"]), f"id must be a bare UUID, got {data['id']!r}"
    assert "_" not in data["id"], "identifiers never carry a type prefix"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be ISO 8601 UTC, got {data['created_at']!r}"
    )
    assert data["created_at"].endswith("Z") and "." in data["created_at"], (
        "created_at carries three fractional digits and a UTC marker"
    )
    assert data["version"] == 1, "version starts at 1"


def test_reading_a_worker_returns_the_stored_row(api, program_admin_headers):
    """PRD §3.1: "A program administrator opens the file on an injured worker by registering an `Employee` with their `full_name`, the employer-assigned payroll number `employee_number`, the `department_code` they belong to, the average weekly earnings before the injury as `pre_injury_weekly_wage_cents` in whole cents, the contracted `pre_injury_weekly_hours`, and the health-benefit tier `benefit_tier`, which is one of `TIER_A`, `TIER_B` or `TIER_C`."

    Design: Corner/entities/employee_get_by_id_returns_the_stored_row
    """
    employee = fixtures.create_employee()

    data = validate_success(api.get_employee(employee["id"], program_admin_headers))

    assert_employee(data)
    assert data["id"] == employee["id"]
    assert data["full_name"] == "Dana Ruiz"
    assert data["benefit_tier"] == "TIER_B"


def test_registering_a_worker_without_the_wage_figure_is_refused(api, program_admin_headers):
    """PRD §2.6: "then request-shape validation (priority 3, `ERR_INVALID_REQUEST`). Request-shape validation covers every required field being present"
    PRD §3.1: "the average weekly earnings before the injury as `pre_injury_weekly_wage_cents` in whole cents"

    Design: Corner/entities/employee_create_missing_required_field_returns_invalid_request
    """
    fixtures.reset_clock()
    payload = create_employee_payload()
    payload.pop("pre_injury_weekly_wage_cents")

    resp = api.create_employee(payload, program_admin_headers)

    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_reusing_a_payroll_number_is_refused(api, program_admin_headers):
    """PRD §3.1: "The payroll number must be between 1 and 32 characters long and must not already exist on another worker; the same uniqueness discipline applies to a claim's `claim_number` and a clinician's `npi`, and a collision on any of the three is refused with `ERR_DUPLICATE_IDENTIFIER` and HTTP 409."

    Design: Corner/validations/duplicate_employee_number_is_rejected
    """
    first = fixtures.create_employee()

    resp = api.create_employee(
        create_employee_payload(
            full_name="Other Person",
            employee_number="EMP-2201",
            department_code="OPS",
            pre_injury_weekly_wage_cents=90_000,
            benefit_tier="TIER_C",
        ),
        program_admin_headers,
    )

    validate_error(resp, ApiErrorId.ERR_DUPLICATE_IDENTIFIER, 409)
    survivor = validate_success(api.get_employee(first["id"], program_admin_headers))
    assert survivor["full_name"] == "Dana Ruiz", "the first worker is left untouched"


def test_opening_a_claim_under_an_unknown_worker_is_refused(api, program_admin_headers):
    """PRD §2.6: "Priority 4 resolves every id templated into the URL, validated strictly left to right in path order, so that a request naming a missing parent and a missing child reports the parent's absence; depending on which segment fails, the answer is one of `ERR_EMPLOYEE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_RESTRICTION_SET_NOT_FOUND`, `ERR_SUPERVISOR_NOT_FOUND`, `ERR_TRAINING_RECORD_NOT_FOUND`, `ERR_JOB_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`, `ERR_DIRECTIVE_NOT_FOUND`, `ERR_PROGRESSION_REVIEW_NOT_FOUND`, `ERR_REINJURY_REPORT_NOT_FOUND`, `ERR_CASE_REVIEW_NOT_FOUND` or `ERR_WAGE_ENTRY_NOT_FOUND`, always with HTTP 404."

    Design: Corner/entities/claim_create_under_unknown_employee_returns_employee_not_found
    """
    fixtures.reset_clock()

    resp = api.create_claim(UNKNOWN_UUID, create_claim_payload(), program_admin_headers)

    validate_error(resp, ApiErrorId.ERR_EMPLOYEE_NOT_FOUND, 404)


def test_reading_an_unknown_claim_is_refused(api, program_admin_headers):
    """PRD §2.6: "Priority 4 resolves every id templated into the URL, validated strictly left to right in path order, so that a request naming a missing parent and a missing child reports the parent's absence; depending on which segment fails, the answer is one of `ERR_EMPLOYEE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`"

    Design: Corner/entities/claim_get_with_unknown_uuid_returns_not_found
    """
    fixtures.reset_clock()

    resp = api.get_claim(UNKNOWN_UUID, program_admin_headers)

    error = validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_FOUND, 404)
    assert "claim_number" not in error, "no partial payload accompanies the 404"


def test_a_worker_may_not_read_another_workers_claim(api):
    """PRD §2.1: "When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the acting `Employee`; ownership checks compare it to the `employee_id` of the addressed claim, to the `employee_id` of the claim owning the addressed placement, or to the employee id named in the URL path. Any mismatch on one of these three roles is refused with `ERR_NOT_RESOURCE_OWNER` and HTTP 403."

    Design: Corner/rbac/employee_cannot_read_another_workers_claim
    """
    employee_a = fixtures.create_employee()
    claim = fixtures.open_claim(employee_a["id"])
    fixtures.authorize_claim(claim["id"])
    employee_b = fixtures.create_employee(
        full_name="Rae Lindqvist", employee_number="EMP-2202",
        pre_injury_weekly_wage_cents=118_000, benefit_tier="TIER_C",
    )

    resp = api.get_claim(claim["id"], make_employee_headers(employee_b["id"]))

    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)


def test_a_request_without_a_role_header_is_refused_before_anything_else(api):
    """PRD §2.1: "Every request to the service — including the logical-clock endpoint — must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the capacity in which that principal is acting. If either header is absent, or if `X-User-Role` is not one of the seven role names enumerated below, the request is refused with `ERR_UNAUTHENTICATED` and HTTP 401. This screening happens before anything else, including before the request body is parsed."
    PRD §2.6: "Authentication runs first (priority 1, `ERR_UNAUTHENTICATED`), then endpoint role membership (priority 2, `ERR_UNAUTHORIZED`), then request-shape validation (priority 3, `ERR_INVALID_REQUEST`)."

    Design: Corner/validations/missing_user_role_header_returns_unauthenticated
    """
    fixtures.reset_clock()

    resp = api.get_employee(UNKNOWN_UUID, {"X-User-ID": "someone", "Content-Type": "application/json"})

    error = validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)
    assert error["error_id"] != "ERR_EMPLOYEE_NOT_FOUND", (
        "authentication is screened before the id is resolved"
    )


def test_a_page_size_above_the_maximum_is_refused(api, rtw_coordinator_headers):
    """PRD §2.3: "Every list endpoint accepts two optional pagination parameters. `limit` controls page size: it defaults to 10, may be no smaller than 1, and may be no larger than 100. `offset` controls how many rows are skipped before the page begins: it defaults to 0 and may not be negative. A `limit` outside the inclusive range from 1 to 100, or a negative `offset`, is a malformed request and is refused with `ERR_INVALID_REQUEST` and HTTP 400."

    Design: Corner/validations/pagination_limit_above_maximum_returns_invalid_request
    """
    fixtures.reset_clock()

    resp = api.list_placements(rtw_coordinator_headers, params={"limit": 101, "offset": 0})

    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_every_unknown_path_id_answers_its_own_not_found_code(api, program_admin_headers):
    """PRD §2.6: "Priority 4 resolves every id templated into the URL, validated strictly left to right in path order, so that a request naming a missing parent and a missing child reports the parent's absence; depending on which segment fails, the answer is one of `ERR_EMPLOYEE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_RESTRICTION_SET_NOT_FOUND`, `ERR_SUPERVISOR_NOT_FOUND`, `ERR_TRAINING_RECORD_NOT_FOUND`, `ERR_JOB_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`, `ERR_DIRECTIVE_NOT_FOUND`, `ERR_PROGRESSION_REVIEW_NOT_FOUND`, `ERR_REINJURY_REPORT_NOT_FOUND`, `ERR_CASE_REVIEW_NOT_FOUND` or `ERR_WAGE_ENTRY_NOT_FOUND`, always with HTTP 404."

    Design: Corner/entities/unknown_ids_return_the_entity_specific_not_found_error
    """
    fixtures.reset_clock()
    coord = fixtures.COORD
    nurse = fixtures.NURSE

    validate_error(
        api.get_treating_provider(UNKNOWN_UUID, program_admin_headers),
        ApiErrorId.ERR_PROVIDER_NOT_FOUND, 404,
    )
    validate_error(
        api.get_restriction_set(UNKNOWN_UUID, coord),
        ApiErrorId.ERR_RESTRICTION_SET_NOT_FOUND, 404,
    )
    validate_error(
        api.get_supervisor(UNKNOWN_UUID, program_admin_headers),
        ApiErrorId.ERR_SUPERVISOR_NOT_FOUND, 404,
    )
    validate_error(
        api.get_training_record(UNKNOWN_UUID, program_admin_headers),
        ApiErrorId.ERR_TRAINING_RECORD_NOT_FOUND, 404,
    )
    validate_error(
        api.get_transitional_job(UNKNOWN_UUID, program_admin_headers),
        ApiErrorId.ERR_JOB_NOT_FOUND, 404,
    )
    validate_error(
        api.get_placement(UNKNOWN_UUID, coord),
        ApiErrorId.ERR_PLACEMENT_NOT_FOUND, 404,
    )
    validate_error(
        api.decide_adjuster_directive(
            UNKNOWN_UUID,
            {"decision": "AUTHORIZED", "authorized_weekly_cost_cents": 1000},
            fixtures.ADJUSTER,
        ),
        ApiErrorId.ERR_DIRECTIVE_NOT_FOUND, 404,
    )
    validate_error(
        api.get_progression_review(UNKNOWN_UUID, coord),
        ApiErrorId.ERR_PROGRESSION_REVIEW_NOT_FOUND, 404,
    )
    validate_error(
        api.triage_reinjury_report(UNKNOWN_UUID, {"triage_note": "n/a"}, nurse),
        ApiErrorId.ERR_REINJURY_REPORT_NOT_FOUND, 404,
    )
    validate_error(
        api.get_case_review(UNKNOWN_UUID, nurse),
        ApiErrorId.ERR_CASE_REVIEW_NOT_FOUND, 404,
    )
    validate_error(
        api.get_wage_entry(UNKNOWN_UUID, program_admin_headers),
        ApiErrorId.ERR_WAGE_ENTRY_NOT_FOUND, 404,
    )
