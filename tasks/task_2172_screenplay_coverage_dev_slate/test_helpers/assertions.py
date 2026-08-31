"""Entity assertions and domain invariant checkers."""

from datetime import datetime, timezone

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    CALIBRATION_ANCHOR,
    RECOMMENDATION_BONUS,
    SCORE_WEIGHTS,
    TIER_HOT_MIN,
    TIER_PRIORITY_MIN,
    TIER_RANK_ORDER,
    TIER_WATCH_MIN,
)

# --------------------------------------------------------------------------
# Instants and money
# --------------------------------------------------------------------------


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating 'Z' and any fractional digits."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: str, expected: str, field: str = "instant") -> None:
    """Assert two ISO 8601 instants denote the same moment in time."""
    assert parse_instant(actual) == parse_instant(expected), (
        f"Expected {field} to be the instant {expected}, got {actual}"
    )


def assert_two_decimal_value(value, field: str = "value") -> None:
    """A decimal number carried to exactly two decimal places."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be a number, got {value!r}"
    )
    assert round(float(value), 2) == float(value), (
        f"{field} must be carried to two decimal places, got {value!r}"
    )


def assert_whole_cents(value, field: str = "amount") -> None:
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be a whole-cent integer, got {value!r}"
    )


# --------------------------------------------------------------------------
# Envelope / common-field shape
# --------------------------------------------------------------------------


def assert_common_fields(data: dict, entity: str = "resource") -> None:
    """Mutable resources carry id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1"
    )


