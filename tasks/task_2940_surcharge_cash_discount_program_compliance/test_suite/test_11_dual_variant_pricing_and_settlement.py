"""Pricing arms, the effective cap fork, and the settlement rounding order."""
import pytest

from test_helpers import (
    ApiErrorId,
    activate_program,
    api_client,
    capture_sale,
    create_jurisdiction,
    create_merchant,
    create_program,
    decide_registration,
    effectuate_registration,
    file_cost_documentation,
    file_rate_rule,
    get_success_data,
    read_merchant,
    read_program,
    set_clock,
    setup_enforcing_surcharge_estate,
    setup_enforcing_terminal,
    submit_registration,
    validate_error,
    list_total,
    validate_success,
)
from test_helpers.constants import CLOCK_AUG_01, CLOCK_AUG_31, CLOCK_DEC_31
from test_helpers.fixtures import ADMIN, OFFICER_ONE


def _setup_texas_twin_programs():
    """One TX merchant on one cost document operating two ACTIVE programs — a
    SURCHARGE program and a CASH_DISCOUNT program — each with a VISA/ALL rate
    rule at 2.0 percent and one ENFORCING terminal."""
    set_clock(CLOCK_AUG_01)
    jurisdiction = create_jurisdiction("TX")
    merchant = create_merchant(jurisdiction["id"], legal_name="Lone Star Goods LLC", mcc="5999")
    documentation = file_cost_documentation(merchant["id"], merchant["version"], "docA")

    surcharge_program = create_program(
        merchant["id"], jurisdiction["id"], documentation["id"], "SURCHARGE", "BRAND_LEVEL"
    )
    file_rate_rule(
        surcharge_program["id"],
        surcharge_program["version"],
        rate_pct=2.0,
        effective_from=CLOCK_AUG_01,
        effective_to=CLOCK_DEC_31,
    )
    registration = submit_registration(surcharge_program["id"], "VISA", "VS-2940-TX-001")
    decide_registration(registration["id"], "ACKNOWLEDGE")

    cash_program = create_program(
        merchant["id"], jurisdiction["id"], documentation["id"], "CASH_DISCOUNT", "BRAND_LEVEL"
    )
    file_rate_rule(
        cash_program["id"],
        cash_program["version"],
        rate_pct=2.0,
        effective_from=CLOCK_AUG_01,
        effective_to=CLOCK_DEC_31,
    )
    cash_program = activate_program(cash_program["id"])

    set_clock(CLOCK_AUG_31)
    effectuate_registration(registration["id"])
    surcharge_program = activate_program(surcharge_program["id"])

    surcharge_terminal = setup_enforcing_terminal(
        merchant["id"], surcharge_program["id"], "T-S-001"
    )
    cash_terminal = setup_enforcing_terminal(merchant["id"], cash_program["id"], "T-C-001")
    return {
        "jurisdiction": jurisdiction,
        "merchant": merchant,
        "cost_documentation": documentation,
        "surcharge_program": surcharge_program,
        "cash_program": cash_program,
        "surcharge_terminal": surcharge_terminal,
        "cash_terminal": cash_terminal,
    }


