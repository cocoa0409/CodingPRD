"""Decision execution: three-link cascade, reverse compensation, labor and
hedge gates, evaluation-order masking, and immediate consistency
(PRD §3.5, §3.3, §2.11, §2.7, §2.8).
"""
import pytest
from datetime import datetime, timezone
from test_helpers import (
    ApiErrorId,
    DEFAULT_CLOCK,
    create_hedge,
    create_labor_agreement,
    create_potline,
    get_success_data,
    make_smelter_manager_headers,
    setup_approved_decision,
    setup_executed_decision,
    setup_site,
    post_standard_price_set,
    propose_decision,
    approve_decision,
    validate_error,
    validate_success,
)


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _setup_two_potline_approved(api, depth_pct=60, notice_period_days=0, hedge_volume=20000):
    """Site with two OPERATING potlines (P1 500, P2 300), labor agreement,
    price set, OPEN hedge, and an APPROVED decision on P1."""
    env = setup_site()
    env["potline2"] = create_potline(env["smelter"]["id"], line_code="P2",
                                     capacity_tpd=300, amperage_ka=280)
    env["labor_agreement"] = create_labor_agreement(
        env["smelter"]["id"], notice_period_days=notice_period_days
    )
    post_standard_price_set()
    env["hedge"] = create_hedge(env["smelter"]["id"], volume_tonnes=hedge_volume)
    env["decision"] = propose_decision(env["potline"]["id"], depth_pct=depth_pct,
                                       proposer_id="mgr-1")
    env["decision"] = approve_decision(env["decision"]["id"])
    return env


class TestExecuteCascade:
    def test_execute_mutates_decision_and_potline(self, api, smelter_manager_headers):
        """PRD §3.5: "First, decision to potline: the potline moves from
        `OPERATING` or `CURTAILED` to `CURTAILED` at the decision's depth when
        that depth is below 100, or to `IDLE` at a depth of 100;
        `curtailment_depth_pct` is set to the decision's `depth_pct`;
        `curtailed_since` is stamped with the clock when the line leaves
        `OPERATING` (a deepened line keeps its existing downtime clock);
        `active_decision_id` is set to the decision's `id`; and the potline's
        `version` increments."
        PRD §3.5: "The decision itself records `executed_at` and increments
        its `version`."

        Design: Difficulty/transitive_cascade/decision_execute_cascade_depth3
        """
        env = _setup_two_potline_approved(api, depth_pct=60)
        data = validate_success(api.execute_decision(env["decision"]["id"], smelter_manager_headers))
        assert data["status"] == "EXECUTED"
        assert _parse_ts(data["executed_at"]) == _parse_ts(DEFAULT_CLOCK)

        potline = get_success_data(api.get_potline(env["potline"]["id"], smelter_manager_headers))
        assert potline["operating_status"] == "CURTAILED"
        assert potline["curtailment_depth_pct"] == 60
        assert potline["active_decision_id"] == env["decision"]["id"]

    def test_execute_cascades_to_smelter_and_contract(self, api, smelter_manager_headers,
                                                      energy_manager_headers):
        """PRD §3.5: "Second, potline to smelter: the potline mutation forces
        `operating_posture` and `curtailed_capacity_tpd` to recompute on the
        next read. Third, smelter to contract: the posture change flips every
        `ACTIVE` power contract of the smelter whose window covers the clock
        into take-or-pay exposure, so settled billing thereafter covers at
        least `take_or_pay_pct` of contracted energy regardless of interrupted
        volume."
        PRD §3.3: "the boolean `take_or_pay_exposed` marks a contract that is
        `ACTIVE` while its smelter's `operating_posture` has left
        `FULL_OPERATION` for `PARTIAL_CURTAILMENT`, `FULL_CURTAILMENT`, or
        `SHUTDOWN`".

        Design: Difficulty/transitive_cascade/decision_execute_cascade_depth3
        """
        env = _setup_two_potline_approved(api, depth_pct=60)
        validate_success(api.execute_decision(env["decision"]["id"], smelter_manager_headers))

        smelter = get_success_data(api.get_smelter(env["smelter"]["id"], smelter_manager_headers))
        assert smelter["operating_posture"] == "PARTIAL_CURTAILMENT"  # P2 still OPERATING
        assert smelter["curtailed_capacity_tpd"] == 500

        contract = get_success_data(api.get_power_contract(env["contract"]["id"], energy_manager_headers))
        assert contract["take_or_pay_exposed"] is True


