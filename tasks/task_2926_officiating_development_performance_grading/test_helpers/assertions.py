"""Entity assertions, instant helpers and the PRD's derived-value arithmetic."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

import pytest
from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    CREW_POSITION_WEIGHT,
    ERROR_POSITION_FACTOR,
    ERROR_SCALE,
    EXPERIENCE_CAP,
    GRADE_BASE,
    IMPACT_MULTIPLIER,
    TIER_WEIGHT,
    W_ACCURACY,
    W_AVAILABILITY,
    W_MECHANICS,
    W_PRESENCE,
    W_RULES,
)

# ─── Instants ─────────────────────────────────────────


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating any fractional-second width."""
    assert isinstance(value, str) and value.endswith("Z"), (
        f"Expected an ISO 8601 UTC instant ending in Z, got {value!r}"
    )
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def canonical_instant(value: str) -> str:
    """Normalise an instant to the three-fractional-digit form the PRD mandates,
    so comparisons never hinge on how many digits a server chose to print."""
    parsed = parse_instant(value)
    parsed = parsed.astimezone(timezone.utc)
    return parsed.strftime("%Y-%m-%dT%H:%M:%S.") + f"{parsed.microsecond // 1000:03d}Z"


def assert_instant_equals(actual: str, expected: str, field: str = "timestamp") -> None:
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{field}: expected {canonical_instant(expected)}, "
        f"got {canonical_instant(actual)}"
    )


def shift_instant(value: str, *, hours: float = 0, seconds: float = 0) -> str:
    """Move an instant by hours and/or seconds, returning canonical form."""
    moved = (parse_instant(value) + timedelta(hours=hours, seconds=seconds)).astimezone(
        timezone.utc
    )
    return moved.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moved.microsecond // 1000:03d}Z"


def assert_three_fractional_digits(value: str, field: str = "timestamp") -> None:
    """The PRD serialises every timestamp-bearing field with exactly three
    fractional digits."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert len(value) >= 24 and value.endswith("Z") and value[19] == ".", (
        f"{field} must be an ISO 8601 UTC instant with three fractional digits, "
        f"got {value!r}"
    )
    assert value[20:23].isdigit() and len(value) == 24, (
        f"{field} must carry exactly three fractional digits, got {value!r}"
    )


# ─── Numeric helpers ──────────────────────────────────


def round_half_up(value, places: int = 2) -> float:
    """Round half up, away from zero, as every rounding step in the PRD does."""
    quant = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def assert_two_decimal_number(value, field: str = "value") -> None:
    """Decimal quantities are JSON numbers carried to exactly 2 decimal places."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be a JSON number, got {type(value).__name__} ({value!r})"
    )
    assert_cost_precision(float(value))


def approx2(expected: float):
    return pytest.approx(expected, abs=0.01)


# ─── The PRD's derived arithmetic ─────────────────────


def expected_error_points(grade_code: str, impact: str, position: str) -> float:
    """Grade base x impact multiplier x position factor, rounded once."""
    return round_half_up(
        GRADE_BASE[grade_code] * IMPACT_MULTIPLIER[impact] * ERROR_POSITION_FACTOR[position]
    )


def expected_crew_contribution(
    seasons_experience: int, tier: str, assignment_position: str
) -> float:
    """One assignment's already-rounded contribution to crew strength."""
    return round_half_up(
        min(EXPERIENCE_CAP, seasons_experience)
        * TIER_WEIGHT[tier]
        * CREW_POSITION_WEIGHT[assignment_position]
    )


def expected_crew_strength_index(contributions, crew_size_required: int) -> float:
    """Sum of the rounded contributions divided by the required crew size, and
    rounded again."""
    return round_half_up(sum(contributions) / crew_size_required)


def expected_composite_score(
    mechanics_score: float, rules_score: float, presence_score: float
) -> float:
    return round_half_up(
        mechanics_score * W_MECHANICS
        + rules_score * W_RULES
        + presence_score * W_PRESENCE
    )


def expected_accuracy_index(weighted_error_points: float, graded_play_count: int) -> float:
    if graded_play_count == 0:
        return 100.00
    return round_half_up(
        100.00 - (weighted_error_points / graded_play_count) * ERROR_SCALE
    )


def expected_availability_component(completed_count: int, obligation_total: int) -> float:
    return round_half_up(100.00 * completed_count / max(1, obligation_total))


def expected_raw_composite(accuracy_index: float, availability_component: float) -> float:
    return round_half_up(
        accuracy_index * W_ACCURACY + availability_component * W_AVAILABILITY
    )


# ─── Common resource properties ───────────────────────


