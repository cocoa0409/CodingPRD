"""State-machine lifecycle and terminal-lockdown claims (queue B)."""
from test_helpers import (
    ApiErrorId,
    create_active_licensee,
    create_effective_schedule,
    create_licensee,
    create_ownership_claim_payload,
    create_pool,
    create_report_with_lines,
    create_rate_proceeding_payload,
    make_admin_headers,
    make_licensee_headers,
    make_matching_agent_headers,
    make_payee_admin_headers,
    make_royalty_ops_headers,
    make_statutory_board_headers,
    pay_liability,
    set_clock,
    setup_recording_with_claimants,
    setup_standard_paid_scenario,
    submit_and_accept_report,
    validate_error,
    validate_success,
)

ADMIN = make_admin_headers()
OPS = make_royalty_ops_headers()
PAYEE = make_payee_admin_headers()
BOARD = make_statutory_board_headers()
MATCHER = make_matching_agent_headers()


class TestLicenseeLifecycle:
    def test_licensee_terminal_lockdown_after_termination(self, api):
        """PRD §3.1: "Once TERMINATED, nothing further mutates the licensee."
        PRD §2.8: "sixth, state-machine legality of the requested transition
        (`ERR_INVALID_STATE`)"

        Design: Corner/state_machines/licensee_terminal_lockdown_after_termination
        """
        lic = create_licensee(legal_name="TermCo")
        terminated = validate_success(api.terminate_licensee(lic["id"], ADMIN))
        assert terminated["license_status"] == "TERMINATED"

        err1 = api.suspend_licensee(lic["id"], {"reason": "post-mortem"}, ADMIN)
        validate_error(err1, ApiErrorId.ERR_INVALID_STATE.value)
        err2 = api.reinstate_licensee(lic["id"], ADMIN)
        validate_error(err2, ApiErrorId.ERR_INVALID_STATE.value)
        got = validate_success(api.get_licensee(lic["id"], ADMIN))
        assert got["license_status"] == "TERMINATED"

    def test_suspend_reinstate_cycle_restores_submission(self, api):
        """PRD §3.1: "Suspension moves the licensee `ACTIVE` → `SUSPENDED`. An
        `Admin` suspends a licensee by supplying a free-text `reason`, which is
        recorded on the licensee's `suspended_reason` field; that field is null
        in every other status."
        PRD §3.1: "Reinstatement moves the licensee `SUSPENDED` → `ACTIVE` and
        clears `suspended_reason`."

        Design: Corner/state_machines/suspend_reinstate_cycle_restores_submission
        """
        create_effective_schedule()
        lic = create_active_licensee(legal_name="CycLic")
        suspended = validate_success(
            api.suspend_licensee(lic["id"], {"reason": "review"}, ADMIN)
        )
        assert suspended["license_status"] == "SUSPENDED"
        reinstated = validate_success(api.reinstate_licensee(lic["id"], ADMIN))
        assert reinstated["license_status"] == "ACTIVE"
        assert reinstated["suspended_reason"] is None

        lh = make_licensee_headers(lic["id"])
        report, _ = create_report_with_lines(
            lic["id"],
            [{"isrc": "NM-S", "track_title": "s", "artist_name": "s",
              "performance_count": 5}],
            "2026-01-01T00:00:00Z",
            "2026-01-31T00:00:00Z",
        )
        submitted = validate_success(api.submit_usage_report(report["id"], lh))
        assert submitted["report_status"] == "SUBMITTED"


