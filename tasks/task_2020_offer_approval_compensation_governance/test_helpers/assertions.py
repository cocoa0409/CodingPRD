"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

ROLE_LEVELS = ["L3", "L4", "L5", "L6", "L7"]
GEO_TIERS = ["T1", "T2", "T3"]
REQUISITION_STATUSES = ["DRAFT", "BUDGET_REVIEW", "RANGE_APPROVAL", "OPEN", "PAUSED", "CLOSED", "CANCELLED"]
CANDIDATE_STATUSES = ["PROSPECT", "IN_PROCESS", "HIRED", "ARCHIVED"]
OFFER_STATUSES = [
    "DRAFT", "PENDING_APPROVAL", "RETURNED", "APPROVED", "LETTER_GENERATED",
    "EXTENDED", "COUNTERED", "ACCEPTED", "HIRED", "DECLINED", "EXPIRED",
    "RESCINDED", "WITHDRAWN",
]
STEP_STATUSES = ["WAITING", "ACTIONABLE", "APPROVED", "REJECTED", "SUPERSEDED"]
ROUND_STATUSES = ["PROPOSED", "ACCEPTED", "REJECTED", "WITHDRAWN"]
PERK_STATUSES = ["DRAFT", "LOCKED", "APPROVED", "ACTIVE", "VOIDED"]
CHECK_STATUSES = ["INITIATED", "IN_PROGRESS", "CLEARED", "FLAGGED", "FAILED", "WAIVED", "CANCELLED"]
LETTER_STATUSES = ["GENERATED", "SUPERSEDED"]
GRANT_STATUSES = ["ACTIVE", "REVOKED", "EXPIRED"]
BANDS = ["IN_BAND", "BELOW_MIN", "ABOVE_BAND", "EXCEPTION"]
POSTURES = ["NOT_STARTED", "PENDING", "CLEARED", "FAILED"]
EVENT_TYPES = [
    "OFFER_CREATED", "TERMS_REVISED", "SUBMITTED", "STEP_APPROVED", "STEP_REJECTED",
    "STEP_SUPERSEDED", "APPROVED", "RETURNED", "LETTER_GENERATED", "LETTER_SUPERSEDED",
    "EXTENDED", "COUNTER_RECORDED", "COUNTER_ACCEPTED", "COUNTER_REJECTED",
    "ROUND_WITHDRAWN", "ACCEPTED", "DECLINED", "EXPIRED", "RESCINDED", "WITHDRAWN",
    "HIRED", "CHECK_INITIATED", "CHECK_TRANSITIONED", "CHECK_WAIVED", "CHECK_CANCELLED",
    "PERK_ADDED", "PERK_VOIDED",
]


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive integer"


def assert_requisition(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["department"], str) and data["department"]
    assert data["role_level"] in ROLE_LEVELS
    assert data["geo_tier"] in GEO_TIERS
    assert isinstance(data["hiring_manager_id"], str) and data["hiring_manager_id"]
    for f in ("annual_budget_cents", "salary_min_cents", "salary_mid_cents", "salary_max_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"
    assert isinstance(data["headcount_authorized"], int) and data["headcount_authorized"] >= 1
    assert isinstance(data["headcount_filled"], int) and data["headcount_filled"] >= 0
    assert isinstance(data["committed_budget_cents"], int) and data["committed_budget_cents"] >= 0
    assert data["status"] in REQUISITION_STATUSES
    assert data.get("close_reason") in (None, "FILLED")


def assert_candidate(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["status"] in CANDIDATE_STATUSES


def assert_snapshot(data: dict):
    _assert_common_fields(data)
    assert data["role_level"] in ROLE_LEVELS
    assert data["geo_tier"] in GEO_TIERS
    assert isinstance(data["base_cents"], int) and data["base_cents"] > 0


def assert_policy(data: dict):
    _assert_common_fields(data)
    assert data["min_band_severity"] in ["BELOW_MIN", "ABOVE_BAND", "EXCEPTION"]
    assert data["required_role"] in ["CompAnalyst", "DepartmentDirector", "VPPeople"]
    assert isinstance(data["chain_position"], int) and data["chain_position"] >= 1
    assert data["status"] in ["ACTIVE", "INACTIVE"]


def assert_offer(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("requisition_id", "")), "requisition_id must be a UUID"
    assert is_valid_uuid(data.get("candidate_id", "")), "candidate_id must be a UUID"
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]
    assert isinstance(data["base_cents"], int) and data["base_cents"] > 0
    assert isinstance(data["bonus_target_cents"], int)
    assert isinstance(data["total_cash_cents"], int)
    assert isinstance(data["cash_only_annual_cost_cents"], int)
    assert isinstance(data["fully_loaded_annual_cost_cents"], int)
    assert data["band"] in BANDS
    assert data["clearance_posture"] in POSTURES
    assert isinstance(data["round_count"], int) and data["round_count"] >= 0
    assert data["status"] in OFFER_STATUSES
    assert isinstance(data["equity_compa_risk_flag"], bool)
    assert isinstance(data["equity_percentile_risk_flag"], bool)


def assert_approval_step(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sequence"], int) and data["sequence"] >= 0
    assert data["required_role"] in ["HiringManager", "CompAnalyst", "DepartmentDirector", "VPPeople"]
    assert data["status"] in STEP_STATUSES


def assert_negotiation_round(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1
    assert isinstance(data["proposed_base_cents"], int) and data["proposed_base_cents"] > 0
    assert data["status"] in ROUND_STATUSES


def assert_perk(data: dict):
    _assert_common_fields(data)
    assert data["kind"] in ["SIGN_ON", "RELOCATION"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["clawback_months"], int) and data["clawback_months"] >= 1
    assert data["clawback_variant"] in ["FULL_CLIFF", "PRORATED_MONTHLY"]
    assert data["status"] in PERK_STATUSES


def assert_clearance_check(data: dict):
    _assert_common_fields(data)
    assert data["kind"] in ["BACKGROUND", "REFERENCE"]
    assert data["status"] in CHECK_STATUSES


def assert_offer_letter(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1
    assert isinstance(data["pinned_offer_version"], int) and data["pinned_offer_version"] >= 1
    assert data["status"] in LETTER_STATUSES


def assert_offer_event(data: dict):
    # Append-only: id + created_at only — no updated_at, no version.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "OfferEvent must not expose updated_at"
    assert "version" not in data, "OfferEvent must not expose version"
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1
    assert data["event_type"] in EVENT_TYPES
    assert isinstance(data["actor_user_id"], str) and data["actor_user_id"]


def assert_delegation_grant(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["grantor_user_id"], str) and data["grantor_user_id"]
    assert isinstance(data["delegate_user_id"], str) and data["delegate_user_id"]
    assert data["scope_role"] in ["CompAnalyst", "DepartmentDirector", "VPPeople"]
    assert data["status"] in GRANT_STATUSES


def event_types(events: list) -> list:
    """Extract the ordered event_type list from an events data list."""
    return [e["event_type"] for e in events]
