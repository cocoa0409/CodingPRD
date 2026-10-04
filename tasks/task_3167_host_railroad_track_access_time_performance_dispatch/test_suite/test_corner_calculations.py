"""Calculation corners: padded schedule walk, OTP precision, feasibility and capacity."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    ApiErrorId,
    PASSENGER_OPERATOR_HEADERS,
    assert_instant,
    factories,
    fixtures,
)


def test_planned_passage_times_use_ceiled_running_time_pad(api):
    """The padded running time is rounded up before dwell: 21 x 1.25 pads to 27 minutes.

    Segment 1's planned window is [08:00,08:27) and segment 2's is
    [08:27,09:17) with zero dwell.

    PRD: "The schedule walk proceeds segment by segment in ascending `sequence_no` — strictly chronological, with no ties possible since `sequence_no` is unique per corridor: the first segment's planned entry equals the scheduled departure; each segment's planned exit is its planned entry plus its padded running time, the pad being the `pure_run_minutes` multiplied by one plus the agreement's `running_time_allowance_pct` and then rounded up to the next whole minute; and each following segment's planned entry is the previous segment's planned exit plus that segment's `dwell_after_minutes`."
    PRD: "Running-time pads are computed in whole minutes, with the padded run time rounded up to the next whole minute before dwell is added."
    Design: Corner/calculations/planned_passage_times_include_ceil_allowance
    """
    net = fixtures.setup_published_timetable(api, trains_per_day=1, service_date="2026-09-02")
    p1, p2 = net["passages"][0]

    passage1 = fixtures.read_passage(api, p1["id"], PASSENGER_OPERATOR_HEADERS)
    passage2 = fixtures.read_passage(api, p2["id"], PASSENGER_OPERATOR_HEADERS)

    assert_instant(passage1["planned_entry_at"], "2026-09-02T08:00:00Z", "p1.planned_entry_at")
    assert_instant(passage1["planned_exit_at"], "2026-09-02T08:27:00Z", "p1.planned_exit_at")
    assert_instant(passage2["planned_entry_at"], "2026-09-02T08:27:00Z", "p2.planned_entry_at")
    assert_instant(passage2["planned_exit_at"], "2026-09-02T09:17:00Z", "p2.planned_exit_at")


def test_otp_percentage_carried_to_four_decimal_places(api):
    """One on-time run of two completed yields otp_pct exactly 50.0000.

    PRD: "`otp_pct` is the percentage of completed runs whose `on_time_endpoint` flag is true — one hundred times the on-time count divided by `completed_run_count`, rounded half-up to four decimal places."
    PRD: "On-time percentages are carried to four decimal places with round half-up."
    Design: Corner/calculations/otp_percentage_precision_four_decimals
    """
    net = fixtures.runs_0903_one_ontime_one_late(api)

    statement = fixtures.create_statement(api, net)

    assert statement["completed_run_count"] == 2
    assert statement["otp_pct"] == 50.0000


def test_tight_headway_overlap_on_single_segment_rejected_infeasible(api):
    """A 30-minute headway overlaps planned passages on a SINGLE segment; propose fails.

    Run1's segment-2 planned window is [08:27,09:17); run2's is [08:57,09:47).

    PRD: "The proposal is rejected with `ERR_SCHEDULE_INFEASIBLE` if any two planned passages on a `SINGLE` segment overlap under the half-open rule of §2.5"
    Design: Corner/calculations/schedule_overlap_infeasible_headway_rejected
    """
    net = fixtures.setup_active_agreement(api)
    timetable = fixtures.create_timetable(
        api, net, service_date_start="2026-09-04", service_date_end="2026-09-04",
        trains_per_day=2, headway_minutes=30,
    )

    response = api.propose_timetable(timetable["id"], PASSENGER_OPERATOR_HEADERS)

    assert response.status_code == 422
    validate_error(response, ApiErrorId.ERR_SCHEDULE_INFEASIBLE)
    assert fixtures.read_timetable(api, timetable["id"])["status"] == "DRAFT"


def test_propose_beyond_segment_capacity_rejected(api):
    """A 2-train timetable on a capacity-1 segment is rejected even without overlap.

    The bottleneck corridor's single segment grants one train per day; the
    120-minute headway is geometrically non-overlapping but exceeds the grant.

    PRD: "Host railroads grant passenger access in trains-per-day on each segment, recorded as `capacity_trains_per_day`. No timetable may schedule more runs across a segment on a service date than that grant allows; a proposal that would is rejected with `ERR_CAPACITY_EXCEEDED`."
    Design: Corner/calculations/capacity_exceeded_at_propose_rejected
    """
    net = fixtures.setup_network(api)
    corridor = fixtures.create_corridor(
        api,
        net["host"]["id"],
        code="GP-CAP",
        name="Bottleneck",
        endpoint_a="STL",
        endpoint_b="MEM",
        service_type="LONG_DISTANCE",
        annual_cost_cents=8_000_000,
    )
    fixtures.create_segment(
        api,
        corridor["id"],
        sequence_no=1,
        milepost_start=0.0,
        milepost_end=12.0,
        state_code="MO",
        track_class="SINGLE",
        capacity_trains_per_day=1,
        pure_run_minutes=30,
        dwell_after_minutes=0,
    )
    agreement = fixtures.create_agreement(
        api,
        net,
        corridor_id=corridor["id"],
        on_time_threshold_minutes=30,
        penalty_rate_cents_per_minute=40,
        incentive_rate_cents_per_train_mile=10,
        otp_target_pct=0.75,
        running_time_allowance_pct=0.20,
    )
    fixtures.activate_agreement(api, net, agreement["id"])
    timetable = get_success_data(api.create_timetable(
        factories.timetable_payload(
            corridor["id"], agreement["id"],
            service_date_start="2026-09-04", service_date_end="2026-09-04",
            trains_per_day=2, headway_minutes=120,
        ),
        PASSENGER_OPERATOR_HEADERS,
    ))

    response = api.propose_timetable(timetable["id"], PASSENGER_OPERATOR_HEADERS)

    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_CAPACITY_EXCEEDED)
    assert fixtures.read_timetable(api, timetable["id"])["status"] == "DRAFT"
