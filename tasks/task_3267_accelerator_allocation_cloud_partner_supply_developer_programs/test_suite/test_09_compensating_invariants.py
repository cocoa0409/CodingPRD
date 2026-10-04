"""Compensating invariants: conserved quantities that net to zero across a paired
operation, with a visible mid-pair excursion.
"""
from test_helpers import (
    api, validate_success, get_success_data, ApiErrorId,
    TEST_USERS, make_partner_ops_headers, startup_clock,
    create_certified_blueprint, create_validated_partner, create_product,
    create_supply_node, create_stack_license, create_deployment,
    activate_deployment, create_subscription, create_and_activate_subscription,
    create_and_commit_allocation_hold, create_evaluation_loan, get_product,
    get_partner, get_subscription, advance_product_lifecycle,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PROGRAM = TEST_USERS["partner_program_manager_headers"]
SUPPORT = TEST_USERS["support_account_manager_headers"]
SUPPORT_SECOND = TEST_USERS["support_account_manager_2_headers"]


class TestEntitlementLedgerCompensation:
    """The compensating partner of a subscription confirmation is deployment termination."""

    def test_reclaim_leaves_the_entitlement_ledger_holding_the_confirmed_units(self):
        """PRD §2.8: "reclaiming a subscription never returns entitlement units: only
        the deployment termination path releases them".
        PRD §3.8: "confirming a subscription and then reclaiming it leaves the partner's
        held entitlement exactly unchanged."

        Design: Difficulty/compensating_invariant/entitlement_ledger_compensation_is_termination_not_reclaim
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
        subscription = create_subscription(deployment["id"], stack_license_id=stack["id"])
        assert get_partner(partner["id"])["entitlement_units_held"] == 0

        validate_success(api.activate_subscription(subscription["id"], SUPPORT))
        assert get_partner(partner["id"])["entitlement_units_held"] == 250, (
            "confirming the subscription adds the bound stack's 250 entitlement units"
        )

        validate_success(api.reclaim_subscription(subscription["id"], SUPPORT))
        assert get_partner(partner["id"])["entitlement_units_held"] == 250, (
            "reclaiming a subscription does not return entitlement units"
        )

    def test_termination_returns_the_ledger_to_its_pre_confirmation_value(self):
        """PRD §3.7: "the partner's held entitlement is reduced by the released
        entitlement computed for the SKU".
        PRD §2.8: "a partner whose subscriptions were suspended and then reinstated must
        show an unchanged `entitlement_units_held`."

        Design: Difficulty/compensating_invariant/entitlement_ledger_compensation_is_termination_not_reclaim
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
                                           seat_count=39)
        get_success_data(api.handover_deployment(deployment["id"],
                                                 {"handover_reason": "operator rotation"},
                                                 SUPPORT_SECOND))
        before = get_partner(partner["id"])["entitlement_units_held"]
        assert before == 0

        validate_success(api.activate_subscription(subscription["id"], SUPPORT))
        assert get_partner(partner["id"])["entitlement_units_held"] == 250

        validate_success(api.terminate_deployment(deployment["id"], SUPPORT))
        after = get_partner(partner["id"])["entitlement_units_held"]
        assert after == before, (
            f"the confirmation and the deployment termination form the compensating "
            f"pair: expected {before}, got {after}"
        )


class TestEvaluationRingFenceCompensation:
    """Approval/return and approval/reclaim round trips each net a zero ring fence."""

    def _ring_fenced_product_with_two_loans(self):
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        product = advance_product_lifecycle(product["id"])
        loan_one = create_evaluation_loan(product["id"], blueprint["id"], partner["id"],
                                          loan_units=50)
        loan_two = create_evaluation_loan(product["id"], blueprint["id"], partner["id"],
                                          loan_units=50)
        return partner, product, blueprint, loan_one, loan_two

    def test_approve_and_return_round_trip_nets_zero_ring_fence(self):
        """PRD §3.8: "Because approvals and round trips are additive on a conserved field, two
        invariants hold and are directly testable from the read surfaces."
        PRD §3.8: "Approving a loan of some quantity and then returning or reclaiming it
        leaves the product's reserved evaluation units exactly where they started."

        Design: Difficulty/compensating_invariant/evaluation_ring_fence_nets_zero_across_loan_round_trips
        """
        partner, product, blueprint, loan_one, loan_two = self._ring_fenced_product_with_two_loans()
        assert get_product(product["id"])["reserved_evaluation_units"] == 1000

        version = get_product(product["id"])["version"]
        validate_success(api.approve_evaluation_loan(
            loan_one["id"], {"expected_product_version": version}, PROGRAM))
        assert get_product(product["id"])["reserved_evaluation_units"] == 1050, (
            "approval exposes a 1050 excursion mid-pair"
        )
        validate_success(api.start_evaluation_loan(loan_one["id"], PROGRAM))
        validate_success(api.return_evaluation_loan(loan_one["id"], PROGRAM))
        assert get_product(product["id"])["reserved_evaluation_units"] == 1000, (
            "returning the loan releases the ring fence back to 1000"
        )

    def test_approve_and_reclaim_round_trip_nets_zero_ring_fence(self):
        """PRD §3.8: "It may also be reclaimed, moving it to `RECLAIMED` with the same zero net
        delta".
        PRD §3.8: "Because approvals and round trips are additive on a conserved field,
        two invariants hold and are directly testable from the read surfaces."

        Design: Difficulty/compensating_invariant/evaluation_ring_fence_nets_zero_across_loan_round_trips
        """
        partner, product, blueprint, loan_one, loan_two = self._ring_fenced_product_with_two_loans()
        version = get_product(product["id"])["version"]
        validate_success(api.approve_evaluation_loan(
            loan_two["id"], {"expected_product_version": version}, PROGRAM))
        assert get_product(product["id"])["reserved_evaluation_units"] == 1050
        validate_success(api.reclaim_evaluation_loan(loan_two["id"], PROGRAM))
        assert get_product(product["id"])["reserved_evaluation_units"] == 1000, (
            "reclaiming an approved loan nets the same zero delta as a return"
        )