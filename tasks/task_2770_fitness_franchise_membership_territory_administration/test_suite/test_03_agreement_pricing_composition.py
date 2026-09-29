"""Signing pricing: three stacked credits, each rounded before any of them is summed.

A 4500-cent list plan with a 12.5 percent promotion, a 4.5 percent corporate credit and
the 1.5 percent multi-club credit. Every component lands on a half cent, so the order of
rounding decides the stored price.
"""

from test_helpers import (
    assert_agreement_pricing_components,
    create_approved_promotion,
    create_corporate_account,
    create_member,
    setup_single_club_franchise,
    sign_agreement,
)


def _agreement_with_all_three_credits() -> dict:
    scenario = setup_single_club_franchise(
        legal_name="Harbor Fit Group LLC",
        contact_email="ops@harborfitgroup.example",
        club_name="Harbor Club",
    )
    promotion = create_approved_promotion(
        scenario["franchisee"]["id"],
        scenario["plan_template"]["id"],
        code="SUMMER125",
        discount_pct=0.125,
        starts_on="2026-07-01",
        ends_on="2026-09-30",
    )
    corporate = create_corporate_account(
        name="Meridian Logistics",
        corporate_credit_pct=0.045,
        allocation_method="USAGE_SHARE",
    )
    member = create_member(
        scenario["club"]["id"], full_name="Ana Reyes", email="ana.reyes@example.com"
    )
    agreement = sign_agreement(
        member["id"],
        scenario["club"]["id"],
        scenario["plan_template"]["id"],
        signed_on="2026-08-01",
        multi_club_access=True,
        promotion_id=promotion["id"],
        corporate_account_id=corporate["id"],
    )
    scenario["member"] = member
    scenario["promotion"] = promotion
    scenario["corporate_account"] = corporate
    scenario["agreement"] = agreement
    return scenario


def test_each_discount_component_is_rounded_on_its_own_before_any_summing():
    """562.5, 202.5 and 67.5 each round away from zero on their own, giving 563, 203 and
    68 rather than one combined rounding of 832.5.

    PRD 3.3: "Each of the three discount components is computed and rounded half up to
    whole cents *independently*: `promo_discount_cents` is 0 when no `promotion_id` was
    quoted and otherwise the base multiplied by the promotion's `discount_pct`, rounded
    half up; `corporate_credit_cents` is 0 when no `corporate_account_id` was named and
    otherwise the base multiplied by the account's `corporate_credit_pct`, rounded half up;
    and `multi_club_credit_cents` is 0 when `multi_club_access` is false and otherwise the
    base multiplied by the multi-club credit rate of 0.015 — one and a half percent —
    rounded half up."

    Design: Difficulty/combinatorial_formula/effective_dues_rounds_each_discount_component_before_summing
    """
    agreement = _agreement_with_all_three_credits()["agreement"]

    assert agreement["monthly_dues_base_cents"] == 4500
    assert agreement["promo_discount_cents"] == 563
    assert agreement["corporate_credit_cents"] == 203
    assert agreement["multi_club_credit_cents"] == 68


def test_effective_dues_subtracts_the_sum_of_the_already_rounded_components():
    """4500 minus 834 is 3666. Summing the three unrounded fractions and rounding once
    would have produced 3667, which is the forbidden alternative.

    PRD 3.3: "Only then are the three *already-rounded* components added together to form
    the total discount, and the gross monthly dues are the base minus that total."

    Design: Difficulty/combinatorial_formula/effective_dues_rounds_each_discount_component_before_summing
    """
    agreement = _agreement_with_all_three_credits()["agreement"]

    assert agreement["effective_monthly_dues_cents"] == 3666
    assert agreement["effective_monthly_dues_cents"] != 3667
    assert_agreement_pricing_components(agreement)


def test_gross_price_clears_the_floor_and_is_stored_verbatim():
    """3666 sits above the 3600-cent brand floor, so it is stored exactly as computed
    with nothing lifted up to the floor.

    PRD 3.3: "When the gross figure is at or above the floor, it is stored verbatim as
    `effective_monthly_dues_cents`, and that figure — like every other pinned term — never
    moves again, not when the quoted promotion is later withdrawn by the brand, and not
    when the membership is transferred to another club."

    Design: Difficulty/combinatorial_formula/effective_dues_rounds_each_discount_component_before_summing
    """
    setup = _agreement_with_all_three_credits()

    assert setup["plan_template"]["floor_price_cents"] == 3600
    assert setup["agreement"]["effective_monthly_dues_cents"] >= 3600
    assert setup["agreement"]["effective_monthly_dues_cents"] == 3666


def test_signing_pins_the_statute_and_the_list_terms_off_their_sources():
    """The governing statute comes from the home club and both money terms are copies of
    the template, so a later library edit cannot move this contract.

    PRD 3.3: "`monthly_dues_base_cents` is a pinned copy of the template's
    `monthly_dues_cents`, and `initiation_fee_cents` a pinned copy of the template's
    `initiation_fee_cents`, so a later edit to the library cannot move a signed contract."

    Design: Difficulty/combinatorial_formula/effective_dues_rounds_each_discount_component_before_summing
    """
    setup = _agreement_with_all_three_credits()
    agreement = setup["agreement"]

    assert agreement["state_code"] == "CA"
    assert agreement["state_code"] == setup["club"]["state_code"]
    assert agreement["monthly_dues_base_cents"] == setup["plan_template"]["monthly_dues_cents"]
    assert agreement["initiation_fee_cents"] == setup["plan_template"]["initiation_fee_cents"]
    assert agreement["cancellation_notice_days"] == 30


def test_new_agreement_opens_on_pending_and_current_with_an_empty_ledger():
    """Both status dimensions start at their initial values and every money projection is
    zero until a dues entry lands.

    PRD 3.3: "Alongside them the agreement is created with `outstanding_balance_cents` 0,
    `dues_paid_cents` 0, `delinquency_days` 0 and `transfer_count` 0, and with
    `cancellation_requested_on`, `cancellation_effective_on`, `refund_cents`,
    `early_termination_fee_cents` and `net_settlement_cents` all null."

    Design: Difficulty/combinatorial_formula/effective_dues_rounds_each_discount_component_before_summing
    """
    agreement = _agreement_with_all_three_credits()["agreement"]

    assert agreement["agreement_status"] == "PENDING"
    assert agreement["dues_status"] == "CURRENT"
    assert agreement["outstanding_balance_cents"] == 0
    assert agreement["dues_paid_cents"] == 0
    assert agreement["delinquency_days"] == 0
    assert agreement["transfer_count"] == 0
    assert agreement["cancellation_requested_on"] is None
    assert agreement["net_settlement_cents"] is None
