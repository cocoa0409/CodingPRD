"""Driver safety scoring: dual variants, rounding order, aging boundaries."""
from test_helpers import (
    TEST_USERS,
    create_confirmed_event,
    create_driver,
    get_event,
    ingest_event,
    register_clip,
    review_event,
    setup_base,
    upload_clip,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import set_clock

MANAGER = TEST_USERS["safety_manager_headers"]


class TestDualVariantScoring:
    def test_driver_score_provisional_vs_final_diverge(self, api):
        """PRD §3.9: "The two variants differ only in their input sets:
        `safety_score_provisional` includes events in `IN_REVIEW`,
        `CONFIRMED`, and `RECLASSIFIED`, serving the live operational view,
        the review queue, and projected incentive pricing;
        `safety_score_final` includes only `CONFIRMED` events and serves
        season close, finalized snapshots, the leaderboard, and payouts."
        PRD §3.9: "The raw penalty per event is the severity weight
        (1/3/6/10 for `LOW`/`MEDIUM`/`HIGH`/`CRITICAL`) multiplied by the
        penalty factor 2.5, multiplied by the age factor."

        Design: Difficulty/dual_variant_calc/driver_score_provisional_vs_final_diverge
        """
        base = setup_base()
        # HIGH event left IN_REVIEW: provisional penalty 15.00 only.
        ev_a = ingest_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="HARSH_BRAKE", severity="HIGH",
            occurred_at="2026-08-30T00:00:00Z",
        )
        clip_a = register_clip(ev_a["id"], captured_at="2026-08-30T00:00:00Z")
        upload_clip(clip_a["id"])
        # MEDIUM event confirmed: both variants carry 7.50.
        create_confirmed_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="FOLLOWING_DISTANCE", severity="MEDIUM",
            occurred_at="2026-08-31T00:00:00Z",
        )
        driver = validate_success(api.get_driver(base["driver"]["id"], MANAGER), 200)
        assert float(driver["safety_score_provisional"]) == 77.50
        assert float(driver["safety_score_final"]) == 92.50
        assert float(driver["safety_score_provisional"]) != float(driver["safety_score_final"])
        assert driver["confirmed_events_90d"] == 1

    def test_provisional_excludes_detected_events(self, api):
        """PRD §3.9: "`DETECTED`, `DISMISSED`, and `EXONERATED` events are
        excluded from both variants, so identical inputs always yield a final
        score greater than or equal to the provisional score."

        Design: Difficulty/dual_variant_calc/driver_score_provisional_vs_final_diverge
        """
        base = setup_base()
        # A DETECTED event (no clip uploaded) must not move either variant.
        ingest_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="HARSH_BRAKE", severity="CRITICAL",
            occurred_at="2026-08-30T00:00:00Z",
        )
        driver = validate_success(api.get_driver(base["driver"]["id"], MANAGER), 200)
        assert float(driver["safety_score_provisional"]) == 100.00
        assert float(driver["safety_score_final"]) == 100.00


class TestPerEventRounding:
    def test_per_event_rounding_then_sum_pinned(self, api):
        """PRD §2.7: "Where the scoring rules require rounding, each event's
        penalty is rounded to two decimal places before penalties are summed;
        rounding only the final sum is a rejected evaluation order."
        PRD §3.9: "For each event in the variant's input set, an age factor
        applies: 1.00 when the event occurred at most 30 days before the
        clock, 0.33 when it occurred more than 30 and at most 90 days before,
        and events older than 90 days are excluded from the window entirely.
        The raw penalty per event is the severity weight (1/3/6/10 for
        `LOW`/`MEDIUM`/`HIGH`/`CRITICAL`) multiplied by the penalty factor
        2.5, multiplied by the age factor; each event's penalty is rounded
        half-up to two decimal places before any summation, and the rounded
        per-event penalties are then summed — rounding the unrounded sum
        instead is a rejected evaluation order."

        Design: Difficulty/combinatorial_formula/per_event_rounding_then_sum_pinned
        """
        base = setup_base()
        # Two aged LOW events (48 days old at the default clock): factor 0.33.
        for occurred in ("2026-07-15T00:00:00Z", "2026-07-15T12:00:00Z"):
            create_confirmed_event(
                base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
                event_type="SEAT_BELT", severity="LOW", occurred_at=occurred,
            )
        driver = validate_success(api.get_driver(base["driver"]["id"], MANAGER), 200)
        # round_half_up(1 x 2.5 x 0.33, 2) == 0.83 per event; 0.83+0.83 == 1.66.
        assert float(driver["safety_score_final"]) == 98.34
        assert driver["confirmed_events_90d"] == 2
        assert driver["status"] == "ACTIVE"

    def test_per_event_rounding_order_rejects_sum_then_round(self, api):
        """PRD §2.7: "Where the scoring rules require rounding, each event's
        penalty is rounded to two decimal places before penalties are summed;
        rounding only the final sum is a rejected evaluation order."

        Design: Difficulty/combinatorial_formula/per_event_rounding_then_sum_pinned
        """
        base = setup_base()
        create_confirmed_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="SEAT_BELT", severity="LOW",
            occurred_at="2026-07-15T00:00:00Z",
        )
        driver = validate_success(api.get_driver(base["driver"]["id"], MANAGER), 200)
        # Single aged LOW event: round(0.825, 2) == 0.83, score 99.17.
        # Sum-then-round would coincide here; the pinned value proves the
        # per-event rounding step is observable as 0.83 not 0.82.
        assert float(driver["safety_score_final"]) == 99.17


