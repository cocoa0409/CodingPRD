"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_center(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["center_code"], str) and data["center_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["tier"] in ("STANDARD", "PREFERRED", "NATIONAL_HUB")
    assert data["participation_status"] in ("ACTIVE", "PROBATION", "SUSPENDED")
    assert isinstance(data["max_concurrent_chains"], int)
    assert isinstance(data["version"], int)


def assert_donor(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["abo_type"] in ("A", "B", "AB", "O")
    assert data["donor_kind"] in ("PAIRED", "ALTRUISTIC", "BRIDGE")
    assert data["medical_status"] in ("CLEARED", "ON_HOLD", "WITHDRAWN", "DECEASED")
    assert data["surgery_state"] in (
        "PRE_SURGERY", "SURGERY_SCHEDULED", "NEPHRECTOMY_DONE", "FAILED_PREOP"
    )
    assert data["chain_participation_state"] in (
        "POOL", "PROPOSED", "LOCKED", "COMMITTED", "COMPLETED", "BROKEN", "WITHDRAWN"
    )
    assert isinstance(data["version"], int)


def assert_recipient(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["abo_type"] in ("A", "B", "AB", "O")
    assert data["medical_status"] in (
        "LISTED", "ON_HOLD", "TRANSPLANTED", "WITHDRAWN", "DECEASED"
    )
    assert data["chain_participation_state"] in (
        "POOL", "PROPOSED", "LOCKED", "COMMITTED", "TRANSPLANTED", "ORPHANED", "WITHDRAWN"
    )
    assert isinstance(data["cpra_percent"], int)


def assert_pair(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["pair_state"] in (
        "REGISTERED", "VERIFIED", "IN_POOL", "IN_PROPOSED_CHAIN", "LOCKED",
        "RELEASED", "DISSOLVED",
    )


def assert_chain_run(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["run_state"] in ("DRAFT", "EXECUTED", "PUBLISHED", "SUPERSEDED")


def assert_chain(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["chain_state"] in (
        "PROPOSED", "ACCEPTING", "LOCKED", "SCHEDULED", "EXECUTING",
        "COMPLETED", "BROKEN", "ABORTED",
    )
    assert data["completion_grade"] in ("PENDING", "FULL", "PARTIAL", "BROKEN_PARTIAL")


def assert_match_offer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["offer_state"] in (
        "PENDING_CROSSMATCH", "CROSSMATCH_PASSED", "CROSSMATCH_FAILED",
        "CENTER_ACCEPTED", "CENTER_DECLINED", "SCHEDULED", "DONOR_SURGERY_DONE",
        "ORGAN_SHIPPED", "TRANSPLANT_COMPLETED", "OFFER_FAILED",
    )
    assert isinstance(data["match_score_bps"], int)
    assert 0 <= data["match_score_bps"] <= 10000
    assert isinstance(data["abo_compatible"], bool)
    assert isinstance(data["hla_mismatch_count"], int)
    assert isinstance(data["unacceptable_antigen_hit"], bool)


def assert_crossmatch_review(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["virtual_result"] in (
        "NEGATIVE", "WEAK_POSITIVE", "STRONG_POSITIVE", "INDETERMINATE"
    )
    assert data["decision"] in ("PENDING", "PASS", "FAIL")
    assert isinstance(data["dsa_mfi_max"], int)


def assert_slot(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["slot_state"] in ("OPEN", "RESERVED", "CONSUMED", "RELEASED", "EXPIRED")
    assert data["room_kind"] in ("NEPHRECTOMY_OR", "TRANSPLANT_OR", "BACK_OR")


def assert_shipment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["shipment_state"] in (
        "PLANNED", "DEPARTED", "DELAYED", "REROUTED", "DELIVERED", "CANCELLED"
    )
    assert data["shipment_mode"] in ("COMMERCIAL_FLIGHT", "CHARTER", "GROUND_COURIER")
    assert isinstance(data["routing_sequence"], int)


def assert_itinerary(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["itinerary_state"] in ("DRAFT", "CONFIRMED", "CANCELLED", "REIMBURSED")
    assert isinstance(data["segment_miles"], int)
    assert isinstance(data["lodging_nights"], int)


def assert_policy(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["policy_state"] in ("ACTIVE", "LAPSED", "EXHAUSTED")
    assert isinstance(data["covered_complication_max_cents"], int)
    assert isinstance(data["covered_lost_wages_max_cents"], int)


def assert_claim(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["claim_kind"] in ("COMPLICATION", "LOST_WAGES", "TRAVEL", "PRIORITY_KIDNEY")
    assert data["claim_state"] in (
        "SUBMITTED", "UNDER_REVIEW", "APPROVED", "PARTIALLY_APPROVED", "DENIED", "PAID"
    )


def assert_outcome(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["outcome_kind"] in (
        "SUCCESS", "DELAYED_GRAFT_FUNCTION", "PRIMARY_NON_FUNCTION", "REJECTED_30D", "FAILED"
    )
    assert data["outcome_state"] in ("REPORTED", "ATTRIBUTED_TO_CENTER", "APPEALED", "FINAL")


def assert_chain_break_event(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["trigger_kind"] in (
        "DONOR_MEDICAL_DECLINE", "DONOR_WITHDRAWAL", "DONOR_DECEASED",
        "SURGERY_ABORTED", "ORGAN_LOST_IN_TRANSIT",
    )
    assert data["event_state"] in ("RECORDED", "CASCADED", "RECONSTRUCTED")
