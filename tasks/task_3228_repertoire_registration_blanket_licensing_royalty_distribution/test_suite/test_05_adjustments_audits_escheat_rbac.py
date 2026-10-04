"""Adjustments, audits, escheatment, RBAC, and optimistic concurrency tests."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    get_success_data,
    make_publisher_headers,
    make_songwriter_headers,
    make_finance_officer_headers,
    validate_error,
    validate_success,
    create_affiliate_payload,
    create_work_payload,
    create_adjustment_payload,
    create_audit_payload,
    create_licensee_payload,
    create_performance_payload,
    create_publisher_affiliate,
    create_songwriter_affiliate,
    setup_with_performance,
    setup_distributed_cycle,
    _create_work,
    _create_claim,
    _confirm_work,
    _create_licensee,
    _issue_license,
    _ingest_performance,
    _create_cycle,
    _close_collection,
    _list_cycle_statements,
)

REGISTRAR = TEST_USERS["pro_registrar_headers"]
LIC_ADMIN = TEST_USERS["pro_licensing_admin_headers"]
DISTRIBUTOR = TEST_USERS["royalty_distributor_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]
SYSADMIN = TEST_USERS["pro_system_admin_headers"]


def _suspend(affiliate_id, api):
    validate_success(api.update_affiliate(affiliate_id, {"status": "SUSPENDED"}, REGISTRAR))


def _setup_distributed_with_unclaimed_writer(api):
    """Distributed cycle where the writer's share routed to the pool (suspended)."""
    writer = create_songwriter_affiliate(legal_name="Writer P", affiliation_code="WRP")
    pub = create_publisher_affiliate(legal_name="Pub P", affiliation_code="PUBP")
    work = _create_work(pub["id"], title="Song P")
    _create_claim(work["id"], writer["id"], "WRITER", 5000)
    _create_claim(work["id"], pub["id"], "PUBLISHER", 5000)
    _confirm_work(work["id"])
    licensee = _create_licensee(legal_name="Prio Radio")
    license_ = _issue_license(licensee)
    event = _ingest_performance(
        work["id"], license_["id"], performance_date="2026-02-01", play_count=100
    )
    cycle = _create_cycle(label="P1", period_start="2026-01-01", period_end="2026-03-31")
    get_success_data(api.open_cycle(cycle["id"], DISTRIBUTOR))
    get_success_data(
        api.capture_performances(
            cycle["id"], {"performance_event_ids": [event["id"]]}, DISTRIBUTOR
        )
    )
    _suspend(writer["id"], api)
    closed = _close_collection(cycle["id"])
    statements = _list_cycle_statements(closed["id"])
    for s in statements:
        get_success_data(api.finalize_statement(s["id"], DISTRIBUTOR))
    validate_success(api.distribute_cycle(closed["id"], DISTRIBUTOR))
    by_affiliate = {s["affiliate_id"]: s for s in statements}
    return {
        "writer": writer, "pub": pub, "work": work, "licensee": licensee,
        "license": license_, "event": event, "cycle": closed,
        "statements": statements, "by_affiliate": by_affiliate,
    }