def test_surcharge_program_adds_the_fee_while_cash_discount_deducts_it(api):
    """PRD §3.9: "On a `SURCHARGE` program with `card_funding` of `CREDIT`: `surcharge_amount_cents` is `base_amount_cents` multiplied by the applied rate, divided by 100, rounded half up to a whole cent; `cash_discount_amount_cents` is 0; `cash_price_cents` equals `base_amount_cents`; `total_amount_cents` is `base_amount_cents` plus `surcharge_amount_cents`; and `outcome` is `APPROVED_WITH_SURCHARGE`."
    PRD §3.9: "On a `CASH_DISCOUNT` program, whatever the funding: `surcharge_amount_cents` is 0; `cash_discount_amount_cents` is `base_amount_cents` multiplied by the applied rate, divided by 100, rounded half up to a whole cent; `cash_price_cents` is `base_amount_cents` minus `cash_discount_amount_cents`; `total_amount_cents` equals `base_amount_cents`, because under a cash-discount structure the card price *is* the posted price; and `outcome` is `APPROVED_CASH_DISCOUNT`."

    Design: Difficulty/dual_variant_calc/price_resolution_surcharge_addon_vs_cash_discount_deduct
    """
    ctx = _setup_texas_twin_programs()

    surcharge_sale = capture_sale(
        ctx["surcharge_terminal"]["id"],
        ctx["surcharge_program"]["id"],
        base_amount_cents=10000,
        requested_surcharge_cents=200,
        receipt_line_present=True,
    )
    cash_sale = capture_sale(
        ctx["cash_terminal"]["id"],
        ctx["cash_program"]["id"],
        base_amount_cents=10000,
        requested_surcharge_cents=0,
        receipt_line_present=False,
    )

    assert surcharge_sale["applied_rate_pct"] == pytest.approx(2.0, abs=0.0001)
    assert surcharge_sale["surcharge_amount_cents"] == 200
    assert surcharge_sale["cash_discount_amount_cents"] == 0
    assert surcharge_sale["cash_price_cents"] == 10000
    assert surcharge_sale["total_amount_cents"] == 10200
    assert surcharge_sale["outcome"] == "APPROVED_WITH_SURCHARGE"

    assert cash_sale["applied_rate_pct"] == pytest.approx(2.0, abs=0.0001)
    assert cash_sale["surcharge_amount_cents"] == 0
    assert cash_sale["cash_discount_amount_cents"] == 200
    assert cash_sale["cash_price_cents"] == 9800
    assert cash_sale["total_amount_cents"] == 10000
    assert cash_sale["outcome"] == "APPROVED_CASH_DISCOUNT"

    assert (
        surcharge_sale["total_amount_cents"] - cash_sale["total_amount_cents"] == 200
    ), "the two structures must diverge by exactly the priced amount on identical inputs"


def test_only_the_surcharge_arm_moves_the_merchant_surcharge_ledger(api):
    """PRD §3.9: "The merchant's `gross_surcharge_collected_cents` is the sum of `surcharge_amount_cents` over every sale captured by that merchant's terminals whose `outcome` is `APPROVED_WITH_SURCHARGE`, taken over all time with no window; it increases by this sale's surcharge and never decreases for any reason."
    PRD §3.3: "For a `CASH_DISCOUNT` program the cap is simply the cash-discount ceiling of 10.0 percent. For a `SURCHARGE` program it is the smallest of three numbers: the frozen `documented_cost_pct` of the pinned cost documentation, the jurisdiction's statutory `surcharge_cap_pct`, and the network ceiling of 3.0 percent."

    Design: Difficulty/dual_variant_calc/price_resolution_surcharge_addon_vs_cash_discount_deduct
    """
    ctx = _setup_texas_twin_programs()

    surcharge_program = read_program(ctx["surcharge_program"]["id"])
    cash_program = read_program(ctx["cash_program"]["id"])
    assert surcharge_program["effective_cap_pct"] == pytest.approx(2.0, abs=0.0001), (
        "the Texas statutory cap of 2.0 is the smallest of the three surcharge inputs"
    )
    assert cash_program["effective_cap_pct"] == pytest.approx(10.0, abs=0.0001)

    capture_sale(
        ctx["surcharge_terminal"]["id"],
        ctx["surcharge_program"]["id"],
        base_amount_cents=10000,
        requested_surcharge_cents=200,
        receipt_line_present=True,
    )
    capture_sale(
        ctx["cash_terminal"]["id"],
        ctx["cash_program"]["id"],
        base_amount_cents=10000,
        requested_surcharge_cents=0,
        receipt_line_present=False,
    )

    merchant = read_merchant(ctx["merchant"]["id"])
    assert merchant["gross_surcharge_collected_cents"] == 200, (
        "only the APPROVED_WITH_SURCHARGE sale contributes to the gross figure"
    )
    assert merchant["net_surcharge_collected_cents"] == 200


def _three_sales_at_two_point_one_nine():
    """An ACTIVE AZ surcharge program at 2.19 percent with one ENFORCING terminal
    that has captured sales of 1234, 5678 and 9012 cents."""
    ctx = setup_enforcing_surcharge_estate(rate_pct=2.19)
    ctx["sales"] = [
        capture_sale(
            ctx["terminal"]["id"],
            ctx["program"]["id"],
            base_amount_cents=base,
            requested_surcharge_cents=requested,
        )
        for base, requested in ((1234, 27), (5678, 124), (9012, 197))
    ]
    return ctx


