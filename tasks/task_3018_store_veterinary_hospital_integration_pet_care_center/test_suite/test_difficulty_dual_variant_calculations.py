"""Dual-variant calculations and the pinned nested rounding order.

Every claim here is arithmetic that two plausible readings answer differently:
the credit-then-tax order of a billing cycle, the separation of the frozen
authorization price from the live unit price, and the order in which a
package's monthly total is rounded before the cycle count multiplies it.
"""

import pytest

from test_helpers import (
    EXAM_CHARGE_CENTS,
    advance_cycle,
    check_in,
    complete_exam,
    create_encounter,
    create_prescription,
    dispense_order,
    get_success_data,
    raise_pharmacy_order,
    read_encounter,
    read_member,
    read_prescription,
    setup_member_with_package,
    start_exam,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]


def test_billing_cycle_deducts_overage_credit_before_tax(api):
    """A five-visit PLUS cycle bills 16387.50, not the tax-first 16433.75.

    PRD §3.8: "the grooming visits consumed in the cycle multiplied by 2500
    cents, plus the veterinary visits consumed in the cycle multiplied by 4000
    cents, plus the vaccination visits consumed in the cycle multiplied by 1500
    cents, gives the cycle's pre-tax component."
    PRD §3.8: "The difference is then multiplied by one plus the state sales tax
    rate and rounded half-up to two decimal places, giving the cycle's
    `cycle_total_cents`."
    PRD §3.8: "Under that treatment a cycle consuming two grooming visits and one
    veterinary visit at a tax rate of 0.0925 bills 16433.75 cents, against
    16387.50 cents under the treatment described above. The tax-then-credit order
    is the alternative; the credit-then-tax order is the specification."

    Design: Difficulty/dual_variant_calc/package_cycle_credit_tax_order_dual_variant
    """
    world = setup_member_with_package(
        api, tier="PLUS", state_code="CA", state_sales_tax_rate=0.0925, billing_cycle_count=3
    )
    cycle = advance_cycle(
        api,
        world["store"]["id"],
        world["member"]["id"],
        world["package"],
        grooming_visits_consumed=3,
        vet_visits_consumed=2,
        vaccine_visits_consumed=0,
    )
    # pre-tax 3*2500 + 2*4000 = 15500; the cycle consumed 5 visits against a PLUS
    # allowance of 4, so one overage visit earns a 500-cent credit. The credit is
    # deducted before tax: (15500 - 500) * 1.0925 = 16387.50.
    assert cycle["cycle_total_cents"] == pytest.approx(16387.50, abs=0.01)
    # The tax-first reading would have billed 16433.75 — the same input, a
    # different order.
    assert cycle["cycle_total_cents"] != pytest.approx(16433.75, abs=0.01)
    assert cycle["tax_cents"] == pytest.approx(1387.50, abs=0.01)
    assert cycle["cycle_total_cents"] - cycle["tax_cents"] == pytest.approx(15000.00, abs=0.01)


