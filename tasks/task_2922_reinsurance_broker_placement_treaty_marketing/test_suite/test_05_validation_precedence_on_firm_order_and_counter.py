"""Which gate speaks first when a firm order or a counter breaches two rules at once (PRD §2.8, §3.5).

Queue A — rule ``priority_pair_validation_conflict``: three doubly-invalid
requests, each pairing a higher-priority gate with a lower-priority one. Every
pair is asserted twice: once with both defects present, to pin the winning error,
and once with the higher-priority defect removed, to prove the loser was live all
along.
"""
from test_helpers import (
    LEAD,
    ApiErrorId,
    add_quote,
    api_client,
    assert_capacity_invariants,
    assert_is_null,
    assert_money_equals,
    assert_pct_equals,
    assert_status,
    counter_payload,
    counter_quote,
    current_layer_version,
    decline_payload,
    firm_order_payload,
    get_success_data,
    list_rows,
    make_reinsurer_underwriter_headers,
    read_layer,
    read_quote,
    read_reinsurer,
    requote,
    send_submission,
    set_clock,
    setup_program_in_market,
    suspend_market,
    validate_error,
)

PROGRAM_OVERRIDES = {"program_name": "Northwind Property CAT 2026"}
SUBMISSION_OVERRIDES = {"package_label": "NW-CAT-2026-EDP"}

# Instance 1 — a lead-authorised market whose quote is walked away from and whose
# security is then pulled, so both the own-state gate (26) and the safety gate
# (37) are live on the same firm order.
GOLF_MARKET_SPECS = [
    {
        "name": "Golf Re",
        "security_rating": "A",
        "capacity_limit_minor": 1_000_000_000,
        "max_line_pct": 50.0000,
        "lead_authorised": True,
    }
]

# Instance 2 — a tiny follower market: 25.0000 of line cap against a
# 1,000,000,000 layer needs 250,000,000 of capacity, but the market carries only
# 100,000,000, so a 30.0000 line breaches the constraint gate (56) and the fiscal
# gate (67) simultaneously.
FOXTROT_MARKET_SPECS = [
    {
        "name": "Foxtrot Re",
        "security_rating": "BBB",
        "capacity_limit_minor": 100_000_000,
        "max_line_pct": 25.0000,
        "lead_authorised": False,
    }
]

# Instance 3 — three full counter/requote rounds burn the negotiation cap while
# the quote's own expiry instant is where the clock is later parked.
HOTEL_MARKET_SPECS = [
    {
        "name": "Hotel Re",
        "security_rating": "A",
        "capacity_limit_minor": 1_000_000_000,
        "max_line_pct": 50.0000,
        "lead_authorised": True,
    }
]

# counter_note, then the rate the market comes back with on the matching requote.
NEGOTIATION_ROUNDS = [
    ("round one", 8.8000),
    ("round two", 8.5000),
    ("round three", 8.2000),
]

QUOTE_EXPIRES_AT = "2026-02-15T00:00:00.000Z"


def _decline_own_quote(quote_id: str, reinsurer_id: str):
    """The owning market walks away from its own live quote (PRD §3.4)."""
    return get_success_data(
        api_client.decline_quote(
            quote_id,
            decline_payload(decline_reason="aggregate full in this zone"),
            make_reinsurer_underwriter_headers(reinsurer_id),
        )
    )


def _attempt_firm_order(quote_id: str, layer_id: str, accepted_line_pct: float):
    """Raw firm-order call against the layer's live version, so no gate is masked."""
    return api_client.firm_order(
        quote_id,
        firm_order_payload(accepted_line_pct, current_layer_version(layer_id)),
        LEAD,
    )


def _attempt_counter(quote_id: str, counter_note: str):
    """Raw counter call, returned unvalidated so the error id can be asserted."""
    return api_client.counter_quote(quote_id, counter_payload(counter_note), LEAD)


