"""Pinned evaluation order in the layer technical premium and per-line brokerage rounding (PRD §3.3, §3.6).

Queue A — rule ``combinatorial_formula``: the volume discount tier is selected
from the *provisional* premium and never re-derived from the discounted result,
and the program's brokerage is rounded once per signing line and only then
summed, which lands a whole minor unit above the sum-then-round figure.
"""
from test_helpers import (
    CLOCK,
    acknowledge_disclosure,
    assert_money_equals,
    assert_pct_equals,
    assert_placement_money_invariants,
    assert_status,
    bind_program,
    create_cedent,
    create_layer,
    create_program,
    place_lines,
    read_layer,
    read_program,
    read_signing_line,
    set_clock,
    setup_program_in_market,
)

# The catastrophe layer whose four-stage pipeline straddles a tier boundary:
# base rate 8.0000 loaded by one reinstatement to 8.4000, applied to a subject
# premium base of 1,250,000,000, gives a provisional premium of 105,000,000.
CAT_LAYER_INPUTS = {
    "layer_label": "PROP CAT 1B xs 2B",
    "layer_type": "CATASTROPHE",
    "attachment_minor": 2_000_000_000,
    "limit_minor": 1_000_000_000,
    "base_rate_pct": 8.0000,
    "subject_premium_base_minor": 1_250_000_000,
    "expected_loss_cost_minor": 60_000_000,
    "reinstatements_total": 1,
    "reinstatement_premium_pct": 100.0000,
    "sublimit_minor": 0,
}
# 105,000,000 sits at or above the 100,000,000 floor, so the tier is 7.5000%
# and the frozen premium is 105,000,000 * 0.925 = 97,125,000.
CAT_PROVISIONAL_PREMIUM_MINOR = 105_000_000
CAT_GROSS_PREMIUM_MINOR = 97_125_000
# Re-deriving the tier from the discounted 97,125,000 would pick the 5.0000%
# tier and yield 105,000,000 * 0.95 = 99,750,000 instead.
CAT_WRONG_GROSS_PREMIUM_MINOR = 99_750_000

# Four markets sized so that each can write its slice of a 200,000,000 limit.
BROKERAGE_MARKET_SPECS = [
    {
        "name": "Alpha Re",
        "security_rating": "AA",
        "capacity_limit_minor": 500_000_000,
        "max_line_pct": 40.0000,
        "lead_authorised": True,
    },
    {
        "name": "Bravo Re",
        "security_rating": "A",
        "capacity_limit_minor": 400_000_000,
        "max_line_pct": 35.0000,
        "lead_authorised": False,
    },
    {
        "name": "Charlie Re",
        "security_rating": "A",
        "capacity_limit_minor": 400_000_000,
        "max_line_pct": 30.0000,
        "lead_authorised": False,
    },
    {
        "name": "Delta Re",
        "security_rating": "BBB",
        "capacity_limit_minor": 300_000_000,
        "max_line_pct": 25.0000,
        "lead_authorised": False,
    },
]

# The excess layer whose provisional premium of 10,000,000 selects the 2.5000%
# tier, so quoted_gross_premium_minor is 9,750,000.
XOL_LAYER_OVERRIDES = {
    "layer_label": "XOL 200M xs 800M",
    "attachment_minor": 800_000_000,
    "limit_minor": 200_000_000,
    "base_rate_pct": 5.0000,
    "subject_premium_base_minor": 200_000_000,
    "expected_loss_cost_minor": 8_000_000,
    "reinstatements_total": 0,
    "sublimit_minor": 0,
}
XOL_GROSS_PREMIUM_MINOR = 9_750_000
XOL_QUOTE_OVERRIDES = {
    "quoted_rate_pct": 5.0000,
    "ceding_commission_pct": 0.0000,
    "reinstatements_offered": 0,
    "sublimit_minor": 0,
}
# 35 / 30 / 20 / 15 sums to exactly 100.0000, so the layer is FULLY_PLACED and
# no sign-down is needed.
BROKERAGE_LINE_PCTS = [35.0000, 30.0000, 20.0000, 15.0000]
# Per-line brokerage at 2.5000% of each line's gross, each rounded half up:
# 85,313 + 73,125 + 48,750 + 36,563.
BROKERAGE_EARNED_PER_LINE_MINOR = 243_751
BROKERAGE_EARNED_SUM_THEN_ROUND_MINOR = 243_750
NET_REMITTANCE_MINOR = 9_506_249


