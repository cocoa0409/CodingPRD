"""Certainty holds, the security cascade, deadline guards and line lockdown (PRD §3.4, §3.5, §3.7).

Queue B — the second half of the ``state_machines`` corner index: the contract
certainty checkpoint freezes outbound money and nothing else, suspending a
market unwinds its line back up through layer and program, the response
deadline is a closed bound on quoting while the sweep touches no compound
status, the four documents file in exactly one order, and a ``BOUND`` or
already-``RELEASED`` signing line is locked out of release.
"""
from test_helpers import (
    CLOCK,
    COMPLIANCE,
    LEAD,
    ApiErrorId,
    api_client,
    assert_append_only_fields,
    assert_instant_equals,
    assert_is_null,
    assert_money_equals,
    assert_pct_equals,
    assert_status,
    book_transaction,
    approve_transaction,
    acknowledge_disclosure,
    bind_program,
    create_contract_document_payload,
    create_market_submission_payload,
    create_quote_payload,
    documentation_checkpoint,
    execute_contract,
    file_document,
    make_reinsurer_underwriter_headers,
    market_sweep,
    place_lines,
    read_layer,
    read_market_submission,
    read_program,
    read_quote,
    read_reinsurer,
    read_signing_line,
    read_transaction,
    refresh,
    release_line,
    send_submission,
    set_clock,
    settle_cedent_receipt,
    setup_bound_program,
    setup_program_in_market,
    suspend_market,
    quote_on,
    validate_error,
    validate_paginated,
)

# The certainty window of the canonical program: inception 2026-01-01 plus the
# thirty-day constant, so the deadline is 2026-01-31 and 2026-02-01 is the first
# instant strictly past it.
EARLY_CHECKPOINT_CLOCK = "2026-01-05T00:00:00.000Z"
PAST_DEADLINE_CLOCK = "2026-02-01T00:00:00.000Z"

# The three movements booked at 2026-01-05 against the bound program: an inflow
# already settled, an inflow still pending, and the one outflow the breach is
# entitled to freeze.
SETTLED_RECEIPT_MINOR = 100_000_000
PENDING_RECEIPT_MINOR = 20_000_000
PENDING_REMITTANCE_MINOR = 50_000_000

# Two markets each able to carry its whole line on a 1,000,000,000 CAT layer;
# only Alpha may lead.
TWO_MARKET_SPECS = [
    {
        "name": "Alpha Re",
        "max_line_pct": 100.0000,
        "lead_authorised": True,
        "capacity_limit_minor": 1_000_000_000,
    },
    {
        "name": "Bravo Re",
        "max_line_pct": 100.0000,
        "lead_authorised": False,
        "capacity_limit_minor": 1_000_000_000,
    },
]

# A third market for the oversubscription that has to be handed back.
THREE_MARKET_SPECS = TWO_MARKET_SPECS + [
    {
        "name": "Charlie Re",
        "max_line_pct": 100.0000,
        "lead_authorised": False,
        "capacity_limit_minor": 1_000_000_000,
    }
]

# Both submissions of the quoting-deadline chain fall due on the same instant,
# and the millisecond after it is the first clock that is past the deadline.
RESPONSE_DEADLINE = CLOCK["RESPONSE_DEADLINE"]
ONE_MS_PAST_DEADLINE = "2026-02-01T00:00:00.001Z"

# The four documents in the only order the chain accepts.
DOCUMENT_CHAIN = ["SLIP", "WORDING_DRAFT", "AGREED_WORDING", "EXECUTED_CONTRACT"]


def _bound_program_at_slip_issued(approve_remittance: bool = False):
    """A BOUND program at SLIP_ISSUED holding a settled receipt, a pending receipt and a remittance."""
    ctx = setup_bound_program()
    program_id = ctx["program"]["id"]
    set_clock(EARLY_CHECKPOINT_CLOCK)
    ctx["slip"] = file_document(program_id, "SLIP")
    ctx["settled_receipt"] = settle_cedent_receipt(program_id, SETTLED_RECEIPT_MINOR)
    ctx["pending_receipt"] = book_transaction(
        program_id, "CEDENT_RECEIPT", PENDING_RECEIPT_MINOR
    )
    ctx["remittance"] = book_transaction(
        program_id,
        "REINSURER_REMITTANCE",
        PENDING_REMITTANCE_MINOR,
        signing_line_id=ctx["signing_lines"][0]["id"],
    )
    if approve_remittance:
        ctx["remittance"] = approve_transaction(ctx["remittance"]["id"])
    return refresh(ctx)


