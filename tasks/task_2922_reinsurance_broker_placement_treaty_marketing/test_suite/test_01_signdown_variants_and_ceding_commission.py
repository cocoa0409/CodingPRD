"""Sign-down allocation variants and the two-variant ceding commission (PRD §3.6, §3.9).

Queue A — rule ``dual_variant_calc``: the same written lines allocate differently
under ``PRO_RATA`` and ``LEAD_PROTECTED``, and the same quota-share layer is
commissioned once flat at bind and once on the slide at settlement.
"""
from test_helpers import (
    CLOCK,
    assert_money_equals,
    assert_pct_equals,
    assert_status,
    collect,
    create_cedent,
    create_exposure_submission,
    create_layer,
    create_program,
    create_reinsurer,
    agree_wording,
    approve_transaction,
    firm_order,
    go_to_market,
    notify_claim,
    quote_on,
    read_layer,
    read_program,
    read_signing_line,
    review_claim,
    set_clock,
    settle_program,
    settle_transaction,
    setup_bound_program,
    setup_oversubscribed_layer,
    sign_down,
    sign_off_exposure,
    submit_to_market,
)

# Two markets sized so that each can write its line on BOTH twin layers inside
# one aggregation window: Alpha writes 60% of a 1,000,000,000 limit twice and
# Bravo 50% twice, against a 2,000,000,000 capacity each.
TWIN_MARKET_SPECS = [
    {
        "name": "Alpha Re",
        "max_line_pct": 60.0000,
        "lead_authorised": True,
        "capacity_limit_minor": 2_000_000_000,
    },
    {
        "name": "Bravo Re",
        "max_line_pct": 50.0000,
        "lead_authorised": False,
        "capacity_limit_minor": 2_000_000_000,
    },
]

# The quota-share commission chain: gross premium 740,000,000 at a provisional
# 30.0000% commission, one market taking the whole line.
QS_MARKET_SPECS = [
    {
        "name": "Echo Re",
        "max_line_pct": 100.0000,
        "lead_authorised": True,
        "capacity_limit_minor": 800_000_000,
    }
]
QS_LAYER_OVERRIDES = {"layer_label": "QS 40 pct", "limit_minor": 800_000_000}
QS_QUOTE_OVERRIDES = {
    "quoted_rate_pct": 40.0000,
    "ceding_commission_pct": 30.0000,
    "reinstatements_offered": 0,
}


def _oversubscribed_at_60_and_50(signdown_method: str):
    """Alpha writes 60.0000 as lead and Bravo 50.0000 as follower on one CAT layer."""
    return setup_oversubscribed_layer(
        first_line_pct=60.0000,
        second_line_pct=50.0000,
        market_specs=TWIN_MARKET_SPECS,
        program_overrides={"signdown_method": signdown_method},
    )


def _twin_oversubscribed_programs():
    """One cedent, two markets, twin programs differing only in signdown_method."""
    set_clock(CLOCK["PLACEMENT_START"])
    cedent = create_cedent()
    markets = [create_reinsurer(**spec) for spec in TWIN_MARKET_SPECS]
    twins = {}
    for key, method, line_of_business, tag in (
        ("pro_rata", "PRO_RATA", "PROPERTY", "PROP"),
        ("lead_protected", "LEAD_PROTECTED", "MARINE", "MAR"),
    ):
        program = create_program(
            cedent["id"],
            program_name=f"Northwind {tag} 2026",
            line_of_business=line_of_business,
            signdown_method=method,
        )
        submission = create_exposure_submission(
            program["id"], cedent["id"], package_label=f"NW-{tag}-2026-EDP"
        )
        layer = create_layer(program["id"], layer_label=f"{tag} CAT 1B xs 2B")
        sign_off_exposure(submission["id"])
        go_to_market(program["id"])
        # Both markets are addressed and both quotes taken before either line is
        # firm-ordered: PRD §3.4 admits a market submission only while "the layer
        # must be either `OPEN` or `IN_MARKET`", and the lead's firm order carries
        # the layer to PARTIALLY_PLACED.
        terms = ((markets[0], 60.0000, True), (markets[1], 50.0000, False))
        quotes = []
        for market, _line_pct, is_lead in terms:
            market_submission = submit_to_market(layer["id"], market["id"])
            quotes.append(
                quote_on(
                    market_submission["id"],
                    market["id"],
                    offered_line_pct=100.0000,
                    is_lead=is_lead,
                )
            )
        lines = [
            firm_order(quote["id"], line_pct, layer_id=layer["id"])
            for quote, (_market, line_pct, _is_lead) in zip(quotes, terms)
        ]
        twins[key] = {"layer": layer, "lead_line": lines[0], "follower_line": lines[1]}
    twins["cedent"] = cedent
    twins["markets"] = markets
    return twins


