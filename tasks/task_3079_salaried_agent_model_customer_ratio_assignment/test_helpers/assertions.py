"""Entity assertions and domain invariant checkers.

These helpers assert only structural facts the PRD states outright: identifier
shape, timestamp shape, the declared enumerated bands and the conservation
identities. They deliberately avoid asserting any field the PRD leaves optional.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data["id"]), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data["created_at"]), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data["updated_at"]), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data["version"], int) and data["version"] >= 1, \
        f"version must be an integer >= 1, got {data.get('version')!r}"


def assert_region(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["service_area_codes"], list) and data["service_area_codes"]
    assert 0 < data["traditional_commission_pct"] <= 1
    assert data["target_client_ratio"] > 0
    assert data["occupancy_band"] in ("UNDER_TARGET", "NEAR_TARGET", "OVER_TARGET")
    assert isinstance(data["agent_count"], int)
    assert isinstance(data["clients_in_pipeline"], int)
    assert isinstance(data["referral_count"], int)
    assert isinstance(data["open_referral_count"], int)


def assert_agent(data: dict):
    _assert_common_fields(data)
    assert data["agent_kind"] in ("LEAD", "ASSOCIATE")
    assert data["status"] in ("ACTIVE", "AT_CAPACITY", "ON_LEAVE")
    assert isinstance(data["base_salary_cents"], int) and data["base_salary_cents"] > 0
    assert isinstance(data["benefits_cents"], int) and data["benefits_cents"] >= 0
    assert isinstance(data["expense_allowance_cents"], int) and data["expense_allowance_cents"] >= 0
    assert isinstance(data["bonus_cents"], int) and data["bonus_cents"] >= 0
    assert isinstance(data["referral_fee_bps"], int) and 0 <= data["referral_fee_bps"] <= 2500


def assert_open_client_count(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["active_client_count"], int) and data["active_client_count"] >= 0
    assert data["ratio_state"] in ("UNDER_TARGET", "ON_TARGET", "OVER_TARGET")


def assert_lead_capacity(data: dict):
    _assert_common_fields(data)
    assert data["current_state"] in ("OPEN", "AT_CAPACITY", "OVER_TARGET")
    assert isinstance(data["tours_in_week"], int)
    assert isinstance(data["associate_capacity_used"], int)


def assert_client(data: dict):
    _assert_common_fields(data)
    assert data["need_kind"] in ("BUY", "SELL")
    assert data["status"] in ("UNASSIGNED", "ASSIGNED", "IN_TRANSACTION", "CLOSED", "REFERRED")
    assert data["assignment_mode"] in ("ASSIGNED_DIRECT", "REFERRED_PARTNER", "UNASSIGNED")


def assert_transaction(data: dict):
    _assert_common_fields(data)
    assert data["coordination_status"] in ("UNASSIGNED", "ASSIGNED", "REVIEW", "CLOSED", "CANCELLED")


def assert_listing_agreement(data: dict):
    _assert_common_fields(data)
    assert data["service_tier"] in ("FULL_SERVICE", "LIMITED_SERVICE", "MLS_ONLY")
    assert data["status"] in ("DRAFT", "ACTIVE", "UNDER_CONTRACT", "CLOSED", "WITHDRAWN")
    assert isinstance(data["gross_listing_fee_cents"], int)
    assert isinstance(data["traditional_listing_fee_cents"], int)
    assert isinstance(data["savings_amount_cents"], int)


def assert_tour(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "ACCESS_PENDING", "CONFIRMED", "COMPLETED", "CANCELLED_NO_SHOW", "CANCELLED",
    )
    assert is_iso8601_timestamp(data["scheduled_at"])


def assert_survey(data: dict):
    _assert_common_fields(data)
    assert data["response_status"] in ("DISPATCHED", "RESPONDED", "EXPIRED_DISPATCH")
    assert isinstance(data["bonus_eligible"], bool)


def assert_agent_referral(data: dict):
    _assert_common_fields(data)
    assert data["settlement_status"] in ("PENDING", "COMPUTED", "SETTLED")
    assert data["split_policy"] in ("SPLIT_25_PARTNER", "SPLIT_50_PARTNER")
    assert 0 < data["referral_fee_bps"] <= 2500


def assert_activity_audit(data: dict):
    """Append-only row: id and created_at only — never updated_at or version."""
    assert is_valid_uuid(data["id"]), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data["created_at"]), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert "updated_at" not in data, "ActivityAudit is append-only and carries no updated_at"
    assert "version" not in data, "ActivityAudit is append-only and carries no version"
    assert data["entity_type"] in (
        "Transaction", "OpenClientCount", "ListingAgreement", "AgentReferral",
    )
    assert data["kind"] in (
        "TRANSACTION_CREATED", "TRANSACTION_STATUS_CHANGED",
        "CLIENT_CAPACITY_RELEASED", "SERVICE_COMMITMENT_BREACH",
    )


def assert_referral_split_conserves(referral: dict):
    """The referral split conserves exactly: partner + house == fee."""
    assert referral["partner_cents"] + referral["house_cents"] == referral["referral_fee_cents"], (
        f"conservation violated: {referral['partner_cents']} + {referral['house_cents']} "
        f"!= {referral['referral_fee_cents']}"
    )


def assert_salary_commitment_equals_components(agent: dict):
    """salary_commitment_cents carries base + bonus + benefits + expense."""
    expected = (
        agent["base_salary_cents"]
        + agent["bonus_cents"]
        + agent["benefits_cents"]
        + agent["expense_allowance_cents"]
    )
    assert agent["salary_commitment_cents"] == expected, (
        f"salary_commitment_cents {agent['salary_commitment_cents']} != components sum {expected}"
    )


def assert_final_listing_fee_never_negative(listing: dict):
    """The final fee is the gross fee less a deduction that can never exceed it."""
    assert listing["final_listing_fee_cents"] >= 0
    assert listing["final_listing_fee_cents"] <= listing["gross_listing_fee_cents"]