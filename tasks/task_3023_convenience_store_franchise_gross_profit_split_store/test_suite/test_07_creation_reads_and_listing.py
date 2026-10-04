"""Resource creation, single reads and the list contract."""

import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, ADMIN, NON_EXISTENT_UUID, assert_franchisee, assert_store,
    is_valid_uuid, is_iso8601_timestamp, set_clock, create_franchisee, create_store,
    create_agreement, create_open_settlement, setup_store_with_agreement,
    create_settlement_payload, next_store_number,
)


class TestFranchiseeRegistration:
    """Registration establishes the operator's derived fiscal picture at once."""

    def test_registration_returns_every_declared_field_with_derived_figures_and_starts_active(self):
        """PRD §3.1: "Registration is the moment an operator's derived fiscal
        picture is first established: it enters the system in status `ACTIVE`
        with a `draw_outstanding_cents` of zero and an `open_shrink_charge_cents`
        of zero, so its `audit_adjusted_net_worth_cents` equals its stated net
        worth and its `risk_band` is derived from that figure on the spot."
        PRD §2.5: "`created_at` (string): an ISO 8601 UTC timestamp with three
        fractional digits (for example `2025-05-24T10:30:00.123Z`) recording
        first creation."

        Design: Corner/entities/franchisee_create_returns_every_declared_field_and_starts_active
        """
        set_clock("2026-09-01T00:00:00Z")
        response = api_client.create_franchisee({
            "legal_name": "Anchor Point Retail LLC",
            "owner_name": "Priya Deshmukh",
            "entity_type": "LLC",
            "stated_net_worth_cents": 30_000_000,
        }, ADMIN)
        franchisee = validate_success(response, 201)

        assert is_valid_uuid(franchisee["id"])
        assert is_iso8601_timestamp(franchisee["created_at"])
        assert is_iso8601_timestamp(franchisee["updated_at"])
        assert franchisee["legal_name"] == "Anchor Point Retail LLC"
        assert franchisee["owner_name"] == "Priya Deshmukh"
        assert franchisee["status"] == "ACTIVE"
        assert franchisee["risk_band"] == "A"
        assert franchisee["version"] == 1
        assert franchisee["draw_outstanding_cents"] == 0
        assert franchisee["open_shrink_charge_cents"] == 0
        assert franchisee["audit_adjusted_net_worth_cents"] == 30_000_000
        assert franchisee["stated_net_worth_cents"] == 30_000_000

        assert_franchisee(franchisee)

        # The same row round-trips unchanged on a read.
        read = get_success_data(api_client.get_franchisee(franchisee["id"], ADMIN))
        assert read["id"] == franchisee["id"]
        assert read["audit_adjusted_net_worth_cents"] == 30_000_000

    def test_omitting_the_entity_type_stores_the_llc_default_and_derives_band_b(self):
        """PRD §3.1: "The `entity_type` is optional and, when omitted, defaults
        to `LLC`; when supplied it must be one of `INDIVIDUAL`, `LLC` or
        `CORPORATION`."
        PRD §2.7: "An operator lands in band `A` when the audit-adjusted net worth
        is at least 15,000,000 cents, in band `B` when it is at least 5,000,000
        cents but less than the band `A` floor".

        Design: Corner/entities/franchisee_create_omitting_entity_type_defaults_it_to_llc
        """
        set_clock("2026-09-01T00:00:00Z")
        response = api_client.create_franchisee({
            "legal_name": "Plainview Operator LLC",
            "owner_name": "Bo Carmichael",
            "stated_net_worth_cents": 8_000_000,
        }, ADMIN)
        franchisee = validate_success(response, 201)

        assert franchisee["entity_type"] == "LLC"
        assert franchisee["entity_type"] != "INDIVIDUAL"
        # 8,000,000 is at or above the B floor and below the A floor.
        assert franchisee["risk_band"] == "B"

        listed, meta = validate_paginated(
            api_client.list_franchisees(ADMIN, {"entity_type": "LLC"}))
        assert meta["total_count"] == 1


