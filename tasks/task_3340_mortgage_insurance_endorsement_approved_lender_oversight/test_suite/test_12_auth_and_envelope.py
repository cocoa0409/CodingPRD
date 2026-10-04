"""Authentication, role authorization, and the response envelope contract."""
import pytest

from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUID,
    attach_appraisal,
    create_case,
    create_lender,
    endorse_case,
    setup_approved_lender,
    setup_endorsed_case,
    submit_case,
    validate_error,
    validate_success,
)
from test_helpers import api_client
from test_helpers.test_users import (
    TEST_USERS,
    anonymous_headers,
    make_approver_headers,
    make_examiner_headers,
    make_lender_officer_headers,
    make_reviewer_headers,
    make_servicer_officer_headers,
    unknown_role_headers,
)


# ---------------------------------------------------------------------------
# Authentication (priority 1)
# ---------------------------------------------------------------------------
def test_unauthenticated_request_missing_role_header(api):
    """PRD §2.1: "Every request carries two headers: `X-User-ID` identifying the
    caller, and `X-User-Role` naming the caller's role. A request missing either
    header, or carrying a role the platform does not recognize, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/unauthenticated_request_missing_role_header
    """
    response = api_client.get_lender(UNKNOWN_UUID, anonymous_headers())
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)


def test_unrecognized_role_header_rejected(api):
    """PRD §2.1: "A request missing either header, or carrying a role the platform does
    not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/unrecognized_role_header_rejected
    """
    response = api_client.get_lender(UNKNOWN_UUID, unknown_role_headers())
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)


def test_invalid_action_enum_on_status_change(api):
    """PRD §3.1: "The action vocabulary is `ADVANCE_TO_FIELD_REVIEW`, `RETURN`,
    `RESUBMIT`, `APPROVE`, `SUSPEND`, `REINSTATE`, and `TERMINATE`"
    PRD §2.7: "Payload shape: required fields present, enums valid, amounts positive,
    `start_date` not after `end_date`, `deficiency_codes` non-empty on a flag-deficient
    decision (`ERR_VALIDATION`)."

    Design: Corner/validations/invalid_action_enum_on_status_change
    """
    lender = create_lender(legal_name="Bad Action Co")
    response = api_client.lender_status_change(
        lender["id"], {"action": "DEMOTE"}, make_reviewer_headers("rev-1")
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION)


# ---------------------------------------------------------------------------
# Role authorization (priority 2)
# ---------------------------------------------------------------------------
def test_servicer_officer_cannot_create_loan_case(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for the endpoint
    — or, on the lender lifecycle endpoint, not permitted for the requested action — is
    rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: "| POST | /mi/loan-cases | Open a mortgage insurance case | LenderOfficer |"

    Design: Corner/rbac/servicer_officer_cannot_create_loan_case
    """
    lender = setup_approved_lender(lender_overrides={"legal_name": "RBAC Case Co"})
    response = api_client.create_loan_case(
        {
            "lender_id": lender["id"],
            "borrower_reference": "RS-1",
            "base_loan_amount_cents": 30_000_000,
            "appraised_value_cents": 31_250_000,
            "term_months": 360,
            "note_rate_bps": 700,
            "current_monthly_payment_cents": 200_000,
        },
        make_servicer_officer_headers(lender["id"]),
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_fha_reviewer_cannot_void_endorsement(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for the endpoint
    — or, on the lender lifecycle endpoint, not permitted for the requested action — is
    rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: "| POST | /mi/loan-cases/{loanCaseId}/void-endorsement | Void an
    endorsement; compensates volume and cancels billed annual MIP | FhaApprover |"

    Design: Corner/rbac/fha_reviewer_cannot_void_endorsement
    """
    _lender, case = setup_endorsed_case(
        lender_overrides={"legal_name": "RBAC Void Co"}
    )
    response = api_client.void_endorsement(
        case["id"], {"reason": "test"}, make_reviewer_headers("rev-2")
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_lender_officer_cannot_perform_approver_status_change(api):
    """PRD §3.1: "the role-to-action matrix gates each: `RESUBMIT` belongs to the
    owning `LenderOfficer`, `ADVANCE_TO_FIELD_REVIEW` and `RETURN` belong to an
    `FhaReviewer`, and `APPROVE`, `SUSPEND`, `REINSTATE`, and `TERMINATE` belong to an
    `FhaApprover`; a caller attempting an action outside their role is rejected with
    `ERR_UNAUTHORIZED_ROLE`."

    Design: Corner/rbac/lender_officer_cannot_perform_approver_status_change
    """
    lender = create_lender(legal_name="RBAC Action Co")
    api_client.lender_status_change(
        lender["id"], {"action": "ADVANCE_TO_FIELD_REVIEW"},
        make_reviewer_headers("rev-1"),
    )
    response = api_client.lender_status_change(
        lender["id"], {"action": "APPROVE"},
        make_lender_officer_headers(lender["id"]),
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_shared_get_endpoints_work_for_every_role(api):
    """PRD §4: "| GET | /mi/lenders/{lenderId} | Get a lender | PlatformAdmin,
    LenderOfficer, ServicerOfficer, FhaReviewer, FhaApprover, ClaimsExaminer |"

    Design: Corner/rbac/shared_get_endpoints_work_for_every_role
    """
    lender = create_lender(legal_name="Shared GET Co")
    all_headers = [
        TEST_USERS["platform_admin_headers"],
        make_lender_officer_headers(lender["id"]),
        make_servicer_officer_headers(lender["id"]),
        make_reviewer_headers("rev-1"),
        make_approver_headers("app-1"),
        make_examiner_headers("cx-1"),
    ]
    for headers in all_headers:
        data = validate_success(api_client.get_lender(lender["id"], headers))
        assert data["id"] == lender["id"]


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def test_success_envelope_shape_on_create(api):
    """PRD §2.2: "All successful API responses (those with 2xx status codes) follow
    this standard envelope format in their JSON body"
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."

    Design: Corner/endpoints/success_envelope_shape_on_create
    """
    response = api_client.create_lender(
        {
            "legal_name": "Envelope Co",
            "institution_type": "MORTGAGEE_SUPERVISED",
            "home_state": "VA",
            "qc_plan_on_file": True,
        },
        TEST_USERS["platform_admin_headers"],
    )
    assert response.status_code == 201
    body = response.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert body["data"]["legal_name"] == "Envelope Co"


def test_error_envelope_shape_on_failure(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this standard
    envelope format"
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the
    specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/endpoints/error_envelope_shape_on_failure
    """
    response = api_client.get_lender(
        UNKNOWN_UUID, TEST_USERS["platform_admin_headers"]
    )
    assert response.status_code == 404
    body = response.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()


def test_clock_set_endpoint_returns_current_utc(api):
    """PRD §2.4: "A `PlatformAdmin` advances it by supplying a target instant
    `to_iso8601` through an admin-only test-driving capability, and the response echoes
    the resulting `current_utc`."

    Design: Corner/endpoints/clock_set_endpoint_returns_current_utc
    """
    response = api_client.set_current_utc(
        "2026-10-15T12:00:00Z", TEST_USERS["platform_admin_headers"]
    )
    data = validate_success(response)
    assert data["current_utc"].startswith("2026-10-15T12:00:00")
