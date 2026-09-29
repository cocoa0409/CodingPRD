"""Dual-view valuation and exposure figures, plus the pinned-order money formulas.

Every test builds its own world from the declared endpoints only: the logical
clock is pinned first, the reference data and the engagement chain follow, and the
asserted figures are the literals the PRD's own prose derives.
"""

from test_helpers import (
    CLOCK_DEFAULT,
    COMP_FEES_DE,
    LENDER_APPROVER,
    LENDER_DRAWER,
    assert_account_counters,
    assert_allocations,
    assert_buyer_exposure,
    assert_contract_axes,
    assert_created,
    assert_facility_figures,
    assert_film_counters,
    assert_instant,
    assert_money,
    assert_money_precision,
    assert_tier,
    assert_valuation_prices,
    approve_facility,
    bond_facility,
    buyer_amendment_payload,
    distribute_payload,
    draw_facility,
    executed_contract,
    executed_contract_environment,
    expense_payload,
    facility_payload,
    find_by,
    get_success_data,
    make_collection_agent_headers,
    make_comparables,
    make_facility,
    make_film,
    make_lender_headers,
    make_platform_admin_headers,
    make_sales_agent_headers,
    make_territory,
    make_tiers,
    milestone_by_label,
    pin_clock,
    post_receipt,
    read_account,
    read_agreement,
    read_buyer,
    read_contract,
    read_facility,
    read_film,
    read_milestones,
    read_tiers,
    read_valuation,
    valuation_payload,
)

# --------------------------------------------------------------------------
# Private builders.  These live in this module rather than in the shared helper
# package because they encode setups specific to the rules asserted below.
# --------------------------------------------------------------------------

# The three verified in-genre comparables of the canonical territory, each
# released inside the seven-year lookback from the pinned clock reading.
_COMP_YEARS = (2022, 2023, 2021)

# The receipt sequence whose arrival order decides which commission band each
# receipt lands in: 900000.00, then 400000.00, then 200000.00.
_RECEIPT_SEQUENCE = (
    ("ON_SIGNATURE", "2026-08-05T00:00:00Z"),
    ("ON_DELIVERY", "2026-08-06T00:00:00Z"),
    ("ON_RELEASE", "2026-08-07T00:00:00Z"),
)

# Six tiers in cascade order; the last one is the single uncapped tier.
_TIER_SPECS = (
    (1, "COLLECTION_FEE", 0.0125, 25000.00),
    (2, "SALES_COMMISSION", 1.00, 145000.00),
    (3, "SALES_EXPENSES", 1.00, 75000.00),
    (4, "BANK_DEBT", 0.85, 1000000.00),
    (5, "EQUITY_RECOUPMENT", 0.60, 12000000.00),
    (6, "PARTICIPATION", 1.00, None),
)


def _both_method_valuations(api):
    """One picture, one territory, three verified comparables, and one valuation
    per method on that identical comparable data."""
    pin_clock(api, CLOCK_DEFAULT)
    film = make_film(api)
    territory = make_territory(api)
    comparables = make_comparables(api, territory["id"], COMP_FEES_DE, _COMP_YEARS)
    weighted = assert_created(
        api.create_valuation(
            valuation_payload(film["id"], territory["id"], "COMPARABLE_WEIGHTED"),
            make_sales_agent_headers(),
        )
    )
    cast_adjusted = assert_created(
        api.create_valuation(
            valuation_payload(film["id"], territory["id"], "CAST_ADJUSTED"),
            make_sales_agent_headers(),
        )
    )
    return {
        "film": film,
        "territory": territory,
        "comparables": comparables,
        "weighted": weighted,
        "cast_adjusted": cast_adjusted,
    }


def _post_receipt_sequence(api, env, sequence=_RECEIPT_SEQUENCE):
    """Book each milestone's own amount, in the given arrival order."""
    posted = []
    for label, received_at in sequence:
        milestone = milestone_by_label(read_milestones(api, env["contract"]["id"]), label)
        posted.append(post_receipt(api, milestone, received_at))
    env["receipts"] = posted
    return posted


def _collected_environment(api, sequence=_RECEIPT_SEQUENCE):
    """The canonical executed contract with an OPEN account and the receipt
    sequence already booked."""
    env = executed_contract_environment(api)
    _post_receipt_sequence(api, env, sequence)
    return env


