"""Claim lifecycle tests: info loop, reopen cycle, terminal lockdown,
cross-entity preconditions, and validation precedence on resolve/execute.
"""
from test_helpers import (
    TEST_USERS,
    assign_agent,
    create_agent,
    create_client,
    create_notice,
    create_office,
    create_poa_payload,
    create_preparer,
    create_remediation_payload,
    create_return,
    draft_and_execute_poa,
    get_success_data,
    make_client_headers,
    pay_notice,
    quality_close,
    resolve_claim,
    scope_claim_in_scope,
    set_clock,
    setup_claim_in_representing,
    setup_claim_in_triage,
    setup_filed_return,
    setup_office_preparer_client,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
OM = TEST_USERS["office_manager_headers"]
CM = TEST_USERS["case_manager_headers"]
CM_SCOPER = TEST_USERS["case_manager_scoper_headers"]
CM_RESOLVER = TEST_USERS["case_manager_resolver_headers"]


class TestClaimInfoLoopAndReopenCycle:
    def test_info_loop_round_trip(self, api):
        """PRD §3.5: "Requesting information moves the claim to `INFO_NEEDED`;
        the client — and only the owning client, by entity-backed identity —
        then provides information to return the claim to `TRIAGE`. This pair
        forms the information loop; `INFO_NEEDED` is never terminal, and
        either move bumps the claim's `version`."

        Design: Difficulty/non_linear_state_machine/claim_info_loop_and_reopen_cycle
        """
        ctx = setup_claim_in_triage(components=["1040_SIMPLE"], product_tier="STANDARD")
        claim = ctx["claim"]
        moved = validate_success(api.request_info_claim(claim["id"], CM), 200)
        assert moved["status"] == "INFO_NEEDED"
        assert moved["version"] == claim["version"] + 1
        back = validate_success(
            api.provide_info_claim(claim["id"], make_client_headers(ctx["client"]["id"])), 200
        )
        assert back["status"] == "TRIAGE"
        assert back["version"] == claim["version"] + 2

    def test_full_reopen_cycle_reaches_resolved_twice(self, api):
        """PRD §3.7: "A `RESOLVED` claim may be reopened by a `CaseManager`;
        reopening credits the escrow by subtracting the claim's retained
        `final_liability_cents` from `paid_out_cents` (with an escrow
        `version` bump) while leaving `expected_accrual_cents` untouched,
        keeps `final_liability_cents` on the claim for audit, and moves the
        claim to `REOPENED`."

        Claim resolves, reopens, is re-scoped and re-driven through assignment
        and POA execution, and resolves a second time; the escrow's paid-out
        returns to the full liability and the historical accrual accrues per
        resolution.

        Design: Difficulty/non_linear_state_machine/claim_info_loop_and_reopen_cycle
        """
        ctx = setup_claim_in_representing(
            components=["1040_ITEMIZED", "1040_MULTI_STATE"],
            product_tier="PLUS",
            with_escrow=True,
            notice_overrides={
                "authority_type": "FEDERAL",
                "tax_delta_cents": 50000,
                "penalty_cents": 5000,
                "issued_at": "2026-09-15T00:00:00Z",
                "due_at": "2026-10-01T00:00:00Z",
            },
            window_start="2026-10-02T00:00:00Z",
            window_end="2026-12-02T00:00:00Z",
        )
        set_clock("2026-11-01T00:00:00Z")
        pay_notice(ctx["notice"]["id"])
        resolved = resolve_claim(ctx["claim"]["id"])
        assert resolved["status"] == "RESOLVED"
        assert resolved["payout_total_cents"] == 55425
        assert resolved["final_liability_cents"] == 105425

        reopened = validate_success(api.reopen_claim(ctx["claim"]["id"], CM), 200)
        assert reopened["status"] == "REOPENED"

        scope_claim_in_scope(ctx["claim"]["id"], error_attribution="PREPARER_ERROR")
        assign_agent(ctx["claim"]["id"], ctx["agent"]["id"],
                     window_start="2026-12-03T00:00:00Z", window_end="2027-01-03T00:00:00Z")
        draft_and_execute_poa(ctx["claim"]["id"], ctx["agent"]["id"])
        resolved2 = resolve_claim(ctx["claim"]["id"])
        assert resolved2["status"] == "RESOLVED"

        escrow = validate_success(api.get_escrow(ctx["escrow"]["id"], ADMIN), 200)
        assert escrow["paid_out_cents"] == 105425, "credited at reopen, re-debited at second resolve"
        assert escrow["expected_accrual_cents"] == 121936, "historical accrual persists per resolution"


class TestClaimDeniedTerminalLockdown:
    def test_denied_claim_rejects_reopen(self, api):
        """PRD §3.5: "Scoping with `scope` set to `OUT_OF_SCOPE` denies the
        claim outright: `scope` is recorded, the payout fields stay 0, and the
        claim moves to `DENIED`, which is terminal — every further transition
        attempt on it returns `ERR_INVALID_STATE`."

        Design: Corner/state_machines/claim_denied_terminal_lockdown
        """
        ctx = setup_claim_in_triage(components=["1040_SIMPLE"], product_tier="STANDARD")
        denied = validate_success(
            api.scope_claim(ctx["claim"]["id"], {"scope": "OUT_OF_SCOPE"}, CM_SCOPER), 200
        )
        assert denied["status"] == "DENIED"
        res = api.reopen_claim(ctx["claim"]["id"], CM)
        validate_error(res, "ERR_INVALID_STATE")
        after = validate_success(api.get_claim(ctx["claim"]["id"], CM), 200)
        assert after["status"] == "DENIED"

    def test_denied_claim_rejects_request_info_assign_resolve(self, api):
        """PRD §3.5: "the claim moves to `DENIED`, which is terminal — every
        further transition attempt on it returns `ERR_INVALID_STATE`."

        Design: Corner/state_machines/claim_denied_terminal_lockdown
        """
        ctx = setup_claim_in_triage(components=["1040_SIMPLE"], product_tier="STANDARD")
        validate_success(
            api.scope_claim(ctx["claim"]["id"], {"scope": "OUT_OF_SCOPE"}, CM_SCOPER), 200
        )
        agent = create_agent()
        for res in (
            api.request_info_claim(ctx["claim"]["id"], CM),
            api.assign_claim(ctx["claim"]["id"], {"agent_id": agent["id"],
                                                  "window_start": "2026-11-02T00:00:00Z",
                                                  "window_end": "2026-12-02T00:00:00Z"}, CM),
            api.resolve_claim(ctx["claim"]["id"], CM_RESOLVER),
        ):
            validate_error(res, "ERR_INVALID_STATE")
        after = validate_success(api.get_claim(ctx["claim"]["id"], CM), 200)
        assert after["status"] == "DENIED"


class TestClaimReopenFromRepresentingRejected:
    def test_reopen_representing_claim_fails(self, api):
        """PRD §3.7: "A `RESOLVED` claim may be reopened by a `CaseManager`" —
        reopen is defined only from RESOLVED, and per PRD §2.8 "State
        preconditions on the target resource come fourth
        (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/claim_reopen_from_representing_rejected
        """
        ctx = setup_claim_in_representing(components=["1040_SIMPLE"], product_tier="STANDARD")
        res = api.reopen_claim(ctx["claim"]["id"], CM)
        validate_error(res, "ERR_INVALID_STATE")
        after = validate_success(api.get_claim(ctx["claim"]["id"], CM), 200)
        assert after["status"] == "REPRESENTING"


class TestFilingRequiresActivePreparer:
    def test_suspended_preparer_cannot_file(self, api):
        """PRD §3.2: "the assigned preparer must resolve to someone whose
        `credential_status` is currently `ACTIVE` (a suspended preparer cannot
        have returns filed under their name)".
        PRD §2.8: "State preconditions on the target resource come fourth
        (`ERR_INVALID_STATE`)".

        A probation close suspends the preparer with an overdue OPEN
        remediation; filing that preparer's return is then rejected.

        Design: Difficulty/cross_entity_state_dependency/filing_requires_active_preparer
        """
        office = create_office()
        prep1 = create_preparer(office["id"], full_name="P One", tier="ASSOCIATE")
        prep2 = create_preparer(office["id"], full_name="P Two", tier="ASSOCIATE")
        c1, c2 = create_client(), create_client()
        r1 = create_return(c1["id"], office["id"], prep1["id"], components=["1040_SIMPLE"])
        create_return(c2["id"], office["id"], prep2["id"], components=["1040_SIMPLE"])
        get_success_data(api.create_remediation(
            create_remediation_payload(prep1["id"], due_at="2026-09-05T00:00:00Z"), OM))
        set_clock("2026-09-10T00:00:00Z")
        quality_close(office["id"], period_month="2026-09", returns_examined=100,
                      returns_with_defects=25)
        res = api.file_return(r1["id"], OM)
        validate_error(res, "ERR_INVALID_STATE")
        after1 = validate_success(api.get_return(r1["id"], OM), 200)
        assert after1["status"] == "PREPARING"

    def test_active_preparer_still_files_after_probation_close(self, api):
        """PRD §3.2: "the assigned preparer must resolve to someone whose
        `credential_status` is currently `ACTIVE` (a suspended preparer cannot
        have returns filed under their name)".

        The probation close suspends only the preparer with the overdue OPEN
        remediation; the clean preparer's return files normally.

        Design: Difficulty/cross_entity_state_dependency/filing_requires_active_preparer
        """
        office = create_office()
        prep1 = create_preparer(office["id"], full_name="P One", tier="ASSOCIATE")
        prep2 = create_preparer(office["id"], full_name="P Two", tier="ASSOCIATE")
        c1, c2 = create_client(), create_client()
        create_return(c1["id"], office["id"], prep1["id"], components=["1040_SIMPLE"])
        r2 = create_return(c2["id"], office["id"], prep2["id"], components=["1040_SIMPLE"])
        get_success_data(api.create_remediation(
            create_remediation_payload(prep1["id"], due_at="2026-09-05T00:00:00Z"), OM))
        set_clock("2026-09-10T00:00:00Z")
        quality_close(office["id"], period_month="2026-09", returns_examined=100,
                      returns_with_defects=25)
        filed = validate_success(api.file_return(r2["id"], OM), 200)
        assert filed["status"] == "FILED"


class TestResolveRequiresNoticesTerminal:
    def test_resolve_blocked_while_notice_open(self, api):
        """PRD §3.7: "Every linked authority notice must be in a terminal
        state — `PAID`, `ABATED`, or `WITHDRAWN`; a still-`OPEN` notice blocks
        resolution with `ERR_NOTICE_NOT_TERMINAL` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/resolve_requires_notices_terminal
        """
        ctx = setup_claim_in_representing(
            components=["1040_SIMPLE"], product_tier="STANDARD", with_escrow=True,
            notice_overrides={"tax_delta_cents": 1000, "penalty_cents": 0,
                              "issued_at": "2026-09-10T00:00:00Z",
                              "due_at": "2026-10-01T00:00:00Z"},
        )
        res = api.resolve_claim(ctx["claim"]["id"], CM_RESOLVER)
        validate_error(res, "ERR_NOTICE_NOT_TERMINAL")

    def test_resolve_succeeds_after_notice_paid(self, api):
        """PRD §3.7: "Every linked authority notice must be in a terminal
        state — `PAID`, `ABATED`, or `WITHDRAWN`; a still-`OPEN` notice blocks
        resolution with `ERR_NOTICE_NOT_TERMINAL` (HTTP 409)."
        PRD §3.4: "paying on or before `due_at` yields zero days and zero
        interest."

        Once the notice is paid (before its due date, so zero interest), the
        same resolve succeeds.

        Design: Difficulty/cross_entity_state_dependency/resolve_requires_notices_terminal
        """
        ctx = setup_claim_in_representing(
            components=["1040_SIMPLE"], product_tier="STANDARD", with_escrow=True,
            notice_overrides={"tax_delta_cents": 1000, "penalty_cents": 0,
                              "issued_at": "2026-09-10T00:00:00Z",
                              "due_at": "2026-10-01T00:00:00Z"},
        )
        validate_error(api.resolve_claim(ctx["claim"]["id"], CM_RESOLVER), "ERR_NOTICE_NOT_TERMINAL")
        paid = pay_notice(ctx["notice"]["id"])
        assert paid["interest_cents"] == 0
        resolved = resolve_claim(ctx["claim"]["id"])
        assert resolved["status"] == "RESOLVED"


class TestPoaExecuteStateBeforeTemporal:
    def test_revoked_poa_surfaces_invalid_state_not_expired(self, api):
        """PRD §2.8: "State preconditions on the target resource come fourth
        (`ERR_INVALID_STATE`), followed by terminal-state lockdown
        (`ERR_ALREADY_TERMINAL`), then the optimistic-concurrency check
        (`ERR_STALE_VERSION`). Business rules — segregation of duties,
        office-posture gating, POA temporal validity, referential requirements
        such as terminal notices or protection coverage, capacity and window
        constraints, close-period monotonicity, and component-set rules — are
        evaluated next, in the priority order stated alongside each rule in
        §3."

        A POA that is both revoked and past its expiry surfaces the state
        rejection, never the temporal one, and the claim stays ASSIGNED.

        Design: Difficulty/priority_pair_validation_conflict/poa_execute_state_before_temporal
        """
        ctx = setup_claim_in_triage(components=["1040_SIMPLE"], product_tier="STANDARD")
        scope_claim_in_scope(ctx["claim"]["id"], "PREPARER_ERROR")
        agent = create_agent(max_parallel=3)
        assign_agent(ctx["claim"]["id"], agent["id"],
                     window_start="2026-09-12T00:00:00Z", window_end="2026-12-12T00:00:00Z")
        poa = get_success_data(api.create_poa(
            ctx["claim"]["id"], create_poa_payload(agent["id"], expires_at="2026-09-20T00:00:00Z"), CM))
        validate_success(api.revoke_poa(poa["id"], CM), 200)
        set_clock("2026-09-25T00:00:00Z")
        res = api.execute_poa(ctx["claim"]["id"], {"expected_poa_version": poa["version"]}, CM)
        validate_error(res, "ERR_INVALID_STATE")
        claim = validate_success(api.get_claim(ctx["claim"]["id"], CM), 200)
        assert claim["status"] == "ASSIGNED"

    def test_expired_but_draft_poa_surfaces_expired(self, api):
        """PRD §3.6: "the draft's `expires_at` must be strictly later than the
        logical clock, or execution fails with `ERR_POA_EXPIRED` (HTTP 422)".

        A still-DRAFT but expired POA fails the temporal rule only when no
        earlier category (here: state) is violated — confirming the two checks
        are distinct categories ordered per §2.8.

        Design: Difficulty/priority_pair_validation_conflict/poa_execute_state_before_temporal
        """
        ctx = setup_claim_in_triage(components=["1040_SIMPLE"], product_tier="STANDARD")
        scope_claim_in_scope(ctx["claim"]["id"], "PREPARER_ERROR")
        agent = create_agent(max_parallel=3)
        assign_agent(ctx["claim"]["id"], agent["id"],
                     window_start="2026-09-12T00:00:00Z", window_end="2026-12-12T00:00:00Z")
        poa = get_success_data(api.create_poa(
            ctx["claim"]["id"], create_poa_payload(agent["id"], expires_at="2026-09-20T00:00:00Z"), CM))
        set_clock("2026-09-25T00:00:00Z")
        res = api.execute_poa(ctx["claim"]["id"], {"expected_poa_version": poa["version"]}, CM)
        validate_error(res, "ERR_POA_EXPIRED")
        claim = validate_success(api.get_claim(ctx["claim"]["id"], CM), 200)
        assert claim["status"] == "ASSIGNED"


class TestResolveSodBeforeNoticeTerminal:
    def test_scoper_resolve_rejected_before_notice_terminal_check(self, api):
        """PRD §3.7: "A `CaseManager` may resolve a claim in `REPRESENTING`,
        subject to three checks evaluated in order after the global gates: the
        segregation-of-duties rule, the notice-terminal rule, and then the
        payout computation itself."
        PRD §3.7: "Segregation of duties forbids the same operator who scoped
        the claim from resolving it — if the acting `X-User-ID` equals the
        claim's `scoped_by_user_id`, the resolve is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        The scoper resolving while the notice is still OPEN must surface the
        SoD rejection, and the claim stays REPRESENTING.

        Design: Difficulty/priority_pair_validation_conflict/resolve_sod_before_notice_terminal
        """
        ctx = setup_claim_in_representing(
            components=["1040_SIMPLE"], product_tier="STANDARD",
            notice_overrides={"tax_delta_cents": 1000, "penalty_cents": 0},
        )
        res = api.resolve_claim(ctx["claim"]["id"], CM_SCOPER)
        validate_error(res, "ERR_SEGREGATION_OF_DUTIES")
        claim = validate_success(api.get_claim(ctx["claim"]["id"], CM), 200)
        assert claim["status"] == "REPRESENTING"

    def test_other_manager_resolve_reaches_notice_terminal_check(self, api):
        """PRD §3.7: "subject to three checks evaluated in order after the
        global gates: the segregation-of-duties rule, the notice-terminal
        rule, and then the payout computation itself."

        A different case manager passes the SoD check, so the still-OPEN
        notice surfaces `ERR_NOTICE_NOT_TERMINAL` — proving the SoD check ran
        first and passed.

        Design: Difficulty/priority_pair_validation_conflict/resolve_sod_before_notice_terminal
        """
        ctx = setup_claim_in_representing(
            components=["1040_SIMPLE"], product_tier="STANDARD",
            notice_overrides={"tax_delta_cents": 1000, "penalty_cents": 0},
        )
        res = api.resolve_claim(ctx["claim"]["id"], CM_RESOLVER)
        validate_error(res, "ERR_NOTICE_NOT_TERMINAL")
        claim = validate_success(api.get_claim(ctx["claim"]["id"], CM), 200)
        assert claim["status"] == "REPRESENTING"


class TestNoticeTerminalLockdown:
    def test_pay_paid_notice_rejected(self, api):
        """PRD §3.4: "Notices in any terminal state — `PAID`, `ABATED`,
        `WITHDRAWN` — are immutable; further action attempts draw
        `ERR_ALREADY_TERMINAL`."

        Design: Corner/state_machines/notice_pay_from_paid_rejected
        """
        ctx = setup_filed_return(components=["1040_SIMPLE"])
        notice = create_notice(ctx["tax_return"]["id"], tax_delta_cents=1000, penalty_cents=0,
                               issued_at="2026-09-02T00:00:00Z", due_at="2026-10-01T00:00:00Z")
        paid = pay_notice(notice["id"])
        assert paid["status"] == "PAID"
        assert paid["interest_cents"] == 0  # paid before due date
        res = api.pay_notice(notice["id"], OM)
        validate_error(res, "ERR_ALREADY_TERMINAL")
        after = validate_success(api.get_notice(notice["id"], CM), 200)
        assert after["interest_cents"] == 0
        assert after["version"] == paid["version"]


class TestWithdrawLinkedNoticeRejected:
    def test_withdraw_linked_notice_fails(self, api):
        """PRD §3.4: "An `OfficeManager` may instead withdraw an `OPEN`
        notice, moving it to `WITHDRAWN` — but only while the notice's
        `claim_id` is still null; a claim-linked notice must be resolved
        through the claim, not withdrawn, and attempting to withdraw a linked
        notice is rejected with `ERR_INVALID_STATE`."

        Design: Corner/errors/withdraw_linked_notice_rejected
        """
        ctx = setup_claim_in_triage(components=["1040_SIMPLE"], product_tier="STANDARD")
        res = api.withdraw_notice(ctx["notice"]["id"], OM)
        validate_error(res, "ERR_INVALID_STATE")
        after = validate_success(api.get_notice(ctx["notice"]["id"], CM), 200)
        assert after["status"] == "OPEN"


class TestClaimIntakeRequiresProtection:
    def test_intake_without_product_rejected(self, api):
        """PRD §3.5: "Intake enforces three protection prerequisites, all
        surfaced as `ERR_PROTECTION_REQUIRED` (HTTP 422): the return must be
        `FILED`; the notice must be `OPEN` and not already linked to another
        claim; and the return must carry an `ACTIVE` protection product."

        A FILED return with no product fails intake.

        Design: Corner/validations/claim_intake_requires_protection
        """
        ctx = setup_filed_return(components=["1040_SIMPLE"], product_tier=None)
        notice = create_notice(ctx["tax_return"]["id"])
        ret = validate_success(api.get_return(ctx["tax_return"]["id"], CM), 200)
        res = api.create_claim(
            {"return_id": ret["id"], "notice_id": notice["id"],
             "expected_return_version": ret["version"]}, CM)
        validate_error(res, "ERR_PROTECTION_REQUIRED")
