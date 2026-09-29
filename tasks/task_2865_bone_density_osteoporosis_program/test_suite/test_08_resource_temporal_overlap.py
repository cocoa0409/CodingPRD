"""Two different collision rules over the same booking endpoint.

The device rule pads every occupied interval on both sides and compares
instants; the patient rule ignores instants altogether and buckets by UTC
calendar date across every instrument.
"""

from test_helpers import (
    ApiErrorId,
    PHYSICIAN_HEADERS,
    ProgramWorld,
    SCHEDULER_HEADERS,
    appointment_payload,
    assert_counters,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

SCAN_DATE = "2026-03-10"
INCUMBENT_START = SCAN_DATE + "T09:00:00Z"
INCUMBENT_END = SCAN_DATE + "T09:30:00Z"


def _three_patients_one_incumbent_slot(world: ProgramWorld):
    """One booked nine o'clock slot, plus two more patients waiting to be placed."""
    pipeline = world.build(stop_after="booked")
    assert pipeline.appointment["slot_index"] == 1

    second_patient = world.create_patient(pipeline.policy_id)
    second_order = world.create_order(
        second_patient["id"], requested_scan_date=SCAN_DATE
    )
    third_patient = world.create_patient(pipeline.policy_id)
    third_order = world.create_order(
        third_patient["id"], requested_scan_date=SCAN_DATE
    )
    return pipeline, second_order, third_order


def _attempt_slot(world: ProgramWorld, order_id: str, device_id: str, start: str, end: str):
    """Ask for one window on one device without unwrapping the response."""
    return world.api.create_scan_appointment(
        appointment_payload(order_id, device_id, start_utc=start, end_utc=end),
        SCHEDULER_HEADERS,
    )


class TestDeviceBufferRejectsInsideTheGap:
    """The padded interval is 08:45 to 09:45, and the test is strict on both halves."""

    def test_windows_inside_the_buffer_are_refused_on_both_sides(
        self, world: ProgramWorld
    ):
        """09:40 does not touch the raw interval yet still collides; 08:30 abuts it.

        "The overlap test applies the device's own `appointment_buffer_minutes`
        symmetrically, on **both** sides of every occupied interval: an existing
        appointment on the same `densitometer_id` in `status` `BOOKED` or
        `CHECKED_IN` conflicts when the new start falls before the existing end
        extended by the buffer **and** the existing start falls before the new end
        extended by the buffer, which is refused with `ERR_DEVICE_SLOT_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/device_buffer_rejects_slots_inside_the_gap_but_admits_exact_adjacency
        """
        pipeline, second_order, third_order = _three_patients_one_incumbent_slot(world)

        trailing = _attempt_slot(
            world,
            second_order["id"],
            pipeline.device_id,
            SCAN_DATE + "T09:40:00Z",
            SCAN_DATE + "T10:10:00Z",
        )
        validate_error(trailing, ApiErrorId.DEVICE_SLOT_CONFLICT.value, 409)

        leading = _attempt_slot(
            world,
            third_order["id"],
            pipeline.device_id,
            SCAN_DATE + "T08:30:00Z",
            SCAN_DATE + "T09:00:00Z",
        )
        validate_error(leading, ApiErrorId.DEVICE_SLOT_CONFLICT.value, 409)

    def test_windows_exactly_one_buffer_clear_are_admitted_and_reindex_the_day(
        self, world: ProgramWorld
    ):
        """09:45 and 08:45 touch the padded edge exactly, so both are accepted.

        "It also assigns `slot_index`: the 1-based position of this appointment
        among all appointments on the same `densitometer_id` whose `start_utc`
        falls on the same UTC calendar date ... inserting a slot earlier in the day
        shifts the later ones up."

        Design: Difficulty/resource_temporal_overlap/device_buffer_rejects_slots_inside_the_gap_but_admits_exact_adjacency
        """
        pipeline, second_order, third_order = _three_patients_one_incumbent_slot(world)

        trailing = validate_success(
            _attempt_slot(
                world,
                second_order["id"],
                pipeline.device_id,
                SCAN_DATE + "T09:45:00Z",
                SCAN_DATE + "T10:15:00Z",
            ),
            201,
        )
        assert trailing["status"] == "BOOKED"
        assert trailing["scheduled_duration_minutes"] == 30

        leading = validate_success(
            _attempt_slot(
                world,
                third_order["id"],
                pipeline.device_id,
                SCAN_DATE + "T08:15:00Z",
                SCAN_DATE + "T08:45:00Z",
            ),
            201,
        )
        assert leading["status"] == "BOOKED"
        assert leading["scheduled_duration_minutes"] == 30

        slots, meta = validate_paginated(
            world.api.list_scan_appointments(
                SCHEDULER_HEADERS,
                {"densitometer_id": pipeline.device_id, "status": "BOOKED"},
            )
        )
        assert meta["total_count"] == 3
        assert [slot["slot_index"] for slot in slots] == [1, 2, 3]
        assert slots[0]["id"] == leading["id"]
        assert slots[1]["id"] == pipeline.appointment_id
        assert slots[2]["id"] == trailing["id"]

        incumbent = get_success_data(
            world.api.get_scan_appointment(pipeline.appointment_id, PHYSICIAN_HEADERS)
        )
        assert incumbent["status"] == "BOOKED"
        assert incumbent["slot_index"] == 2

        for order in (second_order, third_order):
            refreshed = get_success_data(
                world.api.get_scan_order(order["id"], PHYSICIAN_HEADERS)
            )
            assert refreshed["status"] == "SCHEDULED"

        assert_counters(world.read_patient(pipeline.patient_id), 1, 0)
        assert_counters(world.read_patient(second_order["patient_id"]), 1, 0)
        assert_counters(world.read_patient(third_order["patient_id"]), 1, 0)


def _one_patient_two_orders_two_devices(world: ProgramWorld):
    """A patient booked on the first instrument, with a second order still open."""
    pipeline = world.build(stop_after="booked")
    second_device = world.create_certified_device()
    second_order = world.create_order(
        pipeline.patient_id, requested_scan_date=SCAN_DATE
    )
    return pipeline, second_device, second_order


class TestPatientSameDayRuleIsADateBucket:
    """The patient bucket is closed over every device and keyed on the UTC date."""

    def test_a_second_slot_on_another_device_the_same_day_is_refused(
        self, world: ProgramWorld
    ):
        """Eleven hours clear and a different instrument, yet still a double booking.

        "Separately, a patient may hold only one live slot per UTC calendar date:
        another appointment for the same patient in `status` `BOOKED` or
        `CHECKED_IN` whose `start_utc` falls on the same UTC date is refused with
        `ERR_PATIENT_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/patient_same_day_rule_rejects_second_device_but_admits_next_day
        """
        pipeline, second_device, second_order = _one_patient_two_orders_two_devices(
            world
        )

        same_day = _attempt_slot(
            world,
            second_order["id"],
            second_device["id"],
            SCAN_DATE + "T14:00:00Z",
            SCAN_DATE + "T14:30:00Z",
        )

        validate_error(same_day, ApiErrorId.PATIENT_DOUBLE_BOOKED.value, 409)

        incumbent = get_success_data(
            world.api.get_scan_appointment(pipeline.appointment_id, PHYSICIAN_HEADERS)
        )
        assert incumbent["status"] == "BOOKED"
        assert_counters(world.read_patient(pipeline.patient_id), 1, 0)

    def test_the_identical_window_on_the_next_day_is_admitted(
        self, world: ProgramWorld
    ):
        """Moving the same request forward one calendar date clears the bucket.

        "A successful booking creates the slot in `status` `BOOKED`, moves the
        order from `REQUESTED` to `SCHEDULED`, increments the patient's
        `open_scheduled_order_count` by one — the forward half of the open-order
        invariant — and clears `reschedule_required` to false."

        Design: Difficulty/resource_temporal_overlap/patient_same_day_rule_rejects_second_device_but_admits_next_day
        """
        pipeline, second_device, second_order = _one_patient_two_orders_two_devices(
            world
        )

        next_day = validate_success(
            _attempt_slot(
                world,
                second_order["id"],
                second_device["id"],
                "2026-03-11T14:00:00Z",
                "2026-03-11T14:30:00Z",
            ),
            201,
        )

        assert next_day["status"] == "BOOKED"
        assert next_day["slot_index"] == 1

        for order_id in (pipeline.order_id, second_order["id"]):
            refreshed = get_success_data(
                world.api.get_scan_order(order_id, PHYSICIAN_HEADERS)
            )
            assert refreshed["status"] == "SCHEDULED"

        assert_counters(world.read_patient(pipeline.patient_id), 2, 0)

        slots, meta = validate_paginated(
            world.api.list_scan_appointments(
                SCHEDULER_HEADERS,
                {"densitometer_id": second_device["id"], "status": "BOOKED"},
            )
        )
        assert meta["total_count"] == 1
        assert slots[0]["id"] == next_day["id"]
