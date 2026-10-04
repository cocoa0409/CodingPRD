"""Authentication, authorization, not-found resolution and RBAC boundaries."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, set_clock,
    create_client, create_funder, create_program, create_grant, open_assessment,
    walk_screen_to_eligible, activate_enrollment, authorize_units, setup_landscape,
    setup_active_enrollment, build_user_headers, UNDECLARED_ROLE, NON_EXISTENT_UUID,
    ApiErrorId, INTAKE, PROGRAM, FINANCE, COMPLIANCE, ADMIN, TEST_USERS,
)

UNKNOWN_GRANT_UUID = "11111111-1111-4111-8111-111111111111"


def test_missing_or_undeclared_role_header_returns_unauthenticated():
    """PRD §2.1: "If either header is absent, or if `X-User-Role` carries a
    value that is not one of the declared roles, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401) before any other consideration."
    PRD §2.10: "Priority 1 is authentication. The request must carry both
    `X-User-ID` and `X-User-Role`, and the role must be one of the six declared
    roles."

    Design: Corner/validations/missing_or_undeclared_role_header_returns_unauthenticated
    """
    set_clock("2026-09-01T00:00:00Z")
    missing = api_client.list_grants({})
    validate_error(missing, ApiErrorId.ERR_UNAUTHENTICATED)

    undeclared = api_client.list_grants(build_user_headers("test-auditor-1", UNDECLARED_ROLE))
    validate_error(undeclared, ApiErrorId.ERR_UNAUTHENTICATED)


def test_exclusive_operations_reject_other_roles_with_forbidden_role():
    """PRD §2.1: "If the headers are well formed but the acting role is not
    among the roles an endpoint authorizes, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.10: "Priority 2 is authorization. The acting role must appear in the
    endpoint's own roles set."

    Design: Corner/validations/exclusive_operations_reject_other_roles_with_forbidden_role
    """
    set_clock("2026-09-01T00:00:00Z")
    first = api_client.create_program(
        {"name": "Housing First", "service_domain": "HOUSING",
         "faith_based_activity_offered": False, "nondiscrimination_attested": True,
         "capacity_slots": 3, "match_eligible": True},
        PROGRAM,
    )
    validate_error(first, ApiErrorId.ERR_FORBIDDEN_ROLE)

    second = api_client.determine_eligibility_screen(
        NON_EXISTENT_UUID, {"determination": "ELIGIBLE"}, INTAKE
    )
    validate_error(second, ApiErrorId.ERR_FORBIDDEN_ROLE)

    third = api_client.bill_service_delivery(NON_EXISTENT_UUID, PROGRAM)
    validate_error(third, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_faith_based_activity_flag_blocks_public_funds_on_grant_creation():
    """PRD §2.8: "When the governing funder has `allow_faith_based_activity` set
    to false, the funded program's `faith_based_activity_offered` must be false
    before public funds may be drawn. A request that would attach such a
    funder's money to such a program is rejected with
    `ERR_FAITH_BASED_ACTIVITY_PROHIBITED` (HTTP 422)."

    Design: Corner/validations/faith_based_activity_flag_blocks_public_funds_on_grant_creation
    """
    set_clock("2026-09-01T00:00:00Z")
    funder = create_funder(name="County Human Services", funder_type="COUNTY",
                           allow_faith_based_activity=False,
                           requires_time_and_effort_documentation=True,
                           max_admin_rate_pct=0.10, fiscal_year_start_month=7)
    program = create_program(name="Parish Pantry", service_domain="FOOD",
                             faith_based_activity_offered=True, match_eligible=False)

    resp = api_client.create_grant(
        {"funder_id": funder["id"], "program_id": program["id"], "grant_code": "G-BAD",
         "total_award_cents": 100000, "admin_rate_pct": 0.10, "allocation_rank": 1,
         "max_in_kind_rate_cents": 3000, "matching_requirement_pct": 0.0,
         "cost_allocation_basis": "DIRECT_ONLY", "restricted_purpose": "FOOD_DISTRIBUTION",
         "period_start": "2026-09-01T00:00:00Z", "period_end": "2027-08-31T23:59:59Z"},
        FINANCE,
    )
    validate_error(resp, ApiErrorId.ERR_FAITH_BASED_ACTIVITY_PROHIBITED)

    listed = get_success_data(api_client.list_grants(FINANCE, {"funder_id": funder["id"]}))
    assert listed == [], "the refused award was never created"


def test_admin_rate_above_funder_ceiling_rejected_on_grant_creation():
    """PRD §3.1: "That administrative rate is checked against the governing
    funder's ceiling: if it exceeds the funder's `max_admin_rate_pct`, the award
    is refused with `ERR_ADMIN_RATE_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/admin_rate_above_funder_ceiling_rejected_on_grant_creation
    """
    set_clock("2026-09-01T00:00:00Z")
    funder = create_funder(name="County Human Services", funder_type="COUNTY",
                           allow_faith_based_activity=False,
                           requires_time_and_effort_documentation=True,
                           max_admin_rate_pct=0.10, fiscal_year_start_month=7)
    program = create_program(name="Housing First")
    base = {"funder_id": funder["id"], "program_id": program["id"],
            "total_award_cents": 200000, "allocation_rank": 1,
            "max_in_kind_rate_cents": 3000, "matching_requirement_pct": 0.0,
            "cost_allocation_basis": "DIRECT_ONLY",
            "restricted_purpose": "HOUSING_ASSISTANCE",
            "period_start": "2026-09-01T00:00:00Z",
            "period_end": "2027-08-31T23:59:59Z"}

    over = api_client.create_grant(dict(base, grant_code="G-OVER", admin_rate_pct=0.15),
                                   FINANCE)
    validate_error(over, ApiErrorId.ERR_ADMIN_RATE_EXCEEDED)

    at_ceiling = api_client.create_grant(dict(base, grant_code="G-AT", admin_rate_pct=0.10),
                                         FINANCE)
    data = validate_success(at_ceiling, expected_status=201)
    assert data["admin_rate_pct"] == 0.10, "exactly at the ceiling is allowed"


def test_unresolvable_path_segments_return_the_specific_not_found_error():
    """PRD §2.10: "`ERR_ENROLLMENT_NOT_FOUND` (HTTP 404) when the enrollment
    named in a path or body does not exist, guarding enrollment activation,
    enrollment exit and unit authorization; `ERR_AUTHORIZATION_NOT_FOUND`
    (HTTP 404) when the `service_authorization_id` in a body does not resolve,
    guarding delivery recording; `ERR_DELIVERY_NOT_FOUND` (HTTP 404) when a
    delivery path segment does not resolve, guarding documentation, billing and
    voiding; and `ERR_OUTCOME_REPORT_NOT_FOUND` (HTTP 404) when an outcome report
    path segment does not resolve, guarding submission, acceptance and
    rejection."

    Design: Corner/errors/unresolvable_path_segments_return_the_specific_not_found_error
    """
    set_clock("2026-09-01T00:00:00Z")
    first = api_client.activate_enrollment(NON_EXISTENT_UUID, PROGRAM)
    validate_error(first, ApiErrorId.ERR_ENROLLMENT_NOT_FOUND)

    second = api_client.document_service_delivery(NON_EXISTENT_UUID, PROGRAM)
    validate_error(second, ApiErrorId.ERR_DELIVERY_NOT_FOUND)

    third = api_client.submit_outcome_report(NON_EXISTENT_UUID, PROGRAM)
    validate_error(third, ApiErrorId.ERR_OUTCOME_REPORT_NOT_FOUND)


def test_unresolvable_body_references_return_the_specific_not_found_error():
    """PRD §2.11: "A body that names a `program_id`, a `grant_id`, an
    `enrollment_id` or a `service_authorization_id` must resolve to a live row of
    the corresponding collection before any later-tier check runs, and an
    unresolvable one is reported with that collection's not-found code."

    Design: Corner/errors/unresolvable_body_references_return_the_specific_not_found_error
    """
    set_clock("2026-09-01T00:00:00Z")
    funder = create_funder()
    program = create_program()
    client = create_client()
    assessment = open_assessment(client["id"])

    screen = api_client.create_eligibility_screen(
        assessment["id"],
        {"program_id": NON_EXISTENT_UUID, "grant_id": UNKNOWN_GRANT_UUID,
         "verified_income_cents": 120000, "household_size_at_screen": 2},
        INTAKE,
    )
    validate_error(screen, ApiErrorId.ERR_PROGRAM_NOT_FOUND)

    enrollment = api_client.create_enrollment(
        {"client_id": client["id"], "program_id": program["id"],
         "grant_id": UNKNOWN_GRANT_UUID},
        PROGRAM,
    )
    validate_error(enrollment, ApiErrorId.ERR_GRANT_NOT_FOUND)


def test_unresolvable_authorization_reference_returns_authorization_not_found():
    """PRD §2.10: "`ERR_AUTHORIZATION_NOT_FOUND` (HTTP 404) when the
    `service_authorization_id` in a body does not resolve, guarding delivery
    recording".
    PRD §2.11: "an unresolvable one is reported with that collection's
    not-found code."

    Design: Corner/errors/unresolvable_authorization_reference_returns_authorization_not_found
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_active_enrollment(authorize=True)

    resp = api_client.create_service_delivery(
        {"service_authorization_id": NON_EXISTENT_UUID, "grant_id": ctx["grant"]["id"],
         "client_id": ctx["client"]["id"], "service_date": "2026-09-02T00:00:00Z",
         "units_delivered": 1, "unit_rate_cents": 5000,
         "expected_service_authorization_version": ctx["authorization"]["version"]},
        PROGRAM,
    )
    validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_NOT_FOUND)


def test_exclusive_write_operations_are_refused_for_unlisted_roles():
    """PRD §4: "Every endpoint is mounted under the `/api` prefix, and every
    request must carry the `X-User-ID` and `X-User-Role` headers described in
    §2.1."
    PRD §2.1: "the acting role is not among the roles an endpoint authorizes, the
    request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/exclusive_write_operations_are_refused_for_unlisted_roles
    """
    set_clock("2026-09-01T00:00:00Z")
    first = api_client.create_funder(
        {"name": "Diocesan Fund", "funder_type": "DIOCESAN",
         "allow_faith_based_activity": True,
         "requires_time_and_effort_documentation": False,
         "max_admin_rate_pct": 0.25, "fiscal_year_start_month": 1},
        FINANCE,
    )
    validate_error(first, ApiErrorId.ERR_FORBIDDEN_ROLE)

    second = api_client.exit_enrollment(NON_EXISTENT_UUID, {"exit_reason": "WITHDRAWN"},
                                        INTAKE)
    validate_error(second, ApiErrorId.ERR_FORBIDDEN_ROLE)

    third = api_client.recompute_grant_posture(NON_EXISTENT_UUID, PROGRAM)
    validate_error(third, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_read_operations_respect_the_role_allowlist():
    """PRD §2.1: "If the headers are well formed but the acting role is not
    among the roles an endpoint authorizes, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/read_operations_respect_the_role_allowlist
    """
    set_clock("2026-09-01T00:00:00Z")
    client = create_client()
    first = api_client.list_cost_allocations(INTAKE)
    validate_error(first, ApiErrorId.ERR_FORBIDDEN_ROLE)

    second = api_client.get_client(client["id"], PROGRAM)
    validate_error(second, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_operator_endpoints_are_refused_for_business_and_client_roles():
    """PRD §2.5: "An operator holding the `PlatformAdmin` role has one exclusive
    capability: setting the logical clock to a supplied instant, passed as
    `to_iso8601`."
    PRD §2.1: "A `Client` is the person receiving services, acting through a
    self-service portal on their own record only."

    Design: Corner/rbac/operator_endpoints_are_refused_for_business_and_client_roles
    """
    set_clock("2026-09-01T00:00:00Z")
    first = api_client.set_current_utc({"to_iso8601": "2026-10-01T00:00:00Z"}, COMPLIANCE)
    validate_error(first, ApiErrorId.ERR_FORBIDDEN_ROLE)

    second = api_client.create_client(
        {"full_name": "Ada Vance", "date_of_birth": "1990-01-01", "household_size": 2,
         "immigration_status": "CITIZEN", "county_code": "COOK"},
        TEST_USERS["client_headers"],
    )
    validate_error(second, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_in_kind_donation_creation_is_shared_by_program_and_finance_roles():
    """PRD §4: "| POST | `/api/in-kind-donations` | Record a parish or volunteer
    contribution and compute its match credit | ProgramManager, FinanceOfficer |"
    PRD §2.1: "A `ProgramManager` is program staff who enroll clients, authorize
    service units, document deliveries and file outcome reports. A
    `FinanceOfficer` is fiscal staff who create awards, bill funders, reverse
    misbillings and value in-kind contributions."

    Design: Corner/rbac/in_kind_donation_creation_is_shared_by_program_and_finance_roles
    """
    set_clock("2026-09-02T00:00:00Z")
    ctx = setup_landscape(grants=[{"matching_requirement_pct": 0.25}])
    grant_id = ctx["grant"]["id"]

    as_program = api_client.create_in_kind_donation(
        {"grant_id": grant_id, "donor_type": "VOLUNTEER", "donor_reference": "VOL-1",
         "donation_date": "2026-09-02T00:00:00Z", "hours": 2,
         "valuation_method": "APPRAISAL", "rate_cents": 3000},
        PROGRAM,
    )
    first = validate_success(as_program, expected_status=201)

    as_finance = api_client.create_in_kind_donation(
        {"grant_id": grant_id, "donor_type": "PARISH", "donor_reference": "PARISH-01",
         "donation_date": "2026-09-02T00:00:00Z", "hours": 2,
         "valuation_method": "APPRAISAL", "rate_cents": 3000},
        FINANCE,
    )
    second = validate_success(as_finance, expected_status=201)

    assert first["value_cents"] == 6000
    assert second["value_cents"] == 6000

    as_intake = api_client.create_in_kind_donation(
        {"grant_id": grant_id, "donor_type": "CORPORATE", "donor_reference": "CORP-9",
         "donation_date": "2026-09-02T00:00:00Z", "hours": 2,
         "valuation_method": "APPRAISAL", "rate_cents": 3000},
        INTAKE,
    )
    validate_error(as_intake, ApiErrorId.ERR_FORBIDDEN_ROLE)
