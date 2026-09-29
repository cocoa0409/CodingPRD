"""Calculation kernels at their edges: the pinned debit-then-credit order and the
shelf clamp, which stops feed a commitment rollup, an empty attachment
denominator, the sizing ranking, the depreciation floor, and the finality of a
price snapshot.
"""

from test_helpers.assertions import (
    assert_invoice,
    assert_invoice_line,
    assert_par_level,
    assert_par_unit_invariant,
    assert_placement,
    assert_price_adjustment,
    assert_stock_status_derived,
)
from test_helpers.constants import ANCHOR_MONDAY
from test_helpers.fixtures import (
    CATALOG_SPEC_COFFEE_ONLY,
    assemble_invoice_for,
    cancel_account,
    complete_stop,
    create_account,
    create_asset,
    create_model,
    create_product,
    create_route,
    create_second_route,
    create_site,
    evaluate_compliance,
    lines_by_type,
    override_par_line,
    par_line_for,
    place_asset_at_site,
    plan_site,
    propose_adjustment,
    read_account,
    read_asset,
    read_placement,
    read_site,
    read_visit,
    recompute_attachment,
    respond_adjustment,
    schedule_stop_with_lines,
    set_clock,
    set_market_index,
    setup_placed_site,
    setup_planned_site,
    void_visit,
)
from test_helpers.test_users import TEST_USERS

AM = TEST_USERS["account_manager_headers"]
BS = TEST_USERS["billing_specialist_headers"]

# Coffee is green-linked; the creamer beside it never is.
GREEN_LINKED_CATALOG = [
    ("COFFEE", "COFFEE", "COF-HOUSE-1LB", 4500000, True),
    ("CREAMER", "CREAMER", "CRM-DAIRY-QT", 2000000, False),
]


def _coffee_line(visit: dict, product_id: str) -> dict:
    """The one element of a reported stop that carries the named product."""
    matches = [line for line in visit["lines"] if line["product_id"] == product_id]
    assert len(matches) == 1, "a visit carries at most one line per product"
    return matches[0]


