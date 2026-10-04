"""Corner coverage: state-machine preconditions and invalid transitions."""
from test_helpers import (
    api, validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, make_partner_ops_headers, startup_clock,
    create_certified_blueprint, create_validated_partner, create_product,
    create_supply_node, create_stack_license, create_deployment,
    activate_deployment, create_subscription, create_and_activate_subscription,
    create_allocation_hold, create_membership, create_evaluation_loan,
    create_and_commit_allocation_hold, get_supply_node, get_membership,
    get_evaluation_loan, get_product, get_partner, advance_product_lifecycle,
    get_subscription, get_deployment,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PLANNER = TEST_USERS["supply_planner_headers"]
PROGRAM = TEST_USERS["partner_program_manager_headers"]
SUPPORT = TEST_USERS["support_account_manager_headers"]


class TestAllocationHoldCommitLockdown:
    """A hold that is already COMMITTED refuses a second commit."""

    def test_second_commit_is_refused_and_held_units_do_not_move(self):
        """PRD §3.4: "Committing a requested hold is a `PartnerOps` action that moves it
        from `REQUESTED` to `COMMITTED`".

        Design: Corner/state_machines/allocation_hold_commit_after_commit_is_rejected
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"])
        hold = create_allocation_hold(product["id"], node["id"], 300, partner["id"])

        first = validate_success(api.commit_allocation_hold(
            hold["id"], make_partner_ops_headers(partner["id"]),
            {"consume_reservation": False}))
        assert first["state"] == "COMMITTED"

        response = api.commit_allocation_hold(
            hold["id"], make_partner_ops_headers(partner["id"]),
            {"consume_reservation": False})
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)
        assert get_supply_node(node["id"])["held_units"] == 300, (
            "the held units do not move a second time"
        )


class TestDrainedSupplyNode:
    """A drained pool refuses new allocations."""

    def test_drained_pool_refuses_a_fresh_allocation(self):
        """PRD §2.6: "A pool in `DRAINING` or `BINDING` refuses allocation-creating
        requests with `ERR_NODE_NOT_OPEN_FOR_ALLOCATION` and HTTP 409."

        Design: Corner/state_machines/drained_supply_node_refuses_new_allocation
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"])

        drained = validate_success(api.set_supply_node_stage(
            node["id"], {"target_stage": "DRAINING"}, PLANNER))
        assert drained["stage"] == "DRAINING"

        partner_state = get_partner(partner["id"])
        product_state = get_product(product["id"])
        response = api.create_allocation_hold({
            "product_sku_id": product["id"],
            "supply_node_id": node["id"],
            "quantity_units": 100,
            "hold_friction_tier": "COOL",
            "expected_partner_version": partner_state["version"],
            "expected_allocated_units": product_state["allocated_units"],
        }, make_partner_ops_headers(partner["id"]))
        validate_error(response, ApiErrorId.ERR_NODE_NOT_OPEN_FOR_ALLOCATION)
        assert get_supply_node(node["id"])["held_units"] == 0


class TestMembershipRenewalGraceWindow:
    """A renewal before the evaluation deadline is refused."""

    def test_renewal_before_the_deadline_is_refused(self):
        """PRD §3.6: "A renewal attempted before the deadline is refused with
        `ERR_INVALID_STATE`."
        PRD §3.6: "the tier actually held — the `stored_tier` — always begins at
        `COMMUNITY` regardless of what was requested".

        Design: Corner/state_machines/membership_renewal_before_evaluation_deadline_is_rejected
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        membership = create_membership(partner["id"], requested_tier="ELITE")
        assert membership["stored_tier"] == "COMMUNITY"
        evaluated = validate_success(api.evaluate_membership(membership["id"], PROGRAM))
        assert evaluated["status"] == "UNDER_EVALUATION"

        response = api.renew_membership(membership["id"], PROGRAM)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)
        after = get_membership(membership["id"])
        assert after["status"] == "UNDER_EVALUATION"
        assert after["stored_tier"] == "COMMUNITY", (
            "the one-tier lift only happens once the grace window has elapsed"
        )


class TestReclaimedSubscriptionLockdown:
    """RECLAIMED is terminal for the activation trigger."""

    def test_reclaimed_subscription_cannot_be_reactivated(self):
        """PRD §3.7: "Reclamation is available from both `ACTIVE` and `SUSPENDED`; it
        moves the subscription to `RECLAIMED` and finalises its `settled_fee_cents` by
        the chronological computation, and it deliberately leaves the partner's held
        entitlement unchanged".

        Design: Corner/state_machines/reclaimed_subscription_cannot_be_reactivated
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"])
        create_and_commit_allocation_hold(product["id"], node["id"], 400, partner["id"])
        stack = create_stack_license(product["id"], entitlement_units=250)
        deployment = create_deployment(
            product["id"],
            partner["id"],
            stack_manifest=[{"license_id": stack["id"], "entitlement_units": 250}],
            destination_country_code="US")
        deployment = activate_deployment(deployment["id"])
        subscription = create_subscription(deployment["id"], stack_license_id=stack["id"],
                                           seat_count=60)
        validate_success(api.activate_subscription(subscription["id"], SUPPORT))
        reclaimed = validate_success(api.reclaim_subscription(subscription["id"], SUPPORT))
        assert reclaimed["status"] == "RECLAIMED"

        response = api.activate_subscription(subscription["id"], SUPPORT)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)
        assert get_partner(partner["id"])["entitlement_units_held"] == 250, (
            "the entitlement ledger stays at its post-activation value"
        )


