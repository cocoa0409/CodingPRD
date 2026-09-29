"""Pricing, benchmarking and rollup arithmetic of the venue sourcing API.

Every test here drives the documented endpoints and then checks the figures the
PRD pins: the tiered audiovisual adjustment inside the total cost model, the
four-decimal benchmark variance and its verdict, the filtered shortlist rollup,
the approval route generated from the contracted total, the post-event
reconciliation and the tiered cancellation ladder.
"""

from test_helpers import (
    CLOCK_SOURCING_WINDOW,
    PLANNER_HEADERS,
    api_client,
    validate_paginated,
)
from test_helpers import assertions as domain_assert
from test_helpers import factories, fixtures

# A deliberately flat bid grid: one hundred NET room nights, no comps, no resort
# fee, no food and beverage and no concession, so that a single quoted figure is
# the only thing moving between two bids.
_SIMPLE_GRID = {
    "room_rate_usd": 200.00,
    "rate_type": "NET",
    "commission_pct": 0.00,
    "room_nights_offered": 100,
    "comp_room_ratio": 0,
    "resort_fee_usd_per_night": 0.00,
    "service_charge_pct": 0.20,
    "tax_pct": 0.10,
    "av_estimate_usd": 0.00,
    "fnb_minimum_usd": 0.00,
    "concession_credit_usd": 0.00,
    "attrition_allowance_pct": 0.20,
    "force_majeure_scope": "STANDARD",
    "rebooking_credit_pct": 0.50,
}


def _simple_grid(**changes):
    """The flat grid with only the quoted field under examination changed."""
    grid = dict(_SIMPLE_GRID)
    grid.update(changes)
    return grid


def _build_four_bidder_round(preferred_statuses):
    """Issue round 1 of one locked event to four venues, one per given standing.

    Returns the event and round identifiers alongside the four venues and the
    four ``INVITED`` bids the issue minted for them, in rank order.
    """
    fixtures.set_clock(CLOCK_SOURCING_WINDOW)
    benchmark = fixtures.create_benchmark()
    venues = [
        fixtures.create_venue(
            name=factories.next_venue_name(),
            guest_rooms_total=300,
            largest_space_sqft=13000,
            preferred_supplier_status=status,
        )
        for status in preferred_statuses
    ]
    event = fixtures.create_event()
    fixtures.lock_event(event["id"])
    for rank, venue in enumerate(venues, start=1):
        entry = fixtures.add_entry(event["id"], venue["id"], rank_seq=rank)
        fixtures.promote_entry(entry["id"])
    rfp = fixtures.issue_rfp(fixtures.create_rfp(event["id"])["id"])
    proposals = [
        fixtures.find_invited_proposal(rfp["id"], venue["id"]) for venue in venues
    ]
    return {
        "benchmark": benchmark,
        "venues": venues,
        "event_id": event["id"],
        "rfp_id": rfp["id"],
        "proposals": proposals,
    }


def _submit_across_bidders(world, **varying_field):
    """Submit the flat grid for all four venues, varying one field per bidder.

    ``varying_field`` carries exactly one keyword whose value is the list of four
    per-bidder values.
    """
    (field, values), = varying_field.items()
    for venue, proposal, value in zip(world["venues"], world["proposals"], values):
        fixtures.submit_bid(
            proposal["id"], venue["id"], **_simple_grid(**{field: value})
        )


