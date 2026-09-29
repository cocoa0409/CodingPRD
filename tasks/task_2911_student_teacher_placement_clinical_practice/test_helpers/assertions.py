"""Shape and invariant assertions for this API's resources.

Two things live here that the shared framework cannot supply:

* ``validate_page`` — this API paginates with page / page_size and reports
  page, page_size, total_count and has_more in meta, so the framework's
  limit/offset paginated validator does not apply.
* per-entity shape assertions that check the four common fields (id,
  created_at, updated_at, version) plus that entity's own required members.
"""
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant

COMMON_FIELDS = ("id", "created_at", "updated_at", "version")


# ─── Envelope / pagination ────────────────────────────

def assert_envelope(response) -> Dict[str, Any]:
    """A success body carries meta, response_type and data."""
    body = response.json()
    for member in ("meta", "response_type", "data"):
        assert member in body, f"response envelope has no {member}: {body}"
    return body


def validate_page(response, expected_status: int = 200
                  ) -> Tuple[List[Any], Dict[str, Any]]:
    """Unwrap a list response and assert its page meta shape."""
    body = response.json()
    assert response.status_code == expected_status, (
        f"expected {expected_status}, got {response.status_code}: {body}")
    assert "data" in body and isinstance(body["data"], list), (
        f"list response data must be an array: {body}")
    meta = body.get("meta")
    assert isinstance(meta, dict), f"list response meta must be an object: {body}"
    for member in ("page", "page_size", "total_count", "has_more"):
        assert member in meta, f"page meta has no {member}: {meta}"
    assert isinstance(meta["page"], int), f"page must be an integer: {meta}"
    assert isinstance(meta["page_size"], int), f"page_size must be an integer: {meta}"
    assert isinstance(meta["total_count"], int), (
        f"total_count must be an integer: {meta}")
    assert isinstance(meta["has_more"], bool), f"has_more must be a boolean: {meta}"
    return body["data"], meta


def assert_page_meta(meta: Dict[str, Any], page: int, page_size: int,
                     total_count: int, has_more: bool) -> None:
    assert meta["page"] == page, f"page: expected {page}, got {meta['page']}"
    assert meta["page_size"] == page_size, (
        f"page_size: expected {page_size}, got {meta['page_size']}")
    assert meta["total_count"] == total_count, (
        f"total_count: expected {total_count}, got {meta['total_count']}")
    assert meta["has_more"] is has_more, (
        f"has_more: expected {has_more}, got {meta['has_more']}")


def assert_ids_present(rows: List[Dict[str, Any]], expected_ids: List[str]) -> None:
    got = {row["id"] for row in rows}
    for expected in expected_ids:
        assert expected in got, f"row {expected} missing from {sorted(got)}"


def assert_ids_absent(rows: List[Dict[str, Any]], excluded_ids: List[str]) -> None:
    got = {row["id"] for row in rows}
    for excluded in excluded_ids:
        assert excluded not in got, f"row {excluded} should not appear in {sorted(got)}"


# ─── Common fields ────────────────────────────────────

def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None
                         ) -> None:
    for field in COMMON_FIELDS:
        assert field in entity, f"entity has no {field}: {entity}"
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']}"
    assert_instant_shape(entity["created_at"])
    assert_instant_shape(entity["updated_at"])
    assert isinstance(entity["version"], int), (
        f"version must be an integer: {entity['version']}")
    assert entity["version"] >= 1, f"version starts at 1: {entity['version']}"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"version: expected {expected_version}, got {entity['version']}")


def assert_instant_shape(value: str) -> None:
    """ISO-8601 UTC with a Z suffix and three fractional digits."""
    assert isinstance(value, str), f"instant must be a string: {value!r}"
    assert is_iso8601_timestamp(value), f"not an ISO-8601 UTC instant: {value!r}"
    assert value.endswith("Z"), f"instant must end in Z: {value!r}"
    assert "." in value and len(value.split(".")[1]) == 4, (
        f"instant must carry exactly three fractional digits: {value!r}")