def _waterfall_environment(api):
    """A drawn facility, an overspent expense log, three booked receipts and the
    six-tier waterfall, all on the canonical executed contract."""
    env = executed_contract_environment(api)
    facility = make_facility(api, env["film"]["id"])
    approve_facility(api, facility["id"], LENDER_APPROVER)
    bond_facility(api, facility["id"])
    env["facility"] = draw_facility(api, facility["id"], LENDER_DRAWER)
    get_success_data(
        api.log_expense(
            env["agreement"]["id"],
            expense_payload(90000.00, memo="AFM market costs"),
            make_sales_agent_headers(),
        )
    )
    _post_receipt_sequence(api, env)
    env["tiers"] = make_tiers(api, env["account"]["id"], _TIER_SPECS)
    return env


def _tier_of_type(api, account_id, tier_type):
    return find_by(read_tiers(api, account_id), tier_type=tier_type)


# ==========================================================================
# Territory pricing: the two valuation methods on byte-identical comparables
# ==========================================================================
class TestTerritoryValuationMethodVariants:
    def test_comparable_weighted_forces_the_cast_multiplier_to_one(self, api):
        """COMPARABLE_WEIGHTED ignores the cast score entirely and prices off the median alone.

        PRD: "Under `COMPARABLE_WEIGHTED` — the pure market view the agency uses to argue a territory's floor to financiers — `cast_multiplier` is forced to exactly 1.00, the film's `principal_cast_score` is ignored entirely, and `estimate_usd` is the comparable median multiplied by the territory's `base_value_index`, rounded half-up to two decimal places."

        Design: Difficulty/dual_variant_calc/territory_value_estimate_diverges_between_comparable_weighted_and_cast_adjusted
        """
        env = _both_method_valuations(api)
        weighted = env["weighted"]

        assert weighted["method"] == "COMPARABLE_WEIGHTED", (
            f"expected method COMPARABLE_WEIGHTED, got {weighted['method']!r}"
        )
        assert weighted["comp_sample_size"] == 3, (
            f"expected comp_sample_size 3, got {weighted['comp_sample_size']}"
        )
        assert_money(weighted["comp_median_usd"], 1000000.00, "comp_median_usd")
        assert_money(weighted["cast_multiplier"], 1.00, "cast_multiplier")
        assert_money(weighted["estimate_usd"], 1200000.00, "estimate_usd")

        # The frozen row reads the same on a later fetch.
        stored = read_valuation(api, weighted["id"])
        assert_money(stored["estimate_usd"], 1200000.00, "estimate_usd")
        assert_money(stored["cast_multiplier"], 1.00, "cast_multiplier")

    def test_comparable_weighted_ask_and_floor_derive_from_its_own_estimate(self, api):
        """The ask premium and the floor discount are applied to the 1200000.00 market estimate.

        PRD: "`floor_price_usd` is the estimate multiplied by a floor discount of 0.70, rounded half-up to two decimal places — the minimum guarantee floor that will be enforced when a contract for this territory is countersigned."

        Design: Difficulty/dual_variant_calc/territory_value_estimate_diverges_between_comparable_weighted_and_cast_adjusted
        """
        env = _both_method_valuations(api)

        assert_valuation_prices(env["weighted"], 1200000.00, 1500000.00, 840000.00)
        assert env["weighted"]["status"] == "DRAFT", (
            f"a new valuation is DRAFT, got {env['weighted']['status']!r}"
        )
        assert env["weighted"]["published_by_user_id"] is None, (
            "a new valuation carries no published_by_user_id"
        )
        assert env["weighted"]["published_at"] is None, (
            "a new valuation carries no published_at"
        )

    def test_cast_adjusted_applies_the_top_cast_tier_multiplier(self, api):
        """A principal_cast_score of 88 lands in the 85-and-above band, so the multiplier is 1.40.

        PRD: "The **cast tier multiplier** is a step function of the film's `principal_cast_score`, with each band inclusive on its lower bound: a score of 85 or above yields 1.40; a score from 70 up to but not including 85 yields 1.20; a score from 50 up to but not including 70 yields 1.00; and a score below 50 yields 0.80."

        Design: Difficulty/dual_variant_calc/territory_value_estimate_diverges_between_comparable_weighted_and_cast_adjusted
        """
        env = _both_method_valuations(api)
        cast_adjusted = env["cast_adjusted"]

        assert env["film"]["principal_cast_score"] == 88, (
            "the picture carries the cast score the top band needs"
        )
        assert cast_adjusted["method"] == "CAST_ADJUSTED", (
            f"expected method CAST_ADJUSTED, got {cast_adjusted['method']!r}"
        )
        assert cast_adjusted["comp_sample_size"] == 3, (
            f"expected comp_sample_size 3, got {cast_adjusted['comp_sample_size']}"
        )
        assert_money(cast_adjusted["comp_median_usd"], 1000000.00, "comp_median_usd")
        assert_money(cast_adjusted["cast_multiplier"], 1.40, "cast_multiplier")
        assert_money(cast_adjusted["estimate_usd"], 1680000.00, "estimate_usd")

    def test_cast_adjusted_ask_and_floor_derive_from_the_lifted_estimate(self, api):
        """The packaging view prices its ask at 2100000.00 and its floor at 1176000.00.

        PRD: "`ask_price_usd` is the estimate multiplied by an ask premium of 1.25, rounded half-up to two decimal places — the opening number the sales agent carries into negotiation."

        Design: Difficulty/dual_variant_calc/territory_value_estimate_diverges_between_comparable_weighted_and_cast_adjusted
        """
        env = _both_method_valuations(api)

        assert_valuation_prices(env["cast_adjusted"], 1680000.00, 2100000.00, 1176000.00)
        assert env["cast_adjusted"]["status"] == "DRAFT", (
            f"a new valuation is DRAFT, got {env['cast_adjusted']['status']!r}"
        )

    def test_the_two_methods_diverge_by_exactly_the_top_cast_tier_factor(self, api):
        """On the same three comparables the two estimates differ by exactly 480000.00.

        PRD: "On identical comparables and a `principal_cast_score` of 85 or more, the `CAST_ADJUSTED` estimate is exactly 1.40 times the `COMPARABLE_WEIGHTED` estimate."

        Design: Difficulty/dual_variant_calc/territory_value_estimate_diverges_between_comparable_weighted_and_cast_adjusted
        """
        env = _both_method_valuations(api)
        weighted = read_valuation(api, env["weighted"]["id"])
        cast_adjusted = read_valuation(api, env["cast_adjusted"]["id"])

        # Both rows sampled the identical comparable set.
        assert_money(weighted["comp_median_usd"], 1000000.00, "comp_median_usd")
        assert_money(cast_adjusted["comp_median_usd"], 1000000.00, "comp_median_usd")
        assert weighted["comp_sample_size"] == cast_adjusted["comp_sample_size"] == 3, (
            "both valuations sampled the same three comparables"
        )

        assert_money(weighted["estimate_usd"], 1200000.00, "estimate_usd")
        assert_money(cast_adjusted["estimate_usd"], 1680000.00, "estimate_usd")
        assert_money(
            cast_adjusted["estimate_usd"] - weighted["estimate_usd"],
            480000.00,
            "estimate_usd divergence",
        )
        assert_money_precision(weighted["estimate_usd"], "estimate_usd")
        assert_money_precision(cast_adjusted["estimate_usd"], "estimate_usd")


