"""Corner queue: endpoints — pagination envelope semantics, the fixed error
envelope, and the computed servicing-status portfolio filter."""
from test_helpers import (
    EXPECTED_SUCCESS_STATUS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_draft,
    read_loan,
    set_clock,
    setup_active_loan,
    setup_draft_application,
    setup_loan_with_t1_released,
    validate_error,
    validate_paginated,
)


def test_applications_list_paginates_with_envelope_fields(api):
    """PRD §2.3: "List endpoints accept two query parameters. `limit` sets the page size: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of records to skip and defaults to 0. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in its `meta` object. Unless a workflow states a different ordering, list results are ordered by `created_at` ascending."
    PRD §3.2: "Applications can be listed with optional `applicant_id`, `declaration_id`, `loan_id`, and `status` filters, ordered by `created_at` ascending."

    Design: Corner/endpoints/applications_list_paginates_with_envelope_fields
    """
    ctx = setup_draft_application(requested_amount_cents=2500000)
    applicant_id = ctx["applicant"]["id"]
    create_draft(ctx, requested_amount_cents=3000000)
    create_draft(ctx, loan_purpose="ECONOMIC_INJURY",
                 requested_amount_cents=3500000)

    resp = api.list_applications(
        ctx["officer_headers"],
        params={"applicant_id": applicant_id, "limit": 2, "offset": 0})
    page1, meta1 = validate_paginated(resp)
    assert len(page1) == 2
    # total_count counts the filtered set (3), not the page.
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert isinstance(resp.json()["meta"].get("api_request_id"), str)
    assert isinstance(resp.json()["meta"].get("api_request_timestamp"), str)

    resp = api.list_applications(
        ctx["officer_headers"],
        params={"applicant_id": applicant_id, "limit": 2, "offset": 2})
    page2, meta2 = validate_paginated(resp)
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    assert isinstance(resp.json()["meta"].get("api_request_id"), str)
    assert isinstance(resp.json()["meta"].get("api_request_timestamp"), str)


def test_error_response_uses_fixed_envelope(api, servicing_agent_headers):
    """PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."
    PRD §2.6: "The first identifier that does not resolve yields `ERR_NOT_FOUND` (HTTP 404)"

    Design: Corner/endpoints/error_response_uses_fixed_envelope
    """
    resp = api.get_loan(NON_EXISTENT_UUID, servicing_agent_headers)
    assert resp.status_code == 404
    error_data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert error_data["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(error_data["message"], str) and error_data["message"]

    body = resp.json()
    assert body["response_type"] == "error"
    assert set(body["meta"].keys()) == {
        "api_request_id", "api_request_timestamp"}
    assert body["meta"]["api_request_id"]
    assert body["meta"]["api_request_timestamp"]


def test_loans_portfolio_filter_by_servicing_status(api):
    """PRD §3.9: "Otherwise, while `next_due_date` is null or the current date is on or before it, `days_past_due` is zero; past that, it is the count of calendar days between `next_due_date` and the current date."
    PRD §3.9: "Status boundaries are inclusive at every rung: at 30 or more days past due a `CURRENT` loan becomes `DELINQUENT`; at 120 or more a `DELINQUENT` loan becomes `DEFAULT`; at 180 or more a loan in `DEFAULT` is charged off, moving `lifecycle_status` to `CHARGED_OFF`, which is terminal and accepts no further payments (`ERR_LOAN_NOT_ACTIVE`)."
    PRD §4: "Paginated list of loans with `application_id`, `applicant_id`, `servicing_status`, and `lifecycle_status` filters."

    Design: Corner/endpoints/loans_portfolio_filter_by_servicing_status
    """
    # Loan A: accepted 2026-11-01 with T1 released -> next_due 2027-12-01.
    ctx = setup_loan_with_t1_released()
    loan_a_id = ctx["loan"]["id"]
    # Loan B: accepted but never disbursed -> next_due_date stays null.
    ctx = setup_active_loan(_ctx=ctx)
    loan_b_id = ctx["loan"]["id"]

    # 2027-12-31 is exactly 30 days past loan A's due date (inclusive).
    set_clock("2027-12-31T00:00:00Z", ctx["admin_headers"])

    resp = api.list_loans(
        ctx["servicing_headers"], params={"servicing_status": "DELINQUENT"})
    rows, _meta = validate_paginated(resp)
    assert [row["id"] for row in rows] == [loan_a_id]

    loan_b = read_loan(ctx, loan_id=loan_b_id)
    assert loan_b["servicing_status"] == "CURRENT"
    assert loan_b["next_due_date"] is None