class TestExecuteReverseConservation:
    def test_execute_then_reverse_conserves_curtailed_capacity(self, api, smelter_manager_headers):
        """PRD §3.5: "the potline returns from `CURTAILED` to `OPERATING` with
        `curtailment_depth_pct` cleared to 0, `curtailed_since` and
        `active_decision_id` cleared to null, and its `version` incremented —
        unwinding the execute cascade so the smelter's curtailed capacity
        returns to its pre-execute value — while the decision moves to
        terminal `REVERSED` with its own `version` bump."

        Design: Difficulty/compensating_invariant/decision_execute_reverse_conserves_curtailed_capacity
        """
        env = _setup_two_potline_approved(api, depth_pct=50)
        sm_id = env["smelter"]["id"]
        baseline = get_success_data(api.get_smelter(sm_id, smelter_manager_headers))
        assert baseline["curtailed_capacity_tpd"] == 0

        validate_success(api.execute_decision(env["decision"]["id"], smelter_manager_headers))
        after_execute = get_success_data(api.get_smelter(sm_id, smelter_manager_headers))
        assert after_execute["curtailed_capacity_tpd"] == 500

        validate_success(api.reverse_decision(env["decision"]["id"], smelter_manager_headers))
        after_reverse = get_success_data(api.get_smelter(sm_id, smelter_manager_headers))
        assert after_reverse["curtailed_capacity_tpd"] == 0

    def test_reverse_restores_potline_and_terminates_decision(self, api, smelter_manager_headers):
        """PRD §3.5: "A `SmelterManager` may reverse an `EXECUTED` decision
        only while the potline is still `CURTAILED` and its
        `active_decision_id` still points at that decision".
        PRD §3.5: "the potline returns from `CURTAILED` to `OPERATING` with
        `curtailment_depth_pct` cleared to 0, `curtailed_since` and
        `active_decision_id` cleared to null".

        Design: Difficulty/compensating_invariant/decision_execute_reverse_conserves_curtailed_capacity
        """
        env = _setup_two_potline_approved(api, depth_pct=50)
        validate_success(api.execute_decision(env["decision"]["id"], smelter_manager_headers))
        data = validate_success(api.reverse_decision(env["decision"]["id"], smelter_manager_headers))
        assert data["status"] == "REVERSED"
        potline = get_success_data(api.get_potline(env["potline"]["id"], smelter_manager_headers))
        assert potline["operating_status"] == "OPERATING"
        assert potline["curtailment_depth_pct"] == 0
        assert potline["active_decision_id"] is None


class TestExecuteLaborGate:
    def _setup_approved_then_expire_agreement(self, api, platform_admin_headers):
        env = setup_approved_decision(notice_period_days=0, hedge_volume=20000, depth_pct=50)
        validate_success(
            api.expire_labor_agreement(env["labor_agreement"]["id"], platform_admin_headers)
        )
        return env

    def test_execute_with_expired_agreement_rejected(self, api, platform_admin_headers,
                                                     smelter_manager_headers):
        """PRD §3.5: "the agreement-presence gate requires an `ACTIVE` labor
        agreement for the smelter at all, or execution is rejected with
        `ERR_LABOR_AGREEMENT_INACTIVE` (HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/decision_execute_requires_active_labor_agreement
        """
        env = self._setup_approved_then_expire_agreement(api, platform_admin_headers)
        resp = api.execute_decision(env["decision"]["id"], smelter_manager_headers)
        validate_error(resp, ApiErrorId.ERR_LABOR_AGREEMENT_INACTIVE)

    def test_blocked_execute_leaves_decision_and_potline_unchanged(
            self, api, platform_admin_headers, smelter_manager_headers):
        """PRD §3.5: "the agreement-presence gate requires an `ACTIVE` labor
        agreement for the smelter at all, or execution is rejected with
        `ERR_LABOR_AGREEMENT_INACTIVE` (HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/decision_execute_requires_active_labor_agreement
        """
        env = self._setup_approved_then_expire_agreement(api, platform_admin_headers)
        validate_error(
            api.execute_decision(env["decision"]["id"], smelter_manager_headers),
            ApiErrorId.ERR_LABOR_AGREEMENT_INACTIVE,
        )
        decisions = get_success_data(
            api.list_curtailment_decisions(env["potline"]["id"], smelter_manager_headers)
        )
        assert decisions[0]["status"] == "APPROVED"
        potline = get_success_data(api.get_potline(env["potline"]["id"], smelter_manager_headers))
        assert potline["operating_status"] == "OPERATING"