def assert_instant_iso(value: str, label: str = "instant") -> None:
    """A valid ISO-8601 UTC instant, without pinning the fractional width."""
    assert isinstance(value, str), f"{label} must be a string: {value!r}"
    assert is_iso8601_timestamp(value), (
        f"{label} is not an ISO-8601 UTC instant: {value!r}")


def assert_instant_equals(actual: Optional[str], expected: Optional[str],
                          label: str = "instant") -> None:
    """Compare two instants by whole seconds, ignoring fractional width."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected}, got {actual}")


def assert_date_equals(actual: Optional[str], expected: Optional[str],
                       label: str = "date") -> None:
    assert actual == expected, f"{label}: expected {expected}, got {actual}"


def assert_version_bumped(before: Dict[str, Any], after: Dict[str, Any],
                          by: int = 1) -> None:
    assert after["version"] == before["version"] + by, (
        f"version: expected {before['version'] + by}, got {after['version']}")


def assert_unchanged(before: Dict[str, Any], after: Dict[str, Any],
                     fields: List[str]) -> None:
    for field in fields:
        assert after[field] == before[field], (
            f"{field} should be untouched: was {before[field]}, now {after[field]}")


# ─── Money / ratio precision ──────────────────────────

def assert_whole_cents(value: Any, label: str = "amount") -> None:
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be a whole integer number of cents, got {value!r}")


def assert_ratio_precision(value: Any, label: str = "observation_compliance_ratio"
                           ) -> None:
    """A ratio carried to four decimal places."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be a number, got {value!r}")
    assert round(float(value), 4) == float(value), (
        f"{label} must carry at most four decimal places, got {value!r}")


def assert_ratio_equals(actual: Any, expected: float,
                        label: str = "observation_compliance_ratio") -> None:
    assert_ratio_precision(actual, label)
    assert abs(float(actual) - expected) < 1e-9, (
        f"{label}: expected {expected}, got {actual}")