def test_settlement_settles_the_per_line_total_not_the_pooled_reference(api):
    """PRD §3.11: "That last figure is the settled number, and the rounding order behind it is pinned: each line was rounded to the cent when it was captured, and the lines are then summed — the summary never re-rounds and never pools first."
    PRD §3.11: "Consider three surcharged sales of 1234, 5678, and 9012 cents all priced at 2.19 percent: the per-line surcharges are 27, 124, and 197, summing to 348, whereas pooling the bases to 15924 and applying the rate once gives 349."

    Design: Difficulty/combinatorial_formula/settlement_rounding_order_per_line_then_sum_vs_pooled
    """
    ctx = _three_sales_at_two_point_one_nine()
    assert [sale["surcharge_amount_cents"] for sale in ctx["sales"]] == [27, 124, 197]

    summary = get_success_data(
        api_client.get_settlement_summary(ctx["program"]["id"], OFFICER_ONE)
    )
    assert summary["program_id"] == ctx["program"]["id"]
    assert summary["transaction_count"] == 3
    assert summary["base_amount_total_cents"] == 15924
    assert summary["per_line_rounded_surcharge_cents"] == 348
    assert summary["pooled_rounding_reference_cents"] == 349
    assert summary["refunded_surcharge_cents"] == 0
    assert summary["net_surcharge_cents"] == 348

    merchant = read_merchant(ctx["merchant"]["id"])
    assert merchant["gross_surcharge_collected_cents"] == 348, (
        "the merchant ledger carries the per-line total, never the pooled figure"
    )


def test_rounding_divergence_is_the_per_line_total_less_the_pooled_reference(api):
    """PRD §3.11: "`rounding_divergence_cents` is then `per_line_rounded_surcharge_cents` minus `pooled_rounding_reference_cents`."
    PRD §3.11: "The settled figure is 348 and `rounding_divergence_cents` is -1."

    Design: Difficulty/combinatorial_formula/settlement_rounding_order_per_line_then_sum_vs_pooled
    """
    ctx = _three_sales_at_two_point_one_nine()

    summary = get_success_data(
        api_client.get_settlement_summary(ctx["program"]["id"], OFFICER_ONE)
    )
    assert summary["rounding_divergence_cents"] == -1
    assert (
        summary["rounding_divergence_cents"]
        == summary["per_line_rounded_surcharge_cents"]
        - summary["pooled_rounding_reference_cents"]
    )


def test_second_cost_document_freezes_the_realised_average_ticket_and_lowers_the_cap(api):
    """PRD §3.2: "It then takes the arithmetic mean of those sales' `base_amount_cents`, rounds it half up to a whole number of cents, and stores the result as `average_ticket_cents` on the new document."
    PRD §3.2: "The per-item component is `per_item_fee_cents` divided by `average_ticket_cents`, multiplied by 100, and rounded half up to four decimal places."
    PRD §3.2: "`documented_cost_pct` is then `base_mdr_pct` plus `assessment_pct` plus that per-item component, with the sum rounded half up to four decimal places."

    Design: Difficulty/combinatorial_formula/average_ticket_cost_cap_pinned_four_step_chain
    """
    ctx = _three_sales_at_two_point_one_nine()
    first_document = ctx["cost_documentation"]
    assert first_document["average_ticket_cents"] == 5000, (
        "the first document was filed before any sale existed, so it took the fallback"
    )
    assert first_document["documented_cost_pct"] == pytest.approx(2.19, abs=0.0001)

    # A DRAFT sibling program on the same merchant, pinned to the first document
    # while it is still ACTIVE. PRD §3.3 permits the re-pinning partial update only
    # while a program's status is DRAFT or PENDING_REGISTRATION, so the re-pin is
    # exercised here rather than on the ACTIVE program that captured the sales.
    sibling = create_program(
        ctx["merchant"]["id"],
        ctx["jurisdiction"]["id"],
        first_document["id"],
        "SURCHARGE",
        "BRAND_LEVEL",
    )
    assert sibling["status"] == "DRAFT"
    assert sibling["effective_cap_pct"] == pytest.approx(2.19, abs=0.0001)

    merchant = read_merchant(ctx["merchant"]["id"])
    second_document = file_cost_documentation(
        ctx["merchant"]["id"], merchant["version"], "docA"
    )
    assert second_document["average_ticket_cents"] == 5308, (
        "15924 cents over three sales averages to 5308 cents"
    )
    assert second_document["documented_cost_pct"] == pytest.approx(2.1784, abs=0.00001)
    assert second_document["state"] == "ACTIVE"

    superseded = get_success_data(
        api_client.get_cost_documentation(first_document["id"], OFFICER_ONE)
    )
    assert superseded["state"] == "SUPERSEDED"
    assert superseded["average_ticket_cents"] == 5000, (
        "a frozen document is never recomputed by a later filing"
    )
    assert superseded["documented_cost_pct"] == pytest.approx(2.19, abs=0.0001)

    merchant = read_merchant(ctx["merchant"]["id"])
    assert merchant["active_cost_documentation_id"] == second_document["id"]

    repinned = validate_success(
        api_client.patch_program(
            sibling["id"],
            {
                "cost_documentation_id": second_document["id"],
                "expected_program_version": read_program(sibling["id"])["version"],
            },
            OFFICER_ONE,
        )
    )
    assert repinned["cost_documentation_id"] == second_document["id"]
    assert repinned["effective_cap_pct"] == pytest.approx(2.1784, abs=0.00001)


