"""Difficulty queue — resource_temporal_overlap: aggregate-per-day capacity
on a crush plant versus half-open interval occupancy on a BARGE lane
(PRD §3.6 and §3.5).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_crush_run,
    assert_shipment,
    book_shipment,
    create_barge_lane,
    create_crush_plant,
    create_crush_run,
    create_shipment_payload,
    post_crush_quote_set,
    read_crush_run,
    schedule_crush_run_payload,
    schedule_run,
    setup_elevator_with_stored_bushels,
    validate_error,
    validate_success,
)
from conftest import parse_iso

SCHEDULER = TEST_USERS["plant_scheduler_headers"]
LOGISTICS = TEST_USERS["logistics_coordinator_headers"]


class TestPlantDailyAggregateCapacity:
    """ACTIVE plant with daily_crush_capacity_bushels 50000; three runs of
    30000 bu — A and B share 2026-09-10, C sits on 2026-09-11."""

    def _setup(self):
        plant = create_crush_plant()
        post_crush_quote_set("2026-11", bean=1200, oil=55, meal=17,
                             quote_date="2026-09-01T00:00:00Z")
        run_a = create_crush_run(plant["id"], run_date="2026-09-10T00:00:00Z",
                                 planned_bushels=30000, futures_month="2026-11")
        run_b = create_crush_run(plant["id"], run_date="2026-09-10T00:00:00Z",
                                 planned_bushels=30000, futures_month="2026-11")
        run_c = create_crush_run(plant["id"], run_date="2026-09-11T00:00:00Z",
                                 planned_bushels=30000, futures_month="2026-11")
        return run_a, run_b, run_c

    def test_second_same_day_run_exceeds_aggregate(self, api):
        """PRD §3.6: "the plant's per-day aggregate — the sum of
        `planned_bushels` over that plant's runs in `SCHEDULED`, `RUNNING`, or
        `COMPLETE` on the same `run_date`, plus this run's own bushels — must
        not exceed `daily_crush_capacity_bushels` (`ERR_PLANT_CAPACITY_EXCEEDED`)".
        A's 30000 schedules; B would push the 2026-09-10 aggregate to 60000
        and is refused; B stays PLANNED.

        Design: Difficulty/resource_temporal_overlap/plant_daily_aggregate_capacity
        """
        run_a, run_b, _ = self._setup()
        scheduled = schedule_run(run_a["id"], expected_run_version=run_a["version"])
        assert scheduled["status"] == "SCHEDULED"
        resp = api_client.schedule_crush_run(
            run_b["id"], schedule_crush_run_payload(run_b["version"]), SCHEDULER
        )
        validate_error(resp, ApiErrorId.ERR_PLANT_CAPACITY_EXCEEDED)
        after = read_crush_run(run_b["id"])
        assert_crush_run(after)
        assert after["status"] == "PLANNED"

    def test_adjacent_day_does_not_interact(self, api):
        """PRD §3.6: the aggregate sums runs "on the same `run_date" — a run on
        2026-09-11 shares no capacity with 2026-09-10, so C schedules cleanly
        while B's date is full.

        Design: Difficulty/resource_temporal_overlap/plant_daily_aggregate_capacity
        """
        run_a, run_b, run_c = self._setup()
        schedule_run(run_a["id"], expected_run_version=run_a["version"])
        resp_b = api_client.schedule_crush_run(
            run_b["id"], schedule_crush_run_payload(run_b["version"]), SCHEDULER
        )
        validate_error(resp_b, ApiErrorId.ERR_PLANT_CAPACITY_EXCEEDED)
        scheduled_c = schedule_run(
            run_c["id"], expected_run_version=run_c["version"]
        )
        assert_crush_run(scheduled_c)
        assert scheduled_c["status"] == "SCHEDULED"


class TestBargeLaneHalfOpenIntervalOverlap:
    """Elevator holding 20000 bu; a BARGE lane with transit 5 days and
    daily_capacity_bushels 1 (ignored for barges); shipment 1 departs
    2026-09-10 and occupies [09-10, 09-15)."""

    def _setup(self):
        base = setup_elevator_with_stored_bushels(20000)
        plant = create_crush_plant()
        lane = create_barge_lane(
            base["site"]["elevator"]["id"], plant["id"],
            transit_days=5, daily_capacity_bushels=1,
        )
        ship1 = book_shipment(
            lane["id"], 5000, departure_date="2026-09-10T00:00:00Z"
        )
        return lane, ship1

    def test_overlapping_departure_rejected_but_capacity_ignored(self, api):
        """PRD §3.5: "The capacity field governs per-departure-date totals for truck and rail; barges ignore it, because barge occupancy is governed by interval semantics instead" and "the half-open interval from `departure_date` to `arrival_date` — departure inclusive, arrival exclusive — must not overlap any other booked barge movement on the same lane, though back-to-back runs where one barge's arrival equals the next departure are legal (`ERR_BARGE_SCHEDULE_OVERLAP`)."
        Shipment 1 books 5000 bu over a lane whose daily capacity is 1; a
        2026-09-14 departure inside [09-10, 09-15) fails 409.

        Design: Difficulty/resource_temporal_overlap/barge_lane_half_open_interval_overlap
        """
        lane, ship1 = self._setup()
        assert_shipment(ship1)
        assert ship1["status"] == "BOOKED"
        assert parse_iso(ship1["arrival_date"]) == parse_iso(
            "2026-09-15T00:00:00Z"
        ), "arrival is departure plus 5 transit days"
        resp = api_client.create_shipment(
            create_shipment_payload(
                lane["id"], 5000, departure_date="2026-09-14T00:00:00Z"
            ),
            LOGISTICS,
        )
        validate_error(resp, ApiErrorId.ERR_BARGE_SCHEDULE_OVERLAP)

    def test_back_to_back_departure_at_arrival_is_legal(self, api):
        """PRD §3.5: "back-to-back runs where one barge's arrival equals the next departure are legal". Departing exactly at 2026-09-15 — shipment
        1's arrival — books 201 because the interval is arrival-exclusive.

        Design: Difficulty/resource_temporal_overlap/barge_lane_half_open_interval_overlap
        """
        lane, _ = self._setup()
        resp = api_client.create_shipment(
            create_shipment_payload(
                lane["id"], 5000, departure_date="2026-09-15T00:00:00Z"
            ),
            LOGISTICS,
        )
        ship3 = validate_success(resp, 201)
        assert_shipment(ship3)
        assert ship3["status"] == "BOOKED"