def test_billing_cycle_records_the_overage_credit_and_the_advance_counters(api):
    """Seven visits against a PLUS allowance of four records a three-visit credit.

    PRD §3.8: "The overage for the cycle is the number of visits consumed in the
    cycle beyond the package's `included_visits_total`, counted only when it
    exceeds that allowance — that is, the excess over the included total for that
    single cycle, or zero when the cycle consumed no more than its allowance."
    PRD §3.8: "Each such overage visit earns a credit of 500 cents, and the total
    credit for the cycle is recorded as the cycle's `overage_credit_cents` and
    deducted from the pre-tax figure."
    PRD §3.8: "Advancing a cycle also increments the package's `cycles_consumed`,
    adds the cycle's consumed visits to the package's `consumed_visits`,
    recomputes the member's `outstanding_balance_cents`, and advances the
    package's version."

    Design: Difficulty/dual_variant_calc/package_cycle_credit_tax_order_dual_variant
    """
    world = setup_member_with_package(
        api, tier="PLUS", state_code="CA", state_sales_tax_rate=0.0, billing_cycle_count=3
    )
    store_id = world["store"]["id"]
    member_id = world["member"]["id"]
    cycle = advance_cycle(
        api, store_id, member_id, world["package"],
        grooming_visits_consumed=5, vet_visits_consumed=2, vaccine_visits_consumed=0,
    )
    # pre-tax 5*2500 + 2*4000 = 20500; three overage visits earn 1500 cents of
    # credit; at a zero tax rate the cycle bills 19000.00.
    assert cycle["overage_credit_cents"] == 1500
    assert cycle["cycle_total_cents"] == pytest.approx(19000.00, abs=0.01)
    assert cycle["tax_cents"] == pytest.approx(0.00, abs=0.01)

    package = get_success_data(api.get_package(world["package"]["id"], ADMIN))
    assert package["consumed_visits"] == 7
    assert package["cycles_consumed"] == 1
    assert package["version"] > world["package"]["version"]
    member = read_member(api, member_id)
    assert member["outstanding_balance_cents"] == pytest.approx(
        float(package["total_price_cents"]) - 19000.00, abs=0.01
    )


def test_complete_exam_charge_uses_the_frozen_price_not_the_live_unit_price(api):
    """The provisional charge is EXAM_CHARGE_CENTS plus the frozen price term.

    PRD §3.4: "The encounter's `charge_total_cents` at the moment of completion
    is the examination charge plus the sum of `price_at_authorization_cents`
    across that encounter's prescriptions whose status is `AUTHORIZED` or
    `PARTIALLY_DISPENSED`."
    PRD §3.4: "The examination charge is a fixed 8500 cents."
    PRD §3.5: "the frozen price is computed as the prescribed unit price
    multiplied by the prescribed quantity."

    Design: Difficulty/dual_variant_calc/dispensing_price_dual_variant_on_encounter_charge
    """
    world = setup_member_with_package(
        api, tier="PLUS", state_code="CA", state_sales_tax_rate=0.0, billing_cycle_count=1
    )
    store_id = world["store"]["id"]
    pet_id = world["pet"]["id"]
    encounter = check_in(api, store_id, create_encounter(api, store_id, pet_id))
    encounter = start_exam(api, store_id, encounter)
    prescription = create_prescription(
        api, store_id, pet_id, encounter["id"],
        item_type="DIET", unit_price_cents=6000, quantity=2,
    )
    encounter = complete_exam(api, store_id, encounter)

    assert encounter["charge_total_cents"] == EXAM_CHARGE_CENTS + 12000
    authorization = read_prescription(api, prescription["id"])
    assert authorization["status"] == "AUTHORIZED"
    assert authorization["price_at_authorization_cents"] == 12000
    # The frozen term and the live term are different fields; the live one is
    # untouched by authorization, so the two readings stay distinguishable.
    assert authorization["unit_price_cents"] == 6000


def test_charge_summary_adds_the_dispensed_term_on_top_of_the_frozen_term(api):
    """A partly dispensed prescription contributes to both terms of the read.

    PRD §3.5: "The charge-summary read computes a finalized total instead, in a
    pinned and non-iterative order: first the frozen authorization term is summed
    over prescriptions whose status is `AUTHORIZED` or `PARTIALLY_DISPENSED`,
    exactly as in the provisional figure, and only then is a dispensed term
    added, over pharmacy orders of the encounter whose status is `DISPENSED`"
    PRD §3.5: "a prescription which was only partly dispensed contributes its
    full frozen price to the first term while the order that partly consumed it
    contributes its own dispensed amount to the second, so the same underlying
    spend is counted twice by design."

    Design: Difficulty/dual_variant_calc/dispensing_price_dual_variant_on_encounter_charge
    """
    world = setup_member_with_package(
        api, tier="PLUS", state_code="CA", state_sales_tax_rate=0.0, billing_cycle_count=1
    )
    store_id = world["store"]["id"]
    pet_id = world["pet"]["id"]
    encounter = check_in(api, store_id, create_encounter(api, store_id, pet_id))
    encounter = start_exam(api, store_id, encounter)
    prescription = create_prescription(
        api, store_id, pet_id, encounter["id"],
        item_type="MEDICATION", unit_price_cents=2000, quantity=4,
    )
    encounter = complete_exam(api, store_id, encounter)

    authorization = read_prescription(api, prescription["id"])
    order = raise_pharmacy_order(api, store_id, authorization, 2)
    dispense_order(api, store_id, order)

    frozen_term = 2000 * 4
    dispensed_term = 2000 * 2
    summary = get_success_data(api.get_charge_summary(store_id, encounter["id"], ADMIN))
    assert summary["exam_charge_cents"] == EXAM_CHARGE_CENTS
    assert summary["finalized_charge_total_cents"] == (
        EXAM_CHARGE_CENTS + frozen_term + dispensed_term
    )
    # The encounter's own stored charge still carries the provisional figure.
    assert read_encounter(api, encounter["id"])["charge_total_cents"] == (
        EXAM_CHARGE_CENTS + frozen_term
    )


