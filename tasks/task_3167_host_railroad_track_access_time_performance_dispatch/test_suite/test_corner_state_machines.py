"""State-machine corners: initial states, invalid transitions, lockdown, side effects."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId, PASSENGER_OPERATOR_HEADERS, SYSTEM_ADMIN_HEADERS, fixtures


def test_coded_incident_born_open_with_derived_host_flag(api):
    """A coded HOST_SIGNAL incident starts OPEN, host_attributable true, origin CODED.

    PRD: "A coded incident is born `OPEN` with `origin` `CODED`, and its `host_attributable` flag is derived from the cause: exactly the codes `HOST_FREIGHT_HOLD`, `HOST_SIGNAL`, and `HOST_TRACK` are host-attributable, while `MECHANICAL`, `STATION_DWELL`, `WEATHER`, and `DISRUPTION` are not."
    Design: Corner/state_machines/delay_incident_initial_state_open_and_host_flag_derived
    """
    net = fixtures.run_0902_completed_20_late(api)

    incident = fixtures.code_incident(api, net, net["run"]["id"], "HOST_SIGNAL", 9)

    assert incident["status"] == "OPEN"
    assert incident["host_attributable"] is True
    assert incident["origin"] == "CODED"


def test_complete_on_scheduled_run_rejected_invalid_state(api):
    """Complete on a SCHEDULED run (never departed) is rejected; the run is unchanged.

    PRD: "sixth, state-machine legality of the requested transition (`ERR_INVALID_STATE`)"
    PRD: "Recording the actual origin departure with an `actual_departure_at` instant moves a run from `SCHEDULED` to `EN_ROUTE`"
    Design: Corner/state_machines/run_complete_from_scheduled_rejected_invalid_state
    """
    net = fixtures.setup_published_timetable(api, trains_per_day=1, service_date="2026-09-02")
    run = net["runs"][0]

    response = api.complete_train_run(
        run["id"], {"actual_arrival_at": "2026-09-02T09:17:00Z"}, net["host_headers"]
    )

    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert fixtures.read_run(api, run["id"])["status"] == "SCHEDULED"


def test_depart_on_cancelled_run_rejected_and_reason_preserved(api):
    """A CANCELLED run is terminal for depart; the operator-cancel reason stays.

    PRD: "The operator may instead cancel a still-`SCHEDULED` run — optionally recording a `reason` — which sets `cancellation_reason` to `OPERATOR_CANCEL`."
    PRD: "sixth, state-machine legality of the requested transition (`ERR_INVALID_STATE`)"
    Design: Corner/state_machines/cancelled_run_terminal_lockdown_depart_rejected
    """
    net = fixtures.setup_published_timetable(api, trains_per_day=1, service_date="2026-09-02")
    run = net["runs"][0]
    cancelled = validate_success(
        api.cancel_train_run(run["id"], {"reason": "consolidated"}, PASSENGER_OPERATOR_HEADERS), 200
    )
    assert cancelled["status"] == "CANCELLED"

    response = api.depart_train_run(
        run["id"], {"actual_departure_at": "2026-09-02T08:00:00Z"}, net["host_headers"]
    )

    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert fixtures.read_run(api, run["id"])["cancellation_reason"] == "OPERATOR_CANCEL"


def test_second_confirm_rejected_and_minutes_not_double_counted(api):
    """Confirming an already-CONFIRMED incident is rejected; minutes are not double-counted.

    PRD: "Every confirmation and every reversal recomputes the owning run's `attributed_host_delay_minutes`: the sum of `delay_minutes` over that run's `CONFIRMED` host-attributable incidents only."
    PRD: "sixth, state-machine legality of the requested transition (`ERR_INVALID_STATE`)"
    Design: Corner/state_machines/incident_confirm_twice_second_rejected
    """
    net = fixtures.run_0902_completed_20_late(api)
    incident = fixtures.code_incident(
        api, net, net["run"]["id"], "HOST_FREIGHT_HOLD", 20, segment_passage_id=net["passage_ids"][0]
    )
    fixtures.confirm_incident(api, incident["id"])

    response = api.confirm_delay_incident(incident["id"], PASSENGER_OPERATOR_HEADERS)

    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert fixtures.read_run(api, net["run"]["id"])["attributed_host_delay_minutes"] == 20


def test_capital_project_suspend_and_resume_cycle_leaves_capacity_unchanged(api):
    """The IN_PROGRESS -> SUSPENDED -> IN_PROGRESS loop never bumps segment capacity.

    PRD: "Starting construction moves `FUNDED` → `IN_PROGRESS` and places the segment's `status` on `CAPITAL_HOLD`; the same start action also resumes a `SUSPENDED` project back to `IN_PROGRESS`. Construction may be paused (`IN_PROGRESS` → `SUSPENDED`, optionally with a `reason`). Completion moves `IN_PROGRESS` → `COMPLETED` and, exactly once per project, adds the project's `added_frequency_capacity` to the segment's `capacity_trains_per_day` while returning the segment to `OPERABLE`."
    Design: Corner/state_machines/capital_project_suspend_and_restart_cycle
    """
    net = fixtures.setup_active_agreement(api)
    project = fixtures.create_project(api, net, added_frequency_capacity=4)
    fixtures.approve_project(api, net, project["id"], net["agreement_version"])
    api.start_capital_project(project["id"], net["host_headers"])
    api.suspend_capital_project(project["id"], {"reason": "weather"}, net["host_headers"])

    resumed = validate_success(api.start_capital_project(project["id"], net["host_headers"]), 200)

    assert resumed["status"] == "IN_PROGRESS"
    assert fixtures.read_segment(api, net["seg1"]["id"])["capacity_trains_per_day"] == 20


def test_window_released_directly_from_planned_keeps_full_allowance(api):
    """Releasing a never-locked window consumes nothing; availability stays 40.00.

    PRD: "Releasing a window moves it from `PLANNED` or `LOCKED` to `RELEASED`; releasing a locked window restores exactly its `window_hours` to the unit's weekly allowance and recomputes `equipment_week_hours_available`."
    Design: Corner/state_machines/maintenance_release_from_planned
    """
    net = fixtures.setup_network(api)
    window = fixtures.create_window(
        api,
        net,
        track_segment_id=net["seg1"]["id"],
        window_start_at="2026-09-08T06:00:00Z",
        window_end_at="2026-09-08T10:00:00Z",
        equipment_unit_id="EQ-2",
        clearance_buffer_minutes=15,
    )

    released = fixtures.release_window(api, net, window["id"])

    assert released["status"] == "RELEASED"
    assert released["equipment_week_hours_available"] == 40.00


def test_overturned_from_under_review_rejected_but_upheld_accepted(api):
    """OVERTURNED requires ESCALATED; UPHELD is accepted directly from UNDER_REVIEW.

    PRD: "From `UNDER_REVIEW`, only `UPHELD` is accepted — attempting `OVERTURNED` without prior escalation is rejected with `ERR_INVALID_STATE` — while from `ESCALATED` either outcome is accepted."
    Design: Corner/state_machines/dispute_overturned_from_under_review_rejected
    """
    net = fixtures.run_0902_completed_20_late(api)
    inc_host = fixtures.code_incident(
        api, net, net["run"]["id"], "HOST_FREIGHT_HOLD", 20, segment_passage_id=net["passage_ids"][0]
    )
    inc_weather = fixtures.code_incident(api, net, net["run"]["id"], "WEATHER", 4)
    dispute1 = fixtures.dispute_incident(api, inc_host["id"])
    dispute2 = fixtures.dispute_incident(api, inc_weather["id"])

    blocked = api.resolve_dispute(dispute1["id"], {"resolution": "OVERTURNED"}, SYSTEM_ADMIN_HEADERS)
    assert blocked.status_code == 409
    validate_error(blocked, ApiErrorId.ERR_INVALID_STATE)

    resolved = fixtures.resolve_dispute(api, dispute2["id"], "UPHELD")
    assert resolved["status"] == "RESOLVED"
    assert fixtures.read_incident(api, inc_weather["id"])["status"] == "CONFIRMED"
    assert fixtures.read_incident(api, inc_host["id"])["status"] == "DISPUTED"


def test_disputing_incident_creates_under_review_dispute_and_flips_incident(api):
    """POST dispute returns a new UNDER_REVIEW dispute and flips the incident to DISPUTED.

    PRD: "Either party — operator or host representative — may instead dispute an `OPEN` incident, which moves the incident to `DISPUTED` and creates a **DispatchPriorityDispute** in `UNDER_REVIEW`, carrying a free-text `reason`, the incident's `delay_incident_id`, and the denormalized `train_run_id`."
    Design: Corner/state_machines/incident_dispute_creates_dispute_in_under_review
    """
    net = fixtures.run_0902_completed_20_late(api)
    incident = fixtures.code_incident(
        api, net, net["run"]["id"], "HOST_FREIGHT_HOLD", 20, segment_passage_id=net["passage_ids"][0]
    )

    response = api.dispute_delay_incident(
        incident["id"], {"reason": "contest coding"}, PASSENGER_OPERATOR_HEADERS
    )

    dispute = validate_success(response, 201)
    assert dispute["status"] == "UNDER_REVIEW"
    assert dispute["delay_incident_id"] == incident["id"]
    assert dispute["train_run_id"] == net["run"]["id"]
    assert fixtures.read_incident(api, incident["id"])["status"] == "DISPUTED"
