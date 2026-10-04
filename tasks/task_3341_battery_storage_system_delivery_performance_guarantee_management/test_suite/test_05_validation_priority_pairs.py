"""Priority-pair validation conflicts: the PRD's fixed validation order
decides which error surfaces when one request violates two rules."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_all_permits,
    create_esa,
    create_project,
    get_success_data,
    submit_permit,
    validate_error,
    validate_success,
)

DEV = TEST_USERS["project_developer_headers"]
SAFETY = TEST_USERS["safety_authority_headers"]


class TestSizingConstraintBeatsBudgetFiscal:
    def _setup_double_violation(self, api):
        """CAPACITY_FIRMING with duration 3.00 (INVALID sizing) AND a contract
        whose total price exceeds the budget; all permits approved."""
        project = create_project(
            api=api,
            market_application="CAPACITY_FIRMING",
            duty_cycle_profile="ONE_CYCLE_DAILY",
            rated_power_mw=11,
            rated_energy_mwh=33,
            budget_cents=5_000_000,
        )
        esa = create_esa(
            project["id"],
            api=api,
            contracted_energy_mwh=40,
            guaranteed_capacity_mwh=30,
            price_per_mwh_cents=300000,
        )
        approve_all_permits(project["id"], api=api)
        return project, esa

    def test_sizing_invalid_wins_over_budget_exceeded(self, api):
        """PRD §2.8: "When a request could fail more than one check, checks are
        evaluated in this fixed order, and the first failure wins:"
        PRD §2.8: "8. Structural integrity: window overlap, window ordering,
        sizing validity, guarantee-versus-rated-energy, and commissioning
        prerequisites (`ERR_TEST_WINDOW_OVERLAP`, `ERR_BID_WINDOW_OVERLAP`,
        `ERR_INVALID_WINDOW`, `ERR_SIZING_INVALID`,
        `ERR_GUARANTEE_EXCEEDS_RATED_ENERGY`, `ERR_PROJECT_NOT_COMMISSIONED`)."
        PRD §2.8: "10. Fiscal checks, which are always last: owner budget,
        spare-parts credit headroom, and waiver headroom (`ERR_BUDGET_EXCEEDED`,
        `ERR_CREDIT_POOL_EXHAUSTED`, `ERR_WAIVER_EXCEEDS_ACCRUED`, all HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/sizing_constraint_beats_budget_fiscal
        """
        project, esa = self._setup_double_violation(api)
        current = get_success_data(api.get_project(project["id"], DEV))
        assert current["sizing_status"] == "INVALID", (
            "duration 3.00 < 4.00 for CAPACITY_FIRMING -> INVALID"
        )
        assert current["duration_hours"] == 3.0

        resp = api.execute_esa(
            esa["id"], {"expected_project_version": current["version"]}, DEV
        )
        validate_error(resp, ApiErrorId.ERR_SIZING_INVALID)
        esa_after = get_success_data(api.get_esa(esa["id"], DEV))
        assert esa_after["status"] == "DRAFT", "no partial execution"

    def test_sizing_fix_then_budget_surfaces_last(self, api):
        """PRD §2.8: "10. Fiscal checks, which are always last: owner budget,
        spare-parts credit headroom, and waiver headroom (`ERR_BUDGET_EXCEEDED`,
        `ERR_CREDIT_POOL_EXHAUSTED`, `ERR_WAIVER_EXCEEDS_ACCRUED`, all HTTP 402)."
        PRD §3.2: "the project's `sizing_status` must be `VALID` (otherwise
        `ERR_SIZING_INVALID`); `guaranteed_capacity_mwh` must not exceed the
        project's `rated_energy_mwh` (otherwise
        `ERR_GUARANTEE_EXCEEDS_RATED_ENERGY`); and finally `total_price_cents`
        must not exceed the project's `budget_cents` (otherwise
        `ERR_BUDGET_EXCEEDED`)."

        Design: Difficulty/priority_pair_validation_conflict/sizing_constraint_beats_budget_fiscal
        """
        # Same fiscal violation but VALID sizing -> the fiscal check fires.
        project = create_project(
            api=api,
            market_application="CAPACITY_FIRMING",
            duty_cycle_profile="ONE_CYCLE_DAILY",
            rated_power_mw=10,
            rated_energy_mwh=40,
            budget_cents=5_000_000,
        )
        esa = create_esa(
            project["id"],
            api=api,
            contracted_energy_mwh=40,
            guaranteed_capacity_mwh=30,
            price_per_mwh_cents=300000,
        )
        approve_all_permits(project["id"], api=api)
        current = get_success_data(api.get_project(project["id"], DEV))
        assert current["sizing_status"] == "VALID"

        resp = api.execute_esa(
            esa["id"], {"expected_project_version": current["version"]}, DEV
        )
        # total_price 12000000 > budget 5000000, and all earlier checks pass
        validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED)
        esa_after = get_success_data(api.get_esa(esa["id"], DEV))
        assert esa_after["status"] == "DRAFT"


class TestRoleAuthzBeatsPermitState:
    def _setup_approved_permit(self, api):
        project = create_project(api=api)
        permit = submit_permit(project["id"], "THERMAL_RUNAWAY_PLAN", api=api)
        decided = validate_success(
            api.decide_permit(permit["id"], {"decision": "APPROVED"}, SAFETY)
        )
        return project, decided

    def test_forbidden_role_on_decided_permit_gets_403_not_409(self, api):
        """PRD §2.8: "When a request could fail more than one check, checks are
        evaluated in this fixed order, and the first failure wins:"
        PRD §2.8: "2. Role permission for the endpoint
        (`ERR_INSUFFICIENT_PERMISSIONS`)."
        PRD §2.8: "5. State-machine legality: the target resource must be in a
        state from which the requested transition exists (the `ERR_*_NOT_*`
        family, HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/role_authz_beats_permit_state
        """
        _, permit = self._setup_approved_permit(api)
        # ProjectDeveloper is not permitted on decide; the permit is also in a
        # state where decide is invalid. The 403 must win.
        resp = api.decide_permit(permit["id"], {"decision": "REJECTED"}, DEV)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        current = get_success_data(api.get_permit(permit["id"], DEV))
        assert current["status"] == "APPROVED"

    def test_authorized_role_on_decided_permit_gets_409(self, api):
        """PRD §3.2: "a decide on a permit that is not `SUBMITTED` is refused
        with `ERR_PERMIT_NOT_PENDING`."
        PRD §2.8: "2. Role permission for the endpoint
        (`ERR_INSUFFICIENT_PERMISSIONS`)."

        Design: Difficulty/priority_pair_validation_conflict/role_authz_beats_permit_state
        """
        _, permit = self._setup_approved_permit(api)
        # SafetyAuthority is the authorized role; only the state check fails.
        resp = api.decide_permit(permit["id"], {"decision": "REJECTED"}, SAFETY)
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_PENDING)
        current = get_success_data(api.get_permit(permit["id"], DEV))
        assert current["status"] == "APPROVED"
