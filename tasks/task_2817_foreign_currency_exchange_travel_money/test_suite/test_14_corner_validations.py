"""Conditional, cross-entity, temporal and four-eyes validation.

PRD 2.8 rank 9 pins both four-eyes rules: "On `POST /inventory-plans/{id}/review` a
reviewer may not be the plan's own submitter, failing with
`ERR_SEGREGATION_OF_DUTIES`.  On `POST /exchange-transactions/{id}/settle` the settling
user may not be the authorising user once `settled_usd_gross_cents` reaches 500000
cents (five thousand dollars) or more, failing with `ERR_DUAL_CONTROL_REQUIRED`."  Rank
10 pins the two temporal edges as non-strict: "The logical clock must be at or before
`quote_expires_at`", and "at or before `settled_at` plus 24 hours".
"""

from test_helpers import (
    CLOCK_START,
    OPERATORS,
    ApiErrorId,
    assertions as a,
    factories as f,
    fixtures as fx,
    make_treasury_headers,
    validate_error,
    validate_success,
)


def test_the_restricted_class_gates_the_document_then_the_export_ceiling(
    api, teller_headers
):
    """A MAD sale is refused with ERR_RESTRICTED_CURRENCY_DOC_REQUIRED for a customer
    with no travel document even at 23269 cents, authorizes for a customer who has one
    when fx_gross_minor_units equals the 20000-minor export limit exactly, and is
    refused with ERR_EXPORT_LIMIT_EXCEEDED at 30000 minor - and no gross here is large
    enough for the identification floor to be involved.

    Design: Corner/validations/restricted_currency_document_gate_and_export_ceiling
    """
    branch = fx.register_branch(api, code="BR-CMN", name="Casablanca Desk")
    currency = fx.register_currency(
        api,
        f.restricted_currency_payload(
            standard_denominations=[2000, 10000], export_limit_minor_units=20000
        ),
    )
    wholesale = fx.record_wholesale_rate(
        api, currency_code="MAD", mid_rate_micros=900_000
    )
    card = fx.published_rate_card(
        api,
        branch["id"],
        wholesale["id"],
        currency_code="MAD",
        board_display_label="MAD Dirham",
    )
    assert card["sell_rate_micros"] == 859500
    position = fx.open_position(api, branch["id"], "MAD", [f.denom(10000, 10)])
    assert position["usd_equivalent_cents"] == 111111

    undocumented = fx.onboard_customer(
        api, full_name="Omar Belkacem", nationality_code="MA", home_branch_id=branch["id"]
    )
    documented = fx.onboard_customer(
        api,
        full_name="Selma Idrissi",
        nationality_code="MA",
        home_branch_id=branch["id"],
        travel_document_reference="TD-77120",
    )
    world = {"branch": branch, "customer": documented, "card": card, "currency": currency}

    no_doc = fx.quote_deal(
        api,
        world,
        "SELL_FX_TO_CUSTOMER",
        [f.denom(10000, 2)],
        teller_headers,
        customer_id=undocumented["id"],
    )
    a.assert_quote_money(no_doc, 20000, 859500, 23269, 814, 24083)

    at_limit = fx.quote_deal(
        api, world, "SELL_FX_TO_CUSTOMER", [f.denom(10000, 2)], teller_headers
    )
    over_limit = fx.quote_deal(
        api, world, "SELL_FX_TO_CUSTOMER", [f.denom(10000, 3)], teller_headers
    )
    a.assert_quote_money(over_limit, 30000, 859500, 34904, 873, 35777)

    validate_error(
        api.authorize_transaction(no_doc["id"], teller_headers),
        ApiErrorId.ERR_RESTRICTED_CURRENCY_DOC_REQUIRED,
        422,
    )
    assert fx.read_transaction(api, no_doc["id"])["settlement_status"] == "QUOTED"

    authorized = validate_success(
        api.authorize_transaction(at_limit["id"], teller_headers)
    )
    assert authorized["settlement_status"] == "AUTHORIZED"
    assert authorized["fx_gross_minor_units"] == currency["export_limit_minor_units"]

    validate_error(
        api.authorize_transaction(over_limit["id"], teller_headers),
        ApiErrorId.ERR_EXPORT_LIMIT_EXCEEDED,
        422,
    )
    assert fx.read_transaction(api, over_limit["id"])["settlement_status"] == "QUOTED"

    a.assert_mix_counts(fx.read_position(api, position["id"]), 10000, available=10)