def test_the_shelf_debit_floors_the_modelled_draw_then_clamps_at_what_is_there():
    """Three stops a week apart on one overridden coffee shelf: no draw on the
    first, a floored fourteen-unit draw on the second, and on the third a modelled
    thirty-five units clamped down to the twenty-one actually on the shelf.

    "The elapsed days are the time from the par line's `last_service_at` to the
    visit's `window_start`, divided by 86400 seconds, rounded down to a whole
    number of days."

    "The modelled consumption is the daily draw multiplied by the elapsed days,
    rounded down to whole units, and then clamped to the shelf quantity: the
    consumed quantity is the smaller of the current `on_hand_units` and that
    modelled figure, so the shelf can never be driven negative."

    Design: Corner/calculations/corner_consumption_debit_floors_the_modeled_draw_then_clamps_at_the_shelf_quantity
    """
    base = setup_planned_site(
        clock=ANCHOR_MONDAY, catalog_spec=CATALOG_SPEC_COFFEE_ONLY
    )
    site_id = base["site"]["id"]
    coffee_id = base["products"]["COFFEE"]["id"]

    forecast_line = par_line_for(site_id, coffee_id)
    assert forecast_line["par_units"] == 65
    assert forecast_line["reorder_point_units"] == 26
    assert forecast_line["source"] == "FORECAST"

    # A two-week cover of 28 units is a modelled draw of exactly 2.0 a day.
    overridden = override_par_line(
        forecast_line["id"], par_units=28, reorder_point_units=12
    )
    assert_par_level(overridden)
    assert overridden["par_units"] == 28
    assert overridden["reorder_point_units"] == 12
    assert overridden["source"] == "MANUAL"

    first = schedule_stop_with_lines(base, {"COFFEE": 30})
    first = complete_stop(base, first, {"COFFEE": 30}, complete_at="2026-08-03T09:30:00Z")
    element = _coffee_line(first, coffee_id)
    assert element["consumed_units"] == 0, "nothing elapsed before the first stop"
    assert element["delivered_units"] == 30
    assert element["resulting_on_hand_units"] == 30

    after_first = par_line_for(site_id, coffee_id)
    assert after_first["cumulative_consumed_units"] == 0
    assert after_first["cumulative_delivered_units"] == 30
    assert after_first["on_hand_units"] == 30
    assert after_first["stock_status"] == "IN_STOCK"
    assert after_first["last_service_at"] == "2026-08-03T09:00:00Z"
    assert_par_unit_invariant(after_first)
    assert_stock_status_derived(after_first)

    second = schedule_stop_with_lines(
        base,
        {"COFFEE": 5},
        window_start="2026-08-10T09:00:00Z",
        window_end="2026-08-10T09:45:00Z",
    )
    second = complete_stop(
        base, second, {"COFFEE": 5}, complete_at="2026-08-10T09:30:00Z"
    )
    element = _coffee_line(second, coffee_id)
    assert element["consumed_units"] == 14, "floor(28 / 14 * 7) over seven days"
    assert element["delivered_units"] == 5
    assert element["resulting_on_hand_units"] == 21, "30 debited by 14 then credited 5"

    after_second = par_line_for(site_id, coffee_id)
    assert after_second["cumulative_consumed_units"] == 14
    assert after_second["cumulative_delivered_units"] == 35
    assert after_second["on_hand_units"] == 21
    assert after_second["stock_status"] == "IN_STOCK"
    assert after_second["last_service_at"] == "2026-08-10T09:00:00Z"
    assert_par_unit_invariant(after_second)

    # Lifting the cover target to 70 asks for a 35-unit draw off a 21-unit shelf.
    raised = override_par_line(after_second["id"], par_units=70, reorder_point_units=28)
    assert raised["par_units"] == 70
    assert raised["reorder_point_units"] == 28
    assert raised["on_hand_units"] == 21

    third = schedule_stop_with_lines(
        base,
        {"COFFEE": 3},
        window_start="2026-08-17T09:00:00Z",
        window_end="2026-08-17T09:45:00Z",
    )
    third = complete_stop(
        base, third, {"COFFEE": 3}, complete_at="2026-08-17T09:30:00Z"
    )
    element = _coffee_line(third, coffee_id)
    assert element["consumed_units"] == 21, "the clamp, not the modelled 35"
    assert element["delivered_units"] == 3
    assert element["resulting_on_hand_units"] == 3, "debited to 0, then credited 3"
    assert element["resulting_on_hand_units"] >= 0

    after_third = par_line_for(site_id, coffee_id)
    assert after_third["cumulative_consumed_units"] == 35
    assert after_third["cumulative_delivered_units"] == 38
    assert after_third["on_hand_units"] == 3
    assert after_third["stock_status"] == "LOW", "0 < 3 <= 28"
    assert_par_unit_invariant(after_third)
    assert_stock_status_derived(after_third)

    site = read_site(site_id)
    assert site["escalation_score"] == 7.5, "one shelf below its reorder point"
    assert site["service_posture"] == "ACTIVE"


