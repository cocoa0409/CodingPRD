"""Validation priority pairs and cross-entity state gates."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import ApiErrorId, PASSENGER_OPERATOR_HEADERS, fixtures


def test_suspended_agreement_state_beats_invalid_settlement_period(api):
    """When the agreement is SUSPENDED and the period is out of range, the state error wins.

    The agreement is suspended, then a statement is requested for a period
    outside the agreement's effective range; both the agreement-active check
    and the settlement-period check fail, and the earlier one is reported.

    PRD: "When several checks apply to one request, the server evaluates them in a fixed priority order so that the reported failure is deterministic."
    PRD: "seventh, the requirement that the operating agreement be `ACTIVE` where applicable (`ERR_AGREEMENT_NOT_ACTIVE`); eighth, the run-completion passage-finality check (`ERR_RUN_PASSAGES_OPEN`); ninth, the maintenance clearance conflict (`ERR_MAINTENANCE_CONFLICT`); tenth, single-track actual occupancy conflict (`ERR_SEGMENT_OCCUPANCY_CONFLICT`); eleventh, internal schedule feasibility of a proposed timetable (`ERR_SCHEDULE_INFEASIBLE`); twelfth, segment capacity (`ERR_CAPACITY_EXCEEDED`); thirteenth, the equipment weekly allowance (`ERR_EQUIPMENT_ALLOWANCE_EXCEEDED`); fourteenth, cross-entity referential integrity (`ERR_REFERENTIAL_INTEGRITY`); fifteenth, settlement period validity (`ERR_SETTLEMENT_PERIOD_INVALID`); and sixteenth, funding period overlap (`ERR_FUNDING_PERIOD_OVERLAP`)."
    Design: Difficulty/priority_pair_validation_conflict/agreement_state_beats_settlement_period_fiscal
    """
    net = fixtures.setup_active_agreement(api)
    api.suspend_operating_agreement(net["agreement"]["id"], {}, net["host_headers"])

    response = api.create_settlement_statement(
        {
            "operating_agreement_id": net["agreement"]["id"],
            "period_start": "2027-10-01",
            "period_end": "2027-10-31",
        },
        PASSENGER_OPERATOR_HEADERS,
    )

    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)


def test_state_error_reported_regardless_of_period_validity(api):
    """The agreement-active failure is reported even when the period is also invalid.

    PRD: "Creation also requires the agreement to be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`)."
    PRD: "The statement period must lie within the agreement's effective range and must not overlap an existing `ISSUED` or `PAID` statement for the same agreement; violations are rejected with `ERR_SETTLEMENT_PERIOD_INVALID`."
    Design: Difficulty/priority_pair_validation_conflict/agreement_state_beats_settlement_period_fiscal
    """
    net = fixtures.setup_active_agreement(api)
    api.suspend_operating_agreement(net["agreement"]["id"], {}, net["host_headers"])

    response = api.create_settlement_statement(
        {
            "operating_agreement_id": net["agreement"]["id"],
            "period_start": "2027-10-01",
            "period_end": "2027-10-31",
        },
        PASSENGER_OPERATOR_HEADERS,
    )

    error = validate_error(response, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)
    assert error["error_id"] == "ERR_AGREEMENT_NOT_ACTIVE"
    assert response.status_code == 409


def _dual_conflict_world(api):
    """A 2-run day with a LOCKED zero-buffer window on segment 2 [09:20,09:40),
    run1 en route with passage 1 actualized, and run2's passage 2 ACTUALIZED
    early at [08:50,09:10) — so run1's passage-2 actualize at [08:43,09:35)
    violates both the maintenance clearance and the single-track occupancy rule.
    """
    net = fixtures.setup_published_timetable(api, trains_per_day=2, service_date="2026-09-03")
    r1, r2 = net["runs"]
    (r1p1, r1p2), (r2p1, r2p2) = net["passages"]
    window = fixtures.create_window(
        api,
        net,
        track_segment_id=net["seg2"]["id"],
        window_start_at="2026-09-03T09:20:00Z",
        window_end_at="2026-09-03T09:40:00Z",
        equipment_unit_id="EQ-X",
        clearance_buffer_minutes=0,
    )
    fixtures.lock_window(api, net, window["id"])
    fixtures.depart_run(api, net, r1["id"], "2026-09-03T08:00:00Z")
    fixtures.depart_run(api, net, r2["id"], "2026-09-03T10:00:00Z")
    fixtures.actualize_passage(api, net, r1p1["id"], "2026-09-03T08:00:00Z", "2026-09-03T08:27:00Z")
    # Run2's passage 2 actualized early at [08:50, 09:10) on segment 2.
    fixtures.actualize_passage(api, net, r2p2["id"], "2026-09-03T08:50:00Z", "2026-09-03T09:10:00Z")
    net.update({"r1p2": r1p2, "r2p2": r2p2, "window": window})
    return net


def test_maintenance_conflict_beats_occupancy_conflict(api):
    """An actualize violating both the clearance and occupancy rules reports the clearance error.

    The candidate passage [08:43,09:35) intersects the LOCKED window's expanded
    interval and also overlaps an ACTUALIZED passage on the same SINGLE segment;
    the maintenance check runs earlier in the declared order.

    PRD: "Actualization enforces two guards, in the priority order of §2.7: the actual interval must not intersect a `LOCKED` maintenance window on the same segment under clearance-buffer semantics (`ERR_MAINTENANCE_CONFLICT`), and on a `SINGLE` segment the actual interval must not overlap any other `ACTUALIZED` passage on that segment, half-open so exact adjacency is allowed (`ERR_SEGMENT_OCCUPANCY_CONFLICT`)."
    Design: Difficulty/priority_pair_validation_conflict/maintenance_safety_beats_occupancy_temporal
    """
    net = _dual_conflict_world(api)

    response = api.actualize_segment_passage(
        net["r1p2"]["id"],
        {"actual_entry_at": "2026-09-03T08:43:00Z", "actual_exit_at": "2026-09-03T09:35:00Z"},
        net["host_headers"],
    )

    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_MAINTENANCE_CONFLICT)
    # The rejected actualize persists nothing.
    assert fixtures.read_passage(api, net["r1p2"]["id"])["status"] == "PLANNED"


def test_dual_failure_reports_exactly_one_error_and_leaves_passage_planned(api):
    """The dual-failure actualize is rejected once and the passage stays PLANNED.

    PRD: "ninth, the maintenance clearance conflict (`ERR_MAINTENANCE_CONFLICT`); tenth, single-track actual occupancy conflict (`ERR_SEGMENT_OCCUPANCY_CONFLICT`)"
    Design: Difficulty/priority_pair_validation_conflict/maintenance_safety_beats_occupancy_temporal
    """
    net = _dual_conflict_world(api)

    response = api.actualize_segment_passage(
        net["r1p2"]["id"],
        {"actual_entry_at": "2026-09-03T08:43:00Z", "actual_exit_at": "2026-09-03T09:35:00Z"},
        net["host_headers"],
    )

    error = validate_error(response, ApiErrorId.ERR_MAINTENANCE_CONFLICT)
    assert error["error_id"] == "ERR_MAINTENANCE_CONFLICT"
    passage = fixtures.read_passage(api, net["r1p2"]["id"])
    assert passage["status"] == "PLANNED"
    assert passage["actual_entry_at"] is None
    assert passage["actual_exit_at"] is None


def test_ratify_rejected_while_agreement_is_draft(api):
    """Ratification requires the agreement to be ACTIVE; while DRAFT it fails.

    PRD: "Ratification by the owning `HostRailroadRep` moves `UNDER_REVIEW` → `RATIFIED` and requires the operating agreement to be `ACTIVE` — otherwise the request fails with `ERR_AGREEMENT_NOT_ACTIVE`."
    Design: Difficulty/cross_entity_state_dependency/ratify_requires_active_agreement
    """
    net = fixtures.setup_draft_agreement(api)
    timetable = fixtures.timetable_to_under_review(api, net)

    response = api.ratify_timetable(timetable["id"], net["host_headers"])

    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)
    assert fixtures.read_timetable(api, timetable["id"])["status"] == "UNDER_REVIEW"


def test_ratify_succeeds_once_the_agreement_is_active(api):
    """After activation the same ratify call succeeds with no change to the timetable's terms.

    PRD: "Ratification by the owning `HostRailroadRep` moves `UNDER_REVIEW` → `RATIFIED` and requires the operating agreement to be `ACTIVE` — otherwise the request fails with `ERR_AGREEMENT_NOT_ACTIVE`."
    Design: Difficulty/cross_entity_state_dependency/ratify_requires_active_agreement
    """
    net = fixtures.setup_draft_agreement(api)
    timetable = fixtures.timetable_to_under_review(api, net)

    blocked = api.ratify_timetable(timetable["id"], net["host_headers"])
    assert blocked.status_code == 409
    validate_error(blocked, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)

    fixtures.activate_agreement(api, net, net["agreement"]["id"])
    ratified = fixtures.ratify_timetable(api, net, timetable["id"])
    assert ratified["status"] == "RATIFIED"


def test_complete_rejected_while_a_passage_is_still_planned(api):
    """Completing with a PLANNED passage is rejected with ERR_RUN_PASSAGES_OPEN.

    Passage 1 is ACTUALIZED; passage 2 is still PLANNED when complete is first
    attempted.

    PRD: "Recording the actual destination arrival with an `actual_arrival_at` instant completes the run — but only when every one of its passages is already `ACTUALIZED` or `SKIPPED`; completing with a passage still `PLANNED` is rejected with `ERR_RUN_PASSAGES_OPEN`."
    Design: Difficulty/cross_entity_state_dependency/complete_requires_all_passages_final
    """
    net = fixtures.setup_published_timetable(api, trains_per_day=1, service_date="2026-09-02")
    run = net["runs"][0]
    p1, _p2 = net["passages"][0]
    fixtures.depart_run(api, net, run["id"], "2026-09-02T08:00:00Z")
    fixtures.actualize_passage(api, net, p1["id"], "2026-09-02T08:00:00Z", "2026-09-02T08:27:00Z")

    response = api.complete_train_run(
        run["id"], {"actual_arrival_at": "2026-09-02T09:17:00Z"}, net["host_headers"]
    )

    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_RUN_PASSAGES_OPEN)
    assert fixtures.read_run(api, run["id"])["status"] == "EN_ROUTE"


def test_complete_succeeds_once_the_last_passage_is_final(api):
    """Once the last passage is ACTUALIZED, complete succeeds and the run is on time.

    The run arrives at its scheduled 09:17, so the arrival delay is 0.

    PRD: "Recording the actual destination arrival with an `actual_arrival_at` instant completes the run — but only when every one of its passages is already `ACTUALIZED` or `SKIPPED`; completing with a passage still `PLANNED` is rejected with `ERR_RUN_PASSAGES_OPEN`."
    PRD: "Completion moves `EN_ROUTE` → `COMPLETED` and computes three results: `destination_arrival_delay_minutes`, the actual-minus-scheduled arrival difference floored to whole minutes and clamped at zero"
    Design: Difficulty/cross_entity_state_dependency/complete_requires_all_passages_final
    """
    net = fixtures.setup_published_timetable(api, trains_per_day=1, service_date="2026-09-02")
    run = net["runs"][0]
    p1, p2 = net["passages"][0]
    fixtures.depart_run(api, net, run["id"], "2026-09-02T08:00:00Z")
    fixtures.actualize_passage(api, net, p1["id"], "2026-09-02T08:00:00Z", "2026-09-02T08:27:00Z")

    blocked = api.complete_train_run(
        run["id"], {"actual_arrival_at": "2026-09-02T09:17:00Z"}, net["host_headers"]
    )
    assert blocked.status_code == 409

    fixtures.actualize_passage(api, net, p2["id"], "2026-09-02T08:27:00Z", "2026-09-02T09:17:00Z")
    completed = fixtures.complete_run(api, net, run["id"], "2026-09-02T09:17:00Z")
    assert completed["status"] == "COMPLETED"
    assert completed["destination_arrival_delay_minutes"] == 0
    assert completed["on_time_endpoint"] is True