def test_an_exotic_sale_waits_for_an_active_plan_naming_the_currency(
    api, teller_headers, treasury_headers
):
    """The identical VND quote is refused with ERR_EXOTIC_PLAN_REQUIRED while the
    branch's only plan is still DRAFT, SUBMITTED or APPROVED, and authorizes untouched
    once that plan reaches ACTIVE carrying a 5000000-minor VND target.

    Design: Corner/validations/exotic_currency_requires_active_plan_covering_it
    """
    branch = fx.register_branch(api, code="BR-SGN", name="Saigon Desk")
    currency = fx.register_currency(api, f.exotic_currency_payload())
    wholesale = fx.record_wholesale_rate(
        api, currency_code="VND", mid_rate_micros=250_000_000
    )
    corridor = fx.register_corridor(
        api,
        code="LHR-SGN-SUMMER",
        destination_country_code="VN",
        destination_currency_code="VND",
        season="SUMMER",
        season_start_date="2026-06-01T00:00:00Z",
        season_end_date="2026-09-01T00:00:00Z",
        demand_index_bps=10000,
    )
    card = fx.published_rate_card(
        api,
        branch["id"],
        wholesale["id"],
        currency_code="VND",
        board_display_label="VND Dong",
    )
    assert card["sell_rate_micros"] == 238750000
    position = fx.open_position(api, branch["id"], "VND", [f.denom(100000, 40)])
    assert position["usd_equivalent_cents"] == 16000
    customer = fx.onboard_customer(
        api, full_name="Linh Pham", nationality_code="VN", home_branch_id=branch["id"]
    )
    world = {"branch": branch, "customer": customer, "card": card, "currency": currency}

    txn = fx.quote_deal(
        api, world, "SELL_FX_TO_CUSTOMER", [f.denom(100000, 1)], teller_headers
    )
    a.assert_quote_money(txn, 100000, 238750000, 419, 400, 819)

    validate_error(
        api.authorize_transaction(txn["id"], teller_headers),
        ApiErrorId.ERR_EXOTIC_PLAN_REQUIRED,
        422,
    )
    assert fx.read_transaction(api, txn["id"])["settlement_status"] == "QUOTED"

    plan = fx.draft_plan(
        api,
        branch["id"],
        corridor["id"],
        season_days=10,
        target_lines=[f.target_line("VND", 500000)],
    )
    fx.submit_plan(api, plan["id"])
    fx.review_plan(api, plan["id"], "APPROVE", "seasonal stocking agreed", treasury_headers)
    active = fx.activate_plan(api, plan["id"])

    a.assert_inventory_plan(active)
    assert active["status"] == "ACTIVE"
    assert active["revision_count"] == 0
    assert active["computed_targets"] == [
        {"currency_code": "VND", "target_minor_units": 5000000}
    ]

    authorized = validate_success(api.authorize_transaction(txn["id"], teller_headers))
    assert authorized["settlement_status"] == "AUTHORIZED"
    assert authorized["quoted_usd_gross_cents"] == 419


