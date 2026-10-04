"""Corner coverage: calculation variants, constants and input-set filtering."""
from test_helpers import (
    api, validate_success, get_success_data, ApiErrorId,
    TEST_USERS, make_partner_ops_headers, startup_clock, set_clock,
    create_certified_blueprint, create_validated_partner, create_product,
    create_supply_node, create_stack_license, create_deployment,
    activate_deployment, create_and_commit_allocation_hold, create_allocation_hold,
    create_allocation_forecast, create_validation, get_product, get_partner,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SUPPORT = TEST_USERS["support_account_manager_headers"]


class TestExportDensityVariant:
    """The computed density variant rounds the board power up at activation."""

    def test_declared_density_stays_verbatim_before_any_activation(self):
        """PRD §2.5: "During the declared variant, used while a product is being created
        and before any deployment has activated on it, the declared density is the board
        power draw verbatim, and the band is `HIGH` when that figure is at least 1400
        watts and `LOW` otherwise."

        Design: Corner/calculations/export_density_band_flips_at_first_deployment_activation
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product(tdp_watts=1350)
        node = create_supply_node(product["id"])
        create_and_commit_allocation_hold(product["id"], node["id"], 400, partner["id"])
        stack = create_stack_license(product["id"], entitlement_units=250)
        deployment = create_deployment(
            product["id"],
            partner["id"],
            stack_manifest=[{"license_id": stack["id"], "entitlement_units": 250}],
            destination_country_code="US")

        assert get_product(product["id"])["export_performance_density"] == 1350, (
            "the declared variant uses tdp_watts verbatim"
        )
        # Leave the deployment pending: no activation has happened yet.
        assert deployment["activation_state"] == "PENDING"

    def test_computed_density_rounds_up_at_the_first_activation(self):
        """PRD §2.5: "During the computed variant, used at deployment activation, the
        density is the board power draw rounded up to the next whole multiple of 100
        watts".
        PRD §2.5: "the computed variant of the same product yields 1400 watts and flips
        to `HIGH`, recording `export_performance_density` as 1400."

        Design: Corner/calculations/export_density_band_flips_at_first_deployment_activation
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product(tdp_watts=1350)
        node = create_supply_node(product["id"])
        create_and_commit_allocation_hold(product["id"], node["id"], 400, partner["id"])
        stack = create_stack_license(product["id"], entitlement_units=250)
        deployment = create_deployment(
            product["id"],
            partner["id"],
            stack_manifest=[{"license_id": stack["id"], "entitlement_units": 250}],
            destination_country_code="US")

        validate_success(api.activate_deployment(deployment["id"], SUPPORT))
        assert get_product(product["id"])["export_performance_density"] == 1400, (
            f"ceil(1350 / 100) * 100 is 1400, got "
            f"{get_product(product['id'])['export_performance_density']}"
        )


class TestCommittedRateMarginalBands:
    """The unit-based model prices each successive 100-unit band higher."""

    def test_one_hundred_units_is_charged_the_flat_base_rate(self):
        """PRD §3.2: "the first block is charged at 1.75 per unit".
        PRD §3.2: "the time-based model still charges 1.75 for the same quantity."

        Design: Corner/calculations/committed_rate_v2_marginal_bands_price_above_the_first_hundred
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"])

        hold = create_allocation_hold(product["id"], node["id"], 100, partner["id"])
        assert hold["committed_rate_v2"] == 1.75, (
            f"a single 100-unit band is charged 1.75 per unit, got {hold['committed_rate_v2']}"
        )

    def test_two_hundred_fifty_units_averages_above_the_base_rate(self):
        """PRD §3.2: "each subsequent block adds 0.25 to the per-unit rate, capped at a
        ceiling of 4.5 per unit."
        PRD §3.2: "A request for 250 units therefore bears a rate of 1.95 under the
        unit-based model, while the time-based model still charges 1.75 for the same
        quantity."

        Design: Corner/calculations/committed_rate_v2_marginal_bands_price_above_the_first_hundred
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"])

        hold = create_allocation_hold(product["id"], node["id"], 250, partner["id"])
        assert hold["committed_rate_v2"] == 1.95, (
            f"250 units span bands 1.75, 2.00 and 2.25 and average to 1.95, "
            f"got {hold['committed_rate_v2']}"
        )


class TestQualificationAttemptPenalty:
    """Every rejection increments the attempt counter; the penalty caps at four."""

    def test_attempt_counter_reaches_four_then_five(self):
        """PRD §3.2: "The rejection also increments the partner's `qualification_attempt_count`,
        and that counter is preserved across any later re-application."
        PRD §2.4: "the tier-1 path requires all three of: an `entitlement_units_held` of
        at least 2000, an on-time delivery ratio of at least 0.8, and a
        `qualification_attempt_count` of exactly zero."

        Design: Corner/calculations/qualification_attempt_penalty_caps_at_four_rejections
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(qualified=False, blueprint_id=blueprint["id"])
        for _ in range(4):
            create_validation(partner["id"], blueprint["id"])
            rejected = validate_success(api.reject_partner(partner["id"],
                                                           TEST_USERS["partner_program_manager_headers"]))
        assert rejected["qualification_attempt_count"] == 4, (
            f"four rejection rounds record four attempts, "
            f"got {rejected['qualification_attempt_count']}"
        )

        create_validation(partner["id"], blueprint["id"])
        fifth = validate_success(api.reject_partner(
            partner["id"], TEST_USERS["partner_program_manager_headers"]))
        assert fifth["qualification_attempt_count"] == 5, (
            f"a fifth rejection records a fifth attempt, "
            f"got {fifth['qualification_attempt_count']}"
        )

    def test_attempt_counter_survives_a_later_qualification(self):
        """PRD §3.2: "that counter is preserved across any later re-application."
        PRD §2.4: "a single prior rejection removes the partner from the tier-1 path even
        when it holds 2000 or more entitlement units".

        Design: Corner/calculations/qualification_attempt_penalty_caps_at_four_rejections
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(qualified=False, blueprint_id=blueprint["id"])
        create_validation(partner["id"], blueprint["id"])
        validate_success(api.reject_partner(
            partner["id"], TEST_USERS["partner_program_manager_headers"]))

        evidence = create_validation(partner["id"], blueprint["id"],
                                     validation_minutes=300, test_count=8)
        validate_success(api.accept_validation(
            evidence["id"], TEST_USERS["partner_program_manager_headers"]))
        qualified = validate_success(api.qualify_partner(
            partner["id"], TEST_USERS["partner_program_manager_headers"]))
        assert qualified["qualification_attempt_count"] == 1, (
            "the count of prior rejections is preserved through qualification"
        )


class TestForecastForfeitBand:
    """The SHORT band carries the 0.10 rate and a 14-day notice period."""

    def test_short_band_commit_sets_the_short_rate_and_notice(self):
        """PRD §3.5: "the base rate is 0.1 for `SHORT` and 0.25 for both `MEDIUM` and
        `LONG`" and "the `SHORT` band yields exactly 0.10 when the partner's committed
        volume does not exceed the requested ceiling."
        PRD §3.5: "The notice period follows the band: 14 days for `SHORT`, 30 days for
        `MEDIUM`, and 60 days for `LONG`."

        Design: Corner/calculations/forecast_forfeit_rate_uses_the_short_band_rate
        """
        set_clock("2026-09-01T00:00:00Z")
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        # 2026-09-18 is day 18 and sits at or past the 15th and no later than the third
        # Saturday plus one day, so the acknowledgement takes the SHORT band.
        set_clock("2026-09-18T00:00:00Z")
        forecast = create_allocation_forecast(product["id"], partner["id"],
                                              requested_quantity_units=1000,
                                              acknowledge_only=True)
        assert forecast["horizon_band"] == "SHORT", (
            f"an acknowledgement on day 18 takes the SHORT band, got "
            f"{forecast['horizon_band']!r}"
        )

        committed = validate_success(api.commit_demand_forecast(
            forecast["id"], {"committed_quantity_units": 1000},
            make_partner_ops_headers(partner["id"])))
        assert committed["forfeit_rate"] == 0.1, (
            f"the SHORT band yields 0.10 with no overage, got {committed['forfeit_rate']}"
        )
        assert committed["cancellation_notice_days"] == 14, (
            f"the SHORT band carries a 14-day notice, "
            f"got {committed['cancellation_notice_days']}"
        )

    def test_medium_band_acknowledgement_is_only_for_earlier_days(self):
        """PRD §3.5: "If the acknowledgement falls on day 15 or later and no later than
        the day after that boundary, the band is `SHORT` ... Otherwise, if the
        acknowledgement falls no later than seven days after the boundary, the band is
        `MEDIUM`".

        Design: Corner/calculations/forecast_forfeit_rate_uses_the_short_band_rate
        """
        set_clock("2026-09-01T00:00:00Z")
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        forecast = create_allocation_forecast(product["id"], partner["id"],
                                              requested_quantity_units=1000,
                                              acknowledge_only=True)
        assert forecast["horizon_band"] == "MEDIUM", (
            f"a 2026-09-01 acknowledgement takes the MEDIUM band, got "
            f"{forecast['horizon_band']!r}"
        )