class TestExecuteGateOrdering:
    def _setup_approved_notice14_no_hedge(self, api):
        return setup_approved_decision(notice_period_days=14, with_hedge=False, depth_pct=50)

    def test_notice_period_error_masks_hedge_error(self, api, smelter_manager_headers):
        """PRD §3.5: "the labor notice gate requires the logical clock to have
        reached `approved_at` plus the smelter labor agreement's
        `notice_period_days` — arriving exactly at the boundary is allowed,
        and arriving earlier is rejected with `ERR_LABOR_NOTICE_PERIOD`
        (HTTP 422)".
        PRD §2.7: "12. The labor notice period on decision execution —
        `ERR_LABOR_NOTICE_PERIOD`."
        PRD §2.7: "25. The hedge coverage floor at decision execution —
        `ERR_HEDGE_COVERAGE_INSUFFICIENT`."
        PRD §2.7: "a lower-numbered check masks every higher-numbered one."

        Design: Difficulty/priority_pair_validation_conflict/execute_notice_period_beats_hedge_coverage
        """
        env = self._setup_approved_notice14_no_hedge(api)
        resp = api.execute_decision(env["decision"]["id"], smelter_manager_headers)
        validate_error(resp, ApiErrorId.ERR_LABOR_NOTICE_PERIOD)

    def test_notice_blocked_execute_leaves_state_unchanged(self, api, smelter_manager_headers):
        """PRD §3.5: "the labor notice gate requires the logical clock to have
        reached `approved_at` plus the smelter labor agreement's
        `notice_period_days` — arriving exactly at the boundary is allowed,
        and arriving earlier is rejected with `ERR_LABOR_NOTICE_PERIOD`
        (HTTP 422)".

        Design: Difficulty/priority_pair_validation_conflict/execute_notice_period_beats_hedge_coverage
        """
        env = self._setup_approved_notice14_no_hedge(api)
        validate_error(
            api.execute_decision(env["decision"]["id"], smelter_manager_headers),
            ApiErrorId.ERR_LABOR_NOTICE_PERIOD,
        )
        decisions = get_success_data(
            api.list_curtailment_decisions(env["potline"]["id"], smelter_manager_headers)
        )
        assert decisions[0]["status"] == "APPROVED"
        potline = get_success_data(api.get_potline(env["potline"]["id"], smelter_manager_headers))
        assert potline["operating_status"] == "OPERATING"

    def test_execute_without_hedge_coverage_rejected(self, api, smelter_manager_headers):
        """PRD §3.5: "the hedge gate requires the smelter's
        `hedge_coverage_ratio` to be at least 0.5, compared unrounded, or
        execution is rejected with `ERR_HEDGE_COVERAGE_INSUFFICIENT`
        (HTTP 422)."

        Design: Corner/validations/execute_without_hedge_coverage_rejected
        """
        env = setup_approved_decision(notice_period_days=0, with_hedge=False, depth_pct=50)
        resp = api.execute_decision(env["decision"]["id"], smelter_manager_headers)
        validate_error(resp, ApiErrorId.ERR_HEDGE_COVERAGE_INSUFFICIENT)
        decisions = get_success_data(
            api.list_curtailment_decisions(env["potline"]["id"], smelter_manager_headers)
        )
        assert decisions[0]["status"] == "APPROVED"
        potline = get_success_data(api.get_potline(env["potline"]["id"], smelter_manager_headers))
        assert potline["operating_status"] == "OPERATING"


class TestImmediateConsistency:
    def test_execute_response_and_next_read_agree(self, api, smelter_manager_headers):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."
        PRD §3.5: "The decision itself records `executed_at` and increments
        its `version`."
        PRD §2.4: "At startup the logical clock reads exactly
        `2026-09-01T00:00:00Z`".

        Design: Corner/consistency_model/immediate_consistency_execute_response_and_read
        """
        env = setup_approved_decision(notice_period_days=0, hedge_volume=20000, depth_pct=50)
        data = validate_success(api.execute_decision(env["decision"]["id"], smelter_manager_headers))
        assert data["status"] == "EXECUTED"
        assert _parse_ts(data["executed_at"]) == _parse_ts(DEFAULT_CLOCK)
        potline = get_success_data(api.get_potline(env["potline"]["id"], smelter_manager_headers))
        assert potline["operating_status"] == "CURTAILED"
