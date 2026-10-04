"""
Entity assertions and domain invariant checkers for the Micro-Task Marketplace.

Each ``assert_<entity>`` validates one resource's response shape against the
contract; the ``*_invariants`` helpers encode the platform's conservation and
monotonicity rules that must hold after any operation.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


STANDARD_FIELDS = ("created_at", "updated_at")


def _assert_standard_fields(data: dict):
    """Resources in the standard field set carry id + both timestamps + version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


# ─── Entity assertions ───────────────────────────────────────────────────────

def assert_requester(data: dict):
    _assert_standard_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["prepaid_balance_cents"], int)
    assert isinstance(data["escrowed_cents"], int)
    assert isinstance(data["lifetime_spent_cents"], int)
    assert isinstance(data["approved_count"], int)
    assert isinstance(data["rejected_count"], int)
    assert isinstance(data["lifetime_rejection_rate_pct"], int)
    assert isinstance(data["abuse_score"], int)
    assert isinstance(data["task_abuse_flag"], bool)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "PENDING_REVIEW")
    assert data["suspension_reason"] in (None, "NONE", "ABUSE_AUTO", "ADMIN_MANUAL")


def assert_worker(data: dict):
    _assert_standard_fields(data)
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0
    assert data["country"] in ("US", "IN", "PH", "BR")
    assert isinstance(data["approval_rate_pct"], int)
    assert 0 <= data["approval_rate_pct"] <= 100
    for counter in ("approved_count", "rejected_count", "returned_count", "expired_count"):
        assert isinstance(data[counter], int)
    assert isinstance(data["total_earned_cents"], int)
    assert isinstance(data["withdrawable_cents"], int)
    assert isinstance(data["identity_verified"], bool)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_worker_qualification(data: dict):
    _assert_standard_fields(data)
    assert is_valid_uuid(data["worker_id"])
    assert is_valid_uuid(data["qualification_type_id"])
    assert isinstance(data["score"], int)
    assert data["source"] in ("CASCADE", "EXAM")
    assert data["status"] in ("ACTIVE", "REVOKED")


def assert_qualification_type(data: dict):
    _assert_standard_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["kind"] in ("SYSTEM", "REQUESTER")
    assert isinstance(data["exam_available"], bool)
    assert isinstance(data["auto_assign_threshold_pct"], int)
    assert 0 <= data["auto_assign_threshold_pct"] <= 100
    assert isinstance(data["default_score"], int)


def assert_qualification_exam(data: dict):
    _assert_standard_fields(data)
    assert is_valid_uuid(data["qualification_type_id"])
    assert isinstance(data["passing_score"], int)
    assert isinstance(data["max_attempts"], int)
    assert isinstance(data["retake_cooldown_days"], int)


def assert_qualification_exam_attempt(data: dict):
    _assert_standard_fields(data)
    assert is_valid_uuid(data["exam_id"])
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1
    assert isinstance(data["score"], int)
    assert data["outcome"] in ("PASSED", "FAILED")


def assert_hit(data: dict):
    _assert_standard_fields(data)
    assert is_valid_uuid(data["requester_id"])
    assert isinstance(data["title"], str)
    assert isinstance(data["reward_cents"], int)
    assert isinstance(data["required_qualification_ids"], list)
    assert isinstance(data["max_assignments"], int)
    assert isinstance(data["assignment_duration_minutes"], int)
    assert isinstance(data["time_limit_minutes"], int)
    assert isinstance(data["bonus_budget_cents"], int)
    assert isinstance(data["funds_required_cents"], int)
    assert isinstance(data["escrowed_cents"], int)
    assert isinstance(data["accepted_count"], int)
    assert isinstance(data["assignment_count"], int)
    assert isinstance(data["committed_assignments"], int)
    assert isinstance(data["spent_rewards_cents"], int)
    assert isinstance(data["spent_bonus_cents"], int)
    assert data["status"] in ("DRAFT", "PUBLISHED", "DISPATCHED", "COMPLETED", "CANCELLED")


def assert_assignment(data: dict):
    _assert_standard_fields(data)
    assert is_valid_uuid(data["hit_id"])
    assert is_valid_uuid(data["worker_id"])
    assert isinstance(data["sequence"], int)
    assert isinstance(data["bonus_cents"], int)
    assert isinstance(data["eligible_for_approval"], bool)
    assert isinstance(data["approval_rate_effect_applied"], bool)
    assert isinstance(data["committed"], bool)
    assert data["status"] in (
        "ACCEPTED", "SUBMITTED", "APPROVED", "REJECTED", "DISPUTED", "RETURNED", "EXPIRED"
    )


def assert_deposit(data: dict):
    _assert_standard_fields(data)
    assert is_valid_uuid(data["requester_id"])
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("PENDING", "SUCCEEDED", "FAILED")
    assert isinstance(data["escrowed_cents"], int)
    assert isinstance(data["refunded_cents"], int)


def assert_payout(data: dict):
    _assert_standard_fields(data)
    assert is_valid_uuid(data["worker_id"])
    assert data["payment_method"] in ("BANK_TRANSFER", "PAYPAL", "GIFT_CARD")
    assert isinstance(data["amount_cents"], int)
    assert is_iso8601_timestamp(data["hold_until_at"])
    assert data["status"] in ("HELD_FOR_VETTING", "PAID", "REJECTED")


def assert_review(data: dict):
    """Review is append-only: id + created_at only, never updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only Review must not expose updated_at"
    assert "version" not in data, "append-only Review must not expose version"
    assert is_valid_uuid(data["assignment_id"])
    assert is_valid_uuid(data["actor_requester_id"])
    assert data["actor_role"] in ("REQUESTER", "REVIEWER", "PLATFORM_ADMIN")
    assert data["kind"] in ("APPROVAL", "REJECTION", "BONUS")
    assert isinstance(data["bonus_cents"], int)
    assert isinstance(data["abuse_points"], int)


# ─── Domain invariant checkers ───────────────────────────────────────────────

def assert_requester_invariants(data: dict):
    """Balance conservation that must hold after ANY operation."""
    for field in (
        "prepaid_balance_cents", "escrowed_cents", "lifetime_spent_cents",
        "approved_count", "rejected_count", "abuse_score",
    ):
        assert data[field] >= 0, f"{field} must never be negative"
    assert 0 <= data["lifetime_rejection_rate_pct"] <= 100
    if data["status"] != "SUSPENDED":
        assert data["suspension_reason"] in (None, "NONE"), (
            "suspension_reason is null unless the requester is SUSPENDED"
        )


def assert_worker_invariants(data: dict):
    """Earning monotonicity and non-negativity that must hold after any operation."""
    assert data["total_earned_cents"] >= 0
    assert data["withdrawable_cents"] >= 0
    assert data["withdrawable_cents"] <= data["total_earned_cents"], (
        "withdrawable_cents can never exceed total_earned_cents"
    )
    for counter in ("approved_count", "rejected_count", "returned_count", "expired_count"):
        assert data[counter] >= 0


def assert_hit_invariants(data: dict):
    """Escrow and pool invariants that must hold after any operation."""
    assert data["escrowed_cents"] >= 0
    assert data["accepted_count"] <= data["max_assignments"], (
        "accepted_count is bounded by max_assignments"
    )
    assert data["committed_assignments"] >= 0
    assert data["spent_rewards_cents"] >= 0
    assert data["spent_bonus_cents"] <= data["bonus_budget_cents"], (
        "spent_bonus_cents never exceeds the bonus budget"
    )
    if data["status"] in ("COMPLETED", "CANCELLED"):
        assert data["escrowed_cents"] == 0, "terminal tasks hold no escrow"