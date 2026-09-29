"""Validation-ladder breadth: which rung speaks when several conditions hold at once."""

from test_helpers import (
    COORDINATOR_HEADERS,
    DIRECTOR_HEADERS,
    ERR_DUPLICATE_BID,
    ERR_GUEST_ISSUE_NOT_FOUND,
    ERR_INVALID_TIME_WINDOW,
    ERR_NOT_RESOURCE_OWNER,
    ERR_REFUND_BUDGET_EXHAUSTED,
    ERR_REFUND_STATE_INVALID,
    ERR_RELOCATION_ZONE_UNSTAFFED,
    ERR_REOPEN_LIMIT_REACHED,
    ERR_REOPEN_WINDOW_CLOSED,
    ERR_RESOLUTION_TYPE_MISMATCH,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STAFF_MEMBER_NOT_FOUND,
    ERR_STAFFING_PLAN_NOT_FOUND,
    ERR_UNAUTHENTICATED,
    ERR_VALIDATION_FAILED,
    ERR_ISSUE_STATE_INVALID,
    SUPERVISOR_HEADERS,
    activate_plan,
    advance_event,
    assert_cents,
    assert_fields,
    assert_instant,
    assert_slot_fill,
    assign_issue,
    create_assignment,
    create_bid,
    create_certification,
    create_elevator_operator,
    create_event,
    create_member,
    create_plan,
    create_slot,
    create_ticket_taker,
    created,
    err,
    headers_empty_user_id,
    headers_missing_role,
    headers_missing_user_id,
    headers_unknown_role,
    make_staff_member_headers,
    make_supervisor_headers,
    make_director_headers,
    ok,
    page,
    read_assignment,
    read_bid,
    read_event,
    read_issue,
    read_member,
    read_plan,
    read_slot,
    resolve_issue,
    set_clock,
)
from test_helpers.factories import (
    attendance_payload,
    certification_payload,
    event_payload,
    guest_issue_payload,
    issue_resolve_payload,
    position_slot_payload,
    refund_decision_payload,
    refund_request_payload,
    shift_bid_payload,
    usher_payload,
)

ABSENT_ID = "00000000-0000-0000-0000-0000000000ff"
TICKET_TAKER = {
    "base_hourly_rate_cents": 2000,
    "attendance_ratio_per_1000": 0.8,
    "min_headcount": 1,
    "required_certifications": [],
}


def _plain_event(client, name, **overrides):
    """A FORECAST event on 2026-09-20 with an eight-hour doors window."""
    return create_event(
        client,
        name=name,
        event_date="2026-09-20T00:00:00Z",
        doors_open_at="2026-09-20T13:00:00Z",
        doors_close_at="2026-09-20T21:00:00Z",
        expected_attendance=6000,
        **overrides,
    )


def _match_day_event(client, name, **overrides):
    """A FORECAST event on 2026-09-12 with a 17:00-23:00 doors window."""
    return create_event(
        client,
        name=name,
        event_date="2026-09-12T00:00:00Z",
        doors_open_at="2026-09-12T17:00:00Z",
        doors_close_at="2026-09-12T23:00:00Z",
        expected_attendance=6000,
        **overrides,
    )


def _responder(client, full_name="Ida Responder"):
    """An ACTIVE part-time worker holding the VALID code-of-conduct credential."""
    member = create_member(
        client,
        full_name=full_name,
        employment_type="PART_TIME_EMPLOYEE",
        seniority_date="2020-01-01T00:00:00Z",
        hourly_rate_cents=2000,
    )
    credential = create_certification(
        client,
        member["id"],
        "CODE_OF_CONDUCT",
        issued_on="2026-01-01T00:00:00Z",
        expires_on="2027-01-01T00:00:00Z",
    )
    assert_fields(credential, status="VALID")
    return member


def _issue_in_progress(client, event_id, responder_id, *, reporter, **overrides):
    """One issue filed by a named reporter and handed to a credentialled responder."""
    issue = created(
        client.create_guest_issue(
            guest_issue_payload(event_id, **overrides), make_supervisor_headers(reporter)
        )
    )
    assign_issue(client, issue["id"], responder_id, make_supervisor_headers(reporter))
    return issue


def _unset(entity, *fields):
    """A field the PRD calls absent reads as missing or null, never as a value."""
    for field in fields:
        assert entity.get(field) is None, (
            f"{field} should be absent here, got {entity.get(field)!r}"
        )