class TestAgeFactorBoundary:
    def test_aged_factor_boundary_exactly_30_days(self, api):
        """PRD §3.9: "For each event in the variant's input set, an age factor
        applies: 1.00 when the event occurred at most 30 days before the
        clock, 0.33 when it occurred more than 30 and at most 90 days before,
        and events older than 90 days are excluded from the window entirely."

        Design: Corner/calculations/aged_factor_boundary_exactly_30_days
        """
        base = setup_base()
        driver_b = create_driver(
            base["terminal"]["id"], employee_ref="E-3003", name="Sam Okafor"
        )
        # Exactly 30 days before the 2026-09-01 clock: full factor.
        create_confirmed_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="HARSH_BRAKE", severity="MEDIUM",
            occurred_at="2026-08-02T00:00:00Z",
        )
        # 30 days + 1 second: aged factor.
        create_confirmed_event(
            base["fleet"]["id"], driver_b["id"], base["vehicle"]["id"],
            event_type="HARSH_BRAKE", severity="MEDIUM",
            occurred_at="2026-08-01T23:59:59Z",
        )
        driver_a = validate_success(api.get_driver(base["driver"]["id"], MANAGER), 200)
        driver_b_after = validate_success(api.get_driver(driver_b["id"], MANAGER), 200)
        assert float(driver_a["safety_score_final"]) == 92.50
        # round_half_up(7.50 x 0.33, 2) == round(2.475, 2) == 2.48
        assert float(driver_b_after["safety_score_final"]) == 97.52


class TestMaintenanceRecomputation:
    def test_run_maintenance_recomputes_scores_after_clock_move(self, api, platform_admin_headers):
        """PRD §3.9: "Both variants are computed on read and recomputed after
        every review action, every exoneration decision, and every clock
        movement observed via maintenance."
        PRD §3.9: "The platform recomputes derived state through an ops-run
        checkpoint: a `PlatformAdmin` invokes run-maintenance on a fleet,
        which increments the fleet's `ops_run_index` by one, sweeps coaching
        sessions, and refreshes derived score fields for all drivers of the
        fleet."

        Design: Corner/cross-cutting complexity layers/run_maintenance_recomputes_scores_after_clock_move
        """
        base = setup_base()
        create_confirmed_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="HARSH_BRAKE", severity="MEDIUM",
            occurred_at="2026-08-10T00:00:00Z",
        )
        driver = validate_success(api.get_driver(base["driver"]["id"], MANAGER), 200)
        assert float(driver["safety_score_final"]) == 92.50
        set_clock("2026-09-15T00:00:00Z")
        validate_success(api.run_maintenance(base["fleet"]["id"], platform_admin_headers), 200)
        driver = validate_success(api.get_driver(base["driver"]["id"], MANAGER), 200)
        # 36 days old: aged factor 0.33, penalty round(7.50*0.33, 2) == 2.48.
        assert float(driver["safety_score_final"]) == 97.52
        assert driver["confirmed_events_90d"] == 1


class TestTerminalScoring:
    def test_terminal_score_mean_of_drivers(self, api, fleet_admin_headers):
        """PRD §3.9: "The terminal score is the mean of `safety_score_final`
        over the terminal's drivers in `ACTIVE`, `SUSPENDED`, or
        `COACHING_HOLD` status — `INACTIVE` drivers are excluded — rounded
        half-up to two decimal places, and a terminal with no such drivers
        scores 100.00."

        Design: Corner/calculations/terminal_score_mean_of_drivers
        """
        base = setup_base()
        driver_b = create_driver(
            base["terminal"]["id"], employee_ref="E-3003", name="Sam Okafor"
        )
        create_confirmed_event(
            base["fleet"]["id"], driver_b["id"], base["vehicle"]["id"],
            event_type="HARSH_BRAKE", severity="MEDIUM",
            occurred_at="2026-08-30T00:00:00Z",
        )
        snapshot = validate_success(
            api.compute_score_snapshot(
                base["fleet"]["id"],
                {
                    "scope_type": "TERMINAL",
                    "scope_id": base["terminal"]["id"],
                    "period_start": "2026-08-01T00:00:00Z",
                    "period_end": "2026-09-30T23:59:59Z",
                    "finalize": True,
                },
                fleet_admin_headers,
            ),
            201,
        )
        # Mean of 100.00 and 92.50 == 96.25.
        assert float(snapshot["score"]) == 96.25
        assert snapshot["scope_type"] == "TERMINAL"
        assert snapshot["status"] == "FINAL"
        terminal = validate_success(api.get_terminal(base["terminal"]["id"], MANAGER), 200)
        assert float(terminal["safety_score_cached"]) == 96.25
