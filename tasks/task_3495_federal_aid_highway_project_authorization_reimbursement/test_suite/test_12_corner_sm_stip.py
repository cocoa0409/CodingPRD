"""Corner queue — state_machines (STIP): the 30-day comment window boundary,
the zero-comment participation gate, REJECT preserving the window, and the
decide state gate (PRD §3.2, §2.7)."""
from test_helpers import (
    TEST_USERS,
    add_stip_comment,
    api_client,
    assert_state_program,
    create_stip,
    decide_stip,
    get_success_data,
    set_clock,
    submit_stip,
    validate_error,
)
from test_helpers import ApiErrorId

H = TEST_USERS


class TestStipStateMachine:
    def test_stip_submit_before_thirty_days_returns_comment_period_open(self, api):
        """PRD §3.2: "And the logical clock must have reached at least 30 days
        after the window opened — a submission at exactly 30 days elapsed
        passes — else `ERR_COMMENT_PERIOD_OPEN` (409)."

        Nine days into the window, with the participation minimum already met
        by an existing comment, the window gate is the one that fires.

        Design: Corner/state_machines/stip_submit_before_thirty_days_returns_comment_period_open
        """
        set_clock("2026-09-01T00:00:00Z")
        stip = create_stip(state_code="AZ", land_pct=0.0, start_ffy=2027)
        add_stip_comment(stip["id"])
        set_clock("2026-09-10T00:00:00Z")

        resp = api.submit_stip(stip["id"], H["state_dot_planner"])
        error = validate_error(resp, ApiErrorId.ERR_COMMENT_PERIOD_OPEN)
        assert resp.status_code == 409, f"expected 409, got {resp.status_code} ({error})"
        reread = get_success_data(api.get_stip(stip["id"], H["state_dot_planner"]))
        assert reread["status"] == "PUBLIC_INVOLVEMENT"

    def test_stip_submit_at_exactly_thirty_days_allowed(self, api):
        """PRD §3.2: "And the logical clock must have reached at least 30 days
        after the window opened — a submission at exactly 30 days elapsed
        passes — else `ERR_COMMENT_PERIOD_OPEN` (409)."

        The comparison is inclusive: exactly comment_period_opened_at + 30
        days (2026-09-01 -> 2026-10-01) submits successfully.

        Design: Corner/state_machines/stip_submit_at_exactly_thirty_days_allowed
        """
        set_clock("2026-09-01T00:00:00Z")
        stip = create_stip(state_code="AZ", land_pct=0.0, start_ffy=2027)
        add_stip_comment(stip["id"])
        set_clock("2026-10-01T00:00:00Z")  # exactly +30 days

        submitted = submit_stip(stip["id"])
        assert_state_program(submitted)
        assert submitted["status"] == "SUBMITTED"

    def test_stip_submit_with_zero_comments_returns_public_involvement_incomplete(self, api):
        """PRD §3.2: "The public record must contain at least 1 comment whose
        `created_at` is on or after `comment_period_opened_at`, else
        `ERR_PUBLIC_INVOLVEMENT_INCOMPLETE` (422)."

        With the window fully elapsed but zero comments recorded, the
        participation gate fires.

        Design: Corner/state_machines/stip_submit_with_zero_comments_returns_public_involvement_incomplete
        """
        set_clock("2026-09-01T00:00:00Z")
        stip = create_stip(state_code="AZ", land_pct=0.0, start_ffy=2027)
        set_clock("2026-10-02T00:00:00Z")  # 31 days: window satisfied

        resp = api.submit_stip(stip["id"], H["state_dot_planner"])
        error = validate_error(resp, ApiErrorId.ERR_PUBLIC_INVOLVEMENT_INCOMPLETE)
        assert resp.status_code == 422, f"expected 422, got {resp.status_code} ({error})"
        reread = get_success_data(api.get_stip(stip["id"], H["state_dot_planner"]))
        assert reread["status"] == "PUBLIC_INVOLVEMENT"

    def test_stip_reject_returns_to_public_involvement_preserving_window(self, api):
        """PRD §3.2: "A `decision` of `REJECT` returns the STIP to
        `PUBLIC_INVOLVEMENT` without resetting `comment_period_opened_at` and
        preserving existing comments, so a window that had already elapsed
        permits immediate resubmission."

        After the rejection the original 2026-09-01 window opener and its
        comment are intact, so the immediate resubmission succeeds without any
        new comment or clock advance.

        Design: Corner/state_machines/stip_reject_returns_to_public_involvement_preserving_window
        """
        set_clock("2026-09-01T00:00:00Z")
        stip = create_stip(state_code="AZ", land_pct=0.0, start_ffy=2027)
        add_stip_comment(stip["id"])
        set_clock("2026-10-02T00:00:00Z")
        submit_stip(stip["id"])

        rejected = decide_stip(stip["id"], "REJECT")
        assert_state_program(rejected)
        assert rejected["status"] == "PUBLIC_INVOLVEMENT"
        assert rejected["comment_period_opened_at"] == "2026-09-01T00:00:00Z", (
            "REJECT must not reset the comment window, got "
            f"{rejected['comment_period_opened_at']}"
        )
        assert rejected["amendment_count"] == 0

        resubmitted = submit_stip(stip["id"])
        assert resubmitted["status"] == "SUBMITTED", (
            "the original window had already elapsed and its comment still "
            "counts, so immediate resubmission succeeds"
        )

    def test_stip_decide_while_public_involvement_returns_invalid_state(self, api):
        """PRD §2.7: "6. State gate: the target resource must be in a valid
        from-state for the requested action, else `ERR_INVALID_STATE` (409)."
        PRD §3.2: "An `FHWADivisionAdmin` then decides the `SUBMITTED` STIP by
        supplying a `decision`."

        The decide action is defined on a SUBMITTED STIP; calling it on a
        freshly created (PUBLIC_INVOLVEMENT) STIP is a wrong-state call.

        Design: Corner/state_machines/stip_decide_while_public_involvement_returns_invalid_state
        """
        set_clock("2026-09-01T00:00:00Z")
        stip = create_stip(state_code="AZ", land_pct=0.0, start_ffy=2027)

        resp = api.decide_stip(stip["id"], {"decision": "APPROVE"}, H["fhwa_division_admin"])
        error = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409, f"expected 409, got {resp.status_code} ({error})"
        reread = get_success_data(api.get_stip(stip["id"], H["state_dot_planner"]))
        assert reread["status"] == "PUBLIC_INVOLVEMENT"
