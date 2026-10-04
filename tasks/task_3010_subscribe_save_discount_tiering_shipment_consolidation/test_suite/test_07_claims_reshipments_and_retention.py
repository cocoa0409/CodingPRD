"""Damage claims, refunds, reshipments, retention offers, RBAC, ownership."""
from test_helpers import (
    ApiErrorId,
    assert_inventory_conservation,
    cancel_subscription_and_get_offer,
    create_customer,
    create_product_payload,
    create_stocked_product,
    create_subscription,
    get_customer_by_id,
    get_plan,
    get_subscription_by_id,
    list_notifications,
    list_plan_lines,
    lock_plan,
    make_customer_headers,
    make_platform_admin_headers,
    make_support_agent_headers,
    report_damage_claim,
    set_clock,
    setup_customer_with_plan,
    setup_delivered_plan,
    setup_reported_claim,
    setup_shipped_plan,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = make_platform_admin_headers()
SUPPORT = make_support_agent_headers()


class TestDamageClaimPreconditions:
    def test_damage_claim_on_shipped_but_not_delivered_plan_rejected(self, api):
        """PRD §3.11: "the customer reports it on a `DELIVERED` plan — a claim
        against a plan in any other status is rejected with
        `ERR_PLAN_NOT_DELIVERED`".

        Design: Corner/state_machines/damage_claim_on_shipped_but_not_delivered_plan_rejected
        """
        customer, product, placement, subs, plan = setup_shipped_plan(
            num_subscriptions=1,
        )
        line = list_plan_lines(plan, as_customer=customer)[0]
        resp = api.create_damage_claim(
            plan["id"], {"damaged_line_ids": [line["id"]]},
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_DELIVERED.value, 409)

    def test_claim_with_empty_damaged_lines_returns_claim_lines_invalid(self, api):
        """PRD §3.11: "An empty array, an id that is not on the plan, or a line
        not in `SHIPPED` status is rejected with `ERR_CLAIM_LINES_INVALID`."

        Design: Corner/validations/claim_with_empty_damaged_lines_returns_claim_lines_invalid
        """
        customer, product, placement, subs, plan = setup_delivered_plan(
            num_subscriptions=1,
        )
        resp = api.create_damage_claim(
            plan["id"], {"damaged_line_ids": []},
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_LINES_INVALID.value, 422)

    def test_resolved_plan_rejects_new_damage_claim(self, api):
        """PRD §3.11: "the customer reports it on a `DELIVERED` plan — a claim
        against a plan in any other status is rejected with
        `ERR_PLAN_NOT_DELIVERED`".
        PRD §3.9: "Resolution moves the plan to `RESOLVED`, which is terminal."

        Design: Corner/state_machines/resolved_plan_rejects_new_damage_claim
        """
        customer, product, placement, subs, plan = setup_delivered_plan(
            num_subscriptions=1,
        )
        validate_success(api.resolve_plan(plan["id"], SUPPORT))
        line = list_plan_lines(plan, as_customer=customer)[0]
        resp = api.create_damage_claim(
            plan["id"], {"damaged_line_ids": [line["id"]]},
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_DELIVERED.value, 409)
        refreshed = get_plan(plan["id"], as_customer=customer)
        assert refreshed["plan_status"] == "RESOLVED"


class TestRefundInvariant:
    def _refund_first_line(self, api):
        customer, product, placement, subs, plan, line, claim = (
            setup_reported_claim(num_subscriptions=3)
        )
        resp = api.review_damage_claim(
            claim["id"], {"decision": "APPROVE_REFUND"}, SUPPORT,
        )
        return customer, product, plan, line, claim, validate_success(resp)

    def test_damage_refund_completes_claim_and_flips_line(self, api):
        """PRD §3.11: "A refund approval completes the claim immediately:
        `claim_refund_cents` is set to the sum of the damaged lines'
        `line_charged_cents`, every damaged line moves to `REFUNDED`, and the
        plan's `refunded_total_cents` increases by the same amount."

        Design: Difficulty/compensating_invariant/damage_refund_preserves_gross_line_total_invariant
        """
        customer, product, plan, line, claim, reviewed = self._refund_first_line(api)
        assert reviewed["claim_status"] == "COMPLETED"
        assert reviewed["claim_refund_cents"] == 950
        refreshed_line = validate_success(
            api.get_plan_line(line["id"], make_customer_headers(customer["id"])),
        )
        assert refreshed_line["line_status"] == "REFUNDED"
        refreshed_plan = get_plan(plan["id"], as_customer=customer)
        assert refreshed_plan["refunded_total_cents"] == 950

    def test_damage_refund_preserves_gross_line_total_invariant(self, api):
        """PRD §3.9: "For every plan that has been locked,
        `gross_line_total_cents` always equals the sum of `line_charged_cents`
        over lines in `SHIPPED` or `RESHIPPED` status, plus
        `refunded_total_cents`, plus the sum of `line_charged_cents` over lines
        still `SCHEDULED`. Refunds and reshipments redistribute value across
        these buckets; they never create or destroy it."

        Design: Difficulty/compensating_invariant/damage_refund_preserves_gross_line_total_invariant
        """
        customer, product, plan, line, claim, reviewed = self._refund_first_line(api)
        refreshed_plan = get_plan(plan["id"], as_customer=customer)
        assert refreshed_plan["gross_line_total_cents"] == 2850
        lines = list_plan_lines(refreshed_plan, as_customer=customer)
        shipped_total = sum(
            l["line_charged_cents"] for l in lines if l["line_status"] == "SHIPPED"
        )
        # 2 * 950 shipped + 950 refunded == 2850 gross.
        assert shipped_total == 1900
        assert (
            shipped_total + refreshed_plan["refunded_total_cents"]
            == refreshed_plan["gross_line_total_cents"]
        )

    def test_review_of_completed_claim_returns_claim_not_reviewable(self, api):
        """PRD §3.11: "reviewing a claim no longer in `REPORTED` status is
        rejected with `ERR_CLAIM_NOT_REVIEWABLE`."

        Design: Corner/state_machines/review_of_completed_claim_returns_claim_not_reviewable
        """
        customer, product, plan, line, claim, reviewed = self._refund_first_line(api)
        resp = api.review_damage_claim(
            claim["id"], {"decision": "REJECT"}, SUPPORT,
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_REVIEWABLE.value, 409)
        refreshed = validate_success(api.get_damage_claim(claim["id"], SUPPORT))
        assert refreshed["claim_status"] == "COMPLETED"


class TestReshipment:
    def test_reship_review_without_stock_returns_insufficient_inventory(self, api):
        """PRD §3.11: "A reship approval is gated on stock: for every damaged
        line, the line's product must have a placement in the plan customer's
        region with `on_hand_units` at least the line's `quantity`, or the
        review is rejected with `ERR_INSUFFICIENT_INVENTORY`."

        Design: Corner/validations/reship_review_without_stock_returns_insufficient_inventory
        """
        customer, product, placement, subs, plan, line, claim = (
            setup_reported_claim(num_subscriptions=1, quantity=4, units=4)
        )
        resp = api.review_damage_claim(
            claim["id"], {"decision": "APPROVE_RESHIP"}, SUPPORT,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_INVENTORY.value, 422)
        refreshed = validate_success(api.get_damage_claim(claim["id"], SUPPORT))
        assert refreshed["claim_status"] == "REPORTED"
        refreshed_placement = validate_success(
            api.get_inventory_placement(placement["id"], ADMIN),
        )
        assert refreshed_placement["on_hand_units"] == 0
        assert refreshed_placement["shipped_units"] == 4

    def test_reship_approval_creates_pending_reshipment(self, api):
        """PRD §3.11: "Approval moves the claim to `APPROVED_RESHIP`, creates a
        Reshipment in `PENDING` status whose `claim_id` points back at the claim
        and whose `reshipped_line_ids` are copied from the claim's
        `damaged_line_ids`, and moves every damaged line to `RESHIPPED`."

        Design: Difficulty/transitive_cascade/reship_dispatch_cascades_inventory_to_product_availability
        """
        customer, product, placement, subs, plan, line, claim = (
            setup_reported_claim(num_subscriptions=1, quantity=1, units=2)
        )
        reviewed = validate_success(api.review_damage_claim(
            claim["id"], {"decision": "APPROVE_RESHIP"}, SUPPORT,
        ))
        assert reviewed["claim_status"] == "APPROVED_RESHIP"
        refreshed_line = validate_success(
            api.get_plan_line(line["id"], make_customer_headers(customer["id"])),
        )
        assert refreshed_line["line_status"] == "RESHIPPED"
        reshipments, _ = validate_paginated(
            api.list_claim_reshipments(claim["id"], SUPPORT),
        )
        assert len(reshipments) == 1
        assert reshipments[0]["claim_id"] == claim["id"]
        assert reshipments[0]["reshipped_line_ids"] == [line["id"]]
        assert reshipments[0]["reshipment_status"] == "PENDING"

    def test_reship_dispatch_cascades_inventory_to_product_availability(self, api):
        """PRD §3.11: "Dispatching requires `PENDING` status and re-verifies
        stock — every reshipped line's placement must still hold at least the
        line's quantity on hand, or the dispatch is rejected with
        `ERR_INSUFFICIENT_INVENTORY` — then moves each line's quantity from
        `on_hand_units` into `shipped_units`, flips any emptied product's
        availability per §2.10, sends the customer a `RESHIP_DISPATCHED`
        notification, and moves the reshipment to `DISPATCHED`."

        Design: Difficulty/transitive_cascade/reship_dispatch_cascades_inventory_to_product_availability
        """
        customer, product, placement, subs, plan, line, claim = (
            setup_reported_claim(num_subscriptions=1, quantity=1, units=2)
        )
        validate_success(api.review_damage_claim(
            claim["id"], {"decision": "APPROVE_RESHIP"}, SUPPORT,
        ))
        reshipments, _ = validate_paginated(
            api.list_claim_reshipments(claim["id"], SUPPORT),
        )
        reshipment = reshipments[0]
        dispatched = validate_success(
            api.dispatch_reshipment(reshipment["id"], ADMIN),
        )
        assert dispatched["reshipment_status"] == "DISPATCHED"
        refreshed_placement = validate_success(
            api.get_inventory_placement(placement["id"], ADMIN),
        )
        assert refreshed_placement["on_hand_units"] == 0
        assert refreshed_placement["shipped_units"] == 2
        assert_inventory_conservation(refreshed_placement)
        refreshed_product = validate_success(
            api.get_product(product["id"], ADMIN),
        )
        assert refreshed_product["availability_status"] == "OUT_OF_STOCK"
        notifications = list_notifications(customer, "RESHIP_DISPATCHED")
        assert len(notifications) == 1

    def test_inventory_conservation_across_receive_lock_ship_reship(self, api):
        """PRD §2.10: "At all times, `received_total_units` equals the sum of
        `on_hand_units`, `reserved_units`, and `shipped_units`. Receiving stock
        adds to `received_total_units` and `on_hand_units`; locking a plan moves
        quantity from `on_hand_units` into `reserved_units`; shipping a plan
        moves it from `reserved_units` into `shipped_units`; dispatching a
        reshipment moves it directly from `on_hand_units` into
        `shipped_units`."

        Design: Difficulty/compensating_invariant/inventory_conservation_across_receive_lock_ship_reship
        """
        customer, product, placement, subs, plan, line, claim = (
            setup_reported_claim(num_subscriptions=1, quantity=4, units=10)
        )
        # After ship: 6 on hand, 0 reserved, 4 shipped.
        mid = validate_success(
            api.get_inventory_placement(placement["id"], ADMIN),
        )
        assert mid["on_hand_units"] == 6
        assert mid["reserved_units"] == 0
        assert mid["shipped_units"] == 4
        assert_inventory_conservation(mid)

        validate_success(api.review_damage_claim(
            claim["id"], {"decision": "APPROVE_RESHIP"}, SUPPORT,
        ))
        reshipments, _ = validate_paginated(
            api.list_claim_reshipments(claim["id"], SUPPORT),
        )
        validate_success(api.dispatch_reshipment(reshipments[0]["id"], ADMIN))
        final = validate_success(
            api.get_inventory_placement(placement["id"], ADMIN),
        )
        assert final["on_hand_units"] == 2
        assert final["reserved_units"] == 0
        assert final["shipped_units"] == 8
        assert final["received_total_units"] == 10
        assert_inventory_conservation(final)


class TestRetentionOffers:
    def test_subscription_cancel_offer_accept_cycle_returns_to_active(self, api):
        """PRD §3.4: "Accepting — which additionally requires the logical today
        to be on or before `expires_on` — moves the offer to `ACCEPTED`, returns
        the subscription to `ACTIVE`, and adds 500 cents to the customer's
        `credit_balance_cents`."

        Design: Difficulty/non_linear_state_machine/subscription_cancel_offer_accept_cycle_returns_to_active
        """
        set_clock()
        customer = create_customer()
        product, _ = create_stocked_product()
        sub = create_subscription(customer, product)
        offer = cancel_subscription_and_get_offer(sub, customer)
        headers = make_customer_headers(customer["id"])
        accepted = validate_success(api.accept_retention_offer(offer["id"], headers))
        assert accepted["offer_status"] == "ACCEPTED"
        assert get_customer_by_id(customer["id"])["credit_balance_cents"] == 500
        assert get_subscription_by_id(sub["id"], customer)["status"] == "ACTIVE"
        # The cycle is re-entrant: the ACTIVE subscription can pause again.
        paused = validate_success(api.pause_subscription(sub["id"], headers))
        assert paused["status"] == "PAUSED"

    def test_cancel_creates_offered_retention_offer_with_notification(self, api):
        """PRD §3.4: "Cancelling from either `ACTIVE` or `PAUSED` moves the
        subscription to `PENDING_CANCEL` and creates a RetentionOffer in
        `OFFERED` status: a fixed goodwill credit of exactly 500 cents, recorded
        as `offer_type` `CREDIT` with `credit_amount_cents` 500, expiring seven
        days after the cancellation request date (`expires_on` is the request
        date plus 7 days). The customer is informed via an `OFFER_CREATED`
        notification."

        Design: Difficulty/non_linear_state_machine/subscription_cancel_offer_accept_cycle_returns_to_active
        """
        set_clock()
        customer = create_customer()
        product, _ = create_stocked_product()
        sub = create_subscription(customer, product)
        offer = cancel_subscription_and_get_offer(sub, customer)
        assert offer["offer_status"] == "OFFERED"
        assert offer["offer_type"] == "CREDIT"
        assert offer["credit_amount_cents"] == 500
        assert offer["expires_on"] == "2026-09-08"
        assert get_subscription_by_id(sub["id"], customer)["status"] == "PENDING_CANCEL"
        notifications = list_notifications(customer, "OFFER_CREATED")
        assert len(notifications) == 1

    def test_pause_from_pending_cancel_returns_subscription_not_active(self, api):
        """PRD §3.4: "Pausing or resuming a subscription in any other status is
        rejected with `ERR_SUBSCRIPTION_NOT_ACTIVE`."

        Design: Corner/state_machines/pause_from_pending_cancel_returns_subscription_not_active
        """
        set_clock()
        customer = create_customer()
        product, _ = create_stocked_product()
        sub = create_subscription(customer, product)
        headers = make_customer_headers(customer["id"])
        validate_success(api.cancel_subscription(sub["id"], headers))
        resp = api.pause_subscription(sub["id"], headers)
        validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE.value, 409)
        assert get_subscription_by_id(sub["id"], customer)["status"] == "PENDING_CANCEL"

    def test_accept_declined_offer_returns_offer_not_open(self, api):
        """PRD §3.4: "While the offer is `OFFERED`, the customer may accept or
        decline it; acting on an offer in any other status is rejected with
        `ERR_OFFER_NOT_OPEN`."
        PRD §3.4: "Declining moves the offer to `DECLINED` and the subscription
        to `CANCELLED`, which is terminal."

        Design: Corner/state_machines/accept_declined_offer_returns_offer_not_open
        """
        set_clock()
        customer = create_customer()
        product, _ = create_stocked_product()
        sub = create_subscription(customer, product)
        offer = cancel_subscription_and_get_offer(sub, customer)
        headers = make_customer_headers(customer["id"])
        validate_success(api.decline_retention_offer(offer["id"], headers))
        resp = api.accept_retention_offer(offer["id"], headers)
        validate_error(resp, ApiErrorId.ERR_OFFER_NOT_OPEN.value, 409)
        assert get_subscription_by_id(sub["id"], customer)["status"] == "CANCELLED"
        assert get_customer_by_id(customer["id"])["credit_balance_cents"] == 0

    def test_retention_offer_lazy_expiry_cancels_subscription(self, api):
        """PRD §3.4: "whenever the system reads or mutates the subscription, or
        reads its offers or the customer's notifications, and finds an `OFFERED`
        offer whose `expires_on` is strictly before the logical today, the offer
        flips to `EXPIRED`, the subscription flips to `CANCELLED`, and an
        `OFFER_EXPIRED` notification is created for the customer."

        Design: Corner/cross_cutting_layers/retention_offer_lazy_expiry_cancels_subscription
        """
        set_clock()
        customer = create_customer()
        product, _ = create_stocked_product()
        sub = create_subscription(customer, product)
        offer = cancel_subscription_and_get_offer(sub, customer)
        headers = make_customer_headers(customer["id"])
        set_clock("2026-09-09T00:00:00Z")
        refreshed = validate_success(api.get_subscription(sub["id"], headers))
        assert refreshed["status"] == "CANCELLED"
        offers, _ = validate_paginated(
            api.list_subscription_offers(sub["id"], headers),
        )
        assert offers[0]["offer_status"] == "EXPIRED"
        assert offers[0]["expires_on"] == "2026-09-08"
        notifications = list_notifications(customer, "OFFER_EXPIRED")
        assert len(notifications) == 1


