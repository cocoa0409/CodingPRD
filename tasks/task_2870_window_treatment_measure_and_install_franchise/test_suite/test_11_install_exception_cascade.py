"""The install exception: one call, four hops, five entity types."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers.assertions import (
    assert_instant_equals,
    assert_ledger_entry,
    assert_page_meta,
    assert_remake_buckets_sum,
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
    read_designer,
    read_install_job,
    read_opening,
    read_order,
    read_quote,
    read_territory,
    receive_order,
    record_opening,
    schedule_install,
    set_clock,
    ship_order,
)
from test_helpers.test_users import designer_headers, franchisee_headers

EXCEPTION_CLOCK = "2026-08-20T09:30:00.000Z"


def _racked_opening_fixture(api):
    """One received order on a visibly racked inside-mount opening, ready to install.

    The measured spread is 0.500 inch, the ordered blind is 23.500 by 47.750 and it
    lists at 4960 cents, so the order cost is 2083 cents and the provisional royalty
    273 cents. The manufacturer is a `FULL_VENDOR_90D` partner on purpose.
    """
    territory = charter_territory(api, royalty_rate_pct=0.055,
                                 lead_capacity_per_week=5,
                                 credit_limit_cents=2000000,
                                 liability_window="ROLLING_180D")
    designer = hire_designer(api, territory)
    vendor = onboard_vendor(api, base_lead_time_days=10,
                            motorization_extra_days=3, cutoff_hour_utc=15,
                            remake_policy="FULL_VENDOR_90D",
                            concurrent_capacity=2,
                            supported_lift_systems=["CORDED", "CORDLESS",
                                                    "MOTORIZED"])
    lead = intake_lead(api, territory, customer_name="Ana Ruiz",
                       source="WEB_FORM",
                       requested_at="2026-08-03T00:00:00.000Z",
                       child_occupied_dwelling=False)
    consultation = book_consultation(api, designer, lead)
    opening = record_opening(api, designer, consultation,
                             label="Racked bay window", room_type="LIVING_ROOM",
                             mount_type="INSIDE",
                             width_top_in=24.000, width_middle_in=24.500,
                             width_bottom_in=24.100,
                             height_left_in=48.000, height_center_in=48.100,
                             height_right_in=48.050, depth_in=3.000)
    opening = configure_opening(api, designer, opening, fabric_code="LT-SHEER",
                                lift_system="CORDED", motorization_option="NONE")
    quote = build_quote(api, designer, consultation)
    set_clock(api, "2026-08-03T16:00:00.000Z")
    present_quote(api, designer, quote)
    quote = accept_quote(api, designer, quote)
    order = place_order(api, territory, quote, [opening["id"]], vendor)
    ship_order(api, vendor, order)
    set_clock(api, "2026-08-17T09:00:00.000Z")
    receive_order(api, territory, order)

    # A second appointment far in the future for a different homeowner — the
    # collateral row the suspension cascade has to cancel.
    later_lead = intake_lead(api, territory, customer_name="Bo Chen",
                             source="REFERRAL",
                             requested_at="2026-09-01T00:00:00.000Z")
    future_consultation = book_consultation(
        api, designer, later_lead,
        scheduled_start_at="2026-09-10T14:00:00.000Z",
        scheduled_end_at="2026-09-10T15:00:00.000Z",
    )
    job = schedule_install(api, territory, order, designer,
                           scheduled_start_at="2026-08-20T09:00:00.000Z",
                           scheduled_end_at="2026-08-20T11:00:00.000Z")
    set_clock(api, EXCEPTION_CLOCK)
    return {
        "territory": territory, "designer": designer, "vendor": vendor,
        "consultation": consultation, "opening": opening, "quote": quote,
        "order": order, "job": job,
        "future_consultation": future_consultation,
    }


def test_an_out_of_square_inside_mount_charges_the_measurer_and_freezes_the_job(api):
    """A 0.500 inch spread on an inside mount is the measurer's charge, hop one included.

    "An out-of-square failure yields `MEASURER` when the opening is an `INSIDE`
    mount **and** its `out_of_square_in` is strictly greater than 0.375 inches,
    because an inside mount on a visibly racked opening was the measurer's call to
    refuse; otherwise — an outside mount, or a spread within tolerance — it yields
    `CUSTOMER`, an unforeseeable wall condition."

    "**Hop one**: the named opening moves `QUOTED → REMEASURE_REQUIRED` and its
    `install_outcome` becomes `NOT_INSTALLED`."

    Design: Difficulty/transitive_cascade/install_exception_cascades_four_hops_from_opening_to_designer_suspension
    """
    world = _racked_opening_fixture(api)
    designer, opening, job = world["designer"], world["opening"], world["job"]

    raised = validate_success(api.raise_install_exception(
        job["id"], {"opening_id": opening["id"],
                    "exception_reason": "OUT_OF_SQUARE"},
        designer_headers(designer["id"])))

    assert raised["install_status"] == "EXCEPTION_RAISED"
    assert raised["exception_reason"] == "OUT_OF_SQUARE"
    assert raised["exception_opening_id"] == opening["id"]
    assert_instant_equals(raised["exception_raised_at"], EXCEPTION_CLOCK,
                          "exception_raised_at")
    assert raised["liable_party"] == "MEASURER"
    assert raised["remeasure_charge_cents"] == 1736

    # Hop one lands on the opening itself.
    superseded = read_opening(api, designer, opening["id"])
    assert superseded["out_of_square_in"] == 0.500
    assert superseded["measure_status"] == "REMEASURE_REQUIRED"
    assert superseded["install_outcome"] == "NOT_INSTALLED"

    frozen = read_install_job(api, designer, job["id"])
    assert frozen["install_status"] == "EXCEPTION_RAISED"
    assert frozen["completed_at"] is None


def test_the_exception_re_places_the_order_and_ignores_the_vendors_remake_policy(api):
    """Hop two re-places the order on the measurer's account, not the mill's.

    "When the origin is the install-exception cascade of §3.9, the vendor's
    `remake_policy` is **ignored entirely** and the targets are driven by the liable
    party recorded on the driving install job."

    "A liable party of `MEASURER` makes the territory's target the whole cost and
    the vendor's target zero."

    "**Hop two**: that `NOT_INSTALLED` outcome drives the order carrying the opening
    through `RECEIVED → REMAKE_REQUESTED → PLACED`, with the waterfall of §3.8 run
    on the install-exception origin and the lead time re-computed with the four-day
    expedite."

    Design: Difficulty/transitive_cascade/install_exception_cascades_four_hops_from_opening_to_designer_suspension
    """
    world = _racked_opening_fixture(api)
    territory, designer = world["territory"], world["designer"]
    opening, job, order = world["opening"], world["job"], world["order"]

    assert order["effective_placement_date"] == "2026-08-04"
    assert order["promised_ship_date"] == "2026-08-14"
    assert order["order_cost_cents"] == 2083

    validate_success(api.raise_install_exception(
        job["id"], {"opening_id": opening["id"],
                    "exception_reason": "OUT_OF_SQUARE"},
        designer_headers(designer["id"])))

    reopened = read_order(api, territory, order["id"])
    assert reopened["status"] == "PLACED"
    assert reopened["remake_count"] == 1
    assert reopened["credit_scope"] == "REPLACEMENT"
    assert reopened["lead_time_days"] == 6
    assert reopened["effective_placement_date"] == "2026-08-20"
    assert reopened["promised_ship_date"] == "2026-08-26"
    assert reopened["received_at"] is None

    assert reopened["remake_cost_cents"] == 2083
    assert reopened["vendor_absorbed_cents"] == 0
    assert reopened["territory_absorbed_cents"] == 2083
    assert reopened["customer_absorbed_cents"] == 0
    assert_remake_buckets_sum(reopened)


def test_the_chargebacks_suspend_the_measurer_and_cancel_only_future_appointments(api):
    """Hops three and four: two chargeback rows, a score of 78, and one cancellation.

    "The raw score starts at a base of 100, subtracts 22 points for each counted
    measurer-liable exception, subtracts 9 points for each counted late sample
    return, and adds 3 points for each counted clean installation."

    "**Hop four**: a recomputed score strictly below the suspension threshold drives
    the designer `ACTIVE → SUSPENDED`, which cancels that designer's other future
    consultations and install jobs."

    "Every consultation of that designer that is still `SCHEDULED` and whose
    `scheduled_start_at` is at or after the logical clock moves `SCHEDULED →
    CANCELLED`, and every install job of that designer that is still `SCHEDULED` and
    whose `scheduled_start_at` is at or after the logical clock moves
    `install_status` `SCHEDULED → CANCELLED`."

    Design: Difficulty/transitive_cascade/install_exception_cascades_four_hops_from_opening_to_designer_suspension
    """
    world = _racked_opening_fixture(api)
    territory, designer = world["territory"], world["designer"]
    opening, job = world["opening"], world["job"]
    owner = franchisee_headers(territory["id"])

    before = read_designer(api, territory, designer["id"])
    assert before["status"] == "ACTIVE"
    assert before["remeasure_liability_score"] == 100
    assert before["remeasure_exception_count"] == 0

    validate_success(api.raise_install_exception(
        job["id"], {"opening_id": opening["id"],
                    "exception_reason": "OUT_OF_SQUARE"},
        designer_headers(designer["id"])))

    # Hop three — the money lands on the franchise account as two rows.
    charge_rows, charge_meta = validate_paginated(api.list_ledger_entries(
        territory["id"], owner, entry_type="REMEASURE_CHARGEBACK"))
    assert_page_meta(charge_meta, total_count=1, has_more=False)
    assert_ledger_entry(charge_rows[0], "REMEASURE_CHARGEBACK", 1736, 4960,
                        "remeasure_chargeback", "INSTALL_JOB",
                        source_entity_id=job["id"],
                        territory_id=territory["id"],
                        occurred_at=EXCEPTION_CLOCK)

    remake_rows, remake_meta = validate_paginated(api.list_ledger_entries(
        territory["id"], owner, entry_type="REMAKE_CHARGEBACK"))
    assert_page_meta(remake_meta, total_count=1, has_more=False)
    assert_ledger_entry(remake_rows[0], "REMAKE_CHARGEBACK", 2083, 2083,
                        "remake_replacement", "VENDOR_ORDER",
                        source_entity_id=world["order"]["id"],
                        territory_id=territory["id"])

    counters = read_territory(api, territory)
    assert counters["remake_chargeback_cents"] == 3819

    # Hop four — the score drops through the threshold and the flag sticks.
    after = read_designer(api, territory, designer["id"])
    assert after["remeasure_exception_count"] == 1
    assert after["remeasure_liability_score"] == 78
    assert after["status"] == "SUSPENDED"

    cancelled = validate_success(
        api.get_consultation(world["future_consultation"]["id"], owner))
    assert cancelled["status"] == "CANCELLED"

    untouched = validate_success(
        api.get_consultation(world["consultation"]["id"], owner))
    assert untouched["status"] == "SCHEDULED"

    # Nothing installed, so the final royalty variant never ran.
    assert counters["royalty_accrued_cents"] == 273
    assert counters["net_sales_cents"] == 4960
    assert read_quote(api, territory,
                      world["quote"]["id"])["recognized_net_sales_cents"] == 4960
