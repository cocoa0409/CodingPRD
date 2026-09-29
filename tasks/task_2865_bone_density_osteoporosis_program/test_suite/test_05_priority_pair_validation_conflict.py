"""One request breaking several rules at once, and only the earliest may surface.

Each request below is simultaneously wrong in two or three different ways. The
published rejection order decides which single code the caller sees, so an
implementation that checks the cheapest rule first is visible here.
"""

from test_helpers import (
    ApiErrorId,
    PHYSICIAN_HEADERS,
    ProgramWorld,
    SCHEDULER_HEADERS,
    TECHNOLOGIST_HEADERS,
    appointment_payload,
    assert_counters,
    get_success_data,
    validate_error,
    validate_paginated,
    vfa_payload,
)


def _second_booking_attempt(world: ProgramWorld):
    """A booked order re-booked into a window that also collides three ways."""
    pipeline = world.build(stop_after="booked")
    assert pipeline.appointment["status"] == "BOOKED"

    order = get_success_data(
        world.api.get_scan_order(pipeline.order_id, PHYSICIAN_HEADERS)
    )
    assert order["status"] == "SCHEDULED"

    response = world.api.create_scan_appointment(
        appointment_payload(
            pipeline.order_id,
            pipeline.device_id,
            start_utc="2026-03-10T09:10:00Z",
            end_utc="2026-03-10T09:40:00Z",
        ),
        SCHEDULER_HEADERS,
    )
    return pipeline, response


class TestOrderStateBeatsTheSchedulingCollisions:
    """The order-state rule sits above both temporal collision rules."""

    def test_the_order_state_code_surfaces_rather_than_either_collision_code(
        self, world: ProgramWorld
    ):
        """The window overlaps the buffer and the day, yet neither code is returned.

        "The referenced order is not `REQUESTED`, on `POST
        /bone-density/scan-appointments` — `ERR_ORDER_NOT_SCHEDULABLE`, 409."
        "Booking is permitted only when the order is in `status` `REQUESTED` and
        its `frequency_eligibility` is `ELIGIBLE` or `ELIGIBLE_WITH_GRACE`."

        Design: Difficulty/priority_pair_validation_conflict/order_state_check_beats_device_slot_conflict_returns_409
        """
        _, response = _second_booking_attempt(world)

        validate_error(response, ApiErrorId.ORDER_NOT_SCHEDULABLE.value, 409)

        surfaced = response.json()["data"]["error_id"]
        assert surfaced != ApiErrorId.DEVICE_SLOT_CONFLICT.value
        assert surfaced != ApiErrorId.PATIENT_DOUBLE_BOOKED.value

    def test_the_refused_booking_leaves_the_schedule_exactly_as_it_was(
        self, world: ProgramWorld
    ):
        """No second slot is persisted and the open-order counter does not move.

        "That decrement is the compensating half of the open-order invariant:
        after a book-then-cancel pair the counter reads exactly its pre-booking
        value, and it must never drift below zero."

        Design: Difficulty/priority_pair_validation_conflict/order_state_check_beats_device_slot_conflict_returns_409
        """
        pipeline, _ = _second_booking_attempt(world)

        existing = get_success_data(
            world.api.get_scan_appointment(pipeline.appointment_id, PHYSICIAN_HEADERS)
        )
        assert existing["status"] == "BOOKED"

        order = get_success_data(
            world.api.get_scan_order(pipeline.order_id, PHYSICIAN_HEADERS)
        )
        assert order["status"] == "SCHEDULED"

        assert_counters(world.read_patient(pipeline.patient_id), 1, 0)

        slots, meta = validate_paginated(
            world.api.list_scan_appointments(
                SCHEDULER_HEADERS, {"scan_order_id": pipeline.order_id}
            )
        )
        assert meta["total_count"] == 1
        assert len(slots) == 1
        assert slots[0]["id"] == pipeline.appointment_id


VFA_POLICY = {"vfa_covered": False, "vfa_requires_height_loss_cm": 4.0}
SHRUNK_BY_TWO_CENTIMETRES = {"height_cm": 163.0, "glucocorticoid_use": False}


def _vfa_session(world: ProgramWorld, vfa_requested: bool):
    """An open acquisition on a patient who matches no eligibility branch."""
    return world.build(
        stop_after="session",
        with_profile=True,
        policy_overrides=VFA_POLICY,
        profile_overrides=SHRUNK_BY_TWO_CENTIMETRES,
        order_overrides={"vfa_requested": vfa_requested},
    )


