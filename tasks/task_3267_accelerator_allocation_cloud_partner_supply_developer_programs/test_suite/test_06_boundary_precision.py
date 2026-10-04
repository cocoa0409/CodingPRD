"""Boundary-precision rules: inclusive thresholds reached through live API state."""
from test_helpers import (
    api, validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, make_partner_ops_headers, startup_clock, create_certified_blueprint,
    create_validated_partner, create_product, create_supply_node, create_stack_license,
    create_deployment, activate_deployment, create_subscription, activate_subscription,
    create_and_commit_allocation_hold, create_allocation_forecast,
    create_allocation_hold, get_supply_node, get_partner, get_product,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PLANNER = TEST_USERS["supply_planner_headers"]
SUPPORT = TEST_USERS["support_account_manager_headers"]


def _active_deployment_with_stack(quantity_units=400, entitlement_units=250):
    blueprint = create_certified_blueprint()
    partner = create_validated_partner(blueprint_id=blueprint["id"])
    product = create_product()
    node = create_supply_node(product["id"])
    create_and_commit_allocation_hold(product["id"], node["id"], quantity_units,
                                      partner["id"])
    stack = create_stack_license(product["id"], entitlement_units=entitlement_units)
    deployment = create_deployment(
        product["id"],
        partner["id"],
        stack_manifest=[{"license_id": stack["id"], "entitlement_units": entitlement_units}],
        destination_country_code="US")
    deployment = activate_deployment(deployment["id"])
    return partner, product, node, stack, deployment


class TestSupportCreditSeatBoundary:
    """The seat minimum is an inclusive threshold for the support credit."""

    def test_thirty_nine_seats_uses_the_below_minimum_multiplier(self):
        """PRD §2.9: "Below 40 seats the credit is the seat count multiplied by 3; at
        40 seats or above it is the seat count multiplied by 5."
        PRD §2.9: "The boundary is inclusive at 40, giving 200 credit units at exactly
        40 seats and 117 at 39 seats."

        Design: Difficulty/boundary_precision_check/support_credit_seat_min_boundary_is_inclusive
        """
        startup_clock()
        partner, product, node, stack, deployment = _active_deployment_with_stack()
        subscription = create_subscription(deployment["id"], stack_license_id=stack["id"],
                                           support_tier="BUSINESS", seat_count=39)

        data = validate_success(api.activate_subscription(subscription["id"], SUPPORT))
        assert data["support_credit_units"] == 117, (
            f"39 seats * 3 is 117 below the minimum, got {data['support_credit_units']}"
        )

    def test_forty_seats_uses_the_at_or_above_minimum_multiplier(self):
        """PRD §2.9: "at 40 seats or above it is the seat count multiplied by 5" and
        "The boundary is inclusive at 40, giving 200 credit units at exactly 40 seats".

        Design: Difficulty/boundary_precision_check/support_credit_seat_min_boundary_is_inclusive
        """
        startup_clock()
        partner, product, node, stack, deployment = _active_deployment_with_stack()
        subscription = create_subscription(deployment["id"], stack_license_id=stack["id"],
                                           support_tier="BUSINESS", seat_count=40)

        data = validate_success(api.activate_subscription(subscription["id"], SUPPORT))
        assert data["support_credit_units"] == 200, (
            f"40 seats * 5 is 200 at or above the minimum, got {data['support_credit_units']}"
        )


class TestSupplyHotnessBoundary:
    """The HOT breakpoint is inclusive at a committed rate of exactly 7.0."""

    def _pool_accumulating_rate(self, node_code, target_rate):
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"], node_code=node_code)
        forecast = create_allocation_forecast(product["id"], partner["id"],
                                              requested_quantity_units=1000)
        while True:
            node_state = get_supply_node(node["id"])
            if node_state["total_committed_rate"] >= target_rate - 1e-9:
                break
            create_allocation_hold(product["id"], node["id"], 1, partner["id"],
                                   forecast_id=forecast["id"])
        return partner, product, node

    def test_pool_at_exactly_seven_reads_hot_and_warm_ceiling(self):
        """PRD §2.6: "`HOT` at at least 7.0 ... The comparisons are inclusive at their
        boundaries, so a pool sitting at exactly 7.0 is `HOT` while one at 6.999 is
        `WARM`."
        PRD §2.6: "a `HOT` pool has a ceiling of `WARM`".

        Design: Difficulty/boundary_precision_check/supply_hotness_tier_threshold_is_inclusive_at_seven
        """
        startup_clock()
        partner, product, node = self._pool_accumulating_rate("POOL-EXACT-1", 7.0)

        node = get_supply_node(node["id"])
        assert node["total_committed_rate"] == 7.0, (
            f"four 1-unit holds at 1.75 each sum to exactly 7.0, "
            f"got {node['total_committed_rate']}"
        )
        assert node["hotness_tier"] == "HOT", (
            f"the 7.0 breakpoint is inclusive, got {node['hotness_tier']!r}"
        )
        assert node["temp_band_ceiling"] == "WARM", (
            f"a HOT pool grants a WARM ceiling, got {node['temp_band_ceiling']!r}"
        )

    def test_pool_below_the_breakpoint_reads_warm(self):
        """PRD §2.6: "a pool sitting at exactly 7.0 is `HOT` while one at 6.999 is
        `WARM`".

        Design: Difficulty/boundary_precision_check/supply_hotness_tier_threshold_is_inclusive_at_seven
        """
        startup_clock()
        partner, product, node = self._pool_accumulating_rate("POOL-LOW-1", 5.25)

        node = get_supply_node(node["id"])
        assert node["total_committed_rate"] == 5.25, (
            f"three 1-unit holds at 1.75 each sum to 5.25, got {node['total_committed_rate']}"
        )
        assert node["hotness_tier"] == "WARM", (
            f"5.25 is below the 7.0 breakpoint and above 2.0, got {node['hotness_tier']!r}"
        )


class TestEmptyCandidateSetBoundary:
    """A displacing request with no REQUESTED candidate fails before capacity."""

    def test_all_committed_reservations_leave_an_empty_candidate_set(self):
        """PRD §2.7: "the candidate set is empty when no `REQUESTED` hold exists on the
        SKU."
        PRD §2.12: "A displacing allocation finds a non-empty candidate set, otherwise
        `ERR_NO_ALLOCATION_CANDIDATE`; the candidate check precedes any capacity
        comparison."

        Design: Difficulty/boundary_precision_check/empty_allocation_candidate_set_is_rejected_before_capacity
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"], capacity_units=700)
        forecast = create_allocation_forecast(product["id"], partner["id"],
                                              requested_quantity_units=1000)
        create_and_commit_allocation_hold(product["id"], node["id"], 600, partner["id"],
                                          forecast_id=forecast["id"])
        # Only 100 units of unheld capacity remain, but no REQUESTED hold exists.
        partner_state = get_partner(partner["id"])
        product_state = get_product(product["id"])
        response = api.create_allocation_hold({
            "product_sku_id": product["id"],
            "supply_node_id": node["id"],
            "quantity_units": 200,
            "hold_friction_tier": "COOL",
            "forecast_id": forecast["id"],
            "preempt_lower_tier": True,
            "expected_partner_version": partner_state["version"],
            "expected_allocated_units": product_state["allocated_units"],
        }, make_partner_ops_headers(partner["id"]))
        validate_error(response, ApiErrorId.ERR_NO_ALLOCATION_CANDIDATE)

    def test_the_committed_hold_and_pool_are_untouched_by_the_refusal(self):
        """PRD §2.7: "`ERR_NO_ALLOCATION_CANDIDATE`; the candidate check precedes any
        capacity comparison."
        PRD §3.4: "The displaced partner's capacity ledger is debited, while the pool's
        held units are untouched because those reservations were never committed."

        Design: Difficulty/boundary_precision_check/empty_allocation_candidate_set_is_rejected_before_capacity
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"], capacity_units=700)
        forecast = create_allocation_forecast(product["id"], partner["id"],
                                              requested_quantity_units=1000)
        committed = create_and_commit_allocation_hold(product["id"], node["id"], 600,
                                                      partner["id"],
                                                      forecast_id=forecast["id"])
        partner_state = get_partner(partner["id"])
        product_state = get_product(product["id"])
        api.create_allocation_hold({
            "product_sku_id": product["id"],
            "supply_node_id": node["id"],
            "quantity_units": 200,
            "hold_friction_tier": "COOL",
            "forecast_id": forecast["id"],
            "preempt_lower_tier": True,
            "expected_partner_version": partner_state["version"],
            "expected_allocated_units": product_state["allocated_units"],
        }, make_partner_ops_headers(partner["id"]))

        assert get_supply_node(node["id"])["held_units"] == 600, (
            "the pool's held units are unchanged by the refused displacement"
        )
        hold = get_success_data(api.get_allocation_hold(
            committed["id"], make_partner_ops_headers(partner["id"])))
        assert hold["state"] == "COMMITTED", (
            "the existing reservation stays COMMITTED"
        )