def _draft_program_without_layers():
    """clock -> cedent -> DRAFT program, ready for the layer that is the trigger."""
    set_clock(CLOCK["PLACEMENT_START"])
    cedent = create_cedent()
    program = create_program(
        cedent["id"], program_name="Northwind Property CAT 2026"
    )
    return {"cedent": cedent, "program": program}


def _four_line_xol_program_awaiting_bind():
    """One XOL layer taken 35/30/20/15 by four markets, with brokerage acknowledged."""
    ctx = setup_program_in_market(
        layer_kind="XOL",
        layer_overrides=XOL_LAYER_OVERRIDES,
        market_specs=BROKERAGE_MARKET_SPECS,
        program_overrides={"program_name": "Northwind Property XOL 2026"},
        submission_overrides={"package_label": "NW-XOL-2026-EDP"},
    )
    place_lines(
        ctx,
        [
            {
                "market_index": market_index,
                "accepted_line_pct": line_pct,
                "offered_line_pct": line_pct,
                "quote_overrides": dict(XOL_QUOTE_OVERRIDES),
                "is_lead": market_index == 0,
            }
            for market_index, line_pct in enumerate(BROKERAGE_LINE_PCTS)
        ],
    )
    ctx["disclosure"] = acknowledge_disclosure(
        ctx["program"]["id"], ctx["cedent"]["id"], 2.5000
    )
    return ctx


def test_layer_premium_selects_the_volume_tier_from_the_provisional_premium():
    """A provisional 105,000,000 earns the 7.5000% tier, so the layer prices at 97,125,000.

    PRD: "Third, a volume discount tier is selected **from the provisional
    premium**, that is, from the premium before any discount is applied."

    Design: Difficulty/combinatorial_formula/cat_layer_premium_pins_volume_tier_to_provisional_not_discounted_premium
    """
    ctx = _draft_program_without_layers()

    layer = create_layer(ctx["program"]["id"], **CAT_LAYER_INPUTS)

    assert_money_equals(
        layer["quoted_gross_premium_minor"],
        CAT_GROSS_PREMIUM_MINOR,
        "quoted_gross_premium_minor on the creation response",
    )
    assert_status(layer, "status", "OPEN")

    stored = read_layer(layer["id"])
    assert_money_equals(
        stored["quoted_gross_premium_minor"],
        CAT_GROSS_PREMIUM_MINOR,
        "quoted_gross_premium_minor read back",
    )
    assert_pct_equals(stored["base_rate_pct"], 8.0000, "base_rate_pct")
    assert stored["reinstatements_total"] == 1, (
        "the single purchased reinstatement is what loads the rate to 8.4000"
    )


def test_layer_premium_never_re_derives_the_tier_from_the_discounted_premium():
    """The 5.0000% tier that the discounted 97,125,000 would select is never applied.

    PRD: "The tier is never re-derived from the discounted result: doing so would
    let a large layer fall back into a cheaper tier and produce a different,
    wrong premium."

    Design: Difficulty/combinatorial_formula/cat_layer_premium_pins_volume_tier_to_provisional_not_discounted_premium
    """
    ctx = _draft_program_without_layers()

    layer = create_layer(ctx["program"]["id"], **CAT_LAYER_INPUTS)

    gross = int(round(float(layer["quoted_gross_premium_minor"])))
    assert gross != CAT_WRONG_GROSS_PREMIUM_MINOR, (
        "99,750,000 is the premium obtained by re-deriving the tier from the "
        "discounted figure and taking the 5.0000% tier; it must never be produced"
    )
    assert_money_equals(gross, CAT_GROSS_PREMIUM_MINOR, "quoted_gross_premium_minor")
    # The 7.5000% tier applied to the provisional 105,000,000 is the only
    # arithmetic that reaches this figure.
    assert_money_equals(
        gross,
        round(CAT_PROVISIONAL_PREMIUM_MINOR * 925 / 1000),
        "the provisional premium discounted at the 7.5000% tier",
    )
    assert_money_equals(
        read_layer(layer["id"])["quoted_gross_premium_minor"],
        CAT_GROSS_PREMIUM_MINOR,
        "quoted_gross_premium_minor read back",
    )


