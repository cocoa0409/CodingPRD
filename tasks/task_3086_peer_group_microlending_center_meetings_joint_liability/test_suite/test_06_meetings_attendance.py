"""Meeting lifecycle, attendance streaks, and close-out cascades.

Covers difficulty instances under non_linear_state_machine (parallel
dimensions), transitive_cascade (strike cascade), boundary_precision_check
(absence streak), and meeting corner instances.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    close_meeting,
    draft_application,
    get_success_data,
    make_center_manager_headers,
    make_member_headers,
    mark_attendance,
    open_meeting,
    post_collection,
    schedule_meeting,
    setup_active_group,
    setup_open_meeting_with_loan,
    setup_org,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)

PA = TEST_USERS["program_admin_headers"]
BM = TEST_USERS["branch_manager_headers"]
BM_B = TEST_USERS["branch_manager_b_headers"]


class TestMeetingLifecycleCorners:
    def test_meeting_initial_state_and_parallel_dimensions(self, api):
        """PRD §3.5: "a meeting carries two independent state dimensions at once
        — a `status` dimension (`SCHEDULED → OPEN → CLOSED`, or `CANCELLED`) and
        a `settlement_status` dimension (`PENDING → POSTED → RECONCILED`, with
        `DISPUTED` as a retryable branch) that only advances after close."

        Design: Corner/state_machines/meeting_initial_state_and_parallel_dimensions
        """
        branch, manager, center = setup_org()
        meeting = schedule_meeting(center["id"], manager)
        assert meeting["status"] == "SCHEDULED"
        assert meeting["settlement_status"] == "PENDING"
        assert meeting["declared_cash_cents"] is None
        assert meeting["closer_user_id"] is None

    def test_cancel_open_meeting_returns_not_scheduled(self, api):
        """PRD §3.5: "A scheduled meeting may be cancelled while `SCHEDULED`
        (`ERR_MEETING_NOT_SCHEDULED`), moving it to `CANCELLED`".

        Design: Corner/state_machines/cancel_open_meeting_returns_not_scheduled
        """
        branch, manager, center = setup_org()
        meeting = schedule_meeting(center["id"], manager)
        open_meeting(meeting["id"], manager)
        response = api.cancel_meeting(
            meeting["id"], make_center_manager_headers(manager["id"])
        )
        validate_error(response, ApiErrorId.ERR_MEETING_NOT_SCHEDULED, expected_status=409)
        current = get_success_data(api.get_center_meeting(meeting["id"], PA))
        assert current["status"] == "OPEN"

    def test_meeting_close_twice_returns_meeting_not_open(self, api):
        """PRD §3.7: "Closing a meeting is the trigger for the attendance
        cascade, and it belongs to the center's own manager — a meeting must be
        `OPEN` (`ERR_MEETING_NOT_OPEN`) and the caller must manage its center
        (`ERR_NOT_CENTER_MANAGER`)."

        Design: Corner/state_machines/meeting_close_twice_returns_meeting_not_open
        """
        ctx = setup_active_group(prefix="close-twice")
        meeting = schedule_meeting(ctx["center"]["id"], ctx["manager"])
        open_meeting(meeting["id"], ctx["manager"])
        mark_attendance(
            meeting["id"],
            ctx["manager"],
            [ctx["applicant"]["id"]] + [p["id"] for p in ctx["peers"]],
        )
        close_meeting(meeting["id"], ctx["manager"])
        response = api.close_meeting(
            meeting["id"], make_center_manager_headers(ctx["manager"]["id"])
        )
        validate_error(response, ApiErrorId.ERR_MEETING_NOT_OPEN, expected_status=409)
        member_now = get_success_data(api.get_member(ctx["applicant"]["id"], PA))
        assert member_now["consecutive_absence_streak"] == 0, (
            "auto-marking must not run twice"
        )


class TestParallelDimensionsEvolve:
    def test_center_meeting_parallel_dimensions_evolve_independently(self, api):
        """PRD §3.7: "The close stamps `closer_user_id` with the caller's
        `X-User-ID` — the value the segregation-of-duties rule will check at
        reconciliation — and flips `settlement_status` from `PENDING` to
        `POSTED`."
        PRD §3.7: "A match moves `settlement_status` to `RECONCILED` and records
        the `declared_cash_cents`."

        Design: Difficulty/non_linear_state_machine/center_meeting_parallel_dimensions_evolve_independently
        """
        ctx = setup_open_meeting_with_loan(prefix="parallel")
        post_collection(
            ctx["meeting"]["id"], ctx["manager"],
            ctx["applicant"]["id"], ctx["loan"]["id"], 4_801,
        )
        close_meeting(ctx["meeting"]["id"], ctx["manager"])

        after_close = get_success_data(api.get_center_meeting(ctx["meeting"]["id"], PA))
        assert after_close["status"] == "CLOSED"
        assert after_close["settlement_status"] == "POSTED"

        reconciled = get_success_data(
            api.reconcile_meeting(
                ctx["meeting"]["id"], {"declared_cash_cents": 4_801}, BM
            )
        )
        assert reconciled["status"] == "CLOSED", (
            "reconciliation moves only the settlement dimension"
        )
        assert reconciled["settlement_status"] == "RECONCILED"

    def test_center_meeting_parallel_dimensions_evolve_independently_from_pending(self, api):
        """PRD §3.5: "a meeting carries two independent state dimensions at once
        — a `status` dimension (`SCHEDULED → OPEN → CLOSED`, or `CANCELLED`) and
        a `settlement_status` dimension (`PENDING → POSTED → RECONCILED`, with
        `DISPUTED` as a retryable branch) that only advances after close."

        Design: Difficulty/non_linear_state_machine/center_meeting_parallel_dimensions_evolve_independently
        """
        ctx = setup_open_meeting_with_loan(prefix="parallel-open")
        mid_open = get_success_data(api.get_center_meeting(ctx["meeting"]["id"], PA))
        assert mid_open["status"] == "OPEN"
        assert mid_open["settlement_status"] == "PENDING", (
            "opening advances the lifecycle dimension only"
        )
        closed = get_success_data(
            api.close_meeting(
                ctx["meeting"]["id"],
                make_center_manager_headers(ctx["manager"]["id"]),
            )
        )
        assert closed["status"] == "CLOSED"
        assert closed["settlement_status"] == "POSTED"


class TestAttendanceStrikeCascade:
    def test_meeting_close_absence_strike_cascade_rejects_voting_application(self, api):
        """PRD §3.7: "Then the cascade walks three hops: each member's
        `consecutive_absence_streak` is recomputed — a `PRESENT` resets it to 0,
        an `ABSENT` increments it; any member whose streak reaches exactly 2
        gains one `attendance_strikes` and has their `credit_score` recomputed;
        and any `VOTING` application whose applicant just received a strike is
        moved to `REJECTED`."
        PRD §3.4: "with no open loan it is the final score of their most
        recently terminated loan; and a member who has never held a loan reads
        600."

        Design: Difficulty/transitive_cascade/meeting_close_absence_strike_cascade_rejects_voting_application
        """
        ctx = setup_active_group(prefix="strike-cascade")
        p1 = ctx["peers"][0]
        others = [ctx["applicant"], ctx["peers"][1], ctx["peers"][2], ctx["peers"][3]]

        application = draft_application(ctx["group"]["id"], p1["id"], 50_000)
        submit_application(application["id"])
        for voter in others[:2]:
            get_success_data(
                api.cast_vote(
                    application["id"], {"decision": "APPROVE"},
                    make_member_headers(voter["id"]),
                )
            )

        # First meeting: p1 unmarked -> auto-ABSENT at close (streak 1).
        meeting1 = schedule_meeting(ctx["center"]["id"], ctx["manager"])
        open_meeting(meeting1["id"], ctx["manager"])
        mark_attendance(meeting1["id"], ctx["manager"], [m["id"] for m in others])
        close_meeting(meeting1["id"], ctx["manager"])

        # Second meeting: p1 unmarked again.
        meeting2 = schedule_meeting(
            ctx["center"]["id"], ctx["manager"],
            start="2026-09-15T10:00:00Z", end="2026-09-15T11:00:00Z",
        )
        open_meeting(meeting2["id"], ctx["manager"])
        mark_attendance(meeting2["id"], ctx["manager"], [m["id"] for m in others])
        close_meeting(meeting2["id"], ctx["manager"])

        p1_now = get_success_data(api.get_member(p1["id"], PA))
        assert p1_now["consecutive_absence_streak"] == 2
        assert p1_now["attendance_strikes"] == 1
        assert p1_now["credit_score"] == 600, (
            "a member who has never held a loan reads 600"
        )
        app_now = get_success_data(api.get_loan_application(application["id"], PA))
        assert app_now["status"] == "REJECTED", (
            "a strike during VOTING auto-rejects the application"
        )

    def test_meeting_close_absence_strike_cascade_rejects_voting_application_present_resets(self, api):
        """PRD §3.7: "Then the cascade walks three hops: each member's
        `consecutive_absence_streak` is recomputed — a `PRESENT` resets it to 0,
        an `ABSENT` increments it; any member whose streak reaches exactly 2
        gains one `attendance_strikes` and has their `credit_score` recomputed".

        Design: Difficulty/transitive_cascade/meeting_close_absence_strike_cascade_rejects_voting_application
        """
        ctx = setup_active_group(prefix="streak-reset")
        p1 = ctx["peers"][0]
        others = [ctx["applicant"], ctx["peers"][1], ctx["peers"][2], ctx["peers"][3]]

        # Meeting 1: p1 auto-ABSENT (streak 1).
        meeting1 = schedule_meeting(ctx["center"]["id"], ctx["manager"])
        open_meeting(meeting1["id"], ctx["manager"])
        mark_attendance(meeting1["id"], ctx["manager"], [m["id"] for m in others])
        close_meeting(meeting1["id"], ctx["manager"])
        mid = get_success_data(api.get_member(p1["id"], PA))
        assert mid["consecutive_absence_streak"] == 1

        # Meeting 2: p1 marked PRESENT -> streak resets; no strike fires.
        meeting2 = schedule_meeting(
            ctx["center"]["id"], ctx["manager"],
            start="2026-09-15T10:00:00Z", end="2026-09-15T11:00:00Z",
        )
        open_meeting(meeting2["id"], ctx["manager"])
        mark_attendance(
            meeting2["id"], ctx["manager"],
            [m["id"] for m in others] + [p1["id"]],
        )
        close_meeting(meeting2["id"], ctx["manager"])
        p1_now = get_success_data(api.get_member(p1["id"], PA))
        assert p1_now["consecutive_absence_streak"] == 0, "PRESENT resets the streak"
        assert p1_now["attendance_strikes"] == 0, "no strike fires below streak 2"

    def test_absence_streak_1_vs_2_boundary_at_close(self, api):
        """PRD §3.3: "must carry a `consecutive_absence_streak` below 2 — a
        streak of exactly 2 blocks submission with `ERR_ATTENDANCE_INELIGIBLE`".
        PRD §3.7: "any member whose streak reaches exactly 2 gains one
        `attendance_strikes` and has their `credit_score` recomputed; and any
        `VOTING` application whose applicant just received a strike is moved to
        `REJECTED`."

        Design: Difficulty/boundary_precision_check/absence_streak_1_vs_2_boundary_at_close
        """
        ctx = setup_active_group(prefix="streak-12")
        p1 = ctx["peers"][0]
        others = [ctx["applicant"], ctx["peers"][1], ctx["peers"][2], ctx["peers"][3]]

        # First meeting: p1 auto-ABSENT (streak 1, strike 0).
        meeting1 = schedule_meeting(ctx["center"]["id"], ctx["manager"])
        open_meeting(meeting1["id"], ctx["manager"])
        mark_attendance(meeting1["id"], ctx["manager"], [m["id"] for m in others])
        close_meeting(meeting1["id"], ctx["manager"])

        # Streak 1 does not block submission.
        application = draft_application(ctx["group"]["id"], p1["id"], 50_000)
        submitted = submit_application(application["id"])
        assert submitted["status"] == "VOTING"

        # Second consecutive absence fires the strike.
        meeting2 = schedule_meeting(
            ctx["center"]["id"], ctx["manager"],
            start="2026-09-15T10:00:00Z", end="2026-09-15T11:00:00Z",
        )
        open_meeting(meeting2["id"], ctx["manager"])
        mark_attendance(meeting2["id"], ctx["manager"], [m["id"] for m in others])
        close_meeting(meeting2["id"], ctx["manager"])

        p1_now = get_success_data(api.get_member(p1["id"], PA))
        assert p1_now["consecutive_absence_streak"] == 2
        assert p1_now["attendance_strikes"] == 1
        app_now = get_success_data(api.get_loan_application(application["id"], PA))
        assert app_now["status"] == "REJECTED", (
            "the strike cascade fires on the applicant's VOTING application"
        )

    def test_absence_streak_1_vs_2_boundary_at_close_blocked_submit(self, api):
        """PRD §3.3: "must carry a `consecutive_absence_streak` below 2 — a
        streak of exactly 2 blocks submission with `ERR_ATTENDANCE_INELIGIBLE`".
        PRD §3.7: "any member whose streak reaches exactly 2 gains one
        `attendance_strikes` and has their `credit_score` recomputed".

        Design: Difficulty/boundary_precision_check/absence_streak_1_vs_2_boundary_at_close
        """
        ctx = setup_active_group(prefix="streak-block")
        p1 = ctx["peers"][0]
        others = [ctx["applicant"], ctx["peers"][1], ctx["peers"][2], ctx["peers"][3]]

        for start in ("2026-09-08T10:00:00Z", "2026-09-15T10:00:00Z"):
            meeting = schedule_meeting(
                ctx["center"]["id"], ctx["manager"],
                start=start, end=start.replace("T10:00:00Z", "T11:00:00Z"),
            )
            open_meeting(meeting["id"], ctx["manager"])
            mark_attendance(meeting["id"], ctx["manager"], [m["id"] for m in others])
            close_meeting(meeting["id"], ctx["manager"])

        p1_now = get_success_data(api.get_member(p1["id"], PA))
        assert p1_now["consecutive_absence_streak"] == 2
        assert p1_now["attendance_strikes"] == 1

        application = draft_application(ctx["group"]["id"], p1["id"], 50_000)
        response = api.submit_loan_application(application["id"], TEST_USERS["field_officer_headers"])
        validate_error(response, ApiErrorId.ERR_ATTENDANCE_INELIGIBLE, expected_status=409)
