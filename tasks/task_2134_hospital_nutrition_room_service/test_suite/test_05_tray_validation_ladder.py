"""The tray validation ladder: safety battery, envelope ceilings and capacity."""
import pytest
from test_helpers import (
    ApiErrorId,
    PHYSICIAN_1,
    api_client,
    TEST_USERS,
    approx2,
    create_active_diet_order,
    diet_order_version,
    line,
    lock_forecast,
    new_diet_rule,
    new_meal_period,
    new_menu_item,
    new_menu_items,
    new_patient,
    new_procedure_hold,
    new_ward,
    place_tray,
    read_diet_order,
    read_meal_order,
    read_meal_period,
    read_patient,
    read_procedure_hold,
    set_clock,
    setup_tray_scenario,
    validate_error,
    validate_paginated,
    validate_success,
    validate_tray,
)

MANAGER = TEST_USERS["nutrition_manager_headers"]
CLERK = TEST_USERS["diet_clerk_headers"]
PHYSICIAN = TEST_USERS["physician_headers"]
AIDE = TEST_USERS["tray_aide_headers"]


def _allergen_and_capacity_conflict():
    """A one-tray period already at capacity plus a peanut tray for an allergic patient."""
    ward = new_ward()
    rule = new_diet_rule("REGULAR_STD")
    menu = new_menu_items(("SID-RIC", "SID-PNB"))
    patient_a = new_patient(ward["id"], mrn="MRN-A001", full_name="Ada Kern",
                            age_years=71)
    patient_b = new_patient(ward["id"], mrn="MRN-B001", full_name="Ben Oduya",
                            age_years=64, allergen_codes=["PEANUT"])
    order_a = create_active_diet_order(patient_a["id"], rule["id"])
    order_b = create_active_diet_order(patient_b["id"], rule["id"])
    period = new_meal_period(ward["id"], production_capacity_trays=1)
    set_clock("2026-08-02T09:00:00Z")
    tray_a = place_tray(patient_a["id"], period["id"], order_a["id"],
                        [line(menu["SID-RIC"]["id"], 1)], order_a["version"])
    validate_tray(tray_a["id"])
    tray_b = place_tray(patient_b["id"], period["id"], order_b["id"],
                        [line(menu["SID-PNB"]["id"], 1)], order_b["version"])
    return {"ward": ward, "menu": menu, "patient_b": patient_b,
            "period": period, "tray_a": tray_a, "tray_b": tray_b}


def _discontinued_pin_scenario():
    ward = new_ward()
    rule = new_diet_rule("REGULAR_STD")
    rice = new_menu_item("SID-RIC")
    patient = new_patient(ward["id"], mrn="MRN-F001", full_name="Finn Doyle",
                          age_years=55)
    diet_order = create_active_diet_order(patient["id"], rule["id"])
    period = new_meal_period(ward["id"])
    set_clock("2026-08-02T09:00:00Z")
    tray = place_tray(patient["id"], period["id"], diet_order["id"],
                      [line(rice["id"], 1)], diet_order["version"])
    discontinued = validate_success(
        api_client.discontinue_diet_order(diet_order["id"], PHYSICIAN), 200
    )
    return {"ward": ward, "patient": patient, "diet_order": discontinued,
            "period": period, "tray": tray}


