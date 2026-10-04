"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    validate_paginated,
)

MEMBER_STATUSES = ["PENDING_CERTIFICATION", "CERTIFIED", "PROBATION", "SUSPENDED"]
LOAD_STATUSES = ["POSTED", "BIDDING", "AWARDED", "IN_TRANSIT", "DELIVERED", "CANCELLED"]
SAFETY_STATUSES = ["CLEAR", "HELD", "RECALLED"]
BID_STATUSES = ["SUBMITTED", "WITHDRAWN", "AWARDED", "REJECTED"]
AGREEMENT_STATUSES = ["DRAFT", "ACTIVE", "SUSPENDED", "CLOSED"]
RECALL_STATUSES = ["OPEN", "TRACING", "RESOLVED", "REOPENED"]
HOLD_STATUSES = ["ACTIVE", "RELEASED", "DESTROYED"]
AUDIT_STATUSES = ["IN_PROGRESS", "PASSED", "FAILED"]
PROGRAM_STATUSES = ["PENDING", "ACTIVE", "SUSPENDED"]
PICKUP_STATUSES = ["SCHEDULED", "COMPLETED", "MISSED"]
LEDGER_ENTRY_TYPES = [
    "GRANT", "BID_HOLD", "BID_RELEASE", "AWARD_DEBIT",
    "AWARD_REFUND", "ACTIVITY_BONUS", "RECALL_REFUND",
]


def _assert_common(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}.created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{label}.updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{label}.version must be an integer starting at 1"


def assert_member(data: dict):
    _assert_common(data, "MemberFoodBank")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["food_insecure_population"], int) and data["food_insecure_population"] >= 0
    assert isinstance(data["storage_capacity_lbs"], int) and data["storage_capacity_lbs"] > 0
    assert isinstance(data["refrigerated_capacity_lbs"], int)
    assert data["refrigerated_capacity_lbs"] <= data["storage_capacity_lbs"]
    assert data["transport_ability"] in ["NONE", "LOCAL", "REGIONAL", "NATIONAL"]
    assert data["certification_status"] in MEMBER_STATUSES
    assert isinstance(data["share_balance"], int) and data["share_balance"] >= 0
    assert isinstance(data["share_reserved"], int) and data["share_reserved"] >= 0
    assert isinstance(data["audit_score"], int) and data["audit_score"] >= 0
    assert isinstance(data["active_bid_count"], int) and data["active_bid_count"] >= 0


def assert_donor_agreement(data: dict):
    _assert_common(data, "DonorAgreement")
    assert data["donor_type"] in ["MANUFACTURER", "RETAILER", "DISTRIBUTOR"]
    assert data["product_category"] in [
        "DRY_GOODS", "PRODUCE", "DAIRY", "FROZEN_PROTEIN", "BAKERY"
    ]
    assert isinstance(data["committed_lbs"], int) and data["committed_lbs"] > 0
    assert isinstance(data["meal_equivalency_factor"], (int, float))
    assert data["meal_equivalency_factor"] > 0
    assert data["status"] in AGREEMENT_STATUSES
    assert isinstance(data["freight_subsidy_pool_cents"], int)
    assert isinstance(data["freight_subsidy_used_cents"], int)
    assert data["freight_subsidy_used_cents"] <= data["freight_subsidy_pool_cents"]


def assert_load(data: dict):
    _assert_common(data, "DonatedLoad")
    assert data["storage_type"] in ["DRY", "REFRIGERATED", "FROZEN"]
    assert isinstance(data["weight_lbs"], int) and data["weight_lbs"] > 0
    assert isinstance(data["origin_zip"], str) and len(data["origin_zip"]) == 5
    assert data["destination_region"] in [
        "NORTHEAST", "SOUTHEAST", "MIDWEST", "SOUTHWEST", "WEST"
    ]
    assert isinstance(data["distance_miles"], int) and data["distance_miles"] > 0
    assert data["status"] in LOAD_STATUSES
    assert data["safety_status"] in SAFETY_STATUSES
    assert data["freight_decision"] in ["PENDING", "COVERED", "DECLINED"]
    assert isinstance(data["delivered_lbs"], int) and data["delivered_lbs"] >= 0
    assert isinstance(data["meal_equivalent"], int) and data["meal_equivalent"] >= 0


