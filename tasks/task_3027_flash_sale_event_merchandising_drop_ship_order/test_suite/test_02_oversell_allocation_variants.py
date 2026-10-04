"""Oversell attribution: the persisted ordering and the provisional preview ordering."""

from test_helpers import (
    ANY, TEST_USERS, api_client, create_buy, fresh_vendor, get_success_data,
    setup_live_event_with_listing, validate_success,
)

MERCH = TEST_USERS["merchandiser_headers"]
PLANNER = TEST_USERS["inventory_planner_headers"]


def _two_lines_then_buy(allocation_units=5, quantity_each=3):
    """Two customers each hold one submitted line on the same listing, in order.

    The excess stays inside the listing's oversell bound so the later confirmation is
    admissible.

    Returns (vendor, event, listing, customer_early, customer_late,
             line_early, line_late, po).
    """
    vendor, shop, event, listing = setup_live_event_with_listing(
        unit_price_cents=100, vendor_unit_cost_cents=60,
        allocation_units=allocation_units, ship_time_quote_days=14)

    customer_early = get_success_data(api_client.create_customer(
        {"email": "early@example.com", "full_name": "Early Buyer"}, ANY))
    customer_late = get_success_data(api_client.create_customer(
        {"email": "late@example.com", "full_name": "Late Buyer"}, ANY))
    early_h = TEST_USERS["customer_headers"].copy()
    early_h["X-User-ID"] = customer_early["id"]
    late_h = TEST_USERS["customer_headers"].copy()
    late_h["X-User-ID"] = customer_late["id"]

    order_early = get_success_data(api_client.create_order(
        {"customer_id": customer_early["id"]}, early_h))
    order_late = get_success_data(api_client.create_order(
        {"customer_id": customer_late["id"]}, late_h))
    line_early = get_success_data(api_client.add_order_line(
        order_early["id"], {"listing_id": listing["id"], "quantity": quantity_each},
        early_h))
    line_late = get_success_data(api_client.add_order_line(
        order_late["id"], {"listing_id": listing["id"], "quantity": quantity_each},
        late_h))

    api_client.set_clock("2026-09-01T10:00:00Z", MERCH)
    get_success_data(api_client.submit_order(order_early["id"], early_h))
    api_client.set_clock("2026-09-01T11:00:00Z", MERCH)
    get_success_data(api_client.submit_order(order_late["id"], late_h))

    po = create_buy(vendor, event)
    get_success_data(api_client.add_po_line(
        po["id"], {"listing_id": listing["id"],
                   "quantity_ordered": quantity_each * 2}, PLANNER))
    get_success_data(api_client.issue_purchase_order(
        po["id"], {"expected_vendor_version": fresh_vendor(vendor["id"])["version"]}, PLANNER))
    return (vendor, event, listing, customer_early, customer_late,
            line_early, line_late, po)


def test_provisional_preview_makes_the_newest_line_absorb_the_excess(
        api, merchandiser_headers):
    """PRD §3.4: "A separate, explicitly provisional preview orders candidates the
    other way round — by `confirmed_at` descending, then `line_unit_price_cents`
    ascending, then `created_at` descending — which makes the newest line absorb the
    oversell first and gives 2 on A and 0 on B for the same pair."

    Design: Difficulty/dual_variant_calc/oversell_split_variant_divergence_on_two_lines
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    (vendor, event, listing, cust_early, cust_late,
     line_early, line_late, po) = _two_lines_then_buy()

    listing_now = validate_success(api.get_listing(listing["id"], ANY), 200)
    assert listing_now["units_ordered"] == 6
    assert listing_now["allocation_units"] == 5

    preview = validate_success(
        api.get_oversell_preview(listing["id"], merchandiser_headers), 200)
    assert preview["provisional_variant"] == "cancel_newest_first"
    assert preview["excess_units"] == 1

    by_line = {s["confirmation_id"]: s["oversold_units"]
               for s in preview["provisional_splits"]}
    # PRD §3.4 pins this variant by its worked pair: the preview ordering gives
    # "2 on A and 0 on B" — the excess lands on line A, the earlier-confirmed
    # line — which is the mirror image of the persisted fifo split below.
    assert by_line[line_early["id"]] == 1, (
        "the preview ordering puts the excess on line A, the earlier line")
    assert by_line[line_late["id"]] == 0


def test_confirmation_keeps_the_earliest_confirmed_line_intact(
        api, merchandiser_headers, vendor_headers):
    """PRD §3.4: "The order in which candidates absorb the excess is fixed when the
    confirmation actually happens: candidates are ranked by `confirmed_at`
    ascending, then by `line_unit_price_cents` descending, then by `created_at`
    ascending, so the earliest-confirmed buyer keeps their units and the newest
    lines absorb the oversell."

    Design: Difficulty/dual_variant_calc/oversell_split_variant_divergence_on_two_lines
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    (vendor, event, listing, cust_early, cust_late,
     line_early, line_late, po) = _two_lines_then_buy()

    vendor_h = dict(vendor_headers)
    vendor_h["X-User-ID"] = vendor["id"]
    validate_success(api.confirm_line(
        line_late["id"], {"confirm_units": 3}, vendor_h), 200)

    early = validate_success(api.get_confirmation(line_early["id"], ANY), 200)
    late = validate_success(api.get_confirmation(line_late["id"], ANY), 200)
    assert early["oversold_units"] == 0, (
        "the earliest-confirmed buyer keeps their units")
    assert late["oversold_units"] == 1, "the newest line absorbs the oversell"

    listing_now = validate_success(api.get_listing(listing["id"], ANY), 200)
    assert listing_now["oversell_units"] == 1