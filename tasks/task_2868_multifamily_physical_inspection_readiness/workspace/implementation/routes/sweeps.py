"""Self-assessment sweeps and the work-order loop (PRD 3.3)."""

from flask import Blueprint

import auth
import calc
import derive
import envelope
import shapes
import store
from errors import ApiError
from routes import common

bp = Blueprint("sweeps", __name__)

SCOPE_AREAS = {
    "UNIT_ONLY": ["UNIT"],
    "INSIDE_OUTSIDE": ["INSIDE", "OUTSIDE"],
    "ALL_AREAS": ["UNIT", "INSIDE", "OUTSIDE"],
}
LIVE_SWEEP_STATUSES = ("PLANNED", "IN_PROGRESS")


def _capacity_exceeded(property_id, start, end):
    """At most SWEEP_OVERLAP_CAPACITY live sweeps may cover one instant."""
    intervals = []
    for row in store.sweeps.values():
        if row["property_id"] != property_id:
            continue
        if row["status"] not in LIVE_SWEEP_STATUSES:
            continue
        other_start = store.parse_instant(row["window_start"])
        other_end = store.parse_instant(row["window_end"])
        if calc.half_open_overlap(start, end, other_start, other_end):
            intervals.append((other_start, other_end))
    if len(intervals) < calc.SWEEP_OVERLAP_CAPACITY:
        return False
    probes = [start] + [s for (s, _e) in intervals if start < s < end]
    for probe in probes:
        depth = len([1 for (s, e) in intervals if s <= probe < e])
        if depth >= calc.SWEEP_OVERLAP_CAPACITY:
            return True
    return False


@bp.post("/self-assessment-sweeps")
def plan_sweep():
    user_id, role = auth.authenticate([auth.OWNER, auth.ADMIN])
    values = shapes.validate(
        [
            shapes.F("property_id", "string"),
            shapes.F("window_start", "datetime"),
            shapes.F("window_end", "datetime"),
            shapes.F("planned_area_scope", "enum", values=shapes.PLANNED_AREA_SCOPE),
        ]
    )
    prop = common.body_fetch("property", values["property_id"])
    auth.require_owner(role, user_id, prop["id"])
    start = shapes.instant(values, "window_start")
    end = shapes.instant(values, "window_end")
    if end <= start:
        raise ApiError(
            "ERR_INVALID_TIME_WINDOW", "window_end must be strictly after window_start."
        )
    if _capacity_exceeded(prop["id"], start, end):
        raise ApiError(
            "ERR_SWEEP_CAPACITY_EXCEEDED",
            "At most two live sweeps on a property may cover any single instant.",
        )
    row = {
        "property_id": prop["id"],
        "status": "PLANNED",
        "window_start": values["window_start"],
        "window_end": values["window_end"],
        "planned_area_scope": values["planned_area_scope"],
        "started_at": None,
        "closed_at": None,
        "generated_work_order_count": 0,
        "open_work_order_count": 0,
        "verified_work_order_count": 0,
        "void_work_order_count": 0,
        "closure_verified_rate": calc.d("100.00"),
        "urgent_work_order_count": 0,
    }
    store.stamp_new(row)
    store.sweeps[row["id"]] = row
    return envelope.created(row)


@bp.get("/self-assessment-sweeps/<sweep_id>")
def read_sweep(sweep_id):
    user_id, role = auth.authenticate(auth.ANY_ROLE)
    sweep = common.fetch("sweep", sweep_id)
    auth.require_owner(role, user_id, sweep["property_id"])
    return envelope.ok(sweep)


@bp.get("/self-assessment-sweeps")
def list_sweeps():
    user_id, role = auth.authenticate(auth.ANY_ROLE)
    return common.listing(
        store.sweeps.values(),
        ["property_id", "status"],
        role=role,
        user_id=user_id,
        property_getter=lambda r: r["property_id"],
    )


@bp.post("/self-assessment-sweeps/<sweep_id>/start")
def start_sweep(sweep_id):
    user_id, role = auth.authenticate([auth.OWNER, auth.ADMIN])
    values = shapes.validate([shapes.F("started_at", "datetime")])
    sweep = common.fetch("sweep", sweep_id)
    auth.require_owner(role, user_id, sweep["property_id"])
    if sweep["status"] != "PLANNED":
        raise ApiError("ERR_SWEEP_INVALID_STATE", "Only a PLANNED sweep may be started.")
    sweep["status"] = "IN_PROGRESS"
    sweep["started_at"] = values["started_at"]
    store.touch(sweep, bump_version=True)
    return envelope.ok(sweep)


