"""Booking the shop floor: stall windows, calibration bay slots and the minutes ledger.

A stall is a single-capacity resource ringed by a closed cleanup buffer, while a
calibration bay is an aggregate resource with no buffer at all and half-open
window overlap. Both keep a derived occupancy figure that has to rise on every
booking, sit still when a booking is merely promoted, and fall by exactly the
finished window's length when the work moves on.
"""

from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TECHNICIAN_HEADERS

T0630 = "2026-08-01T06:30:00Z"
T0730 = "2026-08-01T07:30:00Z"
T1130 = "2026-08-01T11:30:00Z"
T1030 = "2026-08-01T10:30:00Z"


def _try_book(api, order_id: str, stall_id: str, stage: str, start: str, end: str):
    """Attempt a stall booking and hand back the raw response for inspection."""
    return api.create_stage_assignment(
        order_id,
        f.stage_assignment_payload(stall_id, stage, start, end),
        TECHNICIAN_HEADERS,
    )


def _try_schedule(api, record_id: str, bay_id: str, start: str, end: str):
    """Attempt a calibration booking and hand back the raw response."""
    return api.schedule_calibration(
        record_id,
        f.calibration_schedule_payload(bay_id, start, end),
        TECHNICIAN_HEADERS,
    )


def _booked_minutes(api, stall_id: str) -> int:
    return fx.read_stall(api, stall_id)["booked_minutes"]


def _scheduled_window_count(api, bay_id: str) -> int:
    return fx.read_bay(api, bay_id)["scheduled_window_count"]


def _locked_order_on_a_body_line(api, customer_id: str, insurer_id: str) -> Dict[str, Any]:
    """One repair order carried from intake to a committed estimate."""
    order = fx.create_repair_order(api, customer_id, insurer_id, deductible_cents=25000)
    fx.add_finding(api, order["id"], panel_code="L_FRONT_DOOR", severity="MODERATE")
    fx.add_estimate_line(api, order["id"], labor_type="BODY", guide_hours=4.5)
    fx.publish_blueprint(api, order["id"])
    return fx.lock_estimate(api, order["id"])


