"""Two opposite interval conventions: half-open rooms and closed carrier windows."""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (ERR_CARRIER_CAPACITY_EXCEEDED,
                                     ERR_QUARANTINE_ROOM_CONFLICT)
from test_helpers.test_users import make_vet_headers


def _two_room_world(api):
    """Room Q-1 released FAILED and room Q-2 still SCHEDULED at the receiver."""
    world = fx.world_with_parallel_agreements(api, count=2)
    second_agreement = world.extra["agreements"][1]
    second_male = world.extra["pairs"][1][0]
    world.extra["ta2_id"] = second_agreement["id"]
    world.extra["m2_id"] = second_male["id"]

    fx.record_panel(world)
    world.set_clock(fx.CLOCK_DOCUMENTS)
    fx.issue_certificate(world)
    fx.issue_permit(world)
    world.set_clock(fx.CLOCK_PRESHIPMENT)
    fx.crate_train(world)
    fx.book_transport(world)
    fx.schedule_quarantine(world, quarantine_room_code="Q-1",
                           scheduled_start_date="2026-09-01",
                           scheduled_end_date="2026-10-01")
    fx.confirm_transport(world)
    fx.depart(world)
    fx.deliver(world)

    second_occupancy = validate_success(
        api.create_quarantine_occupancy(
            f.quarantine_payload(
                world.extra["ta2_id"], world.receiver_id, world.extra["m2_id"],
                quarantine_room_code="Q-2",
                scheduled_start_date="2026-09-20",
                scheduled_end_date="2026-10-20",
            ),
            world.receiver,
        ),
        201,
    )
    world.extra["q2_occupancy_id"] = second_occupancy["id"]

    world.set_clock("2026-09-10T09:00:00Z")
    failed = validate_success(
        api.fail_quarantine(world.occupancy_id,
                            make_vet_headers(world.vet_c_id),
                            f.quarantine_fail_payload())
    )
    world.extra["failed_occupancy"] = failed
    return world


def _reserve(world, room_code, start_date, end_date):
    return world.api.create_quarantine_occupancy(
        f.quarantine_payload(
            world.extra["ta2_id"], world.receiver_id, world.extra["m2_id"],
            quarantine_room_code=room_code,
            scheduled_start_date=start_date, scheduled_end_date=end_date,
        ),
        world.receiver,
    )


class TestQuarantineRoomWindow:
    """The blocked window's right edge depends on how the room was released."""

    def test_a_failed_release_widens_the_sanitation_buffer_to_a_fortnight(
            self, api):
        """A reservation starting 2026-10-14 still falls inside Q-1's window.

        PRD: "**The buffer is conditional on how the room was released:** a room
        freed by a `FAILED` occupancy is blocked for a further fourteen days,
        whereas a room freed in any other way is blocked for a further three days."

        Design: Difficulty/resource_temporal_overlap/quarantine_room_half_open_window_with_phase_conditional_buffer
        """
        world = _two_room_world(api)
        failed = world.read_occupancy(world.occupancy_id)
        assert failed["phase"] == "FAILED"
        assert failed["cleared_on"] is None
        agreement = world.read_agreement(world.ta_id)
        assert agreement["status"] == "TERMINATED"
        assert agreement["termination_reason"] == "QUARANTINE_FAILED"
        response = _reserve(world, "Q-1", "2026-10-14", "2026-11-13")
        validate_error(response, ERR_QUARANTINE_ROOM_CONFLICT)

    def test_a_reservation_may_start_on_the_exact_day_the_window_ends(self, api):
        """2026-10-15 is the first free day for the failed room and is accepted.

        PRD: "Because both intervals stop short of their end dates, a new
        occupancy may legitimately start on the exact day a previous blocked
        window ends."

        Design: Difficulty/resource_temporal_overlap/quarantine_room_half_open_window_with_phase_conditional_buffer
        """
        world = _two_room_world(api)
        validate_error(_reserve(world, "Q-1", "2026-10-14", "2026-11-13"),
                       ERR_QUARANTINE_ROOM_CONFLICT)
        data = validate_success(
            _reserve(world, "Q-1", "2026-10-15", "2026-11-14"), 201
        )
        assert data["phase"] == "SCHEDULED"
        assert data["quarantine_room_code"] == "Q-1"

    def test_a_scheduled_occupancy_blocks_only_three_further_days(self, api):
        """Q-2 ends 2026-10-20 and still blocks 2026-10-22 but not 2026-10-23.

        PRD: "Each such occupancy blocks a window that begins on its own
        `scheduled_start_date` and runs up to — but does not include — its
        effective end plus a post-occupancy sanitation buffer."

        Design: Difficulty/resource_temporal_overlap/quarantine_room_half_open_window_with_phase_conditional_buffer
        """
        world = _two_room_world(api)
        assert world.read_occupancy(
            world.extra["q2_occupancy_id"])["phase"] == "SCHEDULED"
        validate_error(_reserve(world, "Q-2", "2026-10-22", "2026-11-21"),
                       ERR_QUARANTINE_ROOM_CONFLICT)
        data = validate_success(
            _reserve(world, "Q-2", "2026-10-23", "2026-11-22"), 201
        )
        assert data["phase"] == "SCHEDULED"
        assert data["quarantine_room_code"] == "Q-2"

    def test_the_occupied_resource_is_the_institution_and_room_pair(self, api):
        """The sending institution may hold its own room called Q-1 unimpeded.

        PRD: "The occupied resource is the pair of institution and room code, not
        the room code alone, so two institutions may both operate a room called
        "Q3"."

        Design: Difficulty/resource_temporal_overlap/quarantine_room_half_open_window_with_phase_conditional_buffer
        """
        world = _two_room_world(api)
        validate_error(_reserve(world, "Q-1", "2026-10-14", "2026-11-13"),
                       ERR_QUARANTINE_ROOM_CONFLICT)
        data = validate_success(
            api.create_quarantine_occupancy(
                f.quarantine_payload(
                    world.extra["ta2_id"], world.sender_id,
                    world.extra["m2_id"], quarantine_room_code="Q-1",
                    scheduled_start_date="2026-10-14",
                    scheduled_end_date="2026-11-13",
                ),
                world.sender,
            ),
            201,
        )
        assert data["institution_id"] == world.sender_id
        assert data["phase"] == "SCHEDULED"


