"""Operations gated on the state of a neighbouring entity rather than their own."""

from test_helpers import (
    COORDINATOR_HEADERS,
    ERR_CERTIFICATION_MISSING,
    ERR_EVENT_STATE_INVALID,
    ERR_STAFF_MEMBER_NOT_ACTIVE,
    SUPERVISOR_HEADERS,
    advance_event,
    assert_fields,
    assert_instant,
    assert_slot_fill,
    certified_member,
    change_member_status,
    create_assignment,
    create_issue,
    create_member,
    event_with_active_plan,
    err,
    event_in_progress_with_slot,
    make_staff_member_headers,
    ok,
    read_assignment,
    read_issue,
    read_member,
    read_plan,
    read_slot,
    set_clock,
)
from test_helpers.factories import (
    attendance_payload,
    guest_services_rep_payload,
    issue_assign_payload,
    ticket_taker_payload,
)


def _planned_event_with_scheduled_worker(client):
    """A PLANNED event whose ACTIVE plan already carries one scheduled worker."""
    set_clock(client, "2026-09-12T15:00:00Z")
    context = event_with_active_plan(
        client,
        position_type_payload=ticket_taker_payload(required_certifications=[]),
        slot_overrides={
            "zone_code": "Z920",
            "shift_start": "2026-09-12T16:00:00Z",
            "shift_end": "2026-09-12T20:00:00Z",
            "required_headcount_override": 1,
        },
        name="Parent State Gate Fixture",
        doors_open_at="2026-09-12T15:30:00Z",
        doors_close_at="2026-09-12T21:00:00Z",
        expected_attendance=20000,
    )
    member = create_member(
        client,
        full_name="Abe Larkin",
        employment_type="PART_TIME_EMPLOYEE",
        seniority_date="2024-01-01T00:00:00Z",
        hourly_rate_cents=2000,
    )
    context["member"] = member
    context["assignment"] = create_assignment(client, context["slot"]["id"], member["id"])
    set_clock(client, "2026-09-12T16:00:00Z")
    return context


def test_check_in_is_refused_while_the_parent_event_is_only_planned(client):
    """The worker's own row is impeccable, so only the parent event can be refusing.

    "Checking in moves the assignment `SCHEDULED → CHECKED_IN` and requires the
    event to stand exactly in `IN_PROGRESS` — before that the request is refused
    with `ERR_EVENT_STATE_INVALID` — and the block not to be `CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_event_in_progress
    """
    context = _planned_event_with_scheduled_worker(client)
    member_headers = make_staff_member_headers(context["member"]["id"])

    assert_fields(context["event"], status="PLANNED")
    assert_fields(read_member(client, context["member"]["id"]), status="ACTIVE")

    err(
        client.record_attendance(
            context["assignment"]["id"], attendance_payload("CHECK_IN"), member_headers
        ),
        ERR_EVENT_STATE_INVALID,
    )

    row = read_assignment(client, context["assignment"]["id"])
    assert_fields(
        row,
        attendance_status="SCHEDULED",
        check_in_at=None,
        late_check_in=False,
        payout_status="PENDING",
    )


def test_the_identical_check_in_succeeds_once_the_event_is_in_progress(client):
    """Advancing the parent is the only change the retry needs.

    "Crossing into `IN_PROGRESS` is also what makes check-in, no-show marking and
    refund decisions permissible."

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_event_in_progress
    """
    context = _planned_event_with_scheduled_worker(client)
    member_headers = make_staff_member_headers(context["member"]["id"])

    err(
        client.record_attendance(
            context["assignment"]["id"], attendance_payload("CHECK_IN"), member_headers
        ),
        ERR_EVENT_STATE_INVALID,
    )

    event = advance_event(client, context["event"]["id"], "IN_PROGRESS")
    assert_fields(event, status="IN_PROGRESS")
    assert_fields(read_plan(client, context["plan"]["id"]), status="LOCKED")

    row = ok(
        client.record_attendance(
            context["assignment"]["id"], attendance_payload("CHECK_IN"), member_headers
        )
    )
    assert_fields(row, attendance_status="CHECKED_IN", late_check_in=False)
    assert_instant(row["check_in_at"], "2026-09-12T16:00:00.000Z", "check_in_at")


def test_the_parent_gate_is_action_specific_not_entity_wide(client):
    """Creating the assignment is legal from PLANNED even though checking in is not.

    "Direct assignment requires the owning event to be in `PLANNED` or
    `IN_PROGRESS` and the owning plan to be in `ACTIVE` or `LOCKED`, failing which
    the request is refused with `ERR_EVENT_STATE_INVALID` or
    `ERR_PLAN_STATE_INVALID` respectively, and it runs the same eligibility ladder
    in the same order."

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_event_in_progress
    """
    context = _planned_event_with_scheduled_worker(client)
    member_headers = make_staff_member_headers(context["member"]["id"])

    assert_fields(context["assignment"], attendance_status="SCHEDULED", source="MANUAL")
    assert_slot_fill(
        read_slot(client, context["slot"]["id"]), filled=1, required=1, status="FILLED"
    )

    err(
        client.record_attendance(
            context["assignment"]["id"], attendance_payload("CHECK_IN"), member_headers
        ),
        ERR_EVENT_STATE_INVALID,
    )

    # The refusal touched nothing: the block is still full.
    assert_slot_fill(
        read_slot(client, context["slot"]["id"]), filled=1, required=1, status="FILLED"
    )


