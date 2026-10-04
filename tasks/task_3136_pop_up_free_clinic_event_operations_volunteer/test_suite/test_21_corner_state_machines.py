"""Corner coverage — state machines: terminal lockdown, idempotency,
posture-gated child operations, denial-code cascades, encounter abandon
compensation, clock-driven review expiry, handoff checklist gate, and the
end-service turn-away cascade."""

from test_helpers import (
    CLOCK_START_UTC,
    TEST_USERS,
    begin_service_payload,
    create_event,
    create_event_in_service,
    create_event_site_locked,
    create_handoff_payload,
    create_volunteer,
    get_success_data,
    issue_ticket,
    setup_event_in_teardown,
    setup_event_with_open_encounter,
    setup_event_with_queued_ticket,
    validate_error,
    validate_paginated,
    validate_success,
)

CO = TEST_USERS["credentialing_officer_headers"]
CPR = TEST_USERS["community_partner_rep_headers"]
ED = TEST_USERS["event_director_headers"]
PA = TEST_USERS["platform_admin_headers"]
QM = TEST_USERS["queue_marshal_headers"]
SL = TEST_USERS["station_lead_headers"]
VC = TEST_USERS["volunteer_coordinator_headers"]


def test_cancel_terminal_event_returns_invalid_state(api):
    """PRD §3.8: "Cancellation is the alternate terminal path: from any
    pre-service posture — `PLANNING`, `SITE_LOCKED`, `STAFFING`, or `READY` —
    the `EventDirector` may cancel the event, which moves it to `CANCELLED`" —
    a second cancel on the terminal event is rejected with
    `ERR_INVALID_STATE`.

    Design: Corner/state_machines/cancel_terminal_event_returns_invalid_state
    """
    event = create_event(
        event_code="RAM-C1",
        service_date="2027-03-06",
        doors_open_utc="2027-03-06T10:00:00Z",
        total_patient_capacity=10,
    )
    cancelled = get_success_data(api.cancel_event(event["id"], ED))
    assert cancelled["posture"] == "CANCELLED"

    response = api.cancel_event(event["id"], ED)
    validate_error(response, "ERR_INVALID_STATE")

    event_now = validate_success(api.get_event(event["id"], ED))
    assert event_now["posture"] == "CANCELLED"


def test_open_doors_twice_idempotency_rejected(api):
    """PRD §2.4: "Two posture moves are operator-driven (opening doors and
    ending service, closing, and cancelling)" — once the event has moved
    `READY → IN_SERVICE`, a second open-doors call has no valid from-state and
    is rejected with `ERR_INVALID_STATE`.

    Design: Corner/state_machines/open_doors_twice_idempotency_rejected
    """
    event = create_event_in_service()
    response = api.open_doors(event["id"], ED)
    validate_error(response, "ERR_INVALID_STATE")

    event_now = validate_success(api.get_event(event["id"], ED))
    assert event_now["posture"] == "IN_SERVICE"


def test_ticket_issue_requires_in_service_posture(api):
    """PRD §3.6: "Issuance requires the event posture to be `IN_SERVICE`" and
    PRD §2.4: "a forbidden attempt is rejected with
    `ERR_EVENT_POSTURE_FORBIDS` (HTTP 409)".

    Design: Corner/state_machines/ticket_call_requires_in_service_posture
    """
    event = create_event_site_locked()
    response = api.issue_ticket(
        event["id"],
        {
            "patient_ref": "P-TC",
            "arrival_utc": "2026-10-03T09:00:00Z",
            "requested_service": "MEDICAL",
            "priority_tier": "STANDARD",
        },
        QM,
    )
    validate_error(response, "ERR_EVENT_POSTURE_FORBIDS")

    event_now = validate_success(api.get_event(event["id"], ED))
    assert event_now["tickets_issued_count"] == 0


def test_verification_deny_terminal_code_rejects_volunteer(api):
    """PRD §3.3: "The denial's effect on the volunteer splits by code:
    `UNVERIFIABLE` and `DISCIPLINE_MISMATCH` are terminal and push the
    volunteer `VERIFICATION_PENDING → REJECTED`, while `LICENSE_EXPIRED` and
    `STATE_MISMATCH` leave the volunteer eligible to request verification
    again."

    Design: Corner/state_machines/verification_deny_terminal_code_rejects_volunteer
    """
    event = create_event(
        event_code="RAM-DN",
        service_date="2027-04-03",
        doors_open_utc="2027-04-03T10:00:00Z",
        total_patient_capacity=10,
    )
    vol_a = create_volunteer(discipline="DENTAL", license_state_code="TN")
    vol_b = create_volunteer(discipline="DENTAL", license_state_code="TN")
    ver_a = get_success_data(
        api.request_verification(
            vol_a["id"],
            {"clinic_event_id": event["id"], "reviewer_notes": "a"},
            VC,
        )
    )
    ver_b = get_success_data(
        api.request_verification(
            vol_b["id"],
            {"clinic_event_id": event["id"], "reviewer_notes": "b"},
            VC,
        )
    )

    get_success_data(
        api.deny_verification(
            vol_a["id"], ver_a["id"], {"denial_code": "UNVERIFIABLE"}, CO
        )
    )
    get_success_data(
        api.deny_verification(
            vol_b["id"], ver_b["id"], {"denial_code": "LICENSE_EXPIRED"}, CO
        )
    )

    vol_a_now = validate_success(api.get_volunteer(vol_a["id"], VC))
    vol_b_now = validate_success(api.get_volunteer(vol_b["id"], VC))
    assert vol_a_now["status"] == "REJECTED"
    assert vol_b_now["status"] != "REJECTED"


