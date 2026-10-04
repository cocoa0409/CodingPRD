"""Member organization registration, reads, and the logical clock."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    assert_member_org,
    api_client,
    create_donation_site_payload,
    create_member_org_payload,
    get_org,
    make_member_admin_headers,
    validate_error,
    validate_success,
)


def _parse_instant(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class TestMemberOrgBasics:
    def test_member_org_create_applies_defaults(self, api, platform_admin_headers):
        """PRD 3.1: "The optional `costing_method` selects the unit-costing
        variant used at pricing time — `STANDARD` or `ACTUAL` — and defaults to
        `STANDARD` when omitted."
        PRD 3.1: "A newly registered organization starts with
        `brand_license_status` `ACTIVE`, every ledger zeroed
        (`retail_margin_pool_cents`, `reserved_cents`, `contract_revenue_cents`,
        `total_diverted_lbs`, `total_disposed_lbs` all at zero), `margin_health`
        `HEALTHY`, `diversion_compliant` true, and `last_markdown_week` null
        until its first markdown event."
        PRD 2.9: "The `diversion_rate_bps` is the diverted share expressed in
        basis points: when the two totals sum to zero the rate is defined as
        10000; otherwise it is the floor of `total_diverted_lbs` multiplied by
        10000 and divided by the sum of the two totals."
        PRD 2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."

        Design: Corner/entities/member_org_create_applies_defaults_system_fields_and_envelope
        """
        resp = api_client.create_member_org(
            create_member_org_payload(
                name="Org Defaults",
                reserve_floor_cents=1000,
                diversion_floor_bps=7500),
            platform_admin_headers)
        data = validate_success(resp, 201)
        body = resp.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert body["meta"]["api_request_timestamp"]
        assert_member_org(data)
        assert data["costing_method"] == "STANDARD"
        assert data["brand_license_status"] == "ACTIVE"
        assert data["margin_health"] == "HEALTHY"
        assert data["diversion_compliant"] is True
        assert data["diversion_rate_bps"] == 10000
        assert data["retail_margin_pool_cents"] == 0
        assert data["reserved_cents"] == 0
        assert data["contract_revenue_cents"] == 0
        assert data["total_diverted_lbs"] == 0
        assert data["total_disposed_lbs"] == 0
        assert data.get("last_markdown_week") is None

    def test_member_org_get_unknown_id_returns_not_found(
            self, api, platform_admin_headers):
        """PRD 2.10: "Existence of path identifiers and body-referenced foreign
        keys, validated left to right: `ERR_NOT_FOUND` (HTTP 404)."
        PRD 2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/entities/member_org_get_unknown_id_returns_not_found
        """
        resp = api_client.get_member_org(
            "00000000-0000-0000-0000-000000000000", platform_admin_headers)
        error = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        body = resp.json()
        assert body["response_type"] == "error"
        assert error["message"]

    def test_clock_defaults_to_fixed_epoch_and_drives_timestamps(
            self, api, platform_admin_headers):
        """PRD 2.4: "All time-dependent behavior in the system is driven by a
        logical clock, never by wall-clock time."
        PRD 2.4: "The server starts at `2026-09-01T00:00:00Z` and stays there
        until explicitly advanced."

        Design: Corner/endpoints/clock_defaults_to_fixed_epoch_and_drives_timestamps
        """
        resp = api_client.create_member_org(
            create_member_org_payload(name="Org Clock"), platform_admin_headers)
        org = validate_success(resp, 201)
        assert _parse_instant(org["created_at"]) == datetime(
            2026, 9, 1, tzinfo=timezone.utc)

        api_client.set_clock("2026-10-15T08:30:00Z", platform_admin_headers)
        site_resp = api_client.create_donation_site(
            create_donation_site_payload(org["id"], name="Site Clock"),
            make_member_admin_headers(org["id"]))
        site = validate_success(site_resp, 201)
        assert _parse_instant(site["created_at"]) == datetime(
            2026, 10, 15, 8, 30, tzinfo=timezone.utc)
