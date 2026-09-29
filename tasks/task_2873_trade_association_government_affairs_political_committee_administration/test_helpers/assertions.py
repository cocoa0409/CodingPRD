"""Entity assertions and domain invariant checkers."""
import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonicalize_instant, instants_equal

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --- primitive shape helpers ---

def assert_bare_uuid(value: Any, field: str = "id") -> None:
    assert isinstance(value, str), f"{field} must be a string, got {type(value)}"
    assert is_valid_uuid(value), f"{field} must be a UUID string with no type prefix: {value!r}"
    assert len(value) == 36, f"{field} must carry no type prefix: {value!r}"


def assert_instant_field(value: Any, field: str) -> None:
    assert isinstance(value, str), f"{field} must be an ISO 8601 instant string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{field} must be an ISO 8601 UTC instant: {value!r}"


def assert_instant_equals(actual: Any, expected: str, field: str = "instant") -> None:
    assert instants_equal(actual, expected), (
        f"Expected {field} {canonicalize_instant(expected)}, got {canonicalize_instant(actual)}"
    )


def assert_iso_date(value: Any, field: str) -> None:
    assert isinstance(value, str) and _DATE_RE.match(value), (
        f"{field} must be an ISO YYYY-MM-DD calendar date, got {value!r}"
    )


def assert_integer_cents(value: Any, field: str) -> None:
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be returned as an integer number of cents, got {value!r}"
    )


def assert_two_decimal_pct(value: Any, field: str) -> None:
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be a number, got {value!r}"
    )
    assert round(float(value), 2) == float(value), (
        f"{field} must carry at most two decimal places, got {value!r}"
    )
    assert 0.00 <= float(value) <= 100.00, f"{field} must lie within 0.00 and 100.00, got {value!r}"


def assert_three_decimal_hours(value: Any, field: str = "hours") -> None:
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be a number, got {value!r}"
    )
    assert round(float(value), 3) == float(value), (
        f"{field} must carry at most three decimal places, got {value!r}"
    )


def assert_common_fields(data: Dict[str, Any], entity: str) -> None:
    """id, created_at, updated_at and version, as carried by most resources."""
    assert_bare_uuid(data.get("id"), f"{entity}.id")
    assert_instant_field(data.get("created_at"), f"{entity}.created_at")
    assert_instant_field(data.get("updated_at"), f"{entity}.updated_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1, got {data.get('version')!r}"
    )


# --- entity assertions ---

def assert_member(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "member")
    assert isinstance(data["legal_name"], str) and 0 < len(data["legal_name"]) <= 200
    assert data["membership_tier"] in ("ASSOCIATE", "FULL", "PREMIER")
    assert data["home_jurisdiction_code"] in ("FEDERAL", "STATE_CA", "STATE_NY")
    assert isinstance(data["home_district_code"], str) and data["home_district_code"]
    assert data["notice_method"] in ("RATIO", "FLAT_FLOOR")
    assert_integer_cents(data["annual_dues_cents"], "member.annual_dues_cents")
    assert data["annual_dues_cents"] >= 0
    assert isinstance(data["dues_year"], int) and 2020 <= data["dues_year"] <= 2100
    assert isinstance(data["restricted_class_size"], int) and data["restricted_class_size"] >= 0
    assert data["status"] in ("ACTIVE", "LAPSED", "SUSPENDED")
    assert isinstance(data["advocacy_optout"], bool)
    assert isinstance(data["engagement_score"], int) and 0 <= data["engagement_score"] <= 100
    assert isinstance(data["recorded_dissent_count"], int) and data["recorded_dissent_count"] >= 0
    assert isinstance(data["pac_solicitable"], bool)


