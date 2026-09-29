"""Transitive cascades from a firm order and from a claim collection (PRD §2.9, §3.5, §3.9).

Queue A — rule ``transitive_cascade``: one four-hop chain triggered by a firm
order (line -> layer -> program -> rival quote lapse) and one three-hop chain
triggered by a fiduciary collection (erosion -> reinstatement premium -> the
cedent's own aggregate). Nothing but the first link is asked for by the caller.
"""
from test_helpers import (
    ACCOUNTANT,
    add_quote,
    api_client,
    assert_capacity_invariants,
    assert_is_null,
    assert_money_equals,
    assert_pct_equals,
    assert_status,
    collect,
    firm_order,
    list_rows,
    notify_claim,
    read_advocacy,
    read_cedent,
    read_layer,
    read_market_submission,
    read_program,
    read_quote,
    read_reinsurer,
    read_signing_line,
    review_claim,
    send_submission,
    setup_bound_program,
    setup_program_in_market,
)

# Three markets on one 1,000,000,000 catastrophe layer. Alpha leads at 60.0000
# and Bravo follows at 50.0000, which together written-total 110.0000; Echo's
# 40.0000 quote is never addressed by the broker at all.
CASCADE_MARKET_SPECS = [
    {
        "name": "Alpha Re",
        "security_rating": "AA",
        "capacity_limit_minor": 2_000_000_000,
        "max_line_pct": 60.0000,
        "lead_authorised": True,
    },
    {
        "name": "Bravo Re",
        "security_rating": "A",
        "capacity_limit_minor": 2_000_000_000,
        "max_line_pct": 50.0000,
        "lead_authorised": False,
    },
    {
        "name": "Echo Re",
        "security_rating": "A",
        "capacity_limit_minor": 1_000_000_000,
        "max_line_pct": 40.0000,
        "lead_authorised": False,
    },
]

# offered_line_pct, quoted_rate_pct, is_lead — one entry per market above.
CASCADE_QUOTE_TERMS = [
    (60.0000, 8.0000, True),
    (50.0000, 8.0000, False),
    (40.0000, 8.5000, False),
]

# The single market holding the whole catastrophe layer for the collection chain:
# limit 1,000,000,000 with one reinstatement at 100.0000%, technical premium
# 97,125,000 minor units.
COLLECTION_MARKET_SPECS = [
    {
        "name": "Echo Re",
        "security_rating": "AA",
        "capacity_limit_minor": 1_000_000_000,
        "max_line_pct": 100.0000,
        "lead_authorised": True,
    }
]

FIRST_CLAIM = {
    "claim_reference": "CL-2026-CAT-001",
    "event_date": "2026-03-01T00:00:00.000Z",
    "gross_claim_minor": 2_600_000_000,
}
SECOND_CLAIM = {
    "claim_reference": "CL-2026-CAT-002",
    "event_date": "2026-09-01T00:00:00.000Z",
    "gross_claim_minor": 3_200_000_000,
}


def _three_markets_quoted_with_the_lead_line_placed():
    """Three live quotes on one layer, with only Alpha's 60.0000 line firm-ordered.

    Leaves the layer PARTIALLY_PLACED at 60.0000, the program still IN_MARKET and
    Echo's quote untouched in QUOTED. ``ctx["layer_before"]`` is the layer read
    immediately before the trigger.
    """
    ctx = setup_program_in_market(
        market_specs=CASCADE_MARKET_SPECS,
        program_overrides={
            "program_name": "Northwind Property CAT 2026",
            "signdown_method": "PRO_RATA",
        },
        submission_overrides={"package_label": "NW-CAT-2026-EDP"},
    )
    for index, (offered_line_pct, quoted_rate_pct, is_lead) in enumerate(
        CASCADE_QUOTE_TERMS
    ):
        market_submission = send_submission(ctx, market_index=index)
        add_quote(
            ctx,
            market_index=index,
            market_submission=market_submission,
            offered_line_pct=offered_line_pct,
            quoted_rate_pct=quoted_rate_pct,
            is_lead=is_lead,
        )
    ctx["signing_lines"].append(
        firm_order(ctx["quotes"][0]["id"], 60.0000, layer_id=ctx["layer"]["id"])
    )
    ctx["layer_before"] = read_layer(ctx["layer"]["id"])
    return ctx


