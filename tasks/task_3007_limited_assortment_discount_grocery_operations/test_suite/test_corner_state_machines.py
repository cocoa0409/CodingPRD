"""State machine rules: initial states, terminal lockdowns, precondition enforcement."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    CATEGORY_MANAGER_HEADERS,
    CUSTOMER_SERVICE_HEADERS,
    PROCUREMENT_LEAD_HEADERS,
    fixtures,
    make_store_manager_headers,
)
from test_helpers.factories import scan_payload


def test_tender_initial_state_is_draft(api):
    """A newly created tender has status DRAFT and version 1.

    PRD §3.4: "A tender is born in `DRAFT`. Opening it moves it `DRAFT → OPEN` and admits bids; closing it moves it `OPEN → CLOSED` and freezes the bid set."
    PRD §2.4: "The `version` field is a system-managed integer that increments by exactly 1 on every mutation and underpins optimistic concurrency control."

    Design: Corner/state_machines/tender_initial_state_is_draft
    """
    category = fixtures.create_category(api)
    product = fixtures.create_product(api, category["id"])
    tender = validate_success(
        api.create_tender(
            {"product_id": product["id"], "bid_ceiling_cents": 1000}, PROCUREMENT_LEAD_HEADERS
        ),
        201,
    )
    assert tender["status"] == "DRAFT"
    assert tender["version"] == 1


def test_paid_claim_rejects_every_further_action(api):
    """PAID is terminal: a dispute against a PAID claim fails ERR_INVALID_STATE.

    PRD §3.9: "`PAID`, `REJECTED`, and `RESCINDED` are terminal. Every claim transition increments the claim's `version`."
    PRD §2.8: "5. State admissibility: the target resource is in a state that permits the operation (`ERR_INVALID_STATE`, and its state-specific counterparts such as `ERR_TENDER_NOT_OPEN` and `ERR_SHIFT_NOT_OPEN`)."

    Design: Corner/state_machines/claim_terminal_paid_lockdown
    """
    world = fixtures.claims_world(api)
    claim = fixtures.claim_under_review(
        api, world["product"]["id"], world["store"]["id"], reason="OTHER"
    )
    validate_success(api.approve_claim(claim["id"], CUSTOMER_SERVICE_HEADERS))
    validate_success(api.pay_claim(claim["id"], CUSTOMER_SERVICE_HEADERS))

    response = api.dispute_claim(claim["id"], CUSTOMER_SERVICE_HEADERS)
    validate_error(response, "ERR_INVALID_STATE", 409)


def test_scan_against_closed_shift_rejected(api):
    """Scanning a CLOSED shift fails ERR_SHIFT_NOT_OPEN and changes nothing.

    PRD §3.7: "Any scan or close attempted on a shift not in `OPEN` status is rejected with `ERR_SHIFT_NOT_OPEN`."

    Design: Corner/state_machines/double_scan_second_shift_open_rejected
    """
    world = fixtures.store_with_cashier(api)
    store, cashier = world["store"], world["cashier"]
    shift = fixtures.open_shift(api, store, cashier, opened_at="2026-09-01T08:00:00Z")

    validate_success(
        api.scan_shift(shift["id"], scan_payload(items_count=10), world["cashier_headers"])
    )
    validate_success(api.close_shift(shift["id"], make_store_manager_headers(store["id"])))

    response = api.scan_shift(
        shift["id"], scan_payload(items_count=5), world["cashier_headers"]
    )
    validate_error(response, "ERR_SHIFT_NOT_OPEN", 409)

    read = validate_success(
        api.get_register_shift(shift["id"], make_store_manager_headers(store["id"]))
    )
    assert read["items_scanned"] == 10, "the rejected scan must not change the counters"


def test_discontinue_proposed_product_rejected(api):
    """Discontinuation is only available while ACTIVE; PROPOSED fails ERR_INVALID_STATE.

    PRD §3.2: "Discontinuation is an explicit `CategoryManager` action available only while the product is `ACTIVE`. It moves the product `ACTIVE → DISCONTINUED`, recomputes the owning category's `active_sku_count` (which may auto-`OPEN` a `LOCKED` category), refreshes the product's `updated_at`, and increments its `version`."

    Design: Corner/state_machines/discontinue_nonactive_product_rejected
    """
    category = fixtures.create_category(api)
    product = fixtures.create_product(api, category["id"])
    assert product["status"] == "PROPOSED"

    response = api.discontinue_product(product["id"], CATEGORY_MANAGER_HEADERS)
    validate_error(response, "ERR_INVALID_STATE", 409)


def test_sell_side_effects_applied(api):
    """A partial sell moves sold/remaining on the allocation and remaining on the buy.

    PRD §3.5: "A recorded sale increases `sold_quantity` by `quantity` and recomputes `remaining_quantity`. If that leaves the allocation at zero remaining, it auto-transitions to `SOLD_OUT`; the buy's `remaining_quantity` is then recomputed, and if it too reaches zero the buy auto-transitions `ON_SALE → SOLD_OUT`."

    Design: Corner/state_machines/sell_side_effects_applied
    """
    category = fixtures.create_category(api)
    product = fixtures.active_finds_product(api, category)
    store = fixtures.create_store(api)
    world = fixtures.finds_buy_on_sale(
        api, product["id"], total_quantity=5,
        week_start_date="2026-09-07", week_end_date="2026-09-13",
    )
    buy, alloc = world["buy"], world["allocations"][0]
    manager = make_store_manager_headers(store["id"])

    fixtures.set_clock(api, "2026-09-08T10:00:00Z")
    sold = validate_success(api.sell_allocation(alloc["id"], {"quantity": 2}, manager))
    assert sold["sold_quantity"] == 2
    assert sold["remaining_quantity"] == 3
    assert sold["status"] == "ON_SALE"
    assert sold["version"] == alloc["version"] + 1, "the sell bumps the allocation version"

    read_buy = validate_success(api.get_finds_buy(buy["id"], CATEGORY_MANAGER_HEADERS))
    assert read_buy["remaining_quantity"] == 3
    assert read_buy["status"] == "ON_SALE"


def test_retender_rejected_when_dual_source_satisfied(api):
    """Retender with two ELIGIBLE bids from distinct suppliers fails ERR_INVALID_STATE.

    PRD §3.4: "When evaluation leaves fewer than `min_sources` distinct suppliers holding `ELIGIBLE` bids, the tender cannot be awarded but it is not dead: a retender loops it `EVALUATING → OPEN`."

    Design: Corner/state_machines/retender_requires_insufficient_eligible_sources
    """
    category = fixtures.create_category(api)
    sup_a = fixtures.create_supplier(api)
    sup_b = fixtures.create_supplier(api)
    product = fixtures.create_product(api, category["id"])
    tender, _, _ = fixtures.tender_in_evaluating(
        api, product["id"], bids=[(sup_a, 700, 80), (sup_b, 800, 70)],
    )

    response = api.retender(tender["id"], PROCUREMENT_LEAD_HEADERS)
    validate_error(response, "ERR_INVALID_STATE", 409)


def test_second_review_of_under_review_claim_rejected(api):
    """Repeating review on an already UNDER_REVIEW claim fails ERR_INVALID_STATE.

    PRD §3.9: "Review moves a claim `FILED → UNDER_REVIEW`, and the same action re-opens a `DISPUTED` claim — the cycle `UNDER_REVIEW → DISPUTED → UNDER_REVIEW` may repeat."

    Design: Corner/state_machines/claim_review_idempotent_second_attempt_rejected
    """
    world = fixtures.claims_world(api)
    claim = fixtures.file_claim(
        api, world["product"]["id"], world["store"]["id"], reason="OTHER"
    )

    first = validate_success(api.review_claim(claim["id"], CUSTOMER_SERVICE_HEADERS))
    assert first["status"] == "UNDER_REVIEW"

    second = api.review_claim(claim["id"], CUSTOMER_SERVICE_HEADERS)
    validate_error(second, "ERR_INVALID_STATE", 409)
