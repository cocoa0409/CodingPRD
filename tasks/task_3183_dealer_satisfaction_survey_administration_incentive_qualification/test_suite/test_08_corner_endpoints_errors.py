"""Corner queue: endpoint-conditional actions and remaining error gates."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    TEST_USERS, make_customer_headers,
    reset_clock, setup_draft_question_set, setup_dealer_env,
    create_tx, open_wave_and_get_invitations, send_invitation, respond,
    create_wave_payload, create_statement, find_invitation_for_transaction,
)

ADMIN = TEST_USERS["admin_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]


class TestEndpointConditions:
    def test_open_wave_with_draft_question_set_rejected(self, api):
        """PRD §3.4: "The transition DRAFT → OPEN requires the pinned
        question set to be ACTIVE; otherwise the request fails with
        ERR_QUESTION_SET_NOT_ACTIVE."

        Design: Corner/endpoints/wave_open_requires_active_question_set
        """
        qs = setup_draft_question_set(code="QS-D")
        wave = validate_success(api.create_wave(
            create_wave_payload(qs["id"]), ADMIN,
        ), 201)
        err = api.open_wave(wave["id"], ADMIN)
        validate_error(
            err, ApiErrorId.ERR_QUESTION_SET_NOT_ACTIVE, expected_status=409
        )

    def test_pay_provisional_statement_rejected(self, api):
        """PRD §3.10: "A statement is born PROVISIONAL." and "At wave
        finalize, every PROVISIONAL statement for the wave promotes to FINAL.
        A PlatformAdmin may then mark a FINAL statement paid, transitioning
        it to PAID. PAID and SUPERSEDED are the terminal states; there is no
        path back."
        PRD §2.9: "6. State validity — resource is in a from-state for the
        requested transition (ERR_INVALID_STATE)."

        Design: Corner/endpoints/statement_pay_from_provisional_rejected
        """
        env = setup_dealer_env(dealer_code="A", customers=1)
        cust = env["customers"][0]
        create_tx(env, cust, margin_cents=100)
        invs = open_wave_and_get_invitations(env)
        send_invitation(invs[0]["id"])
        respond(invs[0], cust, {"q1": 9})
        reset_clock("2026-10-01T00:00:00Z")
        validate_success(api.close_wave(env["wave"]["id"], ADMIN), 200)
        st = create_statement(env["dealer"]["id"], env["wave"]["id"])
        assert st["status"] == "PROVISIONAL"
        err = api.pay_statement(st["id"], ADMIN)
        validate_error(err, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_wave_invitations_status_filter_interacts_with_pagination(self, api):
        """PRD §3.5: "An invitation's lifecycle begins in QUEUED. A
        SurveyVendor sends it — the transition QUEUED → SENT."
        PRD §4: "GET /survey/waves/{id}/invitations | List invitations in a
        wave, filterable by status".
        PRD §2.3: "The meta block of a paginated response carries limit,
        offset, total_count, and has_more, where has_more is true when the
        requested window does not exhaust the underlying collection."

        Design: Corner/endpoints/list_invitations_filter_by_status
        """
        env = setup_dealer_env(dealer_code="A", customers=3)
        c1, c2, c3 = env["customers"]
        create_tx(env, c1, margin_cents=100, completed_at="2026-09-05T00:00:00Z")
        create_tx(env, c2, margin_cents=100, completed_at="2026-09-06T00:00:00Z")
        create_tx(env, c3, margin_cents=100, completed_at="2026-09-07T00:00:00Z")
        invs = open_wave_and_get_invitations(env)
        assert len(invs) == 3
        send_invitation(invs[0]["id"])
        wave_id = env["wave"]["id"]
        queued, meta_q = validate_paginated(api.list_wave_invitations(
            wave_id, ADMIN, params={"status": "QUEUED", "limit": 100}
        ))
        sent, meta_s = validate_paginated(api.list_wave_invitations(
            wave_id, ADMIN, params={"status": "SENT", "limit": 100}
        ))
        assert len(queued) == 2 and meta_q["total_count"] == 2
        assert len(sent) == 1 and meta_s["total_count"] == 1
        assert all(i["status"] == "QUEUED" for i in queued)
        assert all(i["status"] == "SENT" for i in sent)

    def test_opt_out_flips_customer_do_not_contact(self, api):
        """PRD §3.5: "A customer may instead opt out. The opt-out action —
        available on invitations in either QUEUED or SENT, and guarded by the
        same X-User-ID ownership check — transitions the invitation to
        OPTED_OUT, decrements whichever of queued_count or sent_count
        applied, increments opted_out_count, and permanently flips the
        customer's do_not_contact to true."

        Design: Corner/endpoints/opt_out_flips_customer_do_not_contact
        """
        env = setup_dealer_env(dealer_code="A", customers=1)
        cust = env["customers"][0]
        create_tx(env, cust, margin_cents=100)
        invs = open_wave_and_get_invitations(env)
        result = validate_success(api.opt_out_invitation(
            invs[0]["id"], make_customer_headers(cust["id"])
        ), 200)
        assert result["status"] == "OPTED_OUT"
        cust_after = validate_success(api.get_customer(cust["id"], ADMIN), 200)
        assert cust_after["do_not_contact"] is True


class TestErrorGates:
    def test_finalize_blocked_by_open_flag(self, api):
        """PRD §3.4: "It is blocked when any appeal on a response belonging
        to this wave is still in FILED or UNDER_REVIEW (the rejection is
        ERR_APPEALS_PENDING), and independently blocked when any manipulation
        flag on a dealer with invitations in this wave is still OPEN (the
        rejection is ERR_FLAGS_PENDING)."

        Design: Corner/errors/err_flags_pending_blocks_finalize
        """
        env = setup_dealer_env(dealer_code="A", customers=1)
        cust = env["customers"][0]
        create_tx(env, cust, margin_cents=100)
        invs = open_wave_and_get_invitations(env)
        send_invitation(invs[0]["id"])
        respond(invs[0], cust, {"q1": 9})
        reset_clock("2026-10-01T00:00:00Z")
        validate_success(api.close_wave(env["wave"]["id"], ADMIN), 200)
        # open a flag but leave it OPEN
        validate_success(api.create_flag(
            {
                "dealer_id": env["dealer"]["id"],
                "kind": "COACHING",
                "evidence": "e",
            },
            AUDITOR,
        ), 201)
        err = api.finalize_wave(env["wave"]["id"], ADMIN)
        validate_error(err, ApiErrorId.ERR_FLAGS_PENDING, expected_status=409)

    def test_send_blocked_when_customer_opted_out_after_queueing(self, api):
        """PRD §3.5: "the transition QUEUED → SENT — which requires two
        preconditions evaluated in priority order: the owning wave must be
        OPEN (otherwise ERR_WAVE_NOT_OPEN), and the customer's do_not_contact
        must still be false (otherwise ERR_CONTACT_RESTRICTED). The second
        check exists because a customer may have opted out through another
        channel after the invitation was queued; send-time re-evaluation is
        the safety net."

        Design: Corner/errors/err_contact_restricted_blocks_send_when_do_not_contact_true
        """
        from test_helpers import setup_department
        env = setup_dealer_env(dealer_code="A", customers=1)
        cust = env["customers"][0]
        dept_v = setup_department(env["dealer"]["id"], kind="SERVICE",
                                  name="Svc")
        tx_sale = create_tx(env, cust, kind="SALE",
                            completed_at="2026-09-05T00:00:00Z",
                            margin_cents=100)
        tx_serv = create_tx(env, cust, kind="SERVICE_VISIT",
                            completed_at="2026-09-06T00:00:00Z",
                            margin_cents=50, department=dept_v)
        validate_success(api.open_wave(env["wave"]["id"], ADMIN), 200)
        inv_sale = find_invitation_for_transaction(tx_sale["id"])
        inv_serv = find_invitation_for_transaction(tx_serv["id"])
        # customer opts out of the SALE invitation, flipping do_not_contact
        validate_success(api.opt_out_invitation(
            inv_sale["id"], make_customer_headers(cust["id"])
        ), 200)
        err = api.send_invitation(
            inv_serv["id"], TEST_USERS["survey_vendor_headers"]
        )
        validate_error(err, ApiErrorId.ERR_CONTACT_RESTRICTED,
                       expected_status=422)