def _golf_re_quote(declined: bool):
    """Golf Re's 50.0000 lead quote on a suspended market, optionally declined first.

    With ``declined`` true the quote is in the terminal ``DECLINED`` state and the
    market is ``SUSPENDED``, so the own-state gate and the safety gate are both
    live on a firm order. With it false only the suspension remains.
    """
    ctx = setup_program_in_market(
        market_specs=GOLF_MARKET_SPECS,
        program_overrides=PROGRAM_OVERRIDES,
        submission_overrides=SUBMISSION_OVERRIDES,
    )
    send_submission(ctx)
    add_quote(
        ctx,
        offered_line_pct=50.0000,
        quoted_rate_pct=8.0000,
        ceding_commission_pct=0.0000,
        reinstatements_offered=1,
        sublimit_minor=0,
        expires_at=QUOTE_EXPIRES_AT,
        is_lead=True,
    )
    if declined:
        _decline_own_quote(ctx["quotes"][0]["id"], ctx["reinsurers"][0]["id"])
    suspend_market(ctx["reinsurers"][0]["id"], "rating downgrade below treaty minimum")
    return ctx


def test_a_declined_quote_on_a_suspended_market_reports_the_quote_state_not_the_suspension():
    """Both gates are breached; the own-state check at priority 26 speaks first.

    PRD: "The quote's own status is checked first and must be `QUOTED` or
    `REQUOTED`, else `ERR_QUOTE_STATE_INVALID`."

    Design: Difficulty/priority_pair_validation_conflict/declined_quote_on_suspended_market_reports_quote_state_before_market_suspension
    """
    ctx = _golf_re_quote(declined=True)
    quote_id = ctx["quotes"][0]["id"]
    assert_status(read_quote(quote_id), "status", "DECLINED")
    assert_status(read_reinsurer(ctx["reinsurers"][0]["id"]), "security_status", "SUSPENDED")

    response = _attempt_firm_order(quote_id, ctx["layer"]["id"], 50.0000)

    error = validate_error(response, ApiErrorId.ERR_QUOTE_STATE_INVALID.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_MARKET_SUSPENDED.value, (
        "priority 26 outranks priority 37, so the suspension must never be reported here"
    )

    quote = read_quote(quote_id)
    assert_status(quote, "status", "DECLINED")
    assert_is_null(quote, "accepted_line_pct")
    assert_status(read_reinsurer(ctx["reinsurers"][0]["id"]), "security_status", "SUSPENDED")
    lines = list_rows(api_client.list_layer_signing_lines(ctx["layer"]["id"], LEAD))
    assert len(lines) == 0, f"the refused firm order must mint no signing line, got {lines!r}"


def test_a_live_quote_on_a_suspended_market_reports_the_suspension():
    """Drop the decline and the lower-priority safety gate at 37 surfaces on its own.

    PRD: "Then the quoting market's `security_status` must be either `APPROVED` or
    `RESTRICTED`, since a `SUSPENDED` market cannot be firm-ordered, else
    `ERR_MARKET_SUSPENDED`."

    Design: Difficulty/priority_pair_validation_conflict/declined_quote_on_suspended_market_reports_quote_state_before_market_suspension
    """
    ctx = _golf_re_quote(declined=False)
    quote_id = ctx["quotes"][0]["id"]
    assert_status(read_quote(quote_id), "status", "QUOTED")
    assert_status(read_reinsurer(ctx["reinsurers"][0]["id"]), "security_status", "SUSPENDED")

    response = _attempt_firm_order(quote_id, ctx["layer"]["id"], 50.0000)

    validate_error(response, ApiErrorId.ERR_MARKET_SUSPENDED.value, 422)

    quote = read_quote(quote_id)
    assert_status(quote, "status", "QUOTED")
    assert_is_null(quote, "accepted_line_pct")
    lines = list_rows(api_client.list_layer_signing_lines(ctx["layer"]["id"], LEAD))
    assert len(lines) == 0, f"the refused firm order must mint no signing line, got {lines!r}"


def _foxtrot_re_quote():
    """Foxtrot Re offers 30.0000 on a 1,000,000,000 layer against a 100,000,000 book.

    Offers are not capped at quote time, so a 30.0000 offer stands even though the
    market's ``max_line_pct`` is 25.0000 and its whole capacity would buy only
    10.0000 of this layer.
    """
    ctx = setup_program_in_market(
        market_specs=FOXTROT_MARKET_SPECS,
        program_overrides=PROGRAM_OVERRIDES,
        submission_overrides=SUBMISSION_OVERRIDES,
    )
    send_submission(ctx)
    add_quote(
        ctx,
        offered_line_pct=30.0000,
        quoted_rate_pct=8.0000,
        ceding_commission_pct=0.0000,
        reinstatements_offered=1,
        sublimit_minor=0,
        expires_at=QUOTE_EXPIRES_AT,
        is_lead=False,
    )
    return ctx


def test_a_line_over_both_the_line_cap_and_the_book_reports_the_line_cap():
    """30.0000 breaches max_line 25.0000 and needs 300,000,000 of a 100,000,000 book.

    PRD: "Fiscal checks come last deliberately: in a placement business the broker
    must be told that the terms themselves are inadmissible — wrong state,
    suspended market, blown deadline, oversized line — before being told that the
    market has run out of money for them."

    Design: Difficulty/priority_pair_validation_conflict/oversized_line_on_tiny_market_reports_max_line_before_capacity
    """
    ctx = _foxtrot_re_quote()
    quote_id = ctx["quotes"][0]["id"]
    market = read_reinsurer(ctx["reinsurers"][0]["id"])
    assert_pct_equals(market["max_line_pct"], 25.0000, "max_line_pct")
    assert_money_equals(market["capacity_limit_minor"], 100_000_000, "capacity_limit_minor")

    response = _attempt_firm_order(quote_id, ctx["layer"]["id"], 30.0000)

    error = validate_error(response, ApiErrorId.ERR_LINE_EXCEEDS_MAX_LINE.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_CAPACITY_EXCEEDED.value, (
        "priority 56 outranks priority 67, so the capacity breach must stay silent"
    )

    assert_status(read_quote(quote_id), "status", "QUOTED")
    layer = read_layer(ctx["layer"]["id"])
    assert_pct_equals(layer["written_line_total_pct"], 0.0000, "written_line_total_pct")
    assert_status(layer, "status", "IN_MARKET")
    market = read_reinsurer(ctx["reinsurers"][0]["id"])
    assert_money_equals(market["committed_capacity_minor"], 0, "committed_capacity_minor")
    assert_money_equals(
        market["available_capacity_minor"], 100_000_000, "available_capacity_minor"
    )
    assert_capacity_invariants(market)


def test_a_line_exactly_on_the_line_cap_falls_through_to_the_capacity_gate():
    """25.0000 passes the cap by equality, so the 250,000,000 need against 100,000,000 bites.

    PRD: "The gate itself is then that the windowed committed total, plus this
    line's capacity — the target layer's `limit_minor` multiplied by
    `accepted_line_pct`, divided by one hundred and rounded half up to whole minor
    units — must be **no greater than** the market's `capacity_limit_minor`."

    Design: Difficulty/priority_pair_validation_conflict/oversized_line_on_tiny_market_reports_max_line_before_capacity
    """
    ctx = _foxtrot_re_quote()
    quote_id = ctx["quotes"][0]["id"]
    assert_money_equals(ctx["layer"]["limit_minor"], 1_000_000_000, "limit_minor")

    response = _attempt_firm_order(quote_id, ctx["layer"]["id"], 25.0000)

    validate_error(response, ApiErrorId.ERR_CAPACITY_EXCEEDED.value, 422)

    assert_status(read_quote(quote_id), "status", "QUOTED")
    layer = read_layer(ctx["layer"]["id"])
    assert_pct_equals(layer["written_line_total_pct"], 0.0000, "written_line_total_pct")
    assert_status(layer, "status", "IN_MARKET")
    market = read_reinsurer(ctx["reinsurers"][0]["id"])
    assert_money_equals(market["committed_capacity_minor"], 0, "committed_capacity_minor")
    assert_money_equals(
        market["available_capacity_minor"], 100_000_000, "available_capacity_minor"
    )
    assert_capacity_invariants(market)
    lines = list_rows(api_client.list_layer_signing_lines(ctx["layer"]["id"], LEAD))
    assert len(lines) == 0, f"the refused firm order must mint no signing line, got {lines!r}"


def _hotel_re_quote_at_the_round_cap(clock_at_expiry: bool):
    """Hotel Re's quote after three full counter/requote rounds, so negotiation_round is 3.

    Only the broker's counter advances the round counter, so three counters each
    answered by a requote leave the quote in ``REQUOTED`` at the cap. With
    ``clock_at_expiry`` true the clock is then parked on the quote's own
    ``expires_at`` instant, which has already lapsed it.
    """
    ctx = setup_program_in_market(
        market_specs=HOTEL_MARKET_SPECS,
        program_overrides=PROGRAM_OVERRIDES,
        submission_overrides=SUBMISSION_OVERRIDES,
    )
    send_submission(ctx)
    add_quote(
        ctx,
        offered_line_pct=50.0000,
        quoted_rate_pct=9.0000,
        ceding_commission_pct=0.0000,
        reinstatements_offered=1,
        sublimit_minor=0,
        expires_at=QUOTE_EXPIRES_AT,
        is_lead=True,
    )
    quote_id = ctx["quotes"][0]["id"]
    for counter_note, requoted_rate_pct in NEGOTIATION_ROUNDS:
        counter_quote(quote_id, counter_note)
        ctx["quote_at_cap"] = requote(
            quote_id,
            ctx["reinsurers"][0]["id"],
            offered_line_pct=50.0000,
            quoted_rate_pct=requoted_rate_pct,
            ceding_commission_pct=0.0000,
            reinstatements_offered=1,
            sublimit_minor=0,
            expires_at=QUOTE_EXPIRES_AT,
            is_lead=True,
        )
    if clock_at_expiry:
        set_clock(QUOTE_EXPIRES_AT)
    return ctx


def test_a_lapsed_quote_at_the_round_cap_reports_the_expiry_not_the_exhausted_rounds():
    """A clock sitting exactly on expires_at outranks a negotiation_round already at three.

    PRD: "The ladder runs authentication, then authorization, then request shape,
    then existence, then own-state, then cross-entity state, then stale parent
    version, then regulatory and compliance safety, then temporal windows, then
    structural constraints, then referential linkage, and finally fiscal capacity."

    Design: Difficulty/priority_pair_validation_conflict/expired_quote_at_round_cap_reports_expiry_before_round_exhaustion
    """
    ctx = _hotel_re_quote_at_the_round_cap(clock_at_expiry=True)
    quote_id = ctx["quotes"][0]["id"]
    assert ctx["quote_at_cap"]["negotiation_round"] == 3, (
        "three counters burn the whole cap, got "
        f"{ctx['quote_at_cap']['negotiation_round']!r}"
    )
    assert_status(ctx["quote_at_cap"], "status", "REQUOTED")

    response = _attempt_counter(quote_id, "one more, after the bell")

    error = validate_error(response, ApiErrorId.ERR_QUOTE_EXPIRED.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_NEGOTIATION_ROUNDS_EXHAUSTED.value, (
        "priority 46 outranks priority 57, so the round cap must stay silent"
    )

    quote = read_quote(quote_id)
    assert_status(quote, "status", "REQUOTED")
    assert quote["negotiation_round"] == 3, (
        f"the refused counter must not advance the round, got {quote['negotiation_round']!r}"
    )
    assert quote["last_counter_note"] == "round three", (
        f"last_counter_note must still hold round three, got {quote['last_counter_note']!r}"
    )


def test_a_live_quote_at_the_round_cap_reports_the_exhausted_rounds():
    """Leave the clock inside the quote's life and the structural round cap surfaces.

    PRD: "The quote's `negotiation_round` must be **less than three** before a
    further counter is accepted, so at most three counters are ever possible on one
    quote and a fourth attempt is refused with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`."

    Design: Difficulty/priority_pair_validation_conflict/expired_quote_at_round_cap_reports_expiry_before_round_exhaustion
    """
    ctx = _hotel_re_quote_at_the_round_cap(clock_at_expiry=False)
    quote_id = ctx["quotes"][0]["id"]
    assert ctx["quote_at_cap"]["negotiation_round"] == 3, (
        "three counters burn the whole cap, got "
        f"{ctx['quote_at_cap']['negotiation_round']!r}"
    )
    assert_status(ctx["quote_at_cap"], "status", "REQUOTED")

    response = _attempt_counter(quote_id, "one more, before the bell")

    validate_error(response, ApiErrorId.ERR_NEGOTIATION_ROUNDS_EXHAUSTED.value, 422)

    quote = read_quote(quote_id)
    assert_status(quote, "status", "REQUOTED")
    assert quote["negotiation_round"] == 3, (
        f"the refused counter must not advance the round, got {quote['negotiation_round']!r}"
    )
    assert quote["last_counter_note"] == "round three", (
        f"last_counter_note must still hold round three, got {quote['last_counter_note']!r}"
    )
    assert_pct_equals(quote["quoted_rate_pct"], 8.2000, "quoted_rate_pct")