def assert_committee(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "committee")
    assert isinstance(data["name"], str) and 0 < len(data["name"]) <= 200
    assert data["jurisdiction_scope"] in ("FEDERAL", "STATE_CA", "STATE_NY", "MULTI")
    assert_two_decimal_pct(data["quorum_threshold_pct"], "committee.quorum_threshold_pct")
    assert_two_decimal_pct(data["consensus_threshold_pct"], "committee.consensus_threshold_pct")
    assert isinstance(data["seat_count"], int) and data["seat_count"] >= 0
    assert isinstance(data["total_voting_weight"], int) and data["total_voting_weight"] >= 0
    assert data["roster_state"] in ("FORMING", "IMPAIRED", "QUORATE")
    assert_roster_state_matches_arithmetic(data)


def assert_roster_state_matches_arithmetic(committee: Dict[str, Any]) -> None:
    """roster_state follows seat_count and total_voting_weight."""
    if committee["seat_count"] < 3:
        expected = "FORMING"
    elif committee["total_voting_weight"] < 6:
        expected = "IMPAIRED"
    else:
        expected = "QUORATE"
    assert committee["roster_state"] == expected, (
        f"Expected roster_state {expected} for seat_count {committee['seat_count']} and "
        f"total_voting_weight {committee['total_voting_weight']}, got {committee['roster_state']}"
    )


def assert_committee_seat(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "seat")
    assert_bare_uuid(data["committee_id"], "seat.committee_id")
    assert_bare_uuid(data["member_id"], "seat.member_id")
    assert data["seat_role"] in ("CHAIR", "MEMBER")
    assert isinstance(data["voting_weight"], int) and data["voting_weight"] >= 1
    assert isinstance(data["dissent_strikes"], int) and data["dissent_strikes"] >= 0
    assert data["status"] in ("ACTIVE", "DAMPENED")


def assert_policy_position(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "position")
    assert_bare_uuid(data["committee_id"], "position.committee_id")
    assert isinstance(data["title"], str) and 0 < len(data["title"]) <= 200
    assert data["jurisdiction_code"] in ("FEDERAL", "STATE_CA", "STATE_NY")
    assert isinstance(data["summary"], str) and 0 < len(data["summary"]) <= 2000
    assert data["status"] in (
        "DRAFT", "BALLOTING", "CONSENSUS_REACHED", "RECONSIDERATION",
        "FAILED_CONSENSUS", "ADOPTED",
    )
    assert isinstance(data["round_number"], int) and 0 <= data["round_number"] <= 3
    for field in ("support_weight", "oppose_weight", "abstain_weight"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert_two_decimal_pct(data["quorum_pct"], "position.quorum_pct")
    assert_two_decimal_pct(data["consensus_pct"], "position.consensus_pct")
    assert data["last_tally_outcome"] in ("NONE", "NO_QUORUM", "CONSENSUS", "DISSENSUS")
    assert isinstance(data["dissent_register_count"], int) and data["dissent_register_count"] >= 0


def assert_position_vote(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "vote")
    assert_bare_uuid(data["position_id"], "vote.position_id")
    assert_bare_uuid(data["member_id"], "vote.member_id")
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert data["ballot"] in ("SUPPORT", "OPPOSE", "ABSTAIN")
    assert isinstance(data["weight_snapshot"], int) and data["weight_snapshot"] >= 1
    assert data["ballot_status"] in ("CAST", "SUPERSEDED")
    assert data["dissent_status"] in ("NONE", "FILED", "WITHDRAWN", "RECORDED")


def assert_registration(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "registration")
    assert data["jurisdiction_code"] in ("FEDERAL", "STATE_CA", "STATE_NY")
    assert isinstance(data["registrant_name"], str) and 0 < len(data["registrant_name"]) <= 200
    assert_iso_date(data["coverage_start_date"], "registration.coverage_start_date")
    assert_iso_date(data["coverage_end_date"], "registration.coverage_end_date")
    assert data["coverage_end_date"] > data["coverage_start_date"]
    assert data["status"] in ("DRAFT", "ACTIVE", "AMENDMENT_PENDING", "TERMINATED")
    assert isinstance(data["amendment_round"], int) and data["amendment_round"] >= 0
    assert_integer_cents(data["ytd_reportable_cents"], "registration.ytd_reportable_cents")
    assert_three_decimal_hours(data["ytd_reportable_hours"], "registration.ytd_reportable_hours")


def assert_lobbying_activity(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "activity")
    assert_bare_uuid(data["registration_id"], "activity.registration_id")
    assert_bare_uuid(data["position_id"], "activity.position_id")
    assert data["activity_kind"] in (
        "DIRECT_LOBBYING", "COALITION_CONTRIBUTION", "THIRD_PARTY_ADVOCACY",
        "GRASSROOTS_SUPPORT",
    )
    assert_iso_date(data["activity_date"], "activity.activity_date")
    assert_three_decimal_hours(data["hours"])
    assert_integer_cents(data["expenditure_cents"], "activity.expenditure_cents")
    assert_integer_cents(data["staff_cost_cents"], "activity.staff_cost_cents")
    assert isinstance(data["third_party_disclosure_required"], bool)
    assert data["status"] in ("LOGGED", "VOIDED")
    assert_instant_field(data["logged_at"], "activity.logged_at")


def assert_expenditure_report(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "report")
    assert_bare_uuid(data["registration_id"], "report.registration_id")
    assert isinstance(data["period_code"], str) and data["period_code"]
    assert_iso_date(data["period_start_date"], "report.period_start_date")
    assert_iso_date(data["period_end_date"], "report.period_end_date")
    assert_iso_date(data["due_date"], "report.due_date")
    assert data["basis"] in ("METHOD_A", "METHOD_B")
    for field in ("method_a_total_cents", "method_b_total_cents", "filed_total_cents"):
        assert_integer_cents(data[field], f"report.{field}")
    assert isinstance(data["included_activity_count"], int)
    assert data["status"] in ("OPEN", "CERTIFIED", "SUPERSEDED")
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]
    assert isinstance(data["late"], bool)
    expected_filed = (
        data["method_a_total_cents"] if data["basis"] == "METHOD_A"
        else data["method_b_total_cents"]
    )
    assert data["filed_total_cents"] == expected_filed, (
        f"filed_total_cents must follow basis {data['basis']}: expected {expected_filed}, "
        f"got {data['filed_total_cents']}"
    )


