"""Request-payload builders.

Each builder emits only the fields the PRD declares as client input for that
operation, with sane defaults that every other builder can rely on.  Money and
quantity fields are emitted as JSON numbers; calendar dates are ``YYYY-MM-DD``
strings and instants are ISO 8601 UTC at whole-second precision with a trailing
``Z`` and no fractional-second digits.

Pass ``None`` explicitly for an optional field to drop it from the payload, e.g.
``create_segment_payload(route_id=r, predecessor_segment_id=None)`` keeps the key
present with a null value, while ``drop(create_segment_payload(...), "terrain_class")``
removes the key entirely.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

DEFAULTS: Dict[str, Any] = {
    # Route
    "route_name": "Harbor Loop",
    "topology_objective": "RING_CLOSURE",
    "target_in_service_date": "2027-03-01",
    "budget_authorized_cents": 250000000,
    # RouteSegment
    "sequence_index": 1,
    "street_name": "Dock Street",
    "municipality_code": "MUN-014",
    "length_feet": 400,
    "terrain_class": "URBAN_PAVED",
    "planned_work_start_on": "2026-09-15",
    "planned_work_end_on": "2026-09-20",
    # FieldWalkout
    "walked_on": "2026-08-11",
    # PoleObservation
    "pole_tag": "P-001",
    "pole_owner": "TELCO",
    "condition_grade": "B",
    "available_vertical_clearance_in": 45,
    "existing_attachment_count": 2,
    # PoleAttachmentApplication
    "pole_count": 10,
    # PermitApplication
    "authority_type": "MUNICIPAL_ROW",
    "authority_name": "Harbor City Right-of-Way Office",
    "work_window_start_on": "2026-09-15",
    "work_window_end_on": "2026-09-20",
    # MoratoriumWindow
    "resurfaced_on": "2026-06-01",
    "starts_on": "2026-09-01",
    "ends_on": "2026-10-31",
    "moratorium_class": "FULL_RESTORATION",
    "ordinance_reference": "ORD-2026-114",
    # DesignPackage
    "fiber_count_allocated": 288,
    "express_fiber_count": 48,
    # SplicePoint
    "station_feet": 0,
    "enclosure_type": "HANDHOLE",
    "fiber_count_dropped": 24,
    # AsBuiltRecord
    "design_revision": 1,
    "as_built_length_feet": 400,
    "splice_point_count_field_verified": 1,
    "records_system_reference": "NRS-2026-0001",
}


def drop(payload: Dict[str, Any], *field_names: str) -> Dict[str, Any]:
    """Return a copy of ``payload`` with the named keys removed entirely."""

    return {key: value for key, value in payload.items() if key not in field_names}


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


def create_route_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "name": DEFAULTS["route_name"],
            "topology_objective": DEFAULTS["topology_objective"],
            "target_in_service_date": DEFAULTS["target_in_service_date"],
            "budget_authorized_cents": DEFAULTS["budget_authorized_cents"],
        },
        overrides,
    )


def budget_adjustment_payload(delta_cents: int, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"delta_cents": delta_cents, "reason": "revised construction estimate"}, overrides
    )


# ---------------------------------------------------------------------------
# RouteSegment
# ---------------------------------------------------------------------------


def create_segment_payload(route_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "route_id": route_id,
            "sequence_index": DEFAULTS["sequence_index"],
            "street_name": DEFAULTS["street_name"],
            "municipality_code": DEFAULTS["municipality_code"],
            "length_feet": DEFAULTS["length_feet"],
            "terrain_class": DEFAULTS["terrain_class"],
            "planned_work_start_on": DEFAULTS["planned_work_start_on"],
            "planned_work_end_on": DEFAULTS["planned_work_end_on"],
        },
        overrides,
    )


def construction_method_payload(
    method: str, expected_route_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {"method": method, "expected_route_version": expected_route_version}, overrides
    )


# ---------------------------------------------------------------------------
# FieldWalkout / PoleObservation
# ---------------------------------------------------------------------------


def create_walkout_payload(segment_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"segment_id": segment_id, "walked_on": DEFAULTS["walked_on"]}, overrides)


def create_pole_observation_payload(walkout_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "walkout_id": walkout_id,
            "pole_tag": DEFAULTS["pole_tag"],
            "pole_owner": DEFAULTS["pole_owner"],
            "condition_grade": DEFAULTS["condition_grade"],
            "available_vertical_clearance_in": DEFAULTS["available_vertical_clearance_in"],
            "existing_attachment_count": DEFAULTS["existing_attachment_count"],
        },
        overrides,
    )


def walkout_review_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


# ---------------------------------------------------------------------------
# PoleAttachmentApplication / MakeReadyItem
# ---------------------------------------------------------------------------


def create_pole_attachment_application_payload(
    segment_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "segment_id": segment_id,
            "pole_owner": DEFAULTS["pole_owner"],
            "pole_count": DEFAULTS["pole_count"],
        },
        overrides,
    )


def make_ready_item(pole_tag: str, work_class: str, quantity: int) -> Dict[str, Any]:
    return {"pole_tag": pole_tag, "work_class": work_class, "quantity": quantity}


def owner_response_payload(
    outcome: str, make_ready_items: Optional[List[Dict[str, Any]]] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    if make_ready_items is not None:
        payload["make_ready_items"] = make_ready_items
    return _merge(payload, overrides)


def withdraw_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"reason": "corridor abandoned"}, overrides)


# ---------------------------------------------------------------------------
# PermitApplication
# ---------------------------------------------------------------------------


def create_permit_application_payload(segment_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "segment_id": segment_id,
            "authority_type": DEFAULTS["authority_type"],
            "authority_name": DEFAULTS["authority_name"],
            "work_window_start_on": DEFAULTS["work_window_start_on"],
            "work_window_end_on": DEFAULTS["work_window_end_on"],
        },
        overrides,
    )


def permit_review_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


# ---------------------------------------------------------------------------
# MoratoriumWindow
# ---------------------------------------------------------------------------


def create_moratorium_window_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "municipality_code": DEFAULTS["municipality_code"],
            "street_name": DEFAULTS["street_name"],
            "resurfaced_on": DEFAULTS["resurfaced_on"],
            "starts_on": DEFAULTS["starts_on"],
            "ends_on": DEFAULTS["ends_on"],
            "moratorium_class": DEFAULTS["moratorium_class"],
            "ordinance_reference": DEFAULTS["ordinance_reference"],
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# DesignPackage / SplicePoint
# ---------------------------------------------------------------------------


def create_design_package_payload(
    route_id: str, expected_route_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "route_id": route_id,
            "fiber_count_allocated": DEFAULTS["fiber_count_allocated"],
            "express_fiber_count": DEFAULTS["express_fiber_count"],
            "expected_route_version": expected_route_version,
        },
        overrides,
    )


def create_splice_point_payload(design_id: str, segment_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "design_id": design_id,
            "segment_id": segment_id,
            "station_feet": DEFAULTS["station_feet"],
            "enclosure_type": DEFAULTS["enclosure_type"],
            "fiber_count_dropped": DEFAULTS["fiber_count_dropped"],
        },
        overrides,
    )


def return_to_draft_payload(return_note: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"return_note": return_note}, overrides)


# ---------------------------------------------------------------------------
# AsBuiltRecord
# ---------------------------------------------------------------------------


def create_as_built_record_payload(route_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "route_id": route_id,
            "design_revision": DEFAULTS["design_revision"],
            "as_built_length_feet": DEFAULTS["as_built_length_feet"],
            "splice_point_count_field_verified": DEFAULTS["splice_point_count_field_verified"],
            "records_system_reference": DEFAULTS["records_system_reference"],
        },
        overrides,
    )


def certify_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


def clock_payload(to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}
