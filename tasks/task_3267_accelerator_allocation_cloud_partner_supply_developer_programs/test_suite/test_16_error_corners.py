"""Corner coverage: error-triggering rules that report a specific error_id."""
from test_helpers import (
    api, validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, make_partner_ops_headers, startup_clock, set_clock,
    create_certified_blueprint, create_validated_partner, create_product,
    create_supply_node, create_stack_license, create_deployment,
    activate_deployment, create_allocation_hold, create_and_commit_allocation_hold,
    create_allocation_forecast, create_evaluation_loan, get_product, get_partner,
    advance_product_lifecycle, create_export_license,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PROGRAM = TEST_USERS["partner_program_manager_headers"]
SUPPORT = TEST_USERS["support_account_manager_headers"]


class TestForecastDeadline:
    """A commit landing exactly on the eligibility deadline is refused."""

    def test_medium_acknowledgement_sets_the_forty_five_day_deadline(self):
        """PRD §3.5: "an acknowledgement at the very start of 2026-09-01, before the
        15th, lands on a boundary of 2026-09-19 and, sitting within the seven-day
        window, takes the `MEDIUM` band with a deadline of 2026-10-16."

        Design: Corner/errors/forecast_commit_at_the_deadline_instant_is_refused
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        forecast = create_allocation_forecast(product["id"], partner["id"],
                                              requested_quantity_units=1000,
                                              acknowledge_only=True)
        assert forecast["horizon_band"] == "MEDIUM"
        deadline = get_partner(partner["id"])["eligibility_deadline_at"]
        assert deadline.startswith("2026-10-16"), (
            f"a 2026-09-01 acknowledgement carries a 2026-10-16 deadline, got {deadline}"
        )

    def test_commit_one_second_before_the_deadline_is_accepted(self):
        """PRD §3.5: "the logical clock strictly before the partner's eligibility
        deadline" — a commit one second earlier is inside the window.

        Design: Corner/errors/forecast_commit_at_the_deadline_instant_is_refused
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        forecast = create_allocation_forecast(product["id"], partner["id"],
                                              requested_quantity_units=1000,
                                              acknowledge_only=True)
        set_clock("2026-10-15T23:59:59Z")

        data = validate_success(api.commit_demand_forecast(
            forecast["id"], {"committed_quantity_units": 1000},
            make_partner_ops_headers(partner["id"])))
        assert data["tracking_status"] == "ACTIVE"

    def test_deadline_instant_refusal_leaves_the_forecast_uncommitted(self):
        """PRD §3.5: "a commit arriving exactly on the deadline instant is late and is
        refused with `ERR_FORECAST_DEADLINE_PASSED`".
        PRD §2.12: "17. A forecast commit arrives strictly before the eligibility
        deadline, otherwise `ERR_FORECAST_DEADLINE_PASSED`."

        Design: Corner/errors/forecast_commit_at_the_deadline_instant_is_refused
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        forecast = create_allocation_forecast(product["id"], partner["id"],
                                              requested_quantity_units=1000,
                                              acknowledge_only=True)
        set_clock("2026-10-16T00:00:00Z")

        response = api.commit_demand_forecast(
            forecast["id"], {"committed_quantity_units": 1000},
            make_partner_ops_headers(partner["id"]))
        validate_error(response, ApiErrorId.ERR_FORECAST_DEADLINE_PASSED)
        fetched = get_success_data(api.get_demand_forecast(
            forecast["id"], make_partner_ops_headers(partner["id"])))
        assert fetched["tracking_status"] == "FORECAST_SUBMITTED"


class TestForecastSupportsHold:
    """A hold naming an acknowledged but uncommitted forecast is refused."""

    def test_uncommitted_forecast_is_refused(self):
        """PRD §3.4: "If a `forecast_id` is named, the referenced forecast must be in
        `ACTIVE` or `COMMITTED` tracking status for the same partner and SKU, otherwise
        the request is refused with `ERR_FORECAST_NOT_COMMITTED`."

        Design: Corner/errors/hold_naming_an_uncommitted_forecast_returns_forecast_error
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"])
        forecast = create_allocation_forecast(product["id"], partner["id"],
                                              requested_quantity_units=1000,
                                              acknowledge_only=True)
        partner_state = get_partner(partner["id"])
        product_state = get_product(product["id"])

        response = api.create_allocation_hold({
            "product_sku_id": product["id"],
            "supply_node_id": node["id"],
            "quantity_units": 200,
            "hold_friction_tier": "COOL",
            "forecast_id": forecast["id"],
            "expected_partner_version": partner_state["version"],
            "expected_allocated_units": product_state["allocated_units"],
        }, make_partner_ops_headers(partner["id"]))
        validate_error(response, ApiErrorId.ERR_FORECAST_NOT_COMMITTED)
        assert get_success_data(api.get_demand_forecast(
            forecast["id"], make_partner_ops_headers(partner["id"]))
        )["tracking_status"] == "FORECAST_SUBMITTED"


class TestSubscriptionLicenceGroupResolves:
    """A licence group naming a stack built for another SKU is unresolved."""

    def test_foreign_sku_stack_is_refused_and_matching_stack_accepted(self):
        """PRD §3.7: "Every `HardwareDeployment` ... a licence group naming a stack
        license whose product SKU does not match the deployment's SKU is refused with
        `ERR_LICENSE_GROUP_UNRESOLVED` at HTTP 422."

        Design: Corner/errors/subscription_licence_from_another_sku_is_unresolved
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        other = create_product(sku_code="AC-EMB-PCIE", product_family="EMBEDDED",
                               tdp_watts=900, supply_ceiling_units=4000,
                               long_term_availability_through="2032-01-01T00:00:00Z")
        node = create_supply_node(product["id"])
        create_and_commit_allocation_hold(product["id"], node["id"], 5, partner["id"])
        matching = create_stack_license(product["id"], license_code="SL-OK-1",
                                        entitlement_units=50)
        foreign = create_stack_license(other["id"], license_code="SL-OTHER-1",
                                       entitlement_units=50)
        deployment = create_deployment(
            product["id"],
            partner["id"],
            stack_manifest=[{"license_id": matching["id"], "entitlement_units": 50}],
            destination_country_code="US")
        deployment = activate_deployment(deployment["id"])

        refused = api.create_subscription({
            "deployment_id": deployment["id"], "support_tier": "BASIC",
            "seat_count": 50, "licence_group": [{"license_id": foreign["id"]}],
            "trial_flag": True}, SUPPORT)
        validate_error(refused, ApiErrorId.ERR_LICENSE_GROUP_UNRESOLVED, 422)

        accepted = validate_success(api.create_subscription({
            "deployment_id": deployment["id"], "support_tier": "BASIC",
            "seat_count": 50, "licence_group": [{"license_id": matching["id"]}],
            "trial_flag": True}, SUPPORT), 201)
        assert accepted["deployment_id"] == deployment["id"]


class TestEvaluationReservationBound:
    """A loan larger than the SKU's ring fence is refused."""

    def test_oversized_loan_is_refused_inside_the_fence_is_approved(self):
        """PRD §3.8: "A loan's units must be positive and must not exceed the SKU's
        reserved evaluation units."
        PRD §3.8: "A loan that exceeds the reservation is refused with
        `ERR_RESERVED_FOR_EVALUATION`."

        Design: Corner/errors/evaluation_loan_beyond_the_ring_fence_returns_reserved_error
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        product = advance_product_lifecycle(product["id"])
        assert get_product(product["id"])["reserved_evaluation_units"] == 1000
        small = create_evaluation_loan(product["id"], blueprint["id"], partner["id"],
                                       loan_units=50)
        big = create_evaluation_loan(product["id"], blueprint["id"], partner["id"],
                                     loan_units=1500)

        version = get_product(product["id"])["version"]
        refused = api.approve_evaluation_loan(
            big["id"], {"expected_product_version": version}, PROGRAM)
        validate_error(refused, ApiErrorId.ERR_RESERVED_FOR_EVALUATION)

        version = get_product(product["id"])["version"]
        approved = validate_success(api.approve_evaluation_loan(
            small["id"], {"expected_product_version": version}, PROGRAM))
        assert approved["loan_state"] == "APPROVED"
        assert get_product(product["id"])["reserved_evaluation_units"] == 1050


class TestPartnerSupplyCeiling:
    """The committed-volume ceiling is checked in the strict form."""

    def test_one_unit_over_the_ceiling_is_refused_exactly_on_it_is_accepted(self):
        """PRD §3.4: "The request is also refused with `ERR_SUPPLY_CEILING_EXCEEDED`
        when the partner's committed volume plus the requested quantity would exceed the
        partner's committed volume plus its held entitlement units plus the configured
        supply-ceiling headroom; the comparison uses the strict form, so a request
        landing exactly on the ceiling is accepted."

        Design: Corner/errors/allocation_past_the_partner_supply_ceiling_returns_ceiling_error
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"], capacity_units=20000)
        forecast = create_allocation_forecast(product["id"], partner["id"],
                                              requested_quantity_units=1000)
        product_state = get_product(product["id"])

        over = api.create_allocation_hold({
            "product_sku_id": product["id"],
            "supply_node_id": node["id"],
            "quantity_units": 1001,
            "hold_friction_tier": "COOL",
            "forecast_id": forecast["id"],
            "expected_partner_version": get_partner(partner["id"])["version"],
            "expected_allocated_units": product_state["allocated_units"],
        }, make_partner_ops_headers(partner["id"]))
        validate_error(over, ApiErrorId.ERR_SUPPLY_CEILING_EXCEEDED)

        product_state = get_product(product["id"])
        edge = validate_success(api.create_allocation_hold({
            "product_sku_id": product["id"],
            "supply_node_id": node["id"],
            "quantity_units": 1000,
            "hold_friction_tier": "COOL",
            "forecast_id": forecast["id"],
            "expected_partner_version": get_partner(partner["id"])["version"],
            "expected_allocated_units": product_state["allocated_units"],
        }, make_partner_ops_headers(partner["id"])), 201)
        assert edge["quantity_units"] == 1000, (
            "a request landing exactly on the ceiling is accepted"
        )