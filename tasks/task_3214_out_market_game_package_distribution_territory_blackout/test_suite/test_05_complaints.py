"""Complaints: refund waterfall, grace window, escalation cycle, and ledger
conservation."""
from test_helpers import (
    ApiErrorId,
    make_subscriber_headers,
    make_support_agent_headers,
    set_clock,
    setup_week4_game_account_sub,
    validate_error,
    validate_paginated,
    validate_success,
)
SUPPORT_JANE = make_support_agent_headers("sa-jane")


def _blackout_complaint_setup(api, email="cmp@x.com", detail="blocked"):
    """Account with ACTIVE paid BASE subscription (16667) + one game + one
    BLACKOUT_DISPUTE complaint. Clock stays at 2026-09-01 (purchase day)."""
    ctx = setup_week4_game_account_sub(email=email, billing_zip="75001")
    case = validate_success(
        api.create_complaint_case(
            ctx["account"]["id"], ctx["subscription"]["id"],
            ctx["games"][0]["id"], "BLACKOUT_DISPUTE", detail,
            make_subscriber_headers(ctx["account"]["id"]),
        ),
        expected_status=201,
    )
    ctx["case"] = case
    return ctx


def test_first_approve_refunds_one_weekly_unit_second_after_cancel_fails(
    api, platform_admin_headers
):
    """PRD §3.7: "Otherwise the refund is the smaller of that weekly value and
    the subscription's current `paid_amount_cents`." PRD §3.7: "If the
    subscription's `status` is `CANCELLED`, the refund is zero by rule (a
    cancelled subscription is never refund-eligible via complaint), which then
    fails the floor above."

    Design: Difficulty/cross_entity_state_dependency/complaint_approve_gated_by_subscription_and_season_states
    """
    ctx = _blackout_complaint_setup(api)
    sub = ctx["subscription"]
    account_id = ctx["account"]["id"]
    game_id = ctx["games"][0]["id"]
    case_1 = ctx["case"]
    case_2 = validate_success(
        api.create_complaint_case(
            account_id, sub["id"], game_id, "BLACKOUT_DISPUTE",
            "second complaint", make_subscriber_headers(account_id),
        ),
        expected_status=201,
    )
    set_clock("2026-09-03T00:00:00Z")

    approved = validate_success(
        api.resolve_complaint_case(case_1["id"], "APPROVE", "goodwill",
                                   SUPPORT_JANE)
    )
    assert approved["status"] == "APPROVED_REFUND"
    # weekly value = round_half_up(16667 / 15) = 1111.
    assert approved["refund_amount_cents"] == 1111

    sub_now = validate_success(
        api.get_subscription(sub["id"], platform_admin_headers)
    )
    assert sub_now["paid_amount_cents"] == 15556

    validate_success(
        api.cancel_subscription(sub["id"], make_subscriber_headers(account_id))
    )
    validate_error(
        api.resolve_complaint_case(case_2["id"], "APPROVE", "second goodwill",
                                   SUPPORT_JANE),
        ApiErrorId.ERR_REFUND_NOT_AVAILABLE,
    )
    case2_now = validate_success(
        api.get_complaint_case(case_2["id"], platform_admin_headers)
    )
    assert case2_now["status"] == "OPEN"


def test_paid_amount_reduced_by_refund_while_case_records_amount(
    api, platform_admin_headers
):
    """PRD §3.7: "On approval, the case moves `OPEN` → `APPROVED_REFUND`, with
    `refund_amount_cents` set, `resolution_note` recorded, a `Payment` row of
    `kind` `REFUND` carrying the refund as a positive `amount_cents` appended
    to the subscription, and the subscription's `paid_amount_cents` reduced by
    the same amount."

    Design: Difficulty/cross_entity_state_dependency/complaint_approve_gated_by_subscription_and_season_states
    """
    ctx = _blackout_complaint_setup(api, email="cmp2@x.com")
    approved = validate_success(
        api.resolve_complaint_case(ctx["case"]["id"], "APPROVE", "goodwill",
                                   SUPPORT_JANE)
    )
    assert approved["refund_amount_cents"] == 1111
    assert approved["resolution_note"] == "goodwill"

    sub_now = validate_success(
        api.get_subscription(ctx["subscription"]["id"], platform_admin_headers)
    )
    assert sub_now["paid_amount_cents"] == 16667 - 1111

    ledger, meta = validate_paginated(
        api.list_subscription_payments(ctx["subscription"]["id"],
                                       platform_admin_headers)
    )
    assert meta["total_count"] == 2
    kinds = sorted(row["kind"] for row in ledger)
    assert kinds == ["CHARGE", "REFUND"]


def test_refund_row_uses_remaining_weeks_anchor(api, platform_admin_headers):
    """PRD §3.7: "The weekly value basis divides the subscription's
    `price_charged_cents` by the number of weeks the subscriber received —
    `regular_season_weeks` minus `purchase_week_index` plus one, the
    remaining-weeks anchor — rounded half-up to a whole cent."

    Design: Corner/calculations/blackout_refund_uses_remaining_weeks_anchor_not_elapsed
    """
    ctx = _blackout_complaint_setup(api, email="anch@x.com")
    sub = ctx["subscription"]
    assert sub["price_charged_cents"] == 16667  # week 4 of 18

    approved = validate_success(
        api.resolve_complaint_case(ctx["case"]["id"], "APPROVE", "refund",
                                   SUPPORT_JANE)
    )
    # Remaining-weeks anchor: round_half_up(16667 / 15) == 1111.
    # NOT 926 (16667/18) and NOT 5555 (16667/3).
    assert approved["refund_amount_cents"] == 1111