def test_firm_order_materialises_a_provisional_line_reserving_the_written_capacity():
    """Bravo's 50.0000 firm order mints a PROVISIONAL line tying up 500,000,000.

    PRD: "The first hop creates a signing line whose `layer_id`, `quote_id` and
    `reinsurer_id` identify the layer, the quote and the market, whose
    `written_line_pct` is copied from the `accepted_line_pct` just accepted and is
    **never mutated again**, whose `signed_line_pct` is null, and whose status is
    `PROVISIONAL`."

    Design: Difficulty/transitive_cascade/firm_order_cascades_line_to_layer_to_program_to_rival_quote_lapse
    """
    ctx = _three_markets_quoted_with_the_lead_line_placed()
    assert_status(ctx["layer_before"], "status", "PARTIALLY_PLACED")
    assert_pct_equals(
        ctx["layer_before"]["written_line_total_pct"], 60.0000, "written_line_total_pct before"
    )

    follower_line = firm_order(
        ctx["quotes"][1]["id"], 50.0000, layer_id=ctx["layer"]["id"]
    )

    line = read_signing_line(follower_line["id"])
    assert_status(line, "status", "PROVISIONAL")
    assert_pct_equals(line["written_line_pct"], 50.0000, "written_line_pct")
    assert_is_null(line, "signed_line_pct")
    assert_pct_equals(line["effective_line_pct"], 50.0000, "effective_line_pct")
    assert_money_equals(
        line["committed_capacity_minor"], 500_000_000, "committed_capacity_minor"
    )
    assert line["layer_id"] == ctx["layer"]["id"], "the line names the target layer"
    assert line["quote_id"] == ctx["quotes"][1]["id"], "the line names the firm-ordered quote"
    assert line["reinsurer_id"] == ctx["reinsurers"][1]["id"], "the line names Bravo Re"


def test_the_new_line_pushes_the_layer_written_total_to_one_hundred_and_ten():
    """The second link: 60.0000 + 50.0000 re-derives the layer as OVERSUBSCRIBED.

    PRD: "The second hop recomputes the layer's `written_line_total_pct` — the sum
    of `written_line_pct` over the layer's lines in `PROVISIONAL`, `SIGNED` or
    `BOUND` — and lets the layer's compound status follow from the recomputed
    total: a total greater than `0.0000` but less than `100.0000` leaves the layer
    `PARTIALLY_PLACED`, a total of exactly `100.0000` makes it `FULLY_PLACED`, and
    a total greater than `100.0000` makes it `OVERSUBSCRIBED`."

    Design: Difficulty/transitive_cascade/firm_order_cascades_line_to_layer_to_program_to_rival_quote_lapse
    """
    ctx = _three_markets_quoted_with_the_lead_line_placed()
    assert_status(ctx["layer_before"], "status", "PARTIALLY_PLACED")
    assert_pct_equals(
        ctx["layer_before"]["written_line_total_pct"], 60.0000, "written_line_total_pct before"
    )

    firm_order(ctx["quotes"][1]["id"], 50.0000, layer_id=ctx["layer"]["id"])

    layer = read_layer(ctx["layer"]["id"])
    assert_pct_equals(layer["written_line_total_pct"], 110.0000, "written_line_total_pct")
    assert_status(layer, "status", "OVERSUBSCRIBED")
    assert_pct_equals(layer["signed_line_total_pct"], 0.0000, "signed_line_total_pct")


