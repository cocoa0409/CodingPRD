"""Depth tests for transitive cascades across entities."""
from test_helpers import (
    api_client,
    buy_title,
    create_buyer,
    create_key_batch_payload,
    create_purchase_payload,
    create_released_title,
    create_title,
    get_success_data,
    make_developer_headers,
    make_user_headers,
    read_title,
    record_playtime,
    request_refund,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    ApiErrorId,
    TEST_USERS,
)

OPS = TEST_USERS["platform_ops_headers"]
TRUST = TEST_USERS["trust_safety_headers"]


class TestRefundCascadeToKeyBatchGate:
    def test_second_refund_trips_abuse_flag_and_blocks_batch_approval(self):
        """PRD §3.4: "A title's `refund_abuse_flag` turns true when its
        `lifetime_refund_events` is greater than zero and that count exceeds
        thirty percent of the title's lifetime completed sales (purchases in
        `COMPLETED` or `PARTIALLY_REFUNDED` status)."

        Design: Difficulty/transitive_cascade/refund_cascades_through_title_tier_to_key_batch_gate
        """
        developer, title = create_released_title(base_price_usd_cents=1000)
        dev_headers = make_developer_headers(developer["id"])
        buyers = [create_buyer() for _ in range(4)]
        purchases = [buy_title(b, title) for b in buyers]

        record_playtime(purchases[1], buyers[1], 200)

        # First refund auto-approves (0 playtime, same day).
        rr1 = request_refund(purchases[0], buyers[0], reason="not fun")
        assert rr1["status"] == "APPROVED"
        # Second refund fails the playtime clause, stays REQUESTED, manual approve.
        rr2 = request_refund(purchases[1], buyers[1], reason="ran badly")
        assert rr2["status"] == "REQUESTED"
        get_success_data(api_client.approve_refund_request(rr2["id"], TRUST))

        title_read = read_title(title["id"], developer)
        assert title_read["refund_abuse_flag"] is True
        # 4 x 1000 credited, two full 1000-cent refunds debited.
        assert title_read["lifetime_recognized_revenue_usd_cents"] == 2000

        batch = get_success_data(
            api_client.create_key_batch(
                create_key_batch_payload(title["id"], requested_quantity=100, free_keys_in_batch=0),
                dev_headers,
            )
        )
        res = api_client.approve_key_batch(batch["id"], OPS)
        validate_error(res, ApiErrorId.ERR_GRAY_MARKET_RISK)
        batch_read = get_success_data(api_client.get_key_batch(batch["id"], dev_headers))
        assert batch_read["status"] == "REQUESTED"

    def test_refund_cascade_recomputes_flag_from_refund_events_vs_sales(self):
        """PRD §3.6: "the title's `refund_abuse_flag` must be false — a
        gray-market control whose violation is rejected with
        `ERR_GRAY_MARKET_RISK` (HTTP 422)"

        Design: Difficulty/transitive_cascade/refund_cascades_through_title_tier_to_key_batch_gate
        """
        developer, title = create_released_title(base_price_usd_cents=1000)
        buyers = [create_buyer() for _ in range(2)]
        purchases = [buy_title(b, title) for b in buyers]

        # One refund out of one remaining sale: 1 > 0.30 * 1 -> flag true.
        rr1 = request_refund(purchases[0], buyers[0], reason="refund me")
        assert rr1["status"] == "APPROVED"

        title_read = read_title(title["id"], developer)
        assert title_read["lifetime_refund_events"] == 1
        assert title_read["refund_abuse_flag"] is True
        assert title_read["lifetime_recognized_revenue_usd_cents"] == 1000

        batch = get_success_data(
            api_client.create_key_batch(
                create_key_batch_payload(title["id"], requested_quantity=5, free_keys_in_batch=0),
                make_developer_headers(developer["id"]),
            )
        )
        res = api_client.approve_key_batch(batch["id"], OPS)
        validate_error(res, ApiErrorId.ERR_GRAY_MARKET_RISK)


class TestDeveloperSuspendCascade:
    def test_suspend_delists_released_title_and_blocks_purchase(self):
        """PRD §3.1: "Suspension is deliberately blunt: every title of that
        developer currently in `RELEASED` or `RELEASE_SCHEDULED` cascades to
        `DELISTED`, and new purchases and key requests for all of the
        developer's titles are blocked while the suspension holds."

        Design: Difficulty/transitive_cascade/developer_suspend_delists_title_then_blocks_sale
        """
        developer, title = create_released_title(base_price_usd_cents=500)
        buyer = create_buyer()

        get_success_data(api_client.suspend_developer(developer["id"], OPS))

        title_read = read_title(title["id"], developer)
        assert title_read["status"] == "DELISTED"

        res = api_client.create_purchase(
            create_purchase_payload(buyer["id"], title["id"]),
            make_user_headers(buyer["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

        purchases, _meta = validate_paginated(
            api_client.list_purchases(OPS, params={"user_account_id": buyer["id"]})
        )
        assert purchases == []

    def test_suspend_cascade_leaves_draft_titles_but_blocks_purchases(self):
        """PRD §3.1: "every title of that developer currently in `RELEASED` or
        `RELEASE_SCHEDULED` cascades to `DELISTED`, and new purchases and key
        requests for all of the developer's titles are blocked while the
        suspension holds."

        Design: Difficulty/transitive_cascade/developer_suspend_delists_title_then_blocks_sale
        """
        developer, released = create_released_title(base_price_usd_cents=500)
        # A second title still in DRAFT is not cascaded (only RELEASED /
        # RELEASE_SCHEDULED are), but purchases are blocked for all titles.
        draft = create_title(developer, title_name="Draft Game")

        get_success_data(api_client.suspend_developer(developer["id"], OPS))

        released_read = read_title(released["id"], developer)
        assert released_read["status"] == "DELISTED"
        draft_read = read_title(draft["id"], developer)
        assert draft_read["status"] == "DRAFT"

        buyer = create_buyer()
        res = api_client.create_purchase(
            create_purchase_payload(buyer["id"], released["id"]),
            make_user_headers(buyer["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