def assert_bid(data: dict):
    _assert_common(data, "LoadBid")
    assert is_valid_uuid(data["load_id"])
    assert is_valid_uuid(data["member_id"])
    assert isinstance(data["shares_offered"], int) and data["shares_offered"] > 0
    assert isinstance(data["preference_rank"], int) and data["preference_rank"] >= 1
    assert isinstance(data["can_self_transport"], bool)
    assert data["bid_status"] in BID_STATUSES
    assert isinstance(data["submitted_round"], int) and data["submitted_round"] >= 1


def assert_ledger_entry(data: dict):
    """ShareLedgerEntry is append-only: id and created_at only, no version."""
    assert is_valid_uuid(data.get("id", "")), "ShareLedgerEntry.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "ShareLedgerEntry.created_at must be an ISO 8601 UTC timestamp"
    assert "updated_at" not in data, "ShareLedgerEntry must not carry updated_at"
    assert "version" not in data, "ShareLedgerEntry must not carry version"
    assert is_valid_uuid(data["member_id"])
    assert data["entry_type"] in LEDGER_ENTRY_TYPES
    assert isinstance(data["amount"], int)
    assert isinstance(data["balance_after"], int)
    assert isinstance(data["epoch"], str)


def assert_recall(data: dict):
    _assert_common(data, "ProductRecall")
    assert is_valid_uuid(data["donor_agreement_id"])
    assert data["product_category"] in [
        "DRY_GOODS", "PRODUCE", "DAIRY", "FROZEN_PROTEIN", "BAKERY"
    ]
    assert isinstance(data["affected_lbs"], int) and data["affected_lbs"] >= 0
    assert data["recall_status"] in RECALL_STATUSES
    assert isinstance(data["traced_load_count"], int) and data["traced_load_count"] >= 0
    assert isinstance(data["held_lbs"], int) and data["held_lbs"] >= 0
    assert is_iso8601_timestamp(data["opened_at"])


def assert_recall_hold(data: dict):
    """RecallHold is append-only: id and created_at only, no version."""
    assert is_valid_uuid(data.get("id", "")), "RecallHold.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "RecallHold.created_at must be an ISO 8601 UTC timestamp"
    assert "updated_at" not in data, "RecallHold must not carry updated_at"
    assert "version" not in data, "RecallHold must not carry version"
    assert is_valid_uuid(data["recall_id"])
    assert is_valid_uuid(data["load_id"])
    assert data["hold_status"] in HOLD_STATUSES


def assert_audit(data: dict):
    _assert_common(data, "MemberAudit")
    assert is_valid_uuid(data["member_id"])
    assert data["audit_type"] in ["STORAGE", "DISTRIBUTION", "REPORTING", "COMPREHENSIVE"]
    for field in ("storage_score", "distribution_score", "reporting_score"):
        assert isinstance(data[field], int) and 0 <= data[field] <= 100
    assert isinstance(data["weighted_score"], (int, float))
    assert 0 <= data["weighted_score"] <= 100
    assert data["audit_status"] in AUDIT_STATUSES
    assert isinstance(data["opened_by_user_id"], str)


def assert_store_program(data: dict):
    _assert_common(data, "StoreDonationProgram")
    assert is_valid_uuid(data["member_id"])
    assert data["pickup_frequency"] in ["DAILY", "WEEKLY", "BIWEEKLY"]
    assert isinstance(data["expected_weekly_lbs"], int) and data["expected_weekly_lbs"] >= 0
    assert data["program_status"] in PROGRAM_STATUSES


def assert_pickup(data: dict):
    _assert_common(data, "StorePickup")
    assert is_valid_uuid(data["program_id"])
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["pickup_status"] in PICKUP_STATUSES
    assert isinstance(data["collected_lbs"], int) and data["collected_lbs"] >= 0
    assert isinstance(data["meal_equivalent"], int) and data["meal_equivalent"] >= 0


# ── Domain invariant checkers ────────────────────────────────────────

def assert_ledger_reconciles(api, member: dict, headers) -> int:
    """A member's share_balance must equal the sum of its ledger amounts."""
    data, meta = validate_paginated(
        api.list_member_ledger(member["id"], headers, params={"limit": 100})
    )
    assert meta["total_count"] == len(data), (
        f"ledger listing truncated: total_count {meta['total_count']} vs {len(data)} rows"
    )
    total = sum(row["amount"] for row in data)
    assert total == member["share_balance"], (
        f"ledger sum {total} != share_balance {member['share_balance']}"
    )
    return total


def assert_hold_supersession(load_before: str, load_after: str):
    """A released hold returns a load to CLEAR; a RECALLED load never leaves."""
    assert load_after in SAFETY_STATUSES
    if load_before == "RECALLED":
        assert load_after == "RECALLED", "RECALLED is terminal and is never left"
