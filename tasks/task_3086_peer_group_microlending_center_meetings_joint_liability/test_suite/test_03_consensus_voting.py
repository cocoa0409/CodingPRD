"""Consensus voting and application state corners."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_application,
    cast_approve,
    draft_application,
    get_success_data,
    make_member_headers,
    setup_active_group,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)

PA = TEST_USERS["program_admin_headers"]
FO = TEST_USERS["field_officer_headers"]


class TestApplicationStateTransitions:
    def test_submit_on_voting_application_returns_not_draft(self, api):
        """PRD §3.3: "The application must be `DRAFT` (`ERR_APPLICATION_NOT_DRAFT`)."

        Design: Corner/state_machines/submit_on_voting_application_returns_not_draft
        """
        ctx = setup_active_group(prefix="resubmit")
        application = draft_application(ctx["group"]["id"], ctx["applicant"]["id"])
        submitted = submit_application(application["id"])
        original_deadline = submitted["voting_deadline"]

        response = api.submit_loan_application(application["id"], FO)
        validate_error(response, ApiErrorId.ERR_APPLICATION_NOT_DRAFT, expected_status=409)

        current = get_success_data(api.get_loan_application(application["id"], PA))
        assert current["status"] == "VOTING"
        assert current["voting_deadline"] == original_deadline, (
            "no second voting_deadline may be minted"
        )

    def test_vote_on_rejected_application_returns_not_voting(self, api):
        """PRD §3.3: "Any single `REJECT` vote kills it immediately as
        `REJECTED`."
        PRD §3.3: "The application must be `VOTING` (`ERR_APPLICATION_NOT_VOTING`)".

        Design: Corner/state_machines/vote_on_rejected_application_returns_not_voting
        """
        ctx = setup_active_group(prefix="vote-rejected")
        application = draft_application(ctx["group"]["id"], ctx["applicant"]["id"])
        submit_application(application["id"])
        get_success_data(
            api.cast_vote(
                application["id"],
                {"decision": "REJECT"},
                make_member_headers(ctx["peers"][0]["id"]),
            )
        )
        response = api.cast_vote(
            application["id"],
            {"decision": "APPROVE"},
            make_member_headers(ctx["peers"][1]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_APPLICATION_NOT_VOTING, expected_status=409)
        current = get_success_data(api.get_loan_application(application["id"], PA))
        assert current["status"] == "REJECTED"

    def test_vote_cast_requires_application_voting_state(self, api):
        """PRD §3.3: "The application must be `VOTING`
        (`ERR_APPLICATION_NOT_VOTING`); the voter must belong to the applicant's
        group (`ERR_VOTER_NOT_GROUP_PEER`)".

        Design: Difficulty/cross_entity_state_dependency/vote_cast_requires_application_voting_state
        """
        ctx = setup_active_group(prefix="vote-draft")
        application = draft_application(ctx["group"]["id"], ctx["applicant"]["id"])
        response = api.cast_vote(
            application["id"],
            {"decision": "APPROVE"},
            make_member_headers(ctx["peers"][0]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_APPLICATION_NOT_VOTING, expected_status=409)
        votes, meta = validate_paginated(api.list_application_votes(application["id"], PA))
        assert votes == [], "a rejected vote must not be recorded"
        current = get_success_data(api.get_loan_application(application["id"], PA))
        assert current["status"] == "DRAFT"

    def test_vote_cast_requires_application_voting_state_after_disbursement(self, api):
        """PRD §3.3: "The application must be `VOTING`
        (`ERR_APPLICATION_NOT_VOTING`)".
        PRD §3.4: "the application itself moves from `APPROVED` to its terminal
        `DISBURSED` status."

        Design: Difficulty/cross_entity_state_dependency/vote_cast_requires_application_voting_state
        """
        ctx = setup_active_group(prefix="vote-disbursed")
        application = draft_application(ctx["group"]["id"], ctx["applicant"]["id"])
        submit_application(application["id"])
        approve_application(
            application["id"], ctx["applicant"]["id"], [p["id"] for p in ctx["peers"]]
        )
        get_success_data(api.disburse_loan_application(application["id"], TEST_USERS["branch_manager_headers"]))
        response = api.cast_vote(
            application["id"],
            {"decision": "APPROVE"},
            make_member_headers(ctx["peers"][0]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_APPLICATION_NOT_VOTING, expected_status=409)
        current = get_success_data(api.get_loan_application(application["id"], PA))
        assert current["status"] == "DISBURSED"

    def test_double_vote_returns_already_voted(self, api):
        """PRD §3.3: "each peer votes at most once (`ERR_ALREADY_VOTED`)".

        Design: Corner/state_machines/double_vote_returns_already_voted
        """
        ctx = setup_active_group(prefix="double-vote")
        application = draft_application(ctx["group"]["id"], ctx["applicant"]["id"])
        submit_application(application["id"])
        voter = ctx["peers"][0]
        cast_approve(application["id"], voter["id"])
        response = api.cast_vote(
            application["id"], {"decision": "REJECT"}, make_member_headers(voter["id"])
        )
        validate_error(response, ApiErrorId.ERR_ALREADY_VOTED, expected_status=409)
        votes, meta = validate_paginated(api.list_application_votes(application["id"], PA))
        assert len(votes) == 1, f"exactly one vote may be recorded, got {len(votes)}"
