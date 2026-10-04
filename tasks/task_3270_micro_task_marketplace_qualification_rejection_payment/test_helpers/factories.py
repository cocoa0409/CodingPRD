"""Payload factories — one per entity, client-supplied input fields only."""
from .constants import TEST_DEFAULTS


def create_requester_payload(**overrides) -> dict:
    defaults = {"name": TEST_DEFAULTS["REQUESTER_NAME"]}
    defaults.update(overrides)
    return defaults


def create_worker_payload(**overrides) -> dict:
    defaults = {
        "display_name": TEST_DEFAULTS["WORKER_NAME"],
        "country": TEST_DEFAULTS["WORKER_COUNTRY"],
    }
    defaults.update(overrides)
    return defaults


def create_deposit_payload(**overrides) -> dict:
    defaults = {"amount_cents": TEST_DEFAULTS["DEPOSIT_CENTS"]}
    defaults.update(overrides)
    return defaults


def create_qualification_type_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Qualification",
        "kind": "SYSTEM",
        "auto_assign_threshold_pct": 80,
    }
    defaults.update(overrides)
    return defaults


def create_exam_payload(**overrides) -> dict:
    defaults = {"passing_score": 80}
    defaults.update(overrides)
    return defaults


def create_exam_attempt_payload(**overrides) -> dict:
    defaults = {"score": 90}
    defaults.update(overrides)
    return defaults


def create_hit_payload(requester_id: str, **overrides) -> dict:
    defaults = {
        "requester_id": requester_id,
        "title": "Test Task",
        "reward_cents": TEST_DEFAULTS["REWARD_CENTS"],
        "max_assignments": TEST_DEFAULTS["MAX_ASSIGNMENTS"],
        "assignment_duration_minutes": TEST_DEFAULTS["ASSIGNMENT_DURATION_MINUTES"],
        "time_limit_minutes": TEST_DEFAULTS["TIME_LIMIT_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_acceptance_payload(worker_id: str, **overrides) -> dict:
    defaults = {"worker_id": worker_id}
    defaults.update(overrides)
    return defaults


def create_submission_payload(assignment_version: int, **overrides) -> dict:
    defaults = {"expected_assignment_version": assignment_version}
    defaults.update(overrides)
    return defaults


def create_rejection_payload(**overrides) -> dict:
    defaults = {"reason": "work did not meet the instructions"}
    defaults.update(overrides)
    return defaults


def create_dispute_payload(**overrides) -> dict:
    defaults = {"reason": "the work followed the checklist"}
    defaults.update(overrides)
    return defaults


def create_bonus_payload(**overrides) -> dict:
    defaults = {"bonus_cents": 50}
    defaults.update(overrides)
    return defaults


def create_resolution_payload(**overrides) -> dict:
    defaults = {"decision": "APPROVE"}
    defaults.update(overrides)
    return defaults


def create_payout_payload(**overrides) -> dict:
    defaults = {"payment_method": "BANK_TRANSFER", "amount_cents": 100}
    defaults.update(overrides)
    return defaults


def create_cancel_payload(expected_hit_version: int, **overrides) -> dict:
    defaults = {"expected_hit_version": expected_hit_version}
    defaults.update(overrides)
    return defaults


def create_sweep_payload(expected_hit_version: int, **overrides) -> dict:
    defaults = {"expected_hit_version": expected_hit_version}
    defaults.update(overrides)
    return defaults


def create_verify_payout_payload(expected_payout_request_version: int, **overrides) -> dict:
    defaults = {"expected_payout_request_version": expected_payout_request_version}
    defaults.update(overrides)
    return defaults


def create_identity_verification_payload(**overrides) -> dict:
    defaults = {"outcome": "VERIFIED"}
    defaults.update(overrides)
    return defaults


def create_deposit_settlement_payload(**overrides) -> dict:
    defaults = {"outcome": "SUCCEEDED"}
    defaults.update(overrides)
    return defaults


def create_set_clock_payload(current_utc: str, **overrides) -> dict:
    defaults = {"current_utc": current_utc}
    defaults.update(overrides)
    return defaults


def create_advance_clock_payload(target_utc: str, **overrides) -> dict:
    defaults = {"target_utc": target_utc}
    defaults.update(overrides)
    return defaults