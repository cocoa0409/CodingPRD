"""Corner queue: state machine claims and read-side calculations."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS,
    reset_clock, setup_draft_question_set, setup_dealer_env,
    create_tx, open_wave_and_get_invitations, send_invitation, respond,
    find_invitation_for_transaction, file_appeal,
)

ADMIN = TEST_USERS["admin_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]
VENDOR = TEST_USERS["survey_vendor_headers"]


class TestStateMachines:
    def test_question_set_initial_state_draft(self, api):
        """PRD §3.2: "A question set begins life in DRAFT. Activation — a
        PlatformAdmin action — moves it to ACTIVE, but only if no other set
        is currently ACTIVE; the check fires with
        ERR_ACTIVE_QUESTION_SET_EXISTS when a singleton is violated."

        Design: Corner/state_machines/question_set_initial_state_draft
        """
        qs = validate_success(api.create_question_set(
            {
                "code": "QS-Z",
                "questions": [{"question_code": "q1", "prompt": "A", "weight": 1}],
                "comparability_factor": 1.0,
            },
            ADMIN,
        ), 201)
        assert qs["status"] == "DRAFT"

    def test_retired_question_set_cannot_be_reactivated(self, api):
        """PRD §3.2: "Retirement moves ACTIVE to RETIRED."
        PRD §2.9: "6. State validity — resource is in a from-state for the
        requested transition (ERR_INVALID_STATE)."

        Design: Corner/state_machines/question_set_retire_terminal_lockdown
        """
        reset_clock()
        qs = setup_draft_question_set(code="QS-Z")
        validate_success(api.activate_question_set(qs["id"], ADMIN), 200)
        validate_success(api.retire_question_set(qs["id"], ADMIN), 200)
        err = api.activate_question_set(qs["id"], ADMIN)
        validate_error(err, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_opted_out_invitation_cannot_be_sent(self, api):
        """PRD §3.5: "A customer may instead opt out. The opt-out action —
        available on invitations in either QUEUED or SENT, and guarded by the
        same X-User-ID ownership check — transitions the invitation to
        OPTED_OUT, decrements whichever of queued_count or sent_count
        applied, increments opted_out_count, and permanently flips the
        customer's do_not_contact to true."
        PRD §2.9: "6. State validity — resource is in a from-state for the
        requested transition (ERR_INVALID_STATE)."

        Design: Corner/state_machines/invitation_opt_out_terminal_lockdown
        """
        env = setup_dealer_env(dealer_code="A", customers=1)
        cust = env["customers"][0]
        create_tx(env, cust, margin_cents=100)
        invs = open_wave_and_get_invitations(env)
        from test_helpers import make_customer_headers
        validate_success(
            api.opt_out_invitation(invs[0]["id"],
                                   make_customer_headers(cust["id"])),
            200,
        )
        err = api.send_invitation(invs[0]["id"], VENDOR)
        validate_error(err, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_decide_filed_appeal_rejected(self, api):
        """PRD §3.7: "Routing the appeal to review is a RegionalManager
        action: assignment moves FILED → UNDER_REVIEW. Decision belongs to
        ComplianceAuditor, who supplies an outcome and a
        decision_rationale."
        PRD §2.9: "6. State validity — resource is in a from-state for the
        requested transition (ERR_INVALID_STATE)."

        Design: Corner/state_machines/appeal_invalid_from_filed_decide_rejected
        """
        env = setup_dealer_env(dealer_code="A", customers=1)
        cust = env["customers"][0]
        create_tx(env, cust, margin_cents=100)
        invs = open_wave_and_get_invitations(env)
        send_invitation(invs[0]["id"])
        resp = respond(invs[0], cust, {"q1": 5})
        appeal = file_appeal(env["dealer"]["id"], resp, reason="test")
        assert appeal["status"] == "FILED"
        err = api.decide_appeal(
            appeal["id"],
            {"outcome": "UPHELD", "decision_rationale": "x"},
            AUDITOR,
        )
        validate_error(err, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestCalculations:
    def test_benchmark_tied_dealers_share_rank(self, api):
        """PRD §3.11: "The target's rank is one plus the count of eligible
        peers whose adjusted score is strictly greater than the target's — so
        dealers tied on score share a rank. The percentile is one hundred
        times the quantity one minus the ratio of (rank minus one) to the
        eligible count, rounded half-up to two decimal places; when the
        target is the only eligible dealer, the count is treated as one so
        the percentile lands at 100.00 rather than dividing by zero."

        Design: Corner/calculations/regional_benchmark_tied_dealers_share_rank
        """
        reset_clock()
        from test_helpers import (
            setup_region, setup_dealer, setup_department, setup_customer,
            setup_active_question_set, setup_wave,
        )
        region = setup_region()
        dealers = {}
        depts = {}
        custs = {}
        for i, code in enumerate(("DA", "DB", "DC")):
            dealers[code] = setup_dealer(region["id"], code=code, name=code)
            depts[code] = setup_department(dealers[code]["id"])
            custs[code] = setup_customer(
                full_name=f"C{code}", email=f"c{code}@x.com",
                phone=f"5550100{i:03d}",
            )
        qs = setup_active_question_set()
        wave = setup_wave(qs["id"])
        score_by_code = {"DA": 10, "DB": 9, "DC": 9}
        for code in ("DA", "DB", "DC"):
            validate_success(api.create_transaction(
                {
                    "dealer_id": dealers[code]["id"],
                    "department_id": depts[code]["id"],
                    "customer_id": custs[code]["id"],
                    "kind": "SALE",
                    "completed_at": "2026-09-05T00:00:00Z",
                    "margin_cents": 100,
                },
                ADMIN,
            ), 201)
        validate_success(api.open_wave(wave["id"], ADMIN), 200)
        for code in ("DA", "DB", "DC"):
            txs = validate_success(api.list_transactions(
                ADMIN, params={"dealer_id": dealers[code]["id"]}
            ))
            inv = find_invitation_for_transaction(txs[0]["id"])
            send_invitation(inv["id"])
            respond(inv, custs[code], {"q1": score_by_code[code]})
        reset_clock("2026-10-01T00:00:00Z")
        validate_success(api.close_wave(wave["id"], ADMIN), 200)
        bench_db = validate_success(
            api.get_wave_benchmark(wave["id"], dealers["DB"]["id"], ADMIN)
        )
        assert bench_db["dealer_count"] == 3
        assert bench_db["dealer_rank"] == 2, "1 + 1 strictly-greater"
        assert bench_db["percentile"] == 66.67
        bench_dc = validate_success(
            api.get_wave_benchmark(wave["id"], dealers["DC"]["id"], ADMIN)
        )
        assert bench_dc["dealer_rank"] == 2, "tied with DB"
        assert bench_dc["percentile"] == 66.67
        bench_da = validate_success(
            api.get_wave_benchmark(wave["id"], dealers["DA"]["id"], ADMIN)
        )
        assert bench_da["dealer_rank"] == 1
        assert bench_da["percentile"] == 100.0

    def test_score_history_applies_each_waves_own_factor(self, api):
        """PRD §3.11: "For every prior wave in CLOSED or FINALIZED status
        with at least one SCORED response for the dealer, the history reports
        wave_id, the raw_score as computed under that wave's own question set
        on the 0–1000 scale, and a normalized_score equal to the raw score
        multiplied by that wave's question set's comparability_factor,
        rounded half-up to two decimal places. Crucially, the factor applied
        is the historical set's own — not the current set's — so a wave
        administered under a lenient instrument stays corrected by its own
        leniency factor even after the network has moved on."

        Design: Corner/calculations/score_history_comparability_uses_each_wave_own_factor
        """
        reset_clock()
        from test_helpers import (
            setup_region, setup_dealer, setup_department, setup_customer,
            setup_active_question_set, setup_draft_question_set, setup_wave,
        )
        region = setup_region()
        dealer = setup_dealer(region["id"], code="D", name="D")
        dept = setup_department(dealer["id"])
        c1 = setup_customer(full_name="C1", email="c1@x.com", phone="5550000001")
        c2 = setup_customer(full_name="C2", email="c2@x.com", phone="5550000002")

        qs_a = setup_active_question_set(code="QS-A", comparability_factor=1.0)
        w1 = setup_wave(qs_a["id"])
        validate_success(api.create_transaction(
            {
                "dealer_id": dealer["id"], "department_id": dept["id"],
                "customer_id": c1["id"], "kind": "SALE",
                "completed_at": "2026-09-05T00:00:00Z", "margin_cents": 100,
            },
            ADMIN,
        ), 201)
        validate_success(api.open_wave(w1["id"], ADMIN), 200)
        inv1s = validate_success(
            api.list_wave_invitations(w1["id"], ADMIN, params={"limit": 100})
        )
        send_invitation(inv1s[0]["id"])
        respond(inv1s[0], c1, {"q1": 9})  # raw 900
        reset_clock("2026-10-01T00:00:00Z")
        validate_success(api.close_wave(w1["id"], ADMIN), 200)
        validate_success(api.retire_question_set(qs_a["id"], ADMIN), 200)

        qs_b = setup_active_question_set(code="QS-B", comparability_factor=0.8)
        w2 = setup_wave(
            qs_b["id"],
            period_start="2026-10-01T00:00:00Z",
            period_end="2026-11-01T00:00:00Z",
        )
        validate_success(api.create_transaction(
            {
                "dealer_id": dealer["id"], "department_id": dept["id"],
                "customer_id": c2["id"], "kind": "SALE",
                "completed_at": "2026-10-05T00:00:00Z", "margin_cents": 100,
            },
            ADMIN,
        ), 201)
        validate_success(api.open_wave(w2["id"], ADMIN), 200)
        inv2s = validate_success(
            api.list_wave_invitations(w2["id"], ADMIN, params={"limit": 100})
        )
        send_invitation(inv2s[0]["id"])
        respond(inv2s[0], c2, {"q1": 8})  # raw 800
        reset_clock("2026-11-01T00:00:00Z")
        validate_success(api.close_wave(w2["id"], ADMIN), 200)

        history = validate_success(
            api.get_dealer_score_history(dealer["id"], ADMIN)
        )
        assert len(history) == 2
        by_wave = {entry["wave_id"]: entry for entry in history}
        assert by_wave[w1["id"]]["raw_score"] == 900.0
        assert by_wave[w1["id"]]["normalized_score"] == 900.0, "factor 1.0"
        assert by_wave[w2["id"]]["raw_score"] == 800.0
        assert by_wave[w2["id"]]["normalized_score"] == 640.0, (
            "factor 0.8 of W2's own question set, not the other's"
        )
