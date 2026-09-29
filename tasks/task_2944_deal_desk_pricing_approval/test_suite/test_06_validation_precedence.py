"""Requests that violate two rules at once must answer the higher-priority one."""
import pytest

from test_helpers import (
    add_line,
    ApiErrorId,
    assert_paginated_list,
    create_grant,
    decide_exception,
    decide_step,
    file_exception,
    latest_approval_request,
    make_deal_desk_analyst_headers,
    make_sales_rep_headers,
    pending_step_of_request,
    read_account,
    read_exception,
    read_quote,
    read_step,
    revoke_exception,
    setup_single_line_quote,
    submit_quote,
    validate_error,
    USER_IDS,
)


def _setup_resubmit_conflict(api, base, cfo_headers):
    """A submitted below-floor quote whose rescuing exception has been revoked."""
    quote, _ = setup_single_line_quote(
        api, base, "service", 10, 0.00, term_months=12, title="Northwind Services Only",
        payment_terms_days=30, billing_frequency="ANNUAL",
    )
    exception = file_exception(
        api, quote["id"], competitor_name="Vertex Systems",
        competitor_quoted_total_cents=1850000, evidence_reference="EV-2026-115",
        justification="Displacement deal",
    )
    decide_exception(api, exception["id"], "ACCEPT", decision_note="Approved by desk")
    submit_quote(api, quote["id"])
    revoke_exception(api, exception["id"], headers=cfo_headers, decision_note="Evidence withdrawn")
    return quote["id"], exception["id"]


def test_resubmit_answers_the_state_error_not_the_margin_floor_breach(
    api, base, rep_headers, cfo_headers
):
    """PRD §2.11: "Checks are evaluated from the top of the list downwards, the first
    violated check decides the response, and no side effect of the request — not a state
    change, not a recomputation, not a ledger move — is applied when any check fails."
    PRD §2.11: "**State precondition.** The target record is in a status from which the
    requested transition is declared."
    PRD §2.11: "**Fiscal floors and budgets.** `ERR_DISCOUNT_STACK_EXCEEDED`,
    `ERR_ABSOLUTE_MARGIN_FLOOR_BREACH`, `ERR_MARGIN_FLOOR_BREACH`,
    `ERR_EXCEPTION_NOT_NEEDED`, `ERR_EXCEPTION_ALLOWANCE_EXHAUSTED` and
    `ERR_NO_ACTIVE_DESK_POLICY`, all with HTTP 422."

    Design: Difficulty/priority_pair_validation_conflict/resubmit_conflict_state_error_wins_over_margin_floor_breach
    """
    quote_id, _ = _setup_resubmit_conflict(api, base, cfo_headers)

    response = api.submit_quote(quote_id, rep_headers)
    validate_error(response, ApiErrorId.ERR_QUOTE_NOT_DRAFT.value, 409)


def test_the_refused_resubmit_changes_nothing_at_all(api, base, rep_headers, cfo_headers, analyst_headers):
    """PRD §2.11: "When a single request violates more than one rule, exactly one error is
    returned, and which one is fully determined by the following order."
    PRD §3.5: "Revocation moves `ACCEPTED` to `REVOKED`, stamps `released_at` with the
    logical clock and records the note, returns exactly `allowance_consumed_cents` to the
    account's pool while retaining that recorded figure on the exception for audit,
    recomputes the quote's `required_approval_level` from the matrix without the
    accepted-exception floor, and increments `Quote.version` by one."

    Design: Difficulty/priority_pair_validation_conflict/resubmit_conflict_state_error_wins_over_margin_floor_breach
    """
    quote_id, exception_id = _setup_resubmit_conflict(api, base, cfo_headers)
    api.submit_quote(quote_id, rep_headers)

    quote = read_quote(api, quote_id)
    assert quote["status"] == "PENDING_APPROVAL"
    assert quote["required_approval_level"] == 0
    assert quote["final_margin_pct"] == pytest.approx(0.250000, abs=1e-9)

    exception = read_exception(api, quote_id, exception_id)
    assert exception["status"] == "REVOKED"
    assert exception["allowance_consumed_cents"] == 200000

    assert read_account(api, base["account"]["id"])["exception_allowance_used_cents"] == 0
    assert_paginated_list(
        api.list_quote_approval_requests(quote_id, analyst_headers), expected_total=1
    )


