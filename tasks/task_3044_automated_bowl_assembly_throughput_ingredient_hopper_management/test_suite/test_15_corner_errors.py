"""Corner — errors: physical-bounds sensor rejection, double eighty-six,
substitution overlap geometry, and the availability-gate satisfaction pass."""

from test_helpers import (
    ApiErrorId,
    CUSTOMER_HEADERS,
    LINE_OPERATOR_HEADERS,
    OPS_ADMIN_HEADERS,
    SHIFT_MANAGER_HEADERS,
    get_success_data,
    validate_error,
    validate_success,
    clock_payload,
    create_restaurant_payload,
    create_assembly_line_payload,
    create_ingredient_payload,
    create_recipe_payload,
    create_hopper_payload,
    load_hopper_payload,
    create_order_payload,
    sensor_reading_payload,
    create_substitution_rule_payload,
)


class TestSensorReadingOutOfRange:
    def test_reading_above_capacity_rejected(self, api):
        """PRD §3.4: "A `LineOperator` reports a reading by submitting
        `grams_reading`; the value must lie between 0 and the hopper's
        `capacity_grams` inclusive, or the report is rejected with
        `ERR_SENSOR_READING_OUT_OF_RANGE`."

        Design: Corner/errors/error_sensor_reading_above_capacity
        """
        rest = get_success_data(api.create_restaurant(
            create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        line = get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="L1", line_type="AUTOMATED"), OPS_ADMIN_HEADERS))
        ing = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="ROM", name="Romaine", station_type="BASE",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        hopper = get_success_data(api.create_hopper(
            create_hopper_payload(line["id"], ing["id"], capacity_grams=500, station_slot=0,
                                  calibration_coefficient=1.0), OPS_ADMIN_HEADERS))
        get_success_data(api.load_hopper(hopper["id"], load_hopper_payload(300, hopper["version"]),
                                         LINE_OPERATOR_HEADERS))
        response = api.report_sensor_reading(hopper["id"], sensor_reading_payload(501),
                                             LINE_OPERATOR_HEADERS)
        validate_error(response, ApiErrorId.ERR_SENSOR_READING_OUT_OF_RANGE)
        h = get_success_data(api.get_hopper(hopper["id"], LINE_OPERATOR_HEADERS))
        assert h["current_grams"] == 300


class TestDoubleEightySix:
    def test_eighty_six_of_eighty_sixed_rejected(self, api):
        """PRD §3.2: "Eighty-sixing an already `EIGHTY_SIXED` ingredient is
        rejected with `ERR_ALREADY_EIGHTY_SIXED` (HTTP 409)."

        Design: Corner/errors/error_double_eighty_six
        """
        ing = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="ROM", name="Romaine", station_type="BASE",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        get_success_data(api.eighty_six_ingredient(ing["id"], SHIFT_MANAGER_HEADERS))
        response = api.eighty_six_ingredient(ing["id"], SHIFT_MANAGER_HEADERS)
        validate_error(response, ApiErrorId.ERR_ALREADY_EIGHTY_SIXED)