def test_the_trailing_purchase_rollup_counts_only_this_break_rooms_live_stops():
    """Of three reported stops inside the ninety-day window only one counts: the
    voided stop of this break room and the live stop of the sister break room are
    both excluded, and the warning precedes any fee.

    "Only the placement's **own site** contributes — a corporate account's other
    break rooms never subsidise this one — and only visits whose status is
    `COMPLETED` count."

    "When the measured trailing purchase is strictly below the placement's
    `minimum_purchase_cents`, a placement in `MEETING_MINIMUM` moves to
    `SHORTFALL_WARNED` and **no fee at all is accrued on the first miss** — the
    first shortfall is a warning."

    Design: Corner/calculations/corner_trailing_purchase_rollup_excludes_voided_visits_and_other_sites
    """
    base = setup_planned_site(
        clock=ANCHOR_MONDAY, catalog_spec=CATALOG_SPEC_COFFEE_ONLY
    )
    account_id = base["account"]["id"]
    coffee_id = base["products"]["COFFEE"]["id"]
    tuesday_route = create_second_route(name="Uptown Tuesday Route", service_day="TUE")

    first_asset = create_asset(base["model"]["id"], serial_number="URN30-0001")
    second_asset = create_asset(base["model"]["id"], serial_number="URN30-0002")
    rental_terms = {
        "terms_type": "RENTAL",
        "minimum_purchase_cents": 60000,
        "min_term_months": 12,
    }
    placement = place_asset_at_site(base["site"], first_asset["id"], **rental_terms)

    sister = create_site(
        account_id, tuesday_route["id"], site_name="Second Floor Break Room"
    )
    sister = plan_site(sister["id"])
    sister_placement = place_asset_at_site(sister, second_asset["id"], **rental_terms)
    sister_base = dict(base)
    sister_base["route"] = tuesday_route
    sister_base["site"] = sister

    counted = schedule_stop_with_lines(base, {"COFFEE": 20})
    complete_stop(base, counted, {"COFFEE": 20}, complete_at="2026-08-03T09:30:00Z")

    voided = schedule_stop_with_lines(
        base,
        {"COFFEE": 20},
        window_start="2026-08-03T10:15:00Z",
        window_end="2026-08-03T11:00:00Z",
    )
    complete_stop(base, voided, {"COFFEE": 20}, complete_at="2026-08-03T10:30:00Z")
    void_visit(voided["id"])

    elsewhere = schedule_stop_with_lines(
        sister_base,
        {"COFFEE": 20},
        window_start="2026-08-04T09:00:00Z",
        window_end="2026-08-04T09:45:00Z",
    )
    complete_stop(
        sister_base, elsewhere, {"COFFEE": 20}, complete_at="2026-08-04T09:30:00Z"
    )

    assert read_visit(voided["id"])["visit_status"] == "VOIDED"
    assert read_visit(elsewhere["id"])["visit_status"] == "COMPLETED"
    assert _coffee_line(read_visit(counted["id"]), coffee_id)[
        "effective_unit_price_micros"
    ] == 4500000

    warned = evaluate_compliance(placement["id"])
    assert_placement(warned)
    assert warned["trailing_purchase_cents"] == 9000, "20 units at 4500000 micros"
    assert warned["trailing_purchase_cents"] != 18000, "the voided stop is excluded"
    assert warned["trailing_purchase_cents"] != 27000, "the sister site is excluded"
    assert warned["compliance_status"] == "SHORTFALL_WARNED"
    assert warned["shortfall_fee_cents"] == 0, "the first miss is only a warning"
    assert warned["rent_charge_cents"] == 0, "rent is prorated at invoice assembly"
    assert warned["placement_status"] == "ACTIVE"
    assert warned["version"] == placement["version"] + 1

    billed = evaluate_compliance(placement["id"])
    assert billed["trailing_purchase_cents"] == 9000
    assert billed["compliance_status"] == "SHORTFALL_BILLED"
    assert billed["shortfall_fee_cents"] == 1125, "2500 bps of the full 4500 rent"
    assert billed["rent_charge_cents"] == 0
    assert billed["version"] == warned["version"] + 1

    untouched = read_placement(sister_placement["id"])
    assert untouched["trailing_purchase_cents"] == 0
    assert untouched["compliance_status"] == "MEETING_MINIMUM"
    assert untouched["shortfall_fee_cents"] == 0
    assert untouched["version"] == sister_placement["version"]


