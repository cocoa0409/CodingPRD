"""The entity surface: declared defaults, immutable reference data, the 404
catalogue, request well-formedness and the flat cross-reference topology.

PRD 3.1 fixes what a freshly registered branch looks like: "A freshly registered
branch begins with `posture` `OPEN`, `vault_usd_equivalent_cents` 0,
`vault_utilization_bps` 0, `buyback_liability_usd_cents` 0, `repatriation_pending`
false and `version` 1."  PRD 2.4 fixes which rows carry an audit version at all,
and PRD 2.8 rank 3 and rank 4 fix the order in which a bad request is refused.
"""

from test_helpers import (
    CLOCK_START,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assertions as a,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_branch_creation_applies_declared_defaults(api, admin_headers):
    """A branch created with only code, name, region_code and
    vault_limit_usd_cents comes back USD/ACTIVE/OPEN with a zero vault, zero
    utilisation, zero buy-back liability, repatriation_pending false, version 1
    and a created_at at the logical clock's start instant.

    Design: Corner/entities/branch_creation_applies_declared_defaults
    """
    branch = validate_success(
        api.create_branch(
            {
                "code": "BR-LHR",
                "name": "London Heathrow",
                "region_code": "SOUTH",
                "vault_limit_usd_cents": 20_000_000,
            },
            admin_headers,
        ),
        201,
    )

    a.assert_branch(branch)
    assert branch["home_currency_code"] == "USD"
    assert branch["status"] == "ACTIVE"
    assert branch["posture"] == "OPEN"
    assert branch["vault_usd_equivalent_cents"] == 0
    assert branch["vault_utilization_bps"] == 0
    assert branch["buyback_liability_usd_cents"] == 0
    assert branch["repatriation_pending"] is False
    assert branch["version"] == 1
    a.assert_timestamp_equals(branch["created_at"], CLOCK_START)


def test_currency_profile_is_immutable_and_carries_no_version(api, teller_headers):
    """The euro profile read exposes neither version nor updated_at, defaults
    damaged_note_recovery_bps to 6500, leaves export_limit_minor_units null for a
    MAJOR currency and keeps the five declared denominations in ascending order.

    Design: Corner/entities/currency_profile_is_immutable_and_carries_no_version
    """
    fx.register_currency(api)

    profile = validate_success(api.get_currency("EUR", teller_headers))

    a.assert_currency_profile(profile)
    assert "version" not in profile
    assert "updated_at" not in profile
    assert profile["damaged_note_recovery_bps"] == 6500
    assert profile["export_limit_minor_units"] is None
    assert profile["standard_denominations"] == [500, 1000, 2000, 5000, 10000]

    rows, meta = validate_paginated(api.list_currencies(teller_headers))
    assert meta["total_count"] == 1
    assert len(rows) == 1


def test_unresolvable_ids_return_not_found_for_every_entity(
    api, admin_headers, treasury_headers, manager_headers, teller_headers, compliance_headers
):
    """Each of the fourteen single-resource reads answers its own entity-specific
    404 for an unresolvable identifier, and the currency read answers
    ERR_CURRENCY_NOT_FOUND for the syntactically valid but unregistered code ZZZ.

    Design: Corner/entities/unresolvable_ids_return_not_found_for_every_entity
    """
    validate_error(
        api.get_branch(NON_EXISTENT_UUID, admin_headers), ApiErrorId.ERR_BRANCH_NOT_FOUND, 404
    )
    validate_error(
        api.get_currency("ZZZ", admin_headers), ApiErrorId.ERR_CURRENCY_NOT_FOUND, 404
    )
    validate_error(
        api.get_wholesale_rate(NON_EXISTENT_UUID, treasury_headers),
        ApiErrorId.ERR_WHOLESALE_RATE_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_travel_corridor(NON_EXISTENT_UUID, treasury_headers),
        ApiErrorId.ERR_CORRIDOR_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_armored_route(NON_EXISTENT_UUID, admin_headers),
        ApiErrorId.ERR_ROUTE_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_rate_card(NON_EXISTENT_UUID, treasury_headers),
        ApiErrorId.ERR_RATE_CARD_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_inventory_position(NON_EXISTENT_UUID, manager_headers),
        ApiErrorId.ERR_POSITION_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_inventory_plan(NON_EXISTENT_UUID, manager_headers),
        ApiErrorId.ERR_PLAN_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_customer(NON_EXISTENT_UUID, teller_headers),
        ApiErrorId.ERR_CUSTOMER_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_exchange_transaction(NON_EXISTENT_UUID, teller_headers),
        ApiErrorId.ERR_TRANSACTION_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_buyback_contract(NON_EXISTENT_UUID, teller_headers),
        ApiErrorId.ERR_CONTRACT_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_note_assessment(NON_EXISTENT_UUID, manager_headers),
        ApiErrorId.ERR_ASSESSMENT_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_compliance_report(NON_EXISTENT_UUID, compliance_headers),
        ApiErrorId.ERR_REPORT_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_cash_shipment(NON_EXISTENT_UUID, treasury_headers),
        ApiErrorId.ERR_SHIPMENT_NOT_FOUND,
        404,
    )


def test_body_foreign_keys_validated_against_not_found(
    api, treasury_headers, manager_headers
):
    """Foreign keys carried in the request body resolve against the same 404
    catalogue as path identifiers, and none of the four rejected calls touches the
    branch version or creates a row.

    Design: Corner/entities/body_foreign_keys_validated_against_not_found
    """
    branch = fx.register_branch(api)
    fx.register_currency(api)
    fx.record_wholesale_rate(api)

    validate_error(
        api.create_inventory_position(
            f.create_inventory_position_payload(
                NON_EXISTENT_UUID, "EUR", [f.denom(10000, 1)]
            ),
            manager_headers,
        ),
        ApiErrorId.ERR_BRANCH_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_inventory_position(
            f.create_inventory_position_payload(
                branch["id"], "ZZZ", [f.denom(10000, 1)]
            ),
            manager_headers,
        ),
        ApiErrorId.ERR_CURRENCY_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_rate_card(
            f.create_rate_card_payload(branch["id"], NON_EXISTENT_UUID, branch["version"]),
            treasury_headers,
        ),
        ApiErrorId.ERR_WHOLESALE_RATE_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_inventory_plan(
            f.create_inventory_plan_payload(branch["id"], NON_EXISTENT_UUID, 92),
            manager_headers,
        ),
        ApiErrorId.ERR_CORRIDOR_NOT_FOUND,
        404,
    )

    assert fx.read_branch(api, branch["id"])["version"] == 1
    _, positions_meta = validate_paginated(api.list_inventory_positions(manager_headers))
    assert positions_meta["total_count"] == 0
    _, cards_meta = validate_paginated(api.list_rate_cards(treasury_headers))
    assert cards_meta["total_count"] == 0


def test_missing_required_fields_rejected_on_creates(
    api, admin_headers, treasury_headers, teller_headers
):
    """Four creates that each omit exactly one mandatory input - a branch without
    its vault ceiling, a currency without its denominations, a wholesale quote
    without effective_at and a deal without direction - are all refused with
    ERR_INVALID_REQUEST and create nothing.

    Design: Corner/entities/missing_required_fields_rejected_on_creates
    """
    world = fx.trading_world(api, with_position=False)

    validate_error(
        api.create_branch(
            {"code": "BR-CDG", "name": "Paris CDG", "region_code": "NORTH"}, admin_headers
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_currency(
            {
                "iso_code": "CHF",
                "display_name": "Swiss Franc",
                "minor_unit_digits": 2,
                "currency_class": "MAJOR",
            },
            admin_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_wholesale_rate(
            {"currency_code": "EUR", "mid_rate_micros": 900000, "source_code": "REUTERS_MID"},
            treasury_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_exchange_transaction(
            {
                "branch_id": world["branch"]["id"],
                "customer_id": world["customer"]["id"],
                "rate_card_id": world["card"]["id"],
                "currency_code": "EUR",
                "requested_denominations": [f.denom(10000, 1)],
            },
            teller_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )

    _, branches_meta = validate_paginated(api.list_branches(admin_headers))
    assert branches_meta["total_count"] == 1
    _, currencies_meta = validate_paginated(api.list_currencies(admin_headers))
    assert currencies_meta["total_count"] == 1
    _, rates_meta = validate_paginated(api.list_wholesale_rates(treasury_headers))
    assert rates_meta["total_count"] == 1
    _, deals_meta = validate_paginated(api.list_exchange_transactions(teller_headers))
    assert deals_meta["total_count"] == 0


def test_type_and_range_constraint_violations_rejected(
    api, admin_headers, treasury_headers, teller_headers
):
    """Six distinct shape defects all land on ERR_INVALID_REQUEST: an
    out-of-domain currency_class, an export cap on a MAJOR currency, a vault
    ceiling below the 100000-cent floor, a board window whose effective_to equals
    its effective_from, a season that ends before it starts, and a document type
    with no document number.

    Design: Corner/entities/type_and_range_constraint_violations_rejected
    """
    branch = fx.register_branch(api)
    fx.register_currency(api)
    wholesale = fx.record_wholesale_rate(api)

    validate_error(
        api.create_currency(
            {
                "iso_code": "JPY",
                "display_name": "Japanese Yen",
                "minor_unit_digits": 0,
                "currency_class": "SEMI_EXOTIC",
                "standard_denominations": [1000, 5000, 10000],
            },
            admin_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_currency(
            f.chf_currency_payload(
                standard_denominations=[1000, 5000, 20000],
                export_limit_minor_units=200000,
            ),
            admin_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_branch(
            f.create_branch_payload(
                code="BR-TINY", name="Kiosk", vault_limit_usd_cents=99999
            ),
            admin_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_rate_card(
            f.create_rate_card_payload(
                branch["id"],
                wholesale["id"],
                branch["version"],
                effective_from="2026-08-01T00:00:00Z",
                effective_to="2026-08-01T00:00:00Z",
            ),
            treasury_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_travel_corridor(
            f.create_travel_corridor_payload(
                code="LHR-CMN-BAD",
                destination_country_code="MA",
                destination_currency_code="EUR",
                season="SUMMER",
                season_start_date="2026-09-01T00:00:00Z",
                season_end_date="2026-06-01T00:00:00Z",
                demand_index_bps=13500,
            ),
            treasury_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_customer(
            f.create_customer_payload(
                full_name="Omar Ali",
                nationality_code="MA",
                home_branch_id=branch["id"],
                id_document_type="PASSPORT",
            ),
            teller_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )

    _, currencies_meta = validate_paginated(api.list_currencies(admin_headers))
    assert currencies_meta["total_count"] == 1
    assert fx.read_branch(api, branch["id"])["version"] == 1


def test_rate_card_computed_rates_extra_field_input_ignored(api, treasury_headers):
    """A card create that smuggles buy_rate_micros, sell_rate_micros and a
    PUBLISHED status into the body still stores the derived 970600 and 878600 from
    the cited 920000-micro mid and the 550/450 spreads, is born DRAFT, and bumps
    the branch exactly once.

    Design: Corner/entities/rate_card_computed_rates_extra_field_input_ignored
    """
    branch = fx.register_branch(api)
    fx.register_currency(api)
    wholesale = fx.record_wholesale_rate(api)

    card = validate_success(
        api.create_rate_card(
            f.create_rate_card_payload(
                branch["id"],
                wholesale["id"],
                branch["version"],
                buy_rate_micros=111111,
                sell_rate_micros=222222,
                status="PUBLISHED",
            ),
            treasury_headers,
        ),
        201,
    )

    a.assert_rate_card(card)
    assert card["buy_rate_micros"] == 970600
    assert card["sell_rate_micros"] == 878600
    a.assert_rate_card_derivation(card, 920000)
    assert card["status"] == "DRAFT"
    assert card["superseded_by_rate_card_id"] is None
    assert card["version"] == 1
    assert fx.read_branch(api, branch["id"])["version"] == 2


def test_system_fields_generated_and_version_increments_on_writes(
    api, treasury_headers, manager_headers
):
    """The branch starts at version 1 and each declared parent-incrementing write
    moves it by exactly one, so after one card create and one position create it
    reads version 3 with its created_at untouched, while the new position is a
    distinct server-minted row at version 1 worth 10870 cents.

    Design: Corner/entities/system_fields_generated_and_version_increments_on_writes
    """
    branch = fx.register_branch(api)
    assert branch["version"] == 1
    created_at = branch["created_at"]

    fx.register_currency(api)
    wholesale = fx.record_wholesale_rate(api)
    fx.draft_rate_card(api, branch["id"], wholesale["id"], branch["version"])

    position = validate_success(
        api.create_inventory_position(
            f.create_inventory_position_payload(
                branch["id"], "EUR", [f.denom(10000, 1)]
            ),
            manager_headers,
        ),
        201,
    )

    final = fx.read_branch(api, branch["id"])
    assert final["version"] == 3
    a.assert_timestamp_equals(final["created_at"], created_at)

    a.assert_inventory_position(position)
    assert position["id"] != branch["id"]
    assert position["version"] == 1
    assert position["total_minor_units"] == 10000
    assert position["usd_equivalent_cents"] == 10870


def test_branch_listing_pagination_and_region_filter(api, admin_headers):
    """Three branches page under limit 2 with total_count 3 and has_more true,
    the second page carries the last row with has_more false, the SOUTH filter
    narrows the count to 2, the posture filter still finds all three at 0 bps, and
    the unfiltered read applies the declared limit 10 / offset 0 defaults.

    Design: Corner/entities/branch_listing_pagination_and_region_filter
    """
    first = fx.register_branch(api, code="BR-LHR", name="London Heathrow", region_code="SOUTH")
    fx.register_branch(api, code="BR-LGW", name="London Gatwick", region_code="SOUTH")
    third = fx.register_branch(api, code="BR-CDG", name="Paris CDG", region_code="NORTH")

    page_one, meta_one = validate_paginated(
        api.list_branches(admin_headers, {"limit": 2, "offset": 0})
    )
    assert len(page_one) == 2
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert page_one[0]["id"] == first["id"]

    page_two, meta_two = validate_paginated(
        api.list_branches(admin_headers, {"limit": 2, "offset": 2})
    )
    assert len(page_two) == 1
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False

    south, south_meta = validate_paginated(
        api.list_branches(admin_headers, {"region_code": "SOUTH"})
    )
    assert south_meta["total_count"] == 2
    assert south_meta["has_more"] is False
    assert third["id"] not in [row["id"] for row in south]

    _, posture_meta = validate_paginated(
        api.list_branches(admin_headers, {"posture": "OPEN"})
    )
    assert posture_meta["total_count"] == 3

    unfiltered, unfiltered_meta = validate_paginated(api.list_branches(admin_headers))
    assert unfiltered_meta["limit"] == 10
    assert unfiltered_meta["offset"] == 0
    assert len(unfiltered) == 3


def test_flat_topology_cross_reference_route_region_must_match_branch(
    api, admin_headers, treasury_headers
):
    """A SOUTH branch's shipment refuses a NORTH route with
    ERR_ROUTE_BRANCH_NOT_SERVICED and stays REQUESTED with a null route, while the
    SOUTH route accepts the identical window and the manifest values at the
    wholesale mid.

    Design: Corner/entities/flat_topology_cross_reference_route_region_must_match_branch
    """
    branch = fx.register_branch(api, code="BR-CDG", name="Paris CDG", region_code="SOUTH")
    fx.register_currency(api)
    fx.record_wholesale_rate(api)
    south = fx.register_route(
        api, code="RT-SOUTH-1", carrier_name="SecurCash", region_code="SOUTH",
        daily_capacity_usd_cents=200000,
    )
    north = fx.register_route(
        api, code="RT-NORTH-1", carrier_name="NordVault", region_code="NORTH",
        daily_capacity_usd_cents=200000,
    )
    shipment = fx.raise_shipment(
        api, branch["id"], "EUR", "REPLENISHMENT", [f.denom(10000, 4)]
    )

    validate_error(
        api.schedule_cash_shipment(
            shipment["id"],
            f.schedule_shipment_payload(
                north["id"], "2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z"
            ),
            treasury_headers,
        ),
        ApiErrorId.ERR_ROUTE_BRANCH_NOT_SERVICED,
        422,
    )

    unchanged = fx.read_shipment(api, shipment["id"])
    assert unchanged["status"] == "REQUESTED"
    assert unchanged["armored_route_id"] is None

    scheduled = validate_success(
        api.schedule_cash_shipment(
            shipment["id"],
            f.schedule_shipment_payload(
                south["id"], "2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z"
            ),
            treasury_headers,
        )
    )

    a.assert_cash_shipment(scheduled)
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["armored_route_id"] == south["id"]
    assert scheduled["manifest_minor_units"] == 40000
    assert scheduled["manifest_usd_equivalent_cents"] == 43478
