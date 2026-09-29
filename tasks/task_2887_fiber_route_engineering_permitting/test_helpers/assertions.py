"""Shape and invariant checkers for every resource this API mints."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    BASIS_POINTS_DENOMINATOR,
    MAKE_READY_CLEARANCE_THRESHOLD_IN,
    MAKE_READY_GRADES,
)

JsonDict = Dict[str, Any]

# Fields present on all nine versioned resources.
VERSIONED_AUDIT_FIELDS = ("id", "created_at", "updated_at", "version")
# The two append-only observation types carry only these.
APPEND_ONLY_AUDIT_FIELDS = ("id", "created_at")


def _assert_instant(value: str, field_name: str) -> None:
    assert isinstance(value, str), f"{field_name} must be a string, got {value!r}"
    assert value.endswith("Z"), f"{field_name} must end with a trailing Z, got {value!r}"
    assert "." not in value, (
        f"{field_name} must be whole-second precision with no fractional digits, got {value!r}"
    )
    assert len(value) == 20, (
        f"{field_name} must render as YYYY-MM-DDTHH:MM:SSZ, got {value!r}"
    )
    assert is_iso8601_timestamp(value), f"{field_name} must be ISO 8601 UTC, got {value!r}"


def _assert_calendar_date(value: str, field_name: str) -> None:
    assert isinstance(value, str), f"{field_name} must be a string, got {value!r}"
    assert len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"{field_name} must be a plain calendar date YYYY-MM-DD, got {value!r}"
    )


def assert_versioned_audit_fields(data: JsonDict, entity: str) -> None:
    for field in VERSIONED_AUDIT_FIELDS:
        assert field in data, f"{entity} must expose {field}"
    assert is_valid_uuid(data["id"]), f"{entity}.id must be a UUID, got {data['id']!r}"
    _assert_instant(data["created_at"], f"{entity}.created_at")
    _assert_instant(data["updated_at"], f"{entity}.updated_at")
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1, got {data['version']!r}"
    )


def assert_append_only_audit_fields(data: JsonDict, entity: str) -> None:
    for field in APPEND_ONLY_AUDIT_FIELDS:
        assert field in data, f"{entity} must expose {field}"
    assert is_valid_uuid(data["id"]), f"{entity}.id must be a UUID, got {data['id']!r}"
    _assert_instant(data["created_at"], f"{entity}.created_at")
    assert "updated_at" not in data, (
        f"{entity} is append-only: updated_at must be absent entirely, not present-and-null"
    )
    assert "version" not in data, (
        f"{entity} is append-only: version must be absent entirely, not present-and-null"
    )


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


def assert_route(data: JsonDict) -> JsonDict:
    assert_versioned_audit_fields(data, "Route")
    for field in (
        "name",
        "topology_objective",
        "target_in_service_date",
        "status",
        "budget_authorized_cents",
        "budget_committed_cents",
        "budget_available_cents",
        "segment_count",
        "design_total_length_feet",
        "total_preliminary_cost_cents",
        "total_bid_ready_cost_cents",
        "scope_locked_at",
        "planned_complexity_index",
        "live_complexity_index",
    ):
        assert field in data, f"Route must expose {field}"
    _assert_calendar_date(data["target_in_service_date"], "Route.target_in_service_date")
    if data["scope_locked_at"] is not None:
        _assert_instant(data["scope_locked_at"], "Route.scope_locked_at")
    for money in (
        "budget_authorized_cents",
        "budget_committed_cents",
        "budget_available_cents",
        "total_preliminary_cost_cents",
        "total_bid_ready_cost_cents",
    ):
        assert isinstance(data[money], int) and not isinstance(data[money], bool), (
            f"Route.{money} must be an integer count of cents, got {data[money]!r}"
        )
    assert_budget_invariant(data)
    return data


def assert_budget_invariant(route: JsonDict) -> None:
    """budget_authorized_cents always equals committed plus available."""

    authorized = route["budget_authorized_cents"]
    committed = route["budget_committed_cents"]
    available = route["budget_available_cents"]
    assert authorized == committed + available, (
        "Budget invariant broken: authorized "
        f"{authorized} != committed {committed} + available {available}"
    )


# ---------------------------------------------------------------------------
# RouteSegment
# ---------------------------------------------------------------------------


def assert_route_segment(data: JsonDict) -> JsonDict:
    assert_versioned_audit_fields(data, "RouteSegment")
    for field in (
        "route_id",
        "sequence_index",
        "street_name",
        "municipality_code",
        "length_feet",
        "terrain_class",
        "planned_work_start_on",
        "planned_work_end_on",
        "predecessor_segment_id",
        "existing_conduit_available",
        "required_authority_type",
        "engineering_status",
        "permit_status",
        "construction_method",
        "moratorium_class",
        "restoration_cost_cents",
        "accepted_obstruction_count",
        "preliminary_cost_cents",
        "bid_ready_cost_cents",
    ):
        assert field in data, f"RouteSegment must expose {field}"
    _assert_calendar_date(data["planned_work_start_on"], "RouteSegment.planned_work_start_on")
    _assert_calendar_date(data["planned_work_end_on"], "RouteSegment.planned_work_end_on")
    assert isinstance(data["restoration_cost_cents"], int), (
        "RouteSegment.restoration_cost_cents must be an integer count of cents, got "
        f"{data['restoration_cost_cents']!r}"
    )
    return data


# ---------------------------------------------------------------------------
# FieldWalkout / PoleObservation
# ---------------------------------------------------------------------------


def assert_field_walkout(data: JsonDict) -> JsonDict:
    assert_versioned_audit_fields(data, "FieldWalkout")
    for field in (
        "segment_id",
        "walked_on",
        "obstruction_count",
        "conduit_available_confirmed",
        "surveyor_note",
        "status",
        "review_round",
        "worst_pole_condition_grade",
        "make_ready_flagged_pole_count",
        "reviewed_by_user_id",
        "rejection_reason",
    ):
        assert field in data, f"FieldWalkout must expose {field}"
    _assert_calendar_date(data["walked_on"], "FieldWalkout.walked_on")
    return data


def assert_pole_observation(data: JsonDict) -> JsonDict:
    assert_append_only_audit_fields(data, "PoleObservation")
    for field in (
        "walkout_id",
        "pole_tag",
        "pole_owner",
        "condition_grade",
        "available_vertical_clearance_in",
        "existing_attachment_count",
        "requires_make_ready",
    ):
        assert field in data, f"PoleObservation must expose {field}"
    assert_requires_make_ready_derivation(data)
    return data


def assert_requires_make_ready_derivation(observation: JsonDict) -> None:
    """requires_make_ready is true when grade is C or D, or clearance < 40 inches."""

    expected = (
        observation["condition_grade"] in MAKE_READY_GRADES
        or observation["available_vertical_clearance_in"] < MAKE_READY_CLEARANCE_THRESHOLD_IN
    )
    assert observation["requires_make_ready"] is expected, (
        "requires_make_ready must be "
        f"{expected} for grade {observation['condition_grade']} at "
        f"{observation['available_vertical_clearance_in']} inches of clearance, got "
        f"{observation['requires_make_ready']!r}"
    )


# ---------------------------------------------------------------------------
# PoleAttachmentApplication / MakeReadyItem
# ---------------------------------------------------------------------------


def assert_pole_attachment_application(data: JsonDict) -> JsonDict:
    assert_versioned_audit_fields(data, "PoleAttachmentApplication")
    for field in (
        "segment_id",
        "pole_owner",
        "pole_count",
        "status",
        "revision_round",
        "committed",
        "submitted_at",
        "owner_note",
        "make_ready_items_subtotal_cents",
        "make_ready_admin_fee_bp",
        "make_ready_admin_fee_cents",
        "make_ready_cost_cents",
        "make_ready_days",
    ):
        assert field in data, f"PoleAttachmentApplication must expose {field}"
    if data["submitted_at"] is not None:
        _assert_instant(data["submitted_at"], "PoleAttachmentApplication.submitted_at")
    if data["make_ready_cost_cents"] is not None:
        assert (
            data["make_ready_cost_cents"]
            == data["make_ready_items_subtotal_cents"] + data["make_ready_admin_fee_cents"]
        ), (
            "make_ready_cost_cents must equal subtotal plus admin fee, got "
            f"{data['make_ready_cost_cents']} vs "
            f"{data['make_ready_items_subtotal_cents']} + {data['make_ready_admin_fee_cents']}"
        )
    return data


def assert_make_ready_item(data: JsonDict) -> JsonDict:
    assert_append_only_audit_fields(data, "MakeReadyItem")
    for field in (
        "application_id",
        "pole_tag",
        "work_class",
        "quantity",
        "unit_cost_cents",
        "lead_days",
        "extended_cost_cents",
    ):
        assert field in data, f"MakeReadyItem must expose {field}"
    return data


# ---------------------------------------------------------------------------
# PermitApplication
# ---------------------------------------------------------------------------


def assert_permit_application(data: JsonDict) -> JsonDict:
    assert_versioned_audit_fields(data, "PermitApplication")
    for field in (
        "segment_id",
        "authority_type",
        "authority_name",
        "work_window_start_on",
        "work_window_end_on",
        "status",
        "revision_round",
        "review_days",
        "submitted_at",
        "decision_due_at",
        "decided_at",
        "decided_by_user_id",
        "decision_note",
        "deemed",
    ):
        assert field in data, f"PermitApplication must expose {field}"
    _assert_calendar_date(
        data["work_window_start_on"], "PermitApplication.work_window_start_on"
    )
    for instant in ("submitted_at", "decision_due_at", "decided_at"):
        if data[instant] is not None:
            _assert_instant(data[instant], f"PermitApplication.{instant}")
    return data


# ---------------------------------------------------------------------------
# MoratoriumWindow
# ---------------------------------------------------------------------------


def assert_moratorium_window(data: JsonDict) -> JsonDict:
    assert_versioned_audit_fields(data, "MoratoriumWindow")
    for field in (
        "municipality_code",
        "street_name",
        "resurfaced_on",
        "starts_on",
        "ends_on",
        "moratorium_class",
        "ordinance_reference",
    ):
        assert field in data, f"MoratoriumWindow must expose {field}"
    for date_field in ("resurfaced_on", "starts_on", "ends_on"):
        _assert_calendar_date(data[date_field], f"MoratoriumWindow.{date_field}")
    return data


# ---------------------------------------------------------------------------
# DesignPackage / SplicePoint
# ---------------------------------------------------------------------------


def assert_design_package(data: JsonDict) -> JsonDict:
    assert_versioned_audit_fields(data, "DesignPackage")
    for field in (
        "route_id",
        "revision",
        "fiber_count_allocated",
        "express_fiber_count",
        "status",
        "assigned_drop_fiber_count",
        "reserve_fiber_count",
        "spare_ratio_bp",
        "splice_point_count",
        "handhole_count",
        "submitted_by_user_id",
        "stamped_by_user_id",
        "stamped_at",
        "stamp_voided_at",
        "return_note",
    ):
        assert field in data, f"DesignPackage must expose {field}"
    for instant in ("stamped_at", "stamp_voided_at"):
        if data[instant] is not None:
            _assert_instant(data[instant], f"DesignPackage.{instant}")
    assert_fiber_invariant(data)
    return data


def assert_fiber_invariant(design: JsonDict) -> None:
    """fiber_count_allocated always equals express + assigned drop + reserve."""

    allocated = design["fiber_count_allocated"]
    express = design["express_fiber_count"]
    assigned = design["assigned_drop_fiber_count"]
    reserve = design["reserve_fiber_count"]
    assert allocated == express + assigned + reserve, (
        "Fiber invariant broken: allocated "
        f"{allocated} != express {express} + assigned {assigned} + reserve {reserve}"
    )


def assert_spare_ratio_bp(design: JsonDict) -> None:
    """spare_ratio_bp is reserve * 10000 / allocated, rounded half up."""

    numerator = design["reserve_fiber_count"] * BASIS_POINTS_DENOMINATOR
    allocated = design["fiber_count_allocated"]
    expected = (2 * numerator + allocated) // (2 * allocated)
    assert design["spare_ratio_bp"] == expected, (
        "spare_ratio_bp must be reserve * 10000 / allocated rounded half up: expected "
        f"{expected}, got {design['spare_ratio_bp']}"
    )


def assert_splice_point(data: JsonDict) -> JsonDict:
    assert_versioned_audit_fields(data, "SplicePoint")
    for field in (
        "design_id",
        "segment_id",
        "station_feet",
        "enclosure_type",
        "fiber_count_dropped",
        "status",
        "voided_at",
    ):
        assert field in data, f"SplicePoint must expose {field}"
    if data["voided_at"] is not None:
        _assert_instant(data["voided_at"], "SplicePoint.voided_at")
    return data


# ---------------------------------------------------------------------------
# AsBuiltRecord
# ---------------------------------------------------------------------------


def assert_as_built_record(data: JsonDict) -> JsonDict:
    assert_versioned_audit_fields(data, "AsBuiltRecord")
    for field in (
        "route_id",
        "design_revision",
        "as_built_length_feet",
        "splice_point_count_field_verified",
        "records_system_reference",
        "status",
        "length_variance_bp",
        "submitted_by_user_id",
        "certified_by_user_id",
        "certification_note",
    ):
        assert field in data, f"AsBuiltRecord must expose {field}"
    assert isinstance(data["length_variance_bp"], int), (
        "AsBuiltRecord.length_variance_bp must be an integer count of basis points, got "
        f"{data['length_variance_bp']!r}"
    )
    return data


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def assert_status(data: JsonDict, expected: str, label: str = "status") -> None:
    assert data[label] == expected, f"Expected {label} {expected}, got {data[label]}"


def assert_version_advanced_by(data: JsonDict, baseline: int, delta: int, entity: str) -> None:
    assert data["version"] == baseline + delta, (
        f"{entity}.version must advance from {baseline} by {delta}, got {data['version']}"
    )


def assert_no_pagination_leak(meta: JsonDict) -> None:
    """Error envelopes carry only api_request_id and api_request_timestamp in meta."""

    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, (
        "The meta object for error responses contains only api_request_id and "
        f"api_request_timestamp, got {sorted(meta.keys())}"
    )


def ids_of(rows: Iterable[JsonDict]) -> list:
    return [row["id"] for row in rows]


def find_by_id(rows: Iterable[JsonDict], target_id: str) -> Optional[JsonDict]:
    for row in rows:
        if row["id"] == target_id:
            return row
    return None
