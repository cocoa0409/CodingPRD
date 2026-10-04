"""Entity assertions and domain invariant checkers.

validate_created() exists so creation endpoints (PRD §4: "Endpoints that
create a new resource answer 201 Created") are asserted with an explicit 201
— never left at validate_success's 200 default. validate_error_is_one_of is
re-exported for PRD-permitted ambiguity sets.
"""
from decimal import ROUND_HALF_UP, Decimal

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error_is_one_of,
    validate_success,
)

from .constants import SCORE_MAX, SCORE_MIN, SCORE_STEP
from .types import (
    ArtifactType,
    AssessorStatus,
    AssignmentStatus,
    BookingStatus,
    CandidateStatus,
    CertificationStatus,
    ComponentKind,
    CycleStatus,
    ProgramStatus,
    RenewalStatus,
    StipendStatus,
    SubmissionStatus,
)

# Re-exported so tests can pull it from test_helpers in one import.
__all_framework_reexports__ = ["validate_error_is_one_of"]


def validate_created(response) -> dict:
    """Assert a 201 Created envelope and return the data payload."""
    return validate_success(response, 201)


def _enum_values(enum_cls) -> list:
    return [member.value for member in enum_cls]


def assert_common_fields(data: dict, context: str = "resource"):
    """PRD §2.5: id is a bare UUID; created_at/updated_at ISO 8601; version int."""
    assert is_valid_uuid(data.get("id", "")), f"{context}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{context}.created_at must be an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{context}.updated_at must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{context}.version must be an integer >= 1"
    )


def assert_score_on_grid(value, context: str = "score"):
    """PRD §2.6: within [0.00, 4.00] and an exact multiple of 0.25."""
    assert isinstance(value, (int, float)), f"{context} must be numeric"
    assert SCORE_MIN <= value <= SCORE_MAX, (
        f"{context} {value} outside [{SCORE_MIN}, {SCORE_MAX}]"
    )
    steps = Decimal(str(value)) / Decimal(str(SCORE_STEP))
    assert steps == steps.to_integral_value(), (
        f"{context} {value} is off the 0.25 grid"
    )


# ---------------------------------------------------------------------------
# Per-entity shape assertions
# ---------------------------------------------------------------------------
def assert_cycle(data: dict):
    assert_common_fields(data, "CertificationCycle")
    assert isinstance(data.get("code"), str) and data["code"]
    components = data.get("components")
    assert isinstance(components, list) and len(components) >= 1
    for comp in components:
        assert isinstance(comp.get("code"), str)
        assert comp.get("kind") in _enum_values(ComponentKind)
        assert isinstance(comp.get("weight"), (int, float))
    for field in ("submission_window_open", "submission_window_close", "retake_window_close"):
        assert is_iso8601_timestamp(data.get(field, "")), f"cycle.{field} must be ISO 8601"
    assert isinstance(data.get("certification_threshold"), (int, float))
    assert isinstance(data.get("max_attempts_per_component"), int)
    assert data.get("status") in _enum_values(CycleStatus)


def assert_candidate(data: dict):
    assert_common_fields(data, "Candidate")
    for field in ("full_name", "email", "license_number", "license_state", "district_code"):
        assert isinstance(data.get(field), str) and data[field], f"candidate.{field} required"
    assert isinstance(data.get("years_experience"), int)
    assert isinstance(data.get("fte_fraction"), (int, float))
    assert 0.5 <= data["fte_fraction"] <= 1.0
    assert data.get("status") in _enum_values(CandidateStatus)
    assert "eligibility_note" in data


def assert_assessment_center(data: dict):
    assert_common_fields(data, "AssessmentCenter")
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("region_code"), str) and data["region_code"]
    assert isinstance(data.get("slot_capacity"), int) and data["slot_capacity"] >= 1


def assert_booking(data: dict):
    assert_common_fields(data, "AssessmentBooking")
    for field in ("candidate_id", "center_id", "cycle_id"):
        assert is_valid_uuid(data.get(field, "")), f"booking.{field} must be a UUID"
    assert is_iso8601_timestamp(data.get("slot_start_at", ""))
    assert is_iso8601_timestamp(data.get("slot_end_at", ""))
    assert data.get("status") in _enum_values(BookingStatus)
    assert "earned_score" in data
    if data["earned_score"] is not None:
        assert_score_on_grid(data["earned_score"], "booking.earned_score")


def assert_submission(data: dict):
    assert_common_fields(data, "ComponentSubmission")
    assert is_valid_uuid(data.get("candidate_id", ""))
    assert is_valid_uuid(data.get("cycle_id", ""))
    assert isinstance(data.get("component_code"), str) and data["component_code"]
    assert data.get("kind") in _enum_values(ComponentKind)
    assert isinstance(data.get("attempt_number"), int) and data["attempt_number"] >= 1
    assert "prior_submission_id" in data
    assert data.get("status") in _enum_values(SubmissionStatus)
    assert "final_score" in data
    assert "counted_score" in data
    assert isinstance(data.get("superseded"), bool)


def assert_artifact(data: dict):
    """PRD §2.5: artifacts are immutable records — id + created_at only;
    version and updated_at MUST be absent."""
    assert is_valid_uuid(data.get("id", "")), "artifact.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "artifact must not carry updated_at"
    assert "version" not in data, "artifact must not carry version"
    assert is_valid_uuid(data.get("submission_id", ""))
    assert data.get("artifact_type") in _enum_values(ArtifactType)
    assert isinstance(data.get("file_format"), str) and data["file_format"]
    assert isinstance(data.get("file_size_mb"), (int, float)) and data["file_size_mb"] > 0


