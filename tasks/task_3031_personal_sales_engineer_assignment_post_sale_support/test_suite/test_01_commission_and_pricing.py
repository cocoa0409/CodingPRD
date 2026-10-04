"""Depth: dual-variant commission, capped share, and the pinned package-price order."""
from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    SALES_OPS,
    SETUP_TECH,
    accept_assignment,
    add_quote_line,
    create_assignment,
    create_customer,
    create_instrument_unit,
    create_product,
    create_quote,
    quote_summary,
    setup_book_world,
    setup_catalog,
    setup_instrument_unit,
    setup_reserved_quote,
    start_setup,
    walk_unit_to_inspected,
)


def _reserved_world_with_inspected_unit(clock="2026-09-01T00:00:00.000Z"):
    """TIER_1 engineer, ACTIVE assignment, RESERVED SYSTEM_PACKAGE quote
    (guitar anchor + dependent amp), and one guitar unit inspected PASS."""
    world = setup_book_world(clock=clock)
    setup_reserved_quote(world)
    unit = setup_instrument_unit(world)
    walk_unit_to_inspected(unit)
    world["unit"] = unit
    return world


def _ship_line(world, line, serial, model):
    """Register, inspect and ship one unit against a quote line (PRD 3.4)."""
    unit = create_instrument_unit(line, serial, model)
    walk_unit_to_inspected(unit)
    return validate_success(api_client.ship_instrument_unit(unit["id"], SETUP_TECH))


def test_commission_provisional_then_final_variant_on_shipped_quote():
    """PRD 3.3: "The pool is 800 basis points of the quote's `gross_subtotal_cents`,
    rounded half-up to 2 decimal places." PRD 3.3: "In the provisional variant,
    applied when the quote is submitted, the engineer's credit is the pool
    multiplied by that share in basis points and divided by 10000, rounded
    half-up to 2 decimal places." PRD 3.3: "In the final variant, applied once
    every line on the quote has a shipped instrument, the pool is prorated by
    the fraction of line value that actually shipped: the shipped line totals
    are summed, multiplied through the same pool and share, divided by
    `gross_subtotal_cents`, and rounded half-up to 2 decimal places."

    Design: Difficulty/dual_variant_calc/commission_provisional_vs_final_on_quote
    """
    world = _reserved_world_with_inspected_unit()
    engineer, quote_id = world["engineer"], world["quote_id"]

    quote = validate_success(api_client.get_quote(quote_id, SALES_OPS))
    assert quote["gross_subtotal_cents"] == 69993, (
        "guitar 39996 + amp 29997 must fold into the quote subtotal"
    )

    before = quote_summary(quote_id)
    assert before["engineer_commission_cents"] == 2800
    assert before["commission_variant"] == "provisional"

    # The final variant is applied only once EVERY line has a shipped
    # instrument (PRD 3.3), so both lines must ship for the variant to flip.
    validate_success(api_client.ship_instrument_unit(world["unit"]["id"], SETUP_TECH))
    _ship_line(world, world["amp_line"], "SN-AMP-7002", "SW-AMP-050")

    after = quote_summary(quote_id)
    assert after["engineer_commission_cents"] == 2800
    assert after["commission_variant"] == "final"

    refreshed = validate_success(api_client.get_engineer(engineer["id"], SALES_OPS))
    assert refreshed["lifetime_commission_cents"] == 2800


def test_commission_provisional_and_final_agree_once_everything_ships():
    """PRD 3.3: "Because the provisional variant pays the full share before
    anything ships, it always exceeds the final variant whenever any line
    remains unshipped; when everything ships, the two agree."

    Design: Difficulty/dual_variant_calc/commission_provisional_vs_final_on_quote
    """
    world = _reserved_world_with_inspected_unit()
    quote_id = world["quote_id"]

    provisional = quote_summary(quote_id)["engineer_commission_cents"]
    assert provisional == 2800

    validate_success(api_client.ship_instrument_unit(world["unit"]["id"], SETUP_TECH))
    _ship_line(world, world["amp_line"], "SN-AMP-7003", "SW-AMP-050")

    final = quote_summary(quote_id)["engineer_commission_cents"]
    assert final == 2800
    assert provisional == final, (
        "with every line shipped the prorated final credit and the full-share "
        "provisional credit agree"
    )


def test_lifetime_commission_rolls_up_only_the_finalized_amount():
    """PRD 3.3: "The finalized amount rolls into the engineer's
    `lifetime_commission_cents`, which sums finalized engineer commission
    across the quotes that engineer authored, limited to quotes that are
    `RESERVED` and fully shipped."

    Design: Difficulty/dual_variant_calc/commission_provisional_vs_final_on_quote
    """
    world = _reserved_world_with_inspected_unit()
    engineer, quote_id = world["engineer"], world["quote_id"]

    assert quote_summary(quote_id)["commission_variant"] == "provisional"
    assert validate_success(
        api_client.get_engineer(engineer["id"], SALES_OPS)
    )["lifetime_commission_cents"] == 0

    validate_success(api_client.ship_instrument_unit(world["unit"]["id"], SETUP_TECH))
    _ship_line(world, world["amp_line"], "SN-AMP-7004", "SW-AMP-050")

    assert validate_success(
        api_client.get_engineer(engineer["id"], SALES_OPS)
    )["lifetime_commission_cents"] == 2800


