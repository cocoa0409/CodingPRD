"""Breadth coverage of the cross-cutting layers: the OCC happy path and immediate
read-your-write consistency on order placement."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    assert_cents,
    assert_instant,
    factories as f,
    fixtures,
)


class TestOccCorrectVersionSucceeds:
    def test_create_with_current_version_bumps_store_version(self, api):
        """The guarded create succeeds against the current version and advances it by one.

        PRD §2.8: "Two write operations are guarded by optimistic concurrency control against the parent store. Creating a staffing deployment for a store requires a non-optional `expected_store_version` field in the request body carrying the client's last observed `version` of that store; if the store's current `version` has advanced since that observation, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). Closing the business day likewise requires `expected_store_version` matching the store's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes a version field. Both guarded operations increment the store's `version` by one on success."
        Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds
        """
        fixtures.set_clock(api, fixtures.MORNING)
        store = fixtures.create_store(api, store_code="OC")
        base_version = store["version"]

        deployment = validate_success(
            api.create_deployment(
                store["id"],
                f.deployment_payload(fixtures.BUSINESS_DAY, base_version),
                fixtures.STORE_MANAGER_HEADERS,
            ),
            expected_status=201,
        )
        assert deployment["status"] == "DRAFT"

        store_after = fixtures.read_store(api, store["id"])
        assert store_after["version"] == base_version + 1, (
            f"the guarded create must bump the store version by exactly one: "
            f"{base_version} -> {store_after['version']}"
        )


class TestOrderPlacementResponseCarriesComputedFields:
    def test_place_response_shows_promise_line_and_pricing_immediately(self, api):
        """The placement response itself carries every computed order field.

        PRD §3.4: "On acceptance the order's `fulfillment_status` moves from the transient `PLACED` straight to `ACCEPTED`, `payment_status` is `AUTHORIZED`, and `accuracy_status` begins `UNVERIFIED`. The selected window's `digital_committed` (or `instore_committed` for in-store orders) and the store's matching interval load each increase by `entree_count`, and the throttle band is re-evaluated."
        PRD §3.3: "The first eligible window in start order wins, and the order's `promised_at` is stamped as that window's `interval_end`."
        PRD §3.2: "For first-party digital and in-store orders there is no markup and no commission: the line's `unit_price_cents` is simply `base_price_cents`, `commission_cents` is zero, and `net_revenue_cents` equals `subtotal_cents` — so the same basket yields a different net revenue under the two variants."
        Design: Corner/consistency_model/all_changes_visible_in_same_request_response
        """
        fixtures.set_clock(api, fixtures.MORNING)
        world = fixtures.store_with_bowl(api, store_overrides={"store_code": "IM"})
        order = validate_success(
            api.create_order(
                world["store_id"],
                f.order_payload(
                    "FIRST_PARTY_DIGITAL", [f.order_line_payload(world["item_id"])]
                ),
                fixtures.STORE_MANAGER_HEADERS,
            ),
            expected_status=201,
        )
        assert_instant(order["promised_at"], "2026-09-01T10:30:00Z", "promised_at")
        assert order["line"] == "DIGITAL"
        assert order["entree_count"] == 1
        assert_cents(order["subtotal_cents"], 1095, "subtotal_cents")
        assert_cents(order["commission_cents"], 0, "commission_cents")
        assert_cents(order["net_revenue_cents"], 1095, "net_revenue_cents")
        assert order["production_window_id"] == world["window_id"]
        assert order["fulfillment_status"] == "ACCEPTED"
