"""Difficulty queue: boundary precision, resource temporal overlap,
compensating invariants."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS, make_customer_headers,
    setup_dealer_env, setup_draft_question_set, setup_wave,
    send_invitation, respond, reset_clock, create_statement,
    assert_wave_partition_invariant, create_question_set_payload,
    list_wave_invitations, create_tx, open_wave_and_get_invitations,
)

ADMIN = TEST_USERS["admin_headers"]
VENDOR = TEST_USERS["survey_vendor_headers"]


class TestBoundaryPrecision:
    def test_response_at_exact_window_close_rejected(self, api):
        """PRD §3.5: "Submission requires the invitation to be in SENT; the
        logical clock must be strictly before window_closes_at, with the
        boundary exclusive — a submission exactly at window_closes_at is
        rejected with ERR_RESPONSE_WINDOW_CLOSED."

        Design: Difficulty/boundary_precision_check/response_window_exclusive_upper_bound
        """
        env = setup_dealer_env(dealer_code="D11", customers=1)
        cust = env["customers"][0]
        create_tx(env, cust, margin_cents=1000)
        invs = open_wave_and_get_invitations(env)
        reset_clock("2026-09-06T00:00:00Z")
        sent = send_invitation(invs[0]["id"])
        # window = sent_at + 14 days = 2026-09-20T00:00:00 UTC; PRD does not
        # pin the precise ISO8601 rendering, so compare the parsed value.
        from datetime import datetime, timezone
        parsed = datetime.fromisoformat(
            sent["window_closes_at"].replace("Z", "+00:00")
        )
        assert parsed == datetime(2026, 9, 20, tzinfo=timezone.utc)
        # advance the logical clock to exactly window_closes_at
        reset_clock("2026-09-20T00:00:00Z")
        err = api.submit_response(
            invs[0]["id"], {"answers": [{"question_code": "q1", "score": 5}]},
            make_customer_headers(cust["id"]),
        )
        validate_error(
            err, ApiErrorId.ERR_RESPONSE_WINDOW_CLOSED, expected_status=422
        )

    def test_response_one_second_before_window_close_accepted(self, api):
        """PRD §3.5: "Submission requires the invitation to be in SENT; the
        logical clock must be strictly before window_closes_at, with the
        boundary exclusive — a submission exactly at window_closes_at is
        rejected with ERR_RESPONSE_WINDOW_CLOSED."

        Design: Difficulty/boundary_precision_check/response_window_exclusive_upper_bound
        """
        env = setup_dealer_env(dealer_code="D11b", customers=1)
        cust = env["customers"][0]
        create_tx(env, cust, margin_cents=1000)
        invs = open_wave_and_get_invitations(env)
        reset_clock("2026-09-06T00:00:00Z")
        sent = send_invitation(invs[0]["id"])
        from datetime import datetime, timezone
        parsed = datetime.fromisoformat(
            sent["window_closes_at"].replace("Z", "+00:00")
        )
        assert parsed == datetime(2026, 9, 20, tzinfo=timezone.utc)
        # one second before the exclusive upper bound is still valid
        reset_clock("2026-09-19T23:59:59Z")
        resp = validate_success(api.submit_response(
            invs[0]["id"], {"answers": [{"question_code": "q1", "score": 5}]},
            make_customer_headers(cust["id"]),
        ), 201)
        assert resp["status"] == "SCORED"

    def test_score_exactly_900_lands_gold(self, api):
        """PRD §3.10: "Otherwise, tier selection by score: at least 900 earns
        GOLD; at least 800 but below 900 earns SILVER; at least 700 but
        below 800 earns BRONZE; below 700 is INELIGIBLE."

        Design: Difficulty/boundary_precision_check/incentive_score_threshold_exact_900_inclusive
        """
        env = setup_dealer_env(dealer_code="D12", customers=1)
        cust = env["customers"][0]
        create_tx(env, cust, margin_cents=100000)
        invs = open_wave_and_get_invitations(env)
        send_invitation(invs[0]["id"])
        respond(invs[0], cust, {"q1": 9})
        reset_clock("2026-10-01T00:00:00Z")
        validate_success(api.close_wave(env["wave"]["id"], ADMIN), 200)
        st = create_statement(env["dealer"]["id"], env["wave"]["id"])
        assert st["score_used"] == 900.0
        assert st["tier"] == "GOLD", "900 >= 900 is inclusive"
        assert st["payout_cents"] == 8000

    def test_score_850_lands_silver_below_gold_bound(self, api):
        """PRD §3.10: "Otherwise, tier selection by score: at least 900 earns
        GOLD; at least 800 but below 900 earns SILVER; at least 700 but
        below 800 earns BRONZE; below 700 is INELIGIBLE."

        Design: Difficulty/boundary_precision_check/incentive_score_threshold_exact_900_inclusive
        """
        env = setup_dealer_env(dealer_code="D12b", customers=2)
        ca, cb = env["customers"]
        create_tx(env, ca, margin_cents=50000, completed_at="2026-09-05T00:00:00Z")
        create_tx(env, cb, margin_cents=50000, completed_at="2026-09-06T00:00:00Z")
        invs = open_wave_and_get_invitations(env)
        by_cust = {inv["customer_id"]: inv for inv in invs}
        send_invitation(by_cust[ca["id"]]["id"])
        send_invitation(by_cust[cb["id"]]["id"])
        respond(by_cust[ca["id"]], ca, {"q1": 8})
        respond(by_cust[cb["id"]], cb, {"q1": 9})  # mean 85 -> 850
        reset_clock("2026-10-01T00:00:00Z")
        validate_success(api.close_wave(env["wave"]["id"], ADMIN), 200)
        st = create_statement(env["dealer"]["id"], env["wave"]["id"])
        assert st["score_used"] == 850.0
        assert st["tier"] == "SILVER", "850 is below the GOLD bound of 900"
        assert st["payout_cents"] == 5000, "100000 * 0.05 = 5000"


class TestResourceTemporalOverlap:
    def test_sampling_suppressed_when_prior_wave_invitation_in_window(self, api):
        """PRD §3.4: "For each dealer, the sweep collects transactions whose
        completed_at falls within the half-open period [period_start,
        period_end), whose customer's do_not_contact is false, and for which
        no other invitation already exists pairing the same customer_id and
        kind in any wave whose period overlaps the trailing ninety days — the
        contact-suppression rule that prevents a customer from being
        resurveyed on the same visit type within a quarter."

        Design: Difficulty/resource_temporal_overlap/sampling_90day_contact_suppression_window
        """
        env = setup_dealer_env(dealer_code="D15", customers=1)
        cust = env["customers"][0]
        wave_b = setup_wave(
            env["qs"]["id"],
            period_start="2026-10-01T00:00:00Z",
            period_end="2026-11-01T00:00:00Z",
        )
        create_tx(env, cust, completed_at="2026-09-10T00:00:00Z")
        validate_success(api.open_wave(env["wave"]["id"], ADMIN), 200)
        wave_a_after = validate_success(api.get_wave(env["wave"]["id"], ADMIN))
        assert wave_a_after["invitations_total"] == 1
        # same customer, same kind, next period (within trailing 90 days)
        create_tx(env, cust, completed_at="2026-10-15T00:00:00Z")
        wave_b_after = validate_success(api.open_wave(wave_b["id"], ADMIN), 200)
        assert wave_b_after["invitations_total"] == 0, (
            "contact suppression: customer invited in a wave whose period "
            "overlaps the trailing ninety days is skipped"
        )
        invs_b = list_wave_invitations(wave_b["id"])
        assert invs_b == []

    def test_second_activation_while_first_active_rejected(self, api):
        """PRD §3.2: "Activation — a PlatformAdmin action — moves it to
        ACTIVE, but only if no other set is currently ACTIVE; the check fires
        with ERR_ACTIVE_QUESTION_SET_EXISTS when a singleton is violated."

        Design: Difficulty/resource_temporal_overlap/question_set_active_singleton_overlap
        """
        setup_dealer_env(dealer_code="DZ", customers=0)  # QS-A ACTIVE
        qs2 = setup_draft_question_set(code="QS-O2")
        err = api.activate_question_set(qs2["id"], ADMIN)
        validate_error(
            err, ApiErrorId.ERR_ACTIVE_QUESTION_SET_EXISTS, expected_status=409
        )
        qs2_after = validate_success(api.get_question_set(qs2["id"], ADMIN))
        assert qs2_after["status"] == "DRAFT", "failed activation leaves DRAFT"

    def test_activation_after_retire_succeeds(self, api):
        """PRD §3.2: "Activation — a PlatformAdmin action — moves it to
        ACTIVE, but only if no other set is currently ACTIVE; the check fires
        with ERR_ACTIVE_QUESTION_SET_EXISTS when a singleton is violated.
        Retirement moves ACTIVE to RETIRED. At most one set is ever ACTIVE at
        a time, and that set is the one pinned to subsequently created waves."

        Design: Difficulty/resource_temporal_overlap/question_set_active_singleton_overlap
        """
        env = setup_dealer_env(dealer_code="DZ2", customers=0)  # QS-A ACTIVE
        validate_success(api.retire_question_set(env["qs"]["id"], ADMIN), 200)
        qs2 = setup_draft_question_set(code="QS-O3")
        activated = validate_success(
            api.activate_question_set(qs2["id"], ADMIN), 200
        )
        assert activated["status"] == "ACTIVE"


class TestCompensatingInvariant:
    def test_partition_invariant_holds_across_respond(self, api):
        """PRD §3.4: "The wave is born in DRAFT with all counters —
        invitations_total, queued_count, sent_count, responded_count,
        expired_count, opted_out_count, suppressed_count — at zero." and "Each
        selected transaction spawns a SurveyInvitation in QUEUED status, with
        customer_id and question_set_id copied from the transaction and the
        wave respectively; each creation increments the wave's
        invitations_total and queued_count by one."
        PRD §3.5: "On success, a SurveyResponse is created in SCORED status
        with a computed score, a submitted_at stamped from the logical clock,
        and the invitation transitions SENT → RESPONDED — sent_count
        decrements, responded_count increments."

        Design: Difficulty/compensating_invariant/wave_invitation_partition_invariant_under_respond
        """
        env = setup_dealer_env(dealer_code="D16", customers=1)
        cust = env["customers"][0]
        create_tx(env, cust, margin_cents=1000)
        invs = open_wave_and_get_invitations(env)
        wave = validate_success(api.get_wave(env["wave"]["id"], ADMIN))
        assert wave["invitations_total"] == 1
        assert wave["queued_count"] == 1
        assert_wave_partition_invariant(wave)
        send_invitation(invs[0]["id"])
        wave = validate_success(api.get_wave(env["wave"]["id"], ADMIN))
        assert (wave["queued_count"], wave["sent_count"]) == (0, 1)
        assert_wave_partition_invariant(wave)
        respond(invs[0], cust, {"q1": 8})
        wave = validate_success(api.get_wave(env["wave"]["id"], ADMIN))
        assert wave["invitations_total"] == 1
        assert wave["queued_count"] == 0
        assert wave["sent_count"] == 0
        assert wave["responded_count"] == 1
        assert wave["expired_count"] == 0
        assert wave["opted_out_count"] == 0
        assert wave["suppressed_count"] == 0
        assert_wave_partition_invariant(wave)

    def test_partition_invariant_holds_across_close_expiry(self, api):
        """PRD §3.4: "First, every invitation still in QUEUED or SENT
        transitions to EXPIRED, with queued_count and sent_count decrementing
        and expired_count incrementing by the number expired." and "Each
        selected transaction spawns a SurveyInvitation in QUEUED status, with
        customer_id and question_set_id copied from the transaction and the
        wave respectively; each creation increments the wave's
        invitations_total and queued_count by one."

        Design: Difficulty/compensating_invariant/wave_invitation_partition_invariant_under_respond
        """
        env = setup_dealer_env(dealer_code="D16b", customers=2)
        ca, cb = env["customers"]
        create_tx(env, ca, margin_cents=1000, completed_at="2026-09-05T00:00:00Z")
        create_tx(env, cb, margin_cents=1000, completed_at="2026-09-06T00:00:00Z")
        invs = open_wave_and_get_invitations(env)
        by_cust = {inv["customer_id"]: inv for inv in invs}
        send_invitation(by_cust[ca["id"]]["id"])
        respond(by_cust[ca["id"]], ca, {"q1": 8})
        reset_clock("2026-10-01T00:00:00Z")
        wave = validate_success(api.close_wave(env["wave"]["id"], ADMIN), 200)
        assert wave["invitations_total"] == 2
        assert wave["responded_count"] == 1
        assert wave["expired_count"] == 1
        assert_wave_partition_invariant(wave)

    def test_statement_supersede_keeps_single_provisional(self, api):
        """PRD §3.10: "If a prior PROVISIONAL statement already exists for
        the same (dealer_id, wave_id), creating the new one supersedes the
        old: the old statement transitions to SUPERSEDED, and the new
        statement's supersedes_id points back at it."

        Design: Difficulty/compensating_invariant/statement_supersede_chain_conserves_active_provisional_count
        """
        env = setup_dealer_env(dealer_code="D17", customers=1)
        cust = env["customers"][0]
        create_tx(env, cust, margin_cents=100000)
        invs = open_wave_and_get_invitations(env)
        send_invitation(invs[0]["id"])
        respond(invs[0], cust, {"q1": 9})
        reset_clock("2026-10-01T00:00:00Z")
        validate_success(api.close_wave(env["wave"]["id"], ADMIN), 200)
        st1 = create_statement(env["dealer"]["id"], env["wave"]["id"])
        assert st1["status"] == "PROVISIONAL"
        st2 = create_statement(env["dealer"]["id"], env["wave"]["id"])
        st1_after = validate_success(api.get_statement(st1["id"], ADMIN))
        st2_after = validate_success(api.get_statement(st2["id"], ADMIN))
        assert st1_after["status"] == "SUPERSEDED"
        assert st2_after["status"] == "PROVISIONAL"
        assert st2_after["supersedes_id"] == st1["id"]
        listed = validate_success(api.list_dealer_statements(
            env["dealer"]["id"], ADMIN, params={"status": "PROVISIONAL"}
        ))
        assert len(listed) == 1, (
            "exactly one PROVISIONAL statement per (dealer, wave) survives"
        )

    def test_third_statement_supersedes_second_chain_links(self, api):
        """PRD §3.10: "If a prior PROVISIONAL statement already exists for
        the same (dealer_id, wave_id), creating the new one supersedes the
        old: the old statement transitions to SUPERSEDED, and the new
        statement's supersedes_id points back at it."

        Design: Difficulty/compensating_invariant/statement_supersede_chain_conserves_active_provisional_count
        """
        env = setup_dealer_env(dealer_code="D17b", customers=1)
        cust = env["customers"][0]
        create_tx(env, cust, margin_cents=100000)
        invs = open_wave_and_get_invitations(env)
        send_invitation(invs[0]["id"])
        respond(invs[0], cust, {"q1": 9})
        reset_clock("2026-10-01T00:00:00Z")
        validate_success(api.close_wave(env["wave"]["id"], ADMIN), 200)
        st1 = create_statement(env["dealer"]["id"], env["wave"]["id"])
        st2 = create_statement(env["dealer"]["id"], env["wave"]["id"])
        st3 = create_statement(env["dealer"]["id"], env["wave"]["id"])
        assert validate_success(api.get_statement(st1["id"], ADMIN))["status"] == "SUPERSEDED"
        st2_after = validate_success(api.get_statement(st2["id"], ADMIN))
        assert st2_after["status"] == "SUPERSEDED"
        st3_after = validate_success(api.get_statement(st3["id"], ADMIN))
        assert st3_after["status"] == "PROVISIONAL"
        assert st3_after["supersedes_id"] == st2["id"], (
            "each restatement points back at the statement it superseded"
        )