def test_pro_rata_signdown_scales_the_lead_line_alongside_every_follower():
    """A 60/50 oversubscription resolves to 54.5455/45.4545 under PRO_RATA.

    PRD: "Under `PRO_RATA`, the default, every line is scaled by the same factor
    of one hundred over the written total; the lead's status buys it nothing at
    all."

    Design: Difficulty/dual_variant_calc/signdown_pro_rata_versus_lead_protected_on_signing_line_percentages
    """
    ctx = _oversubscribed_at_60_and_50("PRO_RATA")
    lead_line, follower_line = ctx["signing_lines"][0], ctx["signing_lines"][1]

    layer = sign_down(ctx["layer"]["id"])

    assert_pct_equals(layer["signed_line_total_pct"], 100.0000, "signed_line_total_pct")
    assert_status(layer, "status", "SIGNED_DOWN")

    lead = read_signing_line(lead_line["id"])
    follower = read_signing_line(follower_line["id"])
    assert_pct_equals(lead["signed_line_pct"], 54.5455, "lead signed_line_pct")
    assert_pct_equals(lead["effective_line_pct"], 54.5455, "lead effective_line_pct")
    assert_pct_equals(follower["signed_line_pct"], 45.4545, "follower signed_line_pct")
    assert_money_equals(
        lead["committed_capacity_minor"], 545_455_000, "lead committed_capacity_minor"
    )
    assert_money_equals(
        follower["committed_capacity_minor"], 454_545_000, "follower committed_capacity_minor"
    )
    assert_status(lead, "status", "SIGNED")
    assert_status(follower, "status", "SIGNED")


def test_lead_protected_signdown_holds_the_lead_line_whole_and_scales_the_followers():
    """The same 60/50 oversubscription resolves to 60.0000/40.0000 under LEAD_PROTECTED.

    PRD: "Under `LEAD_PROTECTED`, the line whose quote carried `is_lead` true
    keeps its `written_line_pct` completely untouched, and the followers share
    only what is left over — each follower's raw share is its
    `written_line_pct` multiplied by the difference between `100.0000` and the
    lead's written line, divided by the sum of the followers' written lines —
    with the floor-and-residue pass running over the followers alone and the
    residue closing against that reduced target rather than against `100.0000`."

    Design: Difficulty/dual_variant_calc/signdown_pro_rata_versus_lead_protected_on_signing_line_percentages
    """
    ctx = _oversubscribed_at_60_and_50("LEAD_PROTECTED")
    lead_line, follower_line = ctx["signing_lines"][0], ctx["signing_lines"][1]

    layer = sign_down(ctx["layer"]["id"])

    assert_pct_equals(layer["signed_line_total_pct"], 100.0000, "signed_line_total_pct")
    assert_status(layer, "status", "SIGNED_DOWN")

    lead = read_signing_line(lead_line["id"])
    follower = read_signing_line(follower_line["id"])
    assert_pct_equals(lead["signed_line_pct"], 60.0000, "lead signed_line_pct")
    assert_pct_equals(follower["signed_line_pct"], 40.0000, "follower signed_line_pct")
    assert_money_equals(
        lead["committed_capacity_minor"], 600_000_000, "lead committed_capacity_minor"
    )
    assert_money_equals(
        follower["committed_capacity_minor"], 400_000_000, "follower committed_capacity_minor"
    )
    assert_status(lead, "status", "SIGNED")
    assert_status(follower, "status", "SIGNED")


def test_signdown_method_moves_the_follower_line_between_twin_placements():
    """Twin layers written 60/50 disagree on the follower by 5.4545 points.

    PRD: "Which lines are scaled depends on the program's `signdown_method`, and
    the two variants disagree on every follower line."

    Design: Difficulty/dual_variant_calc/signdown_pro_rata_versus_lead_protected_on_signing_line_percentages
    """
    twins = _twin_oversubscribed_programs()

    pro_rata_layer = sign_down(twins["pro_rata"]["layer"]["id"])
    lead_protected_layer = sign_down(twins["lead_protected"]["layer"]["id"])

    assert_pct_equals(
        pro_rata_layer["signed_line_total_pct"], 100.0000, "PRO_RATA signed_line_total_pct"
    )
    assert_pct_equals(
        lead_protected_layer["signed_line_total_pct"],
        100.0000,
        "LEAD_PROTECTED signed_line_total_pct",
    )

    pro_rata_follower = read_signing_line(twins["pro_rata"]["follower_line"]["id"])
    lead_protected_follower = read_signing_line(
        twins["lead_protected"]["follower_line"]["id"]
    )
    assert_pct_equals(
        pro_rata_follower["signed_line_pct"], 45.4545, "PRO_RATA follower signed_line_pct"
    )
    assert_pct_equals(
        lead_protected_follower["signed_line_pct"],
        40.0000,
        "LEAD_PROTECTED follower signed_line_pct",
    )
    divergence = float(pro_rata_follower["signed_line_pct"]) - float(
        lead_protected_follower["signed_line_pct"]
    )
    assert_pct_equals(divergence, 5.4545, "follower divergence between the two variants")

    pro_rata_lead = read_signing_line(twins["pro_rata"]["lead_line"]["id"])
    lead_protected_lead = read_signing_line(twins["lead_protected"]["lead_line"]["id"])
    assert_pct_equals(pro_rata_lead["signed_line_pct"], 54.5455, "PRO_RATA lead")
    assert_pct_equals(lead_protected_lead["signed_line_pct"], 60.0000, "LEAD_PROTECTED lead")


