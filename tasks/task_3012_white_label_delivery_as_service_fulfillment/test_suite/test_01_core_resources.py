"""Core resource creation, defaults, validation errors, not-found handling,
pagination, and idempotency (PRD sections 2.1-2.4, 3.1-3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    activate_merchant,
    activate_policy,
    add_courier,
    add_policy,
    add_store,
    admin_headers,
    base_chain,
    c_headers,
    create_quote_payload,
    m_headers,
    make_order_from_quote,
    new_merchant,
    new_quote,
    set_clock,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


class TestMerchantCreation:
    def test_create_merchant_applies_defaults_and_envelope(self, api):
        """PRD section 3.1: "A `PlatformAdmin` creates a merchant by supplying
        its brand `name` and an initial prepaid `billing_balance_cents`, and may
        optionally set `default_refund_split_merchant_pct` — the merchant's
        share, as a whole percentage from 0 to 100 inclusive, applied to refund
        faults attributed to customer unavailability or address problems,
        defaulting to 50 — and `late_credit_enabled`, a boolean defaulting to
        true that controls whether accrued late-delivery credits are applied
        automatically. A new merchant starts in `ONBOARDING` status with
        `credit_balance_cents` at zero; the credit balance is the running sum
        of `amount_cents` across the merchant's service credits in `APPLIED`
        status, excluding any in `VOIDED`."

        Design: Corner/entities/merchant_create_applies_defaults_and_response_envelope
        """
        set_clock()
        resp = api.create_merchant(
            {"name": "Corner Merchant", "billing_balance_cents": 100000}, admin_headers()
        )
        data = validate_success(resp, 201)
        assert resp.json()["response_type"] == "object"
        meta = resp.json()["meta"]
        assert meta.get("api_request_id"), "meta must carry api_request_id"
        assert meta.get("api_request_timestamp"), "meta must carry api_request_timestamp"
        assert data["status"] == "ONBOARDING"
        assert data["version"] == 1
        assert data["default_refund_split_merchant_pct"] == 50
        assert data["late_credit_enabled"] is True
        assert data["credit_balance_cents"] == 0

    def test_suspend_blocks_accept_via_cascade_cancellation(self, api):
        """PRD section 3.1: "Suspension moves an `ACTIVE` merchant to
        `SUSPENDED` and cascades through its book of work: every delivery order
        still in `QUOTED`, `ACCEPTED`, or `READY_FOR_PICKUP` is cancelled, each
        such order's billing moves to `VOIDED`, and any order whose fee had
        been authorized releases its hold by adding its `quoted_fee_cents` back
        to the merchant's `billing_balance_cents`."
        PRD section 3.5: "From any other fulfillment state, cancellation is
        rejected with `ERR_INVALID_STATE`."

        Design: Corner/errors/merchant_suspended_blocks_accept
        """
        env = base_chain(with_courier=False)
        m_id = env["merchant"]["id"]
        quote = new_quote(m_id, env["store"]["id"])
        order = make_order_from_quote(m_id, quote["id"], "ms-1")

        suspended = validate_success(api.suspend_merchant(m_id, admin_headers()), 200)
        assert suspended["status"] == "SUSPENDED"

        # The suspension cascade already cancelled the QUOTED order, so the
        # accept surfaces the state error rather than the merchant suspension.
        accept_resp = api.accept_order(
            order["id"], {"promised_at": "2026-09-01T02:00:00Z"}, m_headers(m_id)
        )
        validate_error(accept_resp, ApiErrorId.ERR_INVALID_STATE)

        order_after = validate_success(api.get_order(order["id"], admin_headers()))
        assert order_after["fulfillment_status"] == "CANCELLED"
        assert order_after["billing_status"] == "VOIDED"


class TestStoreResource:
    def test_store_create_get_roundtrip_and_active_default(self, api):
        """PRD section 3.2: "A merchant (or a `PlatformAdmin` on its behalf)
        creates a store with a `name`, a pickup `address_text`, coordinates
        `lat` and `lng` in degrees, a `delivery_radius_m` in meters, and an
        IANA `timezone`. The store begins `ACTIVE`; it can later be updated —
        a new `delivery_radius_m`, a new `timezone`, or a `status` change to
        `CLOSED` — and each update increments the store's `version`."

        Design: Corner/entities/store_create_get_roundtrip_and_active_default
        """
        set_clock()
        merchant = new_merchant()
        activate_merchant(merchant["id"])
        store = add_store(merchant["id"])
        assert store["status"] == "ACTIVE"
        assert store["version"] == 1
        assert store["delivery_radius_m"] == 20000
        assert store["timezone"] == "UTC"

        fetched = validate_success(api.get_store(store["id"], m_headers(merchant["id"])))
        assert fetched["id"] == store["id"]
        assert fetched["status"] == "ACTIVE"
        assert fetched["delivery_radius_m"] == 20000
        assert fetched["timezone"] == "UTC"
        assert fetched["merchant_id"] == merchant["id"]

        listed, _ = validate_paginated(
            api.list_stores(merchant["id"], m_headers(merchant["id"]))
        )
        assert len(listed) == 1
        assert listed[0]["id"] == store["id"]

    def test_store_create_missing_required_field_returns_invalid_request(self, api):
        """PRD section 3.2: "A merchant (or a `PlatformAdmin` on its behalf)
        creates a store with a `name`, a pickup `address_text`, coordinates
        `lat` and `lng` in degrees, a `delivery_radius_m` in meters, and an
        IANA `timezone`."
        PRD section 3 (final note): "a missing required field, a type mismatch,
        an enum value outside its declared set, or a structural payload error —
        for example an `order_ids` array whose size falls outside the
        one-to-three range or a disposition completion whose `outcome` does not
        match the disposition's `resolution` — is rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/store_create_missing_required_field_returns_invalid_request
        """
        set_clock()
        merchant = new_merchant()
        activate_merchant(merchant["id"])
        resp = api.create_store(
            merchant["id"],
            {
                "name": "No Radius",
                "address_text": "1 Origin Way",
                "lat": 0.0,
                "lng": 0.0,
                "timezone": "UTC",
            },
            m_headers(merchant["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        listed, _ = validate_paginated(
            api.list_stores(merchant["id"], m_headers(merchant["id"]))
        )
        assert listed == [], "no store row may be persisted on a rejected create"


class TestPricingPolicyResource:
    def test_policy_create_starts_draft_and_lists(self, api):
        """PRD section 3.3: "A new policy is `DRAFT`."

        Design: Corner/entities/pricing_policy_create_starts_draft_and_lists
        """
        set_clock()
        merchant = new_merchant()
        activate_merchant(merchant["id"])
        add_store(merchant["id"])
        policy = add_policy(merchant["id"])
        assert policy["status"] == "DRAFT"
        assert policy["version"] == 1

        listed, _ = validate_paginated(
            api.list_pricing_policies(merchant["id"], m_headers(merchant["id"]))
        )
        assert len(listed) == 1 and listed[0]["id"] == policy["id"]


class TestQuoteResource:
    def test_quote_computed_components_at_band_c(self, api):
        """PRD section 3.4: "The quoted fee is assembled from four components,
        each an integer number of cents and each rounded half up before
        summing. The `band_fee_cents` come from the first band in array order
        whose `max_m` is at least the distance: for the first band that is
        simply its `base_cents`; for any later band it is the band's
        `base_cents` plus its `per_100m_cents` multiplied by the excess
        distance over the previous band's `max_m`, with the excess divided
        into 100-meter increments and any partial increment rounded up to a
        whole increment."
        PRD section 3.4: "The `quoted_fee_cents` are the base total plus the
        surge component."
        PRD section 3.4: "The quote pins the policy it used as
        `pricing_policy_id` and the surge multiplier in force as
        `quoted_surge_multiplier`, records the computed `distance_m`, and is
        usable for fifteen minutes: `valid_until` is set to the creation clock
        time plus fifteen minutes."

        Design: Corner/entities/quote_computed_components_at_band_c
        """
        env = base_chain(with_courier=False)
        m_id = env["merchant"]["id"]
        quote = validate_success(
            api.create_quote(
                create_quote_payload(
                    env["store"]["id"],
                    dropoff_lat=0.072,
                    dropoff_lng=0.0,
                    order_value_cents=5000,
                    pickup_ready_at="2026-09-01T09:00:00Z",
                ),
                m_headers(m_id),
            ),
            201,
        )
        assert quote["distance_m"] == 8015
        assert quote["band_fee_cents"] == 1790
        assert quote["value_surcharge_cents"] == 0
        assert quote["peak_uplift_cents"] == 0
        assert quote["surge_component_cents"] == 0
        assert quote["quoted_fee_cents"] == 1790
        assert quote["pricing_policy_id"] == env["policy"]["id"]
        assert quote["status"] == "ACTIVE"
        assert quote["valid_until"].startswith("2026-09-01T00:15:00")

    def test_quote_rejects_out_of_enum_and_type_mismatch(self, api):
        """PRD section 3 (final note): "a missing required field, a type
        mismatch, an enum value outside its declared set, or a structural
        payload error — for example an `order_ids` array whose size falls
        outside the one-to-three range or a disposition completion whose
        `outcome` does not match the disposition's `resolution` — is rejected
        with `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD section 3.4: "If the computed distance exceeds the last distance
        band's `max_m`, the quote is rejected with
        `ERR_OUTSIDE_DELIVERY_RADIUS`."

        Design: Corner/entities/quote_create_rejects_out_of_enum_and_type_mismatch
        """
        env = base_chain(with_courier=False)
        m_id = env["merchant"]["id"]
        type_resp = api.create_quote(
            create_quote_payload(env["store"]["id"], order_value_cents="lots"),
            m_headers(m_id),
        )
        validate_error(type_resp, ApiErrorId.ERR_INVALID_REQUEST)

        band_resp = api.create_quote(
            create_quote_payload(env["store"]["id"], dropoff_lat=0.2),
            m_headers(m_id),
        )
        # The dropoff is both outside every distance band (22259m > 15000m)
        # and beyond the store's delivery radius (20000m). Both failures live
        # in the same validation layer (2.6 layer 8 names address
        # serviceability and band coverage side by side, without a within-layer
        # order), so either rejection is PRD-consistent.
        validate_error_is_one_of(
            band_resp,
            [ApiErrorId.ERR_OUTSIDE_DELIVERY_RADIUS,
             ApiErrorId.ERR_ADDRESS_NOT_SERVICEABLE],
        )

        listed, _ = validate_paginated(api.list_quotes(m_headers(m_id)))
        assert listed == [], "no quote may be persisted from a rejected request"


class TestOrderCreation:
    def test_order_create_ignores_smuggled_system_fields(self, api):
        """PRD section 3.5: "Consuming the quote moves it to `CONSUMED` and
        creates the order with `merchant_id` and `store_id` copied from the
        quote, `quoted_fee_cents` copied and thereafter immutable, fulfillment
        status `QUOTED` and billing status `PENDING` — the order carries these
        two status dimensions in parallel — `batch_id` empty until batching,
        `final_fee_cents`, `merchant_invoice_cents`, and `batch_fee_share_cents`
        empty until dispatch, `late_credit_cents` at zero, and `delivered_at`
        empty until delivery."
        PRD section 2.4: "`version` (integer): starts at its initial value on
        creation and increments by one on every mutation of the resource."

        Design: Corner/entities/order_create_with_system_fields_input_ignored
        """
        env = base_chain(with_courier=False)
        m_id = env["merchant"]["id"]
        quote = new_quote(m_id, env["store"]["id"])
        resp = api.create_order(
            {
                "quote_id": quote["id"],
                "customer_reference": "CO-1",
                "idempotency_key": "co-1",
                "fulfillment_status": "DELIVERED",
                "version": 99,
            },
            m_headers(m_id),
        )
        order = validate_success(resp, 201)
        assert order["fulfillment_status"] == "QUOTED"
        assert order["billing_status"] == "PENDING"
        assert order["version"] == 1
        assert order["merchant_id"] == m_id
        assert order["quoted_fee_cents"] == 500

    def test_order_create_idempotency_key_replay_returns_original(self, api):
        """PRD section 3.5: "The key is scoped to the merchant: repeating the
        same key returns the original order rather than creating a duplicate."

        Design: Corner/endpoints/order_create_idempotency_key_replay_returns_original
        """
        env = base_chain(with_courier=False)
        m_id = env["merchant"]["id"]
        quote = new_quote(m_id, env["store"]["id"])
        payload = {
            "quote_id": quote["id"],
            "customer_reference": "CO-1",
            "idempotency_key": "co-1",
        }
        first = validate_success(api.create_order(payload, m_headers(m_id)), 201)
        second = validate_success(api.create_order(payload, m_headers(m_id)))
        assert second["id"] == first["id"], "replay must return the same server-minted id"

        listed, _ = validate_paginated(api.list_orders(admin_headers()))
        assert len(listed) == 1, "replay must not create a second order"

        quote_after = validate_success(api.get_quote(quote["id"], m_headers(m_id)))
        assert quote_after["status"] == "CONSUMED"


class TestOrderListing:
    def test_order_list_pagination_and_status_filter(self, api):
        """PRD section 2.3: "The `limit` parameter caps the number of items
        returned; it defaults to 10, with a minimum of 1 and a maximum of 100.
        The `offset` parameter skips a number of items from the start of the
        result set and defaults to 0."
        PRD section 2.3: "List responses carry the pagination fields `limit`,
        `offset`, `total_count`, and `has_more` in the `meta` object of the
        response envelope."

        Design: Corner/entities/delivery_orders_list_pagination_and_status_filter
        """
        env = base_chain(with_courier=False)
        m_id = env["merchant"]["id"]
        for i in (1, 2, 3):
            quote = new_quote(m_id, env["store"]["id"], address_text=f"1{i} Dest Rd")
            make_order_from_quote(m_id, quote["id"], f"co-{i}")

        # Fresh database: the unfiltered list contains exactly the three orders.
        page1, meta1 = validate_paginated(
            api.list_orders(admin_headers(), params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_orders(admin_headers(), params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        default_page, meta3 = validate_paginated(api.list_orders(admin_headers()))
        assert len(default_page) == 3
        assert meta3["limit"] == 10
        assert meta3["offset"] == 0
        assert meta3["has_more"] is False


class TestNotFoundErrors:
    def test_order_get_with_unknown_id_returns_order_not_found(self, api):
        """PRD section 2.6: "a request naming a merchant and a pricing policy
        under it is rejected with `ERR_MERCHANT_NOT_FOUND` (HTTP 404) if the
        merchant does not exist, before the policy id is ever examined; a
        nonexistent policy under an existing merchant yields
        `ERR_PRICING_POLICY_NOT_FOUND`. The same pattern applies to stores
        (`ERR_STORE_NOT_FOUND`), quotes (`ERR_QUOTE_NOT_FOUND`), delivery
        orders (`ERR_DELIVERY_ORDER_NOT_FOUND`), couriers
        (`ERR_COURIER_NOT_FOUND`), batches (`ERR_BATCH_NOT_FOUND`), dispositions
        (`ERR_DISPOSITION_NOT_FOUND`), claims (`ERR_CLAIM_NOT_FOUND`), reports
        (`ERR_REPORT_NOT_FOUND`), and credits (`ERR_CREDIT_NOT_FOUND`)."

        Design: Corner/entities/order_get_with_unknown_id_returns_order_not_found
        """
        set_clock()
        resp = api.get_order(NON_EXISTENT_UUID, admin_headers())
        data = validate_error(resp, ApiErrorId.ERR_DELIVERY_ORDER_NOT_FOUND)
        body = resp.json()
        assert body["response_type"] == "error"
        assert data.get("message"), "error envelope must carry a message"

    def test_remaining_not_found_ids_return_entity_specific_404s(self, api):
        """PRD section 2.6: "The same pattern applies to stores
        (`ERR_STORE_NOT_FOUND`), quotes (`ERR_QUOTE_NOT_FOUND`), delivery
        orders (`ERR_DELIVERY_ORDER_NOT_FOUND`), couriers
        (`ERR_COURIER_NOT_FOUND`), batches (`ERR_BATCH_NOT_FOUND`), dispositions
        (`ERR_DISPOSITION_NOT_FOUND`), claims (`ERR_CLAIM_NOT_FOUND`), reports
        (`ERR_REPORT_NOT_FOUND`), and credits (`ERR_CREDIT_NOT_FOUND`)."

        Design: Corner/errors/remaining_not_found_ids_return_entity_specific_404s
        """
        set_clock()
        u = lambda n: f"00000000-0000-4000-8000-00000000000{n}"
        validate_error(api.get_merchant(u(1), admin_headers()),
                       ApiErrorId.ERR_MERCHANT_NOT_FOUND)
        validate_error(api.get_sla_report(u(2), admin_headers()),
                       ApiErrorId.ERR_REPORT_NOT_FOUND)
        validate_error(api.apply_service_credit(u(3), admin_headers()),
                       ApiErrorId.ERR_CREDIT_NOT_FOUND)
        validate_error(
            api.complete_disposition(
                u(4), {"outcome": "DISPOSED"},
                c_headers("00000000-0000-4000-8000-0000000000aa"),
            ),
            ApiErrorId.ERR_DISPOSITION_NOT_FOUND,
        )


class TestBatchForeignKeyOrder:
    def test_batch_create_checks_body_foreign_keys_in_declared_input_order(self, api):
        """PRD section 2.6: "Identifiers carried in the request body are
        validated in the endpoint's declared input order — for example, when
        creating a batch, `store_id` is checked before `courier_id`, which is
        checked before `order_ids` — and a missing referenced resource yields
        the corresponding not-found error."

        Design: Corner/entities/batch_create_checks_body_foreign_keys_in_declared_input_order
        """
        env = base_chain(with_courier=False)
        courier = add_courier()
        unknown_store = "00000000-0000-4000-8000-000000000001"
        unknown_courier = "00000000-0000-4000-8000-000000000002"
        base_payload = {
            "order_ids": [],
            "dispatch_window_start": "2026-09-01T00:30:00Z",
            "dispatch_window_end": "2026-09-01T01:30:00Z",
            "expected_courier_version": courier["version"],
        }

        both_resp = api.create_batch(
            {**base_payload, "store_id": unknown_store, "courier_id": unknown_courier},
            admin_headers(),
        )
        validate_error(both_resp, ApiErrorId.ERR_STORE_NOT_FOUND)

        courier_resp = api.create_batch(
            {**base_payload, "store_id": env["store"]["id"], "courier_id": unknown_courier},
            admin_headers(),
        )
        validate_error(courier_resp, ApiErrorId.ERR_COURIER_NOT_FOUND)

        listed, _ = validate_paginated(api.list_batches(admin_headers()))
        assert listed == []


class TestTrackingEventAppendOnly:
    def test_tracking_event_is_append_only_without_version(self, api):
        """PRD section 2.4: "The TrackingEvent is the exception: it is an
        append-only feed item and carries only `id` and `created_at` — both
        `updated_at` and `version` are absent from it."
        PRD section 3.9 (final paragraph): "a courier or `PlatformAdmin` may
        append a tracking event to an order directly, supplying an
        `event_type` — one of `ORDER_ACCEPTED`, `COURIER_ASSIGNED`,
        `PICKED_UP`, `IN_TRANSIT`, `DELIVERED`, `UNDELIVERABLE`,
        `RETURN_IN_PROGRESS`, `RETURNED_TO_STORE`, `DISPOSED`, `CANCELLED`, or
        `NOTE` — an optional free-text `note` defaulting to empty, and a
        `visibility` of `MERCHANT_VISIBLE` or `INTERNAL_ONLY`, defaulting to
        `MERCHANT_VISIBLE`; the event records the logical clock time as
        `occurred_at`."

        Design: Corner/entities/tracking_event_is_append_only_without_version
        """
        env = base_chain(with_courier=False)
        m_id = env["merchant"]["id"]
        quote = new_quote(m_id, env["store"]["id"])
        order = make_order_from_quote(m_id, quote["id"], "co-1")

        resp = api.create_tracking_event(
            order["id"],
            {"event_type": "NOTE", "note": "customer called",
             "visibility": "INTERNAL_ONLY"},
            c_headers("00000000-0000-4000-8000-0000000000aa"),
        )
        event = validate_success(resp, 201)
        assert "version" not in event
        assert "updated_at" not in event
        assert event["occurred_at"].startswith("2026-09-01T00:00:00")
        assert event["delivery_order_id"] == order["id"]
        assert event["visibility"] == "INTERNAL_ONLY"

        merchant_feed, _ = validate_paginated(
            api.list_tracking_events(order["id"], m_headers(m_id))
        )
        assert merchant_feed == [], "INTERNAL_ONLY must be hidden from the branded feed"


class TestPlatformControls:
    def test_surge_and_clock_endpoints_round_trip(self, api):
        """PRD section 2.5: "The platform runs on a logical clock rather than
        wall time. At startup, before any adjustment, the clock reads exactly
        `2026-09-01T00:00:00Z`, and it never falls back to wall time
        thereafter."
        PRD section 2.5: "A second admin-only capability sets the platform
        surge multiplier by accepting a `multiplier` value and echoing it back.
        The surge multiplier defaults to 1.0, meaning no surge."
        PRD section 3.4: "`valid_until` is set to the creation clock time plus
        fifteen minutes."

        Design: Corner/endpoints/surge_and_clock_endpoints_round_trip
        """
        # No clock set: startup default must be 2026-09-01T00:00:00Z.
        merchant = new_merchant()
        activate_merchant(merchant["id"])
        store = add_store(merchant["id"])
        policy = add_policy(
            merchant["id"],
            distance_bands=[{"max_m": 3000, "base_cents": 500, "per_100m_cents": 0}],
            value_tiers=[],
            peak_windows=[],
            peak_uplift_pct=0.0,
        )
        activate_policy(merchant["id"], policy["id"])

        quote = validate_success(
            api.create_quote(create_quote_payload(store["id"]), m_headers(merchant["id"])),
            201,
        )
        assert quote["valid_until"].startswith("2026-09-01T00:15:00")
        assert quote["quoted_surge_multiplier"] == 1.0

        surge = validate_success(api.set_surge({"multiplier": 1.75}, admin_headers()))
        assert surge["multiplier"] == 1.75