def assert_grassroots_campaign(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "campaign")
    assert_bare_uuid(data["position_id"], "campaign.position_id")
    assert isinstance(data["name"], str) and 0 < len(data["name"]) <= 200
    assert data["target_jurisdiction_code"] in ("FEDERAL", "STATE_CA", "STATE_NY")
    assert data["status"] in ("PLANNED", "LIVE", "CLOSED")
    for field in ("alert_count", "matched_member_total", "unmatched_alert_count"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert_integer_cents(data["cumulative_cost_cents"], "campaign.cumulative_cost_cents")
    assert isinstance(data["disclosure_required"], bool)


def assert_action_alert(data: Dict[str, Any]) -> None:
    """An alert is immutable: it carries only id and created_at as system fields."""
    assert_bare_uuid(data.get("id"), "alert.id")
    assert_instant_field(data.get("created_at"), "alert.created_at")
    assert "updated_at" not in data, "an action alert has no updated_at field"
    assert "version" not in data, "an action alert has no version field"
    assert_bare_uuid(data["campaign_id"], "alert.campaign_id")
    assert isinstance(data["target_district_code"], str) and data["target_district_code"]
    assert data["target_chamber"] in ("US_HOUSE", "US_SENATE", "STATE_ASSEMBLY")
    assert isinstance(data["message_subject"], str) and 0 < len(data["message_subject"]) <= 200
    assert_integer_cents(data["unit_cost_cents"], "alert.unit_cost_cents")
    assert isinstance(data["matched_member_ids"], list)
    assert data["matched_member_count"] == len(data["matched_member_ids"]), (
        "matched_member_count must be the length of matched_member_ids"
    )
    assert_integer_cents(data["cost_cents"], "alert.cost_cents")
    assert data["cost_cents"] == data["unit_cost_cents"] * data["matched_member_count"]
    assert data["status"] in ("DISPATCHED", "NO_MATCH")
    expected_status = "DISPATCHED" if data["matched_member_count"] >= 1 else "NO_MATCH"
    assert data["status"] == expected_status, (
        f"an alert with {data['matched_member_count']} matched members must be {expected_status}"
    )


def assert_prior_approval(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "prior_approval")
    assert_bare_uuid(data["member_id"], "prior_approval.member_id")
    assert isinstance(data["calendar_year"], int) and 2020 <= data["calendar_year"] <= 2100
    assert isinstance(data["solicitable_class_size"], int) and data["solicitable_class_size"] >= 1
    assert_iso_date(data["effective_date"], "prior_approval.effective_date")
    assert_iso_date(data["expires_at_date"], "prior_approval.expires_at_date")
    assert data["status"] in ("REQUESTED", "GRANTED", "REVOKED", "EXPIRED")


def assert_candidate(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "candidate")
    assert isinstance(data["name"], str) and 0 < len(data["name"]) <= 200
    assert data["office"] in ("US_HOUSE", "US_SENATE", "STATE_ASSEMBLY")
    assert data["jurisdiction_code"] in ("FEDERAL", "STATE_CA", "STATE_NY")
    assert isinstance(data["district_code"], str) and data["district_code"]
    assert isinstance(data["election_cycle"], str) and data["election_cycle"]
    assert data["incumbency"] in ("INCUMBENT", "CHALLENGER", "OPEN_SEAT")
    assert_two_decimal_pct(data["voting_alignment_pct"], "candidate.voting_alignment_pct")
    assert isinstance(data["committee_relevance_score"], int)
    assert 0 <= data["committee_relevance_score"] <= 100
    assert_two_decimal_pct(data["latest_support_score"], "candidate.latest_support_score")
    for field in ("pending_support_cents", "committed_support_cents", "disbursed_support_cents"):
        assert_integer_cents(data[field], f"candidate.{field}")


def assert_segregated_fund(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "fund")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["fund_year"], int) and 2020 <= data["fund_year"] <= 2100
    assert data["jurisdiction_code"] in ("FEDERAL", "STATE_CA", "STATE_NY")
    for field in (
        "min_reserve_cents", "receipts_total_cents", "committed_balance_cents",
        "disbursed_total_cents", "filing_fee_accrued_cents", "available_balance_cents",
    ):
        assert_integer_cents(data[field], f"fund.{field}")
    assert isinstance(data["filings_completed_count"], int)
    assert data["posture"] in ("OPEN", "RESTRICTED")
    assert_fund_invariants(data)


