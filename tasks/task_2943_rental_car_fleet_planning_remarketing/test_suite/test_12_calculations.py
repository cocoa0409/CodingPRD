"""Four arithmetic claims read end to end: a clamp, a threshold, a split and a
ranking.

Each one is checked at the value the rule actually turns on, and each is read
back through the endpoint that exposes the computed figure rather than inferred
from a side effect.
"""

from test_helpers import (
    AppliedVariant,
    ApiErrorId,
    ChannelCode,
    ChannelStatus,
    ConditionStatus,
    DamageStatus,
    EntryType,
    MileageBand,
    SourceEntityType,
    factories,
    fixtures,
    make_remarketing_manager_headers,
    validate_error,
    validate_success,
)
from test_helpers.assertions import (
    assert_channel_recommendation,
    assert_valuation,
    entries_of_type,
)


class TestPolicyScheduleFloor:
    """A car driven hard enough sits exactly on its floor residual."""

    def test_the_schedule_stops_at_the_floor_and_discards_the_excess_decay(
        self, client, world
    ):
        """Fifteen months and a hundred thousand kilometres overshoot the floor.

        PRD 3.5: "`policy_net_book_value_cents` is then the larger of two figures:
        the capitalized cost minus the sum of the time and mileage decay, and the
        floor value."
        PRD 3.5: "The clamp is what keeps a very high-mileage unit from depreciating
        below its salvage worth, and a unit driven hard enough sits exactly on the
        floor with the excess decay simply discarded."
        PRD 3.5: "`accumulated_depreciation_cents` is the capitalized cost minus the
        applied `net_book_value_cents`, so it too follows the pinned choice."
        PRD 3.5: "it is `OVER_HARD` when `odometer_km` is strictly greater than the
        segment's `mileage_band_hard_limit_km`"

        Design: Corner/calculations/policy_schedule_net_book_value_clamped_at_floor_residual_pct
        """
        built = fixtures.setup_in_service_vehicle(
            client,
            world,
            market_code="ATL",
            program_key="RSK",
            vin_prefix="FL",
            in_service_clock="2026-01-15T00:00:00Z",
        )
        vehicle_id = built["vehicle"]["id"]

        fixtures.set_clock(client, "2027-04-15T00:00:00Z")
        fixtures.post_usage(
            client,
            world,
            vehicle_id,
            100000,
            rented_days_delta=300,
            available_days_delta=400,
            revenue_cents_delta=1650000,
        )

        valuation = fixtures.read_valuation(client, vehicle_id)
        assert_valuation(valuation)
        assert valuation["holding_days"] == 455
        assert valuation["holding_months"] == 15
        assert valuation["capitalized_cost_cents"] == 2800000
        assert valuation["policy_net_book_value_cents"] == 980000
        assert valuation["applied_variant"] == AppliedVariant.POLICY_SCHEDULE
        assert valuation["net_book_value_cents"] == 980000
        assert valuation["accumulated_depreciation_cents"] == 1820000
        assert valuation["mileage_band"] == MileageBand.OVER_HARD
        assert valuation["program_guaranteed_value_cents"] == 0


