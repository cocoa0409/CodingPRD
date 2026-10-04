"""Authentication, role authorization, undeclared fields and catalogue errors."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    create_pool,
    create_region,
    set_clock,
    setup_funded_casework_scenario,
    setup_open_shelter,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_request_without_auth_headers_is_refused_before_existence(api):
    """PRD §2.1: "When either header is absent or empty, the request is refused with
    `ERR_MISSING_AUTH_HEADER` and HTTP status 401."

    Design: Corner/errors/unauthenticated_request_returns_missing_auth_header
    """
    set_clock("2026-09-01T00:00:00Z")

    resp = api.get_region(NON_EXISTENT_UUID, {})
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_HEADER)
    assert resp.status_code == 401, "header presence outranks the existence check"


def test_volunteer_role_may_not_open_a_shelter(api):
    """PRD §2.1: "If the acting `X-User-Role` is not among the roles the endpoint authorizes,
    the request is refused with `ERR_UNAUTHORIZED` and HTTP status 403."

    Design: Corner/rbac/volunteer_cannot_open_shelter
    """
    bundle = setup_open_shelter(open_the_shelter=False)

    resp = api.open_shelter(bundle["shelter_id"], bundle["volunteer_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    shelter = validate_success(
        api.get_shelter_operation(bundle["shelter_id"], bundle["coordinator_headers"]))
    assert shelter["posture"] == "PENDING_OPEN"


def test_caseworker_role_may_not_issue_a_card(api):
    """PRD §2.1: "`FinanceOfficer` disburses: approving awards, issuing and redeeming cards, and
    booking cost ledger entries."

    PRD §2.1: "If the acting `X-User-Role` is not among the roles the endpoint authorizes, the
    request is refused with `ERR_UNAUTHORIZED` and HTTP status 403."

    Design: Corner/rbac/caseworker_cannot_issue_card
    """
    bundle = setup_funded_casework_scenario(
        requested_amount_cents=30000, approve_twice=True)

    resp = api.issue_card(bundle["request_id"], bundle["caseworker_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    still = validate_success(
        api.get_assistance_request(bundle["request_id"], bundle["finance_headers"]))
    assert still["card_status"] == "NOT_ISSUED"


def test_undeclared_credential_status_is_rejected_on_volunteer_creation(api):
    """PRD §2.1: "A request that omits a required body field, supplies a field the endpoint does
    not declare, or supplies a value of the wrong type is refused with `ERR_INVALID_REQUEST` and
    HTTP status 400."

    Design: Corner/entities/volunteer_create_rejects_undeclared_field
    """
    region = create_region()
    coord = TEST_USERS["regional_coordinator_headers"]

    resp = api.create_volunteer(
        {"full_name": "Dana Ruiz", "home_region_id": region["id"],
         "qualified_role_codes": ["SHELTER_MANAGER"], "credential_status": "ACTIVE"},
        coord)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    rows, _meta = validate_paginated(api.list_region_volunteers(region["id"], coord))
    assert rows == [], "a rejected create must not leave a row behind"


def test_duplicate_fund_code_is_refused(api):
    """PRD §3.8: "a `fund_code` that must be unique and non-empty — a duplicate is refused with
    `ERR_DUPLICATE_FUND_CODE` at HTTP status 409."

    Design: Corner/errors/duplicate_fund_code_rejected
    """
    create_pool(fund_code="DR-9101-GEN", total_received_cents=100000)

    resp = api.create_fund_pool(
        {"fund_code": "DR-9101-GEN", "restriction_type": "UNRESTRICTED",
         "total_received_cents": 50000},
        TEST_USERS["finance_officer_headers"])
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_FUND_CODE)
