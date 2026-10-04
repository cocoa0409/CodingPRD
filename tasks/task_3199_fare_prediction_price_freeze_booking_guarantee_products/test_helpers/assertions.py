"""Entity assertions and domain invariant checkers.

Each ``assert_{entity}`` validates a response payload against the field set and
value domains the PRD declares for that resource. The invariant checkers encode
the conservation rules that must hold after *any* operation.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)

from .constants import insurance_tier_ceiling


# ─── Shared system-managed property checks ──────────────────────────────────

def _assert_common_fields(data: dict):
    """id / created_at / updated_at / version are carried by every resource."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an integer >= 1, got {data.get('version')!r}"


def _assert_iso_or_null(data: dict, field: str):
    value = data.get(field)
    assert value is None or is_iso8601_timestamp(value), \
        f"{field} must be null or ISO 8601, got {value!r}"


def _assert_money(data: dict, field: str):
    value = data.get(field)
    assert isinstance(value, (int, float)), f"{field} must be numeric, got {value!r}"
    assert_cost_precision(float(value))


# ─── Route ──────────────────────────────────────────────────────────────────

def assert_route(data: dict):
    _assert_common_fields(data)
    assert data["posture"] in ("ACTIVE", "SURGE", "RESTRICTED", "CLOSED")
    assert isinstance(data["posture_reason_code"], str)
    assert isinstance(data["base_fare_cents"], int)
    assert isinstance(data["fare_band_cents"], list) and len(data["fare_band_cents"]) == 5
    assert data["travel_class"] in ("ECO", "PREMIUM", "BUSINESS")
    assert isinstance(data["curve_published"], bool)
    assert isinstance(data["open_freeze_count"], int)
    for field in ("war_chest_cents", "reserved_exposure_cents", "available_exposure_cents",
                  "pooled_exposure_cents", "highest_curve_price_cents"):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"
    assert data["peak_day_demand_multiplier"] >= 1.0


def assert_route_exposure_invariants(data: dict):
    """available_exposure_cents is the war chest minus reserved exposure.

    It may legitimately be negative, and is reported rather than clamped.
    """
    expected = data["war_chest_cents"] - data["reserved_exposure_cents"]
    assert data["available_exposure_cents"] == expected, (
        f"available_exposure_cents {data['available_exposure_cents']} != "
        f"war_chest_cents {data['war_chest_cents']} - "
        f"reserved_exposure_cents {data['reserved_exposure_cents']}"
    )
    assert data["reserved_exposure_cents"] >= 0


# ─── Itinerary ──────────────────────────────────────────────────────────────

def assert_itinerary(data: dict):
    _assert_common_fields(data)
    assert data["travel_status"] in ("PLANNED", "WATCHING", "BOOKED", "CANCELLED")
    assert isinstance(data["listed_fare_cents"], int)
    assert isinstance(data["last_observed_fare_cents"], int)
    assert isinstance(data["demand_curve_price_cents"], int)
    assert isinstance(data["each_day_disruption_fare_cents"], (int, float))
    assert isinstance(data["fare_tier_ceiling_cents"], (int, float))
    assert isinstance(data["observed_fares_cents"], list)
    assert isinstance(data["watch_armed"], bool)
    assert isinstance(data["guarantee_locked"], bool)
    _assert_iso_or_null(data, "booking_hold_expires_at")
    assert is_iso8601_timestamp(data["booking_date"])


# ─── PriceObservation ───────────────────────────────────────────────────────

def assert_price_observation(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["fare_cents"], int) and data["fare_cents"] >= 1
    assert isinstance(data["seats_left"], int)
    assert is_iso8601_timestamp(data["observed_at"])


# ─── DemandCurve ────────────────────────────────────────────────────────────

def assert_demand_curve(data: dict):
    _assert_common_fields(data)
    assert len(data["each_day_prices_cents"]) == 5
    assert all(p > 0 for p in data["each_day_prices_cents"])
    assert len(data["seats_left_at_each_day"]) == 5
    assert data["seats_left_at_each_day"][0] >= data["seats_left_at_each_day"][4]
    assert is_iso8601_timestamp(data["published_at"])


# ─── WatchSubscription ──────────────────────────────────────────────────────

