"""Corner coverage of the error surface and the role grid: the foreclosure
jurisdiction errors, the two-dimensional signer gate, and the RBAC denials."""
import pytest

from test_helpers import (
    ADMIN,
    QA_CREATOR,
    TEST_USERS,
    add_finding,
    api_client,
    create_active_member,
    create_loan_payload,
    create_member,
    create_member_payload,
    issue_review,
    make_qa_auditor_headers,
    member_rep,
    open_review,
    read_loan,
    register_loan,
    set_clock,
    setup_two_member_pair,
    validate_error,
    validate_paginated,
    validate_success,
)

BORROWER = TEST_USERS["borrower_inquirer_headers"]
QA_CREATOR_HEADERS = make_qa_auditor_headers(QA_CREATOR)


def test_foreclosure_jurisdiction_errors_split_by_mode(api):
    """PRD §3.3: "For an `ASSIGN_OUT_REQUIRED` loan the request must carry
    `assignment_out` set to true; omitting it or setting it false is refused
    with `ERR_ASSIGNMENT_OUT_REQUIRED`."
    PRD §3.3: "For an `IN_REGISTRY_ALLOWED` loan the opposite holds:
    `assignment_out` must be false or omitted entirely, and setting it true is
    refused with `ERR_FORECLOSURE_MODE_FORBIDS_ASSIGN_OUT`."

    Design: Corner/errors/foreclosure_jurisdiction_errors_split_by_mode
    """
    set_clock("2026-01-05T00:00:00Z")
    a = create_active_member(org_id="1000000")
    rows, _ = validate_paginated(api.list_signers(a["id"], ADMIN))
    signer_id = rows[0]["id"]
    loan_ny = register_loan(a["id"], property_state="NY", loan_amount_cents=50000000)
    loan_tx = register_loan(a["id"], property_state="TX", loan_amount_cents=50000000)

    resp_ny = api.foreclose_loan(loan_ny["id"], {"signer_id": signer_id},
                                 member_rep(a["id"]))
    assert resp_ny.status_code == 422, resp_ny.text
    validate_error(resp_ny, "ERR_ASSIGNMENT_OUT_REQUIRED")

    resp_tx = api.foreclose_loan(
        loan_tx["id"], {"signer_id": signer_id, "assignment_out": True},
        member_rep(a["id"]),
    )
    assert resp_tx.status_code == 422, resp_tx.text
    validate_error(resp_tx, "ERR_FORECLOSURE_MODE_FORBIDS_ASSIGN_OUT")

    assert read_loan(loan_ny["id"])["status"] == "ACTIVE"
    assert read_loan(loan_tx["id"])["status"] == "ACTIVE"


def test_signer_scope_and_window_gate_foreclosure(api):
    """PRD §3.3: "The request names a `signer_id`, which must resolve to an
    `ACTIVE` AuthorizedSigner of the acting member whose `role_scope` covers
    the action (`FORECLOSURE` or `ALL`) and whose authority window contains the
    current logical clock position; any failure on those points — missing
    signer, revoked signer, signer of a different member, insufficient scope,
    or a clock position outside the signer's window — is
    `ERR_SIGNER_NOT_AUTHORIZED`."

    Design: Corner/errors/signer_scope_and_window_gate_foreclosure
    """
    set_clock("2026-01-05T00:00:00Z")
    a = create_member(org_id="1000000")
    from test_helpers import add_signer
    s2 = add_signer(a["id"], effective_from="2026-01-01T00:00:00Z",
                    effective_until="2026-03-01T00:00:00Z", role_scope="ALL")
    # Half-open windows that merely touch at the 2026-03-01 endpoint are clean.
    s1 = add_signer(a["id"], effective_from="2026-03-01T00:00:00Z",
                    role_scope="REGISTRATION")
    validate_success(api.activate_member(a["id"], ADMIN))
    loan = register_loan(a["id"], loan_amount_cents=50000000)

    set_clock("2026-06-01T00:00:00Z")
    # Wrong scope: REGISTRATION does not cover foreclosure.
    resp_scope = api.foreclose_loan(loan["id"], {"signer_id": s1["id"]},
                                    member_rep(a["id"]))
    assert resp_scope.status_code == 403, resp_scope.text
    validate_error(resp_scope, "ERR_SIGNER_NOT_AUTHORIZED")

    # Right scope, but the window closed before the clock's position.
    resp_window = api.foreclose_loan(loan["id"], {"signer_id": s2["id"]},
                                     member_rep(a["id"]))
    assert resp_window.status_code == 403, resp_window.text
    validate_error(resp_window, "ERR_SIGNER_NOT_AUTHORIZED")

    assert read_loan(loan["id"])["status"] == "ACTIVE"


