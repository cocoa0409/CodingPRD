"""Entity assertions and domain invariant checkers."""
import pytest
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data, with_version=True):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), (
            "updated_at must be ISO 8601"
        )
        assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_region(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]


def assert_dealer(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["region_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["dealer_code"], str) and data["dealer_code"]
    assert data["posture"] in ["GOOD_STANDING", "WATCH", "PROBATION", "SUSPENDED"]
    assert data["current_score_adjusted"] is None or isinstance(
        data["current_score_adjusted"], (int, float)
    )
    assert data["current_response_rate"] is None or isinstance(
        data["current_response_rate"], (int, float)
    )
    assert isinstance(data["confirmed_flag_count"], int)


def assert_department(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["dealer_id"])
    assert data["kind"] in ["SALES", "SERVICE"]
    assert isinstance(data["name"], str) and data["name"]


def assert_advisor(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["department_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["employee_ref"], str) and data["employee_ref"]


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["phone"], str) and data["phone"]
    assert isinstance(data["do_not_contact"], bool)


def assert_question_set(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["questions"], list) and len(data["questions"]) >= 1
    assert isinstance(data["comparability_factor"], (int, float))
    assert data["status"] in ["DRAFT", "ACTIVE", "RETIRED"]


def assert_wave(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["question_set_id"])
    assert data["status"] in ["DRAFT", "OPEN", "CLOSED", "FINALIZED"]
    for counter in (
        "invitations_total", "queued_count", "sent_count", "responded_count",
        "expired_count", "opted_out_count", "suppressed_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0


def assert_wave_partition_invariant(wave: dict):
    """invitations_total == queued + sent + responded + expired + opted_out + suppressed."""
    total = wave["invitations_total"]
    parts = (
        wave["queued_count"] + wave["sent_count"] + wave["responded_count"]
        + wave["expired_count"] + wave["opted_out_count"] + wave["suppressed_count"]
    )
    assert total == parts, (
        f"partition broken: total={total} but parts sum to {parts}"
    )


def assert_transaction(data: dict):
    # Immutable record: id + created_at only; no updated_at, no version.
    _assert_common(data, with_version=False)
    assert "updated_at" not in data, "Transaction must not carry updated_at"
    assert "version" not in data, "Transaction must not carry version"
    assert is_valid_uuid(data["dealer_id"])
    assert is_valid_uuid(data["department_id"])
    assert is_valid_uuid(data["customer_id"])
    assert data["kind"] in ["SALE", "SERVICE_VISIT"]
    assert isinstance(data["margin_cents"], int) and data["margin_cents"] >= 0


def assert_invitation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["transaction_id"])
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["wave_id"])
    assert data["status"] in [
        "QUEUED", "SENT", "RESPONDED", "EXPIRED", "OPTED_OUT", "SUPPRESSED",
    ]


def assert_response(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["invitation_id"])
    assert isinstance(data["score"], (int, float))
    assert data["status"] in ["SCORED", "FLAGGED", "EXCLUDED"]
    assert data["excluded_reason"] in [None, "APPEAL_UPHELD", "MANIPULATION_CONFIRMED"]


def assert_appeal(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["response_id"])
    assert is_valid_uuid(data["dealer_id"])
    assert data["status"] in ["FILED", "UNDER_REVIEW", "UPHELD", "DENIED"]


def assert_flag(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["dealer_id"])
    assert data["kind"] in ["COACHING", "OPT_OUT_SUPPRESSION", "CONTACT_TAMPERING"]
    assert data["status"] in ["OPEN", "CONFIRMED", "DISMISSED"]


def assert_statement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["dealer_id"])
    assert is_valid_uuid(data["wave_id"])
    assert data["status"] in ["PROVISIONAL", "FINAL", "PAID", "SUPERSEDED"]
    assert data["tier"] in ["GOLD", "SILVER", "BRONZE", "INELIGIBLE"]
    assert isinstance(data["eligible_margin_cents"], int)
    assert isinstance(data["payout_cents"], int)


def assert_action_plan(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["dealer_id"])
    assert is_valid_uuid(data["wave_id"])
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "APPROVED", "REJECTED",
        "IN_PROGRESS", "COMPLETED", "OVERDUE",
    ]
