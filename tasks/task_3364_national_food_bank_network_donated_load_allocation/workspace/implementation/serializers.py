"""Resource -> JSON shaping (PRD 2.4: common fields; ledger/holds append-only)."""

import clock
from decimal import Decimal

COMMON = ("id", "created_at", "updated_at", "version")


def _value(field, value):
    if field in ("created_at", "updated_at", "opened_at", "delivery_window_start",
                 "delivery_window_end", "scheduled_date", "window_start", "window_end"):
        return clock.fmt(value)
    if isinstance(value, Decimal):
        return float(value)
    return value


def _shape(row, fields, common=True):
    # id and created_at are universal (PRD 2.4); updated_at and version belong
    # only to the first-class resources — the ledger and holds are append-only.
    out = {
        "id": row.get("id"),
        "created_at": _value("created_at", row.get("created_at")),
    }
    if common:
        out["updated_at"] = _value("updated_at", row.get("updated_at"))
        out["version"] = row.get("version")
    for field in fields:
        out[field] = _value(field, row.get(field))
    return out


MEMBER_FIELDS = (
    "name", "state_code", "food_insecure_population", "storage_capacity_lbs",
    "refrigerated_capacity_lbs", "transport_ability", "certification_status",
    "share_balance", "share_reserved", "audit_score", "last_grant_epoch",
    "active_bid_count",
)

AGREEMENT_FIELDS = (
    "donor_name", "donor_type", "product_category", "committed_lbs",
    "meal_equivalency_factor", "status", "freight_subsidy_pool_cents",
    "freight_subsidy_used_cents",
)

LOAD_FIELDS = (
    "donor_agreement_id", "product_category", "storage_type", "weight_lbs",
    "lot_code", "origin_zip", "destination_region", "distance_miles", "status",
    "safety_status", "awarded_bid_id", "awarded_member_id",
    "freight_estimate_cents", "freight_subsidy_cents", "member_freight_due_cents",
    "freight_decision", "delivery_window_start", "delivery_window_end",
    "delivered_lbs", "meal_equivalent",
)

BID_FIELDS = (
    "load_id", "member_id", "shares_offered", "preference_rank",
    "can_self_transport", "bid_status", "rejection_reason", "submitted_round",
)

LEDGER_FIELDS = ("member_id", "entry_type", "amount", "balance_after", "epoch", "reference_id")

RECALL_FIELDS = (
    "donor_agreement_id", "lot_code", "product_category", "affected_lbs",
    "recall_status", "traced_load_count", "held_lbs", "opened_at",
)

HOLD_FIELDS = ("recall_id", "load_id", "hold_status", "hold_reason")

AUDIT_FIELDS = (
    "member_id", "audit_type", "storage_score", "distribution_score",
    "reporting_score", "weighted_score", "opened_by_user_id", "audit_status",
)

PROGRAM_FIELDS = (
    "member_id", "store_name", "store_chain", "pickup_frequency",
    "expected_weekly_lbs", "program_status",
)

PICKUP_FIELDS = (
    "program_id", "scheduled_date", "window_start", "window_end",
    "pickup_status", "collected_lbs", "meal_equivalent",
)


def member(row):
    return _shape(row, MEMBER_FIELDS)


def agreement(row):
    return _shape(row, AGREEMENT_FIELDS)


def load(row):
    return _shape(row, LOAD_FIELDS)


def bid(row):
    return _shape(row, BID_FIELDS)


def ledger_entry(row):
    return _shape(row, LEDGER_FIELDS, common=False)


def recall(row):
    return _shape(row, RECALL_FIELDS)


def hold(row):
    return _shape(row, HOLD_FIELDS, common=False)


def audit(row):
    return _shape(row, AUDIT_FIELDS)


def program(row):
    return _shape(row, PROGRAM_FIELDS)


def pickup(row):
    return _shape(row, PICKUP_FIELDS)