def assert_append_only_fields(data: dict, entity: str = "record") -> None:
    """Append-only records carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert "updated_at" not in data, (
        f"{entity} is append-only and must not expose updated_at"
    )
    assert "version" not in data, (
        f"{entity} is append-only and must not expose version"
    )


def assert_envelope_meta(body: dict, expected_response_type: str) -> None:
    meta = body.get("meta") or {}
    assert isinstance(meta.get("api_request_id"), str) and meta[
        "api_request_id"
    ].startswith("req_"), "meta.api_request_id must be a string starting with req_"
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", "")), (
        "meta.api_request_timestamp must be an ISO 8601 UTC timestamp"
    )
    assert body.get("response_type") == expected_response_type, (
        f"Expected response_type {expected_response_type}, got {body.get('response_type')}"
    )


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------


def assert_literary_property(data: dict) -> None:
    assert_common_fields(data, "LiteraryProperty")
    assert isinstance(data["title"], str) and data["title"]
    assert data["material_type"] in [
        "SPEC_SCRIPT", "BOOK", "ARTICLE", "PLAY", "LIFE_RIGHTS_STORY", "ORIGINAL_PITCH",
    ]
    assert isinstance(data["source_author_name"], str)
    assert data["genre"] in [
        "DRAMA", "COMEDY", "THRILLER", "HORROR", "SCIFI", "FAMILY", "DOCUMENTARY",
    ]
    assert data["rights_chain_status"] in ["UNVERIFIED", "PARTIAL", "CLEAR", "DISPUTED"]
    assert data["tracking_tier"] in TIER_RANK_ORDER
    assert isinstance(data["verified_document_count"], int)
    assert data["verified_document_count"] >= 0
    assert isinstance(data["encumbrance_count"], int)
    assert data["encumbrance_count"] >= 0


def assert_rights_chain_document(data: dict) -> None:
    assert_append_only_fields(data, "RightsChainDocument")
    assert data["doc_type"] in [
        "CHAIN_OF_TITLE", "COPYRIGHT_CERT", "WGA_REGISTRATION",
        "PRIOR_ASSIGNMENT", "LIFE_RIGHTS_RELEASE", "CLEARANCE_OPINION",
    ]
    assert isinstance(data["verified"], bool)
    assert isinstance(data["superseded"], bool)
    assert isinstance(data["executed_on"], str)


def assert_submission(data: dict) -> None:
    assert_common_fields(data, "Submission")
    assert is_valid_uuid(data["property_id"])
    assert data["submitted_via"] in [
        "AGENCY", "MANAGER", "ATTORNEY", "UNSOLICITED", "INTERNAL",
    ]
    assert data["priority_flag"] in ["RUSH", "STANDARD", "BACKLOG"]
    assert isinstance(data["release_form_required"], bool)
    assert data["status"] in [
        "RECEIVED", "RELEASE_PENDING", "INTAKE_CLEARED", "READER_ASSIGNED",
        "COVERAGE_IN_REVIEW", "TRACKED", "PASSED", "IN_DEVELOPMENT", "WITHDRAWN",
    ]
    assert data["decision"] in [
        "PENDING", "PASS", "CONSIDER", "RECOMMEND", "STRONG_RECOMMEND",
    ]
    assert is_iso8601_timestamp(data["received_at"])
    assert is_iso8601_timestamp(data["coverage_due_at"])


def assert_release_form(data: dict) -> None:
    assert_common_fields(data, "ReleaseForm")
    assert is_valid_uuid(data["submission_id"])
    assert data["status"] in ["REQUIRED", "SENT", "EXECUTED", "WAIVED", "EXPIRED"]
    assert is_iso8601_timestamp(data["expires_at"])


def assert_reader(data: dict) -> None:
    assert_common_fields(data, "Reader")
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["specialty_genre"] in [
        "DRAMA", "COMEDY", "THRILLER", "HORROR", "SCIFI", "FAMILY", "DOCUMENTARY",
    ]
    assert isinstance(data["weekly_capacity"], int)
    assert 1 <= data["weekly_capacity"] <= 20
    assert data["employment_type"] in ["STAFF", "FREELANCE"]
    assert data["status"] in ["ACTIVE", "ON_LEAVE", "INACTIVE"]
    assert isinstance(data["active_assignment_count"], int)
    assert data["active_assignment_count"] >= 0
    assert isinstance(data["completed_report_count"], int)
    assert data["completed_report_count"] >= 0
    assert_two_decimal_value(data["calibration_bias"], "Reader.calibration_bias")


def assert_coverage_assignment(data: dict) -> None:
    assert_common_fields(data, "CoverageAssignment")
    assert is_valid_uuid(data["submission_id"])
    assert is_valid_uuid(data["reader_id"])
    assert data["status"] in [
        "ASSIGNED", "IN_PROGRESS", "SUBMITTED", "COMPLETED", "RECALLED",
    ]
    assert isinstance(data["auto_selected"], bool)
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_due"])


def assert_coverage_report(data: dict) -> None:
    assert_common_fields(data, "CoverageReport")
    assert is_valid_uuid(data["assignment_id"])
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "REVISION_REQUESTED", "APPROVED", "REJECTED",
    ]
    assert isinstance(data["revision_round_count"], int)
    assert 0 <= data["revision_round_count"] <= 2
    if data.get("recommendation") is not None:
        assert data["recommendation"] in [
            "PASS", "CONSIDER", "RECOMMEND", "STRONG_RECOMMEND",
        ]
    if data.get("composite_score") is not None:
        assert_two_decimal_value(data["composite_score"], "composite_score")
    if data.get("normalized_score") is not None:
        assert_two_decimal_value(data["normalized_score"], "normalized_score")
        assert 1.00 <= data["normalized_score"] <= 10.00, (
            "normalized_score is clamped into [1.00, 10.00]"
        )


def assert_tracking_board_entry(data: dict) -> None:
    assert_common_fields(data, "TrackingBoardEntry")
    assert is_valid_uuid(data["property_id"])
    assert is_valid_uuid(data["report_id"])
    assert data["board_tier"] in TIER_RANK_ORDER
    assert data["status"] in ["LIVE", "ARCHIVED"]
    assert_two_decimal_value(data["heat_score"], "heat_score")
    assert isinstance(data["competing_submission_count"], int)
    assert data["competing_submission_count"] >= 0
    assert is_iso8601_timestamp(data["entered_at"])
    assert_tier_ladder(data["heat_score"], data["board_tier"])


def assert_option_agreement(data: dict) -> None:
    assert_common_fields(data, "OptionAgreement")
    assert is_valid_uuid(data["property_id"])
    assert_whole_cents(data["option_fee_cents"], "option_fee_cents")
    assert_whole_cents(data["purchase_price_cents"], "purchase_price_cents")
    assert data["status"] in [
        "DRAFTED", "ACTIVE", "EXTENDED", "EXERCISED", "LAPSED", "REVERTED", "TERMINATED",
    ]
    assert isinstance(data["extension_exercised"], bool)
    assert isinstance(data["applicable_to_purchase"], bool)
    assert_whole_cents(data["escalation_bps"], "escalation_bps")
    if data.get("adjusted_purchase_price_cents") is not None:
        assert_whole_cents(
            data["adjusted_purchase_price_cents"], "adjusted_purchase_price_cents"
        )
    if data.get("net_purchase_due_cents") is not None:
        assert_whole_cents(data["net_purchase_due_cents"], "net_purchase_due_cents")


def assert_development_project(data: dict) -> None:
    assert_common_fields(data, "DevelopmentProject")
    assert is_valid_uuid(data["property_id"])
    assert is_valid_uuid(data["option_agreement_id"])
    assert data["rights_status"] in ["OPTIONED", "OWNED", "LAPSED_RIGHTS", "REVERTED"]
    assert data["development_status"] in [
        "SETUP", "WRITING", "DRAFT_DELIVERED", "POLISH", "POLISH_DELIVERED",
        "GREENLIT", "TURNAROUND", "DEAD",
    ]
    assert_whole_cents(data["budget_cents"], "budget_cents")
    assert_whole_cents(data["writer_budget_cap_cents"], "writer_budget_cap_cents")
    assert_whole_cents(
        data["committed_writer_fee_cents"], "committed_writer_fee_cents"
    )
    assert isinstance(data["greenlight_ready"], bool)
    assert_greenlight_ready_consistent(data)


def assert_writer(data: dict) -> None:
    assert_common_fields(data, "Writer")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["guild_member"], bool)
    assert data["status"] in ["ACTIVE", "UNAVAILABLE"]
    assert_whole_cents(data["committed_fee_cents"], "committed_fee_cents")
    assert_whole_cents(data["paid_fee_cents"], "paid_fee_cents")
    assert data["committed_fee_cents"] >= 0
    assert data["paid_fee_cents"] >= 0
    assert isinstance(data["active_engagement_count"], int)
    assert data["active_engagement_count"] >= 0


def assert_writer_engagement(data: dict) -> None:
    assert_common_fields(data, "WriterEngagement")
    assert is_valid_uuid(data["project_id"])
    assert is_valid_uuid(data["writer_id"])
    assert data["engagement_type"] in [
        "ORIGINAL_DRAFT", "REWRITE", "POLISH", "PRODUCTION_REWRITE",
    ]
    assert data["status"] in [
        "PROPOSED", "ATTACHED", "ACTIVE", "COMPLETED", "TERMINATED",
    ]
    assert_whole_cents(data["total_fee_cents"], "total_fee_cents")
    assert_whole_cents(data["guild_minimum_cents"], "guild_minimum_cents")
    assert isinstance(data["milestone_count"], int)


def assert_milestone_payment(data: dict) -> None:
    assert_common_fields(data, "MilestonePayment")
    assert is_valid_uuid(data["engagement_id"])
    assert data["milestone_type"] in [
        "COMMENCEMENT", "FIRST_DRAFT_DELIVERY", "FIRST_DRAFT_ACCEPTANCE",
        "REWRITE_DELIVERY", "POLISH_DELIVERY", "PRODUCTION_BONUS",
    ]
    assert data["status"] in ["SCHEDULED", "DUE", "APPROVED", "PAID", "VOIDED"]
    assert isinstance(data["sequence_index"], int) and data["sequence_index"] >= 0
    assert_whole_cents(data["percentage_bps"], "percentage_bps")
    assert_whole_cents(data["gross_amount_cents"], "gross_amount_cents")
    assert isinstance(data["due_on"], str)


def assert_greenlight_review(data: dict) -> None:
    assert_common_fields(data, "GreenlightReview")
    assert is_valid_uuid(data["project_id"])
    assert data["status"] in [
        "OPEN", "VOTING", "PASSED", "DECLINED", "DEFERRED", "WITHDRAWN",
    ]
    for field in (
        "eligible_weight_bps",
        "cast_weight_bps",
        "decisive_weight_bps",
        "approve_weight_bps",
    ):
        assert_whole_cents(data[field], field)
        assert data[field] >= 0
    assert_two_decimal_value(data["quorum_pct"], "quorum_pct")
    assert_two_decimal_value(data["approval_pct"], "approval_pct")
    assert isinstance(data["veto_cast"], bool)
    assert data["decisive_weight_bps"] <= data["cast_weight_bps"], (
        "decisive_weight_bps is cast_weight_bps less the ABSTAIN weight"
    )
    assert data["approve_weight_bps"] <= data["decisive_weight_bps"], (
        "APPROVE ballots are a subset of the decisive ballots"
    )


def assert_committee_member(data: dict) -> None:
    assert_common_fields(data, "CommitteeMember")
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["vote_weight_bps"], int)
    assert 1 <= data["vote_weight_bps"] <= 10000
    assert isinstance(data["veto_power"], bool)
    assert data["status"] in ["ACTIVE", "INACTIVE"]


def assert_committee_vote(data: dict) -> None:
    assert_append_only_fields(data, "CommitteeVote")
    assert is_valid_uuid(data["review_id"])
    assert is_valid_uuid(data["member_id"])
    assert data["vote_value"] in ["APPROVE", "DECLINE", "ABSTAIN", "VETO"]
    assert isinstance(data["weight_bps_snapshot"], int)


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------


def assert_tier_ladder(heat_score: float, board_tier: str) -> None:
    """The tier ladder is applied to the rounded heat_score, lower bounds inclusive."""
    if heat_score >= TIER_PRIORITY_MIN:
        expected = "PRIORITY"
    elif heat_score >= TIER_HOT_MIN:
        expected = "HOT"
    elif heat_score >= TIER_WATCH_MIN:
        expected = "WATCH"
    else:
        expected = "NONE"
    assert board_tier == expected, (
        f"Expected board_tier {expected} for heat_score {heat_score}, got {board_tier}"
    )


def assert_greenlight_ready_consistent(project: dict) -> None:
    """greenlight_ready is true exactly when rights are OWNED and a draft/polish is in."""
    expected = (
        project["rights_status"] == "OWNED"
        and project["development_status"] in ("DRAFT_DELIVERED", "POLISH_DELIVERED")
    )
    assert project["greenlight_ready"] is expected, (
        "greenlight_ready must be true exactly when rights_status is OWNED and "
        f"development_status is DRAFT_DELIVERED or POLISH_DELIVERED; got "
        f"{project['rights_status']}/{project['development_status']} with "
        f"greenlight_ready={project['greenlight_ready']}"
    )


def raw_weighted_score(
    logline: int, structure: int, character: int, dialogue: int, marketability: int
) -> float:
    """The raw weighted craft score, before rounding, calibration or clamping."""
    return (
        SCORE_WEIGHTS["logline"] * logline
        + SCORE_WEIGHTS["structure"] * structure
        + SCORE_WEIGHTS["character"] * character
        + SCORE_WEIGHTS["dialogue"] * dialogue
        + SCORE_WEIGHTS["marketability"] * marketability
    )


def expected_calibration_bias(approved_composite_scores) -> float:
    """Mean composite score of approved reports less the 5.50 anchor."""
    scores = list(approved_composite_scores)
    if not scores:
        return 0.00
    return round(sum(scores) / len(scores) - CALIBRATION_ANCHOR + 1e-9, 2)


def assert_milestone_schedule_reconciles(rows, total_fee_cents: int) -> None:
    """The sum of gross_amount_cents across an engagement's milestones is exact."""
    total = sum(row["gross_amount_cents"] for row in rows)
    assert total == total_fee_cents, (
        f"Expected the milestone schedule to sum to total_fee_cents "
        f"{total_fee_cents}, got {total}"
    )


def assert_recommendation_bonus_known(recommendation: str) -> None:
    assert recommendation in RECOMMENDATION_BONUS, (
        f"Unknown recommendation {recommendation}"
    )