class TestTotalLossThreshold:
    """The ratio test is inclusive at seventy percent and recomputes both ways."""

    def _reported_event(self, client, world, estimate_cents):
        built = fixtures.setup_in_service_vehicle(
            client,
            world,
            market_code="ATL",
            program_key="RSK",
            vin_prefix="TH",
            in_service_clock="2026-01-15T00:00:00Z",
        )
        vehicle_id = built["vehicle"]["id"]
        event = fixtures.report_damage(client, world, vehicle_id, estimate_cents)
        return vehicle_id, event

    def test_the_flag_flips_in_both_directions_around_the_exact_boundary(
        self, client, world
    ):
        """One cent short is not a total loss; the exact point is.

        PRD 3.7: "`total_loss_required` is then decided by the **ratio test**, and
        the test is deliberately pure integer cross-multiplication with no floating
        point and therefore no rounding at the boundary: the event requires a
        total-loss determination when `estimate_cents` multiplied by ten thousand is
        **greater than or equal to** `net_book_value_at_report_cents` multiplied by
        seven thousand."
        PRD 3.7: "In plain terms, a repair estimate reaching seventy percent of the
        frozen book value is a total loss, and the exact seventy-percent point counts
        as one."

        Design: Corner/calculations/total_loss_flag_flips_at_exactly_seventy_percent_of_the_frozen_baseline
        """
        _vehicle_id, event = self._reported_event(client, world, 1959999)
        assert event["net_book_value_at_report_cents"] == 2800000
        assert event["total_loss_required"] is False

        at_the_point = fixtures.revise_estimate(client, world, event["id"], 1960000)
        assert at_the_point["total_loss_required"] is True

        one_cent_short = fixtures.revise_estimate(client, world, event["id"], 1959999)
        assert one_cent_short["total_loss_required"] is False

    def test_the_baseline_is_never_re_frozen_by_a_later_revision(
        self, client, world
    ):
        """Eight months of depreciation must not turn a stale claim into a write-off.

        PRD 3.7: "The revision replaces `estimate_cents`, recomputes
        `total_loss_required` **against the unchanged `net_book_value_at_report_cents`
        baseline**, leaves `status` exactly where it was — this is a self-loop, not a
        transition — and increments the event's `version` by 1."
        PRD 3.7: "The baseline is emphatically **not** re-frozen: months of
        depreciation may have passed since the report, and re-freezing would let a
        stale claim become a total loss purely through the passage of time."

        Design: Corner/calculations/total_loss_flag_flips_at_exactly_seventy_percent_of_the_frozen_baseline
        """
        _vehicle_id, event = self._reported_event(client, world, 1959999)
        assert event["version"] == 1

        fixtures.set_clock(client, "2026-09-15T00:00:00Z")
        revised = fixtures.revise_estimate(client, world, event["id"], 1800000)
        assert revised["net_book_value_at_report_cents"] == 2800000
        assert revised["total_loss_required"] is False
        assert revised["status"] == DamageStatus.REPORTED

        fixtures.revise_estimate(client, world, event["id"], 1960000)
        final = fixtures.revise_estimate(client, world, event["id"], 1959999)
        assert final["status"] == DamageStatus.REPORTED
        assert final["version"] == 4
        assert final["net_book_value_at_report_cents"] == 2800000


