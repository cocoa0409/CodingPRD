"""Compensating movements over two conserved quantities (PRD §3.5, §3.8).

Queue A — rule ``compensating_invariant``: reversing a settled remittance
conserves MONEY, restoring ``Program.fiduciary_holding_minor`` by appending a
``REMITTANCE_REVERSAL`` inflow rather than by rewriting the outflow; releasing a
provisional line conserves UNDERWRITING CAPACITY, handing the market's
``committed_capacity_minor`` back in full and unwinding the derived chain the
line caused.
"""
from test_helpers import (
    ApiErrorId,
    CLOCK,
    TEST_USERS,
    api_client,
    as_minor,
    assert_capacity_invariants,
    assert_instant_equals,
    assert_money_equals,
    assert_pct_equals,
    assert_placement_money_invariants,
    assert_status,
    book_approve_settle,
    list_rows,
    add_quote,
    firm_order,
    read_cedent,
    read_layer,
    read_program,
    read_quote,
    read_reinsurer,
    read_signing_line,
    read_transaction,
    release_line,
    reverse_transaction,
    send_submission,
    setup_bound_program_with_agreed_wording,
    setup_program_in_market,
    validate_error,
)

ACCOUNTANT_HEADERS = TEST_USERS["accountant_headers"]
COMPLIANCE_HEADERS = TEST_USERS["compliance_headers"]

# ==========================================================================
# Instance 1 — MONEY. Echo Re writes the whole canonical CATASTROPHE layer, so
# the bound program books gross 97,125,000, brokerage 2,428,125 and net
# remittance 94,696,875. A 97,125,000 receipt then a 94,696,875 remittance
# leave the fiduciary account holding exactly the brokerage.
# ==========================================================================
ECHO_RE_SPECS = [
    {
        "name": "Echo Re",
        "security_rating": "AA",
        "capacity_limit_minor": 1_000_000_000,
        "max_line_pct": 100.0000,
        "lead_authorised": True,
    }
]
CAT_PROGRAM_NAME = "Northwind Property CAT 2026"

GROSS_WRITTEN_PREMIUM_MINOR = 97_125_000
BROKERAGE_EARNED_MINOR = 2_428_125
NET_REMITTANCE_MINOR = 94_696_875


def _settled_remittance_on_a_bound_program():
    """A bound, wording-agreed program whose net remittance has settled to Echo Re.

    The chain is receipt 97,125,000 settled -> remittance 94,696,875 settled, so
    ``fiduciary_holding_minor`` steps 0 -> 97,125,000 -> 2,428,125.
    """
    ctx = setup_bound_program_with_agreed_wording(
        market_specs=ECHO_RE_SPECS,
        program_overrides={"program_name": CAT_PROGRAM_NAME},
        receipt_minor=GROSS_WRITTEN_PREMIUM_MINOR,
    )
    ctx["holding_after_receipt"] = read_program(ctx["program"]["id"])[
        "fiduciary_holding_minor"
    ]
    ctx["remittance"] = book_approve_settle(
        ctx["program"]["id"],
        "REINSURER_REMITTANCE",
        NET_REMITTANCE_MINOR,
        signing_line_id=ctx["signing_lines"][0]["id"],
    )
    ctx["holding_after_remittance"] = read_program(ctx["program"]["id"])[
        "fiduciary_holding_minor"
    ]
    return ctx


