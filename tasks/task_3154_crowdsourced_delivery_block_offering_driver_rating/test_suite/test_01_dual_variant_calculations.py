"""Dual-variant calculations: provisional vs final pay; rolling vs lifetime rating."""

from test_helpers import (
    TEST_USERS,
    set_clock,
    create_station,
    onboard_active_driver,
    warmup_clean_completion,
    complete_block_flow,
    setup_settlement_scenario,
    complete,
    get_driver,
)


class TestPayVariantsDiverge:
    def test_provisional_and_final_pay_diverge_for_identical_block_data(self, api):
        """PRD §3.3: "The assignment's `provisional_pay_cents` is the provisional pay variant:
        the block's base pay multiplied by the frozen surge snapshot and divided by 10000,
        rounded half-up to whole cents. It deliberately excludes tier bonuses, handling
        surcharges, and penalties — it is the estimate shown to the driver before work
        begins, and it diverges from the final settlement whenever any bonus, surcharge,
        or penalty is nonzero."
        PRD §3.6: "Finally, `final_pay_cents` is gross plus tier bonus plus surcharges
        minus the capped penalties."

        Design: Difficulty/dual_variant_calc/settlement_pay_provisional_estimate_diverges_from_final
        """
        (
            _station,
            driver,
            _vehicle,
            _block,
            assignment,
            _packages,
            provisional,
        ) = setup_settlement_scenario()

        assert provisional == 7500, (
            f"provisional variant should be round_half_up(6000 * 12500 / 10000) = 7500, "
            f"got {provisional}"
        )

        ps = complete(assignment["id"])
        assert ps["final_pay_cents"] == 8521, (
            f"final variant should be 7500 + 750 + 621 - 350 = 8521, got {ps['final_pay_cents']}"
        )
        assert ps["final_pay_cents"] - provisional == 1021

    def test_assignment_carries_provisional_variant_at_acceptance(self, api):
        """PRD §3.3: "The assignment's `provisional_pay_cents` is the provisional pay variant:
        the block's base pay multiplied by the frozen surge snapshot and divided by 10000,
        rounded half-up to whole cents."

        Design: Difficulty/dual_variant_calc/settlement_pay_provisional_estimate_diverges_from_final
        """
        (
            _station,
            _driver,
            _vehicle,
            _block,
            assignment,
            _packages,
            provisional,
        ) = setup_settlement_scenario()

        assert assignment["provisional_pay_cents"] == 7500
        assert provisional == 7500
        assert assignment["surge_multiplier_snapshot_bp"] == 12500


class TestRatingVariantsDiverge:
    def test_rolling_and_lifetime_ratings_diverge_over_same_history(self, api):
        """PRD §2.8: "`rating_score_x100` is recomputed from rating events: it is the
        round-half-up average of `points` over all of the driver's rating events whose
        `event_at` falls within the last 90 days inclusive, and it is 0 when the window
        is empty."
        PRD §2.8: "A separate lifetime value, `lifetime_rating_x100`, is exposed on the
        driver profile: it is a recency-weighted average over all rating events
        regardless of age, where an event 30 or fewer days old weighs 100, an event
        between 31 and 90 days old weighs 50, and an event older than 90 days weighs 25;
        the value is the round-half-up quotient of the sum of each event's `points`
        times its weight over the sum of the weights, and 0 when the driver has no
        events at all."

        Design: Difficulty/dual_variant_calc/rating_rolling_window_diverges_from_lifetime_weighted
        """
        set_clock("2026-05-10T00:00:00Z")
        station = create_station()
        driver, vehicle, _s = onboard_active_driver(clock="2026-05-10T00:00:00Z")

        # Event 1: clean completion on 2026-05-20 (500 points).
        warmup_clean_completion(
            station,
            driver,
            vehicle,
            starts_at="2026-05-20T02:00:00Z",
            ends_at="2026-05-20T04:00:00Z",
            promised_by="2026-05-20T03:00:00Z",
            deliver_at="2026-05-20T02:30:00Z",
        )

        # Event 2: one-late-package completion on 2026-08-20 (400 points).
        complete_block_flow(
            station,
            driver,
            vehicle,
            starts_at="2026-08-20T10:00:00Z",
            ends_at="2026-08-20T12:00:00Z",
            package_specs=[
                {
                    "tracking_code": "R2-1",
                    "billable_weight_kg": 1.0,
                    "promised_by": "2026-08-20T11:00:00Z",
                    "outcome": "deliver",
                    "deliver_at": "2026-08-20T11:05:00Z",
                }
            ],
        )

        set_clock("2026-09-01T00:00:00Z")
        profile = get_driver(driver["id"])

        # Rolling window (90 days inclusive from 2026-09-01) contains only the
        # 400-point event: the 500-point event of 2026-05-20 is 103 days old.
        assert profile["rating_score_x100"] == 400, (
            f"rolling 90d rating should be 400, got {profile['rating_score_x100']}"
        )
        # Lifetime: round_half_up((400*100 + 500*25) / (100 + 25)) = round_half_up(420) = 420.
        assert profile["lifetime_rating_x100"] == 420, (
            f"lifetime weighted rating should be 420, got {profile['lifetime_rating_x100']}"
        )

    def test_rolling_window_excludes_stale_events_lifetime_keeps_them(self, api):
        """PRD §2.8: "Because the rolling value excludes old events entirely while the
        lifetime value keeps them at reduced weight, the two produce different numbers
        whenever events older than 90 days exist."

        Design: Difficulty/dual_variant_calc/rating_rolling_window_diverges_from_lifetime_weighted
        """
        set_clock("2026-05-10T00:00:00Z")
        station = create_station()
        driver, vehicle, _s = onboard_active_driver(clock="2026-05-10T00:00:00Z")

        warmup_clean_completion(
            station,
            driver,
            vehicle,
            starts_at="2026-05-20T02:00:00Z",
            ends_at="2026-05-20T04:00:00Z",
            promised_by="2026-05-20T03:00:00Z",
            deliver_at="2026-05-20T02:30:00Z",
        )
        complete_block_flow(
            station,
            driver,
            vehicle,
            starts_at="2026-08-20T10:00:00Z",
            ends_at="2026-08-20T12:00:00Z",
            package_specs=[
                {
                    "tracking_code": "R2-1",
                    "billable_weight_kg": 1.0,
                    "promised_by": "2026-08-20T11:00:00Z",
                    "outcome": "deliver",
                    "deliver_at": "2026-08-20T11:05:00Z",
                }
            ],
        )

        set_clock("2026-09-01T00:00:00Z")
        profile = get_driver(driver["id"])

        assert profile["rating_score_x100"] != profile["lifetime_rating_x100"]
        assert profile["rating_score_x100"] == 400
        assert profile["lifetime_rating_x100"] == 420