def test_three_header_faults_all_answer_unauthenticated_but_a_read_survives_one(client):
    """No role, an unknown role and an empty id are all 401; a read needs no id at all.

    "If `X-User-Role` is absent or is not one of the four role names below, or if `X-User-ID` is
    absent or empty on a mutating request, the request is refused with `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/validations/request_missing_auth_headers_returns_unauthenticated
    """
    set_clock(client, "2026-09-01T09:00:00Z")
    filing = event_payload(
        name="No Role Header",
        event_date="2026-09-20T00:00:00Z",
        doors_open_at="2026-09-20T13:00:00Z",
        doors_close_at="2026-09-20T21:00:00Z",
        expected_attendance=6000,
    )

    err(client.create_event(filing, headers_missing_role()), ERR_UNAUTHENTICATED)
    err(client.create_event(filing, headers_unknown_role()), ERR_UNAUTHENTICATED)
    err(client.create_event(filing, headers_empty_user_id()), ERR_UNAUTHENTICATED)

    _events, meta = page(client.list_events(headers_missing_user_id(), {"limit": 10, "offset": 0}))
    assert meta["total_count"] == 0, "none of the three refused filings created an event"


def test_the_wrong_role_is_refused_on_four_different_surfaces(client):
    """A coordinator, a supervisor and a worker each hit a door that is not theirs.

    "When the headers are well formed but the declared role is not among the roles the target
    endpoint admits, the refusal is `ERR_ROLE_NOT_PERMITTED` (403)."

    Design: Corner/validations/coordinator_on_event_lifecycle_returns_role_not_permitted
    """
    set_clock(client, "2026-09-01T09:00:00Z")
    event = _plain_event(client, "Role Gate Fixture")
    worker = create_member(client)

    err(
        client.event_lifecycle(event["id"], {"target_status": "CANCELLED"}, COORDINATOR_HEADERS),
        ERR_ROLE_NOT_PERMITTED,
    )
    err(
        client.create_event(
            event_payload(
                name="Coordinator Event",
                event_date="2026-09-21T00:00:00Z",
                doors_open_at="2026-09-21T13:00:00Z",
                doors_close_at="2026-09-21T21:00:00Z",
                expected_attendance=6000,
            ),
            COORDINATOR_HEADERS,
        ),
        ERR_ROLE_NOT_PERMITTED,
    )
    err(client.create_position_type(usher_payload(), SUPERVISOR_HEADERS), ERR_ROLE_NOT_PERMITTED)
    err(
        client.create_guest_issue(
            guest_issue_payload(
                event["id"], channel="KIOSK", category="LOST_FOUND", severity="LOW",
                description="Wallet at gate 2",
            ),
            make_staff_member_headers(worker["id"]),
        ),
        ERR_ROLE_NOT_PERMITTED,
    )

    assert_fields(read_event(client, event["id"]), status="FORECAST", version=1)
    _families, family_meta = page(client.list_position_types(COORDINATOR_HEADERS))
    assert family_meta["total_count"] == 0, "the refused filing registered no position family"
    _issues, issue_meta = page(
        client.list_guest_issues(SUPERVISOR_HEADERS, {"event_id": event["id"]})
    )
    assert issue_meta["total_count"] == 0, "the refused filing logged no issue"


def test_every_declared_interval_is_strict_but_the_schema_rung_speaks_first(client):
    """Reversed and zero-length windows are 422 time-window faults; a bad integer outranks them.

    "Interval ordering — an event's `doors_close_at` strictly after its `doors_open_at`, a shift
    block's `shift_end` strictly after its `shift_start`, a credential's `expires_on` strictly
    after its `issued_on`, and an accessibility booking's `window_end` strictly after its
    `window_start` (`ERR_INVALID_TIME_WINDOW`)."

    "A rejected request returns exactly one `error_id`: the one belonging to the lowest-numbered
    rule in the following ladder whose condition holds."

    Design: Corner/validations/interval_fields_out_of_order_return_invalid_time_window
    """
    set_clock(client, "2026-09-01T09:00:00Z")
    event = _plain_event(client, "Interval Fixture")
    family = create_ticket_taker(client, **TICKET_TAKER)
    plan = create_plan(client, event["id"], plan_variant="FORECAST_BASED")
    worker = create_member(client, full_name="Ada Usher")

    reversed_window = position_slot_payload(
        plan["id"],
        family["id"],
        zone_code="Z100",
        shift_start="2026-09-20T20:00:00Z",
        shift_end="2026-09-20T14:00:00Z",
    )
    err(client.create_position_slot(reversed_window, COORDINATOR_HEADERS), ERR_INVALID_TIME_WINDOW)
    err(
        client.create_position_slot(
            position_slot_payload(
                plan["id"],
                family["id"],
                zone_code="Z100",
                shift_start="2026-09-20T14:00:00Z",
                shift_end="2026-09-20T14:00:00Z",
            ),
            COORDINATOR_HEADERS,
        ),
        ERR_INVALID_TIME_WINDOW,
    )
    err(
        client.create_certification(
            certification_payload(
                worker["id"],
                "CODE_OF_CONDUCT",
                issued_on="2027-01-01T00:00:00Z",
                expires_on="2026-01-01T00:00:00Z",
            ),
            COORDINATOR_HEADERS,
        ),
        ERR_INVALID_TIME_WINDOW,
    )
    err(
        client.create_event(
            event_payload(
                name="Backwards Doors",
                event_date="2026-09-21T00:00:00Z",
                doors_open_at="2026-09-21T21:00:00Z",
                doors_close_at="2026-09-21T13:00:00Z",
                expected_attendance=6000,
            ),
            DIRECTOR_HEADERS,
        ),
        ERR_INVALID_TIME_WINDOW,
    )
    err(
        client.create_position_slot(
            dict(reversed_window, required_headcount_override=0), COORDINATOR_HEADERS
        ),
        ERR_VALIDATION_FAILED,
    )

    _slots, slot_meta = page(client.list_position_slots(COORDINATOR_HEADERS, {"plan_id": plan["id"]}))
    assert slot_meta["total_count"] == 0, "no block survived the five refusals"
    assert_cents(read_plan(client, plan["id"])["base_labor_cost_cents"], 0, "plan base cost")
    _certs, cert_meta = page(
        client.list_certifications(COORDINATOR_HEADERS, {"staff_member_id": worker["id"]})
    )
    assert cert_meta["total_count"] == 0, "no credential survived the reversed interval"


