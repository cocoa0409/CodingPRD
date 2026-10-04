"""Products (round-trip reads, enum discipline) and commodity contracts
(defaults, hedge bounds, and the provisional-vs-final landed-cost variants).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    Commodity,
    CommodityContractStatus,
    ProductKind,
    TEST_USERS,
    api_client,
    assert_commodity_contract,
    assert_product,
    compute_effective_spend_cents,
    compute_provisional_spend_cents,
    create_commodity_contract_payload,
    create_product,
    create_product_payload,
    setup_program,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CM = TEST_USERS["category_manager_headers"]


def test_product_get_round_trips_the_stored_configuration(api):
    """PRD §3.1: "Every product has a globally unique `sku_code` — a duplicate
    is rejected with `ERR_DUPLICATE_RESOURCE` — a free-form `molded_shape` name
    (a pumpkin, a heart, an egg, or the everyday standard bar), a positive
    `units_per_case`, and two flags that matter later: `brand_protected`,
    marking a branded molded shape that may never be diverted to the secondary
    channel, and `requires_temp_control`, marking heat-sensitive product whose
    summer shipments receive special claim treatment."

    Design: Corner/entities/product_get_round_trips_the_stored_configuration
    """
    program = setup_program()
    created = create_product(
        program["id"],
        sku_code="HAL-PUMP-0499",
        kind="SEASONAL",
        molded_shape="pumpkin",
        brand_protected=True,
        requires_temp_control=True,
        units_per_case=24,
    )
    resp = api_client.get_product(created["id"], CM)
    data = validate_success(resp, 200)
    assert_product(data)
    assert data["sku_code"] == "HAL-PUMP-0499"
    assert data["kind"] == ProductKind.SEASONAL.value
    assert data["molded_shape"] == "pumpkin"
    assert data["brand_protected"] is True
    assert data["requires_temp_control"] is True
    assert data["units_per_case"] == 24
    assert data["program_id"] == program["id"]
    assert data["version"] == 1

    reread = validate_success(api_client.get_product(created["id"], CM), 200)
    assert reread == data, "an immediate re-read must show identical values"


def test_product_create_kind_out_of_enum_returns_invalid_request(api):
    """PRD §3.1: "Products come in two kinds, declared at creation in the
    `kind` field as exactly `SEASONAL` or `EVERYDAY`." PRD §2.8: "a request
    with a missing required field, a wrong-typed value, an out-of-enum value,
    or a violated field constraint ... is rejected with `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/product_create_kind_out_of_enum_returns_invalid_request
    """
    program = setup_program()
    resp = api_client.create_product(
        create_product_payload(
            program_id=program["id"], sku_code="BAD-ENUM-1", kind="WEEKLY",
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    rows, _meta = validate_paginated(
        api_client.list_products(ADMIN, params={"program_id": program["id"]})
    )
    assert rows == [], "the rejected product must not be persisted"


def test_contract_create_omitting_hedge_fields_defaults_hedged_zero(api):
    """PRD §3.3: "A hedge is optional: `hedged_quantity_units` defaults to 0,
    may not exceed `quantity_units`, and whenever it is greater than zero a
    `hedge_price_cents_per_unit` strike must be supplied"."

    Design: Corner/entities/contract_create_omitting_hedge_fields_defaults_hedged_zero
    """
    program = setup_program()
    resp = api_client.create_commodity_contract(
        create_commodity_contract_payload(
            program_id=program["id"], commodity="SUGAR",
            quantity_units=5000, contract_price_cents_per_unit=80,
        ),
        ADMIN,
    )
    data = validate_success(resp, 201)
    assert_commodity_contract(data)
    assert data["hedged_quantity_units"] == 0, "default applied, not null"
    assert data["provisional_spend_cents"] == 400000  # 5000 x 80, no hedge offset
    assert data["status"] == CommodityContractStatus.OPEN.value
    assert data["version"] == 1


def test_contract_hedged_quantity_above_contracted_returns_hedge_exceeds(api):
    """PRD §3.3: "a contract whose hedged quantity exceeds its contracted
    quantity, or that hedges without a strike price, is rejected with
    `ERR_HEDGE_EXCEEDS_QUANTITY` (HTTP 422)."

    Design: Corner/validations/contract_hedged_quantity_above_contracted_returns_hedge_exceeds
    """
    program = setup_program()
    over = api_client.create_commodity_contract(
        create_commodity_contract_payload(
            program_id=program["id"], commodity="COCOA",
            quantity_units=5000, contract_price_cents_per_unit=200,
            hedged_quantity_units=6000, hedge_price_cents_per_unit=210,
        ),
        ADMIN,
    )
    validate_error(over, ApiErrorId.ERR_HEDGE_EXCEEDS_QUANTITY)

    at_bound = api_client.create_commodity_contract(
        create_commodity_contract_payload(
            program_id=program["id"], commodity="COCOA",
            quantity_units=5000, contract_price_cents_per_unit=200,
            hedged_quantity_units=5000, hedge_price_cents_per_unit=210,
        ),
        ADMIN,
    )
    data = validate_success(at_bound, 201)
    # hedged == quantity is inclusive-allowed; payoff max(0, 200-210) == 0.
    assert data["provisional_spend_cents"] == 1000000
    assert data["provisional_spend_cents"] == compute_provisional_spend_cents(
        5000, 200, 5000, 210,
    )


def test_landed_cost_provisional_variant_priced_off_contract_price(api):
    """PRD §3.3: "At creation — and on any read while the contract remains
    `OPEN` — the **provisional** landed cost `provisional_spend_cents` is the
    contracted quantity times the contract price, reduced by the hedged
    quantity times the amount by which the contract price exceeds the hedge
    strike, with that excess counted as zero when the strike is at or above the
    contract price."

    Design: Difficulty/dual_variant_calc/landed_cost_provisional_vs_final_settlement
    """
    program = setup_program()
    cocoa = validate_success(api_client.create_commodity_contract(
        create_commodity_contract_payload(
            program_id=program["id"], commodity="COCOA",
            quantity_units=10000, contract_price_cents_per_unit=200,
            hedged_quantity_units=6000, hedge_price_cents_per_unit=210,
        ),
        ADMIN,
    ), 201)
    sugar = validate_success(api_client.create_commodity_contract(
        create_commodity_contract_payload(
            program_id=program["id"], commodity="SUGAR",
            quantity_units=5000, contract_price_cents_per_unit=80,
        ),
        ADMIN,
    ), 201)

    # Strike 210 >= contract 200, so the hedge payoff is zero while OPEN.
    assert cocoa["provisional_spend_cents"] == 2000000
    assert cocoa["provisional_spend_cents"] == compute_provisional_spend_cents(
        10000, 200, 6000, 210,
    )
    assert sugar["provisional_spend_cents"] == 400000
    assert sugar["provisional_spend_cents"] == compute_provisional_spend_cents(
        5000, 80, 0, 0,
    )
    assert cocoa["status"] == CommodityContractStatus.OPEN.value
    assert sugar["status"] == CommodityContractStatus.OPEN.value


def test_landed_cost_final_variant_priced_off_spot_at_settle(api):
    """PRD §3.3: "the **final** landed cost `effective_spend_cents` as the
    contracted quantity times the spot price, reduced by the hedged quantity
    times the amount by which the spot price exceeds the hedge strike, again
    with a zero floor. The hedge therefore pays off only when the reference
    price exceeds the strike, and the provisional and final figures diverge
    exactly when the spot price differs from the contract price."

    Design: Difficulty/dual_variant_calc/landed_cost_provisional_vs_final_settlement
    """
    program = setup_program()
    cocoa = validate_success(api_client.create_commodity_contract(
        create_commodity_contract_payload(
            program_id=program["id"], commodity="COCOA",
            quantity_units=10000, contract_price_cents_per_unit=200,
            hedged_quantity_units=6000, hedge_price_cents_per_unit=210,
        ),
        ADMIN,
    ), 201)
    sugar = validate_success(api_client.create_commodity_contract(
        create_commodity_contract_payload(
            program_id=program["id"], commodity="SUGAR",
            quantity_units=5000, contract_price_cents_per_unit=80,
        ),
        ADMIN,
    ), 201)

    settled_cocoa = validate_success(api_client.settle_commodity_contract(
        cocoa["id"], {"spot_price_cents_per_unit": 250}, ADMIN,
    ), 200)
    settled_sugar = validate_success(api_client.settle_commodity_contract(
        sugar["id"], {"spot_price_cents_per_unit": 95}, ADMIN,
    ), 200)

    # FINAL variant: 10000x250 - 6000x(250-210) = 2500000 - 240000.
    assert settled_cocoa["effective_spend_cents"] == 2260000
    assert settled_cocoa["effective_spend_cents"] == compute_effective_spend_cents(
        10000, 250, 6000, 210,
    )
    # Same inputs, two variants: delta == hedge payoff 240000 + spot drift.
    assert settled_cocoa["effective_spend_cents"] != cocoa["provisional_spend_cents"]
    assert settled_sugar["effective_spend_cents"] == 475000  # 5000x95, no hedge
    assert settled_sugar["effective_spend_cents"] == compute_effective_spend_cents(
        5000, 95, 0, 0,
    )
    assert settled_cocoa["status"] == CommodityContractStatus.SETTLED.value
    assert settled_sugar["status"] == CommodityContractStatus.SETTLED.value
