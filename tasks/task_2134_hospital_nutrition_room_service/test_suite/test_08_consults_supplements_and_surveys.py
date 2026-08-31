"""Nutrition consults, malnutrition scoring, supplement ledgers and bedside surveys."""
import pytest
from test_helpers import (
    ApiErrorId,
    DIETITIAN_1,
    NON_EXISTENT_UUID,
    TEST_USERS,
    TRAY_AIDE_1,
    TRAY_AIDE_2,
    activate_supplement_order,
    approx1,
    approx2,
    assert_consult,
    assert_risk_tier_matches_score,
    assert_satisfaction_survey,
    assert_supplement_order,
    assign_consult,
    create_active_diet_order,
    create_supplement_order_payload,
    create_survey_payload,
    deliver_tray,
    line,
    lock_and_open,
    new_consult,
    new_diet_rule,
    new_dinner_period,
    new_meal_period,
    new_menu_item,
    new_patient,
    new_supplement_order,
    new_ward,
    pass_accuracy_check,
    pass_temperature_check,
    place_tray,
    plate_tray,
    read_consult,
    read_patient,
    read_supplement_order,
    set_clock,
    setup_assessed_consult,
    setup_delivered_tray,
    setup_signed_consult,
    setup_temp_passed_tray,
    sign_consult,
    validate_error,
    validate_paginated,
    validate_success,
    validate_tray,
)

MANAGER = TEST_USERS["nutrition_manager_headers"]
CLERK = TEST_USERS["diet_clerk_headers"]
PHYSICIAN = TEST_USERS["physician_headers"]
DIETITIAN = TEST_USERS["dietitian_headers"]
AIDE_1 = TEST_USERS["tray_aide_headers"]

IDENTICAL_ANTHROPOMETRICS = {
    "weight_loss_pct": 16.0,
    "intake_pct": 40.0,
    "bmi": 23.0,
}


def _two_assigned_consults():
    ward = new_ward()
    patient = new_patient(ward["id"], mrn="MRN-1001", full_name="Ada Kern",
                          age_years=71)
    first = new_consult(patient["id"], PHYSICIAN, reason_code="WEIGHT_LOSS",
                        acuity="ROUTINE")
    assign_consult(first["id"], DIETITIAN_1)
    second = new_consult(patient["id"], PHYSICIAN, reason_code="WEIGHT_LOSS_RECHECK",
                         acuity="ROUTINE")
    assign_consult(second["id"], DIETITIAN_1)
    return {"ward": ward, "patient": patient, "first": first, "second": second}


def _two_delivered_trays_for_one_patient():
    ward = new_ward()
    rule = new_diet_rule("REGULAR_STD")
    broth = new_menu_item("SOU-BRO")
    patient = new_patient(ward["id"], mrn="MRN-AE01", full_name="Gil Marsh",
                          age_years=59)
    diet_order = create_active_diet_order(patient["id"], rule["id"])
    lunch = new_meal_period(ward["id"])
    lock_and_open(lunch["id"])
    dinner = new_dinner_period(ward["id"])
    lock_and_open(dinner["id"])
    set_clock("2026-08-02T09:00:00Z")
    # Placing a tray bumps the pinned diet order's version (PRD 3.6), so each tray
    # must be validated while its pinned_diet_order_version still equals the
    # order's current version -- before the next tray is placed.
    lunch_tray = place_tray(patient["id"], lunch["id"], diet_order["id"],
                            [line(broth["id"], 1)], diet_order["version"])
    validate_tray(lunch_tray["id"])
    dinner_tray = place_tray(patient["id"], dinner["id"], diet_order["id"],
                             [line(broth["id"], 1)])
    validate_tray(dinner_tray["id"])
    for tray in (lunch_tray, dinner_tray):
        plate_tray(tray["id"], TRAY_AIDE_1)
        pass_accuracy_check(tray["id"], 1, TRAY_AIDE_1)
        pass_temperature_check(tray["id"], 64.0, None, TRAY_AIDE_2)
    set_clock("2026-08-02T11:00:00Z")
    deliver_tray(lunch_tray["id"], TRAY_AIDE_1)
    set_clock("2026-08-02T19:00:00Z")
    deliver_tray(dinner_tray["id"], TRAY_AIDE_1)
    return {"ward": ward, "patient": patient,
            "lunch_tray": lunch_tray, "dinner_tray": dinner_tray}