class TestSubstitutionOverlap:
    def test_overlapping_same_from_ingredient_rejected_different_allowed(self, api):
        """PRD §3.2: "Activation — `PENDING → ACTIVE` — requires the
        `to_ingredient` to be `ACTIVE` and requires that no other `ACTIVE` rule
        for the same restaurant and the same `from_ingredient_id` have an
        overlapping window; two rules for different from-ingredients may overlap
        freely."

        Design: Corner/errors/error_substitution_overlap_same_from_ingredient
        """
        get_success_data(api.set_clock(clock_payload("2026-09-01T00:00:00Z"), OPS_ADMIN_HEADERS))
        rest = get_success_data(api.create_restaurant(
            create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        ing_a = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="A1", name="A", station_type="BASE",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        ing_b = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="B1", name="B", station_type="BASE",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        ing_c = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="C1", name="C", station_type="BASE",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        # Propose both rules before either is ACTIVE: the same-from-ingredient
        # overlap constraint is stated against ACTIVE rules, so an overlapping
        # proposal is only rejected at activation time.
        rule1 = get_success_data(api.create_substitution_rule(
            create_substitution_rule_payload(rest["id"], ing_a["id"], ing_b["id"],
                                             "2026-09-01T00:00:00Z", "2026-09-01T12:00:00Z"),
            OPS_ADMIN_HEADERS))
        rule2 = get_success_data(api.create_substitution_rule(
            create_substitution_rule_payload(rest["id"], ing_a["id"], ing_c["id"],
                                             "2026-09-01T06:00:00Z", "2026-09-01T18:00:00Z"),
            OPS_ADMIN_HEADERS))
        get_success_data(api.activate_substitution_rule(rule1["id"], SHIFT_MANAGER_HEADERS))

        response = api.activate_substitution_rule(rule2["id"], SHIFT_MANAGER_HEADERS)
        validate_error(response, ApiErrorId.ERR_SUBSTITUTION_CONFLICT)

        rule3 = get_success_data(api.create_substitution_rule(
            create_substitution_rule_payload(rest["id"], ing_b["id"], ing_c["id"],
                                             "2026-09-01T06:00:00Z", "2026-09-01T18:00:00Z"),
            OPS_ADMIN_HEADERS))
        activated = validate_success(
            api.activate_substitution_rule(rule3["id"], SHIFT_MANAGER_HEADERS))
        assert activated["status"] == "ACTIVE"


class TestEightySixCoveredBySubstitution:
    def test_order_accepted_when_covering_rule_active(self, api):
        """PRD §3.2: "a recipe's `is_available` is true if and only if every
        `portion_spec` entry resolves — either the named ingredient is `ACTIVE`,
        or an `ACTIVE` `SubstitutionRule` at the same restaurant covers it"

        Design: Corner/errors/error_eighty_six_covered_by_substitution_order_still_accepted
        """
        get_success_data(api.set_clock(clock_payload("2026-09-01T00:00:00Z"), OPS_ADMIN_HEADERS))
        rest = get_success_data(api.create_restaurant(
            create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        line = get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="LA", line_type="AUTOMATED"), OPS_ADMIN_HEADERS))
        ing_a = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="A1", name="A", station_type="BASE",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        ing_b = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="B1", name="B", station_type="BASE",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        recipe = get_success_data(api.create_recipe(
            create_recipe_payload(rest["id"], [{"ingredient_id": ing_a["id"], "target_grams": 100}],
                                  name="Harvest", base_complexity=0), OPS_ADMIN_HEADERS))
        hopper_b = get_success_data(api.create_hopper(
            create_hopper_payload(line["id"], ing_b["id"], capacity_grams=2000, station_slot=0,
                                  calibration_coefficient=1.0), OPS_ADMIN_HEADERS))
        get_success_data(api.load_hopper(hopper_b["id"], load_hopper_payload(1000, hopper_b["version"]),
                                         LINE_OPERATOR_HEADERS))
        rule = get_success_data(api.create_substitution_rule(
            create_substitution_rule_payload(rest["id"], ing_a["id"], ing_b["id"],
                                             "2026-09-01T00:00:00Z", "2026-09-01T23:59:00Z"),
            OPS_ADMIN_HEADERS))
        get_success_data(api.activate_substitution_rule(rule["id"], SHIFT_MANAGER_HEADERS))
        get_success_data(api.eighty_six_ingredient(ing_a["id"], SHIFT_MANAGER_HEADERS))
        fresh = get_success_data(api.get_recipe(recipe["id"], CUSTOMER_HEADERS))
        assert fresh["is_available"] is True

        order = validate_success(api.create_order(
            create_order_payload(rest["id"], recipe["id"], fresh["version"]), CUSTOMER_HEADERS), 201)
        assert order["route"] == "AUTOMATED"
        assert order["assigned_line_id"] == line["id"]
