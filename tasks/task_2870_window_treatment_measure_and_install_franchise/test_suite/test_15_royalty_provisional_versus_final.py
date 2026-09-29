"""Royalty accrual read twice on one quote: provisionally, then against reality."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers.assertions import (
    assert_instant_equals,
    assert_ledger_entry,
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
    receive_order,
    record_opening,
    schedule_install,
    set_clock,
    ship_order,
)
from test_helpers.test_users import designer_headers, franchisee_headers

SIGN_OFF_CLOCK = "2026-08-18T09:30:00.000Z"


def _two_openings_one_installed(api):
    """Two identical 4960-cent openings on one quote, each on its own order.

    Only the first order is shipped and received, and only that order gets an
    install job. Its `motorized_channel_count` is zero, so commissioning is
    `NOT_REQUIRED` and sign-off is unblocked.
    """
    territory = charter_territory(api, postal_codes=["30301", "30302"],
                                 royalty_rate_pct=0.055,
                                 lead_capacity_per_week=5,
                                 credit_limit_cents=2000000,
                                 liability_window="ROLLING_180D")
    designer = hire_designer(api, territory, certifications=["MOTORIZATION"])
    vendor = onboard_vendor(api, base_lead_time_days=10,
                            motorization_extra_days=3, cutoff_hour_utc=15,
                            remake_policy="SHARED_50_50",
                            concurrent_capacity=2,
                            supported_lift_systems=["CORDED", "CORDLESS",
                                                    "MOTORIZED"],
                            supported_hub_platforms=["MATTER"])
    lead = intake_lead(api, territory, customer_name="Ana Ruiz",
                       source="WEB_FORM",
                       requested_at="2026-08-03T00:00:00.000Z",
                       child_occupied_dwelling=False)
    consultation = book_consultation(api, designer, lead)
    first = record_opening(api, designer, consultation,
                           label="Living room west", room_type="LIVING_ROOM")
    second = record_opening(api, designer, consultation,
                            label="Office south", room_type="OFFICE")
    first = configure_opening(api, designer, first, fabric_code="LT-SHEER",
                              lift_system="CORDED", motorization_option="NONE")
    second = configure_opening(api, designer, second, fabric_code="LT-SHEER",
                               lift_system="CORDED", motorization_option="NONE")
    quote = build_quote(api, designer, consultation)
    present_quote(api, designer, quote)
    quote = accept_quote(api, designer, quote)
    first_order = place_order(api, territory, quote, [first["id"]], vendor)
    second_order = place_order(api, territory, quote, [second["id"]], vendor)
    ship_order(api, vendor, first_order)
    set_clock(api, "2026-08-14T09:00:00.000Z")
    receive_order(api, territory, first_order)
    job = schedule_install(api, territory, first_order, designer,
                           scheduled_start_at="2026-08-18T09:00:00.000Z",
                           scheduled_end_at="2026-08-18T11:00:00.000Z")
    set_clock(api, SIGN_OFF_CLOCK)
    return {
        "territory": territory, "designer": designer, "vendor": vendor,
        "consultation": consultation, "first": first, "second": second,
        "quote": quote, "first_order": first_order,
        "second_order": second_order, "job": job,
    }


def test_the_provisional_variant_accrues_on_every_attached_opening(api):
    """Acceptance recognizes both openings because no install outcome is known yet.

    "Acceptance stamps `accepted_at` from the logical clock and runs the
    **provisional** royalty recognition: the recognized basis is the quote's
    `net_sales_cents` — that is, the subtotal less the discount, over every attached
    opening whatever its install outcome, because install outcomes are not yet known
    and are deliberately ignored."

    Design: Difficulty/dual_variant_calc/royalty_provisional_versus_final_diverges_when_one_of_two_orders_installs
    """
    world = _two_openings_one_installed(api)
    territory, quote = world["territory"], world["quote"]

    assert quote["status"] == "ACCEPTED"
    assert quote["subtotal_cents"] == 9920
    assert quote["install_fee_cents"] == 12500
    assert quote["pre_discount_total_cents"] == 22420
    assert quote["discount_pct"] == 0
    assert quote["net_sales_cents"] == 9920
    assert quote["recognized_net_sales_cents"] == 9920
    assert quote["credited_net_sales_cents"] == 0

    rows, meta = validate_paginated(api.list_ledger_entries(
        territory["id"], franchisee_headers(territory["id"]),
        entry_type="NET_SALES_ROYALTY"))
    assert_page_meta(meta, total_count=1, has_more=False)
    assert_ledger_entry(rows[0], "NET_SALES_ROYALTY", 546, 9920,
                        "quote_accepted", "QUOTE",
                        source_entity_id=quote["id"],
                        territory_id=territory["id"])


def test_sign_off_re_derives_royalty_from_the_installed_opening_alone(api):
    """The final variant recognizes 4960 and reverses the 273-cent difference.

    "The royalty delta is the royalty on the final basis minus the royalty on the
    quote's current `recognized_net_sales_cents`, each figure computed independently
    as its basis multiplied by the territory's `royalty_rate_pct` and rounded half
    up."

    "When the delta is positive a ledger row of type `NET_SALES_ROYALTY` is appended
    for it; when negative, a row of type `ROYALTY_REVERSAL` carrying the negative
    amount; and when the delta is exactly zero **no ledger row is written at all**."

    Design: Difficulty/dual_variant_calc/royalty_provisional_versus_final_diverges_when_one_of_two_orders_installs
    """
    world = _two_openings_one_installed(api)
    territory, designer = world["territory"], world["designer"]
    quote, job = world["quote"], world["job"]
    owner = franchisee_headers(territory["id"])

    assert job["motorized_channel_count"] == 0
    assert job["commissioning_status"] == "NOT_REQUIRED"

    signed = validate_success(
        api.complete_install_job(job["id"], designer_headers(designer["id"])))
    assert signed["install_status"] == "COMPLETED"

    assert read_opening(api, designer,
                        world["first"]["id"])["install_outcome"] == "INSTALLED"
    assert read_opening(api, designer,
                        world["second"]["id"])["install_outcome"] == "PENDING"

    restated = read_quote(api, territory, quote["id"])
    assert restated["net_sales_cents"] == 9920
    assert restated["recognized_net_sales_cents"] == 4960

    counters = read_territory(api, territory)
    assert counters["net_sales_cents"] == 4960
    assert counters["royalty_accrued_cents"] == 273

    accrued, accrued_meta = validate_paginated(api.list_ledger_entries(
        territory["id"], owner, entry_type="NET_SALES_ROYALTY"))
    assert_page_meta(accrued_meta, total_count=1, has_more=False)
    assert accrued[0]["amount_cents"] == 546
    assert accrued[0]["basis_cents"] == 9920

    reversals, reversal_meta = validate_paginated(api.list_ledger_entries(
        territory["id"], owner, entry_type="ROYALTY_REVERSAL"))
    assert_page_meta(reversal_meta, total_count=1, has_more=False)
    assert reversals[0]["amount_cents"] == -273
    assert reversals[0]["memo"] == "install_trueup"
    assert reversals[0]["source_entity_type"] == "INSTALL_JOB"
    assert reversals[0]["source_entity_id"] == job["id"]
    assert_instant_equals(reversals[0]["occurred_at"], SIGN_OFF_CLOCK,
                          "occurred_at")

    # The territory's accrual is the sum of its rows, never an independent figure.
    assert (accrued[0]["amount_cents"] + reversals[0]["amount_cents"]
            == counters["royalty_accrued_cents"])
