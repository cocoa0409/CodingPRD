"""One call at the top of a hierarchy propagating down every declared level."""
import pytest

from test_helpers import (
    add_price_hold_term,
    add_term,
    assert_instant_equals,
    assert_paginated_list,
    assess_revrec,
    decide_exception,
    decide_step,
    file_exception,
    latest_approval_request,
    list_terms,
    open_revrec,
    pending_step_of_request,
    read_account,
    read_exception,
    read_quote,
    read_revrec,
    read_step,
    reopen_quote,
    review_term,
    setup_quote_with_lines,
    setup_single_line_quote,
    submit_quote,
)


def _setup_changes_requested_quote(api, base):
    """A quote carrying reviewed terms and a cleared assessment, sent back at level 2."""
    quote, _ = setup_quote_with_lines(
        api, base, [("core", 60, 0.15), ("service", 4, 0.10)], term_months=24,
        title="Northwind Platform + Services", payment_terms_days=90, billing_frequency="ANNUAL",
    )
    add_term(api, quote["id"], "PAYMENT_TERMS", 90, requested_text="Net 90")
    add_price_hold_term(
        api, quote["id"], base["core"]["id"], "2027-01-01", "2027-12-31",
        requested_numeric_value=24, requested_text="Hold platform pricing through 2027",
    )
    assessment = open_revrec(api, quote["id"])
    assess_revrec(api, assessment["id"], "CLEAR", assessment_note="Allocation reviewed")
    submit_quote(api, quote["id"])

    request = latest_approval_request(api, quote["id"])
    step1 = pending_step_of_request(api, request["id"])
    decide_step(api, step1["id"], "APPROVE", decision_note="Desk ok")
    for term in list_terms(api, quote["id"]):
        review_term(api, term["id"], "APPROVE", reviewer_note="Ok")
    step2 = pending_step_of_request(api, request["id"])
    decide_step(api, step2["id"], "REQUEST_CHANGES", decision_note="Rework the services scope")
    return {
        "quote_id": quote["id"],
        "request_id": request["id"],
        "step1_id": step1["id"],
        "step2_id": step2["id"],
        "assessment": assessment,
    }


def test_reopen_cancels_the_request_without_touching_decided_steps(api, base, analyst_headers):
    """PRD §3.7: "The quote's approval request moves `CHANGES_REQUESTED` to `CANCELLED` and
    stamps its `decided_at`."
    PRD §3.7: "Every approval step on that request whose `decision` is still `PENDING`
    moves `PENDING` to `VOIDED`, with `decided_at` stamped and `turnaround_hours`
    deliberately left unset."

    Design: Difficulty/transitive_cascade/reopen_cascade_four_levels_request_steps_terms_revrec
    """
    scenario = _setup_changes_requested_quote(api, base)
    reopen_quote(api, scenario["quote_id"])

    quote = read_quote(api, scenario["quote_id"])
    assert quote["status"] == "DRAFT"
    assert quote["revision_count"] == 1
    assert quote["submitted_at"] is None
    assert quote["final_net_total_cents"] == 6432502
    assert quote["final_blended_discount_pct"] == pytest.approx(0.219357, abs=1e-9)

    request = latest_approval_request(api, scenario["quote_id"])
    assert request["id"] == scenario["request_id"]
    assert request["status"] == "CANCELLED"
    assert request["terms_track_state"] == "CLEARED", "the cleared axis is not rolled back"

    assert read_step(api, scenario["step1_id"])["decision"] == "APPROVED"
    assert read_step(api, scenario["step2_id"])["decision"] == "CHANGES_REQUESTED"
    assert_paginated_list(
        api.list_approval_steps(analyst_headers, params={"decision": "VOIDED"}),
        expected_total=0, expected_page_size=0,
    )


def test_reopen_reverts_reviewed_terms_and_stales_the_assessment(api, base):
    """PRD §3.7: "Every non-standard term on the quote whose `review_state` is `APPROVED`
    moves back from `APPROVED` to `PENDING`, clearing `reviewed_by_user_id`,
    `reviewed_at`, `reviewer_note`, `cfo_cosigned_at` and `cfo_cosigned_by_user_id` — so a
    term can be reviewed more than once across a deal's life."
    PRD §3.7: "And every revenue recognition assessment on the quote in `ASSESSED`,
    `CLEARED` or `BLOCKED` moves to `STALE`."
    PRD §3.6: "When at least two distinct categories appear and `USAGE_AS_INCURRED` is
    among them, it is `USAGE_BASED_HYBRID`. In every other case — two or more distinct
    categories with no usage-metered line — it is `MULTI_ELEMENT`."

    Design: Difficulty/transitive_cascade/reopen_cascade_four_levels_request_steps_terms_revrec
    """
    scenario = _setup_changes_requested_quote(api, base)
    assessment = scenario["assessment"]
    assert assessment["arrangement_type"] == "MULTI_ELEMENT"
    assert assessment["allocable_amount_cents"] == 6432502
    assert assessment["allocation_residual_cents"] == 1

    reopen_quote(api, scenario["quote_id"])

    for term in list_terms(api, scenario["quote_id"]):
        assert term["review_state"] == "PENDING", term["term_category"]
        assert term["reviewed_by_user_id"] is None
        assert term["reviewed_at"] is None

    assert read_revrec(api, scenario["quote_id"], assessment["id"])["status"] == "STALE"