# ==========================================================================
# Buyer credit: the gross pipeline basis against the net unpaid basis
# ==========================================================================
class TestBuyerExposureVariants:
    def test_gross_pipeline_still_counts_the_whole_minimum_guarantee(self, api):
        """Cash already received does not reduce the gross pipeline figure.

        PRD: "The **gross pipeline** figure, stored as `outstanding_exposure_usd`, is the sum of `minimum_guarantee_usd` across every contract of this buyer whose `negotiation_status` is `OFFERED`, `COUNTERED`, `ACCEPTED` or `EXECUTED`, rounded half-up to two decimal places once at the end rather than per contract."

        Design: Difficulty/dual_variant_calc/buyer_exposure_diverges_between_gross_pipeline_and_net_unpaid_after_first_receipt
        """
        env = executed_contract_environment(api)
        signature = milestone_by_label(read_milestones(api, env["contract"]["id"]), "ON_SIGNATURE")
        post_receipt(api, signature, "2026-08-05T00:00:00Z")

        contract = read_contract(api, env["contract"]["id"])
        assert_contract_axes(contract, negotiation="EXECUTED")
        assert_money(contract["minimum_guarantee_usd"], 2000000.00, "minimum_guarantee_usd")

        buyer = read_buyer(api, env["buyer"]["id"])
        assert_buyer_exposure(buyer, gross=2000000.00)

    def test_net_unpaid_drops_the_received_milestone(self, api):
        """Only the still-unbilled and unpaid milestone amounts remain in the net figure.

        PRD: "The **net unpaid** figure, stored as `net_unpaid_exposure_usd`, is the sum of `amount_usd` across every payment milestone belonging to a contract of this buyer whose `negotiation_status` is exactly `EXECUTED` and whose own milestone `status` is `SCHEDULED` or `INVOICED`, again rounded once at the end to two decimal places."

        Design: Difficulty/dual_variant_calc/buyer_exposure_diverges_between_gross_pipeline_and_net_unpaid_after_first_receipt
        """
        env = executed_contract_environment(api)
        signature = milestone_by_label(read_milestones(api, env["contract"]["id"]), "ON_SIGNATURE")
        assert_money(signature["amount_usd"], 900000.00, "amount_usd")
        post_receipt(api, signature, "2026-08-05T00:00:00Z")

        buyer = read_buyer(api, env["buyer"]["id"])
        assert_buyer_exposure(buyer, net=1100000.00)

    def test_the_two_exposure_bases_diverge_by_the_received_amount(self, api):
        """The 900000.00 gap between the two figures is exactly the cash collected.

        PRD: "It counts only unbilled and unpaid milestone amounts of executed contracts, so received milestones and every non-executed contract drop out of it."

        Design: Difficulty/dual_variant_calc/buyer_exposure_diverges_between_gross_pipeline_and_net_unpaid_after_first_receipt
        """
        env = executed_contract_environment(api)
        buyer_before = read_buyer(api, env["buyer"]["id"])
        assert_buyer_exposure(buyer_before, gross=2000000.00, net=2000000.00)

        signature = milestone_by_label(read_milestones(api, env["contract"]["id"]), "ON_SIGNATURE")
        post_receipt(api, signature, "2026-08-05T00:00:00Z")

        buyer = read_buyer(api, env["buyer"]["id"])
        assert_buyer_exposure(buyer, gross=2000000.00, net=1100000.00)
        assert_money(
            buyer["outstanding_exposure_usd"] - buyer["net_unpaid_exposure_usd"],
            900000.00,
            "exposure divergence",
        )

    def test_the_received_milestone_and_the_contract_cash_axis_follow(self, api):
        """The booked milestone reads RECEIVED and the contract turns PARTIALLY_PAID.

        PRD: "`UNPAID → PARTIALLY_PAID` fires when, after the receipt, the contract's `received_amount_usd` is greater than zero **and** its `unpaid_amount_usd` is still greater than zero."

        Design: Difficulty/dual_variant_calc/buyer_exposure_diverges_between_gross_pipeline_and_net_unpaid_after_first_receipt
        """
        env = executed_contract_environment(api)
        signature = milestone_by_label(read_milestones(api, env["contract"]["id"]), "ON_SIGNATURE")
        booked = post_receipt(api, signature, "2026-08-05T00:00:00Z")

        assert booked["status"] == "RECEIVED", (
            f"expected milestone status RECEIVED, got {booked['status']!r}"
        )
        assert_money(booked["received_amount_usd"], 900000.00, "received_amount_usd")
        assert_instant(booked["received_at"], "2026-08-05T00:00:00Z", "received_at")

        contract = read_contract(api, env["contract"]["id"])
        assert_money(contract["unpaid_amount_usd"], 1100000.00, "unpaid_amount_usd")
        assert_money(contract["received_amount_usd"], 900000.00, "received_amount_usd")
        assert_contract_axes(contract, negotiation="EXECUTED", collection="PARTIALLY_PAID")


