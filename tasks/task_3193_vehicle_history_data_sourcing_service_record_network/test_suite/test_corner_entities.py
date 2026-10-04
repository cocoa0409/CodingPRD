"""Breadth tests: entity creation defaults, lazy vehicle creation, not-found
envelopes, listing pagination, and shop provisioning."""

from test_helpers import (
    NON_EXISTENT_UUID,
    VIN_C,
    ApiErrorId,
    assert_network,
    get_vehicle,
    make_network_admin_headers,
    register_source,
    setup_network,
    setup_network_with_source,
    submit_inspection,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import create_shop_payload


class TestNetworkCreationDefaults:
    def test_network_starts_at_epoch_zero_with_defaults(self, api, admin_headers):
        """PRD §3.1: "The new network starts at `epoch_index` 0 with the default `brand_lexicon` of §2.7 installed, and with `enrolled_listing_count` at 0 — a running count of listings currently enrolled in the guarantee program."

        Design: Corner/entities/network_creation_applies_defaults
        """
        network = setup_network(api)
        assert_network(network)
        assert network["epoch_index"] == 0, f"network must start at epoch 0, got {network['epoch_index']}"
        assert network["enrolled_listing_count"] == 0
        assert network["brand_lexicon"]["CA"]["salvage certificate"] == "SALVAGE"


class TestVehicleLazyCreation:
    def test_first_record_creates_vehicle_with_zeroed_rollups(self, api, admin_headers):
        """PRD §3.3: "When no vehicle matches at all, a new `Vehicle` is created lazily with the submitted `vin`, and the record attaches to it as an `EXACT_VIN` match."
        PRD §3.4: "Its `canonical_brand` is the brand of highest severity among the vehicle's `ACTIVE` title-brand records — `NONE` when no such records exist, with `brand_severity` 0"

        Design: Corner/entities/vehicle_lazy_creation_on_first_match
        """
        network, source = setup_network_with_source(api)
        record = submit_inspection(api, source["id"], VIN_C, 12_000)
        assert record["match_method"] == "EXACT_VIN"
        vehicle = get_vehicle(api, record["vehicle_id"])
        assert vehicle["vin"] == VIN_C
        assert vehicle["canonical_brand"] == "NONE"
        assert vehicle["brand_severity"] == 0
        assert vehicle["active_record_count"] == 1


class TestVehicleNotFound:
    def test_get_unknown_vehicle_returns_not_found(self, api, admin_headers):
        """PRD §2.9: "the platform validates path segments left to right: the network first, then each successive child, returning `ERR_NOT_FOUND` for the first segment that does not resolve within its parent's scope, before any business rule is evaluated."

        Design: Corner/entities/vehicle_not_found
        """
        setup_network(api)
        resp = api.get_vehicle(NON_EXISTENT_UUID, admin_headers)
        validate_error(resp, ApiErrorId.NOT_FOUND)


class TestListPaginationEnvelope:
    def test_sources_list_carries_pagination_meta_with_defaults(self, api, admin_headers):
        """PRD §2.3: "`limit` caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips a number of items from the front of the result set and defaults to 0."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope."

        Design: Corner/entities/list_endpoint_pagination_envelope
        """
        setup_network(api)
        register_source(api, activate=False)
        resp = api.list_sources(admin_headers)
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert len(data) == 1


class TestShopProvisioning:
    def test_approval_provisions_service_shop_source_and_grants_basic(self, api, admin_headers):
        """PRD §3.6: "Approval moves the shop from `APPLIED` to `ACTIVE` and does two more things atomically: it auto-provisions a dedicated `DataSource` of `source_type` `SERVICE_SHOP` with `jurisdiction` \"SHOP\" in `ACTIVE` status, recorded as the shop's `data_source_id`, and it grants the shop the `BASIC` reporting-tool tier."

        Design: Corner/entities/shop_data_source_provisioning_fk
        """
        setup_network(api)
        shop = validate_success(api.create_shop(create_shop_payload(), admin_headers), expected_status=201)
        approved = validate_success(api.approve_shop(shop["id"], admin_headers))
        assert approved["status"] == "ACTIVE"
        assert approved["reporting_tool_tier"] == "BASIC"
        assert approved["data_source_id"], "approval must record the provisioned source id"
        source = validate_success(api.get_source(approved["data_source_id"], admin_headers))
        assert source["source_type"] == "SERVICE_SHOP"
        assert source["jurisdiction"] == "SHOP"
        assert source["status"] == "ACTIVE"
