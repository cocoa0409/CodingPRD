"""Non-linear state machine tests: cyclic transitions (permit reject/resubmit
loop; LTSA suspend/reactivate loop)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_all_permits,
    create_project,
    get_success_data,
    setup_active_ltsa,
    submit_permit,
    validate_error,
    validate_success,
)

DEV = TEST_USERS["project_developer_headers"]
SVC_MGR = TEST_USERS["service_manager_headers"]
SAFETY = TEST_USERS["safety_authority_headers"]


class TestSafetyPermitRejectResubmitCycle:
    def test_permit_cycles_reject_resubmit_then_approves(self, api):
        """PRD §3.2: "A rejected permit is not dead — the developer may
        resubmit it, cycling `REJECTED` back to `SUBMITTED` with `decided_at`
        cleared to null, and there is no bound on the number of resubmission
        cycles"

        Design: Difficulty/non_linear_state_machine/safety_permit_reject_resubmit_cycle
        """
        project = create_project(api=api)
        permit = submit_permit(project["id"], "THERMAL_RUNAWAY_PLAN", api=api)
        assert permit["status"] == "SUBMITTED"

        for _ in range(2):
            rejected = validate_success(
                api.decide_permit(permit["id"], {"decision": "REJECTED"}, SAFETY)
            )
            assert rejected["status"] == "REJECTED"
            assert rejected["decided_at"] is not None
            resubmitted = validate_success(api.resubmit_permit(permit["id"], DEV))
            assert resubmitted["status"] == "SUBMITTED"
            assert resubmitted["decided_at"] is None, (
                "resubmit clears decided_at to null"
            )

        approved = validate_success(
            api.decide_permit(permit["id"], {"decision": "APPROVED"}, SAFETY)
        )
        assert approved["status"] == "APPROVED"
        assert approved["decided_at"] is not None

    def test_decide_on_approved_permit_is_terminal_locked(self, api):
        """PRD §3.2: "a decide on a permit that is not `SUBMITTED` is refused
        with `ERR_PERMIT_NOT_PENDING`."

        Design: Difficulty/non_linear_state_machine/safety_permit_reject_resubmit_cycle
        """
        project = create_project(api=api)
        permit = submit_permit(project["id"], "FIRE_CODE", api=api)
        decided = validate_success(
            api.decide_permit(permit["id"], {"decision": "APPROVED"}, SAFETY)
        )
        assert decided["status"] == "APPROVED"

        resp = api.decide_permit(permit["id"], {"decision": "REJECTED"}, SAFETY)
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_PENDING)
        current = get_success_data(api.get_permit(permit["id"], DEV))
        assert current["status"] == "APPROVED"

    def test_resubmit_of_non_rejected_permit_rejected(self, api):
        """PRD §3.2: "resubmitting a permit that is not `REJECTED` is refused
        with `ERR_PERMIT_NOT_REJECTED`."

        Design: Difficulty/non_linear_state_machine/safety_permit_reject_resubmit_cycle
        """
        project = create_project(api=api)
        permit = submit_permit(project["id"], "LOCAL_APPROVAL", api=api)
        resp = api.resubmit_permit(permit["id"], DEV)
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_REJECTED)


class TestLtsaSuspendReactivateCycle:
    def test_suspend_reactivate_cycle_keeps_pool_and_first_activation_stamp(self, api):
        """PRD §3.6: "First activation stamps `activated_at` with the logical
        clock and computes the spare-parts credit pool exactly once:
        `credit_pool_cents` is 30 percent of `annual_fee_cents`, rounded down
        to a whole cent."
        PRD §3.6: "Reactivation never recomputes the pool."

        Design: Difficulty/non_linear_state_machine/ltsa_suspend_reactivate_cycle
        """
        project = create_project(api=api)
        ltsa = setup_active_ltsa(project["id"], api=api, annual_fee_cents=2_000_000)
        assert ltsa["status"] == "ACTIVE"
        assert ltsa["credit_pool_cents"] == 600000, (
            f"floor(2000000 * 0.30) == 600000, got {ltsa['credit_pool_cents']}"
        )
        first_activation = ltsa["activated_at"]
        assert first_activation is not None

        for _ in range(2):
            suspended = validate_success(api.suspend_service_agreement(ltsa["id"], SVC_MGR))
            assert suspended["status"] == "SUSPENDED"
            reactivated = validate_success(
                api.reactivate_service_agreement(ltsa["id"], SVC_MGR)
            )
            assert reactivated["status"] == "ACTIVE"
            assert reactivated["credit_pool_cents"] == 600000, (
                "pool computed once at first activation, never recomputed"
            )
            assert reactivated["activated_at"] == first_activation

    def test_suspend_and_reactivate_state_errors(self, api):
        """PRD §3.6: "An active agreement may be suspended (`ACTIVE` to
        `SUSPENDED`; any other source state is `ERR_LTSA_NOT_ACTIVE`) and later
        reactivated (`SUSPENDED` to `ACTIVE`; any other source state is
        `ERR_LTSA_NOT_SUSPENDED`)"

        Design: Difficulty/non_linear_state_machine/ltsa_suspend_reactivate_cycle
        """
        project = create_project(api=api)
        ltsa = setup_active_ltsa(project["id"], api=api)

        # reactivate on ACTIVE (not SUSPENDED) -> ERR_LTSA_NOT_SUSPENDED
        resp = api.reactivate_service_agreement(ltsa["id"], SVC_MGR)
        validate_error(resp, ApiErrorId.ERR_LTSA_NOT_SUSPENDED)

        validate_success(api.suspend_service_agreement(ltsa["id"], SVC_MGR))
        # suspend on SUSPENDED (not ACTIVE) -> ERR_LTSA_NOT_ACTIVE
        resp = api.suspend_service_agreement(ltsa["id"], SVC_MGR)
        validate_error(resp, ApiErrorId.ERR_LTSA_NOT_ACTIVE)

        reactivated = validate_success(api.reactivate_service_agreement(ltsa["id"], SVC_MGR))
        assert reactivated["status"] == "ACTIVE"
