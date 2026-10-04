"""Entity assertions and domain invariant checkers."""
import pytest
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    """Every resource carries a UUID id and ISO 8601 timestamps."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_worker(data: dict):
    assert_common_fields(data)
    assert isinstance(data["handle"], str) and data["handle"]
    assert data["payout_currency"] in ("USD", "MXN", "PHP", "VND", "BRL", "INR")
    assert isinstance(data["worker_receivable_cents"], int)
    assert isinstance(data["lifetime_earned_cents"], int)
    assert isinstance(data["restricted"], bool)


def assert_worker_invariants(data: dict):
    """Domain invariants that hold on any worker read."""
    assert data["worker_receivable_cents"] >= 0, "receivable must never be negative"
    assert data["lifetime_earned_cents"] >= 0, "lifetime earnings must never be negative"
    assert data["total_accepted_payout_cents"] >= 0


def assert_program(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "QUALITY_EMBARGO", "FROZEN")
    assert data["language_code"] in ("es-MX", "en-US", "vi-VN", "tl-PH", "pt-BR", "ta-IN", "hi-IN")
    assert data["instruction_model"] in (
        "IDEAL_RESPONSE", "RANKED_PREFERENCE", "SPAN_EXTRACTION", "SAFETY_CLASSIFICATION",
    )
    assert data["sensitivity_class"] in ("STANDARD", "SENSITIVE", "RESTRICTED")
    assert isinstance(data["demand_points"], int)
    assert isinstance(data["capacity_requirement_points"], int)
    assert isinstance(data["capacity_feasible"], bool)
    assert isinstance(data["accuracy_floor_variant_below"], bool)


def assert_program_invariants(data: dict):
    assert data["demand_points"] >= 0
    assert data["capacity_requirement_points"] >= 0
    assert data["accuracy_denominator_count"] >= 0
    assert data["open_incident_count"] >= 0
    assert 0.0 <= data["accepted_accuracy_pct"] <= 100.0
    assert data["provisional_accuracy_pct"] >= data["accepted_accuracy_pct"], (
        "provisional accuracy is always at or above accepted accuracy"
    )


def assert_spec_unit(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "COMPLETE", "REJECTED")
    assert data["piece_status"] in (
        "DECOMPOSED", "IN_PRODUCTION", "CONSENSUS", "CERTIFIED", "REJECTED", "REWORK",
    )
    assert data["instruction_status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED")
    assert isinstance(data["max_items"], int)
    assert isinstance(data["item_count"], int)


def assert_spec_unit_invariants(data: dict):
    assert data["item_count"] <= data["max_items"], "item_count may never exceed max_items"
    assert data["remaining_item_slots"] == data["max_items"] - data["item_count"]
    assert data["certified_item_count"] >= 0
    assert data["unit_ceiling_points"] >= 0
    assert data["unit_effective_points"] >= data["unit_ceiling_points"]


def assert_labeling_item(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "RELEASED", "IN_PANEL", "RESOLVED")
    assert data["item_status"] in ("PENDING", "ROUTED", "IN_REVIEW", "COMPLETED", "REWORK")
    assert data["consensus_status"] in (
        "PENDING", "AWAITING_CONSENSUS", "CERTIFIED", "HELD_QUORUM", "REJECTED", "REWORK",
    )
    assert isinstance(data["item_seq"], int)
    assert isinstance(data["gold_audits_this_week"], int)
    assert isinstance(data["gold_rotation"], bool)
    assert isinstance(data["holds_quorum"], bool)
    assert isinstance(data["rework_cycles"], int)


def assert_labeling_item_invariants(data: dict):
    assert data["rework_cycles"] >= 0
    assert 0.0 <= data["agreement_ratio"] <= 1.0
    assert data["gold_rotation"] == (
        data["gold_audits_this_week"] >= 3 and data["consensus_status"] != "REWORK"
    ), "gold_rotation must derive from the weekly counter and the rework exemption"


def assert_commit(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("DISPATCHED", "COMMITTED", "ABSTAINED", "COMMIT_EXPIRED")
    assert data["kind"] in ("PRODUCTION", "GOLD")
    assert data["payment_status"] in ("UNPAID", "PENDING", "ACCEPTED", "REVERSED")
    assert is_valid_uuid(data["item_id"])
    assert is_valid_uuid(data["worker_id"])
    assert isinstance(data["dispatch_rank"], int)


def assert_qualification(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("IN_TRAINING", "QUALIFIED", "PROBATION", "SUSPENDED", "REVOKED")
    assert data["tier"] in ("NOVICE", "PROFICIENT", "EXPERT")
    assert 5000 <= data["qualification_score"] <= 9999
    assert data["tier_min_score"] in (5000, 6500, 8000)
    assert isinstance(data["gold_fail_streak"], int)


def assert_qualification_invariants(data: dict):
    assert data["provisional_accuracy_pct"] >= data["accuracy_pct"]
    assert data["gold_denominator_count"] >= 0


def assert_appeal_claim(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "ADVOCACY", "PROPOSED", "CONCURRENCE", "ADJUDICATION",
        "ACCEPTED", "REVIEWER_SUSPENSION", "REJECTED", "DEADLOCK",
    )
    assert data["grounds"] in ("AMBIGUOUS_INSTRUCTIONS", "INSUFFICIENT_CONTEXT", "TECHNICAL_ERROR")
    if data.get("consensus_outcome") is not None:
        assert data["consensus_outcome"] in ("UPHELD", "DENIED", "DEADLOCKED")


def assert_incident(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("OPEN", "RESOLVED", "DISMISSED")
    assert data["severity"] in ("MINOR", "MAJOR", "CATASTROPHIC")
    assert data["category"] in (
        "PII_EXPOSURE", "DATASET_DOWNLOAD", "SCREEN_RECORDING", "UNAUTHORIZED_SHARE",
    )


def assert_wrapper_metadata(data) -> None:
    """The exposed payload_uri must be gone once the engagement is sensitive."""
    assert isinstance(data, dict)


def assert_two_decimal_pct(value: float):
    assert value == pytest.approx(round(value, 2), abs=1e-9), (
        f"percentage must carry exactly two decimal places, got {value}"
    )


def assert_four_decimal_ratio(value: float):
    assert value == pytest.approx(round(value, 4), abs=1e-9), (
        f"agreement ratio must carry exactly four decimal places, got {value}"
    )