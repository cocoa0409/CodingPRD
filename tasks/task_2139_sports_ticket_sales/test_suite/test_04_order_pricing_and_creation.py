"""Seat-game line pricing, the pinned order assembly and order-creation gates."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_plan_order,
    create_account_with_rep,
    create_confirmed_order,
    create_game,
    create_order,
    create_plan,
    create_plan_order_payload,
    create_published_plan,
    create_rep,
    create_season,
    create_seats_payload,
    mint_seats,
    open_renewal,
    read_order,
    read_season,
    read_seat,
    setup_dual_variant_world,
    setup_four_seat_zone_c_world,
    setup_selling_world,
    submit_order,
    confirm_order,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    OPS_HEADERS,
)



def test_order_quote_prices_every_game_in_the_plan():
    """PRD 3.4: "The **quoted** variant prices *every* game listed in the plan's `game_ids`, regardless of each game's `game_date_utc` or `game_status`, and freezes the result in the order's `quoted_total_cents` at creation time."
    PRD 3.4: "Fourth, a tenure credit is computed as the account's `tenure_years` multiplied by 500 cents, capped at 5,000 cents — that is, the credit is whichever is smaller of the cap and the per-year product, so a fifteen-year account and a ten-year account both earn the same 5,000-cent credit."

    Design: Difficulty/dual_variant_calc/order_total_quoted_vs_final_diverges_once_a_game_is_behind_the_clock
    """
    world = setup_dual_variant_world()

    order = create_order(
        world["account_id"], world["plan_id"], world["seat_ids"], world["rep_headers"]
    )

    assert_plan_order(order)
    assert order["quoted_total_cents"] == 26644, (
        "one ZONE_B seat over a MARQUEE/WEEKEND/85 opener and a STANDARD/WEEKDAY/50 "
        "closer, less a four-year tenure credit, plus the six percent service fee"
    )
    assert order["final_total_cents"] == 0, "the final figure is only written at confirm"


def test_final_total_drops_games_already_behind_the_clock():
    """PRD 3.4: "The **final** variant prices only those games in the plan whose `game_date_utc` is strictly after the current instant — a game whose date has already arrived is dropped from the priced set, pro-rating the plan — and re-reads the season's `dynamic_pricing_mode` at that moment."
    PRD 3.6: "`final_total_cents` is written from the **final** pricing variant of §3.4, evaluated against the season's `dynamic_pricing_mode` as read at the start of this request."
    PRD 2.10: "The ledger obeys a standing invariant: at all times it equals the sum of `final_total_cents` over every plan order whose `order_status` is `CONFIRMED`, plus the sum of `total_due_cents` over every hospitality package whose `package_status` is either `CONFIRMED` or `SETTLED`."

    Design: Difficulty/dual_variant_calc/order_total_quoted_vs_final_diverges_once_a_game_is_behind_the_clock
    """
    world = setup_dual_variant_world()
    order = create_order(
        world["account_id"], world["plan_id"], world["seat_ids"], world["rep_headers"]
    )
    submit_order(order["id"], world["rep_headers"])
    set_clock("2026-10-15T00:00:00Z")

    confirmed = confirm_order(order["id"], world["rep_headers"], installment_count=1)

    assert confirmed["order_status"] == "CONFIRMED"
    assert confirmed["quoted_total_cents"] == 26644
    assert confirmed["final_total_cents"] == 6360, (
        "the MARQUEE opener is behind the clock, so only the STANDARD closer is priced"
    )
    assert confirmed["quoted_total_cents"] != confirmed["final_total_cents"]
    assert read_season(world["season_id"])["contracted_revenue_cents"] == 6360


def test_subtotal_rounds_each_seat_game_line_before_summing():
    """PRD 3.4: "First, each individual seat-game line is priced and rounded to whole cents, and only then are the rounded lines summed: the subtotal is the sum, over every included game and over every seat in `seat_ids`, of the rounded line price for that pair. Summing unrounded products and rounding once at the end is explicitly not the rule and produces different cents on fractional lines."
    PRD 3.4: "Second, a volume discount fraction is looked up on the number of seats on the order — 0.00 for 1 to 3 seats, 0.03 for 4 to 9 seats, 0.07 for 10 to 19 seats, and 0.12 for 20 seats or more — and the subtotal is multiplied by one minus that fraction, the result rounded half-up."

    Design: Difficulty/combinatorial_formula/order_subtotal_rounds_every_seat_game_line_before_summing
    """
    world = setup_four_seat_zone_c_world()

    order = create_order(
        world["account_id"], world["plan_id"], world["seat_ids"], world["rep_headers"]
    )

    assert order["quoted_total_cents"] == 38430, (
        "four 9,343.75-cent lines round to 9,344 each before they are summed"
    )
    assert order["quoted_total_cents"] != 38429, (
        "38,429 is what summing the raw products and rounding once would produce"
    )


def test_order_creation_mints_order_holds_and_leaves_the_order_in_draft():
    """PRD 3.4: "Creating an order also reserves the inventory. The order is minted with `order_status` `DRAFT` and `payment_status` `NOT_STARTED`, `final_total_cents` and `amount_paid_cents` at 0, an empty `installments` array, and null `installment_count`, `submitted_by_user_id`, `reviewed_by_user_id` and `cancelled_reason`."
    PRD 2.7: "`available_seat_count`, `held_seat_count` and `assigned_seat_count` are the numbers of those seats whose recomputed `seat_status` is `AVAILABLE`, `HELD` and `ASSIGNED` respectively."

    Design: Difficulty/combinatorial_formula/order_subtotal_rounds_every_seat_game_line_before_summing
    """
    world = setup_four_seat_zone_c_world()

    order = create_order(
        world["account_id"], world["plan_id"], world["seat_ids"], world["rep_headers"]
    )

    assert order["order_status"] == "DRAFT"
    assert order["payment_status"] == "NOT_STARTED"
    assert order["final_total_cents"] == 0
    assert order["amount_paid_cents"] == 0
    assert order["installments"] == []
    assert order["submitted_by_user_id"] is None
    assert order["reviewed_by_user_id"] is None
    assert order["cancelled_reason"] is None
    season = read_season(world["season_id"])
    assert season["held_seat_count"] == 4
    assert season["available_seat_count"] == 0


def _flat_zone_d_world():
    """Eight ZONE_D seats against a STANDARD/WEEKDAY/50 game: every line is 3,000."""
    return setup_selling_world(
        games=[
            {
                "opponent_code": "MID",
                "opponent_tier": "STANDARD",
                "day_bucket": "WEEKDAY",
                "demand_index": 50,
            }
        ],
        seat_ranges=[
            {"section_code": "310", "row_label": "C", "price_zone": "ZONE_D",
             "seat_number_from": 1, "seat_number_to": 8}
        ],
        plan={"min_seats": 1, "max_seats": 8},
        account={"account_type": "GROUP"},
    )


def test_three_seat_order_takes_no_volume_discount():
    """PRD 3.4: "Second, a volume discount fraction is looked up on the number of seats on the order — 0.00 for 1 to 3 seats, 0.03 for 4 to 9 seats, 0.07 for 10 to 19 seats, and 0.12 for 20 seats or more — and the subtotal is multiplied by one minus that fraction, the result rounded half-up."
    PRD 3.4: "Sixth, a service fee of 6 percent of the net amount is computed and rounded half-up. The order total is the net amount plus that service fee."

    Design: Difficulty/boundary_precision_check/volume_discount_tier_flips_exactly_at_the_fourth_seat
    """
    world = _flat_zone_d_world()

    order = create_order(
        world["account_id"], world["plan_id"], world["seat_ids"][:3], world["rep_headers"]
    )

    assert order["quoted_total_cents"] == 9540, "three 3,000-cent lines at the 0.00 tier"
    assert order["quoted_total_cents"] != 9254, (
        "9,254 is what a 0.03 tier applied at three seats would produce"
    )


def test_fourth_seat_is_the_first_to_earn_the_volume_discount():
    """PRD 3.4: "Second, a volume discount fraction is looked up on the number of seats on the order — 0.00 for 1 to 3 seats, 0.03 for 4 to 9 seats, 0.07 for 10 to 19 seats, and 0.12 for 20 seats or more — and the subtotal is multiplied by one minus that fraction, the result rounded half-up."
    PRD 3.4: "Its size must fall inside the plan's `min_seats` and `max_seats` bounds, inclusive at both ends, or the request is `ERR_SEAT_COUNT_OUT_OF_RANGE`."

    Design: Difficulty/boundary_precision_check/volume_discount_tier_flips_exactly_at_the_fourth_seat
    """
    world = _flat_zone_d_world()
    create_order(
        world["account_id"], world["plan_id"], world["seat_ids"][:3], world["rep_headers"]
    )

    four_seat_order = create_order(
        world["account_id"], world["plan_id"], world["seat_ids"][3:7], world["rep_headers"]
    )

    assert four_seat_order["quoted_total_cents"] == 12338, (
        "four 3,000-cent lines at the 0.03 tier"
    )
    season = read_season(world["season_id"])
    assert season["held_seat_count"] == 7
    assert season["available_seat_count"] == 1


def test_demand_band_boundary_sits_between_index_fifty_nine_and_sixty():
    """PRD 3.4: "While the season is `AGGRESSIVE`, a `demand_index` of 80 or more selects 1.30, a `demand_index` of 60 or more but below 80 selects 1.15, a `demand_index` of 40 or more but below 60 selects 1.00, and anything below 40 selects 0.90."
    PRD 3.4: "Because the boundaries are inclusive, a `demand_index` of exactly 60 sits in the 1.15 band under `AGGRESSIVE` while a `demand_index` of 59 sits in the 1.00 band."

    Design: Corner/calculations/calc_demand_multiplier_tier_switches_between_index_59_and_60
    """
    world = setup_selling_world(
        season={"total_home_games": 2},
        games=[
            {"opponent_code": "LOW", "opponent_tier": "STANDARD", "day_bucket": "WEEKDAY",
             "demand_index": 59, "game_date_utc": "2026-10-10T23:00:00Z"},
            {"opponent_code": "HIGH", "opponent_tier": "STANDARD", "day_bucket": "WEEKDAY",
             "demand_index": 60, "game_date_utc": "2026-10-20T23:00:00Z"},
        ],
        seat_ranges=[
            {"section_code": "310", "row_label": "C", "price_zone": "ZONE_D",
             "seat_number_from": 1, "seat_number_to": 1}
        ],
    )

    order = create_order(
        world["account_id"], world["plan_id"], world["seat_ids"], world["rep_headers"]
    )

    assert order["quoted_total_cents"] == 6837, (
        "the 59-index line prices 3,000 and the 60-index line prices 3,450"
    )
    assert order["quoted_total_cents"] != 6360, (
        "6,360 is what two 1.00-band games would produce"
    )
    assert read_season(world["season_id"])["held_seat_count"] == 1


def test_client_supplied_identity_and_status_on_order_creation_are_ignored():
    """PRD 2.4: "Every persisted resource carries a server-minted `id`: a UUID string with no type prefix. Clients never supply an `id`, and the server never derives one from business data."
    PRD 3.4: "The order is minted with `order_status` `DRAFT` and `payment_status` `NOT_STARTED`, `final_total_cents` and `amount_paid_cents` at 0, an empty `installments` array, and null `installment_count`, `submitted_by_user_id`, `reviewed_by_user_id` and `cancelled_reason`."

    Design: Corner/entities/e_plan_order_system_fields_input_ignored
    """
    world = setup_selling_world()
    payload = create_plan_order_payload(
        world["account_id"], world["plan_id"], [world["seat_ids"][0]]
    )
    payload.update(
        {
            "id": "99999999-8888-4777-8666-555555555555",
            "order_status": "CONFIRMED",
            "quoted_total_cents": 1,
        }
    )

    order = validate_success(
        api_client.create_plan_order(payload, world["rep_headers"]), 201
    )

    assert order["id"] != "99999999-8888-4777-8666-555555555555"
    assert order["order_status"] == "DRAFT"
    assert order["quoted_total_cents"] == 9905
    assert order["final_total_cents"] == 0
    assert order["version"] == 1


def test_order_below_the_plan_minimum_seat_count_is_rejected():
    """PRD 3.4: "Three structural rules govern the seat set. Its size must fall inside the plan's `min_seats` and `max_seats` bounds, inclusive at both ends, or the request is `ERR_SEAT_COUNT_OUT_OF_RANGE`."

    Design: Corner/validations/val_order_below_plan_minimum_seat_count_rejected
    """
    world = setup_selling_world(
        seat_ranges=[
            {"section_code": "104", "row_label": "A", "price_zone": "ZONE_C",
             "seat_number_from": 1, "seat_number_to": 4}
        ],
        plan={"min_seats": 2, "max_seats": 4},
    )

    response = api_client.create_plan_order(
        create_plan_order_payload(
            world["account_id"], world["plan_id"], [world["seat_ids"][0]]
        ),
        world["rep_headers"],
    )

    validate_error(response, ApiErrorId.ERR_SEAT_COUNT_OUT_OF_RANGE.value, 422)
    season = read_season(world["season_id"])
    assert season["available_seat_count"] == 4
    assert season["held_seat_count"] == 0
    _, meta = validate_paginated(
        api_client.list_plan_orders(
            OPS_HEADERS, params={"account_id": world["account_id"]}
        )
    )
    assert meta["total_count"] == 0


def test_order_mixing_two_price_zones_is_rejected():
    """PRD 3.4: "And every seat in the set must share a single `price_zone` — a mixed-zone request is `ERR_ZONE_MISMATCH`."
    PRD 2.9: "**Single-zone rule** — `ERR_ZONE_MISMATCH` (422), guarding order creation and relocation."

    Design: Corner/validations/val_order_mixing_two_price_zones_rejected
    """
    world = setup_selling_world(
        seat_ranges=[
            {"section_code": "104", "row_label": "A", "price_zone": "ZONE_C",
             "seat_number_from": 1, "seat_number_to": 2},
            {"section_code": "310", "row_label": "C", "price_zone": "ZONE_D",
             "seat_number_from": 1, "seat_number_to": 2},
        ]
    )
    zone_c_seat = world["seat_groups"][0][0]
    zone_d_seat = world["seat_groups"][1][0]

    response = api_client.create_plan_order(
        create_plan_order_payload(
            world["account_id"], world["plan_id"], [zone_c_seat["id"], zone_d_seat["id"]]
        ),
        world["rep_headers"],
    )

    validate_error(response, ApiErrorId.ERR_ZONE_MISMATCH.value, 422)
    assert read_season(world["season_id"])["held_seat_count"] == 0


def test_discount_above_the_rep_ceiling_is_rejected():
    """PRD 3.4: "The discount is a fraction rather than a percentage — it defaults to 0 and may not exceed 0.25, with anything above that ceiling refused as `ERR_DISCOUNT_LIMIT_EXCEEDED`."

    Design: Corner/validations/val_discount_above_the_rep_cap_rejected
    """
    world = setup_selling_world()

    response = api_client.create_plan_order(
        create_plan_order_payload(
            world["account_id"], world["plan_id"], [world["seat_ids"][0]],
            discount_pct=0.30,
        ),
        world["rep_headers"],
    )

    validate_error(response, ApiErrorId.ERR_DISCOUNT_LIMIT_EXCEEDED.value, 422)
    _, meta = validate_paginated(
        api_client.list_plan_orders(
            OPS_HEADERS, params={"account_id": world["account_id"]}
        )
    )
    assert meta["total_count"] == 0


def test_order_naming_a_seat_from_another_season_is_rejected():
    """PRD 3.4: "Every seat must belong to the plan's own season, or the request is `ERR_SEAT_SEASON_MISMATCH`."
    PRD 2.9: "**Seat-to-season referential integrity.** Every seat referenced by an order or a relocation belongs to the plan's season — otherwise `ERR_SEAT_SEASON_MISMATCH` (422)."

    Design: Corner/validations/val_seat_belonging_to_another_season_rejected
    """
    world = setup_selling_world()
    other_season = create_season(code="2027-28", year=2027,
                                 renewal_deadline_utc="2027-09-15T00:00:00Z")
    foreign_seats = mint_seats(
        other_season["id"], section_code="104", row_label="A", price_zone="ZONE_C",
        seat_number_from=1, seat_number_to=2,
    )

    response = api_client.create_plan_order(
        create_plan_order_payload(
            world["account_id"], world["plan_id"], [foreign_seats[0]["id"]]
        ),
        world["rep_headers"],
    )

    validate_error(response, ApiErrorId.ERR_SEAT_SEASON_MISMATCH.value, 422)
    assert read_seat(foreign_seats[0]["id"])["seat_status"] == "AVAILABLE"
    assert read_season(other_season["id"])["held_seat_count"] == 0


def test_schema_violation_outranks_body_foreign_key_existence():
    """PRD 2.9: "**Schema.** Required fields present, enum members valid, integers inside their declared ranges, ISO 8601 UTC timestamps parseable, `limit` inside 1 through 100, `offset` at least 0, `seat_ids` and `new_seat_ids` non-empty and free of duplicates, `installment_count` one of 1, 3 or 6, `hold_window_end_utc` strictly after `hold_window_start_utc`, and `service_window_end_utc` strictly after `service_window_start_utc` — otherwise `ERR_INVALID_REQUEST` (400). This applies to every endpoint."
    PRD 2.9: "**Body foreign-key existence.** Every reference supplied in the body — `season_id`, `game_id`, `seat_id`, each member of `seat_ids`, each member of `new_seat_ids`, `plan_id`, `base_plan_id`, `account_id`, `order_id` and `to_account_id` — must resolve to a stored row, yielding the matching not-found code above with HTTP 404."

    Design: Corner/validations/val_schema_check_runs_before_body_foreign_key_existence
    """
    create_rep()
    account, rep_headers = create_account_with_rep()

    response = api_client.create_plan_order(
        {
            "account_id": account["id"],
            "plan_id": "33333333-4444-4555-8666-777777777777",
            "seat_ids": [],
        },
        rep_headers,
    )

    error = validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    assert error["error_id"] != ApiErrorId.ERR_PLAN_NOT_FOUND.value


def test_order_against_a_draft_plan_is_rejected():
    """PRD 2.9: "**Plan publication status.** Order creation and order confirmation require the referenced plan's `plan_status` to be `PUBLISHED`; publication itself requires the plan to be `DRAFT`. Either violation is `ERR_PLAN_NOT_PUBLISHED` (409)."
    PRD 3.1: "A separate publication step by the same role moves a plan from `DRAFT` to `PUBLISHED` and bumps its `version` by 1; only a `PUBLISHED` plan may back an order, and only a `DRAFT` plan may be published."

    Design: Corner/errors/err_order_against_a_draft_plan_returns_plan_not_published
    """
    season = create_season()
    game = create_game(season["id"])
    seats = mint_seats(season["id"])
    create_published_plan(season["id"], [game["id"]])
    draft_plan = create_plan(season["id"], [game["id"]])
    open_renewal(season["id"])
    create_rep()
    account, rep_headers = create_account_with_rep()

    response = api_client.create_plan_order(
        create_plan_order_payload(account["id"], draft_plan["id"], [seats[0]["id"]]),
        rep_headers,
    )

    validate_error(response, ApiErrorId.ERR_PLAN_NOT_PUBLISHED.value, 409)
    season_now = read_season(season["id"])
    assert season_now["season_status"] == "RENEWAL_OPEN"
    assert season_now["held_seat_count"] == 0


def test_renewal_quote_for_an_account_without_assigned_seats_is_zero():
    """PRD 3.4: "The caller names an account and supplies a `plan_id` as a query parameter, and the server prices the seats currently `ASSIGNED` to that account against that plan using the quoted variant."
    PRD 3.4: "The response is a summary object carrying `account_id`, `plan_id`, `seat_count` (the number of seats currently assigned to the account), `included_game_count` (taken from the plan), `quoted_total_cents`, a `pricing_variant` naming which variant produced the figure, and `campaign_risk_score` carrying the account's current campaign churn score."

    Design: Corner/endpoints/ep_renewal_quote_returns_zero_for_an_account_without_assigned_seats
    """
    world = setup_selling_world(account={"tenure_years": 4})

    quote = validate_success(
        api_client.get_renewal_quote(
            world["account_id"], world["plan_id"], world["rep_headers"]
        ),
        200,
    )

    assert quote["account_id"] == world["account_id"]
    assert quote["plan_id"] == world["plan_id"]
    assert quote["seat_count"] == 0
    assert quote["quoted_total_cents"] == 0
    assert quote["included_game_count"] == 1
    assert quote["pricing_variant"] == "QUOTED"
    assert quote["campaign_risk_score"] == 0
