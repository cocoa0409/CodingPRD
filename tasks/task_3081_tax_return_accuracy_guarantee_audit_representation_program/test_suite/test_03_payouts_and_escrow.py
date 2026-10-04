"""Reimbursement payout variants, escrow liability fold, resolve cascades,
and the resolve/reopen escrow invariant.
"""
from test_helpers import (
    TEST_USERS,
    assign_agent,
    create_agent,
    create_client,
    create_escrow,
    create_notice,
    create_office,
    create_preparer,
    create_product,
    create_return,
    draft_and_execute_poa,
    file_return,
    get_success_data,
    make_enrolled_agent_headers,
    open_claim,
    pay_notice,
    resolve_claim,
    scope_claim_in_scope,
    set_clock,
    setup_claim_in_representing,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
OM = TEST_USERS["office_manager_headers"]
CM = TEST_USERS["case_manager_headers"]


def _filed_plus_return_with_paid_notice(api, office, preparer, tax_delta, penalty,
                                        pay_clock, client=None):
    """Build a FILED return (components 1040_ITEMIZED+1040_MULTI_STATE) with a
    PLUS product, a FEDERAL notice due 2026-10-01, and an open claim; then pay
    the notice at the given clock. Returns (client, ret, notice, claim)."""
    client = client or create_client()
    ret = create_return(client["id"], office["id"], preparer["id"],
                        components=["1040_ITEMIZED", "1040_MULTI_STATE"])
    ret = file_return(ret["id"])
    create_product(ret["id"], tier="PLUS")
    notice = create_notice(ret["id"], authority_type="FEDERAL", tax_delta_cents=tax_delta,
                           penalty_cents=penalty, issued_at="2026-09-15T00:00:00Z",
                           due_at="2026-10-01T00:00:00Z")
    claim = open_claim(ret["id"], notice["id"])
    set_clock(pay_clock)
    pay_notice(notice["id"])
    return client, ret, notice, claim


def _drive_to_representing(claim_id, agent_id):
    assign_agent(claim_id, agent_id)
    draft_and_execute_poa(claim_id, agent_id)


class TestPayoutVariantPreparerVsClientDataError:
    def test_preparer_error_payout_full_plus_coverage(self, api):
        """PRD §3.7: "For a `PREPARER_ERROR` claim, `payout_base_cents` covers
        the notice's `tax_delta_cents` in full, `payout_interest_cents` covers
        its `interest_cents` (zero while the notice was still `OPEN`, and
        zeroed entirely if the notice was abated), and `payout_penalty_cents`
        covers its `penalty_cents` only when the claim's product tier is
        `PLUS`".
        PRD §3.4: "For a positive day count, the interest is the notice's
        `tax_delta_cents` multiplied by a daily rate of 0.000273972602739726
        and by the number of days, with the full-precision product rounded
        half-up once to cents."

        tax_delta 38000, penalty 5000, PLUS, 31 days late: interest 323, so
        total 38000 + 323 + 5000 = 43323 and liability 43323 + 38000 = 81323.

        Design: Difficulty/dual_variant_calc/payout_variant_preparer_vs_client_data_error
        """
        office = create_office()
        create_escrow(office["id"])
        preparer = create_preparer(office["id"])
        _, _, notice, claim = _filed_plus_return_with_paid_notice(
            api, office, preparer, 38000, 5000, "2026-11-01T00:00:00Z")
        assert get_success_data(api.get_notice(notice["id"], CM))["interest_cents"] == 323
        scope_claim_in_scope(claim["id"], "PREPARER_ERROR")
        agent = create_agent(max_parallel=5)
        _drive_to_representing(claim["id"], agent["id"])
        resolved = resolve_claim(claim["id"])
        assert resolved["payout_base_cents"] == 38000
        assert resolved["payout_interest_cents"] == 323
        assert resolved["payout_penalty_cents"] == 5000
        assert resolved["payout_total_cents"] == 43323
        assert resolved["final_liability_cents"] == 81323

    def test_client_data_error_payout_interest_only(self, api):
        """PRD §3.7: "For a `CLIENT_DATA_ERROR` claim, the base and penalty
        stay the taxpayer's own liability — `payout_base_cents` and
        `payout_penalty_cents` are both 0 — and only `payout_interest_cents`
        is covered."
        PRD §3.7: "`final_liability_cents` equals `payout_total_cents` plus
        `payout_base_cents` once more".

        Identical figures (tax_delta 38000, penalty 5000, PLUS, interest 323)
        under CLIENT_DATA_ERROR: total 323, liability 323 + 0 = 323.

        Design: Difficulty/dual_variant_calc/payout_variant_preparer_vs_client_data_error
        """
        office = create_office()
        create_escrow(office["id"])
        preparer = create_preparer(office["id"])
        _, _, _, claim = _filed_plus_return_with_paid_notice(
            api, office, preparer, 38000, 5000, "2026-11-01T00:00:00Z")
        scope_claim_in_scope(claim["id"], "CLIENT_DATA_ERROR")
        agent = create_agent(max_parallel=5)
        _drive_to_representing(claim["id"], agent["id"])
        resolved = resolve_claim(claim["id"])
        assert resolved["payout_base_cents"] == 0
        assert resolved["payout_interest_cents"] == 323
        assert resolved["payout_penalty_cents"] == 0
        assert resolved["payout_total_cents"] == 323
        assert resolved["final_liability_cents"] == 323


class TestAccrualVsPayoutLiabilityFold:
    def test_resolve_pins_payout_liability_and_escrow_accrual(self, api):
        """PRD §3.7: "`final_liability_cents` equals `payout_total_cents` plus
        `payout_base_cents` once more: the additional-tax component is counted
        twice in the escrow debit (once as the reimbursement to the taxpayer,
        once as the program's make-whole cost), while interest and penalty
        count once each."
        PRD §3.7: "`expected_accrual_cents` increases by the claim's
        `payout_total_cents` marked up by one tenth — that is, multiplied by
        1.1 and rounded half-up to cents, rounded per claim and then summed."

        tax_delta 50000, penalty 5000, PLUS, interest 424 (31 days): total
        55425, liability 105425, accrual round_half_up(55425 * 1.1) = 60968.

        Design: Difficulty/combinatorial_formula/accrual_vs_payout_liability_fold
        """
        office = create_office()
        escrow = create_escrow(office["id"])
        preparer = create_preparer(office["id"])
        _, _, _, claim = _filed_plus_return_with_paid_notice(
            api, office, preparer, 50000, 5000, "2026-11-01T00:00:00Z")
        scope_claim_in_scope(claim["id"], "PREPARER_ERROR")
        agent = create_agent(max_parallel=3)
        _drive_to_representing(claim["id"], agent["id"])
        resolved = resolve_claim(claim["id"])
        assert resolved["payout_total_cents"] == 55425
        assert resolved["final_liability_cents"] == 105425
        esc = validate_success(api.get_escrow(escrow["id"], ADMIN), 200)
        assert esc["paid_out_cents"] == 105425
        assert esc["expected_accrual_cents"] == 60968

    def test_three_quantities_diverge_by_design(self, api):
        """PRD §3.7: "while interest and penalty count once each. Resolution
        writes this figure onto the claim (it is null until then), completes
        the claim's `ACTIVE` assignment by moving it to `COMPLETED`, and
        debits the office escrow: `paid_out_cents` increases by
        `final_liability_cents`, while `expected_accrual_cents` increases by
        the claim's `payout_total_cents` marked up by one tenth".

        The three pinned quantities from one resolution: payout_total 55425,
        final_liability 105425 (paid_out), expected_accrual 60968.

        Design: Difficulty/combinatorial_formula/accrual_vs_payout_liability_fold
        """
        office = create_office()
        escrow = create_escrow(office["id"])
        preparer = create_preparer(office["id"])
        _, _, _, claim = _filed_plus_return_with_paid_notice(
            api, office, preparer, 50000, 5000, "2026-11-01T00:00:00Z")
        scope_claim_in_scope(claim["id"], "PREPARER_ERROR")
        agent = create_agent(max_parallel=3)
        _drive_to_representing(claim["id"], agent["id"])
        resolved = resolve_claim(claim["id"])
        esc = validate_success(api.get_escrow(escrow["id"], ADMIN), 200)
        quantities = {resolved["payout_total_cents"], esc["paid_out_cents"], esc["expected_accrual_cents"]}
        assert quantities == {55425, 105425, 60968}


class TestResolveCascadeFourHops:
    def test_resolve_completes_assignment_and_releases_capacity(self, api):
        """PRD §3.7: "Resolution writes this figure onto the claim (it is null
        until then), completes the claim's `ACTIVE` assignment by moving it to
        `COMPLETED`, and debits the office escrow".
        PRD §3.6: "The agent's parallel capacity must have room: the count of
        claims currently in `REPRESENTING` under that agent must be below
        their `max_parallel`, or the assignment is rejected with
        `ERR_AGENT_CAPACITY` (HTTP 409)."

        With max_parallel 1 the second claim cannot be assigned while the
        first REPRESENTs; after the first resolves (assignment COMPLETED), the
        second assign succeeds.

        Design: Difficulty/transitive_cascade/resolve_cascade_four_hops
        """
        office = create_office()
        escrow = create_escrow(office["id"])
        preparer = create_preparer(office["id"])
        c1, c2 = create_client(), create_client()
        r1 = file_return(create_return(c1["id"], office["id"], preparer["id"],
                                       components=["1040_ITEMIZED", "1040_MULTI_STATE"])["id"])
        r2 = file_return(create_return(c2["id"], office["id"], preparer["id"],
                                       components=["1040_ITEMIZED", "1040_MULTI_STATE"])["id"])
        create_product(r1["id"], tier="STANDARD")
        create_product(r2["id"], tier="PLUS")
        n1 = create_notice(r1["id"], authority_type="FEDERAL", tax_delta_cents=20000,
                           penalty_cents=5000, issued_at="2026-09-15T00:00:00Z",
                           due_at="2026-10-01T00:00:00Z")
        n2 = create_notice(r2["id"], authority_type="FEDERAL", tax_delta_cents=10000,
                           penalty_cents=1000, issued_at="2026-09-15T00:00:00Z",
                           due_at="2026-10-01T00:00:00Z")
        cl1 = open_claim(r1["id"], n1["id"])
        cl2 = open_claim(r2["id"], n2["id"])
        scope_claim_in_scope(cl1["id"], "PREPARER_ERROR")
        scope_claim_in_scope(cl2["id"], "PREPARER_ERROR")
        agent = create_agent(max_parallel=1)
        asg1, _ = assign_agent(cl1["id"], agent["id"],
                               window_start="2026-10-02T00:00:00Z", window_end="2026-12-02T00:00:00Z")
        draft_and_execute_poa(cl1["id"], agent["id"])
        set_clock("2026-11-01T00:00:00Z")
        pay_notice(n1["id"])
        blocked = api.assign_claim(cl2["id"], {"agent_id": agent["id"],
                                               "window_start": "2026-11-03T00:00:00Z",
                                               "window_end": "2026-12-03T00:00:00Z"}, CM)
        validate_error(blocked, "ERR_AGENT_CAPACITY")

        resolved = resolve_claim(cl1["id"])
        assert resolved["payout_total_cents"] == 20170, "STANDARD: penalty excluded; 20000 + 170 interest"

        assignments, _meta = validate_paginated(api.list_claim_assignments(cl1["id"], CM))
        assert assignments[0]["status"] == "COMPLETED"

        asg2 = validate_success(
            api.assign_claim(cl2["id"], {"agent_id": agent["id"],
                                         "window_start": "2026-11-03T00:00:00Z",
                                         "window_end": "2026-12-03T00:00:00Z"}, CM), 201)
        assert asg2["status"] == "ACTIVE"

        esc = validate_success(api.get_escrow(escrow["id"], ADMIN), 200)
        assert esc["paid_out_cents"] == 40170, "20170 total + 20000 base folded again"
        assert esc["expected_accrual_cents"] == 22187, "round_half_up(20170 * 1.1)"

    def test_resolve_debits_escrow_immediately(self, api):
        """PRD §3.7: "Resolution writes this figure onto the claim (it is null
        until then), completes the claim's `ACTIVE` assignment by moving it to
        `COMPLETED`, and debits the office escrow: `paid_out_cents` increases
        by `final_liability_cents`, while `expected_accrual_cents` increases
        by the claim's `payout_total_cents` marked up by one tenth".

        The resolve response already carries the final payout and the escrow
        GET in the same test shows the debit — consistency is immediate.

        Design: Difficulty/transitive_cascade/resolve_cascade_four_hops
        """
        office = create_office()
        escrow = create_escrow(office["id"])
        preparer = create_preparer(office["id"])
        client = create_client()
        r1 = file_return(create_return(client["id"], office["id"], preparer["id"],
                                       components=["1040_ITEMIZED", "1040_MULTI_STATE"])["id"])
        create_product(r1["id"], tier="STANDARD")
        n1 = create_notice(r1["id"], authority_type="FEDERAL", tax_delta_cents=20000,
                           penalty_cents=5000, issued_at="2026-09-15T00:00:00Z",
                           due_at="2026-10-01T00:00:00Z")
        cl1 = open_claim(r1["id"], n1["id"])
        scope_claim_in_scope(cl1["id"], "PREPARER_ERROR")
        agent = create_agent(max_parallel=1)
        asg1, _ = assign_agent(cl1["id"], agent["id"],
                               window_start="2026-10-02T00:00:00Z", window_end="2026-12-02T00:00:00Z")
        draft_and_execute_poa(cl1["id"], agent["id"])
        set_clock("2026-11-01T00:00:00Z")
        pay_notice(n1["id"])
        resolved = resolve_claim(cl1["id"])
        assert resolved["final_liability_cents"] == 40170
        esc = validate_success(api.get_escrow(escrow["id"], ADMIN), 200)
        assert esc["paid_out_cents"] == 40170
        assert esc["expected_accrual_cents"] == 22187


class TestClaimResolveReopenEscrowInvariant:
    def test_resolve_then_reopen_conserves_paid_out(self, api):
        """PRD §3.7: "reopening credits the escrow by subtracting the claim's
        retained `final_liability_cents` from `paid_out_cents` (with an escrow
        `version` bump) while leaving `expected_accrual_cents` untouched,
        keeps `final_liability_cents` on the claim for audit, and moves the
        claim to `REOPENED`."

        Resolve then reopen returns paid_out to 0 while the historical
        accrual keeps its increment.

        Design: Difficulty/compensating_invariant/claim_resolve_reopen_escrow_invariant
        """
        office = create_office()
        escrow = create_escrow(office["id"])
        preparer = create_preparer(office["id"])
        _, _, _, claim = _filed_plus_return_with_paid_notice(
            api, office, preparer, 50000, 5000, "2026-11-01T00:00:00Z")
        scope_claim_in_scope(claim["id"], "PREPARER_ERROR")
        agent = create_agent(max_parallel=3)
        _drive_to_representing(claim["id"], agent["id"])
        resolve_claim(claim["id"])
        reopened = validate_success(api.reopen_claim(claim["id"], CM), 200)
        assert reopened["status"] == "REOPENED"
        assert reopened["final_liability_cents"] == 105425, "retained for audit"
        esc = validate_success(api.get_escrow(escrow["id"], ADMIN), 200)
        assert esc["paid_out_cents"] == 0
        assert esc["expected_accrual_cents"] == 60968

    def test_accrual_is_historical_not_credited_back(self, api):
        """PRD §3.7: "`expected_accrual_cents` is the running per-claim sum
        just described across all of the office's resolved claims, and it is
        historical: reopening never reduces it. `paid_out_cents`, by contrast,
        is the live cash view."

        Design: Difficulty/compensating_invariant/claim_resolve_reopen_escrow_invariant
        """
        office = create_office()
        escrow = create_escrow(office["id"])
        preparer = create_preparer(office["id"])
        _, _, _, claim = _filed_plus_return_with_paid_notice(
            api, office, preparer, 50000, 5000, "2026-11-01T00:00:00Z")
        scope_claim_in_scope(claim["id"], "PREPARER_ERROR")
        agent = create_agent(max_parallel=3)
        _drive_to_representing(claim["id"], agent["id"])
        resolve_claim(claim["id"])
        mid = validate_success(api.get_escrow(escrow["id"], ADMIN), 200)
        assert mid["paid_out_cents"] == 105425
        assert mid["expected_accrual_cents"] == 60968
        validate_success(api.reopen_claim(claim["id"], CM), 200)
        esc = validate_success(api.get_escrow(escrow["id"], ADMIN), 200)
        assert esc["paid_out_cents"] == 0, "live cash view is credited back"
        assert esc["expected_accrual_cents"] == 60968, "historical accrual is never reduced"


class TestStandardTierPenaltyNotCovered:
    def test_standard_excludes_penalty(self, api):
        """PRD §3.7: "`payout_penalty_cents` covers its `penalty_cents` only
        when the claim's product tier is `PLUS` — a `STANDARD` product pays no
        penalty."
        PRD §3.4: "For a positive day count, the interest is the notice's
        `tax_delta_cents` multiplied by a daily rate of 0.000273972602739726
        and by the number of days, with the full-precision product rounded
        half-up once to cents."

        tax_delta 1000, penalty 100, paid 10 days late -> interest 3; base and
        interest covered, penalty not; liability folds the base twice.

        Design: Corner/calculations/standard_tier_penalty_not_covered
        """
        ctx = setup_claim_in_representing(
            components=["1040_SIMPLE"], product_tier="STANDARD", with_escrow=True,
            notice_overrides={"tax_delta_cents": 1000, "penalty_cents": 100,
                              "issued_at": "2026-09-10T00:00:00Z",
                              "due_at": "2026-10-01T00:00:00Z"},
        )
        set_clock("2026-10-11T00:00:00Z")
        paid = pay_notice(ctx["notice"]["id"])
        assert paid["interest_cents"] == 3
        resolved = resolve_claim(ctx["claim"]["id"])
        assert resolved["payout_base_cents"] == 1000
        assert resolved["payout_interest_cents"] == 3
        assert resolved["payout_penalty_cents"] == 0
        assert resolved["payout_total_cents"] == 1003
        assert resolved["final_liability_cents"] == 2003


class TestNoticeAbateZeroesInterestAndPenalty:
    def test_abatement_zeroes_and_recomputes_payout(self, api):
        """PRD §3.4: "An enrolled agent who holds the `ACTIVE` assignment on a
        claim in `REPRESENTING` may win an abatement on that claim's linked
        notice: the notice's `interest_cents` and `penalty_cents` are zeroed
        (the authority granted relief), the notice moves from `OPEN` to
        `ABATED`, and the linked claim's payout figures recompute."
        PRD §3.7: "`final_liability_cents` equals `payout_total_cents` plus
        `payout_base_cents` once more".

        PLUS product, tax_delta 1000, penalty 100: after abatement the payout
        is base-only (1000) and the liability folds the base twice (2000).

        Design: Corner/cross_cutting_complexity_layers/notice_abate_zeroes_interest_and_penalty
        """
        ctx = setup_claim_in_representing(
            components=["1040_SIMPLE"], product_tier="PLUS", with_escrow=True,
            notice_overrides={"tax_delta_cents": 1000, "penalty_cents": 100,
                              "issued_at": "2026-09-10T00:00:00Z",
                              "due_at": "2026-10-01T00:00:00Z"},
        )
        set_clock("2026-10-11T00:00:00Z")
        abated = validate_success(
            api.abate_notice(ctx["notice"]["id"], make_enrolled_agent_headers(ctx["agent"]["id"])), 200)
        assert abated["status"] == "ABATED"
        assert abated["interest_cents"] == 0
        assert abated["penalty_cents"] == 0
        resolved = resolve_claim(ctx["claim"]["id"])
        assert resolved["payout_total_cents"] == 1000, "base only after abatement"
        assert resolved["final_liability_cents"] == 2000


class TestImmediateConsistencyResolveEscrowVisible:
    def test_resolve_values_visible_immediately(self, api):
        """PRD §3.7: "Resolution writes this figure onto the claim (it is null
        until then), completes the claim's `ACTIVE` assignment by moving it to
        `COMPLETED`, and debits the office escrow: `paid_out_cents` increases
        by `final_liability_cents`, while `expected_accrual_cents` increases
        by the claim's `payout_total_cents` marked up by one tenth".

        The resolve response carries the final payout values and the escrow
        read in the same test shows the debit — no waiting.

        Design: Corner/consistency_model/immediate_consistency_resolve_escrow_visible
        """
        ctx = setup_claim_in_representing(
            components=["1040_SIMPLE"], product_tier="STANDARD", with_escrow=True,
            notice_overrides={"tax_delta_cents": 1000, "penalty_cents": 100,
                              "issued_at": "2026-09-02T00:00:00Z",
                              "due_at": "2026-10-01T00:00:00Z"},
        )
        pay_notice(ctx["notice"]["id"])  # default clock, before due date: interest 0
        resolved = resolve_claim(ctx["claim"]["id"])
        assert resolved["payout_total_cents"] == 1000, "interest 0, STANDARD penalty excluded"
        assert resolved["final_liability_cents"] == 2000
        esc = validate_success(api.get_escrow(ctx["escrow"]["id"], ADMIN), 200)
        assert esc["paid_out_cents"] == 2000
