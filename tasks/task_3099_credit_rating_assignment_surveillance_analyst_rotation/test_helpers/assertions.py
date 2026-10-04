"""Entity assertions and domain invariant checkers."""
import pytest

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only(data: dict):
    """Append-only artifacts carry only id + created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data or data.get("updated_at") is None
    assert "version" not in data or data.get("version") is None


def assert_methodology(data: dict):
    _assert_common(data)
    assert isinstance(data["methodology_code"], str) and data["methodology_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["version_code"], str) and data["version_code"]
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED")
    assert isinstance(data["is_public"], bool)


def assert_rated_entity(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["revenue_band"] in ("LARGE", "MID", "SMALL")
    assert data["solicitation_status"] in ("SOLICITED", "UNSOLICITED")
    assert data["surveillance_posture"] in ("NORMAL", "ACTIVE_WATCH", "RESTRICTED")


def assert_engagement_letter(data: dict):
    _assert_common(data)
    assert isinstance(data["fee_amount_cents"], int)
    assert isinstance(data["fee_credited_cents"], int)
    assert isinstance(data["fee_reversed_cents"], int)
    assert isinstance(data["fee_payer_is_issuer"], bool)
    assert data["fee_structure"] in ("FLAT_ANNUAL", "MILESTONE", "TRANSACTION")
    assert data["status"] in ("DRAFT", "SIGNED", "ACTIVE", "TERMINATED")
    assert data["fee_credited_cents"] + data["fee_reversed_cents"] <= data["fee_amount_cents"]


def assert_rating_request(data: dict):
    _assert_common(data)
    assert isinstance(data["instrument_notional_cents"], int)
    assert isinstance(data["allocated_fee_cents"], int)
    assert data["request_status"] in (
        "SUBMITTED", "SCREENING", "TEAM_CONFIRMED", "COMMITTEE_DECIDED",
        "APPEALED", "PUBLISHED", "WITHDRAWN",
    )
    assert is_iso8601_timestamp(data["received_at"]), "received_at must be ISO 8601"


def assert_analyst(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["analyst_tier"] in ("LEAD", "SUPPORT", "COMMITTEE_ELIGIBLE")
    assert isinstance(data["consecutive_lead_months"], int)
    assert isinstance(data["rotation_eligible"], bool)
    assert isinstance(data["is_departed"], bool)


def assert_team_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in ("PROPOSED", "SCREENED", "CONFIRMED", "REVOKED")
    assert data["conflict_status"] in ("PENDING_SCREEN", "CLEAR", "POTENTIAL", "DISQUALIFYING")
    assert isinstance(data["rotation_exemption_granted"], bool)
    assert is_iso8601_timestamp(data["assigned_at"])


def assert_conflict_screening(data: dict):
    _assert_append_only(data)
    assert data["screening_result"] in ("CLEAR", "POTENTIAL", "DISQUALIFYING")
    assert data["conflict_type"] in (
        "NONE", "PRIOR_EMPLOYMENT", "FAMILY_TIE", "SECURITY_HOLDING", "FEE_DEPENDENCE",
    )
    assert isinstance(data["reviewer_user_id"], str) and data["reviewer_user_id"]


def assert_rating_committee(data: dict):
    _assert_common(data)
    assert data["committee_status"] in (
        "CONVENED", "IN_SESSION", "DECIDED", "DISSOLVED", "QUORUM_FAILED",
    )
    assert isinstance(data["votes_cast"], int)
    assert isinstance(data["quorum_met"], bool)
    assert 2 <= data["required_voting_members"] <= 9


def assert_committee_vote(data: dict):
    _assert_append_only(data)
    assert data["vote_value"] in ("UPGRADE", "AFFIRM", "DOWNGRADE", "ABSTAIN")
    assert isinstance(data["is_dissent"], bool)


def assert_rating_decision(data: dict):
    _assert_common(data)
    assert data["decision_status"] in ("DRAFT", "APPEAL_WINDOW", "PUBLISHED", "WITHDRAWN")
    assert data["outlook"] in ("POSITIVE", "STABLE", "NEGATIVE", "DEVELOPING")
    assert data["watch_status"] in ("NO_WATCH", "WATCH_UPGRADE", "WATCH_DOWNGRADE")
    assert isinstance(data["dissent_count"], int)
    assert isinstance(data["dissent_score"], (int, float))
    assert isinstance(data["is_unsolicited"], bool)
    assert len(data["rationale"]) >= 200


def assert_issuer_appeal(data: dict):
    _assert_common(data)
    assert data["appeal_outcome"] in (None, "PENDING", "ACCEPTED", "REJECTED")
    assert isinstance(data["contains_new_information"], bool)


def assert_surveillance_review(data: dict):
    _assert_common(data)
    assert data["review_status"] in (
        "SCHEDULED", "OVERDUE", "ESCALATED", "IN_PROGRESS", "COMPLETED",
    )
    assert data["review_type"] in ("PERIODIC", "EVENT_DRIVEN")
    assert isinstance(data["overdue_days"], int) and data["overdue_days"] >= 0
    assert isinstance(data["escalation_index"], int)


def assert_appearance_reconciliation(data: dict):
    _assert_common(data)
    assert data["reconciliation_status"] in (
        "PENDING", "BREACH_CONFIRMED", "APPEAL_PENDING", "CLEARED",
    )
    assert data["stated_role"] in ("LEAD_ANALYST", "SUPPORT_ANALYST", "COMMITTEE_VOTER")
    assert isinstance(data["evidence_reference"], str)


def assert_review_slot(data: dict):
    _assert_common(data)
    assert data["status"] in ("BOOKED", "CANCELLED", "UNFILLED")
    assert data["pre_buffer_minutes"] == 30
    assert data["post_buffer_minutes"] == 30


def assert_analyst_compensation(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "APPROVED", "PAID")
    assert isinstance(data["base_salary_cents"], int)
    assert isinstance(data["accuracy_bonus_cents"], int)
    assert isinstance(data["fee_generation_bonus_cents"], int)
    assert isinstance(data["total_compensation_cents"], int)
    assert isinstance(data["compensation_separation_pct"], (int, float))


def assert_look_back_review(data: dict):
    _assert_common(data)
    assert data["review_status"] in ("INITIATED", "IN_PROGRESS", "CLOSED")
    assert isinstance(data["affected_decisions_count"], int)


def assert_rating_action_event(data: dict):
    _assert_append_only(data)
    assert data["event_status"] in ("PENDING", "APPLIED", "REVERTED")
    assert data["event_type"] in (
        "UPGRADE", "DOWNGRADE", "AFFIRM", "WATCH_PLACEMENT", "WITHDRAWAL",
    )


# ─── Domain invariants ───

def assert_compensation_conservation(data: dict):
    """total == base + accuracy bonus + 0, and the fee component is exactly 0."""
    assert data["fee_generation_bonus_cents"] == 0, "fee-generation bonus must be zero"
    expected = data["base_salary_cents"] + data["accuracy_bonus_cents"] + 0
    assert data["total_compensation_cents"] == expected, (
        f"total {data['total_compensation_cents']} != base+accuracy {expected}"
    )
    assert data["compensation_separation_pct"] == pytest.approx(1.0)


def assert_fee_pool_conserved(data: dict, expected_total: int):
    """fee_credited_cents + fee_reversed_cents is a conserved pool."""
    total = data["fee_credited_cents"] + data["fee_reversed_cents"]
    assert total == expected_total, f"conserved fee pool drifted: {total} != {expected_total}"
    assert_cost_precision(total, 0)


def assert_same_instant(actual: str, expected: str, label: str = "timestamp"):
    """Two ISO 8601 stamps name the same instant.

    PRD §2.2 fixes three fractional digits for server-generated stamps while
    §2.5 allows an input instant to be written without them, so the test must
    compare the instants rather than the literal strings.
    """
    def _parse(text: str):
        from datetime import datetime, timezone

        value = str(text).strip()
        if value.endswith("Z") or value.endswith("z"):
            value = value[:-1] + "+00:00"
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    assert _parse(actual) == _parse(expected), (
        f"{label}: {actual!r} is not the same instant as {expected!r}"
    )