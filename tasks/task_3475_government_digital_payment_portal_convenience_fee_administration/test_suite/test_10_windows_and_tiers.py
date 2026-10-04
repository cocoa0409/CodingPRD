"""Half-open settlement-account windows, closed pricing bands, and the
optimistic-concurrency gate on settlement-account creation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_settlement_account,
    create_agency,
    create_pricing_band,
    create_settlement_account,
    get_agency,
    set_clock,
    setup_active_agency,
    validate_error,
    verify_account,
    validate_paginated,
    validate_success,
)

PA = TEST_USERS["platform_admin_headers"]


def _account_payload(agency_id, expected_version, **overrides):
    payload = {
        "agency_id": agency_id,
        "routing_number": "103000648",
        "account_number_last4": "8888",
        "effective_from": "2026-06-01T00:00:00Z",
        "expected_agency_version": expected_version,
    }
    payload.update(overrides)
    return payload


class TestSettlementAccountWindows:
    def _agency_with_verified_account(self):
        set_clock()
        agency = create_agency()
        account = create_settlement_account(agency["id"], agency["version"])
        verified = verify_account(account["id"], "SUCCESS")
        agency_after = get_agency(agency["id"])  # version 2 after the account create
        return agency_after, verified

    def test_bare_overlapping_account_create_rejected(self, api):
        """PRD §3.1: "A create without `supersedes_account_id` is rejected
        with `ERR_ACCOUNT_WINDOW_OVERLAP` whenever its half-open window would
        overlap any non-`RETIRED` account of the same agency."

        Design: Difficulty/resource_temporal_overlap/settlement_account_half_open_adjacency_vs_overlap
        """
        agency, _verified = self._agency_with_verified_account()
        resp = api_client.create_settlement_account(
            _account_payload(agency["id"], agency["version"]), PA
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_WINDOW_OVERLAP)
        data, _ = validate_paginated(api_client.list_settlement_accounts(agency["id"], PA))
        assert len(data) == 1, "the rejected create persists nothing"
        assert get_agency(agency["id"])["version"] == 2, "a rejected create does not bump the agency"

    def test_supersede_at_same_instant_is_legal_adjacency(self, api):
        """PRD §3.1: "A create that names `supersedes_account_id` performs an
        orderly handoff: the named `VERIFIED` account moves to `RETIRED` and
        its `effective_to` is set to the new account's `effective_from`, so
        the old window closes exactly where the new one opens."
        PRD §3.1: "because creating an account mutates the agency aggregate,
        the agency's `version` increments by one on every successful create."

        Design: Difficulty/resource_temporal_overlap/settlement_account_half_open_adjacency_vs_overlap
        """
        agency, verified = self._agency_with_verified_account()
        resp = api_client.create_settlement_account(
            _account_payload(
                agency["id"], agency["version"], supersedes_account_id=verified["id"]
            ),
            PA,
        )
        new_account = validate_success(resp, 201)
        assert_settlement_account(new_account)
        assert new_account["status"] == "PENDING_VERIFICATION"
        assert new_account["effective_to"] is None
        rows, _ = validate_paginated(api_client.list_settlement_accounts(agency["id"], PA))
        by_id = {row["id"]: row for row in rows}
        old = by_id[verified["id"]]
        assert old["status"] == "RETIRED"
        assert old["effective_to"] is not None and old["effective_to"].startswith("2026-06-01"), (
            "the old half-open window closes exactly where the new one opens"
        )
        assert get_agency(agency["id"])["version"] == 3

    def test_occ_stale_agency_version_returns_412(self, api):
        """PRD §2.7: "Creating a settlement account requires the non-optional
        input field `expected_agency_version`, carrying the agency's
        `version` as the client last observed it; if it does not match the
        agency's current `version` — because another writer has since
        committed a change to the agency aggregate, for example a prior
        account create that superseded the same live account — the create is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting/occ_stale_agency_version_returns_412
        """
        set_clock()
        agency = create_agency()  # version 1
        create_settlement_account(agency["id"], agency["version"])  # bumps agency to version 2
        resp = api_client.create_settlement_account(
            _account_payload(agency["id"], 1), PA  # the caller's stale view
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        rows, _ = validate_paginated(api_client.list_settlement_accounts(agency["id"], PA))
        assert len(rows) == 1, "the stale write created nothing"
        assert get_agency(agency["id"])["version"] == 2


class TestPricingTierBands:
    def _absorbed_agency_with_first_band(self):
        built = setup_active_agency(
            agency_overrides={
                "legal_name": "County Treasurer",
                "agency_type": "LOCAL",
                "default_fee_model": "ABSORBED",
            }
        )
        agency = built["agency"]
        create_pricing_band(
            agency["id"],
            volume_min_cents=0,
            volume_max_cents=500000,
            rate_bp=250,
            per_txn_cents=20,
            effective_month="2026-09",
        )
        return agency

    def test_tier_band_sharing_boundary_cent_rejected(self, api):
        """PRD §3.2: "Bands of the same agency and `effective_month` must not
        overlap, and because the intervals are closed, two bands sharing a
        boundary cent count as overlapping and are rejected with
        `ERR_TIER_BAND_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/tier_band_shared_boundary_cent_is_overlap
        """
        agency = self._absorbed_agency_with_first_band()
        resp = api_client.create_pricing_tier(
            {
                "agency_id": agency["id"],
                "volume_min_cents": 500000,  # shares the boundary cent 500000
                "volume_max_cents": 900000,
                "rate_bp": 200,
                "per_txn_cents": 18,
                "effective_month": "2026-09",
            },
            PA,
        )
        validate_error(resp, ApiErrorId.ERR_TIER_BAND_OVERLAP)

    def test_adjacent_band_and_other_month_accepted(self, api):
        """PRD §3.2: "Absorbed-model pricing is configured per agency and
        month as closed-interval volume bands."

        Design: Difficulty/resource_temporal_overlap/tier_band_shared_boundary_cent_is_overlap
        """
        agency = self._absorbed_agency_with_first_band()
        resp = api_client.create_pricing_tier(
            {
                "agency_id": agency["id"],
                "volume_min_cents": 500001,  # starts one cent past the existing band
                "volume_max_cents": 900000,
                "rate_bp": 200,
                "per_txn_cents": 18,
                "effective_month": "2026-09",
            },
            PA,
        )
        validate_success(resp, 201)
        rows, _ = validate_paginated(
            api_client.list_pricing_tiers(agency["id"], PA, params={"effective_month": "2026-09"})
        )
        assert len(rows) == 2
        # the overlap scope is (agency, effective_month): the same interval is legal for another month
        resp2 = api_client.create_pricing_tier(
            {
                "agency_id": agency["id"],
                "volume_min_cents": 500000,
                "volume_max_cents": 900000,
                "rate_bp": 200,
                "per_txn_cents": 18,
                "effective_month": "2026-10",
            },
            PA,
        )
        validate_success(resp2, 201)
