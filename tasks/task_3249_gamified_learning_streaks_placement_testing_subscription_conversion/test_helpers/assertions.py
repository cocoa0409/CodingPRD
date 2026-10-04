"""Entity assertions and domain invariant checkers.

Each ``assert_<entity>`` validates the response shape a client is entitled to
expect from PRD §2.4, §3.x.  They are used by tests and by fixtures that need a
clear failure message when a setup read returns an unexpected shape.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_learner(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Learner.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "Learner.created_at"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "Learner.updated_at"
    assert isinstance(data.get("version"), int), "Learner.version must be an int"
    assert data["program_tier"] in ["FREE", "PLUS_FAMILY", "CERTIFICATION_ELITE"]
    for counter in ("xp_total", "gems_balance", "leaf_count"):
        assert isinstance(data[counter], int), f"Learner.{counter} must be an int"
        assert data[counter] >= 0, f"Learner.{counter} cannot be negative"


def assert_subscription(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Subscription.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "Subscription.created_at"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "Subscription.updated_at"
    assert isinstance(data.get("version"), int), "Subscription.version must be an int"
    assert data["plan_code"] in ["FREE", "PLUS_FAMILY", "CERTIFICATION_ELITE"]
    assert data["status"] in ["FREE", "ACTIVE", "IN_GRACE", "EXPIRED"]
    assert isinstance(data["seats_total"], int) and data["seats_total"] >= 1
    assert isinstance(data["seats_used"], int) and data["seats_used"] >= 0
    assert isinstance(data["limits_removed"], bool)


def assert_family_membership(data: dict):
    assert is_valid_uuid(data.get("id", "")), "FamilyMembership.id must be a UUID"
    assert data["status"] in ["INVITED", "ACTIVE", "REMOVED"]
    assert data["seat_role"] in ["OWNER", "MEMBER"]


def assert_course_unit(data: dict):
    assert is_valid_uuid(data.get("id", "")), "CourseUnit.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "CourseUnit.created_at"
    assert "updated_at" not in data, "CourseUnit carries no updated_at"
    assert "version" not in data, "CourseUnit carries no version"
    assert data["cefr_band"] in ["A1", "A2", "B1", "B2", "C1"]
    assert isinstance(data["unit_index"], int)


def assert_practice_attempt(data: dict):
    assert is_valid_uuid(data.get("id", "")), "PracticeAttempt.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "PracticeAttempt.created_at"
    assert "updated_at" not in data, "PracticeAttempt carries no updated_at"
    assert "version" not in data, "PracticeAttempt carries no version"
    assert data["outcome"] in ["ACCEPTED", "REJECTED_LIMIT", "REJECTED_DECAY_CAP"]
    assert isinstance(data["xp_awarded"], int)


def assert_lesson_node(data: dict):
    assert is_valid_uuid(data.get("id", "")), "LessonNode.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "LessonNode.created_at"
    assert isinstance(data.get("version"), int), "LessonNode.version must be an int"
    assert data["state"] in [
        "LOCKED", "UNLOCKED", "BRONZE", "SILVER", "GOLD", "LEGENDARY", "DECAYED",
    ]
    assert 0 <= data["decay_level"] <= 4, "LessonNode.decay_level is bounded 0..4"
    assert isinstance(data["decay_meter"], int)


def assert_streak_state(data: dict):
    assert is_valid_uuid(data.get("id", "")), "StreakState.id must be a UUID"
    assert isinstance(data.get("version"), int), "StreakState.version must be an int"
    assert data["status"] in [
        "EVALUATING", "QUALIFIED", "FROZEN", "BROKEN", "REPAIRED",
    ]
    assert isinstance(data["current_length"], int) and data["current_length"] >= 0
    assert isinstance(data["freeze_tokens"], int) and data["freeze_tokens"] >= 0


def assert_placement_test(data: dict):
    assert is_valid_uuid(data.get("id", "")), "PlacementTest.id must be a UUID"
    assert isinstance(data.get("version"), int), "PlacementTest.version must be an int"
    assert data["status"] in [
        "CREATED", "IN_PROGRESS", "SCORED", "CALIBRATED", "ABANDONED", "CERTIFIED",
    ]
    assert isinstance(data["total_items"], int)


def assert_league(data: dict):
    assert is_valid_uuid(data.get("id", "")), "League.id must be a UUID"
    assert data["tier"] in ["BRONZE", "SILVER", "GOLD", "SAPPHIRE", "RUBY"]
    assert data["status"] in ["FORMING", "ACTIVE", "SETTLING", "CLOSED"]
    assert isinstance(data["member_count"], int)


def assert_league_standing(data: dict):
    assert is_valid_uuid(data.get("id", "")), "LeagueStanding.id must be a UUID"
    assert data["standing"] in ["GOOD_STANDING", "FLAGGED", "PROMOTED", "DEMOTED"]
    assert data["settled_outcome"] in ["NONE", "PROMOTED", "DEMOTED", "HELD"]
    assert isinstance(data["weekly_xp"], int)


def assert_certification_exam(data: dict):
    assert is_valid_uuid(data.get("id", "")), "CertificationExam.id must be a UUID"
    assert data["product_code"] in ["DET_BASIC", "DET_PRO", "DET_INSTITUTIONAL"]
    assert data["status"] in [
        "PURCHASED", "PROCTORING", "SUBMITTED", "SCORED", "REPORTED", "VOID",
        "EXPIRED",
    ]


def assert_engagement_offer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "EngagementOffer.id must be a UUID"
    assert data["milestone_code"] in [
        "STREAK_7", "STREAK_30", "PLACEMENT_SKIP", "LEAGUE_PROMOTION",
        "HEART_DEPLETION",
    ]
    assert data["status"] in ["ISSUED", "REDEEMED", "EXPIRED", "SUPPRESSED"]
    assert data["scored_tier"] in ["PLUS", "PLUS_FAMILY"]
    assert isinstance(data["discount_pct"], int)


def assert_score_report(data: dict):
    assert is_valid_uuid(data.get("id", "")), "ScoreReport.id must be a UUID"
    assert data["score_band"] in ["NOT_CERTIFIED", "PASS", "STRONG_PASS", "DISTINCTION"]
    assert isinstance(data["raw_score"], int)


# ── Domain invariants ────────────────────────────────────────────────────────

def assert_learner_free_tier_invariants(data: dict):
    """A gated learner's budgets stay inside their declared bounds."""
    assert data["hearts_available"] is None or 0 <= data["hearts_available"] <= 5
    assert data["energy_units"] is None or 0 <= data["energy_units"] <= 30


def assert_subscription_seat_invariant(data: dict):
    assert data["seats_used"] <= data["seats_total"], (
        "seats_used can never exceed seats_total"
    )


def assert_limits_removed_consistent(data: dict):
    """limits_removed is true only for an ACTIVE non-FREE plan."""
    expected = data["status"] == "ACTIVE" and data["plan_code"] != "FREE"
    assert data["limits_removed"] is expected, (
        f"limits_removed should be {expected} for "
        f"{data['status']}/{data['plan_code']}"
    )