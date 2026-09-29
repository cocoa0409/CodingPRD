"""Provisional versus awarded pricing, range shapes, and the contract total."""

from test_helpers import (
    CA_BID_CONFIG,
    SALES,
    TX_BID_CONFIG,
    ApiErrorId,
    api_client,
    assert_bid,
    assert_bid_revision,
    assert_contract_order,
    award_bid,
    bid_revision_payload,
    ca_profile_payload,
    close_solicitation,
    create_bid,
    create_profile,
    create_propulsion_package,
    create_solicitation,
    electric_package_payload,
    set_clock,
    setup_awarded_order,
    setup_ca_catalogue,
    setup_ok_catalogue,
    setup_submitted_bid,
    setup_tx_catalogue,
    submit_bid,
    read_bid,
    validate_error,
    validate_paginated,
    validate_success,
)

# The California offer priced across the six line items: a 12,750,000 cent body,
# a 14,900,000 cent electric package, seven seats beyond the base at 34,500 each,
# both lighting items, heated crossview mirrors and the full safety group.
CA_PROVISIONAL_UNIT_CENTS = 30_913_950
# The same six line items with the preparation fee rounded once on their total.
CA_COLLAPSED_FEE_UNIT_CENTS = 30_913_948
# The award raises the exit count to seven and escalates three whole months.
CA_AWARDED_UNIT_CENTS = 31_401_843


def _ca_twelve_unit_bid(solicitation_code: str, **solicitation_overrides) -> dict:
    """A fully optioned California bid for twelve buses, submitted 2026-08-15."""
    catalogue = setup_ca_catalogue()
    overrides = {
        "solicitation_code": solicitation_code,
        "buyer_type": "COOPERATIVE",
        "buyer_name": "Bay Area Purchasing Cooperative",
        "required_delivery_date": "2026-12-15",
        "price_cap_cents_per_unit": 32_000_000,
    }
    overrides.update(solicitation_overrides)
    return setup_submitted_bid(
        catalogue,
        unit_count=12,
        submit_clock="2026-08-15T00:00:00Z",
        solicitation_overrides=overrides,
        bid_config=CA_BID_CONFIG,
    )


class TestProvisionalVersusAwardedPrice:
    """One offered configuration produces two prices: the bid's own provisional
    figure and the order's awarded figure."""

    def test_award_upgrades_the_exit_count_and_escalates_without_touching_the_bid(self):
        """The award raises every priceable item toward the profile published at
        award time and re-prices the raised configuration, while the bid keeps the
        provisional number it was submitted with.

        PRD: "Each priceable configuration item is raised toward the award-time
        profile and never lowered".
        PRD: "It is never written back onto the bid: a bid keeps its provisional
        figure forever, and only the order carries the awarded one."

        Design: Difficulty/dual_variant_calc/bid_price_provisional_firm_versus_final_award_variant
        """
        scenario = _ca_twelve_unit_bid("SOL-CA-001")
        bid = scenario["bid"]
        first_profile = scenario["profile"]
        assert bid["provisional_unit_price_cents"] == CA_PROVISIONAL_UNIT_CENTS
        assert bid["offered_emergency_exit_count"] == 6
        assert bid["evaluated_spec_profile_id"] == first_profile["id"]

        # California re-legislates: seven emergency exits from now on.
        second_profile = create_profile(ca_profile_payload(min_emergency_exit_count=7))
        close_solicitation(scenario["solicitation"]["id"])
        set_clock("2026-11-20T00:00:00Z")
        order = award_bid(bid["id"], "2026-12-15")
        assert_contract_order(order)

        assert order["awarded_emergency_exit_count"] == 7
        assert order["awarded_seat_capacity"] == 78
        assert order["awarded_mirror_config"] == "CROSSVIEW_HEATED"
        assert order["awarded_rollover_reinforcement"] is True
        # 58.0 kN of body joint strength plus the 9.5 kN reinforcement bonus.
        assert order["awarded_joint_strength_kn"] == 67.5
        assert order["spec_profile_id"] == second_profile["id"]
        assert order["awarded_unit_price_cents"] == CA_AWARDED_UNIT_CENTS

        after = read_bid(bid["id"])
        assert after["provisional_unit_price_cents"] == CA_PROVISIONAL_UNIT_CENTS
        assert after["offered_emergency_exit_count"] == 6
        assert after["evaluated_spec_profile_id"] == first_profile["id"]
        assert after["status"] == "AWARDED"
        reconciliation = (
            order["awarded_unit_price_cents"] - after["provisional_unit_price_cents"]
        )
        assert reconciliation == 487_893

    def test_contract_total_is_built_in_four_stages_over_the_awarded_price(self):
        """The awarded unit price feeds a subtotal, a volume discount, a freight
        tier and an administration fee, in that order.

        PRD: "`total_contract_cents` is built in four stages in a fixed order,
        each stage consuming the previous stage's output."

        Design: Difficulty/dual_variant_calc/bid_price_provisional_firm_versus_final_award_variant
        """
        scenario = _ca_twelve_unit_bid("SOL-CA-010")
        create_profile(ca_profile_payload(min_emergency_exit_count=7))
        close_solicitation(scenario["solicitation"]["id"])
        set_clock("2026-11-20T00:00:00Z")
        order = award_bid(scenario["bid"]["id"], "2026-12-15")

        assert order["unit_count"] == 12
        # 31,401,843 x 12 = 376,822,116 subtotal; a twelve-bus order takes the
        # 2 percent band, a 7,536,442 cent discount, leaving 369,285,674; that is
        # at or above 150,000,000 so freight is 2,950,000; and 1.25 percent of
        # 372,235,674 is a 4,652,946 cent administration fee.
        assert order["total_contract_cents"] == 376_888_620
        assert order["status"] == "ACTIVE"
        assert order["delivery_posture"] == "ON_TRACK"
        assert order["created_unit_count"] == 0
        assert order["delivered_unit_count"] == 0
        assert order["liquidated_damages_cents"] == 0


