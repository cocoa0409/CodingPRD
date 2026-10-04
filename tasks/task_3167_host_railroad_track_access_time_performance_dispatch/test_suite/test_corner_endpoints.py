"""Endpoint corners: publish materialization and the amend cascade."""

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from test_helpers import PASSENGER_OPERATOR_HEADERS, fixtures


def test_publish_materializes_one_run_and_two_passages(api):
    """Publishing a 1-train, 1-day, 2-segment timetable materializes 1 run and 2 passages.

    PRD: "Publication **materializes the operating plan**: one `TrainRun` is created per service date from `service_date_start` through `service_date_end` inclusive, per daily frequency, each in `SCHEDULED` status with a sequence-based `train_number`, its `timetable_id` set, and its `scheduled_departure_at` and `scheduled_arrival_at` computed from the schedule walk. For each run, one `SegmentPassage` per track segment of the corridor is created in `PLANNED` status, ordered by `segment_sequence_no` copied from the segment, with `planned_entry_at` and `planned_exit_at` per the walk."
    Design: Corner/endpoints/publish_materializes_runs_and_passages
    """
    net = fixtures.setup_active_agreement(api)
    timetable = fixtures.timetable_to_ratified(api, net)

    published = fixtures.publish_timetable(api, timetable["id"])
    assert published["status"] == "PUBLISHED"

    runs, meta_runs = validate_paginated(
        api.list_train_runs(PASSENGER_OPERATOR_HEADERS, params={"timetable_id": timetable["id"]})
    )
    assert meta_runs["total_count"] == 1
    assert runs[0]["status"] == "SCHEDULED"
    assert runs[0]["timetable_id"] == timetable["id"]

    passages, meta_passages = validate_paginated(
        api.list_segment_passages(PASSENGER_OPERATOR_HEADERS, params={"train_run_id": runs[0]["id"]})
    )
    assert meta_passages["total_count"] == 2
    assert [p["status"] for p in passages] == ["PLANNED", "PLANNED"]
    assert passages[0]["track_segment_id"] == net["seg1"]["id"]
    assert passages[1]["track_segment_id"] == net["seg2"]["id"]
    assert passages[0]["segment_sequence_no"] == 1
    assert passages[1]["segment_sequence_no"] == 2


def test_amend_bumps_version_seq_and_returns_in_flight_timetable_to_draft(api):
    """A successful amend bumps version and amendment_seq and cascades in-flight timetables.

    The UNDER_REVIEW timetable of the amended agreement returns to DRAFT.

    PRD: "An accepted amendment leaves the agreement `ACTIVE`, increments `amendment_seq` by one, bumps the agreement's `version` by one, and forces every timetable of this agreement sitting in `PROPOSED` or `UNDER_REVIEW` back to `DRAFT`, since the negotiated basis of those schedules has changed."
    Design: Corner/endpoints/amend_cascade_returns_in_flight_timetable_to_draft
    """
    net = fixtures.setup_active_agreement(api)
    timetable = fixtures.timetable_to_under_review(api, net)
    observed_version = net["agreement_version"]

    amended = get_success_data(
        api.amend_operating_agreement(
            net["agreement"]["id"],
            {"expected_operating_agreement_version": observed_version, "penalty_rate_cents_per_minute": 75},
            PASSENGER_OPERATOR_HEADERS,
        )
    )

    assert amended["version"] == observed_version + 1
    assert amended["amendment_seq"] == 1
    assert amended["penalty_rate_cents_per_minute"] == 75
    assert amended["status"] == "ACTIVE"
    assert fixtures.read_timetable(api, timetable["id"])["status"] == "DRAFT"
