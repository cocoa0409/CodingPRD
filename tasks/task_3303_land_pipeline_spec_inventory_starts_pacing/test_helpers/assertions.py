"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    BuildStage,
    CommunityPhase,
    CommunityPosture,
    IncentiveStatus,
    IncentiveType,
    LotState,
    OptionContractState,
    PacingPlanState,
    SalesContractState,
    SalesStatus,
    SeriesCode,
    TakedownState,
    Trade,
)


def _assert_common(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, f"{label}.version must be int >= 1"


def assert_land_parcel(data: dict):
    _assert_common(data, "LandParcel")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["market_code"], str) and data["market_code"]
    assert isinstance(data["acres"], (int, float))


def assert_option_contract(data: dict):
    _assert_common(data, "OptionContract")
    assert data["state"] in {s.value for s in OptionContractState}
    assert isinstance(data["option_fee_cents"], int)
    assert isinstance(data["earnest_money_cents"], int)
    assert isinstance(data["total_lots"], int)
    assert isinstance(data["lot_base_price_cents"], int)
    assert isinstance(data["lots_taken_down"], int)
    assert isinstance(data["cure_fee_cents"], int)


def assert_takedown(data: dict):
    _assert_common(data, "Takedown")
    assert data["state"] in {s.value for s in TakedownState}
    assert isinstance(data["lot_count"], int)
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])


def assert_community(data: dict):
    _assert_common(data, "Community")
    assert data["phase"] in {p.value for p in CommunityPhase}
    assert isinstance(data["standing_spec_count"], int)
    assert isinstance(data["starts_this_period"], int)
    assert isinstance(data["lifetime_closed_sales"], int)


def assert_product_series(data: dict):
    _assert_common(data, "ProductSeries")
    assert data["series_code"] in {s.value for s in SeriesCode}
    assert isinstance(data["min_price_cents"], int)
    assert isinstance(data["max_price_cents"], int)


def assert_lot(data: dict):
    _assert_common(data, "Lot")
    assert data["state"] in {s.value for s in LotState}


def assert_home(data: dict):
    _assert_common(data, "Home")
    assert data["build_stage"] in {s.value for s in BuildStage}
    assert data["sales_status"] in {s.value for s in SalesStatus}
    assert isinstance(data["base_price_cents"], int)
    assert isinstance(data["lot_premium_cents"], int)
    assert isinstance(data["gross_price_cents"], int)
    assert isinstance(data["adjusted_price_cents"], int)
    assert isinstance(data["stacked_incentive_cents"], int)
    assert isinstance(data["net_effective_price_cents"], int)


def assert_sales_contract(data: dict):
    _assert_common(data, "SalesContract")
    assert data["state"] in {s.value for s in SalesContractState}
    assert isinstance(data["contract_price_cents"], int)
    assert isinstance(data["renegotiation_count"], int)


def assert_incentive(data: dict):
    _assert_common(data, "Incentive")
    assert data["type"] in {t.value for t in IncentiveType}
    assert data["status"] in {s.value for s in IncentiveStatus}


def assert_trade_partner(data: dict):
    _assert_common(data, "TradePartner")
    assert data["trade"] in {t.value for t in Trade}


def assert_capacity_commitment(data: dict):
    _assert_common(data, "CapacityCommitment")
    assert isinstance(data["committed_units"], int)
    assert isinstance(data["allocated_units"], int)
    assert isinstance(data["remaining_units"], int)


def assert_pacing_plan(data: dict):
    _assert_common(data, "PacingPlan")
    assert data["state"] in {s.value for s in PacingPlanState}
    assert isinstance(data["max_starts"], int)


def assert_capacity_invariant(commitment: dict):
    """committed_units == allocated_units + remaining_units at all times."""
    assert (
        commitment["committed_units"]
        == commitment["allocated_units"] + commitment["remaining_units"]
    ), (
        f"capacity invariant violated: committed {commitment['committed_units']} != "
        f"allocated {commitment['allocated_units']} + remaining {commitment['remaining_units']}"
    )


def assert_home_status_partition(homes: list):
    """Every home's sales_status is one of the four partition buckets."""
    buckets = {s.value for s in SalesStatus}
    for h in homes:
        assert h["sales_status"] in buckets, f"unexpected sales_status {h['sales_status']}"