def _setup_rejected_step_scenario(api, base):
    """A submitted below-floor quote rescued by an accepted exception."""
    quote, _ = setup_single_line_quote(
        api, base, "service", 10, 0.00, term_months=12, title="Northwind Implementation",
        payment_terms_days=30, billing_frequency="ANNUAL",
    )
    add_term(api, quote["id"], "INDEMNITY_CAP", 3, requested_text="3x cap")
    add_term(api, quote["id"], "TERMINATION_FOR_CONVENIENCE", 3, requested_text="3 months notice")
    exception = file_exception(
        api, quote["id"], competitor_name="Vertex Systems",
        competitor_quoted_total_cents=1850000, evidence_reference="EV-2026-114",
        justification="Competitor undercut on services",
    )
    accepted = decide_exception(api, exception["id"], "ACCEPT", decision_note="Strategic logo")
    submit_quote(api, quote["id"])
    request = latest_approval_request(api, quote["id"])
    return {
        "quote_id": quote["id"],
        "account_id": base["account"]["id"],
        "exception": accepted,
        "request_id": request["id"],
        "step1_id": pending_step_of_request(api, request["id"])["id"],
    }


def test_step_reject_blocks_the_discount_axis_and_rejects_request_and_quote(api, base):
    """PRD §3.7: "A `REJECT` moves the step `PENDING` to `REJECTED` and blocks the discount
    axis, moving `discount_track_state` from `PENDING` to `BLOCKED`; that forces the
    request `OPEN` to `REJECTED` regardless of where the terms axis stands, which forces
    the quote `PENDING_APPROVAL` to `REJECTED` with all of the quote's own rejection
    cascades."
    PRD §3.7: "Moving `OPEN` to `REJECTED` requires the request to still be `OPEN` with
    either axis in `BLOCKED`; it stamps `decided_at` and `total_turnaround_hours`, and sets
    `sla_state` to `BREACHED` when `escalation_count` is greater than zero and to `MET`
    otherwise, then moves the quote to `REJECTED`."

    Design: Difficulty/transitive_cascade/step_reject_cascade_releases_exception_allowance_and_withdraws_terms
    """
    scenario = _setup_rejected_step_scenario(api, base)
    assert scenario["exception"]["allowance_consumed_cents"] == 200000
    assert read_account(api, scenario["account_id"])["exception_allowance_used_cents"] == 200000

    decide_step(api, scenario["step1_id"], "REJECT", decision_note="Margin unacceptable")

    step = read_step(api, scenario["step1_id"])
    assert step["decision"] == "REJECTED"
    assert step["acting_user_id"] == "u-desk-1"

    request = latest_approval_request(api, scenario["quote_id"])
    assert request["discount_track_state"] == "BLOCKED"
    assert request["terms_track_state"] == "PENDING_LEGAL", "the terms axis is left where it stood"
    assert request["status"] == "REJECTED"
    assert request["sla_state"] == "MET"
    assert request["total_turnaround_hours"] == pytest.approx(0.00, abs=1e-9)

    quote = read_quote(api, scenario["quote_id"])
    assert quote["status"] == "REJECTED"
    assert quote["final_margin_pct"] == pytest.approx(0.250000, abs=1e-9)
    assert quote["required_approval_level"] == 3


def test_rejection_withdraws_pending_terms_and_returns_the_allowance(api, base):
    """PRD §3.7: "Reaching `REJECTED` withdraws and releases: every non-standard term on
    the quote whose `review_state` is `PENDING` moves `PENDING` to `WITHDRAWN`, after which
    it no longer contributes to any later risk recomputation; and every competitive
    exception on the quote in `ACCEPTED` moves to `RELEASED`, stamps `released_at`, and
    returns its `allowance_consumed_cents` to the account's pool."
    PRD §3.5: "Alternatively, the exception is released automatically: whenever the parent
    quote reaches `REJECTED` or `EXPIRED`, every exception of that quote sitting in
    `ACCEPTED` moves `ACCEPTED` to `RELEASED`, has `released_at` stamped, and returns its
    `allowance_consumed_cents` to the account's pool."

    Design: Difficulty/transitive_cascade/step_reject_cascade_releases_exception_allowance_and_withdraws_terms
    """
    scenario = _setup_rejected_step_scenario(api, base)
    decide_step(api, scenario["step1_id"], "REJECT", decision_note="Margin unacceptable")

    for term in list_terms(api, scenario["quote_id"]):
        assert term["review_state"] == "WITHDRAWN", term["term_category"]

    exception = read_exception(api, scenario["quote_id"], scenario["exception"]["id"])
    assert exception["status"] == "RELEASED"
    assert exception["allowance_consumed_cents"] == 200000, (
        "the consumed figure is retained on the exception for audit"
    )
    assert_instant_equals(exception["released_at"], "2026-08-01T00:00:00.000Z", "released_at")

    account = read_account(api, scenario["account_id"])
    assert account["exception_allowance_used_cents"] == 0, "the pool returns to where it started"