def test_the_disclosure_floor_is_enforced_at_publish_not_at_creation(
    api, treasury_headers, teller_headers
):
    """A card carrying disclosure_text_version 2 is created happily and only its
    publish attempt is refused with ERR_DISCLOSURE_VERSION_UNSUPPORTED; the version-3
    card publishes, the board shows one line at min_disclosure_text_version 3, and the
    rejected card is left DRAFT and unsuperseded with identical derived rates.

    Design: Corner/validations/disclosure_version_gate_on_publish_and_board
    """
    branch = fx.register_branch(api, code="BR-EDI", name="Edinburgh", region_code="NORTH")
    fx.register_currency(api)
    wholesale = fx.record_wholesale_rate(api)

    old_card = fx.draft_rate_card(
        api, branch["id"], wholesale["id"], branch["version"], disclosure_text_version=2
    )
    new_card = fx.draft_rate_card(
        api, branch["id"], wholesale["id"], disclosure_text_version=3
    )
    for card in (old_card, new_card):
        assert card["buy_rate_micros"] == 970600
        assert card["sell_rate_micros"] == 878600

    validate_error(
        api.publish_rate_card(old_card["id"], treasury_headers),
        ApiErrorId.ERR_DISCLOSURE_VERSION_UNSUPPORTED,
        422,
    )
    stalled = validate_success(api.get_rate_card(old_card["id"], treasury_headers))
    assert stalled["status"] == "DRAFT"
    assert stalled["published_at"] is None

    published = fx.publish_rate_card(api, new_card["id"])
    assert published["status"] == "PUBLISHED"
    a.assert_timestamp_equals(published["published_at"], CLOCK_START)

    board = fx.read_board(api, branch["id"], teller_headers, {"currency_code": "EUR"})
    a.assert_rate_board(board)
    assert board["line_count"] == 1
    assert board["min_disclosure_text_version"] == 3

    final_old = validate_success(api.get_rate_card(old_card["id"], treasury_headers))
    assert final_old["superseded_by_rate_card_id"] is None


def test_both_temporal_edges_admit_their_last_legal_instant(
    api, teller_headers, manager_headers
):
    """Authorisation succeeds at exactly quote_expires_at and is refused with
    ERR_QUOTE_EXPIRED one second later; a reversal succeeds at exactly settled_at plus
    24 hours and is refused with ERR_REVERSAL_WINDOW_CLOSED one second later; and the
    surviving settlement is the only row left in the customer's rolling window.

    Design: Corner/validations/quote_ttl_and_reversal_window_temporal_edges
    """
    world = fx.trading_world(api, position_mix=[f.denom(10000, 20)], identified=False)
    first, second, third = [
        fx.quote_deal(
            api, world, "SELL_FX_TO_CUSTOMER", [f.denom(10000, 1)], teller_headers
        )
        for _ in range(3)
    ]
    a.assert_timestamp_equals(first["quote_expires_at"], "2026-08-01T00:15:00Z")

    fx.set_clock(api, "2026-08-01T00:15:00Z")
    for deal in (first, third):
        fx.authorize_deal(api, deal["id"], teller_headers)
        settled = fx.settle_deal(api, deal["id"], teller_headers)
        assert settled["settled_usd_gross_cents"] == 11382
        a.assert_timestamp_equals(settled["settled_at"], "2026-08-01T00:15:00Z")

    fx.set_clock(api, "2026-08-01T00:15:01Z")
    validate_error(
        api.authorize_transaction(second["id"], teller_headers),
        ApiErrorId.ERR_QUOTE_EXPIRED,
        409,
    )
    stalled = fx.read_transaction(api, second["id"])
    assert stalled["settlement_status"] == "QUOTED"
    assert stalled["authorized_at"] is None

    fx.set_clock(api, "2026-08-02T00:15:00Z")
    reversed_deal = fx.reverse_deal(
        api, first["id"], manager_headers, "wrong note handed over"
    )
    assert reversed_deal["settlement_status"] == "REVERSED"
    a.assert_timestamp_equals(reversed_deal["reversed_at"], "2026-08-02T00:15:00Z")

    fx.set_clock(api, "2026-08-02T00:15:01Z")
    validate_error(
        api.reverse_transaction(
            third["id"],
            f.reverse_payload("same complaint, one second later"),
            manager_headers,
        ),
        ApiErrorId.ERR_REVERSAL_WINDOW_CLOSED,
        409,
    )
    assert fx.read_transaction(api, third["id"])["settlement_status"] == "SETTLED"

    a.assert_mix_counts(fx.read_position(api, world["position"]["id"]), 10000, available=19)
    customer = fx.read_customer(api, world["customer"]["id"])
    assert customer["rolling_30d_settled_usd_cents"] == 11382