def test_reversing_the_settled_remittance_restores_the_fiduciary_balance_exactly():
    """The balance walks 97,125,000 -> 2,428,125 -> 97,125,000, a delta of exactly +94,696,875.

    PRD: "A reversed movement therefore stays in the projection for ever as the
    outflow it always was, and its compensating inflow cancels it exactly, so the
    balance returns to precisely the value it held before the reversed movement
    settled — a delta of the reversed amount and not one unit more."

    Design: Difficulty/compensating_invariant/reversing_a_settled_remittance_restores_the_fiduciary_balance_exactly
    """
    ctx = _settled_remittance_on_a_bound_program()
    program_before = read_program(ctx["program"]["id"])
    assert_money_equals(
        program_before["gross_written_premium_minor"],
        GROSS_WRITTEN_PREMIUM_MINOR,
        "gross_written_premium_minor",
    )
    assert_money_equals(
        program_before["brokerage_earned_minor"],
        BROKERAGE_EARNED_MINOR,
        "brokerage_earned_minor",
    )
    assert_money_equals(
        program_before["net_remittance_minor"],
        NET_REMITTANCE_MINOR,
        "net_remittance_minor",
    )
    assert_placement_money_invariants(program_before)
    assert_money_equals(
        ctx["holding_after_receipt"], 97_125_000, "fiduciary_holding_minor after the receipt"
    )
    assert_money_equals(
        ctx["holding_after_remittance"],
        2_428_125,
        "fiduciary_holding_minor after the remittance settles — exactly the brokerage",
    )

    reverse_transaction(ctx["remittance"]["id"])

    program_after = read_program(ctx["program"]["id"])
    assert_money_equals(
        program_after["fiduciary_holding_minor"],
        97_125_000,
        "fiduciary_holding_minor restored by the compensating inflow",
    )
    delta = as_minor(program_after["fiduciary_holding_minor"]) - as_minor(
        ctx["holding_after_remittance"]
    )
    assert_money_equals(delta, 94_696_875, "the reversal delta, and not one minor unit more")
    assert_money_equals(
        read_cedent(ctx["cedent"]["id"])["settled_receipts_minor"],
        97_125_000,
        "settled_receipts_minor is untouched by the reversal",
    )


def test_the_reversal_appends_one_compensating_row_and_rewrites_nothing():
    """The remittance goes REVERSED in place and a single 94,696,875 REMITTANCE_REVERSAL is appended.

    PRD: "Reversal moves the original row from `SETTLED` to `REVERSED`, which is
    terminal, and appends a **new** movement of type `REMITTANCE_REVERSAL` for
    the same `amount_minor`, with the original's `signing_line_id` copied across,
    with `reverses_transaction_id` pointing at the reversed row, already in
    status `SETTLED` and with `value_date` stamped from the current clock."

    Design: Difficulty/compensating_invariant/reversing_a_settled_remittance_restores_the_fiduciary_balance_exactly
    """
    ctx = _settled_remittance_on_a_bound_program()
    remittance_id = ctx["remittance"]["id"]
    signing_line_id = ctx["signing_lines"][0]["id"]

    reversal = reverse_transaction(remittance_id)

    original = read_transaction(remittance_id)
    assert_status(original, "status", "REVERSED")
    assert_status(original, "txn_type", "REINSURER_REMITTANCE")
    assert_money_equals(
        original["amount_minor"], 94_696_875, "the reversed row keeps its own amount_minor"
    )

    assert_status(reversal, "txn_type", "REMITTANCE_REVERSAL")
    assert_status(reversal, "status", "SETTLED")
    assert_money_equals(reversal["amount_minor"], 94_696_875, "compensating amount_minor")
    assert reversal["reverses_transaction_id"] == remittance_id, (
        "reverses_transaction_id must point at the reversed row, got "
        f"{reversal['reverses_transaction_id']!r}"
    )
    assert reversal["signing_line_id"] == signing_line_id, (
        "the original's signing_line_id must be copied across, got "
        f"{reversal['signing_line_id']!r}"
    )
    assert_instant_equals(
        reversal["value_date"], CLOCK["PLACEMENT_START"], "compensating value_date"
    )

    linked = list_rows(
        api_client.list_fiduciary_transactions(
            ACCOUNTANT_HEADERS, params={"reverses_transaction_id": remittance_id}
        )
    )
    assert len(linked) == 1, (
        f"exactly one compensating row may reference the remittance, got {len(linked)}"
    )
    assert linked[0]["id"] == reversal["id"], "the linked row is the compensating movement"

    ledger = list_rows(
        api_client.list_program_fiduciary_transactions(
            ctx["program"]["id"], ACCOUNTANT_HEADERS
        )
    )
    reversals = [row for row in ledger if row["txn_type"] == "REMITTANCE_REVERSAL"]
    assert len(reversals) == 1, (
        f"the program ledger holds exactly one REMITTANCE_REVERSAL, got {len(reversals)}"
    )
    assert len(ledger) == 3, (
        "the ledger is append-only: receipt, reversed remittance and compensating row, "
        f"got {len(ledger)} rows"
    )


