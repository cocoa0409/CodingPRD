"""Role-based access control and the user-context pipeline stage: missing
headers, role-vs-endpoint permission, and the four ownership scopes
(PRD §2.1, §2.8).
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    advance_phase_payload,
    build_user_headers,
    cast_vote,
    get_group,
    get_investigation,
    get_meeting,
    make_board_member_headers,
    make_group_chairman_headers,
    make_iic_headers,
    set_clock,
    setup_factual,
    setup_launched_investigation,
    setup_meeting_in_session,
    validate_error,
    verify_report,
    vote_payload,
)

DUTY_OFFICER = TEST_USERS["duty_officer_headers"]


class TestUserContextStage:
    def test_missing_auth_headers_on_case_get_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or naming a role outside
        the declared set, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`." PRD §2.8: "Every request
        is evaluated against a fixed pipeline of checks; when several checks
        would fail, the earliest stage's error is the one returned."

        Design: Corner/validations/missing_auth_headers_on_case_get_returns_unauthenticated
        """
        set_clock()
        # No headers at all: the id need not exist — user context (stage 1)
        # precedes existence (stage 3), so no not-found information leaks.
        resp = api.get_accident_case(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

        # Only one of the two headers present.
        resp = api.get_accident_case(NON_EXISTENT_UUID, headers={"X-User-ID": "someone"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

        # A role outside the declared set.
        resp = api.get_accident_case(
            NON_EXISTENT_UUID, headers=build_user_headers("someone", "SuperUser")
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_duty_officer_cannot_adopt_and_role_check_precedes_existence(self, api):
        """PRD §2.1: "Each endpoint declares the roles permitted to call it; a
        caller whose role is not permitted is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS`." PRD §2.8: "when several checks would
        fail, the earliest stage's error is the one returned" — role (stage 2)
        precedes existence (stage 3).

        Design: Corner/validations/duty_officer_cannot_adopt_and_role_check_precedes_existence
        """
        set_clock()
        resp = api.adopt_launch_decision(
            NON_EXISTENT_UUID,
            NON_EXISTENT_UUID,
            {"iic_user_id": "iic-1"},
            DUTY_OFFICER,
        )
        error_data = validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        assert error_data["error_id"] != ApiErrorId.ERR_ACCIDENT_CASE_NOT_FOUND


class TestOwnershipScopes:
    def test_group_chairman_cannot_complete_another_chairmans_group(self, api):
        """PRD §2.1: "`GroupChairman` actions require `X-User-ID` to equal the
        group's `chairman_user_id`, with violations reported as
        `ERR_CHAIRMAN_OWNERSHIP`."

        Design: Corner/rbac/group_chairman_cannot_complete_another_chairmans_group
        """
        ctx = setup_factual()
        group_id = ctx["group"]["id"]
        # All state gates satisfied (FACTUAL phase, seat, VERIFIED report);
        # only the caller's identity is wrong.
        verify_report(group_id, ctx["report_id"], iic_user_id=ctx["iic_user_id"])

        resp = api.complete_group(group_id, make_group_chairman_headers("gc-2"))
        validate_error(resp, ApiErrorId.ERR_CHAIRMAN_OWNERSHIP)
        assert get_group(group_id)["status"] == "ACTIVE"

    def test_non_sitting_member_cannot_vote(self, api):
        """PRD §2.1: "`BoardMember` votes require `X-User-ID` to appear in the
        meeting's `sitting_member_ids`, else `ERR_NOT_SITTING_MEMBER`."

        Design: Corner/rbac/non_sitting_member_cannot_vote
        """
        ctx = setup_meeting_in_session()
        meeting = ctx["meeting"]

        resp = api.cast_vote(
            meeting["id"],
            vote_payload("ADOPT", meeting["version"]),
            make_board_member_headers("bm-9"),  # not on the roster
        )
        validate_error(resp, ApiErrorId.ERR_NOT_SITTING_MEMBER)

        reread = get_meeting(meeting["id"])
        assert reread["member_votes"] == []
        assert reread["version"] == meeting["version"]

    def test_board_member_cannot_close_meeting(self, api):
        """PRD §2.1: "Each endpoint declares the roles permitted to call it; a
        caller whose role is not permitted is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS`." PRD §4: closing a meeting is a
        `BoardAdmin` operation; `BoardMember` is not on it.

        Design: Corner/rbac/board_member_cannot_close_meeting
        """
        ctx = setup_meeting_in_session()
        meeting = cast_vote(ctx["meeting"], "bm-1", "ADOPT")

        resp = api.close_board_meeting(meeting["id"], make_board_member_headers("bm-1"))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

        reread = get_meeting(meeting["id"])
        assert reread["status"] == "IN_SESSION"
        assert reread["outcome"] is None

    def test_iic_scope_violation_cannot_advance_foreign_investigation(self, api):
        """PRD §2.1: "`IIC` actions require `X-User-ID` to equal the
        investigation's `iic_user_id`" — a caller holding the IIC role but a
        different identity is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

        Design: Corner/rbac/iic_scope_violation_cannot_advance_foreign_investigation
        """
        ctx = setup_launched_investigation()
        inv_id = ctx["investigation"]["id"]
        assert ctx["iic_user_id"] == "iic-1"

        resp = api.advance_phase(
            inv_id, advance_phase_payload("ON_SCENE"), make_iic_headers("iic-2")
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        assert get_investigation(inv_id)["phase"] == "GO_TEAM_ASSEMBLED"
