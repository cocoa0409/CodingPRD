"""The settlement waterfall to the first lien: per-line rounding, the junior-lien
inclusion sets, the mortgage-insurance credit and the relocation tier."""

import pytest

from test_helpers import (
    TEST_USERS,
    assert_net_sheet,
    assert_net_sheet_arithmetic,
    create_case,
    create_lien,
    create_listing,
    create_offer,
    prepare_net_sheet,
    respond_to_lien,
    send_lien_demand,
    set_clock,
    setup_case_with_submitted_offer,
    setup_ready_for_issuance,
    validate_success,
)

NEG = TEST_USERS["negotiator_headers"]


def _line(sheet, line_type):
    return [line for line in sheet["line_items"] if line["line_type"] == line_type][0]


def test_preliminary_sheet_prices_the_full_commission_and_the_demanded_payoff(api):
    """PRD §3.8: "A preliminary sheet charges the controlling listing's full
    `commission_pct` as agreed with the brokerage. A final sheet charges the lesser of
    that agreed rate and the servicer's own cap of `0.055`, so a brokerage that agreed to
    seven percent is priced at five and a half on the auditable sheet. Either way, the
    rate actually used is recorded on the sheet as `commission_pct_applied`."
    PRD §3.8: "A preliminary sheet always carries a `mi_contribution_credit_cents` of 0."

    Design: Difficulty/dual_variant_calc/net_sheet_preliminary_vs_final_diverge_on_same_offer
    """
    scenario = setup_ready_for_issuance(with_valuation=False, net_sheet_variant=None)

    sheet = validate_success(
        api.create_net_sheet(
            scenario["offer"]["id"],
            {
                "variant": "PRELIMINARY",
                "title_escrow_cents": 187_500,
                "property_tax_arrears_cents": 412_300,
                "hoa_arrears_cents": 96_450,
                "expected_offer_version": scenario["offer"]["version"],
            },
            NEG,
        ),
        201,
    )

    assert sheet["commission_pct_applied"] == pytest.approx(0.06)
    assert sheet["gross_deductions_cents"] == 3_250_002
    assert sheet["mi_contribution_credit_cents"] == 0
    assert sheet["base_net_cents"] == 21_250_039
    assert sheet["relocation_incentive_cents"] == 300_000
    assert sheet["net_proceeds_cents"] == 20_950_039
    assert _line(sheet, "JUNIOR_LIEN_PAYOFF")["amount_cents"] == 900_000, (
        "the preliminary junior line prices the demanded payoff"
    )
    assert_net_sheet(sheet)


def test_final_sheet_clamps_the_commission_and_credits_the_carrier(api):
    """PRD §3.8: "On a **final** sheet it is the sum of `approved_contribution_cents`
    across the case's liens whose status is `APPROVED` and no other; every other status
    contributes 0."
    PRD §3.8: "A final sheet carries the carrier's `required_contribution_cents` when the
    case has an MI claim in `APPROVED` status, and 0 in every other situation — no claim
    at all, a pending one, a declined one, or one declared not required."

    Design: Difficulty/dual_variant_calc/net_sheet_preliminary_vs_final_diverge_on_same_offer
    """
    scenario = setup_ready_for_issuance(with_valuation=False, net_sheet_variant=None)
    offer_id = scenario["offer"]["id"]

    preliminary = prepare_net_sheet(offer_id, "PRELIMINARY")
    final = prepare_net_sheet(offer_id, "FINAL")

    assert final["commission_pct_applied"] == pytest.approx(0.055)
    assert final["gross_deductions_cents"] == 2_827_502
    assert final["mi_contribution_credit_cents"] == 750_000
    assert final["base_net_cents"] == 22_422_539
    assert final["net_proceeds_cents"] == 22_122_539
    assert _line(final, "JUNIOR_LIEN_PAYOFF")["amount_cents"] == 600_000, (
        "the final junior line prices the approved contribution"
    )
    assert final["net_proceeds_cents"] - preliminary["net_proceeds_cents"] == 1_172_500

    offer_after = validate_success(api.get_offer(offer_id, NEG), 200)
    assert offer_after["offer_price_cents"] == 24_500_041, (
        "neither sheet rewrites the contract price"
    )
    assert_net_sheet(final)


