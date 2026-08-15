"""Broker onboarding gates, suspension branching, reinstatement, termination cascades."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_broker,
    create_broker,
    dispatch_to_broker,
    drive_order_to_completed,
    drive_order_to_in_progress,
    get_broker,
    get_order,
    list_broker_licenses,
    new_order,
    setup_market,
    submit_order,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

COMPLIANCE = TEST_USERS["compliance_officer_headers"]


class TestBrokerActivation:
    def test_broker_activation_without_license_rejected(
            self, api, compliance_officer_headers):
        """PRD §3.3: "moving a broker from `PENDING_ONBOARDING` to `ACTIVE` requires
        that the broker hold at least one `BrokerLicense` row whose `status` is
        `ACTIVE` and whose `expires_on` is strictly in the future; otherwise the
        activation is rejected with `ERR_NO_ACTIVE_LICENSE`."

        Design: Corner/validations/broker_activation_without_license_rejected
        """
        broker = create_broker(broker_code="BNL")
        resp = api.activate_broker(broker["id"], compliance_officer_headers)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_LICENSE)

        fresh = get_broker(broker["id"])
        assert_broker(fresh)
        assert fresh["status"] == "PENDING_ONBOARDING"


class TestBrokerSuspensionBranching:
    def test_suspend_reverts_only_dispatched_orders(
            self, api, compliance_officer_headers):
        """PRD §3.3: "suspension moves the broker to `SUSPENDED`, reverts every
        order assigned to that broker that is still in `DISPATCHED` back to
        `READY_FOR_DISPATCH` with its `assigned_broker_id` cleared, and leaves
        orders already in `IN_PROGRESS`, `REPORT_SUBMITTED`, `QC_REVIEW`, or
        `REVISION_REQUESTED` in place while blocking any new dispatch to that
        broker."

        Design: Difficulty/non_linear_state_machine/broker_suspend_reinstate_branching
        """
        env = setup_market("OR", client_code="CLF", broker_code="BRKF")
        dispatched = new_order(env)
        dispatched = submit_order(env, dispatched)
        dispatched = dispatch_to_broker(env, dispatched)
        in_progress = drive_order_to_in_progress(env)

        resp = api.suspend_broker(env["broker"]["id"], compliance_officer_headers)
        suspended = validate_success(resp)
        assert suspended["status"] == "SUSPENDED"

        after_dispatched = get_order(dispatched["id"])
        assert after_dispatched["fulfillment_status"] == "READY_FOR_DISPATCH", (
            "DISPATCHED order must revert to READY_FOR_DISPATCH on suspension")
        assert after_dispatched["assigned_broker_id"] is None, (
            "Reverted order must have its assigned_broker_id cleared")

        after_in_progress = get_order(in_progress["id"])
        assert after_in_progress["fulfillment_status"] == "IN_PROGRESS", (
            "IN_PROGRESS order must not be touched by suspension")
        assert after_in_progress["assigned_broker_id"] == env["broker"]["id"]

    def test_suspend_then_reinstate_returns_broker_to_active(
            self, api, compliance_officer_headers):
        """PRD §3.3: "A suspended broker may be reinstated to `ACTIVE`, but only
        if no order assigned to the broker sits in `REVISION_REQUESTED` with a
        revision request whose `outcome` is still `OPEN` and whose `due_at` has
        already passed"

        Design: Difficulty/non_linear_state_machine/broker_suspend_reinstate_branching
        """
        env = setup_market("OR", client_code="CLF", broker_code="BRKF")
        resp = api.suspend_broker(env["broker"]["id"], compliance_officer_headers)
        assert validate_success(resp)["status"] == "SUSPENDED"

        resp = api.reinstate_broker(env["broker"]["id"], compliance_officer_headers)
        reinstated = validate_success(resp)
        assert reinstated["status"] == "ACTIVE", (
            "Suspend then reinstate is a fork-join that returns the broker to ACTIVE")

    def test_cascading_side_effect_broker_suspend_reverts_dispatched(
            self, api, compliance_officer_headers):
        """PRD §2.7: "When a broker is suspended, every order assigned to that
        broker that is still in `DISPATCHED` reverts to `READY_FOR_DISPATCH` and
        has its `assigned_broker_id` cleared, while orders already in `IN_PROGRESS`,
        `REPORT_SUBMITTED`, `QC_REVIEW`, or `REVISION_REQUESTED` remain in place
        but the broker becomes ineligible for new dispatch."

        Design: Corner/cross_cutting_layers/cascading_side_effect_broker_suspend_reverts_dispatched
        """
        env = setup_market("NE", client_code="CCAS", broker_code="BCAS",
                           max_concurrent_orders=10)
        dispatched = new_order(env)
        dispatched = submit_order(env, dispatched)
        dispatched = dispatch_to_broker(env, dispatched)
        in_progress = drive_order_to_in_progress(env)

        resp = api.suspend_broker(env["broker"]["id"], compliance_officer_headers)
        assert validate_success(resp)["status"] == "SUSPENDED"

        after_dispatched = get_order(dispatched["id"])
        assert after_dispatched["fulfillment_status"] == "READY_FOR_DISPATCH"
        assert after_dispatched["assigned_broker_id"] is None

        after_in_progress = get_order(in_progress["id"])
        assert after_in_progress["fulfillment_status"] == "IN_PROGRESS"
        assert after_in_progress["assigned_broker_id"] == env["broker"]["id"]


class TestBrokerTermination:
    def test_broker_terminate_with_open_orders_rejected(
            self, api, compliance_officer_headers):
        """PRD §3.3: "Termination, from either `ACTIVE` or `SUSPENDED`, is allowed
        only when the broker has no order in `DISPATCHED`, `IN_PROGRESS`,
        `REPORT_SUBMITTED`, `QC_REVIEW`, `REVISION_REQUESTED`, or `ACCEPTED` —
        open work blocks termination with `ERR_OPEN_ORDERS_EXIST`"

        Design: Corner/validations/broker_terminate_with_open_orders_rejected
        """
        env = setup_market("DE", client_code="CTO", broker_code="BTO")
        order = new_order(env)
        order = submit_order(env, order)
        dispatch_to_broker(env, order)

        resp = api.terminate_broker(env["broker"]["id"], compliance_officer_headers)
        validate_error(resp, ApiErrorId.ERR_OPEN_ORDERS_EXIST)
        assert get_broker(env["broker"]["id"])["status"] == "ACTIVE"

    def test_terminate_revokes_all_licenses(self, api, compliance_officer_headers):
        """PRD §3.3: "on termination every `BrokerLicense` row for the broker
        transitions to `REVOKED`."

        Design: Difficulty/transitive_cascade/broker_terminate_cascades_licenses_then_orders
        """
        env = setup_market("CO", client_code="CLG", broker_code="BRKG")
        drive_order_to_completed(env)

        resp = api.terminate_broker(env["broker"]["id"], compliance_officer_headers)
        terminated = validate_success(resp)
        assert terminated["status"] == "TERMINATED"

        licenses = list_broker_licenses(env["broker"]["id"])
        assert len(licenses) >= 1, "Setup must have attached at least one license"
        for lic in licenses:
            assert lic["status"] == "REVOKED", (
                f"License {lic['id']} must be REVOKED after termination, "
                f"got {lic['status']}")

    def test_terminated_broker_rejects_future_dispatch(
            self, api, dispatch_coordinator_headers):
        """PRD §3.4: "the selected broker's `status` must be `ACTIVE`
        (`ERR_BROKER_NOT_ACTIVE`)"
        PRD §3.4: "the broker must hold an `ACTIVE` license for the subject
        property's state whose `license_kind` covers the `order_kind` — an
        `APPRAISAL` license covers both `APPRAISAL` and `BPO` orders, while a
        `BPO` license covers only `BPO` orders — and whose `expires_on` is
        strictly in the future (`ERR_LICENSE_NOT_VALID_FOR_STATE`)"
        (A terminated broker fails both checks; the two PRD passages order them
        differently, so either error discharge is accepted.)

        Design: Difficulty/transitive_cascade/broker_terminate_cascades_licenses_then_orders
        """
        env = setup_market("CO", client_code="CLG", broker_code="BRKG")
        drive_order_to_completed(env)
        ready = new_order(env)
        ready = submit_order(env, ready)

        resp = api.terminate_broker(env["broker"]["id"], COMPLIANCE)
        assert validate_success(resp)["status"] == "TERMINATED"

        payload = {"broker_id": env["broker"]["id"],
                   "expected_order_version": ready["version"]}
        resp = api.dispatch_order(ready["id"], payload, dispatch_coordinator_headers)
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_BROKER_NOT_ACTIVE,
                   ApiErrorId.ERR_LICENSE_NOT_VALID_FOR_STATE])

        after = get_order(ready["id"])
        assert after["fulfillment_status"] == "READY_FOR_DISPATCH"
        assert after["assigned_broker_id"] is None