def _build_four_entry_event():
    """A locked event carrying one candidate, two committed and one inspected entry.

    Rank 1 is never promoted, ranks 2 and 3 are promoted, and rank 4 is promoted
    and then has an inspection planned against it.
    """
    fixtures.set_clock(CLOCK_SOURCING_WINDOW)
    fixtures.create_benchmark()
    venues = [
        fixtures.create_venue(
            name=factories.next_venue_name(),
            guest_rooms_total=300,
            largest_space_sqft=13000,
        )
        for _ in range(4)
    ]
    event = fixtures.create_event()
    fixtures.lock_event(event["id"])
    entry_one = fixtures.add_entry(event["id"], venues[0]["id"], rank_seq=1)
    entry_two = fixtures.add_entry(event["id"], venues[1]["id"], rank_seq=2)
    fixtures.promote_entry(entry_two["id"])
    entry_three = fixtures.add_entry(event["id"], venues[2]["id"], rank_seq=3)
    fixtures.promote_entry(entry_three["id"])
    entry_four = fixtures.add_entry(
        event["id"], venues[3]["id"], rank_seq=4, inspection_required=True
    )
    fixtures.promote_entry(entry_four["id"])
    fixtures.plan_inspection(entry_four["id"])
    return {
        "event_id": event["id"],
        "entry_ids": [
            entry_one["id"],
            entry_two["id"],
            entry_three["id"],
            entry_four["id"],
        ],
    }


class TestAudiovisualVolumeTiers:
    """The audiovisual volume adjustment at both tier boundaries."""

    def test_av_adjusted_usd_at_and_one_cent_past_each_boundary(self):
        """Four otherwise identical bids differing only in their quoted AV estimate.

        In every tier the product is rounded half up to two decimals, and the tier boundaries are inclusive at the top, so an estimate of exactly 10,000.00 takes the full-value tier and one of exactly 25,000.00 takes the five-percent tier.

        Design: Corner/calculations/av_tiered_pricing_at_both_tier_boundaries
        """
        world = _build_four_bidder_round(("PREFERRED",) * 4)
        _submit_across_bidders(
            world, av_estimate_usd=[10000.00, 10000.01, 25000.00, 25000.01]
        )

        evaluations = [
            fixtures.evaluate_bid(proposal["id"]) for proposal in world["proposals"]
        ]

        domain_assert.assert_money(
            evaluations[0]["av_adjusted_usd"], 10000.00, "av_adjusted_usd"
        )
        domain_assert.assert_money(
            evaluations[1]["av_adjusted_usd"], 9500.01, "av_adjusted_usd"
        )
        domain_assert.assert_money(
            evaluations[2]["av_adjusted_usd"], 23750.00, "av_adjusted_usd"
        )
        domain_assert.assert_money(
            evaluations[3]["av_adjusted_usd"], 22500.01, "av_adjusted_usd"
        )

    def test_the_av_adjustment_flows_through_the_service_charge_and_tax_bases(self):
        """The adjusted estimate, not the quoted one, feeds the two derived bases.

        `tax_usd` is `tax_pct` applied to the sum of `room_revenue_usd`, `resort_fee_total_usd`, `fnb_usd`, `av_adjusted_usd` and `service_charge_usd`.

        Design: Corner/calculations/av_tiered_pricing_at_both_tier_boundaries
        """
        world = _build_four_bidder_round(("PREFERRED",) * 4)
        _submit_across_bidders(
            world, av_estimate_usd=[10000.00, 10000.01, 25000.00, 25000.01]
        )

        evaluations = [
            fixtures.evaluate_bid(proposal["id"]) for proposal in world["proposals"]
        ]

        expected = [
            {"service_charge_usd": 6000.00, "tax_usd": 3600.00, "total_cost_usd": 39600.00},
            {"service_charge_usd": 5900.00, "tax_usd": 3540.00, "total_cost_usd": 38940.01},
            {"service_charge_usd": 8750.00, "tax_usd": 5250.00, "total_cost_usd": 57750.00},
            {"service_charge_usd": 8500.00, "tax_usd": 5100.00, "total_cost_usd": 56100.01},
        ]
        for evaluation, components in zip(evaluations, expected):
            domain_assert.assert_cost_components(evaluation, components)
        for evaluation in evaluations:
            domain_assert.assert_cost_components(
                evaluation,
                {
                    "paid_room_nights_used": 100,
                    "room_revenue_usd": 20000.00,
                    "resort_fee_total_usd": 0.00,
                    "fnb_usd": 0.00,
                    "concession_applied_usd": 0.00,
                    "attrition_damages_usd": 0.00,
                    "benchmark_adr_usd": 260.00,
                },
            )

    def test_each_bid_carries_its_own_total_and_the_event_tracks_the_cheapest(self):
        """One cent past the first boundary makes the bid cheaper, and the event notices.

        The contracted-basis output is written to the bid's `total_cost_contracted_usd` on every submission and on every revision, and that figure — never the actualized one — is the only total the budget ceiling is tested against and the only total the volume-rebate tier reads.

        Otherwise it is the `total_cost_contracted_usd` of the live bid with the smallest `total_cost_contracted_usd`, with ties broken in favour of the bid with the earlier `created_at` and never by comparing `id` values; the stored two-decimal value is carried across unchanged with no further rounding.

        Design: Corner/calculations/av_tiered_pricing_at_both_tier_boundaries
        """
        world = _build_four_bidder_round(("PREFERRED",) * 4)
        _submit_across_bidders(
            world, av_estimate_usd=[10000.00, 10000.01, 25000.00, 25000.01]
        )
        for proposal in world["proposals"]:
            fixtures.evaluate_bid(proposal["id"])

        totals = [
            fixtures.read_proposal(proposal["id"])["total_cost_contracted_usd"]
            for proposal in world["proposals"]
        ]

        domain_assert.assert_money(totals[0], 39600.00, "total_cost_contracted_usd")
        domain_assert.assert_money(totals[1], 38940.01, "total_cost_contracted_usd")
        domain_assert.assert_money(totals[2], 57750.00, "total_cost_contracted_usd")
        domain_assert.assert_money(totals[3], 56100.01, "total_cost_contracted_usd")
        event = fixtures.read_event(world["event_id"])
        domain_assert.assert_money_field(event, "best_total_cost_usd", 38940.01)