def test_a_checkpoint_before_the_certainty_deadline_is_refused_and_freezes_nothing():
    """At 2026-01-05 the 2026-01-31 deadline has not passed, so the checkpoint refuses.

    PRD: "The checkpoint requires the current logical clock to be **strictly
    after** the deadline — landing exactly on the deadline instant is not yet a
    breach — and requires the `documentation_status` to be `NOT_STARTED`,
    `SLIP_ISSUED` or `WORDING_DRAFTED`, since a program that already has agreed
    wording, or is already in breach, has nothing to test."

    Design: Corner/state_machines/the_documentation_checkpoint_holds_only_remittance_type_transactions_not_receipts
    """
    ctx = _bound_program_at_slip_issued()
    assert_instant_equals(
        ctx["program"]["contract_certainty_deadline"],
        CLOCK["CERTAINTY_DEADLINE"],
        "contract_certainty_deadline",
    )

    response = api_client.documentation_checkpoint(ctx["program"]["id"], COMPLIANCE)
    validate_error(response, ApiErrorId.ERR_CERTAINTY_NOT_BREACHED.value)

    program = read_program(ctx["program"]["id"])
    assert_status(program, "documentation_status", "SLIP_ISSUED")
    assert_status(program, "placement_status", "BOUND")
    for txn in (ctx["remittance"], ctx["pending_receipt"]):
        row = read_transaction(txn["id"])
        assert_status(row, "status", "PENDING")
        assert_is_null(row, "hold_reason")
    assert_money_equals(
        program["fiduciary_holding_minor"], SETTLED_RECEIPT_MINOR, "fiduciary_holding_minor"
    )


def test_the_certainty_breach_holds_the_remittance_and_leaves_every_receipt_alone():
    """Past the deadline only the 50,000,000 outflow is held; both receipts are untouched.

    PRD: "A breach moves `documentation_status` to `CERTAINTY_BREACHED` from
    whichever of `NOT_STARTED`, `SLIP_ISSUED` or `WORDING_DRAFTED` it was in,
    increments the program's `version`, and freezes the outbound money: every
    fiduciary movement of the program whose `txn_type` is `REINSURER_REMITTANCE`
    or `REINSTATEMENT_PREMIUM` and whose status is `PENDING` or `APPROVED`
    becomes `HELD` with its `hold_reason` set to the string
    `CONTRACT_CERTAINTY_BREACHED`."

    Design: Corner/state_machines/the_documentation_checkpoint_holds_only_remittance_type_transactions_not_receipts
    """
    ctx = _bound_program_at_slip_issued()

    set_clock(PAST_DEADLINE_CLOCK)
    breached = documentation_checkpoint(ctx["program"]["id"])
    assert_status(breached, "documentation_status", "CERTAINTY_BREACHED")

    program = read_program(ctx["program"]["id"])
    assert_status(program, "documentation_status", "CERTAINTY_BREACHED")
    assert_status(program, "placement_status", "BOUND")

    remittance = read_transaction(ctx["remittance"]["id"])
    assert_status(remittance, "status", "HELD")
    assert_status(remittance, "hold_reason", "CONTRACT_CERTAINTY_BREACHED")

    pending_receipt = read_transaction(ctx["pending_receipt"]["id"])
    assert_status(pending_receipt, "status", "PENDING")
    assert_is_null(pending_receipt, "hold_reason")

    settled_receipt = read_transaction(ctx["settled_receipt"]["id"])
    assert_status(settled_receipt, "status", "SETTLED")
    assert_is_null(settled_receipt, "hold_reason")

    assert_money_equals(
        program["fiduciary_holding_minor"],
        SETTLED_RECEIPT_MINOR,
        "fiduciary_holding_minor after the hold",
    )


