"""Priority-pair validation conflicts: the earlier rule in the fixed ordering
is the one reported when a request violates two rules at once."""

import pytest

from test_helpers import (
    ApiErrorId,
    CUSTOMER_HEADERS,
    LINE_OPERATOR_HEADERS,
    OPS_ADMIN_HEADERS,
    QUALITY_LEAD_HEADERS,
    SHIFT_MANAGER_HEADERS,
    get_success_data,
    validate_error,
    make_line_operator_headers,
    make_quality_lead_headers,
    clock_payload,
    create_restaurant_payload,
    create_assembly_line_payload,
    create_ingredient_payload,
    create_recipe_payload,
    create_hopper_payload,
    load_hopper_payload,
    create_order_payload,
    submit_verification_payload,
    calibration_adjustment_payload,
)


class TestOrderCreateCustomizationBeatsStaleVersion:
    """On order creation, customization validity (priority 17) is evaluated
    before OCC on order creation (priority 22), so an invalid customization
    is reported even when the expected recipe version is also stale."""

    def test_duplicate_customization_wins_over_stale_recipe_version(self, api):
        """PRD §2.9: "Every request is evaluated against the validation rules in
        a fixed priority order, and a request that fails multiple checks reports
        the earliest one."
        PRD §2.9: "17. Customization validity (`ERR_INVALID_CUSTOMIZATION`)."
        PRD §2.9: "22. OCC on order creation (`ERR_STALE_RECIPE_VERSION`)."

        Design: Difficulty/priority_pair_validation_conflict/order_create_state_vs_business_fiscal_conflict
        """
        get_success_data(api.set_clock(clock_payload("2026-09-01T00:00:00Z"), OPS_ADMIN_HEADERS))
        rest = get_success_data(api.create_restaurant(create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        line = get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="L1", line_type="AUTOMATED",
                                         service_rate_seconds_per_bowl=45), OPS_ADMIN_HEADERS))
        get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="LM", line_type="MANUAL",
                                         service_rate_seconds_per_bowl=120), OPS_ADMIN_HEADERS))
        ing = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="ROM", name="Romaine", station_type="BASE",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        recipe = get_success_data(api.create_recipe(
            create_recipe_payload(rest["id"], [{"ingredient_id": ing["id"], "target_grams": 100}],
                                  name="Harvest", base_complexity=0), OPS_ADMIN_HEADERS))
        hopper = get_success_data(api.create_hopper(
            create_hopper_payload(line["id"], ing["id"], capacity_grams=2000, station_slot=0,
                                  calibration_coefficient=1.0), OPS_ADMIN_HEADERS))
        get_success_data(api.load_hopper(hopper["id"], load_hopper_payload(1000, hopper["version"]),
                                         LINE_OPERATOR_HEADERS))
        # Bump the recipe version twice so the captured version is stale.
        get_success_data(api.eighty_six_ingredient(ing["id"], SHIFT_MANAGER_HEADERS))
        get_success_data(api.restore_ingredient(ing["id"], SHIFT_MANAGER_HEADERS))

        response = api.create_order(
            create_order_payload(
                rest["id"], recipe["id"], recipe["version"],
                customizations=[
                    {"ingredient_id": ing["id"], "action": "EXTRA"},
                    {"ingredient_id": ing["id"], "action": "REMOVE"},
                ],
            ),
            CUSTOMER_HEADERS,
        )
        # Customization validity (rule 17) precedes OCC on order creation
        # (rule 22) in the fixed ordering, so the duplicate-customization
        # violation is reported even though the expected version is also stale.
        validate_error(response, ApiErrorId.ERR_INVALID_CUSTOMIZATION)

    def test_fresh_version_with_invalid_customization_reports_customization(self, api):
        """PRD §3.5: "duplicate customization entries for the same ingredient
        are rejected. Any violation is `ERR_INVALID_CUSTOMIZATION` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/order_create_state_vs_business_fiscal_conflict
        """
        get_success_data(api.set_clock(clock_payload("2026-09-01T00:00:00Z"), OPS_ADMIN_HEADERS))
        rest = get_success_data(api.create_restaurant(create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        line = get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="L1", line_type="AUTOMATED",
                                         service_rate_seconds_per_bowl=45), OPS_ADMIN_HEADERS))
        ing = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="ROM", name="Romaine", station_type="BASE",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        recipe = get_success_data(api.create_recipe(
            create_recipe_payload(rest["id"], [{"ingredient_id": ing["id"], "target_grams": 100}],
                                  name="Harvest", base_complexity=0), OPS_ADMIN_HEADERS))
        hopper = get_success_data(api.create_hopper(
            create_hopper_payload(line["id"], ing["id"], capacity_grams=2000, station_slot=0,
                                  calibration_coefficient=1.0), OPS_ADMIN_HEADERS))
        get_success_data(api.load_hopper(hopper["id"], load_hopper_payload(1000, hopper["version"]),
                                         LINE_OPERATOR_HEADERS))
        # Same dual violation but with the CURRENT recipe version: the OCC check
        # passes and the customization violation surfaces.
        response = api.create_order(
            create_order_payload(
                rest["id"], recipe["id"], recipe["version"],
                customizations=[
                    {"ingredient_id": ing["id"], "action": "EXTRA"},
                    {"ingredient_id": ing["id"], "action": "REMOVE"},
                ],
            ),
            CUSTOMER_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_CUSTOMIZATION)


