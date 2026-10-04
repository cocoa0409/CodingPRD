"""Corner queue — entities section: creation envelopes, identity blocks,
initial derived counters, append-only market quotes, contract birth states,
required/forbidden fields, not-found paths, pagination, and ticket birth
state (PRD §2.2/§2.3/§2.4/§2.6/§2.9/§3.1/§3.2/§3.3).

Skipped instance: elevator_create_computed_field_input_ignored — the PRD
never states how the server treats a computed field carried in a create body
(§2.10's "clients never write them directly" is equally satisfied by ignoring
the field or rejecting the request), so the asserted 201-plus-zero outcome is
not uniquely derivable.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_delivery_ticket,
    assert_elevator,
    assert_farmer,
    assert_market_quote,
    assert_origination_contract,
    create_cash_contract,
    create_cash_contract_payload,
    create_deferred_contract,
    create_elevator_payload,
    create_farmer_payload,
    create_published_schedule,
    create_ticket,
    is_valid_uuid,
    post_market_quote,
    setup_origination_site,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MERCH = TEST_USERS["origination_merchandiser_headers"]


class TestFarmerCreate:
    def test_farmer_create_returns_201_with_system_fields(self, api):
        """PRD §3.1: "Farmers are registered with a `legal_name` and the `county` of the home farm operation." PRD §2.2: "operations that create or modify a resource will return the created or updated resource object in the data field." PRD §2.4: every resource carries "id",
        "created_at", "updated_at", and "version".

        Design: Corner/entities/farmer_create_returns_201_with_system_fields
        """
        resp = api_client.create_farmer(
            create_farmer_payload(legal_name="A. Farmer", county="Macoupin"),
            ADMIN,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"]
        assert body["meta"]["api_request_timestamp"]
        farmer = body["data"]
        assert_farmer(farmer)
        assert farmer["legal_name"] == "A. Farmer"
        assert farmer["county"] == "Macoupin"
        assert farmer["version"] == 1

    def test_farmer_id_is_uuid_without_type_prefix(self, api):
        """PRD §2.4: "id` — a server-minted UUID with no type prefix, assigned at creation." The minted id is a bare 36-character UUID; no
        entity-type prefix like farm_ is prepended.

        Design: Corner/entities/farmer_id_is_uuid_without_type_prefix
        """
        farmer = validate_success(
            api_client.create_farmer(create_farmer_payload(), ADMIN), 201
        )
        assert is_valid_uuid(farmer["id"])
        assert len(farmer["id"]) == 36 and farmer["id"].count("-") == 4, (
            "bare UUID carries no type prefix"
        )


class TestElevatorCreate:
    def test_elevator_create_derived_counters_start_at_zero(self, api):
        """PRD §3.1: "A new elevator starts with `stored_bushels` and `certified_stored_bushels` at zero and `receiving_open` true."

        Design: Corner/entities/elevator_create_derived_counters_start_at_zero
        """
        schedule = create_published_schedule()
        resp = api_client.create_elevator(
            create_elevator_payload(
                schedule["id"], name="Riverbend", region="IL",
                storage_capacity_bushels=100000,
            ),
            ADMIN,
        )
        elevator = validate_success(resp, 201)
        assert_elevator(elevator)
        assert float(elevator["stored_bushels"]) == pytest.approx(0)
        assert float(elevator["certified_stored_bushels"]) == pytest.approx(0)
        assert elevator["receiving_open"] is True
        assert elevator["active_discount_schedule_id"] == schedule["id"]


class TestMarketQuotes:
    def test_market_quotes_append_and_filter_by_month(self, api):
        """PRD §2.4: "The sole exception is the market quote. Quotes are append-only observations: a quote carries `id` and `created_at` only; `updated_at` and `version` are absent because a quote, once posted, never changes." PRD §2.6: "Quote lists can be filtered by `commodity` and `quote_month`."

        Design: Corner/entities/market_quotes_append_and_filter_by_month
        """
        post_market_quote("BEAN", "2026-11", 1200, "2026-09-01T00:00:00Z")
        post_market_quote("BEAN", "2026-12", 1210, "2026-09-01T00:00:00Z")
        rows, meta = validate_paginated(
            api_client.list_market_quotes(ADMIN, params={"commodity": "BEAN"})
        )
        assert len(rows) == 2
        assert meta["total_count"] == 2
        for row in rows:
            assert_market_quote(row)
        filtered, meta2 = validate_paginated(
            api_client.list_market_quotes(
                ADMIN, params={"commodity": "BEAN", "quote_month": "2026-12"}
            )
        )
        assert len(filtered) == 1
        assert meta2["total_count"] == 1
        assert filtered[0]["price_cents"] == 1210


class TestContractBirthStates:
    def test_contract_create_cash_born_priced(self, api):
        """PRD §3.2: "Pricing starts `PRICED` on the `pricing_status` dimension for `CASH` — creation seeds `elections` with a single election covering the full `quantity_bushels` at the agreed `cash_price_cents_per_bushel`, sets `priced_bushels` equal to `quantity_bushels`, and sets `priced_value_cents` to their exact integer product".

        Design: Corner/entities/contract_create_cash_born_priced
        """
        site = setup_origination_site()
        contract = create_cash_contract(
            site["farmer"]["id"], site["elevator"]["id"],
            quantity_bushels=100, cash_price_cents_per_bushel=1000,
        )
        assert_origination_contract(contract)
        assert contract["pricing_status"] == "PRICED"
        assert contract["fulfillment_status"] == "OPEN"
        assert float(contract["priced_bushels"]) == pytest.approx(100)
        assert contract["priced_value_cents"] == 100000
        assert len(contract["elections"]) == 1
        election = contract["elections"][0]
        assert float(election["bushels"]) == pytest.approx(100)
        assert election["unit_price_cents"] == 1000
        assert election["origin"] == "CLIENT"

    def test_contract_create_deferred_born_unpriced(self, api):
        """PRD §3.2: "starts `UNPRICED` for `BASIS` and `DEFERRED`, which accumulate price later through elections" and "The remaining server-maintained fields start at zero or null: `delivered_bushels`, `accrued_storage_cents`, and `unpriced_pool_bushels` at zero; `last_accrual_date` null while the unpriced pool is empty".

        Design: Corner/entities/contract_create_deferred_born_unpriced
        """
        site = setup_origination_site()
        contract = create_deferred_contract(
            site["farmer"]["id"], site["elevator"]["id"],
            quantity_bushels=2000, futures_month="2026-12",
            pricing_deadline="2026-12-15T00:00:00Z",
            storage_rate_cents_per_bushel_day=1,
        )
        assert_origination_contract(contract)
        assert contract["pricing_status"] == "UNPRICED"
        assert contract["fulfillment_status"] == "OPEN"
        assert float(contract["priced_bushels"]) == pytest.approx(0)
        assert contract["priced_value_cents"] == 0
        assert contract["elections"] == []
        assert float(contract["unpriced_pool_bushels"]) == pytest.approx(0)


class TestContractFieldDiscipline:
    def test_contract_create_cash_with_basis_field_rejected(self, api):
        """PRD §3.2: "A `CASH` contract requires `cash_price_cents_per_bushel` and forbids the basis, futures-month, deadline, and storage-rate fields"
        and "Supplying a field the chosen type forbids, or omitting one it requires, is `ERR_INVALID_REQUEST`."

        Design: Corner/entities/contract_create_cash_with_basis_field_rejected
        """
        site = setup_origination_site()
        resp = api_client.create_origination_contract(
            create_cash_contract_payload(
                site["farmer"]["id"], site["elevator"]["id"],
                quantity_bushels=100, cash_price_cents_per_bushel=1000,
                basis_cents_per_bushel=-25,
            ),
            MERCH,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        rows, meta = validate_paginated(
            api_client.list_origination_contracts(
                MERCH, params={"farmer_id": site["farmer"]["id"]}
            )
        )
        assert meta["total_count"] == 0, "the rejected create persists nothing"

    def test_contract_create_missing_required_quantity_returns_invalid_request(self, api):
        """PRD §3.2: a contract names "a positive `quantity_bushels` carried to three decimals" and "Supplying a field the chosen type forbids, or omitting one it requires, is `ERR_INVALID_REQUEST`." Omitting
        quantity_bushels fails 400.

        Design: Corner/entities/contract_create_missing_required_quantity_returns_invalid_request
        """
        site = setup_origination_site()
        payload = create_cash_contract_payload(
            site["farmer"]["id"], site["elevator"]["id"],
            quantity_bushels=100, cash_price_cents_per_bushel=1000,
        )
        del payload["quantity_bushels"]
        resp = api_client.create_origination_contract(payload, MERCH)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestContractReadPaths:
    def test_contract_get_with_unknown_id_returns_not_found(self, api):
        """PRD §2.9 rule 3: "every identifier in the URL path resolves to an existing entity, checked left-to-right along the path; the first failure produces that resource's not-found error" — for an
        origination contract, ERR_CONTRACT_NOT_FOUND.

        Design: Corner/entities/contract_get_with_unknown_id_returns_not_found
        """
        resp = api_client.get_origination_contract(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", MERCH
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_FOUND)

    def test_contracts_list_paginates_with_total_count_and_has_more(self, api):
        """PRD §2.3: "`limit` sets the maximum number of items returned: it
        defaults to 10 when omitted, accepts a minimum of 1, and is capped at
        100. `offset` sets the number of items skipped and defaults to 0." and
        "Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object".

        Design: Corner/entities/contracts_list_paginates_with_total_count_and_has_more
        """
        site = setup_origination_site()
        for quantity, price in ((100, 1000), (200, 1001), (300, 1002)):
            create_cash_contract(
                site["farmer"]["id"], site["elevator"]["id"],
                quantity_bushels=quantity, cash_price_cents_per_bushel=price,
            )
        page1, meta1 = validate_paginated(
            api_client.list_origination_contracts(
                MERCH,
                params={"farmer_id": site["farmer"]["id"], "limit": 2, "offset": 0},
            )
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(
            api_client.list_origination_contracts(
                MERCH,
                params={"farmer_id": site["farmer"]["id"], "limit": 2, "offset": 2},
            )
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        everything, meta3 = validate_paginated(
            api_client.list_origination_contracts(
                MERCH, params={"farmer_id": site["farmer"]["id"]}
            )
        )
        assert len(everything) == 3
        assert meta3["limit"] == 10 and meta3["offset"] == 0


class TestTicketBirthState:
    def test_ticket_create_received_with_null_computed_fields(self, api):
        """PRD §3.3: "The new ticket is born `RECEIVED`, with `elevator_id` and `program_id` copied from its contract" and "Until the apply, all four computed fields are null."

        Design: Corner/entities/ticket_create_received_with_null_computed_fields
        """
        site = setup_origination_site()
        contract = create_cash_contract(
            site["farmer"]["id"], site["elevator"]["id"], quantity_bushels=100
        )
        ticket = create_ticket(
            contract["id"], gross_bushels=50, moisture_pct=14.0,
            damage_pct=1.0, foreign_material_pct=0.5,
        )
        assert_delivery_ticket(ticket)
        assert ticket["status"] == "RECEIVED"
        for field in (
            "shrink_bushels", "net_bushels", "discount_cents_per_bushel",
            "premium_cents_per_bushel", "schedule_id",
        ):
            assert ticket[field] is None, f"{field} must be null before apply"
        assert ticket["elevator_id"] == site["elevator"]["id"]