def test_agreed_wording_releases_the_held_remittance_and_strips_its_approval():
    """Filing AGREED_WORDING from CERTAINTY_BREACHED returns the held outflow to PENDING.

    PRD: "Every fiduciary movement of the program sitting in `HELD` returns to
    `PENDING`, with its `hold_reason` cleared back to null and its
    `approved_by_user_id` cleared back to null as well — a released movement must
    be re-approved from scratch, because the approval it once had was given
    against a contract that did not yet exist."

    Design: Corner/state_machines/the_documentation_checkpoint_holds_only_remittance_type_transactions_not_receipts
    """
    ctx = _bound_program_at_slip_issued(approve_remittance=True)
    assert_status(ctx["remittance"], "status", "APPROVED")
    assert ctx["remittance"]["approved_by_user_id"] is not None, (
        "the remittance must carry an approval before the breach freezes it"
    )

    set_clock(PAST_DEADLINE_CLOCK)
    documentation_checkpoint(ctx["program"]["id"])
    held = read_transaction(ctx["remittance"]["id"])
    assert_status(held, "status", "HELD")
    assert_status(held, "hold_reason", "CONTRACT_CERTAINTY_BREACHED")

    file_document(ctx["program"]["id"], "AGREED_WORDING")

    program = read_program(ctx["program"]["id"])
    assert_status(program, "documentation_status", "WORDING_AGREED")
    assert_status(program, "placement_status", "BOUND")

    released = read_transaction(ctx["remittance"]["id"])
    assert_status(released, "status", "PENDING")
    assert_is_null(released, "hold_reason")
    assert_is_null(released, "approved_by_user_id")

    assert_status(read_transaction(ctx["pending_receipt"]["id"]), "status", "PENDING")
    assert_status(read_transaction(ctx["settled_receipt"]["id"]), "status", "SETTLED")


def _fully_placed_by_two_markets():
    """Alpha writes 60.0000 as lead and Bravo 40.0000, so the CAT layer fills exactly."""
    ctx = setup_program_in_market(market_specs=TWO_MARKET_SPECS)
    place_lines(
        ctx,
        [
            {
                "market_index": 0,
                "accepted_line_pct": 60.0000,
                "offered_line_pct": 60.0000,
                "is_lead": True,
            },
            {
                "market_index": 1,
                "accepted_line_pct": 40.0000,
                "offered_line_pct": 40.0000,
                "is_lead": False,
            },
        ],
    )
    return refresh(ctx)


def test_suspending_a_market_releases_its_line_and_hands_its_capacity_straight_back():
    """Alpha's suspension releases its 60.0000 line for SECURITY_FAILURE and frees 600,000,000.

    PRD: "Every signing line of the suspended market that is `PROVISIONAL` or
    `SIGNED` and sits on a layer that is not `BOUND` becomes `RELEASED` with
    `release_reason` set to `SECURITY_FAILURE`; that is hop one."

    Design: Corner/state_machines/suspending_a_market_releases_its_line_and_reverts_the_layer_and_the_program
    """
    ctx = _fully_placed_by_two_markets()
    assert_pct_equals(ctx["layer"]["written_line_total_pct"], 100.0000, "written_line_total_pct")
    assert_status(ctx["layer"], "status", "FULLY_PLACED")
    assert_status(ctx["program"], "placement_status", "FIRM_ORDER")

    alpha = suspend_market(ctx["reinsurers"][0]["id"], reason="Rating downgrade")
    assert_status(alpha, "security_status", "SUSPENDED")
    assert_money_equals(alpha["committed_capacity_minor"], 0, "Alpha committed_capacity_minor")
    assert_money_equals(
        alpha["available_capacity_minor"], 1_000_000_000, "Alpha available_capacity_minor"
    )

    alpha_line = read_signing_line(ctx["signing_lines"][0]["id"])
    assert_status(alpha_line, "status", "RELEASED")
    assert_status(alpha_line, "release_reason", "SECURITY_FAILURE")
    assert_pct_equals(alpha_line["written_line_pct"], 60.0000, "Alpha written_line_pct")
    assert_status(read_quote(ctx["quotes"][0]["id"]), "status", "LAPSED")

    bravo_line = read_signing_line(ctx["signing_lines"][1]["id"])
    assert_status(bravo_line, "status", "PROVISIONAL")
    assert_is_null(bravo_line, "release_reason")
    assert_status(read_quote(ctx["quotes"][1]["id"]), "status", "FIRM_ORDER")
    assert_money_equals(
        read_reinsurer(ctx["reinsurers"][1]["id"])["committed_capacity_minor"],
        400_000_000,
        "Bravo committed_capacity_minor",
    )


