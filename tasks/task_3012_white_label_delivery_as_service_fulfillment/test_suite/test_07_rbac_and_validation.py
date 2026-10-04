"""RBAC exclusivity, validation-layer ordering, tracking-feed visibility,
immediate consistency, and cross-entity accept gating (PRD sections 2.1, 2.6,
3.5, 3.9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_courier,
    add_policy,
    admin_headers,
    base_chain,
    batch_orders,
    c_headers,
    complete_delivery,
    decide_claim,
    dispatch_batch,
    drive_to_in_transit,
    file_claim,
    get_merchant,
    get_order,
    m_headers,
    make_order_accepted,
    make_order_from_quote,
    make_order_ready_fresh,
    new_quote,
    open_report,
    set_clock,
    support_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _delivered_env(api):
    """Base chain plus one on-time DELIVERED order."""
    env = base_chain()
    m_id = env["merchant"]["id"]
    s_id = env["store"]["id"]
    c_id = env["courier"]["id"]
    order = make_order_ready_fresh(m_id, s_id, "rb-1",
                                   promised_at="2026-09-01T02:00:00Z")
    batch = batch_orders(s_id, c_id, [order["id"]])
    dispatch_batch(c_id, batch["id"])
    drive_to_in_transit(c_id, order["id"])
    set_clock("2026-09-01T01:00:00Z")
    order = complete_delivery(c_id, order["id"])
    env = dict(env)
    env["order"] = order
    return env


class TestAuthLayer:
    def test_missing_role_header_rejected_before_any_business_check(self, api):
        """PRD section 2.1: "A request missing either header, or carrying a
        role outside this declared set, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
        PRD section 2.6: "Because the layers are ordered, a request that fails
        an earlier layer never reaches a later one: a stale-version rejection,
        for example, always masks any business-constraint problem the same
        payload might also have, and an authentication failure masks
        everything."

        Design: Corner/rbac/missing_role_header_rejected_before_any_business_check
        """
        set_clock()
        # Bogus path id AND missing role header: auth (layer 1) wins over the
        # existence layer (3).
        resp = api.get_merchant(
            "00000000-0000-4000-8000-000000000001",
            headers={"X-User-ID": "test-admin-1"},
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestMerchantRoleExclusions:
    def test_merchant_cannot_create_couriers_or_settle_claims(self, api):
        """PRD section 2.1: "A `PlatformAdmin` operates the platform itself:
        merchant onboarding and lifecycle, courier administration, batch
        creation, settlement and reversal of claims, SLA report finalization,
        service-credit application, and the clock and surge test-driving
        controls."
        PRD section 2.1: "A request whose role is recognized but not permitted
        for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP
        403)."

        Design: Corner/rbac/merchant_cannot_create_couriers_or_settle_claims
        """
        env = _delivered_env(api)
        m_id = env["merchant"]["id"]
        claim = decide_claim(
            file_claim(m_id, env["order"]["id"], "ADDRESS_ISSUE", 500)["id"],
            "APPROVE",
        )
        assert claim["status"] == "APPROVED"

        validate_error(
            api.create_courier({"name": "Sneaky Courier"}, m_headers(m_id)),
            ApiErrorId.ERR_UNAUTHORIZED_ROLE,
        )
        validate_error(api.settle_claim(claim["id"], m_headers(m_id)),
                       ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        assert get_claim_status(api, claim["id"]) == "APPROVED"


def get_claim_status(api, claim_id):
    return validate_success(api.get_refund_claim(claim_id, admin_headers()))["status"]


class TestCourierRoleExclusions:
    def test_courier_cannot_accept_orders_or_file_claims(self, api):
        """PRD section 2.1: "A `Merchant` manages its own stores, pricing
        policies, quotes, and orders up to pickup readiness, decides
        dispositions, and files and appeals refund claims. A `Courier`
        executes the physical work: dispatching and failing batches,
        confirming pickup, driving transit, completing delivery, reporting
        undeliverable orders, and completing dispositions."
        PRD section 2.1: "A request whose role is recognized but not permitted
        for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP
        403)."

        Design: Corner/rbac/courier_cannot_accept_orders_or_file_claims
        """
        env = base_chain()
        m_id = env["merchant"]["id"]
        c_id = env["courier"]["id"]
        quote = new_quote(m_id, env["store"]["id"])
        order = make_order_from_quote(m_id, quote["id"], "cr-1")

        validate_error(
            api.accept_order(order["id"], {"promised_at": "2026-09-01T02:00:00Z"},
                             c_headers(c_id)),
            ApiErrorId.ERR_UNAUTHORIZED_ROLE,
        )
        validate_error(
            api.create_disposition(order["id"], {"resolution": "DISPOSE"},
                                   c_headers(c_id)),
            ApiErrorId.ERR_UNAUTHORIZED_ROLE,
        )
        validate_error(
            api.create_refund_claim(
                {"delivery_order_id": order["id"], "fault_code": "COURIER_DELAY",
                 "claimed_amount_cents": 100},
                c_headers(c_id),
            ),
            ApiErrorId.ERR_UNAUTHORIZED_ROLE,
        )
        assert get_order(m_id, order["id"])["fulfillment_status"] == "QUOTED"


class TestSupportAgentRoleExclusions:
    def test_support_agent_cannot_decide_config_or_drive_deliveries(self, api):
        """PRD section 2.1: "A `SupportAgent` triages the refund-claim queue
        on the merchant's behalf — support routing back to the merchant
        happens through the claim workflow, never through direct customer
        contact."
        PRD section 2.1: "A request whose role is recognized but not permitted
        for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP
        403)."
        PRD section 3.8: "A `SupportAgent` picks the claim up, moving `FILED`
        to `UNDER_REVIEW`, and then decides it by supplying a `decision`."

        Design: Corner/rbac/support_agent_cannot_decide_merchant_config_or_drive_deliveries
        """
        env = base_chain()
        m_id = env["merchant"]["id"]
        s_id = env["store"]["id"]
        c_id = env["courier"]["id"]
        order = make_order_ready_fresh(m_id, s_id, "sa-1",
                                       promised_at="2026-09-01T02:00:00Z")
        batch = batch_orders(s_id, c_id, [order["id"]])
        dispatch_batch(c_id, batch["id"])
        drive_to_in_transit(c_id, order["id"])
        # A claim requires the order's billing to be SETTLED (PRD 3.8), which
        # only delivery performs; drive the order to DELIVERED first.
        order = complete_delivery(c_id, order["id"])
        claim = file_claim(m_id, order["id"], "COURIER_DELAY", 100)
        report = open_report(m_id)

        validate_error(
            api.activate_pricing_policy(
                m_id, env["policy"]["id"],
                {"expected_merchant_version": env["merchant"]["version"]},
                support_headers(),
            ),
            ApiErrorId.ERR_UNAUTHORIZED_ROLE,
        )
        # A second in-flight order for the drive-deliveries exclusion, since
        # the first order is already DELIVERED.
        order2 = make_order_ready_fresh(m_id, s_id, "sa-2",
                                        promised_at="2026-09-01T02:00:00Z")
        validate_error(
            api.complete_delivery(order2["id"], support_headers()),
            ApiErrorId.ERR_UNAUTHORIZED_ROLE,
        )
        validate_error(
            api.finalize_sla_report(report["id"], support_headers()),
            ApiErrorId.ERR_UNAUTHORIZED_ROLE,
        )

        # The support agent's own exclusive operation still works.
        reviewing = validate_success(
            api.start_claim_review(claim["id"], support_headers())
        )
        assert reviewing["status"] == "UNDER_REVIEW"


class TestValidationPriority:
    def test_accept_state_before_fiscal_dual_failure(self, api):
        """PRD section 2.6 layer 6: "State preconditions. The target entity
        must be in the state the transition requires (`ERR_INVALID_STATE`,
        `ERR_MERCHANT_SUSPENDED`, `ERR_STORE_NOT_ACTIVE`, `ERR_QUOTE_EXPIRED`,
        `ERR_DISPOSITION_NOT_REQUIRED`, HTTP 409)."
        PRD section 2.6 layer 9: "Fiscal sufficiency. The merchant's billing
        balance must cover the funds being committed
        (`ERR_INSUFFICIENT_BILLING_BALANCE`, HTTP 402)."
        PRD section 2.6: "Because the layers are ordered, a request that fails
        an earlier layer never reaches a later one"

        Design: Difficulty/priority_pair_validation_conflict/accept_state_before_fiscal_dual_failure
        """
        env = base_chain(
            with_courier=False, merchant_overrides={"billing_balance_cents": 700}
        )
        m_id = env["merchant"]["id"]
        quote = new_quote(m_id, env["store"]["id"])  # quoted fee 500
        order = make_order_from_quote(m_id, quote["id"], "pp-1")
        validate_success(
            api.accept_order(order["id"], {"promised_at": "2026-09-01T02:00:00Z"},
                             m_headers(m_id))
        )
        # 700 - 500 = 200: a second accept would violate BOTH the state rule
        # (already ACCEPTED) and the fiscal rule (200 < 500).
        assert get_merchant(m_id)["billing_balance_cents"] == 200

        resp = api.accept_order(
            order["id"], {"promised_at": "2026-09-01T02:00:00Z"}, m_headers(m_id)
        )
        data = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert data["error_id"] != ApiErrorId.ERR_INSUFFICIENT_BILLING_BALANCE, (
            "state preconditions (layer 6) must mask fiscal sufficiency (layer 9)"
        )
        assert get_merchant(m_id)["billing_balance_cents"] == 200, (
            "no double debit from the rejected accept"
        )

    def test_fiscal_error_fires_alone_when_state_is_valid(self, api):
        """PRD section 3.5: "acceptance also requires the merchant to be
        `ACTIVE` (`ERR_MERCHANT_SUSPENDED`), the store to be `ACTIVE`
        (`ERR_STORE_NOT_ACTIVE`), and the billing balance to be at least the
        quoted fee — a shortfall is rejected with
        `ERR_INSUFFICIENT_BILLING_BALANCE` (HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/accept_state_before_fiscal_dual_failure
        """
        env = base_chain(
            with_courier=False, merchant_overrides={"billing_balance_cents": 400}
        )
        m_id = env["merchant"]["id"]
        quote = new_quote(m_id, env["store"]["id"])  # quoted fee 500 > 400
        order = make_order_from_quote(m_id, quote["id"], "pp-2")

        resp = api.accept_order(
            order["id"], {"promised_at": "2026-09-01T02:00:00Z"}, m_headers(m_id)
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BILLING_BALANCE)
        assert get_merchant(m_id)["billing_balance_cents"] == 400
        assert get_order(m_id, order["id"])["fulfillment_status"] == "QUOTED"


class TestCrossEntityAcceptGating:
    def test_order_accept_requires_active_store(self, api):
        """PRD section 3.5: "acceptance also requires the merchant to be
        `ACTIVE` (`ERR_MERCHANT_SUSPENDED`), the store to be `ACTIVE`
        (`ERR_STORE_NOT_ACTIVE`)"
        PRD section 3.2: "The store begins `ACTIVE`; it can later be updated —
        a new `delivery_radius_m`, a new `timezone`, or a `status` change to
        `CLOSED` — and each update increments the store's `version`."

        Design: Difficulty/cross_entity_state_dependency/order_accept_requires_active_store
        """
        env = base_chain(with_courier=False)
        m_id = env["merchant"]["id"]
        s_id = env["store"]["id"]
        quote = new_quote(m_id, s_id)
        order = make_order_from_quote(m_id, quote["id"], "xs-1")

        closed = validate_success(
            api.update_store(s_id, {"status": "CLOSED"}, m_headers(m_id))
        )
        assert closed["status"] == "CLOSED"

        blocked = api.accept_order(
            order["id"], {"promised_at": "2026-09-01T02:00:00Z"}, m_headers(m_id)
        )
        validate_error(blocked, ApiErrorId.ERR_STORE_NOT_ACTIVE)

        mid = get_order(m_id, order["id"])
        assert mid["fulfillment_status"] == "QUOTED"
        assert mid["billing_status"] == "PENDING"

        validate_success(api.update_store(s_id, {"status": "ACTIVE"}, m_headers(m_id)))
        accepted = validate_success(
            api.accept_order(order["id"], {"promised_at": "2026-09-01T02:00:00Z"},
                             m_headers(m_id))
        )
        assert accepted["billing_status"] == "AUTHORIZED"
        assert accepted["fulfillment_status"] == "ACCEPTED"

    def test_accept_debits_balance_exactly_once_after_store_reactivation(self, api):
        """PRD section 3.5: "Acceptance authorizes funds: the `billing_status`
        dimension moves from `PENDING` to `AUTHORIZED` and the merchant's
        `billing_balance_cents` is debited by the `quoted_fee_cents`."
        PRD section 3.5: "acceptance also requires the merchant to be
        `ACTIVE` (`ERR_MERCHANT_SUSPENDED`), the store to be `ACTIVE`
        (`ERR_STORE_NOT_ACTIVE`)"

        Design: Difficulty/cross_entity_state_dependency/order_accept_requires_active_store
        """
        env = base_chain(with_courier=False)
        m_id = env["merchant"]["id"]
        s_id = env["store"]["id"]
        quote = new_quote(m_id, s_id)
        order = make_order_from_quote(m_id, quote["id"], "xs-2")

        validate_success(api.update_store(s_id, {"status": "CLOSED"}, m_headers(m_id)))
        validate_error(
            api.accept_order(order["id"], {"promised_at": "2026-09-01T02:00:00Z"},
                             m_headers(m_id)),
            ApiErrorId.ERR_STORE_NOT_ACTIVE,
        )
        # The rejected accept must not have debited anything.
        assert get_merchant(m_id)["billing_balance_cents"] == 100000

        validate_success(api.update_store(s_id, {"status": "ACTIVE"}, m_headers(m_id)))
        validate_success(
            api.accept_order(order["id"], {"promised_at": "2026-09-01T02:00:00Z"},
                             m_headers(m_id))
        )
        assert get_merchant(m_id)["billing_balance_cents"] == 99500


class TestTrackingFeedVisibility:
    def test_merchant_feed_shows_only_merchant_visible_events(self, api):
        """PRD section 3.9 (final paragraph): "The branded tracking feed for
        an order shows `MERCHANT_VISIBLE` events only when read by a
        `Merchant`, and all events regardless of visibility when read by a
        `Courier`, `SupportAgent`, or `PlatformAdmin`."

        Design: Corner/endpoints/merchant_tracking_feed_shows_only_merchant_visible_events
        """
        env = base_chain(with_courier=False)
        m_id = env["merchant"]["id"]
        quote = new_quote(m_id, env["store"]["id"])
        order = make_order_from_quote(m_id, quote["id"], "tv-1")
        validate_success(
            api.accept_order(order["id"], {"promised_at": "2026-09-01T02:00:00Z"},
                             m_headers(m_id))
        )  # system event: ORDER_ACCEPTED, MERCHANT_VISIBLE

        validate_success(
            api.create_tracking_event(
                order["id"],
                {"event_type": "NOTE", "note": "internal ops note",
                 "visibility": "INTERNAL_ONLY"},
                admin_headers(),
            ),
            201,
        )

        merchant_feed, _ = validate_paginated(
            api.list_tracking_events(order["id"], m_headers(m_id))
        )
        assert len(merchant_feed) == 1
        assert merchant_feed[0]["event_type"] == "ORDER_ACCEPTED"

        admin_feed, _ = validate_paginated(
            api.list_tracking_events(order["id"], admin_headers())
        )
        assert len(admin_feed) == 2
        assert any(e["visibility"] == "INTERNAL_ONLY" for e in admin_feed)


class TestImmediateConsistency:
    def test_writes_visible_in_same_response_and_next_read(self, api):
        """PRD section 3.5: "Acceptance, performed by the merchant, supplies
        the `promised_at` delivery time against which lateness is later
        measured, and moves the order's `fulfillment_status` from `QUOTED` to
        `ACCEPTED`. Acceptance authorizes funds: the `billing_status`
        dimension moves from `PENDING` to `AUTHORIZED` and the merchant's
        `billing_balance_cents` is debited by the `quoted_fee_cents`. ...
        Acceptance emits a merchant-visible `ORDER_ACCEPTED` tracking event."

        Design: Corner/consistency_model/immediate_consistency_writes_visible_in_same_response_and_next_read
        """
        env = base_chain(with_courier=False)
        m_id = env["merchant"]["id"]
        quote = new_quote(m_id, env["store"]["id"])
        order = make_order_from_quote(m_id, quote["id"], "ic-1")

        accepted = validate_success(
            api.accept_order(order["id"], {"promised_at": "2026-09-01T02:00:00Z"},
                             m_headers(m_id))
        )
        assert accepted["billing_status"] == "AUTHORIZED"

        # The very next reads reflect the mutation with no lag.
        assert get_merchant(m_id)["billing_balance_cents"] == 99500
        events, _ = validate_paginated(
            api.list_tracking_events(order["id"], m_headers(m_id))
        )
        assert [e["event_type"] for e in events] == ["ORDER_ACCEPTED"]