def test_the_allied_attachment_answers_zero_before_the_first_delivery():
    """Refreshing the non-coffee share before any delivery reports zero rather than
    dividing by nothing; after one stop of coffee and creamer it reports 2105 basis
    points, and refreshing again does not move it.

    "When the sum of both buckets is zero, the metric is 0 rather than an error —
    an account that has taken no delivery in the window reports zero attachment and
    the recompute succeeds."

    "The metric is the allied bucket multiplied by 10000 and divided by the sum of
    both buckets, rounded half up."

    Design: Corner/calculations/corner_allied_attachment_rollup_returns_zero_bps_on_an_empty_denominator
    """
    base = setup_planned_site(clock=ANCHOR_MONDAY, catalog_spec=GREEN_LINKED_CATALOG)
    account_id = base["account"]["id"]
    coffee_id = base["products"]["COFFEE"]["id"]
    creamer_id = base["products"]["CREAMER"]["id"]

    empty = recompute_attachment(account_id, headers=BS)
    assert empty["allied_attachment_bps"] == 0, "a zero denominator reports zero"
    assert empty["green_price_factor_bps"] == 10000

    visit = schedule_stop_with_lines(base, {"COFFEE": 20, "CREAMER": 12})
    visit = complete_stop(
        base,
        visit,
        {"COFFEE": 20, "CREAMER": 12},
        complete_at="2026-08-03T09:30:00Z",
    )
    assert _coffee_line(visit, coffee_id)["effective_unit_price_micros"] == 4500000
    assert _coffee_line(visit, creamer_id)["effective_unit_price_micros"] == 2000000

    # 9000 cents of coffee beside 2400 cents of creamer: 2400 * 10000 / 11400.
    measured = recompute_attachment(account_id, headers=AM)
    assert measured["allied_attachment_bps"] == 2105

    again = recompute_attachment(account_id, headers=BS)
    assert again["allied_attachment_bps"] == 2105, "no new delivery, no movement"


def test_the_sizing_selector_ranks_capacity_then_rent_then_registration_order():
    """Six catalogued brewers: the undersized one and the wrong-band one are
    ineligible, the smallest sufficient capacity beats a cheaper larger machine, the
    cheaper rent wins the capacity tie, and the earlier registration wins the rent
    tie.

    "The eligible candidates are the brewer models whose headcount band contains
    the site's headcount — that is, the model's minimum headcount is at or below the
    site's headcount and the model's maximum headcount is at or above it, both
    bounds inclusive — and whose cups-per-hour capacity is at or above the site's
    required peak throughput."

    "Candidates are ranked by cups-per-hour capacity ascending, so the **smallest
    sufficient** brewer wins; ties are broken by monthly rent ascending, and any
    remaining tie is broken by the model's `created_at` ascending — never by
    identifier."

    Design: Corner/calculations/corner_equipment_sizing_selector_ranks_capacity_then_rent_then_created_at
    """
    set_clock(ANCHOR_MONDAY)
    route = create_route()
    create_product(
        sku="COF-HOUSE-1LB",
        category="COFFEE",
        base_unit_price_micros=4500000,
        pack_units=1,
        green_coffee_linked=True,
    )

    # Registered a minute apart, so the created_at tie-break is observable.
    catalogue = [
        ("TOO-SMALL", 20, 100, 1, 250, "2026-08-03T08:00:00Z"),
        ("BIG-RENT", 30, 4500, 1, 250, "2026-08-03T08:01:00Z"),
        ("TIE-EARLY", 30, 3000, 1, 250, "2026-08-03T08:02:00Z"),
        ("TIE-LATE", 30, 3000, 1, 250, "2026-08-03T08:03:00Z"),
        ("CAP-60", 60, 2000, 1, 250, "2026-08-03T08:04:00Z"),
        ("WRONG-BAND", 90, 500, 200, 400, "2026-08-03T08:05:00Z"),
    ]
    models = {}
    for code, capacity, rent, low, high, registered_at in catalogue:
        set_clock(registered_at)
        models[code] = create_model(
            model_code=code,
            cups_per_hour_capacity=capacity,
            monthly_rent_cents=rent,
            min_headcount=low,
            max_headcount=high,
        )
    assert models["TIE-EARLY"]["created_at"] < models["TIE-LATE"]["created_at"]

    account = create_account()
    site = create_site(account["id"], route["id"])
    assert site["headcount"] == 40
    planned = plan_site(site["id"])

    assert planned["forecast_cups_per_week"] == 360
    assert planned["required_peak_cups_per_hour"] == 26
    assert planned["recommended_model_id"] == models["TIE-EARLY"]["id"]
    assert planned["recommended_model_id"] != models["TOO-SMALL"]["id"], (
        "a 20-cup brewer cannot serve a 26-cup peak, however cheap its rent"
    )
    assert planned["recommended_model_id"] != models["WRONG-BAND"]["id"], (
        "a headcount of 40 is outside the 200-400 band"
    )
    assert planned["recommended_model_id"] != models["CAP-60"]["id"], (
        "capacity ascending beats a cheaper oversized brewer"
    )
    assert planned["recommended_model_id"] != models["BIG-RENT"]["id"], (
        "the capacity tie is broken by the lower rent"
    )
    assert planned["recommended_model_id"] != models["TIE-LATE"]["id"], (
        "the rent tie is broken by the earlier created_at"
    )


