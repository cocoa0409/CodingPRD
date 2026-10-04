"""Corner/endpoints: OCC stale version on adjust-fleet and election, renewal
finalize, adjust-fleet return semantics."""
from datetime import datetime, timezone

from test_helpers import (
    api_client, validate_success, validate_error, create_account,
    create_tool_model, create_agreement_payload, setup_agreement_with_assets,
    get_settlement_rows, set_clock, make_contractor_manager_headers, TEST_USERS,
)

ADMIN = TEST_USERS["fleet_admin_headers"]


def _parse_iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_occ_stale_version_on_adjust_fleet_returns_412(api):
    """PRD §2.7: "If the submitted value does not match the agreement's current
    `version` — because another writer has advanced the agreement since the
    client read it — the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412). For adjust-fleet this prevents repricing against a superseded
    fleet composition"

    Design: Corner/endpoints/occ_stale_version_on_adjust_fleet_returns_412
    """
    account = create_account()
    acct = account["id"]
    cm = make_contractor_manager_headers(acct)
    tm = create_tool_model(category="SAW", replacement_value_cents=50000)
    r = api_client.create_agreement(acct, create_agreement_payload(), ADMIN)
    agreement = validate_success(r, expected_status=201)
    stale_version = agreement["version"]
    r = api_client.adjust_fleet(
        acct, agreement["id"],
        {"expected_agreement_version": stale_version,
         "add_tool_model_ids": [tm["id"]], "return_asset_ids": []}, cm)
    validate_success(r)  # version advances to 2
    r = api_client.adjust_fleet(
        acct, agreement["id"],
        {"expected_agreement_version": stale_version,
         "add_tool_model_ids": [tm["id"]], "return_asset_ids": []}, cm)
    validate_error(r, "ERR_STALE_VERSION")


def test_occ_stale_version_on_election_returns_412(api):
    """PRD §2.7: "If the submitted value does not match the agreement's current
    `version` — because another writer has advanced the agreement since the
    client read it — the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412). For adjust-fleet this prevents repricing against a superseded
    fleet composition; for end-of-term election it prevents a provisional
    settlement being frozen from a fleet snapshot the client never saw."

    Design: Corner/endpoints/occ_stale_version_on_election_returns_412
    """
    env = setup_agreement_with_assets(
        n_assets=1, clock="2026-09-01T00:00:00Z", term_months=1,
        start_date="2026-09-01T00:00:00Z", end_of_term_option="RETURN")
    # version 1 was captured at creation; after adjust (+1) and activate (+1)
    # the agreement is at version 3, so 1 is stale
    r = api_client.elect_end_of_term(
        env["account_id"], env["agreement_id"],
        {"expected_agreement_version": 1, "end_of_term_option": "RETURN"},
        env["cm"])
    validate_error(r, "ERR_STALE_VERSION")
    r = api_client.elect_end_of_term(
        env["account_id"], env["agreement_id"],
        {"expected_agreement_version": env["agreement_version"],
         "end_of_term_option": "RETURN"}, env["cm"])
    agreement = validate_success(r)
    assert agreement["status"] == "ENDING"


def test_renewal_extends_term_and_returns_to_active(api):
    """PRD §3.9: "Under `RENEWAL`, the agreement returns from `ENDING` to
    `ACTIVE` instead: `term_months` grows by 12, `end_date` is recomputed, the
    settlement is finalized with a `final_amount_cents` of 0, and subsequent
    billing uses the rate card effective at the renewal date."

    Design: Corner/endpoints/renewal_extends_term_and_returns_to_active
    """
    env = setup_agreement_with_assets(
        n_assets=1, clock="2026-09-01T00:00:00Z", term_months=1,
        start_date="2026-09-01T00:00:00Z", end_of_term_option="RENEWAL")
    r = api_client.elect_end_of_term(
        env["account_id"], env["agreement_id"],
        {"expected_agreement_version": env["agreement_version"],
         "end_of_term_option": "RENEWAL"}, env["cm"])
    validate_success(r)
    r = api_client.finalize_settlement(
        env["account_id"], env["agreement_id"], 0, ADMIN)
    agreement = validate_success(r)
    assert agreement["status"] == "ACTIVE"
    assert agreement["term_months"] == 13
    assert _parse_iso(agreement["end_date"]) == _parse_iso("2027-10-01T00:00:00Z")
    rows = get_settlement_rows(env["agreement_id"])
    assert rows[0]["final_amount_cents"] == 0
    assert rows[0]["finalized"] is True


def test_adjust_fleet_return_registered_asset(api):
    """PRD §3.4: "Each returned asset must currently be `REGISTERED`;
    attempting to return an asset that is `DEPLOYED`, `IN_TRANSIT`, or
    `IN_REPAIR` is rejected with `ERR_INVALID_STATE`. Accepted returns move the
    asset from `REGISTERED` to `RETIRED`."

    Design: Corner/endpoints/adjust_fleet_return_registered_asset
    """
    from test_helpers import create_jobsite, deploy_asset, get_agreement, get_asset
    env = setup_agreement_with_assets(n_assets=3)
    site = create_jobsite(env["account_id"], capacity_assets=5, cm=env["cm"])
    deploy_asset(env["asset_ids"][2], site["id"], env["js"])
    # return a REGISTERED asset: succeeds, fleet_size_target drops 3 -> 2
    r = api_client.adjust_fleet(
        env["account_id"], env["agreement_id"],
        {"expected_agreement_version": env["agreement_version"],
         "add_tool_model_ids": [], "return_asset_ids": [env["asset_ids"][0]]},
        env["cm"])
    agreement = validate_success(r)
    assert agreement["fleet_size_target"] == 2
    assert get_asset(env["asset_ids"][0])["status"] == "RETIRED"
    # returning a DEPLOYED asset is rejected
    r = api_client.adjust_fleet(
        env["account_id"], env["agreement_id"],
        {"expected_agreement_version": agreement["version"],
         "add_tool_model_ids": [], "return_asset_ids": [env["asset_ids"][2]]},
        env["cm"])
    validate_error(r, "ERR_INVALID_STATE")