def test_a_missing_path_row_is_reported_before_a_missing_body_reference(client):
    """The path segment is resolved first, and within the body the declaration order rules.

    "Path identifier existence, left to right (the entity-specific 404)."

    "Body foreign-key existence, in entity declaration order (the entity-specific 404)."

    "The coordinator adds a block to a plan by naming the owning `plan_id`, the `position_type_id`
    of the family, a `zone_code` label such as `GATE_A`, `TOWER` or `BOWL`, and the `shift_start`
    and `shift_end` bounds of the window, where `shift_end` must fall strictly after
    `shift_start`."

    Design: Corner/validations/path_not_found_precedes_body_fk_not_found
    """
    set_clock(client, "2026-09-01T09:00:00Z")
    event = create_event(
        client,
        name="Not Found Order Fixture",
        event_date="2026-09-01T00:00:00Z",
        doors_open_at="2026-09-01T08:00:00Z",
        doors_close_at="2026-09-01T21:00:00Z",
        expected_attendance=6000,
    )
    plan = create_plan(client, event["id"], plan_variant="FORECAST_BASED")
    activate_plan(client, plan["id"], event["id"], 1)
    advance_event(client, event["id"], "IN_PROGRESS")
    issue = created(
        client.create_guest_issue(
            guest_issue_payload(
                event["id"], channel="KIOSK", category="LOST_FOUND", severity="LOW",
                description="Keys at gate 3",
            ),
            SUPERVISOR_HEADERS,
        )
    )

    err(
        client.assign_guest_issue(
            ABSENT_ID, {"staff_member_id": ABSENT_ID}, SUPERVISOR_HEADERS
        ),
        ERR_GUEST_ISSUE_NOT_FOUND,
    )
    err(
        client.assign_guest_issue(
            issue["id"], {"staff_member_id": ABSENT_ID}, SUPERVISOR_HEADERS
        ),
        ERR_STAFF_MEMBER_NOT_FOUND,
    )
    err(
        client.create_position_slot(
            position_slot_payload(
                ABSENT_ID,
                ABSENT_ID,
                zone_code="Z100",
                shift_start="2026-09-01T14:00:00Z",
                shift_end="2026-09-01T20:00:00Z",
            ),
            COORDINATOR_HEADERS,
        ),
        ERR_STAFFING_PLAN_NOT_FOUND,
    )

    untouched = read_issue(client, issue["id"])
    assert_fields(untouched, status="OPEN")
    _unset(untouched, "assigned_staff_member_id")


