"""Nil-per-os holds, the tray-voiding cascade and the missed-meal escalation."""
import pytest
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_procedure_hold,
    approx1,
    assert_instant_equals,
    assert_procedure_hold,
    close_period,
    create_active_diet_order,
    create_procedure_hold_payload,
    line,
    lock_and_open,
    new_diet_rule,
    new_dinner_period,
    new_meal_period,
    new_menu_item,
    new_patient,
    new_procedure_hold,
    new_ward,
    place_tray,
    read_meal_order,
    read_meal_period,
    read_patient,
    read_procedure_hold,
    set_clock,
    setup_validated_tray,
    validate_error,
    validate_paginated,
    validate_success,
    validate_tray,
)

MANAGER = TEST_USERS["nutrition_manager_headers"]
CLERK = TEST_USERS["diet_clerk_headers"]
PHYSICIAN = TEST_USERS["physician_headers"]


def _two_validated_trays_under_a_covering_hold():
    ward = new_ward()
    rule = new_diet_rule("REGULAR_STD")
    broth = new_menu_item("SOU-BRO")
    patient = new_patient(ward["id"], mrn="MRN-8001", full_name="Ada Kern",
                          age_years=71, texture_level="PUREED")
    diet_order = create_active_diet_order(patient["id"], rule["id"])
    lunch = new_meal_period(ward["id"])
    dinner = new_dinner_period(ward["id"])
    hold = new_procedure_hold(
        patient["id"],
        procedure_code="ENDO-01",
        npo_kind="NPO_STRICT",
        hold_start_at="2026-08-02T06:00:00Z",
        hold_end_at="2026-08-02T20:00:00Z",
    )
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
    return {
        "ward": ward, "patient": patient, "hold": hold,
        "lunch": lunch, "dinner": dinner,
        "lunch_tray": lunch_tray, "dinner_tray": dinner_tray,
    }


class TestHoldActivationCascade:
    def test_activation_voids_every_covered_tray_and_moves_patient_counters(self, api):
        """PRD §3.8: "**Level one:** the patient's `npo_status` is set to the hold's
        `npo_kind` and `active_procedure_hold_id` is pointed at this hold."
        PRD §3.8: "**Level two:** because the patient's `npo_status` has left `NONE`,
        every meal order for this patient whose meal period window — read from
        `window_start_at` inclusive to `window_end_at` exclusive — intersects the hold's
        buffered interval, and whose fulfillment dimension reads `PENDING_VALIDATION`,
        `VALIDATED`, `IN_PRODUCTION` or `PLATED`, moves to `MISSED` with
        `missed_reason` recorded as `NPO_HOLD`; the hold's `missed_meal_order_count` is
        set to the number of trays it moved."
        PRD §3.8: "Within a single cascade the affected trays are processed in
        ascending `created_at` order, and for each one: the patient's
        `missed_meal_count` increases by 1, and their `protein_deficit_g` becomes the
        previous deficit plus that tray's `total_protein_g`, rounded half up to 1
        decimal place after each addition."

        Design: Difficulty/transitive_cascade/npo_hold_activation_cascades_through_missed_trays_slot_release_and_auto_consult
        """
        scenario = _two_validated_trays_under_a_covering_hold()

        activated = validate_success(
            api.activate_procedure_hold(scenario["hold"]["id"], PHYSICIAN), 200
        )
        assert_procedure_hold(activated)
        assert activated["status"] == "ACTIVE"
        assert activated["missed_meal_order_count"] == 2

        patient = read_patient(scenario["patient"]["id"])
        assert patient["npo_status"] == "NPO_STRICT"
        assert patient["active_procedure_hold_id"] == scenario["hold"]["id"]
        assert patient["missed_meal_count"] == 2
        assert patient["protein_deficit_g"] == approx1(8.0)

        for key in ("lunch_tray", "dinner_tray"):
            tray = read_meal_order(scenario[key]["id"])
            assert tray["fulfillment_status"] == "MISSED"
            assert tray["missed_reason"] == "NPO_HOLD"

    def test_voided_trays_release_their_ledgers_and_raise_one_urgent_consult(self, api):
        """PRD §3.8: "**Level three:** because each of those trays that had been
        `VALIDATED`, `IN_PRODUCTION` or `PLATED` left a committed state, its meal period
        decrements `committed_tray_count`, subtracts that tray's `food_cost_cents` from
        `committed_food_cost_cents`, and recomputes `period_overhead_cents`,
        `period_bulk_discount_cents`, `period_total_cost_cents` and
        `forecast_variance_pct`."
        PRD §3.8: "If the patient's `missed_meal_count` has reached **two or more**,
        and no nutrition consult for that patient currently sits in `REQUESTED`,
        `ASSIGNED` or `ASSESSED`, the system raises a consult on the patient's behalf:
        `patient_id` set to the patient, `acuity` set to `URGENT`, `reason_code` set to
        the literal string `MISSED_MEALS`, `requested_by_user_id` set to the literal
        string `SYSTEM`, `auto_generated` set to true, and `status` at `REQUESTED`."
        PRD §3.8: "At most **one** automatic consult is raised per cascade, because the
        first creation makes the no-open-consult guard false for every later tray in
        that same cascade."
        PRD §3.8: "**Level five:** because the patient's `npo_status` has left `NONE`,
        the ward's `active_patient_census` is recomputed."

        Design: Difficulty/transitive_cascade/npo_hold_activation_cascades_through_missed_trays_slot_release_and_auto_consult
        """
        scenario = _two_validated_trays_under_a_covering_hold()

        activate_procedure_hold(scenario["hold"]["id"])

        lunch = read_meal_period(scenario["lunch"]["id"])
        assert lunch["committed_tray_count"] == 0
        assert lunch["committed_food_cost_cents"] == 0
        assert lunch["period_overhead_cents"] == 0
        assert lunch["period_total_cost_cents"] == 0

        dinner = read_meal_period(scenario["dinner"]["id"])
        assert dinner["committed_tray_count"] == 0
        assert dinner["committed_food_cost_cents"] == 0

        rows, meta = validate_paginated(
            api.list_consults(
                CLERK,
                params={"patient_id": scenario["patient"]["id"],
                        "auto_generated": "true"},
            )
        )
        assert meta["total_count"] == 1, "at most one automatic consult per cascade"
        auto_consult = rows[0]
        assert auto_consult["status"] == "REQUESTED"
        assert auto_consult["acuity"] == "URGENT"
        assert auto_consult["requested_by_user_id"] == "SYSTEM"
        assert auto_consult["auto_generated"] is True
        assert auto_consult["reason_code"] == "MISSED_MEALS"

        assert validate_success(
            api.get_ward(scenario["ward"]["id"], MANAGER)
        )["active_patient_census"] == 0


