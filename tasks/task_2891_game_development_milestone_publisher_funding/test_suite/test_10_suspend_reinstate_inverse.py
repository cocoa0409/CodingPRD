"""Suspension and reinstatement as an exact compensating pair across the payment, the
posture and the vendor engagement."""

from test_helpers.assertions import assert_budget_summary, assert_fields_equal, assert_ledger
from test_helpers.fixtures import (
    DEFAULT_CRITERIA_2,
    accept_milestone,
    activate,
    add_milestone,
    create_engagement,
    draft_agreement,
    payment_of_milestone,
    read_agreement,
    setup_registry,
)
from prd_bench_local_runner.testing import validate_success

ALPHA_PASSING = {
    "feature_completeness_pct": 75.00,
    "crash_free_sessions_pct": 96.00,
    "content_completeness_pct": 60.00,
    "known_blocker_count": 5,
}


def _saltglass_with_unauthorized_payment(api):
    """An accepted milestone whose payment is left unauthorized and a live engagement."""
    reg = setup_registry(api, studio_name="Saltglass Studio",
                        studio_email="dev@saltglass.example", studio_country="NZ")
    agreement = draft_agreement(reg, "Saltglass", 3600000, 2500, "2027-03-31",
                                live_ops_quarterly_funding_cents=100000)
    milestone = add_milestone(reg, agreement["id"], 1, "Alpha", "ALPHA",
                              3600000, 400000, DEFAULT_CRITERIA_2)
    activate(reg, agreement["id"])
    engagement = create_engagement(
        reg, milestone["id"], "ANIM-SALT", 400000, "2026-08-05", "2026-09-05",
        "Character animation",
    )
    assert engagement["status"] == "ACTIVE"

    accept_milestone(reg, milestone["id"], 1, ALPHA_PASSING)
    payment = payment_of_milestone(reg, milestone["id"])
    assert payment["status"] == "PENDING_AUTHORIZATION"
    assert payment["scheduled_amount_cents"] == 3600000

    before = read_agreement(reg, agreement["id"])
    assert before["funding_posture"] == "RESTRICTED"
    assert before["accepted_value_cents"] == 3600000
    return reg, agreement, milestone, engagement, payment


def _assert_committed_basis_intact(api, reg, milestone_id):
    assert_budget_summary(
        validate_success(api.get_budget_summary(milestone_id, reg.dev)),
        milestone_id=milestone_id, budget=400000, committed_basis=400000,
        incurred_basis=0, available_committed=0, overrun=0,
    )


def test_suspension_holds_the_payment_and_freezes_the_engagement(api):
    """PRD §3.3: "Suspension moves the agreement `ACTIVE → SUSPENDED` and forces
    `funding_posture` to `FROZEN` ... Step one moves every milestone payment of this
    agreement whose `status` is `PENDING_AUTHORIZATION` to `HELD_PENDING_CURE`. Step
    two, because those payments have moved, recomputes `withheld_payment_cents` as the
    sum of their `scheduled_amount_cents`. Step three moves every contractor engagement
    whose milestone belongs to this agreement and whose `status` is `ACTIVE` to
    `SUSPENDED`."

    Design: Difficulty/compensating_invariant/suspend_then_reinstate_restores_payment_withholding_posture_and_engagement_exactly
    """
    reg, agreement, milestone, engagement, payment = _saltglass_with_unauthorized_payment(api)

    suspended = validate_success(
        api.suspend_agreement(agreement["id"], reg.finance,
                              {"reason": "Publisher liquidity review"})
    )
    assert_fields_equal(
        suspended, {"status": "SUSPENDED", "funding_posture": "FROZEN"}, "agreement"
    )
    assert_ledger(suspended, withheld_payment_cents=3600000)

    held = validate_success(api.get_payment(payment["id"], reg.finance))
    assert_fields_equal(
        held, {"status": "HELD_PENDING_CURE", "scheduled_amount_cents": 3600000}, "payment"
    )
    assert validate_success(api.get_engagement(engagement["id"], reg.dev))["status"] == "SUSPENDED"
    _assert_committed_basis_intact(api, reg, milestone["id"])


def test_reinstatement_restores_the_payment_the_posture_and_the_engagement(api):
    """PRD §3.3: "Step one of the restoration returns every payment in
    `HELD_PENDING_CURE` to `PENDING_AUTHORIZATION` and recomputes
    `withheld_payment_cents` down to 0." The posture returns to `RESTRICTED` because
    §2.6 derives it from an unchanged `accepted_value_cents`.

    Design: Difficulty/compensating_invariant/suspend_then_reinstate_restores_payment_withholding_posture_and_engagement_exactly
    """
    reg, agreement, milestone, engagement, payment = _saltglass_with_unauthorized_payment(api)

    validate_success(
        api.suspend_agreement(agreement["id"], reg.finance,
                              {"reason": "Publisher liquidity review"})
    )
    reinstated = validate_success(
        api.reinstate_agreement(agreement["id"], reg.finance,
                                {"reason": "Liquidity review cleared"})
    )
    assert_fields_equal(
        reinstated, {"status": "ACTIVE", "funding_posture": "RESTRICTED"}, "agreement"
    )
    assert_ledger(
        reinstated,
        withheld_payment_cents=0,
        accepted_value_cents=3600000,
        advance_disbursed_cents=0,
        holdback_reserve_cents=0,
    )

    restored = validate_success(api.get_payment(payment["id"], reg.finance))
    assert_fields_equal(
        restored,
        {"status": "PENDING_AUTHORIZATION", "scheduled_amount_cents": 3600000},
        "payment",
    )
    engagement_after = validate_success(api.get_engagement(engagement["id"], reg.dev))
    assert_fields_equal(
        engagement_after, {"status": "ACTIVE", "committed_cents": 400000}, "engagement"
    )
    _assert_committed_basis_intact(api, reg, milestone["id"])


def test_the_payment_obligation_survives_the_whole_cycle(api):
    """PRD §3.3: "Across the whole suspend-then-reinstate pair the payment-obligation
    invariant holds: the sum of `scheduled_amount_cents` over the agreement's payments
    equals `accepted_value_cents` before the freeze and after the thaw, because a held
    payment's `scheduled_amount_cents` never changes across the cycle."

    Design: Difficulty/compensating_invariant/suspend_then_reinstate_restores_payment_withholding_posture_and_engagement_exactly
    """
    reg, agreement, milestone, _engagement, _payment = _saltglass_with_unauthorized_payment(api)

    def obligation():
        rows = validate_success(api.list_payments(reg.finance, {"milestone_id": milestone["id"]}))
        return sum(row["scheduled_amount_cents"] for row in rows)

    before = read_agreement(reg, agreement["id"])
    assert obligation() == before["accepted_value_cents"] == 3600000

    validate_success(
        api.suspend_agreement(agreement["id"], reg.finance, {"reason": "Liquidity review"})
    )
    validate_success(
        api.reinstate_agreement(agreement["id"], reg.finance, {"reason": "Cleared"})
    )

    after = read_agreement(reg, agreement["id"])
    assert obligation() == after["accepted_value_cents"] == 3600000