def test_refund_consumed_portion_never_refundable(api, platform_admin_headers):
    """PRD §3.7: "the elapsed portion of the season — the weeks before the
    purchase week, measured by the elapsed-weeks factor of
    purchase-week-minus-one over total weeks — is never refundable, and
    exactly one weekly-value unit is refundable per complaint."

    Design: Corner/calculations/blackout_refund_uses_remaining_weeks_anchor_not_elapsed
    """
    ctx = _blackout_complaint_setup(api, email="anch2@x.com")
    sub = ctx["subscription"]
    approved = validate_success(
        api.resolve_complaint_case(ctx["case"]["id"], "APPROVE", "refund",
                                   SUPPORT_JANE)
    )
    refund = approved["refund_amount_cents"]
    # A single complaint refunds exactly one weekly unit (1111), which is far
    # below both the charged price (16667) and the paid balance.
    assert refund == 1111
    assert refund < sub["price_charged_cents"]
    sub_now = validate_success(
        api.get_subscription(sub["id"], platform_admin_headers)
    )
    # The consumed/elapsed portion is not part of the refund: paid balance
    # only drops by the single weekly unit.
    assert sub_now["paid_amount_cents"] == 16667 - 1111


def test_ledger_conservation_charge_then_refund(api, platform_admin_headers):
    """PRD §3.7: "a `Payment` row of `kind` `REFUND` carrying the refund as a
    positive `amount_cents` appended to the subscription, and the
    subscription's `paid_amount_cents` reduced by the same amount."

    Design: Difficulty/compensating_invariant/subscription_paid_amount_ledger_conservation
    """
    ctx = _blackout_complaint_setup(api, email="led@x.com")
    sub = ctx["subscription"]
    approved = validate_success(
        api.resolve_complaint_case(ctx["case"]["id"], "APPROVE",
                                   "refund approved", SUPPORT_JANE)
    )
    assert approved["refund_amount_cents"] == 1111

    ledger, meta = validate_paginated(
        api.list_subscription_payments(sub["id"], platform_admin_headers)
    )
    assert meta["total_count"] == 2
    charge = [r for r in ledger if r["kind"] == "CHARGE"]
    refund = [r for r in ledger if r["kind"] == "REFUND"]
    assert len(charge) == 1 and charge[0]["amount_cents"] == 16667
    assert len(refund) == 1 and refund[0]["amount_cents"] == 1111

    sub_now = validate_success(
        api.get_subscription(sub["id"], platform_admin_headers)
    )
    assert sub_now["paid_amount_cents"] == 15556
    assert sub_now["paid_amount_cents"] == 16667 - 1111


def test_refund_payment_row_carries_reason(api, platform_admin_headers):
    """PRD §3.7: "(A `REFUND` payment row always carries a `reason`; `CHARGE`
    rows may omit it.)"

    Design: Difficulty/compensating_invariant/subscription_paid_amount_ledger_conservation
    """
    ctx = _blackout_complaint_setup(api, email="led2@x.com")
    sub = ctx["subscription"]
    validate_success(
        api.resolve_complaint_case(ctx["case"]["id"], "APPROVE",
                                   "refund approved", SUPPORT_JANE)
    )
    ledger, _ = validate_paginated(
        api.list_subscription_payments(sub["id"], platform_admin_headers)
    )
    refund = [r for r in ledger if r["kind"] == "REFUND"]
    assert len(refund) == 1
    assert isinstance(refund[0].get("reason"), str)
    assert len(refund[0]["reason"]) > 0


def test_escalate_deescalate_cycle_returns_case_to_open(
    api, platform_admin_headers
):
    """PRD §3.7: "Escalation is the holding pattern: a support agent may move
    `OPEN` → `ESCALATED`, and only from `ESCALATED` may the case be
    de-escalated back to `OPEN`. The loop may cycle; `APPROVED_REFUND` and
    `DENIED` are terminal."

    Design: Corner/state_machines/complaint_escalate_deescalate_cycle_returns_to_open
    """
    ctx = _blackout_complaint_setup(api, email="esc@x.com")
    escalated = validate_success(
        api.escalate_complaint_case(ctx["case"]["id"], SUPPORT_JANE)
    )
    assert escalated["status"] == "ESCALATED"

    reopened = validate_success(
        api.deescalate_complaint_case(ctx["case"]["id"], SUPPORT_JANE)
    )
    assert reopened["status"] == "OPEN"
    assert reopened["refund_amount_cents"] == 0


def test_escalation_does_not_consume_refund_window(api, platform_admin_headers):
    """PRD §3.7: "A complaint is born `OPEN` with `refund_amount_cents` zero
    and `resolution_note` null." PRD §3.7: "Escalation is the holding
    pattern: a support agent may move `OPEN` → `ESCALATED`, and only from
    `ESCALATED` may the case be de-escalated back to `OPEN`."

    Design: Corner/state_machines/complaint_escalate_deescalate_cycle_returns_to_open
    """
    ctx = _blackout_complaint_setup(api, email="esc2@x.com")
    validate_success(
        api.escalate_complaint_case(ctx["case"]["id"], SUPPORT_JANE)
    )
    validate_success(
        api.deescalate_complaint_case(ctx["case"]["id"], SUPPORT_JANE)
    )
    # Still within the grace window (same logical day): the case is resolvable.
    approved = validate_success(
        api.resolve_complaint_case(ctx["case"]["id"], "APPROVE", "ok",
                                   SUPPORT_JANE)
    )
    assert approved["status"] == "APPROVED_REFUND"
    assert approved["refund_amount_cents"] == 1111