class TestCalibrationStateBeatsSegregation:
    """On calibration approval, the hopper state check precedes the
    segregation-of-duties check."""

    def test_invalid_state_wins_over_segregation_of_duties(self, api):
        """PRD §2.9: "Every request is evaluated against the validation rules in
        a fixed priority order, and a request that fails multiple checks reports
        the earliest one."
        PRD §2.9: "5. The target resource's state permits the requested
        transition (`ERR_INVALID_STATE`)"
        PRD §2.9: "6. Business-safety segregation of duties on calibration
        approval (`ERR_SEGREGATION_OF_DUTIES`)."

        Design: Difficulty/priority_pair_validation_conflict/calibration_state_vs_segregation_conflict
        """
        get_success_data(api.set_clock(clock_payload("2026-09-01T00:00:00Z"), OPS_ADMIN_HEADERS))
        rest = get_success_data(api.create_restaurant(create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        line = get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="L1", line_type="AUTOMATED",
                                         service_rate_seconds_per_bowl=45), OPS_ADMIN_HEADERS))
        ing = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="ROM", name="Romaine", station_type="BASE",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        recipe = get_success_data(api.create_recipe(
            create_recipe_payload(rest["id"], [{"ingredient_id": ing["id"], "target_grams": 100}],
                                  name="Harvest", base_complexity=0), OPS_ADMIN_HEADERS))
        hopper = get_success_data(api.create_hopper(
            create_hopper_payload(line["id"], ing["id"], capacity_grams=2000, station_slot=0,
                                  calibration_coefficient=1.0), OPS_ADMIN_HEADERS))
        get_success_data(api.load_hopper(hopper["id"], load_hopper_payload(1000, hopper["version"]),
                                         LINE_OPERATOR_HEADERS))
        verifier = make_line_operator_headers("op_verifier_1")
        order = get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
        get_success_data(api.start_order_assembly(order["id"], verifier))
        get_success_data(api.submit_order_verification(
            order["id"], submit_verification_payload(
                [{"hopper_id": hopper["id"], "actual_grams": 104.0}]), verifier))

        # The hopper is still IN_SERVICE (one sample cannot quarantine), and the
        # caller IS the recording verifier — both the state check and the
        # segregation check fail; the state check is earlier.
        response = api.create_calibration_adjustment(
            hopper["id"], calibration_adjustment_payload(0.95),
            make_quality_lead_headers("op_verifier_1"),
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)

    def test_segregation_of_duties_fires_when_state_is_valid(self, api):
        """PRD §2.7: "the approver must not be the operator whose finding caused
        it: the `X-User-ID` of the approver must differ from the
        `recorded_by_user_id` of the most recent `PortionVerification` on that
        hopper. A violation is rejected with `ERR_SEGREGATION_OF_DUTIES`
        (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/calibration_state_vs_segregation_conflict
        """
        get_success_data(api.set_clock(clock_payload("2026-09-01T00:00:00Z"), OPS_ADMIN_HEADERS))
        rest = get_success_data(api.create_restaurant(create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        line = get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="L1", line_type="AUTOMATED",
                                         service_rate_seconds_per_bowl=45), OPS_ADMIN_HEADERS))
        get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="LM", line_type="MANUAL",
                                         service_rate_seconds_per_bowl=120), OPS_ADMIN_HEADERS))
        ing = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="ROM", name="Romaine", station_type="BASE",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        recipe = get_success_data(api.create_recipe(
            create_recipe_payload(rest["id"], [{"ingredient_id": ing["id"], "target_grams": 100}],
                                  name="Harvest", base_complexity=0), OPS_ADMIN_HEADERS))
        hopper = get_success_data(api.create_hopper(
            create_hopper_payload(line["id"], ing["id"], capacity_grams=5000, station_slot=0,
                                  calibration_coefficient=1.0), OPS_ADMIN_HEADERS))
        get_success_data(api.load_hopper(hopper["id"], load_hopper_payload(2000, hopper["version"]),
                                         LINE_OPERATOR_HEADERS))
        verifier = make_line_operator_headers("op_verifier_1")
        for _ in range(3):
            order = get_success_data(api.create_order(
                create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
            get_success_data(api.start_order_assembly(order["id"], verifier))
            get_success_data(api.submit_order_verification(
                order["id"], submit_verification_payload(
                    [{"hopper_id": hopper["id"], "actual_grams": 104.0}]), verifier))

        h = get_success_data(api.get_hopper(hopper["id"], QUALITY_LEAD_HEADERS))
        assert h["status"] == "QUARANTINED"
        # State is valid (QUARANTINED); the approver equals the most recent
        # verifier, so the segregation check fires.
        response = api.create_calibration_adjustment(
            hopper["id"], calibration_adjustment_payload(0.95),
            make_quality_lead_headers("op_verifier_1"),
        )
        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