class TestEvaluationLoanReturnLockdown:
    """A return sent while the loan is still REQUESTED is refused."""

    def test_return_before_approval_is_refused_and_the_fence_is_unchanged(self):
        """PRD §3.8: "An overdue loan may be returned by a `PartnerProgramManager`,
        moving it to `RETURNED` and releasing the ring-fence" — the trigger is only
        defined from ACTIVE or OVERDUE.

        Design: Corner/state_machines/evaluation_loan_return_is_rejected_before_approval
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        product = advance_product_lifecycle(product["id"])
        loan = create_evaluation_loan(product["id"], blueprint["id"], partner["id"],
                                      loan_units=50)
        assert loan["loan_state"] == "REQUESTED"

        response = api.return_evaluation_loan(loan["id"], PROGRAM)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)
        assert get_product(product["id"])["reserved_evaluation_units"] == 1000, (
            "the ring fence is unchanged by the refused return"
        )


class TestSubscriptionSuspensionCascade:
    """Suspension applies its side effects in order while pinning the entitlement ledger."""

    def _activated_stack(self, seat_count=60, entitlement_units=250):
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"])
        create_and_commit_allocation_hold(product["id"], node["id"], 400, partner["id"])
        stack = create_stack_license(product["id"], entitlement_units=entitlement_units)
        deployment = create_deployment(
            product["id"],
            partner["id"],
            stack_manifest=[{"license_id": stack["id"], "entitlement_units": entitlement_units}],
            destination_country_code="US")
        deployment = activate_deployment(deployment["id"])
        subscription = create_subscription(deployment["id"], stack_license_id=stack["id"],
                                           seat_count=seat_count)
        validate_success(api.activate_subscription(
            subscription["id"], TEST_USERS["support_account_manager_headers"]))
        return partner, product, node, stack, deployment, subscription

    def test_suspension_applies_each_side_effect_in_order(self):
        """PRD §3.2: "at the first depth every enterprise support subscription belonging
        to that partner that is `ACTIVE` becomes `SUSPENDED`; at the second depth each
        covered deployment has its service readiness recomputed, becoming false when no
        remaining active subscription covers it".
        PRD §3.2: "The partner's `entitlement_units_held` is deliberately not reduced by
        suspension."

        Design: Corner/state_machines/subscription_suspension_cascade_reaches_the_deployment
        """
        partner, product, node, stack, deployment, subscription = self._activated_stack()
        assert get_partner(partner["id"])["entitlement_units_held"] == 250

        suspended = validate_success(api.suspend_partner(partner["id"], PROGRAM))
        assert suspended["qualification_status"] == "SUSPENDED"
        assert get_subscription(subscription["id"])["status"] == "SUSPENDED", (
            "depth 1: the ACTIVE subscription becomes SUSPENDED"
        )
        deployment = get_deployment(deployment["id"])
        assert deployment["service_ready"] is False, (
            "depth 2: service readiness is recomputed to false"
        )
        assert get_partner(partner["id"])["entitlement_units_held"] == 0, (
            "the third depth terminates the deployment and releases the entitlement"
        )

    def test_suspension_side_effects_are_the_same_when_reached_by_a_different_partner(self):
        """PRD §3.2: "Reinstatement is a `PlatformAdmin` action that lifts a suspension,
        returning the partner from `SUSPENDED` to `QUALIFIED` with `ACTIVE` standing."
        PRD §3.6: "the system itself revokes a membership when one of its bound preview
        grants has been revoked" — a distinct trigger that leaves this cascade intact.

        Design: Corner/state_machines/subscription_suspension_cascade_reaches_the_deployment
        """
        partner, product, node, stack, deployment, subscription = self._activated_stack()
        validate_success(api.suspend_partner(partner["id"], PROGRAM))
        assert get_deployment(deployment["id"])["activation_state"] == "TERMINATED"

        reinstated = validate_success(api.reinstate_partner(partner["id"], ADMIN))
        assert reinstated["qualification_status"] == "QUALIFIED"
        assert reinstated["status"] == "ACTIVE"
        assert get_subscription(subscription["id"])["status"] == "SUSPENDED", (
            "reinstatement does not auto-reactivate the suspended subscription"
        )