def test_each_deduction_line_is_rounded_on_its_own(api):
    """PRD §3.8: "Line 1 is `COMMISSION`, on a `PCT_OF_PRICE` basis at the applied
    commission rate: the offer's price multiplied by that rate, rounded half up to whole
    cents."
    PRD §3.8: "`gross_deductions_cents` is then the sum of those six **already-rounded**
    line amounts. Summing the raw products and rounding once at the end is wrong and will
    produce a different total."

    Design: Difficulty/combinatorial_formula/net_sheet_per_line_rounding_order_pinned
    """
    set_clock("2026-08-05T00:00:00Z")
    case = create_case(property_address="7 Vireo Way, Reno NV")
    create_listing(case["id"])
    offer = create_offer(case["id"], buyer_name="P. Nakamura")

    sheet = prepare_net_sheet(offer["id"], "PRELIMINARY")

    # 24_500_041 * 0.06 == 1_470_002.46 and 24_500_041 * 0.0075 == 183_750.3075.
    assert _line(sheet, "COMMISSION")["amount_cents"] == 1_470_002
    assert _line(sheet, "TRANSFER_TAX")["amount_cents"] == 183_750
    assert _line(sheet, "JUNIOR_LIEN_PAYOFF")["amount_cents"] == 0
    assert sheet["gross_deductions_cents"] == 2_350_002
    assert sheet["gross_deductions_cents"] != 2_350_003, (
        "summing the raw products and rounding once at the end is wrong"
    )


def test_line_order_and_totals_reconcile_on_the_settlement_sheet(api):
    """PRD §3.8: "Each entry in `line_items` records its `line_type`, its `basis`, the
    `rate_or_amount` it was computed from, and its own `amount_cents`."
    PRD §3.8: "First compute `base_net_cents`: the offer's price, less
    `gross_deductions_cents`, plus `mi_contribution_credit_cents`."

    Design: Difficulty/combinatorial_formula/net_sheet_per_line_rounding_order_pinned
    """
    set_clock("2026-08-05T00:00:00Z")
    case = create_case(property_address="7 Vireo Way, Reno NV")
    create_listing(case["id"])
    offer = create_offer(case["id"], buyer_name="P. Nakamura")

    sheet = prepare_net_sheet(offer["id"], "PRELIMINARY")

    assert [line["line_type"] for line in sheet["line_items"]] == [
        "COMMISSION",
        "TITLE_AND_ESCROW",
        "TRANSFER_TAX",
        "PROPERTY_TAX_ARREARS",
        "HOA_ARREARS",
        "JUNIOR_LIEN_PAYOFF",
    ]
    assert sheet["base_net_cents"] == 22_150_039
    assert sheet["net_proceeds_cents"] == 21_850_039
    assert_net_sheet_arithmetic(sheet)
    assert_net_sheet(sheet)


def test_relocation_tier_is_keyed_on_the_pre_incentive_base_net(api):
    """PRD §3.8: "First compute `base_net_cents`: the offer's price, less
    `gross_deductions_cents`, plus `mi_contribution_credit_cents`. Select the incentive
    tier from **that** figure, before any incentive has been deducted. A `base_net_cents`
    of at least 20,000,000 cents — two hundred thousand dollars — earns
    `relocation_incentive_cents` of 300,000 cents, three thousand dollars."
    PRD §3.8: "Finally, `net_proceeds_cents` is `base_net_cents` less
    `relocation_incentive_cents`. Selecting the tier from the post-deduction figure is
    wrong."

    Design: Difficulty/combinatorial_formula/relocation_incentive_tier_keyed_on_pre_incentive_base_net
    """
    set_clock("2026-08-05T00:00:00Z")
    case = create_case(property_address="9 Ptarmigan Dr, Reno NV")
    create_listing(case["id"])
    offer = create_offer(case["id"], buyer_name="D. Okoro")

    sheet = prepare_net_sheet(
        offer["id"], "PRELIMINARY",
        property_tax_arrears_cents=1_558_789,
        hoa_arrears_cents=1_000_000,
    )

    assert sheet["gross_deductions_cents"] == 4_400_041
    assert sheet["base_net_cents"] == 20_100_000
    assert sheet["relocation_incentive_cents"] == 300_000
    assert sheet["net_proceeds_cents"] == 19_800_000
    assert sheet["net_proceeds_cents"] != 19_900_000, (
        "keying the tier on the post-deduction figure is rejected"
    )


def test_the_tier_survives_the_net_falling_below_its_own_threshold(api):
    """PRD §3.8: "Select the incentive tier from **that** figure, before any incentive has
    been deducted."
    PRD §3.8: "Finally, `net_proceeds_cents` is `base_net_cents` less
    `relocation_incentive_cents`. Selecting the tier from the post-deduction figure is
    wrong."

    Design: Difficulty/combinatorial_formula/relocation_incentive_tier_keyed_on_pre_incentive_base_net
    """
    set_clock("2026-08-05T00:00:00Z")
    case = create_case(property_address="9 Ptarmigan Dr, Reno NV")
    create_listing(case["id"])
    offer = create_offer(case["id"], buyer_name="D. Okoro")

    sheet = prepare_net_sheet(
        offer["id"], "PRELIMINARY",
        property_tax_arrears_cents=1_558_789,
        hoa_arrears_cents=1_000_000,
    )

    assert sheet["base_net_cents"] >= 20_000_000, "the tier key clears the high threshold"
    assert sheet["net_proceeds_cents"] < 20_000_000, (
        "the resulting net falls back below the threshold the tier was chosen on"
    )
    assert sheet["relocation_incentive_cents"] == 300_000
    assert_net_sheet_arithmetic(sheet)


