"""Placement: the cutoff roll, the closed production window, and the ladder's tail."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_VENDOR_CAPACITY_EXCEEDED,
)
from test_helpers.assertions import (
    assert_date_string,
    assert_instant_equals,
    assert_page_meta,
)
from test_helpers.fixtures import (
    accept_quote,
    book_consultation,
    build_quote,
    charter_territory,
    configure_opening,
    hire_designer,
    intake_lead,
    onboard_vendor,
    place_order,
    present_quote,
    read_opening,
    read_quote,
    read_territory,
    record_opening,
    set_clock,
)
from test_helpers.test_users import franchisee_headers


def _two_openings_accepted(api, credit_limit_cents, vendor_kwargs,
                          accept_at, lift_system="CORDED", room_type="OFFICE",
                          child_occupied_dwelling=False, extra_vendor=None):
    """One accepted two-opening quote, plus one or two vendors to route it to."""
    territory = charter_territory(api, royalty_rate_pct=0.055,
                                 lead_capacity_per_week=5,
                                 credit_limit_cents=credit_limit_cents,
                                 liability_window="ROLLING_180D")
    designer = hire_designer(api, territory)
    primary = onboard_vendor(api, **vendor_kwargs)
    secondary = onboard_vendor(api, **extra_vendor) if extra_vendor else None
    lead = intake_lead(api, territory, customer_name="Ana Ruiz",
                       source="WEB_FORM",
                       requested_at="2026-08-01T08:00:00.000Z",
                       child_occupied_dwelling=child_occupied_dwelling)
    consultation = book_consultation(
        api, designer, lead,
        scheduled_start_at="2026-08-04T14:00:00.000Z",
        scheduled_end_at="2026-08-04T15:00:00.000Z")
    first = record_opening(api, designer, consultation, label="Hall north",
                          room_type=room_type, mount_type="INSIDE")
    second = record_opening(api, designer, consultation, label="Hall south",
                            room_type=room_type, mount_type="INSIDE")
    for opening in (first, second):
        configure_opening(api, designer, opening, fabric_code="LT-SHEER",
                          lift_system=lift_system, motorization_option="NONE")
    quote = build_quote(api, designer, consultation)
    set_clock(api, accept_at)
    present_quote(api, designer, quote)
    quote = accept_quote(api, designer, quote)
    return {"territory": territory, "designer": designer, "vendor": primary,
            "other_vendor": secondary, "quote": quote, "first": first,
            "second": second}


CUTOFF_VENDOR = {
    "base_lead_time_days": 10,
    "motorization_extra_days": 3,
    "cutoff_hour_utc": 15,
    "remake_policy": "SHARED_50_50",
    "concurrent_capacity": 5,
    "supported_lift_systems": ["CORDED", "CORDLESS"],
}


def test_one_millisecond_before_the_cutoff_keeps_the_placement_date(api):
    """Placed at 14:59:59.999Z against a cutoff of 15, the date does not roll.

    "First the cutoff roll: the hour component of the placement instant in UTC is
    compared against the vendor's `cutoff_hour_utc`, and when that hour is **strictly
    below** the cutoff the `effective_placement_date` is the UTC calendar date of the
    placement instant, otherwise it is the following calendar date."

    "Fourth, `promised_ship_date` is `effective_placement_date` advanced by
    `lead_time_days` calendar days."

    Design: Difficulty/boundary_precision_check/vendor_cutoff_hour_rolls_the_effective_date_on_one_millisecond
    """
    world = _two_openings_accepted(api, 2000000, CUTOFF_VENDOR,
                                  "2026-08-05T14:00:00.000Z")

    set_clock(api, "2026-08-05T14:59:59.999Z")
    order = place_order(api, world["territory"], world["quote"],
                        [world["first"]["id"]], world["vendor"])

    assert order["status"] == "PLACED"
    assert_instant_equals(order["placed_at"], "2026-08-05T14:59:59.999Z",
                          "placed_at")
    assert_date_string(order["effective_placement_date"],
                       "effective_placement_date")
    assert order["effective_placement_date"] == "2026-08-05"
    assert order["lead_time_days"] == 10
    assert order["promised_ship_date"] == "2026-08-15"
    assert order["order_cost_cents"] == 2083
    assert order["remake_count"] == 0


def test_the_cutoff_instant_itself_rolls_the_promised_date_by_a_day(api):
    """Placed at exactly 15:00:00.000Z, the same order ships a whole day later.

    "A vendor with a cutoff hour of 15 placed at 14:59:59.999Z keeps the same date;
    placed at 15:00:00.000Z it rolls to the next day."

    "The order's wholesale exposure, `order_cost_cents`, is 42 percent of the summed
    `list_price_cents` of the named openings, rounded half up to a whole cent **once**,
    over the summed retail figure."

    Design: Difficulty/boundary_precision_check/vendor_cutoff_hour_rolls_the_effective_date_on_one_millisecond
    """
    world = _two_openings_accepted(api, 2000000, CUTOFF_VENDOR,
                                  "2026-08-05T14:00:00.000Z")
    territory = world["territory"]

    set_clock(api, "2026-08-05T14:59:59.999Z")
    early = place_order(api, territory, world["quote"], [world["first"]["id"]],
                        world["vendor"])

    set_clock(api, "2026-08-05T15:00:00.000Z")
    late = place_order(api, territory, world["quote"], [world["second"]["id"]],
                       world["vendor"])

    assert_instant_equals(late["placed_at"], "2026-08-05T15:00:00.000Z",
                          "placed_at")
    assert late["effective_placement_date"] == "2026-08-06"
    assert late["lead_time_days"] == 10
    assert late["promised_ship_date"] == "2026-08-16"
    assert late["order_cost_cents"] == 2083

    # One millisecond of placement time, one whole day of promised ship date.
    assert late["lead_time_days"] == early["lead_time_days"]
    assert early["promised_ship_date"] == "2026-08-15"
    assert read_territory(api, territory)["open_order_exposure_cents"] == 4166


CAPACITY_ONE_VENDOR = {
    "base_lead_time_days": 10,
    "motorization_extra_days": 3,
    "cutoff_hour_utc": 15,
    "remake_policy": "SHARED_50_50",
    "concurrent_capacity": 1,
    "supported_lift_systems": ["CORDED", "CORDLESS"],
}


def _one_window_occupied(api):
    """A capacity-1 factory already holding the closed window 2026-08-05..2026-08-15."""
    world = _two_openings_accepted(api, 2000000, CAPACITY_ONE_VENDOR,
                                  "2026-08-05T09:00:00.000Z")
    world["order"] = place_order(api, world["territory"], world["quote"],
                                 [world["first"]["id"]], world["vendor"])
    return world


def test_a_single_shared_date_breaches_a_capacity_of_one(api):
    """The candidate's first loaded date is the occupant's last, and that is enough.

    "Because the interval is closed at both ends, two orders that merely touch on one
    shared date do collide on that date — a candidate whose `promised_ship_date` equals
    an existing order's `effective_placement_date` shares exactly one loaded date and
    counts against capacity there."

    "An order occupies its whole production window inclusively at both ends — from its
    `effective_placement_date` through its `promised_ship_date` — for as long as its
    `status` is `PLACED`, `SHIPPED` or `REMAKE_REQUESTED`; orders that have reached
    `RECEIVED` or `CANCELLED` release their slot."

    Design: Difficulty/resource_temporal_overlap/vendor_capacity_counts_closed_production_windows_that_share_a_single_date
    """
    world = _one_window_occupied(api)
    territory, quote = world["territory"], world["quote"]
    occupant = world["order"]

    assert occupant["status"] == "PLACED"
    assert occupant["effective_placement_date"] == "2026-08-05"
    assert occupant["promised_ship_date"] == "2026-08-15"

    set_clock(api, "2026-08-15T09:00:00.000Z")
    pinned_version = read_quote(api, territory, quote["id"])["version"]

    validate_error(
        api.create_vendor_order(
            f.vendor_order_payload(quote["id"], [world["second"]["id"]],
                                   pinned_version,
                                   preferred_vendor_id=world["vendor"]["id"]),
            franchisee_headers(territory["id"])),
        ERR_VENDOR_CAPACITY_EXCEEDED, 409)

    # The refusal wrote nothing at all, so the captured version is still current.
    assert read_quote(api, territory,
                      quote["id"])["version"] == pinned_version
    _rows, meta = validate_paginated(api.list_vendor_orders(
        franchisee_headers(territory["id"]), quote_id=quote["id"]))
    assert_page_meta(meta, total_count=1, has_more=False)


def test_windows_that_merely_abut_across_a_day_do_not_collide(api):
    """One day later the candidate's window starts after the occupant's ends.

    "For the candidate placement the service walks every calendar date in the
    candidate's own window, counts how many occupying orders of that vendor contain that
    date, and admits the placement only when the largest such count plus one is at most
    the vendor's `concurrent_capacity`."

    Design: Difficulty/resource_temporal_overlap/vendor_capacity_counts_closed_production_windows_that_share_a_single_date
    """
    world = _one_window_occupied(api)
    territory, quote = world["territory"], world["quote"]

    set_clock(api, "2026-08-15T09:00:00.000Z")
    pinned_version = read_quote(api, territory, quote["id"])["version"]
    validate_error(
        api.create_vendor_order(
            f.vendor_order_payload(quote["id"], [world["second"]["id"]],
                                   pinned_version,
                                   preferred_vendor_id=world["vendor"]["id"]),
            franchisee_headers(territory["id"])),
        ERR_VENDOR_CAPACITY_EXCEEDED, 409)

    set_clock(api, "2026-08-16T09:00:00.000Z")
    admitted = validate_success(
        api.create_vendor_order(
            f.vendor_order_payload(quote["id"], [world["second"]["id"]],
                                   pinned_version,
                                   preferred_vendor_id=world["vendor"]["id"]),
            franchisee_headers(territory["id"])), 201)

    assert admitted["effective_placement_date"] == "2026-08-16"
    assert admitted["promised_ship_date"] == "2026-08-26"
    assert admitted["lead_time_days"] == 10
    assert admitted["order_cost_cents"] == 2083
    assert admitted["status"] == "PLACED"

    assert read_territory(api, territory)["open_order_exposure_cents"] == 4166
    _rows, meta = validate_paginated(api.list_vendor_orders(
        franchisee_headers(territory["id"]), quote_id=quote["id"]))
    assert_page_meta(meta, total_count=2, has_more=False)


TIGHT_CREDIT_V1 = {
    "name": "Ridgeline Shade Works",
    "base_lead_time_days": 10,
    "motorization_extra_days": 3,
    "cutoff_hour_utc": 15,
    "remake_policy": "SHARED_50_50",
    "concurrent_capacity": 1,
    "supported_lift_systems": ["CORDED", "CORDLESS"],
}
TIGHT_CREDIT_V2 = dict(TIGHT_CREDIT_V1, name="Basin Mill Shades",
                       concurrent_capacity=5)


def _one_order_against_a_3000_cent_limit(api):
    """A 2839-cent order already outstanding against a credit limit of 3000 cents.

    A second order of the same size would occupy the same production window and would
    push exposure to 5678, so it breaches the capacity rule on the capacity-1 vendor
    and the fiscal rule on either.
    """
    world = _two_openings_accepted(api, 3000, TIGHT_CREDIT_V1,
                                  "2026-08-03T16:00:00.000Z",
                                  lift_system="CORDLESS",
                                  room_type="BEDROOM",
                                  child_occupied_dwelling=True,
                                  extra_vendor=TIGHT_CREDIT_V2)
    world["order"] = place_order(api, world["territory"], world["quote"],
                                 [world["first"]["id"]], world["vendor"])
    world["pinned_version"] = read_quote(
        api, world["territory"], world["quote"]["id"])["version"]
    return world


def test_capacity_outranks_credit_on_the_same_placement(api):
    """Both rules are broken and the temporal one is reported.

    "The territory's `open_order_exposure_cents` plus the new order's
    `order_cost_cents` must be at most its `credit_limit_cents`; a breach is
    `ERR_CREDIT_LIMIT_EXCEEDED`. It is evaluated after vendor eligibility and after
    capacity, so an order that would breach both capacity and credit reports the
    capacity error."

    Design: Difficulty/priority_pair_validation_conflict/vendor_capacity_conflict_outranks_credit_limit_on_the_same_placement
    """
    world = _one_order_against_a_3000_cent_limit(api)
    territory, quote = world["territory"], world["quote"]

    assert quote["subtotal_cents"] == 13520
    assert quote["install_fee_cents"] == 12500
    assert world["order"]["order_cost_cents"] == 2839
    assert world["order"]["effective_placement_date"] == "2026-08-04"
    assert world["order"]["promised_ship_date"] == "2026-08-14"
    assert read_territory(api, territory)["open_order_exposure_cents"] == 2839

    validate_error(
        api.create_vendor_order(
            f.vendor_order_payload(quote["id"], [world["second"]["id"]],
                                   world["pinned_version"],
                                   preferred_vendor_id=world["vendor"]["id"]),
            franchisee_headers(territory["id"])),
        ERR_VENDOR_CAPACITY_EXCEEDED, 409)


def test_the_fiscal_rule_surfaces_once_capacity_admits_the_window(api):
    """The identical body on a capacity-5 factory reaches the last check of all.

    "The last check of all is fiscal."

    "When `preferred_vendor_id` **is** supplied the selector does not run at all: that
    one vendor is checked against the first three eligibility conditions, failing with
    `ERR_NO_ELIGIBLE_VENDOR`, and separately against the capacity condition, failing
    with `ERR_VENDOR_CAPACITY_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/vendor_capacity_conflict_outranks_credit_limit_on_the_same_placement
    """
    world = _one_order_against_a_3000_cent_limit(api)
    territory, quote, designer = world["territory"], world["quote"], world["designer"]
    owner = franchisee_headers(territory["id"])

    validate_error(
        api.create_vendor_order(
            f.vendor_order_payload(quote["id"], [world["second"]["id"]],
                                   world["pinned_version"],
                                   preferred_vendor_id=world["other_vendor"]["id"]),
            owner),
        ERR_CREDIT_LIMIT_EXCEEDED, 409)

    _rows, meta = validate_paginated(
        api.list_vendor_orders(owner, quote_id=quote["id"]))
    assert_page_meta(meta, total_count=1, has_more=False)

    counters = read_territory(api, territory)
    assert counters["open_order_exposure_cents"] == 2839
    assert counters["royalty_accrued_cents"] == 744

    assert read_quote(api, territory,
                      quote["id"])["version"] == world["pinned_version"]

    stranded = read_opening(api, designer, world["second"]["id"])
    assert stranded["measure_status"] == "QUOTED"
    assert stranded["install_outcome"] == "PENDING"
