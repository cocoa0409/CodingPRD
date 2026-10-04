"""Corner queue: entities — creation defaults, computed fields, identity,
immutability, and input-shape rejection."""
from test_helpers import (
    EXPECTED_SUCCESS_STATUS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_credit_review,
    assert_declaration,
    create_application_payload,
    create_applicant_payload,
    create_declaration_payload,
    credit_review_payload,
    fresh_user_id,
    is_valid_uuid,
    make_loan_officer_headers,
    new_context,
    register_applicant,
    setup_declaration,
    setup_submitted_application,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_declaration_create_computes_deadlines_and_opens(api):
    """PRD §3.1: "The `physical_filing_deadline` is `declared_date` plus 90 days; the `economic_injury_filing_deadline` is `declared_date` plus 270 days."
    PRD §2.4: "Each declaration's `status` is advanced to match the new instant: `OPEN` while the current instant is on or before `physical_filing_deadline`; `PHYSICAL_CLOSED` once the current instant is strictly after `physical_filing_deadline` but still on or before `economic_injury_filing_deadline`; `FULLY_CLOSED` once the current instant is strictly after `economic_injury_filing_deadline`."
    PRD §2.5: "Most resources also carry the common audit triple: `created_at` (ISO 8601 UTC with three fractional digits, set at creation), `updated_at` (same format, refreshed on every mutation), and `version` (an integer that increments by 1 on every mutation of that resource)."

    Design: Corner/entities/declaration_create_computes_deadlines_and_opens
    """
    ctx = new_context()  # no clock call: logical clock stays at 2026-09-01

    resp = api.create_declaration(
        create_declaration_payload(), ctx["admin_headers"])
    decl = validate_success(resp, EXPECTED_SUCCESS_STATUS["create_declaration"])
    assert_declaration(decl)
    assert decl["status"] == "OPEN"
    assert decl["version"] == 1
    # declared_date 2026-10-01 + 90 days = 2026-12-30; + 270 days = 2027-06-28.
    assert decl["physical_filing_deadline"].startswith("2026-12-30T00:00:00")
    assert decl["economic_injury_filing_deadline"].startswith("2027-06-28T00:00:00")
    # Server-generated identity/audit fields plus the meta request id.
    assert is_valid_uuid(decl["id"])
    body = resp.json()
    assert isinstance(body["meta"].get("api_request_id"), str)


def test_application_create_draft_defaults_and_caller_identity(api):
    """PRD §3.2: "A registered `Applicant` begins the borrowing workflow by creating a loan application in `DRAFT` status, born with `reconsideration_count` at zero, `submitted_at` null until submission, `decline_reason` null, and `loan_id` null until an approval sets it."
    PRD §3.2: "The `applicant_id` is always taken from the caller's `X-User-ID` and never from the request body."

    Design: Corner/entities/application_create_draft_defaults_and_caller_identity
    """
    ctx = new_context()
    setup_declaration(ctx)  # clock -> 2026-10-02, then DR-4821
    applicant, applicant_headers = register_applicant()

    resp = api.create_application(
        create_application_payload(
            ctx["declaration"]["id"], requested_amount_cents=2500000),
        applicant_headers)
    application = validate_success(
        resp, EXPECTED_SUCCESS_STATUS["create_application"])
    assert application["status"] == "DRAFT"
    assert application["reconsideration_count"] == 0
    assert application["submitted_at"] is None
    assert application["loan_id"] is None
    # applicant_id is stamped from X-User-ID, not from any body field.
    assert application["applicant_id"] == applicant["id"]
    assert application["version"] == 1


def test_application_get_missing_id_not_found(api, loan_officer_headers):
    """PRD §2.6: "The first identifier that does not resolve yields `ERR_NOT_FOUND` (HTTP 404); a request to act on a child of a missing parent therefore reports the parent as not found."

    Design: Corner/entities/application_get_missing_id_not_found
    """
    resp = api.get_application(NON_EXISTENT_UUID, loan_officer_headers)
    error_data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert error_data["error_id"] == "ERR_NOT_FOUND"


def test_credit_review_immutable_record_without_version(api):
    """PRD §2.5: "Three record types are immutable ledgers and carry only `id` and `created_at`: the credit review, the payment, and the grant award. For those three, `updated_at` and `version` are absent entirely — they are never updated after creation."
    PRD §3.3: "The officer's `X-User-ID` is recorded as `reviewer_user_id`."

    Design: Corner/entities/credit_review_immutable_record_without_version
    """
    ctx = setup_submitted_application(requested_amount_cents=2500000)
    officer_headers = make_loan_officer_headers(fresh_user_id("lo-nina"))

    resp = api.create_credit_review(
        ctx["application"]["id"],
        credit_review_payload(credit_score=700,
                              verified_monthly_debt_cents=100000),
        officer_headers)
    review = validate_success(resp, EXPECTED_SUCCESS_STATUS["create_credit_review"])
    # Ledger record: id + created_at present; updated_at/version absent.
    assert_credit_review(review)
    assert "version" not in review
    assert "updated_at" not in review
    assert review["reviewer_user_id"] == officer_headers["X-User-ID"]

    rows = validate_success(
        api.list_credit_reviews(ctx["application"]["id"], ctx["officer_headers"]),
        EXPECTED_SUCCESS_STATUS["list_credit_reviews"])
    assert len(rows) == 1
    assert rows[0]["id"] == review["id"]


def test_application_create_invalid_purpose_rejected(api):
    """PRD §3.2: "The create payload names the `declaration_id` of the declaration being filed under, the `county_fips` where the damaged property or injured business sits, the `loan_purpose` (`PHYSICAL_DAMAGE` or `ECONOMIC_INJURY`), and the `requested_amount_cents` (strictly greater than zero)."
    PRD §2.6: "**Request well-formedness** — required fields present, enum values in range, amounts positive where required, and the shape rules of Section 3 (for example, `depreciation_pct` present and within range exactly when the `valuation_basis` calls for it, `end_date` strictly after `start_date`, a grant's `purpose_category` matching the application's `loan_purpose`), else `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/application_create_invalid_purpose_rejected
    """
    ctx = new_context()
    setup_declaration(ctx)
    applicant, applicant_headers = register_applicant()

    resp = api.create_application(
        create_application_payload(
            ctx["declaration"]["id"],
            loan_purpose="EIDL",  # outside {PHYSICAL_DAMAGE, ECONOMIC_INJURY}
            requested_amount_cents=2500000),
        applicant_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    # Nothing was persisted for this applicant.
    data, _meta = validate_paginated(api.list_applications(
        ctx["officer_headers"], params={"applicant_id": applicant["id"]}))
    assert data == []
