"""Outcomes that hinge on the state of a different entity than the one being written."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_line,
    assert_instant_equals,
    book_order_form,
    create_grant,
    decide_step,
    generate_order_form,
    latest_approval_request,
    pending_step_of_request,
    read_account,
    read_order_form,
    read_quote,
    read_step,
    record_signature,
    send_order_form,
    set_clock,
    set_credit_status,
    setup_single_line_quote,
    submit_quote,
    validate_error,
    USER_IDS,
    make_deal_desk_analyst_headers,
    assert_paginated_list,
)


def _signed_order_form(api, base):
    quote, _ = setup_single_line_quote(
        api, base, "support", 10, 0.00, term_months=12, title="Northwind Support Renewal",
        payment_terms_days=30, billing_frequency="ANNUAL",
    )
    submitted = submit_quote(api, quote["id"])
    form = generate_order_form(
        api, quote["id"], submitted["version"], signer_name="Dana Reeves",
        signer_email="dana.reeves@northwind.example",
    )
    sent = send_order_form(api, form["id"])
    signed = record_signature(api, form["id"], "SIGNED", "Dana Reeves")
    return submitted, form, sent, signed


def test_booking_is_refused_while_the_account_sits_on_credit_hold(api, base, analyst_headers):
    """PRD §3.9: "Then come the acceptance criteria themselves, in a fixed order. The
    account's `credit_status` must be `CLEAR` or `WATCH`; an account on `HOLD` is refused
    with `ERR_ACCOUNT_CREDIT_HOLD`."
    PRD §2.11: "no side effect of the request — not a state change, not a recomputation, not
    a ledger move — is applied when any check fails."

    Design: Difficulty/cross_entity_state_dependency/booking_blocked_by_account_credit_hold_then_allowed_after_release
    """
    submitted, form, sent, signed = _signed_order_form(api, base)
    assert submitted["status"] == "APPROVED", "an undiscounted quote needs no approver"
    assert submitted["required_approval_level"] == 0
    assert_instant_equals(submitted["expires_at"], "2026-08-31T00:00:00.000Z", "expires_at")
    # PRD 3.9: "Generation increments Quote.version by one and then records
    # generated_from_quote_version as the incremented value", so the form carries
    # one more than the version the generate call was issued against.
    assert form["generated_from_quote_version"] == submitted["version"] + 1
    assert read_quote(api, submitted["id"])["version"] == submitted["version"] + 1
    assert sent["status"] == "OUT_FOR_SIGNATURE"
    assert signed["status"] == "SIGNED"

    held = set_credit_status(
        api, base["account"]["id"], "HOLD",
        credit_note="Aged receivable escalation opened by treasury",
    )
    assert held["credit_status"] == "HOLD"

    response = api.book_order_form(form["id"], analyst_headers)
    validate_error(response, ApiErrorId.ERR_ACCOUNT_CREDIT_HOLD.value, 409)

    blocked = read_order_form(api, form["id"])
    assert blocked["status"] == "SIGNED"
    assert blocked["booked_arr_cents"] == 0
    assert read_account(api, base["account"]["id"])["booked_arr_cents"] == 0


def test_the_same_booking_call_succeeds_once_the_hold_is_released(api, base):
    """PRD §3.9: "Booking moves the form `SIGNED` to `BOOKED`, stamps `booked_at`, writes
    both figures onto the form, increases the account's conserved `booked_arr_cents` by the
    form's `booked_arr_cents`, and bubbles up: the quote moves `APPROVED` to `BOOKED`, stamps
    its own `booked_at`, and copies both booking figures onto itself."
    PRD §3.1: "Credit posture is changed afterwards by a `PlatformAdmin` or the `CFO`
    recording a decision that sets `credit_status` to `CLEAR`, `WATCH` or `HOLD` together
    with an optional `credit_note`. `CLEAR` and `WATCH` both permit booking; `HOLD` blocks
    it, and an attempt to book against an account on hold is refused with
    `ERR_ACCOUNT_CREDIT_HOLD`."

    Design: Difficulty/cross_entity_state_dependency/booking_blocked_by_account_credit_hold_then_allowed_after_release
    """
    submitted, form, _, _ = _signed_order_form(api, base)
    set_credit_status(
        api, base["account"]["id"], "HOLD",
        credit_note="Aged receivable escalation opened by treasury",
    )
    cleared = set_credit_status(
        api, base["account"]["id"], "CLEAR", credit_note="Receivable settled; hold released"
    )
    assert cleared["credit_status"] == "CLEAR"

    booked = book_order_form(api, form["id"])
    assert booked["status"] == "BOOKED"
    assert booked["booked_arr_cents"] == 300000
    assert booked["booked_tcv_cents"] == 300000

    assert read_account(api, base["account"]["id"])["booked_arr_cents"] == 300000
    quote = read_quote(api, submitted["id"])
    assert quote["status"] == "BOOKED"
    assert quote["booked_arr_cents"] == 300000
    assert quote["booked_tcv_cents"] == 300000


def _delegated_level_two_step(api, base):
    quote, _ = setup_single_line_quote(
        api, base, "core", 250, 0.05, term_months=36, title="Northwind Delegated Approval",
        payment_terms_days=30, billing_frequency="ANNUAL",
    )
    add_line(api, quote["id"], base["support"]["id"], 250, 0.00)
    submitted = submit_quote(api, quote["id"])
    request = latest_approval_request(api, quote["id"])
    step1 = pending_step_of_request(api, request["id"])
    decide_step(api, step1["id"], "APPROVE", decision_note="Level 1 cleared by deal desk")
    step2 = pending_step_of_request(api, request["id"])
    grant = create_grant(
        api, USER_IDS["dual_two"], 2, 0.30, "2026-08-10T00:00:00Z", "2026-08-20T00:00:00Z"
    )
    return submitted, request, step1, step2, grant


def test_a_delegation_is_not_live_at_the_exclusive_end_of_its_window(api, base):
    """PRD §2.10: "The grant must be live: it must still be `ACTIVE`, and the logical clock
    must be at or after `starts_at` and strictly before `ends_at`, otherwise the decision is
    refused with `ERR_DELEGATION_NOT_ACTIVE` (HTTP 409)."
    PRD §2.10: "A `SalesDirector`, a `VPSales` or the `CFO` may issue a **delegation grant**
    naming a `grantee_user_id`, the `tier_level` being lent, a `max_discount_pct` ceiling,
    and a half-open window running from an inclusive `starts_at` to an exclusive `ends_at`."

    Design: Difficulty/cross_entity_state_dependency/step_decision_under_delegation_grant_at_exact_window_end_is_not_active
    """
    submitted, _, step1, step2, grant = _delegated_level_two_step(api, base)
    assert submitted["final_blended_discount_pct"] == pytest.approx(0.246053, abs=1e-9)
    assert submitted["required_approval_level"] == 2
    assert_instant_equals(submitted["expires_at"], "2026-08-31T00:00:00.000Z", "expires_at")
    assert read_step(api, step1["id"])["decision"] == "APPROVED"
    assert step2["level"] == 2
    assert step2["assigned_role"] == "SalesDirector"
    assert grant["status"] == "ACTIVE"

    set_clock(api, "2026-08-20T00:00:00Z")
    response = api.decide_approval_step(
        step2["id"],
        {"decision": "APPROVE", "decision_note": "Approving under delegated authority"},
        make_deal_desk_analyst_headers(USER_IDS["dual_two"]),
    )
    validate_error(response, ApiErrorId.ERR_DELEGATION_NOT_ACTIVE.value, 409)

    blocked = read_step(api, step2["id"])
    assert blocked["decision"] == "PENDING"
    assert blocked["delegation_grant_id"] is None

    grants, _ = assert_paginated_list(
        api.list_delegation_grants(
            make_deal_desk_analyst_headers(), params={"grantee_user_id": USER_IDS["dual_two"]}
        ),
        expected_total=1,
    )
    assert grants[0]["used_step_count"] == 0
    assert grants[0]["status"] == "ACTIVE"


def test_one_second_inside_the_window_the_delegated_decision_lands(api, base):
    """PRD §2.10: "A grant records how many step decisions have been made under it in
    `used_step_count`, and neither revocation nor expiry rewinds that counter or detaches the
    grant from steps already decided under it."
    PRD §3.8: "At approval it is re-based: `expires_at` becomes `approved_at` advanced by the
    same `quote_validity_days` days, except that when `approved_at` itself falls inside the
    surge window the result is truncated to the quarter-end instant — a deal approved in the
    closing days of a quarter cannot carry a price into the next one."
    PRD §3.8: "When a step is decided, `turnaround_hours` records the elapsed time between
    the step's `created_at` and its `decided_at`, expressed in hours — that is, the elapsed
    seconds divided by 3,600 — rounded half up to two decimal places."

    Design: Difficulty/cross_entity_state_dependency/step_decision_under_delegation_grant_at_exact_window_end_is_not_active
    """
    submitted, request, _, step2, grant = _delegated_level_two_step(api, base)
    set_clock(api, "2026-08-20T00:00:00Z")
    api.decide_approval_step(
        step2["id"],
        {"decision": "APPROVE", "decision_note": "Approving under delegated authority"},
        make_deal_desk_analyst_headers(USER_IDS["dual_two"]),
    )

    set_clock(api, "2026-08-19T23:59:59Z")
    decided = decide_step(
        api, step2["id"], "APPROVE",
        headers=make_deal_desk_analyst_headers(USER_IDS["dual_two"]),
        decision_note="Approving under delegated authority",
    )
    assert decided["decision"] == "APPROVED"
    assert decided["delegation_grant_id"] == grant["id"]
    assert decided["acting_user_id"] == USER_IDS["dual_two"]
    assert decided["turnaround_hours"] == pytest.approx(456.00, abs=1e-9)

    grants, _ = assert_paginated_list(
        api.list_delegation_grants(
            make_deal_desk_analyst_headers(), params={"grantee_user_id": USER_IDS["dual_two"]}
        ),
        expected_total=1,
    )
    assert grants[0]["used_step_count"] == 1

    request = latest_approval_request(api, submitted["id"])
    assert request["status"] == "APPROVED"
    assert request["total_turnaround_hours"] == pytest.approx(456.00, abs=1e-9)
    assert request["sla_state"] == "MET"

    quote = read_quote(api, submitted["id"])
    assert quote["status"] == "APPROVED"
    assert_instant_equals(quote["approved_at"], "2026-08-19T23:59:59.000Z", "approved_at")
    assert_instant_equals(quote["expires_at"], "2026-09-18T23:59:59.000Z", "expires_at")