class TestLiabilityLifecycle:
    def test_liability_write_off_is_terminal(self, api):
        """PRD §3.5: "An `Admin` may instead write off a BILLED liability —
        moving it `BILLED` → `WRITTEN_OFF` with a free-text `reason` — and a
        PAID liability flips to `SETTLED` automatically when the distribution
        batch for the same report executes (§3.6). `SETTLED` and `WRITTEN_OFF`
        are terminal."
        PRD §2.8: "sixth, state-machine legality of the requested transition
        (`ERR_INVALID_STATE`)"

        Design: Corner/state_machines/liability_write_off_is_terminal
        """
        scenario = setup_standard_paid_scenario(legal_name="WOCo")
        # Build a COMPUTED->BILLED liability without paying it: use a fresh
        # pipeline then bill only.
        lic = create_active_licensee(legal_name="WOCo2")
        report, _ = create_report_with_lines(
            lic["id"],
            [{"isrc": "NM-W", "track_title": "w", "artist_name": "w",
              "performance_count": 10000}],
            "2026-01-01T00:00:00Z",
            "2026-01-31T00:00:00Z",
        )
        accepted = submit_and_accept_report(report["id"], lic["id"])
        liability = validate_success(
            api.compute_liability(
                report["id"],
                {"expected_usage_report_version": accepted["version"]},
                OPS,
            ),
            expected_status=201,
        )
        validate_success(api.bill_liability(liability["id"], OPS))
        written = validate_success(
            api.write_off_liability(liability["id"], {"reason": "uncollectible"},
                                    ADMIN)
        )
        assert written["liability_status"] == "WRITTEN_OFF"
        err = api.record_liability_payment(liability["id"], OPS)
        validate_error(err, ApiErrorId.ERR_INVALID_STATE.value)


class TestOwnershipClaimLifecycle:
    def test_claim_reject_and_withdraw_terminal_states(self, api):
        """PRD §3.7: "withdrawing moves an OPEN claim to `WITHDRAWN`, which is
        terminal."
        PRD §3.7: "Resolution takes an `outcome` of `UPHELD` or `REJECTED` plus
        a free-text `resolution_note`. Resolving with `REJECTED` moves the claim
        `UNDER_REVIEW` → `REJECTED`, terminal."
        PRD §2.8: "sixth, state-machine legality of the requested transition
        (`ERR_INVALID_STATE`)"

        Design: Corner/state_machines/claim_reject_and_withdraw_terminal_states
        """
        env = setup_recording_with_claimants(isrc="ISRC-OC")
        rec = env["recording"]
        claim = validate_success(
            api.create_ownership_claim(
                rec["id"],
                create_ownership_claim_payload(env["ro2"]["id"],
                                               claimed_share_pct=50),
                PAYEE,
            ),
            expected_status=201,
        )
        # resolve from OPEN is invalid (resolve requires UNDER_REVIEW)
        err1 = api.resolve_claim(
            claim["id"], {"outcome": "REJECTED", "resolution_note": "premature"},
            PAYEE,
        )
        validate_error(err1, ApiErrorId.ERR_INVALID_STATE.value)
        # withdraw from OPEN is valid and terminal
        withdrawn = validate_success(api.withdraw_claim(claim["id"], PAYEE))
        assert withdrawn["claim_status"] == "WITHDRAWN"
        # no further transitions from WITHDRAWN
        err2 = api.start_claim_review(claim["id"], PAYEE)
        validate_error(err2, ApiErrorId.ERR_INVALID_STATE.value)


class TestRateProceedingLifecycle:
    def test_rate_proceeding_publish_before_decide_rejected(self, api):
        """PRD §3.2: "Every proceeding operation validates the proceeding's
        current status — deciding a non-OPEN proceeding, publishing a
        non-DECIDED one, closing a non-PUBLISHED one, or deciding with a
        schedule that is not DRAFT is rejected with `ERR_RATE_PROCEEDING_INVALID`
        (HTTP 409)."

        Design: Corner/state_machines/rate_proceeding_publish_before_decide_rejected
        """
        proc = validate_success(
            api.create_rate_proceeding(create_rate_proceeding_payload(
                docket_no="DKT-X"), BOARD),
            expected_status=201,
        )
        err = api.publish_rate_proceeding(proc["id"], BOARD)
        validate_error(err, ApiErrorId.ERR_RATE_PROCEEDING_INVALID.value)
        got = validate_success(api.get_rate_proceeding(proc["id"], BOARD))
        assert got["proceeding_status"] == "OPEN"


