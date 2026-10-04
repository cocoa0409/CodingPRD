"""Resource temporal overlap: support-case half-open windows; rate-card
closed intervals. Compensating invariants: transfer/cancel counts, fleet size
conservation across repair."""
from test_helpers import (
    api_client, validate_success, validate_error, create_account,
    create_jobsite, setup_agreement_with_assets, setup_deployed_asset,
    open_ticket, drive_ticket_to_closed, get_agreement, get_asset, get_jobsite,
    create_rate_card, make_contractor_manager_headers, TEST_USERS,
)

ADMIN = TEST_USERS["fleet_admin_headers"]


def _account_with_jobsite():
    account = create_account()
    acct = account["id"]
    cm = make_contractor_manager_headers(acct)
    site = create_jobsite(acct, capacity_assets=5, cm=cm)
    return acct, cm, site


def test_support_case_adjacent_half_open_windows_allowed(api):
    """PRD §3.8: "the case occupies the half-open two-hour window beginning at
    `scheduled_for` at that jobsite, and a new case whose window overlaps the
    window of another non-`REJECTED` case at the same jobsite is rejected with
    `ERR_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/support_case_half_open_window_overlap
    """
    acct, cm, site = _account_with_jobsite()
    r = api_client.create_support_case(
        acct, {"kind": "ANCHOR_DESIGN", "jobsite_id": site["id"],
               "scheduled_for": "2026-09-10T10:00:00Z"}, cm)
    validate_success(r, expected_status=201)
    r = api_client.create_support_case(
        acct, {"kind": "FIRESTOP", "jobsite_id": site["id"],
               "scheduled_for": "2026-09-10T12:00:00Z"}, cm)
    validate_success(r, expected_status=201), "[10:00,12:00) and [12:00,14:00) do not overlap"


def test_support_case_overlapping_window_rejected(api):
    """PRD §3.8: "the case occupies the half-open two-hour window beginning at
    `scheduled_for` at that jobsite, and a new case whose window overlaps the
    window of another non-`REJECTED` case at the same jobsite is rejected with
    `ERR_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/support_case_half_open_window_overlap
    """
    acct, cm, site = _account_with_jobsite()
    r = api_client.create_support_case(
        acct, {"kind": "ANCHOR_DESIGN", "jobsite_id": site["id"],
               "scheduled_for": "2026-09-10T10:00:00Z"}, cm)
    validate_success(r, expected_status=201)
    r = api_client.create_support_case(
        acct, {"kind": "FIRESTOP", "jobsite_id": site["id"],
               "scheduled_for": "2026-09-10T11:00:00Z"}, cm)
    validate_error(r, "ERR_WINDOW_OVERLAP")


def test_rate_card_shared_boundary_day_overlaps(api):
    """PRD §3.2: "A new card whose closed interval overlaps the closed interval
    of an existing `ACTIVE` card of the same `tool_category` is rejected with
    `ERR_WINDOW_OVERLAP`"

    Design: Difficulty/resource_temporal_overlap/rate_card_closed_interval_overlap
    """
    create_rate_card(code="RC-OVL2-A", effective_from="2026-01-01T00:00:00Z",
                     effective_to="2026-12-31T00:00:00Z")
    from test_helpers import create_rate_card_payload
    r = api_client.create_rate_card(create_rate_card_payload(
        code="RC-OVL2-B", effective_from="2026-12-31T00:00:00Z",
        effective_to="2027-06-30T00:00:00Z"), ADMIN)
    validate_error(r, "ERR_WINDOW_OVERLAP")


def test_rate_card_disjoint_interval_accepted(api):
    """PRD §3.2: "Each card is valid over a closed interval from
    `effective_from` through `effective_to`, both bounds included"

    Design: Difficulty/resource_temporal_overlap/rate_card_closed_interval_overlap
    """
    create_rate_card(code="RC-OVL2-A", effective_from="2026-01-01T00:00:00Z",
                     effective_to="2026-12-31T00:00:00Z")
    from test_helpers import create_rate_card_payload
    r = api_client.create_rate_card(create_rate_card_payload(
        code="RC-OVL2-C", effective_from="2027-01-01T00:00:00Z",
        effective_to="2027-12-31T00:00:00Z"), ADMIN)
    card = validate_success(r, expected_status=201)
    assert card["status"] == "ACTIVE"


def _transfer_setup():
    env = setup_agreement_with_assets(
        n_assets=1,
        rate_card_overrides={
            "tool_category": "DRILL", "base_monthly_rate_cents": 5000,
            "tier2_threshold": 100, "tier2_monthly_rate_cents": 5000,
            "tier3_threshold": 200, "tier3_monthly_rate_cents": 5000,
            "min_monthly_fee_cents": 0,
        })
    site_a = create_jobsite(env["account_id"], capacity_assets=5, cm=env["cm"])
    site_b = create_jobsite(env["account_id"], capacity_assets=5, cm=env["cm"])
    deploy_id = env["asset_ids"][0]
    from test_helpers import deploy_asset
    deploy_asset(deploy_id, site_a["id"], env["js"])
    env["site_a"] = site_a
    env["site_b"] = site_b
    return env