class TestBenchmarkVarianceVerdicts:
    """The variance at the two programme-premium thresholds and on both standings."""

    def test_variance_and_verdict_at_zero_and_at_the_maximum_premium(self):
        """Three bids on a preferred venue straddle the premium ceiling, a fourth sits outside the programme.

        With the benchmark in hand, `benchmark_variance_pct` is the signed fraction by which the bid's `net_adr_usd` exceeds the benchmark's `benchmark_adr_usd`: the difference between `net_adr_usd` and `benchmark_adr_usd`, divided by `benchmark_adr_usd`, rounded half up to **four** decimal places.

        Both comparisons are inclusive against the already-rounded four-decimal value, so a variance of exactly `0.1000` is `COMPLIANT_WITH_VARIANCE` and not `NON_COMPLIANT`.

        When the venue's `preferred_supplier_status` is `NONE`, the best available verdict is one grade lower: a variance at or below `0.0000` earns `COMPLIANT_WITH_VARIANCE`, and any variance above `0.0000` earns `NON_COMPLIANT`.

        Design: Corner/calculations/benchmark_variance_thresholds_at_zero_and_max_program_premium
        """
        world = _build_four_bidder_round(
            ("PREFERRED", "PREFERRED", "PREFERRED", "NONE")
        )
        _submit_across_bidders(world, room_rate_usd=[260.00, 286.00, 286.02, 260.00])

        bids = [
            fixtures.read_proposal(proposal["id"]) for proposal in world["proposals"]
        ]

        expected = [
            (260.00, 0.0000, "COMPLIANT"),
            (286.00, 0.1000, "COMPLIANT_WITH_VARIANCE"),
            (286.02, 0.1001, "NON_COMPLIANT"),
            (260.00, 0.0000, "COMPLIANT_WITH_VARIANCE"),
        ]
        for bid, (net_adr, variance, verdict) in zip(bids, expected):
            domain_assert.assert_money_field(bid, "net_adr_usd", net_adr)
            domain_assert.assert_variance_pct(bid["benchmark_variance_pct"], variance)
            domain_assert.assert_fields_equal(bid, {"compliance_status": verdict})
        rows = fixtures.list_round_proposals(world["rfp_id"])
        assert len(rows) == 4, f"expected four bids on the round, got {len(rows)}"
        statuses = sorted(row["status"] for row in rows)
        assert statuses == ["SUBMITTED"] * 4, (
            f"every bid should have been accepted at submit time, got {statuses}"
        )

    def test_a_non_compliant_bid_still_prices_and_still_competes(self):
        """Every bid keeps its own total and the cheapest of them becomes the event's benchmark figure.

        `submitted_count` is the number of this round's bids whose `status` is one of `SUBMITTED`, `UNDER_REVIEW`, `COUNTERED`, `REVISED` or `AWARDED`.

        Design: Corner/calculations/benchmark_variance_thresholds_at_zero_and_max_program_premium
        """
        world = _build_four_bidder_round(
            ("PREFERRED", "PREFERRED", "PREFERRED", "NONE")
        )
        _submit_across_bidders(world, room_rate_usd=[260.00, 286.00, 286.02, 260.00])

        totals = [
            fixtures.read_proposal(proposal["id"])["total_cost_contracted_usd"]
            for proposal in world["proposals"]
        ]

        domain_assert.assert_money(totals[0], 34320.00, "total_cost_contracted_usd")
        domain_assert.assert_money(totals[1], 37752.00, "total_cost_contracted_usd")
        domain_assert.assert_money(totals[2], 37754.64, "total_cost_contracted_usd")
        domain_assert.assert_money(totals[3], 34320.00, "total_cost_contracted_usd")
        event = fixtures.read_event(world["event_id"])
        domain_assert.assert_money_field(event, "best_total_cost_usd", 34320.00)
        rfp = fixtures.read_rfp(world["rfp_id"])
        domain_assert.assert_integer(rfp["submitted_count"], 4, "submitted_count")


