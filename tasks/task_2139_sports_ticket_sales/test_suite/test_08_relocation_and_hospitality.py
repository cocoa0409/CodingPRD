"""Seat relocation pricing and the hospitality suite calendar."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_hospitality_package,
    book_package,
    cancel_order,
    confirm_order,
    create_approved_order,
    create_confirmed_order,
    create_hospitality_package_payload,
    pay_order,
    read_account,
    read_game,
    read_order,
    read_season,
    read_seat,
    relocate_order,
    run_ops,
    set_clock,
    setup_hospitality_world,
    setup_selling_world,
    validate_error,
    validate_paginated,
    validate_success,
    OPS_HEADERS,
)


def test_partner_discount_tier_is_keyed_on_the_gross_fee():
    """PRD 3.9: "First, `gross_fee_cents` is the sum of the suite base fee for the game's `opponent_tier` — 25,000 cents for `MARQUEE`, 18,000 for `PREMIUM`, 14,000 for `STANDARD`, 11,000 for `VALUE` — and a food-and-beverage charge of 4,500 cents per head, that sum then multiplied by the `headcount`. Second, `partner_discount_pct` is looked up on `gross_fee_cents` alone: a gross fee of 1,000,000 cents or more earns 0.10, a gross fee of 500,000 cents or more but below 1,000,000 earns 0.05, and anything below 500,000 earns 0.00."
    PRD 3.9: "Fifth, `total_due_cents` is the discounted amount plus `service_fee_cents` — and that fifth figure never feeds back into the second step."

    Design: Difficulty/combinatorial_formula/hospitality_partner_discount_tier_reads_gross_never_total_due
    """
    world = setup_hospitality_world()

    package = validate_success(
        api_client.create_hospitality_package(
            create_hospitality_package_payload(
                world["game"]["id"], world["account_id"], suite_code="SUITE-1",
                headcount=21,
                service_window_start_utc="2026-10-10T18:00:00Z",
                service_window_end_utc="2026-10-10T21:00:00Z",
            ),
            world["rep_headers"],
        ),
        201,
    )

    assert_hospitality_package(package)
    assert package["gross_fee_cents"] == 472500
    assert package["partner_discount_pct"] == 0
    assert package["service_fee_cents"] == 37800
    assert package["total_due_cents"] == 510300
    assert package["total_due_cents"] != 484785, (
        "484,785 is what keying the tier on total_due_cents would produce"
    )


def test_new_package_is_held_and_reserves_the_game_headcount():
    """PRD 3.9: "A new package is minted in `HELD` status, the game's `hospitality_booked_headcount` grows by the booked `headcount`, and the game's attendance analytics are recomputed."
    PRD 3.9: "Fourth, `service_fee_cents` is 8 percent of that discounted amount, rounded half-up."

    Design: Difficulty/combinatorial_formula/hospitality_partner_discount_tier_reads_gross_never_total_due
    """
    world = setup_hospitality_world()

    package = book_package(
        world["game"]["id"], world["account_id"], world["rep_headers"],
        suite_code="SUITE-1", headcount=21,
        service_window_start_utc="2026-10-10T18:00:00Z",
        service_window_end_utc="2026-10-10T21:00:00Z",
    )

    assert package["package_status"] == "HELD"
    assert package["service_fee_cents"] == 37800
    assert read_game(world["game"]["id"])["hospitality_booked_headcount"] == 21


def test_suite_window_with_a_zero_gap_is_rejected():
    """PRD 3.9: "The **suite calendar** is per game and suite: for the same combination of `game_id` and `suite_code`, the requested closed window must be separated from every existing `HELD` or `CONFIRMED` package's window by at least thirty minutes of turnover time. A gap of exactly thirty minutes is accepted; anything less — including two windows that merely touch at an endpoint, a gap of zero — is `ERR_SUITE_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/suite_service_windows_reject_zero_gap_and_accept_a_thirty_minute_turnover
    """
    world = setup_hospitality_world()
    book_package(
        world["game"]["id"], world["account_id"], world["rep_headers"],
        suite_code="SUITE-1", headcount=10,
        service_window_start_utc="2026-10-10T18:00:00Z",
        service_window_end_utc="2026-10-10T21:00:00Z",
    )

    response = api_client.create_hospitality_package(
        create_hospitality_package_payload(
            world["game"]["id"], world["account_id"], suite_code="SUITE-1", headcount=10,
            service_window_start_utc="2026-10-10T21:00:00Z",
            service_window_end_utc="2026-10-10T23:00:00Z",
        ),
        world["rep_headers"],
    )

    validate_error(response, ApiErrorId.ERR_SUITE_WINDOW_CONFLICT.value, 409)
    assert read_game(world["game"]["id"])["hospitality_booked_headcount"] == 10


def test_suite_window_with_a_thirty_minute_turnover_is_accepted():
    """PRD 3.9: "The **suite calendar** is per game and suite: for the same combination of `game_id` and `suite_code`, the requested closed window must be separated from every existing `HELD` or `CONFIRMED` package's window by at least thirty minutes of turnover time. A gap of exactly thirty minutes is accepted; anything less — including two windows that merely touch at an endpoint, a gap of zero — is `ERR_SUITE_WINDOW_CONFLICT`."
    PRD 3.9: "A new package is minted in `HELD` status, the game's `hospitality_booked_headcount` grows by the booked `headcount`, and the game's attendance analytics are recomputed."

    Design: Difficulty/resource_temporal_overlap/suite_service_windows_reject_zero_gap_and_accept_a_thirty_minute_turnover
    """
    world = setup_hospitality_world()
    book_package(
        world["game"]["id"], world["account_id"], world["rep_headers"],
        suite_code="SUITE-1", headcount=10,
        service_window_start_utc="2026-10-10T18:00:00Z",
        service_window_end_utc="2026-10-10T21:00:00Z",
    )

    response = api_client.create_hospitality_package(
        create_hospitality_package_payload(
            world["game"]["id"], world["account_id"], suite_code="SUITE-1", headcount=10,
            service_window_start_utc="2026-10-10T21:30:00Z",
            service_window_end_utc="2026-10-10T23:30:00Z",
        ),
        world["rep_headers"],
    )
    second = validate_success(response, 201)

    assert second["package_status"] == "HELD"
    assert second["total_due_cents"] == 243000
    assert read_game(world["game"]["id"])["hospitality_booked_headcount"] == 20
    _, meta = validate_paginated(
        api_client.list_hospitality_packages(
            OPS_HEADERS, params={"game_id": world["game"]["id"]}
        )
    )
    assert meta["total_count"] == 2


def test_hospitality_booking_over_the_game_headcount_cap_is_rejected():
    """PRD 3.9: "Two capacity rules gate the booking. The **headcount cap** is per game: the game's already-booked `hospitality_booked_headcount` plus the requested `headcount` must not exceed the game's `hospitality_headcount_cap`, and an overflow is `ERR_HOSPITALITY_CAPACITY_EXCEEDED`."
    PRD 3.9: "The `hospitality_booked_headcount` figure itself is the sum of `headcount` over that game's packages whose `package_status` is `HELD`, `CONFIRMED` or `SETTLED`."

    Design: Corner/validations/val_hospitality_headcount_over_the_game_cap_rejected
    """
    world = setup_hospitality_world(headcount_cap=20)
    book_package(
        world["game"]["id"], world["account_id"], world["rep_headers"],
        suite_code="SUITE-1", headcount=15,
        service_window_start_utc="2026-10-10T18:00:00Z",
        service_window_end_utc="2026-10-10T21:00:00Z",
    )

    response = api_client.create_hospitality_package(
        create_hospitality_package_payload(
            world["game"]["id"], world["account_id"], suite_code="SUITE-2", headcount=10,
            service_window_start_utc="2026-10-10T18:00:00Z",
            service_window_end_utc="2026-10-10T21:00:00Z",
        ),
        world["rep_headers"],
    )

    error = validate_error(
        response, ApiErrorId.ERR_HOSPITALITY_CAPACITY_EXCEEDED.value, 422
    )
    assert error["error_id"] != ApiErrorId.ERR_SUITE_WINDOW_CONFLICT.value
    assert read_game(world["game"]["id"])["hospitality_booked_headcount"] == 15
    _, meta = validate_paginated(
        api_client.list_hospitality_packages(
            OPS_HEADERS, params={"game_id": world["game"]["id"]}
        )
    )
    assert meta["total_count"] == 1


def test_hospitality_booking_after_the_game_is_played_is_rejected():
    """PRD 3.9: "Bookings are permitted while the season is `RENEWAL_OPEN`, `GENERAL_ONSALE` or `IN_SEASON`, and only against a game whose `game_status` is still `SCHEDULED`."
    PRD 2.9: "Gate scans, hospitality bookings and transfer requests all require the target game to be `SCHEDULED`, otherwise `ERR_GAME_ALREADY_PLAYED`."

    Design: Corner/errors/err_hospitality_booking_after_the_game_is_played_rejected
    """
    world = setup_hospitality_world()
    set_clock("2026-10-11T00:00:00Z")
    run_ops(world["season_id"])
    assert read_game(world["game"]["id"])["game_status"] == "PLAYED"
    assert read_season(world["season_id"])["season_status"] == "IN_SEASON"

    response = api_client.create_hospitality_package(
        create_hospitality_package_payload(
            world["game"]["id"], world["account_id"], suite_code="SUITE-1", headcount=10,
            service_window_start_utc="2026-10-11T18:00:00Z",
            service_window_end_utc="2026-10-11T21:00:00Z",
        ),
        world["rep_headers"],
    )

    validate_error(response, ApiErrorId.ERR_GAME_ALREADY_PLAYED.value, 409)
    _, meta = validate_paginated(
        api_client.list_hospitality_packages(
            OPS_HEADERS, params={"game_id": world["game"]["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_relocation_upgrade_consumes_loyalty_credit_before_charging_the_rest():
    """PRD 3.8: "The remaining games are the plan's `game_ids` filtered to those whose `game_date_utc` is strictly after the current instant. The old total is the sum, over those remaining games and over the order's current `seat_ids`, of the line price for each pair; the new total is the same sum taken over the same remaining games and over the requested `new_seat_ids`. The delta is the new total minus the old total, and three branches follow from its sign."
    PRD 3.8: "**When the delta is positive — an upgrade** — the account's stored credit absorbs part of the increase. The applied credit is the smallest of three figures: the account's `loyalty_credit_cents`, a per-relocation cap of 10,000 cents, and the delta itself. A relocation fee of 2,500 cents is added when — and only when — the season's `season_status` is `IN_SEASON`; in every other season status the fee is 0. The amount charged is the delta, minus the applied credit, plus that fee. The applied credit is subtracted from the account's `loyalty_credit_cents` and the charge is added to the order's `final_total_cents`."
    PRD 3.8: "In every branch the season's `contracted_revenue_cents` changes by exactly the same signed amount as the order's `final_total_cents` did, keeping the ledger invariant of §2.10 intact."

    Design: Corner/calculations/calc_relocation_upgrade_consumes_loyalty_credit_then_charges_the_rest
    """
    world = setup_selling_world(
        seat_ranges=[
            {"section_code": "310", "row_label": "C", "price_zone": "ZONE_D",
             "seat_number_from": 1, "seat_number_to": 2},
            {"section_code": "104", "row_label": "A", "price_zone": "ZONE_C",
             "seat_number_from": 1, "seat_number_to": 2},
        ]
    )
    zone_d = [s["id"] for s in world["seat_groups"][0]]
    zone_c = [s["id"] for s in world["seat_groups"][1]]

    credit_order = create_confirmed_order(
        world["account_id"], world["plan_id"], [zone_d[1]], world["rep_headers"],
        installment_count=1,
    )
    pay_order(credit_order["id"], world["rep_headers"], 2000)
    cancel_order(
        credit_order["id"], world["rep_headers"], cancel_reason="moved to a new seat set"
    )
    assert read_account(world["account_id"])["loyalty_credit_cents"] == 2000

    order = create_confirmed_order(
        world["account_id"], world["plan_id"], [zone_d[0]], world["rep_headers"],
        installment_count=1,
    )
    assert order["final_total_cents"] == 5942

    relocated = relocate_order(
        order["id"], [zone_c[0]], order["version"], world["rep_headers"]
    )

    assert relocated["final_total_cents"] == 7680, (
        "delta 3,738 less the 2,000 credit, with no in-season relocation fee"
    )
    assert read_account(world["account_id"])["loyalty_credit_cents"] == 0
    old_seat = read_seat(zone_d[0])
    assert old_seat["seat_status"] == "AVAILABLE"
    assert old_seat["assigned_account_id"] is None
    new_seat = read_seat(zone_c[0])
    assert new_seat["seat_status"] == "ASSIGNED"
    assert new_seat["assigned_account_id"] == world["account_id"]
    season = read_season(world["season_id"])
    assert season["contracted_revenue_cents"] == 7680
    assert season["assigned_seat_count"] == 1


def test_relocation_with_a_version_predating_the_payment_is_rejected():
    """PRD 2.8: "**Order relocation** requires a non-optional `expected_order_version` field in its request body, carrying the client's last observed `version` of the target `PlanOrder`. If it does not equal the order's stored `version` — because an earlier relocation, a payment, or a cascade has already rewritten the order's `seat_ids` or `final_total_cents` — the relocation is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412) and neither the seat set nor the price is touched."

    Design: Corner/cross_cutting_layers/occ_relocate_with_a_version_predating_the_payment_rejected
    """
    world = setup_selling_world(
        seat_ranges=[
            {"section_code": "310", "row_label": "C", "price_zone": "ZONE_D",
             "seat_number_from": 1, "seat_number_to": 2}
        ]
    )
    order = create_confirmed_order(
        world["account_id"], world["plan_id"], [world["seat_ids"][0]],
        world["rep_headers"], installment_count=1,
    )
    confirm_time_version = order["version"]
    pay_order(order["id"], world["account_headers"], 1000)

    response = api_client.relocate_plan_order(
        order["id"],
        {
            "new_seat_ids": [world["seat_ids"][1]],
            "expected_order_version": confirm_time_version,
        },
        world["rep_headers"],
    )

    validate_error(response, ApiErrorId.ERR_STALE_ORDER_VERSION.value, 412)
    unchanged = read_order(order["id"])
    assert unchanged["final_total_cents"] == 5942
    assert unchanged["amount_paid_cents"] == 1000
    assert read_seat(world["seat_ids"][0])["seat_status"] == "ASSIGNED"
    assert read_seat(world["seat_ids"][1])["seat_status"] == "AVAILABLE"