class TestSafetyOutranksCapacity:
    def test_allergen_conflict_is_reported_rather_than_tray_capacity(self, api):
        """PRD §2.5: "Second, the four safety checks on a tray — allergen, texture,
        liquid thickness, forbidden tag — are ordered exactly as listed, so a line that
        is simultaneously an allergen conflict and a texture violation reports
        `ERR_ALLERGEN_CONFLICT`, and the nutrient-ceiling check that follows them all
        reports only when no per-line safety defect exists."
        PRD §2.5: "19. **Allergen safety** — else `ERR_ALLERGEN_CONFLICT`."
        PRD §3.6: "Capacity comes last: the period's `committed_tray_count` plus this
        one tray must not exceed `production_capacity_trays`, else
        `ERR_TRAY_CAPACITY_EXCEEDED`; and when the period's `cost_ceiling_cents` is not
        null, its `committed_food_cost_cents` plus this tray's `food_cost_cents` must
        not exceed that ceiling, else `ERR_PERIOD_COST_CEILING_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/allergen_safety_outranks_tray_capacity_fiscal_on_validate
        """
        scenario = _allergen_and_capacity_conflict()

        response = api.validate_meal_order(scenario["tray_b"]["id"], CLERK)
        error = validate_error(response, ApiErrorId.ERR_ALLERGEN_CONFLICT, 422)
        assert error["error_id"] != "ERR_TRAY_CAPACITY_EXCEEDED", (
            "the business-safety check sits above the fiscal capacity check"
        )

    def test_the_rejected_tray_reserves_neither_slot_nor_cents(self, api):
        """PRD §2.5: "Requests are checked in a fixed, globally consistent order, and
        **the first check that fails determines the response**. Later checks are not
        evaluated, which means a request with two independent defects always reports
        the defect that sits higher on the ladder."
        PRD §3.6: "A tray that survives all of that moves `PENDING_VALIDATION →
        VALIDATED`. Its `effective_texture_level` and `effective_liquid_level` are
        refreshed from the pinned order's envelope, its four nutrient totals are
        recomputed, every `line_cost_cents` and the tray's `food_cost_cents` are
        recomputed, and `revalidation_required` is cleared to false."

        Design: Difficulty/priority_pair_validation_conflict/allergen_safety_outranks_tray_capacity_fiscal_on_validate
        """
        scenario = _allergen_and_capacity_conflict()

        response = api.validate_meal_order(scenario["tray_b"]["id"], CLERK)
        assert response.status_code == 422

        tray = read_meal_order(scenario["tray_b"]["id"])
        assert tray["fulfillment_status"] == "PENDING_VALIDATION"

        period = read_meal_period(scenario["period"]["id"])
        assert period["committed_tray_count"] == 1, "only the first tray holds a slot"
        assert period["committed_food_cost_cents"] == 70


class TestPinnedDietOrderState:
    def test_validate_blocked_when_the_pinned_diet_order_is_discontinued(self, api):
        """PRD §3.6: "The tray must be `PENDING_VALIDATION`; its meal period must be
        `PLANNED`, `FORECAST_LOCKED` or `IN_SERVICE`; its patient must be `ADMITTED`;
        the pinned diet order must be `ACTIVE`, else `ERR_DIET_ORDER_NOT_ACTIVE`; and
        the tray's `pinned_diet_order_version` must still equal that diet order's
        current `version`, else `ERR_DIET_ORDER_SUPERSEDED` — the tray has drifted away
        from the envelope it was priced against and must be re-pinned before it can
        pass."
        PRD §2.5: "11. **Pinned diet order active** — the diet order a tray is pinned
        to is `ACTIVE`, else `ERR_DIET_ORDER_NOT_ACTIVE`."
        PRD §2.5: "16. **Envelope drift** — the tray's `pinned_diet_order_version`
        still equals the pinned diet order's current `version`, else
        `ERR_DIET_ORDER_SUPERSEDED`."

        Design: Difficulty/cross_entity_state_dependency/tray_validate_blocked_when_pinned_diet_order_is_discontinued
        """
        scenario = _discontinued_pin_scenario()
        assert scenario["diet_order"]["status"] == "DISCONTINUED"

        response = api.validate_meal_order(scenario["tray"]["id"], CLERK)
        error = validate_error(response, ApiErrorId.ERR_DIET_ORDER_NOT_ACTIVE, 409)
        assert error["error_id"] != "ERR_DIET_ORDER_SUPERSEDED", (
            "the pinned-order-active check sits above the envelope-drift check"
        )

    def test_discontinue_flags_the_open_tray_for_revalidation(self, api):
        """PRD §3.3: "A `Physician` may discontinue an order that is `ACTIVE`, moving
        `ACTIVE → DISCONTINUED`: the patient's `active_diet_order_id` becomes null,
        every meal order pinned to this order whose fulfillment dimension reads
        `PENDING_VALIDATION` or `VALIDATED` has `revalidation_required` set true, and
        the order's `version` increments by 1."

        Design: Difficulty/cross_entity_state_dependency/tray_validate_blocked_when_pinned_diet_order_is_discontinued
        """
        scenario = _discontinued_pin_scenario()

        api.validate_meal_order(scenario["tray"]["id"], CLERK)

        tray = read_meal_order(scenario["tray"]["id"])
        assert tray["fulfillment_status"] == "PENDING_VALIDATION"
        assert tray["revalidation_required"] is True

        assert read_patient(scenario["patient"]["id"])["active_diet_order_id"] is None
        assert read_meal_period(scenario["period"]["id"])["committed_tray_count"] == 0


