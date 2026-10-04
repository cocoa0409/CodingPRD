"""Plan authorizations: denial cascade, appeal window boundary, terminal
lockdown, and non-terminal uniqueness."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_authorization_payload,
    set_clock, setup_employer_with_member,
    grant_consent, setup_navigation_case, setup_authorization,
)
from test_helpers.test_users import (
    make_member_headers,
    make_nurse_navigator_headers,
    make_plan_administrator_headers,
)


def _plan():
    return make_plan_administrator_headers("pa-1")


class TestAuthorizationDenialCascade:
    def test_authorization_denial_blocks_opinion_and_escalates_origin_case(
            self, api):
        """PRD §3.9: "Denial of a `REQUESTED` authorization requires a
        `denial_reason`, stamps `decided_at`, and moves it to `DENIED`; when
        the denied service code is `EXPERT_MEDICAL_OPINION`, the member's
        opinion cases waiting in `INTAKE` move to `AUTH_BLOCKED`, and that
        blockage escalates the linked navigation case per §3.3."
        PRD §3.6: "If the member's `EXPERT_MEDICAL_OPINION` authorization is
        denied while the case awaits one in `INTAKE`, the case moves to
        `AUTH_BLOCKED`; a later approval moves it back to `INTAKE`."

        Design: Difficulty/transitive_cascade/authorization_denial_blocks_opinion_and_escalates_origin_case
        """
        set_clock()
        _, member = setup_employer_with_member(emo_benefit_enabled=True)
        grant_consent(member, "EMO_REVIEW")
        nc = setup_navigation_case(
            member, {"question_type": "CLINICAL", "acuity": "LOW"},
            navigator_id="nn-2", navigator_role="NurseNavigator", start=True)
        emo = validate_success(api.create_expert_opinion(
            member["id"],
            {"condition_summary": "Shoulder surgery second opinion",
             "navigation_case_id": nc["id"]},
            make_member_headers(member["id"])), expected_status=201)
        auth = setup_authorization(member)

        denied = validate_success(api.deny_authorization(
            auth["id"], {"denial_reason": "Not medically necessary per plan"},
            _plan()))
        assert denied["status"] == "DENIED"

        emo_after = validate_success(api.get_expert_opinion(
            emo["id"], make_member_headers(member["id"])))
        assert emo_after["status"] == "AUTH_BLOCKED"

        nc_after = validate_success(api.get_navigation_case(
            nc["id"], make_nurse_navigator_headers("nn-2")))
        assert nc_after["status"] == "ESCALATED"

        validate_success(api.appeal_authorization(
            auth["id"], make_member_headers(member["id"])))
        approved = validate_success(api.approve_authorization(
            auth["id"], _plan()))
        assert approved["status"] == "APPROVED"

        emo_back = validate_success(api.get_expert_opinion(
            emo["id"], make_member_headers(member["id"])))
        assert emo_back["status"] == "INTAKE"

    def test_denial_leaves_unlinked_opinion_cases_untouched(self, api):
        """PRD §3.9: "when the denied service code is `EXPERT_MEDICAL_OPINION`,
        the member's opinion cases waiting in `INTAKE` move to `AUTH_BLOCKED`".

        Design: Difficulty/transitive_cascade/authorization_denial_blocks_opinion_and_escalates_origin_case
        """
        set_clock()
        _, member = setup_employer_with_member(emo_benefit_enabled=True)
        grant_consent(member, "EMO_REVIEW")
        # Opinion not linked to any navigation case: the block still applies.
        emo = validate_success(api.create_expert_opinion(
            member["id"], {"condition_summary": "Standalone opinion"},
            make_member_headers(member["id"])), expected_status=201)
        auth = setup_authorization(member)

        validate_success(api.deny_authorization(
            auth["id"], {"denial_reason": "Not medically necessary per plan"},
            _plan()))
        emo_after = validate_success(api.get_expert_opinion(
            emo["id"], make_member_headers(member["id"])))
        assert emo_after["status"] == "AUTH_BLOCKED"

        validate_success(api.appeal_authorization(
            auth["id"], make_member_headers(member["id"])))
        validate_success(api.approve_authorization(auth["id"], _plan()))
        emo_back = validate_success(api.get_expert_opinion(
            emo["id"], make_member_headers(member["id"])))
        assert emo_back["status"] == "INTAKE"


class TestAppealWindow:
    def test_appeal_window_thirty_day_boundary(self, api):
        """PRD §3.9: "The member may appeal a denial — only their own, else
        `ERR_MEMBER_MISMATCH` — moving the authorization to `APPEALED`, but
        only within thirty days of `decided_at` by the logical clock; an appeal
        after that window is rejected with `ERR_APPEAL_WINDOW_CLOSED` (422)."

        Design: Corner/validations/appeal_window_thirty_day_boundary
        """
        set_clock()
        _, member = setup_employer_with_member()
        auth1 = setup_authorization(member, service_code="PROCEDURE")
        validate_success(api.deny_authorization(
            auth1["id"], {"denial_reason": "Not covered"}, _plan()))
        auth2 = setup_authorization(member, service_code="IMAGING")
        validate_success(api.deny_authorization(
            auth2["id"], {"denial_reason": "Not covered"}, _plan()))

        # decided_at is 2026-09-01T00:00:00Z; +30 days is 2026-10-01T00:00:00Z
        set_clock("2026-10-01T00:00:00Z")
        at_boundary = validate_success(api.appeal_authorization(
            auth1["id"], make_member_headers(member["id"])))
        assert at_boundary["status"] == "APPEALED"

        set_clock("2026-10-01T00:00:01Z")
        late = api.appeal_authorization(
            auth2["id"], make_member_headers(member["id"]))
        validate_error(late, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED,
                       expected_status=422)
        auth2_after = validate_success(api.get_authorization(
            auth2["id"], make_member_headers(member["id"])))
        assert auth2_after["status"] == "DENIED"


class TestAuthorizationTerminal:
    def test_authorization_approve_after_deny_final_rejected(self, api):
        """PRD §3.9: "A denied-again appeal is final: denying an `APPEALED`
        authorization moves it to terminal `DENIED_FINAL`, re-stamps
        `decided_at`, and fires the same authorization-block cascade for the
        member's `INTAKE` opinion cases."
        PRD §2.6: "Sixth, state-machine legality: the target entity must be in
        a valid from-state (else `ERR_INVALID_STATE` or the more specific state
        error the workflow declares)."

        Design: Corner/state_machines/authorization_approve_after_deny_final_rejected
        """
        set_clock()
        _, member = setup_employer_with_member()
        auth = setup_authorization(member, service_code="PROCEDURE")
        validate_success(api.deny_authorization(
            auth["id"], {"denial_reason": "No coverage"}, _plan()))
        validate_success(api.appeal_authorization(
            auth["id"], make_member_headers(member["id"])))

        final = validate_success(api.deny_authorization(
            auth["id"], {"denial_reason": "Upheld on appeal"}, _plan()))
        assert final["status"] == "DENIED_FINAL"

        resp = api.approve_authorization(auth["id"], _plan())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE,
                       expected_status=409)


class TestDuplicateAuthorization:
    def test_duplicate_non_terminal_authorization_rejected(self, api):
        """PRD §3.9: "A member may hold at most one non-terminal authorization
        per service code: an existing `REQUESTED` or `APPEALED` authorization
        blocks a new request for the same code with
        `ERR_DUPLICATE_AUTHORIZATION` (409)."

        Design: Corner/validations/duplicate_non_terminal_authorization_rejected
        """
        set_clock()
        _, member = setup_employer_with_member()
        member_h = make_member_headers(member["id"])
        setup_authorization(member, service_code="PROCEDURE")
        auth_img = setup_authorization(member, service_code="IMAGING")
        validate_success(api.deny_authorization(
            auth_img["id"], {"denial_reason": "No"}, _plan()))

        dup = api.create_authorization(
            member["id"],
            create_authorization_payload(service_code="PROCEDURE", units=2),
            member_h)
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_AUTHORIZATION,
                       expected_status=409)

        fresh = api.create_authorization(
            member["id"],
            create_authorization_payload(service_code="IMAGING", units=2),
            member_h)
        validate_success(fresh, expected_status=201)
