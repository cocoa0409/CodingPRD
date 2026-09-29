"""Stale parent versions, three-level derived totals and quote paging (PRD §2.3, §2.7, §2.9).

Queue B — section ``cross_cutting_complexity_layers``: the two declared
optimistic-concurrency fields (``expected_layer_version`` on a firm order and
``expected_program_version`` on a fiduciary booking), the premium, capacity and
placement totals that must reconcile across layer, market and program after a
create, a restructure and a release, and the offset windows of the quote
register.
"""
from test_helpers import (
    ACCOUNTANT,
    CLOCK,
    LEAD,
    OMIT,
    ApiErrorId,
    add_quote,
    api_client,
    approve_transaction,
    assert_capacity_invariants,
    assert_instant_equals,
    assert_money_equals,
    assert_pct_equals,
    assert_status,
    book_transaction,
    create_cedent,
    create_fiduciary_transaction_payload,
    create_market_submission_payload,
    create_program,
    current_layer_version,
    current_program_version,
    find_row,
    firm_order,
    firm_order_payload,
    go_to_market,
    make_accountant_headers,
    make_placement_lead_headers,
    read_layer,
    read_program,
    read_quote,
    read_reinsurer,
    read_signing_line,
    release_line,
    send_submission,
    set_clock,
    settle_transaction,
    setup_program_in_market,
    setup_submission_ready_program,
    update_layer_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# A second placement lead and a second accountant: the concurrency chains need a
# rival client that read the parent row at a different moment (PRD §2.1).
LEAD_TWO = make_placement_lead_headers("lead-2")
ACCOUNTANT_TWO = make_accountant_headers("acct-2")

# Every quote in this file lives well past the placement window so that nothing
# lapses for temporal reasons (PRD §3.4).
QUOTE_EXPIRY = "2026-03-01T00:00:00.000Z"

# Well-formed identifiers that are never the id of any row.
GHOST_QUOTE_ID = "00000000-0000-4000-8000-00000000abcd"
GHOST_PROGRAM_ID = "00000000-0000-4000-8000-0000000000ff"

# Three deep markets, each able to write the whole 1,000,000,000 catastrophe
# layer, so nothing in the concurrency chain is deflected by a capacity gate.
OCC_MARKET_SPECS = [
    {
        "name": "Alpha Re",
        "security_rating": "AA",
        "capacity_limit_minor": 5_000_000_000,
        "max_line_pct": 100.0000,
        "lead_authorised": True,
    },
    {
        "name": "Bravo Re",
        "security_rating": "A",
        "capacity_limit_minor": 5_000_000_000,
        "max_line_pct": 100.0000,
        "lead_authorised": False,
    },
    {
        "name": "Charlie Re",
        "security_rating": "A",
        "capacity_limit_minor": 5_000_000_000,
        "max_line_pct": 100.0000,
        "lead_authorised": False,
    },
]

# offered_line_pct, quoted_rate_pct, is_lead — one entry per market above. Alpha
# and Bravo together fill the layer exactly; Charlie is never addressed.
OCC_QUOTE_TERMS = [
    (60.0000, 8.0000, True),
    (40.0000, 8.2500, False),
    (20.0000, 8.5000, False),
]


def _occurrence_program_in_market():
    """Occurrence Mutual's catastrophe layer, program IN_MARKET, layer still OPEN."""
    return setup_program_in_market(
        cedent_overrides={"name": "Occurrence Mutual"},
        program_overrides={"program_name": "Occurrence Property CAT 2026"},
        submission_overrides={"package_label": "OM-EDP-1"},
        layer_overrides={"layer_label": "OM CAT 1B xs 2B"},
        market_specs=OCC_MARKET_SPECS,
    )


def _three_quoted_markets():
    """The prologue above plus three market submissions and three live quotes."""
    ctx = _occurrence_program_in_market()
    ctx["submissions"] = [send_submission(ctx, market_index=index) for index in range(3)]
    for index, (offered, rate, is_lead) in enumerate(OCC_QUOTE_TERMS):
        add_quote(
            ctx,
            market_index=index,
            market_submission=ctx["submissions"][index],
            offered_line_pct=offered,
            quoted_rate_pct=rate,
            is_lead=is_lead,
            expires_at=QUOTE_EXPIRY,
        )
    return ctx


def test_only_the_first_market_submission_moves_the_layer_version():
    """A layer opens at version 1, reaches 2 on its first submission and stays there.

    PRD: "The **first** submission on a layer also carries the layer from `OPEN`
    to `IN_MARKET`, which is the moment `quoted_gross_premium_minor` is frozen,
    and increments the layer's `version`."

    Design: Corner/cross_cutting_complexity_layers/firm_order_optimistic_concurrency_on_the_layer_version
    """
    ctx = _occurrence_program_in_market()
    layer_id = ctx["layer"]["id"]

    assert ctx["layer"]["version"] == 1, (
        f"a freshly created layer must open at version 1, got {ctx['layer']['version']}"
    )
    assert_status(ctx["layer"], "status", "OPEN")

    send_submission(ctx, market_index=0)
    layer = read_layer(layer_id)
    assert layer["version"] == 2, (
        f"the first market submission must take the layer to version 2, got {layer['version']}"
    )
    assert_status(layer, "status", "IN_MARKET")

    send_submission(ctx, market_index=1)
    send_submission(ctx, market_index=2)
    layer = read_layer(layer_id)
    assert layer["version"] == 2, (
        "the second and third submissions do not touch the layer row, so its version "
        f"must still be 2, got {layer['version']}"
    )
    assert_status(layer, "status", "IN_MARKET")
    assert current_layer_version(layer_id) == 2, (
        "the version a firm order must quote is still the one read after the first submission"
    )


def test_a_stale_layer_version_places_no_line_and_the_refreshed_retry_places_it():
    """Bravo's firm order at version 2 is refused, and the same order at version 3 lands.

    PRD: "If that value does not equal the layer's current `version`, the firm
    order is rejected with `ERR_STALE_LAYER_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/firm_order_optimistic_concurrency_on_the_layer_version
    """
    ctx = _three_quoted_markets()
    layer_id = ctx["layer"]["id"]
    alpha_quote, bravo_quote = ctx["quotes"][0], ctx["quotes"][1]

    # Both leads read the layer at the same moment: version 2.
    observed_version = current_layer_version(layer_id)
    assert observed_version == 2, (
        f"the layer sits at version 2 after three submissions, got {observed_version}"
    )

    alpha_line = firm_order(alpha_quote["id"], 60.0000, expected_layer_version=observed_version)
    layer = read_layer(layer_id)
    assert layer["version"] == 3, (
        f"Alpha's firm order cascades onto the layer row, so version 3, got {layer['version']}"
    )
    assert_status(layer, "status", "PARTIALLY_PLACED")
    assert_pct_equals(layer["written_line_total_pct"], 60.0000, "written_line_total_pct")

    rejected = api_client.firm_order(
        bravo_quote["id"], firm_order_payload(40.0000, observed_version), LEAD_TWO
    )
    validate_error(rejected, ApiErrorId.ERR_STALE_LAYER_VERSION.value)

    rows, meta = validate_paginated(api_client.list_layer_signing_lines(layer_id, LEAD))
    assert meta["total_count"] == 1, (
        f"the refused firm order must not have created a line, got {meta['total_count']}"
    )
    assert rows[0]["id"] == alpha_line["id"], "the only line on the layer is Alpha's"
    layer = read_layer(layer_id)
    assert layer["version"] == 3, (
        f"a refused firm order mutates nothing, so the version stays 3, got {layer['version']}"
    )
    assert_pct_equals(layer["written_line_total_pct"], 60.0000, "written_line_total_pct")
    assert_status(read_quote(bravo_quote["id"]), "status", "QUOTED")

    # The whole remedy is a re-read: nothing about the request itself changes.
    fresh_version = current_layer_version(layer_id)
    assert fresh_version == 3, f"the refreshed read must return 3, got {fresh_version}"
    bravo_line = firm_order(bravo_quote["id"], 40.0000, expected_layer_version=fresh_version)

    layer = read_layer(layer_id)
    assert layer["version"] == 4, (
        f"Bravo's accepted firm order takes the layer to version 4, got {layer['version']}"
    )
    assert_status(layer, "status", "FULLY_PLACED")
    assert_pct_equals(layer["written_line_total_pct"], 100.0000, "written_line_total_pct")
    assert_status(read_signing_line(bravo_line["id"]), "status", "PROVISIONAL")
    assert_status(read_program(ctx["program"]["id"]), "placement_status", "FIRM_ORDER")


def test_a_layer_version_from_the_future_is_refused_exactly_like_a_stale_one():
    """The gate is equality, so version 102 against a live version 3 is also a 412.

    PRD: "`expected_layer_version` must equal the layer's current `version` on
    `POST /quotes/{quote_id}/firm-order`, else `ERR_STALE_LAYER_VERSION`;
    `expected_program_version` must equal the program's current `version` on
    `POST /programs/{program_id}/fiduciary-transactions`, else
    `ERR_STALE_PROGRAM_VERSION`."

    Design: Corner/cross_cutting_complexity_layers/firm_order_optimistic_concurrency_on_the_layer_version
    """
    ctx = _three_quoted_markets()
    layer_id = ctx["layer"]["id"]
    alpha_quote, bravo_quote = ctx["quotes"][0], ctx["quotes"][1]

    alpha_line = firm_order(alpha_quote["id"], 60.0000, layer_id=layer_id)
    live_version = current_layer_version(layer_id)
    assert live_version == 3, f"the layer sits at version 3, got {live_version}"

    rejected = api_client.firm_order(
        bravo_quote["id"], firm_order_payload(40.0000, live_version + 99), LEAD
    )
    validate_error(rejected, ApiErrorId.ERR_STALE_LAYER_VERSION.value)

    rows, meta = validate_paginated(api_client.list_layer_signing_lines(layer_id, LEAD))
    assert meta["total_count"] == 1, (
        f"a version ahead of the row places no line either, got {meta['total_count']}"
    )
    assert rows[0]["id"] == alpha_line["id"], "the only line on the layer is Alpha's"
    layer = read_layer(layer_id)
    assert layer["version"] == 3, f"the layer row is untouched, got {layer['version']}"
    assert_pct_equals(layer["written_line_total_pct"], 60.0000, "written_line_total_pct")
    assert_status(layer, "status", "PARTIALLY_PLACED")


def test_shape_existence_and_quote_state_all_answer_before_the_stale_layer_version():
    """A missing field is a 400, a ghost quote a 404 and a lapsed quote a 409 — never a 412.

    PRD: "Checks are evaluated in ascending priority, and **the first violated
    rule decides the response** — later violations are never reported."

    Design: Corner/cross_cutting_complexity_layers/firm_order_optimistic_concurrency_on_the_layer_version
    """
    ctx = _three_quoted_markets()
    layer_id = ctx["layer"]["id"]
    alpha_quote, bravo_quote, charlie_quote = ctx["quotes"]

    # Request shape sits at priority 5, above the 412 at priority 35: dropping
    # expected_layer_version entirely is a validation failure, not a staleness one.
    missing_field = api_client.firm_order(
        bravo_quote["id"], firm_order_payload(40.0000, OMIT), LEAD
    )
    validate_error(missing_field, ApiErrorId.ERR_VALIDATION.value)

    # Existence sits at priority 15, still above the 412.
    ghost_quote = api_client.firm_order(
        GHOST_QUOTE_ID, firm_order_payload(20.0000, 99), LEAD
    )
    validate_error(ghost_quote, ApiErrorId.ERR_QUOTE_NOT_FOUND.value)

    rows, meta = validate_paginated(api_client.list_layer_signing_lines(layer_id, LEAD))
    assert meta["total_count"] == 0, (
        f"neither refusal may have placed a line, got {meta['total_count']}"
    )
    assert rows == [], "the layer carries no signing lines yet"

    # Fill the layer so the program reaches FIRM_ORDER and Charlie's quote lapses.
    firm_order(alpha_quote["id"], 60.0000, layer_id=layer_id)
    firm_order(bravo_quote["id"], 40.0000, layer_id=layer_id)
    assert_status(read_program(ctx["program"]["id"]), "placement_status", "FIRM_ORDER")
    assert_status(read_quote(charlie_quote["id"]), "status", "LAPSED")

    # Own-state sits at priority 26, still above the 412: the stale version in this
    # request is never reported because the quote's own status decides first.
    lapsed_quote = api_client.firm_order(
        charlie_quote["id"], firm_order_payload(20.0000, 2), LEAD
    )
    validate_error(lapsed_quote, ApiErrorId.ERR_QUOTE_STATE_INVALID.value)

    layer = read_layer(layer_id)
    assert_pct_equals(layer["written_line_total_pct"], 100.0000, "written_line_total_pct")
    assert_status(layer, "status", "FULLY_PLACED")


# --------------------------------------------------------------------------
# The fiduciary side of the same mechanism (PRD §2.7, §3.8)
# --------------------------------------------------------------------------
# The program carries no layers at all: the chain is purely about the ledger and
# the program row it hangs from.
RECEIPT_MINOR = 97_125_000
FOLLOW_ON_RECEIPT_MINOR = 20_000_000


def _program_with_one_booked_receipt():
    """Ledger Mutual's program plus one PENDING CEDENT_RECEIPT of 97,125,000."""
    set_clock(CLOCK["PLACEMENT_START"])
    cedent = create_cedent(name="Ledger Mutual")
    program = create_program(cedent["id"], program_name="Ledger Property CAT 2026")
    receipt = book_transaction(
        program["id"],
        "CEDENT_RECEIPT",
        RECEIPT_MINOR,
        expected_program_version=program["version"],
    )
    return {
        "cedent": cedent,
        "program": program,
        "receipt": receipt,
        "version_at_create": program["version"],
    }


def test_booking_a_movement_bumps_the_program_version_and_moves_no_money():
    """A program at version 1 reaches version 2 on a booking that leaves the balance at 0.

    PRD: "A booked movement records `created_by_user_id` as the booking
    accountant's identity, starts in `PENDING`, leaves `approved_by_user_id`,
    `value_date`, `hold_reason` and `reverses_transaction_id` null, and increments
    the program's `version`."

    Design: Corner/cross_cutting_complexity_layers/fiduciary_booking_optimistic_concurrency_on_the_program_version
    """
    ctx = _program_with_one_booked_receipt()
    program_id = ctx["program"]["id"]

    assert ctx["version_at_create"] == 1, (
        f"a freshly created program must open at version 1, got {ctx['version_at_create']}"
    )
    assert_status(ctx["receipt"], "status", "PENDING")
    assert ctx["receipt"]["created_by_user_id"] == "acct-1", (
        f"the booking identity is recorded, got {ctx['receipt']['created_by_user_id']!r}"
    )
    assert ctx["receipt"]["approved_by_user_id"] is None, "approval has not happened yet"
    assert ctx["receipt"]["value_date"] is None, "nothing has settled yet"

    program = read_program(program_id)
    assert program["version"] == 2, (
        f"booking the movement must take the program to version 2, got {program['version']}"
    )
    assert_money_equals(program["fiduciary_holding_minor"], 0, "fiduciary_holding_minor")
    assert current_program_version(program_id) == 2, (
        "the version an accountant must quote on the next booking is 2"
    )


def test_a_stale_program_version_books_nothing_into_the_ledger():
    """A second accountant booking against version 1 is refused and writes no row.

    PRD: "If that value does not equal the program's current `version`, the
    booking is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/fiduciary_booking_optimistic_concurrency_on_the_program_version
    """
    ctx = _program_with_one_booked_receipt()
    program_id = ctx["program"]["id"]

    rejected = api_client.create_fiduciary_transaction(
        program_id,
        create_fiduciary_transaction_payload(
            "CEDENT_RECEIPT", FOLLOW_ON_RECEIPT_MINOR, ctx["version_at_create"]
        ),
        ACCOUNTANT_TWO,
    )
    validate_error(rejected, ApiErrorId.ERR_STALE_PROGRAM_VERSION.value)

    rows, meta = validate_paginated(
        api_client.list_program_fiduciary_transactions(program_id, ACCOUNTANT)
    )
    assert meta["total_count"] == 1, (
        f"the refused booking must not have appended a row, got {meta['total_count']}"
    )
    assert rows[0]["id"] == ctx["receipt"]["id"], "the ledger holds only the first receipt"

    program = read_program(program_id)
    assert program["version"] == 2, (
        f"a refused booking mutates nothing, so the version stays 2, got {program['version']}"
    )
    assert_money_equals(program["fiduciary_holding_minor"], 0, "fiduciary_holding_minor")

    # Existence sits at priority 10, above the 412 at priority 36: a ghost program
    # is a 404 even though the version quoted is meaningless for it.
    ghost_program = api_client.create_fiduciary_transaction(
        GHOST_PROGRAM_ID,
        create_fiduciary_transaction_payload("CEDENT_RECEIPT", FOLLOW_ON_RECEIPT_MINOR, 1),
        ACCOUNTANT,
    )
    validate_error(ghost_program, ApiErrorId.ERR_PROGRAM_NOT_FOUND.value)


def test_approving_a_movement_leaves_the_program_version_alone():
    """Approval writes only the child row, so the version read before it still books.

    PRD: "Most resources additionally carry an `updated_at` timestamp, refreshed
    on every mutation, and a `version` integer that starts at 1 when the resource
    is created and increments by exactly one on every mutation of that resource —
    including mutations that arrive as a side effect of an operation on a
    different resource."

    Design: Corner/cross_cutting_complexity_layers/fiduciary_booking_optimistic_concurrency_on_the_program_version
    """
    ctx = _program_with_one_booked_receipt()
    program_id = ctx["program"]["id"]
    version_after_booking = current_program_version(program_id)
    assert version_after_booking == 2, (
        f"the program sits at version 2 after the booking, got {version_after_booking}"
    )

    approved = approve_transaction(ctx["receipt"]["id"])
    assert_status(approved, "status", "APPROVED")
    assert approved["approved_by_user_id"] == "compl-1", (
        f"the approving identity is stamped, got {approved['approved_by_user_id']!r}"
    )

    program = read_program(program_id)
    assert program["version"] == 2, (
        "approval mutates the movement and not the program, so the program stays at "
        f"version 2, got {program['version']}"
    )
    assert_money_equals(program["fiduciary_holding_minor"], 0, "fiduciary_holding_minor")

    # The read taken before the approval is therefore still fresh and still books.
    follow_on = book_transaction(
        program_id,
        "CEDENT_RECEIPT",
        FOLLOW_ON_RECEIPT_MINOR,
        headers=ACCOUNTANT_TWO,
        expected_program_version=version_after_booking,
    )
    assert_status(follow_on, "status", "PENDING")
    assert follow_on["created_by_user_id"] == "acct-2", (
        f"the second accountant is the booking identity, got {follow_on['created_by_user_id']!r}"
    )
    program = read_program(program_id)
    assert program["version"] == 3, (
        f"the second booking takes the program to version 3, got {program['version']}"
    )
    assert_money_equals(program["fiduciary_holding_minor"], 0, "fiduciary_holding_minor")


def test_settlement_moves_the_balance_so_the_pre_settlement_version_no_longer_books():
    """Settling the receipt lifts the balance to 97,125,000 and invalidates version 3.

    PRD: "Settlement stamps `value_date` with the current logical clock, moves the
    status to `SETTLED`, and recomputes the balance and the two cedent
    aggregates."

    Design: Corner/cross_cutting_complexity_layers/fiduciary_booking_optimistic_concurrency_on_the_program_version
    """
    ctx = _program_with_one_booked_receipt()
    program_id = ctx["program"]["id"]
    receipt_id = ctx["receipt"]["id"]

    approve_transaction(receipt_id)
    follow_on = book_transaction(
        program_id,
        "CEDENT_RECEIPT",
        FOLLOW_ON_RECEIPT_MINOR,
        headers=ACCOUNTANT_TWO,
        expected_program_version=2,
    )
    version_before_settlement = current_program_version(program_id)
    assert version_before_settlement == 3, (
        f"the program sits at version 3 before the settlement, got {version_before_settlement}"
    )

    settled = settle_transaction(receipt_id)
    assert_status(settled, "status", "SETTLED")
    assert_instant_equals(settled["value_date"], CLOCK["PLACEMENT_START"], "value_date")

    program = read_program(program_id)
    assert program["version"] == 4, (
        f"settlement rewrites the balance on the program, so version 4, got {program['version']}"
    )
    assert_money_equals(
        program["fiduciary_holding_minor"], RECEIPT_MINOR, "fiduciary_holding_minor"
    )

    rejected = api_client.create_fiduciary_transaction(
        program_id,
        create_fiduciary_transaction_payload(
            "CEDENT_PAYOUT", RECEIPT_MINOR, version_before_settlement
        ),
        ACCOUNTANT_TWO,
    )
    validate_error(rejected, ApiErrorId.ERR_STALE_PROGRAM_VERSION.value)

    # Re-reading the balance is exactly what the gate is for.
    fresh_version = current_program_version(program_id)
    assert fresh_version == 4, f"the refreshed read must return 4, got {fresh_version}"
    payout = book_transaction(
        program_id,
        "CEDENT_PAYOUT",
        RECEIPT_MINOR,
        headers=ACCOUNTANT_TWO,
        expected_program_version=fresh_version,
    )
    approve_transaction(payout["id"])
    assert_status(settle_transaction(payout["id"]), "status", "SETTLED")

    program = read_program(program_id)
    assert_money_equals(program["fiduciary_holding_minor"], 0, "fiduciary_holding_minor")

    rows, meta = validate_paginated(
        api_client.list_program_fiduciary_transactions(program_id, ACCOUNTANT)
    )
    assert meta["total_count"] == 3, (
        f"the append-only ledger holds three rows, got {meta['total_count']}"
    )
    assert rows[0]["id"] == receipt_id, "the settled receipt was booked first"
    assert_status(find_row(rows, follow_on["id"]), "status", "PENDING")
    assert_status(find_row(rows, payout["id"]), "status", "SETTLED")


# --------------------------------------------------------------------------
# Derived totals at three levels: layer, market and program (PRD §3.3, §3.5, §3.6)
# --------------------------------------------------------------------------
# Two markets deep enough to write the whole layer, so the reconciliation is
# never truncated by a capacity gate.
RECONCILE_MARKET_SPECS = [
    {
        "name": "Alpha Re",
        "security_rating": "AA",
        "capacity_limit_minor": 5_000_000_000,
        "max_line_pct": 100.0000,
        "lead_authorised": True,
    },
    {
        "name": "Bravo Re",
        "security_rating": "A",
        "capacity_limit_minor": 5_000_000_000,
        "max_line_pct": 100.0000,
        "lead_authorised": False,
    },
]

# offered_line_pct, quoted_rate_pct, is_lead — Alpha leads at 60.0000 and Bravo
# follows at 40.0000, filling the layer exactly.
RECONCILE_QUOTE_TERMS = [
    (60.0000, 7.0000, True),
    (40.0000, 7.2500, False),
]

# The canonical catastrophe layer prices at 97,125,000 on a base rate of 8.0000%.
# Restructured to 7.0000% the loaded rate is 7.3500%, the provisional premium is
# 91,875,000, which selects the 5.0000% tier, so the premium becomes 87,281,250.
PREMIUM_AT_BASE_RATE_8 = 97_125_000
PREMIUM_AT_BASE_RATE_7 = 87_281_250


def _reconcile_program_submission_ready():
    """Reconcile Mutual's catastrophe layer with the program at SUBMISSION_READY."""
    return setup_submission_ready_program(
        cedent_overrides={"name": "Reconcile Mutual"},
        program_overrides={"program_name": "Reconcile Property CAT 2026"},
        submission_overrides={"package_label": "RM-EDP-1"},
        layer_overrides={"layer_label": "RM CAT 1B xs 2B"},
        market_specs=RECONCILE_MARKET_SPECS,
    )


def _restructured_layer_with_two_quotes():
    """The layer restructured to 7.0000% while OPEN, then in market with two quotes."""
    ctx = _reconcile_program_submission_ready()
    validate_success(
        api_client.update_layer(
            ctx["layer"]["id"], update_layer_payload(base_rate_pct=7.0000), LEAD
        )
    )
    ctx["program"] = go_to_market(ctx["program"]["id"])
    for index, (offered, rate, is_lead) in enumerate(RECONCILE_QUOTE_TERMS):
        market_submission = send_submission(ctx, market_index=index)
        add_quote(
            ctx,
            market_index=index,
            market_submission=market_submission,
            offered_line_pct=offered,
            quoted_rate_pct=rate,
            is_lead=is_lead,
            expires_at=QUOTE_EXPIRY,
        )
    return ctx


def test_the_technical_premium_is_derived_on_create_and_rederived_on_a_restructure():
    """97,125,000 at a base rate of 8.0000% becomes 87,281,250 at 7.0000%.

    PRD: "It is computed when the layer is created, recomputed on every
    restructure while the layer is still `OPEN`, and then **frozen for ever** the
    moment the layer goes to market."

    Design: Corner/cross_cutting_complexity_layers/derived_totals_reconcile_across_three_levels_after_create_update_and_release
    """
    ctx = _reconcile_program_submission_ready()
    layer = ctx["layer"]

    assert_money_equals(
        layer["quoted_gross_premium_minor"],
        PREMIUM_AT_BASE_RATE_8,
        "quoted_gross_premium_minor at creation",
    )
    assert_pct_equals(layer["written_line_total_pct"], 0.0000, "written_line_total_pct")
    assert_pct_equals(layer["signed_line_total_pct"], 0.0000, "signed_line_total_pct")
    assert_status(layer, "status", "OPEN")

    patched = validate_success(
        api_client.update_layer(
            layer["id"], update_layer_payload(base_rate_pct=7.0000), LEAD
        )
    )
    assert_pct_equals(patched["base_rate_pct"], 7.0000, "base_rate_pct")
    assert_money_equals(
        patched["quoted_gross_premium_minor"],
        PREMIUM_AT_BASE_RATE_7,
        "quoted_gross_premium_minor after the restructure",
    )
    assert_status(patched, "status", "OPEN")
    assert_pct_equals(patched["written_line_total_pct"], 0.0000, "written_line_total_pct")

    reread = read_layer(layer["id"])
    assert_money_equals(
        reread["quoted_gross_premium_minor"],
        PREMIUM_AT_BASE_RATE_7,
        "quoted_gross_premium_minor on a fresh read",
    )


def test_a_layer_in_market_refuses_the_restructure_that_would_reprice_it():
    """Once the layer is IN_MARKET the same PATCH is a 409 and the premium holds.

    PRD: "Restructuring is permitted only while the layer is `OPEN` — from any
    other layer status the attempt is `ERR_LAYER_STATE_INVALID` — and only while
    the owning program is `DRAFT` or `SUBMISSION_READY`."

    Design: Corner/cross_cutting_complexity_layers/derived_totals_reconcile_across_three_levels_after_create_update_and_release
    """
    ctx = _reconcile_program_submission_ready()
    layer_id = ctx["layer"]["id"]
    validate_success(
        api_client.update_layer(layer_id, update_layer_payload(base_rate_pct=7.0000), LEAD)
    )
    ctx["program"] = go_to_market(ctx["program"]["id"])
    send_submission(ctx, market_index=0)
    send_submission(ctx, market_index=1)

    layer = read_layer(layer_id)
    assert_status(layer, "status", "IN_MARKET")
    assert_money_equals(
        layer["quoted_gross_premium_minor"],
        PREMIUM_AT_BASE_RATE_7,
        "quoted_gross_premium_minor frozen at market entry",
    )

    rejected = api_client.update_layer(
        layer_id, update_layer_payload(base_rate_pct=6.0000), LEAD
    )
    validate_error(rejected, ApiErrorId.ERR_LAYER_STATE_INVALID.value)

    layer = read_layer(layer_id)
    assert_pct_equals(layer["base_rate_pct"], 7.0000, "base_rate_pct after the refusal")
    assert_money_equals(
        layer["quoted_gross_premium_minor"],
        PREMIUM_AT_BASE_RATE_7,
        "quoted_gross_premium_minor after the refusal",
    )


def test_two_written_lines_reconcile_the_layer_total_and_both_markets_capacity():
    """60.0000 and 40.0000 tie up 600,000,000 and 400,000,000 and fill the layer.

    PRD: "A market's `committed_capacity_minor` is that sum and its
    `available_capacity_minor` is its `capacity_limit_minor` less that sum; both
    are refreshed whenever any of its lines is created, signed down or released."

    Design: Corner/cross_cutting_complexity_layers/derived_totals_reconcile_across_three_levels_after_create_update_and_release
    """
    ctx = _restructured_layer_with_two_quotes()
    layer_id = ctx["layer"]["id"]
    alpha, bravo = ctx["reinsurers"][0], ctx["reinsurers"][1]

    firm_order(ctx["quotes"][0]["id"], 60.0000, layer_id=layer_id)

    layer = read_layer(layer_id)
    assert_pct_equals(layer["written_line_total_pct"], 60.0000, "written_line_total_pct")
    assert_status(layer, "status", "PARTIALLY_PLACED")
    alpha_row = read_reinsurer(alpha["id"])
    assert_money_equals(
        alpha_row["committed_capacity_minor"], 600_000_000, "Alpha committed_capacity_minor"
    )
    assert_money_equals(
        alpha_row["available_capacity_minor"], 4_400_000_000, "Alpha available_capacity_minor"
    )
    assert_capacity_invariants(alpha_row)

    firm_order(ctx["quotes"][1]["id"], 40.0000, layer_id=layer_id)

    layer = read_layer(layer_id)
    assert_pct_equals(layer["written_line_total_pct"], 100.0000, "written_line_total_pct")
    assert_status(layer, "status", "FULLY_PLACED")
    assert_money_equals(
        layer["quoted_gross_premium_minor"],
        PREMIUM_AT_BASE_RATE_7,
        "quoted_gross_premium_minor is untouched by placement",
    )

    bravo_row = read_reinsurer(bravo["id"])
    assert_money_equals(
        bravo_row["committed_capacity_minor"], 400_000_000, "Bravo committed_capacity_minor"
    )
    assert_money_equals(
        bravo_row["available_capacity_minor"], 4_600_000_000, "Bravo available_capacity_minor"
    )
    assert_capacity_invariants(bravo_row)

    alpha_row = read_reinsurer(alpha["id"])
    assert_money_equals(
        alpha_row["committed_capacity_minor"],
        600_000_000,
        "Alpha committed_capacity_minor is unmoved by Bravo's line",
    )
    assert_money_equals(
        alpha_row["available_capacity_minor"],
        4_400_000_000,
        "Alpha available_capacity_minor is unmoved by Bravo's line",
    )

    program = read_program(ctx["program"]["id"])
    assert_status(program, "placement_status", "FIRM_ORDER")
    assert_money_equals(
        program["gross_written_premium_minor"],
        0,
        "gross_written_premium_minor counts BOUND layers only",
    )


def test_releasing_a_line_rederives_the_layer_the_market_and_the_program():
    """Handing Bravo's 40.0000 back leaves 60.0000 written, 5,000,000,000 free and IN_MARKET.

    PRD: "Third, a **compound status is always re-derived, never assumed**: a
    layer's status is a function of the signing lines currently on it, so after any
    line is created or released the totals are recomputed first and the status
    follows from the recomputed totals."

    Design: Corner/cross_cutting_complexity_layers/derived_totals_reconcile_across_three_levels_after_create_update_and_release
    """
    ctx = _restructured_layer_with_two_quotes()
    layer_id = ctx["layer"]["id"]
    alpha, bravo = ctx["reinsurers"][0], ctx["reinsurers"][1]
    alpha_line = firm_order(ctx["quotes"][0]["id"], 60.0000, layer_id=layer_id)
    bravo_line = firm_order(ctx["quotes"][1]["id"], 40.0000, layer_id=layer_id)

    released = release_line(bravo_line["id"])
    assert_status(released, "status", "RELEASED")
    assert_status(released, "release_reason", "WITHDRAWN_BY_BROKER")

    layer = read_layer(layer_id)
    assert_pct_equals(layer["written_line_total_pct"], 60.0000, "written_line_total_pct")
    assert_pct_equals(layer["signed_line_total_pct"], 0.0000, "signed_line_total_pct")
    assert_status(layer, "status", "PARTIALLY_PLACED")
    assert_money_equals(
        layer["quoted_gross_premium_minor"],
        PREMIUM_AT_BASE_RATE_7,
        "the frozen premium is not re-derived by a release",
    )

    bravo_row = read_reinsurer(bravo["id"])
    assert_money_equals(
        bravo_row["committed_capacity_minor"], 0, "Bravo committed_capacity_minor"
    )
    assert_money_equals(
        bravo_row["available_capacity_minor"], 5_000_000_000, "Bravo available_capacity_minor"
    )
    assert_capacity_invariants(bravo_row)

    alpha_row = read_reinsurer(alpha["id"])
    assert_money_equals(
        alpha_row["committed_capacity_minor"],
        600_000_000,
        "Alpha committed_capacity_minor survives Bravo's release",
    )
    assert_money_equals(
        alpha_row["available_capacity_minor"],
        4_400_000_000,
        "Alpha available_capacity_minor survives Bravo's release",
    )

    program = read_program(ctx["program"]["id"])
    assert_status(program, "placement_status", "IN_MARKET")
    assert_money_equals(
        program["gross_written_premium_minor"], 0, "gross_written_premium_minor"
    )
    assert_status(read_quote(ctx["quotes"][1]["id"]), "status", "LAPSED")

    # The released line is retained rather than deleted, so both rows still read.
    rows, meta = validate_paginated(api_client.list_layer_signing_lines(layer_id, LEAD))
    assert meta["total_count"] == 2, (
        f"a release retains the line as a RELEASED row, got {meta['total_count']}"
    )
    assert_status(find_row(rows, alpha_line["id"]), "status", "PROVISIONAL")
    assert_status(find_row(rows, bravo_line["id"]), "status", "RELEASED")

    bravo_rows, bravo_meta = validate_paginated(
        api_client.list_reinsurer_signing_lines(bravo["id"], LEAD)
    )
    assert bravo_meta["total_count"] == 1, (
        f"Bravo still owns exactly one line row, got {bravo_meta['total_count']}"
    )
    assert bravo_rows[0]["id"] == bravo_line["id"], "and it is the released one"
    assert_status(bravo_rows[0], "status", "RELEASED")
    assert_status(bravo_rows[0], "release_reason", "WITHDRAWN_BY_BROKER")

    # The revert is a recompute, not an undo: the reverted layer is not back OPEN
    # and the lapsed quote is not revived.
    resent = api_client.create_market_submission(
        layer_id, create_market_submission_payload(bravo["id"]), LEAD
    )
    validate_error(resent, ApiErrorId.ERR_LAYER_STATE_INVALID.value)

    reordered = api_client.firm_order(
        ctx["quotes"][1]["id"],
        firm_order_payload(40.0000, current_layer_version(layer_id)),
        LEAD,
    )
    validate_error(reordered, ApiErrorId.ERR_QUOTE_STATE_INVALID.value)


# --------------------------------------------------------------------------
# The quote register: ordering, offset windows and declared filters (PRD §2.3)
# --------------------------------------------------------------------------
PAGING_MARKET_SPECS = [
    {
        "name": "Alpha Re",
        "security_rating": "AA",
        "capacity_limit_minor": 5_000_000_000,
        "max_line_pct": 100.0000,
        "lead_authorised": True,
    },
    {
        "name": "Bravo Re",
        "security_rating": "A",
        "capacity_limit_minor": 5_000_000_000,
        "max_line_pct": 100.0000,
        "lead_authorised": False,
    },
    {
        "name": "Charlie Re",
        "security_rating": "A",
        "capacity_limit_minor": 5_000_000_000,
        "max_line_pct": 100.0000,
        "lead_authorised": False,
    },
    {
        "name": "Delta Re",
        "security_rating": "A",
        "capacity_limit_minor": 5_000_000_000,
        "max_line_pct": 100.0000,
        "lead_authorised": False,
    },
    {
        "name": "Echo Re",
        "security_rating": "A",
        "capacity_limit_minor": 5_000_000_000,
        "max_line_pct": 100.0000,
        "lead_authorised": False,
    },
]

# offered_line_pct, quoted_rate_pct, is_lead, the instant the quote is created on.
# One second between quotes, so the ascending created_at order is unambiguous.
PAGING_QUOTE_TERMS = [
    (30.0000, 8.0000, True, "2026-01-01T00:00:01.000Z"),
    (25.0000, 8.1000, False, "2026-01-01T00:00:02.000Z"),
    (20.0000, 8.2000, False, "2026-01-01T00:00:03.000Z"),
    (15.0000, 8.3000, False, "2026-01-01T00:00:04.000Z"),
    (10.0000, 8.4000, False, "2026-01-01T00:00:05.000Z"),
]


def _five_quotes_on_one_layer():
    """Paging Mutual's layer with five markets quoting one second apart."""
    ctx = setup_program_in_market(
        cedent_overrides={"name": "Paging Mutual"},
        program_overrides={"program_name": "Paging Property CAT 2026"},
        submission_overrides={"package_label": "PM-EDP-1"},
        layer_overrides={"layer_label": "PM CAT 1B xs 2B"},
        market_specs=PAGING_MARKET_SPECS,
    )
    ctx["submissions"] = [send_submission(ctx, market_index=index) for index in range(5)]
    for index, (offered, rate, is_lead, instant) in enumerate(PAGING_QUOTE_TERMS):
        set_clock(instant)
        add_quote(
            ctx,
            market_index=index,
            market_submission=ctx["submissions"][index],
            offered_line_pct=offered,
            quoted_rate_pct=rate,
            is_lead=is_lead,
            expires_at=QUOTE_EXPIRY,
        )
    return ctx


def test_the_quote_register_reads_in_created_at_order_inside_the_default_window():
    """Five quotes come back oldest first under the default limit 10 and offset 0.

    PRD: "Collections are returned in ascending `created_at` order."

    Design: Corner/cross_cutting_complexity_layers/quote_listing_composes_filters_ordering_and_offset_windows_across_a_mutation
    """
    ctx = _five_quotes_on_one_layer()
    layer_id = ctx["layer"]["id"]

    response = api_client.list_quotes(LEAD, {"layer_id": layer_id})
    assert response.json()["response_type"] == "array", (
        f"a collection answers response_type array, got {response.json()['response_type']!r}"
    )
    rows, meta = validate_paginated(response)

    assert [row["id"] for row in rows] == [quote["id"] for quote in ctx["quotes"]], (
        "the five quotes must come back in the order they were created"
    )
    for row, (_offered, _rate, _is_lead, instant) in zip(rows, PAGING_QUOTE_TERMS):
        assert_instant_equals(row["created_at"], instant, "quote created_at")
    assert meta["limit"] == 10, f"the default limit is 10, got {meta['limit']}"
    assert meta["offset"] == 0, f"the default offset is 0, got {meta['offset']}"
    assert meta["total_count"] == 5, f"five quotes match the filter, got {meta['total_count']}"
    assert meta["has_more"] is False, "0 + 5 is not less than 5, so has_more is false"


def test_the_offset_window_walks_the_register_while_total_count_ignores_it():
    """Three two-row pages cover q1..q5 and every page reports total_count 5.

    PRD: "Four pagination fields appear in the `meta` object of every list
    response: `limit` and `offset` echo the effective values used, `total_count`
    is the number of rows matching the request's filters **before** `limit` and
    `offset` are applied, and `has_more` is true exactly when the sum of `offset`
    and the number of rows returned in this page is less than `total_count`."

    Design: Corner/cross_cutting_complexity_layers/quote_listing_composes_filters_ordering_and_offset_windows_across_a_mutation
    """
    ctx = _five_quotes_on_one_layer()
    layer_id = ctx["layer"]["id"]
    quote_ids = [quote["id"] for quote in ctx["quotes"]]

    for offset, expected_ids, expected_has_more in (
        (0, quote_ids[0:2], True),
        (2, quote_ids[2:4], True),
        (4, quote_ids[4:5], False),
    ):
        rows, meta = validate_paginated(
            api_client.list_quotes(LEAD, {"layer_id": layer_id, "limit": 2, "offset": offset})
        )
        assert [row["id"] for row in rows] == expected_ids, (
            f"offset {offset} with limit 2 must return {expected_ids}, "
            f"got {[row['id'] for row in rows]}"
        )
        assert meta["limit"] == 2, f"the echoed limit at offset {offset} must be 2"
        assert meta["offset"] == offset, f"the echoed offset must be {offset}"
        assert meta["total_count"] == 5, (
            f"total_count is the population before the window, got {meta['total_count']}"
        )
        assert meta["has_more"] is expected_has_more, (
            f"has_more at offset {offset} must be {expected_has_more}"
        )

    # The 100 ceiling is inclusive, so it returns the whole population in one page.
    rows, meta = validate_paginated(
        api_client.list_quotes(LEAD, {"layer_id": layer_id, "limit": 100})
    )
    assert [row["id"] for row in rows] == quote_ids, "limit 100 returns all five quotes"
    assert meta["limit"] == 100, f"the echoed limit must be 100, got {meta['limit']}"
    assert meta["total_count"] == 5, f"total_count is still 5, got {meta['total_count']}"
    assert meta["has_more"] is False, "0 + 5 is not less than 5, so has_more is false"

    # An offset past the end of the population is a legal empty page, not an error.
    rows, meta = validate_paginated(
        api_client.list_quotes(LEAD, {"layer_id": layer_id, "limit": 2, "offset": 99})
    )
    assert rows == [], f"offset 99 lies past the population, got {rows}"
    assert meta["offset"] == 99, f"the echoed offset must be 99, got {meta['offset']}"
    assert meta["total_count"] == 5, (
        f"total_count still counts the whole population, got {meta['total_count']}"
    )
    assert meta["has_more"] is False, "99 + 0 is not less than 5, so has_more is false"


def test_a_limit_or_offset_outside_its_bounds_is_a_validation_failure():
    """limit 0, limit 101 and offset -1 are each rejected on the quote register.

    PRD: "A `limit` that is not an integer, is below 1 or is above 100, and an
    `offset` that is not an integer or is negative, are rejected with
    `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/cross_cutting_complexity_layers/quote_listing_composes_filters_ordering_and_offset_windows_across_a_mutation
    """
    ctx = _five_quotes_on_one_layer()
    layer_id = ctx["layer"]["id"]

    for params in (
        {"layer_id": layer_id, "limit": 0},
        {"layer_id": layer_id, "limit": 101},
        {"layer_id": layer_id, "offset": -1},
    ):
        rejected = api_client.list_quotes(LEAD, params)
        validate_error(rejected, ApiErrorId.ERR_VALIDATION.value)

    # The bounds are inclusive at both ends, so 1 and 100 are both legal.
    rows, meta = validate_paginated(
        api_client.list_quotes(LEAD, {"layer_id": layer_id, "limit": 1, "offset": 0})
    )
    assert [row["id"] for row in rows] == [ctx["quotes"][0]["id"]], (
        "limit 1 returns the oldest quote alone"
    )
    assert meta["total_count"] == 5, f"total_count is unaffected, got {meta['total_count']}"
    assert meta["has_more"] is True, "0 + 1 is less than 5, so has_more is true"


def test_the_declared_quote_filters_compose_and_an_empty_population_is_still_a_200():
    """layer_id with reinsurer_id narrows to one row, and a contradictory pair to none.

    PRD: "Four pagination fields appear in the `meta` object of every list
    response: `limit` and `offset` echo the effective values used, `total_count`
    is the number of rows matching the request's filters **before** `limit` and
    `offset` are applied, and `has_more` is true exactly when the sum of `offset`
    and the number of rows returned in this page is less than `total_count`."

    Design: Corner/cross_cutting_complexity_layers/quote_listing_composes_filters_ordering_and_offset_windows_across_a_mutation
    """
    ctx = _five_quotes_on_one_layer()
    layer_id = ctx["layer"]["id"]
    alpha, bravo = ctx["reinsurers"][0], ctx["reinsurers"][1]

    rows, meta = validate_paginated(
        api_client.list_quotes(LEAD, {"layer_id": layer_id, "reinsurer_id": alpha["id"]})
    )
    assert [row["id"] for row in rows] == [ctx["quotes"][0]["id"]], (
        "the layer and the market together select Alpha's quote alone"
    )
    assert meta["total_count"] == 1, (
        f"total_count counts the filtered population, got {meta['total_count']}"
    )
    assert meta["has_more"] is False, "0 + 1 is not less than 1, so has_more is false"

    rows, meta = validate_paginated(
        api_client.list_quotes(
            LEAD, {"market_submission_id": ctx["submissions"][2]["id"]}
        )
    )
    assert [row["id"] for row in rows] == [ctx["quotes"][2]["id"]], (
        "the submission filter selects the quote written against it"
    )
    assert meta["total_count"] == 1, f"exactly one quote matches, got {meta['total_count']}"

    # Alpha's submission and Bravo's identity never coincide on one row.
    response = api_client.list_quotes(
        LEAD,
        {"market_submission_id": ctx["submissions"][0]["id"], "reinsurer_id": bravo["id"]},
    )
    assert response.status_code == 200, (
        f"an empty population is a 200, not a 404, got {response.status_code}"
    )
    rows, meta = validate_paginated(response)
    assert rows == [], f"no quote matches both filters, got {rows}"
    assert meta["total_count"] == 0, (
        f"total_count over an empty population is 0, got {meta['total_count']}"
    )
    assert meta["has_more"] is False, "0 + 0 is not less than 0, so has_more is false"
