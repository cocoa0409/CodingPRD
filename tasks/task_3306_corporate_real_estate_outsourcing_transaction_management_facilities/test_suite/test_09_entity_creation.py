"""Entity creation: initial states, derived fields, required fields, listing."""

from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
    create_activated_account,
    create_lease,
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    ae_headers,
)

TM = TEST_USERS["transaction_manager_headers"]


class TestAccountCreation:

    def test_create_sets_initial_lifecycle_and_derived_fields(self, api):
        """PRD §3.1: "Creation places the account in DRAFT, sets
        governance_posture to NORMAL, and derives client_data_rights from the
        tier as described in §2.11."
        PRD §2.5: "version is an integer that starts at 1".

        Design: Corner/entities/account_create_sets_initial_lifecycle_and_derived_fields
        """
        before = validate_paginated(
            api.list_accounts(TEST_USERS["account_executive_headers"])
        )[1]
        assert before["total_count"] == 0
        created = validate_success(
            api.create_account(
                {
                    "account_name": "Aster Holdings",
                    "client_name": "Aster",
                    "portfolio_sqft": 400_000,
                    "platform_tier": "ENTERPRISE",
                },
                TEST_USERS["account_executive_headers"],
            ),
            201,
        )
        assert created["lifecycle_state"] == "DRAFT"
        assert created["governance_posture"] == "NORMAL"
        assert created["client_data_rights"] == "CLIENT_OWNED_EXCLUSIVE"
        assert created["version"] == 1

    def test_create_missing_required_field_returns_400(self, api):
        """PRD §2.8: "a missing or wrongly typed body field is reported last as
        ERR_INVALID_REQUEST (HTTP 400)."
        PRD §3.1: "supplying account_name, client_name, portfolio_sqft and
        platform_tier."

        Design: Corner/entities/account_create_missing_required_field_returns_400
        """
        res = api.create_account(
            {
                "account_name": "NoSqft Ltd",
                "client_name": "NoSqft",
                "platform_tier": "BASIC",
            },
            TEST_USERS["account_executive_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_unknown_id_returns_not_found(self, api):
        """PRD §2.8: "Every path identifier and every foreign-key identifier in a
        body must resolve to a persisted resource; the first one that does not is
        reported as ERR_RESOURCE_NOT_FOUND (HTTP 404)."

        Design: Corner/entities/account_get_unknown_id_returns_not_found
        """
        res = api.get_account(
            "00000000-0000-0000-0000-000000000000",
            TEST_USERS["account_executive_headers"],
        )
        validate_error(res, ApiErrorId.ERR_RESOURCE_NOT_FOUND)


class TestLeaseListingAndCreation:

    def test_list_pagination_reports_total_and_has_more(self, api):
        """PRD §2.3: "limit caps how many items are returned and defaults to 10
        when omitted".
        PRD §2.3: "Responses to list endpoints carry limit, offset, total_count
        and has_more inside the meta object of the response envelope."

        Design: Corner/entities/lease_list_pagination_reports_total_and_has_more
        """
        account = create_activated_account()
        for i in (1, 2, 3):
            create_lease(account, property_address=f"{i} Market St")
        data, meta = validate_paginated(
            api.list_leases(TM, params={"account_id": account["id"], "limit": 2})
        )
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert len(data) == 2
        assert data[0]["account_id"] == account["id"]

    def test_create_lease_sets_pipeline_and_zero_revisions(self, api):
        """PRD §3.2: "A lease begins in PIPELINE with revision_count set to 0".
        PRD §3.2: "That bucket begins as UNASSIGNED".

        Design: Corner/entities/lease_create_initial_state_and_defaults
        """
        account = create_activated_account(platform_tier="COMPLETE")
        lease = validate_success(
            api.create_lease(
                {
                    "account_id": account["id"],
                    "property_address": "9 Pine St",
                    "market_code": "CHI",
                    "leased_sqft": 25_000,
                    "base_rent_cents_per_year": 30_000_000,
                    "lease_start_date": "2026-10-01T00:00:00Z",
                    "lease_end_date": "2027-10-01T00:00:00Z",
                },
                TM,
            ),
            201,
        )
        assert lease["pipeline_state"] == "PIPELINE"
        assert lease["revision_count"] == 0
