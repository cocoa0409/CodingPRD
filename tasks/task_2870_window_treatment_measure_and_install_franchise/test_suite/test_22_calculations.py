"""Arithmetic pinned at its boundaries: rounding order, caps and the true-up delta."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import ERR_NO_ELIGIBLE_VENDOR
from test_helpers.assertions import (
    assert_inches_equal,
    assert_instant_equals,
    assert_ledger_entry,
    assert_page_meta,
    assert_remake_buckets_sum,
)
from test_helpers.fixtures import (
    CLOCK_START,
    accept_quote,
    add_sample_kit,
    book_consultation,
    build_quote,
    charter_territory,
    checkout_kit,
    configure_opening,
    hire_designer,
    intake_lead,
    onboard_vendor,
    place_order,
    present_quote,
    read_designer,
    read_install_job,
    read_opening,
    read_order,
    read_quote,
    read_territory,
    receive_order,
    record_opening,
    return_kit,
    schedule_install,
    set_clock,
    ship_order,
)
from test_helpers.test_users import (
    designer_headers,
    franchisee_headers,
    franchisor_headers,
)

CAPACITY_FIVE = {"cutoff_hour_utc": 15, "concurrent_capacity": 5}


def _appointment(api, **territory_kwargs):
    """One ACTIVE territory, one ACTIVE designer and one SCHEDULED appointment."""
    territory = charter_territory(api, **territory_kwargs)
    designer = hire_designer(api, territory)
    lead = intake_lead(api, territory)
    consultation = book_consultation(api, designer, lead)
    return territory, designer, consultation


def test_the_oversize_surcharge_engages_strictly_above_the_width_boundary(api):
    """Two walls an eighth of an inch apart: 72.000 pays nothing, 72.125 pays 15 percent.

    "When the billable width is strictly greater than 72.000 inches the surcharge rate is
    0.15; otherwise it is zero."

    "The surcharge is the sum of fabric, lift and motor charges multiplied by that rate
    and rounded half up to a whole cent, and it is computed on that **combined** sum,
    never on the fabric charge alone."

    "Their product divided by 144 gives the raw area in square feet, and `billable_sqft`
    is that raw area rounded **up** to the next whole quarter of a square foot — the
    trade's billing unit."

    Design: Corner/calculations/the_oversize_surcharge_engages_strictly_above_the_billable_width_boundary
    """
    _territory, designer, consultation = _appointment(api)
    at_boundary = record_opening(api, designer, consultation,
                                label="Slider at the boundary",
                                room_type="LIVING_ROOM", width_top_in=72.500,
                                height_left_in=48.250)
    over_boundary = record_opening(api, designer, consultation,
                                   label="Slider one eighth over",
                                   room_type="LIVING_ROOM",
                                   width_top_in=72.625,
                                   height_left_in=48.250)
    assert_inches_equal(at_boundary["ordered_width_in"], 72.000,
                        "ordered_width_in")
    assert_inches_equal(over_boundary["ordered_width_in"], 72.125,
                        "ordered_width_in")

    priced_at = configure_opening(api, designer, at_boundary,
                                  fabric_code="LT-SHEER", lift_system="CORDED")
    priced_over = configure_opening(api, designer, over_boundary,
                                    fabric_code="LT-SHEER",
                                    lift_system="CORDED")

    # 72.000 x 48.000 / 144 is exactly 24, so the quarter-sqft step is a no-op.
    assert priced_at["billable_sqft"] == 24.000
    assert priced_at["list_price_cents"] == 14880

    # 72.125 x 48.000 / 144 is 24.041666, which the quarter-sqft step lifts to 24.250.
    assert priced_over["billable_sqft"] == 24.250
    assert priced_over["list_price_cents"] == 17290

    # 15 percent of THIS opening's own 15035, not of the boundary opening's 14880.
    assert priced_over["list_price_cents"] - 15035 == 2255
    assert priced_over["list_price_cents"] - priced_at["list_price_cents"] == 2410

    reread = validate_success(api.get_consultation(
        consultation["id"], designer_headers(designer["id"])))
    assert reread["configured_opening_count"] == 2


def test_wholesale_cost_rounds_once_over_the_summed_retail_prices(api):
    """Retail rounds per opening; wholesale rounds once, and the two differ by a cent.

    "The order's wholesale exposure, `order_cost_cents`, is 42 percent of the summed
    `list_price_cents` of the named openings, rounded half up to a whole cent **once**,
    over the summed retail figure."

    "Rounding each opening's wholesale share separately and then summing is forbidden:
    three openings at 5875 cents each total 17625 cents retail, and 42 percent of that is
    7402.5, which rounds once to 7403 cents — whereas rounding 2467.5 three times and
    summing gives 7404."

    Design: Corner/calculations/wholesale_cost_rounds_once_over_the_summed_retail_prices
    """
    territory, designer, consultation = _appointment(api)
    vendor = onboard_vendor(api, **CAPACITY_FIVE)
    openings = []
    for label in ("Bay left", "Bay centre", "Bay right"):
        opening = record_opening(api, designer, consultation, label=label,
                                 width_top_in=24.000, height_left_in=37.125)
        openings.append(configure_opening(api, designer, opening,
                                          fabric_code="CL-LINEN",
                                          lift_system="CORDED"))
    for priced in openings:
        assert priced["billable_sqft"] == 6.250
        assert priced["list_price_cents"] == 5875

    quote = build_quote(api, designer, consultation)
    quote = present_quote(api, designer, quote)
    assert quote["subtotal_cents"] == 17625
    assert quote["install_fee_cents"] == 15000
    assert quote["pre_discount_total_cents"] == 32625
    assert quote["discount_pct"] == 0
    assert quote["net_sales_cents"] == 17625
    accept_quote(api, designer, quote)

    order = place_order(api, territory, quote,
                        [opening["id"] for opening in openings], vendor)
    assert order["order_cost_cents"] == 7403
    assert set(order["opening_ids"]) == {opening["id"] for opening in openings}

    counters = read_territory(api, territory)
    assert counters["open_order_exposure_cents"] == 7403
    assert counters["net_sales_cents"] == 17625
    assert counters["royalty_accrued_cents"] == 969

    for opening in openings:
        assert read_opening(api, designer,
                           opening["id"])["measure_status"] == "QUOTED"


def test_the_royalty_true_up_is_a_difference_of_two_rounded_figures(api):
    """Both bases land on a half cent, so rounding the delta gives the wrong reversal.

    "The royalty delta is the royalty on the final basis minus the royalty on the quote's
    current `recognized_net_sales_cents`, each figure computed independently as its basis
    multiplied by the territory's `royalty_rate_pct` and rounded half up."

    "When the delta is positive a ledger row of type `NET_SALES_ROYALTY` is appended for
    it; when negative, a row of type `ROYALTY_REVERSAL` carrying the negative amount; and
    when the delta is exactly zero **no ledger row is written at all**."

    Design: Corner/calculations/the_royalty_true_up_is_a_difference_of_two_independently_rounded_figures
    """
    territory, designer, consultation = _appointment(api, royalty_rate_pct=0.055)
    vendor = onboard_vendor(api, **CAPACITY_FIVE)
    first = configure_opening(
        api, designer,
        record_opening(api, designer, consultation, label="Twin left",
                       width_top_in=24.500, height_left_in=30.250),
        fabric_code="LT-SHEER", lift_system="CORDED")
    second = configure_opening(
        api, designer,
        record_opening(api, designer, consultation, label="Twin right",
                       width_top_in=24.500, height_left_in=30.250),
        fabric_code="LT-SHEER", lift_system="CORDED")
    assert first["billable_sqft"] == 5.000
    assert first["list_price_cents"] == 3100

    quote = build_quote(api, designer, consultation)
    present_quote(api, designer, quote)
    accepted = accept_quote(api, designer, quote)
    assert accepted["subtotal_cents"] == 6200
    assert accepted["install_fee_cents"] == 12500
    assert accepted["recognized_net_sales_cents"] == 6200

    installed = place_order(api, territory, quote, [first["id"]], vendor)
    place_order(api, territory, quote, [second["id"]], vendor)
    ship_order(api, vendor, installed)
    receive_order(api, territory, installed)
    job = schedule_install(api, territory, installed, designer)
    signed = validate_success(api.complete_install_job(
        job["id"], designer_headers(designer["id"])))
    assert signed["install_status"] == "COMPLETED"
    assert read_opening(api, designer,
                        first["id"])["install_outcome"] == "INSTALLED"
    assert read_opening(api, designer,
                        second["id"])["install_outcome"] == "PENDING"

    owner = franchisee_headers(territory["id"])
    rows, meta = validate_paginated(api.list_ledger_entries(
        territory["id"], owner))
    assert_page_meta(meta, total_count=2)
    assert_ledger_entry(rows[0], "NET_SALES_ROYALTY", 341, 6200,
                        "quote_accepted", "QUOTE", source_entity_id=quote["id"],
                        territory_id=territory["id"])
    # 171 - 341, not round_half_up(-3100 x 0.055) = -171.
    assert_ledger_entry(rows[1], "ROYALTY_REVERSAL", -170, 3100,
                        "install_trueup", "INSTALL_JOB",
                        source_entity_id=job["id"],
                        territory_id=territory["id"])

    counters = read_territory(api, territory)
    assert counters["royalty_accrued_cents"] == 171
    assert counters["net_sales_cents"] == 3100

    restated = read_quote(api, territory, quote["id"])
    assert restated["recognized_net_sales_cents"] == 3100
    assert restated["credited_net_sales_cents"] == 0


def test_the_liability_matrix_reads_reason_mount_and_geometry_in_that_order(api):
    """Three exceptions, three liable parties, and two boundaries facing opposite ways.

    "Damaged goods are always the manufacturer's fault, so `DAMAGED_GOODS` yields a
    `liable_party` of `VENDOR`."

    "The boundaries are exact: an `out_of_square_in` of exactly 0.375 on an inside mount
    is `CUSTOMER` while 0.376 is `MEASURER`, and a `depth_in` of exactly 2.500 on an
    inside mount is `MEASURER` while 2.499 is `CUSTOMER`."

    "A liable party of `MEASURER` makes the territory's target the whole cost and the
    vendor's target zero."

    Design: Corner/calculations/the_liability_matrix_reads_reason_mount_and_geometry_in_that_order
    """
    territory, designer, consultation = _appointment(
        api, royalty_rate_pct=0.055, liability_window="ROLLING_180D")
    vendor = onboard_vendor(api, remake_policy="SHARED_50_50", **CAPACITY_FIVE)
    square = record_opening(api, designer, consultation, label="Square deep")
    racked = record_opening(api, designer, consultation,
                            label="Racked to tolerance", width_top_in=24.000,
                            width_middle_in=24.375, width_bottom_in=24.100)
    shallow = record_opening(api, designer, consultation,
                             label="Shallow pocket", depth_in=2.500)
    assert_inches_equal(racked["out_of_square_in"], 0.375, "out_of_square_in")

    priced = [configure_opening(api, designer, opening,
                                fabric_code="LT-SHEER", lift_system="CORDED")
              for opening in (square, racked, shallow)]
    for opening in priced:
        assert opening["list_price_cents"] == 4960

    quote = build_quote(api, designer, consultation)
    present_quote(api, designer, quote)
    accepted = accept_quote(api, designer, quote)
    assert accepted["subtotal_cents"] == 14880
    assert accepted["install_fee_cents"] == 15000
    assert accepted["net_sales_cents"] == 14880

    orders, jobs = [], []
    windows = (("09:00", "11:00"), ("11:00", "13:00"), ("13:00", "15:00"))
    for opening, (start, end) in zip(priced, windows):
        order = place_order(api, territory, quote, [opening["id"]], vendor)
        assert order["order_cost_cents"] == 2083
        ship_order(api, vendor, order)
        receive_order(api, territory, order)
        orders.append(order)
        jobs.append(schedule_install(
            api, territory, order, designer,
            scheduled_start_at=f"2026-08-20T{start}:00.000Z",
            scheduled_end_at=f"2026-08-20T{end}:00.000Z"))

    set_clock(api, "2026-08-20T09:30:00.000Z")
    dsg = designer_headers(designer["id"])
    verdicts = []
    for job, opening, reason in zip(jobs, priced,
                                    ("DAMAGED_GOODS", "OUT_OF_SQUARE",
                                     "OBSTRUCTION")):
        verdicts.append(validate_success(api.raise_install_exception(
            job["id"], f.exception_payload(opening["id"], reason), dsg)))
        if reason != "OBSTRUCTION":
            assert read_designer(api, territory,
                                designer["id"])["status"] == "ACTIVE"

    damaged, out_of_square, obstructed = verdicts
    assert damaged["liable_party"] == "VENDOR"
    assert damaged["remeasure_charge_cents"] == 0
    assert out_of_square["liable_party"] == "CUSTOMER"
    assert out_of_square["remeasure_charge_cents"] == 0
    assert obstructed["liable_party"] == "MEASURER"
    assert obstructed["remeasure_charge_cents"] == 1736

    # The waterfall follows the liable party, never the vendor's remake policy.
    expected = ((2083, 0, 0), (0, 0, 2083), (0, 2083, 0))
    for order, (vendor_share, territory_share, customer_share) in zip(orders,
                                                                     expected):
        settled = read_order(api, territory, order["id"])
        assert settled["vendor_absorbed_cents"] == vendor_share
        assert settled["territory_absorbed_cents"] == territory_share
        assert settled["customer_absorbed_cents"] == customer_share
        assert_remake_buckets_sum(settled)
        assert settled["status"] == "PLACED"
        assert settled["remake_count"] == 1

    owner = franchisee_headers(territory["id"])
    remakes, remake_meta = validate_paginated(api.list_ledger_entries(
        territory["id"], owner, entry_type="REMAKE_CHARGEBACK"))
    assert_page_meta(remake_meta, total_count=1)
    assert remakes[0]["amount_cents"] == 2083
    assert remakes[0]["basis_cents"] == 2083

    charges, charge_meta = validate_paginated(api.list_ledger_entries(
        territory["id"], owner, entry_type="REMEASURE_CHARGEBACK"))
    assert_page_meta(charge_meta, total_count=1)
    assert charges[0]["amount_cents"] == 1736
    assert charges[0]["basis_cents"] == 4960

    counters = read_territory(api, territory)
    assert counters["remake_chargeback_cents"] == 3819
    assert counters["royalty_accrued_cents"] == 818

    scored = read_designer(api, territory, designer["id"])
    assert scored["remeasure_exception_count"] == 1
    assert scored["remeasure_liability_score"] == 78
    assert scored["status"] == "SUSPENDED"

    for opening in priced:
        final = read_opening(api, designer, opening["id"])
        assert final["measure_status"] == "REMEASURE_REQUIRED"
        assert final["install_outcome"] == "NOT_INSTALLED"


def test_the_remeasure_cap_and_the_territory_cap_clip_different_figures(api):
    """One expensive opening trips both ceilings, and they clip two different amounts.

    "When and only when `liable_party` is `MEASURER`, `remeasure_charge_cents` is 35
    percent of the named opening's `list_price_cents`, rounded half up to a whole cent
    and **then** capped at 12000 cents — rounding before the cap, never after."

    "`territory_absorbed_cents` is the smallest of the territory's target, a hard
    territory cap of 15000 cents, and whatever remains of `remake_cost_cents` after the
    vendor's bucket."

    "`customer_absorbed_cents` is the pure remainder: `remake_cost_cents` less the
    vendor's bucket less the territory's bucket."

    Design: Corner/calculations/the_remeasure_cap_and_the_territory_cap_clip_two_different_figures
    """
    territory = charter_territory(api, royalty_rate_pct=0.055,
                                 credit_limit_cents=2000000)
    designer = hire_designer(api, territory, certifications=["MOTORIZATION"])
    vendor = onboard_vendor(api, motorization_extra_days=3,
                            remake_policy="FULL_VENDOR_90D",
                            supported_lift_systems=["MOTORIZED"],
                            supported_hub_platforms=["ALEXA"], **CAPACITY_FIVE)
    lead = intake_lead(api, territory, source="REFERRAL")
    consultation = book_consultation(api, designer, lead)
    opening = record_opening(api, designer, consultation,
                             label="Great room slider",
                             room_type="LIVING_ROOM", width_top_in=60.500,
                             width_middle_in=61.000, width_bottom_in=60.700,
                             height_left_in=84.250, depth_in=4.000)
    assert_inches_equal(opening["out_of_square_in"], 0.500, "out_of_square_in")
    opening = configure_opening(api, designer, opening, fabric_code="WD-FAUX",
                                lift_system="MOTORIZED",
                                motorization_option="HARDWIRED")
    assert opening["billable_sqft"] == 35.000
    assert opening["list_price_cents"] == 73750

    quote = build_quote(api, designer, consultation)
    quote = present_quote(api, designer, quote)
    assert quote["install_fee_cents"] == 14500
    assert quote["pre_discount_total_cents"] == 88250
    assert quote["discount_pct"] == 0
    accept_quote(api, designer, quote)

    order = place_order(api, territory, quote, [opening["id"]], vendor)
    assert order["order_cost_cents"] == 30975
    ship_order(api, vendor, order)
    receive_order(api, territory, order)
    job = schedule_install(api, territory, order, designer,
                           scheduled_start_at="2026-08-25T09:00:00.000Z",
                           scheduled_end_at="2026-08-25T12:00:00.000Z")

    set_clock(api, "2026-08-25T10:00:00.000Z")
    raised = validate_success(api.raise_install_exception(
        job["id"], f.exception_payload(opening["id"], "OUT_OF_SQUARE"),
        designer_headers(designer["id"])))
    assert raised["liable_party"] == "MEASURER"
    # round_half_up(73750 x 0.35) is 25813, clipped afterwards to the 12000 cap.
    assert raised["remeasure_charge_cents"] == 12000
    assert raised["commissioning_status"] == "PENDING"

    settled = read_order(api, territory, order["id"])
    assert settled["remake_cost_cents"] == 30975
    assert settled["vendor_absorbed_cents"] == 0
    assert settled["territory_absorbed_cents"] == 15000
    assert settled["customer_absorbed_cents"] == 15975
    assert_remake_buckets_sum(settled)

    owner = franchisee_headers(territory["id"])
    charges, charge_meta = validate_paginated(api.list_ledger_entries(
        territory["id"], owner, entry_type="REMEASURE_CHARGEBACK"))
    assert_page_meta(charge_meta, total_count=1)
    assert_ledger_entry(charges[0], "REMEASURE_CHARGEBACK", 12000, 73750,
                        "remeasure_chargeback", "INSTALL_JOB",
                        source_entity_id=job["id"],
                        territory_id=territory["id"])

    remakes, remake_meta = validate_paginated(api.list_ledger_entries(
        territory["id"], owner, entry_type="REMAKE_CHARGEBACK"))
    assert_page_meta(remake_meta, total_count=1)
    assert remakes[0]["amount_cents"] == 15000
    assert remakes[0]["basis_cents"] == 30975

    counters = read_territory(api, territory)
    assert counters["remake_chargeback_cents"] == 27000
    assert counters["net_sales_cents"] == 73750
    assert counters["royalty_accrued_cents"] == 4056

    scored = read_designer(api, territory, designer["id"])
    assert scored["remeasure_liability_score"] == 78
    assert scored["status"] == "SUSPENDED"


CORDED_ONLY = {"motorization_extra_days": 3, "cutoff_hour_utc": 17,
               "concurrent_capacity": 5, "supported_lift_systems": ["CORDED"]}


def _three_vendors_at_distinct_instants(api):
    """Y and Z promise the same date, X promises four days later.

    The three rows are created at three different logical instants, so their
    `created_at` order is Y, then Z, then X.
    """
    older = onboard_vendor(api, name="Yardley Mills", base_lead_time_days=10,
                           **CORDED_ONLY)
    set_clock(api, "2026-08-01T01:00:00.000Z")
    newer = onboard_vendor(api, name="Zephyr Shade Co", base_lead_time_days=10,
                           **CORDED_ONLY)
    set_clock(api, "2026-08-01T02:00:00.000Z")
    slower = onboard_vendor(api, name="Xanthe Blindworks",
                            base_lead_time_days=14, **CORDED_ONLY)
    return older, newer, slower


def test_the_vendor_selector_walks_all_three_ranking_terms_and_then_runs_dry(api):
    """Date, then book size, then date again — and the fourth placement finds nobody.

    "Among the eligible pool the winner is the candidate with, in order of precedence,
    the earliest promised ship date, then the smallest `open_order_count` — the least
    loaded partner next — then the earliest `created_at`, the longest-standing partner
    next."

    "Should two vendors tie on all three, their ids provide a last-resort total ordering
    that expresses no business preference at all."

    "If the eligible pool is empty the request fails with `ERR_NO_ELIGIBLE_VENDOR`
    (HTTP 422) and **nothing** is written — no order row, no increment of the quote's
    `version`, no ledger row."

    Design: Corner/calculations/the_vendor_selector_walks_all_three_ranking_terms_and_then_runs_dry
    """
    older, newer, slower = _three_vendors_at_distinct_instants(api)
    territory, designer, consultation = _appointment(api)
    corded = []
    for label in ("Front A", "Front B", "Front C"):
        opening = record_opening(api, designer, consultation, label=label)
        corded.append(configure_opening(api, designer, opening,
                                        fabric_code="LT-SHEER",
                                        lift_system="CORDED"))
    loop = record_opening(api, designer, consultation, label="Stairwell loop")
    loop = configure_opening(api, designer, loop, fabric_code="LT-SHEER",
                             lift_system="CONTINUOUS_LOOP")

    # 4960 plus the CONTINUOUS_LOOP uplift: the refusal below is about eligibility.
    assert loop["list_price_cents"] == 7560

    quote = build_quote(api, designer, consultation)
    present_quote(api, designer, quote)
    quote = accept_quote(api, designer, quote)
    set_clock(api, "2026-08-05T09:00:00.000Z")

    # Term 3: Y and Z tie on 2026-08-15 and on an empty book, so created_at decides.
    first = place_order(api, territory, quote, [corded[0]["id"]])
    assert first["vendor_id"] == older["id"]
    assert first["promised_ship_date"] == "2026-08-15"
    assert first["lead_time_days"] == 10

    # Term 2: the dates still tie but Y now carries one live order against Z's none.
    second = place_order(api, territory, quote, [corded[1]["id"]])
    assert second["vendor_id"] == newer["id"]

    # Term 3 again: one order each, so created_at breaks it and ids stay unconsulted.
    third = place_order(api, territory, quote, [corded[2]["id"]])
    assert third["vendor_id"] == older["id"]

    owner = franchisee_headers(territory["id"])
    pinned_version = read_quote(api, territory, quote["id"])["version"]
    validate_error(
        api.create_vendor_order(
            f.vendor_order_payload(quote["id"], [loop["id"]], pinned_version),
            owner),
        ERR_NO_ELIGIBLE_VENDOR, 422)

    placed, meta = validate_paginated(
        api.list_vendor_orders(owner, quote_id=quote["id"]))
    assert_page_meta(meta, total_count=3, has_more=False)
    assert [row["id"] for row in placed] == [first["id"], second["id"],
                                            third["id"]]
    assert read_quote(api, territory, quote["id"])["version"] == pinned_version
    assert read_opening(api, designer,
                        loop["id"])["measure_status"] == "QUOTED"

    hq = franchisor_headers()
    assert validate_success(
        api.get_vendor(older["id"], hq))["open_order_count"] == 2
    assert validate_success(
        api.get_vendor(newer["id"], hq))["open_order_count"] == 1
    assert validate_success(
        api.get_vendor(slower["id"], hq))["open_order_count"] == 0

    # Three orders at 42 percent of 4960, which is 2083 apiece.
    assert read_territory(api,
                          territory)["open_order_exposure_cents"] == 6249


HOLD_START = "2026-08-01T12:00:00.000Z"
FIFTH_AT_NOON = "2026-08-05T12:00:00.000Z"


def _three_open_loans(api):
    """Three OPEN loans across two designers, so neither accrues three late returns.

    Designer A holds the expensive kit KA and the cheap kit KC; designer B holds
    the second expensive kit KB. KA and KB share one due instant.
    """
    territory = charter_territory(api, liability_window="ROLLING_180D")
    first_designer = hire_designer(api, territory, full_name="Dana Reed")
    second_designer = hire_designer(api, territory, full_name="Milo Fry")
    expensive = add_sample_kit(api, territory, kit_code="SHEERS-A",
                               replacement_value_cents=50000)
    twin = add_sample_kit(api, territory, kit_code="SHEERS-B",
                          replacement_value_cents=50000)
    cheap = add_sample_kit(api, territory, kit_code="TRIM-C",
                           replacement_value_cents=5000)
    first_lead = intake_lead(api, territory, customer_name="Ana Ruiz")
    second_lead = intake_lead(api, territory, customer_name="Bo Chen",
                              source="REFERRAL",
                              requested_at="2026-08-01T09:00:00.000Z")
    first_appointment = book_consultation(
        api, first_designer, first_lead,
        scheduled_start_at="2026-08-05T14:00:00.000Z",
        scheduled_end_at="2026-08-05T15:00:00.000Z")
    second_appointment = book_consultation(
        api, second_designer, second_lead,
        scheduled_start_at="2026-08-05T14:00:00.000Z",
        scheduled_end_at="2026-08-05T15:00:00.000Z")
    return {
        "territory": territory,
        "first_designer": first_designer, "second_designer": second_designer,
        "expensive": expensive, "twin": twin, "cheap": cheap,
        "fourteen_days": checkout_kit(api, first_designer, expensive,
                                      first_appointment, HOLD_START,
                                      FIFTH_AT_NOON),
        "seven_days": checkout_kit(api, first_designer, cheap,
                                   first_appointment, HOLD_START,
                                   "2026-08-12T12:00:00.000Z"),
        "fifteen_days": checkout_kit(api, second_designer, twin,
                                     second_appointment, HOLD_START,
                                     FIFTH_AT_NOON),
    }


def test_the_late_fee_cap_and_the_write_off_threshold_are_one_millisecond_apart(api):
    """Fourteen days late is fined 10500; the same due instant a millisecond later is lost.

    "A successful check-out is stamped `OPEN` with `checked_out_at` taken from the logical
    clock and `due_at` set equal to `hold_end_at`; `returned_at` stays null, and
    `days_late` and `late_fee_cents` are both zero while the loan is open."

    "When `days_late` is at most fourteen, the kit is fined rather than written off:
    `late_fee_cents` is 750 cents per day late, capped at the kit's
    `replacement_value_cents` so that a fine can never exceed the asset."

    "A kit worth 5000 cents therefore reaches its cap at seven days late, where seven
    times 750 is 5250, and stays at 5000 for eight through fourteen days late."

    "When `days_late` is greater than fourteen the kit is written off instead of fined."

    Design: Corner/calculations/the_late_fee_cap_and_the_write_off_threshold_are_one_millisecond_apart
    """
    world = _three_open_loans(api)
    territory = world["territory"]
    assert_instant_equals(world["fourteen_days"]["due_at"], FIFTH_AT_NOON,
                          "due_at")

    set_clock(api, "2026-08-19T12:00:00.000Z")
    fined = return_kit(api, world["first_designer"], world["fourteen_days"])
    assert fined["days_late"] == 14
    assert fined["late_fee_cents"] == 10500
    assert fined["status"] == "RETURNED"

    capped = return_kit(api, world["first_designer"], world["seven_days"])
    assert capped["days_late"] == 7
    assert capped["late_fee_cents"] == 5000
    assert capped["status"] == "RETURNED"

    # One millisecond later the same due instant is fifteen days late, not fourteen.
    set_clock(api, "2026-08-19T12:00:00.001Z")
    written_off = return_kit(api, world["second_designer"],
                             world["fifteen_days"])
    assert written_off["days_late"] == 15
    assert written_off["late_fee_cents"] == 50000
    assert written_off["status"] == "LOST"

    owner = franchisee_headers(territory["id"])
    for kit, expected_status in ((world["expensive"], "AVAILABLE"),
                                (world["cheap"], "AVAILABLE"),
                                (world["twin"], "LOST")):
        stocked = validate_success(api.get_sample_kit(kit["id"], owner))
        assert stocked["status"] == expected_status
        assert stocked["loan_count"] == 1
        assert stocked["open_loan_count"] == 0

    counters = read_territory(api, territory)
    assert counters["available_kit_count"] == 2
    assert counters["on_loan_kit_count"] == 0
    assert counters["lost_kit_count"] == 1

    fees, fee_meta = validate_paginated(api.list_ledger_entries(
        territory["id"], owner, entry_type="SAMPLE_LATE_FEE"))
    assert_page_meta(fee_meta, total_count=2, has_more=False)
    assert {row["amount_cents"] for row in fees} == {10500, 5000}

    losses, loss_meta = validate_paginated(api.list_ledger_entries(
        territory["id"], owner, entry_type="SAMPLE_REPLACEMENT"))
    assert_page_meta(loss_meta, total_count=1, has_more=False)
    assert_ledger_entry(losses[0], "SAMPLE_REPLACEMENT", 50000, 50000,
                        "sample_lost", "SAMPLE_CHECKOUT",
                        source_entity_id=world["fifteen_days"]["id"],
                        territory_id=territory["id"])

    # The penalty is per designer, so nobody reaches the suspension threshold.
    two_late = read_designer(api, territory, world["first_designer"]["id"])
    assert two_late["late_sample_return_count"] == 2
    assert two_late["remeasure_liability_score"] == 82
    assert two_late["status"] == "ACTIVE"

    one_late = read_designer(api, territory, world["second_designer"]["id"])
    assert one_late["late_sample_return_count"] == 1
    assert one_late["remeasure_liability_score"] == 91
    assert one_late["status"] == "ACTIVE"


def test_an_uncovered_and_a_non_active_postal_code_both_land_unroutable(api):
    """A PROBATION franchise and an unchartered code are indistinguishable to the router.

    "A territory is an eligible destination when three conditions all hold: its `status`
    is `ACTIVE`, so that `PROBATION`, `SUSPENDED` and `TERMINATED` franchises never
    receive leads; the lead's `postal_code` is a member of that territory's
    `postal_codes`; and its `open_leads_count` is strictly less than its
    `lead_capacity_per_week`."

    "If no `ACTIVE` territory lists the postal code at all, the lead moves
    `NEW → UNROUTABLE`, again with `territory_id` and `routed_at` null, and that is
    terminal: a lead outside every active territory is never revisited."

    "Both outcomes still return HTTP 201 with the created lead, because a routing failure
    is a business state rather than a request error."

    Design: Corner/calculations/an_uncovered_and_a_non_active_postal_code_both_land_unroutable
    """
    hq = franchisor_headers()
    active = charter_territory(api, postal_codes=["30301"],
                              lead_capacity_per_week=5)
    sidelined = charter_territory(api, legal_name="Southmark Window Fashions",
                                  postal_codes=["30401"],
                                  lead_capacity_per_week=5)
    restated = validate_success(api.patch_territory(
        sidelined["id"], f.territory_patch(status="PROBATION"), hq))
    assert restated["status"] == "PROBATION"
    assert restated["version"] == sidelined["version"] + 1

    covered = validate_success(api.create_lead(f.lead_payload(
        customer_name="Ana Ruiz", postal_code="30301",
        source="NATIONAL_CALL_CENTER",
        requested_at="2026-08-01T08:00:00.000Z"), hq), 201)
    on_probation = validate_success(api.create_lead(f.lead_payload(
        customer_name="Bo Chen", postal_code="30401",
        source="NATIONAL_CALL_CENTER",
        requested_at="2026-08-01T09:00:00.000Z"), hq), 201)
    unchartered = validate_success(api.create_lead(f.lead_payload(
        customer_name="Cy Doyle", postal_code="99999",
        requested_at="2026-08-01T10:00:00.000Z"), hq), 201)

    assert covered["status"] == "ROUTED"
    assert covered["territory_id"] == active["id"]
    assert_instant_equals(covered["routed_at"], CLOCK_START, "routed_at")

    # A territory does list 30401, but not an ACTIVE one, so this is not QUEUED.
    assert on_probation["status"] == "UNROUTABLE"
    assert on_probation["territory_id"] is None
    assert on_probation["routed_at"] is None

    assert unchartered["status"] == "UNROUTABLE"
    assert unchartered["territory_id"] is None
    assert unchartered["routed_at"] is None

    assert read_territory(api, active)["open_leads_count"] == 1
    assert validate_success(api.get_territory(
        sidelined["id"], hq))["open_leads_count"] == 0

    stranded, stranded_meta = validate_paginated(
        api.list_leads(hq, status="UNROUTABLE"))
    assert_page_meta(stranded_meta, total_count=2, has_more=False)
    assert {row["id"] for row in stranded} == {on_probation["id"],
                                              unchartered["id"]}

    _rows, empty_meta = validate_paginated(
        api.list_leads(hq, territory_id=sidelined["id"]))
    assert_page_meta(empty_meta, total_count=0, has_more=False)


SIGN_OFF = "2026-08-20T09:30:00.000Z"


def _one_clean_job_and_one_doomed_job(api):
    """Two openings on one quote, each on its own received order and its own job.

    The square opening prices at 4960 and installs cleanly; the opening racked by
    half an inch prices at 7520 and is the one the installer refuses.
    """
    territory, designer, consultation = _appointment(api,
                                                     royalty_rate_pct=0.055,
                                                     liability_window="ROLLING_180D")
    vendor = onboard_vendor(api, base_lead_time_days=10,
                           motorization_extra_days=3, cutoff_hour_utc=15,
                           remake_policy="SHARED_50_50", concurrent_capacity=5,
                           supported_lift_systems=["CORDED"])
    assert read_designer(api, territory,
                         designer["id"])["remeasure_liability_score"] == 100

    square = record_opening(api, designer, consultation, label="Square one")
    racked = record_opening(api, designer, consultation, label="Racked one",
                            width_top_in=24.000, width_middle_in=24.500,
                            width_bottom_in=24.100, height_left_in=48.000,
                            height_center_in=48.100, height_right_in=48.050)
    assert_inches_equal(racked["out_of_square_in"], 0.500, "out_of_square_in")

    square = configure_opening(api, designer, square, fabric_code="LT-SHEER",
                               lift_system="CORDED")
    racked = configure_opening(api, designer, racked, fabric_code="CL-LINEN",
                               lift_system="CORDED")
    assert square["list_price_cents"] == 4960
    assert racked["list_price_cents"] == 7520

    quote = build_quote(api, designer, consultation)
    present_quote(api, designer, quote)
    quote = accept_quote(api, designer, quote)
    assert quote["subtotal_cents"] == 12480
    assert quote["install_fee_cents"] == 12500
    assert quote["recognized_net_sales_cents"] == 12480

    clean_order = place_order(api, territory, quote, [square["id"]], vendor)
    doomed_order = place_order(api, territory, quote, [racked["id"]], vendor)
    assert doomed_order["order_cost_cents"] == 3158
    for order in (clean_order, doomed_order):
        ship_order(api, vendor, order)
        receive_order(api, territory, order)

    clean_job = schedule_install(api, territory, clean_order, designer,
                                scheduled_start_at="2026-08-20T09:00:00.000Z",
                                scheduled_end_at="2026-08-20T11:00:00.000Z")
    doomed_job = schedule_install(api, territory, doomed_order, designer,
                                  scheduled_start_at="2026-08-20T11:00:00.000Z",
                                  scheduled_end_at="2026-08-20T13:00:00.000Z")
    set_clock(api, SIGN_OFF)
    return {
        "territory": territory, "designer": designer, "quote": quote,
        "square": square, "racked": racked, "doomed_order": doomed_order,
        "clean_job": clean_job, "doomed_job": doomed_job,
    }


def test_a_clean_install_is_clamped_at_the_base_score_but_still_offsets_a_later_exception(api):
    """The credit leaves no mark on a perfect record, yet it turns a later 78 into 81.

    "The raw score starts at a base of 100, subtracts 22 points for each counted
    measurer-liable exception, subtracts 9 points for each counted late sample return, and
    adds 3 points for each counted clean installation."

    "`remeasure_liability_score` is that raw figure clamped at both ends — never above the
    base of 100 and never below zero."

    "One measurer-liable exception alone therefore gives 100 minus 22, or 78, and suspends;
    the same exception with one prior clean install gives 81 and does not."

    "An out-of-square failure yields `MEASURER` when the opening is an `INSIDE` mount
    **and** its `out_of_square_in` is strictly greater than 0.375 inches, because an inside
    mount on a visibly racked opening was the measurer's call to refuse; otherwise — an
    outside mount, or a spread within tolerance — it yields `CUSTOMER`, an unforeseeable
    wall condition."

    Design: Corner/calculations/a_clean_install_is_clamped_at_the_base_score_but_still_offsets_a_later_exception
    """
    world = _one_clean_job_and_one_doomed_job(api)
    territory, designer = world["territory"], world["designer"]
    signed = validate_success(api.complete_install_job(
        world["clean_job"]["id"], designer_headers(designer["id"])))
    assert signed["install_status"] == "COMPLETED"

    # The credit is a stored count even where the clamp hides it: raw 103 reads 100.
    after_clean = read_designer(api, territory, designer["id"])
    assert after_clean["clean_install_count"] == 1
    assert after_clean["remeasure_liability_score"] == 100
    assert after_clean["status"] == "ACTIVE"

    refused = validate_success(api.raise_install_exception(
        world["doomed_job"]["id"],
        f.exception_payload(world["racked"]["id"], "OUT_OF_SQUARE"),
        designer_headers(designer["id"])))
    assert refused["liable_party"] == "MEASURER"
    assert refused["remeasure_charge_cents"] == 2632

    # 100 - 22 + 3: the same exception on a designer without the clean install is 78.
    after_exception = read_designer(api, territory, designer["id"])
    assert after_exception["remeasure_exception_count"] == 1
    assert after_exception["remeasure_liability_score"] == 81
    assert after_exception["status"] == "ACTIVE"

    counters = read_territory(api, territory)
    assert counters["net_sales_cents"] == 4960
    assert counters["royalty_accrued_cents"] == 273
    assert counters["remake_chargeback_cents"] == 5790

    rows, meta = validate_paginated(api.list_ledger_entries(
        territory["id"], franchisee_headers(territory["id"])))
    assert_page_meta(meta, total_count=4, has_more=False)
    assert [(row["entry_type"], row["amount_cents"]) for row in rows] == [
        ("NET_SALES_ROYALTY", 686),
        ("ROYALTY_REVERSAL", -413),
        ("REMEASURE_CHARGEBACK", 2632),
        ("REMAKE_CHARGEBACK", 3158),
    ]

    reordered = read_order(api, territory, world["doomed_order"]["id"])
    assert reordered["status"] == "PLACED"
    assert reordered["remake_count"] == 1
    assert reordered["vendor_absorbed_cents"] == 0
    assert reordered["territory_absorbed_cents"] == 3158
    assert reordered["customer_absorbed_cents"] == 0
    assert_remake_buckets_sum(reordered)

    assert read_opening(api, designer,
                        world["square"]["id"])["install_outcome"] == "INSTALLED"
    assert read_opening(
        api, designer, world["racked"]["id"])["install_outcome"] == "NOT_INSTALLED"

    # The finished job is not revisited by the later exception on its neighbour.
    untouched = read_install_job(api, designer, world["clean_job"]["id"])
    assert untouched["install_status"] == "COMPLETED"
    assert untouched["exception_reason"] == "NONE"
    assert untouched["liable_party"] == "NONE"