def _issue_and_three_responders(client):
    """One OPEN conduct issue and three workers in three different standings."""
    set_clock(client, "2026-09-12T19:00:00Z")
    context = event_in_progress_with_slot(
        client,
        position_type_payload=guest_services_rep_payload(
            required_certifications=["CODE_OF_CONDUCT"]
        ),
        slot_overrides={
            "zone_code": "Z930",
            "shift_start": "2026-09-12T18:00:00Z",
            "shift_end": "2026-09-12T22:00:00Z",
            "required_headcount_override": 1,
        },
        name="Sideways Gate Fixture",
        doors_open_at="2026-09-12T17:00:00Z",
        doors_close_at="2026-09-12T23:00:00Z",
        expected_attendance=20000,
    )
    suspended = certified_member(
        client,
        "CODE_OF_CONDUCT",
        full_name="Bea Cortez",
        employment_type="PART_TIME_EMPLOYEE",
        seniority_date="2023-01-01T00:00:00Z",
        hourly_rate_cents=2400,
    )
    uncertified = create_member(
        client,
        full_name="Cal Duffy",
        employment_type="PART_TIME_EMPLOYEE",
        seniority_date="2023-02-01T00:00:00Z",
        hourly_rate_cents=2400,
    )
    eligible = certified_member(
        client,
        "CODE_OF_CONDUCT",
        full_name="Dev Haley",
        employment_type="PART_TIME_EMPLOYEE",
        seniority_date="2023-03-01T00:00:00Z",
        hourly_rate_cents=2400,
    )
    change_member_status(client, suspended["id"], "SUSPENDED", "Pending conduct review")
    issue = create_issue(
        client,
        context["event"]["id"],
        channel="TEXT_LINE",
        category="CONDUCT_VIOLATION",
        severity="HIGH",
        description="Abusive language in section 118",
        seat_reference="118-12-4",
    )
    context.update(
        issue=issue, suspended=suspended, uncertified=uncertified, eligible=eligible
    )
    return context


def _assign(client, issue_id, member_id):
    return client.assign_guest_issue(
        issue_id, issue_assign_payload(member_id), SUPERVISOR_HEADERS
    )


def test_responder_standing_is_reported_ahead_of_credential_compliance(client):
    """A suspended but fully certified responder is refused for standing, not credentials.

    "Cross-entity state gates, evaluated in this order: first the parent event's
    status admits the child operation (`ERR_EVENT_STATE_INVALID`), then the
    referenced worker is `ACTIVE` (`ERR_STAFF_MEMBER_NOT_ACTIVE`), then the
    referenced accessibility pool is `AVAILABLE` (`ERR_RESOURCE_NOT_AVAILABLE`)."

    Design: Difficulty/cross_entity_state_dependency/issue_assign_requires_active_certified_member
    """
    context = _issue_and_three_responders(client)

    err(
        _assign(client, context["issue"]["id"], context["suspended"]["id"]),
        ERR_STAFF_MEMBER_NOT_ACTIVE,
    )

    issue = read_issue(client, context["issue"]["id"])
    assert_fields(issue, status="OPEN", assigned_staff_member_id=None)
    member = read_member(client, context["suspended"]["id"])
    assert_fields(
        member, status="SUSPENDED", last_status_reason="Pending conduct review"
    )


def test_active_but_uncertified_responder_is_refused_then_a_compliant_one_is_taken(client):
    """The credential gate fires only once standing has been cleared.

    "and the responder must hold a credential whose `status` is `VALID` for
    `CODE_OF_CONDUCT`, or the request is refused with `ERR_CERTIFICATION_MISSING`."

    Design: Difficulty/cross_entity_state_dependency/issue_assign_requires_active_certified_member
    """
    context = _issue_and_three_responders(client)
    issue_id = context["issue"]["id"]

    err(_assign(client, issue_id, context["uncertified"]["id"]), ERR_CERTIFICATION_MISSING)
    assert_fields(
        read_issue(client, issue_id), status="OPEN", assigned_staff_member_id=None
    )

    accepted = ok(_assign(client, issue_id, context["eligible"]["id"]))
    assert_fields(
        accepted,
        status="IN_PROGRESS",
        assigned_staff_member_id=context["eligible"]["id"],
    )


def test_handing_the_issue_over_never_restarts_the_response_clock(client):
    """Two refusals and one success all leave the original deadline in place.

    "Assignment deliberately does *not* restart the response clock:
    `sla_clock_started_at` and `sla_deadline` are left exactly as they were, and
    `sla_breached` is merely recomputed against that unchanged deadline."

    Design: Difficulty/cross_entity_state_dependency/issue_assign_requires_active_certified_member
    """
    context = _issue_and_three_responders(client)
    issue_id = context["issue"]["id"]
    filed = context["issue"]

    assert_fields(filed, severity="HIGH", sla_minutes=15, sla_breached=False)
    assert_instant(filed["sla_clock_started_at"], filed["created_at"], "sla_clock_started_at")
    assert_instant(filed["sla_deadline"], "2026-09-12T19:15:00.000Z", "sla_deadline")

    err(_assign(client, issue_id, context["suspended"]["id"]), ERR_STAFF_MEMBER_NOT_ACTIVE)
    err(_assign(client, issue_id, context["uncertified"]["id"]), ERR_CERTIFICATION_MISSING)
    ok(_assign(client, issue_id, context["eligible"]["id"]))

    handed_over = read_issue(client, issue_id)
    assert_fields(handed_over, status="IN_PROGRESS", sla_minutes=15, sla_breached=False)
    assert_instant(
        handed_over["sla_clock_started_at"], filed["created_at"], "sla_clock_started_at"
    )
    assert_instant(handed_over["sla_deadline"], "2026-09-12T19:15:00.000Z", "sla_deadline")