def test_dual_control_arms_above_its_threshold_and_review_bars_the_submitter(
    api, teller_headers, teller2_headers, manager_headers, treasury_headers
):
    """A 455270-cent settlement is allowed for the teller who authorised it, a
    500797-cent settlement by that same teller is refused with
    ERR_DUAL_CONTROL_REQUIRED and succeeds for a second teller, and a plan review by
    the submitter's own operator id is refused with ERR_SEGREGATION_OF_DUTIES even
    though the role is right.

    Design: Corner/validations/dual_control_threshold_and_plan_segregation_of_duties
    """
    world = fx.trading_world(
        api,
        position_mix=[f.denom(10000, 100)],
        customer_overrides={"id_document_expiry": "2030-01-01T00:00:00Z"},
    )
    corridor = fx.register_corridor(
        api,
        code="LHR-CDG-SUMMER",
        destination_country_code="FR",
        destination_currency_code="EUR",
        season="SUMMER",
        season_start_date="2026-06-01T00:00:00Z",
        season_end_date="2026-09-01T00:00:00Z",
        demand_index_bps=10000,
    )
    small = fx.authorized_deal(
        api, world, "SELL_FX_TO_CUSTOMER", [f.denom(10000, 40)], teller_headers
    )
    big = fx.authorized_deal(
        api, world, "SELL_FX_TO_CUSTOMER", [f.denom(10000, 44)], teller_headers
    )
    plan = fx.draft_plan(
        api,
        world["branch"]["id"],
        corridor["id"],
        season_days=10,
        target_lines=[f.target_line("EUR", 5000)],
    )
    fx.submit_plan(api, plan["id"])

    settled_small = fx.settle_deal(api, small["id"], teller_headers)
    a.assert_settlement_money(settled_small, 455270, 6829, 462099)
    assert settled_small["settled_by_user_id"] == OPERATORS["TELLER_1"]
    assert settled_small["authorized_by_user_id"] == OPERATORS["TELLER_1"]

    validate_error(
        api.settle_transaction(big["id"], teller_headers),
        ApiErrorId.ERR_DUAL_CONTROL_REQUIRED,
        403,
    )

    settled_big = fx.settle_deal(api, big["id"], teller2_headers)
    a.assert_settlement_money(settled_big, 500797, 7512, 508309)
    assert settled_big["settled_by_user_id"] == OPERATORS["TELLER_2"]

    validate_error(
        api.review_inventory_plan(
            plan["id"],
            f.review_plan_payload("APPROVE"),
            make_treasury_headers(OPERATORS["MANAGER"]),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    unreviewed = fx.read_plan(api, plan["id"])
    assert unreviewed["status"] == "SUBMITTED"
    assert unreviewed["reviewed_by_user_id"] is None

    approved = validate_success(
        api.review_inventory_plan(
            plan["id"],
            f.review_plan_payload("APPROVE"),
            make_treasury_headers(OPERATORS["TREASURY_ALT"]),
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["reviewed_by_user_id"] == OPERATORS["TREASURY_ALT"]
    assert approved["submitted_by_user_id"] == OPERATORS["MANAGER"]

    position = fx.read_position(api, world["position"]["id"])
    a.assert_mix_counts(position, 10000, available=16)
    assert position["usd_equivalent_cents"] == 173913
    branch = fx.read_branch(api, world["branch"]["id"])
    a.assert_vault_state(branch, 173913, 87, "OPEN")
    customer = fx.read_customer(api, world["customer"]["id"])
    assert customer["rolling_30d_settled_usd_cents"] == 956067
