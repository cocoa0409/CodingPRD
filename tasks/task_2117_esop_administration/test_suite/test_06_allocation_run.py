"""The annual allocation run: proportional distribution, the Section 415 loop and finalize."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    approve_valuation,
    assert_allocation_run,
    assert_share_allocation,
    assert_share_conservation,
    close_year,
    create_allocation_run,
    create_allocation_run_payload,
    create_participant,
    create_plan,
    finalize_run,
    get_allocation_line,
    get_allocation_run,
    get_participant,
    get_plan,
    list_share_allocations,
    list_statements,
    resubmit_valuation_payload,
    set_clock,
    setup_draft_run,
    setup_plan_with_price,
    setup_ironwood_finalized_run,
    submit_valuation,
    terminate_participant,
    validate_error,
    validate_paginated,
    validate_success,
)

SPONSOR = TEST_USERS["sponsor_headers"]
APPRAISER = TEST_USERS["appraiser_headers"]
TRUSTEE = TEST_USERS["trustee_headers"]
ADMIN = TEST_USERS["admin_headers"]
ADMIN_ALT = TEST_USERS["admin_alt_headers"]


class TestProportionalDistribution:
    def test_pool_is_floored_per_participant_then_reconciled(self, api):
        """PRD 3.5: "That value is evaluated as an exact rational number and then floored to a
        whole share, and the flooring happens per participant, before anything is reconciled.
        Because flooring throws away fractions, the floors will normally sum to less than the
        pool; the shortfall is the difference between the pool and the sum of the floors, and
        it is handed out one whole share at a time to the participants with the largest
        discarded fractions."
        PRD 3.5: "The first pass produces exact entitlements of 1069.767, 620.155 and 310.078,
        whose floors are 1069, 620 and 310 and sum to 1999; the single shortfall share goes to
        the largest discarded fraction, the first participant, so the pass-one grants are
        1070, 620 and 310."

        Design: Difficulty/combinatorial_formula/allocation_remainder_floor_then_distribute_mode_b
        """
        ctx = setup_ironwood_finalized_run(contributed_shares=2000)
        run = ctx["run"]
        pa, pb, pc = ctx["participants"]

        assert_allocation_run(run)
        assert run["pool_shares"] == 2000
        assert run["share_price_cents"] == 7875
        assert run["total_capped_compensation_cents"] == 64_500_000, (
            "capped compensation of 34,500,000 + 20,000,000 + 10,000,000"
        )

        line_a = get_allocation_line(run["id"], pa["id"])
        line_b = get_allocation_line(run["id"], pb["id"])
        line_c = get_allocation_line(run["id"], pc["id"])
        assert_share_allocation(line_a)
        assert line_a["remainder_shares_awarded"] == 1
        assert line_a["gross_shares_before_cap"] == 1070
        assert line_b["remainder_shares_awarded"] == 0
        assert line_c["remainder_shares_awarded"] == 1
        assert line_c["gross_shares_before_cap"] == 375
        total = line_a["allocated_shares"] + line_b["allocated_shares"] + line_c["allocated_shares"]
        assert total == 2000, (
            "the per-participant floors plus the reconciled shortfall exhaust the pool exactly"
        )

    def test_final_awards_follow_the_worked_run(self, api):
        """PRD 3.5: "Final awards are 876, 749 and 375, the residue is 0, and the capped count
        is 1."
        PRD 3.5: "The alternative reading — rounding each raw entitlement half up and summing —
        is explicitly not used, because it can hand out more or fewer shares than the pool
        actually holds. Rounding is per participant first; the residue is reconciled second;
        the pool total is never itself rounded."

        Design: Difficulty/combinatorial_formula/allocation_remainder_floor_then_distribute_mode_b
        """
        ctx = setup_ironwood_finalized_run(contributed_shares=2000)
        pa, pb, pc = ctx["participants"]

        assert pa["allocated_shares"] == 876
        assert pb["allocated_shares"] == 749
        assert pc["allocated_shares"] == 375
        assert pa["allocated_shares"] + pb["allocated_shares"] + pc["allocated_shares"] == 2000
        assert ctx["run"]["residual_shares"] == 0

    def test_capped_participant_recycles_excess_over_two_passes(self, api):
        """PRD 3.5: "At the end of the pass, any participant whose award has reached the
        ceiling leaves the open set permanently and never re-enters, even if a later pass
        would have room for them under a different reading."
        PRD 3.5: "The first participant is trimmed from 1070 to 876 and leaves the open set,
        recycling 194 shares into the pool. The second pass runs over the two remaining
        participants against a denominator of 30,000,000, producing exact entitlements of
        129.333 and 64.667, floors of 129 and 64 summing to 193, and one shortfall share to
        the third participant's larger fraction, for grants of 129 and 65. Both fit under the
        ceiling, the pool reaches 0, and the loop stops after two passes."

        Design: Difficulty/combinatorial_formula/annual_additions_cap_recycles_excess_mode_c
        """
        ctx = setup_ironwood_finalized_run(contributed_shares=2000)
        run = ctx["run"]

        assert run["passes_executed"] == 2
        assert run["capped_participant_count"] == 1
        assert run["residual_shares"] == 0
        assert run["status"] == "FINALIZED"

    def test_section_415_line_fields_record_the_ceiling_trim(self, api):
        """PRD 3.5: "Each participant's final `allocated_shares` on their allocation line is
        their accumulated award; `excess_shares_removed` is their `gross_shares_before_cap`
        less that award; `annual_additions_cents` is their award multiplied by the run's
        `share_price_cents`; and the boolean `capped` is true exactly when their award equals
        `max_shares_cap`."
        PRD 3.5: "`max_shares_cap` is the plan's `annual_additions_limit_cents` divided by the
        run's `share_price_cents`, floored to a whole share. The same ceiling applies to every
        participant in the run."

        Design: Difficulty/combinatorial_formula/annual_additions_cap_recycles_excess_mode_c
        """
        ctx = setup_ironwood_finalized_run(contributed_shares=2000)
        run = ctx["run"]
        pa, pb, pc = ctx["participants"]

        line_a = get_allocation_line(run["id"], pa["id"])
        assert line_a["max_shares_cap"] == 876
        assert line_a["gross_shares_before_cap"] == 1070
        assert line_a["excess_shares_removed"] == 194
        assert line_a["allocated_shares"] == 876
        assert line_a["annual_additions_cents"] == 6_898_500
        assert line_a["capped"] is True

        line_b = get_allocation_line(run["id"], pb["id"])
        assert line_b["gross_shares_before_cap"] == 749
        assert line_b["excess_shares_removed"] == 0
        assert line_b["allocated_shares"] == 749
        assert line_b["annual_additions_cents"] == 5_898_375
        assert line_b["capped"] is False

        line_c = get_allocation_line(run["id"], pc["id"])
        assert line_c["gross_shares_before_cap"] == 375
        assert line_c["excess_shares_removed"] == 0
        assert line_c["allocated_shares"] == 375
        assert line_c["annual_additions_cents"] == 2_953_125
        assert line_c["capped"] is False

        plan = ctx["plan"]
        assert plan["unallocated_forfeiture_shares"] == 0
        assert plan["allocated_shares_total"] == 2000


class TestSection415ResidueBoundary:
    def _boundary_context(self):
        """REDUCE_CONTRIBUTION plan, one participant at the compensation limit, price 7875."""
        return setup_draft_run(
            contributed_shares=877,
            plan_overrides={"plan_name": "Boundary Plan",
                            "sponsor_name": "Ironwood Manufacturing Inc.",
                            "forfeiture_policy": "REDUCE_CONTRIBUTION",
                            "annual_compensation_limit_cents": 34_500_000,
                            "annual_additions_limit_cents": 6_900_000},
            participants=[{"employee_number": "E-401"}],
            loan={},
        )

    def test_residue_of_one_share_rejects_the_finalize(self, api):
        """PRD 3.5: "Under `REDUCE_CONTRIBUTION` a non-zero residue is not tolerated at all —
        the finalize is rejected whole with `ERR_ANNUAL_ADDITIONS_EXCEEDED`, no allocation
        lines are written, no counters move, and the run stays `DRAFT`."
        PRD 3.5: "The boundary is sharp: for a single participant at the compensation limit
        with a price of 7875, a contribution of 876 shares finalizes with a residue of 0,
        while a contribution of 877 leaves a residue of 1."

        Design: Difficulty/boundary_precision_check/section415_residue_zero_at_876_nonzero_at_877
        """
        ctx = self._boundary_context()
        participant = ctx["participants"][0]

        validate_error(api.finalize_allocation_run(ctx["run"]["id"], ADMIN_ALT),
                       ApiErrorId.ERR_ANNUAL_ADDITIONS_EXCEEDED)

        run = get_allocation_run(ctx["run"]["id"])
        assert run["status"] == "DRAFT", "the rejected finalize leaves the run in DRAFT"
        assert get_participant(participant["id"])["allocated_shares"] == 0
        plan = get_plan(ctx["plan"]["id"])
        assert plan["plan_status"] == "VALUATION_PENDING", "no counters move on the rejection"
        _rows, meta = validate_paginated(
            api.list_share_allocations(ADMIN, params={"allocation_run_id": run["id"]})
        )
        assert meta["total_count"] == 0, "no allocation lines are written"

    def test_residue_of_zero_finalizes_at_the_boundary(self, api):
        """PRD 3.5: "A residue of exactly 0 finalizes normally under either policy."
        PRD 3.5: "The boundary is sharp: for a single participant at the compensation limit
        with a price of 7875, a contribution of 876 shares finalizes with a residue of 0,
        while a contribution of 877 leaves a residue of 1."

        Design: Difficulty/boundary_precision_check/section415_residue_zero_at_876_nonzero_at_877
        """
        ctx = self._boundary_context()
        participant = ctx["participants"][0]
        validate_error(api.finalize_allocation_run(ctx["run"]["id"], ADMIN_ALT),
                       ApiErrorId.ERR_ANNUAL_ADDITIONS_EXCEEDED)

        exact_run = create_allocation_run(ctx["plan"]["id"], ctx["valuation"]["id"],
                                          contributed_shares=876)
        finalized = validate_success(api.finalize_allocation_run(exact_run["id"], ADMIN_ALT))

        assert finalized["status"] == "FINALIZED"
        assert finalized["pool_shares"] == 876
        assert finalized["residual_shares"] == 0
        assert finalized["capped_participant_count"] == 1
        assert finalized["passes_executed"] == 1

        assert get_participant(participant["id"])["allocated_shares"] == 876
        line = get_allocation_line(exact_run["id"], participant["id"])
        assert line["max_shares_cap"] == 876
        assert line["allocated_shares"] == 876
        assert line["annual_additions_cents"] == 6_898_500
        assert line["capped"] is True

        plan = get_plan(ctx["plan"]["id"])
        assert plan["plan_status"] == "ALLOCATION_LOCKED"
        assert plan["unallocated_forfeiture_shares"] == 0


class TestFinalizeGatedByValuation:
    def _challenged_context(self):
        ctx = setup_draft_run(
            contributed_shares=500,
            plan_overrides={"plan_name": "Gate Plan A", "sponsor_name": "Northgate Tooling Inc.",
                            "annual_additions_limit_cents": 6_900_000},
            participants=[{"employee_number": "E-501"}],
            approve=False,
        )
        validate_success(api_client.challenge_valuation(
            ctx["valuation"]["id"], {"challenge_note": "Reconcile to the peer set."}, TRUSTEE))
        return ctx

    def test_finalize_against_a_challenged_appraisal_is_refused(self, api):
        """PRD 3.5: "The run must still be `DRAFT`, the plan must be in `VALUATION_PENDING`
        posture, and the appraisal named by the run must be `APPROVED` — an appraisal in any
        other status is refused with `ERR_NO_APPROVED_VALUATION`."

        Design: Difficulty/cross_entity_state_dependency/run_finalize_gated_by_valuation_status_run_to_valuation
        """
        ctx = self._challenged_context()

        validate_error(api.finalize_allocation_run(ctx["run"]["id"], ADMIN_ALT),
                       ApiErrorId.ERR_NO_APPROVED_VALUATION)

        assert get_allocation_run(ctx["run"]["id"])["status"] == "DRAFT"
        assert get_plan(ctx["plan"]["id"])["plan_status"] == "VALUATION_PENDING"
        assert get_participant(ctx["participants"][0]["id"])["allocated_shares"] == 0

    def test_finalize_succeeds_once_the_appraisal_is_approved(self, api):
        """PRD 3.5: "The run also copies the approved appraisal's price into its own
        `share_price_cents`, and that copy, not the plan's live `current_share_price_cents`,
        is what the rest of the run uses."
        PRD 3.5: "Finally the plan itself advances from `VALUATION_PENDING` to
        `ALLOCATION_LOCKED`, and the plan's `version` increments by 1."

        Design: Difficulty/cross_entity_state_dependency/run_finalize_gated_by_valuation_status_run_to_valuation
        """
        ctx = self._challenged_context()
        validate_error(api.finalize_allocation_run(ctx["run"]["id"], ADMIN_ALT),
                       ApiErrorId.ERR_NO_APPROVED_VALUATION)

        validate_success(api.resubmit_valuation(ctx["valuation"]["id"],
                                                resubmit_valuation_payload(), APPRAISER))
        approved = approve_valuation(ctx["valuation"]["id"])
        assert approved["status"] == "APPROVED"
        assert approved["share_price_cents"] == 7125

        run = validate_success(api.finalize_allocation_run(ctx["run"]["id"], ADMIN_ALT))
        assert run["status"] == "FINALIZED"
        assert run["share_price_cents"] == 7125
        assert run["pool_shares"] == 500
        assert get_participant(ctx["participants"][0]["id"])["allocated_shares"] == 500
        assert get_plan(ctx["plan"]["id"])["plan_status"] == "ALLOCATION_LOCKED"


class TestEligibleSet:
    def test_allocation_eligible_set_excludes_zero_compensation_and_terminated(self, api):
        """PRD 3.5: "The eligible set is every participant of the run's plan whose `status` is
        `ACTIVE` and whose `eligible_compensation_cents` is greater than 0, taken in ascending
        `created_at` order. Participants who are `TERMINATED`, `RETIRED`, `DECEASED` or
        `DISTRIBUTED` are excluded, as are `ACTIVE` participants sitting at zero
        compensation."
        PRD 3.5: "The size of the set is recorded on the run as `eligible_participant_count`,
        and that ordering — ascending `created_at` — is also the order in which the allocation
        lines are written, so listing the run's allocation lines reproduces the eligible-set
        order the run used."

        Design: Corner/calculations/allocation_eligible_set_excludes_zero_compensation_and_terminated
        """
        set_clock("2026-03-02T00:00:00Z", SPONSOR)
        plan = create_plan(plan_name="Filter Plan", sponsor_name="Corner Corp",
                           vesting_schedule="CLIFF_3YR")
        px = create_participant(plan["id"], employee_number="E-X",
                                eligible_compensation_cents=34_500_000)
        py = create_participant(plan["id"], employee_number="E-Y", date_of_birth="1982-09-23",
                                hire_date="2016-06-01", eligible_compensation_cents=0)
        pz = create_participant(plan["id"], employee_number="E-Z", date_of_birth="1990-02-14",
                                hire_date="2019-03-15", eligible_compensation_cents=20_000_000)
        terminate_participant(pz["id"], "2026-02-28", "TERMINATION")

        closed = close_year(plan["id"])
        valuation = submit_valuation(plan["id"], closed["version"])
        approve_valuation(valuation["id"])
        run = create_allocation_run(plan["id"], valuation["id"], contributed_shares=500)
        finalized = finalize_run(run["id"])

        assert finalized["eligible_participant_count"] == 1
        assert finalized["total_capped_compensation_cents"] == 34_500_000
        assert get_participant(px["id"])["allocated_shares"] == 500
        assert get_participant(py["id"])["allocated_shares"] == 0
        assert get_participant(pz["id"])["allocated_shares"] == 0

        lines = list_share_allocations(allocation_run_id=run["id"])
        assert len(lines) == 1, "one allocation line per eligible participant"
        assert lines[0]["participant_id"] == px["id"]
        statements = list_statements(allocation_run_id=run["id"])
        assert len(statements) == 1 and statements[0]["participant_id"] == px["id"]

    def test_finalize_with_empty_eligible_set_returns_no_eligible_participants(self, api):
        """PRD 3.5: "If the set comes out empty the finalize is refused with
        `ERR_NO_ELIGIBLE_PARTICIPANTS`."
        PRD 3.5: "The eligible set is every participant of the run's plan whose `status` is
        `ACTIVE` and whose `eligible_compensation_cents` is greater than 0, taken in ascending
        `created_at` order."

        Design: Corner/calculations/finalize_with_empty_eligible_set_returns_no_eligible_participants
        """
        ctx = setup_draft_run(
            contributed_shares=500,
            plan_overrides={"plan_name": "Empty Set Plan", "sponsor_name": "Corner Corp",
                            "vesting_schedule": "CLIFF_3YR"},
            participants=[{"employee_number": "E-000", "eligible_compensation_cents": 0}],
        )

        validate_error(api.finalize_allocation_run(ctx["run"]["id"], ADMIN_ALT),
                       ApiErrorId.ERR_NO_ELIGIBLE_PARTICIPANTS)

        assert get_allocation_run(ctx["run"]["id"])["status"] == "DRAFT"
        plan = get_plan(ctx["plan"]["id"])
        assert plan["plan_status"] == "VALUATION_PENDING"
        assert plan["total_plan_shares"] == 0
        _rows, meta = validate_paginated(
            api.list_share_allocations(ADMIN, params={"allocation_run_id": ctx["run"]["id"]})
        )
        assert meta["total_count"] == 0


class TestRunConcurrencyAndImmediacy:
    def test_stale_expected_plan_version_on_allocation_run_create_returns_412(self, api):
        """PRD 2.7: "Opening an allocation run — the `POST /allocation-runs` request —
        likewise requires the non-optional input field `expected_plan_version`, carrying the
        client's last observed `version` of the target `EsopPlan`, and a mismatch with the
        plan's current `version` is rejected with `ERR_STALE_PLAN_VERSION` and HTTP 412."
        PRD 2.7: "A plan may legitimately carry more than one draft run at a time, so no state
        precondition rejects a second create; the stale version is what identifies an
        administrator whose view of `unallocated_released_shares` and
        `unallocated_forfeiture_shares` — the two pool components the run will consume — has
        gone out of date."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_plan_version_on_allocation_run_create_returns_412
        """
        ctx = setup_plan_with_price(
            plan_overrides={"plan_name": "OCC Run", "sponsor_name": "Corner Corp",
                            "vesting_schedule": "CLIFF_3YR", "distribution_policy": "LUMP_SUM"},
            participants=[{"employee_number": "E-950"}],
        )
        priced_version = ctx["plan"]["version"]
        first_run = create_allocation_run(ctx["plan"]["id"], ctx["valuation"]["id"],
                                          contributed_shares=500,
                                          expected_plan_version=priced_version)

        stale = create_allocation_run_payload(
            ctx["plan"]["id"], ctx["valuation"]["id"], priced_version, contributed_shares=400)
        validate_error(api.create_allocation_run(stale, ADMIN), ApiErrorId.ERR_STALE_PLAN_VERSION)
        assert get_plan(ctx["plan"]["id"])["draft_run_count"] == 1, (
            "the refused create opens no run"
        )

        stale["expected_plan_version"] = get_plan(ctx["plan"]["id"])["version"]
        second = validate_success(api.create_allocation_run(stale, ADMIN), 201)
        assert second["status"] == "DRAFT"
        assert second["contributed_shares"] == 400
        assert get_plan(ctx["plan"]["id"])["draft_run_count"] == 2
        assert get_allocation_run(first_run["id"])["status"] == "DRAFT"

    def test_finalize_response_reflects_every_cascade_in_the_same_request(self, api):
        """PRD 3.5: "A successful finalize moves the run from `DRAFT` to `FINALIZED` and
        writes `finalized_by_user_id` from the finalizing administrator's `X-User-ID`,
        alongside every computed run statistic named above. An allocation line is created for
        every eligible participant, and each participant's `allocated_shares` grows by their
        award."
        PRD 3.6: "Every allocation that succeeds produces one statement per eligible
        participant, generated inside the finalize as a frozen snapshot of that participant's
        year."
        PRD 3.5: "On the plan itself, `unallocated_released_shares` is set to 0 — every
        released share has now found an account or become residue — and
        `unallocated_forfeiture_shares` is set to the run's `residual_shares`."

        Design: Corner/consistency_model/finalize_response_reflects_every_cascade_in_the_same_request
        """
        ctx = setup_draft_run(
            contributed_shares=500,
            plan_overrides={"plan_name": "Immediate Plan", "sponsor_name": "Corner Corp",
                            "vesting_schedule": "CLIFF_3YR"},
            participants=[{"employee_number": "E-960"}],
        )
        participant_id = ctx["participants"][0]["id"]

        run = validate_success(api.finalize_allocation_run(ctx["run"]["id"], ADMIN_ALT))
        assert run["status"] == "FINALIZED"
        assert run["pool_shares"] == 500
        assert run["share_price_cents"] == 7125
        assert run["eligible_participant_count"] == 1
        assert run["passes_executed"] == 1
        assert run["residual_shares"] == 0
        assert run["capped_participant_count"] == 0
        assert run["finalized_by_user_id"] == "tpa-02"

        participant = get_participant(participant_id)
        assert participant["allocated_shares"] == 500
        assert participant["vested_shares"] == 500

        line = get_allocation_line(run["id"], participant_id)
        assert line["allocated_shares"] == 500
        assert line["annual_additions_cents"] == 3_562_500

        statement = list_statements(allocation_run_id=run["id"])[0]
        assert statement["closing_shares"] == 500
        assert statement["delivery_status"] == "GENERATED"

        plan = get_plan(ctx["plan"]["id"])
        assert plan["plan_status"] == "ALLOCATION_LOCKED"
        assert plan["total_plan_shares"] == 500
        assert plan["allocated_shares_total"] == 500
        assert plan["unallocated_released_shares"] == 0
        assert_share_conservation(plan)