class TestBufferedIntervalGeometry:
    def test_a_hold_starting_exactly_at_an_existing_buffered_end_is_accepted(self, api):
        """PRD §3.8: "From them the system computes the two instants that actually
        govern everything downstream: `buffered_start_at` is `hold_start_at` moved
        earlier by `buffer_before_minutes`, and `buffered_end_at` is `hold_end_at`
        moved later by `buffer_after_minutes`."
        PRD §3.8: "Two holds on the same patient whose `status` is `SCHEDULED` or
        `ACTIVE` may not occupy overlapping buffered intervals, and this comparison is
        **half-open** — the interval runs from `buffered_start_at` inclusive to
        `buffered_end_at` exclusive — so a new hold whose buffered start falls exactly
        on an existing hold's buffered end is accepted, where the closed-interval
        comparison used for meal period windows in §3.5 would have rejected it."

        Design: Difficulty/resource_temporal_overlap/procedure_hold_buffered_half_open_intervals_touch_without_colliding
        """
        ward = new_ward()
        patient = new_patient(ward["id"], mrn="MRN-I001", full_name="Ivo Petrov",
                              age_years=62)
        first = new_procedure_hold(
            patient["id"], buffer_before_minutes=30, buffer_after_minutes=30
        )
        assert_instant_equals(first["buffered_start_at"], "2026-08-02T07:30:00Z",
                              "buffered_start_at")
        assert_instant_equals(first["buffered_end_at"], "2026-08-02T10:30:00Z",
                              "buffered_end_at")

        response = api.create_procedure_hold(
            create_procedure_hold_payload(
                patient["id"],
                procedure_code="CT-02",
                npo_kind="NPO_CLEAR_LIQUIDS",
                hold_start_at="2026-08-02T10:30:00Z",
                hold_end_at="2026-08-02T12:00:00Z",
                buffer_before_minutes=0,
                buffer_after_minutes=0,
            ),
            PHYSICIAN,
        )
        touching = validate_success(response, 201)
        assert touching["status"] == "SCHEDULED"
        assert_instant_equals(touching["buffered_start_at"], "2026-08-02T10:30:00Z",
                              "buffered_start_at")

    def test_a_pre_buffer_reaching_back_into_an_existing_interval_collides(self, api):
        """PRD §3.8: "Two holds on the same patient whose `status` is `SCHEDULED` or
        `ACTIVE` may not occupy overlapping buffered intervals, and this comparison is
        **half-open** — the interval runs from `buffered_start_at` inclusive to
        `buffered_end_at` exclusive — so a new hold whose buffered start falls exactly
        on an existing hold's buffered end is accepted, where the closed-interval
        comparison used for meal period windows in §3.5 would have rejected it. A
        genuine collision is `ERR_PROCEDURE_HOLD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/procedure_hold_buffered_half_open_intervals_touch_without_colliding
        """
        ward = new_ward()
        patient = new_patient(ward["id"], mrn="MRN-I001", full_name="Ivo Petrov",
                              age_years=62)
        new_procedure_hold(
            patient["id"], buffer_before_minutes=30, buffer_after_minutes=30
        )
        new_procedure_hold(
            patient["id"],
            procedure_code="CT-02",
            npo_kind="NPO_CLEAR_LIQUIDS",
            hold_start_at="2026-08-02T10:30:00Z",
            hold_end_at="2026-08-02T12:00:00Z",
        )

        response = api.create_procedure_hold(
            create_procedure_hold_payload(
                patient["id"],
                procedure_code="US-03",
                npo_kind="NPO_STRICT",
                hold_start_at="2026-08-02T10:00:00Z",
                hold_end_at="2026-08-02T11:00:00Z",
                buffer_before_minutes=45,
                buffer_after_minutes=0,
            ),
            PHYSICIAN,
        )
        # A 45 minute pre-buffer pulls the start back to 09:15, inside [07:30, 10:30).
        validate_error(response, ApiErrorId.ERR_PROCEDURE_HOLD_OVERLAP, 409)

        _, meta = validate_paginated(
            api.list_procedure_holds(PHYSICIAN, params={"patient_id": patient["id"]})
        )
        assert meta["total_count"] == 2


