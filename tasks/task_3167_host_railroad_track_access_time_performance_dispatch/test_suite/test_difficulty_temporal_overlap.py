"""Temporal resource overlap: half-open occupancy and maintenance clearance buffers."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId, PASSENGER_OPERATOR_HEADERS, fixtures


def _two_runs_en_route_with_first_passage_actualized(api):
    """The 2026-09-03 2-run day, both runs en route, run1 passage 1 ACTUALIZED [08:00,08:27)."""
    net = fixtures.setup_published_timetable(api, trains_per_day=2, service_date="2026-09-03")
    r1, r2 = net["runs"]
    (r1p1, _r1p2), (r2p1, _r2p2) = net["passages"]
    fixtures.depart_run(api, net, r1["id"], "2026-09-03T08:00:00Z")
    fixtures.depart_run(api, net, r2["id"], "2026-09-03T10:00:00Z")
    fixtures.actualize_passage(api, net, r1p1["id"], "2026-09-03T08:00:00Z", "2026-09-03T08:27:00Z")
    net.update({"r1p1": r1p1, "r2p1": r2p1})
    return net


def test_overlapping_actual_occupancy_on_single_track_rejected(api):
    """An actual passage overlapping another ACTUALIZED passage on the same SINGLE segment fails.

    Run1's passage 1 occupies [08:00,08:27); run2's candidate [08:25,08:50)
    overlaps it.

    PRD: "on a `SINGLE` segment the actual interval must not overlap any other `ACTUALIZED` passage on that segment, half-open so exact adjacency is allowed (`ERR_SEGMENT_OCCUPANCY_CONFLICT`)"
    Design: Difficulty/resource_temporal_overlap/single_track_half_open_adjacency
    """
    net = _two_runs_en_route_with_first_passage_actualized(api)

    response = api.actualize_segment_passage(
        net["r2p1"]["id"],
        {"actual_entry_at": "2026-09-03T08:25:00Z", "actual_exit_at": "2026-09-03T08:50:00Z"},
        net["host_headers"],
    )

    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_SEGMENT_OCCUPANCY_CONFLICT)
    assert fixtures.read_passage(api, net["r2p1"]["id"])["status"] == "PLANNED"


def test_exact_adjacency_on_single_track_is_not_a_conflict(api):
    """A passage whose entry equals the other's exit is accepted (half-open intervals).

    Run1's passage 1 occupies [08:00,08:27); run2's adjacent candidate is
    [08:27,08:54).

    PRD: "Overlap is judged with half-open intervals: two passages conflict if and only if each one's entry instant precedes the other's exit instant, while one passage's exit instant coinciding exactly with the other's entry instant is **not** a conflict — exact adjacency is permitted."
    Design: Difficulty/resource_temporal_overlap/single_track_half_open_adjacency
    """
    net = _two_runs_en_route_with_first_passage_actualized(api)

    response = api.actualize_segment_passage(
        net["r2p1"]["id"],
        {"actual_entry_at": "2026-09-03T08:27:00Z", "actual_exit_at": "2026-09-03T08:54:00Z"},
        net["host_headers"],
    )

    actualized = validate_success(response, 200)
    assert actualized["status"] == "ACTUALIZED"


def test_passage_entry_exactly_at_clearance_boundary_is_feasible(api):
    """A proposed timetable touching the clearance-expanded window edge is feasible.

    The LOCKED window ends at 07:45 with a 15-minute buffer, so its expanded
    interval ends at 08:00. A 07:33 departure puts segment 2's planned entry at
    exactly 08:00 — equality at the buffer boundary is not a conflict.

    PRD: "A train passage — planned or actual — conflicts with a `LOCKED` window on the same segment when the passage's entry instant precedes the window's expanded end and the passage's exit instant follows the window's expanded start; exact equality at either buffer boundary is **not** a conflict."
    Design: Difficulty/resource_temporal_overlap/maintenance_clearance_buffer_semantics
    """
    net = fixtures.setup_active_agreement(api)
    window = fixtures.create_window(
        api,
        net,
        track_segment_id=net["seg2"]["id"],
        window_start_at="2026-09-02T05:00:00Z",
        window_end_at="2026-09-02T07:45:00Z",
        equipment_unit_id="EQ-1",
        clearance_buffer_minutes=15,
    )
    fixtures.lock_window(api, net, window["id"])
    timetable = fixtures.create_timetable(api, net, departure_time_of_day="07:33")

    proposed = fixtures.propose_timetable(api, timetable["id"])
    assert proposed["status"] == "PROPOSED"


def test_passage_one_minute_inside_clearance_is_infeasible(api):
    """A proposed timetable one minute inside the clearance zone is rejected.

    A 07:32 departure puts segment 2's planned entry at 07:59 — one minute
    before the window's expanded end of 08:00 — and the planned exit follows
    the window's expanded start, so it conflicts.

    PRD: "A train passage — planned or actual — conflicts with a `LOCKED` window on the same segment when the passage's entry instant precedes the window's expanded end and the passage's exit instant follows the window's expanded start; exact equality at either buffer boundary is **not** a conflict. Occupancy that would intersect a locked window under these clearance-buffer semantics is rejected with `ERR_MAINTENANCE_CONFLICT`."
    PRD: "ninth, the maintenance clearance conflict (`ERR_MAINTENANCE_CONFLICT`); tenth, single-track actual occupancy conflict (`ERR_SEGMENT_OCCUPANCY_CONFLICT`); eleventh, internal schedule feasibility of a proposed timetable (`ERR_SCHEDULE_INFEASIBLE`)"
    Design: Difficulty/resource_temporal_overlap/maintenance_clearance_buffer_semantics
    """
    net = fixtures.setup_active_agreement(api)
    window = fixtures.create_window(
        api,
        net,
        track_segment_id=net["seg2"]["id"],
        window_start_at="2026-09-02T05:00:00Z",
        window_end_at="2026-09-02T07:45:00Z",
        equipment_unit_id="EQ-1",
        clearance_buffer_minutes=15,
    )
    fixtures.lock_window(api, net, window["id"])
    timetable = fixtures.create_timetable(api, net, departure_time_of_day="07:32")

    response = api.propose_timetable(timetable["id"], PASSENGER_OPERATOR_HEADERS)

    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_MAINTENANCE_CONFLICT)
    assert fixtures.read_timetable(api, timetable["id"])["status"] == "DRAFT"
