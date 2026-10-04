"""Corner — entities: creation defaults, computed fields, append-only shape,
pagination, and type constraints."""

import pytest

from test_helpers import (
    ApiErrorId,
    LINE_OPERATOR_HEADERS,
    OPS_ADMIN_HEADERS,
    PREP_COOK_HEADERS,
    QUALITY_LEAD_HEADERS,
    CUSTOMER_HEADERS,
    get_success_data,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
    clock_payload,
    create_restaurant_payload,
    create_assembly_line_payload,
    create_ingredient_payload,
    create_recipe_payload,
    create_hopper_payload,
    load_hopper_payload,
    create_order_payload,
    submit_verification_payload,
)
from prd_bench_local_runner.testing import NON_EXISTENT_UUID


class TestRestaurantCreation:
    def test_creation_returns_201_and_system_fields(self, api):
        """PRD §4: "Operations that create a new resource return `201 Created`"
        PRD §2.4: "All primary resources — `Restaurant`, `AssemblyLine`,
        `Ingredient`, `Recipe`, `Hopper`, `RefillTask`, `PrepBatch`, `Order`,
        `SubstitutionRule`, `SanitationCycle`, and `LaborAssignment` — carry a
        standard set of system-managed fields"

        Design: Corner/entities/restaurant_creation_returns_201_and_system_fields
        """
        response = api.create_restaurant(
            create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS)
        data = validate_success(response, 201)
        assert is_valid_uuid(data["id"])
        assert data["name"] == "R1"
        assert data["city"] == "LA"
        assert data["version"] == 1
        assert isinstance(data["created_at"], str)
        assert isinstance(data["updated_at"], str)

    def test_get_unknown_restaurant_returns_404(self, api):
        """PRD §2.9: "Path-templated resources exist, validated left-to-right
        along the path — restaurant, then line, then hopper, task, cycle, order,
        recipe, rule, or batch as applicable (`ERR_NOT_FOUND`)."

        Design: Corner/entities/restaurant_get_not_found_returns_404
        """
        response = api.get_restaurant(NON_EXISTENT_UUID, OPS_ADMIN_HEADERS)
        validate_error(response, ApiErrorId.ERR_NOT_FOUND)


class TestHopperDefaults:
    def test_default_calibration_and_null_drift(self, api):
        """PRD §3.1: "Each hopper carries a `calibration_coefficient` — a
        dispense multiplier that defaults to 1.0"
        PRD §2.7: "If fewer than 3 such samples exist, `drift_pct` is null —
        the system refuses to judge drift on insufficient data."

        Design: Corner/entities/hopper_default_calibration_and_computed_drift_null
        """
        rest = get_success_data(api.create_restaurant(
            create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        line = get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="L1", line_type="AUTOMATED"),
            OPS_ADMIN_HEADERS))
        ing = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="ROM", name="Romaine", station_type="BASE",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        # calibration_coefficient omitted; drift_pct supplied-but-ignored.
        payload = {"line_id": line["id"], "ingredient_id": ing["id"],
                   "capacity_grams": 500, "station_slot": 0, "drift_pct": 9.99}
        hopper = validate_success(api.create_hopper(payload, OPS_ADMIN_HEADERS), 201)
        assert hopper["calibration_coefficient"] == pytest.approx(1.0, abs=1e-9)
        assert hopper["drift_pct"] is None
        assert hopper["status"] == "LOADING"


