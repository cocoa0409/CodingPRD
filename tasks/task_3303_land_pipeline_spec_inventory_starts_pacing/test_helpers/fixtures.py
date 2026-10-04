"""Composite setup helpers.

The most common preamble in this domain is a "ready community": parcel +
ACTIVE option contract + takedown executed (lots BANKED) + open community +
CLASSIC series + FRAMING capacity commitment + PUBLISHED pacing plan covering
the September logical-clock window. All helpers build their preconditions from
scratch via PRD-declared endpoints, using get_success_data so setup failures
surface as clear errors.
"""
from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from .api_client import ApiClient
from .factories import (
    create_capacity_commitment_payload,
    create_community_payload,
    create_home_payload,
    create_incentive_payload,
    create_land_parcel_payload,
    create_option_contract_payload,
    create_pacing_plan_payload,
    create_product_series_payload,
    create_sales_contract_payload,
    create_takedown_payload,
    create_trade_partner_payload,
)
from .test_users import TEST_USERS, make_trade_partner_headers

_DP = TEST_USERS["division_president_headers"]
_LM = TEST_USERS["land_manager_headers"]
_CM = TEST_USERS["community_manager_headers"]
_SA = TEST_USERS["sales_agent_headers"]


def setup_active_contract(api: ApiClient, total_lots: int = C.TOTAL_LOTS,
                          lot_base_price_cents: int = C.LOT_BASE_PRICE_CENTS,
                          option_fee_cents: int = C.OPTION_FEE_CENTS) -> dict:
    """Parcel + option contract executed to ACTIVE.

    Returns dict: parcel, contract (ACTIVE, post-execute).
    """
    parcel = get_success_data(api.create_land_parcel(create_land_parcel_payload(), _LM))
    contract = get_success_data(api.create_option_contract(
        create_option_contract_payload(
            land_parcel_id=parcel["id"],
            total_lots=total_lots,
            lot_base_price_cents=lot_base_price_cents,
            option_fee_cents=option_fee_cents,
        ), _LM))
    contract = get_success_data(api.execute_option_contract(contract["id"], _LM))
    return {"parcel": parcel, "contract": contract}


def create_community(api: ApiClient, **overrides) -> dict:
    return get_success_data(api.create_community(create_community_payload(**overrides), _DP))


def open_community(api: ApiClient, community_id: str) -> dict:
    return get_success_data(api.open_community(community_id, _CM))


def get_contract_version(api: ApiClient, contract_id: str) -> int:
    return get_success_data(api.get_option_contract(contract_id, _LM))["version"]


def schedule_takedown(api: ApiClient, contract_id: str, community_id: str,
                      lot_count: int = 5,
                      window_start: str = C.SEP_WINDOW_START,
                      window_end: str = C.SEP_WINDOW_END) -> dict:
    cv = get_contract_version(api, contract_id)
    return get_success_data(api.create_takedown(contract_id, create_takedown_payload(
        community_id=community_id, lot_count=lot_count,
        window_start=window_start, window_end=window_end,
        expected_contract_version=cv), _LM))


def execute_takedown(api: ApiClient, takedown_id: str) -> dict:
    return get_success_data(api.execute_takedown(takedown_id, _LM))


def create_series(api: ApiClient, community_id: str, **overrides) -> dict:
    return get_success_data(api.create_product_series(
        community_id, create_product_series_payload(**overrides), _CM))


def create_partner_with_commitment(api: ApiClient, community_id: str,
                                   committed_units: int = 10,
                                   period_start: str = C.SEP_PERIOD_START,
                                   period_end: str = C.SEP_PERIOD_END_EXCLUSIVE) -> dict:
    """FRAMING trade partner + one capacity commitment for the community.

    Returns dict: partner, commitment.
    """
    partner = get_success_data(api.create_trade_partner(create_trade_partner_payload(), _DP))
    commitment = get_success_data(api.create_capacity_commitment(
        partner["id"],
        create_capacity_commitment_payload(
            community_id=community_id, committed_units=committed_units,
            period_start=period_start, period_end=period_end),
        make_trade_partner_headers(partner["id"])))
    return {"partner": partner, "commitment": commitment}