def assert_watch_subscription(data: dict):
    _assert_common_fields(data)
    assert data["notification_status"] in (
        "ARMED", "NOTIFIED", "WAIT", "BUY_NOW", "CONFIRMED", "EXPIRED",
    )
    assert isinstance(data["notification_attempt_count"], int)
    assert isinstance(data["last_notified_fare_cents"], int)
    assert isinstance(data["cooldown_suppressed"], bool)
    assert isinstance(data["buy_now_warranty_applied"], bool)
    assert isinstance(data["locked_fare_cents"], int)
    assert is_iso8601_timestamp(data["armed_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    _assert_iso_or_null(data, "last_notified_at")
    _assert_iso_or_null(data, "cooldown_until")


# ─── PriceFreeze ────────────────────────────────────────────────────────────

def assert_price_freeze(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "HELD", "FROZEN", "CLAIM_PENDING", "CLAIMED",
                              "CONVERTED", "EXPIRED", "CANCELLED")
    assert data["deposit_integrity_flag"] in (
        "INTEGRITY_CONSISTENT", "INTEGRITY_UNDER_RECOGNIZED", "INTEGRITY_OVER_RECOGNIZED",
    )
    assert isinstance(data["migrated_manifest"], bool)
    assert 100 <= data["deposit_cents"] <= 5000
    _assert_iso_or_null(data, "freeze_date")
    _assert_iso_or_null(data, "freeze_expires_at")
    _assert_iso_or_null(data, "frozen_effective_at")
    for field in ("manifest_fare_cents", "cap_cents", "overshoot_cents", "capped_impact_cents",
                  "exposure_cents", "hedged_exposure_cents", "unhedged_exposure_cents",
                  "deposit_attributed_cents", "custody_held_cents",
                  "custody_return_pending_cents", "deposit_forfeited_cents",
                  "membership_days_elapsed", "pattern_day_count"):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"


def assert_freeze_exposure_invariants(data: dict):
    """The exposure chain's internal conservation rules."""
    assert data["capped_impact_cents"] >= 0
    assert data["overshoot_cents"] >= 0
    assert data["exposure_cents"] <= data["overshoot_cents"] + 0.001
    assert data["hedged_exposure_cents"] <= data["exposure_cents"] + 0.001
    assert data["unhedged_exposure_cents"] >= 0
    assert data["custody_held_cents"] >= 0
    assert data["custody_return_pending_cents"] >= 0


def assert_deposit_custody_invariants(data: dict):
    """The custody buckets plus the attributed slice reconstitute the deposit.

    Holds at every point of the lifecycle for a freeze with no forfeiture.
    """
    total = (data["custody_held_cents"] + data["custody_return_pending_cents"]
             + data["deposit_attributed_cents"])
    assert abs(total - data["deposit_cents"]) < 0.011, (
        f"custody_held {data['custody_held_cents']} + return_pending "
        f"{data['custody_return_pending_cents']} + attributed "
        f"{data['deposit_attributed_cents']} != deposit {data['deposit_cents']}"
    )


# ─── ProtectionProduct ──────────────────────────────────────────────────────

def assert_protection_product(data: dict):
    _assert_common_fields(data)
    assert data["product_type"] in ("CANCELLATION", "CHANGE")
    assert data["quoted_status"] in ("QUOTED", "QUOTED_FROZEN", "QUOTED_ACTIVE",
                                     "QUOTED_FROZEN_ON_UNPUBLISHED_CURVE")
    assert data["lifecycle_status"] in ("QUOTED", "ACTIVE", "CHANGE_IN_PROGRESS",
                                        "CANCELLED_PROTECTED", "REBOOKED", "TERMINATED",
                                        "EXPIRED")
    assert isinstance(data["minimum_disruption_met"], bool)
    assert isinstance(data["suspended_under_cap"], bool)
    assert isinstance(data["cancelled_by_member"], bool)
    assert isinstance(data["terminated_hard"], bool)
    assert data["bonus_days_total"] in (0, 1, 2)
    assert isinstance(data["premium_cents"], (int, float))
    assert_cost_precision(float(data["premium_cents"]))
    assert is_iso8601_timestamp(data["coverage_expires_at"])


# ─── GuaranteeClaim ─────────────────────────────────────────────────────────

def assert_guarantee_claim(data: dict):
    _assert_common_fields(data)
    assert data["claim_status"] in ("FILED", "UNDER_REVIEW", "APPROVED",
                                    "SETTLED_WITH_PURCHASE", "REJECTED", "WITHDRAWN")
    assert isinstance(data["audit_ready"], bool)
    assert isinstance(data["market_price_cents"], int)
    for field in ("overshoot_cents", "capped_impact_cents", "payout_cents",
                  "transaction_value_cents", "transaction_value_pre_cents",
                  "transaction_value_final_cents", "continuum_absorbed_cents"):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"
    assert isinstance(data["depth_ratio"], (int, float)) and data["depth_ratio"] >= 0
    assert isinstance(data["filer_user_id"], str) and data["filer_user_id"]
    assert data.get("approver_user_id") is None or isinstance(data["approver_user_id"], str)


# ─── ChangeEvent ────────────────────────────────────────────────────────────

def assert_change_event(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("OPEN", "OPTION_SELECTED", "HELD", "SETTLED", "CANCELLED")
    assert data["gap_direction"] in ("ORIGIN_DIRECTION", "DESTINATION_DIRECTION")
    assert data["day_shift"] >= 1
    assert isinstance(data["disruption_days"], int)
    assert isinstance(data["unrecovered_travel_fare_cents"], (int, float))
    assert is_iso8601_timestamp(data["old_departure_date"])
    assert is_iso8601_timestamp(data["new_departure_date"])
    _assert_iso_or_null(data, "option_hold_expires_at")


# ─── RebookingOption ────────────────────────────────────────────────────────

def assert_rebooking_option(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("OFFERED", "SELECTED", "HELD", "ACCEPTED", "SUPERSEDED",
                              "EXPIRED")
    assert data["sequence_index"] >= 1
    assert isinstance(data["option_fare_cents"], int) and data["option_fare_cents"] > 0
    assert is_iso8601_timestamp(data["departure_date"])
    _assert_iso_or_null(data, "hold_expires_at")


# ─── Payment ────────────────────────────────────────────────────────────────

def assert_payment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("AUTHORIZED", "CAPTURED", "PARTIALLY_REFUNDED", "REFUNDED",
                              "FORFEITED", "RETIRED")
    assert data["payment_kind"] in ("DEPOSIT", "MEMBERSHIP_1", "MEMBERSHIP_2", "PREMIUM",
                                    "CHANGE_FEE", "HEDGE_TOPUP")
    assert 1 <= data["amount_cents"] <= 20000
    assert isinstance(data["refundable_remaining_cents"], (int, float))
    assert data["refundable_remaining_cents"] >= 0
    assert isinstance(data["allocations"], list)
    assert isinstance(data["retired_reason"], str)
    for allocation in data["allocations"]:
        assert "target" in allocation
        assert "amount_cents" in allocation
        assert "applied_at" in allocation


# ─── HedgingPosition ────────────────────────────────────────────────────────

def assert_hedging_position(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("OPEN", "HEDGED", "SETTLED", "LAPSED")
    assert isinstance(data["hedge_price_cents"], int)
    assert isinstance(data["contract_quantity_cents"], int)
    assert isinstance(data["projected_day_cost_cents"], (int, float))
    assert isinstance(data["mark_value_cents"], (int, float)) and data["mark_value_cents"] >= 0
    assert isinstance(data["regression_reversed"], bool)
    assert isinstance(data["absorption_released_cents"], (int, float))
    assert isinstance(data["pool_binding_count"], int)
    assert is_iso8601_timestamp(data["coverage_date"])


# ─── RiskPool ───────────────────────────────────────────────────────────────

def assert_risk_pool(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("OPEN", "ABSORBING", "BOUND")
    assert isinstance(data["absorbed_regression_cents"], (int, float))
    assert isinstance(data["absorbed_regression_cents"], (int, float))
    assert isinstance(data["bound_position_count"], int)
    assert isinstance(data["available_capacity_cents"], (int, float))
    assert isinstance(data["pool_code"], str) and data["pool_code"]


# ─── DestinationOption ──────────────────────────────────────────────────────

def assert_destination_option(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("AVAILABLE", "BOUND", "TAKEN")
    assert data["direction"] in ("ORIGIN_DIRECTION", "DESTINATION_DIRECTION")
    assert isinstance(data["eligible"], bool)
    assert isinstance(data["option_fare_cents"], int) and data["option_fare_cents"] > 0
    assert is_iso8601_timestamp(data["departure_date"])
