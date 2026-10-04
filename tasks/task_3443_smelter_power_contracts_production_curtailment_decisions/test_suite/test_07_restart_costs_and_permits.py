"""Restart cost reconciliation, environmental-permit gating, and the
state-vs-safety evaluation order (PRD §3.6, §3.8, §2.7).
"""
import pytest
from test_helpers import (
    ApiErrorId,
    create_environmental_permit_payload,
    create_restart_plan_payload,
    create_spl_permit,
    get_success_data,
    set_clock,
    setup_idled_potline,
    setup_planned_restart,
    setup_site,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRestartCompleteCascade:
    def _setup_in_progress_restart(self, api, smelter_manager_headers):
        """Idled at the default clock 2026-09-01; HOT plan for 2026-09-03;
        clock walked to 09-03 for start and 09-06 for completion."""
        env = setup_planned_restart(with_permit=True,
                                    planned_restart_at="2026-09-03T00:00:00Z")
        set_clock("2026-09-03T00:00:00Z")
        validate_success(api.start_restart_plan(env["plan"]["id"], smelter_manager_headers))
        set_clock("2026-09-06T00:00:00Z")
        return env

    def test_complete_reconciles_actual_cost(self, api, smelter_manager_headers):
        """PRD §3.6: "The plan's `actual_cost_usd` — null until then — is
        computed chronologically from realized timestamps on the same class
        schedule: the base plus the per-tonne-per-day rate times
        `capacity_tpd`, plus the per-idle-day rate times the realized idle
        days from `curtailed_since` or `last_full_shutdown_at` to the start
        timestamp, plus a crew cost of 15,000 USD per realized restart day
        from start to completion".
        PRD §3.6: "The estimate excludes this crew cost entirely, so identical
        plan inputs diverge between estimate and actual whenever realized
        timing slips."

        Design: Difficulty/transitive_cascade/restart_complete_cascade_depth2
        """
        env = self._setup_in_progress_restart(api, smelter_manager_headers)
        data = validate_success(
            api.complete_restart_plan(env["plan"]["id"], smelter_manager_headers)
        )
        assert data["status"] == "COMPLETED"
        # HOT: 80000 + 40*500 + 0*2 idle days + 15000*3 restart days
        assert data["actual_cost_usd"] == 145000
        assert data["estimated_cost_usd"] == 100000

    def test_complete_returns_smelter_to_full_operation(self, api, smelter_manager_headers):
        """PRD §3.6: "returns the potline from `RESTARTING` to `OPERATING`,
        clearing `curtailment_depth_pct` to 0 and both `curtailed_since` and
        `active_decision_id` to null".
        PRD §2.11: "`FULL_OPERATION` when the smelter has no potlines at all
        or every potline is `OPERATING`".

        Design: Difficulty/transitive_cascade/restart_complete_cascade_depth2
        """
        env = self._setup_in_progress_restart(api, smelter_manager_headers)
        validate_success(api.complete_restart_plan(env["plan"]["id"], smelter_manager_headers))
        potline = get_success_data(api.get_potline(env["potline"]["id"], smelter_manager_headers))
        assert potline["operating_status"] == "OPERATING"
        smelter = get_success_data(api.get_smelter(env["smelter"]["id"], smelter_manager_headers))
        assert smelter["operating_posture"] == "FULL_OPERATION"
        assert smelter["curtailed_capacity_tpd"] == 0


class TestWarmClassEstimate:
    def test_warm_restart_estimate_literal(self, api, smelter_manager_headers,
                                           platform_admin_headers):
        """PRD §3.6: "a `WARM` restart carries a base of 350,000 USD plus 120
        USD per tonne-per-day plus 2,500 USD per idle day".
        PRD §2.11: "`WARM` once it has been `IDLE` for at least 24 hours but
        less than 720 hours (thirty days)".
        PRD §3.6: "Idle days for the estimate run from the potline's
        `curtailed_since` (or its `last_full_shutdown_at` when the line is
        `SHUTDOWN`) to `planned_restart_at`, counted in whole calendar days".

        Design: Corner/calculations/restart_cost_warm_class_estimate_literal
        """
        env = setup_idled_potline()  # idled at the default clock 2026-09-01
        set_clock("2026-09-10T00:00:00Z")  # 216h idle -> WARM
        resp = api.create_restart_plan(
            create_restart_plan_payload(env["potline"]["id"],
                                        planned_restart_at="2026-09-24T00:00:00Z"),
            smelter_manager_headers,
        )
        data = validate_success(resp, 201)
        assert data["restart_cost_class"] == "WARM"
        # 350000 + 120*500 + 2500*23
        assert data["estimated_cost_usd"] == 467500


class TestRestartPermitGate:
    def test_start_without_spl_permit_rejected(self, api, smelter_manager_headers):
        """PRD §3.6: "an `ACTIVE` environmental permit of the `SPL_DISPOSAL`
        family must exist for the potline's smelter, and a permit that is
        absent, suspended, or expired yields `ERR_PERMIT_NOT_ACTIVE`
        (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/restart_start_requires_active_spl_permit
        """
        env = setup_planned_restart(with_permit=False)
        resp = api.start_restart_plan(env["plan"]["id"], smelter_manager_headers)
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ACTIVE)
        plans, _ = validate_paginated(
            api.list_restart_plans(env["potline"]["id"], smelter_manager_headers)
        )
        assert plans[0]["status"] == "PLANNED"

    def test_start_succeeds_once_permit_active(self, api, smelter_manager_headers):
        """PRD §3.6: "an `ACTIVE` environmental permit of the `SPL_DISPOSAL`
        family must exist for the potline's smelter".
        PRD §3.6: "A successful start drives the potline from `IDLE` or
        `SHUTDOWN` into `RESTARTING`".

        Design: Difficulty/cross_entity_state_dependency/restart_start_requires_active_spl_permit
        """
        env = setup_planned_restart(with_permit=False)
        create_spl_permit(env["smelter"]["id"])
        data = validate_success(api.start_restart_plan(env["plan"]["id"], smelter_manager_headers))
        assert data["status"] == "IN_PROGRESS"
        potline = get_success_data(api.get_potline(env["potline"]["id"], smelter_manager_headers))
        assert potline["operating_status"] == "RESTARTING"