class TestDifficultyAdjustmentApplyCascade:
    def test_apply_credits_affiliate_and_flips_statement_and_cycle(self, api):
        """PRD §3.9: "Applying an APPROVED adjustment moves it to the terminal APPLIED,
        adds the delta_cents to the affiliate's royalty_balance_cents, and — for a
        positive LATE_CLAIM delta — debits the same cents from the cycle's unclaimed
        pool. The adjusted statement moves to ADJUSTED, and the first applied adjustment
        against any statement of a DISTRIBUTED cycle moves the cycle itself to ADJUSTED,
        where subsequent applied adjustments keep it."

        Design: Difficulty/transitive_cascade/adjustment_apply_three_hop_cascade
        """
        ctx = setup_distributed_cycle()
        stmt = ctx["statements"][0]
        # The claims window is open through 2026-06-29; stay inside it.
        validate_success(api.set_clock({"to_iso8601": "2026-04-15T00:00:00Z"}, SYSADMIN))
        adj = validate_success(
            api.create_adjustment(
                stmt["id"], {"delta_cents": 5000000, "reason": "DATA_CORRECTION"}, DISTRIBUTOR
            ),
            expected_status=201,
        )
        validate_success(api.approve_adjustment(adj["id"], FINANCE))
        applied = validate_success(api.apply_adjustment(adj["id"], FINANCE))
        assert applied["status"] == "APPLIED"

        affiliate = validate_success(api.get_affiliate(ctx["publisher"]["id"], FINANCE))
        # paid net 955_726_027 (gross 1_006_027_397 minus admin 50_301_370) + 5_000_000
        assert affiliate["royalty_balance_cents"] == 960726027

        stmt_after = validate_success(api.get_statement(stmt["id"], FINANCE))
        assert stmt_after["status"] == "ADJUSTED"
        cycle_after = validate_success(api.get_cycle(ctx["cycle"]["id"], FINANCE))
        assert cycle_after["status"] == "ADJUSTED"

    def test_second_applied_adjustment_keeps_cycle_adjusted(self, api):
        """PRD §3.9: "The adjusted statement moves to ADJUSTED, and the first applied
        adjustment against any statement of a DISTRIBUTED cycle moves the cycle itself
        to ADJUSTED, where subsequent applied adjustments keep it."

        Design: Difficulty/transitive_cascade/adjustment_apply_three_hop_cascade
        """
        ctx = setup_distributed_cycle()
        stmt = ctx["statements"][0]
        validate_success(api.set_clock({"to_iso8601": "2026-04-15T00:00:00Z"}, SYSADMIN))
        for delta in (1000000, 2000000):
            adj = validate_success(
                api.create_adjustment(
                    stmt["id"], {"delta_cents": delta, "reason": "DATA_CORRECTION"}, DISTRIBUTOR
                ),
                expected_status=201,
            )
            validate_success(api.approve_adjustment(adj["id"], FINANCE))
            validate_success(api.apply_adjustment(adj["id"], FINANCE))
        affiliate = validate_success(api.get_affiliate(ctx["publisher"]["id"], FINANCE))
        assert affiliate["royalty_balance_cents"] == 955726027 + 1000000 + 2000000
        cycle_after = validate_success(api.get_cycle(ctx["cycle"]["id"], FINANCE))
        assert cycle_after["status"] == "ADJUSTED"