class TestShortlistedVenueCountRollup:
    """The committed-venue count is a filtered aggregate over the entry states."""

    def test_eliminating_a_committed_entry_drops_it_out_of_the_count(self):
        """A candidate that was never promoted and an eliminated entry are both outside the count.

        That count is maintained as the number of the event's entries whose `status` is one of `SHORTLISTED`, `INSPECTION_SCHEDULED`, `INSPECTED`, `RFP_ISSUED` or `AWARDED` — entries still in `CANDIDATE` and entries already `ELIMINATED` are excluded.

        From `SHORTLISTED`, the entry moves `SHORTLISTED → ELIMINATED` with `elimination_reason` stored, and the parent event's `shortlisted_venue_count` decreases by 1.

        Design: Corner/calculations/shortlisted_venue_count_filters_the_input_set_by_entry_state
        """
        world = _build_four_entry_event()
        entry_one, entry_two, entry_three, entry_four = world["entry_ids"]

        eliminated = fixtures.eliminate_entry(
            entry_three,
            elimination_reason="Space configuration cannot host the general session.",
        )

        domain_assert.assert_fields_equal(eliminated, {"status": "ELIMINATED"})
        event = fixtures.read_event(world["event_id"])
        domain_assert.assert_integer(
            event["shortlisted_venue_count"], 2, "shortlisted_venue_count"
        )
        domain_assert.assert_fields_equal(
            fixtures.read_entry(entry_one), {"status": "CANDIDATE"}
        )
        domain_assert.assert_fields_equal(
            fixtures.read_entry(entry_two), {"status": "SHORTLISTED"}
        )
        domain_assert.assert_fields_equal(
            fixtures.read_entry(entry_four), {"status": "INSPECTION_SCHEDULED"}
        )

    def test_the_entry_collection_still_returns_every_row(self):
        """The rollup filters the rows it counts; the collection keeps them all.

        When that live set is empty, `best_total_cost_usd` is null.

        Design: Corner/calculations/shortlisted_venue_count_filters_the_input_set_by_entry_state
        """
        world = _build_four_entry_event()
        entry_three = world["entry_ids"][2]
        fixtures.eliminate_entry(
            entry_three,
            elimination_reason="Space configuration cannot host the general session.",
        )

        rows, meta = validate_paginated(
            api_client.list_shortlist_entries(
                PLANNER_HEADERS, {"event_id": world["event_id"]}
            )
        )

        assert len(rows) == 4, f"expected all four entries to be listed, got {len(rows)}"
        domain_assert.assert_integer(meta["total_count"], 4, "total_count")
        event = fixtures.read_event(world["event_id"])
        domain_assert.assert_nulls(event, ["best_total_cost_usd", "awarded_proposal_id"])