def assert_fund_invariants(fund: Dict[str, Any]) -> None:
    """available_balance_cents, the conservation identity and the posture rule."""
    expected_available = (
        fund["receipts_total_cents"]
        - fund["committed_balance_cents"]
        - fund["disbursed_total_cents"]
        - fund["filing_fee_accrued_cents"]
    )
    assert fund["available_balance_cents"] == expected_available, (
        f"available_balance_cents must be receipts less committed, disbursed and fees: "
        f"expected {expected_available}, got {fund['available_balance_cents']}"
    )
    assert fund["receipts_total_cents"] == (
        fund["available_balance_cents"] + fund["committed_balance_cents"]
        + fund["disbursed_total_cents"] + fund["filing_fee_accrued_cents"]
    ), "the fund conservation identity must hold"
    expected_posture = (
        "RESTRICTED" if fund["available_balance_cents"] < fund["min_reserve_cents"] else "OPEN"
    )
    assert fund["posture"] == expected_posture, (
        f"posture must be {expected_posture} for available {fund['available_balance_cents']} "
        f"against reserve {fund['min_reserve_cents']}, got {fund['posture']}"
    )


def assert_pac_contribution(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "contribution")
    assert_bare_uuid(data["fund_id"], "contribution.fund_id")
    assert_bare_uuid(data["candidate_id"], "contribution.candidate_id")
    assert_integer_cents(data["amount_cents"], "contribution.amount_cents")
    assert data["amount_cents"] >= 1
    assert_two_decimal_pct(data["support_score"], "contribution.support_score")
    assert_integer_cents(data["max_allowed_cents"], "contribution.max_allowed_cents")
    assert data["status"] in (
        "PENDING_BOARD", "SUSPENDED", "BOARD_APPROVED", "DISBURSED", "VOIDED"
    )
    assert isinstance(data["proposed_by_user_id"], str) and data["proposed_by_user_id"]


