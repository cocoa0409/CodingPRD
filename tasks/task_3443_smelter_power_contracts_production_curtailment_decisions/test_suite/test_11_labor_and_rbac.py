"""Labor-agreement lifecycle and role-based access denials
(PRD §3.8, §2.1, §4).
"""
import pytest
from test_helpers import (
    ApiErrorId,
    approve_decision,
    create_active_contract,
    create_hedge,
    create_labor_agreement,
    create_labor_agreement_payload,
    create_power_contract_payload,
    create_smelter,
    get_success_data,
    make_controller_headers,
    post_standard_price_set,
    propose_decision,
    setup_site,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestLaborAgreementLifecycle:
    def test_second_active_agreement_rejected(self, api, platform_admin_headers):
        """PRD §3.8: "At most one agreement may be `ACTIVE` per smelter; a
        second live registration is rejected with `ERR_LABOR_AGREEMENT_EXISTS`
        (HTTP 409)."

        Design: Corner/validations/labor_agreement_second_active_rejected
        """
        smelter = create_smelter()
        create_labor_agreement(smelter["id"])
        resp = api.create_labor_agreement(
            create_labor_agreement_payload(smelter["id"], union_name="IBEW-88",
                                           notice_period_days=7,
                                           severance_weeks_per_year=2.0),
            platform_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_LABOR_AGREEMENT_EXISTS)

    def test_expire_twice_rejected(self, api, platform_admin_headers):
        """PRD §3.8: "A `PlatformAdmin` may expire an `ACTIVE` agreement,
        moving its `status` to terminal `EXPIRED`; expiring one that is not
        `ACTIVE` is rejected with `ERR_INVALID_LIFECYCLE_STATE`."

        Design: Corner/state_machines/labor_expire_twice_rejected
        """
        smelter = create_smelter()
        agreement = create_labor_agreement(smelter["id"])
        expired = validate_success(
            api.expire_labor_agreement(agreement["id"], platform_admin_headers)
        )
        assert expired["status"] == "EXPIRED"
        resp = api.expire_labor_agreement(agreement["id"], platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_LIFECYCLE_STATE)
        agreements, _ = validate_paginated(
            api.list_labor_agreements(smelter["id"], platform_admin_headers)
        )
        assert agreements[0]["status"] == "EXPIRED"


class TestRoleDenials:
    def test_energy_manager_cannot_close_hedge(self, api, energy_manager_headers,
                                               trading_analyst_headers):
        """PRD §2.1: "A request whose role is authenticated but not listed
        among the roles authorized for the target endpoint is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "| POST | `/smelter-ops/hedge-positions/{id}/close` | Close an
        `OPEN` hedge at a price; computes realized P&L | TradingAnalyst |"

        Design: Corner/rbac/energy_manager_cannot_close_hedge_returns_403
        """
        smelter = create_smelter()
        hedge = create_hedge(smelter["id"], volume_tonnes=5000, delivery_month="2026-10")
        resp = api.close_hedge_position(hedge["id"], {"closed_price_usd": 2500.00},
                                        energy_manager_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        hedges, _ = validate_paginated(
            api.list_hedge_positions(smelter["id"], trading_analyst_headers)
        )
        assert hedges[0]["status"] == "OPEN"

    def test_controller_cannot_labor_approve(self, api):
        """PRD §2.1: "A request whose role is authenticated but not listed
        among the roles authorized for the target endpoint is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "| POST | `/smelter-ops/curtailment-decisions/{id}/labor-approve`
        | VPOperations labor and community approval: `LABOR_REVIEW` to
        `APPROVED`; approver must differ from proposer and economic reviewer |
        VPOperations |"

        Design: Corner/rbac/controller_cannot_labor_approve_returns_403
        """
        env = setup_site()
        post_standard_price_set()
        decision = propose_decision(env["potline"]["id"], proposer_id="mgr-1")
        decision = get_success_data(
            api.economic_approve_decision(decision["id"], make_controller_headers("ctrl-1"))
        )
        assert decision["status"] == "LABOR_REVIEW"
        resp = api.labor_approve_decision(decision["id"], make_controller_headers("ctrl-2"))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        decisions = get_success_data(
            api.list_curtailment_decisions(env["potline"]["id"], make_controller_headers("ctrl-9"))
        )
        assert decisions[0]["status"] == "LABOR_REVIEW"

    def test_smelter_manager_cannot_activate_contract(self, api, smelter_manager_headers,
                                                      energy_manager_headers):
        """PRD §2.1: "A request whose role is authenticated but not listed
        among the roles authorized for the target endpoint is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "| POST | `/smelter-ops/power-contracts/{id}/activate` |
        Activate a `DRAFT` contract; rejects on half-open window overlap |
        EnergyManager |"

        Design: Corner/rbac/smelter_manager_cannot_activate_contract_returns_403
        """
        smelter = create_smelter()
        contract = create_active_contract(smelter["id"], activate=False)
        resp = api.activate_power_contract(contract["id"], smelter_manager_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        data = get_success_data(api.get_power_contract(contract["id"], energy_manager_headers))
        assert data["status"] == "DRAFT"

    def test_platform_admin_cannot_curtail_potline(self, api, platform_admin_headers,
                                                   smelter_manager_headers):
        """PRD §2.1: "A request whose role is authenticated but not listed
        among the roles authorized for the target endpoint is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "| POST | `/smelter-ops/potlines/{id}/curtail` | Emergency
        curtail, deepen, or restore by `depth_pct` | SmelterManager |"

        Design: Corner/rbac/platform_admin_cannot_curtail_potline_returns_403
        """
        env = setup_site()
        resp = api.curtail_potline(env["potline"]["id"], {"depth_pct": 40},
                                   platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        potline = get_success_data(api.get_potline(env["potline"]["id"], smelter_manager_headers))
        assert potline["operating_status"] == "OPERATING"
        assert potline["curtailment_depth_pct"] == 0