def test_a_worker_may_only_act_on_their_own_bids_and_shifts(client):
    """Bidding, withdrawing and clocking in for somebody else are all ownership refusals.

    "A worker filing a bid for somebody else, withdrawing somebody else's bid, or marking
    attendance on somebody else's assignment is refused with `ERR_NOT_RESOURCE_OWNER` (403)."

    "Resource ownership for worker-scoped writes — filing a bid, withdrawing a bid, and marking
    attendance while acting as a `StaffMember` (`ERR_NOT_RESOURCE_OWNER`)."

    Design: Corner/validations/staff_member_acting_on_another_members_row_returns_not_resource_owner
    """
    set_clock(client, "2026-09-12T10:00:00Z")
    event = _match_day_event(client, "Ownership Fixture")
    family = create_ticket_taker(client, **TICKET_TAKER)
    plan = create_plan(client, event["id"], plan_variant="FORECAST_BASED")
    slot = create_slot(
        client,
        plan["id"],
        family["id"],
        zone_code="Z100",
        shift_start="2026-09-12T19:00:00Z",
        shift_end="2026-09-12T23:05:00Z",
        required_headcount_override=2,
    )
    owner = create_member(
        client,
        full_name="Ada Owner",
        employment_type="PART_TIME_EMPLOYEE",
        seniority_date="2020-01-01T00:00:00Z",
        hourly_rate_cents=2000,
    )
    intruder = create_member(
        client,
        full_name="Ben Intruder",
        employment_type="PART_TIME_EMPLOYEE",
        seniority_date="2021-01-01T00:00:00Z",
        hourly_rate_cents=2000,
    )
    activate_plan(client, plan["id"], event["id"], 1)
    bid = create_bid(client, owner["id"], slot["id"])
    assignment = create_assignment(client, slot["id"], owner["id"])
    intruder_headers = make_staff_member_headers(intruder["id"])

    err(
        client.create_shift_bid(
            shift_bid_payload(owner["id"], slot["id"]), intruder_headers
        ),
        ERR_NOT_RESOURCE_OWNER,
    )
    err(client.withdraw_shift_bid(bid["id"], intruder_headers), ERR_NOT_RESOURCE_OWNER)
    err(
        client.record_attendance(
            assignment["id"], attendance_payload("CHECK_IN"), intruder_headers
        ),
        ERR_NOT_RESOURCE_OWNER,
    )

    assert_fields(read_bid(client, bid["id"]), status="SUBMITTED", staff_member_id=owner["id"])
    untouched = read_assignment(client, assignment["id"])
    assert_fields(untouched, attendance_status="SCHEDULED")
    _unset(untouched, "check_in_at")
    _bids, meta = page(
        client.list_shift_bids(COORDINATOR_HEADERS, {"position_slot_id": slot["id"]})
    )
    assert meta["total_count"] == 1, "the refused filing added no second bid"


def test_the_operator_who_asked_for_the_refund_may_not_approve_it(client):
    """Same role, different identity: only the second supervisor can move the money.

    "The `X-User-ID` that decides a refund on a guest issue must differ both from the
    `refund_requested_by_user_id` recorded when the ask was filed and from the
    `reported_by_user_id` recorded when the issue was first filed."

    "A supervisor first files the ask, supplying `refund_requested_cents`; the system stores that
    amount, records `refund_requested_by_user_id` from `X-User-ID`, and moves `refund_status`
    `NONE → PENDING`."

    Design: Corner/validations/refund_requester_deciding_own_ask_returns_segregation_of_duties
    """
    set_clock(client, "2026-09-12T19:00:00Z")
    event = _match_day_event(client, "Segregation Fixture")
    assert_cents(event["refund_budget_total_cents"], 100000, "declared default budget")
    plan = create_plan(client, event["id"], plan_variant="FORECAST_BASED")
    activate_plan(client, plan["id"], event["id"], 1)
    advance_event(client, event["id"], "IN_PROGRESS")
    responder = _responder(client)
    issue = _issue_in_progress(
        client,
        event["id"],
        responder["id"],
        reporter="sup-9",
        channel="TEXT_LINE",
        category="OTHER",
        severity="MEDIUM",
        description="Merchandise mix-up",
    )

    asked = ok(
        client.file_refund_request(
            issue["id"], refund_request_payload(2000), make_supervisor_headers("sup-1")
        )
    )
    assert_fields(asked, refund_status="PENDING", refund_requested_by_user_id="sup-1")
    assert_cents(asked["refund_requested_cents"], 2000, "refund_requested_cents")
    assert_cents(
        read_event(client, event["id"])["refund_budget_remaining_cents"], 100000, "ask moves no money"
    )

    err(
        client.file_refund_decision(
            issue["id"], refund_decision_payload("APPROVE"), make_supervisor_headers("sup-1")
        ),
        ERR_SEGREGATION_OF_DUTIES,
    )
    refused = read_issue(client, issue["id"])
    assert_fields(refused, refund_status="PENDING")
    assert_cents(refused["refund_approved_cents"], 0, "nothing authorized by the refusal")
    _unset(refused, "refund_decided_by_user_id")
    assert_cents(
        read_event(client, event["id"])["refund_budget_remaining_cents"], 100000, "ledger untouched"
    )

    decided = ok(
        client.file_refund_decision(
            issue["id"], refund_decision_payload("APPROVE"), make_supervisor_headers("sup-2")
        )
    )
    assert_fields(
        decided,
        refund_status="APPROVED",
        refund_decided_by_user_id="sup-2",
        status="IN_PROGRESS",
    )
    assert_cents(decided["refund_approved_cents"], 2000, "refund_approved_cents")
    ledger = read_event(client, event["id"])
    assert_cents(ledger["refund_approved_total_cents"], 2000, "refund_approved_total_cents")
    assert_cents(ledger["refund_budget_remaining_cents"], 98000, "refund_budget_remaining_cents")