def test_package_price_rounds_each_unit_before_multiplying_quantity():
    """PRD 3.3: "First, the per-unit price for a line is the catalogue
    `unit_price_cents` reduced by the system line discount of 6667 basis points
    and rounded half-up to 2 decimal places". PRD 2.7: "Quote line pricing
    rounds once per unit before the units are multiplied, so a line's total is
    the quantity times an already-rounded per-unit price rather than a rounding
    of quantity times an unrounded price."

    Design: Difficulty/combinatorial_formula/package_bundle_price_nested_rounding_order
    """
    world = setup_book_world(clock="2026-09-12T00:00:00.000Z")
    create_product(product_code="SW-MIC-111", display_name="Field Mic 111",
                   product_family="MICROPHONE", unit_price_cents=1111)
    quote = create_quote(world["customer"], world["engineer"], "SYSTEM_PACKAGE")
    line = add_quote_line(quote, world["engineer"], product_code="SW-MIC-111",
                          quantity=3, is_anchor=True)

    assert line["unit_price_cents"] == 1111
    assert line["bundle_discount_bps"] == 6667
    assert line["line_total_cents"] == 1110, (
        "round_half_up(1111 * 3333 / 10000) == round_half_up(370.2963) == 370, "
        "then 3 * 370"
    )
    assert line["line_total_cents"] != 1111, (
        "the rejected sum-then-round order would have given "
        "round_half_up(3 * 1111 * 3333 / 10000) == round_half_up(1110.8889) == 1111"
    )


def test_submitted_quote_summary_matches_pinned_bundle_price_at_tier_zero():
    """PRD 3.3: "Third, a tier rate is chosen from that already-discounted
    subtotal: a tier of 1000 basis points applies when the subtotal is at least
    500000 cents, a tier of 500 basis points applies when the subtotal is at
    least 200000 cents but below that higher threshold, and no tier applies
    below 200000 cents."

    Design: Difficulty/combinatorial_formula/package_bundle_price_nested_rounding_order
    """
    world = setup_book_world(clock="2026-09-12T00:00:00.000Z")
    create_product(product_code="SW-MIC-111", display_name="Field Mic 111",
                   product_family="MICROPHONE", unit_price_cents=1111)
    quote = create_quote(world["customer"], world["engineer"], "SYSTEM_PACKAGE")
    add_quote_line(quote, world["engineer"], product_code="SW-MIC-111", quantity=3,
                   is_anchor=True)

    headers = {"X-User-ID": world["engineer"]["id"], "X-User-Role": "Engineer",
               "Content-Type": "application/json"}
    submitted = validate_success(api_client.submit_quote(quote["id"], headers))
    assert submitted["status"] == "SUBMITTED"
    assert submitted["bundle_ready"] is True

    summary = quote_summary(quote["id"])
    assert summary["gross_subtotal_cents"] == 1110
    assert summary["package_bundle_price_cents"] == 1110, (
        "1110 is below the 200000-cent tier floor, so no tier rate applies"
    )


def test_commission_share_uses_capped_value_not_the_requested_share():
    """PRD 3.3: "The engineer's share is the assignment's `commission_share_bps`,
    capped at the engineer's `commission_cap_bps` — the lower of the two wins."
    PRD 3.9: "the total engineer share is always the smaller of the assignment's
    requested share and the cap, so an engineer negotiating at the tier ceiling
    is paid the ceiling rather than the request."

    Design: Difficulty/dual_variant_calc/commission_provisional_vs_final_on_quote
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z")
    quote = create_quote(world["customer"], world["engineer"], "SYSTEM_PACKAGE")
    add_quote_line(quote, world["engineer"], product_code="SW-GTR-100", quantity=1,
                   is_anchor=True)
    headers = {"X-User-ID": world["engineer"]["id"], "X-User-Role": "Engineer",
               "Content-Type": "application/json"}
    validate_success(api_client.submit_quote(quote["id"], headers))

    assignment = validate_success(
        api_client.get_assignment(world["assignment_id"], SALES_OPS)
    )
    engineer = validate_success(api_client.get_engineer(world["engineer_id"], SALES_OPS))
    assert assignment["commission_share_bps"] == 5000
    assert engineer["commission_cap_bps"] == 5000

    summary = quote_summary(quote["id"])
    assert summary["gross_subtotal_cents"] == 39996
    assert summary["engineer_commission_cents"] == 1600


def test_assignment_at_the_commission_cap_is_admitted_and_one_above_is_rejected():
    """PRD 2.4: "It is bounded above by the engineer's current
    `commission_cap_bps`: a share equal to the cap is admitted, and a share one
    basis point above the cap is rejected with `ERR_COMMISSION_CAP_EXCEEDED` at
    HTTP 422."

    Design: Difficulty/dual_variant_calc/commission_provisional_vs_final_on_quote
    """
    world = setup_book_world(clock="2026-09-01T00:00:00.000Z", with_catalog=False,
                             accept=False)
    at_cap = create_assignment(world["customer"], world["engineer"],
                               commission_share_bps=5000)
    assert at_cap["commission_share_bps"] == 5000
    accepted = accept_assignment(at_cap)
    assert accepted["status"] == "ACTIVE"

    other = create_customer("Sasha Poe", "sasha.poe@example.com", "TN")
    resp = api_client.create_assignment(
        {"customer_id": other["id"], "engineer_id": world["engineer_id"],
         "reason_code": "NEW_ACCOUNT", "commission_share_bps": 5001,
         "expected_customer_version": other["version"]},
        SALES_OPS,
    )
    validate_error(resp, ApiErrorId.ERR_COMMISSION_CAP_EXCEEDED)

    assignment = validate_success(
        api_client.get_assignment(at_cap["id"], SALES_OPS)
    )
    assert assignment["commission_share_bps"] == 5000
    assert engineer_commission_cap(world["engineer_id"]) == 5000


def engineer_commission_cap(engineer_id):
    return validate_success(
        api_client.get_engineer(engineer_id, SALES_OPS)
    )["commission_cap_bps"]