def test_mid_tier_applies_one_cent_below_the_high_threshold(api):
    """PRD §3.8: "Otherwise, a `base_net_cents` of at least 10,000,000 cents earns 200,000
    cents."
    PRD §3.8: "A `base_net_cents` of at least 20,000,000 cents — two hundred thousand
    dollars — earns `relocation_incentive_cents` of 300,000 cents, three thousand
    dollars."

    Design: Corner/calculations/relocation_tier_mid_applied_one_cent_below_high_threshold
    """
    set_clock("2026-08-05T00:00:00Z")
    case = create_case()
    create_listing(case["id"])
    offer = create_offer(case["id"])

    sheet = prepare_net_sheet(
        offer["id"], "PRELIMINARY",
        property_tax_arrears_cents=1_658_790,
        hoa_arrears_cents=1_000_000,
    )

    assert sheet["gross_deductions_cents"] == 4_500_042
    assert sheet["base_net_cents"] == 19_999_999
    assert sheet["relocation_incentive_cents"] == 200_000
    assert sheet["net_proceeds_cents"] == 19_799_999


def test_preliminary_junior_line_includes_demand_sent_and_excludes_refused(api):
    """PRD §3.8: "On a **preliminary** sheet it is the sum of `demand_cents` across the
    case's liens whose status is `DEMAND_SENT`, `NEGOTIATING` or `APPROVED` — a lien
    still merely `IDENTIFIED` has no demand yet and is excluded, a `REFUSED` lien is
    excluded, and a lien in an included status whose `demand_cents` is still null
    contributes 0."

    Design: Corner/calculations/preliminary_net_sheet_includes_demand_sent_lien_and_excludes_refused
    """
    set_clock("2026-08-05T00:00:00Z")
    case = create_case()
    create_listing(case["id"])
    demanded = create_lien(case["id"])
    send_lien_demand(demanded["id"], 900_000)
    refused = create_lien(case["id"], lien_position=3, balance_cents=1_200_000)
    send_lien_demand(refused["id"], 400_000)
    respond_to_lien(refused["id"], "REFUSE")
    offer = create_offer(case["id"])

    sheet = prepare_net_sheet(offer["id"], "PRELIMINARY")

    junior_line = _line(sheet, "JUNIOR_LIEN_PAYOFF")
    assert junior_line["amount_cents"] == 900_000, (
        "the refused lien's 400_000 demand must not be summed"
    )
    assert sheet["gross_deductions_cents"] == 3_250_002
    assert sheet["base_net_cents"] == 21_250_039
    assert sheet["net_proceeds_cents"] == 20_950_039

    liens = validate_success(api.list_case_junior_liens(case["id"], NEG), 200)
    refused_after = [lien for lien in liens if lien["lien_position"] == 3][0]
    assert refused_after["status"] == "REFUSED"
    assert refused_after["approved_contribution_cents"] == 0


def test_offer_net_sheets_can_be_filtered_by_variant(api):
    """PRD §2.3: "Net sheets on an offer may be filtered by `variant` and by `status`."
    PRD §3.8: "Preparation stamps `prepared_by_user_id`, births the sheet in `CURRENT`,
    demotes any prior sheet on that offer **of the same variant** that was `CURRENT` to
    `SUPERSEDED` — sheets of the other variant are untouched — and increments the parent
    offer's `version`."

    Design: Corner/endpoints/net_sheets_reverse_lookup_filtered_by_variant
    """
    scenario = setup_case_with_submitted_offer()
    offer_id = scenario["offer"]["id"]
    preliminary = prepare_net_sheet(offer_id, "PRELIMINARY")
    final = prepare_net_sheet(offer_id, "FINAL")

    response = api.list_offer_net_sheets(offer_id, NEG, params={"variant": "FINAL"})
    filtered = validate_success(response, 200)

    assert response.json()["response_type"] == "array"
    assert len(filtered) == 1
    assert filtered[0]["id"] == final["id"]

    unfiltered = validate_success(api.list_offer_net_sheets(offer_id, NEG), 200)
    assert len(unfiltered) == 2

    by_id = {sheet["id"]: sheet for sheet in unfiltered}
    assert by_id[preliminary["id"]]["status"] == "CURRENT"
    assert by_id[final["id"]]["status"] == "CURRENT", (
        "sheets of the other variant are untouched by a new preparation"
    )