class TestMalnutritionScoringVariants:
    def test_screening_variant_scores_identical_inputs_into_the_high_tier(self, api):
        """PRD §3.9: "**Weight loss** contributes 0 points when `weight_loss_pct` is
        below 5, 40 points when it is at least 5 but below 10, 70 points when it is at
        least 10 but below 15, and 100 points at 15 or above."
        PRD §3.9: "The `SCREENING` variant is a three-factor bedside screen: it takes
        0.50 of the weight-loss points plus 0.30 of the intake points plus 0.20 of the
        body-mass-index points, and rounds the sum half up to 2 decimal places; albumin
        is excluded altogether, so a patient with heavy weight loss but normal labs
        scores materially **higher** here."
        PRD §3.9: "`risk_tier` follows directly from the score: `LOW` when
        `malnutrition_risk_score` is below 30, `MODERATE` when it is at least 30 but
        below 60, and `HIGH` at 60 or above. Both fields read null before an assessment
        has been recorded."

        Design: Difficulty/dual_variant_calc/malnutrition_score_diverges_by_assessment_variant
        """
        scenario = _two_assigned_consults()

        assessed = validate_success(
            api.assess_consult(
                scenario["first"]["id"],
                dict(assessment_variant="SCREENING", **IDENTICAL_ANTHROPOMETRICS),
                DIETITIAN,
            ),
            200,
        )
        assert_consult(assessed)

        # 0.50 * 100 + 0.30 * 70 + 0.20 * 0 == 71.00
        assert assessed["malnutrition_risk_score"] == approx2(71.00)
        assert assessed["risk_tier"] == "HIGH"
        assert assessed["albumin_g_dl"] is None, "SCREENING ignores albumin entirely"
        assert_risk_tier_matches_score(assessed)

    def test_comprehensive_variant_dilutes_the_weight_loss_term_into_a_lower_tier(self, api):
        """PRD §3.9: "**Albumin** contributes 0 points when `albumin_g_dl` is 3.5 or
        above, 40 points when it is at least 3.0 but below 3.5, 70 points when it is at
        least 2.5 but below 3.0, and 100 points below 2.5."
        PRD §3.9: "The `COMPREHENSIVE` variant is a four-factor assessment: it takes
        0.35 of the weight-loss points plus 0.25 of the intake points plus 0.20 of the
        body-mass-index points plus 0.20 of the albumin points, again rounded half up to
        2 decimal places; adding albumin at a weight of 0.20 dilutes the weight-loss
        term from 0.50 down to 0.35, so identical anthropometrics accompanied by a
        normal albumin land in a **lower** tier than `SCREENING` would report."
        PRD §3.9: "`risk_tier` follows directly from the score: `LOW` when
        `malnutrition_risk_score` is below 30, `MODERATE` when it is at least 30 but
        below 60, and `HIGH` at 60 or above. Both fields read null before an assessment
        has been recorded."

        Design: Difficulty/dual_variant_calc/malnutrition_score_diverges_by_assessment_variant
        """
        scenario = _two_assigned_consults()

        screening = validate_success(
            api.assess_consult(
                scenario["first"]["id"],
                dict(assessment_variant="SCREENING", **IDENTICAL_ANTHROPOMETRICS),
                DIETITIAN,
            ),
            200,
        )
        comprehensive = validate_success(
            api.assess_consult(
                scenario["second"]["id"],
                dict(assessment_variant="COMPREHENSIVE", albumin_g_dl=3.6,
                     **IDENTICAL_ANTHROPOMETRICS),
                DIETITIAN,
            ),
            200,
        )

        # 0.35 * 100 + 0.25 * 70 + 0.20 * 0 + 0.20 * 0 == 52.50
        assert comprehensive["malnutrition_risk_score"] == approx2(52.50)
        assert comprehensive["risk_tier"] == "MODERATE"
        assert comprehensive["albumin_g_dl"] == approx1(3.6)
        assert (
            comprehensive["malnutrition_risk_score"]
            != screening["malnutrition_risk_score"]
        ), "the two variants must disagree on identical anthropometrics"
        assert_risk_tier_matches_score(comprehensive)

    def test_comprehensive_assessment_without_albumin_returns_albumin_required(self, api):
        """PRD §3.9: "`albumin_g_dl`, serum albumin in grams per decilitre, is optional
        in general but **mandatory when `assessment_variant` is `COMPREHENSIVE`** —
        omitting it there is `ERR_ALBUMIN_REQUIRED` — and is ignored entirely by
        `SCREENING`."
        PRD §3.9: "`risk_tier` follows directly from the score: `LOW` when
        `malnutrition_risk_score` is below 30, `MODERATE` when it is at least 30 but
        below 60, and `HIGH` at 60 or above. Both fields read null before an assessment
        has been recorded."

        Design: Corner/validations/comprehensive_assessment_without_albumin_returns_albumin_required
        """
        ward = new_ward()
        patient = new_patient(ward["id"], mrn="MRN-AN01", full_name="Pau Ferrer",
                              age_years=71)
        consult = new_consult(patient["id"], PHYSICIAN)
        assign_consult(consult["id"], DIETITIAN_1)

        response = api.assess_consult(
            consult["id"],
            {"assessment_variant": "COMPREHENSIVE", "weight_loss_pct": 12.0,
             "intake_pct": 30.0, "bmi": 17.0},
            DIETITIAN,
        )
        validate_error(response, ApiErrorId.ERR_ALBUMIN_REQUIRED, 422)

        after = read_consult(consult["id"])
        assert after["status"] == "ASSIGNED"
        assert after["malnutrition_risk_score"] is None
        assert after["risk_tier"] is None
        assert after["assessment_variant"] is None


