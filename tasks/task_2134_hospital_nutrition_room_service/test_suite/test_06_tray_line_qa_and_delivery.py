"""The tray line: parallel quality assurance, probe boundaries and bedside delivery."""
import pytest
from test_helpers import (
    ApiErrorId,
    TRAY_AIDE_1,
    TRAY_AIDE_2,
    TEST_USERS,
    activate_procedure_hold,
    approx1,
    create_active_diet_order,
    deliver_tray,
    diet_order_version,
    line,
    lock_and_open,
    make_tray_aide_headers,
    new_diet_rule,
    new_dinner_period,
    new_meal_period,
    new_menu_item,
    new_patient,
    new_procedure_hold,
    new_ward,
    pass_accuracy_check,
    pass_temperature_check,
    place_tray,
    plate_tray,
    read_meal_order,
    read_meal_period,
    read_patient,
    read_procedure_hold,
    set_clock,
    setup_accuracy_passed_tray,
    setup_plated_tray,
    setup_temp_passed_tray,
    validate_error,
    validate_success,
    validate_tray,
)

MANAGER = TEST_USERS["nutrition_manager_headers"]
CLERK = TEST_USERS["diet_clerk_headers"]
PHYSICIAN = TEST_USERS["physician_headers"]
AIDE_1 = TEST_USERS["tray_aide_headers"]
AIDE_2 = TEST_USERS["tray_aide_2_headers"]

PUREED_BROTH_TRAY = dict(
    menu_keys=("SOU-BRO",),
    patient_overrides={"mrn": "MRN-7001", "full_name": "Ada Kern",
                       "age_years": 71, "texture_level": "PUREED"},
)


class TestParallelQaDimension:
    def test_qa_dimension_walks_four_states_while_fulfillment_stays_plated(self, api):
        """PRD §3.7: "A tray carries **two independent state dimensions**, and they
        advance on separate triggers. `fulfillment_status` tracks where the tray is in
        production and delivery; `qa_status` tracks what quality assurance has
        established about it. Neither dimension's transition implies the other's, and
        both must reach the right value before a tray can reach the bedside."
        PRD §3.7: "From `NOT_CHECKED`, a passing check moves the quality dimension
        `NOT_CHECKED → ACCURACY_PASSED` and stamps `accuracy_checked_by_user_id` with
        the acting `X-User-ID`; a failing check moves it `NOT_CHECKED →
        ACCURACY_FAILED`, increments `accuracy_retry_count` by 1, and stamps
        `accuracy_checked_by_user_id` just the same."
        PRD §3.7: "From `ACCURACY_FAILED` the aide re-runs the check after correcting
        the tray: a passing re-run closes the retry cycle `ACCURACY_FAILED →
        ACCURACY_PASSED` and re-stamps `accuracy_checked_by_user_id`, while a
        still-failing re-run leaves the dimension at `ACCURACY_FAILED` and increments
        `accuracy_retry_count` again."
        PRD §3.7: "From `TEMP_FAILED` the tray is re-thermalised and re-probed: a
        satisfactory re-run moves `TEMP_FAILED → TEMP_PASSED` storing the new readings,
        and an unsatisfactory one leaves the dimension at `TEMP_FAILED` and increments
        `temperature_retry_count` again."

        Design: Difficulty/non_linear_state_machine/meal_order_qa_dimension_advances_independently_of_fulfillment
        """
        scenario = setup_plated_tray(**PUREED_BROTH_TRAY)
        tray_id = scenario["meal_order"]["id"]

        failed = validate_success(
            api.accuracy_check(tray_id, {"observed_line_count": 2}, AIDE_1), 200
        )
        assert failed["qa_status"] == "ACCURACY_FAILED"
        assert failed["fulfillment_status"] == "PLATED"

        passed = validate_success(
            api.accuracy_check(tray_id, {"observed_line_count": 1}, AIDE_1), 200
        )
        assert passed["qa_status"] == "ACCURACY_PASSED"
        assert passed["fulfillment_status"] == "PLATED"

        temp_failed = validate_success(
            api.temperature_check(tray_id, {"hot_probe_celsius": 55.0}, AIDE_2), 200
        )
        assert temp_failed["qa_status"] == "TEMP_FAILED"
        assert temp_failed["fulfillment_status"] == "PLATED"

        temp_passed = validate_success(
            api.temperature_check(tray_id, {"hot_probe_celsius": 61.5}, AIDE_2), 200
        )
        assert temp_passed["qa_status"] == "TEMP_PASSED"
        assert temp_passed["fulfillment_status"] == "PLATED"

        assert temp_passed["accuracy_retry_count"] == 1
        assert temp_passed["temperature_retry_count"] == 1

    def test_both_retry_counters_permanently_cut_the_service_score(self, api):
        """PRD §3.7: "`service_compliance_score` then starts at 100 and subtracts, in
        one pass: 25 points when the delivery was `LATE`, 10 points when it was
        `EARLY`, nothing when it was `ON_TIME`; 15 points for each accumulated
        `temperature_retry_count`; and 20 points for each accumulated
        `accuracy_retry_count`."
        PRD §3.7: "Retry counters are cumulative across the tray's whole quality
        history and are never reset, which is what makes a single failed check follow
        the tray all the way to its score."
        PRD §3.7: "On success `delivered_at` records the logical-clock instant, the
        period's `delivered_tray_count` increments by 1, and both the tray's `version`
        and the period's `version` increment by 1."

        Design: Difficulty/non_linear_state_machine/meal_order_qa_dimension_advances_independently_of_fulfillment
        """
        scenario = setup_plated_tray(**PUREED_BROTH_TRAY)
        tray_id = scenario["meal_order"]["id"]

        validate_success(
            api.accuracy_check(tray_id, {"observed_line_count": 2}, AIDE_1), 200
        )
        validate_success(
            api.accuracy_check(tray_id, {"observed_line_count": 1}, AIDE_1), 200
        )
        validate_success(
            api.temperature_check(tray_id, {"hot_probe_celsius": 55.0}, AIDE_2), 200
        )
        validate_success(
            api.temperature_check(tray_id, {"hot_probe_celsius": 61.5}, AIDE_2), 200
        )
        set_clock("2026-08-02T12:00:00Z")

        delivered = validate_success(api.deliver_meal_order(tray_id, AIDE_1), 200)
        assert delivered["fulfillment_status"] == "DELIVERED"
        assert delivered["delivery_window_compliance"] == "ON_TIME"
        # 100 - 0 late/early - 15 * 1 temperature retry - 20 * 1 accuracy retry.
        assert delivered["service_compliance_score"] == 65

        period = read_meal_period(scenario["period"]["id"])
        assert period["delivered_tray_count"] == 1


