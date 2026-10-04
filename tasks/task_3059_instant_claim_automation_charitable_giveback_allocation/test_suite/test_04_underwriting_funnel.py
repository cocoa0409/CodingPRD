"""Behavioral scoring, quote expiry, binding, and the application funnel."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_application,
    create_bind_payload,
    create_cause_and_cohort,
    create_policyholder,
    create_quote,
    get_policyholder,
    make_policyholder_headers,
    pay_premium,
    set_clock,
    setup_state_fee,
    setup_bound_policy,
    validate_error,
    validate_paginated,
    validate_success,
    deny_claims_with_fraud,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UNDERWRITER = TEST_USERS["underwriting_admin_headers"]
FINANCE = TEST_USERS["finance_ops_headers"]


def _tx_stack(cohort_year=2026):
    set_clock()
    cause, cohort = create_cause_and_cohort(cohort_year)
    setup_state_fee(state_code="TX")
    return cause, cohort


class TestBehavioralScoring:
    def test_velocity_exactly_8_is_not_a_signal(self, api):
        """PRD §3.4: "one if the checkout velocity is strictly under 8 seconds (exactly 8 seconds is not a signal)".

        Design: Corner/calculations/behavioral_signal_count_velocity_exactly_8_is_not_a_signal
        """
        _tx_stack()
        ph8 = create_policyholder(state_code="TX", email="p8@x.com")
        q8 = create_quote(ph8["id"], 100000, 50000)
        app8 = validate_success(
            api.create_application(
                {
                    "quote_id": q8["id"],
                    "checkout_velocity_seconds": 8,
                    "device_reuse_count": 0,
                    "answers_ipa_acknowledged": True,
                },
                make_policyholder_headers(ph8["id"]),
            ),
            expected_status=201,
        )
        assert app8["behavioral_signal_count"] == 0
        assert app8["status"] == "UNDER_REVIEW"

    def test_velocity_7_is_a_soft_signal(self, api):
        """PRD §3.4: "If exactly one signal fired, the application stays UNDER_REVIEW but is soft-flagged: an UnderwritingAdmin may still approve it manually".

        Design: Corner/calculations/behavioral_signal_count_velocity_exactly_8_is_not_a_signal
        """
        _tx_stack()
        ph7 = create_policyholder(state_code="TX", email="p7@x.com")
        q7 = create_quote(ph7["id"], 100000, 50000)
        app7 = validate_success(
            api.create_application(
                {
                    "quote_id": q7["id"],
                    "checkout_velocity_seconds": 7,
                    "device_reuse_count": 0,
                    "answers_ipa_acknowledged": True,
                },
                make_policyholder_headers(ph7["id"]),
            ),
            expected_status=201,
        )
        assert app7["behavioral_signal_count"] == 1
        assert app7["status"] == "UNDER_REVIEW"

    def test_two_signals_auto_decline_at_submission(self, api):
        """PRD §3.4: "Otherwise, if the signal count is at least 2, the application is created and immediately lands in DECLINED — the hard threshold forbids manual approval of such an application."
        PRD §3.4: "Declining an UNDER_REVIEW application moves it to DECLINED; the quote stays OPEN and may be applied against again until it expires."

        Design: Corner/calculations/behavioral_hard_threshold_two_signals_auto_declines
        """
        _tx_stack()
        ph = create_policyholder(state_code="TX")
        quote = create_quote(ph["id"], 100000, 50000)
        app = validate_success(
            api.create_application(
                {
                    "quote_id": quote["id"],
                    "checkout_velocity_seconds": 5,
                    "device_reuse_count": 2,
                    "answers_ipa_acknowledged": True,
                },
                make_policyholder_headers(ph["id"]),
            ),
            expected_status=201,
        )
        assert app["behavioral_signal_count"] == 2
        assert app["status"] == "DECLINED"
        quote_after = validate_success(api.get_quote(quote["id"], UNDERWRITER))
        assert quote_after["status"] == "OPEN"


class TestQuoteExpiry:
    def test_application_one_second_before_expiry_accepted(self, api):
        """PRD §3.4: "If the logical clock passes expires_at while the quote is still OPEN, the quote transitions to EXPIRED, and any later application submitted against it fails with ERR_QUOTE_EXPIRED."
        PRD §2.7: "A PlatformAdmin advances it by supplying a to_iso8601 instant".

        Design: Difficulty/resource_temporal_overlap/quote_expiry_interval_half_open_at_expires_at
        """
        _tx_stack()
        ph = create_policyholder(state_code="MT", email="p@x.com")
        # MT fee config so the setup would be bindable if needed.
        setup_state_fee(state_code="MT")
        quote = create_quote(ph["id"], 100000, 50000)
        set_clock("2026-09-30T23:59:59Z")
        app = validate_success(
            api.create_application(
                {
                    "quote_id": quote["id"],
                    "checkout_velocity_seconds": 60,
                    "device_reuse_count": 0,
                    "answers_ipa_acknowledged": True,
                },
                make_policyholder_headers(ph["id"]),
            ),
            expected_status=201,
        )
        assert app["status"] == "UNDER_REVIEW"

    def test_application_exactly_at_expiry_still_accepted(self, api):
        """PRD §3.4: "If the logical clock passes expires_at while the quote is still OPEN, the quote transitions to EXPIRED, and any later application submitted against it fails with ERR_QUOTE_EXPIRED."
        At exactly expires_at the clock has not yet passed the deadline, so the quote is still OPEN and the application succeeds.

        Design: Difficulty/resource_temporal_overlap/quote_expiry_interval_half_open_at_expires_at
        """
        _tx_stack()
        setup_state_fee(state_code="MT")
        ph = create_policyholder(state_code="MT", email="q@x.com")
        quote = create_quote(ph["id"], 100000, 50000)
        set_clock("2026-10-01T00:00:00Z")
        app = validate_success(
            api.create_application(
                {
                    "quote_id": quote["id"],
                    "checkout_velocity_seconds": 60,
                    "device_reuse_count": 0,
                    "answers_ipa_acknowledged": True,
                },
                make_policyholder_headers(ph["id"]),
            ),
            expected_status=201,
        )
        assert app["status"] == "UNDER_REVIEW"
        quote_after = validate_success(api.get_quote(quote["id"], UNDERWRITER))
        assert quote_after["status"] == "OPEN"

    def test_application_one_second_after_expiry_rejected(self, api):
        """PRD §3.4: "If the logical clock passes expires_at while the quote is still OPEN, the quote transitions to EXPIRED, and any later application submitted against it fails with ERR_QUOTE_EXPIRED."

        Design: Difficulty/resource_temporal_overlap/quote_expiry_interval_half_open_at_expires_at
        """
        _tx_stack()
        setup_state_fee(state_code="MT")
        ph = create_policyholder(state_code="MT", email="r@x.com")
        quote = create_quote(ph["id"], 100000, 50000)
        set_clock("2026-10-01T00:00:01Z")
        resp = api.create_application(
            {
                "quote_id": quote["id"],
                "checkout_velocity_seconds": 60,
                "device_reuse_count": 0,
                "answers_ipa_acknowledged": True,
            },
            make_policyholder_headers(ph["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_QUOTE_EXPIRED)
        quote_after = validate_success(api.get_quote(quote["id"], UNDERWRITER))
        assert quote_after["status"] == "EXPIRED"


class TestStraightThroughBind:
    def test_bind_zero_signals_creates_policy(self, api):
        """PRD §3.4: "When zero signals fire and the quote has not expired, the quote transitions OPEN → BOUND and a Policy is created in one step, exactly as a manual approval would create it, with fraud_flag false."

        Design: Corner/endpoints/quote_bind_straight_through_creates_policy
        """
        _tx_stack()
        ph = create_policyholder(state_code="TX")
        quote = create_quote(ph["id"], 500000, 100000)
        policy = validate_success(
            api.bind_quote(quote["id"], create_bind_payload(), make_policyholder_headers(ph["id"])),
            expected_status=201,
        )
        assert policy["fraud_flag"] is False
        assert policy["status"] == "ACTIVE"
        assert policy["annual_premium_cents"] == 100000
        quote_after = validate_success(api.get_quote(quote["id"], UNDERWRITER))
        assert quote_after["status"] == "BOUND"

    def test_bind_with_any_signal_rejected(self, api):
        """PRD §3.4: "When any signal fires on this path, the request is rejected with ERR_APPLICATION_AUTO_DECLINE_REQUIRED and no application row is created — the conversational bind is only for the demonstrably clean."

        Design: Corner/endpoints/quote_bind_with_any_signal_rejected
        """
        _tx_stack()
        ph = create_policyholder(state_code="TX")
        quote = create_quote(ph["id"], 500000, 100000)
        resp = api.bind_quote(
            quote["id"],
            create_bind_payload(checkout_velocity_seconds=5),
            make_policyholder_headers(ph["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_APPLICATION_AUTO_DECLINE_REQUIRED)
        quote_after = validate_success(api.get_quote(quote["id"], UNDERWRITER))
        assert quote_after["status"] == "OPEN"
        policies, _meta = validate_paginated(
            api.list_policyholder_policies(ph["id"], UNDERWRITER)
        )
        assert policies == []


class TestBindPrerequisites:
    def test_bind_without_open_cohort_rejected(self, api):
        """PRD §3.4: "its cohort_id resolves to the unique OPEN cohort whose cohort_year equals the bind year (if none exists, the approval fails with ERR_COHORT_NOT_OPEN)".

        Design: Corner/validations/bind_without_open_cohort_rejected
        """
        set_clock()
        setup_state_fee(state_code="TX")
        ph = create_policyholder(state_code="TX")
        quote = create_quote(ph["id"], 500000, 50000)
        app = create_application(ph["id"], quote["id"])
        resp = api.approve_application(app["id"], UNDERWRITER)
        validate_error(resp, ApiErrorId.ERR_COHORT_NOT_OPEN)
        app_after = validate_success(api.get_application(app["id"], UNDERWRITER))
        assert app_after["status"] == "UNDER_REVIEW"


class TestResubmit:
    def test_resubmit_reopens_declined_application(self, api):
        """PRD §3.4: "The policyholder may resubmit a DECLINED application with corrected behavioral answers — fresh checkout_velocity_seconds, device_reuse_count, and answers_ipa_acknowledged values. The signal count is recomputed from the new answers; if the recomputed count reaches the hard threshold of 2 the application stays DECLINED, otherwise it returns to UNDER_REVIEW."

        Design: Corner/endpoints/application_resubmit_reopens_declined_application
        """
        _tx_stack()
        ph = create_policyholder(state_code="TX")
        quote = create_quote(ph["id"], 500000, 100000)
        app = create_application(
            ph["id"], quote["id"], checkout_velocity_seconds=5
        )
        validate_success(api.decline_application(app["id"], UNDERWRITER))
        resubmitted = validate_success(
            api.resubmit_application(
                app["id"],
                {
                    "checkout_velocity_seconds": 45,
                    "device_reuse_count": 0,
                    "answers_ipa_acknowledged": True,
                },
                make_policyholder_headers(ph["id"]),
            )
        )
        assert resubmitted["status"] == "UNDER_REVIEW"
        assert resubmitted["behavioral_signal_count"] == 0
        quote_after = validate_success(api.get_quote(quote["id"], UNDERWRITER))
        assert quote_after["status"] == "OPEN"


class TestDebarment:
    def _setup_debarred_policyholder(self, api):
        """Standard TX stack; policy bound, premium paid, 3 FRAUD denials."""
        ctx = setup_bound_policy(state_code="TX", premium_cents=50000)
        pay_premium(ctx["policy"]["id"], 50000)
        ph = ctx["policyholder"]
        deny_claims_with_fraud(ph["id"], ctx["policy"]["id"], 3)
        return ctx

    def test_debarred_policyholder_submission_rejected(self, api):
        """PRD §3.4: "If the policyholder's fraud_strike_count has reached 3, the submission is rejected outright with ERR_POLICYHOLDER_DEBARRED and no application row is created — a DEBARRED policyholder cannot apply at all."

        Design: Corner/validations/debarred_policyholder_submission_rejected
        """
        ctx = self._setup_debarred_policyholder(api)
        ph = ctx["policyholder"]
        ph_after = get_policyholder(ph["id"])
        assert ph_after["status"] == "DEBARRED"
        quote2 = create_quote(ph["id"], 500000, 50000)
        resp = api.create_application(
            {
                "quote_id": quote2["id"],
                "checkout_velocity_seconds": 60,
                "device_reuse_count": 0,
                "answers_ipa_acknowledged": True,
            },
            make_policyholder_headers(ph["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_POLICYHOLDER_DEBARRED)

    def test_third_fraud_denial_cascades_debarment_and_auto_decline(self, api):
        """PRD §3.8: "A fraud denial carries a further consequence: the policyholder's fraud_strike_count increments by one, and when the count reaches 3 the policyholder's status becomes DEBARRED and every still-UNDER_REVIEW application belonging to that policyholder auto-transitions to DECLINED in the same request."

        Design: Difficulty/transitive_cascade/fraud_denial_cascades_strike_debar_auto_decline
        """
        ctx = setup_bound_policy(state_code="NH", premium_cents=50000)
        pay_premium(ctx["policy"]["id"], 50000)
        ph = ctx["policyholder"]
        # First two FRAUD denials.
        deny_claims_with_fraud(ph["id"], ctx["policy"]["id"], 2)
        # A second pending application for the same policyholder.
        quote2 = create_quote(ph["id"], 500000, 50000)
        app2 = create_application(ph["id"], quote2["id"])
        # The third strike: file + deny with FRAUD.
        third = deny_claims_with_fraud(ph["id"], ctx["policy"]["id"], 1)[0]
        ph_after = get_policyholder(ph["id"])
        assert ph_after["fraud_strike_count"] == 3
        assert ph_after["status"] == "DEBARRED"
        app2_after = validate_success(api.get_application(app2["id"], UNDERWRITER))
        assert app2_after["status"] == "DECLINED"
        third_after = validate_success(api.get_claim(third["id"], TEST_USERS["adjuster_1_headers"]))
        assert third_after["status"] == "DENIED"
        assert third_after["denial_reason"] == "FRAUD"

    def test_strike_count_tracks_fraud_denials_incrementally(self, api):
        """PRD §3.8: "A fraud denial carries a further consequence: the policyholder's fraud_strike_count increments by one, and when the count reaches 3 the policyholder's status becomes DEBARRED".
        PRD §3.8: "The strike count is precisely the number of that policyholder's claims denied with reason FRAUD."

        Design: Difficulty/transitive_cascade/fraud_denial_cascades_strike_debar_auto_decline
        """
        ctx = setup_bound_policy(state_code="NH", premium_cents=50000)
        pay_premium(ctx["policy"]["id"], 50000)
        ph = ctx["policyholder"]
        deny_claims_with_fraud(ph["id"], ctx["policy"]["id"], 2)
        ph_after = get_policyholder(ph["id"])
        assert ph_after["fraud_strike_count"] == 2
        assert ph_after["status"] == "ACTIVE"
        deny_claims_with_fraud(ph["id"], ctx["policy"]["id"], 1)
        ph_final = get_policyholder(ph["id"])
        assert ph_final["fraud_strike_count"] == 3
        assert ph_final["status"] == "DEBARRED"

    def test_approve_rejected_after_debarment_cascade(self, api):
        """PRD §3.8: "when the count reaches 3 the policyholder's status becomes DEBARRED and every still-UNDER_REVIEW application belonging to that policyholder auto-transitions to DECLINED in the same request."
        PRD §3.4: "the application must be UNDER_REVIEW (otherwise ERR_INVALID_STATE)".

        Design: Difficulty/cross_entity_state_dependency/application_approve_rejected_when_policyholder_debarred
        """
        ctx = setup_bound_policy(state_code="IA", premium_cents=50000)
        pay_premium(ctx["policy"]["id"], 50000)
        ph = ctx["policyholder"]
        deny_claims_with_fraud(ph["id"], ctx["policy"]["id"], 2)
        quote2 = create_quote(ph["id"], 500000, 50000)
        app2 = create_application(ph["id"], quote2["id"])
        deny_claims_with_fraud(ph["id"], ctx["policy"]["id"], 1)
        ph_after = get_policyholder(ph["id"])
        assert ph_after["status"] == "DEBARRED"
        assert ph_after["fraud_strike_count"] == 3
        app2_after = validate_success(api.get_application(app2["id"], UNDERWRITER))
        assert app2_after["status"] == "DECLINED"
        resp = api.approve_application(app2["id"], UNDERWRITER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_debarred_policyholder_keeps_exactly_one_policy(self, api):
        """PRD §3.8: "when the count reaches 3 the policyholder's status becomes DEBARRED" — debarment targets applications, not already-bound policies.
        PRD §3.4: "an UnderwritingAdmin may still approve it manually" (policy list read path).

        Design: Difficulty/cross_entity_state_dependency/application_approve_rejected_when_policyholder_debarred
        """
        ctx = setup_bound_policy(state_code="IA", premium_cents=50000)
        pay_premium(ctx["policy"]["id"], 50000)
        ph = ctx["policyholder"]
        deny_claims_with_fraud(ph["id"], ctx["policy"]["id"], 3)
        policies, meta = validate_paginated(api.list_policyholder_policies(ph["id"], UNDERWRITER))
        assert meta["total_count"] == 1
        assert policies[0]["id"] == ctx["policy"]["id"]


class TestCauseElectionOcc:
    def test_second_election_with_stale_version_rejected(self, api):
        """PRD §2.6: "Electing a charitable cause on a policy requires expected_policy_version matching the policy's current version; a stale election is rejected with ERR_STALE_VERSION. A second sequential election carrying the previously observed version is deterministically rejected as stale."

        Design: Corner/cross_cutting_layers/occ_policy_cause_election_stale_version
        """
        set_clock()
        from test_helpers import create_cause, create_cohort
        cause_c = create_cause("C")
        cause_d = create_cause("D")
        cohort = create_cohort(2026, cause_c["id"])
        setup_state_fee(state_code="TX")
        ph = create_policyholder(state_code="TX")
        quote = create_quote(ph["id"], 500000, 100000)
        app = create_application(ph["id"], quote["id"])
        policy = validate_success(api.approve_application(app["id"], UNDERWRITER))
        first = validate_success(
            api.elect_cause(
                policy["id"],
                {"cause_id": cause_d["id"], "expected_policy_version": policy["version"]},
                make_policyholder_headers(ph["id"]),
            )
        )
        assert first["cause_id"] == cause_d["id"]
        resp = api.elect_cause(
            policy["id"],
            {"cause_id": cause_c["id"], "expected_policy_version": policy["version"]},
            make_policyholder_headers(ph["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_first_election_sets_cause_and_bumps_election_counter(self, api):
        """PRD §3.6: "A successful election sets cause_id, increments the dedicated cause_election_version guard counter by one, and increments the policy's version by one."

        Design: Corner/cross_cutting_layers/occ_policy_cause_election_stale_version
        """
        set_clock()
        from test_helpers import create_cause, create_cohort
        cause_c = create_cause("C")
        cause_d = create_cause("D")
        cohort = create_cohort(2026, cause_c["id"])
        setup_state_fee(state_code="TX")
        ph = create_policyholder(state_code="TX")
        quote = create_quote(ph["id"], 500000, 100000)
        app = create_application(ph["id"], quote["id"])
        policy = validate_success(api.approve_application(app["id"], UNDERWRITER))
        elected = validate_success(
            api.elect_cause(
                policy["id"],
                {"cause_id": cause_d["id"], "expected_policy_version": policy["version"]},
                make_policyholder_headers(ph["id"]),
            )
        )
        assert elected["cause_id"] == cause_d["id"]
        assert elected["cause_election_version"] == policy["cause_election_version"] + 1
        assert elected["version"] == policy["version"] + 1

    def test_election_after_cohort_close_rejected(self, api):
        """PRD §3.6: "Election is only possible while the policy's cohort is still OPEN — elections lock when the cohort closes, and an attempt afterward is rejected with ERR_COHORT_CLOSED".

        Design: Corner/validations/cause_election_after_cohort_close_rejected
        """
        set_clock()
        from test_helpers import create_cause, create_cohort
        cause_c = create_cause("C")
        cause_d = create_cause("D")
        cohort = create_cohort(2026, cause_c["id"])
        setup_state_fee(state_code="TX")
        ph = create_policyholder(state_code="TX")
        quote = create_quote(ph["id"], 500000, 50000)
        app = create_application(ph["id"], quote["id"])
        policy = validate_success(api.approve_application(app["id"], UNDERWRITER))
        validate_success(api.close_cohort(cohort["id"], ADMIN))
        resp = api.elect_cause(
            policy["id"],
            {"cause_id": cause_d["id"], "expected_policy_version": policy["version"]},
            make_policyholder_headers(ph["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_COHORT_CLOSED)
        policy_after = validate_success(api.get_policy(policy["id"], FINANCE))
        assert policy_after["cause_id"] is None