def test_the_same_bad_body_answers_three_different_errors(client):
    """Who you are is settled before what you sent, so authorisation never leaks.

    "A rejected request returns exactly one `error_id`: the one belonging to the lowest-numbered
    rule in the following ladder whose condition holds."

    "Request schema — required fields present, JSON types correct, enum values recognized,
    integers inside their declared ranges (a forecast attendance of at least 0, a requested unit
    count of at least 1, a satisfaction score from 1 through 5, a headcount override either absent
    or at least 1), and pagination inside its declared range (`ERR_VALIDATION_FAILED`)."

    Design: Corner/validations/role_denial_precedes_validation_failure
    """
    set_clock(client, "2026-09-01T09:00:00Z")
    malformed = event_payload(
        name="Bad Body",
        event_date="2026-09-20T00:00:00Z",
        doors_open_at="2026-09-20T13:00:00Z",
        doors_close_at="2026-09-20T21:00:00Z",
        expected_attendance=-5,
    )

    err(client.create_event(malformed, headers_missing_role()), ERR_UNAUTHENTICATED)
    err(client.create_event(malformed, COORDINATOR_HEADERS), ERR_ROLE_NOT_PERMITTED)
    err(client.create_event(malformed, DIRECTOR_HEADERS), ERR_VALIDATION_FAILED)

    err(
        client.list_events(DIRECTOR_HEADERS, {"limit": 200, "offset": 0}), ERR_VALIDATION_FAILED
    )
    err(client.list_events(DIRECTOR_HEADERS, {"limit": 10, "offset": -1}), ERR_VALIDATION_FAILED)

    _events, meta = page(client.list_events(DIRECTOR_HEADERS, {"limit": 10, "offset": 0}))
    assert meta["total_count"] == 0, "no event survived any of the three refusals"


def test_a_guest_is_only_moved_into_a_zone_the_event_actually_staffs(client):
    """Category mismatch, then unstaffed zone, then refund sub-state, then the one that works.

    "The chosen resolution must be permitted for the issue's `category`, and the permitted sets
    are fixed."

    "A `SEAT_RELOCATION` resolution requires a `relocation_zone_code`, and that zone must match
    the `zone_code` of at least one shift block that is not `CLOSED` on the event's `ACTIVE` or
    `LOCKED` plan — a guest may only be moved into a zone the event actually staffs — failing
    which the request is refused with `ERR_RELOCATION_ZONE_UNSTAFFED`."

    "A `REFUND` resolution requires the issue's `refund_status` to already stand at `APPROVED` or
    `PARTIALLY_APPROVED`, failing which it is refused with `ERR_REFUND_STATE_INVALID`."

    Design: Corner/validations/relocation_zone_not_staffed_rejects_the_resolution
    """
    set_clock(client, "2026-09-12T19:00:00Z")
    event = _match_day_event(client, "Relocation Zone Fixture")
    family = create_ticket_taker(client, **TICKET_TAKER)
    plan = create_plan(client, event["id"], plan_variant="FORECAST_BASED")
    slot = create_slot(
        client,
        plan["id"],
        family["id"],
        zone_code="Z100",
        shift_start="2026-09-12T18:00:00Z",
        shift_end="2026-09-12T22:05:00Z",
        required_headcount_override=1,
    )
    activate_plan(client, plan["id"], event["id"], 1)
    advance_event(client, event["id"], "IN_PROGRESS")
    responder = _responder(client)
    issue = _issue_in_progress(
        client,
        event["id"],
        responder["id"],
        reporter="sup-1",
        channel="IN_PERSON",
        category="SEAT_RELOCATION",
        severity="MEDIUM",
        description="Obstructed view in 114",
        seat_reference="114-R-8",
    )

    err(
        client.resolve_guest_issue(
            issue["id"],
            issue_resolve_payload("EJECTION", relocation_zone_code="Z999"),
            SUPERVISOR_HEADERS,
        ),
        ERR_RESOLUTION_TYPE_MISMATCH,
    )
    err(
        client.resolve_guest_issue(
            issue["id"],
            issue_resolve_payload("SEAT_RELOCATION", relocation_zone_code="Z999"),
            SUPERVISOR_HEADERS,
        ),
        ERR_RELOCATION_ZONE_UNSTAFFED,
    )
    err(
        client.resolve_guest_issue(
            issue["id"], issue_resolve_payload("REFUND"), SUPERVISOR_HEADERS
        ),
        ERR_REFUND_STATE_INVALID,
    )

    still_open = read_issue(client, issue["id"])
    assert_fields(still_open, status="IN_PROGRESS")
    _unset(still_open, "resolution_type", "relocation_zone_code", "resolved_at")

    resolved = resolve_issue(
        client, issue["id"], "SEAT_RELOCATION", relocation_zone_code="Z100"
    )
    assert_fields(
        resolved,
        status="RESOLVED",
        resolution_type="SEAT_RELOCATION",
        relocation_zone_code="Z100",
    )
    assert_instant(resolved["resolved_at"], "2026-09-12T19:00:00.000Z", "resolved_at")
    assert_fields(read_slot(client, slot["id"]), zone_code="Z100", status="OPEN")