class TestRangeShapesByPropulsionFamily:
    """The electric and liquid-fuel range formulas have different shapes, and the
    difference decides the compliance verdict."""

    def _two_bids_on_one_solicitation(self) -> dict:
        """One Texas solicitation carrying an electric bid and a diesel bid on the
        same body."""
        catalogue = setup_tx_catalogue()
        model_id = catalogue["model"]["id"]
        electric = create_propulsion_package(electric_package_payload(model_id))
        diesel = catalogue["package"]
        solicitation = create_solicitation(
            catalogue["profile"]["id"],
            solicitation_code="SOL-TX-020",
            unit_count=2,
            required_delivery_date="2026-12-01",
        )
        config = dict(TX_BID_CONFIG)
        config["unit_count"] = 2
        electric_bid = create_bid(
            solicitation["id"], model_id, electric["id"], **config
        )
        diesel_bid = create_bid(solicitation["id"], model_id, diesel["id"], **config)
        return {
            "solicitation": solicitation,
            "electric_bid": electric_bid,
            "diesel_bid": diesel_bid,
        }

    def test_liquid_fuel_range_ignores_the_hvac_load_that_electric_range_folds_in(self):
        """The electric route figure adds the HVAC draw to nameplate consumption;
        the diesel figure never divides its zero HVAC load by the route speed.

        PRD: "For a diesel or propane package the shape is different, and the HVAC
        term plays no part in it at all — a liquid-fuel package carries a zero
        `hvac_load_kw`, and that zero must never be divided by the route speed and
        folded in."

        Design: Difficulty/dual_variant_calc/range_validation_electric_versus_liquid_fuel_variant
        """
        pair = self._two_bids_on_one_solicitation()
        electric = pair["electric_bid"]
        diesel = pair["diesel_bid"]
        assert_bid(electric)
        assert_bid(diesel)

        # 155.0 kWh at 1.05 kWh per mile is 147 whole miles; 122.76 kWh available
        # against an effective 1.425 kWh per mile is 86.1 miles on flat terrain.
        assert electric["nominal_range_mi"] == 147
        assert electric["derated_route_range_mi"] == 86.1
        # 100 gallons at 7.2 mpg is 720 whole miles; 95 usable gallons at 7.2 mpg
        # less a 3 percent cold-weather derate is 663.4 miles.
        assert diesel["nominal_range_mi"] == 720
        assert diesel["derated_route_range_mi"] == 663.4
        # The same body, so the same joint strength either way.
        assert electric["offered_joint_strength_kn"] == 58.0
        assert diesel["offered_joint_strength_kn"] == 58.0

    def test_the_two_families_reach_opposite_verdicts_on_one_route_requirement(self):
        """Against a 400 mile requirement the electric bid is nonconforming on
        route range alone while the diesel bid conforms outright.

        PRD: "`route_range`, satisfied when the derated route range is at least
        the profile's `required_route_range_mi`".
        PRD: "If that recomputed verdict is `NONCONFORMING`, the submission is
        refused with `ERR_SPEC_NONCONFORMING`".

        Design: Difficulty/dual_variant_calc/range_validation_electric_versus_liquid_fuel_variant
        """
        pair = self._two_bids_on_one_solicitation()
        electric = pair["electric_bid"]
        diesel = pair["diesel_bid"]

        assert electric["spec_compliance_status"] == "NONCONFORMING"
        assert electric["unmet_mandatory_items"] == ["route_range"]
        assert electric["exception_count"] == 0
        assert diesel["spec_compliance_status"] == "CONFORMING"
        assert diesel["unmet_mandatory_items"] == []
        assert diesel["exception_count"] == 0

        refused = api_client.submit_bid(electric["id"], SALES)
        validate_error(refused, ApiErrorId.ERR_SPEC_NONCONFORMING.value)
        accepted = submit_bid(diesel["id"])
        assert accepted["status"] == "SUBMITTED"
        assert read_bid(electric["id"])["status"] == "DRAFT"


