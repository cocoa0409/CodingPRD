"""The headcount identity across a no-show, an auto-fill and a release."""

from test_helpers import (
    COORDINATOR_HEADERS,
    assert_fields,
    assert_slot_fill,
    attendance,
    backfill_requests_for_assignment,
    backfill_requests_for_slot,
    auto_fill,
    create_assignment,
    create_member,
    event_in_progress_with_slot,
    ok,
    page,
    read_assignment,
    read_member,
    read_slot,
    set_clock,
)
from test_helpers.factories import ticket_taker_payload

COUNTABLE = ("SCHEDULED", "CHECKED_IN", "COMPLETED")


def _countable_heads(client, slot_id):
    """The count the block's filled_headcount is defined to equal."""
    rows, _meta = page(
        client.list_staff_assignments(COORDINATOR_HEADERS, {"position_slot_id": slot_id})
    )
    return len([row for row in rows if row["attendance_status"] in COUNTABLE])


def _assert_identity(client, slot_id, *, filled, status):
    slot = read_slot(client, slot_id)
    assert_slot_fill(slot, filled=filled, required=2, status=status)
    assert slot["filled_headcount"] == _countable_heads(client, slot_id), (
        "filled_headcount must equal the number of assignments on the block "
        "standing in SCHEDULED, CHECKED_IN or COMPLETED"
    )


def _pool_of_three(client):
    """A two-head block holding two of three pooled workers."""
    set_clock(client, "2026-09-12T17:00:00Z")
    context = event_in_progress_with_slot(
        client,
        position_type_payload=ticket_taker_payload(required_certifications=[]),
        slot_overrides={
            "zone_code": "B100",
            "shift_start": "2026-09-12T18:00:00Z",
            "shift_end": "2026-09-12T22:00:00Z",
            "required_headcount_override": 2,
        },
        name="Headcount Invariant Fixture",
        doors_open_at="2026-09-12T17:00:00Z",
        doors_close_at="2026-09-12T23:00:00Z",
        expected_attendance=20000,
    )
    members = []
    for name, seniority in (
        ("Fay Osei", "2024-01-01T00:00:00Z"),
        ("Gil Prado", "2024-02-01T00:00:00Z"),
        ("Hana Ruiz", "2024-03-01T00:00:00Z"),
    ):
        members.append(
            create_member(
                client,
                full_name=name,
                employment_type="PART_TIME_EMPLOYEE",
                seniority_date=seniority,
                hourly_rate_cents=2000,
                in_backfill_pool=True,
            )
        )
    slot_id = context["slot"]["id"]
    context["members"] = members
    context["first"] = create_assignment(client, slot_id, members[0]["id"])
    context["second"] = create_assignment(client, slot_id, members[1]["id"])
    return context


def test_headcount_identity_holds_at_every_point_of_the_backfill_round_trip(client):
    """Four observation points, one identity: filled heads equal countable assignments.

    "The two advance on their own triggers, and the block-level counter
    `filled_headcount` reads only the attendance dimension: it is the number of
    assignments on the block whose `attendance_status` is `SCHEDULED`,
    `CHECKED_IN` or `COMPLETED`."

    Design: Difficulty/compensating_invariant/backfill_release_restores_filled_headcount_identity
    """
    context = _pool_of_three(client)
    slot_id = context["slot"]["id"]

    _assert_identity(client, slot_id, filled=2, status="FILLED")

    attendance(client, context["first"]["id"], "NO_SHOW")
    _assert_identity(client, slot_id, filled=1, status="PARTIALLY_FILLED")

    request = backfill_requests_for_assignment(client, context["first"]["id"])[0]
    filled_request = auto_fill(client, request["id"])
    _assert_identity(client, slot_id, filled=2, status="FILLED")

    attendance(client, filled_request["filled_assignment_id"], "RELEASE")
    _assert_identity(client, slot_id, filled=1, status="PARTIALLY_FILLED")


def test_releasing_a_backfill_assignment_reopens_the_request_that_created_it(client):
    """The release walks both sides of the compensation, not just the block.

    "One compensation does fire — when the released assignment's `source` is
    `BACKFILL`, the backfill request that created it reverts `FILLED → OPEN` with
    `selected_staff_member_id` and `filled_assignment_id` cleared, while its
    `attempt_count` is deliberately *not* decremented."

    Design: Difficulty/compensating_invariant/backfill_release_restores_filled_headcount_identity
    """
    context = _pool_of_three(client)
    winner = context["members"][2]

    attendance(client, context["first"]["id"], "NO_SHOW")
    request = backfill_requests_for_assignment(client, context["first"]["id"])[0]
    assert_fields(request, status="OPEN", attempt_count=0)

    filled_request = auto_fill(client, request["id"])
    assert_fields(
        filled_request,
        status="FILLED",
        selected_staff_member_id=winner["id"],
        attempt_count=1,
    )
    backfill_assignment = read_assignment(client, filled_request["filled_assignment_id"])
    assert_fields(
        backfill_assignment,
        source="BACKFILL",
        attendance_status="SCHEDULED",
        staff_member_id=winner["id"],
    )

    released = attendance(client, backfill_assignment["id"], "RELEASE")
    assert_fields(
        released, attendance_status="RELEASED", payout_status="VOIDED", total_payout_cents=0
    )

    reopened = ok(client.get_backfill_request(request["id"], COORDINATOR_HEADERS))
    assert_fields(
        reopened,
        status="OPEN",
        selected_staff_member_id=None,
        filled_assignment_id=None,
    )


def test_the_attempt_counter_and_the_reliability_figures_survive_the_compensation(client):
    """Attempts are a monotone audit counter, and a release never touches reliability.

    "Critically, `no_show_strikes`, `reliability_score` and
    `season_reliability_score` are all left alone: released rows are outside the
    reliability input set entirely, which is what makes releasing a worker
    materially different from writing them off as a no-show."

    Design: Difficulty/compensating_invariant/backfill_release_restores_filled_headcount_identity
    """
    context = _pool_of_three(client)
    no_show_member, _held, winner = context["members"]
    slot_id = context["slot"]["id"]

    attendance(client, context["first"]["id"], "NO_SHOW")
    request = backfill_requests_for_assignment(client, context["first"]["id"])[0]
    filled_request = auto_fill(client, request["id"])
    assert_fields(filled_request, attempt_count=1)

    attendance(client, filled_request["filled_assignment_id"], "RELEASE")

    reopened = ok(client.get_backfill_request(request["id"], COORDINATOR_HEADERS))
    assert_fields(reopened, status="OPEN", attempt_count=1)

    assert_fields(
        read_member(client, winner["id"]),
        no_show_strikes=0,
        reliability_score=100,
        season_reliability_score=100,
    )
    assert_fields(
        read_member(client, no_show_member["id"]),
        status="ACTIVE",
        no_show_strikes=1,
        reliability_score=75,
    )

    assert len(backfill_requests_for_slot(client, slot_id)) == 1, (
        "the release must reopen the original request, never open a second one"
    )