class TestStoreCreationAndRead:
    """The premises stay with the franchisor; only the trading right moves."""

    def test_a_store_round_trips_its_franchisor_held_lease_and_equipment(self):
        """PRD §2.4: "Every `Store` carries a `lease_owner` field whose value is
        always `FRANCHISOR`, and an `equipment_owner` field whose value is
        likewise always `FRANCHISOR`; both are set by the system at store
        creation and cannot be supplied or changed by a client."
        PRD §2.4: "a `monthly_rent_cents` charge recognised against the store,
        derived from that format band."

        Design: Corner/entities/store_get_returns_lease_and_equipment_ownership_as_franchisor_held
        """
        set_clock("2026-09-01T00:00:00Z")
        franchisee = create_franchisee()
        store = create_store(franchisee["id"], store_number="TX-1001",
                             state_code="TX", format="URBAN")

        read = validate_success(api_client.get_store(store["id"], ADMIN), 200)
        assert read["lease_owner"] == "FRANCHISOR"
        assert read["equipment_owner"] == "FRANCHISOR"
        assert read["status"] == "ACTIVE"
        assert read["transfer_status"] == "NONE"
        assert read["store_number"] == "TX-1001"
        assert read["state_code"] == "TX"
        assert read["format"] == "URBAN"
        assert read["franchisee_id"] == franchisee["id"]
        assert read["monthly_rent_cents"] is not None
        assert isinstance(read["monthly_rent_cents"], int)
        assert_store(read)

    def test_a_second_store_on_an_already_allocated_number_is_refused_network_wide(self):
        """PRD §3.1: "The store number must be unique across the entire network;
        attempting to open a second store on a number already in use is rejected
        with `ERR_STORE_NUMBER_DUPLICATE` (HTTP 409)."

        Design: Corner/entities/store_create_duplicate_store_number_returns_store_number_duplicate
        """
        set_clock("2026-09-01T00:00:00Z")
        first_operator = create_franchisee(legal_name="Kestrel Operator LLC")
        second_operator = create_franchisee(legal_name="Peregrine Operator LLC")
        create_store(first_operator["id"], store_number="TX-5001", format="URBAN")

        response = api_client.create_store({
            "franchisee_id": second_operator["id"],
            "store_number": "TX-5001",
            "state_code": "TX",
            "format": "RURAL",
            "opened_on": "2026-09-01T00:00:00Z",
            "cold_chain_certified": True,
        }, ADMIN)
        validate_error(response, ApiErrorId.ERR_STORE_NUMBER_DUPLICATE, expected_status=409)

        # Uniqueness is global, not per-franchisee.
        listed, meta = validate_paginated(
            api_client.list_stores(ADMIN, {"franchisee_id": second_operator["id"]}))
        assert meta["total_count"] == 0
        all_stores, all_meta = validate_paginated(api_client.list_stores(ADMIN))
        assert all_meta["total_count"] == 1

    def test_reading_a_store_whose_id_resolves_to_nothing_is_a_resource_not_found(self):
        """PRD §2.12: "Every identifier appearing as a path segment must resolve
        to an existing resource of the type the path implies; when it does not,
        the request is rejected with `ERR_RESOURCE_NOT_FOUND` (HTTP 404)."
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/entities/store_get_with_an_unknown_id_returns_store_not_found
        """
        set_clock("2026-09-01T00:00:00Z")
        response = api_client.get_store(NON_EXISTENT_UUID, ADMIN)
        error = validate_error(response, ApiErrorId.ERR_RESOURCE_NOT_FOUND, expected_status=404)

        assert set(error.keys()) >= {"error_id", "message"}
        body = response.json()
        assert body["response_type"] == "error"
        assert "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]


class TestSettlementListingContract:
    """total_count describes the whole filtered set, not the returned window."""

    def test_filters_pagination_metadata_and_defaults_agree_with_the_declared_contract(self):
        """PRD §2.3: "The `total_count` reports the size of the full result set
        before pagination, and `has_more` reports whether further items remain
        beyond the returned window."
        PRD §2.3: "The `limit` parameter caps the number of items returned; it
        defaults to 10, accepts a minimum of 1, and accepts a maximum of 100.
        The `offset` parameter skips that many leading items and defaults to 0."

        Design: Corner/entities/settlements_list_filters_by_franchisee_and_reports_total_count_and_has_more
        """
        set_clock("2026-09-01T00:00:00Z")
        first = create_franchisee(legal_name="Northgate Operator LLC")
        second = create_franchisee(legal_name="Southgate Operator LLC")
        first_store = create_store(first["id"], store_number="TX-2001")
        second_store = create_store(second["id"], store_number="TX-2002", format="RURAL")
        create_agreement(first["id"], first_store["id"])
        create_agreement(second["id"], second_store["id"])

        create_open_settlement(first_store, first, period_start="2026-09-01T00:00:00Z",
                               period_end="2026-09-08T00:00:00Z")
        create_open_settlement(first_store, first, period_start="2026-09-08T00:00:00Z",
                               period_end="2026-09-15T00:00:00Z")
        create_open_settlement(second_store, second)

        data, meta = validate_paginated(api_client.list_settlements(
            ADMIN, {"franchisee_id": first["id"], "limit": 1, "offset": 0}))
        assert len(data) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is True

        data, meta = validate_paginated(api_client.list_settlements(
            ADMIN, {"franchisee_id": first["id"], "limit": 1, "offset": 1}))
        assert len(data) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is False

        data, meta = validate_paginated(api_client.list_settlements(ADMIN))
        assert len(data) == 3
        assert meta["limit"] == 10
        assert meta["offset"] == 0

        data, meta = validate_paginated(
            api_client.list_settlements(ADMIN, {"status": "OPEN"}))
        assert meta["total_count"] == 3