class TestRecoveryWaterfall:
    """Three ordered buckets that always re-sum to the recovered money."""

    def _recovery_pending_event(self, client, world):
        built = fixtures.setup_in_service_vehicle(
            client,
            world,
            market_code="ATL",
            program_key="RSK",
            vin_prefix="WF",
            in_service_clock="2026-01-15T00:00:00Z",
        )
        vehicle_id = built["vehicle"]["id"]
        event = fixtures.report_damage(client, world, vehicle_id, 400000)
        assert event["total_loss_required"] is False
        opened = fixtures.open_recovery(client, event["id"])
        assert opened["status"] == DamageStatus.RECOVERY_PENDING
        return vehicle_id, event

    def test_the_cap_is_an_inclusive_ceiling_one_cent_wide(self, client, world):
        """Five hundred thousand and one is refused; five hundred thousand settles.

        PRD 3.7: "The recovery is capped first: the ceiling is `estimate_cents`
        multiplied by 1.25, rounded half up, and a `recovered_cents` strictly above it
        is refused with `ERR_RECOVERY_EXCEEDS_CAP` (HTTP 422) — an insurer may pay a
        modest premium over the estimate but not an unbounded one."

        Design: Corner/calculations/recovery_waterfall_fills_recondition_then_depreciation_then_income
        """
        _vehicle_id, event = self._recovery_pending_event(client, world)

        validate_error(
            client.settle_damage_recovery(
                event["id"],
                factories.settle_recovery_payload(500001),
                make_remarketing_manager_headers(),
            ),
            ApiErrorId.RECOVERY_EXCEEDS_CAP,
        )
        assert (
            fixtures.read_damage_event(client, event["id"])["status"]
            == DamageStatus.RECOVERY_PENDING
        )

        settled = fixtures.settle_recovery(client, event["id"], 500000)
        assert settled["status"] == DamageStatus.RECOVERED
        assert settled["recovered_cents"] == 500000

    def test_the_buckets_fill_in_order_and_leave_no_remainder(self, client, world):
        """An unreconditioned car sends nothing to bucket one and the rest to income.

        PRD 3.7: "Bucket one, `recovery_alloc_recondition_cents`, is the smaller of
        `recovered_cents` and the vehicle's `total_recondition_cents`: reconditioning
        money already spent on the car is reimbursed first."
        PRD 3.7: "Bucket two, `recovery_alloc_depreciation_cents`, is the smaller of
        what remains after bucket one and the quantity `estimate_cents` minus the
        vehicle's `total_recondition_cents` floored at zero: the unreimbursed portion
        of the repair estimate absorbs the next slice."
        PRD 3.7: "Bucket three, `recovery_alloc_income_cents`, is everything still
        left over — `recovered_cents` minus the first two buckets — and it falls to
        income."
        PRD 3.7: "The three buckets sum to `recovered_cents` exactly and always."

        Design: Corner/calculations/recovery_waterfall_fills_recondition_then_depreciation_then_income
        """
        vehicle_id, event = self._recovery_pending_event(client, world)
        assert fixtures.read_vehicle(client, vehicle_id)["total_recondition_cents"] == 0

        settled = fixtures.settle_recovery(client, event["id"], 500000)
        assert settled["recovery_alloc_recondition_cents"] == 0
        assert settled["recovery_alloc_depreciation_cents"] == 400000
        assert settled["recovery_alloc_income_cents"] == 100000
        assert (
            settled["recovery_alloc_recondition_cents"]
            + settled["recovery_alloc_depreciation_cents"]
            + settled["recovery_alloc_income_cents"]
            == 500000
        )

    def test_settlement_credits_the_ledger_once_and_clears_the_condition(
        self, client, world
    ):
        """A single negative row carries the split, and the car reads SOUND again.

        PRD 3.7: "Settlement posts a single ledger line of `entry_type`
        `DAMAGE_RECOVERY` for a **negative** `amount_cents` equal to `recovered_cents`
        — money coming back is a credit against the unit's cost basis — with
        `source_entity_type` `DamageEvent` and a `memo` recording the three-bucket
        split, increments the event's `version` by 1, and triggers the conditional
        condition cascade described below."
        PRD 3.7: "When an event reaches `RECOVERED` or `WRITTEN_OFF`, the system
        counts the vehicle's remaining damage events whose `status` is `REPORTED` or
        `RECOVERY_PENDING`; if that count is zero **after** the triggering transition
        and the vehicle's `condition_status` is still `DAMAGE_REPORTED`, the vehicle
        moves `DAMAGE_REPORTED → SOUND` with its `version` incremented by 1."

        Design: Corner/calculations/recovery_waterfall_fills_recondition_then_depreciation_then_income
        """
        vehicle_id, event = self._recovery_pending_event(client, world)
        assert (
            fixtures.read_vehicle(client, vehicle_id)["condition_status"]
            == ConditionStatus.DAMAGE_REPORTED
        )

        fixtures.settle_recovery(client, event["id"], 500000)

        rows = entries_of_type(
            fixtures.read_ledger(client, vehicle_id), EntryType.DAMAGE_RECOVERY
        )
        assert len(rows) == 1
        assert rows[0]["amount_cents"] == -500000
        assert rows[0]["source_entity_type"] == SourceEntityType.DAMAGE_EVENT
        assert rows[0]["source_entity_id"] == event["id"]
        assert isinstance(rows[0]["memo"], str) and rows[0]["memo"]

        assert (
            fixtures.read_vehicle(client, vehicle_id)["condition_status"]
            == ConditionStatus.SOUND
        )


