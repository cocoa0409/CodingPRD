"""Board meetings: quorum and IIC segregation at scheduling, the room
turnaround buffer, in-session voting semantics (upsert, retract, OCC), and
lazy session opening (PRD §3.8, §2.7, §2.4).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_meeting_tallies,
    cast_vote,
    create_board_meeting_payload,
    get_meeting,
    make_board_member_headers,
    schedule_board_meeting,
    set_clock,
    setup_analysis,
    setup_board_review,
    setup_meeting_in_session,
    validate_error,
    validate_paginated,
    validate_success,
    vote_payload,
)

DUTY_OFFICER = TEST_USERS["duty_officer_headers"]
BOARD_ADMIN = TEST_USERS["board_admin_headers"]


class TestMeetingScheduling:
    def test_quorum_boundary_three_sits_two_fails(self, api):
        """PRD §3.8: "the roster must contain at least three distinct members
        (`ERR_QUORUM_NOT_MET`)".

        Design: Corner/validations/quorum_boundary_three_sits_two_fails
        """
        ctx = setup_analysis()
        inv_id = ctx["investigation"]["id"]

        resp = api.create_board_meeting(
            create_board_meeting_payload(
                inv_id,
                room_id="room-4",
                window_start_utc="2026-09-22T09:00:00Z",
                window_end_utc="2026-09-22T10:00:00Z",
                sitting_member_ids=["bm-1", "bm-2"],
            ),
            BOARD_ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_QUORUM_NOT_MET)

        # Exactly three satisfies the gate: the quorum constant is inclusive.
        meeting = schedule_board_meeting(
            inv_id,
            room_id="room-4",
            window_start_utc="2026-09-22T09:00:00Z",
            window_end_utc="2026-09-22T10:00:00Z",
            sitting_member_ids=["bm-1", "bm-2", "bm-3"],
        )
        assert meeting["status"] == "SCHEDULED"
        assert meeting["member_votes"] == []
        assert meeting["outcome"] is None

        rows, _ = validate_paginated(
            api.list_board_meetings(DUTY_OFFICER, params={"investigation_id": inv_id})
        )
        assert len(rows) == 1

    def test_iic_cannot_sit_on_board_for_own_investigation(self, api):
        """PRD §3.8: "it must not contain the investigation's own
        `iic_user_id` — the investigator-in-charge may not sit in judgment of
        their own investigation (`ERR_SOD_IIC_ON_BOARD`)."

        Design: Corner/validations/iic_cannot_sit_on_board_for_own_investigation
        """
        ctx = setup_analysis()
        inv_id = ctx["investigation"]["id"]

        resp = api.create_board_meeting(
            create_board_meeting_payload(
                inv_id,
                room_id="room-9",
                window_start_utc="2026-09-20T09:00:00Z",
                window_end_utc="2026-09-20T10:00:00Z",
                sitting_member_ids=[ctx["iic_user_id"], "bm-1", "bm-2"],
            ),
            BOARD_ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_SOD_IIC_ON_BOARD)

        rows, _ = validate_paginated(
            api.list_board_meetings(DUTY_OFFICER, params={"investigation_id": inv_id})
        )
        assert rows == []

    def test_room_bookings_enforce_sixty_minute_turnaround_buffer(self, api):
        """PRD §3.8: "Room bookings must not overlap any other `SCHEDULED` or
        `IN_SESSION` meeting on the same `room_id` once each existing meeting's
        window is extended by a sixty-minute post-meeting turnaround buffer
        (`ERR_ROOM_WINDOW_CONFLICT`)."

        Design: Difficulty/resource_temporal_overlap/resource_temporal_overlap_room_turnaround_buffer
        """
        ctx = setup_analysis()
        inv_id = ctx["investigation"]["id"]

        meeting_a = schedule_board_meeting(
            inv_id,
            room_id="room-1",
            window_start_utc="2026-09-20T09:00:00Z",
            window_end_utc="2026-09-20T10:00:00Z",
        )
        assert meeting_a["status"] == "SCHEDULED"

        # 10:30 lies inside the buffer: meeting A occupies [09:00, 11:00).
        resp = api.create_board_meeting(
            create_board_meeting_payload(
                inv_id,
                room_id="room-1",
                window_start_utc="2026-09-20T10:30:00Z",
                window_end_utc="2026-09-20T11:00:00Z",
            ),
            BOARD_ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_ROOM_WINDOW_CONFLICT)

        # The buffer expires exactly at 11:00 — 11:00 < 11:00 is false.
        meeting_c = schedule_board_meeting(
            inv_id,
            room_id="room-1",
            window_start_utc="2026-09-20T11:00:00Z",
            window_end_utc="2026-09-20T12:00:00Z",
        )
        assert meeting_c["status"] == "SCHEDULED"

        rows, _ = validate_paginated(
            api.list_board_meetings(DUTY_OFFICER, params={"investigation_id": inv_id})
        )
        assert len(rows) == 2

    def test_room_buffer_is_per_room_and_extends_only_forward(self, api):
        """PRD §3.8: "must not overlap any other `SCHEDULED` or `IN_SESSION`
        meeting on the same `room_id` once each existing meeting's window is
        extended by a sixty-minute post-meeting turnaround buffer" — the
        resource is the room, and the buffer extends the existing meeting's
        end, so a slot ending before the existing meeting's start is free.

        Design: Difficulty/resource_temporal_overlap/resource_temporal_overlap_room_turnaround_buffer
        """
        ctx = setup_analysis()
        inv_id = ctx["investigation"]["id"]

        schedule_board_meeting(
            inv_id,
            room_id="room-1",
            window_start_utc="2026-09-20T09:00:00Z",
            window_end_utc="2026-09-20T10:00:00Z",
        )
        # The same clock slot on a different room is not a conflict.
        other_room = schedule_board_meeting(
            inv_id,
            room_id="room-2",
            window_start_utc="2026-09-20T09:30:00Z",
            window_end_utc="2026-09-20T10:00:00Z",
        )
        assert other_room["status"] == "SCHEDULED"
        # Ending at 08:00, before the existing meeting starts at 09:00: the
        # buffer extends the existing window forward, not backward.
        early = schedule_board_meeting(
            inv_id,
            room_id="room-1",
            window_start_utc="2026-09-20T07:30:00Z",
            window_end_utc="2026-09-20T08:00:00Z",
        )
        assert early["status"] == "SCHEDULED"

        rows, _ = validate_paginated(
            api.list_board_meetings(DUTY_OFFICER, params={"investigation_id": inv_id})
        )
        assert len(rows) == 3


class TestVoting:
    def test_vote_change_upserts_single_member_position(self, api):
        """PRD §3.8: "A member holds at most one entry in `member_votes`:
        re-voting upserts the caller's existing entry — keyed by
        `member_user_id` — with the new position and a fresh `cast_at`".

        Design: Corner/endpoints/vote_change_upserts_single_member_position
        """
        ctx = setup_meeting_in_session()
        meeting = ctx["meeting"]

        meeting = cast_vote(meeting, "bm-1", "REJECT", dissent_text="Initial reservations.")
        assert meeting["reject_count"] == 1

        meeting = cast_vote(meeting, "bm-1", "ADOPT")
        votes = [v for v in meeting["member_votes"] if v["member_user_id"] == "bm-1"]
        assert len(votes) == 1, "no duplicate ballot may remain"
        assert votes[0]["position"] == "ADOPT"
        assert meeting["adopt_count"] == 1
        assert meeting["reject_count"] == 0
        assert meeting["abstain_count"] == 0
        # The changed vote withdraws the dissent.
        assert meeting["dissenting_member_ids"] == []
        assert_meeting_tallies(meeting)

    def test_retract_without_existing_vote_returns_state_error(self, api):
        """PRD §3.8: "`RETRACT` removes the caller's entry entirely, and
        retracting with no vote on record is rejected with
        `ERR_NO_VOTE_TO_RETRACT`."

        Design: Corner/endpoints/retract_without_existing_vote_returns_state_error
        """
        ctx = setup_meeting_in_session()
        meeting = ctx["meeting"]

        resp = api.cast_vote(
            meeting["id"],
            vote_payload("RETRACT", meeting["version"]),
            make_board_member_headers("bm-2"),
        )
        validate_error(resp, ApiErrorId.ERR_NO_VOTE_TO_RETRACT)

        reread = get_meeting(meeting["id"])
        assert reread["member_votes"] == []
        assert reread["version"] == meeting["version"]

    def test_occ_stale_meeting_version_rejected_on_second_vote(self, api):
        """PRD §2.7: "A vote cast on a board meeting (`POST
        /board-meetings/{id}/votes`) must include `expected_meeting_version`,
        carrying the meeting's `version` as the caller last observed it. Vote
        changes are legitimately permitted while a meeting is in session, so a
        member acting on a stale tally view must refresh before voting; a value
        that does not match the meeting's current `version` is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_meeting_version_rejected_on_second_vote
        """
        ctx = setup_meeting_in_session()
        meeting = ctx["meeting"]
        stale_version = meeting["version"]

        meeting = cast_vote(meeting, "bm-1", "ADOPT")
        assert meeting["version"] == stale_version + 1

        resp = api.cast_vote(
            meeting["id"],
            vote_payload("ADOPT", stale_version),
            make_board_member_headers("bm-2"),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        reread = get_meeting(meeting["id"])
        assert reread["adopt_count"] == 1
        assert len(reread["member_votes"]) == 1

    def test_vote_before_window_start_rejected_until_clock_reaches_it(self, api):
        """PRD §3.8: "While the meeting is effectively in session — the logical
        clock has reached `window_start_utc` and the meeting is not yet
        `COMPLETED`, else `ERR_MEETING_NOT_IN_SESSION`". PRD §2.4: "A board
        meeting becomes `IN_SESSION` once the logical clock reaches its
        `window_start_utc`."

        Design: Corner/cross_cutting_complexity_layers/vote_before_window_start_rejected_until_clock_reaches_it
        """
        ctx = setup_board_review()
        meeting = ctx["meeting"]
        # The chain leaves the clock at 2026-09-01T00:00:00Z; the meeting
        # window opens 2026-09-02T09:00:00Z, so it is still effectively
        # SCHEDULED.
        resp = api.cast_vote(
            meeting["id"],
            vote_payload("ADOPT", meeting["version"]),
            make_board_member_headers("bm-1"),
        )
        validate_error(resp, ApiErrorId.ERR_MEETING_NOT_IN_SESSION)

        set_clock(meeting["window_start_utc"])
        resp = api.cast_vote(
            meeting["id"],
            vote_payload("ADOPT", meeting["version"]),
            make_board_member_headers("bm-1"),
        )
        updated = validate_success(resp, expected_status=200)
        assert updated["adopt_count"] == 1

    def test_vote_cast_then_retract_conserves_tallies(self, api):
        """PRD §3.8: "while `RETRACT` removes the caller's entry entirely".
        PRD §3.8: "Every accepted vote recomputes `adopt_count`,
        `reject_count`, and `abstain_count` and increments the meeting's
        `version`."

        Design: Difficulty/compensating_invariant/compensating_invariant_vote_cast_then_retract_conserves_tallies
        """
        ctx = setup_meeting_in_session()
        meeting = ctx["meeting"]
        base_version = meeting["version"]

        meeting = cast_vote(meeting, "bm-1", "ADOPT")
        assert meeting["adopt_count"] == 1

        meeting = cast_vote(meeting, "bm-1", "RETRACT")
        # Tally conservation: every count returns to zero and no ballot
        # remains; only the OCC version advanced (both mutations counted).
        assert meeting["adopt_count"] == 0
        assert meeting["reject_count"] == 0
        assert meeting["abstain_count"] == 0
        assert meeting["member_votes"] == []
        assert meeting["outcome"] is None
        assert meeting["version"] == base_version + 2
        assert_meeting_tallies(meeting)

    def test_second_retract_after_conservation_returns_no_vote_to_retract(self, api):
        """PRD §3.8: "retracting with no vote on record is rejected with
        `ERR_NO_VOTE_TO_RETRACT`." PRD §2.5: "`version` (integer): a
        system-managed integer that increments by one on every mutation of the
        resource" — a rejected request mutates nothing.

        Design: Difficulty/compensating_invariant/compensating_invariant_vote_cast_then_retract_conserves_tallies
        """
        ctx = setup_meeting_in_session()
        meeting = ctx["meeting"]
        meeting = cast_vote(meeting, "bm-1", "ADOPT")
        meeting = cast_vote(meeting, "bm-1", "RETRACT")
        conserved_version = meeting["version"]

        resp = api.cast_vote(
            meeting["id"],
            vote_payload("RETRACT", conserved_version),
            make_board_member_headers("bm-1"),
        )
        validate_error(resp, ApiErrorId.ERR_NO_VOTE_TO_RETRACT)

        reread = get_meeting(meeting["id"])
        assert reread["member_votes"] == []
        assert reread["adopt_count"] == 0
        assert reread["reject_count"] == 0
        assert reread["abstain_count"] == 0
        assert reread["version"] == conserved_version