# ==========================================================================
# Commission accrual: one rate per receipt, chosen from the pre-receipt total
# ==========================================================================
class TestCommissionBandSelection:
    def test_receipt_straddling_the_first_breakpoint_is_charged_wholly_at_the_first_band(
        self, api
    ):
        """400000.00 arriving on a prior total of 900000.00 accrues 40000.00, not 32500.00.

        PRD: "A receipt of 400,000.00 posted when the prior total is 900,000.00 is charged entirely at the first-band rate; it is not treated as 100,000.00 at the first band plus 300,000.00 at the second."

        Design: Difficulty/combinatorial_formula/commission_rate_picked_from_pre_receipt_total_never_split_across_breakpoint
        """
        env = _collected_environment(api)
        milestones = read_milestones(api, env["contract"]["id"])

        signature = milestone_by_label(milestones, "ON_SIGNATURE")
        delivery = milestone_by_label(milestones, "ON_DELIVERY")

        assert_money(signature["amount_usd"], 900000.00, "ON_SIGNATURE amount_usd")
        assert_money(delivery["amount_usd"], 400000.00, "ON_DELIVERY amount_usd")

        assert_money(
            signature["accrued_commission_usd"],
            90000.00,
            "ON_SIGNATURE accrued_commission_usd",
        )
        assert_money(
            delivery["accrued_commission_usd"],
            40000.00,
            "ON_DELIVERY accrued_commission_usd",
        )

    def test_third_receipt_takes_the_discounted_band_from_the_prior_total(self, api):
        """With 1300000.00 already collected, the 200000.00 receipt accrues at 0.075.

        PRD: "When the prior total is at or above one million and below three million, the rate is `commission_pct` multiplied by 0.75, that product rounded half-up to 6 decimal places."

        Design: Difficulty/combinatorial_formula/commission_rate_picked_from_pre_receipt_total_never_split_across_breakpoint
        """
        env = _collected_environment(api)
        release = milestone_by_label(read_milestones(api, env["contract"]["id"]), "ON_RELEASE")

        assert_money(release["amount_usd"], 200000.00, "ON_RELEASE amount_usd")
        assert_money(
            release["accrued_commission_usd"],
            15000.00,
            "ON_RELEASE accrued_commission_usd",
        )
        assert release["status"] == "RECEIVED", (
            f"expected milestone status RECEIVED, got {release['status']!r}"
        )

    def test_agreement_totals_accumulate_the_banded_accruals_only(self, api):
        """gross_collected_usd reaches 1500000.00 and commission_earned_usd exactly 145000.00.

        PRD: "Step four, and only now: the agreement's `gross_collected_usd` becomes the prior total plus the posted amount, rounded to two decimal places, and its `commission_earned_usd` becomes its previous value plus the accrued commission, rounded to two decimal places."

        Design: Difficulty/combinatorial_formula/commission_rate_picked_from_pre_receipt_total_never_split_across_breakpoint
        """
        env = _collected_environment(api)
        agreement = read_agreement(api, env["film"]["id"], env["agreement"]["id"])

        assert_money(agreement["commission_pct"], 0.10, "commission_pct")
        assert_money(agreement["gross_collected_usd"], 1500000.00, "gross_collected_usd")
        assert_money(agreement["commission_earned_usd"], 145000.00, "commission_earned_usd")

    def test_receipt_sequence_leaves_the_account_film_and_contract_reconciled(self, api):
        """1500000.00 of cash sits undistributed and the contract still owes 500000.00.

        PRD: "The account's `total_receipts_usd` grows by the amount and `balance_usd` is recomputed."

        Design: Difficulty/combinatorial_formula/commission_rate_picked_from_pre_receipt_total_never_split_across_breakpoint
        """
        env = _collected_environment(api)

        account = read_account(api, env["account"]["id"])
        assert_account_counters(
            account, receipts=1500000.00, distributed=0.00, balance=1500000.00
        )

        film = read_film(api, env["film"]["id"])
        assert_film_counters(film, collected=1500000.00)

        contract = read_contract(api, env["contract"]["id"])
        assert_money(contract["unpaid_amount_usd"], 500000.00, "unpaid_amount_usd")
        assert_contract_axes(contract, collection="PARTIALLY_PAID")


