"""Priority-pair conflicts: which of two simultaneously-breached rules is reported.

Each conflict is asserted by toggling a single condition so the exclusive ranking is
directly observable.
"""
from test_helpers import (
    api, validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, make_partner_ops_headers, startup_clock,
    create_certified_blueprint, create_validated_partner, create_product,
    create_supply_node, create_stack_license, create_deployment,
    activate_deployment, create_and_activate_subscription,
    create_and_commit_allocation_hold, create_lifecycle_commitment,
    create_allocation_forecast, get_product, get_deployment, get_subscription,
    get_partner, advance_product_lifecycle,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PROGRAM = TEST_USERS["partner_program_manager_headers"]
SUPPORT = TEST_USERS["support_account_manager_headers"]
SUPPORT_SECOND = TEST_USERS["support_account_manager_2_headers"]
LIFECYCLE = TEST_USERS["lifecycle_program_manager_headers"]


class TestDutyGateBeatsCoveringSubscription:
    """The separation-of-duties gate is ordered below the covering-subscription rule."""

    def test_uncovered_deployment_termination_reports_the_covering_subscription_error(self):
        """PRD §2.12: "The separation-of-duties check on deployment termination sits
        below the covering-subscription constraint, so a deployment with no covering
        subscription reports `ERR_NO_COVERING_SUBSCRIPTION` rather than the same-actor
        error".
        PRD §3.7: "the same error is emitted when a deployment with no covering
        subscription is terminated."

        Design: Difficulty/priority_pair_validation_conflict/same_actor_duty_gate_beats_covering_subscription_referential
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
        get_success_data(api.handover_deployment(deployment["id"],
                                                 {"handover_reason": "operator rotation"},
                                                 SUPPORT_SECOND))

        response = api.terminate_deployment(deployment["id"], SUPPORT)
        validate_error(response, ApiErrorId.ERR_NO_COVERING_SUBSCRIPTION)
        assert get_deployment(deployment["id"])["activation_state"] == "ACTIVATED", (
            "no state change is applied when the covering-subscription gate refuses"
        )

    def test_deployment_terminated_by_its_own_activator_reports_the_duty_error(self):
        """PRD §2.12: "a deployment that does have a covering subscription and is
        terminated by its own activator reports `ERR_SAME_ACTOR_DEPLOYMENT_CHAIN`."
        PRD §3.7: "the `X-User-ID` terminating the deployment must differ from the
        `X-User-ID` recorded on the audit entry for that deployment's activation, and a
        match is rejected with `ERR_SAME_ACTOR_DEPLOYMENT_CHAIN` at HTTP 409 with no
        state changes applied."

        Design: Difficulty/priority_pair_validation_conflict/same_actor_duty_gate_beats_covering_subscription_referential
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
        # Activate with the same opaque SupportAccountManager identity that will terminate.
        deployment = activate_deployment(deployment["id"])
        create_and_activate_subscription(deployment["id"], stack_license_id=stack["id"])

        response = api.terminate_deployment(deployment["id"], SUPPORT)
        validate_error(response, ApiErrorId.ERR_SAME_ACTOR_DEPLOYMENT_CHAIN)
        deployment = get_deployment(deployment["id"])
        assert deployment["activation_state"] == "ACTIVATED", (
            "no state change is applied when the duty gate refuses"
        )
        assert deployment["service_ready"] is True


class TestHoldTierBeatsSupplyCeiling:
    """The band rule is evaluated before the committed-volume ceiling."""

    def _partner_at_the_ceiling_on_a_cool_pool(self):
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"])
        forecast = create_allocation_forecast(product["id"], partner["id"],
                                              requested_quantity_units=1000)
        partner_state = get_partner(partner["id"])
        product_state = get_product(product["id"])
        return partner, product, node, forecast, partner_state, product_state

    def test_hold_above_the_pool_ceiling_reports_the_band_error(self):
        """PRD §3.4: "The allocation path also refuses with `ERR_HOLD_TIER_EXCEEDS_BAND`
        when a hold's friction tier ranks above the pool's ceiling and the request is
        being evaluated through a path that treats tier overshoot as a hard constraint
        rather than the friction path".
        PRD §2.12: "The hold friction tier ranks at or below the pool's ceiling,
        otherwise `ERR_HOLD_TIER_EXCEEDS_BAND`."

        Design: Difficulty/priority_pair_validation_conflict/hold_tier_band_beats_supply_ceiling_fiscal
        """
        partner, product, node, forecast, partner_state, product_state = \
            self._partner_at_the_ceiling_on_a_cool_pool()
        # A COOL pool accepts only COOL; a SCALDING hold ranks above its ceiling, and
        # 5000 units would also breach the partner's committed-volume ceiling.
        response = api.create_allocation_hold({
            "product_sku_id": product["id"],
            "supply_node_id": node["id"],
            "quantity_units": 5000,
            "hold_friction_tier": "SCALDING",
            "forecast_id": forecast["id"],
            "expected_partner_version": partner_state["version"],
            "expected_allocated_units": product_state["allocated_units"],
        }, make_partner_ops_headers(partner["id"]))
        validate_error(response, ApiErrorId.ERR_HOLD_TIER_EXCEEDS_BAND)

    def test_the_band_error_is_reported_rather_than_the_ceiling_error(self):
        """PRD §2.12: "The order is: ... 9. The hold friction tier ranks at or below the
        pool's ceiling, otherwise `ERR_HOLD_TIER_EXCEEDS_BAND`. ... 22. The partner's
        committed-volume ceiling is not breached, otherwise
        `ERR_SUPPLY_CEILING_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/hold_tier_band_beats_supply_ceiling_fiscal
        """
        partner, product, node, forecast, partner_state, product_state = \
            self._partner_at_the_ceiling_on_a_cool_pool()
        response = api.create_allocation_hold({
            "product_sku_id": product["id"],
            "supply_node_id": node["id"],
            "quantity_units": 5000,
            "hold_friction_tier": "SCALDING",
            "forecast_id": forecast["id"],
            "expected_partner_version": partner_state["version"],
            "expected_allocated_units": product_state["allocated_units"],
        }, make_partner_ops_headers(partner["id"]))
        error = validate_error(response, ApiErrorId.ERR_HOLD_TIER_EXCEEDS_BAND)
        assert error["error_id"] != ApiErrorId.ERR_SUPPLY_CEILING_EXCEEDED, (
            "priority 9 is evaluated before priority 22"
        )


class TestLifecycleHorizonBeatsUnits:
    """The horizon grace floor is evaluated before the unit-availability bound."""

    def test_short_horizon_with_excess_units_reports_the_horizon_error(self):
        """PRD §3.9: "the requested horizon is at or after the logical clock plus the
        lifecycle grace period of 365 days, with a shorter horizon refused as
        `ERR_LIFECYCLE_HORIZON_TOO_SHORT` at HTTP 422; and the covered units do not
        exceed the product's available units, with an excess refused as
        `ERR_LIFECYCLE_UNITS_UNCOMMITTED`."

        Design: Difficulty/priority_pair_validation_conflict/lifecycle_horizon_short_beats_lifecycle_units_fiscal
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(
            legal_name="Vector Embedded Ltd", partner_type="EMBEDDED_VENDOR",
            destination_country="SG", export_restriction_tier="LICENSE_REQUIRED",
            blueprint_id=blueprint["id"])
        product = create_product(sku_code="AC-EMB-PCIE", product_family="EMBEDDED",
                                 tdp_watts=900, supply_ceiling_units=10000,
                                 long_term_availability_through="2032-01-01T00:00:00Z")
        product = advance_product_lifecycle(product["id"])
        # A horizon inside the 365-day grace window and covered units far above the
        # product's 9000 available units breach both rules at once.
        commitment = create_lifecycle_commitment(
            product["id"], partner["id"], availability_through="2026-10-01T00:00:00Z",
            covered_units=20000)
        product = get_product(product["id"])

        response = api.grant_lifecycle_commitment(
            commitment["id"], {"expected_product_version": product["version"]}, LIFECYCLE)
        validate_error(response, ApiErrorId.ERR_LIFECYCLE_HORIZON_TOO_SHORT)

    def test_refused_grant_leaves_the_commitment_and_product_untouched(self):
        """PRD §3.9: "Granting it moves it to `GRANTED` and requires three conditions: the
        embedded partner is `QUALIFIED`; the requested horizon is at or after the logical
        clock plus the lifecycle grace period of 365 days, with a shorter horizon refused
        as `ERR_LIFECYCLE_HORIZON_TOO_SHORT` at HTTP 422".
        PRD §3.9: "Granting also sets the embedded partner's `lifecycle_floor_expires_at`
        to the requested horizon and increments the product's `version` by one."

        Design: Difficulty/priority_pair_validation_conflict/lifecycle_horizon_short_beats_lifecycle_units_fiscal
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(
            legal_name="Vector Embedded Ltd", partner_type="EMBEDDED_VENDOR",
            destination_country="SG", export_restriction_tier="LICENSE_REQUIRED",
            blueprint_id=blueprint["id"])
        product = create_product(sku_code="AC-EMB-PCIE", product_family="EMBEDDED",
                                 tdp_watts=900, supply_ceiling_units=10000,
                                 long_term_availability_through="2032-01-01T00:00:00Z")
        product = advance_product_lifecycle(product["id"])
        commitment = create_lifecycle_commitment(
            product["id"], partner["id"], availability_through="2026-10-01T00:00:00Z",
            covered_units=20000)
        product = get_product(product["id"])

        response = api.grant_lifecycle_commitment(
            commitment["id"], {"expected_product_version": product["version"]}, LIFECYCLE)
        error = validate_error(response, ApiErrorId.ERR_LIFECYCLE_HORIZON_TOO_SHORT)
        assert error["error_id"] != ApiErrorId.ERR_LIFECYCLE_UNITS_UNCOMMITTED, (
            "the horizon rule is ordered above the unit-availability rule"
        )
        fetched = get_success_data(api.get_lifecycle_commitment(commitment["id"], LIFECYCLE))
        assert fetched["commitment_status"] == "REQUESTED", (
            "a refused grant leaves the commitment in REQUESTED"
        )
        assert get_product(product["id"])["lifecycle_min_remaining_days"] == 0, (
            "no product lifecycle floor is written when the grant is refused"
        )