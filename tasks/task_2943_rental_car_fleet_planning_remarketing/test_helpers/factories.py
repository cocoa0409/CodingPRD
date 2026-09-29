"""Request-payload factories.

Each factory returns only the fields the PRD lists as client input for that
operation; server-minted, derived and computed fields are never sent unless a
test is deliberately probing that they are ignored. Monetary and count fields
are JSON integers, percentage fields are JSON numbers, and every instant is a
full ISO-8601 UTC instant rather than a bare date.
"""

from typing import Any, Dict, Optional

from .types import (
    ChannelCode,
    DamageType,
    ProgramType,
    Region,
    Season,
    TaskType,
)

# --------------------------------------------------------------------------
# Reference market economics used across scenarios.
# --------------------------------------------------------------------------

ATL = {
    "code": "ATL",
    "name": "Atlanta",
    "region": Region.EAST,
    "transport_hub_distance_km": 23,
    "transfer_cost_per_km_cents": 250,
    "storage_cost_per_day_cents": 800,
    "prep_capacity_per_day": 2,
    "registration_lead_days": 3,
}

DFW = {
    "code": "DFW",
    "name": "Dallas",
    "region": Region.CENTRAL,
    "transport_hub_distance_km": 35,
    "transfer_cost_per_km_cents": 300,
    "storage_cost_per_day_cents": 700,
    "prep_capacity_per_day": 4,
    "registration_lead_days": 2,
}

ORD = {
    "code": "ORD",
    "name": "Chicago",
    "region": Region.CENTRAL,
    "transport_hub_distance_km": 40,
    "transfer_cost_per_km_cents": 280,
    "storage_cost_per_day_cents": 900,
    "prep_capacity_per_day": 5,
    "registration_lead_days": 4,
}

# --------------------------------------------------------------------------
# Reference segment policy numbers.
# --------------------------------------------------------------------------

MIDSIZE = {
    "code": "MIDSIZE",
    "name": "Midsize Sedan",
    "baseline_daily_rate_cents": 5500,
    "target_utilization_pct": 0.80,
    "target_revenue_per_unit_month_cents": 132000,
    "mileage_band_soft_limit_km": 40000,
    "mileage_band_hard_limit_km": 60000,
    "recondition_cap_cents": 90000,
}

SUV = {
    "code": "SUV",
    "name": "Standard SUV",
    "baseline_daily_rate_cents": 7500,
    "target_utilization_pct": 0.75,
    "target_revenue_per_unit_month_cents": 168000,
    "mileage_band_soft_limit_km": 35000,
    "mileage_band_hard_limit_km": 55000,
    "recondition_cap_cents": 120000,
}

COMPACT = {
    "code": "COMPACT",
    "name": "Compact",
    "baseline_daily_rate_cents": 4200,
    "target_utilization_pct": 0.82,
    "target_revenue_per_unit_month_cents": 103000,
    "mileage_band_soft_limit_km": 38000,
    "mileage_band_hard_limit_km": 58000,
    "recondition_cap_cents": 70000,
}

# --------------------------------------------------------------------------
# Reference manufacturer programs: one guaranteed, one at full risk.
# --------------------------------------------------------------------------

PROGRAM_GUARANTEED = {
    "manufacturer_name": "Northstar Motors",
    "program_year": 2026,
    "program_type": ProgramType.PROGRAM,
    "repurchase_guarantee_pct": 0.82,
    "min_holding_days": 180,
    "max_holding_days": 365,
    "max_eligible_mileage_km": 45000,
    "excess_mileage_charge_cents_per_km": 30,
    "damage_deduction_cap_cents": 150000,
}

PROGRAM_RISK = {
    "manufacturer_name": "Cascade Auto",
    "program_year": 2026,
    "program_type": ProgramType.RISK,
    "repurchase_guarantee_pct": 0.00,
    "min_holding_days": 90,
    "max_holding_days": 900,
    "max_eligible_mileage_km": 100000,
    "excess_mileage_charge_cents_per_km": 0,
    "damage_deduction_cap_cents": 0,
}

# --------------------------------------------------------------------------
# Reference remarketing channels.
# --------------------------------------------------------------------------

