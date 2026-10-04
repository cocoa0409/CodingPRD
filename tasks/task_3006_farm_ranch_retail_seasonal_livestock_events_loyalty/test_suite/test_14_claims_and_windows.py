"""Mortality claims (open/review/windows) and sale-window daily-capacity
corners."""

from test_helpers import (
    ApiErrorId,
    create_account,
    create_chick_order_payload,
    create_on_sale_lot,
    create_open_store,
    create_published_schedule,
    make_customer_headers,
    place_chick_order,
    set_clock,
    setup_fulfilled_order,
    setup_spring_store,
    TEST_USERS,
    ts_iso,
    validate_error,
    validate_success,
)

RA = TEST_USERS["regional_admin_headers"]
MGR = TEST_USERS["store_manager_headers"]
ASSOC = TEST_USERS["store_associate_headers"]

SPRING_NOW = "2026-03-10T10:00:00Z"


def test_mortality_claim_approval_posts_refund_and_goodwill(api):
    """PRD §3.5: "Approval computes the remedy: the `refund_cents` for the claim is the order's `total_cents` multiplied by the `claimed_mortality_count` and divided by the order's `quantity`, rounded half-up to integer cents; goodwill points equal the refund in cents divided by 100, rounded down to a whole point."
    PRD §3.5: "Approval moves `claim_status` to `APPROVED`, adds the claimed count into `approved_claim_count`, accumulates the refund into the order's `refund_cents`, and posts an `ADJUSTMENT` ledger entry for the goodwill points to the order's loyalty account."
    PRD §3.5: "Rejection moves `claim_status` to `REJECTED` with no financial effect."

    Design: Corner/endpoints/mortality_claim_approval_posts_refund_and_goodwill
    """
    ctx = setup_fulfilled_order(quantity=6)
    cust = make_customer_headers(ctx["account"]["id"])

    # Order A: claim 2 birds, approve.
    claimed = validate_success(
        api.create_mortality_claim(ctx["order"]["id"], {"mortality_count": 2}, cust),
        expected_status=201,
    )
    assert claimed["claim_status"] == "CLAIMED"

    reviewed = validate_success(
        api.review_mortality_claim(ctx["order"]["id"], {"decision": "APPROVE"}, MGR)
    )
    assert reviewed["claim_status"] == "APPROVED"
    assert reviewed["refund_cents"] == 698  # round_half_up(2094 x 2/6)
    assert reviewed["approved_claim_count"] == 2

    acct = validate_success(api.get_loyalty_account(ctx["account"]["id"], ASSOC))
    assert acct["points_balance"] == 6  # floor(698/100) goodwill points

    # Order B: claim 1 bird, reject — no financial effect.
    ctx_b = setup_fulfilled_order(quantity=6)
    cust_b = make_customer_headers(ctx_b["account"]["id"])
    validate_success(
        api.create_mortality_claim(ctx_b["order"]["id"], {"mortality_count": 1}, cust_b),
        expected_status=201,
    )
    rejected = validate_success(
        api.review_mortality_claim(ctx_b["order"]["id"], {"decision": "REJECT"}, MGR)
    )
    assert rejected["claim_status"] == "REJECTED"
    assert rejected["refund_cents"] == 0

    acct_b = validate_success(api.get_loyalty_account(ctx_b["account"]["id"], ASSOC))
    assert acct_b["points_balance"] == 0


def test_claim_exceeds_remaining_after_partial_approval(api):
    """PRD §3.5: "The claimed count must not exceed the order's `quantity` minus its already-`approved_claim_count`; an over-claim fails with `ERR_CLAIM_EXCEEDS_REMAINING`."

    Design: Corner/endpoints/claim_exceeds_remaining_after_partial_approval
    """
    ctx = setup_fulfilled_order(quantity=6)
    cust = make_customer_headers(ctx["account"]["id"])

    validate_success(
        api.create_mortality_claim(ctx["order"]["id"], {"mortality_count": 2}, cust),
        expected_status=201,
    )
    validate_success(
        api.review_mortality_claim(ctx["order"]["id"], {"decision": "APPROVE"}, MGR)
    )

    over = api.create_mortality_claim(ctx["order"]["id"], {"mortality_count": 5}, cust)
    validate_error(over, ApiErrorId.ERR_CLAIM_EXCEEDS_REMAINING)

    exact = validate_success(
        api.create_mortality_claim(ctx["order"]["id"], {"mortality_count": 4}, cust),
        expected_status=201,
    )
    assert exact["claim_status"] == "CLAIMED"


