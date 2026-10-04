"""Cross-entity state dependencies: panels gating evaluation, products gating buys."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    CATEGORY_MANAGER_HEADERS,
    PROCUREMENT_LEAD_HEADERS,
    QA_LEAD_HEADERS,
    fixtures,
)


def test_evaluate_rejected_until_every_panel_is_scored(api):
    """Evaluate while a panel is SCHEDULED fails ERR_PANEL_INCOMPLETE; scoring fixes it.

    PRD §3.4: "Evaluating a `CLOSED` tender moves it `CLOSED → EVALUATING` and requires that every bid of the tender has exactly one panel and that every such panel is `SCORED`; otherwise the evaluation is rejected with `ERR_PANEL_INCOMPLETE`."

    Design: Difficulty/cross_entity_state_dependency/evaluate_requires_all_panels_scored
    """
    category = fixtures.create_category(api)
    sup_a = fixtures.create_supplier(api, name="Sup A")
    sup_b = fixtures.create_supplier(api, name="Sup B")
    product = fixtures.create_product(api, category["id"], unit_cost_cents=200)
    tender = fixtures.create_open_tender(api, product["id"], bid_ceiling_cents=1000)

    bid_a = fixtures.submit_bid(api, tender["id"], sup_a, 700)
    bid_b = fixtures.submit_bid(api, tender["id"], sup_b, 800)
    fixtures.score_bid_panel(api, bid_a, 80, sample_code="BLIND-A1")
    # Panel B is scheduled but deliberately left unscored.
    panel_b = fixtures._ok(
        api.create_panel(bid_b["id"], {"sample_code": "BLIND-B1"}, QA_LEAD_HEADERS),
        "create_panel",
    )
    validate_success(api.close_tender(tender["id"], PROCUREMENT_LEAD_HEADERS))

    rejected = api.evaluate_tender(tender["id"], PROCUREMENT_LEAD_HEADERS)
    validate_error(rejected, "ERR_PANEL_INCOMPLETE", 409)

    validate_success(api.score_panel(panel_b["id"], {"score": 70}, QA_LEAD_HEADERS))
    evaluated = validate_success(api.evaluate_tender(tender["id"], PROCUREMENT_LEAD_HEADERS))
    assert evaluated["status"] == "EVALUATING"


def test_evaluate_rejected_when_a_bid_has_no_panel(api):
    """A bid with no panel at all also blocks evaluation.

    PRD §3.4: "Evaluating a `CLOSED` tender moves it `CLOSED → EVALUATING` and requires that every bid of the tender has exactly one panel and that every such panel is `SCORED`; otherwise the evaluation is rejected with `ERR_PANEL_INCOMPLETE`."

    Design: Difficulty/cross_entity_state_dependency/evaluate_requires_all_panels_scored
    """
    category = fixtures.create_category(api)
    sup_a = fixtures.create_supplier(api)
    sup_b = fixtures.create_supplier(api)
    product = fixtures.create_product(api, category["id"])
    tender = fixtures.create_open_tender(api, product["id"], bid_ceiling_cents=1000)

    bid_a = fixtures.submit_bid(api, tender["id"], sup_a, 700)
    fixtures.submit_bid(api, tender["id"], sup_b, 800)  # no panel for B at all
    fixtures.score_bid_panel(api, bid_a, 80, sample_code="BLIND-A1")
    validate_success(api.close_tender(tender["id"], PROCUREMENT_LEAD_HEADERS))

    response = api.evaluate_tender(tender["id"], PROCUREMENT_LEAD_HEADERS)
    validate_error(response, "ERR_PANEL_INCOMPLETE", 409)


def test_finds_activation_blocked_while_product_discontinued(api):
    """Activation while the product is DISCONTINUED fails; after reactivation it succeeds.

    PRD §3.5: "Second, the tendered product must still be `ACTIVE`, else `ERR_PRODUCT_NOT_ACTIVE`."
    PRD §3.5: "Activating an `ALLOCATED` buy moves it `ALLOCATED → ON_SALE` under three conditions, all enforced."

    Design: Difficulty/cross_entity_state_dependency/finds_activation_requires_product_active
    """
    category = fixtures.create_category(api)
    product = fixtures.active_finds_product(api, category)

    fixtures.create_store(api)
    buy = fixtures.create_finds_buy(
        api, product["id"], total_quantity=5,
        week_start_date="2026-09-07", week_end_date="2026-09-13",
    )
    buy = fixtures.plan_allocations(api, buy)

    # The product leaves ACTIVE after the buy is planned; activation must refuse.
    validate_success(api.discontinue_product(product["id"], CATEGORY_MANAGER_HEADERS))
    rejected = api.activate_finds_buy(buy["id"], CATEGORY_MANAGER_HEADERS)
    validate_error(rejected, "ERR_PRODUCT_NOT_ACTIVE", 409)

    validate_success(api.reactivate_product(product["id"], CATEGORY_MANAGER_HEADERS))

    activated = validate_success(api.activate_finds_buy(buy["id"], CATEGORY_MANAGER_HEADERS))
    assert activated["status"] == "ON_SALE"


def test_finds_buy_creation_rejected_against_proposed_product(api):
    """A Finds buy against a product that is not ACTIVE fails at creation too.

    PRD §3.5: "The referenced product must be a `FINDS` product in `ACTIVE` status; buying against any other product is rejected with `ERR_PRODUCT_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/finds_activation_requires_product_active
    """
    category = fixtures.create_category(api)
    product = fixtures.create_product(
        api, category["id"], kind="FINDS", shelf_ready_packaging=True, barcode_count=3,
    )
    response = api.create_finds_buy(
        {"product_id": product["id"], "week_start_date": "2026-09-07",
         "week_end_date": "2026-09-13", "total_quantity": 5},
        CATEGORY_MANAGER_HEADERS,
    )
    validate_error(response, "ERR_PRODUCT_NOT_ACTIVE", 409)
