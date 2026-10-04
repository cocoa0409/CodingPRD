"""Difficulty queue: transitive cascades and validation priority pairs."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, NON_EXISTENT_UUID,
    TEST_USERS, make_dealer_principal_headers,
    setup_dealer_env, create_tx, open_wave_and_get_invitations,
    send_invitation, respond, reset_clock, confirm_flag,
    create_draft_plan, create_statement,
    create_transaction_payload,
)

ADMIN = TEST_USERS["admin_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]


class TestFlagConfirmCascade:
    def test_third_confirmed_flag_cascades_to_suspension_and_plan_submit(self, api):
        """PRD §3.8: "A confirmation carries the system's heaviest cascade.
        If the flag's response_id is non-null and that response is currently
        SCORED, the response transitions to EXCLUDED with excluded_reason set
        to MANIPULATION_CONFIRMED. The dealer's confirmed_flag_count is
        recomputed — it counts CONFIRMED flags over the trailing two closed
        waves — and posture is re-derived against the new count and the
        current current_score_adjusted. If the new posture is SUSPENDED,
        every ActionPlan the dealer holds in DRAFT transitions to SUBMITTED,
        escalating remediation out of the principal's hands."
        PRD §3.6: "Otherwise, if confirmed_flag_count is at least three,
        posture is SUSPENDED."

        Design: Difficulty/transitive_cascade/flag_confirm_cascade_to_suspension_and_plans
        """
        env = setup_dealer_env(dealer_code="D7", customers=1)
        cust = env["customers"][0]
        dealer_id = env["dealer"]["id"]
        create_tx(env, cust, margin_cents=5000)
        invs = open_wave_and_get_invitations(env)
        send_invitation(invs[0]["id"])
        resp = respond(invs[0], cust, {"q1": 9})
        # Two dealer-level flags confirmed before close.
        confirm_flag(dealer_id, kind="COACHING", evidence="ev1")
        confirm_flag(dealer_id, kind="OPT_OUT_SUPPRESSION", evidence="ev2")
        # Draft plan while not suspended.
        plan = create_draft_plan(dealer_id, env["wave"]["id"], title="Remediate")
        assert plan["status"] == "DRAFT"
        # Close the wave so the dealer has a non-null score (posture ladder
        # requires a score); adjusted = 900 - 25*2 = 850, flags 2 -> PROBATION.
        reset_clock("2026-10-01T00:00:00Z")
        validate_success(api.close_wave(env["wave"]["id"], ADMIN), 200)
        dealer_mid = validate_success(api.get_dealer(dealer_id, ADMIN))
        assert dealer_mid["current_score_adjusted"] == 850.0
        assert dealer_mid["confirmed_flag_count"] == 2
        assert dealer_mid["posture"] == "PROBATION"
        # Third flag, linked to the still-SCORED response: confirm it.
        confirm_flag(
            dealer_id, kind="CONTACT_TAMPERING", evidence="ev3",
            response_id=resp["id"],
        )
        r_after = validate_success(api.get_response(resp["id"], ADMIN))
        assert r_after["status"] == "EXCLUDED"
        assert r_after["excluded_reason"] == "MANIPULATION_CONFIRMED"
        dealer_after = validate_success(api.get_dealer(dealer_id, ADMIN))
        assert dealer_after["confirmed_flag_count"] == 3
        assert dealer_after["posture"] == "SUSPENDED"
        plan_after = validate_success(api.get_action_plan(plan["id"], ADMIN))
        assert plan_after["status"] == "SUBMITTED", (
            "SUSPENDED cascades the dealer's DRAFT plans to SUBMITTED"
        )

    def test_flag_confirmation_degrades_posture_stepwise_mid_wave(self, api):
        """PRD §3.6: "The same derivation runs whenever a manipulation flag is
        confirmed, so a dealer's posture can degrade mid-wave — not just at
        close — and the resulting transitions are system-driven rather than
        user-initiated." and "Otherwise, if confirmed_flag_count is at least
        three, posture is SUSPENDED. Otherwise, if the count is at least two
        or the adjusted score is below seven hundred, posture is PROBATION.
        Otherwise, if the count is exactly one or the adjusted score is below
        eight hundred, posture is WATCH. Otherwise, the dealer is in
        GOOD_STANDING."

        Design: Difficulty/transitive_cascade/flag_confirm_cascade_to_suspension_and_plans
        """
        env = setup_dealer_env(dealer_code="D7b", customers=1)
        cust = env["customers"][0]
        dealer_id = env["dealer"]["id"]
        create_tx(env, cust, margin_cents=5000)
        invs = open_wave_and_get_invitations(env)
        send_invitation(invs[0]["id"])
        respond(invs[0], cust, {"q1": 9})
        reset_clock("2026-10-01T00:00:00Z")
        validate_success(api.close_wave(env["wave"]["id"], ADMIN), 200)
        dealer = validate_success(api.get_dealer(dealer_id, ADMIN))
        assert dealer["current_score_adjusted"] == 900.0
        assert dealer["posture"] == "GOOD_STANDING"
        confirm_flag(dealer_id, kind="COACHING", evidence="e1")
        dealer = validate_success(api.get_dealer(dealer_id, ADMIN))
        assert dealer["confirmed_flag_count"] == 1
        assert dealer["posture"] == "WATCH", "count exactly one -> WATCH"
        confirm_flag(dealer_id, kind="OPT_OUT_SUPPRESSION", evidence="e2")
        dealer = validate_success(api.get_dealer(dealer_id, ADMIN))
        assert dealer["confirmed_flag_count"] == 2
        assert dealer["posture"] == "PROBATION", "count at least two -> PROBATION"


class TestWaveCloseCascade:
    def test_close_expires_queued_and_derives_watch_posture(self, api):
        """PRD §3.4: "On close, four things happen. First, every invitation
        still in QUEUED or SENT transitions to EXPIRED, with queued_count and
        sent_count decrementing and expired_count incrementing by the number
        expired." and "Third, for every dealer with at least one transaction
        in the period, the system computes that wave's scores and response
        rate, writes them onto the dealer as current_score_adjusted and
        current_response_rate, and re-derives posture."
        PRD §3.6: "Otherwise, if the count is exactly one or the adjusted
        score is below eight hundred, posture is WATCH."

        Design: Difficulty/transitive_cascade/wave_close_cascade_to_dealer_posture_and_invitations
        """
        env = setup_dealer_env(dealer_code="D8", customers=2)
        ca, cb = env["customers"]
        create_tx(env, ca, margin_cents=10000, completed_at="2026-09-05T00:00:00Z")
        create_tx(env, cb, margin_cents=10000, completed_at="2026-09-06T00:00:00Z")
        invs = open_wave_and_get_invitations(env)
        assert len(invs) == 2
        by_cust = {inv["customer_id"]: inv for inv in invs}
        send_invitation(by_cust[ca["id"]]["id"])
        respond(by_cust[ca["id"]], ca, {"q1": 7})
        # second invitation stays QUEUED
        reset_clock("2026-10-01T00:00:00Z")
        wave = validate_success(api.close_wave(env["wave"]["id"], ADMIN), 200)
        assert wave["status"] == "CLOSED"
        inv_b = validate_success(api.get_invitation(by_cust[cb["id"]]["id"], ADMIN))
        assert inv_b["status"] == "EXPIRED"
        dealer = validate_success(api.get_dealer(env["dealer"]["id"], ADMIN))
        assert dealer["current_score_adjusted"] == 700.0, "raw 70*10 = 700"
        assert dealer["posture"] == "WATCH", "700 < 800 -> WATCH"

    def test_close_derives_probation_when_score_below_700(self, api):
        """PRD §3.6: "Otherwise, if the count is at least two or the adjusted
        score is below seven hundred, posture is PROBATION."
        PRD §3.4: "First, every invitation still in QUEUED or SENT
        transitions to EXPIRED, with queued_count and sent_count decrementing
        and expired_count incrementing by the number expired."

        Design: Difficulty/transitive_cascade/wave_close_cascade_to_dealer_posture_and_invitations
        """
        env = setup_dealer_env(dealer_code="D8b", customers=2)
        ca, cb = env["customers"]
        create_tx(env, ca, margin_cents=10000, completed_at="2026-09-05T00:00:00Z")
        create_tx(env, cb, margin_cents=10000, completed_at="2026-09-06T00:00:00Z")
        invs = open_wave_and_get_invitations(env)
        by_cust = {inv["customer_id"]: inv for inv in invs}
        send_invitation(by_cust[ca["id"]]["id"])
        respond(by_cust[ca["id"]], ca, {"q1": 6})  # 60 * 10 = 600
        reset_clock("2026-10-01T00:00:00Z")
        wave = validate_success(api.close_wave(env["wave"]["id"], ADMIN), 200)
        assert wave["expired_count"] == 1, "the QUEUED invitation expired"
        assert wave["responded_count"] == 1
        dealer = validate_success(api.get_dealer(env["dealer"]["id"], ADMIN))
        assert dealer["current_score_adjusted"] == 600.0
        assert dealer["posture"] == "PROBATION", "600 < 700 -> PROBATION"


class TestValidationPriorityPairs:
    def test_close_draft_wave_before_period_end_reports_invalid_state(self, api):
        """PRD §2.9: "The order below is authoritative — earlier checks mask
        later ones:" with "6. State validity — resource is in a from-state
        for the requested transition (ERR_INVALID_STATE)." listed before
        "9. Wave timing — close is not attempted before period_end
        (ERR_WAVE_STILL_OPEN)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_conflict_on_close
        """
        env = setup_dealer_env(dealer_code="D9", customers=0)
        reset_clock("2026-09-15T00:00:00Z")
        # Wave is DRAFT (state check fails) AND clock < period_end (temporal
        # check fails): the higher-priority state error must surface.
        err = api.close_wave(env["wave"]["id"], ADMIN)
        validate_error(err, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_close_open_wave_before_period_end_reports_wave_still_open(self, api):
        """PRD §3.4: "Closing the wave — OPEN → CLOSED — requires the logical
        clock to have reached period_end; an early attempt is rejected with
        ERR_WAVE_STILL_OPEN."
        PRD §2.9: "9. Wave timing — close is not attempted before period_end
        (ERR_WAVE_STILL_OPEN)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_conflict_on_close
        """
        env = setup_dealer_env(dealer_code="D9b", customers=0)
        validate_success(api.open_wave(env["wave"]["id"], ADMIN), 200)
        reset_clock("2026-09-15T00:00:00Z")
        # Wave IS open (state check passes); only the temporal check fails.
        err = api.close_wave(env["wave"]["id"], ADMIN)
        validate_error(err, ApiErrorId.ERR_WAVE_STILL_OPEN, expected_status=422)

    def test_missing_dealer_reports_not_found_before_cross_reference(self, api):
        """PRD §2.9: "The order below is authoritative — earlier checks mask
        later ones:" with "4. Existence — every referenced id resolves
        (ERR_NOT_FOUND)." listed before "5. Cross-reference consistency —
        department under dealer, advisor under department, appeal dealer
        matches caller (ERR_CROSS_REFERENCE_MISMATCH)."
        PRD §2.6: "The same discipline applies to body-referenced identifiers
        — a payload naming a non-existent dealer_id, wave_id,
        question_set_id, invitation_id, or response_id is rejected with
        ERR_NOT_FOUND before any business rule is evaluated."

        Design: Difficulty/priority_pair_validation_conflict/existence_vs_cross_reference_mismatch_conflict_on_transaction
        """
        env = setup_dealer_env(dealer_code="D10", customers=1)
        cust = env["customers"][0]
        # Non-existent dealer_id with an existing department (which belongs to
        # a different, real dealer): existence must win over cross-reference.
        payload = create_transaction_payload(
            NON_EXISTENT_UUID, env["dept"]["id"], cust["id"],
            completed_at="2026-09-05T00:00:00Z", margin_cents=1000,
        )
        err = api.create_transaction(payload, ADMIN)
        validate_error(err, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    def test_department_of_other_dealer_reports_cross_reference_mismatch(self, api):
        """PRD §2.6: "Recording a transaction whose department_id belongs to
        a different dealer than dealer_id, or whose advisor_id belongs to a
        different department than department_id, is rejected with
        ERR_CROSS_REFERENCE_MISMATCH (HTTP 422)."
        PRD §2.9: "5. Cross-reference consistency — department under dealer,
        advisor under department, appeal dealer matches caller
        (ERR_CROSS_REFERENCE_MISMATCH)."

        Design: Difficulty/priority_pair_validation_conflict/existence_vs_cross_reference_mismatch_conflict_on_transaction
        """
        env = setup_dealer_env(dealer_code="D10b", customers=1)
        cust = env["customers"][0]
        # A second dealer in the same region, with its own department.
        from test_helpers import setup_dealer, setup_department
        other = setup_dealer(env["region"]["id"], code="D10c")
        other_dept = setup_department(other["id"])
        payload = create_transaction_payload(
            env["dealer"]["id"], other_dept["id"], cust["id"],
            completed_at="2026-09-05T00:00:00Z", margin_cents=1000,
        )
        err = api.create_transaction(payload, ADMIN)
        validate_error(
            err, ApiErrorId.ERR_CROSS_REFERENCE_MISMATCH, expected_status=422
        )
