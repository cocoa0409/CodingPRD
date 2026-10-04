"""Dual-variant money readings: the two valid computations of one week's charge,
and the two valid readings of a driver's credit.

Each test builds its own preconditions from an empty database; the harness
restarts the server before every test.
"""
from test_helpers import (
    TEST_DEFAULTS,
    agreement_summary,
    assert_amount_due_exact,
    assert_platform_credit,
    get_week,
    open_week,
    pay_week_in_full,
    platform_credit_for,
    settle_week,
    setup_active_agreement,
    setup_agreement_with_open_week,
)


def test_provisional_charge_differs_from_settled_charge(api):
    """PRD §3.5: "In the provisional variant, the week enters OPEN while the mile
    cycle is still open. base_charge_cents is the agreement's weekly_rate_cents
    and insurance_charge_cents is the agreement's insurance_premium_cents, both
    carried across unchanged."
    PRD §3.5: "Because the final variant brings in mileage and damage that the
    provisional variant does not, a settled week always yields an amount owed
    strictly greater than the figure the week showed while provisionally open,
    whenever the driver exceeded their included mileage or any damage liability
    was settled onto the week."

    Design: Difficulty/dual_variant_calc/weekly_charge_provisional_vs_final
    """
    ctx = setup_agreement_with_open_week(miles=2200, mileage_cap_miles=2_000)

    provisional = get_week(ctx.week["id"])
    assert_amount_due_exact(
        provisional["amount_due_cents"],
        TEST_DEFAULTS["WEEKLY_RATE_CENTS"] + TEST_DEFAULTS["INSURANCE_PREMIUM_CENTS"]
        - platform_credit_for(95),
        "opening the period",
    )
    assert provisional["mileage_overage_cents"] == 0, (
        "no mileage has been closed while the week is OPEN"
    )
    assert provisional["damage_charge_cents"] == 0

    settled = settle_week(ctx.week["id"])
    assert_amount_due_exact(settled["amount_due_cents"], 43_435, "settlement")
    assert settled["amount_due_cents"] > provisional["amount_due_cents"], (
        "the final reading must exceed the provisional reading once the mile cycle closes"
    )


def test_settled_charge_is_pinned_component_sum(api):
    """PRD §3.5: "The final computation writes all four money components at once.
    base_charge_cents is again the agreement's weekly_rate_cents, and
    insurance_charge_cents is again insurance_premium_cents."
    PRD §3.5: "amount_due_cents is the base plus the insurance plus the mile
    overage plus the damage, minus the platform credit."

    Design: Difficulty/dual_variant_calc/weekly_charge_provisional_vs_final
    """
    ctx = setup_agreement_with_open_week(miles=2200, mileage_cap_miles=2_000)
    settled = settle_week(ctx.week["id"])

    assert settled["base_charge_cents"] == TEST_DEFAULTS["WEEKLY_RATE_CENTS"]
    assert settled["insurance_charge_cents"] == TEST_DEFAULTS["INSURANCE_PREMIUM_CENTS"]
    assert settled["mileage_overage_cents"] == 5_000, (
        "200 miles beyond the included 2000, at 25 cents per mile"
    )
    assert_platform_credit(settled["platform_credit_cents"], 565)
    assert_amount_due_exact(
        settled["amount_due_cents"],
        settled["base_charge_cents"]
        + settled["insurance_charge_cents"]
        + settled["mileage_overage_cents"]
        + settled["damage_charge_cents"]
        - settled["platform_credit_cents"],
        "settlement",
    )


def test_renewal_credit_is_not_a_copy_of_the_platform_credit_field(api):
    """PRD §3.2: "The renewal credit is reported to the driver on the agreement
    summary alongside outstanding_balance_cents, outstanding_delinquent_weeks,
    escrow_balance_cents and the agreement's current_week_number and
    agreement_status, and it is never written back into platform_credit_cents.
    That field always holds the activity-based figure."

    Design: Difficulty/dual_variant_calc/activity_credit_forward_vs_settled_basis
    """
    ctx = setup_active_agreement(unlimited=True)
    week1 = open_week(ctx.agreement["id"])
    settle_week(week1["id"])
    paid = pay_week_in_full(week1["id"])

    week1 = get_week(week1["id"])
    assert week1["platform_credit_cents"] == 565, (
        "the week always carries the activity-based credit"
    )

    summary = agreement_summary(ctx.agreement["id"])
    assert summary["renewal_credit_cents"] == paid["amount_due_cents"], (
        "the renewal credit counts the money actually collected on the settled week"
    )
    assert summary["renewal_credit_cents"] != week1["platform_credit_cents"], (
        "the settled-basis credit must not be a copy of the platform credit field"
    )


def test_renewal_credit_accumulates_while_platform_credit_stays_activity_based(api):
    """PRD §3.2: "The renewal credit is a statement about money actually
    collected: it counts only the payments whose payment_outcome is SUCCEEDED and
    that were applied to weeks which then settled, so a week that was only
    partially tendered contributes just its coverage_cents, and a week that was
    waived contributes nothing at all."

    Design: Difficulty/dual_variant_calc/activity_credit_forward_vs_settled_basis
    """
    ctx = setup_active_agreement(unlimited=True)
    collected = 0
    for _ in range(2):
        week = open_week(ctx.agreement["id"])
        settle_week(week["id"])
        paid = pay_week_in_full(week["id"])
        collected += paid["amount_due_cents"]
        assert get_week(week["id"])["platform_credit_cents"] == 565

    summary = agreement_summary(ctx.agreement["id"])
    assert summary["renewal_credit_cents"] == collected, (
        f"two settled weeks should report {collected} cents collected"
    )
    assert summary["total_billed_cents"] == collected