def test_an_empty_recovery_pot_refuses_the_next_approval_outright(client):
    """The pot is checked before the amount, so the second ask is refused, not trimmed to zero.

    "Before an approval is attempted at all, the event must still have room: the event's
    `refund_budget_remaining_cents` plus this issue's already-recorded `refund_approved_cents` must
    be greater than zero, or the approval is refused with `ERR_REFUND_BUDGET_EXHAUSTED`."

    "The amount authorized is then the smallest of three figures: the `refund_requested_cents`
    asked for, the effective cap, and that available budget."

    Design: Corner/validations/refund_budget_exhausted_rejects_the_next_approval
    """
    set_clock(client, "2026-09-12T19:00:00Z")
    event = _match_day_event(client, "Budget Exhaustion Fixture", refund_budget_total_cents=3000)
    assert_cents(event["refund_budget_remaining_cents"], 3000, "remaining at creation")
    plan = create_plan(client, event["id"], plan_variant="FORECAST_BASED")
    activate_plan(client, plan["id"], event["id"], 1)
    advance_event(client, event["id"], "IN_PROGRESS")
    responder = _responder(client)

    first = _issue_in_progress(
        client, event["id"], responder["id"], reporter="sup-9",
        channel="TEXT_LINE", category="OTHER", severity="MEDIUM", description="Issue A",
    )
    second = _issue_in_progress(
        client, event["id"], responder["id"], reporter="sup-9",
        channel="TEXT_LINE", category="OTHER", severity="MEDIUM", description="Issue B",
    )
    ok(
        client.file_refund_request(
            first["id"], refund_request_payload(3000), make_supervisor_headers("sup-1")
        )
    )
    asked_second = ok(
        client.file_refund_request(
            second["id"], refund_request_payload(1000), make_supervisor_headers("sup-1")
        )
    )
    assert_fields(asked_second, refund_status="PENDING")

    director = make_director_headers("dir-1")
    approved = ok(
        client.file_refund_decision(first["id"], refund_decision_payload("APPROVE"), director)
    )
    assert_fields(approved, refund_status="APPROVED")
    assert_cents(approved["refund_approved_cents"], 3000, "the full 3000-cent ask")
    drained = read_event(client, event["id"])
    assert_cents(drained["refund_approved_total_cents"], 3000, "refund_approved_total_cents")
    assert_cents(drained["refund_budget_remaining_cents"], 0, "refund_budget_remaining_cents")

    err(
        client.file_refund_decision(second["id"], refund_decision_payload("APPROVE"), director),
        ERR_REFUND_BUDGET_EXHAUSTED,
    )
    refused = read_issue(client, second["id"])
    assert_fields(refused, refund_status="PENDING")
    assert_cents(refused["refund_approved_cents"], 0, "nothing authorized on the second issue")
    _unset(refused, "refund_decided_by_user_id")

    ledger = read_event(client, event["id"])
    assert (
        ledger["refund_budget_remaining_cents"] + ledger["refund_approved_total_cents"]
        == ledger["refund_budget_total_cents"]
    ), "remaining plus approved must still reconcile to the declared total"


