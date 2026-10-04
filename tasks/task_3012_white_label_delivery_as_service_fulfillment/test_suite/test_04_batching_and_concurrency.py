"""Batching, dispatch constraints, OCC guards, batch fail/release, and the
batch fee allocation (PRD sections 2.8, 3.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_courier,
    add_store,
    admin_headers,
    base_chain,
    batch_orders,
    c_headers,
    create_batch_payload,
    courier_version,
    dispatch_batch,
    drive_to_picked_up,
    get_batch,
    get_merchant,
    get_order,
    m_headers,
    make_order_ready_fresh,
    merchant_version,
    new_quote,
    set_clock,
    set_surge,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import create_pricing_policy_payload


class TestOccGuards:
    def test_stale_occ_errors(self, api):
        """PRD section 2.8: "Activating a pricing policy
        (`POST /merchants/{id}/pricing-policies/{pid}/activate`) archives the
        merchant's currently active policy and increments the merchant's
        `version`. The request must carry `expected_merchant_version` equal to
        the merchant's current `version`. If the merchant's version has
        advanced since the client last read it, the request is rejected with
        `ERR_STALE_MERCHANT_VERSION` (HTTP 412), so a superseding activation
        is never silently clobbered by a stale one."
        PRD section 2.8: "Creating a delivery batch (`POST /delivery-batches`)
        commits workload against a courier and increments the courier's
        `version`. The request must carry `expected_courier_version` equal to
        the courier's current `version`. If the courier's version has advanced
        since the client last read it, the request is rejected with
        `ERR_STALE_COURIER_VERSION` (HTTP 412), preventing the client from
        building on a view of the courier's committed workload it has not
        observed."

        Design: Corner/calculations/stale_occ_errors
        """
        env = base_chain()
        m_id = env["merchant"]["id"]
        s_id = env["store"]["id"]
        c_id = env["courier"]["id"]

        # m_version_at_read is the version captured before any further
        # merchant mutation; the policy activation in base_chain already
        # bumped it, and we capture the current one for comparison.
        stale_merchant_version = env["merchant"]["version"] - 1
        p2_resp = api.create_pricing_policy(
            m_id,
            create_pricing_policy_payload(
                distance_bands=[{"max_m": 3000, "base_cents": 600, "per_100m_cents": 0}],
                value_tiers=[], peak_windows=[], peak_uplift_pct=0.0,
                effective_from="2027-01-01T00:00:00Z",
                effective_until="2028-01-01T00:00:00Z",
            ),
            m_headers(m_id),
        )
        p2 = validate_success(p2_resp, 201)

        stale_policy = api.activate_pricing_policy(
            m_id, p2["id"],
            {"expected_merchant_version": stale_merchant_version},
            m_headers(m_id),
        )
        validate_error(stale_policy, ApiErrorId.ERR_STALE_MERCHANT_VERSION)

        # Courier OCC: first batch create consumes the version; a replay is stale.
        order = make_order_ready_fresh(m_id, s_id, "occ-1")
        c_v = courier_version(c_id)
        first = validate_success(
            api.create_batch(
                create_batch_payload(s_id, c_id, [order["id"]], c_v), admin_headers()
            ),
            201,
        )
        second = api.create_batch(
            create_batch_payload(
                s_id, c_id, [order["id"]], c_v,
                dispatch_window_start="2026-09-01T02:00:00Z",
                dispatch_window_end="2026-09-01T03:00:00Z",
            ),
            admin_headers(),
        )
        validate_error(second, ApiErrorId.ERR_STALE_COURIER_VERSION)

        # Fresh database: exactly one batch exists globally.
        batches, _ = validate_paginated(api.list_batches(admin_headers()))
        assert len(batches) == 1
        assert batches[0]["id"] == first["id"]

    def test_version_increments_on_every_mutation(self, api):
        """PRD section 2.4: "`version` (integer): starts at its initial value
        on creation and increments by one on every mutation of the resource."
        PRD section 3.1: "Each of these lifecycle transitions increments the
        merchant's `version`, as does any configuration update to
        `default_refund_split_merchant_pct` or `late_credit_enabled`."
        PRD section 2.8: "If the merchant's version has advanced since the
        client last read it, the request is rejected with
        `ERR_STALE_MERCHANT_VERSION` (HTTP 412)"

        Design: Corner/cross_cutting_layers/occ_version_increments_on_every_mutation
        """
        from test_helpers import (
            activate_merchant,
            add_policy,
            add_store,
            new_merchant,
        )

        set_clock()
        merchant = new_merchant()
        assert merchant["version"] == 1
        activate_merchant(merchant["id"])
        add_store(merchant["id"])
        policy = add_policy(merchant["id"])

        patched = validate_success(
            api.update_merchant(
                merchant["id"], {"default_refund_split_merchant_pct": 60},
                m_headers(merchant["id"]),
            )
        )
        assert patched["version"] == 3

        activated = validate_success(
            api.activate_pricing_policy(
                merchant["id"], policy["id"],
                {"expected_merchant_version": patched["version"]},
                m_headers(merchant["id"]),
            )
        )
        assert activated["status"] == "ACTIVE"
        assert get_merchant(merchant["id"])["version"] == 4

        stale = api.activate_pricing_policy(
            merchant["id"], policy["id"],
            {"expected_merchant_version": patched["version"]},
            m_headers(merchant["id"]),
        )
        validate_error(stale, ApiErrorId.ERR_STALE_MERCHANT_VERSION)

        assert get_merchant(merchant["id"])["default_refund_split_merchant_pct"] == 60


def _two_batches_touching(api, capacity=4):
    env = base_chain(courier_overrides={"max_active_deliveries": capacity})
    m_id = env["merchant"]["id"]
    s_id = env["store"]["id"]
    c_id = env["courier"]["id"]
    o1 = make_order_ready_fresh(m_id, s_id, "wo-1",
                                promised_at="2026-09-01T02:00:00Z")
    o2 = make_order_ready_fresh(m_id, s_id, "wo-2",
                                promised_at="2026-09-01T03:00:00Z",
                                quote_overrides={"address_text": "11 Dest Rd"})
    b1 = batch_orders(s_id, c_id, [o1["id"]],
                      window_start="2026-09-01T00:30:00Z",
                      window_end="2026-09-01T01:30:00Z")
    dispatch_batch(c_id, b1["id"])
    b2 = batch_orders(s_id, c_id, [o2["id"]],
                      window_start="2026-09-01T01:30:00Z",
                      window_end="2026-09-01T02:30:00Z")
    return env, o1, o2, b1, b2


class TestDispatchWindowConflict:
    def test_closed_interval_touch_conflicts(self, api):
        """PRD section 3.6: "that the closed dispatch window not overlap the
        dispatch window of any other `DISPATCHED` batch of the same courier —
        windows that merely touch at an endpoint count as overlapping and are
        rejected with `ERR_COURIER_WINDOW_CONFLICT`"

        Design: Difficulty/resource_temporal_overlap/courier_dispatch_window_closed_interval_touch_conflicts
        """
        env, o1, o2, b1, b2 = _two_batches_touching(api)
        c_id = env["courier"]["id"]

        resp = api.dispatch_batch(b2["id"], c_headers(c_id))
        validate_error(resp, ApiErrorId.ERR_COURIER_WINDOW_CONFLICT)

        assert get_batch(b2["id"])["status"] == "COURIER_ASSIGNED"
        m_id = env["merchant"]["id"]
        assert get_order(m_id, o2["id"])["fulfillment_status"] == "READY_FOR_PICKUP"

    def test_disjoint_window_after_dispatched_batch_is_allowed(self, api):
        """PRD section 3.6: "that the closed dispatch window not overlap the
        dispatch window of any other `DISPATCHED` batch of the same courier —
        windows that merely touch at an endpoint count as overlapping and are
        rejected with `ERR_COURIER_WINDOW_CONFLICT`"

        Design: Difficulty/resource_temporal_overlap/courier_dispatch_window_closed_interval_touch_conflicts
        """
        env = base_chain()
        m_id = env["merchant"]["id"]
        s_id = env["store"]["id"]
        c_id = env["courier"]["id"]
        o1 = make_order_ready_fresh(m_id, s_id, "wo-a",
                                    promised_at="2026-09-01T02:00:00Z")
        o2 = make_order_ready_fresh(m_id, s_id, "wo-b",
                                    promised_at="2026-09-01T05:00:00Z",
                                    quote_overrides={"address_text": "11 Dest Rd"})
        b1 = batch_orders(s_id, c_id, [o1["id"]],
                          window_start="2026-09-01T00:30:00Z",
                          window_end="2026-09-01T01:30:00Z")
        dispatch_batch(c_id, b1["id"])
        # Strictly disjoint (one minute gap): must dispatch cleanly.
        b2 = batch_orders(s_id, c_id, [o2["id"]],
                          window_start="2026-09-01T01:31:00Z",
                          window_end="2026-09-01T02:30:00Z")
        dispatched = validate_success(
            api.dispatch_batch(b2["id"], c_headers(c_id)), 200
        )
        assert dispatched["status"] == "DISPATCHED"


class TestTemporalBeatsCapacity:
    def test_dispatch_temporal_before_constraint_dual_failure(self, api):
        """PRD section 2.6: "The layers, from first to last, are:"
        PRD section 2.6 layer 7: "Temporal conflicts. Courier dispatch-window
        conflicts (`ERR_COURIER_WINDOW_CONFLICT`) and pricing-policy
        effective-window overlaps (`ERR_POLICY_WINDOW_OVERLAP`), both HTTP
        409."
        PRD section 2.6 layer 8: "Business constraints. Batching restrictions,
        courier capacity, batch size, address serviceability, band coverage,
        appeal limits, claim amounts, and disposition-outcome matching
        (`ERR_BATCHING_RESTRICTION_VIOLATION`, `ERR_COURIER_CAPACITY_EXCEEDED`,
        `ERR_INVALID_BATCH_SIZE`, `ERR_ADDRESS_NOT_SERVICEABLE`,
        `ERR_OUTSIDE_DELIVERY_RADIUS`, `ERR_APPEAL_LIMIT_EXCEEDED`,
        `ERR_CLAIM_EXCEEDS_INVOICE`, `ERR_INVALID_REQUEST`)."
        PRD section 2.6: "Because the layers are ordered, a request that fails
        an earlier layer never reaches a later one"

        Design: Difficulty/priority_pair_validation_conflict/dispatch_temporal_before_constraint_dual_failure
        """
        env, o1, o2, b1, b2 = _two_batches_touching(api, capacity=1)
        c_id = env["courier"]["id"]

        resp = api.dispatch_batch(b2["id"], c_headers(c_id))
        data = validate_error(resp, ApiErrorId.ERR_COURIER_WINDOW_CONFLICT)
        assert data["error_id"] != ApiErrorId.ERR_COURIER_CAPACITY_EXCEEDED, (
            "temporal layer (7) must mask the capacity constraint (layer 8)"
        )
        assert get_batch(b2["id"])["status"] == "COURIER_ASSIGNED"

    def test_capacity_alone_fires_when_windows_do_not_touch(self, api):
        """PRD section 3.6: "the courier's committed load stay within
        capacity: the number of orders across the courier's other `DISPATCHED`
        batches plus this batch's size must not exceed
        `max_active_deliveries`, else `ERR_COURIER_CAPACITY_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/dispatch_temporal_before_constraint_dual_failure
        """
        env = base_chain(courier_overrides={"max_active_deliveries": 1})
        m_id = env["merchant"]["id"]
        s_id = env["store"]["id"]
        c_id = env["courier"]["id"]
        o1 = make_order_ready_fresh(m_id, s_id, "pt-a",
                                    promised_at="2026-09-01T02:00:00Z")
        o2 = make_order_ready_fresh(m_id, s_id, "pt-b",
                                    promised_at="2026-09-01T05:00:00Z",
                                    quote_overrides={"address_text": "11 Dest Rd"})
        b1 = batch_orders(s_id, c_id, [o1["id"]],
                          window_start="2026-09-01T00:30:00Z",
                          window_end="2026-09-01T01:30:00Z")
        dispatch_batch(c_id, b1["id"])
        # Disjoint window: only the capacity rule can fail.
        b2 = batch_orders(s_id, c_id, [o2["id"]],
                          window_start="2026-09-01T02:00:00Z",
                          window_end="2026-09-01T03:00:00Z")
        resp = api.dispatch_batch(b2["id"], c_headers(c_id))
        validate_error(resp, ApiErrorId.ERR_COURIER_CAPACITY_EXCEEDED)
        assert get_batch(b2["id"])["status"] == "COURIER_ASSIGNED"


class TestBatchConstraintErrors:
    def test_batch_size_batching_restriction_and_capacity(self, api):
        """PRD section 3.6: "Every order in the batch must belong to the
        batch's store — white-label orders of different stores are never
        co-batched — and every order must already be `READY_FOR_PICKUP`;
        violations are rejected with `ERR_BATCHING_RESTRICTION_VIOLATION`, and
        an `order_ids` array outside the one-to-three range with
        `ERR_INVALID_BATCH_SIZE`."
        PRD section 3.6: "the courier's committed load stay within capacity:
        the number of orders across the courier's other `DISPATCHED` batches
        plus this batch's size must not exceed `max_active_deliveries`, else
        `ERR_COURIER_CAPACITY_EXCEEDED`."

        Design: Corner/calculations/courier_capacity_and_batching_restriction_and_batch_size
        """
        env = base_chain(courier_overrides={"max_active_deliveries": 1})
        m_id = env["merchant"]["id"]
        s_id = env["store"]["id"]
        c_id = env["courier"]["id"]

        store2 = add_store(m_id, name="Second Store", address_text="9 Other Way")

        o1 = make_order_ready_fresh(m_id, s_id, "bc-1",
                                    promised_at="2026-09-01T02:00:00Z")
        b1 = batch_orders(s_id, c_id, [o1["id"]],
                          window_start="2026-09-01T00:30:00Z",
                          window_end="2026-09-01T01:00:00Z")
        dispatch_batch(c_id, b1["id"])

        ready = []
        for i, addr in enumerate(("11 Dest Rd", "12 Dest Rd", "13 Dest Rd"), start=2):
            ready.append(make_order_ready_fresh(
                m_id, s_id, f"bc-{i}", promised_at="2026-09-01T03:00:00Z",
                quote_overrides={"address_text": addr},
            ))
        o5 = make_order_ready_fresh(
            m_id, store2["id"], "bc-5", promised_at="2026-09-01T03:00:00Z",
            quote_overrides={"address_text": "14 Dest Rd"},
        )
        c_v = courier_version(c_id)

        four = api.create_batch(
            create_batch_payload(
                s_id, c_id, [ready[0]["id"], ready[1]["id"], ready[2]["id"], o1["id"]],
                c_v, dispatch_window_start="2026-09-01T02:00:00Z",
                dispatch_window_end="2026-09-01T03:00:00Z",
            ),
            admin_headers(),
        )
        validate_error(four, ApiErrorId.ERR_INVALID_BATCH_SIZE)

        mixed = api.create_batch(
            create_batch_payload(
                s_id, c_id, [ready[0]["id"], o5["id"]], c_v,
                dispatch_window_start="2026-09-01T02:00:00Z",
                dispatch_window_end="2026-09-01T03:00:00Z",
            ),
            admin_headers(),
        )
        validate_error(mixed, ApiErrorId.ERR_BATCHING_RESTRICTION_VIOLATION)

        b2 = validate_success(
            api.create_batch(
                create_batch_payload(
                    s_id, c_id, [ready[0]["id"]], c_v,
                    dispatch_window_start="2026-09-01T02:00:00Z",
                    dispatch_window_end="2026-09-01T03:00:00Z",
                ),
                admin_headers(),
            ),
            201,
        )
        cap = api.dispatch_batch(b2["id"], c_headers(c_id))
        validate_error(cap, ApiErrorId.ERR_COURIER_CAPACITY_EXCEEDED)


class TestBatchFailRelease:
    def test_batch_fail_releases_orders_and_reverts_unpicked_to_ready(self, api):
        """PRD section 3.6: "A batch can also fail. Failing a batch in
        `COURIER_ASSIGNED` or `DISPATCHED` (any other state yields
        `ERR_INVALID_STATE`) releases all of its non-terminal orders by
        clearing their `batch_id`, making them available for a later batch.
        When a `DISPATCHED` batch fails, orders that were never picked up
        revert to `READY_FOR_PICKUP`; invoiced amounts already computed stay
        on the orders, and a later re-dispatch recomputes them."

        Design: Corner/state_machines/batch_fail_releases_orders_and_reverts_unpicked_to_ready
        """
        env = base_chain(merchant_overrides={"billing_balance_cents": 1000})
        m_id = env["merchant"]["id"]
        s_id = env["store"]["id"]
        c_id = env["courier"]["id"]
        courier2 = add_courier(name="Second Courier")

        o1 = make_order_ready_fresh(m_id, s_id, "bf-1",
                                    promised_at="2026-09-01T02:00:00Z")
        o2 = make_order_ready_fresh(m_id, s_id, "bf-2",
                                    promised_at="2026-09-01T02:00:00Z",
                                    quote_overrides={"address_text": "11 Dest Rd"})
        b1 = batch_orders(s_id, c_id, [o1["id"], o2["id"]])
        dispatch_batch(c_id, b1["id"])
        drive_to_picked_up(c_id, o1["id"])  # o1 picked; o2 never picked

        failed = validate_success(api.fail_batch(b1["id"], c_headers(c_id)))
        assert failed["status"] == "FAILED"

        o1_after = get_order(m_id, o1["id"])
        assert o1_after["fulfillment_status"] == "PICKED_UP", (
            "an already-picked order keeps its picked state"
        )
        assert o1_after["batch_id"] is None

        o2_after = get_order(m_id, o2["id"])
        assert o2_after["fulfillment_status"] == "READY_FOR_PICKUP", (
            "a never-picked order reverts to READY_FOR_PICKUP"
        )
        assert o2_after["batch_id"] is None

        # Re-batch the reverted order under a different courier; it dispatches.
        b2 = batch_orders(s_id, courier2["id"], [o2["id"]],
                          window_start="2026-09-01T02:00:00Z",
                          window_end="2026-09-01T03:00:00Z")
        dispatched = validate_success(
            api.dispatch_batch(b2["id"], c_headers(courier2["id"]))
        )
        assert dispatched["status"] == "DISPATCHED"


class TestBatchFeeAllocation:
    def _two_order_dispatch(self, api):
        env = base_chain(surge=2.0)
        m_id = env["merchant"]["id"]
        s_id = env["store"]["id"]
        c_id = env["courier"]["id"]
        o1 = make_order_ready_fresh(
            m_id, s_id, "ba-1", promised_at="2026-09-01T14:00:00Z",
            quote_overrides={
                "dropoff_lat": 0.05, "order_value_cents": 12000,
                "pickup_ready_at": "2026-09-01T12:30:00Z",
            },
        )
        o2 = make_order_ready_fresh(
            m_id, s_id, "ba-2", promised_at="2026-09-01T14:00:00Z",
            quote_overrides={
                "dropoff_lat": 0.02, "order_value_cents": 5000,
                "pickup_ready_at": "2026-09-01T09:00:00Z",
                "address_text": "11 Dest Rd",
            },
        )
        batch = batch_orders(s_id, c_id, [o1["id"], o2["id"]],
                             window_start="2026-09-01T12:00:00Z",
                             window_end="2026-09-01T13:00:00Z")
        validate_success(api.dispatch_batch(batch["id"], env["courier_headers"]), 200)
        return env, batch, o1["id"], o2["id"]

    def test_per_order_floor_with_remainder(self, api):
        """PRD section 3.6: "each order's `batch_fee_share_cents` is allocated
        from the batch courier cost: every order's raw share is the courier
        cost multiplied by that order's invoice and divided by the sum of
        invoices across the batch, each share is floored to whole cents, and
        the leftover remainder after flooring is granted to the order with the
        earliest `created_at`, so the shares sum exactly back to the courier
        cost."

        Design: Difficulty/combinatorial_formula/batch_fee_allocation_per_order_floor_with_remainder
        """
        env, batch, o1_id, o2_id = self._two_order_dispatch(api)
        m_id = env["merchant"]["id"]
        batch_after = get_batch(batch["id"])
        assert batch_after["courier_cost_cents"] == 700

        o1 = get_order(m_id, o1_id)
        o2 = get_order(m_id, o2_id)
        assert o1["merchant_invoice_cents"] == 3376
        assert o2["merchant_invoice_cents"] == 1000
        # floor(700 * 3376 / 4376) == 540; floor(700 * 1000 / 4376) == 159;
        # the 1-cent remainder goes to o1 (earliest created_at).
        assert o1["batch_fee_share_cents"] == 541
        assert o2["batch_fee_share_cents"] == 159

    def test_allocation_conserves_total(self, api):
        """PRD section 2.7: "in the batch fee allocation, each order's share
        is rounded *down* to whole cents and the leftover remainder is granted
        to a single order, so the allocated shares always sum exactly back to
        the batch courier cost."
        PRD section 3.6: "Creation sets each order's `batch_id`, computes the
        batch's `courier_cost_cents` as a base of 400 cents plus 150 cents per
        order, increments the courier's `version`, and leaves the batch
        `COURIER_ASSIGNED`."

        Design: Difficulty/combinatorial_formula/batch_fee_allocation_per_order_floor_with_remainder
        """
        env, batch, o1_id, o2_id = self._two_order_dispatch(api)
        m_id = env["merchant"]["id"]
        batch_after = get_batch(batch["id"])
        o1 = get_order(m_id, o1_id)
        o2 = get_order(m_id, o2_id)
        assert batch_after["courier_cost_cents"] == 400 + 150 * 2
        assert (
            o1["batch_fee_share_cents"] + o2["batch_fee_share_cents"]
            == batch_after["courier_cost_cents"]
        ), "allocated shares must conserve the batch courier cost exactly"
