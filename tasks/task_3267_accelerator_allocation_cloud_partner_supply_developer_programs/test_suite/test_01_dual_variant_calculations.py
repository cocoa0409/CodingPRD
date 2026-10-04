"""Dual-variant calculations: the forward-looking and chronological fee variants,
and the saturating versus non-saturating value-score variants.

Each test is tagged to its upstream design instance.
"""
from test_helpers import (
    api, validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, make_partner_ops_headers, startup_clock,
    create_certified_blueprint, create_validated_partner, create_product,
    create_supply_node, create_stack_license, create_deployment,
    activate_deployment, create_subscription, activate_subscription,
    create_allocation_hold, create_and_commit_allocation_hold,
    get_partner, get_product, get_supply_node,
    create_allocation_forecast, set_clock, advance_product_lifecycle,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PROGRAM = TEST_USERS["partner_program_manager_headers"]


class TestSubscriptionFeeVariants:
    """The forward-looking provisional fee and the chronological settled fee."""

    def test_activation_bills_every_declared_seat(self):
        """PRD §2.9: "The forward-looking provisional fee, written when a subscription
        reaches `ACTIVE`, charges every declared seat: the annual fee field records
        the per-seat fee for the tier, and the billed fee is the declared `seat_count`
        multiplied by that per-seat fee."

        Design: Difficulty/dual_variant_calc/subscription_fee_forward_looking_vs_chronological
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"])
        # Activation requires the parent SKU to hold a positive allocated unit
        # count (PRD 3.7), so a committed allocation is part of the setup.
        create_and_commit_allocation_hold(product["id"], node["id"], 400, partner["id"])
        stack = create_stack_license(product["id"], entitlement_units=250)
        deployment = create_deployment(
            product["id"],
            partner["id"],
            stack_manifest=[{"license_id": stack["id"], "entitlement_units": 250}],
            destination_country_code="US",
        )
        deployment = activate_deployment(deployment["id"])
        subscription = create_subscription(deployment["id"], stack_license_id=stack["id"],
                                           support_tier="BUSINESS", seat_count=25)

        data = validate_success(api.activate_subscription(subscription["id"],
                                                          TEST_USERS["support_account_manager_headers"]))
        assert data["annual_fee_cents"] == 36000, "BUSINESS per-seat fee is 36000 cents"
        assert data["billed_fee_cents"] == 25 * 36000, (
            f"billed_fee_cents should bill all 25 declared seats at 36000 each, "
            f"got {data['billed_fee_cents']}"
        )

    def test_reclaim_settles_at_the_seat_floor_and_diverges_from_the_provisional(self):
        """PRD §2.9: "The chronological settled fee, written when a subscription is
        reclaimed or expired and on every settle pass, applies both bounds: the
        billable seat count is the declared `seat_count` clamped upward to a minimum
        of 40 and downward to a maximum of 1000, and the settled fee is that billable
        count multiplied by the per-seat fee."
        PRD §2.9: "a 25-seat `BUSINESS` subscription settles at 1440000 cents while its
        provisional figure was 900000 cents."

        Design: Difficulty/dual_variant_calc/subscription_fee_forward_looking_vs_chronological
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"])
        # Activation requires the parent SKU to hold a positive allocated unit
        # count (PRD 3.7), so a committed allocation is part of the setup.
        create_and_commit_allocation_hold(product["id"], node["id"], 400, partner["id"])
        stack = create_stack_license(product["id"], entitlement_units=250)
        deployment = create_deployment(
            product["id"],
            partner["id"],
            stack_manifest=[{"license_id": stack["id"], "entitlement_units": 250}],
            destination_country_code="US",
        )
        deployment = activate_deployment(deployment["id"])
        subscription = create_subscription(deployment["id"], stack_license_id=stack["id"],
                                           support_tier="BUSINESS", seat_count=25)
        support = TEST_USERS["support_account_manager_headers"]
        activated = validate_success(api.activate_subscription(subscription["id"], support))

        data = validate_success(api.reclaim_subscription(subscription["id"], support))
        assert data["annual_fee_cents"] == 36000, (
            "the annual fee field records the per-seat fee for the tier"
        )
        assert data["billed_fee_cents"] == 900000, (
            "the provisional billed fee is the 25 declared seats at 36000 each"
        )
        assert data["settled_fee_cents"] == 1440000, (
            f"settled fee should clamp the 25 declared seats up to the floor of 40, "
            f"got {data['settled_fee_cents']}"
        )
        assert data["settled_fee_cents"] - data["billed_fee_cents"] == 540000, (
            "the two variants diverge by exactly 540000 cents on identical input"
        )
        assert activated["billed_fee_cents"] == 900000


class TestAllocationValueVariants:
    """The estimate variant saturates its time ramp; the confirm variant does not."""

    def test_long_horizon_hold_is_tagged_high_value(self):
        """PRD §3.4: "when the confirm-variant value exceeds the estimate-variant value
        the hold is tagged `HIGH_VALUE`, and otherwise it is tagged `LOW_VALUE`."
        PRD §2.7: "The estimate variant caps the gap at 30 days and caps the quantity
        at 500 units before weighting, so elapsed time beyond 30 days is discarded.
        The confirm variant leaves the gap uncapped and caps only the quantity at 500."

        Design: Difficulty/dual_variant_calc/allocation_value_estimate_vs_confirm_saturating_ramp
        """
        # A LONG-band acknowledgement puts the partner's eligibility deadline 90 days
        # out, so the gap far exceeds the estimate variant's 30-day cap.
        set_clock("2026-08-30T00:00:00Z")
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"])
        create_allocation_forecast(product["id"], partner["id"], requested_quantity_units=1000)
        set_clock("2026-09-01T00:00:00Z")

        hold = create_allocation_hold(product["id"], node["id"], 500, partner["id"])
        assert hold["economic_tag"] == "HIGH_VALUE", (
            f"a hold whose gap exceeds the estimate variant's cap should be tagged "
            f"HIGH_VALUE, got {hold['economic_tag']!r}"
        )

    def test_five_hundred_unit_hold_bears_the_unit_based_marginal_rate(self):
        """PRD §3.2: "which prices each successive block of 100 units one step higher:
        the first block is charged at 1.75 per unit and each subsequent block adds
        0.25 to the per-unit rate, capped at a ceiling of 4.5 per unit. The rate is
        the weighted average of those block prices over the requested quantity,
        rounded half-even to four decimal places".

        Design: Difficulty/dual_variant_calc/allocation_value_estimate_vs_confirm_saturating_ramp
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"])

        hold = create_allocation_hold(product["id"], node["id"], 500, partner["id"])
        # Five 100-unit blocks: 1.75, 2.00, 2.25, 2.50, 2.75 -> weighted average 2.25.
        assert hold["committed_rate_v2"] == 2.25, (
            f"500 units span five marginal bands and average to 2.25 per unit, "
            f"got {hold['committed_rate_v2']}"
        )

    def test_confirm_score_exceeds_the_saturated_estimate_score(self):
        """PRD §2.7: "Each candidate's score is the confirm-variant value of the request,
        minus one half of the estimate-variant value of the same request, minus a penalty
        of 5.0 points for each recorded qualification attempt on the candidate's
        partner."

        Design: Difficulty/dual_variant_calc/allocation_value_estimate_vs_confirm_saturating_ramp
        """
        # An acknowledgement at the very start of September sets a MEDIUM band, so the
        # partner's eligibility deadline sits 45 days out — past the estimate cap.
        set_clock("2026-09-01T00:00:00Z")
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"])
        create_allocation_forecast(product["id"], partner["id"], requested_quantity_units=1000)

        hold = create_allocation_hold(product["id"], node["id"], 500, partner["id"])
        # The two variants disagree, so the confirm-minus-half-of-estimate score is
        # strictly positive and a ranking consumes it as a real separation.
        assert hold["economic_tag"] == "HIGH_VALUE", (
            "the confirm variant's uncapped ramp separates the two scores"
        )

    def test_saturating_estimate_variant_does_not_charge_beyond_the_cap(self):
        """PRD §2.7: "The estimate variant caps the gap at 30 days and caps the quantity
        at 500 units before weighting, so elapsed time beyond 30 days is discarded."

        Design: Difficulty/dual_variant_calc/allocation_value_estimate_vs_confirm_saturating_ramp
        """
        set_clock("2026-09-01T00:00:00Z")
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"])
        create_allocation_forecast(product["id"], partner["id"], requested_quantity_units=1000)

        # The estimate value is capped at W_TIME * 30 + W_UNIT * 500 = 800.0.
        capped = create_allocation_hold(product["id"], node["id"], 500, partner["id"])
        assert capped["quantity_units"] == 500, (
            "the request's quantity participates in both variants"
        )
        assert capped["economic_tag"] == "HIGH_VALUE"