def assert_assessor(data: dict):
    assert_common_fields(data, "Assessor")
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("email"), str) and data["email"]
    assert isinstance(data.get("home_district_code"), str) and data["home_district_code"]
    assert data.get("status") in _enum_values(AssessorStatus)
    assert isinstance(data.get("calibration_passes"), int)
    assert isinstance(data.get("calibration_failures"), int)
    assert "calibrated_at" in data
    assert isinstance(data.get("open_assignment_count"), int)
    assert isinstance(data.get("scored_read_count"), int)
    assert "exact_agreement_rate" in data
    assert "adjacent_agreement_rate" in data


def assert_benchmark(data: dict):
    assert_common_fields(data, "CalibrationBenchmark")
    assert isinstance(data.get("component_code"), str) and data["component_code"]
    assert isinstance(data.get("content_domain"), str)
    assert_score_on_grid(data.get("known_score"), "benchmark.known_score")
    assert isinstance(data.get("tolerance"), (int, float)) and data["tolerance"] > 0


def assert_assignment(data: dict):
    assert_common_fields(data, "ScoringAssignment")
    assert is_valid_uuid(data.get("assessor_id", ""))
    assert "submission_id" in data and "benchmark_id" in data
    targets = [data.get("submission_id"), data.get("benchmark_id")]
    assert sum(1 for t in targets if t is not None) == 1, (
        "exactly one of submission_id / benchmark_id must be non-null"
    )
    assert isinstance(data.get("read_number"), int) and data["read_number"] >= 1
    assert data.get("status") in _enum_values(AssignmentStatus)
    assert "score" in data
    if data["score"] is not None:
        assert_score_on_grid(data["score"], "assignment.score")
    assert "score_submitted_at" in data
    assert "is_within_tolerance" in data


def assert_certification(data: dict):
    assert_common_fields(data, "Certification")
    assert is_valid_uuid(data.get("candidate_id", ""))
    assert is_valid_uuid(data.get("cycle_id", ""))
    assert data.get("status") in _enum_values(CertificationStatus)
    assert isinstance(data.get("weighted_total_provisional"), (int, float))
    assert "weighted_total_final" in data
    assert "certified_at" in data
    assert "valid_until" in data


def assert_renewal(data: dict):
    assert_common_fields(data, "RenewalApplication")
    assert is_valid_uuid(data.get("certification_id", ""))
    items = data.get("evidence_items")
    assert isinstance(items, list) and len(items) >= 1
    for item in items:
        assert isinstance(item.get("evidence_type"), str)
        assert isinstance(item.get("description"), str)
        assert isinstance(item.get("hours"), (int, float)) and item["hours"] >= 0
    assert isinstance(data.get("total_hours"), (int, float))
    assert data.get("status") in _enum_values(RenewalStatus)
    assert "review_note" in data


def assert_incentive_program(data: dict):
    assert_common_fields(data, "IncentiveProgram")
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("sponsor_state"), str) and data["sponsor_state"]
    assert "sponsor_district_code" in data
    assert isinstance(data.get("budget_total_cents"), int) and data["budget_total_cents"] >= 0
    assert isinstance(data.get("budget_remaining_cents"), int)
    assert isinstance(data.get("base_stipend_cents"), int)
    assert isinstance(data.get("early_bird_multiplier"), (int, float))
    assert "early_bird_deadline" in data
    assert data.get("status") in _enum_values(ProgramStatus)


def assert_stipend(data: dict):
    assert_common_fields(data, "StipendPayment")
    assert is_valid_uuid(data.get("program_id", ""))
    assert is_valid_uuid(data.get("certification_id", ""))
    assert isinstance(data.get("amount_cents"), int) and data["amount_cents"] >= 0
    assert data.get("status") in _enum_values(StipendStatus)


# ---------------------------------------------------------------------------
# Domain invariant / calculation helpers
# ---------------------------------------------------------------------------
def round_half_up(value, places: int) -> Decimal:
    """PRD §2.6: all rounding in the platform is round half up."""
    quantum = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


def expected_weighted_total(score_weight_pairs) -> float:
    """The pinned rounding order of PRD §2.6/§3.7: each component's weighted
    contribution is rounded half up to 3 decimal places FIRST, the rounded
    contributions are summed, and the sum is rounded half up to 2 places.

    score_weight_pairs: iterable of (score, weight) in component array order.
    """
    contributions = [
        round_half_up(Decimal(str(score)) * Decimal(str(weight)), 3)
        for score, weight in score_weight_pairs
    ]
    return float(round_half_up(sum(contributions, Decimal(0)), 2))


def assert_program_budget_invariant(program: dict, stipends: list):
    """PRD §3.8 compensating invariant: budget_remaining_cents plus the summed
    amount_cents of APPROVED and PAID stipends always equals budget_total_cents.
    PROPOSED and REVOKED stipends encumber nothing."""
    encumbered = sum(
        s["amount_cents"]
        for s in stipends
        if s.get("status") in (StipendStatus.APPROVED.value, StipendStatus.PAID.value)
    )
    assert program["budget_remaining_cents"] + encumbered == program["budget_total_cents"], (
        f"budget invariant violated: remaining {program['budget_remaining_cents']} "
        f"+ encumbered {encumbered} != total {program['budget_total_cents']}"
    )


def assert_certification_validity_window(certification: dict, certified_at: str, days: int):
    """valid_until must equal certified_at + VALIDITY_DAYS days (PRD §3.7)."""
    from datetime import datetime, timedelta, timezone

    start = datetime.fromisoformat(certified_at.replace("Z", "+00:00"))
    expected = start + timedelta(days=days)
    actual = datetime.fromisoformat(certification["valid_until"].replace("Z", "+00:00"))
    assert actual == expected, (
        f"valid_until {certification['valid_until']} != certified_at + {days} days "
        f"({expected.astimezone(timezone.utc).isoformat()})"
    )
