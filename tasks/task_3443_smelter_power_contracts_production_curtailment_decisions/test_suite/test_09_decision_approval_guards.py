"""Segregation of duties, optimistic concurrency on decision creation, and
terminal-state lockdown on decisions (PRD §3.5, §2.8).
"""
import pytest
from test_helpers import (
    ApiErrorId,
    create_curtailment_decision_payload,
    get_success_data,
    make_controller_headers,
    make_smelter_manager_headers,
    make_vp_operations_headers,
    post_standard_price_set,
    propose_decision,
    setup_executed_and_reversed,
    setup_site,
    validate_error,
    validate_paginated,
    validate_success,
)


def _setup_site_with_prices():
    env = setup_site()
    post_standard_price_set()
    return env


class TestSegregationOfDuties:
    def test_economic_approve_by_proposer_rejected(self, api):
        """PRD §3.5: "Segregation of duties forbids the reviewer from being
        the proposer: an `X-User-ID` equal to `proposed_by_user_id` is
        rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/validations/sod_economic_approve_by_proposer_rejected
        """
        env = _setup_site_with_prices()
        decision = propose_decision(env["potline"]["id"], proposer_id="mgr-1")
        resp = api.economic_approve_decision(decision["id"], make_controller_headers("mgr-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        decisions, _ = validate_paginated(
            api.list_curtailment_decisions(env["potline"]["id"], make_smelter_manager_headers("mgr-9"))
        )
        assert decisions[0]["status"] == "ECONOMIC_REVIEW"
        assert decisions[0]["economic_reviewed_by_user_id"] is None

    def test_labor_approve_by_economic_reviewer_rejected(self, api):
        """PRD §3.5: "The segregation net widens here: the labor approver must
        differ from both the proposer and the economic reviewer, or the same
        `ERR_SEGREGATION_OF_DUTIES` fires."

        Design: Corner/validations/sod_labor_approve_by_economic_reviewer_rejected
        """
        env = _setup_site_with_prices()
        decision = propose_decision(env["potline"]["id"], proposer_id="mgr-1")
        validate_success(
            api.economic_approve_decision(decision["id"], make_controller_headers("ctrl-1"))
        )
        resp = api.labor_approve_decision(decision["id"], make_vp_operations_headers("ctrl-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        decisions, _ = validate_paginated(
            api.list_curtailment_decisions(env["potline"]["id"], make_smelter_manager_headers("mgr-9"))
        )
        assert decisions[0]["status"] == "LABOR_REVIEW"
        assert decisions[0]["approved_by_user_id"] is None
        assert decisions[0]["approved_at"] is None


class TestDecisionOptimisticConcurrency:
    def test_stale_potline_version_rejected(self, api):
        """PRD §2.8: "Creating a curtailment decision requires the request to
        carry `expected_potline_version` holding the client's last observed
        `version` of the target potline; if the potline's current `version`
        has advanced beyond that value, the creation is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.8: "decision creation itself increments the potline's `version`
        by 1".

        Design: Corner/cross_cutting_layers/occ_decision_create_stale_potline_version_rejected
        """
        env = _setup_site_with_prices()
        pl = env["potline"]["id"]
        captured_version = env["potline"]["version"]
        first = propose_decision(pl, proposer_id="mgr-1")
        assert first["status"] == "ECONOMIC_REVIEW"

        resp = api.create_curtailment_decision(
            create_curtailment_decision_payload(
                pl, captured_version, trigger_type="POWER_PRICE", depth_pct=30,
                planned_start="2026-09-06T00:00:00Z", planned_end="2026-10-06T00:00:00Z",
            ),
            make_smelter_manager_headers("mgr-2"),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        potline = get_success_data(api.get_potline(pl, make_smelter_manager_headers("mgr-9")))
        assert potline["version"] == 2
        decisions, _ = validate_paginated(
            api.list_curtailment_decisions(pl, make_smelter_manager_headers("mgr-9"))
        )
        statuses = {d["id"]: d["status"] for d in decisions}
        assert statuses[first["id"]] == "ECONOMIC_REVIEW"
        assert len(decisions) == 1

    def test_fresh_version_create_supersedes_prior_review(self, api):
        """PRD §3.5: "Creation also increments the potline's `version` by 1,
        records the creator in `proposed_by_user_id`, and flips any prior
        decision still sitting in `ECONOMIC_REVIEW` for the same potline to
        `SUPERSEDED` (bumping that prior decision's `version`)."

        Design: Corner/cross_cutting_layers/occ_decision_create_supersedes_prior_review
        """
        env = _setup_site_with_prices()
        pl = env["potline"]["id"]
        first = propose_decision(pl, proposer_id="mgr-1")
        fresh = get_success_data(api.get_potline(pl, make_smelter_manager_headers("mgr-2")))
        resp = api.create_curtailment_decision(
            create_curtailment_decision_payload(
                pl, fresh["version"], trigger_type="POWER_PRICE", depth_pct=30,
                planned_start="2026-09-06T00:00:00Z", planned_end="2026-10-06T00:00:00Z",
            ),
            make_smelter_manager_headers("mgr-2"),
        )
        second = validate_success(resp, 201)
        assert second["status"] == "ECONOMIC_REVIEW"

        decisions, _ = validate_paginated(
            api.list_curtailment_decisions(pl, make_smelter_manager_headers("mgr-9"))
        )
        statuses = {d["id"]: d["status"] for d in decisions}
        assert statuses[first["id"]] == "SUPERSEDED"
        potline = get_success_data(api.get_potline(pl, make_smelter_manager_headers("mgr-9")))
        assert potline["version"] == 3


class TestTerminalDecisionLockdown:
    def test_reverse_after_reversed_rejected(self, api):
        """PRD §3.5: "Any decision action invoked from a status for which that
        transition is not declared — approving an already-`APPROVED` decision,
        acting on terminal `REVERSED` or `SUPERSEDED` decisions, or reversing
        after the potline has left `CURTAILED` — is rejected with
        `ERR_DECISION_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/decision_reverse_after_reversed_rejected
        """
        env = setup_executed_and_reversed(depth_pct=50)
        assert env["decision"]["status"] == "REVERSED"
        resp = api.reverse_decision(env["decision"]["id"], make_smelter_manager_headers("mgr-1"))
        validate_error(resp, ApiErrorId.ERR_DECISION_INVALID_STATE)
        potline = get_success_data(
            api.get_potline(env["potline"]["id"], make_smelter_manager_headers("mgr-1"))
        )
        assert potline["operating_status"] == "OPERATING"
        smelter = get_success_data(
            api.get_smelter(env["smelter"]["id"], make_smelter_manager_headers("mgr-1"))
        )
        assert smelter["curtailed_capacity_tpd"] == 0
