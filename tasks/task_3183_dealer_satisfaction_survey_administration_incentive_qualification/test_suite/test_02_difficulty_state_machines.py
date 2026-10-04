"""Difficulty queue: non-linear state machines and cross-entity state guards."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS, make_dealer_principal_headers, make_customer_headers,
    setup_dealer_env, create_tx, open_wave_and_get_invitations,
    send_invitation, respond, reset_clock,
    create_draft_plan, file_appeal,
)

ADMIN = TEST_USERS["admin_headers"]
FC = TEST_USERS["field_consultant_headers"]
RM = TEST_USERS["regional_manager_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]
VENDOR = TEST_USERS["survey_vendor_headers"]


class TestActionPlanRevisionLoop:
    def test_revision_cycle_reaches_completed(self, api):
        """PRD §3.9: "Rejection is not terminal: the principal may revise,
        which returns the plan to DRAFT and clears review_note back to null,
        ready for another cycle. An APPROVED plan is started by the principal
        — again ownership-guarded — moving it to IN_PROGRESS. Completion
        belongs to the field consultant, whose action moves IN_PROGRESS →
        COMPLETED, the plan's only terminal state."

        Design: Difficulty/non_linear_state_machine/action_plan_revision_loop_branching
        """
        env = setup_dealer_env(dealer_code="D5", customers=0)
        dealer_id = env["dealer"]["id"]
        dp = make_dealer_principal_headers(dealer_id)
        plan = create_draft_plan(dealer_id, env["wave"]["id"])
        # first cycle: submit -> rejected -> revise
        validate_success(api.submit_action_plan(plan["id"], dp), 200)
        rejected = validate_success(api.review_action_plan(
            plan["id"],
            {"outcome": "REJECTED", "review_note": "insufficient detail"},
            FC,
        ), 200)
        assert rejected["status"] == "REJECTED"
        revised = validate_success(api.revise_action_plan(plan["id"], dp), 200)
        assert revised["status"] == "DRAFT"
        assert revised["review_note"] is None, (
            "revision clears review_note back to null"
        )
        # second cycle: submit -> approved -> start -> complete
        validate_success(api.submit_action_plan(plan["id"], dp), 200)
        approved = validate_success(api.review_action_plan(
            plan["id"], {"outcome": "APPROVED", "review_note": "ok"}, FC,
        ), 200)
        assert approved["status"] == "APPROVED"
        started = validate_success(api.start_action_plan(plan["id"], dp), 200)
        assert started["status"] == "IN_PROGRESS"
        completed = validate_success(api.complete_action_plan(plan["id"], FC), 200)
        assert completed["status"] == "COMPLETED"

    def test_revise_clears_review_note_and_allows_resubmission(self, api):
        """PRD §3.9: "Rejection is not terminal: the principal may revise,
        which returns the plan to DRAFT and clears review_note back to null,
        ready for another cycle."

        Design: Difficulty/non_linear_state_machine/action_plan_revision_loop_branching
        """
        env = setup_dealer_env(dealer_code="D5b", customers=0)
        dealer_id = env["dealer"]["id"]
        dp = make_dealer_principal_headers(dealer_id)
        plan = create_draft_plan(dealer_id, env["wave"]["id"])
        validate_success(api.submit_action_plan(plan["id"], dp), 200)
        validate_success(api.review_action_plan(
            plan["id"], {"outcome": "REJECTED", "review_note": "more detail"}, FC,
        ), 200)
        after_revise = validate_success(api.revise_action_plan(plan["id"], dp), 200)
        assert after_revise["status"] == "DRAFT"
        assert after_revise["review_note"] is None
        # plan can be resubmitted after revision (cycle repeats)
        resubmitted = validate_success(
            api.submit_action_plan(plan["id"], dp), 200
        )
        assert resubmitted["status"] == "SUBMITTED"


class TestAppealForkJoin:
    def test_appeal_upheld_excludes_response_denied_restores(self, api):
        """PRD §3.7: "An UPHELD outcome moves the appeal to its terminal
        UPHELD state and cascades the response from FLAGGED to EXCLUDED with
        excluded_reason set to APPEAL_UPHELD — the response is permanently out
        of all scoring. A DENIED outcome terminates the appeal at DENIED and
        cascades the response back from FLAGGED to SCORED, restoring it to the
        input set for any future score computation."

        Design: Difficulty/non_linear_state_machine/appeal_response_fork_join_per_response_guard
        """
        env = setup_dealer_env(dealer_code="D6", customers=2)
        ca, cb = env["customers"]
        create_tx(env, ca, margin_cents=1000, completed_at="2026-09-05T00:00:00Z")
        create_tx(env, cb, margin_cents=1000, completed_at="2026-09-06T00:00:00Z")
        invs = open_wave_and_get_invitations(env)
        assert len(invs) == 2
        by_cust = {inv["customer_id"]: inv for inv in invs}
        send_invitation(by_cust[ca["id"]]["id"])
        send_invitation(by_cust[cb["id"]]["id"])
        resp_a = respond(by_cust[ca["id"]], ca, {"q1": 5})
        resp_b = respond(by_cust[cb["id"]], cb, {"q1": 6})

        appeal_a = file_appeal(env["dealer"]["id"], resp_a, reason="wrong customer")
        validate_success(api.assign_appeal(appeal_a["id"], RM), 200)
        upheld = validate_success(api.decide_appeal(
            appeal_a["id"],
            {"outcome": "UPHELD", "decision_rationale": "verified wrong customer"},
            AUDITOR,
        ), 200)
        assert upheld["status"] == "UPHELD"

        appeal_b = file_appeal(env["dealer"]["id"], resp_b, reason="coerced")
        validate_success(api.assign_appeal(appeal_b["id"], RM), 200)
        denied = validate_success(api.decide_appeal(
            appeal_b["id"],
            {"outcome": "DENIED", "decision_rationale": "no evidence"},
            AUDITOR,
        ), 200)
        assert denied["status"] == "DENIED"

        ra = validate_success(api.get_response(resp_a["id"], ADMIN))
        rb = validate_success(api.get_response(resp_b["id"], ADMIN))
        assert ra["status"] == "EXCLUDED"
        assert ra["excluded_reason"] == "APPEAL_UPHELD"
        assert rb["status"] == "SCORED"
        assert rb["excluded_reason"] is None

    def test_appeal_filing_flags_response_and_decision_resolves(self, api):
        """PRD §3.7: "A successful filing does two things atomically. The new
        Appeal is created in FILED status, with dealer_id resolved from the
        response's invitation transaction and prior_response_status capturing
        the response's status at the moment of filing. And the response itself
        transitions SCORED → FLAGGED, which removes it from every subsequent
        score computation sweep until the appeal resolves — the response's
        version increments as part of the transition."
        PRD §3.7: "A DENIED outcome terminates the appeal at DENIED and
        cascades the response back from FLAGGED to SCORED, restoring it to
        the input set for any future score computation."

        Design: Difficulty/non_linear_state_machine/appeal_response_fork_join_per_response_guard
        """
        env = setup_dealer_env(dealer_code="D6b", customers=1)
        cust = env["customers"][0]
        create_tx(env, cust, margin_cents=1000)
        invs = open_wave_and_get_invitations(env)
        send_invitation(invs[0]["id"])
        resp = respond(invs[0], cust, {"q1": 5})
        assert resp["status"] == "SCORED"
        appeal = file_appeal(env["dealer"]["id"], resp, reason="bad data")
        assert appeal["status"] == "FILED"
        assert appeal["prior_response_status"] == "SCORED"
        mid = validate_success(api.get_response(resp["id"], ADMIN))
        assert mid["status"] == "FLAGGED"
        validate_success(api.assign_appeal(appeal["id"], RM), 200)
        validate_success(api.decide_appeal(
            appeal["id"],
            {"outcome": "DENIED", "decision_rationale": "no evidence"},
            AUDITOR,
        ), 200)
        after = validate_success(api.get_response(resp["id"], ADMIN))
        assert after["status"] == "SCORED"


class TestCrossEntityStateDependency:
    def test_send_after_wave_close_rejected_invalid_state(self, api):
        """PRD §3.5: "An invitation's lifecycle begins in QUEUED. A
        SurveyVendor sends it — the transition QUEUED → SENT — which requires
        two preconditions evaluated in priority order: the owning wave must
        be OPEN (otherwise ERR_WAVE_NOT_OPEN), and the customer's
        do_not_contact must still be false (otherwise ERR_CONTACT_RESTRICTED)."
        PRD §3.4: "First, every invitation still in QUEUED or SENT
        transitions to EXPIRED, with queued_count and sent_count decrementing
        and expired_count incrementing by the number expired."

        Design: Difficulty/cross_entity_state_dependency/invitation_send_depends_on_wave_open
        """
        env = setup_dealer_env(dealer_code="D13", customers=1)
        cust = env["customers"][0]
        create_tx(env, cust, margin_cents=1000)
        invs = open_wave_and_get_invitations(env)
        assert len(invs) == 1
        reset_clock("2026-10-01T00:00:00Z")
        validate_success(api.close_wave(env["wave"]["id"], ADMIN), 200)
        # the invitation was swept to EXPIRED by close; send is rejected
        err = api.send_invitation(invs[0]["id"], VENDOR)
        validate_error(err, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_send_needs_open_wave_and_close_expires_invitation(self, api):
        """PRD §3.4: "First, every invitation still in QUEUED or SENT
        transitions to EXPIRED, with queued_count and sent_count decrementing
        and expired_count incrementing by the number expired."
        PRD §3.5: "the transition QUEUED → SENT — which requires two
        preconditions evaluated in priority order: the owning wave must be
        OPEN (otherwise ERR_WAVE_NOT_OPEN), and the customer's do_not_contact
        must still be false (otherwise ERR_CONTACT_RESTRICTED)."

        Design: Difficulty/cross_entity_state_dependency/invitation_send_depends_on_wave_open
        """
        env = setup_dealer_env(dealer_code="D13b", customers=1)
        cust = env["customers"][0]
        create_tx(env, cust, margin_cents=1000)
        invs = open_wave_and_get_invitations(env)
        assert len(invs) == 1
        reset_clock("2026-10-01T00:00:00Z")
        validate_success(api.close_wave(env["wave"]["id"], ADMIN), 200)
        inv = validate_success(api.get_invitation(invs[0]["id"], ADMIN))
        assert inv["status"] == "EXPIRED", "close sweeps QUEUED to EXPIRED"
        err = api.send_invitation(invs[0]["id"], VENDOR)
        validate_error(err, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_finalize_blocked_by_undecided_appeal(self, api):
        """PRD §3.4: "It is blocked when any appeal on a response belonging
        to this wave is still in FILED or UNDER_REVIEW (the rejection is
        ERR_APPEALS_PENDING), and independently blocked when any manipulation
        flag on a dealer with invitations in this wave is still OPEN (the
        rejection is ERR_FLAGS_PENDING)."

        Design: Difficulty/cross_entity_state_dependency/wave_finalize_depends_on_appeal_resolved
        """
        env = setup_dealer_env(dealer_code="D14", customers=1)
        cust = env["customers"][0]
        create_tx(env, cust, margin_cents=1000)
        invs = open_wave_and_get_invitations(env)
        send_invitation(invs[0]["id"])
        resp = respond(invs[0], cust, {"q1": 5})
        reset_clock("2026-10-01T00:00:00Z")
        validate_success(api.close_wave(env["wave"]["id"], ADMIN), 200)
        appeal = file_appeal(env["dealer"]["id"], resp, reason="bad data")
        validate_success(api.assign_appeal(appeal["id"], RM), 200)
        err = api.finalize_wave(env["wave"]["id"], ADMIN)
        validate_error(err, ApiErrorId.ERR_APPEALS_PENDING, expected_status=409)
        wave = validate_success(api.get_wave(env["wave"]["id"], ADMIN))
        assert wave["status"] == "CLOSED", "finalize must not advance the wave"

    def test_finalize_succeeds_after_appeal_decided(self, api):
        """PRD §3.4: "It is blocked when any appeal on a response belonging
        to this wave is still in FILED or UNDER_REVIEW (the rejection is
        ERR_APPEALS_PENDING), and independently blocked when any manipulation
        flag on a dealer with invitations in this wave is still OPEN (the
        rejection is ERR_FLAGS_PENDING)." and "On success, every
        IncentiveStatement for this wave in PROVISIONAL transitions to FINAL,
        and the wave's version increments again."

        Design: Difficulty/cross_entity_state_dependency/wave_finalize_depends_on_appeal_resolved
        """
        env = setup_dealer_env(dealer_code="D14b", customers=1)
        cust = env["customers"][0]
        create_tx(env, cust, margin_cents=1000)
        invs = open_wave_and_get_invitations(env)
        send_invitation(invs[0]["id"])
        resp = respond(invs[0], cust, {"q1": 5})
        reset_clock("2026-10-01T00:00:00Z")
        validate_success(api.close_wave(env["wave"]["id"], ADMIN), 200)
        appeal = file_appeal(env["dealer"]["id"], resp, reason="bad data")
        validate_success(api.assign_appeal(appeal["id"], RM), 200)
        validate_success(api.decide_appeal(
            appeal["id"],
            {"outcome": "DENIED", "decision_rationale": "unfounded"},
            AUDITOR,
        ), 200)
        finalized = validate_success(
            api.finalize_wave(env["wave"]["id"], ADMIN), 200
        )
        assert finalized["status"] == "FINALIZED"