def assert_common_fields(data: dict, entity: str = "resource") -> None:
    """`id`, `created_at`, `updated_at` and `version` on a mutable resource."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity}.id must be a server-minted UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp, "
        f"got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp, "
        f"got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_append_only_fields(data: dict, entity: str = "evidence log") -> None:
    """The two append-only evidence logs carry only `id` and `created_at`; they
    have no `updated_at` and no `version` field at all."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity}.id must be a server-minted UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp, "
        f"got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, (
        f"{entity} is append-only and must have no updated_at field"
    )
    assert "version" not in data, (
        f"{entity} is append-only and must have no version field"
    )


# ─── Per-entity assertions ────────────────────────────


def assert_season_program(data: dict) -> None:
    assert_common_fields(data, "season program")
    assert isinstance(data["season_year"], int), "season_year must be an integer"
    assert 1900 <= data["season_year"] <= 2999, "season_year must lie in 1900..2999"
    assert data["status"] in ("CONFIGURING", "OPEN", "POSTSEASON_LOCKED"), (
        f"unexpected season program status {data['status']!r}"
    )
    assert_two_decimal_number(
        data["accuracy_eligibility_threshold"], "accuracy_eligibility_threshold"
    )
    assert_two_decimal_number(data["physical_test_min_score"], "physical_test_min_score")
    assert_two_decimal_number(data["exam_min_score"], "exam_min_score")
    for int_field in (
        "min_graded_plays_for_eligibility",
        "appeal_credits_per_official",
        "appeal_window_hours",
        "replay_decision_limit_seconds",
        "max_team_exposures_per_season",
        "min_rest_hours_between_games",
        "travel_lead_hours",
        "crew_size_required",
        "max_application_returns",
        "clinic_attendance_required",
        "eligible_official_count",
    ):
        assert isinstance(data[int_field], int) and not isinstance(data[int_field], bool), (
            f"{int_field} must be an integer, got {data[int_field]!r}"
        )
        assert data[int_field] >= 0, f"{int_field} must be non-negative"
    assert isinstance(data["reviewable_categories"], list) and data["reviewable_categories"], (
        "reviewable_categories must be a non-empty list"
    )
    for category in data["reviewable_categories"]:
        assert category in ("SCORING_PLAY", "TURNOVER", "PLAYER_SAFETY", "GAME_ADMIN"), (
            f"unexpected reviewable category {category!r}"
        )


def assert_official(data: dict) -> None:
    assert_common_fields(data, "official")
    assert is_valid_uuid(data["season_program_id"]), "season_program_id must be a UUID"
    assert isinstance(data["full_name"], str) and 1 <= len(data["full_name"]) <= 120
    assert data["position"] in ("REFEREE", "UMPIRE", "DOWN_JUDGE"), (
        f"unexpected position {data['position']!r}"
    )
    assert isinstance(data["seasons_experience"], int) and data["seasons_experience"] >= 0
    assert (
        isinstance(data["home_market_code"], str)
        and len(data["home_market_code"]) == 3
        and data["home_market_code"].isupper()
    ), "home_market_code must be exactly three uppercase letters"
    assert data["tier"] in ("TIER_3", "TIER_2", "TIER_1"), (
        f"unexpected tier {data['tier']!r}"
    )
    affiliated = data["affiliated_team_code"]
    assert affiliated is None or (
        isinstance(affiliated, str) and len(affiliated) == 3 and affiliated.isupper()
    ), "affiliated_team_code must be null or three uppercase letters"
    assert data["status"] in (
        "CANDIDATE",
        "ACTIVE",
        "PROBATION",
        "SUSPENDED",
        "RELEASED",
    ), f"unexpected official status {data['status']!r}"
    assert isinstance(data["preseason_cleared"], bool), "preseason_cleared must be boolean"
    assert isinstance(data["open_assignment_count"], int)
    assert data["open_assignment_count"] >= 0, "open_assignment_count must be non-negative"
    assert isinstance(data["appeal_credits_remaining"], int)
    assert data["appeal_credits_remaining"] >= 0, (
        "appeal_credits_remaining must be non-negative"
    )


def assert_training_record(data: dict) -> None:
    assert_append_only_fields(data, "training record")
    assert is_valid_uuid(data["official_id"]), "official_id must be a UUID"
    assert data["record_type"] in ("RULES_CLINIC", "PHYSICAL_TEST", "RULES_EXAM"), (
        f"unexpected record_type {data['record_type']!r}"
    )
    assert isinstance(data["session_code"], str) and 1 <= len(data["session_code"]) <= 40
    if data["record_type"] == "RULES_CLINIC":
        assert data.get("score") is None, "a clinic attendance carries no score"
    else:
        assert_two_decimal_number(data["score"], "score")
        assert 0.00 <= data["score"] <= 100.00, "score must lie in 0.00..100.00"
    assert isinstance(data["passed"], bool), "passed must be boolean"