def test_bind_fixes_the_flat_provisional_ceding_commission_on_the_quota_share_layer():
    """Bind books 740,000,000 at 30.0000% as 222,000,000 with no slide applied.

    PRD: "The provisional figure is the flat variant of the commission
    settlement: the layer's `quoted_gross_premium_minor` multiplied by its
    `ceding_commission_pct` and divided by one hundred, rounded half up to whole
    minor units, stored as `provisional_ceding_commission_minor`."

    Design: Difficulty/dual_variant_calc/ceding_commission_provisional_flat_versus_final_sliding_on_layer_money
    """
    ctx = setup_bound_program(
        layer_kind="QS",
        layer_overrides=QS_LAYER_OVERRIDES,
        market_specs=QS_MARKET_SPECS,
        quote_overrides=QS_QUOTE_OVERRIDES,
    )

    layer = read_layer(ctx["layer"]["id"])
    assert_money_equals(
        layer["quoted_gross_premium_minor"], 740_000_000, "quoted_gross_premium_minor"
    )
    assert_money_equals(
        layer["provisional_ceding_commission_minor"],
        222_000_000,
        "provisional_ceding_commission_minor",
    )
    assert layer["final_ceding_commission_minor"] is None, (
        "the slide is ignored at binding, so final_ceding_commission_minor stays null"
    )
    assert layer["ceding_commission_delta_minor"] is None, (
        "ceding_commission_delta_minor stays null until settlement reconciles"
    )
    assert layer["loss_ratio_pct"] is None, "no loss experience exists at binding"


def test_settlement_slides_the_final_ceding_commission_against_the_realised_loss_ratio():
    """A realised 80.0000% loss ratio clamps the slide to 20.0000%, so the delta is -74,000,000.

    PRD: "The layer's `final_ceding_commission_minor` is its
    `quoted_gross_premium_minor` multiplied by that final percentage, divided by
    one hundred and rounded half up to whole minor units, and its
    `ceding_commission_delta_minor` is that final amount less the
    `provisional_ceding_commission_minor` fixed at binding — positive where the
    year ran better than expected and negative where it ran worse."

    Design: Difficulty/dual_variant_calc/ceding_commission_provisional_flat_versus_final_sliding_on_layer_money
    """
    ctx = setup_bound_program(
        layer_kind="QS",
        layer_overrides=QS_LAYER_OVERRIDES,
        market_specs=QS_MARKET_SPECS,
        quote_overrides=QS_QUOTE_OVERRIDES,
    )
    agree_wording(ctx["program"]["id"])

    advocacy = notify_claim(
        ctx["layer"]["id"],
        ctx["cedent"]["id"],
        claim_reference="CL-2026-QS-001",
        event_date="2026-06-01T00:00:00.000Z",
        gross_claim_minor=1_480_000_000,
    )
    assert_money_equals(advocacy["ceded_claim_minor"], 592_000_000, "ceded_claim_minor")
    review_claim(advocacy["id"])
    collection = collect(advocacy["id"], ctx["signing_lines"][0]["id"], 592_000_000)
    approve_transaction(collection["id"])
    settle_transaction(collection["id"])

    program = settle_program(ctx["program"]["id"])
    assert_status(program, "placement_status", "SETTLED")

    layer = read_layer(ctx["layer"]["id"])
    assert_money_equals(layer["incurred_ceded_minor"], 592_000_000, "incurred_ceded_minor")
    assert_pct_equals(layer["loss_ratio_pct"], 80.0000, "loss_ratio_pct")
    assert_money_equals(
        layer["provisional_ceding_commission_minor"],
        222_000_000,
        "provisional_ceding_commission_minor",
    )
    assert_money_equals(
        layer["final_ceding_commission_minor"],
        148_000_000,
        "final_ceding_commission_minor",
    )
    assert_money_equals(
        layer["ceding_commission_delta_minor"], -74_000_000, "ceding_commission_delta_minor"
    )
    assert_money_equals(
        layer["quoted_gross_premium_minor"], 740_000_000, "quoted_gross_premium_minor"
    )
    assert_status(read_program(ctx["program"]["id"]), "placement_status", "SETTLED")