class TestPerLineSafetyBattery:
    def test_texture_violation_when_the_item_sits_below_the_effective_floor(self, api):
        """PRD §3.6: "Then the per-line safety battery runs in its fixed order —
        allergen conflict, then texture, then thickness, then forbidden tag, then
        menu-item availability — where the texture test asks whether each line's item
        sits at or above the tray's `effective_texture_level` on the texture scale, the
        thickness test asks the same of items that declare a `liquid_level` against
        `effective_liquid_level`, and the tag test asks whether any line's item carries
        a code listed in the pinned order's `forbidden_tag_codes_effective`."
        PRD §3.4: "`effective_texture_level` is the candidate with the **highest**
        position on the texture scale — the most restrictive of them all."

        Design: Corner/validations/texture_violation_rejected_when_item_is_below_effective_texture
        """
        scenario = setup_tray_scenario(
            menu_keys=("SID-RIC",),
            patient_overrides={"mrn": "MRN-AG01", "full_name": "Ida Vance",
                               "age_years": 73, "texture_level": "PUREED"},
        )

        response = api.validate_meal_order(scenario["meal_order"]["id"], CLERK)
        validate_error(response, ApiErrorId.ERR_TEXTURE_LEVEL_VIOLATION, 422)

        order = read_diet_order(scenario["diet_order"]["id"])
        assert order["effective_texture_level"] == "PUREED"
        assert read_meal_order(
            scenario["meal_order"]["id"]
        )["fulfillment_status"] == "PENDING_VALIDATION"
        assert read_meal_period(scenario["period"]["id"])["committed_tray_count"] == 0

    def test_liquid_violation_when_a_thin_item_is_below_the_required_thickness(self, api):
        """PRD §3.6: "Then the per-line safety battery runs in its fixed order —
        allergen conflict, then texture, then thickness, then forbidden tag, then
        menu-item availability — where the texture test asks whether each line's item
        sits at or above the tray's `effective_texture_level` on the texture scale, the
        thickness test asks the same of items that declare a `liquid_level` against
        `effective_liquid_level`, and the tag test asks whether any line's item carries
        a code listed in the pinned order's `forbidden_tag_codes_effective`."
        PRD §3.4: "`effective_liquid_level` is the candidate with the **highest**
        position on the thickness scale."

        Design: Corner/validations/liquid_violation_rejected_when_thin_item_is_below_required_thickness
        """
        scenario = setup_tray_scenario(
            menu_keys=("SOU-BRO",),
            patient_overrides={"mrn": "MRN-AH01", "full_name": "Jed Kraus",
                               "age_years": 69, "liquid_level": "MODERATELY_THICK"},
        )

        response = api.validate_meal_order(scenario["meal_order"]["id"], CLERK)
        validate_error(response, ApiErrorId.ERR_LIQUID_LEVEL_VIOLATION, 422)

        order = read_diet_order(scenario["diet_order"]["id"])
        assert order["effective_liquid_level"] == "MODERATELY_THICK"
        assert order["effective_texture_level"] == "REGULAR", (
            "texture passes, isolating the thickness failure"
        )
        assert read_meal_order(
            scenario["meal_order"]["id"]
        )["fulfillment_status"] == "PENDING_VALIDATION"

    def test_forbidden_tag_rejected_when_the_renal_rule_bans_high_fat(self, api):
        """PRD §3.6: "Then the per-line safety battery runs in its fixed order —
        allergen conflict, then texture, then thickness, then forbidden tag, then
        menu-item availability — where the texture test asks whether each line's item
        sits at or above the tray's `effective_texture_level` on the texture scale, the
        thickness test asks the same of items that declare a `liquid_level` against
        `effective_liquid_level`, and the tag test asks whether any line's item carries
        a code listed in the pinned order's `forbidden_tag_codes_effective`."
        PRD §3.2: "`forbidden_tag_codes` defaults to an empty list and names menu tag
        codes the rule prohibits, such as `HIGH_FAT`."

        Design: Corner/validations/forbidden_tag_rejected_when_renal_rule_bans_high_fat
        """
        scenario = setup_tray_scenario(
            rule_key="RENAL_2G_NA",
            menu_keys=("SID-PNB",),
            patient_overrides={"mrn": "MRN-AI01", "full_name": "Kai Mensah",
                               "age_years": 58},
        )

        response = api.validate_meal_order(scenario["meal_order"]["id"], CLERK)
        validate_error(response, ApiErrorId.ERR_FORBIDDEN_TAG, 422)

        order = read_diet_order(scenario["diet_order"]["id"])
        assert order["forbidden_tag_codes_effective"] == ["HIGH_FAT"]
        assert read_meal_order(scenario["meal_order"]["id"])["total_sodium_mg"] == 90
        assert read_meal_period(scenario["period"]["id"])["committed_tray_count"] == 0

    def test_renal_sodium_ceiling_rejects_the_tray(self, api):
        """PRD §3.6: "Only once every line is individually safe are the totals weighed
        against the envelope: `total_sodium_mg` must not exceed
        `effective_sodium_cap_mg`, `total_potassium_mg` must not exceed
        `effective_potassium_cap_mg`, and `total_carb_g` must not exceed
        `effective_carb_cap_g`, with any cap that is null skipped entirely rather than
        treated as zero. A breach of any of the three is `ERR_NUTRIENT_CAP_EXCEEDED`."
        PRD §3.2: "`max_sodium_mg_per_meal` and `max_potassium_mg_per_meal` are
        per-meal ceilings in whole milligrams; `max_carb_g_per_meal` is a per-meal
        carbohydrate ceiling in grams carried to 1 decimal place."

        Design: Corner/calculations/renal_sodium_ceiling_rejects_tray_with_nutrient_cap_exceeded
        """
        scenario = setup_tray_scenario(
            rule_key="RENAL_2G_NA",
            menu_keys=("SOU-BRO",),
            patient_overrides={"mrn": "MRN-AD01", "full_name": "Fay Oz",
                               "age_years": 68},
        )

        response = api.validate_meal_order(scenario["meal_order"]["id"], CLERK)
        validate_error(response, ApiErrorId.ERR_NUTRIENT_CAP_EXCEEDED, 422)

        order = read_diet_order(scenario["diet_order"]["id"])
        assert order["effective_sodium_cap_mg"] == 700
        tray = read_meal_order(scenario["meal_order"]["id"])
        assert tray["total_sodium_mg"] == 760
        assert tray["fulfillment_status"] == "PENDING_VALIDATION"
        period = read_meal_period(scenario["period"]["id"])
        assert period["committed_tray_count"] == 0
        assert period["committed_food_cost_cents"] == 0

    def test_period_cost_ceiling_blocks_validate_after_capacity_passes(self, api):
        """PRD §3.6: "Capacity comes last: the period's `committed_tray_count` plus
        this one tray must not exceed `production_capacity_trays`, else
        `ERR_TRAY_CAPACITY_EXCEEDED`; and when the period's `cost_ceiling_cents` is not
        null, its `committed_food_cost_cents` plus this tray's `food_cost_cents` must
        not exceed that ceiling, else `ERR_PERIOD_COST_CEILING_EXCEEDED`."
        PRD §3.5: "`cost_ceiling_cents` is optional; when supplied it must be zero or
        greater and caps the period's committed food cost, and when null the period has
        no cost ceiling at all."

        Design: Corner/validations/period_cost_ceiling_blocks_validate_after_capacity_passes
        """
        scenario = setup_tray_scenario(
            menu_keys=("SOU-BRO",),
            patient_overrides={"mrn": "MRN-AJ01", "full_name": "Lia Sorn",
                               "age_years": 51},
            period_overrides={"production_capacity_trays": 20,
                              "cost_ceiling_cents": 100},
        )

        response = api.validate_meal_order(scenario["meal_order"]["id"], CLERK)
        validate_error(response, ApiErrorId.ERR_PERIOD_COST_CEILING_EXCEEDED, 422)

        tray = read_meal_order(scenario["meal_order"]["id"])
        assert tray["food_cost_cents"] == 146
        period = read_meal_period(scenario["period"]["id"])
        assert period["committed_food_cost_cents"] == 0
        assert period["committed_tray_count"] == 0