def test_plus_package_rounds_the_monthly_total_before_multiplying_by_cycle_count(api):
    """The three-cycle price is the rounded monthly figure multiplied out.

    PRD §3.8: "an `ESSENTIAL` package defaults to 3999 cents per month, a `PLUS`
    package to 6999 and an `UNLIMITED` package to 11999."
    PRD §3.8: "The package's `monthly_total_cents` is its effective monthly fee
    multiplied by one plus the state sales tax rate, rounded half-up to whole
    cents, and its `total_price_cents` is that rounded monthly total multiplied
    by the prepaid cycle count."
    PRD §2.8: "Rounding the monthly total before multiplying by the cycle count
    is load-bearing: rounding the product afterwards produces a different cent
    figure for six-cycle and twelve-cycle packages"

    Design: Difficulty/combinatorial_formula/monthly_membership_rounding_order
    """
    world = setup_member_with_package(
        api, tier="PLUS", state_code="CA", state_sales_tax_rate=0.0925, billing_cycle_count=3
    )
    package = world["package"]
    # 6999 * 1.0925 = 7646.4075, which rounds half-up to 7646.41.
    assert package["monthly_total_cents"] == pytest.approx(7646.41, abs=0.01)
    # That rounded monthly figure is what the cycle count multiplies: 22939.23,
    # where rounding the product afterwards gives 22939.22 — one cent lower.
    assert package["total_price_cents"] == pytest.approx(22939.23, abs=0.01)
    member = read_member(api, world["member"]["id"])
    assert member["outstanding_balance_cents"] == pytest.approx(22939.23, abs=0.01)


def test_unlimited_package_rounds_the_monthly_total_before_multiplying_by_cycle_count(api):
    """The twelve-cycle price is the rounded monthly figure multiplied out.

    PRD §3.8: "its `total_price_cents` is that rounded monthly total multiplied
    by the prepaid cycle count."
    PRD §2.8: "rounding the product afterwards produces a different cent figure
    for six-cycle and twelve-cycle packages"
    PRD §3.8: "a six-cycle or twelve-cycle package's `total_price_cents` is the
    rounded monthly figure multiplied out, not the product rounded afterwards."

    Design: Difficulty/combinatorial_formula/monthly_membership_rounding_order
    """
    world = setup_member_with_package(
        api, tier="UNLIMITED", state_code="FL", state_sales_tax_rate=0.07, billing_cycle_count=12
    )
    package = world["package"]
    # 11999 * 1.07 = 12838.93 exactly, carried at two decimal places.
    assert package["monthly_total_cents"] == pytest.approx(12838.93, abs=0.01)
    # The rounded monthly figure multiplied by twelve, not the rounded product.
    assert package["total_price_cents"] == pytest.approx(154067.16, abs=0.01)
    assert package["billing_cycle_count"] == 12
    member = read_member(api, world["member"]["id"])
    assert member["outstanding_balance_cents"] == pytest.approx(154067.16, abs=0.01)