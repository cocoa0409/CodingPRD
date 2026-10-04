"""Boundary precision: jobsite capacity exact boundary; 48h police window."""
from test_helpers import (
    api_client, validate_success, validate_error, setup_agreement_with_assets,
    create_jobsite, deploy_asset, report_claim, verify_claim,
    set_clock, make_fleet_admin_headers, TEST_USERS,
)

ADMIN = TEST_USERS["fleet_admin_headers"]


def _two_asset_agreement():
    return setup_agreement_with_assets(
        n_assets=2, clock="2026-09-01T00:00:00Z",
        rate_card_overrides={
            "tool_category": "DRILL", "base_monthly_rate_cents": 5000,
            "tier2_threshold": 100, "tier2_monthly_rate_cents": 5000,
            "tier3_threshold": 200, "tier3_monthly_rate_cents": 5000,
            "min_monthly_fee_cents": 0,
        })


def test_deploy_at_exact_capacity_rejected(api):
    """PRD §3.5: "the target's `deployed_asset_count` to be below its
    `capacity_assets` — a full jobsite rejects the deploy with
    `ERR_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/jobsite_capacity_exact_boundary
    """
    env = _two_asset_agreement()
    site = create_jobsite(env["account_id"], capacity_assets=1, cm=env["cm"])
    first = deploy_asset(env["asset_ids"][0], site["id"], env["js"])
    assert first["status"] == "DEPLOYED", "count 0 < capacity 1 succeeds"
    r = api_client.deploy_asset(env["asset_ids"][1], site["id"], env["js"])
    validate_error(r, "ERR_CAPACITY_EXCEEDED")


def test_deploy_below_capacity_keeps_count_accurate(api):
    """PRD §3.5: "A successful deploy moves the asset to `DEPLOYED`, records
    the jobsite in `current_jobsite_id`, stamps `commissioned_on` if the asset
    has never been deployed before (this first-deployment timestamp later
    anchors theft depreciation), and raises the jobsite's
    `deployed_asset_count` by 1."

    Design: Difficulty/boundary_precision_check/jobsite_capacity_exact_boundary
    """
    env = _two_asset_agreement()
    site = create_jobsite(env["account_id"], capacity_assets=2, cm=env["cm"])
    first = deploy_asset(env["asset_ids"][0], site["id"], env["js"])
    assert first["status"] == "DEPLOYED"
    assert first["current_jobsite_id"] == site["id"]
    assert first["commissioned_on"] is not None
    second = deploy_asset(env["asset_ids"][1], site["id"], env["js"])
    assert second["status"] == "DEPLOYED", "count 1 < capacity 2 succeeds"
    from test_helpers import get_jobsite
    site_after = get_jobsite(site["id"])
    assert site_after["deployed_asset_count"] == 2


def _report_two_claims(env):
    site = create_jobsite(env["account_id"], capacity_assets=10, cm=env["cm"])
    deploy_asset(env["asset_ids"][0], site["id"], env["js"])
    deploy_asset(env["asset_ids"][1], site["id"], env["js"])
    c1 = report_claim(env["asset_ids"][0], env["js"])
    c2 = report_claim(env["asset_ids"][1], env["js"])
    return c1, c2


def test_police_report_at_exactly_48h_accepted(api):
    """PRD §3.7: "the `police_report_filed_at` timestamp, which must fall no
    later than 48 hours after `reported_at` — the boundary is inclusive, and a
    report filed after that window is rejected with `ERR_WINDOW_EXPIRED`."

    Design: Difficulty/boundary_precision_check/police_report_48h_inclusive_boundary
    """
    env = _two_asset_agreement()
    c1, _c2 = _report_two_claims(env)  # both reported at 2026-09-01T00:00:00Z
    r = api_client.verify_police_report(
        c1["id"],
        {"police_report_number": "PR-OK",
         "police_report_filed_at": "2026-09-03T00:00:00Z"},
        make_fleet_admin_headers("admin-bnd1"))
    claim = validate_success(r)
    assert claim["status"] == "POLICE_VERIFIED", "exactly +48h is inclusive"


def test_police_report_one_second_past_48h_rejected(api):
    """PRD §3.7: "the `police_report_filed_at` timestamp, which must fall no
    later than 48 hours after `reported_at` — the boundary is inclusive, and a
    report filed after that window is rejected with `ERR_WINDOW_EXPIRED`."

    Design: Difficulty/boundary_precision_check/police_report_48h_inclusive_boundary
    """
    env = _two_asset_agreement()
    _c1, c2 = _report_two_claims(env)
    r = api_client.verify_police_report(
        c2["id"],
        {"police_report_number": "PR-LATE",
         "police_report_filed_at": "2026-09-03T00:00:01Z"},
        make_fleet_admin_headers("admin-bnd1"))
    validate_error(r, "ERR_WINDOW_EXPIRED")