class TestHotProbeBoundary:
    def test_hot_probe_at_fifty_nine_point_nine_fails_and_sixty_exactly_passes(self, api):
        """PRD §3.7: "The hot reading is satisfactory when the tray needs no hot probe
        at all, or when `hot_probe_celsius` is **at least 60.0 degrees Celsius**; the
        cold reading is satisfactory when the tray needs no cold probe at all, or when
        `cold_probe_celsius` is **at most 4.0 degrees Celsius**. Exactly 60.0 passes
        and exactly 4.0 passes; 59.9 and 4.1 do not."
        PRD §3.7: "When both readings are satisfactory the dimension moves
        `ACCURACY_PASSED → TEMP_PASSED`, storing the supplied readings and stamping
        `temperature_checked_by_user_id` with the acting `X-User-ID`. When either is
        not, it moves `ACCURACY_PASSED → TEMP_FAILED`, storing the readings,
        incrementing `temperature_retry_count` by 1, and stamping
        `temperature_checked_by_user_id` all the same."

        Design: Difficulty/boundary_precision_check/hot_probe_boundary_fifty_nine_point_nine_fails_and_sixty_exactly_passes
        """
        scenario = setup_accuracy_passed_tray(
            menu_keys=("SOU-BRO",),
            patient_overrides={"mrn": "MRN-D001", "full_name": "Dov Reyes",
                               "age_years": 80, "texture_level": "PUREED"},
        )
        tray_id = scenario["meal_order"]["id"]

        below = validate_success(
            api.temperature_check(tray_id, {"hot_probe_celsius": 59.9}, AIDE_2), 200
        )
        assert below["qa_status"] == "TEMP_FAILED"
        assert below["temperature_retry_count"] == 1

        at_boundary = validate_success(
            api.temperature_check(tray_id, {"hot_probe_celsius": 60.0}, AIDE_2), 200
        )
        assert at_boundary["qa_status"] == "TEMP_PASSED", "exactly 60.0 passes"
        assert at_boundary["temperature_retry_count"] == 1
        assert at_boundary["hot_probe_celsius"] == approx1(60.0)
        assert at_boundary["cold_probe_celsius"] is None
        assert at_boundary["accuracy_retry_count"] == 0

    def test_one_failed_probe_costs_exactly_fifteen_score_points(self, api):
        """PRD §3.7: "`delivery_window_compliance` places `delivered_at` against the
        period's window, and here the window is read as **half-open**: a delivery
        strictly before `window_start_at` is `EARLY`; a delivery at or after
        `window_end_at` is `LATE`, so the instant exactly equal to `window_end_at` is
        already late; anything in between is `ON_TIME`."
        PRD §3.7: "`service_compliance_score` then starts at 100 and subtracts, in one
        pass: 25 points when the delivery was `LATE`, 10 points when it was `EARLY`,
        nothing when it was `ON_TIME`; 15 points for each accumulated
        `temperature_retry_count`; and 20 points for each accumulated
        `accuracy_retry_count`."

        Design: Difficulty/boundary_precision_check/hot_probe_boundary_fifty_nine_point_nine_fails_and_sixty_exactly_passes
        """
        scenario = setup_accuracy_passed_tray(
            menu_keys=("SOU-BRO",),
            patient_overrides={"mrn": "MRN-D001", "full_name": "Dov Reyes",
                               "age_years": 80, "texture_level": "PUREED"},
        )
        tray_id = scenario["meal_order"]["id"]
        pass_temperature_check(tray_id, 59.9, None, TRAY_AIDE_2)
        pass_temperature_check(tray_id, 60.0, None, TRAY_AIDE_2)
        set_clock("2026-08-02T12:00:00Z")

        delivered = validate_success(api.deliver_meal_order(tray_id, AIDE_1), 200)
        assert delivered["delivery_window_compliance"] == "ON_TIME"
        assert delivered["service_compliance_score"] == 85


