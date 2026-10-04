"""Transitive cascades: partner suspension, deployment termination and qualification
rejection each propagate through a fixed depth of dependent entities.
"""
from test_helpers import (
    api, validate_success, get_success_data, TEST_USERS,
    make_partner_ops_headers, startup_clock, create_certified_blueprint,
    create_validated_partner, create_partner, create_validation,
    create_product, create_supply_node, create_stack_license, create_deployment,
    activate_deployment, create_subscription, activate_subscription,
    create_and_commit_allocation_hold, create_and_activate_subscription,
    get_partner, get_product, get_supply_node, get_subscription, get_deployment,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PLANNER = TEST_USERS["supply_planner_headers"]
PROGRAM = TEST_USERS["partner_program_manager_headers"]
SUPPORT = TEST_USERS["support_account_manager_headers"]
SUPPORT_SECOND = TEST_USERS["support_account_manager_2_headers"]


class TestPartnerSuspensionCascade:
    """Suspension cascades three depths into subscriptions and deployments."""

    def test_suspension_suspends_the_subscription_and_clears_service_readiness(self):
        """PRD §3.2: "at the first depth every enterprise support subscription
        belonging to that partner that is `ACTIVE` becomes `SUSPENDED`; at the second
        depth each covered deployment has its service readiness recomputed, becoming
        false when no remaining active subscription covers it".
        PRD §3.2: "The partner's `entitlement_units_held` is deliberately not reduced by
        suspension."

        Design: Difficulty/transitive_cascade/partner_suspension_releases_entitlements_through_three_hops
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
        assert get_partner(partner["id"])["entitlement_units_held"] == 250

        validate_success(api.suspend_partner(partner["id"], PROGRAM))
        assert get_subscription(subscription["id"])["status"] == "SUSPENDED", (
            "depth 1: the ACTIVE subscription becomes SUSPENDED"
        )
        deployment = get_deployment(deployment["id"])
        assert deployment["service_ready"] is False, (
            "depth 2: the covered deployment's readiness is recomputed to false"
        )

    def test_suspension_terminates_the_deployment_and_releases_entitlement(self):
        """PRD §3.2: "at the third depth a deployment whose readiness flipped false
        while it was `ACTIVATED` is moved to `TERMINATED`, which itself triggers the
        entitlement release described later."
        PRD §2.8: "terminating a deployment subtracts the first step of the release
        computation".

        Design: Difficulty/transitive_cascade/partner_suspension_releases_entitlements_through_three_hops
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
        create_and_activate_subscription(deployment["id"], stack_license_id=stack["id"])
        assert get_partner(partner["id"])["entitlement_units_held"] == 250

        validate_success(api.suspend_partner(partner["id"], PROGRAM))
        assert get_deployment(deployment["id"])["activation_state"] == "TERMINATED", (
            "depth 3: the deployment whose readiness flipped false is terminated"
        )
        assert get_partner(partner["id"])["entitlement_units_held"] == 0, (
            "the termination cascade releases the 250 entitlement units"
        )


class TestDeploymentTerminationCascade:
    """Termination reclaims subscriptions and releases product allocation."""

    def test_termination_reclaims_the_subscription_and_releases_entitlement(self):
        """PRD §3.7: "At the first depth, every subscription bound to the deployment
        whose status is `ACTIVE` or `SUSPENDED` becomes `RECLAIMED`. At the second
        depth, the partner's held entitlement is reduced by the released entitlement
        computed for the SKU".

        Design: Difficulty/transitive_cascade/deployment_termination_releases_allocation_through_three_hops
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
        get_success_data(api.handover_deployment(deployment["id"],
                                                 {"handover_reason": "operator rotation"},
                                                 SUPPORT_SECOND))
        assert get_product(product["id"])["allocated_units"] == 400

        validate_success(api.terminate_deployment(deployment["id"], SUPPORT))
        assert get_subscription(subscription["id"])["status"] == "RECLAIMED", (
            "depth 1: the bound subscription becomes RECLAIMED"
        )
        assert get_partner(partner["id"])["entitlement_units_held"] == 0, (
            "depth 2: the entitlement release drains the held entitlement"
        )

    def test_termination_subtracts_the_allocation_and_re_derives_available_units(self):
        """PRD §3.7: "At the third depth, the deployment's `termination_effect_units`
        is the smaller of the released entitlement and the product's allocated units,
        and the product's allocated units are reduced by that effect, which re-derives
        its available units".

        Design: Difficulty/transitive_cascade/deployment_termination_releases_allocation_through_three_hops
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
        create_and_activate_subscription(deployment["id"], stack_license_id=stack["id"])
        get_success_data(api.handover_deployment(deployment["id"],
                                                 {"handover_reason": "operator rotation"},
                                                 SUPPORT_SECOND))

        terminated = validate_success(api.terminate_deployment(deployment["id"], SUPPORT))
        assert terminated["termination_effect_units"] == 250, (
            f"the released entitlement of 250 is below the 400 allocated units, "
            f"got {terminated['termination_effect_units']}"
        )
        product = get_product(product["id"])
        assert product["allocated_units"] == 400 - 250, (
            f"the product's allocated units drop by the termination effect, "
            f"got {product['allocated_units']}"
        )
        assert product["available_units"] == (
            product["supply_ceiling_units"] - product["allocated_units"]
            - product["reserved_evaluation_units"]
        ), "available units are re-derived from the reduced allocation"


class TestQualificationRejectionCascade:
    """A partner rejection rejects submitted evidence and advances the blueprint era."""

    def test_rejection_rejects_the_submitted_evidence_pack(self):
        """PRD §3.2: "At the first depth, every one of the partner's evidence packs
        still in `SUBMITTED` shape is set to `REJECTED`."

        Design: Difficulty/transitive_cascade/qualification_rejection_invalidates_blueprint_era_in_two_hops
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_partner()
        evidence = create_validation(partner["id"], blueprint["id"])

        validate_success(api.reject_partner(partner["id"], PROGRAM))
        data = validate_success(api.get_validation(evidence["id"], PROGRAM))
        assert data["evidence_pack_status"] == "REJECTED", (
            f"depth 1: submitted evidence becomes REJECTED, got {data['evidence_pack_status']!r}"
        )

    def test_rejection_advances_the_blueprint_era_index(self):
        """PRD §3.2: "At the second depth, for each blueprint that lost its only
        `ACCEPTED` evidence in its current era, the blueprint's `era_index` is
        incremented".

        Design: Difficulty/transitive_cascade/qualification_rejection_invalidates_blueprint_era_in_two_hops
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_partner()
        evidence = create_validation(partner["id"], blueprint["id"])
        validate_success(api.accept_validation(evidence["id"], PROGRAM))
        assert get_success_data(api.get_blueprint(blueprint["id"], PLANNER))["era_index"] == 1

        validate_success(api.reject_partner(partner["id"], PROGRAM))
        data = get_success_data(api.get_blueprint(blueprint["id"], PLANNER))
        assert data["era_index"] == 2, (
            f"the blueprint lost its only accepted evidence and its era advanced, "
            f"got {data['era_index']}"
        )