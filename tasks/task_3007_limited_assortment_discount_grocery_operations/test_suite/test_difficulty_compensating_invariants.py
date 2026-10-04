"""Compensating invariants: cart coin insert/return and claim approve/rescind."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import CUSTOMER_SERVICE_HEADERS, fixtures, make_store_manager_headers
from test_helpers.factories import cart_coin_event_payload


def _reconciliation(api, store):
    return validate_success(
        api.get_cart_reconciliation(store["id"], make_store_manager_headers(store["id"]))
    )


def test_cart_insert_then_compensating_return_restores_zero(api):
    """INSERT 5 then RETURN 5 leaves outstanding 0 and liability 0 — no drift.

    PRD §3.6: "The store's `coins_outstanding` — coins currently held by customers in carts — is derived by replaying the store's events in `created_at` ascending order (timestamps carry three fractional digits, and `id` is never used for ordering): an `INSERT` adds its `coin_count`, a `RETURN` and a `CORRAL_COLLECT` each subtract theirs, and an `AUDIT_ADJUST` adds its signed `coin_count`."
    PRD §3.6: "The store's `coin_liability_cents` is the outstanding count multiplied by 25 — the quarter deposit per cart."

    Design: Difficulty/compensating_invariant/cart_insert_return_conserve_liability
    """
    store = fixtures.create_store(api)
    manager = make_store_manager_headers(store["id"])

    validate_success(
        api.create_cart_coin_event(store["id"], cart_coin_event_payload("INSERT", 5), manager),
        201,
    )
    mid = _reconciliation(api, store)
    assert mid["coins_outstanding"] == 5
    assert mid["coin_liability_cents"] == 125, "5 coins at 25 cents each"

    validate_success(
        api.create_cart_coin_event(store["id"], cart_coin_event_payload("RETURN", 5), manager),
        201,
    )
    end = _reconciliation(api, store)
    assert end["coins_outstanding"] == 0, "the compensating return restores zero"
    assert end["coin_liability_cents"] == 0


def test_cart_insert_return_intermediate_state_visible_on_store_read(api):
    """The intermediate 5-coin / 125-cent state shows on the store resource itself.

    PRD §3.6: "The store's `coin_liability_cents` is the outstanding count multiplied by 25 — the quarter deposit per cart."

    Design: Difficulty/compensating_invariant/cart_insert_return_conserve_liability
    """
    store = fixtures.create_store(api)
    manager = make_store_manager_headers(store["id"])

    validate_success(
        api.create_cart_coin_event(store["id"], cart_coin_event_payload("INSERT", 5), manager),
        201,
    )
    read_store = validate_success(api.get_store(store["id"], manager))
    assert read_store["coins_outstanding"] == 5
    assert read_store["coin_liability_cents"] == 125

    validate_success(
        api.create_cart_coin_event(store["id"], cart_coin_event_payload("RETURN", 5), manager),
        201,
    )
    read_store = validate_success(api.get_store(store["id"], manager))
    assert read_store["coins_outstanding"] == 0
    assert read_store["coin_liability_cents"] == 0


def _store_refund_ledgers(api, store):
    read = validate_success(
        api.get_store(store["id"], CUSTOMER_SERVICE_HEADERS)
    )
    return read["refund_liability_cents"], read["refund_paid_cents"]


def test_claim_approve_then_rescind_fully_compensates_liability(api):
    """Approve +1047 liability; rescind returns liability to 0 and paid stays 0.

    PRD §3.9: "Approval immediately increases the store's `refund_liability_cents` by the computed amount."
    PRD §3.9: "Rescission is the compensating reversal for an approval that should not have stood: it moves the claim `APPROVED → RESCINDED` and decreases the store's `refund_liability_cents` by `refund_amount_cents`, fully compensating the approval without touching `refund_paid_cents`."

    Design: Difficulty/compensating_invariant/claim_approve_rescind_conserve_refund_liability
    """
    world = fixtures.claims_world(api)
    store = world["store"]
    claim = fixtures.claim_under_review(
        api, world["product"]["id"], store["id"],
        quantity=3, unit_price_cents=349, reason="DAMAGED",
    )

    validate_success(api.approve_claim(claim["id"], CUSTOMER_SERVICE_HEADERS))
    liability, paid = _store_refund_ledgers(api, store)
    assert liability == 1047, f"349*3 accrues 1047 of liability, got {liability}"
    assert paid == 0

    rescinded = validate_success(api.rescind_claim(claim["id"], CUSTOMER_SERVICE_HEADERS))
    assert rescinded["status"] == "RESCINDED"

    liability, paid = _store_refund_ledgers(api, store)
    assert liability == 0, "rescission fully compensates the approval"
    assert paid == 0, "rescission never touches refund_paid_cents"


def test_claim_rescind_does_not_touch_paid_total(api):
    """Rescinding one approved claim leaves a separate paid claim's ledger intact.

    PRD §3.9: "Payout moves it `APPROVED → PAID`: the store's `refund_liability_cents` decreases by `refund_amount_cents` and its `refund_paid_cents` increases by the same amount — the cumulative record of refunds actually disbursed."
    PRD §3.9: "Rescission is the compensating reversal for an approval that should not have stood: it moves the claim `APPROVED → RESCINDED` and decreases the store's `refund_liability_cents` by `refund_amount_cents`, fully compensating the approval without touching `refund_paid_cents`."

    Design: Difficulty/compensating_invariant/claim_approve_rescind_conserve_refund_liability
    """
    world = fixtures.claims_world(api)
    store, product = world["store"], world["product"]

    claim_a = fixtures.claim_under_review(
        api, product["id"], store["id"], quantity=1, unit_price_cents=349, reason="DAMAGED",
    )
    claim_b = fixtures.claim_under_review(
        api, product["id"], store["id"], quantity=1, unit_price_cents=349, reason="OTHER",
    )
    validate_success(api.approve_claim(claim_a["id"], CUSTOMER_SERVICE_HEADERS))
    validate_success(api.pay_claim(claim_a["id"], CUSTOMER_SERVICE_HEADERS))
    validate_success(api.approve_claim(claim_b["id"], CUSTOMER_SERVICE_HEADERS))
    validate_success(api.rescind_claim(claim_b["id"], CUSTOMER_SERVICE_HEADERS))

    liability, paid = _store_refund_ledgers(api, store)
    assert liability == 0, f"only claim B's liability, then rescinded: 0, got {liability}"
    assert paid == 349, f"claim A's payout stays recorded: 349, got {paid}"
