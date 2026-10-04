"""Breadth tests: cross-cutting layers — derived-field reconciliation across a
supersede swap, optimistic concurrency on guarantee enrollment, the inclusive
shop tier threshold, and immediate cascade visibility."""

from test_helpers import (
    VIN_A,
    ApiErrorId,
    create_active_shop,
    create_dealer,
    enroll_listing,
    get_listing,
    get_shop,
    get_vehicle,
    make_dealer_agent_headers,
    setup_network_with_source,
    submit_inspection,
    submit_n_service_records,
    submit_service_record,
    submit_title,
    validate_error,
    validate_success,
)


class TestRollupReconciliationOnSupersede:
    def test_counts_and_brand_follow_the_replacement(self, api, admin_headers):
        """PRD §3.3: "Supersession links the two records: the old record transitions from `ACTIVE` to `SUPERSEDED`, its `superseded_by_record_id` points at the new record, the vehicle's `superseded_record_count` increments by one, and `active_record_count` is unchanged because the swap is one-for-one. The vehicle's brand rollup re-runs immediately"

        Design: Corner/cross_cutting_layers/derived_field_reconciliation_on_rollup_after_supersede
        """
        network, source = setup_network_with_source(api)
        submit_inspection(api, source["id"], VIN_A, 100, idempotency_key="k-i1", payload_ref="i1")
        submit_title(api, source["id"], VIN_A, "CA", "clean", idempotency_key="k-t1", payload_ref="t1")
        submit_title(api, source["id"], VIN_A, "CA", "flood", idempotency_key="k-t2", payload_ref="t2")
        vehicle = get_vehicle_from_records(api)
        assert vehicle["active_record_count"] == 2, (
            f"inspection + replacement title; the swap must not add, got {vehicle['active_record_count']}"
        )
        assert vehicle["superseded_record_count"] == 1
        assert vehicle["canonical_brand"] == "FLOOD", (
            f"rollup must follow the replacement, got {vehicle['canonical_brand']}"
        )


class TestOccOnGuaranteeEnrollment:
    def test_stale_listing_version_rejected_current_version_enrolls(self, api, admin_headers):
        """PRD §2.8: "Enrolling a listing into the buyback guarantee requires `expected_listing_version` matching the `InventoryListing`'s current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because enrollment snapshots listing state and vehicle brand, both of which may have moved since the client's last read."

        Design: Corner/cross_cutting_layers/occ_enroll_stale_listing_version
        """
        network, source = setup_network_with_source(api)
        title = submit_title(api, source["id"], VIN_A, "CA", "clean")
        dealer = create_dealer(api)
        created = validate_success(api.create_listing(
            dealer["id"], {"vehicle_id": title["vehicle_id"], "asking_price_cents": 700_000},
            make_dealer_agent_headers(dealer["id"])), expected_status=201)
        version_at_create = created["version"]

        validate_success(api.publish_listing(dealer["id"], created["id"], {}, make_dealer_agent_headers(dealer["id"])))
        stale = api.enroll_guarantee(
            dealer["id"], created["id"],
            {"expected_listing_version": version_at_create},
            make_dealer_agent_headers(dealer["id"]),
        )
        validate_error(stale, ApiErrorId.STALE_VERSION)

        current = get_listing(api, created["id"])
        enrolled = enroll_listing(api, dealer["id"], created["id"], current["version"])
        assert enrolled["guarantee_status"] == "ENROLLED"


class TestShopTierThreshold:
    def test_forty_nine_records_keep_basic(self, api, admin_headers):
        """PRD §3.6: "The rule is a simple threshold over the count of the shop's `ACTIVE` service records: at 50 or more the tier is `PRO`; below 50 it is `BASIC`. The boundary is inclusive — exactly 50 earns `PRO`, while 49 leaves the shop at `BASIC`."

        Design: Corner/cross_cutting_layers/shop_tier_pro_upgrade_at_fifty_records
        """
        setup_network_with_source(api)
        shop = create_active_shop(api)
        submit_n_service_records(api, shop["id"], 49, event_date="2026-08-01")
        assert get_shop(api, shop["id"])["reporting_tool_tier"] == "BASIC"

    def test_fiftieth_record_promotes_to_pro(self, api, admin_headers):
        """PRD §3.6: "The rule is a simple threshold over the count of the shop's `ACTIVE` service records: at 50 or more the tier is `PRO`; below 50 it is `BASIC`. The boundary is inclusive — exactly 50 earns `PRO`, while 49 leaves the shop at `BASIC`."

        Design: Corner/cross_cutting_layers/shop_tier_pro_upgrade_at_fifty_records
        """
        setup_network_with_source(api)
        shop = create_active_shop(api)
        submit_n_service_records(api, shop["id"], 49, event_date="2026-08-01")
        submit_service_record(api, shop["id"], odometer_reading=10_100, event_date="2026-08-02",
                              idempotency_key="k-s50", payload_ref="s50")
        assert get_shop(api, shop["id"])["reporting_tool_tier"] == "PRO"


class TestImmediateCascadeVisibility:
    def test_brand_rollup_visible_in_next_read(self, api, admin_headers):
        """PRD §3.4: "These rollups re-run on any transition of any of the vehicle's records into or out of `ACTIVE` — ingest, same-source supersession, suspension-cascade withdrawal, correction-driven withdrawal or supersession, and the unreliable-record purge alike."
        PRD §2.9: "the cascade executes immediately and recomputes every derived value that depended on the withdrawn children"

        Design: Corner/consistency_model/immediate_visibility_of_cascade_in_same_read
        """
        network, source = setup_network_with_source(api)
        clean = submit_title(api, source["id"], VIN_A, "CA", "clean")
        submit_title(api, source["id"], VIN_A, "TX", "salvage title", idempotency_key="k-t2", payload_ref="t2")
        vehicle = get_vehicle(api, clean["vehicle_id"])
        assert vehicle["canonical_brand"] == "SALVAGE"
        assert vehicle["brand_severity"] == 5


def get_vehicle_from_records(api):
    from test_helpers import make_network_admin_headers
    resp = api.list_vehicles(make_network_admin_headers())
    body = resp.json()
    return get_vehicle(api, body["data"][0]["id"])