def test_a_second_reversal_of_the_same_remittance_is_refused():
    """A movement may be compensated once; the second attempt is ERR_ALREADY_REVERSED.

    PRD: "A movement may be reversed once and once only: if any
    `REMITTANCE_REVERSAL` row already references it, the attempt is
    `ERR_ALREADY_REVERSED`."

    Design: Difficulty/compensating_invariant/reversing_a_settled_remittance_restores_the_fiduciary_balance_exactly
    """
    ctx = _settled_remittance_on_a_bound_program()
    remittance_id = ctx["remittance"]["id"]
    reverse_transaction(remittance_id)

    response = api_client.reverse_fiduciary_transaction(remittance_id, COMPLIANCE_HEADERS)

    validate_error(response, ApiErrorId.ERR_ALREADY_REVERSED.value)
    assert_money_equals(
        read_program(ctx["program"]["id"])["fiduciary_holding_minor"],
        97_125_000,
        "the refused second reversal moves no money",
    )
    ledger = list_rows(
        api_client.list_program_fiduciary_transactions(
            ctx["program"]["id"], ACCOUNTANT_HEADERS
        )
    )
    assert len([row for row in ledger if row["txn_type"] == "REMITTANCE_REVERSAL"]) == 1, (
        "the refused attempt must not append a second compensating row"
    )


# ==========================================================================
# Instance 2 — UNDERWRITING CAPACITY. Kilo Re writes 90.0000 of the canonical
# 1,000,000,000 CATASTROPHE layer (900,000,000, exactly its whole limit) and
# Juliet Re writes 20.0000 (200,000,000 of a 300,000,000 limit), so the written
# total is 110.0000, the layer is OVERSUBSCRIBED and the program is FIRM_ORDER.
# No sign-down is run, so both lines are still PROVISIONAL.
# ==========================================================================
RELEASE_MARKET_SPECS = [
    {
        "name": "Kilo Re",
        "security_rating": "AA",
        "capacity_limit_minor": 900_000_000,
        "max_line_pct": 90.0000,
        "lead_authorised": True,
    },
    {
        "name": "Juliet Re",
        "security_rating": "A",
        "capacity_limit_minor": 300_000_000,
        "max_line_pct": 20.0000,
        "lead_authorised": False,
    },
]

KILO_LINE_PCT = 90.0000
JULIET_LINE_PCT = 20.0000
KILO_COMMITTED_MINOR = 900_000_000
JULIET_COMMITTED_MINOR = 200_000_000


def _oversubscribed_at_ninety_and_twenty():
    """Kilo Re 90.0000 as lead then Juliet Re 20.0000 as follower on one CAT layer.

    ``setup_oversubscribed_layer`` is deliberately not used: it offers 100.0000 on
    both quotes, whereas this instance pins each market's offer to the line it
    actually writes (90.0000 at 8.0000% and 20.0000 at 8.2500%).
    """
    ctx = setup_program_in_market(
        market_specs=RELEASE_MARKET_SPECS,
        program_overrides={
            "program_name": CAT_PROGRAM_NAME,
            "signdown_method": "PRO_RATA",
        },
    )
    # Both markets are addressed and both quotes are taken while the layer is
    # still IN_MARKET, because PRD §3.4 admits a market submission only while
    # "the layer must be either `OPEN` or `IN_MARKET`" and the lead's firm order
    # carries it to PARTIALLY_PLACED.
    kilo_submission = send_submission(ctx, market_index=0)
    juliet_submission = send_submission(ctx, market_index=1)
    kilo_quote = add_quote(
        ctx,
        market_index=0,
        market_submission=kilo_submission,
        offered_line_pct=KILO_LINE_PCT,
        is_lead=True,
        quoted_rate_pct=8.0000,
    )
    juliet_quote = add_quote(
        ctx,
        market_index=1,
        market_submission=juliet_submission,
        offered_line_pct=JULIET_LINE_PCT,
        is_lead=False,
        quoted_rate_pct=8.2500,
    )
    ctx["signing_lines"].append(
        firm_order(kilo_quote["id"], KILO_LINE_PCT, layer_id=ctx["layer"]["id"])
    )
    ctx["layer_after_lead"] = read_layer(ctx["layer"]["id"])
    ctx["signing_lines"].append(
        firm_order(juliet_quote["id"], JULIET_LINE_PCT, layer_id=ctx["layer"]["id"])
    )
    ctx["signing_line"] = ctx["signing_lines"][0]
    ctx["kilo"] = ctx["reinsurers"][0]
    ctx["juliet"] = ctx["reinsurers"][1]
    ctx["kilo_line"] = ctx["signing_lines"][0]
    ctx["juliet_line"] = ctx["signing_lines"][1]
    ctx["juliet_quote"] = ctx["quotes"][1]
    ctx["juliet_before"] = read_reinsurer(ctx["juliet"]["id"])
    return ctx