CHANNEL_AUCTION = {
    "code": ChannelCode.AUCTION,
    "name": "National Auction",
    "fee_pct": 0.06,
    "fixed_fee_cents": 25000,
    "expected_days_to_sell": 14,
    "expected_proceeds_multiplier": 0.92,
    "recondition_required": False,
}

CHANNEL_RETAIL_LOT = {
    "code": ChannelCode.RETAIL_LOT,
    "name": "Retail Lot",
    "fee_pct": 0.03,
    "fixed_fee_cents": 60000,
    "expected_days_to_sell": 45,
    "expected_proceeds_multiplier": 1.08,
    "recondition_required": True,
}

CHANNEL_PROGRAM_REPURCHASE = {
    "code": ChannelCode.PROGRAM_REPURCHASE,
    "name": "Manufacturer Repurchase",
    "fee_pct": 0.00,
    "fixed_fee_cents": 0,
    "expected_days_to_sell": 21,
    "expected_proceeds_multiplier": 1.00,
    "recondition_required": False,
}

CHANNEL_DEALER_DIRECT = {
    "code": ChannelCode.DEALER_DIRECT,
    "name": "Dealer Direct",
    "fee_pct": 0.04,
    "fixed_fee_cents": 15000,
    "expected_days_to_sell": 30,
    "expected_proceeds_multiplier": 0.95,
    "recondition_required": False,
}

#: The capitalized cost every reference allocation buys its cars at.
CAPITALIZED_COST_CENTS = 2800000


# --------------------------------------------------------------------------
# Factories
# --------------------------------------------------------------------------


def market_payload(**overrides: Any) -> Dict[str, Any]:
    payload = dict(ATL)
    payload.update(overrides)
    return payload


def vehicle_segment_payload(**overrides: Any) -> Dict[str, Any]:
    payload = dict(MIDSIZE)
    payload.update(overrides)
    return payload


def manufacturer_program_payload(**overrides: Any) -> Dict[str, Any]:
    payload = dict(PROGRAM_GUARANTEED)
    payload.update(overrides)
    return payload


def remarketing_channel_payload(**overrides: Any) -> Dict[str, Any]:
    payload = dict(CHANNEL_AUCTION)
    payload.update(overrides)
    return payload


def depreciation_policy_payload(
    segment_id: str,
    name: str = "MID-2026",
    monthly_depreciation_pct: float = 0.015,
    mileage_depreciation_cents_per_km: int = 12,
    floor_residual_pct: float = 0.35,
    effective_from: str = "2026-01-01T00:00:00.000Z",
    supersedes_policy_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "segment_id": segment_id,
        "name": name,
        "monthly_depreciation_pct": monthly_depreciation_pct,
        "mileage_depreciation_cents_per_km": mileage_depreciation_cents_per_km,
        "floor_residual_pct": floor_residual_pct,
        "effective_from": effective_from,
    }
    if supersedes_policy_id is not None:
        payload["supersedes_policy_id"] = supersedes_policy_id
    payload.update(overrides)
    return payload


def fleet_plan_payload(
    market_id: str,
    season: str = Season.PEAK,
    plan_year: int = 2026,
    planned_unit_count: int = 10,
    revenue_per_unit_target_cents: int = 132000,
    utilization_target_pct: float = 0.80,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "market_id": market_id,
        "season": season,
        "plan_year": plan_year,
        "planned_unit_count": planned_unit_count,
        "revenue_per_unit_target_cents": revenue_per_unit_target_cents,
        "utilization_target_pct": utilization_target_pct,
    }
    payload.update(overrides)
    return payload


def purchase_allocation_payload(
    program_id: str,
    segment_id: str,
    unit_count: int,
    expected_plan_version: int,
    capitalized_cost_per_unit_cents: int = CAPITALIZED_COST_CENTS,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "program_id": program_id,
        "segment_id": segment_id,
        "unit_count": unit_count,
        "capitalized_cost_per_unit_cents": capitalized_cost_per_unit_cents,
        "expected_plan_version": expected_plan_version,
    }
    payload.update(overrides)
    return payload