def assert_advancement_application(data: dict) -> None:
    assert_common_fields(data, "advancement application")
    assert is_valid_uuid(data["official_id"]), "official_id must be a UUID"
    assert data["target_tier"] in ("TIER_2", "TIER_1"), (
        f"unexpected target_tier {data['target_tier']!r}"
    )
    assert data["status"] in (
        "SUBMITTED",
        "SCREENED",
        "COMMITTEE_REVIEW",
        "RETURNED_FOR_TAPE",
        "APPROVED",
        "DENIED",
    ), f"unexpected application status {data['status']!r}"
    assert isinstance(data["return_count"], int) and data["return_count"] >= 0
    if data["evaluation_average"] is not None:
        assert_two_decimal_number(data["evaluation_average"], "evaluation_average")
    if data.get("screened_at") is not None:
        assert is_iso8601_timestamp(data["screened_at"]), "screened_at must be ISO 8601"


def assert_field_evaluation(data: dict) -> None:
    assert_append_only_fields(data, "field evaluation report")
    assert is_valid_uuid(data["application_id"]), "application_id must be a UUID"
    assert isinstance(data["evaluator_user_id"], str) and data["evaluator_user_id"]
    for score_field in ("mechanics_score", "rules_score", "presence_score", "composite_score"):
        assert_two_decimal_number(data[score_field], score_field)
        assert 0.00 <= data[score_field] <= 100.00, f"{score_field} out of range"
    assert data["composite_score"] == approx2(
        expected_composite_score(
            data["mechanics_score"], data["rules_score"], data["presence_score"]
        )
    ), "composite_score must be the weighted sum of the three sub-scores"


def assert_game(data: dict) -> None:
    assert_common_fields(data, "game")
    assert is_valid_uuid(data["season_program_id"]), "season_program_id must be a UUID"
    for code_field in ("home_team_code", "away_team_code", "venue_market_code"):
        assert (
            isinstance(data[code_field], str)
            and len(data[code_field]) == 3
            and data[code_field].isupper()
        ), f"{code_field} must be exactly three uppercase letters"
    assert data["home_team_code"] != data["away_team_code"], (
        "home_team_code and away_team_code must differ"
    )
    assert is_iso8601_timestamp(data["kickoff_utc"]), "kickoff_utc must be ISO 8601"
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "PLAYED", "FINALIZED"), (
        f"unexpected game status {data['status']!r}"
    )
    assert data["crew_posture"] in ("UNDERSTAFFED", "STAFFED", "LOCKED"), (
        f"unexpected crew_posture {data['crew_posture']!r}"
    )
    assert isinstance(data["confirmed_crew_count"], int)
    assert data["confirmed_crew_count"] >= 0, "confirmed_crew_count must be non-negative"
    assert_two_decimal_number(data["crew_strength_index"], "crew_strength_index")
    assert data["crew_strength_index"] >= 0, "crew_strength_index must be non-negative"
    assert data["crew_strength_variant"] in ("PROJECTED", "REALIZED"), (
        f"unexpected crew_strength_variant {data['crew_strength_variant']!r}"
    )


def assert_crew_assignment(data: dict) -> None:
    assert_common_fields(data, "crew assignment")
    assert is_valid_uuid(data["game_id"]), "game_id must be a UUID"
    assert is_valid_uuid(data["official_id"]), "official_id must be a UUID"
    assert data["position"] in ("REFEREE", "UMPIRE", "DOWN_JUDGE"), (
        f"unexpected position {data['position']!r}"
    )
    assert data["status"] in (
        "PROPOSED",
        "CONFIRMED",
        "COMPLETED",
        "WITHDRAWN",
        "SUPERSEDED",
        "VOIDED",
    ), f"unexpected assignment status {data['status']!r}"
    assert is_iso8601_timestamp(data["occupied_from_utc"]), "occupied_from_utc ISO 8601"
    assert is_iso8601_timestamp(data["occupied_until_utc"]), "occupied_until_utc ISO 8601"
    assert parse_instant(data["occupied_from_utc"]) < parse_instant(
        data["occupied_until_utc"]
    ), "the occupancy window must open before it closes"
    if data.get("released_at") is not None:
        assert is_iso8601_timestamp(data["released_at"]), "released_at must be ISO 8601"