@bp.post("/self-assessment-sweeps/<sweep_id>/findings")
def file_finding(sweep_id):
    user_id, role = auth.authenticate([auth.OWNER, auth.TECHNICIAN])
    values = shapes.validate(
        [
            shapes.F("expected_sweep_version", "integer"),
            shapes.F("defect_definition_id", "string"),
            shapes.F("inspectable_area", "enum", values=shapes.INSPECTABLE_AREA),
            shapes.F("observed_at", "datetime"),
            shapes.F("unit_id", "string", required=False),
            shapes.F("supersedes_deficiency_id", "string", required=False),
            shapes.F("note", "string", required=False),
        ]
    )
    sweep = common.fetch("sweep", sweep_id)
    definition = common.body_fetch("definition", values["defect_definition_id"])
    unit = None
    if values.get("unit_id"):
        unit = common.body_fetch("unit", values["unit_id"])
    if values.get("supersedes_deficiency_id"):
        common.body_fetch("deficiency", values["supersedes_deficiency_id"])
    auth.require_owner(role, user_id, sweep["property_id"])
    if sweep["status"] != "IN_PROGRESS":
        raise ApiError(
            "ERR_SWEEP_INVALID_STATE", "Findings may only be filed on an IN_PROGRESS sweep."
        )
    if values["expected_sweep_version"] != sweep["version"]:
        raise ApiError(
            "ERR_STALE_SWEEP_VERSION",
            "expected_sweep_version does not match the sweep's current version.",
        )
    standard = store.standards.get(definition["standard_id"])
    if standard is None or standard["adoption_status"] != "ADOPTED":
        raise ApiError(
            "ERR_STANDARD_NOT_ADOPTED",
            "The cited definition's standard is not ADOPTED.",
        )
    area = values["inspectable_area"]
    if area != definition["inspectable_area"]:
        raise ApiError(
            "ERR_AREA_MISMATCH",
            "inspectable_area must equal the cited definition's inspectable_area.",
        )
    if (area == "UNIT") != bool(values.get("unit_id")):
        raise ApiError(
            "ERR_AREA_MISMATCH",
            "unit_id must be present exactly when inspectable_area is UNIT.",
        )
    if area not in SCOPE_AREAS[sweep["planned_area_scope"]]:
        raise ApiError(
            "ERR_AREA_OUT_OF_SCOPE",
            "The area is outside the sweep's planned_area_scope.",
        )

    deficiency = {
        "inspection_id": None,
        "sweep_id": sweep["id"],
        "defect_definition_id": definition["id"],
        "unit_id": values.get("unit_id"),
        "supersedes_deficiency_id": values.get("supersedes_deficiency_id"),
        "source": "SELF_ASSESSMENT",
        "inspectable_area": area,
        "severity": definition["severity"],
        "status": "OPEN",
        "observed_at": values["observed_at"],
        "correction_due_at": calc.add_hours(
            values["observed_at"], definition["correction_deadline_hours"]
        ),
        "corrected_at": None,
        "verified_at": None,
        "points_deducted": calc.deficiency_points(
            definition, area, values.get("supersedes_deficiency_id"), unit
        ),
        "recurrence_applied": bool(values.get("supersedes_deficiency_id")),
        "inspection_version_after_record": None,
        "note": values.get("note"),
    }
    store.stamp_new(deficiency)
    store.deficiencies[deficiency["id"]] = deficiency

    work_order = {
        "sweep_id": sweep["id"],
        "deficiency_id": deficiency["id"],
        "repair_status": "OPEN",
        "verification_status": "UNVERIFIED",
        "priority_tier": "ROUTINE",
        "due_at": deficiency["correction_due_at"],
        "completed_at": None,
        "completed_by_user_id": None,
        "verified_at": None,
        "verified_by_user_id": None,
        "rejection_count": 0,
        "resolution_note": None,
        "void_reason": None,
    }
    store.stamp_new(work_order)
    store.work_orders[work_order["id"]] = work_order

    derive.recompute_sweep_counters(sweep)
    store.touch(sweep, bump_version=True)
    if unit is not None:
        derive.recompute_unit_open_count(unit)
    prop = store.properties.get(sweep["property_id"])
    if prop is not None:
        derive.rederive_property(prop, bump_version=True)
    return envelope.created(work_order)


@bp.post("/self-assessment-sweeps/<sweep_id>/close")
def close_sweep(sweep_id):
    user_id, role = auth.authenticate([auth.OWNER, auth.ADMIN])
    values = shapes.validate([shapes.F("closed_at", "datetime")])
    sweep = common.fetch("sweep", sweep_id)
    auth.require_owner(role, user_id, sweep["property_id"])
    if sweep["status"] == "IN_PROGRESS":
        rate = calc.d(sweep["closure_verified_rate"])
        if rate < calc.SWEEP_CLOSURE_RATE_FLOOR:
            raise ApiError(
                "ERR_SWEEP_CLOSURE_RATE_TOO_LOW",
                "closure_verified_rate must be at least 90.00 to close the sweep.",
            )
        sweep["status"] = "CLOSED"
        sweep["closed_at"] = values["closed_at"]
        store.touch(sweep, bump_version=True)
        prop = store.properties.get(sweep["property_id"])
        if prop is not None:
            prop["last_sweep_closed_at"] = values["closed_at"]
            derive.rederive_property(prop, bump_version=True)
        return envelope.ok(sweep)
    if sweep["status"] == "PLANNED":
        sweep["status"] = "ABANDONED"
        sweep["closed_at"] = values["closed_at"]
        store.touch(sweep, bump_version=True)
        return envelope.ok(sweep)
    raise ApiError(
        "ERR_SWEEP_INVALID_STATE", "A CLOSED or ABANDONED sweep cannot be closed again."
    )
