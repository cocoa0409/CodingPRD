"""The endpoint surface: a clock-dependent projection, a sweeping clock control, a
replacing submit, the declared input order of body keys and filters that compose
with the page window.

PRD 2.10 defines the board as a projection rather than a row: it "returns the
requesting branch's `branch_id`, an `as_of` instant equal to the current logical
clock, a `line_count`, the `min_disclosure_text_version` being displayed, and a
`lines` array holding one entry per currency whose published card's window covers
the clock".  PRD 2.4 makes the clock control active - it "sweeps every buy-back
contract whose rate lock has fallen into the past" and "`expired_contract_count`
reports how many contracts the sweep expired".  PRD 3.3 makes submit destructive:
"the submit payload may supply a replacement `target_lines` array, which overwrites
whatever the plan held".  PRD 2.8 rank 3 fixes the order of the existence checks -
"Every foreign-key field in the request body resolves to a live row, checked in the
declaration order of the endpoint's input list" - and PRD 2.3 fixes what the page
window reports: "`total_count` reports the number of rows matching the filters
before paging".
"""

from test_helpers import (
    CLOCK_START,
    NON_EXISTENT_UUID,
    OPERATORS,
    ApiErrorId,
    assertions as a,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


def _labels(board: dict) -> dict:
    """The displayed lines keyed by the label printed on the physical board."""
    return {line["board_display_label"]: line for line in board["lines"]}


def test_the_board_shows_only_published_cards_whose_window_covers_the_clock(
    api, treasury_headers, teller_headers, customer_headers
):
    """One branch carries three cards - a PUBLISHED EUR line already open, a
    PUBLISHED JPY line that opens on 2026-09-01 and a DRAFT CHF line - so the board
    shows one line at 3 before the clock moves and two lines still at 3 the instant
    the clock reaches the JPY window, while the CHF draft never appears and its
    disclosure version 5 never participates.

    Design: Corner/endpoints/rate_board_shows_only_published_and_currently_effective_lines
    """
    branch = fx.register_branch(
        api, code="BR-LHR", name="London Heathrow", region_code="SOUTH"
    )
    fx.register_currency(api)
    fx.register_currency(api, f.jpy_currency_payload())
    fx.register_currency(api, f.chf_currency_payload())
    eur_rate = fx.record_wholesale_rate(api)
    jpy_rate = fx.record_wholesale_rate(
        api, currency_code="JPY", mid_rate_micros=1_475_000
    )
    chf_rate = fx.record_wholesale_rate(
        api, currency_code="CHF", mid_rate_micros=912_345
    )

    fx.published_rate_card(
        api,
        branch["id"],
        eur_rate["id"],
        board_display_label="EUR Euro",
        disclosure_text_version=3,
    )
    fx.published_rate_card(
        api,
        branch["id"],
        jpy_rate["id"],
        currency_code="JPY",
        board_display_label="JPY Yen",
        disclosure_text_version=4,
        effective_from="2026-09-01T00:00:00Z",
    )
    chf_card = fx.draft_rate_card(
        api,
        branch["id"],
        chf_rate["id"],
        currency_code="CHF",
        board_display_label="CHF Franc",
        disclosure_text_version=5,
    )
    assert chf_card["status"] == "DRAFT"
    assert chf_card["published_at"] is None

    before = fx.read_board(api, branch["id"], customer_headers)
    a.assert_rate_board(before)
    assert before["branch_id"] == branch["id"]
    assert before["line_count"] == 1
    assert before["min_disclosure_text_version"] == 3
    a.assert_timestamp_equals(before["as_of"], CLOCK_START)
    euro = _labels(before)["EUR Euro"]
    assert euro["buy_rate_micros"] == 970600
    assert euro["sell_rate_micros"] == 878600

    jpy_before = fx.read_board(api, branch["id"], teller_headers, {"currency_code": "JPY"})
    assert jpy_before["line_count"] == 0
    assert jpy_before["lines"] == []
    chf_before = fx.read_board(api, branch["id"], customer_headers, {"currency_code": "CHF"})
    assert chf_before["line_count"] == 0
    assert chf_before["lines"] == []

    swept = fx.set_clock(api, "2026-09-01T00:00:00Z")
    assert swept["expired_contract_count"] == 0

    after = fx.read_board(api, branch["id"], customer_headers)
    a.assert_rate_board(after)
    assert after["line_count"] == 2
    assert after["min_disclosure_text_version"] == 3
    a.assert_timestamp_equals(after["as_of"], "2026-09-01T00:00:00Z")
    lines = _labels(after)
    assert set(lines) == {"EUR Euro", "JPY Yen"}
    assert lines["JPY Yen"]["buy_rate_micros"] == 1556125
    assert lines["JPY Yen"]["sell_rate_micros"] == 1408625
    assert lines["EUR Euro"]["buy_rate_micros"] == 970600
    assert lines["EUR Euro"]["sell_rate_micros"] == 878600

    chf_after = fx.read_board(api, branch["id"], customer_headers, {"currency_code": "CHF"})
    assert chf_after["line_count"] == 0
    assert chf_after["lines"] == []
    assert fx.read_board(api, branch["id"], teller_headers, {"currency_code": "JPY"})[
        "line_count"
    ] == 1


def test_the_clock_sweep_counts_only_the_contracts_it_moves(
    api, teller_headers, teller2_headers
):
    """Two contracts - one ISSUED at 20606 and one PARTIALLY_REDEEMED at 10303 -
    are both swept by the first advance past their shared lock instant, so the call
    answers 2 and the branch's 30909-cent liability collapses to 0, while the second
    advance four days later answers 0 because the rows it would count are already
    EXPIRED.

    Design: Corner/endpoints/clock_sweep_counts_only_newly_expired_contracts
    """
    world = fx.trading_world(
        api,
        position_mix=[f.denom(10000, 20)],
        card_overrides={"board_display_label": "EUR Euro"},
        identified=False,
        customer_overrides={"full_name": "Nia Adeyemi", "nationality_code": "GH"},
    )
    branch_id = world["branch"]["id"]
    first_customer = world["customer"]["id"]
    second_customer = fx.onboard_customer(
        api, full_name="Tomas Reiner", nationality_code="AT", home_branch_id=branch_id
    )["id"]

    first_deal = fx.settled_deal(
        api,
        world,
        "SELL_FX_TO_CUSTOMER",
        [f.denom(10000, 2)],
        teller_headers,
        settle_headers=teller2_headers,
    )
    a.assert_settlement_money(first_deal, 22763, 797, 23560)
    second_deal = fx.settled_deal(
        api,
        world,
        "SELL_FX_TO_CUSTOMER",
        [f.denom(10000, 2)],
        teller_headers,
        settle_headers=teller2_headers,
        customer_id=second_customer,
    )
    a.assert_settlement_money(second_deal, 22763, 797, 23560)

    intact = fx.issue_contract(api, first_customer, first_deal["id"], headers=teller_headers)
    a.assert_buyback_contract(intact)
    assert intact["status"] == "ISSUED"
    assert intact["fee_usd_cents"] == 683
    assert intact["liability_usd_cents"] == 20606
    a.assert_timestamp_equals(intact["rate_lock_expires_at"], "2026-09-01T00:00:00Z")

    partial = fx.issue_contract(api, second_customer, second_deal["id"], headers=teller_headers)
    redeemed = fx.redeem_contract(api, partial["id"], [f.denom(10000, 1)], teller_headers)
    assert redeemed["status"] == "PARTIALLY_REDEEMED"
    assert redeemed["remaining_fx_minor_units"] == 10000
    assert redeemed["redemption_count"] == 1
    assert redeemed["liability_usd_cents"] == 10303

    assert fx.read_branch(api, branch_id)["buyback_liability_usd_cents"] == 30909
    a.assert_mix_counts(fx.read_position(api, world["position"]["id"]), 10000, available=17)

    first_sweep = fx.set_clock(api, "2026-09-01T00:00:01Z")
    assert first_sweep["expired_contract_count"] == 2
    a.assert_timestamp_equals(first_sweep["current_utc"], "2026-09-01T00:00:01Z")

    expired_intact = fx.read_contract(api, intact["id"])
    assert expired_intact["status"] == "EXPIRED"
    assert expired_intact["liability_usd_cents"] == 0
    assert expired_intact["remaining_fx_minor_units"] == 20000
    expired_partial = fx.read_contract(api, partial["id"])
    assert expired_partial["status"] == "EXPIRED"
    assert expired_partial["liability_usd_cents"] == 0
    assert expired_partial["remaining_fx_minor_units"] == 10000
    assert fx.read_branch(api, branch_id)["buyback_liability_usd_cents"] == 0

    second_sweep = fx.set_clock(api, "2026-09-05T00:00:00Z")
    assert second_sweep["expired_contract_count"] == 0
    assert fx.read_contract(api, intact["id"])["status"] == "EXPIRED"
    assert fx.read_contract(api, partial["id"])["status"] == "EXPIRED"
    assert fx.read_branch(api, branch_id)["buyback_liability_usd_cents"] == 0

    steady = fx.read_position(api, world["position"]["id"])
    a.assert_position_mix_invariants(steady)
    a.assert_mix_counts(steady, 10000, available=17)
    assert steady["total_minor_units"] == 170000


def test_submit_replaces_the_creation_lines_and_orders_the_computed_targets(
    api, treasury_headers, manager_headers
):
    """A plan created with a single 5000-unit EUR line is submitted with EUR 8000
    and CHF 3000, and the creation line is gone rather than merged: computed_targets
    reads CHF before EUR with CHF's raw 37500 rounded up to two 20000-notes and EUR's
    100000 already whole, and neither the approval nor the activation disturbs them.

    Design: Corner/endpoints/plan_submit_replaces_target_lines_and_orders_computed_targets
    """
    branch = fx.register_branch(
        api,
        code="BR-LHR",
        name="London Heathrow",
        region_code="SOUTH",
        vault_limit_usd_cents=20_000_000,
    )
    fx.register_currency(api)
    fx.register_currency(api, f.chf_currency_payload())
    fx.record_wholesale_rate(api)
    fx.record_wholesale_rate(api, currency_code="CHF", mid_rate_micros=912_345)
    corridor = fx.register_corridor(api)
    assert corridor["demand_index_bps"] == 12500

    plan = fx.draft_plan(
        api,
        branch["id"],
        corridor["id"],
        season_days=10,
        target_lines=[f.target_line("EUR", 5000)],
    )
    a.assert_inventory_plan(plan)
    assert plan["status"] == "DRAFT"
    assert plan["revision_count"] == 0
    assert plan["computed_targets"] == []

    submitted = fx.submit_plan(
        api,
        plan["id"],
        [f.target_line("EUR", 8000), f.target_line("CHF", 3000)],
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_by_user_id"] == OPERATORS["MANAGER"]
    assert submitted["revision_count"] == 0
    assert len(submitted["target_lines"]) == 2
    assert {
        line["currency_code"]: line["baseline_daily_minor_units"]
        for line in submitted["target_lines"]
    } == {"EUR": 8000, "CHF": 3000}

    expected_targets = [
        {"currency_code": "CHF", "target_minor_units": 40000},
        {"currency_code": "EUR", "target_minor_units": 100000},
    ]
    a.assert_computed_targets_shape(submitted["computed_targets"])
    assert submitted["computed_targets"] == expected_targets

    approved = fx.review_plan(
        api, plan["id"], "APPROVE", "targets agreed", treasury_headers
    )
    assert approved["status"] == "APPROVED"
    assert approved["reviewed_by_user_id"] == OPERATORS["TREASURY"]
    assert approved["computed_targets"] == expected_targets

    active = fx.activate_plan(api, plan["id"], manager_headers)
    a.assert_inventory_plan(active)
    assert active["status"] == "ACTIVE"
    assert active["revision_count"] == 0
    assert active["computed_targets"] == expected_targets
    assert active["submitted_by_user_id"] == OPERATORS["MANAGER"]
    assert active["reviewed_by_user_id"] == OPERATORS["TREASURY"]


def test_the_first_unresolvable_body_key_in_declared_order_decides_the_error(
    api, teller_headers, manager_headers
):
    """Six calls whose bad foreign keys overlap always report the earliest one in
    the endpoint's declared input list: branch before position before transaction on a
    detention, and customer before rate card before currency on a quote - and nothing
    is created by any of them.

    Design: Corner/endpoints/body_fk_resolution_follows_declared_input_order
    """
    world = fx.trading_world(
        api,
        position_mix=[f.denom(10000, 5)],
        card_overrides={"board_display_label": "EUR Euro"},
        identified=False,
    )
    branch_id = world["branch"]["id"]
    position_id = world["position"]["id"]
    customer_id = world["customer"]["id"]
    card_id = world["card"]["id"]

    validate_error(
        api.create_note_assessment(
            f.create_note_assessment_payload(
                NON_EXISTENT_UUID, NON_EXISTENT_UUID, NON_EXISTENT_UUID
            ),
            teller_headers,
        ),
        ApiErrorId.ERR_BRANCH_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_note_assessment(
            f.create_note_assessment_payload(
                branch_id, NON_EXISTENT_UUID, NON_EXISTENT_UUID
            ),
            teller_headers,
        ),
        ApiErrorId.ERR_POSITION_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_note_assessment(
            f.create_note_assessment_payload(branch_id, position_id, NON_EXISTENT_UUID),
            teller_headers,
        ),
        ApiErrorId.ERR_TRANSACTION_NOT_FOUND,
        404,
    )

    validate_error(
        api.create_exchange_transaction(
            f.create_exchange_transaction_payload(
                branch_id,
                NON_EXISTENT_UUID,
                NON_EXISTENT_UUID,
                "ZZZ",
                "SELL_FX_TO_CUSTOMER",
                [f.denom(10000, 1)],
            ),
            teller_headers,
        ),
        ApiErrorId.ERR_CUSTOMER_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_exchange_transaction(
            f.create_exchange_transaction_payload(
                branch_id,
                customer_id,
                NON_EXISTENT_UUID,
                "ZZZ",
                "SELL_FX_TO_CUSTOMER",
                [f.denom(10000, 1)],
            ),
            teller_headers,
        ),
        ApiErrorId.ERR_RATE_CARD_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_exchange_transaction(
            f.create_exchange_transaction_payload(
                branch_id,
                customer_id,
                card_id,
                "ZZZ",
                "SELL_FX_TO_CUSTOMER",
                [f.denom(10000, 1)],
            ),
            teller_headers,
        ),
        ApiErrorId.ERR_CURRENCY_NOT_FOUND,
        404,
    )

    _, assessments_meta = validate_paginated(api.list_note_assessments(manager_headers))
    assert assessments_meta["total_count"] == 0
    _, deals_meta = validate_paginated(api.list_exchange_transactions(teller_headers))
    assert deals_meta["total_count"] == 0

    untouched = fx.read_position(api, position_id)
    a.assert_position_mix_invariants(untouched)
    a.assert_mix_counts(untouched, 10000, available=5, quarantined=0)
    assert untouched["total_minor_units"] == 50000


def test_transaction_filters_narrow_the_count_before_the_page_window(
    api, teller_headers
):
    """One customer's five deals - three sales and two purchases, one sale voided -
    page under a direction filter as a three-row set: two rows with has_more true,
    then the disjoint third with has_more false, while the settlement_status filter
    composes down to the single voided sale and the unfiltered read still counts all
    five.

    Design: Corner/endpoints/transaction_listing_filters_compose_with_pagination
    """
    world = fx.trading_world(
        api,
        position_mix=[f.denom(10000, 20)],
        card_overrides={"board_display_label": "EUR Euro"},
        identified=False,
        customer_overrides={"full_name": "Nia Adeyemi", "nationality_code": "GH"},
    )
    customer_id = world["customer"]["id"]

    first_sale = fx.settled_deal(
        api, world, "SELL_FX_TO_CUSTOMER", [f.denom(10000, 1)], teller_headers
    )
    a.assert_settlement_money(first_sale, 11382, 400, 11782)

    doomed = fx.quote_deal(
        api, world, "SELL_FX_TO_CUSTOMER", [f.denom(10000, 1)], teller_headers
    )
    voided = validate_success(
        api.void_transaction(
            doomed["id"], f.void_payload("customer changed mind"), teller_headers
        )
    )
    assert voided["settlement_status"] == "VOIDED"

    open_sale = fx.quote_deal(
        api, world, "SELL_FX_TO_CUSTOMER", [f.denom(10000, 1)], teller_headers
    )
    assert open_sale["settlement_status"] == "QUOTED"

    purchase = fx.settled_deal(
        api, world, "BUY_FX_FROM_CUSTOMER", [f.denom(10000, 1)], teller_headers
    )
    a.assert_settlement_money(purchase, 10303, 400, 9903)
    open_purchase = fx.quote_deal(
        api, world, "BUY_FX_FROM_CUSTOMER", [f.denom(10000, 1)], teller_headers
    )
    assert open_purchase["settlement_status"] == "QUOTED"

    sales = {first_sale["id"], doomed["id"], open_sale["id"]}
    purchases = {purchase["id"], open_purchase["id"]}

    page_one, meta_one = validate_paginated(
        api.list_exchange_transactions(
            teller_headers,
            {
                "customer_id": customer_id,
                "direction": "SELL_FX_TO_CUSTOMER",
                "limit": 2,
                "offset": 0,
            },
        )
    )
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0
    first_page_ids = {row["id"] for row in page_one}
    assert len(page_one) == 2
    assert first_page_ids <= sales
    assert not first_page_ids & purchases

    page_two, meta_two = validate_paginated(
        api.list_exchange_transactions(
            teller_headers,
            {
                "customer_id": customer_id,
                "direction": "SELL_FX_TO_CUSTOMER",
                "limit": 2,
                "offset": 2,
            },
        )
    )
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False
    second_page_ids = {row["id"] for row in page_two}
    assert len(page_two) == 1
    assert not first_page_ids & second_page_ids
    assert first_page_ids | second_page_ids == sales

    voided_rows, voided_meta = validate_paginated(
        api.list_exchange_transactions(
            teller_headers,
            {
                "customer_id": customer_id,
                "direction": "SELL_FX_TO_CUSTOMER",
                "settlement_status": "VOIDED",
            },
        )
    )
    assert voided_meta["total_count"] == 1
    assert voided_meta["has_more"] is False
    assert len(voided_rows) == 1
    assert voided_rows[0]["id"] == doomed["id"]

    everything, all_meta = validate_paginated(
        api.list_exchange_transactions(teller_headers, {"customer_id": customer_id})
    )
    assert all_meta["total_count"] == 5
    assert all_meta["limit"] == 10
    assert all_meta["offset"] == 0
    assert all_meta["has_more"] is False
    assert {row["id"] for row in everything} == sales | purchases

    balanced = fx.read_position(api, world["position"]["id"])
    a.assert_position_mix_invariants(balanced)
    a.assert_mix_counts(balanced, 10000, available=20)
    assert balanced["total_minor_units"] == 200000