# ==========================================================================
# The waterfall allocation loop: rounding each tier's share before subtracting
# ==========================================================================
class TestWaterfallRoundingOrder:
    def test_capped_head_tiers_take_their_rounded_share_and_their_room(self, api):
        """The collection fee rounds to 6250.00 and the two resynchronised tiers take their full room.

        PRD: "If the tier has a `cap_usd`, compute its remaining room as `cap_usd` less `recouped_usd`, rounded to two decimal places, and reduce the target to the lesser of the two."

        Design: Difficulty/combinatorial_formula/waterfall_round_each_tier_share_before_subtracting_shifts_a_cent_to_equity_tier
        """
        env = _waterfall_environment(api)
        run = assert_created(
            api.distribute(
                env["account"]["id"],
                distribute_payload(500000.04),
                make_collection_agent_headers(),
            )
        )

        allocations = run["allocations"]
        assert len(allocations) == 6, (
            f"the allocations array must hold one entry per tier, got {len(allocations)}"
        )
        assert_money(allocations[0]["amount_usd"], 6250.00, "allocations[0].amount_usd")
        assert_money(allocations[1]["amount_usd"], 145000.00, "allocations[1].amount_usd")
        assert_money(allocations[2]["amount_usd"], 75000.00, "allocations[2].amount_usd")
        assert [entry["tier_type"] for entry in allocations[:3]] == [
            "COLLECTION_FEE",
            "SALES_COMMISSION",
            "SALES_EXPENSES",
        ], "the allocations array is ordered by tier_order ascending"

    def test_equity_tier_receives_the_cent_the_pinned_rounding_order_produces(self, api):
        """Rounding each share before subtracting leaves EQUITY_RECOUPMENT exactly 24637.51.

        PRD: "First compute the tier's target as the current remaining figure multiplied by the tier's `pct_of_available`, **rounded half-up to two decimal places immediately**."

        Design: Difficulty/combinatorial_formula/waterfall_round_each_tier_share_before_subtracting_shifts_a_cent_to_equity_tier
        """
        env = _waterfall_environment(api)
        run = assert_created(
            api.distribute(
                env["account"]["id"],
                distribute_payload(500000.04),
                make_collection_agent_headers(),
            )
        )

        allocations = run["allocations"]
        assert_money(allocations[3]["amount_usd"], 232687.53, "allocations[3].amount_usd")
        assert_money(allocations[4]["amount_usd"], 24637.51, "allocations[4].amount_usd")
        assert_money(allocations[5]["amount_usd"], 16425.00, "allocations[5].amount_usd")
        assert [entry["tier_type"] for entry in allocations[3:]] == [
            "BANK_DEBT",
            "EQUITY_RECOUPMENT",
            "PARTICIPATION",
        ], "the allocations array is ordered by tier_order ascending"

    def test_run_record_reports_the_full_offered_amount_as_allocated(self, api):
        """The six rounded allocations sum back to 500000.04, leaving no residual.

        PRD: "`residual_usd` is `amount_in_usd` less `amount_allocated_usd`, rounded to two decimal places — cash that stayed behind because no uncapped `ACTIVE` tier could absorb it."

        Design: Difficulty/combinatorial_formula/waterfall_round_each_tier_share_before_subtracting_shifts_a_cent_to_equity_tier
        """
        env = _waterfall_environment(api)
        run = assert_created(
            api.distribute(
                env["account"]["id"],
                distribute_payload(500000.04),
                make_collection_agent_headers(),
            )
        )

        assert run["run_index"] == 1, f"expected run_index 1, got {run['run_index']}"
        assert_allocations(
            run,
            [6250.00, 145000.00, 75000.00, 232687.53, 24637.51, 16425.00],
            tier_count=6,
        )
        assert_money(run["amount_in_usd"], 500000.04, "amount_in_usd")
        assert_money(run["amount_allocated_usd"], 500000.04, "amount_allocated_usd")
        assert_money(run["residual_usd"], 0.00, "residual_usd")

    def test_tier_ledgers_and_derived_statuses_follow_the_allocation(self, api):
        """The two fully recouped tiers read SATISFIED while the bank tier stays ACTIVE.

        PRD: "A tier is `SATISFIED` when its `cap_usd` is not null and its `recouped_usd` has reached or passed that cap."

        Design: Difficulty/combinatorial_formula/waterfall_round_each_tier_share_before_subtracting_shifts_a_cent_to_equity_tier
        """
        env = _waterfall_environment(api)
        get_success_data(
            api.distribute(
                env["account"]["id"],
                distribute_payload(500000.04),
                make_collection_agent_headers(),
            )
        )

        account_id = env["account"]["id"]
        assert_tier(
            _tier_of_type(api, account_id, "SALES_COMMISSION"),
            recouped=145000.00,
            cap=145000.00,
            status="SATISFIED",
        )
        assert_tier(
            _tier_of_type(api, account_id, "SALES_EXPENSES"),
            recouped=75000.00,
            cap=75000.00,
            status="SATISFIED",
        )
        assert_tier(
            _tier_of_type(api, account_id, "BANK_DEBT"),
            recouped=232687.53,
            cap=1000000.00,
            status="ACTIVE",
        )
        assert_tier(
            _tier_of_type(api, account_id, "EQUITY_RECOUPMENT"),
            recouped=24637.51,
            status="ACTIVE",
        )

    def test_account_counters_absorb_the_run(self, api):
        """total_distributed_usd becomes 500000.04 and the balance falls to 999999.96.

        PRD: "The account's `total_distributed_usd` grows by `amount_allocated_usd`, its `balance_usd` is recomputed as `total_receipts_usd` less `total_distributed_usd` rounded to two decimal places, and its `run_count` increments by one."

        Design: Difficulty/combinatorial_formula/waterfall_round_each_tier_share_before_subtracting_shifts_a_cent_to_equity_tier
        """
        env = _waterfall_environment(api)
        get_success_data(
            api.distribute(
                env["account"]["id"],
                distribute_payload(500000.04),
                make_collection_agent_headers(),
            )
        )

        account = read_account(api, env["account"]["id"])
        assert_account_counters(
            account,
            receipts=1500000.00,
            distributed=500000.04,
            balance=999999.96,
            run_count=1,
        )

    def test_expense_recoupment_and_bank_debt_cross_entity_effects(self, api):
        """The agreement recoups only the 75000.00 cap and the facility's debt falls by 232687.53.

        PRD: "Whatever was allocated to the `BANK_DEBT` tier is subtracted from the banking facility's `outstanding_debt_usd`, and once that debt reaches 0.00 — equivalently, once the `BANK_DEBT` tier's `recouped_usd` has reached its `cap_usd` — the facility moves `DRAWN → REPAID` and the picture's `financing_gap_usd` is recomputed."

        Design: Difficulty/combinatorial_formula/waterfall_round_each_tier_share_before_subtracting_shifts_a_cent_to_equity_tier
        """
        env = _waterfall_environment(api)
        get_success_data(
            api.distribute(
                env["account"]["id"],
                distribute_payload(500000.04),
                make_collection_agent_headers(),
            )
        )

        agreement = read_agreement(api, env["film"]["id"], env["agreement"]["id"])
        assert_money(agreement["expenses_incurred_usd"], 90000.00, "expenses_incurred_usd")
        assert_money(agreement["expenses_recouped_usd"], 75000.00, "expenses_recouped_usd")

        facility = read_facility(api, env["film"]["id"], env["facility"]["id"])
        assert_facility_figures(
            facility, drawn=1000000.00, outstanding=767312.47, status="DRAWN"
        )


