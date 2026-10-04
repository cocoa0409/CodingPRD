"""Pricing: override band boundary, half-open windows, RBAC (PRD §3.5, §2.1)."""
from test_helpers import (
    ApiErrorId,
    create_published_pricing,
    get_success_data,
    make_owner_rep_headers,
    setup_managed_property,
    setup_owner,
    setup_property,
    start_onboarding,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

PM = TEST_USERS["pm_headers"]
ANALYST = TEST_USERS["analyst_headers"]


class TestOverrideBandBoundary:
    def test_pricing_override_band_exact_boundary(self, api):
        """PRD §3.5: "the override must stay within a band of plus or minus ten
        percent of `recommended_rent_cents` (the constant
        `MAX_OVERRIDE_BAND_PCT` is 0.10), inclusive at the boundary — a
        deviation of exactly ten percent is permitted, one cent beyond is
        rejected with `ERR_OVERRIDE_BAND_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/pricing_override_band_exact_boundary
        """
        fx = setup_managed_property(legal_name="Band Owner LP",
                                    property_name="Band Property", unit_count=50)
        owner, prop = fx["owner"], fx["prop"]
        hdrs = make_owner_rep_headers(owner["id"])
        pr_a = create_published_pricing(prop, unit_label="U1",
                                        recommended_rent_cents=200000)
        pr_b = create_published_pricing(prop, unit_label="U2",
                                        recommended_rent_cents=200000)

        ok = validate_success(
            api.override_pricing(pr_a["id"], {"override_rent_cents": 220000}, hdrs)
        )
        assert ok["status"] == "OWNER_OVERRIDDEN"
        assert ok["final_rent_cents"] == 220000

        bad = api.override_pricing(pr_b["id"], {"override_rent_cents": 220001}, hdrs)
        validate_error(bad, ApiErrorId.ERR_OVERRIDE_BAND_EXCEEDED)
        after = validate_success(api.get_pricing(pr_b["id"], ANALYST))
        assert after["status"] == "PUBLISHED"

    def test_pricing_override_band_lower_boundary(self, api):
        """PRD §3.5: "the override must stay within a band of plus or minus ten
        percent of `recommended_rent_cents` (the constant
        `MAX_OVERRIDE_BAND_PCT` is 0.10), inclusive at the boundary — a
        deviation of exactly ten percent is permitted, one cent beyond is
        rejected with `ERR_OVERRIDE_BAND_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/pricing_override_band_exact_boundary
        """
        fx = setup_managed_property(legal_name="Band2 Owner LP",
                                    property_name="Band2 Property", unit_count=50)
        owner, prop = fx["owner"], fx["prop"]
        hdrs = make_owner_rep_headers(owner["id"])
        pr_ok = create_published_pricing(prop, unit_label="L1",
                                         recommended_rent_cents=200000)
        pr_bad = create_published_pricing(prop, unit_label="L2",
                                          recommended_rent_cents=200000)

        # Lower boundary: exactly -10% (180000) permitted.
        ok = validate_success(
            api.override_pricing(pr_ok["id"], {"override_rent_cents": 180000}, hdrs)
        )
        assert ok["status"] == "OWNER_OVERRIDDEN"
        assert ok["final_rent_cents"] == 180000

        # One cent below the band rejected.
        bad = api.override_pricing(pr_bad["id"], {"override_rent_cents": 179999}, hdrs)
        validate_error(bad, ApiErrorId.ERR_OVERRIDE_BAND_EXCEEDED)
        after = validate_success(api.get_pricing(pr_bad["id"], ANALYST))
        assert after["status"] == "PUBLISHED"


class TestPricingWindows:
    def test_pricing_window_half_open_adjacency_allowed(self, api):
        """PRD §3.5: "no other `PUBLISHED` recommendation for the same property
        and `unit_label` has an overlapping window; windows are half-open, so
        a window that abuts another exactly is not an overlap, but any true
        overlap is rejected with `ERR_PRICING_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/pricing_window_half_open_adjacency_allowed
        """
        fx = setup_managed_property(legal_name="Window Owner LP",
                                    property_name="Window Property", unit_count=40)
        prop = fx["prop"]
        base = create_published_pricing(
            prop, unit_label="W1", recommended_rent_cents=200000,
            start="2026-10-01T00:00:00Z", end="2026-11-01T00:00:00Z",
        )
        assert base["status"] == "PUBLISHED"

        # Adjacent: start exactly at the prior window's end — NOT an overlap.
        adj = get_success_data(
            api.create_pricing(
                prop["id"],
                {"unit_label": "W1", "recommended_rent_cents": 205000,
                 "effective_start_date": "2026-11-01T00:00:00Z",
                 "effective_end_date": "2026-12-01T00:00:00Z"},
                ANALYST,
            )
        )
        adj_pub = validate_success(api.publish_pricing(adj["id"], ANALYST))
        assert adj_pub["status"] == "PUBLISHED"

        # Overlapping by one second: start 2026-10-31T23:59:59Z < base end.
        ovl = get_success_data(
            api.create_pricing(
                prop["id"],
                {"unit_label": "W1", "recommended_rent_cents": 210000,
                 "effective_start_date": "2026-10-31T23:59:59Z",
                 "effective_end_date": "2026-12-01T00:00:00Z"},
                ANALYST,
            )
        )
        resp = api.publish_pricing(ovl["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_PRICING_WINDOW_OVERLAP)

    def test_pricing_window_fully_nested_overlap_rejected(self, api):
        """PRD §3.5: "no other `PUBLISHED` recommendation for the same property
        and `unit_label` has an overlapping window; windows are half-open, so
        a window that abuts another exactly is not an overlap, but any true
        overlap is rejected with `ERR_PRICING_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/pricing_window_half_open_adjacency_allowed
        """
        fx = setup_managed_property(legal_name="Window2 Owner LP",
                                    property_name="Window2 Property", unit_count=40)
        prop = fx["prop"]
        create_published_pricing(
            prop, unit_label="W2", recommended_rent_cents=200000,
            start="2026-10-01T00:00:00Z", end="2026-12-01T00:00:00Z",
        )
        nested = get_success_data(
            api.create_pricing(
                prop["id"],
                {"unit_label": "W2", "recommended_rent_cents": 210000,
                 "effective_start_date": "2026-10-15T00:00:00Z",
                 "effective_end_date": "2026-11-15T00:00:00Z"},
                ANALYST,
            )
        )
        resp = api.publish_pricing(nested["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_PRICING_WINDOW_OVERLAP)


class TestVendorContractWindows:
    def test_vendor_contract_window_start_gte_end_rejected(self, api, acct_headers):
        """PRD §3.3: "created by a `PropertyAccountant` with `vendor_name`,
        `service_type`, `monthly_cost_cents`, `start_date`, and `end_date`,
        where the window must be valid (a start on or after the end is
        rejected with `ERR_INVALID_REQUEST`)".

        Design: Difficulty/resource_temporal_overlap/vendor_contract_window_start_gte_end_rejected
        """
        owner = setup_owner(legal_name="Vendor Owner LP")
        prop = setup_property(owner, name="Vendor Property", unit_count=30)
        start_onboarding(prop, takeover_date="2026-09-01T00:00:00Z")

        zero = api.create_vendor_contract(
            prop["id"],
            {"vendor_name": "ZeroWindowCo", "service_type": "PEST",
             "monthly_cost_cents": 10000,
             "start_date": "2026-10-01T00:00:00Z",
             "end_date": "2026-10-01T00:00:00Z"},
            acct_headers,
        )
        validate_error(zero, ApiErrorId.ERR_INVALID_REQUEST)

        inverted = api.create_vendor_contract(
            prop["id"],
            {"vendor_name": "InvertedCo", "service_type": "PEST",
             "monthly_cost_cents": 10000,
             "start_date": "2026-11-01T00:00:00Z",
             "end_date": "2026-10-01T00:00:00Z"},
            acct_headers,
        )
        validate_error(inverted, ApiErrorId.ERR_INVALID_REQUEST)

        thin = validate_success(
            api.create_vendor_contract(
                prop["id"],
                {"vendor_name": "ThinCo", "service_type": "PEST",
                 "monthly_cost_cents": 10000,
                 "start_date": "2026-10-01T00:00:00Z",
                 "end_date": "2026-10-01T00:00:01Z"},
                acct_headers,
            ),
            expected_status=201,
        )
        assert thin["assignment_status"] == "PENDING"

    def test_vendor_contract_windows_may_overlap_freely(self, api, acct_headers):
        """PRD §3.3: "each `VendorContract` registered against the property —
        created by a `PropertyAccountant` with `vendor_name`, `service_type`,
        `monthly_cost_cents`, `start_date`, and `end_date`, where the window
        must be valid (a start on or after the end is rejected with
        `ERR_INVALID_REQUEST`) — begins with `assignment_status` `PENDING`".

        Design: Difficulty/resource_temporal_overlap/vendor_contract_window_start_gte_end_rejected
        """
        owner = setup_owner(legal_name="Vendor2 Owner LP")
        prop = setup_property(owner, name="Vendor2 Property", unit_count=30)
        start_onboarding(prop, takeover_date="2026-09-01T00:00:00Z")

        # Two overlapping PEST contracts on the same property: both accepted
        # (vendor windows carry no sibling-overlap rule in the PRD).
        v1 = validate_success(
            api.create_vendor_contract(
                prop["id"],
                {"vendor_name": "PestOne", "service_type": "PEST",
                 "monthly_cost_cents": 10000,
                 "start_date": "2026-10-01T00:00:00Z",
                 "end_date": "2026-12-01T00:00:00Z"},
                acct_headers,
            ),
            expected_status=201,
        )
        v2 = validate_success(
            api.create_vendor_contract(
                prop["id"],
                {"vendor_name": "PestTwo", "service_type": "PEST",
                 "monthly_cost_cents": 12000,
                 "start_date": "2026-11-01T00:00:00Z",
                 "end_date": "2027-02-01T00:00:00Z"},
                acct_headers,
            ),
            expected_status=201,
        )
        assert v1["assignment_status"] == "PENDING"
        assert v2["assignment_status"] == "PENDING"


class TestPricingRbac:
    def test_ownerrep_cannot_create_pricing_recommendation(self, api):
        """PRD §2.1: "`RevenueAnalyst` is the manager-side revenue-management
        function: it proposes, publishes, and withdraws pricing
        recommendations."; PRD §2.1: "An attempt to perform an operation
        outside the caller's role is rejected with `ERR_FORBIDDEN_FOR_ROLE`
        (HTTP 403)."

        Design: Corner/rbac/ownerrep_cannot_create_pricing_recommendation
        """
        owner = setup_owner(legal_name="Z Owner LP")
        prop = setup_property(owner, name="Z Property", unit_count=10)
        start_onboarding(prop, takeover_date="2026-09-01T00:00:00Z")

        resp = api.create_pricing(
            prop["id"],
            {"unit_label": "Z1", "recommended_rent_cents": 150000,
             "effective_start_date": "2026-10-01T00:00:00Z",
             "effective_end_date": "2026-11-01T00:00:00Z"},
            make_owner_rep_headers(owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