class TestPreparationFeePerLineItem:
    """The preparation fee is rounded once per line item, never once on the
    line total."""

    def test_per_line_item_rounding_produces_a_different_unit_price(self):
        """A fully optioned bid prices at 30,913,950 cents; collapsing the fee
        onto the summed line items would report 30,913,948.

        PRD: "For each of the six line items in turn, the dealer preparation fee
        is that line item's amount multiplied by 2.375 percent and rounded half up
        to a whole cent; the six rounded fees are then added to the sum of the six
        line items to give the unit price."

        Design: Difficulty/combinatorial_formula/dealer_prep_fee_rounded_per_line_item_not_on_line_total
        """
        catalogue = setup_ca_catalogue()
        solicitation = create_solicitation(
            catalogue["profile"]["id"],
            solicitation_code="SOL-CA-002",
            buyer_type="COOPERATIVE",
            buyer_name="Sacramento Cooperative",
            unit_count=12,
            required_delivery_date="2026-12-15",
            price_cap_cents_per_unit=32_000_000,
        )
        config = dict(CA_BID_CONFIG)
        config["unit_count"] = 12
        bid = create_bid(
            solicitation["id"],
            catalogue["model"]["id"],
            catalogue["package"]["id"],
            **config,
        )

        assert bid["provisional_unit_price_cents"] == CA_PROVISIONAL_UNIT_CENTS
        assert bid["provisional_unit_price_cents"] != CA_COLLAPSED_FEE_UNIT_CENTS
        # The six rounded fees sum to 717,175 over 30,196,775 cents of line items.
        assert bid["provisional_unit_price_cents"] - 30_196_775 == 717_175

    def test_a_zero_line_item_still_carries_a_zero_fee_after_a_revision(self):
        """Stripping the options leaves two line items at zero; they are still
        line items, and the re-priced round comes to 28,615,758 cents.

        PRD: "The line item set is fixed, and a line item that does not apply
        contributes zero and is still a line item — its preparation fee is
        therefore zero rather than skipped."

        Design: Difficulty/combinatorial_formula/dealer_prep_fee_rounded_per_line_item_not_on_line_total
        """
        catalogue = setup_ca_catalogue()
        solicitation = create_solicitation(
            catalogue["profile"]["id"],
            solicitation_code="SOL-CA-012",
            buyer_type="COOPERATIVE",
            buyer_name="Sacramento Cooperative",
            unit_count=12,
            required_delivery_date="2026-12-15",
            price_cap_cents_per_unit=32_000_000,
        )
        config = dict(CA_BID_CONFIG)
        config["unit_count"] = 12
        bid = create_bid(
            solicitation["id"],
            catalogue["model"]["id"],
            catalogue["package"]["id"],
            **config,
        )

        stripped = bid_revision_payload(
            bid["version"],
            offered_seat_capacity=71,
            offered_emergency_exit_count=5,
            offered_mirror_config="CROSSVIEW",
            offered_lap_shoulder_belts=False,
            offered_eight_lamp_system=True,
            offered_crossing_arm=True,
            offered_rollover_reinforcement=False,
            note="Value engineered to the Texas equipment level.",
        )
        revision = validate_success(
            api_client.create_bid_revision(bid["id"], stripped, SALES), 201
        )
        assert_bid_revision(revision)
        assert revision["round_index"] == 1
        # 27,951,900 cents of line items plus 663,858 cents of fees, where the
        # seating and safety items contribute a zero amount and a zero fee.
        assert revision["unit_price_cents"] == 28_615_758

        after = read_bid(bid["id"])
        assert after["revision_round"] == 1
        assert after["provisional_unit_price_cents"] == 28_615_758

        rounds, _ = validate_paginated(api_client.list_bid_revisions(bid["id"], SALES))
        assert [item["round_index"] for item in rounds] == [0, 1]
        assert rounds[0]["unit_price_cents"] == CA_PROVISIONAL_UNIT_CENTS
        assert rounds[0]["is_superseded"] is True
        assert rounds[1]["is_superseded"] is False