def publish_plan(api: ApiClient, community_id: str, max_starts: int = 10,
                 period_start: str = C.SEP_PERIOD_START,
                 period_end: str = C.SEP_WINDOW_END) -> dict:
    cv = get_success_data(api.get_community(community_id, _DP))["version"]
    return get_success_data(api.create_pacing_plan(community_id, create_pacing_plan_payload(
        period_start=period_start, period_end=period_end,
        max_starts=max_starts, expected_community_version=cv), _DP))


def list_banked_lot_ids(api: ApiClient, community_id: str) -> list:
    lots = get_success_data(api.list_lots(community_id, _CM))
    return [lot["id"] for lot in lots if lot.get("state") == "BANKED"]


def setup_ready_community(api: ApiClient, lot_count: int = 5, max_starts: int = 10,
                          committed_units: int = 10, open_it: bool = True) -> dict:
    """Full ready-to-start scenario at the default logical clock.

    Parcel + ACTIVE contract (40 lots) + executed takedown releasing
    ``lot_count`` BANKED lots + CLASSIC series + FRAMING capacity commitment +
    PUBLISHED September pacing plan.

    Returns dict: parcel, contract, community, series, partner, commitment,
    plan, lot_ids (list of BANKED lot ids, created_at order).
    """
    base = setup_active_contract(api)
    community = create_community(api)
    if open_it:
        community = open_community(api, community["id"])
    series = create_series(api, community["id"])
    takedown = schedule_takedown(api, base["contract"]["id"], community["id"],
                                 lot_count=lot_count)
    execute_takedown(api, takedown["id"])
    cap = create_partner_with_commitment(api, community["id"], committed_units=committed_units)
    plan = publish_plan(api, community["id"], max_starts=max_starts)
    lot_ids = list_banked_lot_ids(api, community["id"])
    return {
        "parcel": base["parcel"],
        "contract": base["contract"],
        "community": community,
        "series": series,
        "partner": cap["partner"],
        "commitment": cap["commitment"],
        "plan": plan,
        "lot_ids": lot_ids,
    }


def start_home(api: ApiClient, community_id: str, lot_id: str, series_id: str,
               base_price_cents: int = C.HOME_BASE_PRICE_CENTS, **overrides) -> dict:
    return get_success_data(api.create_home(community_id, create_home_payload(
        lot_id=lot_id, product_series_id=series_id,
        base_price_cents=base_price_cents, **overrides), _CM))


def advance_home_to(api: ApiClient, home_id: str, target_stage: str) -> dict:
    """Advance build stage one step at a time until target_stage is reached."""
    order = ["PERMITTED", "FOUNDATION", "FRAME", "DRYWALL", "COMPLETE"]
    home = get_success_data(api.get_home(home_id, _CM))
    while home["build_stage"] != target_stage:
        assert home["build_stage"] in order, f"cannot advance from {home['build_stage']}"
        home = get_success_data(api.advance_stage(home_id, _CM))
    return home


def create_contract_for_home(api: ApiClient, home_id: str,
                             contract_price_cents: int = C.HOME_BASE_PRICE_CENTS,
                             buyer_name: str = "Buyer A") -> dict:
    return get_success_data(api.create_sales_contract(create_sales_contract_payload(
        home_id=home_id, contract_price_cents=contract_price_cents,
        buyer_name=buyer_name), _SA))


def approve_contract(api: ApiClient, contract_id: str) -> dict:
    return get_success_data(api.approve_sales_contract(contract_id, _CM))


def close_contract(api: ApiClient, contract_id: str) -> dict:
    return get_success_data(api.close_sales_contract(contract_id, _CM))


def sell_and_close_home(api: ApiClient, home_id: str, price_cents: int) -> dict:
    """Create -> approve -> close a sales contract on a COMPLETE home."""
    sc = create_contract_for_home(api, home_id, contract_price_cents=price_cents)
    approve_contract(api, sc["id"])
    return close_contract(api, sc["id"])


def create_incentive(api: ApiClient, community_id: str, **overrides) -> dict:
    return get_success_data(api.create_incentive(
        community_id, create_incentive_payload(**overrides), _CM))


def set_clock(api: ApiClient, to_iso8601: str) -> dict:
    return get_success_data(api.set_clock(to_iso8601, _DP))