def test_the_security_cascade_reverts_the_layer_and_the_program_and_shuts_the_layer_out():
    """Losing Alpha drops the layer to 40.0000 PARTIALLY_PLACED and the program back to IN_MARKET.

    PRD: "Each affected layer then recomputes its `written_line_total_pct` and
    `signed_line_total_pct` and reverts `FULLY_PLACED` or `OVERSUBSCRIBED` to
    `PARTIALLY_PLACED`; that is hop two."

    Design: Corner/state_machines/suspending_a_market_releases_its_line_and_reverts_the_layer_and_the_program
    """
    ctx = _fully_placed_by_two_markets()

    suspend_market(ctx["reinsurers"][0]["id"], reason="Rating downgrade")
    ctx = refresh(ctx)

    assert_pct_equals(
        ctx["layer"]["written_line_total_pct"], 40.0000, "written_line_total_pct after release"
    )
    assert_status(ctx["layer"], "status", "PARTIALLY_PLACED")
    assert_status(ctx["program"], "placement_status", "IN_MARKET")

    # The layer is no longer OPEN or IN_MARKET, and the layer-state gate sits
    # above the suspended-market gate, so that is the error the broker is told.
    response = api_client.create_market_submission(
        ctx["layer"]["id"],
        create_market_submission_payload(
            ctx["reinsurers"][0]["id"], response_deadline=RESPONSE_DEADLINE
        ),
        LEAD,
    )
    validate_error(response, ApiErrorId.ERR_LAYER_STATE_INVALID.value)


def _two_submissions_sharing_one_deadline():
    """Alpha and Bravo each hold a submission on one CAT layer due 2026-02-01T00:00:00.000Z."""
    ctx = setup_program_in_market(market_specs=TWO_MARKET_SPECS)
    for market_index in (0, 1):
        send_submission(
            ctx, market_index=market_index, response_deadline=RESPONSE_DEADLINE
        )
    return ctx


def test_a_quote_landing_exactly_on_the_response_deadline_is_still_admitted():
    """Alpha quotes at 2026-02-01T00:00:00.000Z, the deadline instant itself, and is accepted.

    PRD: "The current logical clock must be **no later than** the submission's
    `response_deadline` — a clock landing exactly on the deadline still admits
    the quote — and a clock past it is refused with
    `ERR_RESPONSE_DEADLINE_PASSED`."

    Design: Corner/state_machines/quoting_after_the_response_deadline_is_refused_though_the_submission_is_still_sent
    """
    ctx = _two_submissions_sharing_one_deadline()
    alpha_submission = ctx["market_submissions"][0]
    assert_instant_equals(
        alpha_submission["response_deadline"], RESPONSE_DEADLINE, "response_deadline"
    )

    set_clock(RESPONSE_DEADLINE)
    quote = quote_on(
        alpha_submission["id"], ctx["reinsurers"][0]["id"], offered_line_pct=60.0000, is_lead=True
    )

    assert_status(quote, "status", "QUOTED")
    assert_status(read_market_submission(alpha_submission["id"]), "status", "QUOTED")


