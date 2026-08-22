"""The put option, the repurchase reserve, the sweep and the obligation forecast."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_cash_conservation,
    assert_put_option_exercise,
    create_put_option_exercise_payload,
    deposit_repurchase_funding,
    fund_exercise,
    get_exercise,
    get_participant,
    get_plan,
    raise_exercise,
    set_clock,
    setup_cedar_valley_distribution,
    setup_forfeited_participant,
    setup_two_pending_exercises,
    validate_error,
    validate_paginated,
    validate_success,
)

SPONSOR = TEST_USERS["sponsor_headers"]
TRUSTEE = TEST_USERS["trustee_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestRepurchaseSweepModes:
    def test_strict_order_sweep_stops_at_the_first_exercise_that_does_not_fit(self, api):
        """PRD 3.8: "Under `STRICT_ORDER` the queue is honoured absolutely: the first exercise
        that does not fit is recorded as the stopping point, every remaining candidate behind
        it is also set to `DEFERRED` and counted as deferred, and the sweep stops — even a
        small exercise further down the queue that would have fitted is deferred rather than
        funded."
        PRD 3.8: "The sweep reports what it did: `funded_count` and `deferred_count` are the
        numbers of exercises moved each way, `funded_cents_total` is the cash committed across
        the sweep, `reserve_after_cents` is the reserve balance when the sweep finished,
        `sweep_mode_applied` echoes the mode the plan is configured with, and
        `stopped_at_exercise_id` names the exercise at which a strict-order sweep halted, or
        is null when the sweep ran to the end of the queue."

        Design: Difficulty/dual_variant_calc/repurchase_sweep_strict_order_vs_best_fit
        """
        ctx = setup_two_pending_exercises(sweep_mode="STRICT_ORDER", reserve_floor_cents=0,
                                          deposit_cents=3_000_000)

        report = validate_success(api.run_repurchase_sweep(ctx["plan"]["id"], TRUSTEE))
        assert report["funded_count"] == 0
        assert report["deferred_count"] == 2
        assert report["funded_cents_total"] == 0
        assert report["sweep_mode_applied"] == "STRICT_ORDER"
        assert report["stopped_at_exercise_id"] == ctx["ex_big"]["id"]

        assert get_exercise(ctx["ex_big"]["id"])["status"] == "DEFERRED"
        assert get_exercise(ctx["ex_small"]["id"])["status"] == "DEFERRED", (
            "the cheaper exercise behind the stopping point is deferred, not funded"
        )
        plan = get_plan(ctx["plan"]["id"])
        assert plan["repurchase_reserve_cents"] == 3_000_000
        assert plan["committed_repurchase_cents"] == 0

    def test_best_fit_sweep_funds_the_cheaper_exercise_the_strict_queue_deferred(self, api):
        """PRD 3.8: "Under `BEST_FIT` the oversized exercise is deferred and the scan simply
        continues, so a cheaper lower-priority exercise sitting behind it can be funded out of
        the same reserve. Identical inputs therefore fund a genuinely different set of
        exercises under the two modes."
        PRD 3.8: "Walking the queue in order, an exercise whose `exercise_amount_cents` is
        less than or equal to the remaining budget is funded — its status becomes `FUNDED`,
        its `funded_cents` is set to its exercise amount, its `funded_by_user_id` is stamped
        from the sweeping trustee's `X-User-ID`, the budget and the plan's
        `repurchase_reserve_cents` both fall by that amount and `committed_repurchase_cents`
        rises by it."

        Design: Difficulty/dual_variant_calc/repurchase_sweep_strict_order_vs_best_fit
        """
        ctx = setup_two_pending_exercises(sweep_mode="BEST_FIT", reserve_floor_cents=0,
                                          deposit_cents=3_000_000)

        report = validate_success(api.run_repurchase_sweep(ctx["plan"]["id"], TRUSTEE))
        assert report["funded_count"] == 1
        assert report["funded_cents_total"] == 2_850_000
        assert report["sweep_mode_applied"] == "BEST_FIT"

        assert get_exercise(ctx["ex_small"]["id"])["status"] == "FUNDED"
        assert get_plan(ctx["plan"]["id"])["repurchase_reserve_cents"] == 150_000

    def test_sweep_best_fit_skips_oversized_and_funds_cheaper_exercise(self, api):
        """PRD 3.8: "The sweep may spend only the headroom above the floor: its spendable
        budget is the plan's `repurchase_reserve_cents` less its `repurchase_reserve_floor_cents`,
        taken as 0 if that difference would be negative."
        PRD 3.8: "`repurchase_posture` is recomputed exactly once, at the end of the sweep;
        because the sweep never spends below the floor, a sweep can never by itself drive the
        plan to `UNDERFUNDED`."

        Design: Corner/endpoints/sweep_best_fit_skips_oversized_and_funds_cheaper_exercise
        """
        ctx = setup_two_pending_exercises(sweep_mode="BEST_FIT", reserve_floor_cents=0,
                                          deposit_cents=3_000_000)

        report = validate_success(api.run_repurchase_sweep(ctx["plan"]["id"], TRUSTEE))
        assert report["funded_count"] == 1
        assert report["deferred_count"] == 1
        assert report["funded_cents_total"] == 2_850_000
        assert report["sweep_mode_applied"] == "BEST_FIT"
        assert report["reserve_after_cents"] == 150_000

        big = get_exercise(ctx["ex_big"]["id"])
        small = get_exercise(ctx["ex_small"]["id"])
        assert big["status"] == "DEFERRED" and big["funded_cents"] == 0
        assert small["status"] == "FUNDED" and small["funded_cents"] == 2_850_000

        plan = get_plan(ctx["plan"]["id"])
        assert plan["repurchase_reserve_cents"] == 150_000
        assert plan["committed_repurchase_cents"] == 2_850_000
        assert plan["repurchase_posture"] == "FUNDED", "the floor is 0, so the sweep stays funded"
        assert_cash_conservation(plan)


class TestDirectFundingCascade:
    def test_funding_moves_cash_and_flips_the_posture_underfunded(self, api):
        """PRD 3.8: "Funding cascades in three hops. The first hop is the funding itself:
        `funded_cents` is set to the exercise's `exercise_amount_cents`, `funded_by_user_id`
        is set from the trustee's `X-User-ID`, the plan's `repurchase_reserve_cents` decreases
        by that amount and its `committed_repurchase_cents` increases by the same amount. The
        second hop follows if the reserve has now fallen below the plan's
        `repurchase_reserve_floor_cents`: `repurchase_posture` flips from `FUNDED` to
        `UNDERFUNDED`."

        Design: Difficulty/transitive_cascade/put_funding_underfunds_plan_and_defers_siblings_depth3
        """
        ctx = setup_two_pending_exercises(sweep_mode="STRICT_ORDER",
                                          reserve_floor_cents=3_000_000,
                                          deposit_cents=5_000_000)

        funded = validate_success(api.fund_put_option_exercise(ctx["ex_big"]["id"], TRUSTEE))
        assert funded["status"] == "FUNDED"
        assert funded["funded_cents"] == 3_562_500
        assert funded["funded_by_user_id"] == "trustee-01"

        plan = get_plan(ctx["plan"]["id"])
        assert plan["repurchase_reserve_cents"] == 1_437_500
        assert plan["committed_repurchase_cents"] == 3_562_500
        assert plan["repurchase_posture"] == "UNDERFUNDED"
        assert_cash_conservation(plan)

    def test_underfunded_posture_defers_every_untouched_sibling(self, api):
        """PRD 3.8: "The third hop follows from the second: because the plan has gone
        underfunded, every other put option exercise belonging to that plan's participants
        that is still `PENDING` is set to `DEFERRED`."
        PRD 3.8: "`share_price_cents` is a copy of the plan's `current_share_price_cents`, and
        `exercise_amount_cents` is that price multiplied by the tendered share count — the cash
        the plan will owe."
        PRD 3.8: "`priority_class` is derived from the type of the parent election: a `DEATH`
        election yields priority class `DEATH`, a `RETIREMENT` or a `DISABILITY` election both
        yield `RETIREMENT_DISABILITY`, a `TERMINATION` election yields `TERMINATION`, and a
        `DIVERSIFICATION` election yields `DIVERSIFICATION`."

        Design: Difficulty/transitive_cascade/put_funding_underfunds_plan_and_defers_siblings_depth3
        """
        ctx = setup_two_pending_exercises(sweep_mode="STRICT_ORDER",
                                          reserve_floor_cents=3_000_000,
                                          deposit_cents=5_000_000)
        fund_exercise(ctx["ex_big"]["id"])

        sibling = get_exercise(ctx["ex_small"]["id"])
        assert sibling["status"] == "DEFERRED"

        big = get_exercise(ctx["ex_big"]["id"])
        assert_put_option_exercise(big)
        assert big["exercise_amount_cents"] == 3_562_500
        assert sibling["exercise_amount_cents"] == 2_850_000
        assert big["share_price_cents"] == 7125
        assert big["priority_class"] == "TERMINATION"
        assert big["window_open_date"] == "2026-04-01"
        assert big["window_close_date"] == "2026-05-30"

        plan = get_plan(ctx["plan"]["id"])
        assert plan["cumulative_repurchase_funding_cents"] == 5_000_000
        assert_cash_conservation(plan)


class TestPutWindowBoundary:
    def test_exercise_on_the_windows_last_day_is_admitted(self, api):
        """PRD 3.8: "The logical clock date must fall inside the participant's current window,
        treating `put_window_open_date` and `put_window_close_date` as a closed interval
        inclusive at both ends; a date outside the interval, or a participant with no window at
        all, is refused with `ERR_PUT_WINDOW_CLOSED`."
        PRD 3.8: "The exercise is stored `PENDING` with `funded_cents` at 0,
        `funded_by_user_id`, `settled_date` and `cancel_reason` all null, and the participant's
        `tendered_shares_cumulative` increases by the tendered count immediately — the
        commitment is made at creation, not at funding."

        Design: Difficulty/boundary_precision_check/put_window_last_day_admitted_next_day_refused
        """
        ctx = setup_cedar_valley_distribution(plan_overrides={"plan_name": "Cedar Valley Edge"})
        set_clock("2026-05-30T00:00:00Z", ADMIN)

        payload = create_put_option_exercise_payload(ctx["election"]["id"], 400)
        exercise = validate_success(
            api.create_put_option_exercise(payload, ctx["participant_headers"]), 201)

        assert exercise["status"] == "PENDING"
        assert exercise["exercise_date"] == "2026-05-30"
        assert exercise["window_close_date"] == "2026-05-30"
        assert exercise["exercise_amount_cents"] == 2_850_000
        assert exercise["funded_cents"] == 0
        assert exercise["funded_by_user_id"] is None
        assert get_participant(ctx["participant"]["id"])["tendered_shares_cumulative"] == 400

    def test_exercise_one_day_after_the_window_closes_is_refused(self, api):
        """PRD 3.8: "The logical clock date must fall inside the participant's current window,
        treating `put_window_open_date` and `put_window_close_date` as a closed interval
        inclusive at both ends; a date outside the interval, or a participant with no window at
        all, is refused with `ERR_PUT_WINDOW_CLOSED`."
        PRD 3.7: "The candidate window would open on the payment's logical clock date and
        close 59 days later, giving a closed 60-day interval inclusive of both endpoints."

        Design: Difficulty/boundary_precision_check/put_window_last_day_admitted_next_day_refused
        """
        ctx = setup_cedar_valley_distribution(plan_overrides={"plan_name": "Cedar Valley Edge"})
        set_clock("2026-05-30T00:00:00Z", ADMIN)
        raise_exercise(ctx["election"]["id"], 400, ctx["participant"]["id"])

        set_clock("2026-05-31T00:00:00Z", ADMIN)
        late = create_put_option_exercise_payload(ctx["election"]["id"], 100)
        validate_error(api.create_put_option_exercise(late, ctx["participant_headers"]),
                       ApiErrorId.ERR_PUT_WINDOW_CLOSED)

        assert get_participant(ctx["participant"]["id"])["tendered_shares_cumulative"] == 400, (
            "the refused request commits nothing"
        )
        _rows, meta = validate_paginated(
            api.list_put_option_exercises(
                TRUSTEE, params={"participant_id": ctx["participant"]["id"]})
        )
        assert meta["total_count"] == 1, "exactly one exercise row exists"


class TestCompensatingCancellation:
    def test_cancelling_a_funded_exercise_returns_every_cent(self, api):
        """PRD 3.8: "Cancelling a `FUNDED` exercise is the compensating action for the
        funding: the plan's `repurchase_reserve_cents` increases by the exercise's
        `funded_cents` and its `committed_repurchase_cents` decreases by the same amount, the
        exercise's `funded_cents` is reset to 0, and the participant's
        `tendered_shares_cumulative` decreases by the tendered count."
        PRD 3.8: "The cash conservation counters must read identically before the funding and
        after the cancellation."

        Design: Difficulty/compensating_invariant/put_cancel_conserves_repurchase_cash
        """
        ctx = setup_two_pending_exercises(sweep_mode="STRICT_ORDER",
                                          reserve_floor_cents=3_000_000,
                                          deposit_cents=5_000_000)
        fund_exercise(ctx["ex_big"]["id"])
        after_fund = get_plan(ctx["plan"]["id"])
        assert after_fund["repurchase_reserve_cents"] == 1_437_500
        assert after_fund["committed_repurchase_cents"] == 3_562_500

        cancelled = validate_success(api.cancel_put_option_exercise(
            ctx["ex_big"]["id"], {"reason": "Participant withdrew the tender."}, TRUSTEE))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["funded_cents"] == 0
        assert cancelled["cancel_reason"] == "Participant withdrew the tender."

        plan = get_plan(ctx["plan"]["id"])
        assert plan["repurchase_reserve_cents"] == 5_000_000
        assert plan["committed_repurchase_cents"] == 0
        assert plan["cumulative_repurchase_settled_cents"] == 0
        assert plan["cumulative_repurchase_funding_cents"] == 5_000_000, (
            "cumulative funding is monotonically non-decreasing and unchanged by the reversal"
        )
        assert_cash_conservation(plan)

    def test_cancellation_restores_deferred_siblings_and_releases_the_tender(self, api):
        """PRD 3.8: "`repurchase_posture` is recomputed, and if the returned cash lifts the
        plan back to `FUNDED`, every put option exercise of the plan's participants sitting in
        `DEFERRED` is restored to `PENDING`, mirroring the deferral cascade that funding
        caused."
        PRD 3.8: "Cancelling an unfunded exercise moves no cash at all, because its
        `funded_cents` is already 0; the participant's `tendered_shares_cumulative` decreases
        by the exercise's `shares_tendered`, releasing the commitment, and the plan's `version`
        increments by 1."

        Design: Difficulty/compensating_invariant/put_cancel_conserves_repurchase_cash
        """
        ctx = setup_two_pending_exercises(sweep_mode="STRICT_ORDER",
                                          reserve_floor_cents=3_000_000,
                                          deposit_cents=5_000_000)
        fund_exercise(ctx["ex_big"]["id"])
        assert get_exercise(ctx["ex_small"]["id"])["status"] == "DEFERRED"

        validate_success(api.cancel_put_option_exercise(
            ctx["ex_big"]["id"], {"reason": "Participant withdrew the tender."}, TRUSTEE))

        plan = get_plan(ctx["plan"]["id"])
        assert plan["repurchase_posture"] == "FUNDED"
        assert get_exercise(ctx["ex_small"]["id"])["status"] == "PENDING", (
            "the deferred sibling is restored by the reverse cascade"
        )
        assert get_participant(ctx["participant"]["id"])["tendered_shares_cumulative"] == 400
        assert plan["reacquired_shares"] == 0
        assert plan["total_plan_shares"] == 0


class TestReserveRecoveryAndAuthority:
    def test_repurchase_funding_restores_deferred_exercises_to_pending(self, api):
        """PRD 3.8: "The `Trustee` deposits cash into the repurchase reserve by supplying an
        `amount_cents` figure in whole cents. The plan's `repurchase_reserve_cents` and its
        `cumulative_repurchase_funding_cents` each increase by that amount, and
        `repurchase_posture` is recomputed. A deposit that lifts the reserve back to or above
        `repurchase_reserve_floor_cents` returns the posture to `FUNDED`, and that recovery
        has a cascade of its own: every put option exercise of the plan's participants sitting
        in `DEFERRED` is restored to `PENDING`."

        Design: Corner/endpoints/repurchase_funding_restores_deferred_exercises_to_pending
        """
        ctx = setup_two_pending_exercises(sweep_mode="STRICT_ORDER",
                                          reserve_floor_cents=3_000_000,
                                          deposit_cents=5_000_000, fund_first=True)
        assert get_exercise(ctx["ex_small"]["id"])["status"] == "DEFERRED"
        assert ctx["plan"]["repurchase_posture"] == "UNDERFUNDED"

        plan = validate_success(api.deposit_repurchase_funding(
            ctx["plan"]["id"], {"amount_cents": 2_000_000}, TRUSTEE))
        assert plan["repurchase_reserve_cents"] == 3_437_500
        assert plan["cumulative_repurchase_funding_cents"] == 7_000_000
        assert plan["repurchase_posture"] == "FUNDED"
        assert plan["committed_repurchase_cents"] == 3_562_500
        assert_cash_conservation(plan)

        assert get_exercise(ctx["ex_small"]["id"])["status"] == "PENDING"
        big = get_exercise(ctx["ex_big"]["id"])
        assert big["status"] == "FUNDED" and big["funded_cents"] == 3_562_500, (
            "the already funded exercise is untouched by the deposit"
        )

    def test_participant_cannot_fund_a_put_option_exercise(self, api):
        """PRD 2.1: "When the headers are well formed but the named role does not appear in
        the authorized-role list for the endpoint being called, the request is refused with
        `ERR_FORBIDDEN_ROLE` and HTTP 403."
        PRD 3.8: "A trustee may commit reserve cash against a single exercise, which drives it
        to `FUNDED` from either `PENDING` or `DEFERRED`."

        Design: Corner/rbac/participant_cannot_fund_a_put_option_exercise
        """
        ctx = setup_cedar_valley_distribution(
            plan_overrides={"plan_name": "Role Guard", "repurchase_reserve_floor_cents": 0})
        exercise = raise_exercise(ctx["election"]["id"], 500, ctx["participant"]["id"])
        deposit_repurchase_funding(ctx["plan"]["id"], 5_000_000)

        validate_error(
            api.fund_put_option_exercise(exercise["id"], ctx["participant_headers"]),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
        )
        refused = get_exercise(exercise["id"])
        assert refused["status"] == "PENDING"
        assert refused["funded_cents"] == 0
        plan = get_plan(ctx["plan"]["id"])
        assert plan["repurchase_reserve_cents"] == 5_000_000
        assert plan["committed_repurchase_cents"] == 0

        funded = validate_success(api.fund_put_option_exercise(exercise["id"], TRUSTEE))
        assert funded["status"] == "FUNDED", "the identical call by the trustee is accepted"

    def test_repurchase_forecast_sums_vested_value_over_included_statuses(self, api):
        """PRD 3.8: "Taking the current year as the calendar year of the logical clock date,
        the forecast includes every participant of the plan who has already separated — those
        whose `status` is `TERMINATED`, `RETIRED` or `DECEASED` — plus every still-`ACTIVE`
        participant whose birth year advanced by the plan's `normal_retirement_age` falls on
        or before the current year plus the horizon."
        PRD 3.8: "The response reports the `horizon_years` actually used, the
        `participant_count` of included participants, the `projected_obligation_cents` just
        described, the plan's current `committed_repurchase_cents`, the reserve balance as
        `reserve_cents`, and `coverage_bps`, which is the reserve multiplied by 10000 and
        divided by the projected obligation, floored to whole basis points — or exactly 10000
        when the projected obligation is 0, since a plan with no obligation is by definition
        fully covered."
        PRD 3.8: "The request carries an optional `horizon_years`, defaulting to 5."

        Design: Corner/calculations/repurchase_forecast_sums_vested_value_over_included_statuses
        """
        ctx = setup_forfeited_participant(
            plan_overrides={"plan_name": "Forecast Plan",
                            "forfeiture_sweep_threshold_shares": 1000})
        assert ctx["participant"]["vested_shares"] == 580

        forecast = validate_success(api.get_repurchase_forecast(
            ctx["plan"]["id"], TRUSTEE, params={"horizon_years": 5}))
        assert forecast["horizon_years"] == 5
        assert forecast["participant_count"] == 1
        assert forecast["projected_obligation_cents"] == 4_132_500
        assert forecast["reserve_cents"] == 0
        assert forecast["committed_repurchase_cents"] == 0
        assert forecast["coverage_bps"] == 0

        default_forecast = validate_success(
            api.get_repurchase_forecast(ctx["plan"]["id"], TRUSTEE))
        assert default_forecast["horizon_years"] == 5, "horizon_years defaults to 5"
        assert default_forecast["projected_obligation_cents"] == 4_132_500