class TestSupplementActivationGate:
    def test_activation_refused_while_the_consult_is_only_assessed(self, api):
        """PRD §3.9: "Activation requires the supplement order to be `PENDING`, the
        backing consult to be `SIGNED` — anything else is `ERR_CONSULT_NOT_SIGNED` —
        the patient to be `ADMITTED`, and the menu item to still be `ACTIVE`."
        PRD §3.9: "On creation, `patient_id` is copied from the consult rather than
        supplied by the caller, `ordered_by_user_id` is stamped from the acting
        `X-User-ID`, `status` is `PENDING`, `activated_at` and `cancelled_at` are null,
        and `daily_cost_cents` is computed as the menu item's `unit_cost_cents`
        multiplied by `doses_per_day`."

        Design: Difficulty/cross_entity_state_dependency/supplement_activate_blocked_until_consult_is_signed
        """
        scenario = setup_assessed_consult(
            patient_overrides={"mrn": "MRN-G001", "full_name": "Gia Ferro",
                               "age_years": 77},
            consult_overrides={"acuity": "ROUTINE"},
            assessment={"assessment_variant": "SCREENING", "weight_loss_pct": 8.0,
                        "intake_pct": 60.0, "bmi": 17.0},
        )
        supplement = new_supplement_order(
            scenario["consult"]["id"], scenario["menu"]["SUP-ORS"]["id"], 2
        )
        assert_supplement_order(supplement)
        assert supplement["status"] == "PENDING"
        assert supplement["daily_cost_cents"] == 520

        response = api.activate_supplement_order(supplement["id"], DIETITIAN)
        validate_error(response, ApiErrorId.ERR_CONSULT_NOT_SIGNED, 409)

        assert read_supplement_order(supplement["id"])["status"] == "PENDING"
        assert read_patient(
            scenario["patient"]["id"]
        )["daily_supplement_cost_cents"] == 0

        consult = read_consult(scenario["consult"]["id"])
        # 0.50 * 40 + 0.30 * 40 + 0.20 * 70 == 46.00
        assert consult["malnutrition_risk_score"] == approx2(46.00)
        assert consult["risk_tier"] == "MODERATE"

    def test_the_same_activation_succeeds_once_a_second_dietitian_signs(self, api):
        """PRD §3.9: "**Signing** moves it `ASSESSED → SIGNED`, records
        `signed_by_user_id` from the acting `X-User-ID`, and requires that identifier
        to differ from `requested_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`.
        Signing is what unlocks activation for the supplement orders hanging off the
        consult."
        PRD §3.9: "It moves the order `PENDING → ACTIVE`, sets `activated_at` to the
        logical-clock instant, adds `daily_cost_cents` to the patient's
        `daily_supplement_cost_cents`, and increments both the order's `version` and
        the patient's `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/supplement_activate_blocked_until_consult_is_signed
        """
        scenario = setup_assessed_consult(
            patient_overrides={"mrn": "MRN-G001", "full_name": "Gia Ferro",
                               "age_years": 77},
            assessment={"assessment_variant": "SCREENING", "weight_loss_pct": 8.0,
                        "intake_pct": 60.0, "bmi": 17.0},
        )
        supplement = new_supplement_order(
            scenario["consult"]["id"], scenario["menu"]["SUP-ORS"]["id"], 2
        )
        assert api.activate_supplement_order(
            supplement["id"], DIETITIAN
        ).status_code == 409

        signed = validate_success(
            api.sign_consult(scenario["consult"]["id"], DIETITIAN), 200
        )
        assert signed["status"] == "SIGNED"
        assert signed["signed_by_user_id"] == DIETITIAN_1

        activated = validate_success(
            api.activate_supplement_order(supplement["id"], DIETITIAN), 200
        )
        assert activated["status"] == "ACTIVE"
        assert activated["daily_cost_cents"] == 520
        assert read_patient(
            scenario["patient"]["id"]
        )["daily_supplement_cost_cents"] == 520