def test_claim_window_48h_boundary(api):
    """PRD §3.5: "The claim must be opened within 48 hours of `fulfilled_at`; a later attempt fails with `ERR_CLAIM_WINDOW_EXPIRED`."

    Design: Corner/validations/claim_window_48h_boundary
    """
    ctx = setup_fulfilled_order(clock=SPRING_NOW, quantity=6)
    cust = make_customer_headers(ctx["account"]["id"])
    assert ctx["order"]["fulfilled_at"] == ts_iso(SPRING_NOW)

    # Exactly 48 hours after fulfillment: the boundary is inclusive.
    set_clock("2026-03-12T10:00:00Z")
    claimed = validate_success(
        api.create_mortality_claim(ctx["order"]["id"], {"mortality_count": 1}, cust),
        expected_status=201,
    )
    assert claimed["claim_status"] == "CLAIMED"


def test_claim_one_second_past_48h_window_expired(api):
    """PRD §3.5: "The claim must be opened within 48 hours of `fulfilled_at`; a later attempt fails with `ERR_CLAIM_WINDOW_EXPIRED`."

    Design: Corner/validations/claim_window_48h_boundary
    """
    ctx = setup_fulfilled_order(clock=SPRING_NOW, quantity=6)
    cust = make_customer_headers(ctx["account"]["id"])

    set_clock("2026-03-12T10:00:01Z")
    resp = api.create_mortality_claim(ctx["order"]["id"], {"mortality_count": 1}, cust)
    validate_error(resp, ApiErrorId.ERR_CLAIM_WINDOW_EXPIRED)


def test_posture_gate_blocks_chick_order_outside_spring(api):
    """PRD §3.4: "Chick orders are a `Customer`-only affair, and they exist only in spring: creating one requires the selling store's posture to be `SPRING_PLANTING`, failing otherwise with `ERR_POSTURE_NOT_SPRING_PLANTING`."

    Design: Corner/validations/posture_gate_blocks_chick_order_outside_spring
    """
    set_clock(SPRING_NOW)
    store = create_open_store(season="WINTER_HEATING", name="Winter Store")
    schedule = create_published_schedule(store)
    lot = create_on_sale_lot(store, schedule)
    account = create_account()

    resp = api.create_chick_order(
        create_chick_order_payload(
            store["id"], lot["id"], account["id"], lot["version"], quantity=6,
        ),
        make_customer_headers(account["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_POSTURE_NOT_SPRING_PLANTING)


def test_chick_order_past_sale_window_temporal_rejection(api):
    """PRD §3.4: "The `pickup_date` must fall inside the schedule's closed sale window, failing otherwise with `ERR_OUTSIDE_SALE_WINDOW`."

    Design: Corner/validations/chick_order_past_sale_window_temporal_rejection
    """
    ctx = setup_spring_store()
    account = create_account()

    # Clock one instant past sale_window_end (2026-04-30T23:59:59Z); the
    # submitted pickup_date is inside the window, so only the clock position
    # can reject.
    set_clock("2026-05-01T00:00:00Z")
    resp = api.create_chick_order(
        create_chick_order_payload(
            ctx["store"]["id"], ctx["lot"]["id"], account["id"],
            ctx["lot_version"], quantity=6, pickup_date="2026-03-12T10:00:00Z",
        ),
        make_customer_headers(account["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_SALE_WINDOW)


def test_daily_capacity_counts_same_day_reservations_only(api):
    """PRD §3.4: "must not push the birds reserved across all lots of that schedule past its `daily_capacity` for the current UTC date (otherwise `ERR_DAILY_CAPACITY_EXCEEDED`)"
    PRD §3.2: "The schedule also carries `daily_capacity`, the maximum birds reservable across all lots of this schedule per UTC calendar day"

    Design: Corner/validations/daily_capacity_counts_same_day_reservations_only
    """
    set_clock(SPRING_NOW)
    store = create_open_store(
        season="SPRING_PLANTING", aisle_count=2,
        name="Waxahachie Farm & Ranch", region_code="TX-NORTH",
    )
    schedule = create_published_schedule(
        store, species="CHICKEN_MEAT", breed="Cornish Cross",
        daily_capacity=10, min_purchase_qty=4, base_price_cents_per_bird=299,
    )
    lot = create_on_sale_lot(store, schedule)
    account = create_account()
    cust = make_customer_headers(account["id"])

    first = place_chick_order(store, lot, account, quantity=6,
                              lot_version=lot["version"])
    assert first["status"] == "RESERVED"

    # 6 + 5 > 10 on the same UTC day.
    over = api.create_chick_order(
        create_chick_order_payload(
            store["id"], lot["id"], account["id"], lot["version"] + 1, quantity=5,
        ),
        cust,
    )
    validate_error(over, ApiErrorId.ERR_DAILY_CAPACITY_EXCEEDED)

    # The daily counter resets on the next UTC day.
    set_clock("2026-03-11T09:00:00Z")
    fresh_lot = validate_success(api.get_livestock_lot(lot["id"], MGR))
    second = validate_success(
        api.create_chick_order(
            create_chick_order_payload(
                store["id"], lot["id"], account["id"], fresh_lot["version"],
                quantity=6,
            ),
            cust,
        ),
        expected_status=201,
    )
    assert second["status"] == "RESERVED"