def test_releasing_the_provisional_line_hands_back_the_full_two_hundred_million():
    """Juliet Re goes from committed 200,000,000 / available 100,000,000 to 0 / 300,000,000.

    PRD: "A line is live when its status is `PROVISIONAL`, `SIGNED` or `BOUND`;
    `RELEASED` lines are excluded entirely, because releasing a line always hands
    capacity straight back."

    Design: Difficulty/compensating_invariant/releasing_a_provisional_line_hands_the_markets_capacity_back_in_full
    """
    ctx = _oversubscribed_at_ninety_and_twenty()
    assert_money_equals(
        ctx["juliet_before"]["committed_capacity_minor"],
        200_000_000,
        "Juliet Re committed_capacity_minor before the release",
    )
    assert_money_equals(
        ctx["juliet_before"]["available_capacity_minor"],
        100_000_000,
        "Juliet Re available_capacity_minor before the release",
    )

    release_line(ctx["juliet_line"]["id"])

    juliet = read_reinsurer(ctx["juliet"]["id"])
    assert_money_equals(
        juliet["committed_capacity_minor"], 0, "Juliet Re committed_capacity_minor"
    )
    assert_money_equals(
        juliet["available_capacity_minor"],
        300_000_000,
        "Juliet Re available_capacity_minor — the whole limit is free again",
    )
    assert_money_equals(
        juliet["capacity_limit_minor"], 300_000_000, "Juliet Re capacity_limit_minor"
    )
    assert_capacity_invariants(juliet)

    kilo = read_reinsurer(ctx["kilo"]["id"])
    assert_money_equals(
        kilo["committed_capacity_minor"],
        900_000_000,
        "Kilo Re committed_capacity_minor is undisturbed",
    )
    assert_money_equals(kilo["available_capacity_minor"], 0, "Kilo Re available_capacity_minor")
    assert_capacity_invariants(kilo)

    kilo_line = read_signing_line(ctx["kilo_line"]["id"])
    assert_status(kilo_line, "status", "PROVISIONAL")
    assert_money_equals(
        kilo_line["committed_capacity_minor"],
        900_000_000,
        "Kilo Re's line keeps its committed_capacity_minor",
    )