def _setup_dual_hat_step(api, base):
    """A level-2 step on a quote owned by the very user holding the delegation."""
    owner = make_sales_rep_headers(USER_IDS["dual_one"])
    quote, _ = setup_single_line_quote(
        api, base, "core", 250, 0.05, term_months=36, title="Northwind Dual Hat Deal",
        payment_terms_days=30, billing_frequency="ANNUAL", headers=owner,
    )
    add_line(api, quote["id"], base["support"]["id"], 250, 0.00, owner)
    grant = create_grant(
        api, USER_IDS["dual_one"], 2, 0.18, "2026-08-01T00:00:00Z", "2026-08-31T00:00:00Z"
    )
    submit_quote(api, quote["id"], owner)
    request = latest_approval_request(api, quote["id"], owner)
    step1 = pending_step_of_request(api, request["id"], owner)
    decide_step(api, step1["id"], "APPROVE", decision_note="Desk ok")
    step2 = pending_step_of_request(api, request["id"], owner)
    return {
        "quote_id": quote["id"],
        "request_id": request["id"],
        "grant": grant,
        "step2": step2,
    }


def test_step_decision_answers_segregation_of_duties_not_the_delegation_ceiling(api, base):
    """PRD §2.11: "**Segregation of duties.** `ERR_SEGREGATION_OF_DUTIES` (403) on
    `POST /approval-steps/{id}/decide` and `POST /competitive-exceptions/{id}/decide`, as
    described above."
    PRD §2.11: "**Approver authority.** The four delegation and role checks described in
    section 2.10: `ERR_APPROVER_ROLE_MISMATCH` (403), `ERR_DELEGATION_NOT_ACTIVE` (409),
    `ERR_DELEGATION_LEVEL_NOT_DELEGABLE` (422) and `ERR_DELEGATION_SCOPE_EXCEEDED` (422)."
    PRD §2.10: "First, the user who owns a quote may not decide any approval step on it: if
    the acting `X-User-ID` equals the quote's `owner_rep_user_id`, the step decision is
    refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/step_decide_conflict_segregation_of_duties_wins_over_delegation_scope
    """
    scenario = _setup_dual_hat_step(api, base)
    step2 = scenario["step2"]
    assert step2["level"] == 2
    assert step2["assigned_role"] == "SalesDirector"

    response = api.decide_approval_step(
        step2["id"],
        {"decision": "APPROVE", "decision_note": "Self approving under delegation"},
        make_deal_desk_analyst_headers(USER_IDS["dual_one"]),
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)


def test_the_refused_step_decision_records_nothing_on_step_or_grant(api, base):
    """PRD §2.11: "no side effect of the request — not a state change, not a recomputation,
    not a ledger move — is applied when any check fails."
    PRD §3.7: "Every decision records `acting_user_id` from the acting `X-User-ID`,
    `decided_at` from the logical clock, the elapsed `turnaround_hours`, and the supplied
    `decision_note`; and when the decision was made under a delegation it additionally
    records that grant's identifier in the step's `delegation_grant_id` and increments the
    grant's `used_step_count` by one."

    Design: Difficulty/priority_pair_validation_conflict/step_decide_conflict_segregation_of_duties_wins_over_delegation_scope
    """
    scenario = _setup_dual_hat_step(api, base)
    api.decide_approval_step(
        scenario["step2"]["id"],
        {"decision": "APPROVE", "decision_note": "Self approving under delegation"},
        make_deal_desk_analyst_headers(USER_IDS["dual_one"]),
    )

    quote = read_quote(api, scenario["quote_id"], make_sales_rep_headers(USER_IDS["dual_one"]))
    assert quote["final_blended_discount_pct"] == pytest.approx(0.246053, abs=1e-9)
    assert quote["required_approval_level"] == 2
    assert quote["status"] == "PENDING_APPROVAL"

    step = read_step(api, scenario["step2"]["id"])
    assert step["decision"] == "PENDING"
    assert step["acting_user_id"] is None
    assert step["delegation_grant_id"] is None

    grants = {grant["id"]: grant for grant in
              assert_paginated_list(api.list_delegation_grants(
                  make_deal_desk_analyst_headers()))[0]}
    assert grants[scenario["grant"]["id"]]["used_step_count"] == 0

    assert latest_approval_request(api, scenario["quote_id"])["status"] == "OPEN"