def test_memberrep_cannot_create_members_or_settle_reviews(api):
    """PRD §2.1: "A request whose role is recognized but not authorized for the
    target endpoint is rejected with `ERR_ROLE_FORBIDDEN` (HTTP 403)."
    PRD §4: POST /registry/members is authorized for RegistryAdmin only, and
    POST /registry/qa-reviews/{reviewId}/settle is authorized for QAAuditor
    only.

    Design: Corner/rbac/memberrep_cannot_create_members_or_settle_reviews
    """
    set_clock("2026-01-05T00:00:00Z")
    a = create_active_member(org_id="1000000")
    loan = register_loan(a["id"], loan_amount_cents=50000000)
    review = open_review(a["id"])
    add_finding(review["id"], loan["id"], field_name="MIN",
                expected_value="x", actual_value="y", severity="MINOR")
    issue_review(review["id"])

    resp_create = api.create_member(
        create_member_payload(org_id="3000000", legal_name="Rogue Member"),
        member_rep(a["id"]),
    )
    assert resp_create.status_code == 403, resp_create.text
    validate_error(resp_create, "ERR_ROLE_FORBIDDEN")

    resp_settle = api.settle_review(review["id"], {}, member_rep(a["id"]))
    assert resp_settle.status_code == 403, resp_settle.text
    validate_error(resp_settle, "ERR_ROLE_FORBIDDEN")

    rows, meta = validate_paginated(api.list_members(ADMIN))
    assert meta["total_count"] == 1, meta


def test_borrower_inquirer_cannot_write_and_registryadmin_cannot_inquire(api):
    """PRD §3.9: "The borrower-inquiry role may also read loan listings and
    individual loans, but nothing else; it cannot enumerate members, transfers,
    reviews, or any other registry internals."
    PRD §4: GET /registry/borrower-inquiries/{min} is authorized for
    BorrowerInquirer only.

    Design: Corner/rbac/borrower_inquirer_cannot_write_and_registryadmin_cannot_inquire
    """
    set_clock("2026-01-05T00:00:00Z")
    a = create_active_member(org_id="1000000")
    loan = register_loan(a["id"], loan_amount_cents=50000000)

    # The inquiry role has no write access at all.
    resp_write = api.create_loan(create_loan_payload(), BORROWER)
    assert resp_write.status_code == 403, resp_write.text
    validate_error(resp_write, "ERR_ROLE_FORBIDDEN")

    # The inquiry surface is exclusive to the inquiry role.
    resp_inq = api.borrower_inquiry(loan["min"], ADMIN)
    assert resp_inq.status_code == 403, resp_inq.text
    validate_error(resp_inq, "ERR_ROLE_FORBIDDEN")


def test_missing_user_context_header_is_401(api):
    """PRD §2.1: "A request missing either header, or presenting a role string
    the registry does not recognize, is rejected with
    `ERR_MISSING_USER_CONTEXT` (HTTP 401)."
    PRD §2.9: "**Authentication.** The user-context headers must be present and
    the role declared, else `ERR_MISSING_USER_CONTEXT`."

    Design: Corner/rbac/missing_user_context_header_is_401
    """
    from test_helpers import NON_EXISTENT_UUID
    # No user-context headers at all; even an unknown id may not leak a 404.
    resp = api.get_member(NON_EXISTENT_UUID, {})
    assert resp.status_code == 401, resp.text
    validate_error(resp, "ERR_MISSING_USER_CONTEXT")