def test_encounter_abandon_returns_ticket_to_queue(api):
    """PRD §3.6: "An encounter can instead be abandoned, moving `OPEN →
    ABANDONED`. Abandonment sends the patient back to the queue: the ticket
    transitions `IN_SERVICE → QUEUED` with a fresh tail-of-queue
    `queue_position`."

    Design: Corner/state_machines/encounter_abandon_returns_ticket_to_queue
    """
    ctx = setup_event_with_open_encounter()
    tickets, _ = validate_paginated(api.list_event_tickets(ctx["id"], QM))
    original_position = tickets[0]["queue_position"]

    abandoned = get_success_data(
        api.abandon_encounter(ctx["id"], ctx["encounter_id"], SL)
    )
    assert abandoned["status"] == "ABANDONED"

    tickets, _ = validate_paginated(api.list_event_tickets(ctx["id"], QM))
    assert tickets[0]["status"] == "QUEUED"
    assert tickets[0]["queue_position"] == original_position + 1

    event_now = validate_success(api.get_event(ctx["id"], ED))
    assert event_now["tickets_issued_count"] == 1


def test_verification_expired_review_on_clock_passing(api):
    """PRD §2.9: "Advancing the clock past an event's `service_date` while a
    license verification for that event is still `PENDING` transitions that
    verification to `EXPIRED_REVIEW`."

    Design: Corner/state_machines/verification_expired_review_on_clock_passing
    """
    get_success_data(api.set_clock(CLOCK_START_UTC, PA))
    event = create_event(
        event_code="RAM-EX",
        service_date="2026-10-03",
        doors_open_utc="2026-10-03T10:00:00Z",
        total_patient_capacity=10,
    )
    volunteer = create_volunteer(discipline="VISION", license_state_code="TN")
    verification = get_success_data(
        api.request_verification(
            volunteer["id"],
            {"clinic_event_id": event["id"], "reviewer_notes": "pending"},
            VC,
        )
    )

    get_success_data(api.set_clock("2026-10-04T00:00:00Z", PA))
    verifications, _ = validate_paginated(
        api.list_volunteer_verifications(volunteer["id"], CO)
    )
    by_id = {v["id"]: v for v in verifications}
    assert by_id[verification["id"]]["status"] == "EXPIRED_REVIEW"


def test_handoff_accept_requires_checklist_complete(api):
    """PRD §3.8: "Acceptance belongs to the `CommunityPartnerRep`, who moves
    `PACKET_ASSEMBLED → ACCEPTED` only when `teardown_checklist_complete` is
    true, otherwise `ERR_TEARDOWN_INCOMPLETE`."

    Design: Corner/state_machines/handoff_accept_requires_checklist_complete
    """
    event = setup_event_in_teardown()
    handoff = get_success_data(
        api.create_handoff(
            event["id"],
            create_handoff_payload(teardown_checklist_complete=False),
            ED,
        )
    )
    assembled = get_success_data(
        api.assemble_handoff_packet(event["id"], handoff["id"], ED)
    )
    assert assembled["status"] == "PACKET_ASSEMBLED"

    response = api.accept_handoff(event["id"], handoff["id"], CPR)
    validate_error(response, "ERR_TEARDOWN_INCOMPLETE")

    handoffs, _ = validate_paginated(api.list_event_handoffs(event["id"], ED))
    assert handoffs[0]["status"] == "PACKET_ASSEMBLED"


def test_end_service_cascades_queued_to_turned_away(api):
    """PRD §3.8: "The end-of-service cascade turns away everyone still
    waiting: every `QUEUED` ticket transitions to `TURNED_AWAY` with
    `turn_away_reason` set to `EVENT_ENDED`, and the event's
    `unmet_demand_count` is recomputed."

    Design: Corner/state_machines/end_service_cascades_queued_to_turned_away
    """
    event = create_event_in_service()
    issue_ticket(event["id"], patient_ref="P-E1", priority_tier="STANDARD")
    issue_ticket(event["id"], patient_ref="P-E2", priority_tier="VULNERABLE")

    ended = get_success_data(api.end_service(event["id"], ED))
    assert ended["posture"] == "TEARDOWN"

    event_now = validate_success(api.get_event(event["id"], ED))
    assert event_now["unmet_demand_count"] == 2

    tickets, _ = validate_paginated(api.list_event_tickets(event["id"], QM))
    assert len(tickets) == 2
    for ticket in tickets:
        assert ticket["status"] == "TURNED_AWAY"
        assert ticket["turn_away_reason"] == "EVENT_ENDED"