class TestDeliveryUnderNilPerOs:
    def test_delivery_refused_while_the_patient_is_under_an_active_hold(self, api):
        """PRD §3.8: "While a patient's `npo_status` is anything other than `NONE`, two
        operations are blocked outright with `ERR_NPO_ACTIVE`: a tray for that patient
        cannot be validated, and a plated tray cannot be delivered."
        PRD §3.7: "**Bedside delivery** moves the tray `PLATED → DELIVERED` and demands
        three things at once: the fulfillment dimension is `PLATED`, the quality
        dimension has reached `TEMP_PASSED` — anything else is `ERR_QA_NOT_PASSED` —
        and the patient's `npo_status` reads `NONE`, since a hold that landed between
        plating and the bedside must stop the tray, reported as `ERR_NPO_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/tray_deliver_blocked_while_patient_under_non_covering_npo_hold
        """
        scenario = setup_temp_passed_tray(
            menu_keys=("SOU-BRO",),
            patient_overrides={"mrn": "MRN-H001", "full_name": "Hana Ito",
                               "age_years": 68, "texture_level": "PUREED"},
        )
        set_clock("2026-08-02T12:00:00Z")
        hold = new_procedure_hold(
            scenario["patient"]["id"],
            procedure_code="MRI-07",
            npo_kind="NPO_STRICT",
            hold_start_at="2026-08-02T20:00:00Z",
            hold_end_at="2026-08-02T22:00:00Z",
        )
        activate_procedure_hold(hold["id"])

        response = api.deliver_meal_order(scenario["meal_order"]["id"], AIDE_1)
        validate_error(response, ApiErrorId.ERR_NPO_ACTIVE, 422)

        assert read_patient(scenario["patient"]["id"])["npo_status"] == "NPO_STRICT"
        tray = read_meal_order(scenario["meal_order"]["id"])
        assert tray["fulfillment_status"] == "PLATED"
        assert tray["qa_status"] == "TEMP_PASSED"

    def test_a_non_covering_hold_voids_no_tray_yet_still_blocks_the_bedside(self, api):
        """PRD §3.8: "**Level two:** because the patient's `npo_status` has left
        `NONE`, every meal order for this patient whose meal period window — read from
        `window_start_at` inclusive to `window_end_at` exclusive — intersects the hold's
        buffered interval, and whose fulfillment dimension reads `PENDING_VALIDATION`,
        `VALIDATED`, `IN_PRODUCTION` or `PLATED`, moves to `MISSED` with
        `missed_reason` recorded as `NPO_HOLD`; the hold's `missed_meal_order_count` is
        set to the number of trays it moved."
        PRD §3.8: "While a patient's `npo_status` is anything other than `NONE`, two
        operations are blocked outright with `ERR_NPO_ACTIVE`: a tray for that patient
        cannot be validated, and a plated tray cannot be delivered."

        Design: Difficulty/cross_entity_state_dependency/tray_deliver_blocked_while_patient_under_non_covering_npo_hold
        """
        scenario = setup_temp_passed_tray(
            menu_keys=("SOU-BRO",),
            patient_overrides={"mrn": "MRN-H001", "full_name": "Hana Ito",
                               "age_years": 68, "texture_level": "PUREED"},
        )
        set_clock("2026-08-02T12:00:00Z")
        hold = new_procedure_hold(
            scenario["patient"]["id"],
            procedure_code="MRI-07",
            npo_kind="NPO_STRICT",
            hold_start_at="2026-08-02T20:00:00Z",
            hold_end_at="2026-08-02T22:00:00Z",
        )
        activate_procedure_hold(hold["id"])

        response = api.deliver_meal_order(scenario["meal_order"]["id"], AIDE_1)
        assert response.status_code == 422

        # The buffered interval 20:00-22:00 never meets the 11:30-13:00 window.
        assert read_procedure_hold(hold["id"])["missed_meal_order_count"] == 0
        tray = read_meal_order(scenario["meal_order"]["id"])
        assert tray["missed_reason"] is None
        patient = read_patient(scenario["patient"]["id"])
        assert patient["missed_meal_count"] == 0

        period = read_meal_period(scenario["period"]["id"])
        assert period["committed_tray_count"] == 1
        assert period["delivered_tray_count"] == 0


