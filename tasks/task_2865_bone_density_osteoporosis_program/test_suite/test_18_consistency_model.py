"""One booking, and every field it moves read back in the calls that follow it.

The interesting row here is the one the caller never names: an appointment booked
earlier in the setup is renumbered by a booking that addresses a different order,
and that renumbering is already visible on the very next read.
"""

from test_helpers import (
    ProgramWorld,
    SCHEDULER_HEADERS,
    appointment_payload,
    assert_counters,
    validate_paginated,
    validate_success,
)

CLOCK_START = "2026-03-02T08:00:00Z"
SCAN_DATE = "2026-03-10"
LATE_SLOT_START = "2026-03-10T11:00:00Z"
LATE_SLOT_END = "2026-03-10T11:30:00Z"
EARLY_SLOT_START = "2026-03-10T09:00:00Z"
EARLY_SLOT_END = "2026-03-10T09:30:00Z"
DAY_FROM_UTC = "2026-03-10T00:00:00Z"
DAY_TO_UTC = "2026-03-11T00:00:00Z"


def _one_device_two_patients_and_the_late_slot_taken(world: ProgramWorld):
    """Two patients on one certified device, the eleven-o'clock slot already booked."""
    world.set_clock(CLOCK_START)
    policy = world.create_policy()
    device = world.create_certified_device()
    patient_a = world.create_patient(policy["id"], mrn="MRN-8101")
    patient_b = world.create_patient(
        policy["id"],
        mrn="MRN-8102",
        birth_date="1961-09-09",
        baseline_height_cm=158.0,
    )
    order_a = world.create_order(patient_a["id"], requested_scan_date=SCAN_DATE)
    order_b = world.create_order(patient_b["id"], requested_scan_date=SCAN_DATE)

    appointment_a = validate_success(
        world.api.create_scan_appointment(
            appointment_payload(
                order_a["id"],
                device["id"],
                start_utc=LATE_SLOT_START,
                end_utc=LATE_SLOT_END,
            ),
            SCHEDULER_HEADERS,
        ),
        201,
    )
    assert appointment_a["status"] == "BOOKED"
    assert appointment_a["slot_index"] == 1
    assert appointment_a["scheduled_duration_minutes"] == 30
    assert (
        validate_success(
            world.api.get_scan_order(order_a["id"], SCHEDULER_HEADERS), 200
        )["status"]
        == "SCHEDULED"
    )

    return device, patient_a, patient_b, order_b, appointment_a


class TestBookingPublishesEveryDerivedFieldAtOnce:
    """No read-after-write lag: the cascade is complete before the response returns."""

    def test_the_earlier_slot_takes_index_one_and_renumbers_the_slot_nobody_named(
        self, world: ProgramWorld
    ):
        """A row untouched by the request reads back renumbered on the next call.

        "It also assigns `slot_index`: the 1-based position of this appointment among all
        appointments on the same `densitometer_id` whose `start_utc` falls on the same UTC
        calendar date and whose `status` is `BOOKED`, `CHECKED_IN` or `COMPLETED`, ordered
        by `start_utc` ascending and then `created_at` ascending. Because the index is
        positional rather than assigned, it is recomputed for every affected sibling
        whenever that day's set changes: inserting a slot earlier in the day shifts the
        later ones up, and cancelling one shifts them back down."
        "A successful booking creates the slot in `status` `BOOKED`, moves the order from
        `REQUESTED` to `SCHEDULED`, increments the patient's `open_scheduled_order_count`
        by one — the forward half of the open-order invariant — and clears
        `reschedule_required` to false."
        "`open_scheduled_order_count` must always equal the number of that patient's
        orders whose `status` is `SCHEDULED`."

        Design: Corner/consistency_model/booking_a_slot_publishes_every_derived_field_in_the_same_response_cycle
        """
        (
            device,
            patient_a,
            patient_b,
            order_b,
            appointment_a,
        ) = _one_device_two_patients_and_the_late_slot_taken(world)

        appointment_b = validate_success(
            world.api.create_scan_appointment(
                appointment_payload(
                    order_b["id"],
                    device["id"],
                    start_utc=EARLY_SLOT_START,
                    end_utc=EARLY_SLOT_END,
                ),
                SCHEDULER_HEADERS,
            ),
            201,
        )
        assert appointment_b["status"] == "BOOKED"
        assert appointment_b["slot_index"] == 1
        assert appointment_b["scheduled_duration_minutes"] == 30

        renumbered = validate_success(
            world.api.get_scan_appointment(appointment_a["id"], SCHEDULER_HEADERS), 200
        )
        assert renumbered["slot_index"] == 2
        assert renumbered["status"] == "BOOKED"

        assert_counters(world.read_patient(patient_b["id"]), 1, 0)

        booked_order = validate_success(
            world.api.get_scan_order(order_b["id"], SCHEDULER_HEADERS), 200
        )
        assert booked_order["status"] == "SCHEDULED"
        assert booked_order["reschedule_required"] is False

        assert_counters(world.read_patient(patient_a["id"]), 1, 0)

        rows, meta = validate_paginated(
            world.api.list_scan_appointments(
                SCHEDULER_HEADERS,
                {
                    "densitometer_id": device["id"],
                    "from_utc": DAY_FROM_UTC,
                    "to_utc": DAY_TO_UTC,
                },
            )
        )
        assert meta["total_count"] == 2
        assert sorted(row["slot_index"] for row in rows) == [1, 2]
        by_id = {row["id"]: row["slot_index"] for row in rows}
        assert by_id[appointment_b["id"]] == 1
        assert by_id[appointment_a["id"]] == 2
