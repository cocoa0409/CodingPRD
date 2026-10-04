"""Board-meeting close: the adoption outcome computation, the terminal
ADOPTED cascade across investigation/groups/case, the NOT_ADOPTED revert, and
post-close vote lockout (PRD §3.8, §2.10).
"""
from test_helpers import (
    ApiErrorId,
    advance_phase_payload,
    assert_meeting_tallies,
    cast_votes,
    close_meeting,
    get_case,
    get_group,
    get_investigation,
    get_meeting,
    make_board_member_headers,
    make_iic_headers,
    setup_adopted_case,
    setup_meeting_in_session,
    validate_error,
    vote_payload,
)


class TestAdoptionCascade:
    def test_board_adoption_closes_investigation_groups_and_case(self, api):
        """PRD §3.8: "Closing computes the outcome and materializes
        `dissenting_member_ids`, listing the members whose current position is
        `REJECT`, ordered by `cast_at` ascending with ties broken by the order
        in which their vote entries were appended. The probable cause is
        `ADOPTED` only when `adopt_count` strictly exceeds `reject_count`".
        PRD §3.8: "Adoption cascades outward. The investigation moves from
        `BOARD_REVIEW` to `ADOPTED`, its terminal phase; an `OPEN` docket
        becomes `FINAL`; every group still `ACTIVE` or `COMPLETE` is
        `DISBANDED`; and the originating accident case moves from `LAUNCHED` to
        `CLOSED_ADOPTED`, its own terminal state."

        Design: Difficulty/transitive_cascade/transitive_cascade_board_adoption_closes_case
        """
        ctx = setup_meeting_in_session()
        meeting = cast_votes(
            ctx["meeting"],
            [
                ("bm-1", "ADOPT"),
                ("bm-2", "ADOPT"),
                ("bm-3", "REJECT", "The probable cause underweights maintenance culture."),
            ],
        )
        meeting = close_meeting(meeting["id"])

        # Link 1: the meeting itself.
        assert meeting["status"] == "COMPLETED"
        assert meeting["outcome"] == "ADOPTED", "2 > 1 adopts"
        assert meeting["adopt_count"] == 2
        assert meeting["reject_count"] == 1
        assert meeting["abstain_count"] == 0
        assert meeting["dissenting_member_ids"] == ["bm-3"]
        assert_meeting_tallies(meeting)

        # Link 2: the investigation and its groups.
        investigation = get_investigation(ctx["investigation"]["id"])
        assert investigation["phase"] == "ADOPTED"
        assert investigation["docket_status"] == "FINAL"
        assert get_group(ctx["group"]["id"])["status"] == "DISBANDED"

        # Link 3: the originating accident case.
        assert get_case(ctx["case"]["id"])["status"] == "CLOSED_ADOPTED"

    def test_adopted_investigation_is_terminal(self, api):
        """PRD §3.8: "The investigation moves from `BOARD_REVIEW` to
        `ADOPTED`, its terminal phase". PRD §3.5: "any hop outside the declared
        order is rejected with `ERR_INVESTIGATION_PHASE_INVALID`."

        Design: Difficulty/transitive_cascade/transitive_cascade_board_adoption_closes_case
        """
        ctx = setup_adopted_case()
        investigation = ctx["investigation"]
        assert investigation["phase"] == "ADOPTED"

        resp = api.advance_phase(
            investigation["id"],
            advance_phase_payload("ANALYSIS"),
            make_iic_headers(ctx["iic_user_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVESTIGATION_PHASE_INVALID)

        reread = get_investigation(investigation["id"])
        assert reread["phase"] == "ADOPTED"
        assert reread["docket_status"] == "FINAL"
        assert get_case(ctx["case"]["id"])["status"] == "CLOSED_ADOPTED"


class TestNotAdoptedOutcome:
    def test_adoption_tie_votes_resolve_not_adopted_and_revert_to_analysis(self, api):
        """PRD §3.8: "The probable cause is `ADOPTED` only when `adopt_count`
        strictly exceeds `reject_count`; abstentions count toward neither side,
        and a tie — or a meeting closed with no votes at all — resolves to
        `NOT_ADOPTED`." PRD §3.8: "A `NOT_ADOPTED` close instead returns the
        investigation from `BOARD_REVIEW` to `ANALYSIS` for further work."

        Design: Corner/state_machines/adoption_tie_votes_resolve_not_adopted_and_revert_to_analysis
        """
        ctx = setup_meeting_in_session(
            meeting_overrides={
                "room_id": "room-3",
                "window_start_utc": "2026-09-21T13:00:00Z",
                "window_end_utc": "2026-09-21T14:00:00Z",
                "sitting_member_ids": ["bm-1", "bm-2", "bm-3", "bm-4", "bm-5"],
            }
        )
        meeting = cast_votes(
            ctx["meeting"],
            [
                ("bm-1", "ADOPT"),
                ("bm-2", "ADOPT"),
                ("bm-3", "REJECT"),
                ("bm-4", "REJECT"),
                ("bm-5", "ABSTAIN"),
            ],
        )
        meeting = close_meeting(meeting["id"])

        # 2 > 2 is false; the ABSTAIN ballot counts for neither side.
        assert meeting["outcome"] == "NOT_ADOPTED"
        assert meeting["adopt_count"] == 2
        assert meeting["reject_count"] == 2
        assert meeting["abstain_count"] == 1
        assert meeting["status"] == "COMPLETED"
        assert_meeting_tallies(meeting)

        investigation = get_investigation(ctx["investigation"]["id"])
        assert investigation["phase"] == "ANALYSIS", "reverted for further work"
        assert investigation["docket_status"] == "OPEN"
        # The case stays LAUNCHED: no adoption cascade fired.
        assert get_case(ctx["case"]["id"])["status"] == "LAUNCHED"

    def test_vote_after_close_returns_meeting_not_in_session(self, api):
        """PRD §3.8: "While the meeting is effectively in session — the logical
        clock has reached `window_start_utc` and the meeting is not yet
        `COMPLETED`, else `ERR_MEETING_NOT_IN_SESSION`".

        Design: Corner/state_machines/vote_after_close_returns_meeting_not_in_session
        """
        ctx = setup_adopted_case()
        meeting = ctx["meeting"]
        assert meeting["status"] == "COMPLETED"
        assert meeting["outcome"] == "ADOPTED"

        # Terminal state beats OCC freshness: the caller carries the meeting's
        # final version and is still rejected.
        resp = api.cast_vote(
            meeting["id"],
            vote_payload("ABSTAIN", meeting["version"]),
            make_board_member_headers("bm-1"),
        )
        validate_error(resp, ApiErrorId.ERR_MEETING_NOT_IN_SESSION)

        reread = get_meeting(meeting["id"])
        assert reread["outcome"] == "ADOPTED"
        assert reread["adopt_count"] == 2
        assert reread["reject_count"] == 1
        assert reread["abstain_count"] == 0