def test_the_oversubscribed_layer_promotes_the_program_and_lapses_the_untouched_rival_quote():
    """Links three and four: the program reaches FIRM_ORDER and Echo's quote dies unaddressed.

    PRD: "The fourth hop is caused by that program transition rather than by the
    original firm order, and it clears the market down: every quote on the
    program's layers still in `QUOTED`, `COUNTERED` or `REQUOTED` becomes
    `LAPSED`, and every market submission on those layers still in `SENT` or
    `QUOTED` becomes `CLOSED`."

    Design: Difficulty/transitive_cascade/firm_order_cascades_line_to_layer_to_program_to_rival_quote_lapse
    """
    ctx = _three_markets_quoted_with_the_lead_line_placed()
    assert_status(read_program(ctx["program"]["id"]), "placement_status", "IN_MARKET")
    assert_status(read_quote(ctx["quotes"][2]["id"]), "status", "QUOTED")

    firm_order(ctx["quotes"][1]["id"], 50.0000, layer_id=ctx["layer"]["id"])

    assert_status(read_program(ctx["program"]["id"]), "placement_status", "FIRM_ORDER")

    assert_status(read_quote(ctx["quotes"][2]["id"]), "status", "LAPSED")
    assert_status(read_market_submission(ctx["market_submissions"][2]["id"]), "status", "CLOSED")

    assert_status(read_quote(ctx["quotes"][0]["id"]), "status", "FIRM_ORDER")
    assert_status(read_quote(ctx["quotes"][1]["id"]), "status", "FIRM_ORDER")
    assert_status(read_market_submission(ctx["market_submissions"][0]["id"]), "status", "CLOSED")
    assert_status(read_market_submission(ctx["market_submissions"][1]["id"]), "status", "CLOSED")


def test_the_cascade_refreshes_committed_capacity_only_for_the_markets_holding_a_line():
    """Bravo ties up 500,000,000 of its 2,000,000,000 while Echo stays wholly uncommitted.

    PRD: "A market's `committed_capacity_minor` is that sum and its
    `available_capacity_minor` is its `capacity_limit_minor` less that sum; both
    are refreshed whenever any of its lines is created, signed down or released."

    Design: Difficulty/transitive_cascade/firm_order_cascades_line_to_layer_to_program_to_rival_quote_lapse
    """
    ctx = _three_markets_quoted_with_the_lead_line_placed()

    firm_order(ctx["quotes"][1]["id"], 50.0000, layer_id=ctx["layer"]["id"])

    bravo = read_reinsurer(ctx["reinsurers"][1]["id"])
    assert_money_equals(
        bravo["committed_capacity_minor"], 500_000_000, "Bravo committed_capacity_minor"
    )
    assert_money_equals(
        bravo["available_capacity_minor"], 1_500_000_000, "Bravo available_capacity_minor"
    )
    assert_capacity_invariants(bravo)

    echo = read_reinsurer(ctx["reinsurers"][2]["id"])
    assert_money_equals(
        echo["committed_capacity_minor"], 0, "Echo committed_capacity_minor"
    )
    assert_money_equals(
        echo["available_capacity_minor"], 1_000_000_000, "Echo available_capacity_minor"
    )
    assert_capacity_invariants(echo)

    alpha = read_reinsurer(ctx["reinsurers"][0]["id"])
    assert_money_equals(
        alpha["committed_capacity_minor"], 600_000_000, "Alpha committed_capacity_minor"
    )
    assert_money_equals(
        alpha["available_capacity_minor"], 1_400_000_000, "Alpha available_capacity_minor"
    )
    assert_capacity_invariants(alpha)


def _collected_first_claim_and_second_claim_under_review():
    """One bound layer, a first claim already collected, a second claim UNDER_REVIEW.

    The first claim cedes 600,000,000 and is driven to COLLECTED, so the layer is
    eroded by 600,000,000 with no reinstatement consumed. The second claim cedes
    1,000,000,000 — the per-event limit caps its 1,200,000,000 subject amount — and
    waits in UNDER_REVIEW with nothing collected against it.
    """
    ctx = setup_bound_program(
        market_specs=COLLECTION_MARKET_SPECS,
        program_overrides={"program_name": "Northwind Property CAT 2026"},
        submission_overrides={"package_label": "NW-CAT-2026-EDP"},
    )
    first = notify_claim(ctx["layer"]["id"], ctx["cedent"]["id"], **FIRST_CLAIM)
    review_claim(first["id"])
    collect(first["id"], ctx["signing_lines"][0]["id"], 600_000_000)
    ctx["first_advocacy"] = read_advocacy(first["id"])
    ctx["layer_after_first"] = read_layer(ctx["layer"]["id"])
    second = notify_claim(ctx["layer"]["id"], ctx["cedent"]["id"], **SECOND_CLAIM)
    review_claim(second["id"])
    ctx["second_advocacy"] = read_advocacy(second["id"])
    return ctx


