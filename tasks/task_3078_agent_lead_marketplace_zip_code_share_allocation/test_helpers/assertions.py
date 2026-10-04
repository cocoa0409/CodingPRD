"""Entity assertions and domain invariant checkers (PRD §2.10, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

COMMON_STATUSES = {
    "market_status": ["OPEN", "SUSPENDED"],
    "brokerage_status": ["ACTIVE", "SUSPENDED"],
    "agent_status": ["ACTIVE", "SUSPENDED", "DEACTIVATED"],
    "performance_tier": ["UNRATED", "HIGH", "STANDARD", "LOW", "INELIGIBLE"],
    "team_status": ["ACTIVE", "DISSOLVED"],
    "membership_status": ["ACTIVE", "REMOVED"],
    "order_status": [
        "PENDING_PAYMENT", "ACTIVE", "PAUSED", "COMPLETED", "CANCELLED", "PAYMENT_FAILED",
    ],
    "payment_status": ["SUCCEEDED", "DECLINED"],
    "lead_status": [
        "NEW", "ROUTED", "UNASSIGNED", "ASSIGNED", "LIVE_CONNECTED",
        "CLOSED_CONVERTED", "CLOSED_LOST", "REJECTED_DUPLICATE",
    ],
    "assignment_status": ["OFFERED", "ACCEPTED", "EXPIRED", "CANCELLED"],
    "connection_status": [
        "REQUESTED", "BRIDGING", "COMPLETED", "NO_ANSWER", "DROPPED", "REJECTED_DUPLICATE",
    ],
    "recording_status": ["STORED", "PURGED"],
    "claim_status": ["SUBMITTED", "APPROVED", "REJECTED"],
    "listing_status": ["PENDING_REVIEW", "ACTIVE", "REJECTED", "WITHDRAWN"],
    "dispute_status": ["OPEN", "RESOLVED", "REJECTED"],
}


def _assert_common_fields(data, label):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an int >= 1"
    )


def _assert_append_only_fields(data, label):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{label} must not carry updated_at (PRD §2.10)"
    assert "version" not in data, f"{label} must not carry version (PRD §2.10)"


def assert_market(data: dict):
    _assert_common_fields(data, "Market")
    assert isinstance(data["zip_code"], str) and len(data["zip_code"]) == 5
    assert data["zip_code"].isdigit(), "zip_code must be exactly 5 digits"
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["participation_agreement"] in ["IDX_FULL", "IDX_LIMITED", "NON_PARTICIPATING"]
    assert data["market_status"] in COMMON_STATUSES["market_status"]
    assert isinstance(data["base_lead_price_cents"], int) and data["base_lead_price_cents"] > 0
    assert isinstance(data["allocated_bps"], int)
    assert isinstance(data["available_bps"], int)


def assert_brokerage(data: dict):
    _assert_common_fields(data, "Brokerage")
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["primary_state"], str) and len(data["primary_state"]) == 2
    assert data["brokerage_status"] in COMMON_STATUSES["brokerage_status"]


def assert_agent(data: dict):
    _assert_common_fields(data, "Agent")
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["license_number"], str) and len(data["license_number"]) > 0
    assert isinstance(data["license_state"], str) and len(data["license_state"]) == 2
    assert isinstance(data["brokerage_id"], str)
    assert data["agent_status"] in COMMON_STATUSES["agent_status"]
    assert data["performance_tier"] in COMMON_STATUSES["performance_tier"]
    for counter in (
        "rolling_score", "official_score", "offers_received", "offers_accepted",
        "offers_expired", "response_seconds_sum", "leads_converted",
        "leads_closed_lost", "connections_missed", "rating_sum", "rating_count",
    ):
        assert isinstance(data[counter], int), f"Agent.{counter} must be an int"
    assert 0 <= data["rolling_score"] <= 100, "rolling_score must be in 0..100 (PRD §2.11)"
    assert 0 <= data["official_score"] <= 100, "official_score must be in 0..100 (PRD §2.11)"


def assert_team_account(data: dict):
    _assert_common_fields(data, "TeamAccount")
    assert isinstance(data["team_name"], str) and len(data["team_name"]) > 0
    assert isinstance(data["lead_agent_id"], str)
    assert isinstance(data["market_id"], str)
    assert data["distribution_mode"] in ["WEIGHTED_DEFICIT", "MANUAL"]
    assert data["team_status"] in COMMON_STATUSES["team_status"]


def assert_team_membership(data: dict):
    _assert_common_fields(data, "TeamMembership")
    assert isinstance(data["team_id"], str)
    assert isinstance(data["agent_id"], str)
    assert isinstance(data["allocation_weight"], int) and data["allocation_weight"] >= 1
    assert data["membership_status"] in COMMON_STATUSES["membership_status"]
    assert isinstance(data["leads_assigned"], int)
    assert isinstance(data["allocated_charge_cents"], int)


def assert_share_order(data: dict):
    _assert_common_fields(data, "ShareOrder")
    assert isinstance(data["market_id"], str)
    assert isinstance(data["buyer_agent_id"], str)
    assert isinstance(data["share_bps"], int) and 1 <= data["share_bps"] <= 10000
    assert isinstance(data["duration_days"], int) and 1 <= data["duration_days"] <= 90
    assert data["order_status"] in COMMON_STATUSES["order_status"]
    for money in ("unit_price_cents", "deposit_cents", "paid_cents", "charged_cents", "credits_cents"):
        assert isinstance(data[money], int), f"ShareOrder.{money} must be integer cents (PRD §2.11)"
    assert data["tier"] in (1, 2, 3)
    assert isinstance(data["leads_received"], int)
    assert isinstance(data["leads_charged"], int)
    assert isinstance(data["leads_credited"], int)


def assert_payment(data: dict):
    _assert_append_only_fields(data, "Payment")
    assert isinstance(data["share_order_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["outcome"] in ["SUCCEEDED", "DECLINED"]
    assert data["payment_status"] in COMMON_STATUSES["payment_status"]


def assert_lead(data: dict):
    _assert_common_fields(data, "Lead")
    assert isinstance(data["market_id"], str)
    assert isinstance(data["consumer_key"], str) and len(data["consumer_key"]) > 0
    assert data["lead_status"] in COMMON_STATUSES["lead_status"]
    assert isinstance(data["routing_attempts"], int)


def assert_lead_assignment(data: dict):
    _assert_common_fields(data, "LeadAssignment")
    assert isinstance(data["lead_id"], str)
    assert data["assignment_status"] in COMMON_STATUSES["assignment_status"]
    assert isinstance(data["candidate_agent_ids"], list)
    assert len(data["candidate_agent_ids"]) <= 3, "at most 3 candidates per offer (PRD §3.4)"
    assert is_iso8601_timestamp(data.get("offered_at", ""))
    assert is_iso8601_timestamp(data.get("expires_at", ""))


def assert_live_connection(data: dict):
    _assert_common_fields(data, "LiveConnection")
    assert isinstance(data["lead_id"], str)
    assert isinstance(data["consumer_key"], str) and len(data["consumer_key"]) > 0
    assert data["connection_status"] in COMMON_STATUSES["connection_status"]


def assert_call_recording(data: dict):
    _assert_append_only_fields(data, "CallRecording")
    assert isinstance(data["live_connection_id"], str)
    assert isinstance(data["duration_seconds"], int) and data["duration_seconds"] >= 1
    assert isinstance(data["consent_given"], bool)
    assert data["recording_status"] in COMMON_STATUSES["recording_status"]


def assert_rating(data: dict):
    _assert_append_only_fields(data, "Rating")
    assert isinstance(data["lead_id"], str)
    assert isinstance(data["score"], int) and 1 <= data["score"] <= 5


def assert_credit_claim(data: dict):
    _assert_common_fields(data, "CreditClaim")
    assert isinstance(data["lead_id"], str)
    assert data["claim_type"] in ["INVALID", "DUPLICATE"]
    assert isinstance(data["reason"], str)
    assert data["claim_status"] in COMMON_STATUSES["claim_status"]
    assert isinstance(data["credit_cents"], int)


def assert_listing(data: dict):
    _assert_common_fields(data, "Listing")
    assert isinstance(data["external_ref"], str) and len(data["external_ref"]) > 0
    assert isinstance(data["market_id"], str)
    assert data["source_feed"] in ["MLS", "BROKER_DIRECT"]
    assert isinstance(data["brokerage_id"], str)
    assert isinstance(data["listing_agent_id"], str)
    assert data["listing_status"] in COMMON_STATUSES["listing_status"]


def assert_dispute(data: dict):
    _assert_common_fields(data, "Dispute")
    assert data["dispute_type"] in ["LISTING_DISPLAY", "LEAD_ATTRIBUTION"]
    assert isinstance(data["brokerage_id"], str)
    assert isinstance(data["evidence"], str)
    assert data["dispute_status"] in COMMON_STATUSES["dispute_status"]


def assert_performance_snapshot(data: dict):
    _assert_append_only_fields(data, "PerformanceSnapshot")
    assert isinstance(data["agent_id"], str)
    assert isinstance(data["ops_run_seq"], int) and data["ops_run_seq"] >= 1
    assert is_iso8601_timestamp(data.get("window_end_at", ""))
    assert isinstance(data["windowed_score"], int)
    assert 0 <= data["windowed_score"] <= 100, "windowed_score must be in 0..100 (PRD §2.11)"


def assert_ops_run(data: dict):
    _assert_append_only_fields(data, "OpsRun")
    assert isinstance(data["seq"], int) and data["seq"] >= 1
    assert is_iso8601_timestamp(data.get("run_at", ""))
    assert isinstance(data["sweep_counts"], dict)


def assert_market_share_conservation(market: dict):
    """Domain invariant: allocated_bps + available_bps == 10000 (PRD §2.5)."""
    total = market["allocated_bps"] + market["available_bps"]
    assert total == 10000, (
        f"share conservation violated: allocated {market['allocated_bps']} + "
        f"available {market['available_bps']} == {total} != 10000"
    )
    assert 0 <= market["allocated_bps"] <= 10000
    assert 0 <= market["available_bps"] <= 10000
