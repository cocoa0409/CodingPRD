"""Hearings: the continue/reschedule cycle, agenda capacity, the fifteen-day
notice window, the comment period, and layered validation ordering
(PRD §2.8, §3.4)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_public_comment,
    continue_hearing,
    create_meeting,
    decide_by_commissioner,
    get_application,
    get_meeting,
    schedule_hearing,
    setup_commission_track_accepted,
    setup_hearing_open,
    setup_hearing_scheduled,
    setup_staff_track_accepted,
    validate_error,
    validate_paginated,
    validate_success,
)

STAFF = TEST_USERS["staff_headers"]
COMMISSIONER = TEST_USERS["commissioner_headers"]


class TestHearingContinueRescheduleCycle:
    def test_hearing_continue_then_reschedule_cycle(self, api):
        """PRD §3.4: "At the meeting, a `Commissioner` opens the hearing —
        permitted only while its application is `HEARING_SCHEDULED`, otherwise
        `ERR_INVALID_STATE` — which moves the hearing from `SCHEDULED` to
        `OPENED`, advances the application from `HEARING_SCHEDULED` to
        `HEARING_OPEN`, and closes the comment period."
        PRD §3.4: "When testimony cannot conclude, the commissioner continues
        the hearing: from `SCHEDULED` or `OPENED` the hearing moves to
        `CONTINUED`, the application falls back to `HEARING_DEFERRED`, and the
        meeting's `scheduled_hearing_count` drops by one, freeing the agenda
        slot."
        PRD §3.4: "A successful reschedule replaces the hearing's `meeting_id`
        and `notice_posted_at`, raises the new meeting's count by one, and
        returns the application from `HEARING_DEFERRED` to `HEARING_SCHEDULED`."

        Design: Difficulty/non_linear_state_machine/hearing_continue_reschedule_cycle
        """
        ctx = setup_hearing_scheduled(verified_cost_cents=1250000)
        hearing = ctx["hearing"]
        assert hearing["status"] == "SCHEDULED"

        opened = validate_success(api.open_hearing(hearing["id"], COMMISSIONER))
        assert opened["status"] == "OPENED"

        continued = validate_success(api.continue_hearing(hearing["id"], COMMISSIONER))
        assert continued["status"] == "CONTINUED"
        assert get_application(ctx["application"]["id"])["status"] == "HEARING_DEFERRED"

        meeting2 = create_meeting(meeting_date="2026-10-01T00:00:00Z", agenda_capacity=1)
        rescheduled = validate_success(
            api.reschedule_hearing(
                hearing["id"],
                {"meeting_id": meeting2["id"], "notice_posted_at": "2026-09-01T00:00:00Z"},
                STAFF,
            )
        )
        assert rescheduled["status"] == "SCHEDULED"
        assert rescheduled["meeting_id"] == meeting2["id"]
        assert get_application(ctx["application"]["id"])["status"] == "HEARING_SCHEDULED"

    def test_continue_frees_slot_and_reschedule_occupies_new_meeting(self, api):
        """PRD §3.4: "When testimony cannot conclude, the commissioner
        continues the hearing: from `SCHEDULED` or `OPENED` the hearing moves
        to `CONTINUED`, the application falls back to `HEARING_DEFERRED`, and
        the meeting's `scheduled_hearing_count` drops by one, freeing the
        agenda slot."
        PRD §3.4: "A successful reschedule replaces the hearing's `meeting_id`
        and `notice_posted_at`, raises the new meeting's count by one, and
        returns the application from `HEARING_DEFERRED` to `HEARING_SCHEDULED`."

        Design: Difficulty/non_linear_state_machine/hearing_continue_reschedule_cycle
        """
        ctx = setup_hearing_scheduled(verified_cost_cents=1250000)
        meeting1 = ctx["meeting"]
        hearing = ctx["hearing"]
        assert get_meeting(meeting1["id"])["scheduled_hearing_count"] == 1

        opened = validate_success(api.open_hearing(hearing["id"], COMMISSIONER))
        assert opened["status"] == "OPENED"
        continue_hearing(hearing["id"])
        assert get_meeting(meeting1["id"])["scheduled_hearing_count"] == 0, (
            "continuing frees the agenda slot"
        )

        meeting2 = create_meeting(meeting_date="2026-10-01T00:00:00Z", agenda_capacity=1)
        validate_success(
            api.reschedule_hearing(
                hearing["id"],
                {"meeting_id": meeting2["id"], "notice_posted_at": "2026-09-01T00:00:00Z"},
                STAFF,
            )
        )
        assert get_meeting(meeting2["id"])["scheduled_hearing_count"] == 1


class TestMeetingAgendaCapacity:
    def test_meeting_agenda_full_rejects_second_hearing(self, api):
        """PRD §3.4: "The meeting must also have a free agenda slot; when its
        `scheduled_hearing_count` already equals `agenda_capacity`, the
        scheduling is rejected with `ERR_MEETING_AGENDA_FULL`."

        Design: Difficulty/resource_temporal_overlap/meeting_agenda_capacity_count
        """
        first = setup_commission_track_accepted(verified_cost_cents=1100000)
        second = setup_commission_track_accepted(verified_cost_cents=1200000)
        meeting = create_meeting(agenda_capacity=1)
        schedule_hearing(first["application"]["id"], meeting["id"])

        response = api.create_hearing(
            {
                "application_id": second["application"]["id"],
                "meeting_id": meeting["id"],
                "notice_posted_at": "2026-08-10T00:00:00Z",
            },
            STAFF,
        )
        validate_error(response, ApiErrorId.ERR_MEETING_AGENDA_FULL)

    def test_agenda_full_leaves_application_and_meeting_untouched(self, api):
        """PRD §3.4: "The meeting must also have a free agenda slot; when its
        `scheduled_hearing_count` already equals `agenda_capacity`, the
        scheduling is rejected with `ERR_MEETING_AGENDA_FULL`."
        PRD §2.10: "every such cascade commits atomically within the triggering request: there is no eventual-consistency window in which a client could observe a decision without its hearing mirror, a demolition approval without its delay window, or a violation resolution without its property counter adjustment."

        Design: Difficulty/resource_temporal_overlap/meeting_agenda_capacity_count
        """
        first = setup_commission_track_accepted(verified_cost_cents=1100000)
        second = setup_commission_track_accepted(verified_cost_cents=1200000)
        meeting = create_meeting(agenda_capacity=1)
        schedule_hearing(first["application"]["id"], meeting["id"])

        validate_error(
            api.create_hearing(
                {
                    "application_id": second["application"]["id"],
                    "meeting_id": meeting["id"],
                    "notice_posted_at": "2026-08-10T00:00:00Z",
                },
                STAFF,
            ),
            ApiErrorId.ERR_MEETING_AGENDA_FULL,
        )
        assert get_application(second["application"]["id"])["status"] == "ACCEPTED"
        assert get_meeting(meeting["id"])["scheduled_hearing_count"] == 1


class TestScheduleContinueConservesAgenda:
    def test_schedule_then_continue_conserves_agenda_count(self, api):
        """PRD §3.4: "A successful scheduling creates the hearing in
        `SCHEDULED`, moves the application from `ACCEPTED` to
        `HEARING_SCHEDULED` (incrementing the application's `version`), and
        raises the meeting's `scheduled_hearing_count` by one."
        PRD §3.4: "When testimony cannot conclude, the commissioner continues
        the hearing: from `SCHEDULED` or `OPENED` the hearing moves to
        `CONTINUED`, the application falls back to `HEARING_DEFERRED`, and the
        meeting's `scheduled_hearing_count` drops by one, freeing the agenda
        slot."

        Design: Difficulty/compensating_invariant/schedule_continue_pair_conserves_agenda
        """
        ctx = setup_commission_track_accepted(verified_cost_cents=1300000)
        meeting = create_meeting(agenda_capacity=2)
        hearing = schedule_hearing(ctx["application"]["id"], meeting["id"])
        assert get_meeting(meeting["id"])["scheduled_hearing_count"] == 1

        continue_hearing(hearing["id"])
        assert get_meeting(meeting["id"])["scheduled_hearing_count"] == 0

    def test_continue_moves_application_to_hearing_deferred(self, api):
        """PRD §3.4: "When testimony cannot conclude, the commissioner
        continues the hearing: from `SCHEDULED` or `OPENED` the hearing moves
        to `CONTINUED`, the application falls back to `HEARING_DEFERRED`, and
        the meeting's `scheduled_hearing_count` drops by one, freeing the
        agenda slot."

        Design: Difficulty/compensating_invariant/schedule_continue_pair_conserves_agenda
        """
        ctx = setup_hearing_scheduled(verified_cost_cents=1300000)
        continued = validate_success(api.continue_hearing(ctx["hearing"]["id"], COMMISSIONER))
        assert continued["status"] == "CONTINUED"
        assert get_application(ctx["application"]["id"])["status"] == "HEARING_DEFERRED"


def test_notice_exactly_fifteen_days_allowed(api):
    """PRD §3.4: "Public notice law requires fifteen clear days:
    `notice_posted_at` must be no later than the meeting's `meeting_date` minus
    fifteen days, the boundary is inclusive — a notice posted exactly fifteen
    days before the meeting instant passes, and one second later fails with
    `ERR_NOTICE_WINDOW_TOO_SHORT`."

    Design: Corner/calculations/notice_window_exact_15_days_allowed
    """
    ctx = setup_commission_track_accepted(verified_cost_cents=1100000)
    meeting = create_meeting(meeting_date="2026-09-01T00:00:00Z", agenda_capacity=2)
    hearing = validate_success(
        api.create_hearing(
            {
                "application_id": ctx["application"]["id"],
                "meeting_id": meeting["id"],
                "notice_posted_at": "2026-08-17T00:00:00Z",
            },
            STAFF,
        ),
        201,
    )
    assert hearing["status"] == "SCHEDULED"
    assert get_application(ctx["application"]["id"])["status"] == "HEARING_SCHEDULED"


def test_notice_window_too_short_rejected(api):
    """PRD §3.4: "Public notice law requires fifteen clear days:
    `notice_posted_at` must be no later than the meeting's `meeting_date` minus
    fifteen days, the boundary is inclusive — a notice posted exactly fifteen
    days before the meeting instant passes, and one second later fails with
    `ERR_NOTICE_WINDOW_TOO_SHORT`."

    Design: Corner/endpoints/hearing_notice_too_short_rejected
    """
    ctx = setup_commission_track_accepted(verified_cost_cents=1100000)
    meeting = create_meeting(meeting_date="2026-09-01T00:00:00Z", agenda_capacity=2)
    # 2026-08-20 is after the 2026-08-17 cutoff.
    response = api.create_hearing(
        {
            "application_id": ctx["application"]["id"],
            "meeting_id": meeting["id"],
            "notice_posted_at": "2026-08-20T00:00:00Z",
        },
        STAFF,
    )
    validate_error(response, ApiErrorId.ERR_NOTICE_WINDOW_TOO_SHORT)


def test_hearing_create_on_staff_track_rejected(api):
    """PRD §3.4: "Scheduling a hearing for an application in any other
    situation — including a `STAFF`-track `ACCEPTED` application — is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/endpoints/hearing_create_on_staff_track_rejected
    """
    ctx = setup_staff_track_accepted()
    meeting = create_meeting()
    response = api.create_hearing(
        {
            "application_id": ctx["application"]["id"],
            "meeting_id": meeting["id"],
            "notice_posted_at": "2026-08-10T00:00:00Z",
        },
        STAFF,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)

    hearings, meta = validate_paginated(api.list_hearings(STAFF))
    assert meta["total_count"] == 0, "no hearing may be persisted"


class TestRescheduleDecidedHearing:
    def test_state_check_masks_notice_window_violation(self, api):
        """PRD §2.8: "The layers are evaluated in the order below, and a
        failure at an earlier layer masks every later layer: the response
        carries the first failing layer's error, and no later layer is
        evaluated."
        PRD §2.8: "The target resource must be in a state from which the
        requested transition is declared in §3; otherwise the request is
        rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_decided_hearing
        """
        ctx = setup_hearing_open(verified_cost_cents=1100000)
        hearing = ctx["hearing"]
        decide_by_commissioner(ctx["application"]["id"], {"outcome": "APPROVE"})

        meeting2 = create_meeting(meeting_date="2026-08-05T00:00:00Z", agenda_capacity=2)
        # The notice instant violates the fifteen-day window for the new
        # meeting, but the hearing is DECIDED: the state layer fires first.
        response = api.reschedule_hearing(
            hearing["id"],
            {"meeting_id": meeting2["id"], "notice_posted_at": "2026-08-01T00:00:00Z"},
            STAFF,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)

    def test_rejected_reschedule_leaves_no_partial_mutation(self, api):
        """PRD §2.10: "every such cascade commits atomically within the
        triggering request: there is no eventual-consistency window in which a
        client could observe a decision without its hearing mirror, a
        demolition approval without its delay window, or a violation
        resolution without its property counter adjustment."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_decided_hearing
        """
        ctx = setup_hearing_open(verified_cost_cents=1100000)
        hearing = ctx["hearing"]
        decide_by_commissioner(ctx["application"]["id"], {"outcome": "APPROVE"})

        meeting2 = create_meeting(meeting_date="2026-08-05T00:00:00Z", agenda_capacity=2)
        validate_error(
            api.reschedule_hearing(
                hearing["id"],
                {"meeting_id": meeting2["id"], "notice_posted_at": "2026-08-01T00:00:00Z"},
                STAFF,
            ),
            ApiErrorId.ERR_INVALID_STATE,
        )
        after = validate_success(api.get_hearing(hearing["id"], STAFF))
        assert after["status"] == "DECIDED"
        assert after["meeting_id"] == ctx["meeting"]["id"]
        assert get_meeting(meeting2["id"])["scheduled_hearing_count"] == 0


def test_comment_rejected_after_hearing_open(api):
    """PRD §3.4: "While a hearing is `SCHEDULED` (or later `CONTINUED`), the
    public comment period is open: any authenticated participant may submit a
    comment to the hearing it addresses — the comment records that hearing's
    identifier as its `hearing_id` — with a `commenter_name`, a `stance` of
    `SUPPORT`, `OPPOSE`, or `NEUTRAL`, and the `comment_text` body, and the
    system stamps `submitted_at` with the logical clock."
    PRD §3.4: "A comment submitted when the hearing is in any other status is
    rejected with `ERR_COMMENT_PERIOD_CLOSED`."

    Design: Corner/validations/comment_rejected_after_hearing_open
    """
    ctx = setup_hearing_scheduled(verified_cost_cents=1100000)
    hearing = ctx["hearing"]

    first = validate_success(
        api.create_comment(
            hearing["id"],
            {"commenter_name": "Neighborhood Assoc", "stance": "SUPPORT",
             "comment_text": "Good infill"},
            STAFF,
        ),
        201,
    )
    assert_public_comment(first)

    validate_success(api.open_hearing(hearing["id"], COMMISSIONER))
    response = api.create_comment(
        hearing["id"],
        {"commenter_name": "Late Larry", "stance": "OPPOSE", "comment_text": "Too late"},
        STAFF,
    )
    validate_error(response, ApiErrorId.ERR_COMMENT_PERIOD_CLOSED)


def test_public_comment_carries_no_version_fields(api):
    """PRD §2.4: "A public comment is the single exception: it is an immutable
    record of testimony and carries only `id` and `created_at`. Both
    `updated_at` and `version` are absent from a comment, since a comment is
    never modified after submission."
    PRD §3.4: "any authenticated participant may submit a comment to the
    hearing it addresses — the comment records that hearing's identifier as its
    `hearing_id` — with a `commenter_name`, a `stance` of `SUPPORT`, `OPPOSE`,
    or `NEUTRAL`, and the `comment_text` body, and the system stamps
    `submitted_at` with the logical clock."

    Design: Corner/entities/public_comment_has_no_version_field
    """
    ctx = setup_hearing_scheduled(verified_cost_cents=1100000)
    hearing = ctx["hearing"]
    comment = validate_success(
        api.create_comment(
            hearing["id"],
            {"commenter_name": "Neighbor Ned", "stance": "OPPOSE", "comment_text": "Too tall"},
            STAFF,
        ),
        201,
    )
    assert_public_comment(comment)
    assert comment["hearing_id"] == hearing["id"]
    assert comment["stance"] == "OPPOSE"
    assert "submitted_at" in comment
