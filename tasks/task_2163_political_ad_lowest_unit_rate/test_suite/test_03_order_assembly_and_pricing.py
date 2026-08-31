"""Opening an order, adding spots, and the volume-tier repricing that follows."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_spot,
    assert_order,
    assert_order_money_invariants,
    assert_spot,
    assert_unit_equivalent_normalisation,
    create_order,
    create_spot_payload,
    hourly_spots,
    make_advertiser_agent_headers,
    read_order,
    setup_issue_order,
    validate_error,
    validate_paginated,
    validate_success,
)

MORNING_CLASS = {
    "class_code": "RC-AM",
    "daypart": "MORNING",
    "preemptible": True,
    "preemption_priority": 3,
    "posted_rate_cents": 12345,
}


def test_new_order_starts_in_draft_and_unbilled_on_both_dimensions(api):
    """PRD §3.4: "The order is created in lifecycle state `DRAFT` and settlement state
    `UNBILLED`, with `spot_count`, `gross_charge_cents`, `agency_commission_cents`,
    `net_due_cents`, `rebate_total_cents`, `paid_cents` and `refunded_cents` all at
    zero, and with `accepted_at`, `accepted_by_user_id`, `payment_due_at`,
    `first_air_at` and `rejection_reason` all null."
    PRD §3.5: "Only when all four branches are passed does the status read
    `CONFORMING`."

    Design: Corner/state_machines/new_order_starts_in_draft_and_unbilled_on_both_dimensions
    """
    built = setup_issue_order(
        call_sign="WINI-TV",
        market_code="DMA-105",
        station_overrides={"licensee_name": "Initial State Media"},
        classification=None,
    )
    order = built["order"]
    assert_order(order)

    assert order["status"] == "DRAFT"
    assert order["payment_status"] == "UNBILLED"
    assert order["spot_count"] == 0
    assert order["gross_charge_cents"] == 0
    assert order["net_due_cents"] == 0
    assert order["paid_cents"] == 0
    assert order["refunded_cents"] == 0
    assert order["accepted_at"] is None
    assert order["payment_due_at"] is None
    assert order["disclosure_status"] == "CONFORMING"

    advertiser = built["advertiser"]
    assert advertiser["status"] == "SUBMITTED"
    assert advertiser["review_round"] == 0


def test_spot_with_a_forty_five_second_duration_is_rejected(api):
    """PRD §3.4: "Each spot names its `air_date` as a `YYYY-MM-DD` calendar date, its
    `start_offset_seconds` — the number of seconds after midnight of the local
    broadcast day at which the spot begins, an integer within the inclusive range of 0
    through 86399 — its `duration_seconds`, which must be either 30 or 60, and a
    `program_code` naming the programme adjacency it runs in."
    PRD §2.9: "a `duration_seconds` that is neither 30 nor 60" ... "All of these carry
    `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/spot_creation_with_duration_45_rejected_as_invalid_request
    """
    built = setup_issue_order(
        call_sign="WTYP-TV",
        market_code="DMA-103",
        station_overrides={"licensee_name": "Type Guard Media"},
        classification=None,
    )
    order, advertiser = built["order"], built["advertiser"]
    headers = make_advertiser_agent_headers(advertiser["id"])

    validate_error(
        api.add_spot(order["id"], create_spot_payload(duration_seconds=45), headers),
        ApiErrorId.ERR_INVALID_REQUEST,
    )

    assert read_order(order["id"], advertiser["id"])["spot_count"] == 0
    rows, meta = validate_paginated(
        api.list_spots(headers, params={"order_id": order["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_sixty_second_spot_normalises_to_a_thirty_second_unit_rate(api):
    """PRD §2.5: "A rate class publishes a `posted_rate_cents` figure that is always the
    rate for one thirty-second unit; a sixty-second spot is therefore priced at twice
    the thirty-second product before any other adjustment, and any per-spot charge can
    be normalised back to a comparable thirty-second figure."
    PRD §2.5: "That normalisation is stored on each spot as
    `unit_equivalent_rate_cents`, computed by taking the spot's `charged_rate_cents`,
    multiplying by thirty, dividing by the spot's `duration_seconds`, and rounding half
    up."

    Design: Corner/calculations/sixty_second_spot_normalises_to_a_thirty_second_unit_equivalent_rate
    """
    built = setup_issue_order(
        call_sign="WUNQ-TV",
        market_code="DMA-119",
        station_overrides={"licensee_name": "Unit Equivalent Media", "daily_political_seconds_cap": 300},
        classification=None,
    )
    order, advertiser = built["order"], built["advertiser"]

    spot = validate_success(
        api.add_spot(
            order["id"],
            create_spot_payload(duration_seconds=60, program_code="EN-60"),
            make_advertiser_agent_headers(advertiser["id"]),
        ),
        201,
    )
    assert_spot(spot)
    assert spot["charged_rate_cents"] == 200000, "a 60-second spot costs twice the unit rate"
    assert spot["unit_equivalent_rate_cents"] == 100000
    assert spot["luc_capped"] is False
    assert_unit_equivalent_normalisation(spot)

    refreshed = read_order(order["id"], advertiser["id"])
    assert refreshed["gross_charge_cents"] == 200000
    assert refreshed["spot_count"] == 1


def test_fifth_spot_reprices_every_spot_at_the_five_percent_tier(api):
    """PRD §3.4: "Once a spot survives all three checks, **the whole order is repriced
    from scratch**."
    PRD §3.4: "The discount is then read from the tier the recounted `spot_count` falls
    into: a `spot_count` of 1 through 4 earns no discount at all; 5 through 9 earns 5
    percent; 10 through 19 earns 12.5 percent; and 20 or more earns 20 percent."
    PRD §3.4: "For each such spot, take the rate class's `posted_rate_cents`, multiply
    by the daypart multiplier for that class's `daypart`, multiply by the spot's
    `duration_seconds` divided by thirty, and multiply by one minus the reselected
    discount fraction."

    Design: Difficulty/combinatorial_formula/gross_charge_rounds_per_spot_then_sums_at_reselected_tier
    """
    built = setup_issue_order(
        call_sign="WMRN-TV",
        market_code="DMA-311",
        station_overrides={"licensee_name": "Morning Line Media LLC", "daily_political_seconds_cap": 300},
        rate_class_overrides=MORNING_CLASS,
        classification=None,
        spots=hourly_spots(4, prefix="AM"),
    )
    order, advertiser = built["order"], built["advertiser"]
    first_spot = built["spots"][0]

    at_four = read_order(order["id"], advertiser["id"])
    assert at_four["spot_count"] == 4
    assert at_four["gross_charge_cents"] == 29628, "four spots earn no volume discount"

    fifth = validate_success(
        api.add_spot(
            order["id"],
            create_spot_payload(air_date="2026-08-20", start_offset_seconds=14400, program_code="AM-5"),
            make_advertiser_agent_headers(advertiser["id"]),
        ),
        201,
    )
    assert fifth["charged_rate_cents"] == 7037, (
        "the fifth spot selects the 5 percent tier: 12345 * 0.60 * 0.95 rounds half up to 7037"
    )

    refreshed_first = validate_success(
        api.get_spot(first_spot["id"], make_advertiser_agent_headers(advertiser["id"]))
    )
    assert refreshed_first["charged_rate_cents"] == 7037, (
        "spots already on the order feel the tier move too"
    )

    refreshed = read_order(order["id"], advertiser["id"])
    assert refreshed["spot_count"] == 5
    assert refreshed["gross_charge_cents"] == 35185


def test_gross_charge_rounds_each_spot_before_summing_them(api):
    """PRD §3.4: "**Round that single product half up to whole cents once, and store it
    as the spot's `charged_rate_cents`.**"
    PRD §3.4: "The order's `gross_charge_cents` is the sum of the per-spot
    `charged_rate_cents` values **after** each has been individually rounded. The order
    of operations here is part of the contract: round once per spot, then add the
    rounded figures. Adding the unrounded per-spot products and rounding the total once
    is a different — and wrong — answer whenever a per-spot product carries a fractional
    cent."

    Design: Difficulty/combinatorial_formula/gross_charge_rounds_per_spot_then_sums_at_reselected_tier
    """
    built = setup_issue_order(
        call_sign="WRND-TV",
        market_code="DMA-312",
        station_overrides={"licensee_name": "Rounding Line Media LLC", "daily_political_seconds_cap": 300},
        rate_class_overrides=MORNING_CLASS,
        classification=None,
        spots=hourly_spots(5, prefix="AM"),
    )
    order, advertiser = built["order"], built["advertiser"]

    for spot in built["spots"]:
        refreshed = validate_success(
            api.get_spot(spot["id"], make_advertiser_agent_headers(advertiser["id"]))
        )
        assert refreshed["charged_rate_cents"] == 7037, (
            "each spot rounds 7036.65 half up to 7037 on its own"
        )

    final_order = read_order(order["id"], advertiser["id"])
    assert final_order["gross_charge_cents"] == 35185, (
        "round-per-spot-then-sum yields 35185; summing first and rounding once yields 35183"
    )
    assert final_order["gross_charge_cents"] != 35183
    assert final_order["net_due_cents"] == 35185
    assert final_order["agency_commission_cents"] == 0
    assert_order_money_invariants(final_order)


def test_agency_commission_tier_is_selected_from_the_gross_charge(api):
    """PRD §3.4: "When it is true, the commission percentage is selected **from
    `gross_charge_cents` alone** — never from `net_due_cents`, and never reselected
    after the commission is added. An order whose gross is below 50000 cents earns no
    commission; a gross from 50000 through 249999 cents earns 2 percent; a gross of
    250000 cents or more earns 3.5 percent. The commission is that percentage of the
    gross, rounded half up to whole cents. The order's `net_due_cents` is then simply
    `gross_charge_cents` plus `agency_commission_cents`."

    Design: Difficulty/combinatorial_formula/agency_commission_tier_keyed_on_gross_not_on_net_due
    """
    built = setup_issue_order(
        call_sign="WCOM-TV",
        market_code="DMA-221",
        station_overrides={"licensee_name": "Commission Broadcast Group", "daily_political_seconds_cap": 300},
        rate_class_overrides={
            "class_code": "RC-EN",
            "daypart": "EARLY_NEWS",
            "preemptible": False,
            "preemption_priority": 0,
            "posted_rate_cents": 61500,
        },
        order_overrides={"agency_placed": True},
        classification=None,
        spots=hourly_spots(3),
    )
    order, advertiser = built["order"], built["advertiser"]

    add_spot(
        order["id"],
        advertiser["id"],
        air_date="2026-08-20",
        start_offset_seconds=10800,
        program_code="EN-4",
    )

    refreshed = read_order(order["id"], advertiser["id"])
    assert refreshed["spot_count"] == 4
    assert refreshed["gross_charge_cents"] == 246000
    assert refreshed["agency_commission_cents"] == 4920, (
        "the 2 percent band is chosen from gross 246000, not from net_due 250920"
    )
    assert refreshed["net_due_cents"] == 250920
    assert_order_money_invariants(refreshed)


def test_agency_commission_is_zero_when_the_order_is_not_agency_placed(api):
    """PRD §3.4: "When `agency_placed` is false, `agency_commission_cents` is zero."
    PRD §3.4: "The order's `net_due_cents` is then simply `gross_charge_cents` plus
    `agency_commission_cents`."

    Design: Difficulty/combinatorial_formula/agency_commission_tier_keyed_on_gross_not_on_net_due
    """
    built = setup_issue_order(
        call_sign="WDIR-TV",
        market_code="DMA-222",
        station_overrides={"licensee_name": "Direct Buy Broadcast Group", "daily_political_seconds_cap": 300},
        rate_class_overrides={
            "class_code": "RC-EN",
            "daypart": "EARLY_NEWS",
            "preemptible": False,
            "preemption_priority": 0,
            "posted_rate_cents": 61500,
        },
        order_overrides={"agency_placed": False},
        classification=None,
        spots=hourly_spots(4),
    )
    refreshed = read_order(built["order"]["id"], built["advertiser"]["id"])

    assert refreshed["agency_placed"] is False
    assert refreshed["spot_count"] == 4
    assert refreshed["gross_charge_cents"] == 246000
    assert refreshed["agency_commission_cents"] == 0
    assert refreshed["net_due_cents"] == 246000
    assert_order_money_invariants(refreshed)


def test_tenth_spot_moves_the_order_into_the_twelve_and_a_half_percent_tier(api):
    """PRD §3.4: "The discount is then read from the tier the recounted `spot_count`
    falls into: a `spot_count` of 1 through 4 earns no discount at all; 5 through 9
    earns 5 percent; 10 through 19 earns 12.5 percent; and 20 or more earns 20 percent."
    PRD §3.4: "If that sum plus the new spot's own `duration_seconds` would exceed the
    station's `daily_political_seconds_cap`, the placement is rejected with
    `ERR_STATION_DAILY_CAP_EXCEEDED` (HTTP 409). Landing exactly on the cap is
    permitted; exceeding it by one second is not."

    Design: Corner/calculations/tenth_spot_moves_the_order_into_the_12_5_percent_tier_and_fills_the_daily_cap_exactly
    """
    built = setup_issue_order(
        call_sign="WTIR-TV",
        market_code="DMA-121",
        station_overrides={"licensee_name": "Tier Boundary Media", "daily_political_seconds_cap": 300},
        rate_class_overrides=MORNING_CLASS,
        classification=None,
        spots=hourly_spots(9, prefix="AM"),
    )
    order, advertiser = built["order"], built["advertiser"]
    headers = make_advertiser_agent_headers(advertiser["id"])

    tenth = validate_success(
        api.add_spot(
            order["id"],
            create_spot_payload(air_date="2026-08-20", start_offset_seconds=32400, program_code="AM-10"),
            headers,
        ),
        201,
    )
    assert tenth["charged_rate_cents"] == 6481, (
        "12345 * 0.60 * 0.875 is 6481.125, which rounds half up to 6481"
    )

    for spot in (built["spots"][0], built["spots"][8]):
        refreshed = validate_success(api.get_spot(spot["id"], headers))
        assert refreshed["charged_rate_cents"] == 6481

    final_order = read_order(order["id"], advertiser["id"])
    assert final_order["spot_count"] == 10
    assert final_order["gross_charge_cents"] == 64810, (
        "ten spots rounded individually sum to 64810, not the 64811 a sum-then-round gives"
    )
    assert final_order["net_due_cents"] == 64810


def test_spot_that_would_exceed_the_daily_cap_is_refused_but_the_next_day_is_free(api):
    """PRD §3.4: "Sum the `duration_seconds` of every `SCHEDULED` or `AIRED` spot that
    falls on the same `air_date` and whose owning order belongs to the same station and
    is in any of `DRAFT`, `SUBMITTED`, `ACCEPTED`, `SUSPENDED`, `RUNNING` or
    `COMPLETED`."
    PRD §3.4: "If that sum plus the new spot's own `duration_seconds` would exceed the
    station's `daily_political_seconds_cap`, the placement is rejected with
    `ERR_STATION_DAILY_CAP_EXCEEDED` (HTTP 409). Landing exactly on the cap is
    permitted; exceeding it by one second is not."

    Design: Corner/calculations/eleventh_spot_rejected_because_the_station_daily_cap_is_already_exactly_full
    """
    built = setup_issue_order(
        call_sign="WCAP-TV",
        market_code="DMA-122",
        station_overrides={"licensee_name": "Capacity Broadcasting", "daily_political_seconds_cap": 90},
        rate_class_overrides=MORNING_CLASS,
        classification=None,
        spots=hourly_spots(3, prefix="AM"),
    )
    order, advertiser = built["order"], built["advertiser"]
    headers = make_advertiser_agent_headers(advertiser["id"])

    validate_error(
        api.add_spot(
            order["id"],
            create_spot_payload(air_date="2026-08-20", start_offset_seconds=10800, program_code="AM-4"),
            headers,
        ),
        ApiErrorId.ERR_STATION_DAILY_CAP_EXCEEDED,
    )

    next_day = validate_success(
        api.add_spot(
            order["id"],
            create_spot_payload(air_date="2026-08-21", start_offset_seconds=10800, program_code="AM-5"),
            headers,
        ),
        201,
    )
    assert next_day["air_date"] == "2026-08-21", "the cap is scoped per air_date"
    assert read_order(order["id"], advertiser["id"])["spot_count"] == 4


def test_spot_with_an_air_date_before_the_clock_date_is_refused(api):
    """PRD §3.4: "An `air_date` earlier than the date portion of the logical clock is
    refused outright with `ERR_SPOT_AIR_DATE_IN_PAST` (HTTP 422); today's date is
    acceptable."

    Design: Corner/validations/spot_with_air_date_before_the_clock_date_rejected_as_in_past
    """
    built = setup_issue_order(
        call_sign="WPST-TV",
        market_code="DMA-123",
        station_overrides={"licensee_name": "Past Date Media", "daily_political_seconds_cap": 300},
        classification=None,
        clock="2026-08-05T09:00:00Z",
    )
    order, advertiser = built["order"], built["advertiser"]
    headers = make_advertiser_agent_headers(advertiser["id"])

    validate_error(
        api.add_spot(
            order["id"],
            create_spot_payload(air_date="2026-08-04", program_code="EN-PAST"),
            headers,
        ),
        ApiErrorId.ERR_SPOT_AIR_DATE_IN_PAST,
    )

    today = validate_success(
        api.add_spot(
            order["id"],
            create_spot_payload(air_date="2026-08-05", program_code="EN-TODAY"),
            headers,
        ),
        201,
    )
    assert today["air_date"] == "2026-08-05"
    assert read_order(order["id"], advertiser["id"])["spot_count"] == 1


def test_spot_listing_filters_by_owning_order_and_by_rate_class(api):
    """PRD §4: "List scheduled spots, optionally filtered by order, rate class, status
    or air date"
    PRD §2.3: "Collections are always ordered by `created_at` ascending before the page
    window is applied, regardless of any filters supplied."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` and `has_more`; `total_count` counts the rows matching the filters
    before pagination, and `has_more` is true when rows remain beyond the current page."

    Design: Corner/endpoints/spots_filtered_list_returns_only_the_named_orders_rows
    """
    built = setup_issue_order(
        call_sign="WFLT-TV",
        market_code="DMA-137",
        station_overrides={"licensee_name": "Filter Media Group", "daily_political_seconds_cap": 300},
        classification=None,
        spots=hourly_spots(2, prefix="EN-A"),
    )
    station, rate_class = built["station"], built["rate_class"]
    advertiser, order_a = built["advertiser"], built["order"]
    headers = make_advertiser_agent_headers(advertiser["id"])

    order_b = create_order(
        station["id"],
        advertiser["id"],
        rate_class["id"],
        sponsorship_disclosure_text="PAID FOR BY Empire Growth Fund",
    )
    spot_b = add_spot(
        order_b["id"],
        advertiser["id"],
        air_date="2026-08-20",
        start_offset_seconds=7200,
        program_code="EN-B1",
    )

    by_order, meta_order = validate_paginated(
        api.list_spots(headers, params={"order_id": order_a["id"]})
    )
    assert meta_order["total_count"] == 2
    assert [row["id"] for row in by_order] == [
        built["spots"][0]["id"],
        built["spots"][1]["id"],
    ]
    assert spot_b["id"] not in [row["id"] for row in by_order]

    by_class, meta_class = validate_paginated(
        api.list_spots(
            headers, params={"rate_class_id": rate_class["id"], "air_date": "2026-08-20"}
        )
    )
    assert meta_class["total_count"] == 3
    assert by_class[0]["id"] == built["spots"][0]["id"]
