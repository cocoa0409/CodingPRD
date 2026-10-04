"""Boundary precision: ticket issuance at the exact capacity ceiling, and the
sterilization backlog strictly-greater-than-6 degrade threshold."""

from test_helpers import (
    TEST_USERS,
    create_event_in_service,
    get_success_data,
    issue_ticket,
    setup_event_with_operational_sterile_station,
    validate_error,
    validate_paginated,
    validate_success,
)

ED = TEST_USERS["event_director_headers"]
QM = TEST_USERS["queue_marshal_headers"]
SL = TEST_USERS["station_lead_headers"]
ST = TEST_USERS["sterilization_tech_headers"]


class TestTicketIssueAtExactCapacity:
    def test_issue_below_then_at_capacity_then_rejected(self, api):
        """PRD §3.6: "when `tickets_issued_count` already equals
        `total_patient_capacity`, further issuance is rejected with
        `ERR_CAPACITY_EXHAUSTED` — the boundary is inclusive, so issuing at
        exactly capacity fails."

        Design: Difficulty/boundary_precision_check/ticket_issue_at_exact_capacity_rejected
        """
        event = create_event_in_service(
            event_overrides={"total_patient_capacity": 2}
        )
        first = validate_success(
            api.issue_ticket(
                event["id"],
                {
                    "patient_ref": "P-1",
                    "arrival_utc": "2026-10-03T10:00:00Z",
                    "requested_service": "MEDICAL",
                    "priority_tier": "STANDARD",
                },
                QM,
            ),
            201,
        )
        assert first["status"] == "QUEUED"
        second = validate_success(
            api.issue_ticket(
                event["id"],
                {
                    "patient_ref": "P-2",
                    "arrival_utc": "2026-10-03T10:05:00Z",
                    "requested_service": "MEDICAL",
                    "priority_tier": "STANDARD",
                },
                QM,
            ),
            201,
        )
        assert second["status"] == "QUEUED"

        # Third issue: tickets_issued_count == 2 == capacity -> rejected.
        response = api.issue_ticket(
            event["id"],
            {
                "patient_ref": "P-3",
                "arrival_utc": "2026-10-03T10:10:00Z",
                "requested_service": "MEDICAL",
                "priority_tier": "STANDARD",
            },
            QM,
        )
        validate_error(response, "ERR_CAPACITY_EXHAUSTED")

    def test_rejected_issue_leaves_counter_unchanged(self, api):
        """PRD §3.6: "A successfully issued ticket enters `QUEUED` status, the
        event's `tickets_issued_count` increments" — and a rejected issue at
        the capacity boundary does not move the counter.

        Design: Difficulty/boundary_precision_check/ticket_issue_at_exact_capacity_rejected
        """
        event = create_event_in_service(
            event_overrides={"total_patient_capacity": 2}
        )
        issue_ticket(event["id"], patient_ref="P-1")
        issue_ticket(event["id"], patient_ref="P-2")
        response = api.issue_ticket(
            event["id"],
            {
                "patient_ref": "P-3",
                "arrival_utc": "2026-10-03T10:10:00Z",
                "requested_service": "MEDICAL",
                "priority_tier": "STANDARD",
            },
            QM,
        )
        validate_error(response, "ERR_CAPACITY_EXHAUSTED")

        event_now = validate_success(api.get_event(event["id"], ED))
        assert event_now["tickets_issued_count"] == 2


class TestSterilizationBacklogBoundary:
    def test_backlog_exactly_at_max_does_not_degrade(self, api):
        """PRD §2.8: "The sterilization backlog ceiling is 6 pending batches:
        a sterilization-requiring `OPERATIONAL` station degrades only when the
        event's pending batch count is strictly greater than 6, so a backlog
        of exactly 6 leaves stations alone while a backlog of 7 degrades
        them."

        Design: Difficulty/boundary_precision_check/sterilization_backlog_at_max_does_not_degrade
        """
        ctx = setup_event_with_operational_sterile_station()
        event_id, station_id = ctx["id"], ctx["station_id"]

        get_success_data(
            api.start_sterilization_cycle(
                event_id, {"instrument_batch_size": 6}, ST
            )
        )
        stations, _ = validate_paginated(api.list_event_stations(event_id, SL))
        assert stations[0]["status"] == "OPERATIONAL", (
            "a backlog of exactly 6 must not degrade the station"
        )

    def test_backlog_one_above_max_degrades(self, api):
        """PRD §3.5: "Whenever the backlog for an event with a
        sterilization-requiring `OPERATIONAL` station rises strictly above 6
        pending batches, that station degrades automatically to `DEGRADED`;
        a backlog of exactly 6 does not trigger degradation."

        Design: Difficulty/boundary_precision_check/sterilization_backlog_at_max_does_not_degrade
        """
        ctx = setup_event_with_operational_sterile_station()
        event_id, station_id = ctx["id"], ctx["station_id"]

        get_success_data(
            api.start_sterilization_cycle(
                event_id, {"instrument_batch_size": 6}, ST
            )
        )
        get_success_data(
            api.start_sterilization_cycle(
                event_id, {"instrument_batch_size": 1}, ST
            )
        )
        stations, _ = validate_paginated(api.list_event_stations(event_id, SL))
        assert stations[0]["status"] == "DEGRADED", (
            "a backlog of 7 must degrade the station"
        )
