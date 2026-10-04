"""Non-linear state machines: cyclic qualification, the friction-band revert cycle,
and the parallel subscription/deployment axes.
"""
from test_helpers import (
    api, validate_success, get_success_data, TEST_USERS,
    make_partner_ops_headers, startup_clock, set_clock,
    create_certified_blueprint, create_validated_partner, create_partner,
    create_validation, create_product, create_supply_node, create_stack_license,
    create_deployment, activate_deployment, create_subscription,
    activate_subscription, create_allocation_hold, create_and_commit_allocation_hold,
    create_and_activate_subscription, get_partner, get_product, get_supply_node,
    get_subscription, get_deployment,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PLANNER = TEST_USERS["supply_planner_headers"]
PROGRAM = TEST_USERS["partner_program_manager_headers"]
SUPPORT = TEST_USERS["support_account_manager_headers"]
SUPPORT_SECOND = TEST_USERS["support_account_manager_2_headers"]


class TestPartnerRequalificationCycle:
    """PartnerAccount is cyclic: a rejection returns the partner to APPLIED."""

    def test_rejection_returns_the_partner_to_applied(self):
        """PRD §3.2: "A `PartnerProgramManager` rejection moves the partner from
        `IN_VALIDATION` back to `APPLIED`".

        Design: Difficulty/non_linear_state_machine/partner_requalification_rejection_revert_cycle
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_partner()
        create_validation(partner["id"], blueprint["id"])

        data = validate_success(api.reject_partner(partner["id"], PROGRAM))
        assert data["qualification_status"] == "APPLIED", (
            f"rejection rolls the partner back to APPLIED, got {data['qualification_status']!r}"
        )

    def test_partner_visits_applied_twice_and_still_reaches_qualified(self):
        """PRD §3.2: "the rejection also increments the partner's
        `qualification_attempt_count`, and that counter is preserved across any later
        re-application."

        Design: Difficulty/non_linear_state_machine/partner_requalification_rejection_revert_cycle
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_partner()
        create_validation(partner["id"], blueprint["id"])
        rejected = validate_success(api.reject_partner(partner["id"], PROGRAM))
        assert rejected["qualification_attempt_count"] == 1, (
            f"a single rejection records one attempt, got "
            f"{rejected['qualification_attempt_count']}"
        )

        evidence = create_validation(partner["id"], blueprint["id"],
                                     validation_minutes=300, test_count=8)
        validate_success(api.accept_validation(evidence["id"], PROGRAM))
        data = validate_success(api.qualify_partner(partner["id"], PROGRAM))
        assert data["qualification_status"] == "QUALIFIED", (
            "the partner re-enters the pipeline and still reaches QUALIFIED"
        )
        assert data["qualification_attempt_count"] == 1, (
            "the attempt counter survives the re-entry"
        )

    def test_the_applied_to_in_validation_cycle_can_repeat(self):
        """PRD §3.2: "which closes the cycle — a partner may move `APPLIED` to
        `IN_VALIDATION` and back to `APPLIED` indefinitely."

        Design: Difficulty/non_linear_state_machine/partner_requalification_rejection_revert_cycle
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_partner()
        for round_index in range(2):
            create_validation(partner["id"], blueprint["id"])
            rejected = validate_success(api.reject_partner(partner["id"], PROGRAM))
            assert rejected["qualification_status"] == "APPLIED", (
                f"round {round_index + 1} rolls the partner back to APPLIED"
            )
        assert rejected["qualification_attempt_count"] == 2, (
            "two round trips through the cycle record two attempts"
        )


class TestSupplyNodeFrictionCycle:
    """SupplyNode revisits OPEN after a friction hold."""

    def test_warm_hold_against_a_cool_pool_enters_friction_hold(self):
        """PRD §3.3: "A hold created against it with a friction tier ranked strictly
        above its temperature ceiling does not reject the request: the hold commits, a
        `BAND_VIOLATION` penalty is created in `ACTIVE` state, the penalty's score is
        added to the pool's friction score, the offending hold's quantity is never
        counted toward the pool's held units, and the pool moves into `FRICTION_HOLD`."

        Design: Difficulty/non_linear_state_machine/supply_node_friction_band_revert_cycle
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"], requested_hotness_tier="COOL")

        hold = create_allocation_hold(product["id"], node["id"], 500, partner["id"],
                                      hold_friction_tier="WARM")
        assert hold["state"] == "COMMITTED", (
            "the band-violation path commits the hold rather than rejecting it"
        )
        node = get_supply_node(node["id"])
        assert node["stage"] == "FRICTION_HOLD", f"got stage {node['stage']!r}"
        assert node["friction_penalty_score"] > 0.0, (
            f"the penalty's score is added to the pool's friction score, "
            f"got {node['friction_penalty_score']}"
        )
        assert node["held_units"] == 0, (
            "the offending hold's quantity is never counted toward the pool's held units"
        )

    def test_friction_hold_pool_returns_to_open_at_the_next_epoch(self):
        """PRD §3.3: "any penalty whose score reaches zero becomes `DECAYED` and stops
        contributing; a pool sitting in `FRICTION_HOLD` returns to `OPEN` at that point
        provided its accumulated penalty score is below 4.0."
        PRD §3.3: "a pool sitting in `FRICTION_HOLD` returns to `OPEN` at that point
        provided its accumulated penalty score is below 4.0".

        Design: Difficulty/non_linear_state_machine/supply_node_friction_band_revert_cycle
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"], requested_hotness_tier="COOL")
        create_allocation_hold(product["id"], node["id"], 500, partner["id"],
                               hold_friction_tier="WARM")

        get_success_data(api.advance_epoch(ADMIN))
        node = get_supply_node(node["id"])
        assert node["stage"] == "OPEN", (
            f"a pool with a penalty score below 4.0 returns to OPEN, got {node['stage']!r}"
        )


class TestSubscriptionDeploymentAxes:
    """Subscription status and deployment activation state evolve independently."""

    def test_terminating_the_deployment_reclaims_the_subscription_but_reinstating_does_not_undo_it(self):
        """PRD §3.7: "At the first depth, every subscription bound to the deployment
        whose status is `ACTIVE` or `SUSPENDED` becomes `RECLAIMED`."
        PRD §3.7: "A terminated deployment may be returned to `PENDING` provided no
        subscription bound to it is `ACTIVE`, but the allocation subtract performed at
        termination is not reversed".

        Design: Difficulty/non_linear_state_machine/subscription_and_deployment_parallel_state_dimensions
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
        subscription = create_and_activate_subscription(deployment["id"],
                                                        stack_license_id=stack["id"])
        # The activator must differ from the terminator.
        get_success_data(api.handover_deployment(deployment["id"],
                                                 {"handover_reason": "operator rotation"},
                                                 SUPPORT_SECOND))

        terminated = validate_success(api.terminate_deployment(deployment["id"], SUPPORT))
        assert terminated["activation_state"] == "TERMINATED"
        assert terminated["service_ready"] is False
        assert get_subscription(subscription["id"])["status"] == "RECLAIMED"

        reinstated = validate_success(api.reinstate_deployment(deployment["id"], SUPPORT))
        assert reinstated["activation_state"] == "PENDING", (
            f"the deployment axis moves back to PENDING, got {reinstated['activation_state']!r}"
        )
        assert get_subscription(subscription["id"])["status"] == "RECLAIMED", (
            "the subscription axis does not move back with the deployment"
        )

    def test_deployment_service_ready_is_false_until_a_subscription_activates(self):
        """PRD §3.7: "Service readiness is not set by activation itself: the
        deployment's `service_ready` becomes true only once at least one subscription
        bound to it reaches `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/subscription_and_deployment_parallel_state_dimensions
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
        assert deployment["service_ready"] is False, (
            "activation alone does not make the deployment service-ready"
        )

        subscription = create_subscription(deployment["id"], stack_license_id=stack["id"])
        activate_subscription(subscription["id"])
        assert get_deployment(deployment["id"])["service_ready"] is True, (
            "activating a covering subscription makes the deployment service-ready"
        )