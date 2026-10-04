"""Curtailment decision pipeline: economics snapshot, reject/revise cycle,
invalid actions, and decision-linked restore blocking (PRD §3.5, §3.1).
"""
import pytest
from test_helpers import (
    ApiErrorId,
    BLENDED_COMPONENTS,
    assert_curtailment_decision,
    create_alumina_agreement,
    create_curtailment_decision_payload,
    get_success_data,
    make_controller_headers,
    make_smelter_manager_headers,
    make_vp_operations_headers,
    post_price_observation,
    propose_decision,
    setup_executed_decision,
    setup_site,
    validate_error,
    validate_paginated,
    validate_success,
)


def _setup_margin_gate_site(lme, premium, spot):
    """Blended contract + OPERATING potline + COST_PLUS agreement at 345.00 +
    the given market prints."""
    env = setup_site(components=BLENDED_COMPONENTS)
    create_alumina_agreement(env["smelter"]["id"])  # 300.00 * 1.15 = 345.00
    post_price_observation("ALUMINUM_LME", "GLOBAL", "2026-08-15T00:00:00Z", lme)
    post_price_observation("REGIONAL_PREMIUM", "NA_NORTHWEST", "2026-08-15T00:00:00Z", premium)
    post_price_observation("POWER_SPOT", "NA_NORTHWEST", "2026-08-20T00:00:00Z", spot)
    return env


class TestMarginGateSnapshot:
    def test_snapshot_freezes_market_inputs(self, api, smelter_manager_headers):
        """PRD §3.5: "The snapshot's `lme_price_usd` is the latest `GLOBAL`
        `ALUMINUM_LME` observation at or before the clock, and
        `regional_premium_usd` is the latest `REGIONAL_PREMIUM` observation
        for the potline's smelter region. The `transfer_price_per_tonne` is
        the `current_transfer_price` of the smelter's most recently created
        alumina supply agreement, falling back to the latest `GLOBAL`
        `ALUMINA_INDEX` observation when no agreement exists. The
        `power_cost_per_mwh` is the FORWARD effective power cost of the
        smelter's `ACTIVE` power contract whose half-open window covers the
        clock."

        Design: Difficulty/combinatorial_formula/curtailment_margin_gate_multifactor
        """
        env = _setup_margin_gate_site(lme=1750.00, premium=280.00, spot=96.00)
        resp = api.create_curtailment_decision(
            create_curtailment_decision_payload(
                env["potline"]["id"], env["potline"]["version"], trigger_type="POWER_PRICE",
                planned_start="2026-09-10T00:00:00Z", planned_end="2026-10-10T00:00:00Z",
            ),
            smelter_manager_headers,
        )
        data = validate_success(resp, 201)
        assert_curtailment_decision(data)
        snap = data["economics_snapshot"]
        assert snap["lme_price_usd"] == pytest.approx(1750.00, abs=0.01)
        assert snap["regional_premium_usd"] == pytest.approx(280.00, abs=0.01)
        assert snap["transfer_price_per_tonne"] == pytest.approx(345.00, abs=0.01)
        # (150*32 + 100*96 + 50*96*0.75) / 300
        assert snap["power_cost_per_mwh"] == pytest.approx(60.00, abs=0.01)

    def test_snapshot_margin_flag_and_avoidable_loss(self, api, smelter_manager_headers):
        """PRD §3.5: "`curtailment_economic` is true exactly when
        `margin_per_tonne` falls below the 150 USD per-tonne restart reserve;
        `avoidable_loss_per_tonne` is that shortfall — the reserve minus the
        margin — floored at zero".
        PRD §3.5: "`margin_per_tonne` is the LME price plus the regional
        premium, minus 1.92 tonnes of alumina per tonne of metal times the
        transfer price, minus 13.5 MWh per tonne times the power cost, minus a
        further 420 USD per tonne of other conversion cost."

        Design: Difficulty/combinatorial_formula/curtailment_margin_gate_multifactor
        """
        env = _setup_margin_gate_site(lme=1750.00, premium=280.00, spot=96.00)
        resp = api.create_curtailment_decision(
            create_curtailment_decision_payload(
                env["potline"]["id"], env["potline"]["version"], trigger_type="POWER_PRICE",
                planned_start="2026-09-10T00:00:00Z", planned_end="2026-10-10T00:00:00Z",
            ),
            smelter_manager_headers,
        )
        snap = validate_success(resp, 201)["economics_snapshot"]
        # 1750 + 280 - 1.92*345 - 13.5*60 - 420
        assert snap["margin_per_tonne"] == pytest.approx(137.60, abs=0.01)
        assert snap["curtailment_economic"] is True
        assert snap["avoidable_loss_per_tonne"] == pytest.approx(12.40, abs=0.01)