class TestAssemblyLineServiceRateDefaults:
    def test_default_service_rate_by_line_type(self, api):
        """PRD §3.1: "The service rate defaults to 45 seconds for an `AUTOMATED`
        line and 120 seconds for a `MANUAL` line, and must always be greater
        than zero."

        Design: Corner/entities/assembly_line_default_service_rate_by_type
        """
        rest = get_success_data(api.create_restaurant(
            create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        automated = validate_success(api.create_assembly_line(
            {"restaurant_id": rest["id"], "name": "LA", "line_type": "AUTOMATED"},
            OPS_ADMIN_HEADERS), 201)
        manual = validate_success(api.create_assembly_line(
            {"restaurant_id": rest["id"], "name": "LM", "line_type": "MANUAL"},
            OPS_ADMIN_HEADERS), 201)
        assert automated["service_rate_seconds_per_bowl"] == 45
        assert manual["service_rate_seconds_per_bowl"] == 120


class TestRecipeAvailabilityComputed:
    def test_client_supplied_is_available_ignored(self, api):
        """PRD §3.2: "`is_available` is recomputed on every read and again
        whenever an eighty-six, restore, or substitution transition lands;
        client input for it is ignored."

        Design: Corner/entities/recipe_is_available_computed_input_ignored
        """
        rest = get_success_data(api.create_restaurant(
            create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        ing = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="ROM", name="Romaine", station_type="BASE",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        payload = create_recipe_payload(
            rest["id"], [{"ingredient_id": ing["id"], "target_grams": 100}],
            name="Harvest", base_complexity=0)
        payload["is_available"] = False
        recipe = validate_success(api.create_recipe(payload, OPS_ADMIN_HEADERS), 201)
        assert recipe["is_available"] is True


class TestPortionVerificationAppendOnly:
    def test_verification_carries_no_version_or_updated_at(self, api):
        """PRD §2.4: "Two resource types are append-only records and carry only
        `id` and `created_at` — both `updated_at` and `version` are absent on
        them: `PortionVerification` (a scale measurement is a fact, never
        edited) and `CalibrationAdjustment` (an approval record is immutable
        once written)."

        Design: Corner/entities/portion_verification_immutable_no_version_field
        """
        rest = get_success_data(api.create_restaurant(
            create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        line = get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="L1", line_type="AUTOMATED"),
            OPS_ADMIN_HEADERS))
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
        order = get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
        get_success_data(api.start_order_assembly(order["id"], LINE_OPERATOR_HEADERS))
        get_success_data(api.submit_order_verification(
            order["id"], submit_verification_payload(
                [{"hopper_id": hopper["id"], "actual_grams": 100.0}]), LINE_OPERATOR_HEADERS))
        rows = get_success_data(
            api.list_order_portion_verifications(order["id"], QUALITY_LEAD_HEADERS))
        assert len(rows) == 1
        pv = rows[0]
        assert is_valid_uuid(pv["id"])
        assert isinstance(pv["created_at"], str)
        assert "version" not in pv
        assert "updated_at" not in pv
        assert pv["result"] == "PASS"
        assert pv["variance_pct"] == pytest.approx(0.00, abs=0.01)


class TestIngredientListingPagination:
    def test_ingredients_pagination_envelope(self, api):
        """PRD §2.3: "`limit` caps the number of items returned; it defaults to
        10 when omitted, with a minimum accepted value of 1 and a maximum of
        100. `offset` specifies how many items to skip and defaults to 0. Every
        list response includes `limit`, `offset`, `total_count`, and `has_more`
        in the `meta` object of the envelope."

        Design: Corner/entities/ingredients_list_pagination_envelope
        """
        get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="A1", name="IngA", station_type="BASE",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="B1", name="IngB", station_type="PROTEIN",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        response = api.list_ingredients(PREP_COOK_HEADERS, params={"limit": 1})
        body = response.json()
        assert body["response_type"] == "array"
        data, meta = validate_paginated(response)
        assert len(data) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert meta["limit"] == 1


class TestIngredientSkuUniqueness:
    def test_duplicate_sku_rejected(self, api):
        """PRD §3.1: "Each `Ingredient` is created with a globally unique `sku`
        (a duplicate `sku` is rejected with `ERR_VALIDATION`)"

        Design: Corner/entities/ingredient_sku_uniqueness_rejected
        """
        get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="ROM", name="Romaine", station_type="BASE",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        response = api.create_ingredient(
            create_ingredient_payload(sku="ROM", name="Romaine2", station_type="TOPPING",
                                      shelf_life_minutes=120), OPS_ADMIN_HEADERS)
        validate_error(response, ApiErrorId.ERR_VALIDATION)


class TestHopperStationSlotGeometry:
    def test_slot_must_match_ingredient_station_type(self, api):
        """PRD §2.11: "the slot map is constant: slot 0 holds a `BASE`
        ingredient, slot 1 a `PROTEIN`, slots 2 through 5 hold `TOPPING`
        ingredients, and slot 6 holds a `DRESSING`. Mounting a hopper whose
        ingredient's `station_type` disagrees with its `station_slot` is
        rejected with `ERR_INGREDIENT_STATION_MISMATCH` (HTTP 422)."

        Design: Corner/entities/hopper_station_slot_must_match_station_type
        """
        rest = get_success_data(api.create_restaurant(
            create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        line = get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="L1", line_type="AUTOMATED"),
            OPS_ADMIN_HEADERS))
        dressing = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="DRS", name="Dressing", station_type="DRESSING",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        bad = api.create_hopper(
            {"line_id": line["id"], "ingredient_id": dressing["id"],
             "capacity_grams": 500, "station_slot": 0}, OPS_ADMIN_HEADERS)
        validate_error(bad, ApiErrorId.ERR_INGREDIENT_STATION_MISMATCH)
        good = validate_success(api.create_hopper(
            {"line_id": line["id"], "ingredient_id": dressing["id"],
             "capacity_grams": 500, "station_slot": 6}, OPS_ADMIN_HEADERS), 201)
        assert good["station_slot"] == 6