class TestValidationOrdering:
    def test_state_error_beats_constraint_error_on_cancelled_subscription_patch(self, api):
        """PRD §2.5: "(6) state preconditions, including the
        optimistic-concurrency version match on refresh — the state errors and
        `ERR_STALE_PLAN_VERSION`; (7) scalar domain ranges — cadence, delivery
        day, quantity, price cap, claim line shape"
        PRD §2.5: "A later check is only reached when every earlier check
        passes."
        PRD §3.3: "While a subscription is `ACTIVE`, the customer may patch its
        `cadence_months`, `quantity`, or `price_cap_cents`; the same range
        validations apply."

        Design: Difficulty/priority_pair_validation_conflict/state_error_beats_constraint_error_on_cancelled_subscription_patch
        """
        set_clock()
        customer = create_customer()
        product, _ = create_stocked_product()
        sub = create_subscription(customer, product)
        offer = cancel_subscription_and_get_offer(sub, customer)
        headers = make_customer_headers(customer["id"])
        validate_success(api.decline_retention_offer(offer["id"], headers))
        resp = api.patch_subscription(sub["id"], {"cadence_months": 9}, headers)
        validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE.value, 409)


class TestRbacAndOwnership:
    def test_customer_cannot_create_product(self, api):
        """PRD §2.1: "A request whose role is authenticated but not listed among
        the endpoint's permitted roles is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."

        Design: Corner/rbac/customer_cannot_create_product
        """
        set_clock()
        customer = create_customer()
        resp = api.create_product(
            create_product_payload(), make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, 403)

    def test_customer_cannot_review_damage_claim(self, api):
        """PRD §2.1: "A request whose role is authenticated but not listed among
        the endpoint's permitted roles is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."

        Design: Corner/rbac/customer_cannot_review_damage_claim
        """
        customer, product, placement, subs, plan, line, claim = (
            setup_reported_claim(num_subscriptions=1)
        )
        resp = api.review_damage_claim(
            claim["id"], {"decision": "APPROVE_REFUND"},
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, 403)
        refreshed = validate_success(api.get_damage_claim(claim["id"], SUPPORT))
        assert refreshed["claim_status"] == "REPORTED"

    def test_support_agent_cannot_create_coupon(self, api):
        """PRD §2.1: "A request whose role is authenticated but not listed among
        the endpoint's permitted roles is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."

        Design: Corner/rbac/support_agent_cannot_create_coupon
        """
        set_clock()
        resp = api.create_coupon(
            {
                "code": "NOPE",
                "discount_type": "FLAT",
                "flat_off_cents": 10,
                "valid_from": "2026-09-01",
                "valid_to": "2026-09-30",
            },
            SUPPORT,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, 403)

    def test_customer_cannot_lock_another_customers_plan(self, api):
        """PRD §2.1: "ownership checks on any customer-scoped resource
        (subscription, delivery plan, plan line, damage claim, retention offer,
        notification) compare the resource's owning-customer chain to
        `X-User-ID`, and a mismatch is rejected with `ERR_OWNERSHIP_MISMATCH`
        (HTTP 403)."

        Design: Corner/rbac/customer_cannot_lock_another_customers_plan
        """
        customer, product, placement, subs, plan = setup_customer_with_plan(
            num_subscriptions=1,
        )
        intruder = create_customer()
        resp = api.lock_plan(plan["id"], make_customer_headers(intruder["id"]))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH.value, 403)
        refreshed = get_plan(plan["id"], as_customer=customer)
        assert refreshed["plan_status"] == "OPEN"

    def test_request_missing_auth_headers_returns_401(self, api):
        """PRD §2.1: "A request missing either header, or carrying an
        unrecognized role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/request_missing_auth_headers_returns_401
        """
        set_clock()
        resp = api.get_product(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", headers={},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
