"""End-of-term settlement: provisional vs final snapshot divergence (BUYOUT)."""
from test_helpers import (
    api_client, validate_success, get_success_data, setup_agreement_with_assets,
    create_jobsite, deploy_asset, report_claim, verify_claim, approve_claim,
    get_settlement_rows, list_agreement_assets, make_fleet_admin_headers,
    set_clock, TEST_USERS,
)

ADMIN = TEST_USERS["fleet_admin_headers"]


def _setup_two_asset_ending_agreement():
    """ACTIVE agreement (term 1, start 9/1) with 2 assets, one DEPLOYED;
    BUYOUT elected; provisional snapshot taken. Returns env dict."""
    set_clock("2026-09-01T00:00:00Z")
    env = setup_agreement_with_assets(
        n_assets=2, category="BREAKER", weight_class="HEAVY",
        replacement_value_cents=200000,
        rate_card_overrides={
            "tool_category": "BREAKER", "base_monthly_rate_cents": 20000,
            "tier2_threshold": 50, "tier2_monthly_rate_cents": 20000,
            "tier3_threshold": 100, "tier3_monthly_rate_cents": 20000,
            "min_monthly_fee_cents": 0,
        },
        term_months=1, start_date="2026-09-01T00:00:00Z",
        end_of_term_option="BUYOUT")
    site = create_jobsite(env["account_id"], capacity_assets=10, cm=env["cm"])
    asset_a = deploy_asset(env["asset_ids"][0], site["id"], env["js"])
    r = api_client.elect_end_of_term(
        env["account_id"], env["agreement_id"],
        {"expected_agreement_version": env["agreement_version"],
         "end_of_term_option": "BUYOUT"}, env["cm"])
    validate_success(r)
    env["jobsite"] = site
    env["asset"] = asset_a
    return env


def test_provisional_settlement_two_assets(api):
    """PRD §3.9: "For `BUYOUT`, each billable asset is charged 20 percent of its
    model's `replacement_value_cents`, rounded half-up to whole cents per asset,
    and the amount is the sum across assets."
    PRD §3.9: "creates the agreement's settlement — at most one settlement
    exists per agreement, linked by its `agreement_id`, with its `option`
    echoing the elected value — with `provisional_amount_cents` computed from
    the fleet as it stands at election time."

    Design: Difficulty/dual_variant_calc/end_of_term_provisional_vs_final_buyout
    """
    env = _setup_two_asset_ending_agreement()
    rows = get_settlement_rows(env["agreement_id"])
    assert len(rows) == 1, "at most one settlement per agreement"
    settlement = rows[0]
    assert settlement["option"] == "BUYOUT"
    # 2 billable assets * round_half_up(200000 * 0.20) = 2 * 40000
    assert settlement["provisional_amount_cents"] == 80000, (
        f"expected 80000, got {settlement['provisional_amount_cents']}")
    assert settlement["finalized"] is False


def test_final_settlement_diverges_after_asset_lost(api):
    """PRD §3.9: "the final amount is recomputed from the billable fleet as of
    the finalization call — before any retirements the call itself performs —
    so the provisional and final figures diverge whenever the fleet changed in
    between, for example when an asset went `LOST` after the election; the
    result is committed to `final_amount_cents` and `finalized` becomes true."

    Design: Difficulty/dual_variant_calc/end_of_term_provisional_vs_final_buyout
    """
    env = _setup_two_asset_ending_agreement()
    claim = report_claim(env["asset"]["id"], env["js"])
    verify_claim(claim["id"], "PR-S1", "2026-09-01T12:00:00Z", "admin-s1")
    approve_claim(claim["id"], "adj-s1")

    r = api_client.finalize_settlement(
        env["account_id"], env["agreement_id"], 0, ADMIN)
    agreement = validate_success(r)
    assert agreement["status"] == "CLOSED"

    rows = get_settlement_rows(env["agreement_id"])
    settlement = rows[0]
    assert settlement["provisional_amount_cents"] == 80000
    assert settlement["final_amount_cents"] == 40000, (
        "one asset went LOST; only 1 billable asset remains at finalization")
    assert settlement["finalized"] is True
    assert settlement["final_amount_cents"] != settlement["provisional_amount_cents"]