class TestHoldRelease:
    def test_release_clears_npo_without_restoring_missed_trays(self, api):
        """PRD §3.8: "**Releasing** the hold moves it `ACTIVE → RELEASED`, sets
        `released_at` to the logical-clock instant, returns the patient's `npo_status`
        to `NONE` and their `active_procedure_hold_id` to null, recomputes the ward's
        `active_patient_census`, and increments both the hold's `version` and the
        patient's `version` by 1. Release is deliberately **not** a rewind: trays the
        hold pushed into `MISSED` are not resurrected, and neither `missed_meal_count`
        nor `protein_deficit_g` is unwound."

        Design: Corner/state_machines/procedure_hold_release_clears_npo_without_restoring_missed_trays
        """
        ward = new_ward()
        rule = new_diet_rule("REGULAR_STD")
        broth = new_menu_item("SOU-BRO")
        patient = new_patient(ward["id"], mrn="MRN-V001", full_name="Vera Cole",
                              age_years=72, texture_level="PUREED")
        diet_order = create_active_diet_order(patient["id"], rule["id"])
        period = new_meal_period(ward["id"])
        hold = new_procedure_hold(
            patient["id"],
            npo_kind="NPO_STRICT",
            hold_start_at="2026-08-02T06:00:00Z",
            hold_end_at="2026-08-02T20:00:00Z",
        )
        set_clock("2026-08-02T09:00:00Z")
        tray = place_tray(patient["id"], period["id"], diet_order["id"],
                          [line(broth["id"], 1)], diet_order["version"])
        validate_tray(tray["id"])
        activate_procedure_hold(hold["id"])

        released = validate_success(
            api.release_procedure_hold(hold["id"], PHYSICIAN), 200
        )
        assert released["status"] == "RELEASED"
        assert_instant_equals(released["released_at"], "2026-08-02T09:00:00Z",
                              "released_at")

        patient_after = read_patient(patient["id"])
        assert patient_after["npo_status"] == "NONE"
        assert patient_after["active_procedure_hold_id"] is None
        assert patient_after["missed_meal_count"] == 1, "the miss is not unwound"
        assert patient_after["protein_deficit_g"] == approx1(4.0)

        tray_after = read_meal_order(tray["id"])
        assert tray_after["fulfillment_status"] == "MISSED"
        assert tray_after["missed_reason"] == "NPO_HOLD"

        period_after = read_meal_period(period["id"])
        assert period_after["committed_tray_count"] == 0
        assert period_after["committed_food_cost_cents"] == 0
        assert validate_success(
            api.get_ward(ward["id"], MANAGER)
        )["active_patient_census"] == 1

        _, meta = validate_paginated(
            api.list_consults(CLERK, params={"patient_id": patient["id"]})
        )
        assert meta["total_count"] == 0, "one miss is below the escalation threshold"

    def test_cancel_frees_the_buffered_interval_for_a_later_hold(self, api):
        """PRD §3.8: "A hold that never took effect may instead be cancelled, moving
        `SCHEDULED → CANCELLED`, which increments the hold's `version` by 1 and frees
        its buffered interval for future overlap checks."
        PRD §3.8: "Two holds on the same patient whose `status` is `SCHEDULED` or
        `ACTIVE` may not occupy overlapping buffered intervals, and this comparison is
        **half-open** — the interval runs from `buffered_start_at` inclusive to
        `buffered_end_at` exclusive — so a new hold whose buffered start falls exactly
        on an existing hold's buffered end is accepted, where the closed-interval
        comparison used for meal period windows in §3.5 would have rejected it."

        Design: Corner/state_machines/procedure_hold_cancel_frees_the_buffered_interval_for_a_later_hold
        """
        ward = new_ward()
        patient = new_patient(ward["id"], mrn="MRN-W001", full_name="Wes Adler",
                              age_years=57)
        first = new_procedure_hold(patient["id"])

        cancelled = validate_success(
            api.cancel_procedure_hold(first["id"], PHYSICIAN), 200
        )
        assert cancelled["status"] == "CANCELLED"

        response = api.create_procedure_hold(
            create_procedure_hold_payload(
                patient["id"],
                procedure_code="CT-02",
                hold_start_at="2026-08-02T09:00:00Z",
                hold_end_at="2026-08-02T11:00:00Z",
            ),
            PHYSICIAN,
        )
        overlapping = validate_success(response, 201)
        assert overlapping["status"] == "SCHEDULED"

        _, meta = validate_paginated(
            api.list_procedure_holds(
                PHYSICIAN, params={"patient_id": patient["id"], "status": "SCHEDULED"}
            )
        )
        assert meta["total_count"] == 1
        assert read_patient(patient["id"])["npo_status"] == "NONE"

    def test_period_close_misses_one_tray_without_raising_a_consult(self, api):
        """PRD §3.5: "At the first cascade level, every tray in this period whose
        fulfillment dimension reads `PENDING_VALIDATION`, `VALIDATED`, `IN_PRODUCTION`
        or `PLATED` moves to `MISSED` with `missed_reason` recorded as `PERIOD_CLOSED`.
        At the second level, because each of those trays entered `MISSED`, the owning
        patient's `missed_meal_count` increments by 1 and their `protein_deficit_g`
        increases by that tray's `total_protein_g`."
        PRD §3.8: "If the patient's `missed_meal_count` has reached **two or more**,
        and no nutrition consult for that patient currently sits in `REQUESTED`,
        `ASSIGNED` or `ASSESSED`, the system raises a consult on the patient's behalf:
        `patient_id` set to the patient, `acuity` set to `URGENT`, `reason_code` set to
        the literal string `MISSED_MEALS`, `requested_by_user_id` set to the literal
        string `SYSTEM`, `auto_generated` set to true, and `status` at `REQUESTED`."

        Design: Corner/state_machines/meal_period_close_marks_single_open_tray_missed_without_auto_consult
        """
        scenario = setup_validated_tray(
            menu_keys=("SOU-BRO",),
            patient_overrides={"mrn": "MRN-Y001", "full_name": "Yara Bloom",
                               "age_years": 66, "texture_level": "PUREED"},
            forecast_variant="CENSUS_BASED",
            open_for_service=True,
        )

        closed = validate_success(
            api.close_meal_period(scenario["period"]["id"], MANAGER), 200
        )
        assert closed["status"] == "CLOSED"

        tray = read_meal_order(scenario["meal_order"]["id"])
        assert tray["fulfillment_status"] == "MISSED"
        assert tray["missed_reason"] == "PERIOD_CLOSED"

        patient = read_patient(scenario["patient"]["id"])
        assert patient["missed_meal_count"] == 1
        assert patient["protein_deficit_g"] == approx1(4.0)

        _, meta = validate_paginated(
            api.list_consults(CLERK, params={"patient_id": scenario["patient"]["id"]})
        )
        assert meta["total_count"] == 0, "one miss stays below the threshold of two"

        period = read_meal_period(scenario["period"]["id"])
        assert period["committed_tray_count"] == 0
        assert period["committed_food_cost_cents"] == 0
        assert period["delivered_tray_count"] == 0
