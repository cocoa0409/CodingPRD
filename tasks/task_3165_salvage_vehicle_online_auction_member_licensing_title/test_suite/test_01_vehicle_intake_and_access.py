"""Vehicle creation, member defaults, VIN validation, listing, and 404 shape."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_vehicle,
    create_member_payload,
    create_seller,
    create_vehicle_payload,
    create_yard,
    get_success_data,
    make_seller_agent_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestVehicleCreation:
    def test_vehicle_create_returns_defaults_and_assigns_status(self, api, auctioneer_headers):
        """PRD §3.1: "The new vehicle is stamped `ASSIGNED`, its `assigned_at` records
        the logical clock, and its condition fields initialize to `image_count` of 0,
        `primary_damage` of `NONE`, `run_and_drive_status` of `UNKNOWN`, and
        `title_brand` of `NONE`, with an empty `image_ids` list."
        PRD §2.5: "Before any call to the administrative clock-setting capability, the
        logical clock reads exactly `2026-09-01T00:00:00Z`."

        Design: Corner/entities/vehicle_create_returns_defaults_and_assigns_status
        """
        yard = create_yard()
        seller = create_seller()
        payload = create_vehicle_payload(seller["id"], yard["id"], damage_codes=[])
        payload.pop("damage_codes")
        resp = api.create_vehicle(payload, make_seller_agent_headers(seller["id"]))
        vehicle = validate_success(resp, 201)
        assert_vehicle(vehicle)
        assert vehicle["status"] == "ASSIGNED"
        assert vehicle["image_count"] == 0
        assert vehicle["damage_codes"] == []
        assert vehicle["primary_damage"] == "NONE"
        assert vehicle["run_and_drive_status"] == "UNKNOWN"
        assert vehicle["title_brand"] == "NONE"
        assert vehicle["version"] == 1
        assert vehicle["assigned_at"] == "2026-09-01T00:00:00Z"

    def test_vehicle_vin_must_be_seventeen_chars(self, api):
        """PRD §3.1: "a 17-character `vin` that must be unique system-wide (a duplicate
        is rejected with `ERR_VIN_DUPLICATE`)"
        PRD §2.7: "(5) request shape — required fields present, types correct, enum
        values within their declared sets, the VIN exactly 17 characters, temporal ends
        strictly after starts, amounts strictly positive — any failure here is
        `ERR_INVALID_REQUEST` (HTTP 400)"

        Design: Corner/entities/vehicle_vin_must_be_seventeen_chars
        """
        yard = create_yard()
        seller = create_seller()
        payload = create_vehicle_payload(seller["id"], yard["id"], vin="SHORTVIN1234567X")
        assert len(payload["vin"]) == 16
        resp = api.create_vehicle(payload, make_seller_agent_headers(seller["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestMemberDefaults:
    def test_member_create_country_code_defaults_to_us(self, api, platform_admin_headers):
        """PRD §2.9: "A **Member** is registered with an `email` (unique per member), a
        `full_name`, a two-letter `home_state`, a `tier` of `BASIC`, `PREMIER`, or
        `BUSINESS`, and an optional `country_code` defaulting to `US`; members whose
        `country_code` is not `US` are exporters and require an export document per
        purchased vehicle."

        Design: Corner/entities/member_create_country_code_defaults_to_us
        """
        resp = api.create_member(
            create_member_payload(tier="PREMIER"), platform_admin_headers
        )
        member = validate_success(resp, 201)
        assert member["country_code"] == "US"
        assert member["status"] == "ACTIVE"
        assert member["version"] == 1


class TestVehicleListing:
    def test_vehicles_list_filters_and_paginates(self, api, auctioneer_headers):
        """PRD §2.3: "The `limit` parameter caps the number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
        parameter skips a number of items from the start of the result set and defaults
        to 0."
        PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/vehicles_list_filters_and_paginates
        """
        yard = create_yard()
        seller = create_seller()
        agent = make_seller_agent_headers(seller["id"])
        api.create_vehicle(create_vehicle_payload(seller["id"], yard["id"]), agent)
        api.create_vehicle(create_vehicle_payload(seller["id"], yard["id"]), agent)

        data, meta = validate_paginated(
            api.list_vehicles(auctioneer_headers, params={"status": "ASSIGNED", "limit": 1, "offset": 0})
        )
        assert len(data) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is True

        data, meta = validate_paginated(
            api.list_vehicles(auctioneer_headers, params={"status": "ASSIGNED", "limit": 1, "offset": 1})
        )
        assert len(data) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is False

        data, meta = validate_paginated(
            api.list_vehicles(auctioneer_headers, params={"status": "SOLD"})
        )
        assert len(data) == 0
        assert meta["total_count"] == 0

        data, meta = validate_paginated(api.list_vehicles(auctioneer_headers))
        assert len(data) == 2
        assert meta["limit"] == 10


class TestVehicleNotFound:
    def test_vehicle_get_unknown_id_returns_vehicle_not_found(self, api, auctioneer_headers):
        """PRD §2.7: "The request is rejected immediately with the 404 error
        corresponding to the first nonexistent identifier —
        `ERR_VEHICLE_NOT_FOUND`, `ERR_AUCTION_NOT_FOUND`, `ERR_AUCTION_ITEM_NOT_FOUND`,
        `ERR_SALE_NOT_FOUND`, `ERR_GATE_PASS_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, or
        `ERR_TITLE_NOT_FOUND` as applicable."

        Design: Corner/entities/vehicle_get_unknown_id_returns_vehicle_not_found
        """
        resp = api.get_vehicle(NON_EXISTENT_UUID, auctioneer_headers)
        validate_error(resp, ApiErrorId.ERR_VEHICLE_NOT_FOUND)
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_VEHICLE_NOT_FOUND"
        assert "message" in body["data"]


class TestTitleReverseReachability:
    def test_title_record_reverse_reachable_from_vehicle(self, api, title_clerk_headers):
        """PRD §3.2: "Exactly one title record may exist per vehicle; a second attempt
        is rejected with `ERR_TITLE_ALREADY_EXISTS`"
        PRD §3.2: "The record's `jurisdiction_state` is copied from the state of the
        vehicle's yard at creation and is immutable thereafter."
        PRD §3.2: "`CLEAN`, `SALVAGE`, and `REBUILT` titles are `TRANSFERABLE`
        everywhere."

        Design: Corner/entities/title_record_reverse_reachable_from_vehicle
        """
        yard = create_yard(state_code="CA")
        seller = create_seller()
        vehicle = get_success_data(
            api.create_vehicle(create_vehicle_payload(seller["id"], yard["id"]),
                               make_seller_agent_headers(seller["id"]))
        )
        before = get_success_data(api.get_vehicle_title(vehicle["id"], title_clerk_headers))
        assert before == [], f"expected empty array before title receipt, got {before}"

        title = get_success_data(api.create_title(vehicle["id"], {"title_type": "CLEAN"}, title_clerk_headers))
        after = get_success_data(api.get_vehicle_title(vehicle["id"], title_clerk_headers))
        assert len(after) == 1
        assert after[0]["id"] == title["id"]
        assert after[0]["status"] == "RECEIVED"
        assert after[0]["transferability"] == "TRANSFERABLE"
        assert after[0]["jurisdiction_state"] == "CA"


class TestBidImmutability:
    def test_bid_is_immutable_event_row_without_version(self, api):
        """PRD §2.4: "The Bid resource is the sole exception: as an immutable event row
        it carries only `id` and `created_at`. Both `updated_at` and `version` are
        absent from Bid, and a bid's `id` is identity only — it is never used in
        running-order selection or bid-ranking decisions."
        PRD §3.4: "The bid's `bid_type` is derived from the item's status at
        acceptance: `PRELIM` while the item is `QUEUED`, `LIVE` while it is `LIVE`."

        Design: Corner/entities/bid_is_immutable_event_row_without_version
        """
        from test_helpers import setup_live_item, place_bid, assert_bid

        ctx = setup_live_item()
        bid = place_bid(ctx["item"]["id"], ctx["member"], 1000000)
        assert_bid(bid)
        assert bid["bid_type"] == "LIVE"
        assert bid["is_winning"] is True
        assert bid["placed_at"] == "2026-09-01T00:00:00Z"