def test_a_collection_closing_the_collectible_amount_carries_the_file_to_collected():
    """The first link: booking 1,000,000,000 against a 1,000,000,000 collectible closes the file.

    PRD: "When the recomputed `collected_minor` reaches or exceeds
    `collectible_minor`, the file becomes `COLLECTED`, which is terminal, and this
    is reachable both from `RESOLVED` and directly from `UNDER_REVIEW` when no
    dispute was ever raised on the file."

    Design: Difficulty/transitive_cascade/collection_cascades_erosion_to_reinstatement_premium_to_cedent_exposure
    """
    ctx = _collected_first_claim_and_second_claim_under_review()
    assert_money_equals(
        ctx["first_advocacy"]["ceded_claim_minor"], 600_000_000, "first ceded_claim_minor"
    )
    assert_money_equals(
        ctx["second_advocacy"]["ceded_claim_minor"], 1_000_000_000, "second ceded_claim_minor"
    )
    assert_money_equals(
        ctx["second_advocacy"]["collectible_minor"], 1_000_000_000, "second collectible_minor"
    )
    assert_status(ctx["second_advocacy"], "status", "UNDER_REVIEW")
    assert_money_equals(ctx["second_advocacy"]["collected_minor"], 0, "collected_minor before")

    collect(ctx["second_advocacy"]["id"], ctx["signing_lines"][0]["id"], 1_000_000_000)

    advocacy = read_advocacy(ctx["second_advocacy"]["id"])
    assert_status(advocacy, "status", "COLLECTED")
    # PRD: "The file's `collected_minor` is then recomputed as the sum of
    # `amount_minor` over the `CLAIM_COLLECTION` movements linked to the file's
    # signing lines whose status is `PENDING`, `APPROVED` or `SETTLED`." Echo Re
    # writes the whole layer, so the 600,000,000 already collected on the first
    # file sits on the very same signing line and the recomputed sum is
    # 1,600,000,000 — comfortably at or above the 1,000,000,000 collectible,
    # which is what closes the file.
    assert_money_equals(advocacy["collected_minor"], 1_600_000_000, "collected_minor")
    assert_money_equals(advocacy["collectible_minor"], 1_000_000_000, "collectible_minor")


def test_reaching_collected_charges_the_erosion_and_consumes_the_reinstatement():
    """The second link: erosion climbs to 1,600,000,000 and burns reinstatement one.

    PRD: "The first hop charges the erosion: the layer's `limit_eroded_minor`
    increases by the file's `ceded_claim_minor` and its `reinstatements_used` is
    recomputed as described above, with `reinstatement_triggered` set on the file
    when the count moved."

    Design: Difficulty/transitive_cascade/collection_cascades_erosion_to_reinstatement_premium_to_cedent_exposure
    """
    ctx = _collected_first_claim_and_second_claim_under_review()
    assert_money_equals(
        ctx["layer_after_first"]["limit_eroded_minor"], 600_000_000, "limit_eroded_minor before"
    )
    assert ctx["layer_after_first"]["reinstatements_used"] == 0, (
        "burning part of the first limit uses no reinstatement, got "
        f"{ctx['layer_after_first']['reinstatements_used']!r}"
    )

    collect(ctx["second_advocacy"]["id"], ctx["signing_lines"][0]["id"], 1_000_000_000)

    layer = read_layer(ctx["layer"]["id"])
    assert_money_equals(layer["limit_eroded_minor"], 1_600_000_000, "limit_eroded_minor")
    assert layer["reinstatements_used"] == 1, (
        f"crossing into the second limit uses one reinstatement, got {layer['reinstatements_used']!r}"
    )
    advocacy = read_advocacy(ctx["second_advocacy"]["id"])
    assert advocacy["reinstatement_triggered"] is True, (
        "reinstatement_triggered must be true once the count moved"
    )