class TestDeliveryScoring:
    def test_delivery_before_the_window_is_early_and_at_window_end_is_late(self, api):
        """PRD §3.7: "`delivery_window_compliance` places `delivered_at` against the
        period's window, and here the window is read as **half-open**: a delivery
        strictly before `window_start_at` is `EARLY`; a delivery at or after
        `window_end_at` is `LATE`, so the instant exactly equal to `window_end_at` is
        already late; anything in between is `ON_TIME`."
        PRD §3.7: "`service_compliance_score` then starts at 100 and subtracts, in one
        pass: 25 points when the delivery was `LATE`, 10 points when it was `EARLY`,
        nothing when it was `ON_TIME`; 15 points for each accumulated
        `temperature_retry_count`; and 20 points for each accumulated
        `accuracy_retry_count`."

        Design: Corner/calculations/delivery_window_compliance_marks_early_before_start_and_late_at_window_end
        """
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

        # Placing a tray bumps the pinned diet order's version (PRD 3.6), so each
        # tray must be validated while its pinned_diet_order_version still equals
        # the order's current version -- before the next tray is placed.
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
        early = validate_success(api.deliver_meal_order(lunch_tray["id"], AIDE_1), 200)
        set_clock("2026-08-02T19:00:00Z")
        late = validate_success(api.deliver_meal_order(dinner_tray["id"], AIDE_1), 200)

        assert early["delivery_window_compliance"] == "EARLY"
        assert early["service_compliance_score"] == 90
        assert early["fulfillment_status"] == "DELIVERED"

        assert late["delivery_window_compliance"] == "LATE", (
            "the instant exactly equal to window_end_at is already late"
        )
        assert late["service_compliance_score"] == 75
        assert late["fulfillment_status"] == "DELIVERED"

        assert read_meal_period(lunch["id"])["delivered_tray_count"] == 1
        assert read_meal_period(dinner["id"])["delivered_tray_count"] == 1

    def test_cold_probe_omitted_for_a_cold_tray_returns_probe_required(self, api):
        """PRD §3.7: "Which of them is mandatory is decided by the tray's contents —
        `hot_probe_celsius` must be supplied whenever `requires_hot_probe` is true and
        `cold_probe_celsius` must be supplied whenever `requires_cold_probe` is true,
        and an omission is `ERR_TEMPERATURE_PROBE_REQUIRED`."
        PRD §3.6: "Two booleans fall out of the same pass: `requires_hot_probe` is true
        when at least one line resolves to a menu item whose `service_temp_class` is
        `HOT`, and `requires_cold_probe` is true when at least one line resolves to an
        item whose `service_temp_class` is `COLD`. An `AMBIENT` item demands neither
        probe."

        Design: Corner/validations/cold_probe_omitted_for_a_cold_tray_returns_temperature_probe_required
        """
        scenario = setup_accuracy_passed_tray(
            menu_keys=("SUP-ORS",),
            patient_overrides={"mrn": "MRN-AM01", "full_name": "Ola Rustad",
                               "age_years": 60},
        )
        tray_id = scenario["meal_order"]["id"]

        response = api.temperature_check(tray_id, {}, AIDE_2)
        validate_error(response, ApiErrorId.ERR_TEMPERATURE_PROBE_REQUIRED, 422)

        tray = read_meal_order(tray_id)
        assert tray["requires_cold_probe"] is True
        assert tray["requires_hot_probe"] is False
        assert tray["qa_status"] == "ACCURACY_PASSED"
        assert tray["temperature_retry_count"] == 0
        assert tray["food_cost_cents"] == 281