class TestRejectReviseCycle:
    def _setup_labor_review_decision(self, api):
        env = _setup_margin_gate_site(lme=2400.00, premium=380.00, spot=48.00)
        decision = propose_decision(env["potline"]["id"], depth_pct=50, proposer_id="mgr-1")
        decision = get_success_data(
            api.economic_approve_decision(decision["id"], make_controller_headers("ctrl-1"))
        )
        env["decision"] = decision
        return env

    def test_reject_from_labor_review(self, api):
        """PRD §3.5: "Rejection is available to either a `Controller` or a
        `VPOperations` from either review state — `ECONOMIC_REVIEW → REJECTED`
        and `LABOR_REVIEW → REJECTED` — and may carry an optional `reason`."

        Design: Difficulty/non_linear_state_machine/decision_reject_revise_cycle
        """
        env = self._setup_labor_review_decision(api)
        assert env["decision"]["status"] == "LABOR_REVIEW"
        data = validate_success(
            api.reject_decision(env["decision"]["id"], {}, make_vp_operations_headers("vp-1"))
        )
        assert data["status"] == "REJECTED"

    def test_revise_recomputes_snapshot_and_clears_reviewer(self, api):
        """PRD §3.5: "a `SmelterManager` may revise a `REJECTED` decision back
        into `ECONOMIC_REVIEW`, supplying a fresh `depth_pct` (strictly
        greater than 0, at most 100), `planned_start`, and `planned_end`; the
        `economics_snapshot` is recomputed at revise time and
        `economic_reviewed_by_user_id` is cleared, forcing the decision
        through a fresh economic review."

        Design: Difficulty/non_linear_state_machine/decision_reject_revise_cycle
        """
        env = self._setup_labor_review_decision(api)
        validate_success(
            api.reject_decision(env["decision"]["id"], {}, make_vp_operations_headers("vp-1"))
        )
        data = validate_success(
            api.revise_decision(
                env["decision"]["id"],
                {"depth_pct": 60, "planned_start": "2026-09-12T00:00:00Z",
                 "planned_end": "2026-10-12T00:00:00Z"},
                make_smelter_manager_headers("mgr-1"),
            )
        )
        assert data["status"] == "ECONOMIC_REVIEW"
        assert data["economic_reviewed_by_user_id"] is None
        assert data["depth_pct"] == 60
        # 2400 + 380 - 1.92*345 - 13.5*38 - 420 (forward power 38.00 at spot 48)
        assert data["economics_snapshot"]["margin_per_tonne"] == pytest.approx(1184.60, abs=0.01)


class TestInvalidDecisionActions:
    def test_execute_from_economic_review_rejected(self, api, smelter_manager_headers):
        """PRD §3.5: "Any decision action invoked from a status for which that
        transition is not declared — approving an already-`APPROVED` decision,
        acting on terminal `REVERSED` or `SUPERSEDED` decisions, or reversing
        after the potline has left `CURTAILED` — is rejected with
        `ERR_DECISION_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/decision_execute_from_economic_review_rejected
        """
        env = setup_site()
        post_price_observation("ALUMINUM_LME", "GLOBAL", "2026-08-15T00:00:00Z", 2400.00)
        post_price_observation("REGIONAL_PREMIUM", "NA_NORTHWEST", "2026-08-15T00:00:00Z", 380.00)
        post_price_observation("ALUMINA_INDEX", "GLOBAL", "2026-08-15T00:00:00Z", 340.00)
        decision = propose_decision(env["potline"]["id"], depth_pct=50)
        resp = api.execute_decision(decision["id"], smelter_manager_headers)
        validate_error(resp, ApiErrorId.ERR_DECISION_INVALID_STATE)
        decisions, _ = validate_paginated(
            api.list_curtailment_decisions(env["potline"]["id"], smelter_manager_headers)
        )
        assert decisions[0]["status"] == "ECONOMIC_REVIEW"
        potline = get_success_data(api.get_potline(env["potline"]["id"], smelter_manager_headers))
        assert potline["operating_status"] == "OPERATING"

    def test_restore_blocked_while_decision_linked(self, api, smelter_manager_headers):
        """PRD §3.1: "a `depth_pct` outside the inclusive range from 0 to 100,
        a positive deepen that does not strictly exceed the current depth, or
        a zero-depth restore while `active_decision_id` is set are all
        rejected with `ERR_CURTAILMENT_DEPTH_INVALID` (HTTP 422)."
        PRD §3.1: "a decision-linked curtailment must be unwound through the
        decision's own reversal, not through a direct restore."

        Design: Corner/validations/curtail_restore_blocked_when_decision_linked
        """
        env = setup_executed_decision(depth_pct=50)
        assert env["potline"]["operating_status"] == "CURTAILED"
        resp = api.curtail_potline(env["potline"]["id"], {"depth_pct": 0}, smelter_manager_headers)
        validate_error(resp, ApiErrorId.ERR_CURTAILMENT_DEPTH_INVALID)
        potline = get_success_data(api.get_potline(env["potline"]["id"], smelter_manager_headers))
        assert potline["operating_status"] == "CURTAILED"
        assert potline["curtailment_depth_pct"] == 50
        assert potline["active_decision_id"] == env["decision"]["id"]

    def test_create_without_price_observations_rejected(self, api, smelter_manager_headers):
        """PRD §3.5: "Missing LME, premium, or transfer inputs are rejected
        with `ERR_NO_PRICE_OBSERVATION` (HTTP 422)".

        Design: Corner/validations/decision_create_without_price_observations_rejected
        """
        env = setup_site()  # contract + potline, but no price observations
        resp = api.create_curtailment_decision(
            create_curtailment_decision_payload(
                env["potline"]["id"], env["potline"]["version"]
            ),
            smelter_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NO_PRICE_OBSERVATION)
        decisions, _ = validate_paginated(
            api.list_curtailment_decisions(env["potline"]["id"], smelter_manager_headers)
        )
        assert decisions == []
