"""Fiscal capacity, the directional posture gate, the uniqueness conflicts and the
whole rank-4 well-formedness surface.

PRD 2.8 rank 13 states the two inventory checks in a fixed order: "On
`POST /exchange-transactions/{id}/settle`, every requested denomination must already
exist on the branch's inventory position for the currency
(`ERR_DENOMINATION_NOT_STOCKED`), and for a sale to a customer each denomination's
`available_note_count` must be at least the requested `note_count`
(`ERR_INSUFFICIENT_INVENTORY`)."  PRD 2.6 makes one posture directional - "A
`RESTRICTED` branch still permits cash to leave the vault but refuses any operation
that would *add* foreign cash to it" - and rank 5 notes that "Three cross-row
uniqueness rules behave as state preconditions and sit at the same rank, also HTTP
409".
"""

from test_helpers import (
    ApiErrorId,
    assertions as a,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


def _faces(position: dict) -> list:
    return [entry["denomination_minor_units"] for entry in position["denomination_mix"]]


def test_the_stocked_check_sweeps_every_line_before_any_count_is_compared(
    api, teller_headers
):
    """A till holding two 10000-notes and nothing else answers
    ERR_DENOMINATION_NOT_STOCKED for a lone 2000-note sale, ERR_INSUFFICIENT_INVENTORY
    for five 10000-notes, and ERR_DENOMINATION_NOT_STOCKED again for the mixed request
    whose 10000 line is also short - the unstocked face decides - while the two-note
    sale settles and empties the position.

    Design: Corner/validations/settle_checks_stocked_denomination_before_sufficiency
    """
    world = fx.trading_world(api, position_mix=[f.denom(10000, 2)], identified=False)

    unstocked = fx.authorized_deal(
        api, world, "SELL_FX_TO_CUSTOMER", [f.denom(2000, 1)], teller_headers
    )
    a.assert_quote_money(unstocked, 2000, 878600, 2276, 400, 2676)
    short = fx.authorized_deal(
        api, world, "SELL_FX_TO_CUSTOMER", [f.denom(10000, 5)], teller_headers
    )
    a.assert_quote_money(short, 50000, 878600, 56909, 1423, 58332)
    mixed = fx.authorized_deal(
        api,
        world,
        "SELL_FX_TO_CUSTOMER",
        [f.denom(10000, 1), f.denom(2000, 1)],
        teller_headers,
    )
    a.assert_quote_money(mixed, 12000, 878600, 13658, 478, 14136)
    good = fx.authorized_deal(
        api, world, "SELL_FX_TO_CUSTOMER", [f.denom(10000, 2)], teller_headers
    )

    validate_error(
        api.settle_transaction(unstocked["id"], teller_headers),
        ApiErrorId.ERR_DENOMINATION_NOT_STOCKED,
        422,
    )
    validate_error(
        api.settle_transaction(short["id"], teller_headers),
        ApiErrorId.ERR_INSUFFICIENT_INVENTORY,
        422,
    )
    validate_error(
        api.settle_transaction(mixed["id"], teller_headers),
        ApiErrorId.ERR_DENOMINATION_NOT_STOCKED,
        422,
    )

    for refused in (unstocked, short, mixed):
        row = fx.read_transaction(api, refused["id"])
        assert row["settlement_status"] == "AUTHORIZED"
        assert row["settled_at"] is None

    settled = fx.settle_deal(api, good["id"], teller_headers)
    a.assert_settlement_money(settled, 22763, 797, 23560)

    position = fx.read_position(api, world["position"]["id"])
    a.assert_position_mix_invariants(position)
    a.assert_mix_counts(position, 10000, available=0)
    assert _faces(position) == [10000]
    assert position["total_minor_units"] == 0
    assert position["usd_equivalent_cents"] == 0


def test_the_vault_ceiling_is_a_settlement_time_projection(api, teller_headers):
    """Both purchases authorize while the kiosk sits at 8696 basis points, the
    two-note settlement is refused because it would project 108696 cents against a
    100000-cent ceiling, the one-note settlement lands on exactly 97826 and turns the
    branch RESTRICTED, and the retry fails again from the higher base while the
    automatic repatriation asks for the single note the surplus buys.

    Design: Corner/validations/vault_limit_checked_at_settlement_not_authorization
    """
    world = fx.trading_world(
        api,
        vault_limit_usd_cents=100_000,
        branch_overrides={"code": "BR-JER", "name": "Jersey Kiosk"},
        position_mix=[f.denom(10000, 8)],
        identified=False,
    )
    a.assert_vault_state(world["branch"], 86957, 8696, "OPEN")

    two = fx.authorized_deal(
        api, world, "BUY_FX_FROM_CUSTOMER", [f.denom(10000, 2)], teller_headers
    )
    a.assert_quote_money(two, 20000, 970600, 20606, 721, 19885)
    one = fx.authorized_deal(
        api, world, "BUY_FX_FROM_CUSTOMER", [f.denom(10000, 1)], teller_headers
    )
    a.assert_quote_money(one, 10000, 970600, 10303, 400, 9903)

    validate_error(
        api.settle_transaction(two["id"], teller_headers),
        ApiErrorId.ERR_VAULT_LIMIT_WOULD_EXCEED,
        422,
    )

    settled = fx.settle_deal(api, one["id"], teller_headers)
    a.assert_settlement_money(settled, 10303, 400, 9903)

    crowded = fx.read_branch(api, world["branch"]["id"])
    a.assert_vault_state(crowded, 97826, 9783, "RESTRICTED")
    assert crowded["repatriation_pending"] is True

    validate_error(
        api.settle_transaction(two["id"], teller_headers),
        ApiErrorId.ERR_VAULT_LIMIT_WOULD_EXCEED,
        422,
    )
    stuck = fx.read_transaction(api, two["id"])
    assert stuck["settlement_status"] == "AUTHORIZED"
    assert stuck["settled_at"] is None

    auto = fx.auto_repatriation_shipment(api, world["branch"]["id"])
    a.assert_cash_shipment(auto)
    assert auto["status"] == "REQUESTED"
    assert auto["auto_generated"] is True
    assert [
        (entry["denomination_minor_units"], entry["note_count"])
        for entry in auto["manifest_denominations"]
    ] == [(10000, 1)]
    assert auto["manifest_minor_units"] == 10000
    assert auto["manifest_usd_equivalent_cents"] == 10870


def test_the_restricted_posture_only_blocks_cash_coming_in(
    api, teller_headers, treasury_headers
):
    """At exactly 10000 basis points the purchase authorization and the REPLENISHMENT
    request are both refused with ERR_BRANCH_POSTURE_RESTRICTED, the sale on the same
    branch authorizes and settles, and once that settlement has drained the vault to
    8913 basis points the identical REPLENISHMENT is accepted.

    Design: Corner/validations/restricted_posture_blocks_inbound_cash_only
    """
    branch = fx.register_branch(
        api, code="BR-GIB", name="Gibraltar", vault_limit_usd_cents=100_000
    )
    currency = fx.register_currency(api)
    wholesale = fx.record_wholesale_rate(api)
    card = fx.published_rate_card(api, branch["id"], wholesale["id"])
    customer = fx.onboard_customer(api, home_branch_id=branch["id"])
    world = {"branch": branch, "customer": customer, "card": card, "currency": currency}

    buy = fx.quote_deal(
        api, world, "BUY_FX_FROM_CUSTOMER", [f.denom(10000, 1)], teller_headers
    )
    sell = fx.quote_deal(
        api, world, "SELL_FX_TO_CUSTOMER", [f.denom(10000, 1)], teller_headers
    )
    position = fx.open_position(
        api, branch["id"], "EUR", [f.denom(2000, 1), f.denom(10000, 9)]
    )

    restricted = fx.read_branch(api, branch["id"])
    a.assert_vault_state(restricted, 100000, 10000, "RESTRICTED")

    validate_error(
        api.authorize_transaction(buy["id"], teller_headers),
        ApiErrorId.ERR_BRANCH_POSTURE_RESTRICTED,
        409,
    )
    assert fx.read_transaction(api, buy["id"])["settlement_status"] == "QUOTED"

    validate_error(
        api.create_cash_shipment(
            f.create_cash_shipment_payload(
                branch["id"], "EUR", "REPLENISHMENT", [f.denom(10000, 5)]
            ),
            treasury_headers,
        ),
        ApiErrorId.ERR_BRANCH_POSTURE_RESTRICTED,
        409,
    )

    fx.authorize_deal(api, sell["id"], teller_headers)
    settled = fx.settle_deal(api, sell["id"], teller_headers)
    a.assert_settlement_money(settled, 11382, 400, 11782)

    drained = fx.read_position(api, position["id"])
    a.assert_position_mix_invariants(drained)
    a.assert_mix_counts(drained, 10000, available=8)
    a.assert_mix_counts(drained, 2000, available=1)
    assert drained["total_minor_units"] == 82000
    assert drained["usd_equivalent_cents"] == 89130
    a.assert_vault_state(fx.read_branch(api, branch["id"]), 89130, 8913, "OPEN")

    shipment = validate_success(
        api.create_cash_shipment(
            f.create_cash_shipment_payload(
                branch["id"], "EUR", "REPLENISHMENT", [f.denom(10000, 5)]
            ),
            treasury_headers,
        ),
        201,
    )
    a.assert_cash_shipment(shipment)
    assert shipment["status"] == "REQUESTED"
    assert shipment["auto_generated"] is False
    assert shipment["manifest_minor_units"] == 50000
    assert shipment["manifest_usd_equivalent_cents"] == 54348


def test_three_uniqueness_keys_answer_conflict_rather_than_supersede(
    api, admin_headers, manager_headers, teller_headers
):
    """A repeated branch code, a second position for the same branch and currency and
    a second contract against the same origin deal are all 409 state precondition
    failures - the contract one even when the pinned customer version is perfectly
    current, so it is not a 412 - and the incumbent contract keeps its 20606-cent
    liability without being superseded.

    Design: Corner/validations/uniqueness_conflicts_beat_supersession_paths
    """
    world = fx.trading_world(
        api,
        branch_overrides={"code": "BR-DUB", "name": "Dublin"},
        position_mix=[f.denom(10000, 5)],
        identified=False,
    )
    txn = fx.settled_deal(
        api, world, "SELL_FX_TO_CUSTOMER", [f.denom(10000, 2)], teller_headers
    )
    a.assert_settlement_money(txn, 22763, 797, 23560)

    contract = fx.issue_contract(api, world["customer"]["id"], txn["id"])
    a.assert_buyback_contract(contract)
    assert contract["status"] == "ISSUED"
    assert contract["fee_usd_cents"] == 683
    assert contract["liability_usd_cents"] == 20606

    validate_error(
        api.create_branch(
            f.create_branch_payload(
                code="BR-DUB",
                name="Dublin Annex",
                region_code="NORTH",
                vault_limit_usd_cents=500_000,
            ),
            admin_headers,
        ),
        ApiErrorId.ERR_DUPLICATE_BRANCH_CODE,
        409,
    )
    _, branches_meta = validate_paginated(api.list_branches(admin_headers))
    assert branches_meta["total_count"] == 1

    validate_error(
        api.create_inventory_position(
            f.create_inventory_position_payload(
                world["branch"]["id"], "EUR", [f.denom(5000, 4)]
            ),
            manager_headers,
        ),
        ApiErrorId.ERR_POSITION_ALREADY_EXISTS,
        409,
    )
    position = fx.read_position(api, world["position"]["id"])
    assert _faces(position) == [10000]

    pinned = fx.customer_version(api, world["customer"]["id"])
    validate_error(
        api.create_buyback_contract(
            f.create_buyback_contract_payload(
                world["customer"]["id"], txn["id"], pinned
            ),
            teller_headers,
        ),
        ApiErrorId.ERR_CONTRACT_ALREADY_ISSUED,
        409,
    )
    assert fx.read_customer(api, world["customer"]["id"])["version"] == pinned

    incumbent = fx.read_contract(api, contract["id"])
    assert incumbent["status"] == "ISSUED"
    assert incumbent["liability_usd_cents"] == 20606
    assert incumbent["superseded_by_contract_id"] is None
    assert fx.read_transaction(api, txn["id"])["buyback_contract_id"] == contract["id"]
    assert fx.read_branch(api, world["branch"]["id"])["buyback_liability_usd_cents"] == 20606

    _, contracts_meta = validate_paginated(api.list_buyback_contracts(teller_headers))
    assert contracts_meta["total_count"] == 1


def test_every_conditional_pair_and_declared_range_is_refused_as_malformed(
    api, admin_headers, treasury_headers, teller_headers
):
    """The conditional export ceiling bites in both directions, an identification type
    without its number and expiry is malformed, both date pairs refuse a zero-length
    window, a demand index of zero is outside the declared 1-to-50000 range, two lines
    for the same face are not silently summed, and an unknown direction is out of its
    domain - eight refusals at HTTP 400 that write nothing.

    Design: Corner/validations/invalid_request_conditional_field_pairs_rejected
    """
    world = fx.trading_world(api, position_mix=[f.denom(10000, 5)], identified=False)
    branch_id = world["branch"]["id"]

    restricted_without_limit = f.restricted_currency_payload(
        iso_code="TND",
        display_name="Tunisian Dinar",
        minor_unit_digits=3,
        standard_denominations=[5000, 10000, 20000],
    )
    restricted_without_limit.pop("export_limit_minor_units")
    validate_error(
        api.create_currency(restricted_without_limit, admin_headers),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_currency(
            f.create_currency_payload(
                iso_code="SEK",
                display_name="Swedish Krona",
                standard_denominations=[10000, 50000],
                export_limit_minor_units=500_000,
            ),
            admin_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_customer(
            f.create_customer_payload(
                full_name="Half Documented",
                nationality_code="FR",
                home_branch_id=branch_id,
                id_document_type="PASSPORT",
            ),
            teller_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_travel_corridor(
            f.create_travel_corridor_payload(
                code="LHR-CDG-ZERO",
                destination_country_code="FR",
                destination_currency_code="EUR",
                season="SUMMER",
                season_start_date="2026-06-01T00:00:00Z",
                season_end_date="2026-06-01T00:00:00Z",
                demand_index_bps=10000,
            ),
            treasury_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_travel_corridor(
            f.create_travel_corridor_payload(
                code="LHR-CDG-DEMAND",
                destination_country_code="FR",
                destination_currency_code="EUR",
                season="SUMMER",
                season_start_date="2026-06-01T00:00:00Z",
                season_end_date="2026-09-01T00:00:00Z",
                demand_index_bps=0,
            ),
            treasury_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_rate_card(
            f.create_rate_card_payload(
                branch_id,
                world["wholesale"]["id"],
                fx.branch_version(api, branch_id),
                effective_from="2026-07-01T00:00:00Z",
                effective_to="2026-07-01T00:00:00Z",
            ),
            treasury_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_exchange_transaction(
            f.create_exchange_transaction_payload(
                branch_id,
                world["customer"]["id"],
                world["card"]["id"],
                "EUR",
                "SELL_FX_TO_CUSTOMER",
                [f.denom(10000, 1), f.denom(10000, 1)],
            ),
            teller_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_exchange_transaction(
            f.create_exchange_transaction_payload(
                branch_id,
                world["customer"]["id"],
                world["card"]["id"],
                "EUR",
                "SELL",
                [f.denom(10000, 1)],
            ),
            teller_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )

    _, currencies_meta = validate_paginated(api.list_currencies(admin_headers))
    assert currencies_meta["total_count"] == 1
    _, corridors_meta = validate_paginated(api.list_travel_corridors(treasury_headers))
    assert corridors_meta["total_count"] == 0
    _, cards_meta = validate_paginated(api.list_rate_cards(treasury_headers))
    assert cards_meta["total_count"] == 1
    _, deals_meta = validate_paginated(api.list_exchange_transactions(teller_headers))
    assert deals_meta["total_count"] == 0
    _, customers_meta = validate_paginated(api.list_customers(teller_headers))
    assert customers_meta["total_count"] == 1