def assert_deductibility_notice(data: Dict[str, Any]) -> None:
    """The notice carries exactly the eight fields the PRD names."""
    expected_fields = {
        "member_id", "dues_year", "notice_method", "ratio_pct", "nondeductible_pct",
        "nondeductible_amount_cents", "deductible_amount_cents", "lobbying_spend_cents",
    }
    assert set(data.keys()) == expected_fields, (
        f"the notice must carry exactly {sorted(expected_fields)}, got {sorted(data.keys())}"
    )
    assert_bare_uuid(data["member_id"], "notice.member_id")
    assert isinstance(data["dues_year"], int)
    assert data["notice_method"] in ("RATIO", "FLAT_FLOOR")
    assert_two_decimal_pct(data["ratio_pct"], "notice.ratio_pct")
    assert_two_decimal_pct(data["nondeductible_pct"], "notice.nondeductible_pct")
    assert_integer_cents(data["nondeductible_amount_cents"], "notice.nondeductible_amount_cents")
    assert_integer_cents(data["deductible_amount_cents"], "notice.deductible_amount_cents")
    assert_integer_cents(data["lobbying_spend_cents"], "notice.lobbying_spend_cents")


def assert_candidate_accumulator_split(
    candidate: Dict[str, Any], pending: int, committed: int, disbursed: int
) -> None:
    """Each candidate accumulator is checked term by term, never as a grand total."""
    assert candidate["pending_support_cents"] == pending, (
        f"Expected pending_support_cents {pending}, got {candidate['pending_support_cents']}"
    )
    assert candidate["committed_support_cents"] == committed, (
        f"Expected committed_support_cents {committed}, got {candidate['committed_support_cents']}"
    )
    assert candidate["disbursed_support_cents"] == disbursed, (
        f"Expected disbursed_support_cents {disbursed}, got {candidate['disbursed_support_cents']}"
    )


def assert_fund_terms(
    fund: Dict[str, Any],
    receipts: Optional[int] = None,
    committed: Optional[int] = None,
    disbursed: Optional[int] = None,
    fees: Optional[int] = None,
    available: Optional[int] = None,
    posture: Optional[str] = None,
) -> None:
    """Check each fund term individually, then the conservation identity."""
    if receipts is not None:
        assert fund["receipts_total_cents"] == receipts, (
            f"Expected receipts_total_cents {receipts}, got {fund['receipts_total_cents']}"
        )
    if committed is not None:
        assert fund["committed_balance_cents"] == committed, (
            f"Expected committed_balance_cents {committed}, got {fund['committed_balance_cents']}"
        )
    if disbursed is not None:
        assert fund["disbursed_total_cents"] == disbursed, (
            f"Expected disbursed_total_cents {disbursed}, got {fund['disbursed_total_cents']}"
        )
    if fees is not None:
        assert fund["filing_fee_accrued_cents"] == fees, (
            f"Expected filing_fee_accrued_cents {fees}, got {fund['filing_fee_accrued_cents']}"
        )
    if available is not None:
        assert fund["available_balance_cents"] == available, (
            f"Expected available_balance_cents {available}, got {fund['available_balance_cents']}"
        )
    if posture is not None:
        assert fund["posture"] == posture, (
            f"Expected posture {posture}, got {fund['posture']}"
        )
    assert_fund_invariants(fund)
