"""Corner coverage: optimistic concurrency, allocation guards and scheduled sweeps."""
from test_helpers import (
    api, validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, make_partner_ops_headers, startup_clock, set_clock,
    create_certified_blueprint, create_validated_partner, create_validation,
    create_product, create_supply_node, create_stack_license, create_deployment,
    activate_deployment, create_subscription, create_and_commit_allocation_hold,
    create_allocation_hold, create_allocation_forecast, get_partner, get_product,
    get_subscription,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PROGRAM = TEST_USERS["partner_program_manager_headers"]
SUPPORT = TEST_USERS["support_account_manager_headers"]


def _hold_payload(product, node, quantity, partner, expected_version,
                  expected_allocated, **extra):
    payload = {
        "product_sku_id": product["id"],
        "supply_node_id": node["id"],
        "quantity_units": quantity,
        "hold_friction_tier": "COOL",
        "expected_partner_version": expected_version,
        "expected_allocated_units": expected_allocated,
    }
    payload.update(extra)
    return payload


class TestAllocationHoldPartnerVersionGuard:
    """The allocation write is guarded by the parent partner's version."""

    def test_stale_partner_version_is_rejected(self):
        """PRD §2.12: "if the partner's version has moved past the value the client last
        observed, the submission is rejected with `ERR_STALE_PARTNER_VERSION` and HTTP
        412."

        Design: Corner/cross_cutting_complexity_layers/allocation_hold_stale_partner_version_returns_412
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"])
        observed = get_partner(partner["id"])["version"]
        product_state = get_product(product["id"])

        first = validate_success(api.create_allocation_hold(
            _hold_payload(product, node, 100, partner, observed,
                          product_state["allocated_units"]),
            make_partner_ops_headers(partner["id"])), 201)
        assert first["id"]

        replay = api.create_allocation_hold(
            _hold_payload(product, node, 150, partner, observed,
                          product_state["allocated_units"]),
            make_partner_ops_headers(partner["id"]))
        validate_error(replay, ApiErrorId.ERR_STALE_PARTNER_VERSION)
        assert get_partner(partner["id"])["version"] == observed + 1

    def test_only_one_hold_survives_the_replayed_version(self):
        """PRD §2.12: "a submission carrying a superseded version is rejected with
        `ERR_STALE_PARTNER_VERSION` and HTTP 412."

        Design: Corner/cross_cutting_complexity_layers/allocation_hold_stale_partner_version_returns_412
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"])
        observed = get_partner(partner["id"])["version"]
        product_state = get_product(product["id"])
        api.create_allocation_hold(_hold_payload(product, node, 100, partner, observed,
                                                 product_state["allocated_units"]),
                                   make_partner_ops_headers(partner["id"]))
        api.create_allocation_hold(_hold_payload(product, node, 150, partner, observed,
                                                 product_state["allocated_units"]),
                                   make_partner_ops_headers(partner["id"]))

        data, meta = validate_paginated(api.list_allocation_holds(
            make_partner_ops_headers(partner["id"]), params={"partner_id": partner["id"]}))
        assert meta["total_count"] == 1, (
            f"the replayed write is not applied twice, got {meta['total_count']}"
        )


class TestDemandForecastVersionGuard:
    """Forecast creation is guarded by the same parent-version OCC."""

    def test_stale_forecast_version_is_rejected_and_fresh_succeeds(self):
        """PRD §3.5: "a stale version is rejected with `ERR_STALE_PARTNER_VERSION` and
        the request is refused outright."

        Design: Corner/cross_cutting_complexity_layers/demand_forecast_stale_partner_version_returns_412
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"])
        observed = get_partner(partner["id"])["version"]
        product_state = get_product(product["id"])
        # An intervening hold advances the partner version.
        api.create_allocation_hold(_hold_payload(product, node, 100, partner, observed,
                                                 product_state["allocated_units"]),
                                   make_partner_ops_headers(partner["id"]))
        current = get_partner(partner["id"])["version"]

        stale = api.create_demand_forecast({
            "product_sku_id": product["id"], "requested_quantity_units": 800,
            "expected_partner_version": observed,
        }, make_partner_ops_headers(partner["id"]))
        validate_error(stale, ApiErrorId.ERR_STALE_PARTNER_VERSION)

        fresh = validate_success(api.create_demand_forecast({
            "product_sku_id": product["id"], "requested_quantity_units": 800,
            "expected_partner_version": current,
        }, make_partner_ops_headers(partner["id"])), 201)
        assert fresh["id"]


class TestSubscriptionEvaluationGuard:
    """The subscription evaluation is guarded by the subscription's own version."""

    def test_replayed_subscription_version_is_rejected(self):
        """PRD §3.7: "an evaluation carrying a superseded observation of the
        subscription is rejected with `ERR_STALE_SUBSCRIPTION_VERSION` at HTTP 412."

        Design: Corner/cross_cutting_complexity_layers/subscription_evaluate_from_a_stale_version_returns_412
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"])
        create_and_commit_allocation_hold(product["id"], node["id"], 5, partner["id"])
        stack = create_stack_license(product["id"], entitlement_units=250)
        deployment = create_deployment(
            product["id"],
            partner["id"],
            stack_manifest=[{"license_id": stack["id"], "entitlement_units": 250}],
            destination_country_code="US")
        deployment = activate_deployment(deployment["id"])
        subscription = create_subscription(deployment["id"], stack_license_id=stack["id"],
                                           seat_count=50)
        validate_success(api.activate_subscription(subscription["id"], SUPPORT))
        observed = get_subscription(subscription["id"])["version"]

        first = validate_success(api.evaluate_subscription(
            subscription["id"], {"expected_subscription_version": observed}, ADMIN))
        assert first["version"] == observed + 1

        replay = api.evaluate_subscription(
            subscription["id"], {"expected_subscription_version": observed}, ADMIN)
        validate_error(replay, ApiErrorId.ERR_STALE_SUBSCRIPTION_VERSION)


class TestAllocatedUnitsGuard:
    """The allocation guard observes allocated_units, not the product's version."""

    def test_stale_allocated_units_is_rejected_while_the_version_is_current(self):
        """PRD §2.12: "This guard is not optimistic concurrency on the product's
        version: bumping the product version while leaving `allocated_units` unchanged
        must not trip it, and changing `allocated_units` while leaving the version
        untouched must."

        Design: Corner/cross_cutting_complexity_layers/allocated_units_guard_is_independent_of_the_row_version
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"])
        stale_allocated = get_product(product["id"])["allocated_units"]
        # Commit five units so allocated_units moves while the client still observes 0.
        create_and_commit_allocation_hold(product["id"], node["id"], 5, partner["id"])
        current_version = get_partner(partner["id"])["version"]
        current_allocated = get_product(product["id"])["allocated_units"]
        assert stale_allocated == 0 and current_allocated == 5

        refused = api.create_allocation_hold(
            _hold_payload(product, node, 100, partner, current_version, stale_allocated),
            make_partner_ops_headers(partner["id"]))
        validate_error(refused, ApiErrorId.ERR_ALLOCATED_UNITS_CHANGED)

    def test_echoing_the_current_allocated_units_succeeds(self):
        """PRD §2.12: "changing `allocated_units` while leaving the version untouched
        must" trip the guard, and echoing the current value must not.

        Design: Corner/cross_cutting_complexity_layers/allocated_units_guard_is_independent_of_the_row_version
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"])
        create_and_commit_allocation_hold(product["id"], node["id"], 5, partner["id"])
        current_version = get_partner(partner["id"])["version"]
        current_allocated = get_product(product["id"])["allocated_units"]

        accepted = validate_success(api.create_allocation_hold(
            _hold_payload(product, node, 100, partner, current_version, current_allocated),
            make_partner_ops_headers(partner["id"])), 201)
        assert accepted["id"]


class TestEpochAutoCommit:
    """The epoch checkpoint auto-commits a forecast whose deadline has arrived."""

    def test_advance_epoch_auto_commits_an_active_forecast(self):
        """PRD §3.10: "It auto-commits every demand forecast that is `ACTIVE` and whose
        partner eligibility deadline has been reached."
        PRD §3.5: "The other exit is automatic: when the logical clock reaches the
        partner's eligibility deadline, the epoch checkpoint moves any `ACTIVE` forecast
        to `COMMITTED`, freezing its forfeit rate."

        Design: Corner/cross_cutting_complexity_layers/epoch_advance_auto_commits_a_forecast_whose_deadline_has_arrived
        """
        set_clock("2026-09-18T00:00:00Z")
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        # A 2026-09-18 acknowledgement takes the SHORT band, so the deadline is 2026-09-20.
        forecast = create_allocation_forecast(product["id"], partner["id"],
                                              requested_quantity_units=1000)
        assert get_success_data(api.get_demand_forecast(
            forecast["id"], make_partner_ops_headers(partner["id"]))
        )["tracking_status"] == "ACTIVE"

        set_clock("2026-09-21T00:00:00Z")
        validate_success(api.advance_epoch(ADMIN))
        after = get_success_data(api.get_demand_forecast(
            forecast["id"], make_partner_ops_headers(partner["id"])))
        assert after["tracking_status"] == "COMMITTED", (
            f"the advance auto-commits the forecast, got {after['tracking_status']!r}"
        )


class TestPartnerPriorityClassDerivation:
    """The priority class is re-derived at each epoch from the entitlement ledger."""

    def test_clean_partner_at_two_thousand_entitlement_units_is_tier_one(self):
        """PRD §2.4: "the tier-1 path requires all three of: an `entitlement_units_held`
        of at least 2000, an on-time delivery ratio of at least 0.8, and a
        `qualification_attempt_count` of exactly zero."
        PRD §2.4: "an entitlement holding of exactly 2000 satisfies the bar while 1999
        does not."

        Design: Corner/cross_cutting_complexity_layers/prefix_free_commitment_exposes_the_partner_priority_tier
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"])
        create_and_commit_allocation_hold(product["id"], node["id"], 5, partner["id"])
        stack = create_stack_license(product["id"], license_code="SL-BIG-1",
                                     entitlement_units=2000)
        deployment = create_deployment(
            product["id"],
            partner["id"],
            stack_manifest=[{"license_id": stack["id"], "entitlement_units": 2000}],
            destination_country_code="US")
        deployment = activate_deployment(deployment["id"])
        subscription = create_subscription(deployment["id"], stack_license_id=stack["id"],
                                           seat_count=60, support_tier="ENTERPRISE")
        validate_success(api.activate_subscription(subscription["id"], SUPPORT))

        validate_success(api.advance_epoch(ADMIN))
        data = get_partner(partner["id"])
        assert data["entitlement_units_held"] == 2000
        assert data["allocation_priority_class"] == "TIER_1", (
            f"a clean partner at exactly 2000 entitlement units is TIER_1, "
            f"got {data['allocation_priority_class']!r}"
        )

    def test_a_single_rejection_pins_the_partner_below_tier_one(self):
        """PRD §2.4: "a single prior rejection removes the partner from the tier-1 path
        even when it holds 2000 or more entitlement units".

        Design: Corner/cross_cutting_complexity_layers/prefix_free_commitment_exposes_the_partner_priority_tier
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(qualified=False, blueprint_id=blueprint["id"])
        create_validation(partner["id"], blueprint["id"])
        validate_success(api.reject_partner(partner["id"], PROGRAM))
        evidence = create_validation(partner["id"], blueprint["id"],
                                     validation_minutes=300, test_count=8)
        validate_success(api.accept_validation(evidence["id"], PROGRAM))
        partner = get_success_data(api.qualify_partner(partner["id"], PROGRAM))
        assert partner["qualification_attempt_count"] == 1

        product = create_product()
        node = create_supply_node(product["id"])
        create_and_commit_allocation_hold(product["id"], node["id"], 5, partner["id"])
        stack = create_stack_license(product["id"], license_code="SL-BIG-1",
                                     entitlement_units=2000)
        deployment = create_deployment(
            product["id"],
            partner["id"],
            stack_manifest=[{"license_id": stack["id"], "entitlement_units": 2000}],
            destination_country_code="US")
        deployment = activate_deployment(deployment["id"])
        subscription = create_subscription(deployment["id"], stack_license_id=stack["id"],
                                           seat_count=60, support_tier="ENTERPRISE")
        validate_success(api.activate_subscription(subscription["id"], SUPPORT))

        validate_success(api.advance_epoch(ADMIN))
        data = get_partner(partner["id"])
        assert data["entitlement_units_held"] == 2000
        assert data["allocation_priority_class"] == "TIER_2", (
            f"one recorded rejection keeps the partner out of tier 1, "
            f"got {data['allocation_priority_class']!r}"
        )