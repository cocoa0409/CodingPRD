"""Cross-cutting corners: OCC stale versions, equipment boundary, lock cascade, capacity reconciliation."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import ApiErrorId, PASSENGER_OPERATOR_HEADERS, fixtures


def test_second_approve_with_stale_agreement_version_rejected(api):
    """After one approve bumps the agreement version, a second with the old version is stale.

    PRD: "Approving funding for a capital project likewise requires `expected_operating_agreement_version` matching the funding agreement's current `version`. Approval pins the commercial terms the approver observed, and `ERR_STALE_VERSION` (HTTP 412) prevents pinning terms that have already been superseded."
    PRD: "an accepted approval pins those terms by incrementing the agreement's `version` by one — which also means any amendment drafted against the old version will now fail its stale-version check"
    Design: Corner/cross_cutting/project_approve_stale_version_rejected
    """
    net = fixtures.setup_active_agreement(api)
    observed = net["agreement_version"]
    project1 = fixtures.create_project(api, net)
    project2 = fixtures.create_project(
        api, net, track_segment_id=net["seg2"]["id"], project_type="SIGNAL",
        funded_amount_cents=30_000_000, added_frequency_capacity=2,
    )
    fixtures.approve_project(api, net, project1["id"], observed)

    response = api.approve_capital_project(
        project2["id"], {"expected_operating_agreement_version": observed}, net["host_headers"]
    )

    assert response.status_code == 412
    validate_error(response, ApiErrorId.ERR_STALE_VERSION)
    assert fixtures.read_project(api, project2["id"])["status"] == "PROPOSED"
    assert fixtures.read_agreement(api, net["agreement"]["id"])["version"] == observed + 1


def test_amend_with_stale_version_rejected_and_changes_nothing(api):
    """An amend one version behind is rejected with ERR_STALE_VERSION and changes nothing.

    PRD: "Amending an operating agreement requires the request to carry `expected_operating_agreement_version`, the agreement `version` the client last observed. If the agreement's current `version` does not match — for example because another amendment or a capital-project approval landed since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    Design: Corner/cross_cutting/amend_stale_version_rejected
    """
    net = fixtures.setup_active_agreement(api)
    observed = net["agreement_version"]

    response = api.amend_operating_agreement(
        net["agreement"]["id"],
        {"expected_operating_agreement_version": observed - 1, "penalty_rate_cents_per_minute": 99},
        PASSENGER_OPERATOR_HEADERS,
    )

    assert response.status_code == 412
    validate_error(response, ApiErrorId.ERR_STALE_VERSION)
    agreement = fixtures.read_agreement(api, net["agreement"]["id"])
    assert agreement["penalty_rate_cents_per_minute"] == 50
    assert agreement["amendment_seq"] == 0
    assert agreement["version"] == observed


def test_equipment_allowance_exact_boundary_then_overflow(api):
    """Four 10-hour locks in one ISO week hit exactly 40.00; a fifth 1-hour lock is rejected.

    PRD: "Every maintenance unit identified by `equipment_unit_id` may consume at most 40.00 hours of locked window time per ISO week, where weeks start Monday at 00:00:00Z and a window belongs to the week containing its `window_start_at`."
    PRD: "Locking a window is permitted only if the sum of `window_hours` over that unit's already-locked windows in the same week plus the new window's `window_hours` does not exceed 40.00 — a total of exactly 40.00 hours is allowed — and is otherwise rejected with `ERR_EQUIPMENT_ALLOWANCE_EXCEEDED`."
    Design: Corner/cross_cutting/equipment_allowance_exact_boundary
    """
    net = fixtures.setup_network(api)
    window_ids = []
    for day in ("07", "08", "09", "10"):
        w = fixtures.create_window(
            api, net, track_segment_id=net["seg1"]["id"],
            window_start_at=f"2026-09-{day}T06:00:00Z",
            window_end_at=f"2026-09-{day}T16:00:00Z",
            equipment_unit_id="EQ-4",
        )
        window_ids.append(w["id"])
    fifth = fixtures.create_window(
        api, net, track_segment_id=net["seg1"]["id"],
        window_start_at="2026-09-11T06:00:00Z",
        window_end_at="2026-09-11T07:00:00Z",
        equipment_unit_id="EQ-4",
    )

    last_locked = None
    for window_id in window_ids:
        last_locked = fixtures.lock_window(api, net, window_id)
    assert last_locked["equipment_week_hours_available"] == 0.00

    response = api.lock_maintenance_window(fifth["id"], net["host_headers"])
    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_EQUIPMENT_ALLOWANCE_EXCEEDED)
    assert fixtures.read_window(api, fifth["id"])["status"] == "PLANNED"


def test_locking_window_skips_conflicting_planned_passage_only(api):
    """A lock conflicting with a planned passage flips it to SKIPPED; the other passage stays.

    The zero-buffer window [08:30,09:00) on segment 2 intersects the run's
    planned passage [08:27,09:17).

    PRD: "on success the lock consumes the window's hours from the unit's weekly allowance and immediately cascades — every `PLANNED` segment passage on this segment whose clearance-expanded planned interval intersects the window flips to `SKIPPED`, with the incident auto-creation of §3.6 applying if that skip completes a disrupted run's passage set."
    Design: Corner/cross_cutting/maintenance_lock_skips_conflicting_planned_passage
    """
    net = fixtures.setup_published_timetable(api, trains_per_day=1, service_date="2026-09-02")
    run = net["runs"][0]
    p1, p2 = net["passages"][0]
    window = fixtures.create_window(
        api, net, track_segment_id=net["seg2"]["id"],
        window_start_at="2026-09-02T08:30:00Z",
        window_end_at="2026-09-02T09:00:00Z",
        equipment_unit_id="EQ-5",
        clearance_buffer_minutes=0,
    )

    fixtures.lock_window(api, net, window["id"])

    assert fixtures.read_passage(api, p2["id"])["status"] == "SKIPPED"
    assert fixtures.read_passage(api, p1["id"])["status"] == "PLANNED"
    assert fixtures.read_run(api, run["id"])["status"] == "SCHEDULED"


def test_completing_project_recomputes_segment_capacity_exactly_once(api):
    """Completion adds the project's capacity to the segment and returns it to OPERABLE.

    PRD: "Completion moves `IN_PROGRESS` → `COMPLETED` and, exactly once per project, adds the project's `added_frequency_capacity` to the segment's `capacity_trains_per_day` while returning the segment to `OPERABLE`."
    Design: Corner/cross_cutting/segment_capacity_derived_reconciliation_on_complete
    """
    net = fixtures.setup_active_agreement(api)
    project = fixtures.create_project(api, net, added_frequency_capacity=4)
    fixtures.approve_project(api, net, project["id"], net["agreement_version"])
    api.start_capital_project(project["id"], net["host_headers"])
    assert fixtures.read_segment(api, net["seg1"]["id"])["status"] == "CAPITAL_HOLD"

    completed = get_success_data(api.complete_capital_project(project["id"], net["host_headers"]))

    assert completed["status"] == "COMPLETED"
    segment = fixtures.read_segment(api, net["seg1"]["id"])
    assert segment["capacity_trains_per_day"] == 24
    assert segment["status"] == "OPERABLE"
