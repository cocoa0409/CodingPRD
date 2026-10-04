"""Sub-ticket pricing: per-line rounding order and the promised-time formula."""

from test_helpers import (
    api_client,
    clerk_headers,
    get_success_data,
    platform_admin_headers,
    produce_batch,
    set_clock,
    setup_deli_master_data,
    setup_price_file,
    validate_success,
)


def _setup_store_with_case_stock_and_price_file():
    """Store holding 46 lbs of cold cuts plus an ACTIVE price file, and no
    promotion active, so the ticket uplift is zero."""
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(slicer_count=4)
    produce_batch(
        master.s, master.j2["id"], master.a1["id"], "B-001", 16, produced_lbs=16,
        slicer_id=master.slicers[0]["id"],
    )
    produce_batch(
        master.s, master.j2["id"], master.a1["id"], "B-010", 30, produced_lbs=30,
        slicer_id=master.slicers[1]["id"],
    )
    return master


def _create_ticket(master, line_units, channel="DIGITAL"):
    return get_success_data(
        api_client.create_sub_ticket(
            {
                "store_id": master.s,
                "deli_item_id": master.j1["id"],
                "bread_deli_item_id": master.b1["id"],
                "order_channel": channel,
                "lines": [
                    {
                        "deli_item_id": master.j2["id"],
                        "half_lb_units": units,
                        "line_sequence_number": index + 1,
                    }
                    for index, units in enumerate(line_units)
                ],
            },
            clerk_headers(master.a1["id"]),
        )
    )


def test_line_total_rounds_each_line_before_summing():
    """PRD §3.4: "For each such line, the line's poundage is the sum of
    `half_lb_units` over every entry sharing that line number, multiplied by 0.5.
    The line's cost is that poundage multiplied by the per-pound price, rounded
    half up to zero decimal places — that is, to a whole cent."

    Two lines of 3 half-pounds each at 899 cents per pound round to 1349 cents
    apiece, so the per-line sum is 2698 — summing first and rounding afterwards
    would give 2697.

    Design: Difficulty/combinatorial_formula/line_total_per_line_rounding_order
    """
    master = _setup_store_with_case_stock_and_price_file()
    ticket = _create_ticket(master, [3, 3])
    result = validate_success(api_client.get_sub_ticket(ticket["id"], platform_admin_headers()))
    assert result["weight_lbs"] == 3.0, "the derived weight sums half-pound units at 0.5 each"
    assert result["line_total_cents"] == 2698, (
        "each 1.5 lb line rounds to 1349 cents and the rounded lines are summed"
    )


def test_line_total_diverges_from_sum_then_round_on_a_shorter_second_line():
    """PRD §3.4: "The rounding order here is pinned deliberately: each line is
    rounded to cents before the sum, and summing first and rounding afterwards
    would diverge by up to one cent per additional line."

    Design: Difficulty/combinatorial_formula/line_total_per_line_rounding_order
    """
    master = _setup_store_with_case_stock_and_price_file()
    ticket = _create_ticket(master, [3, 2])
    result = validate_success(api_client.get_sub_ticket(ticket["id"], platform_admin_headers()))
    assert result["weight_lbs"] == 2.5
    assert result["line_total_cents"] == 2248, (
        "a 1.5 lb line at 1349 plus an exact 1.0 lb line at 899"
    )
    assert 2698 - 2248 == 450, "the two tickets differ by the third half-pound line's cost"


def test_promised_time_counts_distinct_batches_plus_half_pound_units():
    """PRD §3.4: "The first is 12 minutes multiplied by the number of distinct
    production batches the ticket's lines require. The second is the ticket's
    `weight_lbs` divided by 0.5, rounded up to a whole number of half-pound
    units, multiplied by 1 minute per half-pound unit."

    Design: Difficulty/combinatorial_formula/line_total_per_line_rounding_order
    """
    master = _setup_store_with_case_stock_and_price_file()
    ticket = _create_ticket(master, [3, 2])
    assert ticket["promised_at"] is None, "promised_at is assigned at ticketing, not creation"

    ticketed = validate_success(
        api_client.ticket_sub_ticket(ticket["id"], clerk_headers(master.a1["id"]))
    )
    assert ticketed["promised_at"].startswith("2026-09-02T06:17:00"), (
        "12 minutes for the one required batch plus ceil(2.5 / 0.5) = 5 minutes of weight"
    )


def test_heavier_ticket_promises_one_minute_later():
    """PRD §3.4: "The `promised_at` instant is the logical clock at the moment of
    ticketing plus those preparation minutes."

    Design: Difficulty/combinatorial_formula/line_total_per_line_rounding_order
    """
    master = _setup_store_with_case_stock_and_price_file()
    ticket = _create_ticket(master, [3, 3])
    ticketed = validate_success(
        api_client.ticket_sub_ticket(ticket["id"], clerk_headers(master.a1["id"]))
    )
    assert ticketed["promised_at"].startswith("2026-09-02T06:18:00"), (
        "ceil(3.0 / 0.5) = 6 minutes of weight against the same one required batch"
    )