class TestPoolLifecycle:
    def test_pool_expire_before_window_rejected(self, api):
        """PRD §3.9: "An `Admin` expires an ACCRUING pool once the current
        logical clock has passed `period_end` by more than 365 days; expiring
        before that window is rejected with `ERR_POOL_NOT_EXPIRABLE` (HTTP 409)."
        PRD §2.5: "The clock's startup default, before any explicit set, is
        exactly 2026-09-01T00:00:00Z."

        Design: Corner/state_machines/pool_expire_before_window_rejected
        """
        pool = create_pool()
        err = api.expire_pool(pool["id"], ADMIN)
        validate_error(err, ApiErrorId.ERR_POOL_NOT_EXPIRABLE.value)
        set_clock("2028-01-01T00:00:00Z")
        expired = validate_success(api.expire_pool(pool["id"], ADMIN))
        assert expired["pool_status"] == "EXPIRED"

    def test_pool_complete_campaign_requires_matching_campaign_state(self, api):
        """PRD §3.9: "Completing a campaign requires the pool to be in
        MATCHING_CAMPAIGN — completing against a pool in any other status is
        rejected with `ERR_CAMPAIGN_NOT_OPEN` (HTTP 409)"

        Design: Corner/state_machines/pool_complete_campaign_requires_matching_campaign_state
        """
        pool = create_pool()
        err = api.complete_pool_campaign(pool["id"], MATCHER)
        validate_error(err, ApiErrorId.ERR_CAMPAIGN_NOT_OPEN.value)


class TestPlayLineImmutability:
    def test_play_line_mutation_locked_after_submit(self, api):
        """PRD §3.3: "Adding or removing a play line while the report is in any
        status other than DRAFT or AMENDED is rejected with
        `ERR_PLAY_LINE_IMMUTABLE` (HTTP 409)."

        Design: Corner/state_machines/play_line_mutation_locked_after_submit
        """
        create_effective_schedule()
        lic = create_active_licensee(legal_name="PLCo")
        lh = make_licensee_headers(lic["id"])
        report, _ = create_report_with_lines(
            lic["id"],
            [{"isrc": "NM-PL", "track_title": "pl", "artist_name": "pl",
              "performance_count": 5}],
            "2026-01-01T00:00:00Z",
            "2026-01-31T00:00:00Z",
        )
        validate_success(api.submit_usage_report(report["id"], lh))
        err = api.add_play_line(
            report["id"],
            {"isrc": "NM-PL2", "track_title": "pl2", "artist_name": "pl2",
             "performance_count": 5},
            lh,
        )
        validate_error(err, ApiErrorId.ERR_PLAY_LINE_IMMUTABLE.value)


class TestBatchCancellation:
    def test_batch_cancel_only_from_planned(self, api):
        """PRD §3.6: "Cancelling a batch is possible only while PLANNED — either
        by a `RoyaltyOps` operator or automatically when the report is amended
        out of ACCEPTED — moving it `PLANNED` → `REVERSED`; cancelling a batch in
        any other status is rejected with `ERR_BATCH_NOT_CANCELLABLE` (HTTP 409)."

        Design: Corner/state_machines/batch_cancel_only_from_planned
        """
        scenario = setup_standard_paid_scenario(
            legal_name="CanCo",
            lines=[{"isrc": "NM-CN", "track_title": "cn", "artist_name": "cn",
                    "performance_count": 10000}],
        )
        report = scenario["report"]
        create_pool()
        batch = validate_success(
            api.create_distribution_batch(
                report["id"], {"scheduled_for": "2026-10-01T00:00:00Z"}, OPS,
            ),
            expected_status=201,
        )
        # Advance the logical clock to exactly scheduled_for so the batch is due.
        set_clock("2026-10-01T00:00:00Z")
        executed = validate_success(
            api.execute_distribution_batch(
                batch["id"],
                {"expected_distribution_batch_version": batch["version"]},
                OPS,
            )
        )
        assert executed["batch_status"] == "EXECUTED"
        err = api.cancel_distribution_batch(batch["id"], OPS)
        validate_error(err, ApiErrorId.ERR_BATCH_NOT_CANCELLABLE.value)
        got = validate_success(api.get_distribution_batch(batch["id"], OPS))
        assert got["batch_status"] == "EXECUTED"