def test_rate_rule_at_the_superseded_cost_is_rejected_once_the_program_repins(api):
    """PRD §3.4: "A `rate_pct` at most `effective_cap_pct` is admitted, with equality passing; a `rate_pct` strictly greater than `effective_cap_pct` is rejected with `ERR_SURCHARGE_CAP_EXCEEDED`."
    PRD §3.2: "A sale captured tomorrow does not retroactively change a document filed today; only a *new* document, filed later, picks up the newer average ticket."

    Design: Difficulty/combinatorial_formula/average_ticket_cost_cap_pinned_four_step_chain
    """
    ctx = _three_sales_at_two_point_one_nine()

    # A DRAFT sibling program on the same merchant carrying one VISA rate rule at
    # 2.19, which the first document's cap of 2.19 admits with equality. PRD §3.3
    # permits the re-pinning partial update only from DRAFT or PENDING_REGISTRATION.
    program = create_program(
        ctx["merchant"]["id"],
        ctx["jurisdiction"]["id"],
        ctx["cost_documentation"]["id"],
        "SURCHARGE",
        "BRAND_LEVEL",
    )
    filed_rule = file_rate_rule(
        program["id"],
        program["version"],
        brand="VISA",
        product_tier="ALL",
        rate_pct=2.19,
        effective_from=CLOCK_AUG_01,
        effective_to=CLOCK_DEC_31,
    )

    merchant = read_merchant(ctx["merchant"]["id"])
    second_document = file_cost_documentation(
        ctx["merchant"]["id"], merchant["version"], "docA"
    )
    program = validate_success(
        api_client.patch_program(
            program["id"],
            {
                "cost_documentation_id": second_document["id"],
                "expected_program_version": read_program(program["id"])["version"],
            },
            OFFICER_ONE,
        )
    )
    assert program["effective_cap_pct"] == pytest.approx(2.1784, abs=0.00001)

    already_filed = get_success_data(
        api_client.get_rate_rule(filed_rule["id"], OFFICER_ONE)
    )
    assert already_filed["rate_pct"] == pytest.approx(2.19, abs=0.0001), (
        "lowering the cap does not reach back into rules that were already filed"
    )

    response = api_client.create_rate_rule(
        program["id"],
        {
            "brand": "MASTERCARD",
            "product_tier": "ALL",
            "rate_pct": 2.19,
            "effective_from": "2027-06-01T00:00:00Z",
            "effective_to": "2027-12-31T00:00:00Z",
            "expected_program_version": program["version"],
        },
        OFFICER_ONE,
    )
    validate_error(response, ApiErrorId.ERR_SURCHARGE_CAP_EXCEEDED)

    assert (
        list_total(
            api_client.list_rate_rules(OFFICER_ONE, params={"program_id": program["id"]})
        )
        == 1
    ), "the rejected filing left no row behind"