def test_the_unreturned_write_off_stops_at_the_residual_floor():
    """A brewer forty-seven whole months in service would depreciate below the
    residual floor, so the floor binds and the write-off is thirty percent of list
    value plus the flat trip fee.

    "The depreciated proportion is 10000 basis points reduced by 150 basis points
    for each whole month in service — one and a half percent per month — but never
    allowed below a residual floor of 3000 basis points, so an asset never
    depreciates past thirty percent of its list value no matter how old it is."

    "The charge finally billed is that residual value plus a flat retrieval trip fee
    of 7500 cents, and the sum is what lands in the placement's
    `unreturned_billed_cents` and on the `UNRETURNED_ASSET` line."

    Design: Corner/calculations/corner_unreturned_asset_charge_stops_at_the_residual_floor
    """
    base = setup_placed_site(
        clock=ANCHOR_MONDAY,
        terms_type="LOAN",
        minimum_purchase_cents=90000,
        min_term_months=12,
        serial_number="URN30-0001",
        catalog_spec=CATALOG_SPEC_COFFEE_ONLY,
    )
    assert base["model"]["list_value_cents"] == 120000
    assert base["placement"]["placed_at"] == ANCHOR_MONDAY

    cancel_account(
        base["account"]["id"], retrieval_due_by="2026-09-30T00:00:00Z"
    )
    scheduled = read_placement(base["placement"]["id"])
    assert scheduled["placement_status"] == "RETRIEVAL_SCHEDULED"
    assert scheduled["retrieval_due_by"] == "2026-09-30T00:00:00Z"
    assert scheduled["unreturned_billed_cents"] == 0

    # 1428 days after installation: 47 whole months, 10000 - 47 * 150 == 2950 bps.
    set_clock("2030-07-01T12:00:00Z")
    invoice = assemble_invoice_for(
        base["account"]["id"], "2030-06-01T00:00:00Z", "2030-06-30T23:59:59Z"
    )
    assert_invoice(invoice)
    assert invoice["invoice_status"] == "DRAFT"

    by_type = lines_by_type(invoice["id"])
    assert sorted(by_type) == ["FREIGHT", "UNRETURNED_ASSET"]
    assert len(by_type["UNRETURNED_ASSET"]) == 1
    write_off = by_type["UNRETURNED_ASSET"][0]
    assert_invoice_line(write_off)
    assert write_off["amount_cents"] == 43500, "120000 * 3000 / 10000 plus 7500"
    assert write_off["amount_cents"] != 42900, "the uncapped 2950 bps is never used"
    assert by_type["FREIGHT"][0]["amount_cents"] == 2500

    assert invoice["pre_freight_total_cents"] == 43500
    assert invoice["allied_discount_bps"] == 0
    assert invoice["allied_discount_cents"] == 0
    assert invoice["freight_cents"] == 2500, "43500 is short of the 50000 waiver"
    assert invoice["total_cents"] == 46000
    assert invoice["line_count"] == 2

    billed = read_placement(base["placement"]["id"])
    assert billed["placement_status"] == "UNRETURNED_BILLED"
    assert billed["unreturned_billed_cents"] == 43500
    assert billed["rent_charge_cents"] == 0, "a loan placement never accrues rent"
    assert billed["compliance_status"] == "MEETING_MINIMUM"
    assert read_asset(base["asset"]["id"])["asset_status"] == "UNRETURNED"


