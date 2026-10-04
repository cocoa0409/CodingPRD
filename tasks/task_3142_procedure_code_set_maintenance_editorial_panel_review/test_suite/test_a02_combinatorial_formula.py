"""Combinatorial formulas: outcomes driven by a nested chain of weights and orders."""
import pytest

from test_helpers import (
    validate_success,
    CHAIR, STAFF, LICENSING,
    api_client, create_society, setup_gpci_code_value, setup_release_cycle_only,
)


class TestPaymentUnitsMagnitudeChain:
    def test_nonfacility_total_combines_three_adjusted_components(self, api):
        """PRD §3.7: "The nonfacility payment multiplies the sum of the adjusted work,
        nonfacility practice-expense and malpractice components by the conversion
        factor and by 100 and rounds that single product half up to a whole cent."

        Design: Difficulty/combinatorial_formula/change_payment_units_tiered_magnitude_chain
        """
        bundle = setup_gpci_code_value(code="00003", society_code="GAM")
        value = validate_success(api.get_code_value(bundle["value"]["id"], LICENSING))
        # adjust: 2.80*1.0521 + 1.90*1.1234 + 0.24*0.6980, then * 34.63 * 100
        assert value["nonfacility_payment_cents"] == 18173

    def test_shortfall_is_nonfacility_total_minus_rounded_component_sum(self, api):
        """PRD §2.9: "dollar_split_shortfall_cents records the difference between the
        nonfacility adjusted total and the sum of the rounded components".
        PRD §3.7: "The shortfall between the two rounded bases is recorded in
        dollar_split_shortfall_cents, computed as the nonfacility adjusted total minus
        the sum of the facility and nonfacility rounded components."

        Design: Difficulty/combinatorial_formula/change_payment_units_tiered_magnitude_chain
        """
        bundle = setup_gpci_code_value(code="00003", society_code="GAM")
        value = validate_success(api.get_code_value(bundle["value"]["id"], LICENSING))
        assert value["nonfacility_payment_cents"] == 18173
        assert value["facility_payment_cents"] == 18173
        assert value["dollar_split_shortfall_cents"] == (
            value["nonfacility_payment_cents"] - value["component_round_total_cents"]
        )


class TestReleaseCyclePoolPinnedOrder:
    def test_capacity_one_ninety_floors_each_pool_before_subtracting(self, api):
        """PRD §2.11: "editorial_reserved_codes is 40 percent of capacity, floored to
        a whole number, set aside for editorial panel discretion."
        PRD §2.11: "additions_pool_codes is 35 percent of capacity floored, capped at
        140 descriptors, and made available to billable additions."
        PRD §2.11: "catiii_pool_codes is 5 percent of capacity floored, capped at 25
        descriptors, and made available to emerging-technology tracking codes."

        Design: Difficulty/combinatorial_formula/release_cycle_pool_pinned_subtraction_order
        """
        bundle = setup_release_cycle_only(capacity=190, year=2028,
                                          meeting_code="JUN2027",
                                          meeting_month="JUNE",
                                          comment_open="2026-01-01T00:00:00Z",
                                          comment_close="2026-03-15T00:00:00Z")
        cycle = validate_success(api.open_release_cycle(bundle["cycle"]["id"], STAFF))
        assert cycle["editorial_reserved_codes"] == 76
        assert cycle["additions_pool_codes"] == 66
        assert cycle["catiii_pool_codes"] == 9

    def test_capacity_one_ninety_residual_is_thirty_nine_after_ordered_subtraction(self, api):
        """PRD §2.11: "discretionary_codes is what remains after subtracting those
        three pools from capacity, in the order just given: editorial reserve first,
        then the additions pool, then the category III pool."
        PRD §3.6: "the remainder after subtracting the three pools in that order".

        Design: Difficulty/combinatorial_formula/release_cycle_pool_pinned_subtraction_order
        """
        bundle = setup_release_cycle_only(capacity=190, year=2028,
                                          meeting_code="JUN2027",
                                          meeting_month="JUNE",
                                          comment_open="2026-01-01T00:00:00Z",
                                          comment_close="2026-03-15T00:00:00Z")
        cycle = validate_success(api.open_release_cycle(bundle["cycle"]["id"], STAFF))
        assert cycle["discretionary_codes"] == (
            cycle["code_set_capacity"]
            - cycle["editorial_reserved_codes"]
            - cycle["additions_pool_codes"]
            - cycle["catiii_pool_codes"]
        )
        assert cycle["discretionary_codes"] == 39


class TestCodeValueNestedRoundingOrder:
    def test_component_variant_rounds_each_product_before_summing(self, api):
        """PRD §2.9: "Under COMPONENT_ROUNDING each adjusted component's dollar product
        is rounded individually and the three rounded figures are then summed."

        Design: Difficulty/combinatorial_formula/code_value_nested_rounding_order_pinned
        """
        bundle = setup_gpci_code_value(code="00004", rounding_variant="COMPONENT_ROUNDING",
                                       society_code="DEL")
        value = validate_success(api.get_code_value(bundle["value"]["id"], LICENSING))
        assert value["component_round_total_cents"] == 18174
        assert value["aggregate_round_total_cents"] == 18173

    def test_pinned_order_publishes_the_component_total_for_a_component_variant(self, api):
        """PRD §2.9: "The facility payment stored on the row is the component-rounded
        total when rounding_variant is COMPONENT_ROUNDING".
        PRD §3.7: "a component-rounded facility payment can sit one cent above the
        aggregate-rounded total."

        Design: Difficulty/combinatorial_formula/code_value_nested_rounding_order_pinned
        """
        bundle = setup_gpci_code_value(code="00004", rounding_variant="COMPONENT_ROUNDING",
                                       society_code="DEL")
        value = validate_success(api.get_code_value(bundle["value"]["id"], LICENSING))
        assert value["facility_payment_cents"] == 18174
        assert value["facility_payment_cents"] - value["aggregate_round_total_cents"] == 1