def test_bind_rounds_brokerage_per_signing_line_then_sums_leaving_one_minor_unit():
    """Four lines rounded individually earn 243,751, one unit above the 243,750 aggregate.

    PRD: "Its `brokerage_earned_minor` is the sum of the per-line brokerage
    amounts — it is **not** the program's gross written premium multiplied by
    `brokerage_pct` and rounded once, and the two differ by a minor unit or two
    in ordinary cases, because rounding four lines individually is not the same
    as rounding their total."

    Design: Difficulty/combinatorial_formula/bind_brokerage_rounds_per_signing_line_then_sums_leaving_one_minor_unit
    """
    ctx = _four_line_xol_program_awaiting_bind()

    program = bind_program(ctx["program"]["id"])

    assert_status(program, "placement_status", "BOUND")
    assert_money_equals(
        program["brokerage_earned_minor"],
        BROKERAGE_EARNED_PER_LINE_MINOR,
        "brokerage_earned_minor",
    )
    assert int(round(float(program["brokerage_earned_minor"]))) != (
        BROKERAGE_EARNED_SUM_THEN_ROUND_MINOR
    ), (
        "243,750 is the sum-then-round figure obtained by taking 2.5000% of the "
        "9,750,000 gross once; the per-line discipline must produce 243,751"
    )
    assert_money_equals(
        read_program(ctx["program"]["id"])["brokerage_earned_minor"],
        BROKERAGE_EARNED_PER_LINE_MINOR,
        "brokerage_earned_minor read back",
    )


def test_bind_nets_the_remittance_from_the_per_line_brokerage_with_no_residue():
    """The per-line nets sum to 9,506,249 and rounding_residue_minor still closes at 0.

    PRD: "Its `rounding_residue_minor` is the gross written premium less the sum
    of `brokerage_earned_minor` and `net_remittance_minor`, and it exists
    precisely so that the penny the per-line rounding creates or destroys is
    visible rather than hidden."

    Design: Difficulty/combinatorial_formula/bind_brokerage_rounds_per_signing_line_then_sums_leaving_one_minor_unit
    """
    ctx = _four_line_xol_program_awaiting_bind()

    bind_program(ctx["program"]["id"])

    program = read_program(ctx["program"]["id"])
    assert_money_equals(
        program["net_remittance_minor"], NET_REMITTANCE_MINOR, "net_remittance_minor"
    )
    assert_money_equals(program["rounding_residue_minor"], 0, "rounding_residue_minor")
    assert_money_equals(
        program["brokerage_earned_minor"],
        BROKERAGE_EARNED_PER_LINE_MINOR,
        "brokerage_earned_minor",
    )
    assert_placement_money_invariants(program)


def test_bind_freezes_the_gross_written_premium_and_binds_every_written_line():
    """The single 9,750,000 layer becomes the program's gross and all four lines bind.

    PRD: "The program's `gross_written_premium_minor` is the sum of
    `quoted_gross_premium_minor` over the program's `BOUND` layers."

    Design: Difficulty/combinatorial_formula/bind_brokerage_rounds_per_signing_line_then_sums_leaving_one_minor_unit
    """
    ctx = _four_line_xol_program_awaiting_bind()

    program = bind_program(ctx["program"]["id"])

    assert_money_equals(
        program["gross_written_premium_minor"],
        XOL_GROSS_PREMIUM_MINOR,
        "gross_written_premium_minor",
    )
    layer = read_layer(ctx["layer"]["id"])
    assert_status(layer, "status", "BOUND")
    assert_money_equals(
        layer["quoted_gross_premium_minor"],
        XOL_GROSS_PREMIUM_MINOR,
        "quoted_gross_premium_minor",
    )


def test_bind_sets_each_provisional_line_signed_line_to_its_written_line():
    """The 35.0000 lead line signs and takes effect at 35.0000 and the 15.0000 tail line binds.

    PRD: "On those layers, each `PROVISIONAL` line — a line on a layer that was
    never signed down, therefore written at exactly the line it was firm-ordered
    at — has its `signed_line_pct` set equal to its `written_line_pct` and then
    becomes `BOUND`; each already-`SIGNED` line simply becomes `BOUND`."

    Design: Difficulty/combinatorial_formula/bind_brokerage_rounds_per_signing_line_then_sums_leaving_one_minor_unit
    """
    ctx = _four_line_xol_program_awaiting_bind()

    bind_program(ctx["program"]["id"])

    lead_line = read_signing_line(ctx["signing_lines"][0]["id"])
    assert_pct_equals(lead_line["signed_line_pct"], 35.0000, "lead signed_line_pct")
    assert_pct_equals(lead_line["effective_line_pct"], 35.0000, "lead effective_line_pct")
    assert_pct_equals(lead_line["written_line_pct"], 35.0000, "lead written_line_pct")
    assert_status(lead_line, "status", "BOUND")

    tail_line = read_signing_line(ctx["signing_lines"][3]["id"])
    assert_pct_equals(tail_line["signed_line_pct"], 15.0000, "tail signed_line_pct")
    assert_status(tail_line, "status", "BOUND")
