"""Cross-entity state dependencies: an operation that only succeeds when a related
entity is in the required state.
"""
from test_helpers import (
    api, validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, make_partner_ops_headers, startup_clock,
    create_certified_blueprint, create_validated_partner, create_partner,
    create_product, create_supply_node, create_stack_license, create_deployment,
    activate_deployment, create_and_commit_allocation_hold,
    create_allocation_forecast, create_evaluation_loan, get_product,
    get_deployment, advance_product_lifecycle, get_partner,
    create_allocation_hold,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PROGRAM = TEST_USERS["partner_program_manager_headers"]
SUPPORT = TEST_USERS["support_account_manager_headers"]


class TestDeploymentActivationDependsOnProductAllocation:
    """A deployment cannot activate while its parent SKU holds zero allocated units."""

    def test_activation_with_zero_allocated_units_is_refused(self):
        """PRD §3.7: "the parent product must have a positive allocated unit count".
        PRD §2.12: "The target resource's current state admits the requested trigger,
        otherwise `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/deployment_activation_requires_allocated_parent_product
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        empty_product = create_product(sku_code="AC-EMPTY-PCIE", tdp_watts=700,
                                       supply_ceiling_units=500,
                                       long_term_availability_through="2030-01-01T00:00:00Z")
        stack = create_stack_license(empty_product["id"], license_code="SL-EMPTY-1",
                                     entitlement_units=100)
        deployment = create_deployment(
            empty_product["id"],
            partner["id"],
            stack_manifest=[{"license_id": stack["id"], "entitlement_units": 100}],
            destination_country_code="US")

        response = api.activate_deployment(deployment["id"], SUPPORT)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)
        assert get_deployment(deployment["id"])["activation_state"] == "PENDING", (
            "the deployment stays PENDING when its parent SKU holds no allocation"
        )

    def test_activation_succeeds_once_the_parent_sku_holds_allocated_units(self):
        """PRD §3.7: "the parent product must have a positive allocated unit count".
        PRD §3.7: "Activation applies four gates in the order fixed by §2.12. The partner
        must be `QUALIFIED`; the parent product must have a positive allocated unit
        count; the export classification must not be `TIER_3_PROHIBITED`".

        Design: Difficulty/cross_entity_state_dependency/deployment_activation_requires_allocated_parent_product
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"])
        create_allocation_forecast(product["id"], partner["id"], requested_quantity_units=1000)
        create_and_commit_allocation_hold(product["id"], node["id"], 5, partner["id"])
        stack = create_stack_license(product["id"], license_code="SL-SMALL-1",
                                     entitlement_units=50)
        deployment = create_deployment(
            product["id"],
            partner["id"],
            stack_manifest=[{"license_id": stack["id"], "entitlement_units": 50}],
            destination_country_code="US")

        data = validate_success(api.activate_deployment(deployment["id"], SUPPORT))
        assert data["activation_state"] == "ACTIVATED", (
            "the same activation succeeds on a SKU with a positive allocation"
        )
        assert get_product(product["id"])["allocated_units"] == 5


class TestEvaluationLoanDependsOnPartnerQualification:
    """Loan approval requires a qualified partner and a ring-fenced SKU."""

    def test_loan_approval_requires_a_qualified_partner(self):
        """PRD §3.8: "It requires a `QUALIFIED` partner, a requested quantity no greater
        than the product's reserved evaluation units".
        PRD §2.4: "Attempts without certification are rejected with
        `ERR_QUALIFICATION_NOT_MET` and HTTP 422."

        Design: Difficulty/cross_entity_state_dependency/evaluation_loan_approval_requires_qualified_partner_and_ring_fence
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        unqualified = create_partner(legal_name="Northwind Integrators",
                                     partner_type="SYSTEM_BUILDER",
                                     destination_country="CA", origin_epoch_index=3)
        product = create_product()
        product = advance_product_lifecycle(product["id"])
        assert get_product(product["id"])["reserved_evaluation_units"] == 1000

        good = create_evaluation_loan(product["id"], blueprint["id"], partner["id"],
                                      loan_units=50)
        bad = create_evaluation_loan(product["id"], blueprint["id"], unqualified["id"],
                                     loan_units=50)
        version = get_product(product["id"])["version"]
        approved = validate_success(api.approve_evaluation_loan(
            good["id"], {"expected_product_version": version}, PROGRAM))
        assert approved["loan_state"] == "APPROVED"

        version = get_product(product["id"])["version"]
        response = api.approve_evaluation_loan(
            bad["id"], {"expected_product_version": version}, PROGRAM)
        validate_error(response, ApiErrorId.ERR_QUALIFICATION_NOT_MET)

    def test_ring_fence_only_moves_for_the_qualified_partners_loan(self):
        """PRD §3.8: "Approval adds the loan's units to the product's reserved
        evaluation units, which re-derives its available units".
        PRD §2.4: "Attempts without certification are rejected with
        `ERR_QUALIFICATION_NOT_MET` and HTTP 422."

        Design: Difficulty/cross_entity_state_dependency/evaluation_loan_approval_requires_qualified_partner_and_ring_fence
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        unqualified = create_partner(legal_name="Northwind Integrators",
                                     partner_type="SYSTEM_BUILDER",
                                     destination_country="CA", origin_epoch_index=3)
        product = create_product()
        product = advance_product_lifecycle(product["id"])
        good = create_evaluation_loan(product["id"], blueprint["id"], partner["id"],
                                      loan_units=50)
        bad = create_evaluation_loan(product["id"], blueprint["id"], unqualified["id"],
                                     loan_units=50)

        version = get_product(product["id"])["version"]
        api.approve_evaluation_loan(good["id"], {"expected_product_version": version}, PROGRAM)
        assert get_product(product["id"])["reserved_evaluation_units"] == 1050, (
            "the qualified partner's approval moves the ring fence"
        )

        version = get_product(product["id"])["version"]
        api.approve_evaluation_loan(bad["id"], {"expected_product_version": version}, PROGRAM)
        assert get_product(product["id"])["reserved_evaluation_units"] == 1050, (
            "the refused approval leaves the ring fence untouched"
        )
        loan = get_success_data(api.get_evaluation_loan(
            bad["id"], make_partner_ops_headers(unqualified["id"])))
        assert loan["loan_state"] == "REQUESTED"