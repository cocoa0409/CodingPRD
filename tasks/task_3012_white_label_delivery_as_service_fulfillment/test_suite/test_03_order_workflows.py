"""Order lifecycle workflows: quote consumption, the forward fulfillment
chain, undeliverable disposition, cancellation, suspension cascade, and the
parallel fulfillment/billing state dimensions (PRD sections 3.1, 3.4-3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_courier,
    admin_headers,
    base_chain,
    batch_orders,
    c_headers,
    complete_delivery,
    create_quote_payload,
    dispatch_batch,
    drive_to_in_transit,
    file_claim,
    get_batch,
    get_merchant,
    get_order,
    m_headers,
    make_disposition,
    make_order_from_quote,
    make_order_ready_fresh,
    new_quote,
    report_undeliverable,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _delivered_env(api, promised_at="2026-09-01T02:00:00Z",
                   delivered_at="2026-09-01T01:00:00Z", key="fx-1",
                   merchant_overrides=None):
    """Base chain plus one order delivered on time (surge 1.0 throughout)."""
    env = base_chain(merchant_overrides=merchant_overrides)
    m_id = env["merchant"]["id"]
    s_id = env["store"]["id"]
    c_id = env["courier"]["id"]
    order = make_order_ready_fresh(m_id, s_id, key, promised_at=promised_at)
    batch = batch_orders(s_id, c_id, [order["id"]])
    dispatch_batch(c_id, batch["id"])
    drive_to_in_transit(c_id, order["id"])
    set_clock(delivered_at)
    order = complete_delivery(c_id, order["id"])
    env = dict(env)
    env.update({"order": order, "batch": get_batch(batch["id"])})
    return env


class TestQuoteConsumption:
    def test_quote_consumed_by_order_and_second_use_rejected(self, api):
        """PRD section 3.5: "A merchant turns a quote into a delivery order by
        submitting the `quote_id`, its own `customer_reference` — the
        white-label link back to the merchant's channel, since the platform
        never learns the end customer's identity — and an `idempotency_key`."
        PRD section 3.4: "A quote is `ACTIVE` until it is consumed or its
        validity lapses; any read or use at or after `valid_until` marks it
        `EXPIRED`, and an attempt to consume an expired quote is rejected with
        `ERR_QUOTE_EXPIRED`. `CONSUMED` and `EXPIRED` are terminal."

        Design: Corner/state_machines/quote_consumed_by_order_and_second_use_rejected
        """
        env = base_chain(with_courier=False)
        m_id = env["merchant"]["id"]
        quote = new_quote(m_id, env["store"]["id"])
        make_order_from_quote(m_id, quote["id"], "co-1")

        second = api.create_order(
            {"quote_id": quote["id"], "customer_reference": "CO-2",
             "idempotency_key": "co-2"},
            m_headers(m_id),
        )
        validate_error(second, ApiErrorId.ERR_QUOTE_EXPIRED)

        quote_after = validate_success(api.get_quote(quote["id"], m_headers(m_id)))
        assert quote_after["status"] == "CONSUMED"

        orders, _ = validate_paginated(api.list_orders(admin_headers()))
        assert len(orders) == 1

    def test_quote_expires_at_valid_until_and_reads_expired(self, api):
        """PRD section 3.4: "The quote pins the policy it used as
        `pricing_policy_id` and the surge multiplier in force as
        `quoted_surge_multiplier`, records the computed `distance_m`, and is
        usable for fifteen minutes: `valid_until` is set to the creation clock
        time plus fifteen minutes. A quote is `ACTIVE` until it is consumed or
        its validity lapses; any read or use at or after `valid_until` marks
        it `EXPIRED`, and an attempt to consume an expired quote is rejected
        with `ERR_QUOTE_EXPIRED`."
        PRD section 2.5: "Quotes whose `valid_until` has been reached read as
        `EXPIRED` from that point on."

        Design: Corner/state_machines/quote_expires_at_valid_until_and_reads_expired
        """
        env = base_chain(with_courier=False)
        m_id = env["merchant"]["id"]
        quote = new_quote(m_id, env["store"]["id"])  # created at clock 00:00

        set_clock("2026-09-01T00:15:00Z")  # exactly valid_until
        quote_after = validate_success(api.get_quote(quote["id"], m_headers(m_id)))
        assert quote_after["status"] == "EXPIRED"

        resp = api.create_order(
            {"quote_id": quote["id"], "customer_reference": "CO-1",
             "idempotency_key": "co-1"},
            m_headers(m_id),
        )
        validate_error(resp, ApiErrorId.ERR_QUOTE_EXPIRED)

        orders, _ = validate_paginated(api.list_orders(admin_headers()))
        assert orders == []


class TestHappyPath:
    def test_full_chain_and_batch_auto_complete(self, api):
        """PRD section 3.7: "Completing a delivery moves an order from
        `IN_TRANSIT` to `DELIVERED` and performs settlement. The clock time is
        recorded as `delivered_at`; the billing dimension moves from
        `AUTHORIZED` to `SETTLED`; and the invoice is reconciled against the
        hold by adjusting the merchant's `billing_balance_cents` by the
        difference between `merchant_invoice_cents` and `quoted_fee_cents` —
        a negative difference refunds the merchant. Completion also computes
        the order's late-delivery credit and emits a merchant-visible
        `DELIVERED` event; if every order in the parent batch is now in a
        terminal fulfillment state, the batch moves to `COMPLETED`."
        PRD section 3.6: "Creation sets each order's `batch_id`, computes the
        batch's `courier_cost_cents` as a base of 400 cents plus 150 cents per
        order, increments the courier's `version`, and leaves the batch
        `COURIER_ASSIGNED`."

        Design: Corner/state_machines/order_happy_path_full_chain_and_batch_auto_complete
        """
        env = _delivered_env(api)
        order = env["order"]
        assert order["fulfillment_status"] == "DELIVERED"
        assert order["billing_status"] == "SETTLED"
        assert order["delivered_at"] is not None
        assert order["delivered_at"].startswith("2026-09-01T01:00:00")
        assert order["late_credit_cents"] == 0
        assert order["merchant_invoice_cents"] == 500
        assert order["batch_fee_share_cents"] == 550  # 400 + 150 * 1

        merchant = get_merchant(env["merchant"]["id"])
        assert merchant["billing_balance_cents"] == 99500

        assert env["batch"]["status"] == "COMPLETED"
        assert env["batch"]["courier_cost_cents"] == 550


class TestPickupPrecondition:
    def test_pickup_without_dispatched_batch_returns_invalid_state(self, api):
        """PRD section 3.6: "Confirming pickup moves an order from
        `READY_FOR_PICKUP` to `PICKED_UP` and requires the acting courier to
        be the one whose `courier_id` is on the order's `DISPATCHED` batch —
        the `X-User-ID` must match — otherwise `ERR_INVALID_STATE`; a
        merchant-visible `PICKED_UP` event is emitted."

        Design: Corner/state_machines/pickup_without_dispatched_batch_returns_invalid_state
        """
        env = base_chain()
        m_id = env["merchant"]["id"]
        s_id = env["store"]["id"]
        c_id = env["courier"]["id"]
        order = make_order_ready_fresh(m_id, s_id, "pk-1")
        batch_orders(s_id, c_id, [order["id"]])  # created but NOT dispatched

        resp = api.confirm_pickup(order["id"], c_headers(c_id))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        order_after = get_order(m_id, order["id"])
        assert order_after["fulfillment_status"] == "READY_FOR_PICKUP"

        events, _ = validate_paginated(
            api.list_tracking_events(order["id"], m_headers(m_id))
        )
        assert len(events) == 1
        assert events[0]["event_type"] == "ORDER_ACCEPTED"


class TestUndeliverableDisposition:
    def _undeliverable_env(self, api, reason_code):
        env = base_chain()
        m_id = env["merchant"]["id"]
        s_id = env["store"]["id"]
        c_id = env["courier"]["id"]
        order = make_order_ready_fresh(m_id, s_id, "ud-1",
                                       promised_at="2026-09-01T02:00:00Z")
        batch = batch_orders(s_id, c_id, [order["id"]])
        dispatch_batch(c_id, batch["id"])
        drive_to_in_transit(c_id, order["id"])
        set_clock("2026-09-01T01:00:00Z")
        order = report_undeliverable(c_id, order["id"], reason_code)
        env = dict(env)
        env.update({"order": order, "batch_id": batch["id"]})
        return env

    def test_disposition_return_to_store_terminal(self, api):
        """PRD section 3.7: "Choosing `RETURN_TO_STORE` as the `resolution`
        creates a `PENDING` disposition whose `return_fee_cents` carry the
        platform's fixed return-handling fee, debits that fee from the
        merchant's `billing_balance_cents`, moves the order to
        `RETURN_IN_PROGRESS`, and emits a merchant-visible
        `RETURN_IN_PROGRESS` event. ... The courier then completes the
        disposition by supplying an `outcome`: `RETURNED` completes a
        return-to-store disposition and moves the order to `RETURNED_TO_STORE`
        with the corresponding merchant-visible event"
        PRD section 3.7: "Reporting settles the order financially exactly as
        a completed delivery — billing moves to `SETTLED`, the invoice is
        reconciled the same way, and the merchant still pays"

        Design: Corner/state_machines/undeliverable_disposition_return_to_store_terminal
        """
        env = self._undeliverable_env(api, "CUSTOMER_UNAVAILABLE")
        m_id = env["merchant"]["id"]
        order = env["order"]
        assert order["fulfillment_status"] == "UNDELIVERABLE"
        assert order["billing_status"] == "SETTLED"
        assert get_merchant(m_id)["billing_balance_cents"] == 99500

        disposition = make_disposition(m_id, order["id"], "RETURN_TO_STORE")
        # The PRD requires a fixed platform return-handling fee but does not
        # pin its numeric value; assert the PRD-covered invariants only:
        # a positive fixed fee, debited exactly from the billing balance.
        return_fee = disposition["return_fee_cents"]
        assert isinstance(return_fee, int) and return_fee > 0
        assert disposition["status"] == "PENDING"
        assert get_merchant(m_id)["billing_balance_cents"] == 99500 - return_fee

        completed = validate_success(
            api.complete_disposition(
                disposition["id"], {"outcome": "RETURNED"},
                env["courier_headers"],
            )
        )
        assert completed["status"] == "COMPLETED"

        order_after = get_order(m_id, order["id"])
        assert order_after["fulfillment_status"] == "RETURNED_TO_STORE"
        assert get_batch(env["batch_id"])["status"] == "COMPLETED"

    def test_disposition_dispose_terminal(self, api):
        """PRD section 3.7: "Choosing `DISPOSE` creates a `PENDING`
        disposition with `return_fee_cents` of zero and moves the order to
        `DISPOSAL_PENDING`."
        PRD section 3.7: "`DISPOSED` completes a dispose disposition and moves
        the order to `DISPOSED` likewise."

        Design: Corner/state_machines/undeliverable_disposition_dispose_terminal
        """
        env = self._undeliverable_env(api, "ADDRESS_ISSUE")
        m_id = env["merchant"]["id"]
        order = env["order"]

        disposition = make_disposition(m_id, order["id"], "DISPOSE")
        assert disposition["return_fee_cents"] == 0

        order_mid = get_order(m_id, order["id"])
        assert order_mid["fulfillment_status"] == "DISPOSAL_PENDING"

        validate_success(
            api.complete_disposition(
                disposition["id"], {"outcome": "DISPOSED"}, env["courier_headers"]
            )
        )
        order_after = get_order(m_id, order["id"])
        assert order_after["fulfillment_status"] == "DISPOSED"
        assert get_merchant(m_id)["billing_balance_cents"] == 99500, (
            "DISPOSE must not debit any return fee"
        )

    def test_disposition_on_non_undeliverable_order_rejected(self, api):
        """PRD section 3.7: "Requesting a disposition for an order that is not
        `UNDELIVERABLE`, or a second disposition for an order already
        disposed, is rejected with `ERR_DISPOSITION_NOT_REQUIRED`."

        Design: Corner/state_machines/disposition_on_non_undeliverable_order_rejected
        """
        env = base_chain()
        m_id = env["merchant"]["id"]
        s_id = env["store"]["id"]
        c_id = env["courier"]["id"]
        order = make_order_ready_fresh(m_id, s_id, "dn-1")
        batch = batch_orders(s_id, c_id, [order["id"]])
        dispatch_batch(c_id, batch["id"])
        drive_to_in_transit(c_id, order["id"])

        resp = api.create_disposition(
            order["id"], {"resolution": "DISPOSE"}, m_headers(m_id)
        )
        validate_error(resp, ApiErrorId.ERR_DISPOSITION_NOT_REQUIRED)

        dispositions, _ = validate_paginated(
            api.list_dispositions(order["id"], m_headers(m_id))
        )
        assert dispositions == []
        assert get_order(m_id, order["id"])["fulfillment_status"] == "IN_TRANSIT"

    def test_disposition_complete_with_mismatched_outcome_rejected(self, api):
        """PRD section 3.7: "The outcome must match the disposition's
        `resolution`, the disposition must still be `PENDING` (otherwise
        `ERR_INVALID_STATE`), and completion marks the disposition `COMPLETED`
        and auto-completes the parent batch when all its orders are terminal."
        PRD section 3 (final note): "a missing required field, a type
        mismatch, an enum value outside its declared set, or a structural
        payload error — for example an `order_ids` array whose size falls
        outside the one-to-three range or a disposition completion whose
        `outcome` does not match the disposition's `resolution` — is rejected
        with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/state_machines/disposition_complete_with_mismatched_outcome_rejected
        """
        env = self._undeliverable_env(api, "DAMAGED_IN_TRANSIT")
        m_id = env["merchant"]["id"]
        order = env["order"]
        disposition = make_disposition(m_id, order["id"], "DISPOSE")

        resp = api.complete_disposition(
            disposition["id"], {"outcome": "RETURNED"}, env["courier_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        dispositions, _ = validate_paginated(
            api.list_dispositions(order["id"], m_headers(m_id))
        )
        assert len(dispositions) == 1
        assert dispositions[0]["status"] == "PENDING"
        assert get_order(m_id, order["id"])["fulfillment_status"] == "DISPOSAL_PENDING"


class TestTerminalStateLockdown:
    def test_delivered_and_cancelled_states_are_absorbing(self, api):
        """PRD section 3.5: "From any other fulfillment state, cancellation is
        rejected with `ERR_INVALID_STATE`."
        PRD section 3.6: "Starting transit moves `PICKED_UP` to `IN_TRANSIT`
        with a merchant-visible `IN_TRANSIT` event."
        PRD section 3.7: "An order that cannot be delivered is reported
        undeliverable from either `PICKED_UP` or `IN_TRANSIT` by the courier"

        Design: Corner/state_machines/terminal_state_lockdown_delivered_and_cancelled
        """
        env = _delivered_env(api)
        m_id = env["merchant"]["id"]
        c_id = env["courier"]["id"]
        o1 = env["order"]

        quote2 = new_quote(m_id, env["store"]["id"], address_text="11 Dest Rd")
        o2 = make_order_from_quote(m_id, quote2["id"], "co-2")
        validate_success(api.cancel_order(o2["id"], m_headers(m_id)))

        validate_error(api.start_transit(o1["id"], c_headers(c_id)),
                       ApiErrorId.ERR_INVALID_STATE)
        validate_error(
            api.report_undeliverable(o1["id"], {"reason_code": "ADDRESS_ISSUE"},
                                     c_headers(c_id)),
            ApiErrorId.ERR_INVALID_STATE,
        )
        validate_error(api.cancel_order(o1["id"], m_headers(m_id)),
                       ApiErrorId.ERR_INVALID_STATE)
        validate_error(api.cancel_order(o2["id"], m_headers(m_id)),
                       ApiErrorId.ERR_INVALID_STATE)

        o1_after = get_order(m_id, o1["id"])
        assert o1_after["fulfillment_status"] == "DELIVERED"
        assert o1_after["billing_status"] == "SETTLED"
        o2_after = get_order(m_id, o2["id"])
        assert o2_after["fulfillment_status"] == "CANCELLED"
        assert o2_after["billing_status"] == "VOIDED"


class TestMerchantSuspension:
    def test_suspend_cancels_open_orders_and_releases_holds(self, api):
        """PRD section 3.1: "Suspension moves an `ACTIVE` merchant to
        `SUSPENDED` and cascades through its book of work: every delivery
        order still in `QUOTED`, `ACCEPTED`, or `READY_FOR_PICKUP` is
        cancelled, each such order's billing moves to `VOIDED`, and any order
        whose fee had been authorized releases its hold by adding its
        `quoted_fee_cents` back to the merchant's `billing_balance_cents`. ...
        Resuming returns a `SUSPENDED` merchant to `ACTIVE`."

        Design: Corner/state_machines/merchant_suspend_endpoint_cancels_open_orders_and_releases_holds
        """
        env = base_chain(with_courier=False)
        m_id = env["merchant"]["id"]
        quote = new_quote(m_id, env["store"]["id"])
        order = make_order_from_quote(m_id, quote["id"], "sp-1")
        validate_success(
            api.accept_order(order["id"], {"promised_at": "2026-09-01T02:00:00Z"},
                             m_headers(m_id))
        )
        assert get_merchant(m_id)["billing_balance_cents"] == 99500

        suspended = validate_success(api.suspend_merchant(m_id, admin_headers()))
        assert suspended["status"] == "SUSPENDED"

        merchant = get_merchant(m_id)
        assert merchant["billing_balance_cents"] == 100000, "hold must be released"
        order_after = get_order(m_id, order["id"])
        assert order_after["fulfillment_status"] == "CANCELLED"
        assert order_after["billing_status"] == "VOIDED"

        resumed = validate_success(api.resume_merchant(m_id, admin_headers()))
        assert resumed["status"] == "ACTIVE"


class TestCancelCompensation:
    def test_cancel_accepted_order_releases_hold_quoted_does_not(self, api):
        """PRD section 3.5: "Cancelling a `QUOTED` order moves it to
        `CANCELLED` and voids its billing — no hold ever existed, so nothing
        is returned. Cancelling an `ACCEPTED` order moves it to `CANCELLED`,
        voids the billing, and releases the hold by crediting
        `quoted_fee_cents` back to `billing_balance_cents`, emitting a
        `CANCELLED` tracking event."

        Design: Corner/state_machines/cancel_accepted_order_releases_hold
        """
        env = base_chain(with_courier=False)
        m_id = env["merchant"]["id"]
        quote1 = new_quote(m_id, env["store"]["id"])
        o1 = make_order_from_quote(m_id, quote1["id"], "cx-1")
        validate_success(
            api.accept_order(o1["id"], {"promised_at": "2026-09-01T02:00:00Z"},
                             m_headers(m_id))
        )
        quote2 = new_quote(m_id, env["store"]["id"], address_text="11 Dest Rd")
        o2 = make_order_from_quote(m_id, quote2["id"], "cx-2")
        assert get_merchant(m_id)["billing_balance_cents"] == 99500

        cancelled1 = validate_success(api.cancel_order(o1["id"], m_headers(m_id)))
        assert cancelled1["billing_status"] == "VOIDED"
        assert get_merchant(m_id)["billing_balance_cents"] == 100000, (
            "cancelling ACCEPTED must release the 500-cent hold"
        )

        cancelled2 = validate_success(api.cancel_order(o2["id"], m_headers(m_id)))
        assert cancelled2["billing_status"] == "VOIDED"
        assert get_merchant(m_id)["billing_balance_cents"] == 100000, (
            "cancelling QUOTED never held funds, so nothing is returned"
        )
        assert cancelled1["fulfillment_status"] == "CANCELLED"
        assert cancelled2["fulfillment_status"] == "CANCELLED"


class TestParallelDimensions:
    def test_mid_flight_pair_in_transit_authorized_then_settled_on_delivery(self, api):
        """PRD section 3.5: "fulfillment status `QUOTED` and billing status
        `PENDING` — the order carries these two status dimensions in parallel"
        PRD section 3.5: "the `billing_status` dimension moves from `PENDING`
        to `AUTHORIZED` and the merchant's `billing_balance_cents` is debited
        by the `quoted_fee_cents`."
        PRD section 3.7: "the billing dimension moves from `AUTHORIZED` to
        `SETTLED`"
        PRD section 3.8: "The order's billing must be `SETTLED` — a claim
        against an order in any other billing state is rejected with
        `ERR_CLAIM_ORDER_NOT_SETTLED`"

        Design: Difficulty/non_linear_state_machine/delivery_order_parallel_fulfillment_and_billing_dimensions
        """
        env = base_chain()
        m_id = env["merchant"]["id"]
        s_id = env["store"]["id"]
        c_id = env["courier"]["id"]
        order = make_order_ready_fresh(m_id, s_id, "pd-1")
        batch = batch_orders(s_id, c_id, [order["id"]])
        dispatch_batch(c_id, batch["id"])
        drive_to_in_transit(c_id, order["id"])

        mid = get_order(m_id, order["id"])
        assert mid["fulfillment_status"] == "IN_TRANSIT"
        assert mid["billing_status"] == "AUTHORIZED", (
            "billing lags fulfillment mid-flight: the pair (IN_TRANSIT, AUTHORIZED) "
            "must be representable"
        )

        set_clock("2026-09-01T01:00:00Z")
        done = complete_delivery(c_id, order["id"])
        assert done["fulfillment_status"] == "DELIVERED"
        assert done["billing_status"] == "SETTLED"

        claim = file_claim(m_id, order["id"], "COURIER_DELAY", 200)
        assert claim["status"] == "FILED", (
            "billing SETTLED admits a refund claim while fulfillment stays DELIVERED"
        )

    def test_billing_status_tracks_independently_at_each_fulfillment_step(self, api):
        """PRD section 3.5: "fulfillment status `QUOTED` and billing status
        `PENDING` — the order carries these two status dimensions in parallel"
        PRD section 3.5: "Acceptance authorizes funds: the `billing_status`
        dimension moves from `PENDING` to `AUTHORIZED`"
        PRD section 3.7: "the billing dimension moves from `AUTHORIZED` to
        `SETTLED`"

        Design: Difficulty/non_linear_state_machine/delivery_order_parallel_fulfillment_and_billing_dimensions
        """
        env = base_chain()
        m_id = env["merchant"]["id"]
        s_id = env["store"]["id"]
        c_id = env["courier"]["id"]

        quote = new_quote(m_id, s_id)
        order = make_order_from_quote(m_id, quote["id"], "pd-2")
        assert (order["fulfillment_status"], order["billing_status"]) == ("QUOTED", "PENDING")

        accepted = validate_success(
            api.accept_order(order["id"], {"promised_at": "2026-09-01T02:00:00Z"},
                             m_headers(m_id))
        )
        assert (accepted["fulfillment_status"], accepted["billing_status"]) == (
            "ACCEPTED", "AUTHORIZED")

        ready = validate_success(api.mark_ready(order["id"], m_headers(m_id)))
        assert (ready["fulfillment_status"], ready["billing_status"]) == (
            "READY_FOR_PICKUP", "AUTHORIZED")

        batch = batch_orders(s_id, c_id, [order["id"]])
        dispatch_batch(c_id, batch["id"])
        picked = validate_success(api.confirm_pickup(order["id"], c_headers(c_id)))
        assert (picked["fulfillment_status"], picked["billing_status"]) == (
            "PICKED_UP", "AUTHORIZED")

        transit = validate_success(api.start_transit(order["id"], c_headers(c_id)))
        assert (transit["fulfillment_status"], transit["billing_status"]) == (
            "IN_TRANSIT", "AUTHORIZED")

        set_clock("2026-09-01T01:00:00Z")
        done = complete_delivery(c_id, order["id"])
        assert (done["fulfillment_status"], done["billing_status"]) == (
            "DELIVERED", "SETTLED")
        assert done["delivered_at"] is not None
