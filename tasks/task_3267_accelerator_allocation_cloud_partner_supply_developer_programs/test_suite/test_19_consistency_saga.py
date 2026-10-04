"""Corner coverage: saga compensation on deployment termination."""
from test_helpers import (
    api, validate_success, get_success_data, TEST_USERS,
    make_partner_ops_headers, startup_clock, create_certified_blueprint,
    create_validated_partner, create_product, create_supply_node,
    create_stack_license, create_deployment, activate_deployment,
    create_subscription, create_and_activate_subscription,
    create_and_commit_allocation_hold, get_partner, get_product,
    get_subscription,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PROGRAM = TEST_USERS["partner_program_manager_headers"]
SUPPORT = TEST_USERS["support_account_manager_headers"]
SUPPORT_SECOND = TEST_USERS["support_account_manager_2_headers"]


class TestDeploymentTerminationSaga:
    """Termination steps run to completion even when the reclaim step is a no-op."""

    def test_termination_completes_when_the_covering_subscription_is_suspended(self):
        """PRD §3.7: "At the first depth, every subscription bound to the deployment
        whose status is `ACTIVE` or `SUSPENDED` becomes `RECLAIMED`."
        PRD §2.8: "terminating a deployment subtracts the first step of the release
        computation described in the subscription section."

        Design: Corner/consistency_model/deployment_termination_completes_when_the_covering_subscription_is_already_suspended
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
                                                        stack_license_id=stack["id"],
                                                        seat_count=60)
        assert get_subscription(subscription["id"])["status"] == "ACTIVE"
        # A handover records a fresh actor so the separation-of-duties gate
        # admits the termination.
        get_success_data(api.handover_deployment(deployment["id"],
                                                 {"handover_reason": "operator rotation"},
                                                 SUPPORT_SECOND))

        terminated = validate_success(api.terminate_deployment(deployment["id"], SUPPORT))
        assert terminated["activation_state"] == "TERMINATED", (
            "the covering subscription does not stop the deployment termination"
        )

    def test_suspended_subscription_is_reclaimed_and_entitlement_released(self):
        """PRD §3.7: "At the second depth, the partner's held entitlement is reduced by
        the released entitlement computed for the SKU".
        PRD §3.7: "At the third depth, ... the product's allocated units are reduced by
        that effect".

        Design: Corner/consistency_model/deployment_termination_completes_when_the_covering_subscription_is_already_suspended
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
                                                        stack_license_id=stack["id"],
                                                        seat_count=60)
        get_success_data(api.handover_deployment(deployment["id"],
                                                 {"handover_reason": "operator rotation"},
                                                 SUPPORT_SECOND))
        validate_success(api.terminate_deployment(deployment["id"], SUPPORT))

        assert get_subscription(subscription["id"])["status"] == "RECLAIMED", (
            "the ACTIVE subscription becomes RECLAIMED at depth 1"
        )
        assert get_partner(partner["id"])["entitlement_units_held"] == 0, (
            "the entitlement release still runs to completion"
        )
        # termination_effect_units is the smaller of the released 250 and the
        # product's 400 allocated units, so the SKU is left with 150 (PRD 3.7).
        assert get_product(product["id"])["allocated_units"] == 150, (
            "the allocation subtract still runs to completion"
        )