def assert_play_grade(data: dict) -> None:
    assert_common_fields(data, "play grade")
    assert is_valid_uuid(data["game_id"]), "game_id must be a UUID"
    assert is_valid_uuid(data["official_id"]), "official_id must be a UUID"
    assert isinstance(data["play_ref"], str) and 1 <= len(data["play_ref"]) <= 40
    assert data["call_category"] in (
        "HOLDING",
        "PASS_INTERFERENCE",
        "ROUGHING_PASSER",
        "FALSE_START",
    ), f"unexpected call_category {data['call_category']!r}"
    assert data["grade_code"] in (
        "CORRECT",
        "INCORRECT_CALL",
        "MISSED_CALL",
        "INADVERTENT_WHISTLE",
    ), f"unexpected grade_code {data['grade_code']!r}"
    assert data["impact"] in ("LOW", "MEDIUM", "HIGH", "GAME_CRITICAL"), (
        f"unexpected impact {data['impact']!r}"
    )
    assert_two_decimal_number(data["error_points"], "error_points")
    assert data["error_points"] >= 0, "error_points must be non-negative"
    assert data["grade_status"] in ("DRAFT", "POSTED", "FINAL"), (
        f"unexpected grade_status {data['grade_status']!r}"
    )
    assert data["appeal_state"] in (
        "NOT_APPEALED",
        "APPEAL_PENDING",
        "APPEAL_RESOLVED",
    ), f"unexpected appeal_state {data['appeal_state']!r}"
    assert isinstance(data["graded_by_user_id"], str) and data["graded_by_user_id"]
    if data["grade_status"] == "DRAFT":
        assert data["posted_at"] is None, "a draft grade carries a null posted_at"
    else:
        assert is_iso8601_timestamp(data["posted_at"]), "posted_at must be ISO 8601"


def assert_grade_appeal(data: dict) -> None:
    assert_common_fields(data, "grade appeal")
    assert is_valid_uuid(data["play_grade_id"]), "play_grade_id must be a UUID"
    assert isinstance(data["basis_note"], str) and 1 <= len(data["basis_note"]) <= 500
    assert data["status"] in (
        "SUBMITTED",
        "UNDER_REVIEW",
        "UPHELD",
        "OVERTURNED",
        "MODIFIED",
        "WITHDRAWN",
    ), f"unexpected appeal status {data['status']!r}"
    assert is_iso8601_timestamp(data["submitted_at"]), "submitted_at must be ISO 8601"
    if data.get("revised_grade_code") is not None:
        assert data["revised_grade_code"] in (
            "CORRECT",
            "INCORRECT_CALL",
            "MISSED_CALL",
            "INADVERTENT_WHISTLE",
        ), f"unexpected revised_grade_code {data['revised_grade_code']!r}"


def assert_replay_station(data: dict) -> None:
    assert_common_fields(data, "replay station")
    assert isinstance(data["station_code"], str) and 1 <= len(data["station_code"]) <= 20
    assert isinstance(data["concurrent_capacity"], int) and data["concurrent_capacity"] >= 1
    assert data["status"] in ("ONLINE", "OFFLINE"), (
        f"unexpected replay station status {data['status']!r}"
    )
    assert isinstance(data["active_review_count"], int)
    assert data["active_review_count"] >= 0, "active_review_count must be non-negative"


def assert_replay_review(data: dict) -> None:
    assert_common_fields(data, "replay review")
    assert is_valid_uuid(data["game_id"]), "game_id must be a UUID"
    assert is_valid_uuid(data["station_id"]), "station_id must be a UUID"
    assert isinstance(data["play_ref"], str) and 1 <= len(data["play_ref"]) <= 40
    assert data["category"] in (
        "SCORING_PLAY",
        "TURNOVER",
        "PLAYER_SAFETY",
        "GAME_ADMIN",
    ), f"unexpected review category {data['category']!r}"
    assert data["status"] in ("INITIATED", "DECIDED", "EXPIRED"), (
        f"unexpected review status {data['status']!r}"
    )
    assert is_iso8601_timestamp(data["window_open_utc"]), "window_open_utc ISO 8601"
    assert is_iso8601_timestamp(data["window_close_utc"]), "window_close_utc ISO 8601"
    if data["status"] == "INITIATED":
        assert data["decision"] is None, "an initiated review carries a null decision"
        assert data["elapsed_seconds"] is None, (
            "an initiated review carries a null elapsed_seconds"
        )
    else:
        assert isinstance(data["elapsed_seconds"], int) and data["elapsed_seconds"] >= 0
    if data["status"] == "EXPIRED":
        assert data["decision"] is None, "an expired review stores decision as null"
    if data["decision"] is not None:
        assert data["decision"] in ("STANDS", "CONFIRMED", "REVERSED"), (
            f"unexpected replay decision {data['decision']!r}"
        )