class TestProductionGate:
    def test_start_production_needs_the_period_in_service(self, api):
        """PRD §3.7: "The `TrayAide` drives the fulfillment dimension forward. Sending
        a validated tray to the tray line moves it `VALIDATED → IN_PRODUCTION` and
        requires two things beyond the tray's own state: the owning meal period must be
        `IN_SERVICE`, and the tray's `revalidation_required` flag must read false."
        PRD §2.5: "10. **Transition legality** — the target row currently sits in one
        of the from-states the requested transition declares, else
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/meal_order_start_production_while_period_only_forecast_locked_returns_invalid_state
        """
        scenario = setup_tray_scenario(
            menu_keys=("SOU-BRO",),
            patient_overrides={"mrn": "MRN-AA01", "full_name": "Ana Ruiz",
                               "age_years": 44},
            forecast_variant="CENSUS_BASED",
            open_for_service=False,
        )
        validate_tray(scenario["meal_order"]["id"])

        response = api.start_production(scenario["meal_order"]["id"], AIDE)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

        tray = read_meal_order(scenario["meal_order"]["id"])
        assert tray["fulfillment_status"] == "VALIDATED"
        assert tray["food_cost_cents"] == 146

        period = read_meal_period(scenario["period"]["id"])
        assert period["status"] == "FORECAST_LOCKED"
        assert period["forecast_tray_count"] == 1
        assert period["forecast_cost_cents"] == 1150
        assert period["forecast_variance_pct"] == approx2(0.00)

    def test_discharge_cascades_tray_cancel_hold_cancel_and_order_discontinue(self, api):
        """PRD §3.1: "At the first level, every meal order for this patient whose
        fulfillment dimension reads `PENDING_VALIDATION`, `VALIDATED`, `IN_PRODUCTION`
        or `PLATED` is moved to `CANCELLED`; trays already `DELIVERED`, `CANCELLED` or
        `MISSED` are untouched."
        PRD §3.1: "Independently of the tray cascade, every procedure hold for this
        patient still in `SCHEDULED` moves to `CANCELLED`, and the patient's `ACTIVE`
        diet order, if one exists, moves to `DISCONTINUED` with `active_diet_order_id`
        becoming null."
        PRD §3.1: "At the second level, because each of those trays left a committed
        state, its meal period recomputes its committed tray count and committed cents
        and then re-runs the period cost rollup of §3.5 across its overhead, discount
        and total components."

        Design: Corner/state_machines/patient_discharge_cascades_open_tray_cancel_and_diet_order_discontinue
        """
        scenario = setup_tray_scenario(
            menu_keys=("SOU-BRO",),
            patient_overrides={"mrn": "MRN-X001", "full_name": "Xan Prior",
                               "age_years": 78, "texture_level": "PUREED"},
            place_order=False,
            clock=None,
        )
        hold = new_procedure_hold(
            scenario["patient"]["id"],
            procedure_code="MRI-07",
            hold_start_at="2026-08-03T08:00:00Z",
            hold_end_at="2026-08-03T10:00:00Z",
        )
        set_clock("2026-08-02T09:00:00Z")
        tray = place_tray(
            scenario["patient"]["id"], scenario["period"]["id"],
            scenario["diet_order"]["id"],
            [line(scenario["menu"]["SOU-BRO"]["id"], 1)],
        )
        validate_tray(tray["id"])

        discharged = validate_success(
            api.discharge_patient(scenario["patient"]["id"], CLERK), 200
        )
        assert discharged["status"] == "DISCHARGED"
        assert discharged["active_diet_order_id"] is None
        assert discharged["missed_meal_count"] == 0, (
            "a discharge cancels trays, it does not miss them"
        )

        tray_after = read_meal_order(tray["id"])
        assert tray_after["fulfillment_status"] == "CANCELLED"
        assert tray_after["missed_reason"] is None

        assert read_diet_order(
            scenario["diet_order"]["id"]
        )["status"] == "DISCONTINUED"
        assert read_procedure_hold(hold["id"])["status"] == "CANCELLED"

        period = read_meal_period(scenario["period"]["id"])
        assert period["committed_tray_count"] == 0
        assert period["committed_food_cost_cents"] == 0
        assert period["period_total_cost_cents"] == 0
        assert validate_success(
            api.get_ward(scenario["ward"]["id"], MANAGER)
        )["active_patient_census"] == 0