def test_only_green_linked_coffee_follows_the_index_and_the_snapshot_is_final():
    """An accepted adjustment lifts the account's factor to 11200: the next stop
    prices green-linked coffee twelve percent higher while creamer stands still, and
    the earlier stop keeps its own snapshot right through invoice assembly.

    "When the product's `green_coffee_linked` flag is true, the effective unit price
    in micro-dollars is the product's `base_unit_price_micros` multiplied by the
    account's `green_price_factor_bps`, divided by 10000, rounded half up to whole
    micro-dollars."

    "That snapshot is authoritative forever afterwards: invoice assembly and
    trailing-purchase rollups **must reuse** it and must **never** recompute a price
    at invoice time, even if the account's factor has since moved."

    Design: Corner/calculations/corner_effective_unit_price_scales_only_green_linked_products_and_the_snapshot_is_final
    """
    base = setup_planned_site(
        clock=ANCHOR_MONDAY,
        catalog_spec=GREEN_LINKED_CATALOG,
        account_overrides={"green_index_baseline_micros": 2000000},
    )
    account_id = base["account"]["id"]
    coffee_id = base["products"]["COFFEE"]["id"]
    creamer_id = base["products"]["CREAMER"]["id"]
    assert base["account"]["green_price_factor_bps"] == 10000

    before = schedule_stop_with_lines(base, {"COFFEE": 10, "CREAMER": 10})
    before = complete_stop(
        base,
        before,
        {"COFFEE": 10, "CREAMER": 10},
        complete_at="2026-08-03T09:30:00Z",
    )
    assert _coffee_line(before, coffee_id)["effective_unit_price_micros"] == 4500000
    assert _coffee_line(before, creamer_id)["effective_unit_price_micros"] == 2000000

    set_market_index(2400000, headers=BS)
    proposal = propose_adjustment(account_id, effective_at="2026-08-04T00:00:00Z")
    assert_price_adjustment(proposal)
    assert proposal["index_baseline_micros"] == 2000000
    assert proposal["index_current_micros"] == 2400000
    assert proposal["movement_bps"] == 2000
    assert proposal["adjustment_pct_bps"] == 1200, "6000 bps of 2000, under the cap"
    assert proposal["adj_status"] == "PROPOSED"

    accepted = respond_adjustment(proposal["id"], account_id, "ACCEPT")
    assert accepted["adj_status"] == "ACCEPTED"
    repriced = read_account(account_id)
    assert repriced["green_price_factor_bps"] == 11200
    assert repriced["green_index_baseline_micros"] == 2400000

    after = schedule_stop_with_lines(
        base,
        {"COFFEE": 10, "CREAMER": 10},
        window_start="2026-08-10T09:00:00Z",
        window_end="2026-08-10T09:45:00Z",
    )
    after = complete_stop(
        base,
        after,
        {"COFFEE": 10, "CREAMER": 10},
        complete_at="2026-08-10T09:30:00Z",
    )
    assert _coffee_line(after, coffee_id)["effective_unit_price_micros"] == 5040000
    assert _coffee_line(after, creamer_id)["effective_unit_price_micros"] == 2000000, (
        "the factor only touches green-linked products"
    )

    # The first stop's snapshot survives the reprice.
    assert _coffee_line(read_visit(before["id"]), coffee_id)[
        "effective_unit_price_micros"
    ] == 4500000

    set_clock("2026-09-01T00:00:00Z")
    invoice = assemble_invoice_for(
        account_id, "2026-08-01T00:00:00Z", "2026-08-31T23:59:59Z"
    )
    product_lines = lines_by_type(invoice["id"])["PRODUCT"]
    assert sorted(line["amount_cents"] for line in product_lines) == [
        2000,
        2000,
        4500,
        5040,
    ], "the August coffee line is not repriced to 5040"
    assert invoice["pre_freight_total_cents"] == 13540
    assert invoice["allied_discount_bps"] == 0, "one allied category only"
    assert invoice["freight_cents"] == 2500
    assert invoice["total_cents"] == 16040
    assert invoice["line_count"] == 5