class TestSupplementLedgerSymmetry:
    def _two_active_regimens(self):
        scenario = setup_signed_consult(
            patient_overrides={"mrn": "MRN-K001", "full_name": "Kim Sato",
                               "age_years": 69},
            consult_overrides={"acuity": "URGENT"},
            assessment={"assessment_variant": "COMPREHENSIVE", "weight_loss_pct": 12.0,
                        "intake_pct": 30.0, "bmi": 17.0, "albumin_g_dl": 2.8},
        )
        item_id = scenario["menu"]["SUP-ORS"]["id"]
        first = new_supplement_order(scenario["consult"]["id"], item_id, 2)
        second = new_supplement_order(scenario["consult"]["id"], item_id, 1)
        activate_supplement_order(first["id"])
        activate_supplement_order(second["id"])
        scenario["first"] = first
        scenario["second"] = second
        return scenario

    def test_cancelling_one_active_regimen_subtracts_exactly_its_daily_cost(self, api):
        """PRD §3.9: "Cancelling an `ACTIVE` regimen moves it `ACTIVE → CANCELLED`,
        sets `cancelled_at`, subtracts exactly that `daily_cost_cents` back out of the
        patient's `daily_supplement_cost_cents` — returning the patient ledger to
        precisely its pre-activation value — and increments both versions by 1."
        PRD §2.7: "The same symmetry governs the patient's supplement ledger:
        activating a supplement regimen adds its daily cost to the patient's running
        total and cancelling an active one subtracts exactly that amount, while
        cancelling a regimen that never activated leaves the total untouched because it
        never debited it."

        Design: Difficulty/compensating_invariant/patient_supplement_cost_ledger_conserved_across_activate_then_cancel
        """
        scenario = self._two_active_regimens()
        assert read_patient(
            scenario["patient"]["id"]
        )["daily_supplement_cost_cents"] == 780

        cancelled = validate_success(
            api.cancel_supplement_order(scenario["first"]["id"], DIETITIAN), 200
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["daily_cost_cents"] == 520, (
            "the cancelled order keeps its own daily cost"
        )

        assert read_patient(
            scenario["patient"]["id"]
        )["daily_supplement_cost_cents"] == 260
        assert read_supplement_order(scenario["second"]["id"])["status"] == "ACTIVE"
        assert read_supplement_order(
            scenario["second"]["id"]
        )["daily_cost_cents"] == 260

    def test_the_consult_counts_both_regimens_and_keeps_its_assessment(self, api):
        """PRD §3.9: "Creation also increments the consult's
        `linked_supplement_order_count` by 1 and therefore its `version` by 1."
        PRD §3.9: "The `COMPREHENSIVE` variant is a four-factor assessment: it takes
        0.35 of the weight-loss points plus 0.25 of the intake points plus 0.20 of the
        body-mass-index points plus 0.20 of the albumin points, again rounded half up to
        2 decimal places; adding albumin at a weight of 0.20 dilutes the weight-loss
        term from 0.50 down to 0.35, so identical anthropometrics accompanied by a
        normal albumin land in a **lower** tier than `SCREENING` would report."
        PRD §3.9: "Supplement orders can be surveyed by `consult_id`, `patient_id`,
        `menu_item_id` and `status`."

        Design: Difficulty/compensating_invariant/patient_supplement_cost_ledger_conserved_across_activate_then_cancel
        """
        scenario = self._two_active_regimens()
        validate_success(
            api.cancel_supplement_order(scenario["first"]["id"], DIETITIAN), 200
        )

        _, meta = validate_paginated(
            api.list_supplement_orders(
                DIETITIAN,
                params={"patient_id": scenario["patient"]["id"], "status": "ACTIVE"},
            )
        )
        assert meta["total_count"] == 1

        consult = read_consult(scenario["consult"]["id"])
        assert consult["linked_supplement_order_count"] == 2
        # 0.35 * 70 + 0.25 * 70 + 0.20 * 70 + 0.20 * 70 == 70.00
        assert consult["malnutrition_risk_score"] == approx2(70.00)
        assert consult["risk_tier"] == "HIGH"

    def test_consult_cancel_cascades_pending_supplement_order_to_cancelled(self, api):
        """PRD §3.9: "**Cancelling** is available from `REQUESTED`, from `ASSIGNED` and
        from `ASSESSED`, and behaves identically from all three: the consult moves to
        `CANCELLED`, every supplement order on it that is still `PENDING` moves to
        `CANCELLED`, and the consult's `version` increments by 1."
        PRD §3.9: "Cancelling a `PENDING` regimen, whether directly or through the
        owning consult's cancel cascade, moves it `PENDING → CANCELLED` and sets
        `cancelled_at`, but leaves `daily_supplement_cost_cents` untouched, because a
        `PENDING` order never debited it; only the order's own `version` increments."

        Design: Corner/state_machines/consult_cancel_cascades_pending_supplement_order_to_cancelled
        """
        scenario = setup_assessed_consult(
            patient_overrides={"mrn": "MRN-Z001", "full_name": "Zoe Hart",
                               "age_years": 70},
            assessment={"assessment_variant": "SCREENING", "weight_loss_pct": 8.0,
                        "intake_pct": 60.0, "bmi": 17.0},
        )
        supplement = new_supplement_order(
            scenario["consult"]["id"], scenario["menu"]["SUP-ORS"]["id"], 2
        )

        cancelled = validate_success(
            api.cancel_consult(scenario["consult"]["id"], DIETITIAN), 200
        )
        assert cancelled["status"] == "CANCELLED"

        supplement_after = read_supplement_order(supplement["id"])
        assert supplement_after["status"] == "CANCELLED"
        assert supplement_after["daily_cost_cents"] == 520
        assert read_patient(
            scenario["patient"]["id"]
        )["daily_supplement_cost_cents"] == 0
        assert read_consult(
            scenario["consult"]["id"]
        )["linked_supplement_order_count"] == 1

    def test_supplement_order_with_unknown_consult_returns_consult_not_found(self, api):
        """PRD §2.5: "5. **Body existence** — every identifier supplied in the request
        body resolves to a stored row, checked in the order the endpoint's input list
        declares those fields, else the type-specific not-found error."
        PRD §2.5: "15. **Consult optimistic concurrency** — `expected_consult_version`
        matches, else `ERR_STALE_CONSULT_VERSION`."

        Design: Corner/errors/supplement_order_with_unknown_consult_returns_consult_not_found
        """
        scenario = setup_assessed_consult(
            patient_overrides={"mrn": "MRN-AS01", "full_name": "Uli Brandt",
                               "age_years": 65},
            assessment={"assessment_variant": "SCREENING", "weight_loss_pct": 8.0,
                        "intake_pct": 60.0, "bmi": 17.0},
        )

        response = api.create_supplement_order(
            create_supplement_order_payload(
                NON_EXISTENT_UUID,
                scenario["menu"]["SUP-ORS"]["id"],
                scenario["consult"]["version"],
                2,
            ),
            DIETITIAN,
        )
        error = validate_error(response, ApiErrorId.ERR_CONSULT_NOT_FOUND, 404)
        assert error["error_id"] != "ERR_STALE_CONSULT_VERSION"

        _, meta = validate_paginated(
            api.list_supplement_orders(
                DIETITIAN, params={"consult_id": scenario["consult"]["id"]}
            )
        )
        assert meta["total_count"] == 0


class TestBedsideSatisfaction:
    def test_patient_average_rounds_half_up_over_already_rounded_composites(self, api):
        """PRD §3.9: "Its `composite_score` is 0.40 of the `taste_score` plus 0.35 of
        the `temperature_score` plus 0.25 of the `accuracy_score`, rounded half up to 2
        decimal places."
        PRD §3.9: "`survey_count` becomes the number of surveys held for that patient,
        and `satisfaction_score_avg` becomes the sum of the **already-rounded**
        `composite_score` values of those surveys divided by their count, rounded half
        up to 2 decimal places once more; surveys are taken in ascending `created_at`
        order and no status filtering applies, because a survey is an immutable
        append-only event."
        PRD §2.4: "A satisfaction survey is an immutable, append-only event: it carries
        `id` and `created_at` only. It has **no** `updated_at` and **no** `version`
        field, and neither field appears in its representation."

        Design: Corner/calculations/patient_satisfaction_average_rounds_half_up_over_already_rounded_composites
        """
        scenario = _two_delivered_trays_for_one_patient()

        first = validate_success(
            api.create_survey(
                create_survey_payload(scenario["lunch_tray"]["id"], taste_score=4,
                                      temperature_score=3, accuracy_score=5),
                AIDE_1,
            ),
            201,
        )
        second = validate_success(
            api.create_survey(
                create_survey_payload(scenario["dinner_tray"]["id"], taste_score=5,
                                      temperature_score=5, accuracy_score=4,
                                      comment="Much better"),
                CLERK,
            ),
            201,
        )
        assert_satisfaction_survey(first)
        assert_satisfaction_survey(second)

        assert first["composite_score"] == approx2(3.90)
        assert second["composite_score"] == approx2(4.75)
        assert first["patient_id"] == scenario["patient"]["id"]
        assert second["patient_id"] == scenario["patient"]["id"]

        patient = read_patient(scenario["patient"]["id"])
        assert patient["survey_count"] == 2
        # (3.90 + 4.75) / 2 == 4.325, which rounds half up to 4.33.
        assert patient["satisfaction_score_avg"] == approx2(4.33)

    def test_survey_before_delivery_returns_meal_order_not_delivered(self, api):
        """PRD §3.9: "The rated tray's fulfillment dimension must read `DELIVERED`,
        else `ERR_MEAL_ORDER_NOT_DELIVERED`, and at most one survey may exist per tray,
        so a second attempt is `ERR_DUPLICATE_SURVEY`."

        Design: Corner/calculations/satisfaction_survey_before_delivery_returns_meal_order_not_delivered
        """
        scenario = setup_temp_passed_tray(
            menu_keys=("SOU-BRO",),
            patient_overrides={"mrn": "MRN-AF01", "full_name": "Hal Speer",
                               "age_years": 63},
        )

        response = api.create_survey(
            create_survey_payload(scenario["meal_order"]["id"], 4, 4, 4), AIDE_1
        )
        validate_error(response, ApiErrorId.ERR_MEAL_ORDER_NOT_DELIVERED, 409)

        patient = read_patient(scenario["patient"]["id"])
        assert patient["survey_count"] == 0
        assert patient["satisfaction_score_avg"] is None

        _, meta = validate_paginated(
            api.list_surveys(
                CLERK, params={"meal_order_id": scenario["meal_order"]["id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_second_survey_on_the_same_tray_returns_duplicate_survey(self, api):
        """PRD §3.9: "The rated tray's fulfillment dimension must read `DELIVERED`,
        else `ERR_MEAL_ORDER_NOT_DELIVERED`, and at most one survey may exist per tray,
        so a second attempt is `ERR_DUPLICATE_SURVEY`."
        PRD §3.9: "Its `composite_score` is 0.40 of the `taste_score` plus 0.35 of the
        `temperature_score` plus 0.25 of the `accuracy_score`, rounded half up to 2
        decimal places."

        Design: Corner/errors/second_survey_on_the_same_tray_returns_duplicate_survey
        """
        scenario = setup_delivered_tray(
            deliver_at="2026-08-02T12:00:00Z",
            menu_keys=("SOU-BRO",),
            patient_overrides={"mrn": "MRN-AT01", "full_name": "Vic Aalto",
                               "age_years": 53},
        )
        tray_id = scenario["meal_order"]["id"]
        first = validate_success(
            api.create_survey(create_survey_payload(tray_id, 4, 4, 4), AIDE_1), 201
        )
        assert first["composite_score"] == approx2(4.00)

        response = api.create_survey(
            create_survey_payload(tray_id, 1, 1, 1), CLERK
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_SURVEY, 409)

        patient = read_patient(scenario["patient"]["id"])
        assert patient["survey_count"] == 1
        assert patient["satisfaction_score_avg"] == approx2(4.00)
        assert scenario["meal_order"]["service_compliance_score"] == 100