def test_the_consumed_reinstatement_appends_a_pending_reinstatement_premium_movement():
    """The third link: 100.0000% of 97,125,000 pro-rated on 600,000,000 reinstated is 58,275,000.

    PRD: "The second hop, only when a reinstatement was consumed, appends a
    `REINSTATEMENT_PREMIUM` fiduciary movement on the program in status `PENDING`
    for the reinstatement premium computed above."

    Design: Difficulty/transitive_cascade/collection_cascades_erosion_to_reinstatement_premium_to_cedent_exposure
    """
    ctx = _collected_first_claim_and_second_claim_under_review()
    assert_money_equals(
        ctx["layer"]["quoted_gross_premium_minor"], 97_125_000, "quoted_gross_premium_minor"
    )

    collect(ctx["second_advocacy"]["id"], ctx["signing_lines"][0]["id"], 1_000_000_000)

    ledger = list_rows(
        api_client.list_program_fiduciary_transactions(
            ctx["program"]["id"], ACCOUNTANT, {"limit": 100}
        )
    )
    reinstatement_rows = [
        row for row in ledger if row["txn_type"] == "REINSTATEMENT_PREMIUM"
    ]
    assert len(reinstatement_rows) == 1, (
        f"exactly one REINSTATEMENT_PREMIUM movement is appended, got {len(reinstatement_rows)}"
    )
    row = reinstatement_rows[0]
    assert_money_equals(row["amount_minor"], 58_275_000, "REINSTATEMENT_PREMIUM amount_minor")
    assert_status(row, "status", "PENDING")
    # The PRD describes the second hop as appending "a `REINSTATEMENT_PREMIUM`
    # fiduciary movement on the program in status `PENDING` for the reinstatement
    # premium computed above" and says nothing about a `signing_line_id` on that
    # system-created row, nor which of a layer's lines it would name, so no
    # assertion is made about the attribution.
    assert row["program_id"] == ctx["program"]["id"], (
        "the reinstatement premium movement is appended on the advocacy's program"
    )


def test_the_pending_reinstatement_premium_lifts_the_cedents_outstanding_exposure():
    """The fourth link: the cedent now owes 58,275,000 of unpaid reinstatement premium.

    PRD: "`outstanding_reinstatement_premium_minor` is the sum of `amount_minor`
    over the cedent's movements whose `txn_type` is `REINSTATEMENT_PREMIUM` and
    whose status is `PENDING` or `APPROVED` — reinstatement premium owed but not
    yet paid, which drops out of the figure the moment it settles."

    Design: Difficulty/transitive_cascade/collection_cascades_erosion_to_reinstatement_premium_to_cedent_exposure
    """
    ctx = _collected_first_claim_and_second_claim_under_review()
    assert_money_equals(
        read_cedent(ctx["cedent"]["id"])["outstanding_reinstatement_premium_minor"],
        0,
        "outstanding_reinstatement_premium_minor before",
    )

    collect(ctx["second_advocacy"]["id"], ctx["signing_lines"][0]["id"], 1_000_000_000)

    cedent = read_cedent(ctx["cedent"]["id"])
    assert_money_equals(
        cedent["outstanding_reinstatement_premium_minor"],
        58_275_000,
        "outstanding_reinstatement_premium_minor",
    )


def test_the_whole_collection_cascade_moves_no_fiduciary_money():
    """Both the collection and the reinstatement premium sit PENDING, so the balance stays 0.

    PRD: "Movements in `PENDING`, `APPROVED` or `HELD` are invisible to the
    balance: booking, approving and holding a movement never move money."

    Design: Difficulty/transitive_cascade/collection_cascades_erosion_to_reinstatement_premium_to_cedent_exposure
    """
    ctx = _collected_first_claim_and_second_claim_under_review()

    collect(ctx["second_advocacy"]["id"], ctx["signing_lines"][0]["id"], 1_000_000_000)

    program = read_program(ctx["program"]["id"])
    assert_money_equals(program["fiduciary_holding_minor"], 0, "fiduciary_holding_minor")
    ledger = list_rows(
        api_client.list_program_fiduciary_transactions(
            ctx["program"]["id"], ACCOUNTANT, {"limit": 100}
        )
    )
    assert ledger, "the collection cascade writes movements onto the program's ledger"
    for row in ledger:
        assert_status(row, "status", "PENDING")