def test_a_placement_that_clears_every_gate_answers_created(client):
    """The complement of the refusals: an eligible worker lands and the block turns half-filled.

    "The resulting assignment carries `source` `MANUAL` with `shift_bid_id` absent, opens in
    `SCHEDULED` and `PENDING`, and increments the block's `filled_headcount` by 1."

    "A first award on a block whose `required_headcount` is greater than 1 takes it `OPEN →
    PARTIALLY_FILLED`; a first award on a block that needs exactly one head takes it `OPEN →
    FILLED` immediately; a later award that reaches or passes the requirement takes it
    `PARTIALLY_FILLED → FILLED`, after which further awards are refused with
    `ERR_SLOT_CAPACITY_FULL`."

    Design: Corner/validations/all_gates_satisfied_assignment_creation_succeeds
    """
    set_clock(client, "2026-09-12T10:00:00Z")
    event = _match_day_event(client, "Happy Path Fixture")
    family = create_elevator_operator(
        client,
        base_hourly_rate_cents=2400,
        attendance_ratio_per_1000=0.2,
        min_headcount=1,
        required_certifications=["ELEVATOR_OPERATION"],
        is_tip_eligible=True,
        is_contracted_position=True,
    )
    plan = create_plan(client, event["id"], plan_variant="FORECAST_BASED")
    slot = create_slot(
        client,
        plan["id"],
        family["id"],
        zone_code="Z100",
        shift_start="2026-09-12T18:00:00Z",
        shift_end="2026-09-12T22:05:00Z",
        required_headcount_override=2,
    )
    assert_fields(slot, status="OPEN", required_headcount=2, shift_minutes=245)
    assert_cents(slot["slot_labor_cost_cents"], 19600, "slot_labor_cost_cents")
    worker = create_member(
        client,
        full_name="Ada Certified",
        employment_type="CONTRACTED",
        seniority_date="2020-01-01T00:00:00Z",
        hourly_rate_cents=2400,
    )
    credential = create_certification(
        client,
        worker["id"],
        "ELEVATOR_OPERATION",
        issued_on="2026-01-01T00:00:00Z",
        expires_on="2027-01-01T00:00:00Z",
    )
    assert_fields(credential, status="VALID")
    activated = activate_plan(client, plan["id"], event["id"], 1)
    assert_cents(activated["base_labor_cost_cents"], 19600, "plan base_labor_cost_cents")

    assignment = create_assignment(client, slot["id"], worker["id"])
    assert_fields(
        assignment, attendance_status="SCHEDULED", payout_status="PENDING", source="MANUAL"
    )
    _unset(assignment, "shift_bid_id")

    assert_slot_fill(read_slot(client, slot["id"]), filled=1, required=2, status="PARTIALLY_FILLED")
    frozen = read_plan(client, plan["id"])
    assert_fields(frozen, total_required_headcount=2)
    assert_cents(frozen["base_labor_cost_cents"], 19600, "filling a head does not reprice the plan")
    assert_fields(
        read_member(client, worker["id"]),
        status="ACTIVE",
        reliability_score=100,
        season_reliability_score=100,
        completed_assignment_count=0,
    )
    _requests, meta = page(
        client.list_backfill_requests(COORDINATOR_HEADERS, {"position_slot_id": slot["id"]})
    )
    assert meta["total_count"] == 0, "a clean placement opens no backfill request"


def test_a_second_live_bid_is_refused_but_a_withdrawn_one_frees_the_slot_again(client):
    """Uniqueness counts only the live bids, so a terminal bid does not block a re-bid.

    "If the same worker already holds a bid on the same block whose `status` is `SUBMITTED` or
    `WAITLISTED`, the filing is refused with `ERR_DUPLICATE_BID`; terminal bids are invisible to
    that check."

    "Because the duplicate-bid check considers only non-terminal bids, the same worker may file a
    fresh bid on the same block afterwards; and because a withdrawn bid is terminal, every later
    batch pass skips it."

    Design: Corner/validations/duplicate_bid_on_the_same_slot_rejected
    """
    set_clock(client, "2026-09-12T10:00:00Z")
    event = _match_day_event(client, "Duplicate Bid Fixture")
    family = create_ticket_taker(client, **TICKET_TAKER)
    plan = create_plan(client, event["id"], plan_variant="FORECAST_BASED")
    slot = create_slot(
        client,
        plan["id"],
        family["id"],
        zone_code="Z100",
        shift_start="2026-09-12T18:00:00Z",
        shift_end="2026-09-12T22:05:00Z",
        required_headcount_override=2,
    )
    bidder = create_member(
        client,
        full_name="Ada Bidder",
        employment_type="PART_TIME_EMPLOYEE",
        seniority_date="2020-01-01T00:00:00Z",
        hourly_rate_cents=2000,
    )
    activate_plan(client, plan["id"], event["id"], 1)
    bidder_headers = make_staff_member_headers(bidder["id"])
    first = create_bid(client, bidder["id"], slot["id"])

    err(
        client.create_shift_bid(shift_bid_payload(bidder["id"], slot["id"]), bidder_headers),
        ERR_DUPLICATE_BID,
    )
    _bids, after_refusal = page(
        client.list_shift_bids(COORDINATOR_HEADERS, {"position_slot_id": slot["id"]})
    )
    assert after_refusal["total_count"] == 1, "the refused filing added no bid"

    withdrawn = ok(client.withdraw_shift_bid(first["id"], bidder_headers))
    assert_fields(withdrawn, status="WITHDRAWN")

    second = create_bid(client, bidder["id"], slot["id"])
    assert_fields(second, status="SUBMITTED")

    _all_bids, both = page(
        client.list_shift_bids(COORDINATOR_HEADERS, {"position_slot_id": slot["id"]})
    )
    assert both["total_count"] == 2, "the terminal bid and the fresh bid both persist"
    _live, live_meta = page(
        client.list_shift_bids(
            COORDINATOR_HEADERS, {"position_slot_id": slot["id"], "status": "SUBMITTED"}
        )
    )
    assert live_meta["total_count"] == 1, "only one bid is live"
    assert_slot_fill(read_slot(client, slot["id"]), filled=0, required=2, status="OPEN")