class TestStateMasksPermitSafety:
    def _setup_started_plan_with_suspended_permit(self, api, smelter_manager_headers,
                                                  ehs_manager_headers):
        env = setup_planned_restart(with_permit=True)
        validate_success(api.start_restart_plan(env["plan"]["id"], smelter_manager_headers))
        validate_success(
            api.suspend_environmental_permit(env["permit"]["id"], ehs_manager_headers)
        )
        return env

    def test_state_error_masks_permit_error(self, api, smelter_manager_headers,
                                            ehs_manager_headers):
        """PRD §2.7: "When several checks could reject the same request, the
        platform evaluates them in one fixed global order, and a
        lower-numbered check masks every higher-numbered one."
        PRD §2.7: "9. Restart-plan state compatibility —
        `ERR_RESTART_PLAN_INVALID_STATE`."
        PRD §2.7: "11. Presence of an active spent-potlining-disposal permit
        on restart start — `ERR_PERMIT_NOT_ACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/restart_start_state_beats_permit_safety
        """
        env = self._setup_started_plan_with_suspended_permit(
            api, smelter_manager_headers, ehs_manager_headers
        )
        resp = api.start_restart_plan(env["plan"]["id"], smelter_manager_headers)
        validate_error(resp, ApiErrorId.ERR_RESTART_PLAN_INVALID_STATE)

    def test_double_violation_leaves_plan_unchanged(self, api, smelter_manager_headers,
                                                    ehs_manager_headers):
        """PRD §2.7: "When several checks could reject the same request, the
        platform evaluates them in one fixed global order, and a
        lower-numbered check masks every higher-numbered one."
        PRD §3.6: "a start invoked from any other plan `status` is rejected
        with `ERR_RESTART_PLAN_INVALID_STATE` (HTTP 409)".

        Design: Difficulty/priority_pair_validation_conflict/restart_start_state_beats_permit_safety
        """
        env = self._setup_started_plan_with_suspended_permit(
            api, smelter_manager_headers, ehs_manager_headers
        )
        validate_error(
            api.start_restart_plan(env["plan"]["id"], smelter_manager_headers),
            ApiErrorId.ERR_RESTART_PLAN_INVALID_STATE,
        )
        plans, _ = validate_paginated(
            api.list_restart_plans(env["potline"]["id"], smelter_manager_headers)
        )
        assert plans[0]["status"] == "IN_PROGRESS"


class TestPermitLifecycle:
    def test_double_suspend_rejected(self, api, ehs_manager_headers):
        """PRD §3.8: "an `EHSManager` may suspend an `ACTIVE` permit, moving
        its `status` to `SUSPENDED`, which is terminal — suspending one that
        is not `ACTIVE` is rejected with `ERR_INVALID_LIFECYCLE_STATE`".

        Design: Corner/state_machines/permit_double_suspend_rejected
        """
        smelter_env = setup_site(with_potline=False)
        permit = create_spl_permit(smelter_env["smelter"]["id"])
        suspended = validate_success(
            api.suspend_environmental_permit(permit["id"], ehs_manager_headers)
        )
        assert suspended["version"] == permit["version"] + 1

        resp = api.suspend_environmental_permit(permit["id"], ehs_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_LIFECYCLE_STATE)
        permits, _ = validate_paginated(
            api.list_environmental_permits(smelter_env["smelter"]["id"], ehs_manager_headers)
        )
        assert permits[0]["version"] == suspended["version"]

    def test_duplicate_active_permit_type_rejected(self, api, ehs_manager_headers):
        """PRD §3.8: "At most one `ACTIVE` permit may exist per smelter and
        permit type: registering a duplicate live pair is rejected with
        `ERR_PERMIT_DUPLICATE_TYPE` (HTTP 409)."

        Design: Corner/validations/permit_duplicate_active_type_rejected
        """
        smelter_env = setup_site(with_potline=False)
        sm = smelter_env["smelter"]["id"]
        create_spl_permit(sm, permit_type="EMISSIONS")
        resp = api.create_environmental_permit(
            create_environmental_permit_payload(
                sm, permit_type="EMISSIONS",
                valid_from="2026-03-01T00:00:00Z", valid_to="2028-01-01T00:00:00Z",
            ),
            ehs_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PERMIT_DUPLICATE_TYPE)
