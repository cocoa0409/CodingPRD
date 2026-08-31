"""Remembrance events, family invitations, the RSVP window and event settlement."""

import pytest

from test_helpers import (
    IC,
    PD,
    ApiErrorId,
    UNUSED_UUIDS,
    api_client,
    assert_grant_money_pool,
    assert_invitation,
    confirm_remembrance_event,
    create_funding_allocation,
    create_grant_award,
    create_invitation,
    create_meeting_space,
    create_participant,
    create_remembrance_event,
    create_remembrance_event_payload,
    make_participant_headers,
    read_funding_allocation,
    read_grant_award,
    read_invitation,
    read_remembrance_event,
    respond_invitation,
    send_invitation,
    setup_confirmed_event,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_planning_an_event_before_the_logical_clock_date_is_refused():
    """PRD 3.7: "An event may not be scheduled into the past: if `event_date` is
    earlier than the logical clock date, the request is refused with
    `ERR_EVENT_DATE_IN_PAST`."

    Design: Corner/validations/remembrance_event_dated_before_the_clock_returns_event_date_in_past
    """
    set_clock()
    space = create_meeting_space(name="Hall A", capacity=60,
                                 turnover_buffer_minutes=30)
    validate_error(
        api_client.create_remembrance_event(
            create_remembrance_event_payload(
                space["id"], title="Yesterday Vigil", event_date="2026-08-31"), PD),
        ApiErrorId.ERR_EVENT_DATE_IN_PAST.value, 422)

    rows, meta = validate_paginated(
        api_client.list_remembrance_events(PD, params={"meeting_space_id": space["id"]}))
    assert meta["total_count"] == 0


def test_cancelling_an_event_voids_only_the_invitations_still_in_flight():
    """PRD 3.7: "Cancelling is available from `PLANNED` or `CONFIRMED` and moves
    the event to `CANCELLED`, voiding every invitation still in `DRAFT` or `SENT`
    and releasing every funding allocation on the event still in `COMMITTED`."
    PRD 3.7: "Voiding, by contrast, happens only through event cancellation, and
    likewise changes no headcount."

    Design: Corner/state_machines/event_cancel_voids_draft_and_sent_invitations
    """
    set_clock()
    space, event = setup_confirmed_event(title="Autumn Remembrance",
                                         event_date="2026-10-05",
                                         expected_attendance=30,
                                         direct_cost_cents=10_220)
    first = create_participant(loss_type="SUDDEN_DEATH", contact_name="Inv One")
    second = create_participant(loss_type="SUDDEN_DEATH", contact_name="Inv Two")
    third = create_participant(loss_type="SUDDEN_DEATH", contact_name="Inv Three")

    draft = create_invitation(event["id"], first["id"], guest_count=0)
    sent = create_invitation(event["id"], second["id"], guest_count=1)
    send_invitation(sent["id"])
    accepted = create_invitation(event["id"], third["id"], guest_count=2)
    send_invitation(accepted["id"])
    respond_invitation(accepted["id"], third["id"], "ACCEPT")

    validate_success(api_client.cancel_remembrance_event(event["id"], PD))

    refreshed_event = read_remembrance_event(event["id"])
    assert refreshed_event["status"] == "CANCELLED"
    assert read_invitation(draft["id"])["status"] == "VOID"
    assert read_invitation(sent["id"])["status"] == "VOID"
    assert read_invitation(accepted["id"])["status"] == "ACCEPTED", (
        "an invitation already ACCEPTED keeps its terminal status")
    assert refreshed_event["invitations_accepted"] == 1
    assert refreshed_event["confirmed_headcount"] == 3


def test_an_rsvp_after_the_deadline_is_refused():
    """PRD 3.7: "An invitation is drafted by an `IntakeCoordinator` naming the
    `event_id` and the `participant_id`, plus an optional `guest_count` of
    additional family members accompanying the participant, which defaults to 0 and
    may not be negative. The invitation is created in `DRAFT` with HTTP 201,
    `sent_at` and `responded_at` null, and its `rsvp_deadline` computed as the
    event's `event_date` less three days."
    PRD 3.7: "Responding is the invited `Participant`'s own act, though an
    `IntakeCoordinator` may record it on their behalf; the request carries a
    `response` of either `ACCEPT` or `DECLINE`, and it too requires the logical
    clock date to be on or before `rsvp_deadline` — a late RSVP is refused with
    `ERR_RSVP_WINDOW_CLOSED`."

    Design: Corner/validations/invitation_respond_after_the_rsvp_deadline_returns_rsvp_window_closed
    """
    set_clock()
    space, event = setup_confirmed_event(title="Autumn Remembrance",
                                         event_date="2026-10-05",
                                         direct_cost_cents=10_220)
    participant = create_participant(loss_type="SUDDEN_DEATH",
                                     contact_name="Inv One")
    invitation = create_invitation(event["id"], participant["id"], guest_count=2)
    assert invitation["rsvp_deadline"] == "2026-10-02", (
        f"Expected the event date less three days, got {invitation['rsvp_deadline']}")
    send_invitation(invitation["id"])

    set_clock("2026-10-03T09:00:00Z")
    validate_error(
        api_client.respond_invitation(
            invitation["id"], "ACCEPT", make_participant_headers(participant["id"])),
        ApiErrorId.ERR_RSVP_WINDOW_CLOSED.value, 409)

    refreshed_invitation = read_invitation(invitation["id"])
    assert refreshed_invitation["status"] == "SENT"
    assert refreshed_invitation["responded_at"] is None
    refreshed_event = read_remembrance_event(event["id"])
    assert refreshed_event["confirmed_headcount"] == 0
    assert refreshed_event["invitations_accepted"] == 0


def test_marking_an_event_held_settles_its_money_on_confirmed_headcount():
    """PRD 3.7: "Marking an event as held is available only from `CONFIRMED` and
    only once the logical clock date has reached or passed `event_date`; it moves
    the event to `HELD`, expires every invitation still in `DRAFT` or `SENT`, and
    settles every `COMMITTED` funding allocation on the event against confirmed
    headcount as described in §3.9."
    PRD 3.9: "For a `REMEMBRANCE_EVENT` allocation, take the ratio of the event's
    `confirmed_headcount` to its `expected_attendance`, cap that ratio at 1 so an
    over-subscribed event never settles above plan, multiply the event's
    `program_cost_total_cents` by the capped ratio, and round half up to a whole
    cent; `basis` becomes `CONFIRMED_HEADCOUNT`."

    Design: Corner/calculations/event_settlement_uses_confirmed_headcount_not_expected_attendance
    """
    set_clock()
    space = create_meeting_space(name="Hall A", capacity=60,
                                 turnover_buffer_minutes=30)
    award = create_grant_award(awarded_cents=500_000,
                               allowed_categories=["REMEMBRANCE_EVENT"])
    event = create_remembrance_event(space["id"], title="Autumn Remembrance",
                                     event_date="2026-10-05",
                                     expected_attendance=20,
                                     direct_cost_cents=10_220)
    confirm_remembrance_event(event["id"])
    allocation = create_funding_allocation(
        award["id"], "REMEMBRANCE_EVENT", event_id=event["id"],
        expected_grant_award_version=award["version"])

    for guest_count, name in ((2, "Inv One"), (1, "Inv Two")):
        participant = create_participant(loss_type="SUDDEN_DEATH", contact_name=name)
        invitation = create_invitation(event["id"], participant["id"], guest_count)
        send_invitation(invitation["id"])
        respond_invitation(invitation["id"], participant["id"], "ACCEPT")

    set_clock("2026-10-05T18:00:00Z")
    held = validate_success(api_client.mark_remembrance_event_held(event["id"], PD))
    assert held["status"] == "HELD"
    assert held["confirmed_headcount"] == 5

    settled = read_funding_allocation(allocation["id"])
    assert settled["provisional_cents"] == 11_446
    assert settled["settled_cents"] == 2_862, (
        f"Expected round_half_up(11446 * 5 / 20) = 2862, got {settled['settled_cents']}")
    assert settled["basis"] == "CONFIRMED_HEADCOUNT"
    assert settled["status"] == "SETTLED"

    refreshed_award = read_grant_award(award["id"])
    assert refreshed_award["committed_cents"] == 0
    assert refreshed_award["spent_cents"] == 2_862
    assert refreshed_award["available_cents"] == 497_138
    assert_grant_money_pool(refreshed_award)


def test_confirming_an_unknown_event_is_not_found():
    """PRD 2.8: "Each entity has its own dedicated code — `ERR_REFERRAL_NOT_FOUND`,
    `ERR_PARTICIPANT_NOT_FOUND`, `ERR_SPACE_NOT_FOUND`, `ERR_COHORT_NOT_FOUND`,
    `ERR_ENROLLMENT_NOT_FOUND`, `ERR_COUNSELOR_NOT_FOUND`,
    `ERR_COUNSELING_REFERRAL_NOT_FOUND`, `ERR_COMPANION_NOT_FOUND`,
    `ERR_MATCH_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`"

    Design: Corner/errors/remembrance_event_confirm_with_unknown_id_returns_event_not_found
    """
    set_clock()
    validate_error(
        api_client.confirm_remembrance_event(UNUSED_UUIDS["event"], PD),
        ApiErrorId.ERR_EVENT_NOT_FOUND.value, 404)


def test_sending_an_unknown_invitation_is_not_found():
    """PRD 2.5: "Every resource named by a path segment exists, validated from left
    to right, so the leftmost missing segment determines the reported error —
    otherwise the corresponding not-found error (404)."

    Design: Corner/errors/invitation_send_with_unknown_id_returns_invitation_not_found
    """
    set_clock()
    validate_error(api_client.send_invitation(UNUSED_UUIDS["invitation"], IC),
                   ApiErrorId.ERR_INVITATION_NOT_FOUND.value, 404)


def _setup_planned_event_with_draft_invitation():
    """A PLANNED event in a 60-seat hall plus one DRAFT invitation."""
    set_clock()
    space = create_meeting_space(name="Hall A", capacity=60,
                                 turnover_buffer_minutes=30)
    event = create_remembrance_event(space["id"], title="Autumn Remembrance",
                                     event_date="2026-10-05",
                                     expected_attendance=20,
                                     direct_cost_cents=10_220)
    participant = create_participant(loss_type="ANTICIPATED_ILLNESS",
                                     contact_name="Dana Otis")
    invitation = create_invitation(event["id"], participant["id"], guest_count=2)
    return event, participant, invitation


def test_an_invitation_cannot_be_sent_while_its_event_is_only_planned():
    """PRD 3.7: "Sending moves an invitation `DRAFT → SENT`. It requires the parent
    event to be in `CONFIRMED` — against an event in any other status the send is
    refused with `ERR_EVENT_NOT_CONFIRMED` — and it requires the logical clock date
    to be on or before `rsvp_deadline`, otherwise `ERR_RSVP_WINDOW_CLOSED`. A
    successful send stamps `sent_at` from the logical clock and increases the
    event's `invitations_sent` by one."

    Design: Difficulty/cross_entity_state_dependency/invitation_send_depends_on_remembrance_event_confirmed_state
    """
    event, participant, invitation = _setup_planned_event_with_draft_invitation()
    assert_invitation(invitation)
    assert invitation["rsvp_deadline"] == "2026-10-02"
    assert read_remembrance_event(event["id"])["status"] == "PLANNED"

    validate_error(api_client.send_invitation(invitation["id"], IC),
                   ApiErrorId.ERR_EVENT_NOT_CONFIRMED.value, 409)

    assert read_invitation(invitation["id"])["status"] == "DRAFT"
    assert read_remembrance_event(event["id"])["invitations_sent"] == 0


def test_the_same_send_succeeds_once_the_event_is_confirmed():
    """PRD 3.7: "Confirming moves the event `PLANNED → CONFIRMED` and requires the
    room to be `AVAILABLE`; the event's `version` increments by one. Confirmation
    matters because invitations cannot go out before it."
    PRD 3.7: "A successful send stamps `sent_at` from the logical clock and
    increases the event's `invitations_sent` by one."

    Design: Difficulty/cross_entity_state_dependency/invitation_send_depends_on_remembrance_event_confirmed_state
    """
    event, participant, invitation = _setup_planned_event_with_draft_invitation()
    validate_error(api_client.send_invitation(invitation["id"], IC),
                   ApiErrorId.ERR_EVENT_NOT_CONFIRMED.value, 409)

    confirm_remembrance_event(event["id"])
    sent = validate_success(api_client.send_invitation(invitation["id"], IC))
    assert sent["status"] == "SENT"

    assert read_invitation(invitation["id"])["status"] == "SENT"
    refreshed_event = read_remembrance_event(event["id"])
    assert refreshed_event["invitations_sent"] == 1
    assert refreshed_event["invitations_accepted"] == 0
    assert refreshed_event["confirmed_headcount"] == 0