def test_transfer_then_cancel_conserves_jobsite_counts(api):
    """PRD §3.5: "Cancelling the transfer instead returns the asset to
    `DEPLOYED` at its origin: `current_jobsite_id` is restored to the origin,
    `pending_jobsite_id` is cleared, and the origin jobsite's
    `deployed_asset_count` rises by 1, compensating the earlier decrement."

    Design: Difficulty/compensating_invariant/transfer_cancel_transfer_conserves_jobsite_counts
    """
    env = _transfer_setup()
    asset_id = env["asset_ids"][0]
    r = api_client.transfer_asset(asset_id, env["site_b"]["id"], env["js"])
    asset = validate_success(r)
    assert asset["status"] == "IN_TRANSIT"
    assert asset["current_jobsite_id"] is None
    assert asset["pending_jobsite_id"] == env["site_b"]["id"]
    assert get_jobsite(env["site_a"]["id"])["deployed_asset_count"] == 0
    assert get_jobsite(env["site_b"]["id"])["deployed_asset_count"] == 0

    r = api_client.cancel_transfer(asset_id, env["js"])
    asset = validate_success(r)
    assert asset["status"] == "DEPLOYED"
    assert asset["current_jobsite_id"] == env["site_a"]["id"]
    assert asset["pending_jobsite_id"] is None
    assert get_jobsite(env["site_a"]["id"])["deployed_asset_count"] == 1
    assert get_jobsite(env["site_b"]["id"])["deployed_asset_count"] == 0


def test_transfer_then_confirm_arrival_moves_count(api):
    """PRD §3.5: "Confirming arrival moves the asset back to `DEPLOYED` at the
    pending site: `current_jobsite_id` takes the value of `pending_jobsite_id`,
    `pending_jobsite_id` is cleared, and the target jobsite's
    `deployed_asset_count` rises by 1."

    Design: Difficulty/compensating_invariant/transfer_cancel_transfer_conserves_jobsite_counts
    """
    env = _transfer_setup()
    asset_id = env["asset_ids"][0]
    r = api_client.transfer_asset(asset_id, env["site_b"]["id"], env["js"])
    validate_success(r)
    r = api_client.confirm_arrival(asset_id, env["js"])
    asset = validate_success(r)
    assert asset["status"] == "DEPLOYED"
    assert asset["current_jobsite_id"] == env["site_b"]["id"]
    assert get_jobsite(env["site_a"]["id"])["deployed_asset_count"] == 0
    assert get_jobsite(env["site_b"]["id"])["deployed_asset_count"] == 1


def test_repair_open_close_conserves_fleet_size(api):
    """PRD §3.3: "`fleet_size_target`, the count of its assets in `REGISTERED`,
    `DEPLOYED`, `IN_TRANSIT`, or `IN_REPAIR`"
    PRD §3.6: "The repaired asset returns from `IN_REPAIR` to `DEPLOYED` at the
    jobsite recorded in its `current_jobsite_id`"

    Design: Difficulty/compensating_invariant/repair_open_close_conserves_fleet_size
    """
    env = setup_deployed_asset(
        rate_card_overrides={
            "tool_category": "DRILL", "base_monthly_rate_cents": 5000,
            "tier2_threshold": 100, "tier2_monthly_rate_cents": 5000,
            "tier3_threshold": 200, "tier3_monthly_rate_cents": 5000,
            "min_monthly_fee_cents": 0,
        })
    ticket = open_ticket(env["asset"]["id"], False, env["js"])
    agreement = get_agreement(env["agreement_id"])
    assert agreement["fleet_size_target"] == 1, "IN_REPAIR stays billable"
    drive_ticket_to_closed(ticket["id"])
    agreement = get_agreement(env["agreement_id"])
    assert agreement["fleet_size_target"] == 1
    assert get_asset(env["asset"]["id"])["status"] == "DEPLOYED"


def test_repair_open_decrements_jobsite_count_and_retains_jobsite(api):
    """PRD §3.6: "The asset moves from `DEPLOYED` to `IN_REPAIR`, the ticket is
    created in `OPENED` with `opened_at` stamped from the logical clock, the
    origin jobsite's `deployed_asset_count` falls by 1, and the asset retains
    its `current_jobsite_id` so it can go home after repair."

    Design: Difficulty/compensating_invariant/repair_open_close_conserves_fleet_size
    """
    env = setup_deployed_asset(
        rate_card_overrides={
            "tool_category": "DRILL", "base_monthly_rate_cents": 5000,
            "tier2_threshold": 100, "tier2_monthly_rate_cents": 5000,
            "tier3_threshold": 200, "tier3_monthly_rate_cents": 5000,
            "min_monthly_fee_cents": 0,
        })
    ticket = open_ticket(env["asset"]["id"], False, env["js"])
    assert ticket["status"] == "OPENED"
    asset = get_asset(env["asset"]["id"])
    assert asset["status"] == "IN_REPAIR"
    assert asset["current_jobsite_id"] == env["jobsite"]["id"]
    assert get_jobsite(env["jobsite"]["id"])["deployed_asset_count"] == 0
