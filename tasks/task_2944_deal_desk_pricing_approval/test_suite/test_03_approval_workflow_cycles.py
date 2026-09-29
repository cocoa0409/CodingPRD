"""The cyclic quote workflow and the two-axis approval request."""
import pytest

from test_helpers import (
    add_price_hold_term,
    add_term,
    assert_instant_equals,
    assert_paginated_list,
    approval_requests_of,
    decide_step,
    latest_approval_request,
    list_terms,
    pending_step_of_request,
    read_quote,
    read_step,
    reopen_quote,
    review_term,
    setup_single_line_quote,
    submit_quote,
)


def _run_change_request_loop(api, quote_id):
    """Submit, have the level-1 approver ask for changes, and capture the ids."""
    submit_quote(api, quote_id)
    request = latest_approval_request(api, quote_id)
    step = pending_step_of_request(api, request["id"])
    decide_step(api, step["id"], "REQUEST_CHANGES", decision_note="Reduce the support discount")
    return request["id"], step["id"]


def test_two_change_request_loops_leave_the_quote_back_in_draft(api, base):
    """PRD §3.7: "It moves the quote `CHANGES_REQUESTED` to `DRAFT`, increments
    `revision_count` by one, clears `submitted_at`, `approved_at` and
    `policy_revalidation_required`, and increments `Quote.version` by one."
    PRD §3.7: "The quote may then be edited and submitted again, incrementing
    `revision_count` on each further round."

    Design: Difficulty/non_linear_state_machine/quote_renegotiation_cycle_increments_revision_count_twice
    """
    quote, _ = setup_single_line_quote(
        api, base, "support", 10, 0.20, term_months=12, title="Northwind Support 10",
        payment_terms_days=30, billing_frequency="ANNUAL",
    )
    _run_change_request_loop(api, quote["id"])
    reopened = reopen_quote(api, quote["id"])
    assert reopened["revision_count"] == 1

    _run_change_request_loop(api, quote["id"])
    reopened = reopen_quote(api, quote["id"])

    assert reopened["status"] == "DRAFT"
    assert reopened["revision_count"] == 2, "the same cycle was traversed twice"

    quote = read_quote(api, quote["id"])
    assert quote["status"] == "DRAFT"
    assert quote["revision_count"] == 2
    assert quote["submitted_at"] is None
    assert quote["final_blended_discount_pct"] == pytest.approx(0.200000, abs=1e-9)
    assert quote["final_net_total_cents"] == 240000


def test_each_cycle_cancels_its_request_and_keeps_the_step_decision(api, base, analyst_headers):
    """PRD §3.7: "The quote's approval request moves `CHANGES_REQUESTED` to `CANCELLED`
    and stamps its `decided_at`."
    PRD §3.7: "A `REQUEST_CHANGES` moves the step `PENDING` to `CHANGES_REQUESTED` and
    moves the request `OPEN` to `CHANGES_REQUESTED`, leaving `discount_track_state` at
    `PENDING` and `terms_track_state` exactly as it was; the quote follows from
    `PENDING_APPROVAL` to `CHANGES_REQUESTED`."
    PRD §3.7: "Every approval step on that request whose `decision` is still `PENDING`
    moves `PENDING` to `VOIDED`, with `decided_at` stamped and `turnaround_hours`
    deliberately left unset."

    Design: Difficulty/non_linear_state_machine/quote_renegotiation_cycle_increments_revision_count_twice
    """
    quote, _ = setup_single_line_quote(
        api, base, "support", 10, 0.20, term_months=12, title="Northwind Support 10",
        payment_terms_days=30, billing_frequency="ANNUAL",
    )
    req1_id, step1_id = _run_change_request_loop(api, quote["id"])
    reopen_quote(api, quote["id"])
    req2_id, step2_id = _run_change_request_loop(api, quote["id"])
    reopen_quote(api, quote["id"])

    assert req1_id != req2_id, "each submit cycle raises its own approval request"
    requests = {req["id"]: req for req in approval_requests_of(api, quote["id"])}
    assert requests[req1_id]["status"] == "CANCELLED"
    assert requests[req2_id]["status"] == "CANCELLED"
    assert requests[req1_id]["required_level"] == 2

    assert read_step(api, step1_id)["decision"] == "CHANGES_REQUESTED"
    assert read_step(api, step2_id)["decision"] == "CHANGES_REQUESTED"

    assert_paginated_list(
        api.list_quote_approval_requests(quote["id"], analyst_headers), expected_total=2
    )
    assert_paginated_list(
        api.list_approval_steps(analyst_headers, params={"decision": "PENDING"}), expected_total=0,
        expected_page_size=0,
    )


