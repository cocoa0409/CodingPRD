"""Dispute tests: evidence/reopen cycle, adjust cascade, window boundaries,
priority pairs, resolution rules, ownership, and lifecycle freezing."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    create_partner,
    setup_active_contract,
    setup_finalized_period,
    setup_dispute_under_review,
    set_clock,
    make_managing_partner_headers,
    TEST_USERS,
)

HR = TEST_USERS["hr_recruiter_headers"]
CONTROLLER = TEST_USERS["corporate_controller_headers"]
AUDITOR = TEST_USERS["operations_auditor_headers"]


def test_dispute_evidence_loop_and_period_reopen_cycle(api):
    """PRD §3.9: "This evidence loop is cyclic: multiple rounds of request and
    submission are allowed."
    PRD §3.6: "When a dispute on the period resolves as RESOLVED_ADJUSTED
    (§3.9), the period moves from FINALIZED to REOPENED and a new line item
    appears on it automatically: category ADJUSTMENT, amount_cents equal to
    the dispute's adjustment_cents, and entry_status already FINALIZED. From
    REOPENED, the OperationsAuditor re-runs the provisional computation, which
    now includes the adjustment line, and the period returns to COMPUTED —
    ready for a fresh finalization."
    PRD §3.6: "partner_share_cents — the tiered managing partner share. The
    tiers are marginal, not average-rate: 8% of the first 5,000,000 cents of
    final profit, 10% of the next band up to 10,000,000 cents, and 12% of
    everything above 10,000,000 cents."

    Design: Difficulty/non_linear_state_machine/dispute_evidence_loop_and_period_reopen_cycle
    """
    from test_helpers import create_open_period, post_line_item, compute_period, finalize_period

    setup = setup_finalized_period(
        line_items=[("REVENUE", 8000000), ("LABOR", 2000000)],
        clock_at="2027-04-15T00:00:00Z",
    )
    partner_headers = make_managing_partner_headers(setup["partner"]["id"])
    dispute = validate_success(
        api.create_dispute_case(
            {"period_id": setup["period"]["id"], "claim_text": "Labor overstated"},
            partner_headers,
        ),
        expected_status=201,
    )
    for evidence in ("Payroll register attached", "Second register"):
        validate_success(api.request_evidence(dispute["id"], CONTROLLER))
        validate_success(api.submit_evidence(dispute["id"], {"evidence_text": evidence}, partner_headers))
    resolved = validate_success(
        api.resolve_dispute(
            dispute["id"], {"outcome": "ADJUSTED", "adjustment_cents": 500000}, CONTROLLER
        )
    )
    assert resolved["status"] == "RESOLVED_ADJUSTED"
    assert resolved["adjustment_cents"] == 500000

    period = validate_success(api.get_profit_period(setup["period"]["id"], AUDITOR))
    assert period["status"] == "REOPENED"
    compute_period(setup["period"]["id"])
    finalized = finalize_period(setup["period"]["id"])
    assert finalized["final_distributable_profit_cents"] == 6500000
    assert finalized["partner_share_cents"] == 550000  # 400000 + 150000


def test_evidence_round_returns_dispute_to_review(api):
    """PRD §3.9: "The filing partner answers by submitting evidence — a
    request carrying evidence_text, permitted only when X-User-ID matches the
    dispute's filed_by_partner_id (otherwise ERR_DISPUTE_NOT_OWNED) — which
    returns the dispute to UNDER_REVIEW. This evidence loop is cyclic:
    multiple rounds of request and submission are allowed."

    Design: Difficulty/non_linear_state_machine/dispute_evidence_loop_and_period_reopen_cycle
    """
    setup = setup_dispute_under_review(
        line_items=[("REVENUE", 5000000)],
        clock_at="2027-04-15T00:00:00Z",
    )
    dispute_id = setup["dispute"]["id"]
    requested = validate_success(api.request_evidence(dispute_id, CONTROLLER))
    assert requested["status"] == "EVIDENCE_REQUESTED"
    answered = validate_success(
        api.submit_evidence(
            dispute_id,
            {"evidence_text": "Payroll register attached"},
            make_managing_partner_headers(setup["partner"]["id"]),
        )
    )
    assert answered["status"] == "UNDER_REVIEW"
    requested2 = validate_success(api.request_evidence(dispute_id, CONTROLLER))
    assert requested2["status"] == "EVIDENCE_REQUESTED"


def test_dispute_adjusted_cascades_period_reopen_and_adjustment_line(api):
    """PRD §3.9: "Resolving as ADJUSTED requires a positive adjustment_cents
    ... and moves the dispute to RESOLVED_ADJUSTED: the adjustment is recorded
    on the dispute, and the cascade of §3.6 fires, reopening the period from
    FINALIZED to REOPENED and creating the finalized ADJUSTMENT line item
    carrying the adjustment amount."
    PRD §3.6: "When a dispute on the period resolves as RESOLVED_ADJUSTED
    (§3.9), the period moves from FINALIZED to REOPENED and a new line item
    appears on it automatically: category ADJUSTMENT, amount_cents equal to
    the dispute's adjustment_cents, and entry_status already FINALIZED."

    Design: Difficulty/transitive_cascade/dispute_adjusted_cascades_period_reopen_and_adjustment_line
    """
    setup = setup_finalized_period(
        line_items=[("REVENUE", 7000000), ("LABOR", 2000000)],
        clock_at="2027-04-15T00:00:00Z",
    )
    dispute = validate_success(
        api.create_dispute_case(
            {"period_id": setup["period"]["id"], "claim_text": "Revenue understated"},
            make_managing_partner_headers(setup["partner"]["id"]),
        ),
        expected_status=201,
    )
    resolved = validate_success(
        api.resolve_dispute(
            dispute["id"], {"outcome": "ADJUSTED", "adjustment_cents": 300000}, CONTROLLER
        )
    )
    assert resolved["status"] == "RESOLVED_ADJUSTED"
    period = validate_success(api.get_profit_period(setup["period"]["id"], AUDITOR))
    assert period["status"] == "REOPENED"
    # The reopen does not silently recompute: final figure still 5000000.
    assert period["final_distributable_profit_cents"] == 5000000
    rows, _ = validate_paginated(
        api.list_line_items(setup["period"]["id"], AUDITOR, params={"category": "ADJUSTMENT"})
    )
    assert len(rows) == 1
    assert rows[0]["amount_cents"] == 300000
    assert rows[0]["entry_status"] == "FINALIZED"


def test_adjusted_resolution_synthesizes_adjustment_line_item(api):
    """PRD §3.6: "When a dispute on the period resolves as RESOLVED_ADJUSTED
    (§3.9), the period moves from FINALIZED to REOPENED and a new line item
    appears on it automatically: category ADJUSTMENT, amount_cents equal to
    the dispute's adjustment_cents, and entry_status already FINALIZED."
    PRD §3.9: "Resolving as ADJUSTED requires a positive adjustment_cents ...
    and moves the dispute to RESOLVED_ADJUSTED: the adjustment is recorded on
    the dispute, and the cascade of §3.6 fires, reopening the period from
    FINALIZED to REOPENED and creating the finalized ADJUSTMENT line item
    carrying the adjustment amount."

    Design: Difficulty/transitive_cascade/dispute_adjusted_cascades_period_reopen_and_adjustment_line
    """
    setup = setup_dispute_under_review(
        line_items=[("REVENUE", 5000000)],
        clock_at="2027-04-15T00:00:00Z",
    )
    resolved = validate_success(
        api.resolve_dispute(
            setup["dispute"]["id"],
            {"outcome": "ADJUSTED", "adjustment_cents": 250000},
            CONTROLLER,
        )
    )
    assert resolved["status"] == "RESOLVED_ADJUSTED"
    assert resolved["adjustment_cents"] == 250000
    period = validate_success(api.get_profit_period(setup["period"]["id"], AUDITOR))
    assert period["status"] == "REOPENED"
    rows, meta = validate_paginated(
        api.list_line_items(setup["period"]["id"], AUDITOR, params={"category": "ADJUSTMENT"})
    )
    assert meta["total_count"] == 1
    assert rows[0]["amount_cents"] == 250000
    assert rows[0]["entry_status"] == "FINALIZED"


def test_duplicate_open_dispute_rejected_while_window_open(api):
    """PRD §3.9: "and a period may host only one open dispute at a time, so a
    filing while another dispute on the period sits in SUBMITTED,
    UNDER_REVIEW, EVIDENCE_REQUESTED, or ESCALATED is rejected with
    ERR_DUPLICATE_OPEN_DISPUTE."

    Design: Difficulty/priority_pair_validation_conflict/temporal_dispute_window_beats_referential_duplicate_dispute
    """
    setup = setup_dispute_under_review(
        line_items=[("REVENUE", 8000000)],
        clock_at="2027-04-15T00:00:00Z",
    )
    set_clock("2027-05-10T00:00:00Z")  # well inside the dispute window
    resp = api.create_dispute_case(
        {"period_id": setup["period"]["id"], "claim_text": "Duplicate while open"},
        make_managing_partner_headers(setup["partner"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_OPEN_DISPUTE)


def test_partial_buy_in_funding_fires_fiscal_incomplete(api):
    """PRD §3.3: "The fiscal check follows: if the escrow is greater than zero
    but still below buy_in_required_cents, activation is rejected with
    ERR_BUY_IN_INCOMPLETE."

    Design: Difficulty/priority_pair_validation_conflict/state_gate_beats_fiscal_buy_in_incomplete
    """
    from test_helpers import create_partner, create_active_restaurant, create_draft_contract, submit_contract, fund_contract

    set_clock("2026-09-01T00:00:00Z")
    partner = create_partner()
    restaurant = create_active_restaurant()
    contract = create_draft_contract(partner["id"], restaurant["id"])
    submit_contract(contract["id"])
    fund_contract(contract["id"], partner["id"], 1000000)  # 0 < escrow < 2500000
    resp = api.activate_contract(contract["id"], CONTROLLER)
    validate_error(resp, ApiErrorId.ERR_BUY_IN_INCOMPLETE)
    fetched = validate_success(api.get_contract(contract["id"], CONTROLLER))
    assert fetched["status"] == "PENDING_FUNDING"


def test_temporal_dispute_window_beats_referential_duplicate_dispute(api):
    """PRD §2.5 item 6: "Temporal checks run before aggregate and capacity
    checks; in particular, when a dispute filing is both late and duplicative,
    ERR_DISPUTE_WINDOW_CLOSED is returned rather than
    ERR_DUPLICATE_OPEN_DISPUTE."
    PRD §3.9: "Filing is closed once the logical clock passes the period's
    dispute_deadline — 30 days after finalized_at — with
    ERR_DISPUTE_WINDOW_CLOSED; and a period may host only one open dispute at
    a time, so a filing while another dispute on the period sits in SUBMITTED,
    UNDER_REVIEW, EVIDENCE_REQUESTED, or ESCALATED is rejected with
    ERR_DUPLICATE_OPEN_DISPUTE."

    Design: Difficulty/priority_pair_validation_conflict/temporal_dispute_window_beats_referential_duplicate_dispute
    """
    setup = setup_dispute_under_review(
        line_items=[("REVENUE", 8000000)],
        clock_at="2027-04-15T00:00:00Z",
    )
    set_clock("2027-06-10T00:00:00Z")  # past 2027-04-15 + 30 days
    resp = api.create_dispute_case(
        {"period_id": setup["period"]["id"], "claim_text": "Second dispute — too late AND duplicate"},
        make_managing_partner_headers(setup["partner"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED)
    dispute = validate_success(api.get_dispute_case(setup["dispute"]["id"], CONTROLLER))
    assert dispute["status"] == "UNDER_REVIEW"
    _, meta = validate_paginated(
        api.list_dispute_cases(CONTROLLER, params={"period_id": setup["period"]["id"]})
    )
    assert meta["total_count"] == 1


def test_state_gate_beats_fiscal_buy_in_incomplete(api):
    """PRD §3.3: "The state gate fires first: if buy_in_escrow_cents is zero,
    activation is rejected with ERR_CONTRACT_NOT_FUNDABLE. The fiscal check
    follows: if the escrow is greater than zero but still below
    buy_in_required_cents, activation is rejected with ERR_BUY_IN_INCOMPLETE."

    Design: Difficulty/priority_pair_validation_conflict/state_gate_beats_fiscal_buy_in_incomplete
    """
    from test_helpers import create_partner, create_active_restaurant, create_draft_contract, submit_contract

    set_clock("2026-09-01T00:00:00Z")
    partner = create_partner()
    restaurant = create_active_restaurant()
    contract = create_draft_contract(partner["id"], restaurant["id"])
    submit_contract(contract["id"])
    resp = api.activate_contract(contract["id"], CONTROLLER)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_FUNDABLE)
    fetched = validate_success(api.get_contract(contract["id"], CONTROLLER))
    assert fetched["status"] == "PENDING_FUNDING"


def test_dispute_resolve_adjusted_requires_positive_adjustment(api):
    """PRD §3.9: "Resolving as ADJUSTED requires a positive adjustment_cents
    — omitting it or supplying a non-positive value is rejected with
    ERR_ADJUSTMENT_REQUIRED ..."
    PRD §3.9: "Resolving as UPHELD moves the dispute to RESOLVED_UPHELD and
    leaves the profit period untouched — the original computation stands."

    Design: Corner/validations/dispute_resolve_adjusted_requires_positive_adjustment
    """
    setup = setup_dispute_under_review(
        line_items=[("REVENUE", 5000000)],
        clock_at="2027-04-15T00:00:00Z",
    )
    resp = api.resolve_dispute(
        setup["dispute"]["id"], {"outcome": "ADJUSTED", "adjustment_cents": 0}, CONTROLLER
    )
    validate_error(resp, ApiErrorId.ERR_ADJUSTMENT_REQUIRED)
    dispute = validate_success(api.get_dispute_case(setup["dispute"]["id"], CONTROLLER))
    assert dispute["status"] == "UNDER_REVIEW"
    resolved = validate_success(
        api.resolve_dispute(setup["dispute"]["id"], {"outcome": "UPHELD"}, CONTROLLER)
    )
    assert resolved["status"] == "RESOLVED_UPHELD"
    period = validate_success(api.get_profit_period(setup["period"]["id"], AUDITOR))
    assert period["status"] == "FINALIZED"
    rows, meta = validate_paginated(
        api.list_line_items(setup["period"]["id"], AUDITOR, params={"category": "ADJUSTMENT"})
    )
    assert meta["total_count"] == 0


def test_renewal_and_departure_blocked_by_open_dispute(api):
    """PRD §3.4: "The offer is blocked while any dispute on any profit period
    of the contract's restaurant sits in SUBMITTED, UNDER_REVIEW,
    EVIDENCE_REQUESTED, or ESCALATED; the rejection is
    ERR_RENEWAL_BLOCKED_BY_OPEN_DISPUTE."
    PRD §3.4: "Like renewal, departure is blocked while any open dispute
    exists on the restaurant's periods, with
    ERR_DEPARTURE_BLOCKED_BY_OPEN_DISPUTE."
    PRD §3.9: "Resolving as UPHELD moves the dispute to RESOLVED_UPHELD and
    leaves the profit period untouched — the original computation stands."

    Design: Corner/validations/renewal_and_departure_blocked_by_open_dispute
    """
    setup = setup_dispute_under_review(
        line_items=[("REVENUE", 5000000)],
        clock_at="2027-04-15T00:00:00Z",
    )
    resp_renewal = api.offer_renewal(setup["contract"]["id"], CONTROLLER)
    validate_error(resp_renewal, ApiErrorId.ERR_RENEWAL_BLOCKED_BY_OPEN_DISPUTE)
    resp_depart = api.depart_contract(
        setup["contract"]["id"], make_managing_partner_headers(setup["partner"]["id"])
    )
    validate_error(resp_depart, ApiErrorId.ERR_DEPARTURE_BLOCKED_BY_OPEN_DISPUTE)
    validate_success(
        api.resolve_dispute(setup["dispute"]["id"], {"outcome": "UPHELD"}, CONTROLLER)
    )
    offered = validate_success(api.offer_renewal(setup["contract"]["id"], CONTROLLER))
    assert offered["status"] == "RENEWAL_OFFERED"


def test_period_lock_blocked_by_open_dispute(api):
    """PRD §3.6: "A CorporateController locks a FINALIZED period, but only
    while no dispute on the period sits in SUBMITTED, UNDER_REVIEW,
    EVIDENCE_REQUESTED, or ESCALATED — otherwise the lock is rejected with
    ERR_OPEN_DISPUTE_BLOCKS_LOCK."
    PRD §3.9: "Alternatively, the filing partner may withdraw a dispute while
    it is in SUBMITTED, UNDER_REVIEW, or EVIDENCE_REQUESTED — guarded by the
    same ownership check (ERR_DISPUTE_NOT_OWNED) — moving it to WITHDRAWN."

    Design: Corner/validations/period_lock_blocked_by_open_dispute
    """
    setup = setup_dispute_under_review(
        line_items=[("REVENUE", 5000000)],
        clock_at="2027-04-15T00:00:00Z",
    )
    resp = api.lock_period(setup["period"]["id"], CONTROLLER)
    validate_error(resp, ApiErrorId.ERR_OPEN_DISPUTE_BLOCKS_LOCK)
    period = validate_success(api.get_profit_period(setup["period"]["id"], AUDITOR))
    assert period["status"] == "FINALIZED"
    validate_success(
        api.withdraw_dispute(
            setup["dispute"]["id"], make_managing_partner_headers(setup["partner"]["id"])
        )
    )
    locked = validate_success(api.lock_period(setup["period"]["id"], CONTROLLER))
    assert locked["status"] == "LOCKED"


def test_dispute_window_boundary_inclusive_at_deadline(api):
    """PRD §3.6: "Finalization also stamps finalized_at with the logical clock
    and computes dispute_deadline as exactly 30 days after finalized_at;
    disputes are accepted while the logical clock is on or before the
    deadline."
    PRD §3.9: "Filing is closed once the logical clock passes the period's
    dispute_deadline — 30 days after finalized_at — with
    ERR_DISPUTE_WINDOW_CLOSED ..."

    Design: Corner/validations/dispute_window_boundary_inclusive_at_deadline
    """
    setup = setup_finalized_period(
        line_items=[("REVENUE", 5000000)],
        clock_at="2027-04-15T00:00:00Z",
    )
    set_clock("2027-05-15T00:00:00Z")  # exactly finalized_at + 30 days
    dispute = validate_success(
        api.create_dispute_case(
            {"period_id": setup["period"]["id"], "claim_text": "Filed at the deadline"},
            make_managing_partner_headers(setup["partner"]["id"]),
        ),
        expected_status=201,
    )
    validate_success(
        api.withdraw_dispute(
            dispute["id"], make_managing_partner_headers(setup["partner"]["id"])
        )
    )
    set_clock("2027-05-16T00:00:00Z")  # one day late
    resp = api.create_dispute_case(
        {"period_id": setup["period"]["id"], "claim_text": "One day late"},
        make_managing_partner_headers(setup["partner"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED)


def test_dispute_actions_enforce_filer_ownership(api):
    """PRD §3.9: "The filing partner answers by submitting evidence — a
    request carrying evidence_text, permitted only when X-User-ID matches the
    dispute's filed_by_partner_id (otherwise ERR_DISPUTE_NOT_OWNED) — which
    returns the dispute to UNDER_REVIEW."
    PRD §3.9: "Alternatively, the filing partner may withdraw a dispute while
    it is in SUBMITTED, UNDER_REVIEW, or EVIDENCE_REQUESTED — guarded by the
    same ownership check (ERR_DISPUTE_NOT_OWNED) — moving it to WITHDRAWN."

    Design: Corner/errors/dispute_actions_enforce_filer_ownership
    """
    other = create_partner(full_name="Otto Ther", email="ot@x.com")
    setup = setup_dispute_under_review(
        line_items=[("REVENUE", 5000000)],
        clock_at="2027-04-15T00:00:00Z",
    )
    validate_success(api.request_evidence(setup["dispute"]["id"], CONTROLLER))
    resp_evidence = api.submit_evidence(
        setup["dispute"]["id"],
        {"evidence_text": "Not the filer"},
        make_managing_partner_headers(other["id"]),
    )
    validate_error(resp_evidence, ApiErrorId.ERR_DISPUTE_NOT_OWNED)
    resp_withdraw = api.withdraw_dispute(
        setup["dispute"]["id"], make_managing_partner_headers(other["id"])
    )
    validate_error(resp_withdraw, ApiErrorId.ERR_DISPUTE_NOT_OWNED)
    dispute = validate_success(api.get_dispute_case(setup["dispute"]["id"], CONTROLLER))
    assert dispute["status"] == "EVIDENCE_REQUESTED"