def assert_half_step(value: Any, label: str = "rubric input") -> None:
    """A rubric input arrives in multiples of one half."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be a number, got {value!r}")
    assert (float(value) * 2).is_integer(), (
        f"{label} must be a multiple of 0.5, got {value!r}")


# ─── Entity shapes ────────────────────────────────────

def _assert_members(entity: Dict[str, Any], members: Tuple[str, ...],
                    what: str) -> None:
    for member in members:
        assert member in entity, f"{what} has no {member}: {sorted(entity)}"


def assert_candidate_shape(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity)
    _assert_members(entity, (
        "candidate_code", "full_name", "program_track", "home_grid_x",
        "home_grid_y", "readiness_score", "readiness_status",
        "readiness_variant_used", "licensure_status", "report_status",
        "recommended_by_user_id", "recommended_at", "denial_reason",
        "reported_by_user_id", "reported_at", "reporting_cycle",
        "state_report_deadline"), "candidate")
    assert isinstance(entity["readiness_score"], int), (
        f"readiness_score must be an integer: {entity['readiness_score']}")


def assert_readiness_item_shape(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity)
    _assert_members(entity, (
        "candidate_id", "item_type", "status", "exam_score", "credits",
        "clearance_scope", "issued_on", "expires_on", "verified_by_user_id",
        "verified_at", "rejection_note"), "readiness item")


def assert_district_shape(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity)
    _assert_members(entity, (
        "name", "district_code", "state_code", "requires_district_fingerprint",
        "travel_reimbursement_enabled"), "district")


def assert_agreement_shape(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity)
    _assert_members(entity, (
        "district_id", "term", "window_start", "window_end", "status",
        "placement_cap", "stipend_rate_cents_per_week", "allowed_subjects",
        "allowed_grade_bands", "seats_reserved", "seats_committed",
        "capacity_posture", "stipend_committed_cents", "suspension_reason"),
        "agreement")
    assert_whole_cents(entity["stipend_committed_cents"], "stipend_committed_cents")
    assert_whole_cents(entity["stipend_rate_cents_per_week"],
                       "stipend_rate_cents_per_week")


def assert_teacher_shape(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity)
    _assert_members(entity, (
        "district_id", "full_name", "site_name", "site_grid_x", "site_grid_y",
        "subject_endorsement", "grade_band", "years_experience",
        "consecutive_terms_hosted", "max_concurrent_candidates",
        "qualification_status", "training_completed_on", "training_expires_on",
        "active_placement_count", "disqualification_reason"),
        "cooperating teacher")


def assert_supervisor_shape(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity)
    _assert_members(entity, (
        "full_name", "employment_type", "primary_subject", "covered_grade_bands",
        "home_grid_x", "home_grid_y", "max_travel_miles",
        "max_caseload_points_override", "max_caseload_points", "caseload_points",
        "accepting_new_placements"), "supervisor")
    assert isinstance(entity["caseload_points"], int), (
        f"caseload_points must be an integer: {entity['caseload_points']}")


def assert_request_shape(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity)
    _assert_members(entity, (
        "candidate_id", "preferred_district_id", "term", "requested_subject",
        "requested_grade_band", "max_commute_miles", "term_start_date",
        "weeks_scheduled", "term_end_date", "status", "routing_round",
        "reroute_count", "excluded_cooperating_teacher_ids",
        "current_placement_id"), "placement request")
    assert isinstance(entity["excluded_cooperating_teacher_ids"], list), (
        "excluded_cooperating_teacher_ids must be an array")


def assert_placement_shape(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity)
    _assert_members(entity, (
        "request_id", "candidate_id", "cooperating_teacher_id", "agreement_id",
        "supervisor_id", "replaces_placement_id", "subject", "grade_band",
        "start_date", "end_date", "weeks_scheduled", "commute_miles",
        "supervisor_points", "placement_status", "stipend_status",
        "stipend_variant", "stipend_weekly_cents", "weeks_credited",
        "stipend_gross_cents", "travel_reimbursement_cents",
        "observation_compliance_ratio", "summative_completed_count",
        "removal_reason", "removal_requested_by_role",
        "removal_requested_by_user_id", "removal_decided_by_user_id",
        "removal_narrative", "voided_reason", "settlement_date", "completed_at"),
        "placement")
    assert_whole_cents(entity["stipend_weekly_cents"], "stipend_weekly_cents")
    assert_whole_cents(entity["stipend_gross_cents"], "stipend_gross_cents")
    assert_whole_cents(entity["travel_reimbursement_cents"],
                       "travel_reimbursement_cents")
    assert isinstance(entity["commute_miles"], int), (
        f"commute_miles must be a whole integer of miles: {entity['commute_miles']}")
    assert_ratio_precision(entity["observation_compliance_ratio"])


def assert_cycle_shape(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity)
    _assert_members(entity, (
        "placement_id", "supervisor_id", "sequence_no", "cycle_type",
        "window_start", "window_end", "status", "observed_at", "rubric_score",
        "reschedule_count", "resolution_note"), "observation cycle")


def assert_assessment_shape(entity: Dict[str, Any]) -> None:
    assert_common_fields(entity)
    _assert_members(entity, (
        "placement_id", "window_opens_at", "window_closes_at", "status",
        "attempt_no", "artifact_reference", "submitted_at", "task_planning",
        "task_instruction", "task_assessment", "task_professionalism",
        "total_score", "scored_by_user_id", "scored_at", "returned_feedback"),
        "performance assessment")
    assert isinstance(entity["total_score"], int), (
        f"total_score must be an integer: {entity['total_score']}")


# ─── Domain invariants ────────────────────────────────

def assert_agreement_ledger(agreement: Dict[str, Any], seats_reserved: int,
                            seats_committed: int, stipend_committed_cents: int,
                            capacity_posture: Optional[str] = None) -> None:
    assert agreement["seats_reserved"] == seats_reserved, (
        f"seats_reserved: expected {seats_reserved}, "
        f"got {agreement['seats_reserved']}")
    assert agreement["seats_committed"] == seats_committed, (
        f"seats_committed: expected {seats_committed}, "
        f"got {agreement['seats_committed']}")
    assert agreement["stipend_committed_cents"] == stipend_committed_cents, (
        f"stipend_committed_cents: expected {stipend_committed_cents}, "
        f"got {agreement['stipend_committed_cents']}")
    if capacity_posture is not None:
        assert agreement["capacity_posture"] == capacity_posture, (
            f"capacity_posture: expected {capacity_posture}, "
            f"got {agreement['capacity_posture']}")


def assert_caseload(supervisor: Dict[str, Any], caseload_points: int,
                    max_caseload_points: Optional[int] = None) -> None:
    assert supervisor["caseload_points"] == caseload_points, (
        f"caseload_points: expected {caseload_points}, "
        f"got {supervisor['caseload_points']}")
    if max_caseload_points is not None:
        assert supervisor["max_caseload_points"] == max_caseload_points, (
            f"max_caseload_points: expected {max_caseload_points}, "
            f"got {supervisor['max_caseload_points']}")


def assert_placement_dimensions(placement: Dict[str, Any],
                                placement_status: str,
                                stipend_status: str) -> None:
    """The clinical and money dimensions are read independently."""
    assert placement["placement_status"] == placement_status, (
        f"placement_status: expected {placement_status}, "
        f"got {placement['placement_status']}")
    assert placement["stipend_status"] == stipend_status, (
        f"stipend_status: expected {stipend_status}, "
        f"got {placement['stipend_status']}")


def assert_readiness(candidate: Dict[str, Any], readiness_score: int,
                     readiness_status: str,
                     readiness_variant_used: Optional[str] = None) -> None:
    assert candidate["readiness_score"] == readiness_score, (
        f"readiness_score: expected {readiness_score}, "
        f"got {candidate['readiness_score']}")
    assert candidate["readiness_status"] == readiness_status, (
        f"readiness_status: expected {readiness_status}, "
        f"got {candidate['readiness_status']}")
    if readiness_variant_used is not None:
        assert candidate["readiness_variant_used"] == readiness_variant_used, (
            f"readiness_variant_used: expected {readiness_variant_used}, "
            f"got {candidate['readiness_variant_used']}")


def assert_stipend(placement: Dict[str, Any], variant: Optional[str] = None,
                   weekly_cents: Optional[int] = None,
                   weeks_credited: Optional[int] = None,
                   gross_cents: Optional[int] = None,
                   travel_cents: Optional[int] = None) -> None:
    if variant is not None:
        assert placement["stipend_variant"] == variant, (
            f"stipend_variant: expected {variant}, "
            f"got {placement['stipend_variant']}")
    if weekly_cents is not None:
        assert placement["stipend_weekly_cents"] == weekly_cents, (
            f"stipend_weekly_cents: expected {weekly_cents}, "
            f"got {placement['stipend_weekly_cents']}")
    if weeks_credited is not None:
        assert placement["weeks_credited"] == weeks_credited, (
            f"weeks_credited: expected {weeks_credited}, "
            f"got {placement['weeks_credited']}")
    if gross_cents is not None:
        assert placement["stipend_gross_cents"] == gross_cents, (
            f"stipend_gross_cents: expected {gross_cents}, "
            f"got {placement['stipend_gross_cents']}")
    if travel_cents is not None:
        assert placement["travel_reimbursement_cents"] == travel_cents, (
            f"travel_reimbursement_cents: expected {travel_cents}, "
            f"got {placement['travel_reimbursement_cents']}")