def assert_season_record(data: dict) -> None:
    assert_common_fields(data, "season record")
    assert is_valid_uuid(data["official_id"]), "official_id must be a UUID"
    assert is_valid_uuid(data["season_program_id"]), "season_program_id must be a UUID"
    assert isinstance(data["graded_play_count"], int) and data["graded_play_count"] >= 0
    assert_two_decimal_number(data["weighted_error_points"], "weighted_error_points")
    assert_two_decimal_number(data["accuracy_index"], "accuracy_index")
    assert data["accuracy_variant"] in ("PROVISIONAL", "FINAL"), (
        f"unexpected accuracy_variant {data['accuracy_variant']!r}"
    )
    assert isinstance(data["accuracy_eligible"], bool), "accuracy_eligible must be boolean"
    assert isinstance(data["postseason_eligible"], bool), (
        "postseason_eligible must be boolean"
    )
    assert_two_decimal_number(data["availability_component"], "availability_component")
    assert_two_decimal_number(data["retention_score"], "retention_score")
    assert data["retention_score"] >= 0.00, "retention_score is clamped at a floor of 0.00"
    assert data["retention_recommendation"] in ("RETAIN", "DEVELOP", "RELEASE"), (
        f"unexpected retention_recommendation {data['retention_recommendation']!r}"
    )
    assert data["accuracy_index"] == approx2(
        expected_accuracy_index(data["weighted_error_points"], data["graded_play_count"])
    ), "accuracy_index must follow from weighted_error_points and graded_play_count"


def assert_pool_report(data: dict) -> None:
    assert_common_fields(data, "pool report")
    assert is_valid_uuid(data["game_id"]), "game_id must be a UUID"
    assert is_valid_uuid(data["play_grade_id"]), "play_grade_id must be a UUID"
    assert data["report_type"] in ("POOL_REPORT", "RULES_CLARIFICATION"), (
        f"unexpected report_type {data['report_type']!r}"
    )
    assert isinstance(data["body"], str) and 1 <= len(data["body"]) <= 2000
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED"), (
        f"unexpected report status {data['status']!r}"
    )
    if data["status"] == "DRAFT":
        assert data["published_at"] is None, "a drafted report carries a null published_at"


def assert_discipline_action(data: dict) -> None:
    assert_common_fields(data, "discipline action")
    assert is_valid_uuid(data["official_id"]), "official_id must be a UUID"
    assert data["reason_category"] in ("PERFORMANCE", "CONDUCT", "ATTENDANCE"), (
        f"unexpected reason_category {data['reason_category']!r}"
    )
    assert data["severity"] in ("WARNING", "REMEDIATION", "SUSPENSION"), (
        f"unexpected severity {data['severity']!r}"
    )
    if data["severity"] == "SUSPENSION":
        assert isinstance(data["suspension_games"], int) and data["suspension_games"] >= 1
    else:
        assert data["suspension_games"] is None, (
            "suspension_games must be null for a warning and for a remediation"
        )
    assert data["status"] in (
        "OPENED",
        "REMEDIATION_ASSIGNED",
        "REASSESSED",
        "CLEARED",
        "ESCALATED",
        "SUPERSEDED",
    ), f"unexpected discipline status {data['status']!r}"
    assert isinstance(data["remediation_cycle_count"], int)
    assert 0 <= data["remediation_cycle_count"] <= 2, (
        "remediation_cycle_count is capped at two cycles"
    )


# ─── Envelope-level helpers ───────────────────────────


def assert_list_meta(meta: dict, expected_total: Optional[int] = None,
                     expected_limit: Optional[int] = None,
                     expected_offset: Optional[int] = None,
                     expected_has_more: Optional[bool] = None) -> None:
    """`limit` and `offset` as applied, `total_count` before pagination, and
    `has_more` true when matching records remain beyond the page."""
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            f"total_count must count matching records before pagination: "
            f"expected {expected_total}, got {meta['total_count']}"
        )
    if expected_limit is not None:
        assert meta["limit"] == expected_limit, (
            f"limit as applied must be {expected_limit}, got {meta['limit']}"
        )
    if expected_offset is not None:
        assert meta["offset"] == expected_offset, (
            f"offset as applied must be {expected_offset}, got {meta['offset']}"
        )
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more, (
            f"has_more must be {expected_has_more}, got {meta['has_more']}"
        )


def assert_created_at_ascending(rows: list) -> None:
    instants = [parse_instant(row["created_at"]) for row in rows]
    assert instants == sorted(instants), "list results must be ordered created_at ascending"