def _setup_two_track_quote(api, base):
    quote, _ = setup_single_line_quote(
        api, base, "support", 10, 0.20, term_months=12, title="Northwind Support Net90",
        payment_terms_days=90, billing_frequency="ANNUAL",
    )
    add_term(api, quote["id"], "PAYMENT_TERMS", 90, requested_text="Net 90")
    add_price_hold_term(
        api, quote["id"], base["support"]["id"], "2027-01-01", "2027-12-31",
        requested_numeric_value=24, requested_text="Price hold through 2027",
    )
    submit_quote(api, quote["id"])
    request = latest_approval_request(api, quote["id"])
    for _ in range(2):
        step = pending_step_of_request(api, request["id"])
        decide_step(api, step["id"], "APPROVE", decision_note="Desk ok")
    return quote["id"], request["id"]


def test_discount_track_clears_while_the_terms_track_still_holds_the_request_open(api, base):
    """PRD §3.7: "An `APPROVE` on a step whose `level` equals the request's
    `required_level` moves the step `PENDING` to `APPROVED` and clears the discount axis,
    moving `discount_track_state` from `PENDING` to `CLEARED`, then re-evaluates the join."
    PRD §3.4: "Legal review is mandatory exactly when `terms_risk_score_aggregate` is at
    or above the pinned revision's `terms_review_risk_threshold`; below that threshold the
    terms are handled automatically, as described under submission."

    Design: Difficulty/non_linear_state_machine/approval_request_two_track_fork_join_terms_track_gates_the_join
    """
    quote_id, request_id = _setup_two_track_quote(api, base)

    request = latest_approval_request(api, quote_id)
    assert request["id"] == request_id
    assert request["discount_track_state"] == "CLEARED"
    assert request["terms_track_state"] == "PENDING_LEGAL"
    assert request["status"] == "OPEN", "one cleared axis is not enough to fire the join"
    assert request["current_level"] == 2
    assert read_quote(api, quote_id)["status"] == "PENDING_APPROVAL"

    terms = {term["term_category"]: term for term in list_terms(api, quote_id)}
    review_term(api, terms["PAYMENT_TERMS"]["id"], "APPROVE", reviewer_note="Net 90 acceptable")

    request = latest_approval_request(api, quote_id)
    assert request["terms_track_state"] == "PENDING_LEGAL", "one term is still outstanding"
    assert request["status"] == "OPEN"


def test_the_last_legal_approval_fires_the_join_and_approves_the_quote(api, base):
    """PRD §3.7: "The terms axis clears only when three things hold together:
    `terms_track_state` is `PENDING_LEGAL`, no non-standard term on the quote is left in
    `review_state` `PENDING`, and either the request's `requires_cfo_cosign` is false or
    the one term carrying `requires_cfo_cosign` has its `cfo_cosigned_at` set."
    PRD §3.7: "Moving `OPEN` to `APPROVED` requires the request to still be `OPEN` with
    the discount axis in `NOT_REQUIRED` or `CLEARED` and the terms axis in `NOT_REQUIRED`
    or `CLEARED`; it stamps `decided_at`, computes `total_turnaround_hours`, and sets
    `sla_state` to `MET` when `escalation_count` is zero and to `BREACHED` otherwise, then
    moves the quote `PENDING_APPROVAL` to `APPROVED`."
    PRD §3.4: "The scores are recomputed again at submit, on every legal review decision,
    and whenever a pricing preview is taken."

    Design: Difficulty/non_linear_state_machine/approval_request_two_track_fork_join_terms_track_gates_the_join
    """
    quote_id, request_id = _setup_two_track_quote(api, base)
    terms = {term["term_category"]: term for term in list_terms(api, quote_id)}
    review_term(api, terms["PAYMENT_TERMS"]["id"], "APPROVE", reviewer_note="Net 90 acceptable")
    review_term(
        api, terms["PRICE_HOLD_RENEWAL"]["id"], "APPROVE", reviewer_note="Price hold acceptable"
    )

    quote = read_quote(api, quote_id)
    assert quote["terms_risk_score_aggregate"] == pytest.approx(30.00, abs=1e-9)
    assert quote["terms_risk_score_dominant"] == pytest.approx(25.00, abs=1e-9)

    request = latest_approval_request(api, quote_id)
    assert request["id"] == request_id
    assert request["terms_track_state"] == "CLEARED"
    assert request["discount_track_state"] == "CLEARED"
    assert request["status"] == "APPROVED"
    assert request["sla_state"] == "MET"
    assert request["total_turnaround_hours"] == pytest.approx(0.00, abs=1e-9)
    assert request["requires_cfo_cosign"] is False

    assert quote["status"] == "APPROVED"
    assert_instant_equals(quote["approved_at"], "2026-08-01T00:00:00.000Z", "approved_at")
    assert_instant_equals(quote["expires_at"], "2026-08-31T00:00:00.000Z", "expires_at")
    assert quote["final_net_total_cents"] == 247200

    reviewed = {term["term_category"]: term for term in list_terms(api, quote_id)}
    assert reviewed["PAYMENT_TERMS"]["review_state"] == "APPROVED"
    hold = reviewed["PRICE_HOLD_RENEWAL"]
    assert hold["review_state"] == "APPROVED"
    assert hold["reviewed_by_user_id"] == "u-legal-1"