class TestChannelRanking:
    """A richer multiplier beats a cheaper fee schedule, until the channel closes."""

    def _car_ready_for_disposal(self, client):
        world = fixtures.setup_reference_world(
            client,
            channel_payloads=[factories.CHANNEL_AUCTION, factories.CHANNEL_RETAIL_LOT],
        )
        built = fixtures.setup_in_service_vehicle(
            client,
            world,
            market_code="ATL",
            program_key="RSK",
            vin_prefix="RK",
            in_service_clock="2026-01-15T00:00:00Z",
        )
        vehicle_id = built["vehicle"]["id"]
        fixtures.set_clock(client, "2026-09-15T00:00:00Z")
        fixtures.post_usage(
            client,
            world,
            vehicle_id,
            60000,
            rented_days_delta=180,
            available_days_delta=243,
            revenue_cents_delta=990000,
        )
        return world, vehicle_id

    def test_the_retail_lot_wins_on_projected_net_proceeds(self, client):
        """It nets more despite paying a reconditioning line the auction avoids.

        PRD 3.8: "Projected gross is the vehicle's `net_book_value_cents` multiplied
        by the channel's `expected_proceeds_multiplier`, rounded half up."
        PRD 3.8: "Projected fee is that projected gross multiplied by the channel's
        `fee_pct`, rounded half up, **plus** the channel's `fixed_fee_cents` — the
        fixed component is added after the rounding and is never itself rounded."
        PRD 3.8: "Projected reconditioning is zero when the channel's
        `recondition_required` is false, and otherwise the smaller of the segment's
        `recondition_cap_cents` and the vehicle's `capitalized_cost_cents` multiplied
        by 0.02 rounded half up — two percent of the purchase price is the planning
        estimate, and the segment cap binds it."
        PRD 3.8: "Candidates are ranked by `projected_net_proceeds_cents`
        **descending**."

        Design: Corner/calculations/channel_ranking_prefers_retail_lot_until_it_is_suspended
        """
        world, vehicle_id = self._car_ready_for_disposal(client)
        assert (
            fixtures.read_valuation(client, vehicle_id)["net_book_value_cents"]
            == 1744000
        )

        recommendation = validate_success(
            client.get_channel_recommendation(
                vehicle_id, make_remarketing_manager_headers()
            )
        )
        assert_channel_recommendation(recommendation)
        assert recommendation["eligible_channel_count"] == 2
        assert recommendation["recommended_channel_id"] == world.channel_id("RETAIL_LOT")
        assert recommendation["recommended_channel_code"] == ChannelCode.RETAIL_LOT
        assert recommendation["projected_net_proceeds_cents"] == 1704401
        assert recommendation["ranked_channel_codes"] == [
            ChannelCode.RETAIL_LOT,
            ChannelCode.AUCTION,
        ]
        assert recommendation["excluded_channel_codes"] == []

    def test_suspending_the_winner_hands_the_recommendation_to_the_auction(
        self, client
    ):
        """A suspended channel leaves the pool and the runner-up's figure surfaces.

        PRD 3.8: "The **eligibility filter** admits a channel only if its `status` is
        `ACTIVE`; a `SUSPENDED` channel never enters the pool at all."
        PRD 3.1: "Suspending a channel moves its `status` from `ACTIVE` to
        `SUSPENDED`, is permitted only from `ACTIVE`, increments its `version`, and
        removes it from every vehicle's candidate pool for channel selection."
        PRD 3.8: "`projected_net_proceeds_cents` is the projected gross minus the fee,
        minus the transport and minus the reconditioning, and the subtraction is exact
        integer arithmetic."

        Design: Corner/calculations/channel_ranking_prefers_retail_lot_until_it_is_suspended
        """
        world, vehicle_id = self._car_ready_for_disposal(client)
        before = validate_success(
            client.get_channel_recommendation(
                vehicle_id, make_remarketing_manager_headers()
            )
        )
        assert before["recommended_channel_code"] == ChannelCode.RETAIL_LOT

        suspended = fixtures.suspend_channel(client, world.channel_id("RETAIL_LOT"))
        assert suspended["status"] == ChannelStatus.SUSPENDED

        after = validate_success(
            client.get_channel_recommendation(
                vehicle_id, make_remarketing_manager_headers()
            )
        )
        assert_channel_recommendation(after)
        assert after["eligible_channel_count"] == 1
        assert after["recommended_channel_id"] == world.channel_id("AUCTION")
        assert after["recommended_channel_code"] == ChannelCode.AUCTION
        assert after["projected_net_proceeds_cents"] == 1476598
        assert after["ranked_channel_codes"] == [ChannelCode.AUCTION]
        assert ChannelCode.RETAIL_LOT in after["excluded_channel_codes"]