class TestDifficultyStateBeatsTemporal:
    def test_approve_applied_adjustment_after_window_returns_invalid_state(self, api):
        """PRD §2.9: "When several validations could reject the same request, the server
        evaluates them in a fixed priority order so that callers see a deterministic
        error. Authentication comes first (ERR_UNAUTHENTICATED), then role authorization
        (ERR_FORBIDDEN), then path existence (ERR_NOT_FOUND), then body foreign-key
        existence (ERR_REFERENCE_NOT_FOUND), then state-machine permission
        (ERR_INVALID_STATE), then optimistic concurrency (ERR_STALE_VERSION), then
        segregation of duties (ERR_SEGREGATION_OF_DUTIES), then the business safety,
        temporal, constraint, referential, and fiscal checks in the order described
        through §3, with field-shape validation (ERR_VALIDATION) last."

        Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_business_temporal
        """
        ctx = _setup_distributed_with_unclaimed_writer(api)
        writer_stmt = ctx["by_affiliate"][ctx["writer"]["id"]]

        validate_success(api.set_clock({"to_iso8601": "2026-05-01T00:00:00Z"}, SYSADMIN))
        adj = validate_success(
            api.create_adjustment(
                writer_stmt["id"], {"delta_cents": 1000000, "reason": "LATE_CLAIM"},
                make_songwriter_headers(ctx["writer"]["id"]),
            ),
            expected_status=201,
        )
        validate_success(api.approve_adjustment(adj["id"], FINANCE))
        validate_success(api.apply_adjustment(adj["id"], FINANCE))

        # Advance past the claims window (period_end 2026-03-31 + 90 days = 2026-06-29).
        validate_success(api.set_clock({"to_iso8601": "2026-07-15T00:00:00Z"}, SYSADMIN))
        # The adjustment is already APPLIED: the state check outranks the temporal check.
        resp = api.approve_adjustment(adj["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_apply_applied_adjustment_after_window_returns_invalid_state(self, api):
        """PRD §2.9: "When several validations could reject the same request, the server
        evaluates them in a fixed priority order so that callers see a deterministic
        error. ... then state-machine permission (ERR_INVALID_STATE), then optimistic
        concurrency (ERR_STALE_VERSION), then segregation of duties
        (ERR_SEGREGATION_OF_DUTIES), then the business safety, temporal, constraint,
        referential, and fiscal checks in the order described through §3, with
        field-shape validation (ERR_VALIDATION) last."
        PRD §3.9: "Applying an APPROVED adjustment moves it to the terminal APPLIED".

        Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_business_temporal
        """
        ctx = _setup_distributed_with_unclaimed_writer(api)
        writer_stmt = ctx["by_affiliate"][ctx["writer"]["id"]]
        validate_success(api.set_clock({"to_iso8601": "2026-05-01T00:00:00Z"}, SYSADMIN))
        adj = validate_success(
            api.create_adjustment(
                writer_stmt["id"], {"delta_cents": 1000000, "reason": "LATE_CLAIM"},
                make_songwriter_headers(ctx["writer"]["id"]),
            ),
            expected_status=201,
        )
        validate_success(api.approve_adjustment(adj["id"], FINANCE))
        validate_success(api.apply_adjustment(adj["id"], FINANCE))
        validate_success(api.set_clock({"to_iso8601": "2026-07-15T00:00:00Z"}, SYSADMIN))
        resp = api.apply_adjustment(adj["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestDifficultyClaimLockedByDistribution:
    def test_revoke_locked_claim_rejected_and_remains_accepted(self, api):
        """PRD §3.2: "A claim owner may also revoke their own claim outright, provided
        no FINALIZED-or-later royalty statement for any cycle has routed royalties on
        it; a claim so locked is rejected with ERR_CLAIM_LOCKED_BY_DISTRIBUTION."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_late_claim
        """
        ctx = setup_distributed_cycle()
        claims = get_success_data(
            api.list_work_share_claims(ctx["work"]["id"], REGISTRAR)
        )
        assert len(claims) == 1
        claim = claims[0]
        assert claim["status"] == "ACCEPTED"
        resp = api.revoke_share_claim(
            claim["id"], make_publisher_headers(ctx["publisher"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_LOCKED_BY_DISTRIBUTION)
        after = get_success_data(api.list_work_share_claims(ctx["work"]["id"], REGISTRAR))
        assert after[0]["status"] == "ACCEPTED"

    def test_unlocked_claim_revokes_cleanly_before_any_distribution(self, api):
        """PRD §3.2: "A claim owner may also revoke their own claim outright, provided
        no FINALIZED-or-later royalty statement for any cycle has routed royalties on
        it; a claim so locked is rejected with ERR_CLAIM_LOCKED_BY_DISTRIBUTION."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_late_claim
        """
        pub = create_publisher_affiliate(legal_name="Pub R2", affiliation_code="PUBR2")
        work = _create_work(pub["id"], title="Song R2")
        claim = _create_claim(work["id"], pub["id"], "PUBLISHER", 10000)
        revoked = validate_success(
            api.revoke_share_claim(claim["id"], make_publisher_headers(pub["id"]))
        )
        assert revoked["status"] == "REVOKED"


class TestDifficultyAuditCloseGate:
    def test_close_blocked_without_remedy_adjustment_and_standing_unchanged(self, api):
        """PRD §3.10: "Closing is gated on remedy: if the findings are positive, a
        royalty adjustment with reason AUDIT_FINDING referencing the underpayment must
        already exist in some status other than REJECTED; closing without one is
        rejected with ERR_AUDIT_CLOSE_REQUIRES_ADJUSTMENT."
        PRD §3.10: "When the filed findings_delta_cents is strictly greater than
        1,000,000 cents, closing the audit flips the licensee's credit_standing to
        DELINQUENT; a figure exactly equal to the threshold does not flip it."

        Design: Difficulty/cross_entity_state_dependency/license_issuance_gated_by_licensee_standing_and_audit_close_gated_by_adjustment
        """
        licensee = _create_licensee(
            legal_name="Audit Co", category="VENUE",
            reported_revenue_cents=10000000000, usage_units=400,
        )
        audit = validate_success(
            api.create_audit(licensee["id"], create_audit_payload(), FINANCE),
            expected_status=201,
        )
        validate_success(api.file_findings(audit["id"], {"findings_delta_cents": 2000000}, FINANCE))
        resp = api.close_audit(audit["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_AUDIT_CLOSE_REQUIRES_ADJUSTMENT)
        licensee_after = validate_success(api.get_licensee(licensee["id"], FINANCE))
        assert licensee_after["credit_standing"] == "GOOD"

    def test_close_with_remedy_flips_standing_and_blocks_issuance(self, api):
        """PRD §3.10: "Closing is gated on remedy: if the findings are positive, a
        royalty adjustment with reason AUDIT_FINDING referencing the underpayment must
        already exist in some status other than REJECTED; closing without one is
        rejected with ERR_AUDIT_CLOSE_REQUIRES_ADJUSTMENT."
        PRD §3.5: "Issuance of a blanket license requires the licensee's credit_standing
        to be GOOD; issuance attempted for a DELINQUENT licensee is rejected with
        ERR_LICENSEE_DELINQUENT."

        Design: Difficulty/cross_entity_state_dependency/license_issuance_gated_by_licensee_standing_and_audit_close_gated_by_adjustment
        """
        ctx = setup_distributed_cycle()
        licensee = ctx["licensee"]
        stmt = ctx["statements"][0]
        audit = validate_success(
            api.create_audit(licensee["id"], create_audit_payload(), FINANCE),
            expected_status=201,
        )
        validate_success(api.file_findings(audit["id"], {"findings_delta_cents": 2000000}, FINANCE))
        validate_success(
            api.create_adjustment(
                stmt["id"],
                {"delta_cents": 2000000, "reason": "AUDIT_FINDING", "audit_id": audit["id"]},
                make_finance_officer_headers("fin-41"),
            ),
            expected_status=201,
        )
        closed = validate_success(api.close_audit(audit["id"], FINANCE))
        assert closed["status"] == "CLOSED"
        licensee_after = validate_success(api.get_licensee(licensee["id"], FINANCE))
        assert licensee_after["credit_standing"] == "DELINQUENT"
        resp = api.issue_license(
            licensee["id"],
            {
                "effective_date": "2027-01-01",
                "expiry_date": "2027-12-31",
                "expected_licensee_version": licensee_after["version"],
            },
            LIC_ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_LICENSEE_DELINQUENT)


class TestDifficultyEscheatBoundary:
    def test_grace_final_day_not_due_and_next_day_due(self, api):
        """PRD §3.11: "While the pool is OPEN, a FinanceOfficer may escheat funds only
        after the claims window plus a 30-day grace period — the clock date must be
        strictly later than claims_open_until plus those 30 days, and on the exact
        grace-final day the pool is not yet escheatable; a premature request is rejected
        with ERR_ESCHEAT_NOT_YET_DUE."

        Design: Difficulty/boundary_precision_check/escheat_grace_final_day_not_due
        """
        pub = create_publisher_affiliate(legal_name="Pub E", affiliation_code="PUBE")
        work = _create_work(pub["id"], title="Song E")
        _create_claim(work["id"], pub["id"], "PUBLISHER", 10000)
        _confirm_work(work["id"])
        licensee = _create_licensee(legal_name="Esc Radio")
        license_ = _issue_license(licensee)
        event = _ingest_performance(
            work["id"], license_["id"], performance_date="2026-02-01", play_count=100
        )
        cycle = _create_cycle(label="E1", period_start="2026-01-01", period_end="2026-03-31")
        get_success_data(api.open_cycle(cycle["id"], DISTRIBUTOR))
        get_success_data(
            api.capture_performances(
                cycle["id"], {"performance_event_ids": [event["id"]]}, DISTRIBUTOR
            )
        )
        _suspend(pub["id"], api)
        closed = _close_collection(cycle["id"])
        statements = _list_cycle_statements(closed["id"])
        for s in statements:
            get_success_data(api.finalize_statement(s["id"], DISTRIBUTOR))
        validate_success(api.distribute_cycle(closed["id"], DISTRIBUTOR))
        pool = validate_success(api.get_cycle_pool(closed["id"], DISTRIBUTOR))
        assert pool["balance_cents"] == 1006027397

        # claims_open_until = 2026-06-29; grace final day = 2026-07-29.
        validate_success(api.set_clock({"to_iso8601": "2026-07-29T00:00:00Z"}, SYSADMIN))
        resp = api.escheat_pool(pool["id"], {"amount_cents": 1000000}, FINANCE)
        validate_error(resp, ApiErrorId.ERR_ESCHEAT_NOT_YET_DUE)
        pool_after = validate_success(api.get_pool(pool["id"], FINANCE))
        assert pool_after["balance_cents"] == 1006027397

        # One day later the escheat succeeds.
        validate_success(api.set_clock({"to_iso8601": "2026-07-30T00:00:00Z"}, SYSADMIN))
        escheated = validate_success(api.escheat_pool(pool["id"], {"amount_cents": 1000000}, FINANCE))
        assert escheated["balance_cents"] == 1006027397 - 1000000
        assert escheated["status"] == "PARTIALLY_ESCHEATED"

    def test_escheat_inside_claims_window_also_not_due(self, api):
        """PRD §3.11: "While the pool is OPEN, a FinanceOfficer may escheat funds only
        after the claims window plus a 30-day grace period — the clock date must be
        strictly later than claims_open_until plus those 30 days, and on the exact
        grace-final day the pool is not yet escheatable; a premature request is rejected
        with ERR_ESCHEAT_NOT_YET_DUE."
        PRD §3.9: "sets the cycle's claims_open_until to 90 days after period_end if not
        already set — the window during which late claims remain valid."

        Design: Difficulty/boundary_precision_check/escheat_grace_final_day_not_due
        """
        pub = create_publisher_affiliate(legal_name="Pub E2", affiliation_code="PUBE2")
        work = _create_work(pub["id"], title="Song E2")
        _create_claim(work["id"], pub["id"], "PUBLISHER", 10000)
        _confirm_work(work["id"])
        licensee = _create_licensee(legal_name="Esc Radio 2")
        license_ = _issue_license(licensee)
        event = _ingest_performance(
            work["id"], license_["id"], performance_date="2026-02-01", play_count=100
        )
        cycle = _create_cycle(label="E2", period_start="2026-01-01", period_end="2026-03-31")
        get_success_data(api.open_cycle(cycle["id"], DISTRIBUTOR))
        get_success_data(
            api.capture_performances(
                cycle["id"], {"performance_event_ids": [event["id"]]}, DISTRIBUTOR
            )
        )
        _suspend(pub["id"], api)
        closed = _close_collection(cycle["id"])
        statements = _list_cycle_statements(closed["id"])
        for s in statements:
            get_success_data(api.finalize_statement(s["id"], DISTRIBUTOR))
        validate_success(api.distribute_cycle(closed["id"], DISTRIBUTOR))
        pool = validate_success(api.get_cycle_pool(closed["id"], DISTRIBUTOR))

        # Well inside the claims window (claims_open_until = 2026-06-29): far from due.
        validate_success(api.set_clock({"to_iso8601": "2026-05-01T00:00:00Z"}, SYSADMIN))
        resp = api.escheat_pool(pool["id"], {"amount_cents": 1000000}, FINANCE)
        validate_error(resp, ApiErrorId.ERR_ESCHEAT_NOT_YET_DUE)
        pool_after = validate_success(api.get_pool(pool["id"], FINANCE))
        assert pool_after["balance_cents"] == pool["balance_cents"]
        assert pool_after["status"] == "OPEN"


class TestCornerAuditThreshold:
    def test_findings_exactly_at_threshold_do_not_flip_standing(self, api):
        """PRD §3.10: "When the filed findings_delta_cents is strictly greater than
        1,000,000 cents, closing the audit flips the licensee's credit_standing to
        DELINQUENT; a figure exactly equal to the threshold does not flip it."
        PRD §3.10: "Closing is gated on remedy: if the findings are positive, a royalty
        adjustment with reason AUDIT_FINDING referencing the underpayment must already
        exist in some status other than REJECTED; closing without one is rejected with
        ERR_AUDIT_CLOSE_REQUIRES_ADJUSTMENT."

        Design: Corner/calculations/audit_delinquency_threshold_strictly_greater
        """
        ctx = setup_distributed_cycle()
        licensee = ctx["licensee"]
        stmt = ctx["statements"][0]
        audit = validate_success(
            api.create_audit(licensee["id"], create_audit_payload(), FINANCE),
            expected_status=201,
        )
        validate_success(api.file_findings(audit["id"], {"findings_delta_cents": 1000000}, FINANCE))
        validate_success(
            api.create_adjustment(
                stmt["id"],
                {"delta_cents": 1000000, "reason": "AUDIT_FINDING", "audit_id": audit["id"]},
                make_finance_officer_headers("fin-7"),
            ),
            expected_status=201,
        )
        closed = validate_success(api.close_audit(audit["id"], FINANCE))
        assert closed["status"] == "CLOSED"
        licensee_after = validate_success(api.get_licensee(licensee["id"], FINANCE))
        assert licensee_after["credit_standing"] == "GOOD"


class TestCornerValidationErrors:
    def test_invalid_enum_category_rejected(self, api):
        """PRD §2.5: "Field-shape problems — an invalid enum member, a malformed ISO
        date, an effective_date that is not strictly earlier than the expiry_date, a
        period_start later than the period_end, a play_count below 1, a negative
        disputed_fee_cents — are rejected with ERR_VALIDATION."

        Design: Corner/validations/invalid_enum_category_rejected
        """
        resp = api.create_licensee(
            create_licensee_payload(legal_name="Bad Cat", category="RADIO_STATION",
                                    reported_revenue_cents=1000, usage_units=0),
            LIC_ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_license_dates_inverted_rejected(self, api):
        """PRD §3.5: "The licensing admin supplies the effective_date — the first
        covered day, inclusive — and the expiry_date, the last covered day, also
        inclusive, which must be strictly later than the effective date."
        PRD §2.5: "Field-shape problems — an invalid enum member, a malformed ISO date,
        an effective_date that is not strictly earlier than the expiry_date, a
        period_start later than the period_end, a play_count below 1, a negative
        disputed_fee_cents — are rejected with ERR_VALIDATION."

        Design: Corner/validations/license_dates_inverted_rejected
        """
        licensee = _create_licensee(
            legal_name="Inv Co", category="VENUE",
            reported_revenue_cents=10000000000, usage_units=10,
        )
        resp = api.issue_license(
            licensee["id"],
            {
                "effective_date": "2026-12-31",
                "expiry_date": "2026-01-01",
                "expected_licensee_version": licensee["version"],
            },
            LIC_ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_audit_scope_beyond_lookback_rejected(self, api):
        """PRD §3.10: "The scope may not reach further back than 1095 days before the
        current clock date — an end date beyond that horizon is rejected with
        ERR_AUDIT_SCOPE_TOO_OLD."
        PRD §2.8: "Before any such call, the clock reads exactly 2026-09-01T00:00:00Z."

        Design: Corner/validations/audit_scope_beyond_lookback_rejected
        """
        licensee = _create_licensee(
            legal_name="Old Co", category="VENUE",
            reported_revenue_cents=10000000000, usage_units=10,
        )
        resp = api.create_audit(
            licensee["id"],
            {"scope_period_start": "2019-01-01", "scope_period_end": "2020-01-01"},
            FINANCE,
        )
        validate_error(resp, ApiErrorId.ERR_AUDIT_SCOPE_TOO_OLD)


class TestCornerEntityDefaults:
    def test_affiliate_creation_defaults(self, api):
        """PRD §3.1: "The affiliate begins life with status set to ACTIVE, and two
        ledger fields that track its money: royalty_balance_cents, the unpaid net
        royalty balance that payable statements credit and post-distribution
        adjustments debit or credit, and total_paid_cents, the cumulative lifetime
        amount actually paid across all distributions. Both start at zero and are
        computed by the system."
        PRD §2.4: "The version is an integer that increments by exactly 1 on every
        modification of the resource".

        Design: Corner/entities/affiliate_creation_defaults_active_and_zero_balances
        """
        data = validate_success(
            api.create_affiliate(
                create_affiliate_payload(legal_name="Fresh Pub", affiliation_code="FP1"),
                REGISTRAR,
            ),
            expected_status=201,
        )
        assert data["status"] == "ACTIVE"
        assert data["royalty_balance_cents"] == 0
        assert data["total_paid_cents"] == 0
        assert data["version"] == 1

    def test_affiliate_duplicate_affiliation_code_rejected(self, api):
        """PRD §3.1: "a party-assigned mnemonic that must be unique across all
        affiliates; a duplicate code is rejected with ERR_VALIDATION."

        Design: Corner/entities/affiliate_duplicate_affiliation_code_rejected
        """
        validate_success(
            api.create_affiliate(
                create_affiliate_payload(legal_name="First", affiliation_code="DUP1"),
                REGISTRAR,
            ),
            expected_status=201,
        )
        resp = api.create_affiliate(
            create_affiliate_payload(
                legal_name="Second", party_type="SONGWRITER", affiliation_code="DUP1"
            ),
            REGISTRAR,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestCornerAdjustmentLifecycle:
    def test_approve_twice_rejected(self, api):
        """PRD §3.9: "Rejection moves a PENDING adjustment to REJECTED; approval moves
        it to APPROVED."
        PRD §2.5: "State checks come after existence: an operation that the target's
        current state does not permit is rejected with ERR_INVALID_STATE."

        Design: Corner/state_machines/adjustment_approve_twice_rejected
        """
        ctx = setup_distributed_cycle()
        stmt = ctx["statements"][0]
        adj = validate_success(
            api.create_adjustment(
                stmt["id"], {"delta_cents": -1000, "reason": "DATA_CORRECTION"}, DISTRIBUTOR
            ),
            expected_status=201,
        )
        validate_success(api.approve_adjustment(adj["id"], FINANCE))
        resp = api.approve_adjustment(adj["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_adjustment(adj["id"], FINANCE))
        assert after["status"] == "APPROVED"


class TestCornerRbac:
    def test_songwriter_cannot_register_works(self, api):
        """PRD §4: "POST | /pro/works | Register a musical work | Publisher"
        PRD §2.1: "A request whose role is authenticated but not permitted for the
        target endpoint is rejected with ERR_FORBIDDEN."

        Design: Corner/rbac/songwriter_cannot_register_works
        """
        writer = create_songwriter_affiliate(legal_name="SW One", affiliation_code="SW1")
        resp = api.create_work(
            create_work_payload(writer["id"], title="SW Song"),
            make_songwriter_headers(writer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_finance_officer_cannot_ingest_performances(self, api):
        """PRD §4: "POST | /pro/performances | Ingest a single performance event |
        RoyaltyDistributor"
        PRD §2.1: "A request whose role is authenticated but not permitted for the
        target endpoint is rejected with ERR_FORBIDDEN."

        Design: Corner/rbac/finance_officer_cannot_ingest_performances
        """
        resp = api.ingest_performance(
            create_performance_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID, play_count=1),
            FINANCE,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_adjustment_creator_cannot_approve_own_adjustment(self, api):
        """PRD §3.9: "The adjustment records the statement's affiliate_id, starts in
        PENDING, and is thereafter governed by segregation of duties: the FinanceOfficer
        who approves or rejects must not be the same user who created it, and a
        violation is rejected with ERR_SEGREGATION_OF_DUTIES."

        Design: Corner/rbac/segregation_of_duties_creator_cannot_approve
        """
        ctx = setup_distributed_cycle()
        stmt = ctx["statements"][0]
        creator = make_finance_officer_headers("fin-1")
        adj = validate_success(
            api.create_adjustment(
                stmt["id"], {"delta_cents": 5000, "reason": "DATA_CORRECTION"}, creator
            ),
            expected_status=201,
        )
        resp = api.approve_adjustment(adj["id"], creator)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        after = validate_success(api.get_adjustment(adj["id"], FINANCE))
        assert after["status"] == "PENDING"

    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role outside
        this set, is rejected with ERR_UNAUTHENTICATED."

        Design: Corner/rbac/missing_auth_headers_rejected
        """
        resp = api.list_affiliates({"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestCornerOptimisticConcurrency:
    def test_stale_work_version_on_resolve_conflict_then_retry(self, api):
        """PRD §3.3: "Because the resolution depends on share state the client observed
        earlier, the request must carry expected_work_version matching the work's
        current version; a mismatch is rejected with ERR_STALE_VERSION (HTTP 412), and
        the client re-reads and retries."

        Design: Corner/cross_cutting_layers/occ_stale_work_version_on_resolve_conflict
        """
        pub1 = create_publisher_affiliate(legal_name="OC P1", affiliation_code="OCP1")
        pub2 = create_publisher_affiliate(legal_name="OC P2", affiliation_code="OCP2")
        work = _create_work(pub1["id"], title="OC Song")
        _create_claim(work["id"], pub1["id"], "PUBLISHER", 6000)
        claim_b = _create_claim(work["id"], pub2["id"], "PUBLISHER", 5000)
        stale = validate_success(api.get_work(work["id"], REGISTRAR))
        # A further claim mutation advances the work version after the client read it.
        _create_claim(work["id"], pub2["id"], "WRITER", 1000)

        resp = api.resolve_conflict(
            work["id"],
            {
                "accept_claim_ids": [],
                "revoke_claim_ids": [claim_b["id"]],
                "expected_work_version": stale["version"],
            },
            REGISTRAR,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        # Retry against fresh state: dispose BOTH disputed claims.
        fresh = validate_success(api.get_work(work["id"], REGISTRAR))
        claims = get_success_data(
            api.list_work_share_claims(work["id"], REGISTRAR, params={"status": "DISPUTED"})
        )
        revoked_ids = [c["id"] for c in claims]
        resolved = validate_success(
            api.resolve_conflict(
                work["id"],
                {
                    "accept_claim_ids": [],
                    "revoke_claim_ids": revoked_ids,
                    "expected_work_version": fresh["version"],
                },
                REGISTRAR,
            )
        )
        assert resolved["status"] == "CONFIRMED"

    def test_stale_cycle_version_on_close_collection(self, api):
        """PRD §3.8: "Closing collection requires at least one ACCEPTED event captured
        in the cycle — an empty close is rejected with ERR_CYCLE_NO_PERFORMANCES — and
        requires expected_cycle_version matching the cycle's current version, because a
        prior close legitimately re-ran the allocation and bumped the epoch, making any
        earlier pool assumptions stale; a mismatch is rejected with ERR_STALE_VERSION
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_cycle_version_on_close
        """
        ctx = setup_with_performance()
        cycle = _create_cycle(label="OV1")
        get_success_data(api.open_cycle(cycle["id"], DISTRIBUTOR))
        stale = validate_success(api.get_cycle(cycle["id"], DISTRIBUTOR))
        # Capture advances the cycle version after the client read it.
        get_success_data(
            api.capture_performances(
                cycle["id"], {"performance_event_ids": [ctx["event"]["id"]]}, DISTRIBUTOR
            )
        )
        resp = api.close_collection(
            cycle["id"], {"expected_cycle_version": stale["version"]}, DISTRIBUTOR
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_stale_licensee_version_on_issue_then_retry_pins_new_fee(self, api):
        """PRD §3.5: "Because issuance pins the licensee's current fee into the license,
        the request must carry expected_licensee_version matching the licensee's current
        version; a mismatch is rejected with ERR_STALE_VERSION (HTTP 412), protecting
        the caller from pinning a blanket_fee_cents recomputed by a revenue or usage
        update it never saw."
        PRD §3.5: "The issued license records its licensee_id, copies the licensee's
        category immutably, starts in ACTIVE status, and snapshots fee_basis_cents equal
        to the licensee's blanket_fee_cents at that moment."

        Design: Corner/cross_cutting_layers/occ_stale_licensee_version_on_issue
        """
        licensee = _create_licensee(
            legal_name="OCV Co", category="VENUE",
            reported_revenue_cents=10000000000, usage_units=400,
        )
        assert licensee["blanket_fee_cents"] == 86000000
        stale_version = licensee["version"]
        patched = validate_success(
            api.update_licensee(licensee["id"], {"reported_revenue_cents": 20000000000}, LIC_ADMIN)
        )
        # VENUE: 0.0080 * 20_000_000_000 + 400 * 15_000 = 160_000_000 + 6_000_000
        assert patched["blanket_fee_cents"] == 166000000

        resp = api.issue_license(
            licensee["id"],
            {
                "effective_date": "2026-01-01",
                "expiry_date": "2026-12-31",
                "expected_licensee_version": stale_version,
            },
            LIC_ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        license_ = validate_success(
            api.issue_license(
                licensee["id"],
                {
                    "effective_date": "2026-01-01",
                    "expiry_date": "2026-12-31",
                    "expected_licensee_version": patched["version"],
                },
                LIC_ADMIN,
            ),
            expected_status=201,
        )
        assert license_["fee_basis_cents"] == 166000000