def _file_report_on_the_executed_contract():
    """Execute the canonical contract and file the closeout report against it."""
    world = fixtures.build_executed_contract()
    fixtures.set_clock("2027-03-19T00:00:00.000Z")
    world["report"] = fixtures.file_post_event_report(
        world["event_id"],
        actual_room_nights=400,
        actual_fnb_usd=132000.00,
        actual_av_usd=19500.00,
        notes="Attendance came in 187 room nights below the block.",
    )
    return world


class TestPostEventReconciliation:
    """The closeout report's reconciliation and the two savings figures."""

    def test_attrition_and_realized_lines_of_the_report(self):
        """The reconciliation reads the contract's snapshots, not the winning bid.

        `attrition_allowed_nights` is the contract's `contracted_paid_room_nights` multiplied by one minus its `attrition_allowance_pct`, floored to a whole number, so a fractional allowance never rounds up in the group's favour.

        `realized_service_charge_usd` is the sum of `actual_room_cost_usd`, `actual_fnb_usd` and `actual_av_usd`, multiplied by the contract's `service_charge_pct`, rounded to 2 decimal places — the realized resort fee is outside the service-charge base, exactly as it was at bid time.

        Design: Corner/calculations/post_event_savings_report_produces_the_pinned_literals
        """
        world = _file_report_on_the_executed_contract()
        report = world["report"]

        domain_assert.assert_integer(
            report["attrition_allowed_nights"], 469, "attrition_allowed_nights"
        )
        domain_assert.assert_integer(
            report["attrition_shortfall_nights"], 69, "attrition_shortfall_nights"
        )
        domain_assert.assert_money_field(report, "attrition_charge_usd", 13744.80)
        domain_assert.assert_money_field(report, "actual_room_cost_usd", 99600.00)
        domain_assert.assert_money_field(report, "realized_service_charge_usd", 60264.00)
        domain_assert.assert_money_field(report, "realized_tax_usd", 49695.98)
        domain_assert.assert_money_field(report, "realized_total_usd", 370311.74)
        domain_assert.assert_integer(
            report["actual_room_nights"], 400, "actual_room_nights"
        )
        domain_assert.assert_money_field(report, "actual_fnb_usd", 132000.00)
        domain_assert.assert_money_field(report, "actual_av_usd", 19500.00)

    def test_savings_figures_and_the_closeout_rollups(self):
        """Filing the report closes the event against actuals and releases the block.

        `benchmark_room_cost_usd` is the benchmark's `benchmark_adr_usd` multiplied by `actual_room_nights`, rounded to 2 decimal places, and `savings_vs_benchmark_usd` is `benchmark_room_cost_usd` minus `actual_room_cost_usd`, rounded to 2 decimal places: this is what the negotiation earned against the market rate, and it is a rooms-only comparison.

        Filing the report then moves the event `CONTRACTED → COMPLETED`, sets its `savings_recognized_usd` to the report's `savings_vs_budget_usd`, sets its `committed_spend_usd` to `realized_total_usd` with `budget_remaining_usd` recomputed so the money identity still holds against actuals rather than against the contracted estimate, decreases the venue's `blocked_room_nights` by the contract's `contracted_paid_room_nights` since the rooms have now been consumed, and advances the event's `version` by 1.

        Design: Corner/calculations/post_event_savings_report_produces_the_pinned_literals
        """
        world = _file_report_on_the_executed_contract()
        report = world["report"]

        domain_assert.assert_money_field(report, "benchmark_room_cost_usd", 104000.00)
        domain_assert.assert_money_field(report, "savings_vs_benchmark_usd", 4400.00)
        domain_assert.assert_money_field(report, "savings_vs_budget_usd", 129688.26)
        event = fixtures.read_event(world["event_id"])
        domain_assert.assert_fields_equal(event, {"status": "COMPLETED"})
        domain_assert.assert_money_field(event, "savings_recognized_usd", 129688.26)
        domain_assert.assert_money_field(event, "committed_spend_usd", 370311.74)
        domain_assert.assert_money_field(event, "budget_remaining_usd", 129688.26)
        domain_assert.assert_budget_envelope(event)
        domain_assert.assert_room_night_inventory(
            fixtures.read_venue(world["venue_id"]), 0
        )


