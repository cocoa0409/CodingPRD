"""Bid pricing, supplier scoring, the volume rebate and the deposit split.

Every scenario here exercises the arithmetic the PRD pins down: the two variants
of the total cost model over one submitted bid, the two variants of a venue's
performance score over one set of scorecards, the deposit allocation's pinned
rounding order, and the volume rebate tier that is read from the pre-rebate
total rather than from the rebated one.
"""

from typing import Any, Dict

import pytest

from test_helpers import (
    FINANCE_HEADERS,
    PLANNER_HEADERS,
    api_client,
    assertions as domain_assert,
    fixtures,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Scenario builders local to this module
# ---------------------------------------------------------------------------
@pytest.fixture
def dual_basis_evaluations() -> Dict[str, Any]:
    """One submitted bid priced twice: once contracted, once actualized."""
    world = fixtures.build_submitted_bid()
    contracted = fixtures.evaluate_bid(world["proposal_id"], "CONTRACTED_BASIS")
    actualized = fixtures.evaluate_bid(world["proposal_id"], "ACTUALIZED_BASIS")
    world.update(
        {
            "contracted": contracted,
            "actualized": actualized,
            "proposal": fixtures.read_proposal(world["proposal_id"]),
        }
    )
    return world


@pytest.fixture
def thrice_scored_venue() -> Dict[str, Any]:
    """One venue carrying three imported scorecards that worsen over time."""
    fixtures.set_clock("2026-08-05T09:00:00.000Z")
    venue = fixtures.create_venue()
    fixtures.set_clock("2026-08-06T09:00:00.000Z")
    oldest = fixtures.capture_review(
        venue["id"],
        service_score=5,
        value_score=5,
        av_quality_score=4,
        responsiveness_score=5,
        comment="Imported 2025 scorecard",
    )
    fixtures.set_clock("2026-08-07T09:00:00.000Z")
    middle = fixtures.capture_review(
        venue["id"],
        service_score=3,
        value_score=4,
        av_quality_score=3,
        responsiveness_score=3,
        comment="Imported 2026 H1 scorecard",
    )
    fixtures.set_clock("2026-08-08T09:00:00.000Z")
    newest = fixtures.capture_review(
        venue["id"],
        service_score=2,
        value_score=3,
        av_quality_score=2,
        responsiveness_score=2,
        comment="Imported 2026 H2 scorecard",
    )
    return {
        "venue": fixtures.read_venue(venue["id"]),
        "venue_id": venue["id"],
        "oldest": oldest,
        "middle": middle,
        "newest": newest,
    }


@pytest.fixture
def top_tier_rebate_contract() -> Dict[str, Any]:
    """An award whose pre-rebate total clears 400000.00 but whose rebated total does not."""
    world = fixtures.build_awarded_contract(
        bid_overrides={"fnb_minimum_usd": 115000.00}
    )
    world["event"] = fixtures.read_event(world["event_id"])
    world["proposal"] = fixtures.read_proposal(world["proposal_id"])
    return world


class TestBidCostModelVariants:
    """The same submitted bid priced on both bases of the total cost model."""

    def test_contracted_basis_charges_the_whole_block_with_no_damages(
        self, dual_basis_evaluations
    ):
        """Every component of the contracted-basis snapshot, damages included.

        Under the **`CONTRACTED_BASIS`** variant, the nights charged are the full contracted block — `paid_room_nights` — and the attrition damages term is exactly `0.00`.

        Design: Difficulty/dual_variant_calc/proposal_cost_contracted_basis_vs_actualized_basis
        """
        snapshot = dual_basis_evaluations["contracted"]
        domain_assert.assert_cost_components(
            snapshot,
            {
                "basis": "CONTRACTED_BASIS",
                "paid_room_nights_used": 587,
                "room_revenue_usd": 146163.00,
                "resort_fee_total_usd": 10566.00,
                "av_adjusted_usd": 20900.00,
                "service_charge_usd": 74895.12,
                "tax_usd": 62013.76,
                "concession_applied_usd": 11693.04,
                "attrition_damages_usd": 0.00,
                "total_cost_usd": 447844.84,
            },
        )

    def test_actualized_basis_charges_only_the_projected_nights(
        self, dual_basis_evaluations
    ):
        """Every component of the actualized-basis snapshot of the same bid.

        The nights charged under this variant are the projected paid nights.

        Design: Difficulty/dual_variant_calc/proposal_cost_contracted_basis_vs_actualized_basis
        """
        snapshot = dual_basis_evaluations["actualized"]
        domain_assert.assert_cost_components(
            snapshot,
            {
                "basis": "ACTUALIZED_BASIS",
                "paid_room_nights_used": 517,
                "room_revenue_usd": 128733.00,
                "resort_fee_total_usd": 9306.00,
                "service_charge_usd": 70711.92,
                "tax_usd": 58445.54,
                "concession_applied_usd": 10298.64,
                "attrition_damages_usd": 0.00,
                "total_cost_usd": 422797.82,
            },
        )

    def test_the_two_bases_differ_by_a_fixed_amount_on_one_bid(
        self, dual_basis_evaluations
    ):
        """The two snapshots of one bid are separated by a single fixed delta.

        The model has two variants that differ **only** in how many room nights they charge for and whether they book projected attrition damages; every other step is identical.

        Design: Difficulty/dual_variant_calc/proposal_cost_contracted_basis_vs_actualized_basis
        """
        contracted_total = dual_basis_evaluations["contracted"]["total_cost_usd"]
        actualized_total = dual_basis_evaluations["actualized"]["total_cost_usd"]
        domain_assert.assert_money(
            contracted_total - actualized_total, 25047.02, "variant delta"
        )

    def test_pricing_on_the_actualized_basis_leaves_the_contracted_total_alone(
        self, dual_basis_evaluations
    ):
        """The bid's contracted total survives an actualized-basis re-pricing.

        The bid's `total_cost_contracted_usd` is **not** touched by evaluation; it changes only on submission and revision.

        Design: Difficulty/dual_variant_calc/proposal_cost_contracted_basis_vs_actualized_basis
        """
        proposal = validate_success(
            api_client.get_proposal(dual_basis_evaluations["proposal_id"], PLANNER_HEADERS)
        )
        domain_assert.assert_money_field(proposal, "total_cost_contracted_usd", 447844.84)

    def test_newest_snapshot_overwrites_the_modeled_total_and_basis(
        self, dual_basis_evaluations
    ):
        """The bid's modelled rollup reports the most recent snapshot only.

        In all three cases a new snapshot row is appended and earlier rows are left exactly as written, the bid's `total_cost_modeled_usd` and `last_evaluation_basis` are overwritten from the newest row, and the bid's `version` advances by 1.

        Design: Difficulty/dual_variant_calc/proposal_cost_contracted_basis_vs_actualized_basis
        """
        proposal = dual_basis_evaluations["proposal"]
        domain_assert.assert_money_field(proposal, "total_cost_modeled_usd", 422797.82)
        domain_assert.assert_fields_equal(
            proposal, {"last_evaluation_basis": "ACTUALIZED_BASIS"}
        )

    def test_re_pricing_on_the_other_basis_keeps_the_bid_under_review(
        self, dual_basis_evaluations
    ):
        """A second evaluation of the same bid does not move it out of review.

        All three source states are admitted and each behaves as follows: a bid in `SUBMITTED` moves `SUBMITTED → UNDER_REVIEW`; a bid in `REVISED` moves `REVISED → UNDER_REVIEW`, which is the edge that closes the negotiation cycle; and a bid already in `UNDER_REVIEW` stays in `UNDER_REVIEW`, which is how the planner re-prices the same bid on the other basis.

        Design: Difficulty/dual_variant_calc/proposal_cost_contracted_basis_vs_actualized_basis
        """
        domain_assert.assert_fields_equal(
            dual_basis_evaluations["proposal"], {"status": "UNDER_REVIEW"}
        )


class TestVenuePerformanceScoreVariants:
    """One venue's three scorecards summarised two different ways."""

    def test_each_scorecard_carries_its_weighted_composite(self, thrice_scored_venue):
        """The four sub-scores collapse into one composite per scorecard.

        Each review's `composite_score` is `0.35` times `service_score` plus `0.25` times `value_score` plus `0.20` times `av_quality_score` plus `0.20` times `responsiveness_score`, rounded to 2 decimal places.

        Design: Difficulty/dual_variant_calc/venue_performance_recency_weighted_vs_simple_mean
        """
        domain_assert.assert_money(
            thrice_scored_venue["oldest"]["composite_score"], 4.80, "composite_score"
        )
        domain_assert.assert_money(
            thrice_scored_venue["middle"]["composite_score"], 3.25, "composite_score"
        )
        domain_assert.assert_money(
            thrice_scored_venue["newest"]["composite_score"], 2.25, "composite_score"
        )

    def test_performance_score_decays_older_scorecards(self, thrice_scored_venue):
        """The headline score leans on the newest scorecard.

        The `performance_score` field takes the recency-weighted variant, `RECENCY_WEIGHTED`: each review at rank `r`, counting from 1 for the newest, is weighted by `0.7` raised to the power `r - 1`, and `performance_score` is the sum of weight times `composite_score` divided by the sum of the weights, the division happening before the single rounding to 2 decimal places.

        Design: Difficulty/dual_variant_calc/venue_performance_recency_weighted_vs_simple_mean
        """
        domain_assert.assert_money(
            thrice_scored_venue["venue"]["performance_score"], 3.14, "performance_score"
        )

    def test_simple_mean_weighs_every_scorecard_alike_and_diverges(
        self, thrice_scored_venue
    ):
        """The audit score averages the same three composites unweighted.

        The `performance_score_simple_mean` field takes the unweighted variant, `SIMPLE_MEAN`: the sum of every `composite_score` divided by the number of reviews, rounded to 2 decimal places.

        Design: Difficulty/dual_variant_calc/venue_performance_recency_weighted_vs_simple_mean
        """
        venue = thrice_scored_venue["venue"]
        domain_assert.assert_money(
            venue["performance_score_simple_mean"], 3.43, "performance_score_simple_mean"
        )
        assert venue["performance_score"] != venue["performance_score_simple_mean"], (
            "the two variants must diverge when the scorecards are not all equal"
        )

    def test_capturing_scorecards_counts_them_on_the_venue(self, thrice_scored_venue):
        """The venue's review count tracks the scorecards captured against it.

        Capturing a review also increases the venue's `performance_review_count` by 1 and advances its `version` by 1.

        Design: Difficulty/dual_variant_calc/venue_performance_recency_weighted_vs_simple_mean
        """
        domain_assert.assert_integer(
            thrice_scored_venue["venue"]["performance_review_count"],
            3,
            "performance_review_count",
        )


def _installments_by_seq(installments) -> Dict[int, Dict[str, Any]]:
    """Index a contract's installments by their ``installment_seq``."""
    return {row["installment_seq"]: row for row in installments}


class TestDepositAllocationRoundingOrder:
    """The three-installment split of an executed contract's deposit."""

    def test_deposit_total_is_thirty_percent_of_the_committed_money(
        self, deposit_scheduled_contract
    ):
        """The deposit total is taken from the rebated contract value.

        The deposit is 30 percent of the money actually committed: `deposit_total_usd` is `contracted_total_usd` multiplied by `0.30`, rounded to 2 decimal places.

        Design: Difficulty/combinatorial_formula/deposit_schedule_per_installment_rounding_then_residual
        """
        domain_assert.assert_money_field(
            deposit_scheduled_contract["contract"], "deposit_total_usd", 129651.08
        )

    def test_three_installments_carry_the_declared_weights(
        self, deposit_scheduled_contract
    ):
        """Exactly three installments are generated in the declared weight order.

        That total is then split across exactly three installments carrying `weight_pct` values of `0.34`, `0.33` and `0.33` at `installment_seq` `1`, `2` and `3`.

        Design: Difficulty/combinatorial_formula/deposit_schedule_per_installment_rounding_then_residual
        """
        installments, _meta = validate_paginated(
            api_client.list_deposit_installments(
                deposit_scheduled_contract["contract_id"], FINANCE_HEADERS
            )
        )
        assert len(installments) == 3, f"expected three installments, got {len(installments)}"
        domain_assert.assert_sequence(installments, "installment_seq", [1, 2, 3])
        domain_assert.assert_sequence(installments, "weight_pct", [0.34, 0.33, 0.33])

    def test_each_share_is_rounded_to_the_cent_independently(
        self, deposit_scheduled_contract
    ):
        """The first two installments carry their own independently rounded share.

        First, each installment's `amount_usd` is computed independently as `deposit_total_usd` multiplied by that installment's `weight_pct`, rounded to 2 decimal places.

        Design: Difficulty/combinatorial_formula/deposit_schedule_per_installment_rounding_then_residual
        """
        by_seq = _installments_by_seq(deposit_scheduled_contract["installments"])
        domain_assert.assert_money_field(by_seq[1], "amount_usd", 44081.37)
        domain_assert.assert_money_field(by_seq[2], "amount_usd", 42784.86)

    def test_the_residual_lands_on_the_third_installment(
        self, deposit_scheduled_contract
    ):
        """The last installment absorbs the cent the rounded shares over-allocated.

        The residual always lands on installment 3, never on installment 1 or 2.

        Design: Difficulty/combinatorial_formula/deposit_schedule_per_installment_rounding_then_residual
        """
        by_seq = _installments_by_seq(deposit_scheduled_contract["installments"])
        domain_assert.assert_money_field(by_seq[3], "amount_usd", 42784.85)

    def test_installment_amounts_sum_to_the_deposit_total_to_the_cent(
        self, deposit_scheduled_contract
    ):
        """The split conserves the deposit total exactly.

        What this order guarantees is that the sum of the three `amount_usd` values equals `deposit_total_usd` to the cent, exactly.

        Design: Difficulty/combinatorial_formula/deposit_schedule_per_installment_rounding_then_residual
        """
        installments = deposit_scheduled_contract["installments"]
        domain_assert.assert_deposit_split_sums(installments, 129651.08)
        assert round(sum(row["amount_usd"] for row in installments), 2) != 129651.09, (
            "the shares must not be left summing to 129651.09"
        )

    def test_due_dates_step_back_from_the_arrival_date(self, deposit_scheduled_contract):
        """Each installment falls due a fixed number of days before arrival.

        Each installment's `due_date` is derived from the event's `start_date` by subtracting a fixed offset: 180 days for `installment_seq` 1, 90 days for `installment_seq` 2 and 30 days for `installment_seq` 3, each rendered as a calendar date.

        Design: Difficulty/combinatorial_formula/deposit_schedule_per_installment_rounding_then_residual
        """
        by_seq = _installments_by_seq(deposit_scheduled_contract["installments"])
        for seq in (1, 2, 3):
            domain_assert.assert_calendar_date(by_seq[seq]["due_date"], "due_date")
        assert by_seq[1]["due_date"] == "2026-09-16"
        assert by_seq[2]["due_date"] == "2026-12-15"
        assert by_seq[3]["due_date"] == "2027-02-13"

    def test_the_schedule_leaves_the_whole_deposit_outstanding(
        self, deposit_scheduled_contract
    ):
        """Generating the schedule records nothing as paid yet.

        The contract's `deposit_paid_usd` is set to `0.00` and its `deposit_outstanding_usd` to the sum of the three amounts — which is to say, to `deposit_total_usd` — and its `version` advances by 1.

        Design: Difficulty/combinatorial_formula/deposit_schedule_per_installment_rounding_then_residual
        """
        contract = deposit_scheduled_contract["contract"]
        domain_assert.assert_money_field(contract, "deposit_paid_usd", 0.00)
        domain_assert.assert_money_field(contract, "deposit_outstanding_usd", 129651.08)

    def test_every_installment_starts_scheduled(self, deposit_scheduled_contract):
        """No installment is born paid or cancelled.

        Each installment is created with `status` `SCHEDULED` and with `paid_amount_usd`, `paid_at` and `payment_reference` null.

        Design: Difficulty/combinatorial_formula/deposit_schedule_per_installment_rounding_then_residual
        """
        for row in deposit_scheduled_contract["installments"]:
            domain_assert.assert_fields_equal(row, {"status": "SCHEDULED"})


class TestVolumeRebateTierSelection:
    """The rebate tier is fixed by the pre-rebate figure, not by the rebated one."""

    def test_pre_rebate_total_is_snapshotted_from_the_winning_bid(
        self, top_tier_rebate_contract
    ):
        """Awarding copies the bid's contracted total onto the contract untouched.

        First, `pre_rebate_total_usd` is snapshotted from the winning bid's `total_cost_contracted_usd`.

        Design: Difficulty/combinatorial_formula/volume_rebate_tier_read_from_pre_rebate_total
        """
        domain_assert.assert_money_field(
            top_tier_rebate_contract["contract"], "pre_rebate_total_usd", 404841.64
        )
        domain_assert.assert_money_field(
            top_tier_rebate_contract["proposal"], "total_cost_contracted_usd", 404841.64
        )

    def test_the_pre_rebate_total_selects_the_top_rebate_tier(
        self, top_tier_rebate_contract
    ):
        """A pre-rebate total at or above the upper threshold earns the richest rate.

        The rebate percentage is then chosen from that pre-rebate figure: a `pre_rebate_total_usd` below `150000.00` earns `volume_rebate_pct` of `0.000`; a `pre_rebate_total_usd` at or above `150000.00` but below `400000.00` earns `0.020`; and a `pre_rebate_total_usd` at or above `400000.00` earns `0.035`.

        Design: Difficulty/combinatorial_formula/volume_rebate_tier_read_from_pre_rebate_total
        """
        contract = top_tier_rebate_contract["contract"]
        assert contract["volume_rebate_pct"] == pytest.approx(0.035, abs=1e-9), (
            f"expected the 0.035 tier, got {contract['volume_rebate_pct']}"
        )

    def test_rebate_amount_and_rebated_total_follow_the_chosen_tier(
        self, top_tier_rebate_contract
    ):
        """The rebate is deducted from the pre-rebate total to give the committed value.

        Then `volume_rebate_usd` is `pre_rebate_total_usd` multiplied by `volume_rebate_pct`, rounded to 2 decimal places, and `contracted_total_usd` is `pre_rebate_total_usd` minus `volume_rebate_usd`, rounded to 2 decimal places.

        Design: Difficulty/combinatorial_formula/volume_rebate_tier_read_from_pre_rebate_total
        """
        contract = top_tier_rebate_contract["contract"]
        domain_assert.assert_money_field(contract, "volume_rebate_usd", 14169.46)
        domain_assert.assert_money_field(contract, "contracted_total_usd", 390672.18)

    def test_the_rebated_total_is_never_used_to_re_derive_the_tier(
        self, top_tier_rebate_contract
    ):
        """Falling below the threshold after the rebate does not demote the tier.

        The tier is chosen once, from the pre-rebate total, and is never re-derived from `contracted_total_usd`: a pre-rebate total of `152000.00` sits in the `0.020` tier and yields a `contracted_total_usd` of `148960.00`, which is below `150000.00`, and that does not demote the contract to the `0.000` tier.

        Design: Difficulty/combinatorial_formula/volume_rebate_tier_read_from_pre_rebate_total
        """
        contract = top_tier_rebate_contract["contract"]
        assert contract["contracted_total_usd"] != pytest.approx(382858.74, abs=0.01), (
            "the rebate must not be applied a second time from the rebated total"
        )
        assert contract["volume_rebate_pct"] != pytest.approx(0.020, abs=1e-9), (
            "the contract must not fall back to the middle tier"
        )

    def test_committed_spend_records_the_rebated_total(self, top_tier_rebate_contract):
        """The event's committed money is the rebated contract value, not the quoted one.

        Awarding adds the new contract's `contracted_total_usd` to `committed_spend_usd`.

        Design: Difficulty/combinatorial_formula/volume_rebate_tier_read_from_pre_rebate_total
        """
        event = top_tier_rebate_contract["event"]
        domain_assert.assert_money_field(event, "committed_spend_usd", 390672.18)
        domain_assert.assert_money_field(event, "budget_remaining_usd", 109327.82)
        domain_assert.assert_budget_envelope(event)

    def test_contracted_room_terms_are_copied_from_the_winning_bid(
        self, top_tier_rebate_contract
    ):
        """The contract restates the bid's rate and block as room revenue.

        The contract's `contracted_room_rate_usd` is the bid's `net_adr_usd`; its `contracted_paid_room_nights` is the bid's `paid_room_nights`; its `contracted_room_revenue_usd` is `contracted_room_rate_usd` multiplied by `contracted_paid_room_nights`, rounded to 2 decimal places.

        Design: Difficulty/combinatorial_formula/volume_rebate_tier_read_from_pre_rebate_total
        """
        contract = top_tier_rebate_contract["contract"]
        domain_assert.assert_money_field(contract, "contracted_room_rate_usd", 249.00)
        domain_assert.assert_integer(
            contract["contracted_paid_room_nights"], 587, "contracted_paid_room_nights"
        )
        domain_assert.assert_money_field(contract, "contracted_room_revenue_usd", 146163.00)

    def test_peak_rooms_per_night_rounds_the_block_up(self, top_tier_rebate_contract):
        """The nightly peak is the block spread over the meeting, rounded up.

        A contract's `peak_rooms_per_night` is derived from the contracted block and the meeting's length: it is the contract's `contracted_paid_room_nights` divided by the parent meeting event's `nights_span`, rounded **up** to the next whole room.

        Design: Difficulty/combinatorial_formula/volume_rebate_tier_read_from_pre_rebate_total
        """
        domain_assert.assert_integer(
            top_tier_rebate_contract["contract"]["peak_rooms_per_night"],
            196,
            "peak_rooms_per_night",
        )
