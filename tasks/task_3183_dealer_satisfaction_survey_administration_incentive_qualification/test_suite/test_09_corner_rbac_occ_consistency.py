"""Corner queue: RBAC denials, optimistic concurrency, lazy overdue,
immediate consistency."""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, ApiErrorId,
    TEST_USERS, make_dealer_principal_headers, make_customer_headers,
    reset_clock, setup_region, setup_dealer, setup_dealer_env,
    create_tx, open_wave_and_get_invitations, send_invitation, respond,
    file_appeal, create_statement, create_wave_payload,
    create_action_plan_payload,
)

ADMIN = TEST_USERS["admin_headers"]
RM = TEST_USERS["regional_manager_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]


class TestRbac:
    def test_customer_cannot_open_wave(self, api):
        """PRD §2.1: "A request whose role is authenticated but not permitted
        on the target endpoint is rejected with ERR_UNAUTHORIZED (HTTP 403)."
        PRD §4: "POST /survey/waves/{id}/open | Open wave; runs sampling
        sweep | PlatformAdmin".

        Design: Corner/rbac/customer_cannot_open_wave
        """
        env = setup_dealer_env(dealer_code="A", customers=1)
        cust = env["customers"][0]
        err = api.open_wave(
            env["wave"]["id"], make_customer_headers(cust["id"])
        )
        validate_error(err, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    def test_dealer_principal_cannot_decide_appeal(self, api):
        """PRD §2.1: "Segregation of duties is a load-bearing design choice."
        PRD §3.7: "Decision belongs to ComplianceAuditor, who supplies an
        outcome and a decision_rationale."
        PRD §4: "POST /survey/appeals/{id}/decide | Decide appeal (UPHELD or
        DENIED) | ComplianceAuditor".
        PRD §2.1: "A request whose role is authenticated but not permitted on
        the target endpoint is rejected with ERR_UNAUTHORIZED (HTTP 403)."

        Design: Corner/rbac/dealer_principal_cannot_decide_appeal
        """
        env = setup_dealer_env(dealer_code="A", customers=1)
        cust = env["customers"][0]
        dealer_id = env["dealer"]["id"]
        create_tx(env, cust, margin_cents=100)
        invs = open_wave_and_get_invitations(env)
        send_invitation(invs[0]["id"])
        resp = respond(invs[0], cust, {"q1": 5})
        appeal = file_appeal(dealer_id, resp, reason="r")
        validate_success(api.assign_appeal(appeal["id"], RM), 200)
        err = api.decide_appeal(
            appeal["id"],
            {"outcome": "UPHELD", "decision_rationale": "x"},
            make_dealer_principal_headers(dealer_id),
        )
        validate_error(err, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    def test_dealer_principal_forbidden_on_other_dealers_plan(self, api):
        """PRD §2.1: "A third failure mode, ERR_FORBIDDEN (HTTP 403), applies
        to entity-backed roles whose identity does not own the target
        resource — for example, a customer attempting to respond to someone
        else's invitation."
        PRD §3.9: "From DRAFT, the principal submits the plan for review —
        the transition is guarded by ownership (X-User-ID must equal the
        plan's dealer_id, failing with ERR_FORBIDDEN) and by posture".

        Design: Corner/rbac/dealer_principal_forbidden_on_other_dealers_plan
        """
        reset_clock()
        region = setup_region()
        dealer_a = setup_dealer(region["id"], code="A")
        dealer_b = setup_dealer(region["id"], code="B")
        env = setup_dealer_env(dealer_code="IGNORED", customers=0,
                               region=region)
        plan = validate_success(api.create_action_plan(
            create_action_plan_payload(dealer_a["id"], env["wave"]["id"]),
            make_dealer_principal_headers(dealer_a["id"]),
        ), 201)
        err = api.submit_action_plan(
            plan["id"], make_dealer_principal_headers(dealer_b["id"])
        )
        validate_error(err, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


class TestOptimisticConcurrency:
    def test_statement_create_with_stale_wave_version_rejected(self, api):
        """PRD §2.5: "A request to create an IncentiveStatement must carry
        expected_wave_version, set to the SurveyWave.version the client last
        observed. If another writer has since closed or finalized the wave —
        each of those transitions bumps the wave's version — the client's
        view is stale and the create is rejected with ERR_STALE_VERSION,
        forcing a re-read before the statement is computed against numbers
        the caller has actually seen."

        Design: Corner/cross_cutting_complexity_layers/occ_statement_create_with_stale_wave_version_rejected
        """
        env = setup_dealer_env(dealer_code="A", customers=1)
        cust = env["customers"][0]
        create_tx(env, cust, margin_cents=100)
        invs = open_wave_and_get_invitations(env)
        send_invitation(invs[0]["id"])
        respond(invs[0], cust, {"q1": 9})
        reset_clock("2026-10-01T00:00:00Z")
        validate_success(api.close_wave(env["wave"]["id"], ADMIN), 200)
        wave = validate_success(api.get_wave(env["wave"]["id"], ADMIN))
        stale_version = wave["version"] - 1
        err = api.create_statement(
            {
                "dealer_id": env["dealer"]["id"],
                "wave_id": env["wave"]["id"],
                "expected_wave_version": stale_version,
            },
            ADMIN,
        )
        validate_error(err, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    def test_appeal_create_with_stale_response_version_rejected(self, api):
        """PRD §2.5: "A request to file an Appeal must carry
        expected_response_version, matching the SurveyResponse.version the
        dealer last observed. A system cascade — a manipulation-flag
        confirmation or an invitation suppression — may have already excluded
        the response, advancing its version; the stale appeal attempt is
        rejected with ERR_STALE_VERSION so the caller re-reads the response
        before arguing against it."
        PRD §2.9: state validity (priority 6) masks OCC (priority 7). Because
        the flag-confirm cascade transitions the response out of SCORED, the
        second appeal attempt can surface either ERR_INVALID_STATE (state
        check fires first) or ERR_STALE_VERSION.

        Design: Corner/cross_cutting_complexity_layers/occ_appeal_create_with_stale_response_version_rejected
        """
        from test_helpers import confirm_flag
        env = setup_dealer_env(dealer_code="A", customers=1)
        cust = env["customers"][0]
        dealer_id = env["dealer"]["id"]
        create_tx(env, cust, margin_cents=100)
        invs = open_wave_and_get_invitations(env)
        send_invitation(invs[0]["id"])
        resp = respond(invs[0], cust, {"q1": 9})
        stale_version = resp["version"]
        # a confirmed flag on this response excludes it, advancing its version
        confirm_flag(dealer_id, kind="COACHING", evidence="e",
                     response_id=resp["id"])
        err = api.create_appeal(
            {
                "response_id": resp["id"],
                "reason": "r",
                "expected_response_version": stale_version,
            },
            make_dealer_principal_headers(dealer_id),
        )
        validate_error_is_one_of(
            err,
            [ApiErrorId.ERR_STALE_VERSION, ApiErrorId.ERR_INVALID_STATE],
        )

    def test_in_progress_plan_marked_overdue_lazily_on_read(self, api):
        """PRD §3.9: "The overdue rule is lazy. Whenever a plan in
        IN_PROGRESS is read, and whenever a wave closes, the system compares
        the current logical time to the plan's due_date; if the clock has
        reached or passed the due date, the plan transitions to OVERDUE.
        Clock advances trigger the same evaluation on next read, so an
        OVERDUE badge appears promptly without requiring a synchronous sweep
        at clock-set time."

        Design: Corner/cross_cutting_complexity_layers/lazy_overdue_action_plan_on_read
        """
        from test_helpers import setup_in_progress_plan
        env = setup_dealer_env(dealer_code="A", customers=0)
        dealer_id = env["dealer"]["id"]
        plan = setup_in_progress_plan(
            dealer_id, env["wave"]["id"], due_date="2026-09-15T00:00:00Z"
        )
        assert plan["status"] == "IN_PROGRESS"
        reset_clock("2026-09-20T00:00:00Z")
        after = validate_success(api.get_action_plan(plan["id"], ADMIN), 200)
        assert after["status"] == "OVERDUE"


class TestImmediateConsistency:
    def test_response_create_returns_computed_score_immediately(self, api):
        """PRD §3.5: "On success, a SurveyResponse is created in SCORED
        status with a computed score, a submitted_at stamped from the logical
        clock, and the invitation transitions SENT → RESPONDED — sent_count
        decrements, responded_count increments."
        PRD §3.5: "The response's score is a weighted mean scaled to the
        0–100 range."

        Design: Corner/consistency_model/response_create_returns_computed_score_immediately
        """
        env = setup_dealer_env(dealer_code="A", customers=1)
        cust = env["customers"][0]
        create_tx(env, cust, margin_cents=100)
        invs = open_wave_and_get_invitations(env)
        send_invitation(invs[0]["id"])
        resp = validate_success(api.submit_response(
            invs[0]["id"], {"answers": [{"question_code": "q1", "score": 7}]},
            make_customer_headers(cust["id"]),
        ), 201)
        # score is computed and returned in the SAME response envelope
        assert resp["score"] == 70.0
        assert resp["status"] == "SCORED"
