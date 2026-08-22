"""The plan-year cycle, the posture gate and the terminal freeze."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_participant,
    create_participant_payload,
    create_plan,
    get_participant,
    get_plan,
    get_valuation,
    set_clock,
    setup_draft_run,
    setup_finalized_run,
    validate_error,
    validate_success,
)

SPONSOR = TEST_USERS["sponsor_headers"]
TRUSTEE = TEST_USERS["trustee_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestPlanYearCycle:
    def test_plan_year_cycle_returns_to_open_with_incremented_year(self, api):
        """PRD 3.6: "On success `plan_status` returns from `ALLOCATION_LOCKED` to `OPEN` and
        `plan_year` increases by exactly 1, reopening the plan for enrolment, payroll updates
        and new leveraged borrowing."
        PRD 3.6: "The rollover leaves `current_share_price_cents` exactly where it is."
        PRD 3.6: "What the rollover does recompute is diversification eligibility: for every
        participant of the plan, `diversification_first_eligible_plan_year` is recalculated
        from that participant's birth year and hire year against the plan's
        `diversification_min_age` and `diversification_min_years`, and
        `diversification_eligible` is re-evaluated against the new `plan_year`, so owners who
        age into their qualified election period become eligible on the rollover and owners
        whose six-year period has run out fall out of eligibility on it."

        Design: Corner/state_machines/plan_year_cycle_returns_to_open_with_incremented_year
        """
        ctx = setup_finalized_run(
            contributed_shares=500,
            plan_overrides={"plan_name": "Cycle Rollover", "sponsor_name": "Corner Corp",
                            "vesting_schedule": "CLIFF_3YR"},
            participants=[{"employee_number": "E-801", "date_of_birth": "1968-05-20",
                           "hire_date": "2010-08-15",
                           "eligible_compensation_cents": 34_500_000}],
        )
        assert ctx["plan"]["plan_status"] == "ALLOCATION_LOCKED"

        plan = validate_success(api.rollover_plan(ctx["plan"]["id"], SPONSOR))
        assert plan["plan_status"] == "OPEN", "rolling over reopens the plan"
        assert plan["plan_year"] == 2027, "plan_year increases by exactly 1"
        assert plan["current_share_price_cents"] == 7125, (
            "last year's approved price stays in force across the rollover"
        )
        assert plan["allocated_shares_total"] == 500
        assert plan["total_plan_shares"] == 500
        assert plan["draft_run_count"] == 0

        participant = get_participant(ctx["participants"][0]["id"])
        assert participant["diversification_first_eligible_plan_year"] == 2023
        assert participant["diversification_eligible"] is True, (
            "plan year 2027 still falls inside the six-year span anchored at 2023"
        )

    def test_close_year_twice_returns_invalid_state(self, api):
        """PRD 2.9: "Operations that require a specific posture are refused with
        `ERR_PLAN_STATE_INVALID` and HTTP 409 when the plan is in a different one. Enrolling a
        participant, updating a participant's payroll facts, recording a leveraged loan and
        closing the year all require `OPEN`."
        PRD 3.3: "When contributions and census maintenance for the year are done, the
        `PlanSponsor` closes the year, which requires the plan to be `OPEN` and advances
        `plan_status` from `OPEN` to `VALUATION_PENDING`."

        Design: Corner/state_machines/close_year_twice_returns_invalid_state
        """
        set_clock("2026-03-02T00:00:00Z", SPONSOR)
        plan = create_plan(plan_name="Idem Plan", sponsor_name="Corner Corp")
        closed = validate_success(api.close_year(plan["id"], SPONSOR))
        assert closed["plan_status"] == "VALUATION_PENDING"
        assert closed["version"] == 2, "closing the year increments the plan's version by 1"

        validate_error(api.close_year(plan["id"], SPONSOR), ApiErrorId.ERR_PLAN_STATE_INVALID)

        after = get_plan(plan["id"])
        assert after["plan_status"] == "VALUATION_PENDING", "the refusal changes nothing"
        assert after["version"] == 2, "a refused call is not a mutation and moves no version"


class TestFreezeDoctrine:
    def test_frozen_plan_is_terminal_and_refuses_every_mutation(self, api):
        """PRD 2.9: "Once `plan_status` is `FROZEN`, every mutating operation governed by that
        plan is refused with `ERR_PLAN_FROZEN` and HTTP 409 — every create, every state
        action, every patch."
        PRD 3.9: "There is no unfreeze: once `plan_status` is `FROZEN` the plan stays there,
        every mutating operation governed by it is refused with `ERR_PLAN_FROZEN`, and only
        reads and the logical-clock capability continue to work."
        PRD 3.9: "It is available from `OPEN`, from `VALUATION_PENDING` and from
        `ALLOCATION_LOCKED` — from anything except `FROZEN` itself — and it carries a single
        input, `reason`, which is recorded verbatim on the plan as `frozen_reason`."

        Design: Corner/state_machines/frozen_plan_is_terminal_and_refuses_every_mutation
        """
        set_clock("2026-03-02T00:00:00Z", SPONSOR)
        plan = create_plan(plan_name="Freeze Plan", sponsor_name="Corner Corp")
        participant = create_participant(plan["id"], employee_number="E-990",
                                         eligible_compensation_cents=34_500_000)
        frozen = validate_success(
            api.freeze_plan(plan["id"], {"reason": "DOL examination opened."}, TRUSTEE)
        )
        assert frozen["plan_status"] == "FROZEN"
        assert frozen["frozen_reason"] == "DOL examination opened."

        validate_error(api.close_year(plan["id"], SPONSOR), ApiErrorId.ERR_PLAN_FROZEN)
        validate_error(api.rollover_plan(plan["id"], SPONSOR), ApiErrorId.ERR_PLAN_FROZEN)
        validate_error(
            api.create_participant(
                create_participant_payload(plan["id"], employee_number="E-991"), SPONSOR),
            ApiErrorId.ERR_PLAN_FROZEN,
        )
        validate_error(
            api.freeze_plan(plan["id"], {"reason": "Second attempt."}, TRUSTEE),
            ApiErrorId.ERR_PLAN_FROZEN,
        )

        assert validate_success(api.get_plan(plan["id"], SPONSOR))["plan_status"] == "FROZEN", (
            "reads are entirely unaffected by the freeze"
        )
        assert get_participant(participant["id"])["status"] == "ACTIVE", (
            "an ACTIVE participant is untouched by the freeze"
        )

    def test_freeze_cascade_rejects_open_valuations_and_voids_draft_runs(self, api):
        """PRD 3.9: "Every appraisal of the plan sitting in `SUBMITTED` or `CHALLENGED` is
        driven to `REJECTED` with `rejected_reason` set to `PLAN_FROZEN`, and
        `open_valuation_count` is set to 0. Every allocation run sitting in `DRAFT` is driven
        to `VOID` with `void_reason` set to `PLAN_FROZEN`, and `draft_run_count` is set to 0."

        Design: Corner/state_machines/freeze_cascade_rejects_open_valuations_and_voids_draft_runs
        """
        ctx = setup_draft_run(
            contributed_shares=500,
            plan_overrides={"plan_name": "Cascade Freeze", "sponsor_name": "Corner Corp"},
            participants=[{"employee_number": "E-991"}],
            approve=False,
        )
        plan = validate_success(
            api.freeze_plan(ctx["plan"]["id"], {"reason": "Fiduciary review."}, TRUSTEE)
        )

        assert plan["plan_status"] == "FROZEN"
        assert plan["open_valuation_count"] == 0, "open_valuation_count is set to 0 outright"
        assert plan["draft_run_count"] == 0, "draft_run_count is set to 0 outright"
        assert plan["current_share_price_cents"] == 0
        assert plan["allocated_shares_total"] == 0

        valuation = get_valuation(ctx["valuation"]["id"])
        assert valuation["status"] == "REJECTED"
        assert valuation["rejected_reason"] == "PLAN_FROZEN"

        run = validate_success(api.get_allocation_run(ctx["run"]["id"], ADMIN))
        assert run["status"] == "VOID"
        assert run["void_reason"] == "PLAN_FROZEN"