class TestCarrierAggregateCapacity:
    """Carrier windows are closed at both ends and the limit counts live journeys."""

    @staticmethod
    def _book(world, index, departure_utc, arrival_utc):
        agreement = world.extra["agreements"][index]
        version = world.read_agreement(agreement["id"])["version"]
        return world.api.create_booking(
            f.booking_payload(
                agreement["id"], version, carrier_code="AVI-CARGO-7",
                crate_serial=f"CR-CRATE-00{index + 1}",
                departure_utc=departure_utc, arrival_utc=arrival_utc,
            ),
            world.sender,
        )

    def test_two_journeys_may_be_live_on_one_carrier_at_once(self, api):
        """The first two overlapping bookings are both accepted and RESERVED.

        PRD: "A journey counts as live while its booking is `RESERVED`,
        `CONFIRMED` or `IN_TRANSIT`, across every institution and every agreement
        — `DELIVERED` and `ABORTED` bookings release their interval and are
        ignored."

        Design: Difficulty/resource_temporal_overlap/carrier_closed_interval_aggregate_capacity_at_one_second
        """
        world = fx.world_with_parallel_agreements(api, count=3)
        first = validate_success(
            self._book(world, 0, "2026-09-01T08:00:00Z", "2026-09-02T08:00:00Z"),
            201,
        )
        assert first["status"] == "RESERVED"
        assert first["thermal_excursion_minutes"] == 0
        second = validate_success(
            self._book(world, 1, "2026-09-01T20:00:00Z", "2026-09-02T20:00:00Z"),
            201,
        )
        assert second["status"] == "RESERVED"
        assert world.read_booking(first["id"])["status"] == "RESERVED"

    def test_a_third_journey_touching_both_endpoints_is_refused(self, api):
        """Departing at the exact instant the first arrives counts as overlapping.

        PRD: "Two journeys overlap when the existing booking's `departure_utc` is
        at or before the new booking's `arrival_utc` **and** the new booking's
        `departure_utc` is at or before the existing booking's `arrival_utc`."

        Design: Difficulty/resource_temporal_overlap/carrier_closed_interval_aggregate_capacity_at_one_second
        """
        world = fx.world_with_parallel_agreements(api, count=3)
        validate_success(
            self._book(world, 0, "2026-09-01T08:00:00Z", "2026-09-02T08:00:00Z"),
            201,
        )
        validate_success(
            self._book(world, 1, "2026-09-01T20:00:00Z", "2026-09-02T20:00:00Z"),
            201,
        )
        third_agreement = world.extra["agreements"][2]
        version_before = world.read_agreement(third_agreement["id"])["version"]
        response = self._book(world, 2, "2026-09-02T08:00:00Z",
                              "2026-09-02T12:00:00Z")
        validate_error(response, ERR_CARRIER_CAPACITY_EXCEEDED)
        assert world.read_agreement(third_agreement["id"])["version"] == \
            version_before

    def test_departing_one_second_later_overlaps_only_one_journey(self, api):
        """One second past the shared endpoint leaves the carrier with room.

        PRD: "The comparison is closed at both ends and evaluated to the second,
        so two journeys that merely touch — one arriving at the exact instant the
        next departs — do count as overlapping."

        Design: Difficulty/resource_temporal_overlap/carrier_closed_interval_aggregate_capacity_at_one_second
        """
        world = fx.world_with_parallel_agreements(api, count=3)
        first = validate_success(
            self._book(world, 0, "2026-09-01T08:00:00Z", "2026-09-02T08:00:00Z"),
            201,
        )
        second = validate_success(
            self._book(world, 1, "2026-09-01T20:00:00Z", "2026-09-02T20:00:00Z"),
            201,
        )
        validate_error(
            self._book(world, 2, "2026-09-02T08:00:00Z", "2026-09-02T12:00:00Z"),
            ERR_CARRIER_CAPACITY_EXCEEDED,
        )
        third = validate_success(
            self._book(world, 2, "2026-09-02T08:00:01Z", "2026-09-02T12:00:00Z"),
            201,
        )
        assert third["status"] == "RESERVED"
        assert third["departure_utc"].startswith("2026-09-02T08:00:01")
        assert world.read_booking(first["id"])["status"] == "RESERVED"
        assert world.read_booking(second["id"])["status"] == "RESERVED"