def _stall_world(api, **stall_overrides: Any) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A locked order to own the bookings, plus one stall to consume."""
    world = fx.locked_world(api, order_overrides={"deductible_cents": 25000})
    stall = fx.create_stall(api, **stall_overrides)
    return world, stall


class TestStallCleanupBuffer:
    """The dead time a stall needs for masking and cleanup, at its exact edge."""

    def test_a_stall_booking_exactly_one_cleanup_buffer_after_the_previous_window_is_refused(self, api):
        """A body stall booked to start the very minute the buffer runs out is turned away.

        PRD: "Finally, no other booking on the same stall whose `status` is `SCHEDULED` or `ACTIVE` may come within the stall's `cleanup_buffer_minutes` of the requested window on either side; a violation is refused with `ERR_STALL_WINDOW_CONFLICT`."
        PRD: "That buffer is symmetric and its exclusion zone is **closed**, which means a window starting exactly `cleanup_buffer_minutes` after an existing window ends is still refused, while one starting a single minute later is accepted."
        Design: Difficulty/resource_temporal_overlap/stall_booking_refused_at_exactly_the_cleanup_buffer_gap
        """
        world, stall = _stall_world(api, name="Body 6", stall_type="BODY", cleanup_buffer_minutes=30)
        order_id = world["order_id"]

        first = fx.book_stall(api, order_id, stall["id"], "REPAIR", fx.T0800, fx.T1200)
        assert first["status"] == "SCHEDULED"
        A.assert_count(first["occupied_minutes"], 240, "occupied_minutes")
        A.assert_count(_booked_minutes(api, stall["id"]), 240, "booked_minutes")

        # 12:00 plus exactly the 30-minute buffer: the far edge is still inside the zone.
        validate_error(
            _try_book(api, order_id, stall["id"], "REPAIR", fx.T1230, fx.T1400),
            ApiErrorId.STALL_WINDOW_CONFLICT.value,
            409,
        )

        # The refusal left no trace, and the buffer never inflated the occupancy figure.
        A.assert_count(
            fx.read_assignment(api, first["id"])["occupied_minutes"], 240, "occupied_minutes"
        )
        A.assert_count(_booked_minutes(api, stall["id"]), 240, "booked_minutes")

        # The same gap on the other side of the existing window is refused too.
        validate_error(
            _try_book(api, order_id, stall["id"], "REPAIR", T0630, T0730),
            ApiErrorId.STALL_WINDOW_CONFLICT.value,
            409,
        )
        A.assert_count(_booked_minutes(api, stall["id"]), 240, "booked_minutes")

    def test_a_stall_booking_one_minute_past_the_cleanup_buffer_is_accepted(self, api):
        """One minute of extra breathing room and the second occupancy is taken.

        PRD: "That buffer is symmetric and its exclusion zone is **closed**, which means a window starting exactly `cleanup_buffer_minutes` after an existing window ends is still refused, while one starting a single minute later is accepted."
        PRD: "A successful booking is created with `status` `SCHEDULED` and an `occupied_minutes` fixed at creation as the whole minutes, floored, between its `window_start` and its `window_end`."
        Design: Difficulty/resource_temporal_overlap/stall_booking_refused_at_exactly_the_cleanup_buffer_gap
        """
        world, stall = _stall_world(api, name="Body 6", stall_type="BODY", cleanup_buffer_minutes=30)
        order_id = world["order_id"]

        first = fx.book_stall(api, order_id, stall["id"], "REPAIR", fx.T0800, fx.T1200)
        A.assert_count(first["occupied_minutes"], 240, "occupied_minutes")
        A.assert_count(_booked_minutes(api, stall["id"]), 240, "booked_minutes")

        second = validate_success(
            _try_book(api, order_id, stall["id"], "REPAIR", fx.T1231, fx.T1400), 201
        )
        assert second["status"] == "SCHEDULED"
        A.assert_count(second["occupied_minutes"], 89, "occupied_minutes")
        A.assert_instant(second["window_start"], fx.T1231, "window_start")
        A.assert_instant(second["window_end"], fx.T1400, "window_end")

        # 240 plus 89, with no room made for the buffer itself.
        A.assert_count(_booked_minutes(api, stall["id"]), 329, "booked_minutes")


def _bay_world_with_two_booked_windows(api):
    """A two-capacity static bay holding two overlapping windows, plus a third target."""
    world = fx.open_order_world(api, order_overrides={"deductible_cents": 25000})
    bay = fx.create_bay(api, name="Bay C", supported_types=["STATIC"], concurrent_capacity=2)
    records = [
        fx.add_procedure_record(
            api,
            world["order_id"],
            procedure_code=f"ADAS-CAL-{suffix}",
            source="OEM_PORTAL",
            operation_scope="ADAS",
            requires_calibration=True,
            calibration_type="STATIC",
        )
        for suffix in ("A", "B", "C")
    ]
    for record in records:
        assert record["calibration_status"] == "REQUIRED"

    fx.schedule_calibration(api, records[0]["id"], bay["id"], fx.T0900, fx.T1100)
    fx.schedule_calibration(api, records[1]["id"], bay["id"], fx.T1000, fx.T1200)
    A.assert_count(_scheduled_window_count(api, bay["id"]), 2, "scheduled_window_count")
    return world, bay, records


class TestCalibrationBayCapacity:
    """The bay counts simultaneous setups, and touching windows are not simultaneous."""

    def test_a_calibration_window_that_only_touches_an_earlier_window_is_booked(self, api):
        """A window opening on the instant an earlier one closes overlaps only one neighbour.

        PRD: "Overlap here is half-open — a window runs from its start inclusive to its end exclusive — there is no buffer at all, and two windows that merely touch at a single instant do not overlap."
        PRD: "A successful booking sets `bay_id`, `window_start` and `window_end` on the record, recomputes the bay's `scheduled_window_count`, and increments both the record's `version` and the bay's `version`."
        Design: Difficulty/resource_temporal_overlap/calibration_bay_capacity_counts_only_strictly_overlapping_windows
        """
        world, bay, records = _bay_world_with_two_booked_windows(api)
        third = records[2]

        # 11:00 is the exclusive end of the 09:00-11:00 window, so only 10:00-12:00 overlaps.
        booked = validate_success(_try_schedule(api, third["id"], bay["id"], fx.T1100, T1130), 200)
        assert booked["calibration_status"] == "SCHEDULED"
        assert booked["bay_id"] == bay["id"]
        A.assert_instant(booked["window_start"], fx.T1100, "window_start")
        A.assert_instant(booked["window_end"], T1130, "window_end")

        A.assert_count(_scheduled_window_count(api, bay["id"]), 3, "scheduled_window_count")

    def test_a_third_calibration_window_straddling_both_bookings_exceeds_the_bay_capacity(self, api):
        """A window genuinely simultaneous with two others is the one the bay refuses.

        PRD: "Finally, the number of procedure records already booked into that bay with `calibration_status` `SCHEDULED` whose windows *strictly overlap* the requested window must be **fewer than** the bay's `concurrent_capacity`; when that count has already reached the capacity the booking is refused with `ERR_CALIBRATION_BAY_CAPACITY_EXCEEDED`."
        PRD: "A pass sets `post_scan_dtc_count` and `scan_report_ref`, recomputes the bay's `scheduled_window_count` because the window is released, and increments the record's `version` and the bay's `version`."
        Design: Difficulty/resource_temporal_overlap/calibration_bay_capacity_counts_only_strictly_overlapping_windows
        """
        world, bay, records = _bay_world_with_two_booked_windows(api)
        third = records[2]

        validate_error(
            _try_schedule(api, third["id"], bay["id"], T1030, T1130),
            ApiErrorId.CALIBRATION_BAY_CAPACITY_EXCEEDED.value,
            409,
        )

        refused = fx.read_procedure_record(api, third["id"])
        assert refused["calibration_status"] == "REQUIRED"
        A.assert_null(refused["bay_id"], "bay_id")
        A.assert_count(_scheduled_window_count(api, bay["id"]), 2, "scheduled_window_count")

        # Passing the first target releases its window, so the aggregate count drops to one.
        passed = fx.record_calibration_result(api, records[0]["id"], "PASS", 0, scan_report_ref="SCAN-1")
        assert passed["calibration_status"] == "PASSED"
        A.assert_count(_scheduled_window_count(api, bay["id"]), 1, "scheduled_window_count")

        now_booked = validate_success(_try_schedule(api, third["id"], bay["id"], T1030, T1130), 200)
        assert now_booked["calibration_status"] == "SCHEDULED"
        A.assert_count(_scheduled_window_count(api, bay["id"]), 2, "scheduled_window_count")


class TestAssignmentCancellation:
    """Releasing a booking that never started must leave the stall exactly as it was."""

    def test_cancelling_a_booking_returns_the_stall_to_its_pre_booking_minutes(self, api):
        """Book, release, and book the identical window again without any drift.

        PRD: "It moves the booking to `CANCELLED` and lowers the stall's `booked_minutes` by exactly the booking's `occupied_minutes`, restoring the stall to the value it held before the booking existed; both the booking's `version` and the stall's `version` increment."
        PRD: "A stall's `booked_minutes` always equals the sum of `occupied_minutes` over the bookings on that stall whose `status` is `SCHEDULED` or `ACTIVE`; bookings that are `COMPLETED` or `CANCELLED` contribute nothing."
        Design: Difficulty/compensating_invariant/assignment_cancel_restores_stall_booked_minutes_exactly
        """
        world, stall = _stall_world(api, name="Body 7", stall_type="BODY", cleanup_buffer_minutes=30)
        order_id = world["order_id"]
        A.assert_count(_booked_minutes(api, stall["id"]), 0, "booked_minutes")

        booking = fx.book_stall(api, order_id, stall["id"], "REPAIR", fx.T0800, fx.T1200)
        A.assert_count(booking["occupied_minutes"], 240, "occupied_minutes")
        A.assert_count(_booked_minutes(api, stall["id"]), 240, "booked_minutes")

        released = validate_success(
            api.cancel_stage_assignment(booking["id"], None, TECHNICIAN_HEADERS), 200
        )
        assert released["status"] == "CANCELLED"
        A.assert_count(released["occupied_minutes"], 240, "occupied_minutes")
        A.assert_count(_booked_minutes(api, stall["id"]), 0, "booked_minutes")

        # The released window is out of the conflict set, so the same interval is bookable.
        again = validate_success(
            _try_book(api, order_id, stall["id"], "REPAIR", fx.T0800, fx.T1200), 201
        )
        assert again["status"] == "SCHEDULED"
        A.assert_count(again["occupied_minutes"], 240, "occupied_minutes")
        A.assert_count(_booked_minutes(api, stall["id"]), 240, "booked_minutes")

    def test_a_released_booking_cannot_be_released_a_second_time(self, api):
        """The minutes come back once, so a repeat release is refused outright.

        PRD: "Cancellation requires `status` `SCHEDULED`, and a booking that is `ACTIVE`, `COMPLETED` or already `CANCELLED` is refused with `ERR_ASSIGNMENT_NOT_SCHEDULED`."
        PRD: "It moves the booking to `CANCELLED` and lowers the stall's `booked_minutes` by exactly the booking's `occupied_minutes`, restoring the stall to the value it held before the booking existed; both the booking's `version` and the stall's `version` increment."
        Design: Difficulty/compensating_invariant/assignment_cancel_restores_stall_booked_minutes_exactly
        """
        world, stall = _stall_world(api, name="Body 7", stall_type="BODY", cleanup_buffer_minutes=30)
        booking = fx.book_stall(api, world["order_id"], stall["id"], "REPAIR", fx.T0800, fx.T1200)
        fx.cancel_assignment(api, booking["id"])
        A.assert_count(_booked_minutes(api, stall["id"]), 0, "booked_minutes")

        validate_error(
            api.cancel_stage_assignment(booking["id"], None, TECHNICIAN_HEADERS),
            ApiErrorId.ASSIGNMENT_NOT_SCHEDULED.value,
            409,
        )

        assert fx.read_assignment(api, booking["id"])["status"] == "CANCELLED"
        A.assert_count(_booked_minutes(api, stall["id"]), 0, "booked_minutes")


class TestServerDrivenPromotion:
    """The server promotes and retires bookings as the vehicle moves between stages."""

    def test_entering_repair_activates_the_booking_without_charging_the_stall_twice(self, api):
        """Activation is free; only leaving the stage gives the minutes back.

        PRD: "When an order enters the stage a `SCHEDULED` booking serves, that booking becomes `ACTIVE` and its `version` increments — but the stall's `booked_minutes` is *unchanged*, because `SCHEDULED` and `ACTIVE` both occupy the stall."
        PRD: "On success, every `ACTIVE` `REPAIR` booking on the order becomes `COMPLETED` and releases its `occupied_minutes` from its stall, every `SCHEDULED` `REFINISH_CALIBRATION` booking becomes `ACTIVE`, and the order's `version` increments."
        Design: Corner/state_machines/scheduled_assignment_activates_without_changing_booked_minutes
        """
        world = fx.locked_world(api, order_overrides={"deductible_cents": 25000})
        order_id = world["order_id"]
        body_stall = fx.create_stall(api, name="Body I", stall_type="BODY")
        paint_stall = fx.create_stall(api, name="Paint I", stall_type="PAINT")
        fx.advance_stage(api, order_id, "PARTS_STAGED")

        repair_booking = fx.book_stall(api, order_id, body_stall["id"], "REPAIR", fx.T0800, fx.T1200)
        refinish_booking = fx.book_stall(
            api, order_id, paint_stall["id"], "REFINISH_CALIBRATION", fx.T1300, fx.T1500
        )
        A.assert_count(repair_booking["occupied_minutes"], 240, "occupied_minutes")
        A.assert_count(refinish_booking["occupied_minutes"], 120, "occupied_minutes")
        A.assert_count(_booked_minutes(api, body_stall["id"]), 240, "booked_minutes")
        A.assert_count(_booked_minutes(api, paint_stall["id"]), 120, "booked_minutes")

        in_repair = fx.advance_stage(api, order_id, "REPAIR")
        A.assert_stage(in_repair, "REPAIR")

        activated = fx.read_assignment(api, repair_booking["id"])
        assert activated["status"] == "ACTIVE"
        A.assert_count(activated["occupied_minutes"], 240, "occupied_minutes")
        A.assert_count(_booked_minutes(api, body_stall["id"]), 240, "booked_minutes")

        # Only the stage just entered is promoted; the paint booking waits its turn.
        waiting = fx.read_assignment(api, refinish_booking["id"])
        assert waiting["status"] == "SCHEDULED"
        A.assert_count(_booked_minutes(api, paint_stall["id"]), 120, "booked_minutes")

        in_refinish = fx.advance_stage(api, order_id, "REFINISH_CALIBRATION")
        A.assert_stage(in_refinish, "REFINISH_CALIBRATION")

        retired = fx.read_assignment(api, repair_booking["id"])
        assert retired["status"] == "COMPLETED"
        A.assert_count(retired["occupied_minutes"], 240, "occupied_minutes")
        A.assert_count(_booked_minutes(api, body_stall["id"]), 0, "booked_minutes")

        promoted = fx.read_assignment(api, refinish_booking["id"])
        assert promoted["status"] == "ACTIVE"
        A.assert_count(promoted["occupied_minutes"], 120, "occupied_minutes")
        A.assert_count(_booked_minutes(api, paint_stall["id"]), 120, "booked_minutes")


class TestSharedStallOccupancy:
    """One stall, two vehicles, and a minutes figure that has to stay honest."""

    def test_two_orders_sharing_one_stall_release_only_their_own_minutes(self, api):
        """The body stall's minutes walk 0, 240, 240, 360 and back to 120 as the day runs.

        PRD: "A stall's `booked_minutes` always equals the sum of `occupied_minutes` over the bookings on that stall whose `status` is `SCHEDULED` or `ACTIVE`; bookings that are `COMPLETED` or `CANCELLED` contribute nothing."
        PRD: "On success, every `ACTIVE` `REPAIR` booking on the order becomes `COMPLETED` and releases its `occupied_minutes` from its stall, every `SCHEDULED` `REFINISH_CALIBRATION` booking becomes `ACTIVE`, and the order's `version` increments."
        Design: Corner/cross_cutting_complexity_layers/stall_booked_minutes_reconcile_across_two_orders_sharing_a_stall
        """
        fx.set_clock(api, C.CLOCK_DEFAULT)
        customer = fx.create_customer(api, full_name="Nel Ober")
        insurer = fx.create_insurer(api, name="Cornerstone Mutual")
        shared_stall = fx.create_stall(api, name="Body S", stall_type="BODY")
        paint_stall = fx.create_stall(api, name="Paint S", stall_type="PAINT")
        A.assert_count(_booked_minutes(api, shared_stall["id"]), 0, "booked_minutes")

        # The first vehicle takes the morning window and drives into repair.
        order_x = _locked_order_on_a_body_line(api, customer["id"], insurer["id"])
        fx.advance_stage(api, order_x["id"], "PARTS_STAGED")
        booking_x = fx.book_stall(
            api, order_x["id"], shared_stall["id"], "REPAIR", fx.T0800, fx.T1200
        )
        A.assert_count(booking_x["occupied_minutes"], 240, "occupied_minutes")
        A.assert_count(_booked_minutes(api, shared_stall["id"]), 240, "booked_minutes")

        fx.advance_stage(api, order_x["id"], "REPAIR")
        assert fx.read_assignment(api, booking_x["id"])["status"] == "ACTIVE"
        A.assert_count(_booked_minutes(api, shared_stall["id"]), 240, "booked_minutes")

        # The second vehicle reserves the afternoon window in the very same stall.
        order_y = _locked_order_on_a_body_line(api, customer["id"], insurer["id"])
        fx.advance_stage(api, order_y["id"], "PARTS_STAGED")
        booking_y = fx.book_stall(
            api, order_y["id"], shared_stall["id"], "REPAIR", fx.T1300, fx.T1500
        )
        A.assert_count(booking_y["occupied_minutes"], 120, "occupied_minutes")
        A.assert_count(_booked_minutes(api, shared_stall["id"]), 360, "booked_minutes")

        booking_paint = fx.book_stall(
            api, order_x["id"], paint_stall["id"], "REFINISH_CALIBRATION", fx.T1300, fx.T1500
        )
        A.assert_count(_booked_minutes(api, paint_stall["id"]), 120, "booked_minutes")

        moved_on = validate_success(
            api.advance_stage(
                order_x["id"], f.stage_advance_payload("REFINISH_CALIBRATION"), TECHNICIAN_HEADERS
            ),
            200,
        )
        A.assert_stage(moved_on, "REFINISH_CALIBRATION")

        finished = fx.read_assignment(api, booking_x["id"])
        assert finished["status"] == "COMPLETED"
        A.assert_count(finished["occupied_minutes"], 240, "occupied_minutes")

        # 360 less the first vehicle's 240 leaves the neighbour's reservation standing.
        A.assert_count(_booked_minutes(api, shared_stall["id"]), 120, "booked_minutes")
        assert fx.read_assignment(api, booking_y["id"])["status"] == "SCHEDULED"
        assert fx.read_assignment(api, booking_paint["id"])["status"] == "ACTIVE"
        A.assert_count(_booked_minutes(api, paint_stall["id"]), 120, "booked_minutes")

        rows, meta = fx.page(
            api.list_stage_assignments(TECHNICIAN_HEADERS, {"stall_id": shared_stall["id"]})
        )
        A.assert_page(meta, total_count=2)
        assert {row["id"] for row in rows} == {booking_x["id"], booking_y["id"]}