def test_the_reopen_window_outranks_the_reopen_ceiling(client):
    """Two reopens spent: inside the window it is the ceiling, past it the window, then frozen.

    "Within a window of 1440 minutes measured from `resolved_at` — where exactly 1440 minutes is
    still inside the window — a supervisor may reopen it, moving it `RESOLVED → REOPENED`; past
    that boundary the reopen is refused with `ERR_REOPEN_WINDOW_CLOSED`."

    "An issue may be reopened at most twice: once `reopen_count` has reached 2, a further attempt
    is refused with `ERR_REOPEN_LIMIT_REACHED`, and because the window rule is evaluated first, an
    issue that is both past its window and at its ceiling reports `ERR_REOPEN_WINDOW_CLOSED`."

    "A supervisor may close a `RESOLVED` issue only once strictly more than 1440 minutes have
    elapsed since `resolved_at`; at or inside that boundary the close is refused with
    `ERR_REOPEN_WINDOW_CLOSED`."

    "A closed issue is frozen: reopening it, resolving it again and deciding a refund on it all
    return `ERR_ISSUE_STATE_INVALID` from then on."

    Design: Corner/validations/reopen_limit_reached_after_two_reopens_rejected
    """
    set_clock(client, "2026-09-12T19:00:00Z")
    event = _match_day_event(client, "Reopen Ceiling Fixture")
    plan = create_plan(client, event["id"], plan_variant="FORECAST_BASED")
    activate_plan(client, plan["id"], event["id"], 1)
    advance_event(client, event["id"], "IN_PROGRESS")
    responder = _responder(client)
    issue = _issue_in_progress(
        client, event["id"], responder["id"], reporter="sup-1",
        channel="TEXT_LINE", category="OTHER", severity="MEDIUM", description="Repeat complaint",
    )
    resolve_issue(client, issue["id"], "NO_ACTION")

    set_clock(client, "2026-09-12T19:10:00Z")
    first_reopen = ok(client.reopen_guest_issue(issue["id"], SUPERVISOR_HEADERS))
    assert_fields(first_reopen, status="REOPENED", reopen_count=1)
    _unset(first_reopen, "resolved_at", "resolution_type", "resolved_by_user_id")
    assign_issue(client, issue["id"], responder["id"])
    resolve_issue(client, issue["id"], "NO_ACTION")

    set_clock(client, "2026-09-12T19:20:00Z")
    second_reopen = ok(client.reopen_guest_issue(issue["id"], SUPERVISOR_HEADERS))
    assert_fields(second_reopen, status="REOPENED", reopen_count=2)
    _unset(second_reopen, "resolved_at", "resolution_type", "resolved_by_user_id")
    assign_issue(client, issue["id"], responder["id"])
    final = resolve_issue(client, issue["id"], "NO_ACTION")
    assert_instant(final["resolved_at"], "2026-09-12T19:20:00.000Z", "final resolved_at")

    err(client.reopen_guest_issue(issue["id"], SUPERVISOR_HEADERS), ERR_REOPEN_LIMIT_REACHED)

    set_clock(client, "2026-09-13T19:21:00Z")
    err(client.reopen_guest_issue(issue["id"], SUPERVISOR_HEADERS), ERR_REOPEN_WINDOW_CLOSED)

    closed = ok(client.close_guest_issue(issue["id"], SUPERVISOR_HEADERS))
    assert_fields(closed, status="CLOSED", reopen_count=2)

    err(client.reopen_guest_issue(issue["id"], SUPERVISOR_HEADERS), ERR_ISSUE_STATE_INVALID)
    assert_fields(read_issue(client, issue["id"]), status="CLOSED", reopen_count=2)
