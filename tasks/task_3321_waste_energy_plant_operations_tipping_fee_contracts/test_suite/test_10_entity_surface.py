"""Entity surface tests: required fields, defaults, 404s, list envelopes,
system-field minting, enum validation, and authentication."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    assert_municipality,
    create_municipality_payload,
    create_power_purchase_agreement_payload,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

CM = TEST_USERS["contracts_manager_headers"]
ET = TEST_USERS["energy_trader_headers"]
REG = TEST_USERS["regulator_headers"]


class TestMunicipalityRequiredFields:
    def test_missing_legal_name_rejected(self):
        """PRD §3.1: "A `ContractsManager` begins the commercial setup by registering each municipal counterparty, supplying the municipality's `legal_name`, the `population_served` covered by its collection system, and optionally the `is_host_community` flag and `priority_group`."
        PRD §2.6: "8. Required-field presence — missing required body fields, reported as `ERR_INVALID_REQUEST`."

        Design: Corner/entities/municipality_create_missing_legal_name_returns_invalid_request
        """
        resp = api_client.create_municipality({"population_served": 50000}, CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestMunicipalityDefaults:
    def test_optional_host_fields_default_to_false_and_standard(self):
        """PRD §3.1: "The `is_host_community` flag defaults to `false`, and `priority_group` defaults to `STANDARD`; the only other recognized value is `HOST`, and claiming `HOST` priority requires `is_host_community` to be `true`."

        Design: Corner/entities/municipality_host_defaults_applied
        """
        created = get_success_data(
            api_client.create_municipality(create_municipality_payload(), CM)
        )
        fetched = validate_success(api_client.get_municipality(created["id"], REG))
        assert fetched["is_host_community"] is False
        assert fetched["priority_group"] == "STANDARD"


class TestMunicipalityNotFound:
    def test_unknown_municipality_id_returns_not_found(self):
        """PRD §2.7: "Requests are rejected with `404` and `ERR_NOT_FOUND` at the first identifier in the path — checked left to right — that does not correspond to an existing resource."

        Design: Corner/entities/municipality_not_found_returns_404
        """
        resp = api_client.get_municipality("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", REG)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestMunicipalityListEnvelope:
    def test_list_response_carries_pagination_envelope(self):
        """PRD §2.3: "List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it must be at least 1 and at most 100. The `offset` parameter skips that many items from the front of the result set and defaults to 0."
        PRD §2.3: "List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope."
        PRD §2.5: "Every primary resource in the system — municipalities, host community agreements, waste supply agreements, waste deliveries, boilers, outage windows, diversion plans, diversion legs, daily throughput reports, power purchase agreements, energy deliveries, metals recovery contracts, metals recovery batches, landfills, ash shipments, ash tests, emissions permits, and emissions readings — carries a standard set of system-managed fields"

        Design: Corner/entities/municipality_list_pagination_envelope
        """
        get_success_data(
            api_client.create_municipality(
                create_municipality_payload(legal_name="City of Alder"), CM
            )
        )
        get_success_data(
            api_client.create_municipality(
                create_municipality_payload(legal_name="Town of Bailey", population_served=8000), CM
            )
        )

        data, meta = validate_paginated(api_client.list_municipalities(REG))
        assert len(data) == 2
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        for item in data:
            assert_municipality(item)
            assert item["version"] == 1


class TestSystemFieldsInputIgnored:
    def test_client_supplied_id_and_version_are_ignored(self):
        """PRD §2.5: "`id` (string): a server-minted UUID with no type prefix."
        PRD §2.5: "`version` (integer): a system-managed integer that increments by one on every mutation of the resource, including mutations caused by cascading side effects from operations on related resources."

        Design: Corner/entities/system_fields_input_ignored
        """
        resp = api_client.create_municipality(
            {
                "legal_name": "City of Alder",
                "population_served": 50000,
                "id": "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
                "version": 99,
            },
            CM,
        )
        created = validate_success(resp, expected_status=201)
        assert created["id"] != "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
        assert created["version"] == 1


class TestEnumOutsideDeclaredSetRejected:
    def test_ppa_kind_outside_declared_set_rejected(self):
        """PRD §3.7: "Creating one takes the `counterparty_name`, the contract `kind` — either `PPA` for a fixed-rate agreement or `MERCHANT` for market-priced sales — the `energy_rate_cents_per_mwh`, the `capacity_payment_cents_per_mw_month`, the `contracted_mw` (greater than zero), and the term from `term_start` to `term_end` (exclusive, after the start)."
        PRD §2.6: "7. Field shape and range — numeric positivity and range constraints, interval ordering, and enum membership, else `ERR_INVALID_REQUEST`."

        Design: Corner/entities/enum_field_outside_declared_set_rejected
        """
        resp = api_client.create_power_purchase_agreement(
            create_power_purchase_agreement_payload(kind="WHOLESALE"), ET
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestUnauthenticatedRejected:
    def test_missing_or_undeclared_role_rejected_401(self):
        """PRD §2.1: "A request whose `X-User-Role` header is missing or does not name one of these roles is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.6: "1. Authentication — the `X-User-Role` header must be present and name a declared role, else `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/unauthenticated_request_rejected
        """
        resp = api_client.list_municipalities({"X-User-ID": "test-nobody-1", "X-User-Role": "Nobody"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
