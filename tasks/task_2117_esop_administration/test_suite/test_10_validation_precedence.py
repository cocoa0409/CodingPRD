"""The order in which competing checks are judged."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_valuation,
    close_year,
    create_allocation_run,
    create_participant,
    create_plan,
    create_put_option_exercise_payload,
    deposit_repurchase_funding,
    fund_exercise,
    get_allocation_run,
    get_exercise,
    get_participant,
    get_plan,
    raise_exercise,
    set_clock,
    settle_exercise,
    setup_cedar_valley_distribution,
    submit_valuation,
    validate_error,
    validate_paginated,
)

SPONSOR = TEST_USERS["sponsor_headers"]
APPRAISER = TEST_USERS["appraiser_headers"]
TRUSTEE = TEST_USERS["trustee_headers"]
ADMIN = TEST_USERS["admin_headers"]
ADMIN_ALT = TEST_USERS["admin_alt_headers"]


class TestStateBeatsFiscal:
    def _settled_exercise_with_thin_reserve(self):
        """A SETTLED exercise worth 3562500 cents against a reserve holding 1437500."""
        ctx = setup_cedar_valley_distribution(
            plan_overrides={"plan_name": "Cedar Valley Conflict",
                            "repurchase_reserve_floor_cents": 0})
        exercise = raise_exercise(ctx["election"]["id"], 500, ctx["participant"]["id"])
        deposit_repurchase_funding(ctx["plan"]["id"], 5_000_000)
        fund_exercise(exercise["id"])
        settle_exercise(exercise["id"])
        ctx["exercise"] = get_exercise(exercise["id"])
        return ctx

    def test_funding_a_settled_exercise_reports_invalid_state_not_reserve_shortfall(self, api):
        """PRD 2.12: "Target state — the target resource is in a state from which the
        requested transition is declared, else `ERR_INVALID_STATE` (409). Applies to every
        action endpoint, including every repeat of an already-applied action."
        PRD 2.12: "Sufficient repurchase reserve — else `ERR_INSUFFICIENT_REPURCHASE_RESERVE`
        (402). Applies to funding a put option exercise."
        PRD 3.8: "The reserve must cover the whole amount: `repurchase_reserve_cents` must be
        at least the exercise's `exercise_amount_cents`, and a shortfall is refused with
        `ERR_INSUFFICIENT_REPURCHASE_RESERVE` with HTTP 402."

        Design: Difficulty/priority_pair_validation_conflict/settled_exercise_refund_beats_insufficient_reserve_state_vs_fiscal
        """
        ctx = self._settled_exercise_with_thin_reserve()
        plan = get_plan(ctx["plan"]["id"])
        assert plan["repurchase_reserve_cents"] == 1_437_500, (
            "the reserve alone could not cover another 3562500-cent funding"
        )

        resp = api.fund_put_option_exercise(ctx["exercise"]["id"], TRUSTEE)
        error = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert error["error_id"] != "ERR_INSUFFICIENT_REPURCHASE_RESERVE", (
            "the state check at priority 9 pre-empts the reserve check at priority 29"
        )

    def test_the_refused_refunding_moves_no_cash(self, api):
        """PRD 3.8: "Settlement is the trustee's final act on a funded exercise, driving it
        from `FUNDED` to `SETTLED`."
        PRD 3.8: "The cash leaves the committed bucket for good: the plan's
        `committed_repurchase_cents` decreases by the exercise's `funded_cents` and its
        `cumulative_repurchase_settled_cents` increases by the same amount."

        Design: Difficulty/priority_pair_validation_conflict/settled_exercise_refund_beats_insufficient_reserve_state_vs_fiscal
        """
        ctx = self._settled_exercise_with_thin_reserve()
        validate_error(api.fund_put_option_exercise(ctx["exercise"]["id"], TRUSTEE),
                       ApiErrorId.ERR_INVALID_STATE)

        exercise = get_exercise(ctx["exercise"]["id"])
        assert exercise["status"] == "SETTLED"
        assert exercise["funded_cents"] == 3_562_500

        plan = get_plan(ctx["plan"]["id"])
        assert plan["repurchase_reserve_cents"] == 1_437_500, (
            "the rejected call leaves the reserve untouched"
        )
        assert plan["cumulative_repurchase_settled_cents"] == 3_562_500
        assert plan["committed_repurchase_cents"] == 0


class TestSafetyBeatsReferential:
    def _cross_plan_run(self):
        """A DRAFT run on Plan One naming Plan Two's approved appraisal, opened by tpa-01."""
        set_clock("2026-03-02T00:00:00Z", SPONSOR)
        plan_one = create_plan(plan_name="Plan One", sponsor_name="Northgate Tooling Inc.")
        participant = create_participant(plan_one["id"], employee_number="E-301",
                                         eligible_compensation_cents=34_500_000)
        plan_one = close_year(plan_one["id"])

        plan_two = create_plan(plan_name="Plan Two", sponsor_name="Cedar Valley Foods LLC")
        plan_two = close_year(plan_two["id"])
        valuation_two = submit_valuation(plan_two["id"], plan_two["version"])
        approve_valuation(valuation_two["id"])

        run = create_allocation_run(plan_one["id"], valuation_two["id"],
                                    contributed_shares=500,
                                    expected_plan_version=plan_one["version"])
        return {"plan_one": plan_one, "participant": participant, "run": run}

    def test_segregation_of_duties_is_reported_before_the_entity_mismatch(self, api):
        """PRD 2.8: "An administrator whose `X-User-ID` equals the `created_by_user_id`
        recorded on an allocation run may not finalize that run. Either violation is refused
        with `ERR_SEGREGATION_OF_DUTIES` and HTTP 403."
        PRD 2.12: "Segregation of duties — else `ERR_SEGREGATION_OF_DUTIES` (403). Applies to
        valuation approval and run finalize."
        PRD 2.12: "Cross-entity coherence at finalize — else `ERR_ENTITY_MISMATCH` (409).
        Applies to run finalize."

        Design: Difficulty/priority_pair_validation_conflict/finalize_segregation_beats_valuation_plan_mismatch_safety_vs_referential
        """
        ctx = self._cross_plan_run()

        resp = api.finalize_allocation_run(ctx["run"]["id"], ADMIN)
        error = validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert error["error_id"] != "ERR_ENTITY_MISMATCH", (
            "the duty check at priority 11 pre-empts the coherence check at priority 13"
        )

        run = get_allocation_run(ctx["run"]["id"])
        assert run["status"] == "DRAFT"
        assert run["finalized_by_user_id"] is None
        assert get_plan(ctx["plan_one"]["id"])["plan_status"] == "VALUATION_PENDING"

    def test_a_different_administrator_then_surfaces_the_entity_mismatch(self, api):
        """PRD 3.5: "The appraisal must also belong to the same plan as the run, and three
        plan-year figures must all agree: the run's `plan_year`, the appraisal's `plan_year`
        and the plan's own `plan_year`. Any disagreement, or an appraisal drawn from a
        different plan, is refused with `ERR_ENTITY_MISMATCH`."
        PRD 3.5: "Coherence between the run and the appraisal it names is deliberately not
        checked here: a draft run may name any appraisal that exists, including one belonging
        to another plan or another year."

        Design: Difficulty/priority_pair_validation_conflict/finalize_segregation_beats_valuation_plan_mismatch_safety_vs_referential
        """
        ctx = self._cross_plan_run()
        validate_error(api.finalize_allocation_run(ctx["run"]["id"], ADMIN),
                       ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        validate_error(api.finalize_allocation_run(ctx["run"]["id"], ADMIN_ALT),
                       ApiErrorId.ERR_ENTITY_MISMATCH)

        assert get_allocation_run(ctx["run"]["id"])["status"] == "DRAFT"
        assert get_participant(ctx["participant"]["id"])["allocated_shares"] == 0


class TestTemporalBeatsConstraint:
    def _lapsed_window_holder(self):
        """900 delivered shares, window 2026-04-01 to 2026-05-30, clock one day past it."""
        ctx = setup_cedar_valley_distribution(plan_overrides={"plan_name": "Cedar Valley Late"})
        set_clock("2026-05-31T00:00:00Z", ADMIN)
        return ctx

    def test_lapsed_window_is_reported_before_the_oversized_tender(self, api):
        """PRD 2.12: "Put option window open — else `ERR_PUT_WINDOW_CLOSED` (422). Applies to
        put option exercise creation and to funding an exercise."
        PRD 2.12: "Sufficient shares behind the request — else `ERR_INSUFFICIENT_SHARES`
        (422). Applies to election creation and put option exercise creation."
        PRD 3.8: "And the participant must actually hold undelivered-to-put shares:
        `shares_tendered` may not exceed their `distributed_shares_cumulative` less their
        `tendered_shares_cumulative`, and a larger tender is refused with
        `ERR_INSUFFICIENT_SHARES`."

        Design: Difficulty/priority_pair_validation_conflict/put_window_closed_beats_insufficient_shares_temporal_vs_constraint
        """
        ctx = self._lapsed_window_holder()
        assert ctx["participant"]["distributed_shares_cumulative"] == 900

        payload = create_put_option_exercise_payload(ctx["election"]["id"], 2000)
        resp = api.create_put_option_exercise(payload, ctx["participant_headers"])
        error = validate_error(resp, ApiErrorId.ERR_PUT_WINDOW_CLOSED)
        assert error["error_id"] != "ERR_INSUFFICIENT_SHARES", (
            "the window check at priority 17 pre-empts the share check at priority 24"
        )

    def test_the_doubly_invalid_tender_commits_nothing(self, api):
        """PRD 3.8: "The exercise is stored `PENDING` with `funded_cents` at 0,
        `funded_by_user_id`, `settled_date` and `cancel_reason` all null, and the participant's
        `tendered_shares_cumulative` increases by the tendered count immediately — the
        commitment is made at creation, not at funding."
        PRD 3.7: "On success the participant's `put_window_open_date` and
        `put_window_close_date` are set to the candidate dates and `last_put_window_close_date`
        is set to the same closing date, which is retained after the window lapses so that the
        buffer can still be evaluated later."

        Design: Difficulty/priority_pair_validation_conflict/put_window_closed_beats_insufficient_shares_temporal_vs_constraint
        """
        ctx = self._lapsed_window_holder()
        payload = create_put_option_exercise_payload(ctx["election"]["id"], 2000)
        validate_error(api.create_put_option_exercise(payload, ctx["participant_headers"]),
                       ApiErrorId.ERR_PUT_WINDOW_CLOSED)

        _rows, meta = validate_paginated(
            api.list_put_option_exercises(
                TRUSTEE, params={"participant_id": ctx["participant"]["id"]})
        )
        assert meta["total_count"] == 0, "the refused request creates no exercise row"

        participant = get_participant(ctx["participant"]["id"])
        assert participant["tendered_shares_cumulative"] == 0
        assert participant["put_window_close_date"] == "2026-05-30"
