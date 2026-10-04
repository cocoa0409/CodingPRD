"""Corner queue: uniqueness and open-work singleton claims — scalar
uniqueness (sku_code) and the one-open-work-per-scope rules for cases,
divestitures, transfers, and negotiations.
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_brand,
    create_brand_term,
    create_combined_negotiation_payload,
    create_divestiture_payload,
    create_item_payload,
    create_plant,
    create_product_transfer_payload,
    create_rationalization_case_payload,
    create_retailer,
    setup_divestiture_proposed,
    setup_scored_case,
    setup_transfer_planned,
    validate_error,
)

PM = TEST_USERS["portfolio_manager_headers"]
PM_PROPOSER_2 = TEST_USERS["portfolio_manager_proposer_2_headers"]
SCP = TEST_USERS["supply_chain_planner_headers"]


def test_duplicate_sku_returns_duplicate():
    """PRD §2.9: "a brand `name` is unique across all brands, a plant `name` is
    unique across all plants, a retailer `name` is unique across all retailers,
    an item `sku_code` is unique across all items, and a capital cycle
    `period_code` is unique across all cycles; violating any of these is
    rejected with `ERR_DUPLICATE` (HTTP 409)."

    Design: Corner/validations/duplicate_sku_returns_duplicate
    """
    brand1 = create_brand()
    brand2 = create_brand()
    plant = create_plant()
    api_client.create_item(
        create_item_payload(brand1["id"], plant["id"], sku_code="SKU-VA5"), PM
    )
    # Same sku_code under a DIFFERENT brand still violates global uniqueness.
    resp = api_client.create_item(
        create_item_payload(brand2["id"], plant["id"], sku_code="SKU-VA5",
                            annual_units=100, unit_net_revenue_cents=500,
                            unit_cost_cents=400),
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE)


def test_second_open_case_returns_case_already_open():
    """PRD §2.9: "an item may have at most one open rationalization case —
    where open means `SCORED` or `EXECUTING` — and a second proposal is
    rejected with `ERR_CASE_ALREADY_OPEN`".
    PRD §3.2: "an item already in `CUT_PROPOSED` or `SELL_THROUGH` necessarily
    has an open case and the proposal is rejected with
    `ERR_CASE_ALREADY_OPEN`."

    Design: Corner/validations/second_open_case_returns_case_already_open
    """
    _, _, item, _ = setup_scored_case()  # open SCORED case -> item CUT_PROPOSED
    resp = api_client.create_rationalization_case(
        create_rationalization_case_payload(item["id"]), PM_PROPOSER_2
    )
    validate_error(resp, ApiErrorId.ERR_CASE_ALREADY_OPEN)


def test_second_open_divestiture_returns_divestiture_already_open():
    """PRD §2.9: "a brand may have at most one open divestiture — `PROPOSED`,
    `SPA_SIGNED`, or `CLOSED` — and a second proposal is rejected with
    `ERR_DIVESTITURE_ALREADY_OPEN`".

    Design: Corner/validations/second_open_divestiture_returns_divestiture_already_open
    """
    brand, _ = setup_divestiture_proposed()  # open PROPOSED divestiture
    resp = api_client.create_divestiture(
        create_divestiture_payload(brand["id"], acquirer_name="Acq Two",
                                   headline_price_cents=600000000,
                                   expected_close_date="2026-11-01T00:00:00Z"),
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_DIVESTITURE_ALREADY_OPEN)


def test_second_open_transfer_returns_transfer_already_open():
    """PRD §2.9: "an item may have at most one open product transfer —
    `PLANNED` or `QUALIFYING` — and a second plan is rejected with
    `ERR_TRANSFER_ALREADY_OPEN`".

    Design: Corner/validations/second_open_transfer_returns_transfer_already_open
    """
    _, source_plant, _, item, _ = setup_transfer_planned()  # PLANNED transfer
    third_plant = create_plant(quarterly_capacity_units=1000000)
    resp = api_client.create_product_transfer(
        create_product_transfer_payload(
            item["id"], source_plant["id"], third_plant["id"]
        ),
        SCP,
    )
    validate_error(resp, ApiErrorId.ERR_TRANSFER_ALREADY_OPEN)


def test_duplicate_period_open_negotiation_returns_negotiation_already_open():
    """PRD §3.6: "Separately, the retailer may not already hold a
    `TERMS_PROPOSED` negotiation for the same `period_code`
    (`ERR_NEGOTIATION_ALREADY_OPEN`)."

    Design: Corner/validations/duplicate_period_open_negotiation_returns_negotiation_already_open
    """
    retailer = create_retailer(risk_rating="LOW")
    brand1 = create_brand(private_label_share_pct=40)
    brand2 = create_brand(private_label_share_pct=10,
                          annual_net_revenue_cents=500000000)
    terms1 = [create_brand_term(brand1["id"], 100, 90),
              create_brand_term(brand2["id"], 60, 50)]
    api_client.create_combined_negotiation(
        create_combined_negotiation_payload(retailer["id"], terms1), PM
    )
    # Same (retailer, period_code) but a DISJOINT 2028 window: the uniqueness
    # rule is period-keyed, independent of the window-overlap rule.
    terms2 = [create_brand_term(brand1["id"], 100, 95),
              create_brand_term(brand2["id"], 60, 55)]
    resp = api_client.create_combined_negotiation(
        create_combined_negotiation_payload(
            retailer["id"], terms2,
            effective_from="2028-01-01T00:00:00Z",
            effective_to="2028-06-30T00:00:00Z",
        ),
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_NEGOTIATION_ALREADY_OPEN)