class TestVfaNotOrderedBeatsEligibilityAndCoverage:
    """The referential rule fires before either the clinical or the fiscal rule."""

    def test_an_unordered_add_on_is_refused_on_the_referential_rule(
        self, world: ProgramWorld
    ):
        """Three categories are violated at once and the referential code wins.

        "Three refusals are checked in this exact order: the add-on was never
        ordered, giving `ERR_VFA_NOT_ORDERED`; the patient does not meet clinical
        eligibility, giving `ERR_VFA_NOT_ELIGIBLE`; and the payer policy does not
        cover it, giving `ERR_VFA_NOT_COVERED`."

        Design: Difficulty/priority_pair_validation_conflict/vfa_not_ordered_beats_eligibility_and_coverage_returns_409
        """
        pipeline = _vfa_session(world, vfa_requested=False)

        response = world.api.create_vfa(
            pipeline.session_id, vfa_payload([0, 0, 0]), TECHNOLOGIST_HEADERS
        )

        validate_error(response, ApiErrorId.VFA_NOT_ORDERED.value, 409)
        surfaced = response.json()["data"]["error_id"]
        assert surfaced != ApiErrorId.VFA_NOT_ELIGIBLE.value
        assert surfaced != ApiErrorId.VFA_NOT_COVERED.value

    def test_the_refused_add_on_writes_no_vertebral_fields_onto_the_session(
        self, world: ProgramWorld
    ):
        """The session keeps its four add-on fields at their created values.

        "On success `vfa_max_genant_grade` is the largest grade submitted,
        `vfa_fracture_count` is the number of entries at grade 1 or above, and
        `vfa_performed` becomes true." "`height_loss_cm` is the patient's
        `baseline_height_cm` minus the profile's `height_cm`, rounded half up to
        one decimal place."

        Design: Difficulty/priority_pair_validation_conflict/vfa_not_ordered_beats_eligibility_and_coverage_returns_409
        """
        pipeline = _vfa_session(world, vfa_requested=False)

        world.api.create_vfa(
            pipeline.session_id, vfa_payload([0, 0, 0]), TECHNOLOGIST_HEADERS
        )

        session = world.read_session(pipeline.session_id)
        assert session["vfa_performed"] is False
        assert session["vfa_eligibility_code"] is None
        assert session["vfa_max_genant_grade"] is None
        assert session["vfa_fracture_count"] is None

        assert pipeline.profile["height_loss_cm"] == 2.0


class TestVfaEligibilityBeatsPayerCoverage:
    """With the add-on ordered, the clinical rule still outranks the fiscal one."""

    def test_an_ineligible_patient_gets_the_clinical_code_not_the_payment_code(
        self, world: ProgramWorld
    ):
        """A 409 rather than a 402, even though the policy funds nothing here.

        "That the fiscal band sits at the bottom has a visible consequence worth
        stating outright: a patient who meets no clinical criterion for a
        vertebral fracture assessment *and* whose policy does not cover it
        receives `ERR_VFA_NOT_ELIGIBLE`, never `ERR_VFA_NOT_COVERED`." "Clinical
        eligibility precedes coverage deliberately — the program refuses to tell a
        payer it declined a study the patient did not qualify for."

        Design: Difficulty/priority_pair_validation_conflict/vfa_eligibility_beats_payer_coverage_returns_409
        """
        pipeline = _vfa_session(world, vfa_requested=True)

        response = world.api.create_vfa(
            pipeline.session_id, vfa_payload([0, 1, 2]), TECHNOLOGIST_HEADERS
        )

        validate_error(response, ApiErrorId.VFA_NOT_ELIGIBLE.value, 409)
        assert response.status_code != 402
        assert response.json()["data"]["error_id"] != ApiErrorId.VFA_NOT_COVERED.value

    def test_no_eligibility_branch_matches_so_nothing_is_recorded(
        self, world: ProgramWorld
    ):
        """Height loss below the threshold, no steroids, and under seventy.

        "`vfa_eligibility_code` is decided by the first matching test against the
        patient's active risk-factor profile: a `height_loss_cm` at or above the
        policy's `vfa_requires_height_loss_cm` gives `ELIGIBLE_HEIGHT_LOSS`;
        otherwise a true `glucocorticoid_use` gives `ELIGIBLE_GLUCOCORTICOID`;
        otherwise an age of at least seventy years gives `ELIGIBLE_AGE_THRESHOLD`;
        otherwise the code is `NOT_ELIGIBLE` and the request is refused."

        Design: Difficulty/priority_pair_validation_conflict/vfa_eligibility_beats_payer_coverage_returns_409
        """
        pipeline = _vfa_session(world, vfa_requested=True)

        world.api.create_vfa(
            pipeline.session_id, vfa_payload([0, 1, 2]), TECHNOLOGIST_HEADERS
        )

        session = world.read_session(pipeline.session_id)
        assert session["vfa_performed"] is False
        assert session["vfa_eligibility_code"] is None
        assert session["vfa_max_genant_grade"] is None

        order = get_success_data(
            world.api.get_scan_order(pipeline.order_id, PHYSICIAN_HEADERS)
        )
        assert order["vfa_requested"] is True
        assert pipeline.policy["vfa_covered"] is False