def _route_conditional_narrow_contract():
    """Award and route a contract from a conditional venue offering narrow force majeure."""
    world = fixtures.build_awarded_contract(
        venue_overrides={"preferred_supplier_status": "CONDITIONAL"},
        bid_overrides={"force_majeure_scope": "NARROW"},
    )
    world["contract"] = fixtures.route_contract(world["contract_id"])
    world["steps"] = fixtures.approval_steps(world["contract_id"])
    return world


class TestApprovalRouteGeneration:
    """The route is assembled from the programme standing, the total and the clause."""

    def test_the_route_carries_four_steps_in_the_pinned_order(self):
        """A conditional standing prepends the programme control and the narrow clause adds legal.

        `PROGRAM_COMPLIANCE` is included, and always placed first when present, when the venue's `preferred_supplier_status` is `NONE` or `CONDITIONAL`.

        `LEGAL` is included when `contracted_total_usd` is at or above `500000.00`, or when the contract's `force_majeure_scope` is `NARROW`.

        Each step records its `approval_level` and the `required_role` that may decide it: `ProgramAdmin` for `PROGRAM_COMPLIANCE`, and `ContractApprover` for `MANAGER`, `VP` and `LEGAL`.

        Design: Corner/calculations/approval_route_applies_both_thresholds_and_the_narrow_force_majeure_rule
        """
        world = _route_conditional_narrow_contract()
        steps = world["steps"]

        domain_assert.assert_fields_equal(
            world["contract"], {"approval_state": "IN_APPROVAL"}
        )
        domain_assert.assert_integer(
            world["contract"]["approval_step_count"], 4, "approval_step_count"
        )
        assert len(steps) == 4, f"expected a four-step route, got {len(steps)}"
        domain_assert.assert_sequence(steps, "step_seq", [1, 2, 3, 4])
        domain_assert.assert_sequence(
            steps,
            "approval_level",
            ["PROGRAM_COMPLIANCE", "MANAGER", "VP", "LEGAL"],
        )
        domain_assert.assert_sequence(
            steps,
            "required_role",
            ["ProgramAdmin", "ContractApprover", "ContractApprover", "ContractApprover"],
        )
        for step in steps:
            domain_assert.assert_fields_equal(step, {"decision": "PENDING"})
            domain_assert.assert_nulls(step, ["approver_user_id", "decided_at"])

    def test_the_vp_threshold_is_cleared_while_the_legal_threshold_is_not(self):
        """The contracted total is the rebated figure the two thresholds are read against.

        Both threshold comparisons are inclusive, so a `contracted_total_usd` of exactly `250000.00` adds the `VP` step and exactly `500000.00` adds the `LEGAL` step.

        Then `volume_rebate_usd` is `pre_rebate_total_usd` multiplied by `volume_rebate_pct`, rounded to 2 decimal places, and `contracted_total_usd` is `pre_rebate_total_usd` minus `volume_rebate_usd`, rounded to 2 decimal places.

        Design: Corner/calculations/approval_route_applies_both_thresholds_and_the_narrow_force_majeure_rule
        """
        world = _route_conditional_narrow_contract()
        contract = world["contract"]

        domain_assert.assert_money_field(contract, "pre_rebate_total_usd", 447844.84)
        domain_assert.assert_money_field(contract, "volume_rebate_usd", 15674.57)
        domain_assert.assert_money_field(contract, "contracted_total_usd", 432170.27)
        assert contract["volume_rebate_pct"] == 0.035, (
            f"volume_rebate_pct: expected 0.035, got {contract['volume_rebate_pct']}"
        )