def test_a_quote_one_millisecond_past_the_deadline_is_refused_and_the_submission_stays_sent():
    """At 2026-02-01T00:00:00.001Z Bravo's quote is refused and its submission is still SENT.

    PRD: "The current logical clock must be **no later than** the submission's
    `response_deadline` — a clock landing exactly on the deadline still admits
    the quote — and a clock past it is refused with
    `ERR_RESPONSE_DEADLINE_PASSED`."

    Design: Corner/state_machines/quoting_after_the_response_deadline_is_refused_though_the_submission_is_still_sent
    """
    ctx = _two_submissions_sharing_one_deadline()
    bravo_submission = ctx["market_submissions"][1]

    set_clock(ONE_MS_PAST_DEADLINE)
    response = api_client.create_quote(
        bravo_submission["id"],
        create_quote_payload(offered_line_pct=40.0000, is_lead=False),
        make_reinsurer_underwriter_headers(ctx["reinsurers"][1]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_RESPONSE_DEADLINE_PASSED.value)

    still_open = read_market_submission(bravo_submission["id"])
    assert_status(still_open, "status", "SENT")
    rows, _meta = validate_paginated(
        api_client.list_market_submission_quotes(bravo_submission["id"], LEAD)
    )
    assert rows == [], f"the refused quote must not have been persisted, got {rows}"


def test_a_quote_whose_expiry_is_not_strictly_in_the_future_is_refused():
    """An expires_at equal to the current clock has already lapsed, so the quote is refused.

    PRD: "The supplied `expires_at` must be strictly after the current logical
    clock, else `ERR_DEADLINE_NOT_IN_FUTURE`."

    Design: Corner/state_machines/quoting_after_the_response_deadline_is_refused_though_the_submission_is_still_sent
    """
    ctx = _two_submissions_sharing_one_deadline()
    bravo_submission = ctx["market_submissions"][1]

    set_clock(ONE_MS_PAST_DEADLINE)
    # The freshness gate on expires_at is checked before the response-deadline
    # gate, so this is the error even though the deadline has also gone by.
    response = api_client.create_quote(
        bravo_submission["id"],
        create_quote_payload(
            offered_line_pct=40.0000, is_lead=False, expires_at=ONE_MS_PAST_DEADLINE
        ),
        make_reinsurer_underwriter_headers(ctx["reinsurers"][1]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_DEADLINE_NOT_IN_FUTURE.value)

    assert_status(read_market_submission(bravo_submission["id"]), "status", "SENT")


def test_the_market_sweep_expires_the_unanswered_submission_and_leaves_the_quoted_one_alone():
    """The sweep expires Bravo's SENT submission but never touches Alpha's quote or the program.

    PRD: "The sweep expires every market submission on the program's layers that
    is still in `SENT` and whose `response_deadline` is at or before the current
    logical-clock instant, moving it to `EXPIRED`, and it lapses every quote on
    those layers in `QUOTED`, `COUNTERED` or `REQUOTED` whose `expires_at` is at
    or before that instant, moving it to `LAPSED`."

    Design: Corner/state_machines/quoting_after_the_response_deadline_is_refused_though_the_submission_is_still_sent
    """
    ctx = _two_submissions_sharing_one_deadline()
    alpha_submission, bravo_submission = ctx["market_submissions"]

    set_clock(RESPONSE_DEADLINE)
    alpha_quote = quote_on(
        alpha_submission["id"], ctx["reinsurers"][0]["id"], offered_line_pct=60.0000, is_lead=True
    )
    assert_instant_equals(alpha_quote["expires_at"], CLOCK["QUOTE_EXPIRY"], "expires_at")

    set_clock(ONE_MS_PAST_DEADLINE)
    market_sweep(ctx["program"]["id"])

    assert_status(read_market_submission(bravo_submission["id"]), "status", "EXPIRED")
    assert_status(read_market_submission(alpha_submission["id"]), "status", "QUOTED")
    assert_status(read_quote(alpha_quote["id"]), "status", "QUOTED")
    assert_status(read_program(ctx["program"]["id"]), "placement_status", "IN_MARKET")
    assert_status(read_layer(ctx["layer"]["id"]), "status", "IN_MARKET")


def _file(program_id: str, document_type: str):
    """Attempt one filing and hand back the raw response so the refusals can be read."""
    return api_client.create_contract_document(
        program_id,
        create_contract_document_payload(document_type, f"NW-2026-{document_type}"),
        LEAD,
    )


def _documents(program_id: str):
    """The program's filing trail, oldest first."""
    rows, _meta = validate_paginated(
        api_client.list_program_contract_documents(program_id, LEAD)
    )
    return rows


def test_a_wording_draft_filed_before_any_slip_is_refused_and_appends_nothing():
    """The bound program starts at NOT_STARTED, so a WORDING_DRAFT has no slip to follow.

    PRD: "Filing a type that does not follow from the program's current
    documentation state — a wording draft with no slip, an executed contract with
    no agreed wording, a second slip — is `ERR_DOCUMENT_SEQUENCE_INVALID`."

    Design: Corner/state_machines/the_documentation_chain_refuses_an_out_of_order_or_repeated_filing
    """
    ctx = setup_bound_program()
    program_id = ctx["program"]["id"]
    assert_status(ctx["program"], "placement_status", "BOUND")
    assert_status(ctx["program"], "documentation_status", "NOT_STARTED")

    validate_error(
        _file(program_id, "WORDING_DRAFT"), ApiErrorId.ERR_DOCUMENT_SEQUENCE_INVALID.value
    )

    assert _documents(program_id) == [], "a refused filing must append no ContractDocument"
    assert_status(read_program(program_id), "documentation_status", "NOT_STARTED")


def test_a_second_slip_is_refused_while_the_chain_still_runs_forward_to_executed():
    """Repeating the slip is refused, yet the remaining three filings still reach EXECUTED.

    PRD: "Filing a type that does not follow from the program's current
    documentation state — a wording draft with no slip, an executed contract with
    no agreed wording, a second slip — is `ERR_DOCUMENT_SEQUENCE_INVALID`."

    Design: Corner/state_machines/the_documentation_chain_refuses_an_out_of_order_or_repeated_filing
    """
    ctx = setup_bound_program()
    program_id = ctx["program"]["id"]

    file_document(program_id, "SLIP")
    assert_status(read_program(program_id), "documentation_status", "SLIP_ISSUED")

    validate_error(_file(program_id, "SLIP"), ApiErrorId.ERR_DOCUMENT_SEQUENCE_INVALID.value)
    assert_status(read_program(program_id), "documentation_status", "SLIP_ISSUED")

    for document_type, expected_state in (
        ("WORDING_DRAFT", "WORDING_DRAFTED"),
        ("AGREED_WORDING", "WORDING_AGREED"),
        ("EXECUTED_CONTRACT", "EXECUTED"),
    ):
        file_document(program_id, document_type)
        assert_status(read_program(program_id), "documentation_status", expected_state)

    assert_status(read_program(program_id), "placement_status", "BOUND")


def test_executed_is_terminal_and_the_trail_holds_exactly_the_four_accepted_filings():
    """A repeat EXECUTED_CONTRACT is refused and the trail is the four documents in order.

    PRD: "The system records the document's `program_id`, stamps `issued_at` with
    the current logical clock, records `filed_by_user_id` as the filing broker's
    identity, and computes `days_from_inception` as the whole number of days
    between the program's `inception_date` and `issued_at`: the elapsed seconds
    divided by eighty-six thousand four hundred, floored, which is negative when
    the document was filed before inception."

    Design: Corner/state_machines/the_documentation_chain_refuses_an_out_of_order_or_repeated_filing
    """
    ctx = setup_bound_program()
    program_id = ctx["program"]["id"]
    execute_contract(program_id)
    assert_status(read_program(program_id), "documentation_status", "EXECUTED")

    validate_error(
        _file(program_id, "EXECUTED_CONTRACT"), ApiErrorId.ERR_DOCUMENT_SEQUENCE_INVALID.value
    )
    assert_status(read_program(program_id), "documentation_status", "EXECUTED")

    rows = _documents(program_id)
    assert len(rows) == 4, f"exactly the four accepted filings must be on record, got {len(rows)}"
    assert [row["document_type"] for row in rows] == DOCUMENT_CHAIN, (
        f"the trail must read in filing order, got {[row['document_type'] for row in rows]}"
    )
    for row in rows:
        assert_append_only_fields(row)
        assert_instant_equals(row["issued_at"], CLOCK["INCEPTION"], "issued_at")
        assert row["days_from_inception"] == 0, (
            "every document was filed on the inception instant, so days_from_inception is 0, "
            f"got {row['days_from_inception']}"
        )


def _oversubscribed_by_three_markets():
    """Alpha 60 as lead, then Charlie 30, then Bravo 40, so the layer writes 130.0000.

    Charlie's line has to be taken while the program is still ``IN_MARKET``,
    because a firm order is only admitted from that placement status.
    """
    ctx = setup_program_in_market(market_specs=THREE_MARKET_SPECS)
    place_lines(
        ctx,
        [
            {
                "market_index": 0,
                "accepted_line_pct": 60.0000,
                "offered_line_pct": 60.0000,
                "is_lead": True,
            },
            {
                "market_index": 2,
                "accepted_line_pct": 30.0000,
                "offered_line_pct": 30.0000,
                "is_lead": False,
            },
            {
                "market_index": 1,
                "accepted_line_pct": 40.0000,
                "offered_line_pct": 40.0000,
                "is_lead": False,
            },
        ],
    )
    ctx["charlie_line"] = ctx["signing_lines"][1]
    ctx["charlie_quote"] = ctx["quotes"][1]
    ctx["alpha_line"] = ctx["signing_lines"][0]
    ctx["bravo_line"] = ctx["signing_lines"][2]
    return refresh(ctx)


def test_releasing_the_oversubscribing_line_restores_the_layer_to_exactly_fully_placed():
    """Handing back Charlie's 30.0000 takes the written total from 130.0000 to exactly 100.0000.

    PRD: "The line's status becomes `RELEASED` with `release_reason` set to
    `WITHDRAWN_BY_BROKER`."

    Design: Corner/state_machines/releasing_a_bound_or_an_already_released_line_is_refused
    """
    ctx = _oversubscribed_by_three_markets()
    assert_pct_equals(ctx["layer"]["written_line_total_pct"], 130.0000, "written_line_total_pct")
    assert_status(ctx["layer"], "status", "OVERSUBSCRIBED")
    assert_status(ctx["program"], "placement_status", "FIRM_ORDER")
    assert_status(read_signing_line(ctx["charlie_line"]["id"]), "status", "PROVISIONAL")

    released = release_line(ctx["charlie_line"]["id"])
    assert_status(released, "status", "RELEASED")
    assert_status(released, "release_reason", "WITHDRAWN_BY_BROKER")
    assert_is_null(released, "signed_line_pct")
    assert_status(read_quote(ctx["charlie_quote"]["id"]), "status", "LAPSED")

    ctx = refresh(ctx)
    assert_pct_equals(
        ctx["layer"]["written_line_total_pct"], 100.0000, "written_line_total_pct after release"
    )
    assert_status(ctx["layer"], "status", "FULLY_PLACED")
    assert_status(ctx["program"], "placement_status", "FIRM_ORDER")


def test_a_released_or_bound_signing_line_can_never_be_released_again():
    """The second release of Charlie's line, and the release of Alpha's bound line, both refuse.

    PRD: "Release requires the line's status to be `PROVISIONAL` or `SIGNED` — a
    `BOUND` or already-`RELEASED` line cannot be released, and the attempt is
    `ERR_SIGNING_LINE_STATE_INVALID` — requires the layer not to be `BOUND`, and
    requires the owning program to be in `FIRM_ORDER`, else
    `ERR_PROGRAM_STATE_INVALID`."

    Design: Corner/state_machines/releasing_a_bound_or_an_already_released_line_is_refused
    """
    ctx = _oversubscribed_by_three_markets()
    release_line(ctx["charlie_line"]["id"])

    validate_error(
        api_client.release_signing_line(ctx["charlie_line"]["id"], LEAD),
        ApiErrorId.ERR_SIGNING_LINE_STATE_INVALID.value,
    )
    charlie = read_signing_line(ctx["charlie_line"]["id"])
    assert_status(charlie, "status", "RELEASED")
    assert_status(charlie, "release_reason", "WITHDRAWN_BY_BROKER")

    acknowledge_disclosure(
        ctx["program"]["id"], ctx["cedent"]["id"], ctx["program"]["brokerage_pct"]
    )
    program = bind_program(ctx["program"]["id"])
    assert_status(program, "placement_status", "BOUND")

    alpha = read_signing_line(ctx["alpha_line"]["id"])
    bravo = read_signing_line(ctx["bravo_line"]["id"])
    assert_status(alpha, "status", "BOUND")
    assert_pct_equals(alpha["signed_line_pct"], 60.0000, "Alpha signed_line_pct")
    assert_status(bravo, "status", "BOUND")
    assert_pct_equals(bravo["signed_line_pct"], 40.0000, "Bravo signed_line_pct")

    # The line-state gate sits above the program-state gate, so a bound line is
    # refused for its own status rather than for the program having left FIRM_ORDER.
    validate_error(
        api_client.release_signing_line(ctx["alpha_line"]["id"], LEAD),
        ApiErrorId.ERR_SIGNING_LINE_STATE_INVALID.value,
    )
    assert_status(read_signing_line(ctx["alpha_line"]["id"]), "status", "BOUND")
    assert_is_null(read_signing_line(ctx["charlie_line"]["id"]), "signed_line_pct")
