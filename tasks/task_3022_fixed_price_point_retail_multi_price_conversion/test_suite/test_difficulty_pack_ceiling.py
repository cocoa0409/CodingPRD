"""The exclusive pack landing-cost ceiling: reported while DRAFT, fatal on the advance."""

from test_helpers import (
    ANALYST_HEADERS,
    assert_pack_program,
    E,
    validate_error,
    validate_success,
    fixtures,
)



def _four_dollar_program(api, quoted_landed_cost_cents=124):
    """A 400-cent price point at a 0.35 ratio (ceiling 123) and a DRAFT program above it."""
    fixtures.set_clock()
    price_point = fixtures.create_price_point(400, 0.35, label="FOUR_DOLLAR")
    vendor = fixtures.create_vendor()
    program = fixtures.create_pack_program(
        vendor["id"], price_point["id"], quoted_landed_cost_cents=quoted_landed_cost_cents)
    return price_point, vendor, program


def test_a_draft_program_reports_the_same_ceiling_that_later_refuses_the_advance(api):
    """The 123-cent ceiling is informational while DRAFT and fatal on the same 124-cent quote.

    PRD §3.5: "While the program is still `DRAFT` the ceiling is reported for planning only and
    does not gate anything — a draft program may quote far above the ceiling without being
    refused."
    PRD §3.5: "Once the program is advancing from `PENDING_ACTIVATION` to `ACTIVE`, the same
    ceiling becomes fatal: a `quoted_landed_cost_cents` strictly above it raises
    `ERR_PACK_COST_TARGET_MISSED` and HTTP 422 and the transition does not occur."
    PRD §3.5: "the shelf price is first multiplied by the target landed cost ratio as an exact
    rational, that product is then multiplied by one minus the buffer, and the result is floored
    at the cent, with the cent rounding performed half down."

    Design: Difficulty/dual_variant_calc/pack_ceiling_reported_then_gating_on_identical_inputs
    """
    price_point, vendor, program = _four_dollar_program(api, quoted_landed_cost_cents=124)

    draft = validate_success(api.get_pack_program(program["id"], ANALYST_HEADERS), 200)
    assert_pack_program(draft)
    # floor(400 * 0.35 * (1 - 0.12)) == floor(123.2) == 123.
    assert draft["target_landed_cost_cents"] == 123
    assert draft["status"] == "DRAFT", "a draft program quoting above the ceiling is not refused"

    refused = fixtures.advance_pack_program(program["id"], status="ACTIVE")
    validate_error(refused, E.ERR_PACK_COST_TARGET_MISSED.value)

    still_draft = validate_success(api.get_pack_program(program["id"], ANALYST_HEADERS), 200)
    assert still_draft["status"] == "DRAFT", "the refused advance left the program where it was"
    assert still_draft["quoted_landed_cost_cents"] == 124


def test_bringing_the_quote_to_the_ceiling_passes_the_gate_and_counts_on_the_vendor(api):
    """A re-quote at exactly 123 cents passes the identical gate and lands the program.

    PRD §3.5: "The comparison against the vendor's quote is inclusive on the passing side: a
    quoted cost at or below the ceiling passes, and only a quoted cost strictly above the
    ceiling fails."
    PRD §3.5: "Because the advance call may carry a fresh `quoted_landed_cost_cents`, a vendor
    can re-quote at landing time and the ceiling is recomputed against that new figure before
    the gate is applied."
    PRD §3.5: "Landing a program at `ACTIVE` has a cross-entity consequence: the owning vendor's
    `exclusivity_program_count` is incremented, and that count reports how many of the vendor's
    programs are currently `ACTIVE`."

    Design: Difficulty/dual_variant_calc/pack_ceiling_reported_then_gating_on_identical_inputs
    """
    price_point, vendor, program = _four_dollar_program(api, quoted_landed_cost_cents=124)

    landed = validate_success(
        fixtures.advance_pack_program(program["id"], status="ACTIVE",
                                      quoted_landed_cost_cents=123),
        200,
    )
    assert_pack_program(landed)
    assert landed["status"] == "ACTIVE"
    assert landed["quoted_landed_cost_cents"] == 123, "the advance recorded the fresh quote"
    assert landed["target_landed_cost_cents"] == 123, (
        "the ceiling is recomputed against the same price point and is unchanged"
    )

    vendor_after = validate_success(api.get_vendor(vendor["id"], ANALYST_HEADERS), 200)
    assert vendor_after["exclusivity_program_count"] == 1, (
        "only the successful activation counted toward the vendor's active programs"
    )