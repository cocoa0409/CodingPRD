"""Potline operating lifecycle: emergency curtail, idle, restore, shutdown
gating, and restart-plan preconditions (PRD §3.1, §3.6).
"""
import pytest
from test_helpers import (
    ApiErrorId,
    assert_restart_plan,
    create_restart_plan_payload,
    create_spl_permit,
    get_success_data,
    setup_idled_potline,
    setup_planned_restart,
    setup_site,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCurtailIdleRestartCycle:
    def test_curtail_then_idle_progression(self, api, smelter_manager_headers):
        """PRD §3.1: "From `OPERATING`, a depth strictly between 0 and 100
        moves the potline to `CURTAILED`".
        PRD §3.1: "a depth of exactly 100 completes the idle — the potline
        moves to `IDLE` while `curtailed_since` is deliberately left
        unchanged, because the downtime clock runs continuously from the
        moment the line first left `OPERATING`."

        Design: Difficulty/non_linear_state_machine/potline_curtail_idle_restart_cycle
        """
        env = setup_site()
        pl = env["potline"]["id"]
        curtailed = validate_success(
            api.curtail_potline(pl, {"depth_pct": 40}, smelter_manager_headers)
        )
        assert curtailed["operating_status"] == "CURTAILED"
        assert curtailed["curtailment_depth_pct"] == 40
        since_at_curtail = curtailed["curtailed_since"]
        assert since_at_curtail is not None

        idled = validate_success(
            api.curtail_potline(pl, {"depth_pct": 100}, smelter_manager_headers)
        )
        assert idled["operating_status"] == "IDLE"
        assert idled["curtailment_depth_pct"] == 100
        assert idled["curtailed_since"] == since_at_curtail

    def test_restart_cycle_returns_potline_to_operating(self, api, smelter_manager_headers):
        """PRD §3.6: "A successful start drives the potline from `IDLE` or
        `SHUTDOWN` into `RESTARTING`, incrementing both the plan's and the
        potline's `version`."
        PRD §3.6: "returns the potline from `RESTARTING` to `OPERATING`,
        clearing `curtailment_depth_pct` to 0 and both `curtailed_since` and
        `active_decision_id` to null, again bumping both versions."
        PRD §3.6: "a `HOT` restart carries a base of 80,000 USD plus 40 USD
        per tonne-per-day of the potline's `capacity_tpd`".

        Design: Difficulty/non_linear_state_machine/potline_curtail_idle_restart_cycle
        """
        env = setup_planned_restart(with_permit=True)
        plan = env["plan"]
        assert plan["restart_cost_class"] == "HOT"
        # 80000 + 40*500 (HOT per-idle-day rate is 0)
        assert plan["estimated_cost_usd"] == 100000

        started = validate_success(
            api.start_restart_plan(plan["id"], smelter_manager_headers)
        )
        assert started["status"] == "IN_PROGRESS"
        mid = get_success_data(api.get_potline(env["potline"]["id"], smelter_manager_headers))
        assert mid["operating_status"] == "RESTARTING"

        completed = validate_success(
            api.complete_restart_plan(plan["id"], smelter_manager_headers)
        )
        assert completed["status"] == "COMPLETED"
        final = get_success_data(api.get_potline(env["potline"]["id"], smelter_manager_headers))
        assert final["operating_status"] == "OPERATING"
        assert final["curtailment_depth_pct"] == 0
        assert final["curtailed_since"] is None


class TestInvalidPotlineTransitions:
    def test_curtail_from_idle_rejected(self, api, smelter_manager_headers):
        """PRD §3.1: "Invoking the curtail action from an `operating_status`
        for which no matching transition exists — for example curtailing an
        `IDLE`, `RESTARTING`, or `SHUTDOWN` line — is rejected with
        `ERR_POTLINE_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/potline_curtail_from_idle_rejected
        """
        env = setup_idled_potline()
        pl = env["potline"]["id"]
        resp = api.curtail_potline(pl, {"depth_pct": 50}, smelter_manager_headers)
        validate_error(resp, ApiErrorId.ERR_POTLINE_INVALID_STATE)
        data = get_success_data(api.get_potline(pl, smelter_manager_headers))
        assert data["operating_status"] == "IDLE"
        assert data["curtailment_depth_pct"] == 100

    def test_shutdown_from_operating_rejected(self, api, smelter_manager_headers):
        """PRD §3.1: "A `SmelterManager` may shut down only an `IDLE` potline,
        and only when its `active_decision_id` references a curtailment
        decision that is `EXECUTED` at a `depth_pct` of 100".
        PRD §3.1: "A shutdown attempted on a potline that is not `IDLE` — or
        one whose `active_decision_id` does not reference such an executed
        full-depth decision — is rejected with `ERR_POTLINE_INVALID_STATE`
        (HTTP 409)."

        Design: Corner/state_machines/potline_shutdown_from_operating_rejected
        """
        env = setup_site()
        pl = env["potline"]["id"]
        resp = api.shutdown_potline(pl, smelter_manager_headers)
        validate_error(resp, ApiErrorId.ERR_POTLINE_INVALID_STATE)
        data = get_success_data(api.get_potline(pl, smelter_manager_headers))
        assert data["operating_status"] == "OPERATING"

    def test_deepen_must_strictly_exceed_current_depth(self, api, smelter_manager_headers):
        """PRD §3.1: "a `depth_pct` outside the inclusive range from 0 to 100,
        a positive deepen that does not strictly exceed the current depth, or
        a zero-depth restore while `active_decision_id` is set are all
        rejected with `ERR_CURTAILMENT_DEPTH_INVALID` (HTTP 422)."

        Design: Corner/validations/curtail_deepen_must_strictly_exceed_current
        """
        env = setup_site()
        pl = env["potline"]["id"]
        validate_success(api.curtail_potline(pl, {"depth_pct": 40}, smelter_manager_headers))
        resp = api.curtail_potline(pl, {"depth_pct": 40}, smelter_manager_headers)
        validate_error(resp, ApiErrorId.ERR_CURTAILMENT_DEPTH_INVALID)
        data = get_success_data(api.get_potline(pl, smelter_manager_headers))
        assert data["operating_status"] == "CURTAILED"
        assert data["curtailment_depth_pct"] == 40


class TestRestartPlanPreconditions:
    def test_plan_create_on_operating_potline_rejected(self, api, smelter_manager_headers):
        """PRD §3.6: "A `SmelterManager` creates a **RestartPlan** for a
        potline that is `IDLE` or `SHUTDOWN` — any other status is rejected
        with `ERR_POTLINE_INVALID_STATE`".

        Design: Corner/state_machines/restart_plan_create_on_operating_potline_rejected
        """
        env = setup_site()
        resp = api.create_restart_plan(
            create_restart_plan_payload(env["potline"]["id"]), smelter_manager_headers
        )
        validate_error(resp, ApiErrorId.ERR_POTLINE_INVALID_STATE)

    def test_second_live_plan_rejected(self, api, smelter_manager_headers):
        """PRD §3.6: "Only one live plan may exist per potline: creating a
        plan while another is `PLANNED` or `IN_PROGRESS` for the same potline
        is rejected with `ERR_RESTART_PLAN_EXISTS` (HTTP 409)."

        Design: Corner/state_machines/restart_plan_create_while_active_plan_exists_rejected
        """
        env = setup_planned_restart(with_permit=False)
        resp = api.create_restart_plan(
            create_restart_plan_payload(env["potline"]["id"],
                                        planned_restart_at="2026-09-08T00:00:00Z"),
            smelter_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RESTART_PLAN_EXISTS)
        plans, _ = validate_paginated(
            api.list_restart_plans(env["potline"]["id"], smelter_manager_headers)
        )
        assert len(plans) == 1
        assert plans[0]["id"] == env["plan"]["id"]
        assert plans[0]["status"] == "PLANNED"

    def test_complete_from_planned_rejected(self, api, smelter_manager_headers):
        """PRD §3.6: "Completing the plan moves its `status` from
        `IN_PROGRESS` to `COMPLETED` — completion from any other `status` is
        rejected as `ERR_RESTART_PLAN_INVALID_STATE` (HTTP 409)".

        Design: Corner/state_machines/restart_complete_from_planned_rejected
        """
        env = setup_planned_restart(with_permit=False)
        resp = api.complete_restart_plan(env["plan"]["id"], smelter_manager_headers)
        validate_error(resp, ApiErrorId.ERR_RESTART_PLAN_INVALID_STATE)
        plans, _ = validate_paginated(
            api.list_restart_plans(env["potline"]["id"], smelter_manager_headers)
        )
        assert plans[0]["status"] == "PLANNED"
        assert plans[0]["actual_cost_usd"] is None
        potline = get_success_data(api.get_potline(env["potline"]["id"], smelter_manager_headers))
        assert potline["operating_status"] == "IDLE"
