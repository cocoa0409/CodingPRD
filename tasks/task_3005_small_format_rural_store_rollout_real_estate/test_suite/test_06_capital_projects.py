"""Capital projects: scoring, segregation of duties, budget gate, ranking."""

import pytest

from test_helpers import (
    ApiErrorId,
    create_active_rollout,
    create_capital_project,
    create_cannibalization_study,
    create_existing_store,
    create_qualified_trade_area,
    create_trade_area,
    finalize_study,
    get_success_data,
    make_finance_analyst_headers,
    make_program_admin_headers,
    read_rollout,
    setup_store_with_format,
    submit_capital_project,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
REAL_ESTATE = TEST_USERS["real_estate_manager_headers"]
FINANCE = TEST_USERS["finance_analyst_headers"]

FRESH_AREA = {
    "drive_time_minutes": 18,
    "household_count": 2000,
    "median_household_income_cents": 4500000,
    "grocery_gap_pct": 30,
}


def _program_with_existing_store(api, budget=2000000000, sales=50000000):
    rollout = create_active_rollout(name="P", new_build_capital_budget_cents=budget)
    ta = create_trade_area(
        rollout["id"], name="T0", drive_time_minutes=12, household_count=1000,
        median_household_income_cents=4000000, grocery_gap_pct=20,
    )
    existing = create_existing_store(
        rollout["id"], ta["id"], name="X", open_year_sales_cents=sales
    )
    return rollout, existing


def _submitted_remodel(api, rollout, existing, cost=80000000, uplift=60000000,
                       analyst=None):
    project = create_capital_project(
        rollout["id"], "REMODEL", existing["id"],
        remodel_cost_cents=cost, projected_uplift_cents=uplift,
    )
    return submit_capital_project(
        rollout["id"], project["id"], analyst_user_id=analyst
    )


def _fresh_store_with_final_study(api, rollout, existing):
    area = create_qualified_trade_area(rollout["id"], name="F", **FRESH_AREA)
    store = setup_store_with_format(rollout["id"], area["id"], name="S")
    # X@0.20 on sales 200000000 -> impact 8.00, transfer 10.99 -> PROCEED.
    study = create_cannibalization_study(
        rollout["id"],
        store["id"],
        [{"existing_store_id": existing["id"], "overlap_weight": 0.20}],
    )
    finalized = finalize_study(rollout["id"], study["id"])
    return store, finalized


class TestDecideStateAndPriority:
    def test_decide_on_draft_capital_project_rejected(self, api):
        """PRD §3.8: "Decisions belong to `PROGRAM_ADMIN` and move a
        `SUBMITTED` project to `APPROVED` or `REJECTED` according to the
        `decision` supplied."
        PRD §2.11: "state legality — the target resource must be in a state
        from which the requested transition is defined, else
        `ERR_INVALID_STATE`"

        Design: Corner/state_machines/decide_on_draft_capital_project_rejected
        """
        rollout, existing = _program_with_existing_store(api)
        project = create_capital_project(
            rollout["id"], "REMODEL", existing["id"],
            remodel_cost_cents=80000000, projected_uplift_cents=60000000,
        )
        assert project["status"] == "DRAFT"
        program = read_rollout(rollout["id"])
        resp = api.decide_capital_project(
            project["id"],
            {
                "rollout_program_id": rollout["id"],
                "decision": "APPROVE",
                "expected_program_version": program["version"],
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_occ_stale_version_beats_program_not_active_on_decide(self, api):
        """PRD §2.11: "(6) program activity — child-creating and committing
        operations require the program to be `ACTIVE`, else
        `ERR_PROGRAM_NOT_ACTIVE`; ... and (18) optimistic-concurrency checks,
        else `ERR_STALE_VERSION`."

        Design: Difficulty/priority_pair_validation_conflict/occ_stale_version_beats_program_not_active_on_decide
        """
        rollout, existing = _program_with_existing_store(api)
        project = _submitted_remodel(api, rollout, existing)
        # Capture a program version, then advance it by cycling the program.
        stale_version = read_rollout(rollout["id"])["version"]
        validate_success(api.deactivate_rollout(rollout["id"], ADMIN), 200)
        validate_success(api.activate_rollout(rollout["id"], ADMIN), 200)
        validate_success(api.deactivate_rollout(rollout["id"], ADMIN), 200)
        # Program is DRAFT and the captured version is stale: the program gate
        # (priority 6) is reported before the OCC check (priority 18).
        resp = api.decide_capital_project(
            project["id"],
            {
                "rollout_program_id": rollout["id"],
                "decision": "APPROVE",
                "expected_program_version": stale_version,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE)

    def test_decide_requires_active_program_even_with_current_version(self, api):
        """PRD §3.1: "While `DRAFT`, the program refuses every child-creating
        and committing operation — screening, store creation, agreement
        activation, route planning, opening-plan creation, study creation,
        capital submission, and capital decisions all reject with
        `ERR_PROGRAM_NOT_ACTIVE` until activation has occurred."

        Design: Difficulty/priority_pair_validation_conflict/occ_stale_version_beats_program_not_active_on_decide
        """
        rollout, existing = _program_with_existing_store(api)
        project = _submitted_remodel(api, rollout, existing)
        validate_success(api.deactivate_rollout(rollout["id"], ADMIN), 200)
        current = read_rollout(rollout["id"])["version"]
        resp = api.decide_capital_project(
            project["id"],
            {
                "rollout_program_id": rollout["id"],
                "decision": "APPROVE",
                "expected_program_version": current,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE)


class TestSegregationOfDuties:
    def test_segregation_of_duties_beats_capital_budget_on_decide(self, api):
        """PRD §3.8: "Segregation of duties is enforced first among the
        business checks: the deciding `PROGRAM_ADMIN` must not be the
        `FINANCE_ANALYST` recorded in `submitted_by`; a match fails with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_capital_budget_on_decide
        """
        rollout, existing = _program_with_existing_store(api, budget=50000000)
        project = _submitted_remodel(
            api, rollout, existing, cost=80000000, uplift=60000000, analyst="fa_1"
        )
        program = read_rollout(rollout["id"])
        # Same user id decides: SoD fires before the budget gate even though
        # the 80000000-cent cost also exceeds the 50000000-cent budget.
        resp = api.decide_capital_project(
            project["id"],
            {
                "rollout_program_id": rollout["id"],
                "decision": "APPROVE",
                "expected_program_version": program["version"],
            },
            make_program_admin_headers("fa_1"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_distinct_decider_passes_segregation_check(self, api):
        """PRD §3.8: "Segregation of duties is enforced first among the
        business checks: the deciding `PROGRAM_ADMIN` must not be the
        `FINANCE_ANALYST` recorded in `submitted_by`; a match fails with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD §3.8: "the project's effective cost — `remodel_cost_cents`,
        `project_cost_cents`, or `new_build_cost_cents` according to kind —
        must not exceed the program's `available_capital_cents`, else
        `ERR_CAPITAL_BUDGET_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_capital_budget_on_decide
        """
        rollout, existing = _program_with_existing_store(api, budget=50000000)
        project = _submitted_remodel(
            api, rollout, existing, cost=80000000, uplift=60000000, analyst="fa_1"
        )
        program = read_rollout(rollout["id"])
        # A distinct decider clears the SoD gate; the budget gate then rejects.
        resp = api.decide_capital_project(
            project["id"],
            {
                "rollout_program_id": rollout["id"],
                "decision": "APPROVE",
                "expected_program_version": program["version"],
            },
            make_program_admin_headers("admin_1"),
        )
        validate_error(resp, ApiErrorId.ERR_CAPITAL_BUDGET_EXCEEDED)


class TestBudgetGate:
    def test_error_capital_budget_exceeded_on_approve(self, api):
        """PRD §3.8: "Approval then checks the budget: the project's effective
        cost — `remodel_cost_cents`, `project_cost_cents`, or
        `new_build_cost_cents` according to kind — must not exceed the
        program's `available_capital_cents`, else `ERR_CAPITAL_BUDGET_EXCEEDED`."

        Design: Corner/errors/error_capital_budget_exceeded_on_approve
        """
        rollout, existing = _program_with_existing_store(api, budget=50000000)
        project = _submitted_remodel(
            api, rollout, existing, cost=80000000, uplift=60000000, analyst="fa_1"
        )
        program = read_rollout(rollout["id"])
        resp = api.decide_capital_project(
            project["id"],
            {
                "rollout_program_id": rollout["id"],
                "decision": "APPROVE",
                "expected_program_version": program["version"],
            },
            make_program_admin_headers("admin_1"),
        )
        validate_error(resp, ApiErrorId.ERR_CAPITAL_BUDGET_EXCEEDED)

        # The budget gate applies to approval only: rejection succeeds.
        current = read_rollout(rollout["id"])["version"]
        rejected = validate_success(
            api.decide_capital_project(
                project["id"],
                {
                    "rollout_program_id": rollout["id"],
                    "decision": "REJECT",
                    "expected_program_version": current,
                },
                make_program_admin_headers("admin_1"),
            ),
            200,
        )
        assert rejected["status"] == "REJECTED"


class TestNewBuildStudyGating:
    def test_new_build_submit_requires_final_study(self, api):
        """PRD §3.8: "A `NEW_BUILD` submission additionally requires the
        subject store to hold a `FINAL` cannibalization study that has not been
        superseded; without one the submit fails with `ERR_STUDY_NOT_FINAL`."

        Design: Difficulty/cross_entity_state_dependency/new_build_submit_requires_final_study
        """
        rollout, existing = _program_with_existing_store(api, sales=200000000)
        area = create_qualified_trade_area(rollout["id"], name="F", **FRESH_AREA)
        store = setup_store_with_format(rollout["id"], area["id"], name="S")
        # Study left DRAFT: submit must fail.
        study = create_cannibalization_study(
            rollout["id"],
            store["id"],
            [{"existing_store_id": existing["id"], "overlap_weight": 0.20}],
        )
        project = create_capital_project(rollout["id"], "NEW_BUILD", store["id"])
        resp = api.submit_capital_project(
            project["id"], {"rollout_program_id": rollout["id"]}, FINANCE
        )
        validate_error(resp, ApiErrorId.ERR_STUDY_NOT_FINAL)

        # Finalize the study, then the identical submit succeeds.
        finalized = finalize_study(rollout["id"], study["id"])
        assert finalized["status"] == "FINAL"
        # 10.99% > 8 (and no entry impact >12) -> MITIGATE, still finalizable.
        assert finalized["recommendation"] == "MITIGATE"
        assert finalized["transfer_pct"] == pytest.approx(10.99, abs=0.001)

        submitted = submit_capital_project(rollout["id"], project["id"])
        assert submitted["status"] == "SUBMITTED"
        # npv = 145600000*3 - 500000000 = -63200000; score = -12.64.
        assert submitted["capital_score"] == pytest.approx(-12.64, abs=0.001)

    def test_new_build_submit_blocked_without_any_study(self, api):
        """PRD §3.8: "A `NEW_BUILD` submission additionally requires the
        subject store to hold a `FINAL` cannibalization study that has not been
        superseded; without one the submit fails with `ERR_STUDY_NOT_FINAL`."

        Design: Difficulty/cross_entity_state_dependency/new_build_submit_requires_final_study
        """
        rollout, existing = _program_with_existing_store(api, sales=200000000)
        area = create_qualified_trade_area(rollout["id"], name="F", **FRESH_AREA)
        store = setup_store_with_format(rollout["id"], area["id"], name="S")
        project = create_capital_project(rollout["id"], "NEW_BUILD", store["id"])
        resp = api.submit_capital_project(
            project["id"], {"rollout_program_id": rollout["id"]}, FINANCE
        )
        validate_error(resp, ApiErrorId.ERR_STUDY_NOT_FINAL)


class TestCapitalScoring:
    def test_capital_scoring_newbuild_uses_store_revenue(self, api):
        """PRD §3.8: "The score itself is a three-year net-present-value ratio:
        the uplift — `projected_uplift_cents` for remodels and relocations, the
        store's `projected_revenue_cents` for new builds — is multiplied by 3
        and reduced by the effective cost to give the NPV in cents;
        `capital_score` is the NPV divided by the effective cost, expressed as
        a percentage, multiplied by a kind multiplier — 1.1 for `REMODEL`, 0.9
        for `RELOCATION`, 1.0 for `NEW_BUILD` — and rounded half up to two
        decimal places."
        PRD §3.8: "For `NEW_BUILD`, the effective cost `new_build_cost_cents`
        is computed, not supplied: it is the store's `build_cost_cents` reduced
        by any penalty credit from the store's `COMPLETED` agreement, and zero
        when no agreement has completed."

        Design: Corner/calculations/capital_scoring_newbuild_uses_store_revenue
        """
        rollout, existing = _program_with_existing_store(api, sales=200000000)
        store, _study = _fresh_store_with_final_study(api, rollout, existing)
        assert store["format_type"] == "DG_FRESH"
        project = create_capital_project(rollout["id"], "NEW_BUILD", store["id"])
        submitted = submit_capital_project(rollout["id"], project["id"])
        assert submitted["status"] == "SUBMITTED"
        assert submitted["new_build_cost_cents"] == 500000000
        assert submitted["capital_score"] == pytest.approx(-12.64, abs=0.001)

    def test_capital_plan_ranking_decided_projects(self, api):
        """PRD §3.8: "Every decision, whether approval or rejection, stamps
        `decided_at` with the decision timestamp and recomputes `rank` across
        all decided (`APPROVED` or `REJECTED`) projects in the program:
        projects sort by `capital_score` descending, with ties broken by
        `decided_at` ascending so earlier decisions rank first."

        Design: Corner/calculations/capital_plan_ranking_decided_projects
        """
        rollout, existing_x = _program_with_existing_store(api)
        ta = create_trade_area(
            rollout["id"], name="T1", drive_time_minutes=12, household_count=1000,
            median_household_income_cents=4000000, grocery_gap_pct=20,
        )
        existing_y = get_success_data(
            api.create_store(
                {
                    "rollout_program_id": rollout["id"],
                    "trade_area_id": ta["id"],
                    "name": "Y",
                    "is_existing": True,
                    "format_type": "TRADITIONAL",
                    "open_year_sales_cents": 60000000,
                },
                ADMIN,
            )
        )
        # REMODEL on X: npv 60000000*3 - 80000000 = 100000000; score 137.50.
        cp1 = _submitted_remodel(api, rollout, existing_x)
        # RELOCATION on Y: npv 30000000*3 - 60000000 = 30000000; score 45.00.
        cp2 = create_capital_project(
            rollout["id"], "RELOCATION", existing_y["id"],
            project_cost_cents=60000000, projected_uplift_cents=30000000,
        )
        cp2 = submit_capital_project(rollout["id"], cp2["id"])

        # Decide the lower-scoring project first; rank still follows score.
        version = read_rollout(rollout["id"])["version"]
        approved2 = validate_success(
            api.decide_capital_project(
                cp2["id"],
                {
                    "rollout_program_id": rollout["id"],
                    "decision": "APPROVE",
                    "expected_program_version": version,
                },
                make_program_admin_headers("admin_1"),
            ),
            200,
        )
        assert approved2["capital_score"] == pytest.approx(45.0, abs=0.001)

        version = read_rollout(rollout["id"])["version"]
        approved1 = validate_success(
            api.decide_capital_project(
                cp1["id"],
                {
                    "rollout_program_id": rollout["id"],
                    "decision": "APPROVE",
                    "expected_program_version": version,
                },
                make_program_admin_headers("admin_1"),
            ),
            200,
        )
        assert approved1["capital_score"] == pytest.approx(137.5, abs=0.001)
        assert approved1["rank"] == 1

        cp2_after = get_success_data(api.get_capital_project(cp2["id"], FINANCE))
        assert cp2_after["rank"] == 2

        program = read_rollout(rollout["id"])
        assert program["committed_capital_cents"] == 140000000


class TestCapitalRbac:
    def test_real_estate_manager_cannot_decide_capital(self, api):
        """PRD §2.1: "A request whose role is valid but not permitted for the
        targeted endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: the capital-project decide endpoint is authorized for
        PROGRAM_ADMIN only.

        Design: Corner/rbac/real_estate_manager_cannot_decide_capital
        """
        rollout, existing = _program_with_existing_store(api)
        project = _submitted_remodel(api, rollout, existing)
        program = read_rollout(rollout["id"])
        resp = api.decide_capital_project(
            project["id"],
            {
                "rollout_program_id": rollout["id"],
                "decision": "APPROVE",
                "expected_program_version": program["version"],
            },
            REAL_ESTATE,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_operations_lead_cannot_create_capital_project(self, api):
        """PRD §2.1: "A request whose role is valid but not permitted for the
        targeted endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: the capital-project create endpoint is authorized for
        FINANCE_ANALYST only.

        Design: Corner/rbac/operations_lead_cannot_create_capital_project
        """
        rollout, existing = _program_with_existing_store(api)
        resp = api.create_capital_project(
            {
                "rollout_program_id": rollout["id"],
                "kind": "REMODEL",
                "store_id": existing["id"],
                "remodel_cost_cents": 80000000,
                "projected_uplift_cents": 60000000,
            },
            TEST_USERS["operations_lead_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
