"""Entity assertions and domain invariant checkers (PRD §2.5, §2.9, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp, tolerating optional fractional digits."""
    assert isinstance(value, str), f"Expected timestamp string, got {type(value)}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def assert_same_instant(actual: str, expected_iso: str, label: str = "timestamp"):
    """Two ISO timestamps denote the same instant regardless of fraction format."""
    assert _parse_instant(actual) == _parse_instant(expected_iso), (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')}"
    )


def _assert_event_record_fields(data: dict):
    """Immutable event records carry only id and created_at (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')}"
    )
    assert "updated_at" not in data, "event record must not carry updated_at"
    assert "version" not in data, "event record must not carry version"


def assert_party(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["party_type"] in ("PETITIONER", "PATENT_OWNER")


def assert_patent(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["patent_number"], str) and data["patent_number"]
    assert isinstance(data["title"], str) and data["title"]
    assert is_iso8601_timestamp(data["issue_date"])
    assert is_valid_uuid(data["owner_id"])
    assert isinstance(data["total_claims"], int) and data["total_claims"] >= 1
    assert data["status"] in (
        "ISSUED", "IN_REVIEW", "PARTIALLY_CANCELLED",
        "FULLY_CANCELLED", "CONFIRMED", "AMENDED",
    )
    assert_claim_ledger_invariant(data)


def assert_claim_ledger_invariant(patent: dict):
    """PRD §2.9: claims_alive + claims_cancelled_count == total_claims."""
    alive = patent["claims_alive"]
    cancelled = patent["claims_cancelled_count"]
    total = patent["total_claims"]
    assert alive + cancelled == total, (
        f"claim ledger broken: alive {alive} + cancelled {cancelled} != total {total}"
    )
    assert alive == total - cancelled
    assert patent["claims_amended_count"] >= 0


def assert_litigation_matter(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["patent_id"])
    assert is_valid_uuid(data["defendant_party_id"])
    assert isinstance(data["court_name"], str) and data["court_name"]
    assert isinstance(data["docket_number"], str) and data["docket_number"]
    assert is_iso8601_timestamp(data["complaint_served_date"])
    if data.get("trial_date") is not None:
        assert is_iso8601_timestamp(data["trial_date"])
    assert data["status"] in (
        "ACTIVE", "STAYED", "SETTLED", "TRIAL_COMPLETED", "DISMISSED",
    )
    if data["status"] == "STAYED":
        assert data.get("stay_reason") in (
            "MANUAL_STAY", "INSTITUTION_STAY", "PATENT_CANCELLED",
        )
    else:
        assert data.get("stay_reason") is None, (
            "stay_reason is null in every non-STAYED status (PRD §3.2)"
        )
    assert isinstance(data.get("estoppel_claims", []), list)


def assert_petition(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["patent_id"])
    assert is_valid_uuid(data["petitioner_id"])
    assert data["review_type"] in ("IPR", "PGR")
    assert isinstance(data["challenged_claims"], list) and data["challenged_claims"]
    assert isinstance(data["grounds"], list) and data["grounds"]
    assert isinstance(data["prior_art"], list) and data["prior_art"]
    assert isinstance(data["real_party_in_interest"], str)
    assert isinstance(data["fee_paid_cents"], int)
    assert is_iso8601_timestamp(data["filing_date"])
    assert data["status"] in ("FILED", "NOTICE_ACCORDED", "INSTITUTED", "DENIED")
    assert isinstance(data["fintiv_score"], int)


def assert_institution_decision(data: dict):
    _assert_event_record_fields(data)
    assert is_valid_uuid(data["petition_id"])
    assert data["outcome"] in ("INSTITUTED", "DENIED_MERITS", "DENIED_DISCRETIONARY")
    assert isinstance(data["merits_max_score"], int)
    assert data["threshold_used"] in (40, 51)
    assert isinstance(data["advisory_aggregate_score"], int)
    assert isinstance(data["fintiv_score"], int)
    assert isinstance(data["lead_judge_user_id"], str)
    assert is_iso8601_timestamp(data["decided_at"])


def assert_proceeding(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["petition_id"])
    assert is_valid_uuid(data["patent_id"])
    assert isinstance(data["lead_judge_user_id"], str)
    assert isinstance(data["instituted_claims"], list) and data["instituted_claims"]
    assert data["phase"] in (
        "INSTITUTED", "REPLY_WINDOW", "SUR_REPLY_WINDOW", "HEARING_PHASE",
        "DECISION_PHASE", "DECIDED", "REMANDED", "CLOSED",
    )
    assert is_iso8601_timestamp(data["institution_date"])
    assert is_iso8601_timestamp(data["cycle_anchor_date"])
    assert is_iso8601_timestamp(data["fwd_due_date"])
    assert is_iso8601_timestamp(data["advisory_anniversary_date"])
    assert isinstance(data["extension_used"], bool)
    assert isinstance(data["estoppel_applied"], bool)
    assert isinstance(data["amendment_slots_available"], int)
    assert isinstance(data["briefing_cycle"], int)
    assert isinstance(data["total_overage_fee_cents"], int)


def assert_brief(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["proceeding_id"])
    assert data["brief_type"] in ("PO_RESPONSE", "PETITIONER_REPLY", "PO_SUR_REPLY")
    assert isinstance(data["author_user_id"], str) and data["author_user_id"]
    assert isinstance(data["page_count"], int) and data["page_count"] >= 1
    assert isinstance(data["overage_fee_cents"], int) and data["overage_fee_cents"] >= 0
    assert isinstance(data["cycle"], int)


def assert_expert_declaration(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["brief_id"])
    assert isinstance(data["declarant_name"], str) and data["declarant_name"]
    assert isinstance(data["page_count"], int) and data["page_count"] >= 1
    assert isinstance(data["contains_new_evidence"], bool)


def assert_discovery_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["proceeding_id"])
    assert isinstance(data["requester_user_id"], str) and data["requester_user_id"]
    assert data["discovery_type"] in ("ROUTINE", "ADDITIONAL")
    assert data["status"] in ("PENDING", "GRANTED", "DENIED")


def assert_amendment_motion(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["proceeding_id"])
    assert isinstance(data["cycle"], int)
    assert isinstance(data["substitute_claims"], list) and data["substitute_claims"]
    assert data["status"] in ("FILED", "GRANTED", "DENIED", "WITHDRAWN")
    assert data["construction_standard"] == "PHILLIPS"


def assert_oral_hearing(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["proceeding_id"])
    assert data["status"] in ("REQUESTED", "SCHEDULED", "HELD", "WAIVED")
    assert isinstance(data["argument_minutes"], int) and data["argument_minutes"] >= 1


def assert_hearing_room(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1


def assert_final_written_decision(data: dict):
    _assert_event_record_fields(data)
    assert is_valid_uuid(data["proceeding_id"])
    assert isinstance(data["cycle"], int)
    assert isinstance(data["outcomes"], list) and data["outcomes"]
    assert is_iso8601_timestamp(data["issued_at"])
    assert isinstance(data["claims_cancelled_count"], int)


def assert_appeal(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["proceeding_id"])
    assert isinstance(data["appellant_user_id"], str) and data["appellant_user_id"]
    assert data["status"] in ("FILED", "AFFIRMED", "VACATED_AND_REMANDED", "DISMISSED")