# ==========================================================================
# The lender advance: tenor decay inside the cap, then the unbonded haircut
# ==========================================================================
def _facility_on_executed_contract(api):
    """The canonical executed contract with a freshly proposed facility whose cap
    sits below the discounted collateral."""
    env = executed_contract(api)
    env["facility"] = assert_created(
        api.create_banking_facility(
            env["film"]["id"], facility_payload(), make_lender_headers()
        )
    )
    return env


class TestDiscountedAdvanceLayers:
    def test_creation_discounts_the_unpaid_sum_over_the_latest_tenor(self, api):
        """A 2000000.00 unpaid schedule maturing 2028-08-01 discounts to 1343649.60.

        PRD: "The discount factor is one minus the product of the facility's `discount_rate_pct` and the days to payment divided by 365, that whole expression rounded half-up to 6 decimal places."

        Design: Difficulty/combinatorial_formula/discounted_advance_nests_tenor_decay_inside_cap_then_unbonded_haircut
        """
        env = _facility_on_executed_contract(api)
        facility = env["facility"]

        assert_money(facility["discount_rate_pct"], 0.08, "discount_rate_pct")
        assert_money(facility["advance_rate_pct"], 0.80, "advance_rate_pct")
        assert_money(facility["facility_cap_usd"], 1000000.00, "facility_cap_usd")
        assert_facility_figures(facility, collateral=1343649.60, status="PROPOSED")
        assert facility["completion_bond_required"] is True, (
            "the facility was proposed with the completion bond required"
        )
        assert facility["completion_bond_posted"] is False, (
            "a new facility has completion_bond_posted false"
        )

    def test_cap_binds_before_the_unbonded_haircut_is_applied(self, api):
        """min(cap, collateral) then halve gives 500000.00, which no other order produces.

        PRD: "Then, if `completion_bond_required` is true and `completion_bond_posted` is still false, halve that figure — the unbonded haircut is exactly 0.50 — and round to two decimal places."

        Design: Difficulty/combinatorial_formula/discounted_advance_nests_tenor_decay_inside_cap_then_unbonded_haircut
        """
        env = _facility_on_executed_contract(api)
        facility = env["facility"]

        assert facility["eligible_collateral_usd"] > facility["facility_cap_usd"], (
            "the facility cap must be the binding leg of the nested minimum"
        )
        assert_facility_figures(
            facility,
            collateral=1343649.60,
            advance=500000.00,
            drawn=0.00,
            outstanding=0.00,
        )

    def test_approval_recomputes_the_figures_without_lifting_the_haircut(self, api):
        """Approval re-derives both figures but the bond is still outstanding, so 500000.00 stands.

        PRD: "Approval records `approved_by_user_id` from `X-User-ID`, recomputes `eligible_collateral_usd` and `advance_amount_usd`, and re-derives the picture's `BANK_DEBT` waterfall tier from `SUSPENDED` to `ACTIVE` — until a bank is actually on the hook, that tier absorbs nothing."

        Design: Difficulty/combinatorial_formula/discounted_advance_nests_tenor_decay_inside_cap_then_unbonded_haircut
        """
        env = _facility_on_executed_contract(api)
        approved = approve_facility(api, env["facility"]["id"], LENDER_APPROVER)

        assert approved["approved_by_user_id"] == LENDER_APPROVER, (
            f"expected approved_by_user_id {LENDER_APPROVER!r}, "
            f"got {approved['approved_by_user_id']!r}"
        )
        assert_facility_figures(
            approved,
            collateral=1343649.60,
            advance=500000.00,
            drawn=0.00,
            status="APPROVED",
        )

    def test_posting_the_bond_doubles_the_advance_to_the_capped_figure(self, api):
        """With the bond in hand the advance rises to the full cap of 1000000.00.

        PRD: "It sets `completion_bond_posted` to true, writes both supplied fields, and recomputes `advance_amount_usd` without the unbonded haircut — typically doubling it."

        Design: Difficulty/combinatorial_formula/discounted_advance_nests_tenor_decay_inside_cap_then_unbonded_haircut
        """
        env = _facility_on_executed_contract(api)
        approve_facility(api, env["facility"]["id"], LENDER_APPROVER)
        bonded = bond_facility(api, env["facility"]["id"])

        assert bonded["completion_bond_posted"] is True, (
            "posting the bond sets completion_bond_posted true"
        )
        assert_facility_figures(
            bonded, collateral=1343649.60, advance=1000000.00, status="APPROVED"
        )

        reread = read_facility(api, env["film"]["id"], env["facility"]["id"])
        assert_facility_figures(reread, collateral=1343649.60, advance=1000000.00)

    def test_buyer_downgrade_empties_the_collateral_pool_outright(self, api):
        """Once the buyer is BBB its paper contributes nothing, so both figures fall to 0.00.

        PRD: "A buyer rated `BBB` or `SPECULATIVE` contributes 0.00 even when its milestones are fully current, and so does a buyer on `WATCHLIST` or `BLOCKED`."

        Design: Difficulty/combinatorial_formula/discounted_advance_nests_tenor_decay_inside_cap_then_unbonded_haircut
        """
        env = _facility_on_executed_contract(api)
        approve_facility(api, env["facility"]["id"], LENDER_APPROVER)
        bond_facility(api, env["facility"]["id"])

        get_success_data(
            api.patch_buyer(
                env["buyer"]["id"],
                buyer_amendment_payload(credit_rating="BBB"),
                make_platform_admin_headers(),
            )
        )

        downgraded = read_buyer(api, env["buyer"]["id"])
        assert downgraded["credit_rating"] == "BBB", (
            f"expected credit_rating BBB, got {downgraded['credit_rating']!r}"
        )

        facility = read_facility(api, env["film"]["id"], env["facility"]["id"])
        assert_facility_figures(
            facility, collateral=0.00, advance=0.00, drawn=0.00, status="APPROVED"
        )
