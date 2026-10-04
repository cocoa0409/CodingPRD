"""Cross-cutting claims: OCC on refresh, lazy offer expiry, auto-skip
reconciliation, list filtering, and immediate lock consistency
(PRD §2.11, §3.4, §3.10, §3.6)."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    add_price,
    api_client,
    cancel_subscription_and_get_offer,
    create_customer,
    create_stocked_product,
    create_subscription,
    generate_plan_for,
    get_plan,
    get_subscription_by_id,
    get_success_data,
    list_notifications,
    list_plan_lines,
    make_customer_headers,
    set_clock,
    setup_customer_with_plan,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestOptimisticConcurrency:
    def test_stale_plan_refresh_returns_412_and_version_increments_on_success(self):
        """PRD §2.11: "A refresh request must carry `expected_plan_version`,
        holding the value of the plan's `version` the client last observed. If
        the plan's current `version` differs from `expected_plan_version` —
        because some other write has advanced it since the client's last read
        — the refresh is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412),
        forcing the client to re-read the plan before re-estimating it. A
        successful refresh itself increments the plan's `version` by exactly
        1."

        Design: Corner/cross_cutting_layers/stale_plan_refresh_returns_412_and_version_increments_on_success
        """
        customer, product, placement, subs, plan = setup_customer_with_plan()
        headers = make_customer_headers(customer["id"])
        observed = get_success_data(api_client.get_plan(plan["id"], headers))
        version = observed["version"]
        refreshed = validate_success(api_client.refresh_plan(
            plan["id"], {"expected_plan_version": version}, headers))
        assert refreshed["version"] == version + 1
        stale = api_client.refresh_plan(
            plan["id"], {"expected_plan_version": version}, headers)
        validate_error(stale, ApiErrorId.ERR_STALE_PLAN_VERSION)
        assert get_plan(plan["id"])["version"] == version + 1


class TestLazyOfferExpiry:
    def _setup_expired_offer(self):
        set_clock()
        customer = create_customer()
        product, _placement = create_stocked_product()
        sub = create_subscription(customer, product)
        offer = cancel_subscription_and_get_offer(sub, customer)
        set_clock("2026-09-09T00:00:00Z")
        return customer, sub, offer

    def test_retention_offer_lazy_expiry_cancels_subscription(self):
        """PRD §3.4: "whenever the system reads or mutates the subscription,
        or reads its offers or the customer's notifications, and finds an
        `OFFERED` offer whose `expires_on` is strictly before the logical
        today, the offer flips to `EXPIRED`, the subscription flips to
        `CANCELLED`, and an `OFFER_EXPIRED` notification is created for the
        customer."

        Design: Corner/cross_cutting_layers/retention_offer_lazy_expiry_cancels_subscription
        """
        customer, sub, offer = self._setup_expired_offer()
        headers = make_customer_headers(customer["id"])
        sub_after = validate_success(api_client.get_subscription(
            sub["id"], headers))
        assert sub_after["status"] == "CANCELLED"
        offers = get_success_data(
            api_client.list_subscription_offers(sub["id"], headers))
        assert offers[0]["offer_status"] == "EXPIRED"

    def test_expired_offer_carries_expires_on_and_notification(self):
        """PRD §3.4: "Cancelling from either `ACTIVE` or `PAUSED` moves the
        subscription to `PENDING_CANCEL` and creates a RetentionOffer in
        `OFFERED` status: a fixed goodwill credit of exactly 500 cents,
        recorded as `offer_type` `CREDIT` with `credit_amount_cents` 500,
        expiring seven days after the cancellation request date (`expires_on`
        is the request date plus 7 days)."
        PRD §3.4: "the offer flips to `EXPIRED`, the subscription flips to
        `CANCELLED`, and an `OFFER_EXPIRED` notification is created for the
        customer."

        Design: Corner/cross_cutting_layers/retention_offer_lazy_expiry_cancels_subscription
        """
        customer, sub, offer = self._setup_expired_offer()
        headers = make_customer_headers(customer["id"])
        offers = get_success_data(
            api_client.list_subscription_offers(sub["id"], headers))
        assert offers[0]["offer_status"] == "EXPIRED"
        assert offers[0]["expires_on"] == "2026-09-08"
        expired_notices = list_notifications(customer, "OFFER_EXPIRED")
        assert len(expired_notices) == 1


class TestAutoSkipRecoveryOnRefresh:
    def _setup(self):
        set_clock()
        customer = create_customer()
        product, placement = create_stocked_product(price_cents=1000, units=50)
        capped = create_subscription(customer, product, price_cap_cents=1050)
        create_subscription(customer, product)
        create_subscription(customer, product)
        plan = generate_plan_for(customer)
        add_price(product["id"], price_cents=1200,
                  effective_from="2026-09-02T00:00:00Z")
        set_clock("2026-09-03T00:00:00Z")
        headers = make_customer_headers(customer["id"])
        plan_now = get_plan(plan["id"], as_customer=customer)
        refreshed = validate_success(api_client.refresh_plan(
            plan["id"], {"expected_plan_version": plan_now["version"]},
            headers))
        add_price(product["id"], price_cents=1000,
                  effective_from="2026-09-04T00:00:00Z")
        set_clock("2026-09-05T00:00:00Z")
        return customer, plan, refreshed, capped

    def test_auto_skipped_line_recovers_on_refresh_after_price_drop(self):
        """PRD §3.10: "While the plan remains `OPEN`, a refresh that finds an
        `AUTO_SKIPPED` line's conditions healed — the current unit price at or
        under the subscription's cap (or the cap null) and the product
        `IN_STOCK` in region with sufficient on hand — restores the line to
        `SCHEDULED`, clears `skip_reason`, and triggers the same
        count-tier-total recomputation chain."

        Design: Corner/cross_cutting_layers/auto_skipped_line_recovers_on_refresh_after_price_drop
        """
        customer, plan, refreshed, capped = self._setup()
        assert refreshed["active_line_count"] == 2
        assert refreshed["tier_discount_pct"] == pytest.approx(0.00)
        assert refreshed["estimated_total_cents"] == 2400
        headers = make_customer_headers(customer["id"])
        second = validate_success(api_client.refresh_plan(
            plan["id"], {"expected_plan_version": refreshed["version"]},
            headers))
        assert second["active_line_count"] == 3
        assert second["tier_discount_pct"] == pytest.approx(0.05)
        assert second["estimated_total_cents"] == 2850
        lines, _meta = validate_paginated(api_client.list_plan_lines_global(
            headers, params={"subscription_id": capped["id"]}))
        assert len(lines) == 1
        assert lines[0]["line_status"] == "SCHEDULED"


class TestPlanLineFiltering:
    def test_plan_lines_filter_by_product_id_returns_only_matching_lines(self):
        """PRD §2.3: "The `limit` parameter caps the number of returned items:
        it defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter skips a number of leading items and defaults to 0."
        PRD §4: the endpoint table lists `GET /sns/plan-lines` as "List and
        filter plan lines".

        Design: Corner/cross_cutting_layers/plan_lines_filter_by_product_id_returns_only_matching_lines
        """
        set_clock()
        customer = create_customer()
        product_a, _ = create_stocked_product(price_cents=1000, units=50)
        product_b, _ = create_stocked_product(price_cents=2000, units=50)
        create_subscription(customer, product_a)
        create_subscription(customer, product_b)
        plan = generate_plan_for(customer)
        headers = make_customer_headers(customer["id"])
        data, meta = validate_paginated(api_client.list_plan_lines_global(
            headers, params={"product_id": product_b["id"]}))
        assert len(data) == 1
        assert data[0]["product_id"] == product_b["id"]
        assert meta["total_count"] == 1
        assert meta["has_more"] is False


class TestImmediateConsistency:
    def test_lock_response_carries_final_totals_immediately(self):
        """PRD §3.6: "The plan emerges `LOCKED` with `charged_total_cents`,
        `gross_line_total_cents`, `tier_discount_pct`, and `active_line_count`
        all set."

        Design: Corner/consistency_model/lock_response_carries_final_totals_immediately
        """
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=1, price_cents=1000, quantity=2,
        )
        headers = make_customer_headers(customer["id"])
        resp = api_client.lock_plan(plan["id"], headers)
        locked = validate_success(resp)
        assert locked["plan_status"] == "LOCKED"
        assert locked["charged_total_cents"] == 2000
        assert locked["gross_line_total_cents"] == 2000
        assert locked["tier_discount_pct"] == pytest.approx(0.00)
        assert locked["active_line_count"] == 1
