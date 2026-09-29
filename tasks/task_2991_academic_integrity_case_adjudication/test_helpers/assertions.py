"""Domain assertion helpers.

Envelope convention (PRD §2.2): the framework's `validate_success` already
returns `body["data"]`, so callers must NOT unwrap `["data"]` a second time.
Everything in this module takes an already-unwrapped entity dict, except the
list validators which take the raw `requests.Response`.
"""
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from .api_client import canonical_instant, instants_equal

# ---------------------------------------------------------------------------
# Envelope / meta
# ---------------------------------------------------------------------------


def assert_envelope_meta(response: requests.Response) -> Dict[str, Any]:
    """PRD §2.2: `api_request_id` starts `req_`; the timestamp carries 3 digits."""
    body = response.json()
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        f"meta.api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    ts = meta.get("api_request_timestamp")
    assert is_iso8601_timestamp(ts), f"bad api_request_timestamp {ts!r}"
    assert ts.endswith("Z") and len(ts) == 24, (
        f"api_request_timestamp must carry exactly 3 fractional digits, got {ts!r}"
    )
    return meta


def assert_object_envelope(
    response: requests.Response, expected_status: int = 200
) -> Dict[str, Any]:
    """Validate a single-object success envelope and return `data`."""
    data = validate_success(response, expected_status)
    assert response.json()["response_type"] == "object", (
        f"expected response_type 'object', got {response.json()['response_type']!r}"
    )
    assert_envelope_meta(response)
    assert isinstance(data, dict), f"expected object data, got {type(data)}"
    return data


def assert_array_envelope(
    response: requests.Response, expected_status: int = 200
) -> List[Any]:
    """Validate an array success envelope and return `data`."""
    data = validate_success(response, expected_status)
    assert response.json()["response_type"] == "array", (
        f"expected response_type 'array', got {response.json()['response_type']!r}"
    )
    assert_envelope_meta(response)
    assert isinstance(data, list), f"expected array data, got {type(data)}"
    return data


# ---------------------------------------------------------------------------
# List validators — both paginated and unpaginated flavours
# ---------------------------------------------------------------------------


def validate_list(response: requests.Response) -> Tuple[List[Any], Dict[str, Any]]:
    """Paginated list: full `meta` pagination block is required (PRD §2.3)."""
    return validate_paginated(response)


def validate_unpaginated(response: requests.Response) -> List[Any]:
    """Array read whose `meta` need not carry the pagination counters.

    Use for array responses that the PRD does not describe as paginated
    collections (e.g. an embedded list of children returned by an action).
    """
    return assert_array_envelope(response)


def assert_page(
    response: requests.Response,
    expected_ids: Sequence[str],
    expected_total: Optional[int] = None,
    expected_limit: Optional[int] = None,
    expected_offset: Optional[int] = None,
    expected_has_more: Optional[bool] = None,
    ordered: bool = True,
) -> Tuple[List[Any], Dict[str, Any]]:
    """Assert the exact page contents and pagination counters of a list read."""
    rows, meta = validate_paginated(response)
    ids = [r["id"] for r in rows]
    if ordered:
        assert ids == list(expected_ids), f"expected page {list(expected_ids)}, got {ids}"
    else:
        assert sorted(ids) == sorted(expected_ids), (
            f"expected page members {sorted(expected_ids)}, got {sorted(ids)}"
        )
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            f"expected total_count {expected_total}, got {meta['total_count']}"
        )
    if expected_limit is not None:
        assert meta["limit"] == expected_limit
    if expected_offset is not None:
        assert meta["offset"] == expected_offset
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more, (
            f"expected has_more {expected_has_more}, got {meta['has_more']}"
        )
    return rows, meta


def assert_created_at_ascending(rows: Sequence[Dict[str, Any]]) -> None:
    """PRD §2.3: default ordering is `created_at` ascending."""
    stamps = [canonical_instant(r["created_at"]) for r in rows]
    assert stamps == sorted(stamps), f"rows are not created_at-ascending: {stamps}"


# ---------------------------------------------------------------------------
# Field-level helpers
# ---------------------------------------------------------------------------


def assert_instant_equals(actual: Any, expected: Any, label: str = "instant") -> None:
    """Compare two instants precision-insensitively (PRD §2.4)."""
    assert instants_equal(actual, expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )


def assert_minted_instant(value: Any, label: str = "instant") -> None:
    """A server-minted instant carries exactly three fractional digits."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{label} is not ISO-8601 UTC: {value!r}"
    assert value.endswith("Z") and len(value) == 24, (
        f"{label} must carry exactly 3 fractional digits, got {value!r}"
    )


def assert_two_decimals(value: Any, label: str = "value") -> None:
    """PRD §2.7: percentages and index values carry exactly two decimals."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must cross the wire as a JSON number, got {value!r}"
    )
    assert round(float(value), 2) == float(value), (
        f"{label} must carry at most 2 decimal places, got {value!r}"
    )


def assert_number(value: Any, label: str = "value") -> None:
    """Numbers must never arrive as strings (PRD §2.7)."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be a JSON number, got {value!r} ({type(value).__name__})"
    )


def assert_pct_equals(actual: Any, expected: float, label: str = "pct") -> None:
    assert_two_decimals(actual, label)
    assert float(actual) == float(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_subset(actual: Dict[str, Any], expected: Dict[str, Any]) -> None:
    """Every key in `expected` must be present in `actual` with an equal value."""
    for key, want in expected.items():
        assert key in actual, f"missing field {key!r} in {sorted(actual)}"
        got = actual[key]
        if isinstance(want, str) and isinstance(got, str) and "T" in want:
            assert instants_equal(got, want), f"{key}: expected {want!r}, got {got!r}"
        else:
            assert got == want, f"{key}: expected {want!r}, got {got!r}"


def assert_absent(entity: Dict[str, Any], *field_names: str) -> None:
    """Assert an entity does not expose the given fields at all (PRD §2.5)."""
    for name in field_names:
        assert name not in entity, (
            f"field {name!r} must not appear on this entity, got {entity.get(name)!r}"
        )


# ---------------------------------------------------------------------------
# System-field spines
# ---------------------------------------------------------------------------


def assert_mutable_system_fields(entity: Dict[str, Any]) -> None:
    """The thirteen mutable resource types carry id/created_at/updated_at/version."""
    assert is_valid_uuid(entity.get("id")), f"bad id {entity.get('id')!r}"
    assert_minted_instant(entity.get("created_at"), "created_at")
    assert_minted_instant(entity.get("updated_at"), "updated_at")
    assert isinstance(entity.get("version"), int) and not isinstance(
        entity.get("version"), bool
    ), f"version must be an int, got {entity.get('version')!r}"
    assert entity["version"] >= 1, f"version starts at 1, got {entity['version']}"


def assert_immutable_system_fields(entity: Dict[str, Any]) -> None:
    """EvidenceItem and PanelVote carry only id and created_at (PRD §2.5)."""
    assert is_valid_uuid(entity.get("id")), f"bad id {entity.get('id')!r}"
    assert_minted_instant(entity.get("created_at"), "created_at")
    assert_absent(entity, "updated_at", "version")


# ---------------------------------------------------------------------------
# Per-entity shape assertions.
#
# Each checks the system-field spine, the declared field set, and the JSON
# types the PRD specifies.  `expected` is an optional dict of field values to
# match exactly (delegated to assert_subset).
# ---------------------------------------------------------------------------


def assert_department(
    entity: Dict[str, Any], expected: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    assert_mutable_system_fields(entity)
    for f in ("code", "name", "monitoring_flag"):
        assert isinstance(entity.get(f), str), f"{f} must be a string"
    for f in (
        "enrolled_student_count",
        "faculty_headcount",
        "open_case_count",
    ):
        assert isinstance(entity.get(f), int) and not isinstance(entity.get(f), bool), (
            f"{f} must be an integer, got {entity.get(f)!r}"
        )
    assert_two_decimals(entity.get("training_completion_pct"), "training_completion_pct")
    assert_two_decimals(
        entity.get("reporting_rate_per_1k_submitted"), "reporting_rate_per_1k_submitted"
    )
    if expected:
        assert_subset(entity, expected)
    return entity


def assert_faculty_member(
    entity: Dict[str, Any], expected: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    assert_mutable_system_fields(entity)
    for f in ("department_id", "full_name", "email", "training_status"):
        assert isinstance(entity.get(f), str), f"{f} must be a string"
    assert is_valid_uuid(entity["department_id"])
    assert isinstance(entity.get("reports_submitted_count"), int)
    for f in ("training_completed_at", "training_module_code"):
        assert f in entity, f"missing field {f!r}"
    if expected:
        assert_subset(entity, expected)
    return entity


def assert_student(
    entity: Dict[str, Any], expected: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    assert_mutable_system_fields(entity)
    for f in ("full_name", "email", "program_code", "standing", "transcript_notation"):
        assert isinstance(entity.get(f), str), f"{f} must be a string"
    for f in ("class_year", "prior_upheld_count", "active_sanction_points"):
        assert isinstance(entity.get(f), int) and not isinstance(entity.get(f), bool), (
            f"{f} must be an integer, got {entity.get(f)!r}"
        )
    if expected:
        assert_subset(entity, expected)
    return entity


def assert_course_offering(
    entity: Dict[str, Any], expected: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    assert_mutable_system_fields(entity)
    for f in ("department_id", "instructor_id", "course_code", "term_code"):
        assert isinstance(entity.get(f), str), f"{f} must be a string"
    comps = entity.get("grade_components")
    assert isinstance(comps, list) and comps, "grade_components must be a non-empty list"
    for c in comps:
        assert isinstance(c.get("code"), str)
        assert isinstance(c.get("max_points"), int)
        assert isinstance(c.get("weight_pct"), int)
    if expected:
        assert_subset(entity, expected)
    return entity


def assert_integrity_report(
    entity: Dict[str, Any], expected: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    assert_mutable_system_fields(entity)
    for f in (
        "offering_id",
        "student_id",
        "reporter_id",
        "alleged_violation_type",
        "narrative",
        "incident_at",
        "status",
    ):
        assert isinstance(entity.get(f), str), f"{f} must be a string, got {entity.get(f)!r}"
    scores = entity.get("component_scores")
    assert isinstance(scores, list), "component_scores must be a list"
    for s in scores:
        assert isinstance(s.get("code"), str)
        assert isinstance(s.get("earned_points"), int)
    assert_two_decimals(entity.get("evidence_strength_score"), "evidence_strength_score")
    assert isinstance(entity.get("evidence_complete"), bool), "evidence_complete must be bool"
    assert isinstance(entity.get("resubmission_count"), int)
    for f in ("submitted_at", "returned_at", "triaged_at", "triage_note"):
        assert f in entity, f"missing field {f!r}"
    if expected:
        assert_subset(entity, expected)
    return entity


def assert_evidence_item(
    entity: Dict[str, Any], expected: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """EvidenceItem is immutable: no updated_at, no version (PRD §2.5)."""
    assert_immutable_system_fields(entity)
    for f in ("report_id", "kind", "sha256"):
        assert isinstance(entity.get(f), str), f"{f} must be a string"
    assert isinstance(entity.get("page_count"), int)
    assert "similarity_pct" in entity, "missing field 'similarity_pct'"
    if entity["similarity_pct"] is not None:
        assert_two_decimals(entity["similarity_pct"], "similarity_pct")
    if expected:
        assert_subset(entity, expected)
    return entity


def assert_case(
    entity: Dict[str, Any], expected: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    assert_mutable_system_fields(entity)
    for f in (
        "student_id",
        "offering_id",
        "case_number",
        "origin",
        "pathway",
        "adjudication_status",
        "notation_status",
        "responsibility_finding",
        "finding_basis",
    ):
        assert isinstance(entity.get(f), str), f"{f} must be a string, got {entity.get(f)!r}"
    assert "report_id" in entity, "missing field 'report_id'"
    for f in (
        "hearing_round",
        "cross_course_pattern_points",
        "prior_upheld_count_at_assessment",
        "prior_escalation_points",
        "recommended_ladder_rank",
        "informal_recommended_ladder_rank",
    ):
        assert isinstance(entity.get(f), int) and not isinstance(entity.get(f), bool), (
            f"{f} must be an integer, got {entity.get(f)!r}"
        )
    assert isinstance(entity.get("overturned"), bool), "overturned must be bool"
    for f in (
        "evidence_strength_score",
        "baseline_course_grade_pct",
        "provisional_severity_index",
        "severity_index",
        "informal_severity_index",
    ):
        assert_two_decimals(entity.get(f), f)
    for f in (
        "decided_at",
        "panel_severity_recommendation",
        "pre_appeal_adjudication_status",
        "dismiss_reason",
        "expungement_eligible_at",
    ):
        assert f in entity, f"missing field {f!r}"
    if expected:
        assert_subset(entity, expected)
    return entity


def assert_notification(
    entity: Dict[str, Any], expected: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    assert_mutable_system_fields(entity)
    for f in ("case_id", "kind", "sent_at", "response_deadline_at"):
        assert isinstance(entity.get(f), str), f"{f} must be a string"
    assert isinstance(entity.get("response_window_days"), int)
    assert "acknowledged_at" in entity, "missing field 'acknowledged_at'"
    if expected:
        assert_subset(entity, expected)
    return entity


def assert_advisor_engagement(
    entity: Dict[str, Any], expected: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    assert_mutable_system_fields(entity)
    for f in ("case_id", "advisor_full_name", "advisor_kind", "status"):
        assert isinstance(entity.get(f), str), f"{f} must be a string"
    for f in ("advisor_bar_licensed", "speaking_rights", "reconfirmation_required"):
        assert isinstance(entity.get(f), bool), f"{f} must be bool, got {entity.get(f)!r}"
    assert "decision_reason" in entity, "missing field 'decision_reason'"
    if expected:
        assert_subset(entity, expected)
    return entity


def assert_case_meeting(
    entity: Dict[str, Any], expected: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    assert_mutable_system_fields(entity)
    for f in ("case_id", "instructor_id", "start_at", "end_at", "status"):
        assert isinstance(entity.get(f), str), f"{f} must be a string"
    assert isinstance(entity.get("duration_minutes"), int)
    assert isinstance(entity.get("advisor_present"), bool)
    if expected:
        assert_subset(entity, expected)
    return entity


def assert_hearing_room(
    entity: Dict[str, Any], expected: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    assert_mutable_system_fields(entity)
    assert isinstance(entity.get("code"), str)
    for f in (
        "seat_capacity",
        "buffer_minutes",
        "sessions_per_day_cap",
        "booked_minutes_total",
    ):
        assert isinstance(entity.get(f), int) and not isinstance(entity.get(f), bool), (
            f"{f} must be an integer, got {entity.get(f)!r}"
        )
    if expected:
        assert_subset(entity, expected)
    return entity


def assert_hearing_session(
    entity: Dict[str, Any], expected: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    assert_mutable_system_fields(entity)
    for f in ("case_id", "room_id", "chair_id", "start_at", "end_at", "status"):
        assert isinstance(entity.get(f), str), f"{f} must be a string"
    panelists = entity.get("panelist_ids")
    assert isinstance(panelists, list), "panelist_ids must be a list"
    for p in panelists:
        assert isinstance(p, str), "panelist_ids entries must be strings"
    for f in (
        "required_panel_size",
        "round_number",
        "effective_vote_count",
        "quorum_required",
    ):
        assert isinstance(entity.get(f), int) and not isinstance(entity.get(f), bool), (
            f"{f} must be an integer, got {entity.get(f)!r}"
        )
    for f in ("panel_finding", "panel_severity_recommendation", "adjourn_reason"):
        assert f in entity, f"missing field {f!r}"
    if expected:
        assert_subset(entity, expected)
    return entity


def assert_panel_vote(
    entity: Dict[str, Any], expected: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """PanelVote is immutable: no updated_at, no version (PRD §2.5)."""
    assert_immutable_system_fields(entity)
    for f in ("session_id", "panelist_id", "verdict", "cast_at"):
        assert isinstance(entity.get(f), str), f"{f} must be a string"
    assert "severity_recommendation" in entity, "missing field 'severity_recommendation'"
    if entity["severity_recommendation"] is not None:
        assert isinstance(entity["severity_recommendation"], int)
    if expected:
        assert_subset(entity, expected)
    return entity


def assert_sanction(
    entity: Dict[str, Any], expected: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    assert_mutable_system_fields(entity)
    for f in ("case_id", "kind", "effective_from", "status", "origin"):
        assert isinstance(entity.get(f), str), f"{f} must be a string, got {entity.get(f)!r}"
    assert isinstance(entity.get("ladder_rank"), int)
    for f in (
        "baseline_course_grade_pct",
        "adjusted_course_grade_pct",
        "grade_penalty_delta_pct",
    ):
        assert_two_decimals(entity.get(f), f)
    for f in (
        "replaces_sanction_id",
        "grade_component_code",
        "imposed_at",
        "completed_at",
        "vacated_reason",
    ):
        assert f in entity, f"missing field {f!r}"
    if expected:
        assert_subset(entity, expected)
    return entity


def assert_appeal(
    entity: Dict[str, Any], expected: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    assert_mutable_system_fields(entity)
    for f in ("case_id", "grounds", "statement", "filed_at", "status"):
        assert isinstance(entity.get(f), str), f"{f} must be a string"
    assert isinstance(entity.get("hearing_round_at_filing"), int)
    for f in ("reduced_ladder_rank", "decision_reason", "decided_at"):
        assert f in entity, f"missing field {f!r}"
    if expected:
        assert_subset(entity, expected)
    return entity