def _terminate_at_one_hundred_and_eighty_one_days():
    """Execute the canonical contract, then terminate it 181 days before arrival."""
    world = fixtures.build_executed_contract()
    fixtures.set_clock("2026-09-15T00:00:00.000Z")
    world["contract"] = fixtures.terminate_contract(
        world["contract_id"],
        termination_reason="Sponsor cancelled the programme.",
    )
    return world


class TestCancellationLadder:
    """The tier selection at the boundary and the credit that rides on the fee."""

    def test_the_fee_takes_the_quarter_tier_at_exactly_the_boundary(self):
        """Exactly 181 days out the 181-day row governs rather than the next row down.

        The comparison is inclusive, so being exactly 181 days out selects a tier whose `days_before_arrival_min` is 181 rather than falling to the next tier down.

        Then `cancellation_fee_usd` is the contract's `contracted_room_revenue_usd` multiplied by that tier's `fee_pct`, rounded to 2 decimal places.

        Finally `rebooking_credit_usd` is `cancellation_fee_usd` multiplied by the contract's `rebooking_credit_pct`, rounded to 2 decimal places — the credit is a share of the fee charged, not of the contract value.

        `terminated_at` is stamped from the logical clock and the contract moves `signature_state` `EXECUTED → TERMINATED`.

        Design: Corner/calculations/cancellation_fee_at_exactly_181_days_takes_the_quarter_tier
        """
        world = _terminate_at_one_hundred_and_eighty_one_days()
        contract = world["contract"]

        domain_assert.assert_money_field(contract, "contracted_room_revenue_usd", 146163.00)
        domain_assert.assert_money_field(contract, "cancellation_fee_usd", 36540.75)
        domain_assert.assert_money_field(contract, "rebooking_credit_usd", 21924.45)
        domain_assert.assert_fields_equal(
            contract,
            {
                "signature_state": "TERMINATED",
                "terminated_at": "2026-09-15T00:00:00.000Z",
                "termination_reason": "Sponsor cancelled the programme.",
            },
        )

    def test_termination_moves_the_commitment_into_the_liability_line(self):
        """The released commitment reappears as liability and the room block returns.

        The event's `committed_spend_usd` returns to `0.00`, its `cancellation_liability_usd` increases by the `cancellation_fee_usd`, its `budget_remaining_usd` is recomputed so the money identity of section 2.10 still holds, and the event moves `CONTRACTED → CANCELLED`.

        The venue's `blocked_room_nights` decreases by the contract's `contracted_paid_room_nights`, restoring the room-night identity of section 2.10.

        Design: Corner/calculations/cancellation_fee_at_exactly_181_days_takes_the_quarter_tier
        """
        world = _terminate_at_one_hundred_and_eighty_one_days()

        event = fixtures.read_event(world["event_id"])
        domain_assert.assert_money_field(event, "committed_spend_usd", 0.00)
        domain_assert.assert_money_field(event, "cancellation_liability_usd", 36540.75)
        domain_assert.assert_money_field(event, "budget_remaining_usd", 463459.25)
        domain_assert.assert_fields_equal(event, {"status": "CANCELLED"})
        domain_assert.assert_budget_envelope(event)
        domain_assert.assert_room_night_inventory(
            fixtures.read_venue(world["venue_id"]), 0
        )