class TestFreightTierKeyedOnDiscountedSubtotal:
    """The freight tier is chosen from the discounted subtotal, which moves an
    order sitting near a tier edge into the lower band."""

    def _ok_award(self, solicitation_code: str) -> dict:
        catalogue = setup_ok_catalogue()
        return setup_awarded_order(
            catalogue,
            unit_count=25,
            submit_clock=None,
            award_clock="2026-08-20T00:00:00Z",
            promised_delivery_date="2027-06-30",
            solicitation_overrides={
                "solicitation_code": solicitation_code,
                "buyer_type": "COOPERATIVE",
                "buyer_name": "Oklahoma Regional Cooperative",
                "required_delivery_date": "2027-06-30",
                "price_cap_cents_per_unit": 6_500_000,
            },
            bid_config={
                "offered_seat_capacity": 24,
                "offered_emergency_exit_count": 3,
                "offered_mirror_config": "STANDARD",
                "offered_lap_shoulder_belts": False,
                "offered_eight_lamp_system": False,
                "offered_crossing_arm": False,
                "offered_rollover_reinforcement": False,
            },
        )

    def test_discounted_subtotal_selects_the_middle_freight_tier(self):
        """A 151,003,125 cent subtotal discounts to 145,718,016, which is below
        150,000,000, so freight is 2,100,000 and the total is 149,665,741.

        PRD: "A flat freight fee is then keyed on the **discounted** subtotal:
        1,250,000 cents when the discounted subtotal is below 50,000,000 cents,
        2,100,000 cents when it is below 150,000,000 cents, and 2,950,000 cents
        when it is 150,000,000 cents or more."

        Design: Difficulty/combinatorial_formula/contract_total_freight_tier_keyed_on_discounted_subtotal
        """
        scenario = self._ok_award("SOL-OK-001")
        order = scenario["order"]
        assert_contract_order(order)

        assert order["unit_count"] == 25
        assert order["total_contract_cents"] == 149_665_741
        # Keying freight on the pre-discount subtotal would have charged the top
        # tier and reported 150,526,366 instead.
        assert order["total_contract_cents"] != 150_526_366
        assert order["created_unit_count"] == 0

    def test_a_nineteen_day_wait_escalates_by_zero_whole_months(self):
        """Nineteen days between submission and award is zero elapsed months, so
        the awarded unit price equals the upgraded price unescalated.

        PRD: "the number of whole days between the bid's `submitted_at` date and
        the award date is divided by 30 and any fraction discarded, giving a whole
        number of elapsed months".

        Design: Difficulty/combinatorial_formula/contract_total_freight_tier_keyed_on_discounted_subtotal
        """
        scenario = self._ok_award("SOL-OK-011")
        order = scenario["order"]
        bid = read_bid(scenario["bid"]["id"])

        # 5,800,000 body plus 100,000 propulsion, with 137,750 and 2,375 cents of
        # preparation fee, is 6,040,125 cents before any escalation.
        assert bid["provisional_unit_price_cents"] == 6_040_125
        assert order["awarded_unit_price_cents"] == 6_040_125
        assert order["awarded_seat_capacity"] == 24
        assert order["awarded_emergency_exit_count"] == 3
        assert order["awarded_joint_strength_kn"] == 40.0
        # 40 gallons at 9.0 mpg derates to 331.7 miles against a 300.0 requirement.
        assert bid["derated_route_range_mi"] == 331.7
        assert bid["nominal_range_mi"] == 360
        assert bid["spec_compliance_status"] == "CONFORMING"