def vehicle_payload(vin: str, current_market_id: str, **overrides: Any) -> Dict[str, Any]:
    """A minted car carries only a VIN and the market that will hold it."""
    payload: Dict[str, Any] = {"vin": vin, "current_market_id": current_market_id}
    payload.update(overrides)
    return payload


def vin(suffix: str) -> str:
    """A globally unique VIN of exactly sixteen characters."""
    stem = "VINTEST" + suffix.upper()
    if len(stem) > 16:
        raise ValueError("VIN suffix too long")
    return stem.ljust(16, "0")


def registration_task_payload(cost_cents: int = 14000, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"task_type": TaskType.REGISTRATION, "cost_cents": cost_cents}
    payload.update(overrides)
    return payload


def licensing_task_payload(cost_cents: int = 9000, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"task_type": TaskType.LICENSING, "cost_cents": cost_cents}
    payload.update(overrides)
    return payload


def preparation_task_payload(
    bay_code: str = "B1",
    window_start: str = "2026-01-07T08:00:00.000Z",
    window_end: str = "2026-01-07T10:00:00.000Z",
    cost_cents: int = 21000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "task_type": TaskType.PREPARATION,
        "cost_cents": cost_cents,
        "bay_code": bay_code,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def usage_payload(
    odometer_km: int,
    rented_days_delta: int = 0,
    available_days_delta: int = 0,
    revenue_cents_delta: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "odometer_km": odometer_km,
        "rented_days_delta": rented_days_delta,
        "available_days_delta": available_days_delta,
        "revenue_cents_delta": revenue_cents_delta,
    }
    payload.update(overrides)
    return payload


def redistribution_order_payload(
    vehicle_id: str,
    destination_market_id: str,
    distance_km: int = 200,
    planned_depart_at: str = "2026-03-01T00:00:00.000Z",
    planned_receive_at: str = "2026-03-05T00:00:00.000Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "vehicle_id": vehicle_id,
        "destination_market_id": destination_market_id,
        "distance_km": distance_km,
        "planned_depart_at": planned_depart_at,
        "planned_receive_at": planned_receive_at,
    }
    payload.update(overrides)
    return payload


def rejection_payload(reason: str = "sizing revisited", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"rejection_reason": reason}
    payload.update(overrides)
    return payload


def receive_payload(
    actual_transport_cost_cents: int, odometer_km: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "actual_transport_cost_cents": actual_transport_cost_cents,
        "odometer_km": odometer_km,
    }
    payload.update(overrides)
    return payload


def damage_event_payload(
    estimate_cents: int,
    damage_type: str = DamageType.COLLISION,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "damage_type": damage_type,
        "estimate_cents": estimate_cents,
    }
    payload.update(overrides)
    return payload


def revise_estimate_payload(estimate_cents: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"estimate_cents": estimate_cents}
    payload.update(overrides)
    return payload


def open_recovery_payload(recovery_source: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"recovery_source": recovery_source}
    payload.update(overrides)
    return payload


def settle_recovery_payload(recovered_cents: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"recovered_cents": recovered_cents}
    payload.update(overrides)
    return payload


def total_loss_payload(salvage_proceeds_cents: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"salvage_proceeds_cents": salvage_proceeds_cents}
    payload.update(overrides)
    return payload


def consignment_payload(
    vehicle_id: str,
    channel_id: str,
    expected_vehicle_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "vehicle_id": vehicle_id,
        "channel_id": channel_id,
        "expected_vehicle_version": expected_vehicle_version,
    }
    payload.update(overrides)
    return payload


def authorize_recondition_payload(
    recondition_authorized_cents: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"recondition_authorized_cents": recondition_authorized_cents}
    payload.update(overrides)
    return payload


def complete_recondition_payload(
    recondition_actual_cents: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"recondition_actual_cents": recondition_actual_cents}
    payload.update(overrides)
    return payload


def record_sale_payload(gross_proceeds_cents: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"gross_proceeds_cents": gross_proceeds_cents}
    payload.update(overrides)
    return payload


def clock_payload(current_utc: str) -> Dict[str, Any]:
    return {"current_utc": current_utc}