def test_the_released_line_is_stamped_withdrawn_by_broker_and_its_quote_lapses():
    """The handed-back line reads RELEASED / WITHDRAWN_BY_BROKER and its quote goes LAPSED.

    PRD: "The line's status becomes `RELEASED` with `release_reason` set to
    `WITHDRAWN_BY_BROKER`. The first hop lapses the quote that materialised the
    line, taking it from `FIRM_ORDER` to `LAPSED`."

    Design: Difficulty/compensating_invariant/releasing_a_provisional_line_hands_the_markets_capacity_back_in_full
    """
    ctx = _oversubscribed_at_ninety_and_twenty()
    assert_status(read_quote(ctx["juliet_quote"]["id"]), "status", "FIRM_ORDER")

    released = release_line(ctx["juliet_line"]["id"])

    assert_status(released, "status", "RELEASED")
    assert_status(released, "release_reason", "WITHDRAWN_BY_BROKER")
    assert_pct_equals(
        released["written_line_pct"],
        20.0000,
        "the released line keeps the written_line_pct it once reserved",
    )

    stored = read_signing_line(ctx["juliet_line"]["id"])
    assert_status(stored, "status", "RELEASED")
    assert_status(stored, "release_reason", "WITHDRAWN_BY_BROKER")
    assert_status(read_quote(ctx["juliet_quote"]["id"]), "status", "LAPSED")
    assert_status(read_quote(ctx["quotes"][0]["id"]), "status", "FIRM_ORDER")


def test_the_oversubscribed_layer_reverts_to_partially_placed_on_the_recomputed_total():
    """Written total falls 110.0000 -> 90.0000, so OVERSUBSCRIBED becomes PARTIALLY_PLACED.

    PRD: "The second hop recomputes the layer's `written_line_total_pct` and
    `signed_line_total_pct` and reverts the layer's status from the recomputed
    totals: a `FULLY_PLACED` layer whose written total has fallen below `100.0000`
    becomes `PARTIALLY_PLACED`; an `OVERSUBSCRIBED` layer becomes
    `PARTIALLY_PLACED` when its written total falls below `100.0000` and
    `FULLY_PLACED` when it lands on exactly `100.0000`; and a `SIGNED_DOWN` layer
    whose signed total has fallen below `100.0000` becomes `PARTIALLY_PLACED`,
    with the remaining `SIGNED` lines keeping the `signed_line_pct` they were
    already allocated — the sign-down is emphatically **not** recomputed."

    Design: Difficulty/compensating_invariant/releasing_a_provisional_line_hands_the_markets_capacity_back_in_full
    """
    ctx = _oversubscribed_at_ninety_and_twenty()
    assert_status(ctx["layer_after_lead"], "status", "PARTIALLY_PLACED")
    layer_before = read_layer(ctx["layer"]["id"])
    assert_pct_equals(
        layer_before["written_line_total_pct"], 110.0000, "written_line_total_pct before"
    )
    assert_status(layer_before, "status", "OVERSUBSCRIBED")

    release_line(ctx["juliet_line"]["id"])

    layer_after = read_layer(ctx["layer"]["id"])
    assert_pct_equals(
        layer_after["written_line_total_pct"], 90.0000, "written_line_total_pct after"
    )
    assert_status(layer_after, "status", "PARTIALLY_PLACED")
    assert_pct_equals(
        layer_after["signed_line_total_pct"],
        0.0000,
        "no sign-down was ever run, so signed_line_total_pct stays at zero",
    )
    assert_money_equals(layer_after["limit_minor"], 1_000_000_000, "limit_minor")


def test_the_program_reverts_from_firm_order_to_in_market():
    """One PARTIALLY_PLACED layer is enough to pull the program back off firm order.

    PRD: "The third hop looks up at the program: if, after the releasing hop, at
    least one layer of the program is now `IN_MARKET` or `PARTIALLY_PLACED`, the
    program reverts from `FIRM_ORDER` to `IN_MARKET` and its `version`
    increments."

    Design: Difficulty/compensating_invariant/releasing_a_provisional_line_hands_the_markets_capacity_back_in_full
    """
    ctx = _oversubscribed_at_ninety_and_twenty()
    program_before = read_program(ctx["program"]["id"])
    assert_status(program_before, "placement_status", "FIRM_ORDER")

    release_line(ctx["juliet_line"]["id"])

    program_after = read_program(ctx["program"]["id"])
    assert_status(program_after, "placement_status", "IN_MARKET")
    assert program_after["version"] > program_before["version"], (
        "the revert increments the program's version, got "
        f"{program_after['version']} from {program_before['version']}"
    )
    assert_status(read_layer(ctx["layer"]["id"]), "status", "PARTIALLY_PLACED")
