"""Shift assignments (PRD §3.2): creation under OCC, confirm, cancel, reads."""
from flask import Blueprint, request

import store
from authz import require_ownership, require_roles
from calc import TRAVEL_BUFFER_MINUTES
from envelope import get_body, pagination_params, sort_and_page, success_list, success_object
from errors import (
    raise_err,
    ERR_ASSIGNMENT_OVERLAP,
    ERR_INSPECTOR_INACTIVE,
    ERR_INSPECTOR_NOT_FOUND,
    ERR_INSPECTOR_NOT_QUALIFIED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_SHIFT_ASSIGNMENT_NOT_FOUND,
    ERR_SHIFT_WINDOW_NOT_FOUND,
    ERR_STALE_SHIFT_WINDOW_VERSION,
    ERR_TRAVEL_BUFFER_VIOLATION,
)
from guards import entity_or_404, require_not_suspended, require_not_withdrawn
from store import insert, stamp_new, touch
from validate import require_int, require_string, require_timestamp

bp = Blueprint("shift_assignments", __name__)

READ_ROLES = ("EstablishmentManager", "Inspector", "SupervisoryReviewer", "DistrictManager", "ProgramAdministrator")


def _assignment_or_404(assignment_id):
    return entity_or_404("shift_assignments", assignment_id, ERR_SHIFT_ASSIGNMENT_NOT_FOUND)


def _overlaps(s1, e1, s2, e2):
    """Half-open interval overlap; end == start is continuous, legal coverage."""
    return s1 < e2 and s2 < e1


@bp.post("/inspection/shift-windows/<window_id>/assignments")
def create_assignment(window_id):
    require_roles("ProgramAdministrator")
    # Tier 3: path id existence precedes examination of the body.
    window = entity_or_404("shift_windows", window_id, ERR_SHIFT_WINDOW_NOT_FOUND)
    establishment = store.get("establishments", window["establishment_id"])

    body = get_body()
    inspector_id = require_string(body, "inspector_id")
    line_index = require_int(body, "line_index")
    start_utc = require_timestamp(body, "start_utc")
    end_utc = require_timestamp(body, "end_utc")
    expected_version = require_int(body, "expected_shift_window_version")

    # Tier 3 (cont.): body-supplied FK references.
    inspector = entity_or_404("inspectors", inspector_id, ERR_INSPECTOR_NOT_FOUND)

    # Tier 4: optimistic concurrency on the shift window (PRD §2.8).
    if expected_version != window["version"]:
        raise_err(ERR_STALE_SHIFT_WINDOW_VERSION, "expected_shift_window_version is stale")

    # Tier 5: state gates — inspector ACTIVE; establishment gates (PRD §3.2).
    if inspector["employment_status"] != "ACTIVE":
        raise_err(ERR_INSPECTOR_INACTIVE, "inspector is not ACTIVE")
    require_not_withdrawn(establishment)
    require_not_suspended(establishment)

    # Tier 6: qualification covers every species class of the establishment.
    qualified = set(inspector["species_qualifications"])
    if not set(establishment["species_classes"]).issubset(qualified):
        raise_err(ERR_INSPECTOR_NOT_QUALIFIED, "inspector is not qualified for every species class")

    # Tier 7: interval shape, line range, same-line overlap, travel buffer.
    if not (end_utc > start_utc):
        raise_err(ERR_INVALID_REQUEST, "end_utc must be strictly after start_utc")
    if not (window["start_utc"] <= start_utc < window["end_utc"]):
        raise_err(ERR_INVALID_REQUEST, "start_utc must lie within the shift window")
    if end_utc > window["end_utc"]:
        raise_err(ERR_INVALID_REQUEST, "end_utc must be no later than the window end")
    if not (1 <= line_index <= int(window["planned_line_count"])):
        raise_err(ERR_INVALID_REQUEST, "line_index must be between 1 and planned_line_count")

    for existing in store.all_of("shift_assignments"):
        if existing["status"] == "CANCELLED":
            continue
        if (
            existing["shift_window_id"] == window["id"]
            and existing["line_index"] == line_index
            and _overlaps(existing["start_utc"], existing["end_utc"], start_utc, end_utc)
        ):
            raise_err(ERR_ASSIGNMENT_OVERLAP, "overlapping assignment on the same line")

    buffer_seconds = TRAVEL_BUFFER_MINUTES * 60
    for existing in store.all_of("shift_assignments"):
        if existing["status"] == "CANCELLED" or existing["inspector_id"] != inspector_id:
            continue
        if existing["establishment_id"] == establishment["id"]:
            continue  # same-establishment assignments are exempt
        s2, e2 = existing["start_utc"], existing["end_utc"]
        if _overlaps(start_utc, end_utc, s2, e2):
            raise_err(ERR_TRAVEL_BUFFER_VIOLATION, "overlapping assignment at another establishment")
        gap = (s2 - end_utc).total_seconds() if s2 >= end_utc else (start_utc - e2).total_seconds()
        if gap < buffer_seconds:
            raise_err(ERR_TRAVEL_BUFFER_VIOLATION, "assignment at another establishment within 30 minutes")

    assignment = {
        "shift_window_id": window["id"],
        "establishment_id": window["establishment_id"],  # denormalized at creation
        "inspector_id": inspector_id,
        "line_index": line_index,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "status": "SCHEDULED",
    }
    stamp_new(assignment)
    insert("shift_assignments", assignment)
    # Every assignment creation increments the window's version (PRD §2.8/§2.11).
    touch(window)
    return success_object(assignment, status=201)


@bp.get("/inspection/shift-assignments")
def list_assignments():
    require_roles(*READ_ROLES)
    rows = store.all_of("shift_assignments")
    for param in ("shift_window_id", "establishment_id", "inspector_id", "status"):
        value = request.args.get(param)
        if value is not None:
            rows = [a for a in rows if a.get(param) == value]
    limit, offset = pagination_params()
    page, total = sort_and_page(rows, limit, offset)
    return success_list(page, limit, offset, total)


@bp.get("/inspection/shift-assignments/<assignment_id>")
def get_assignment(assignment_id):
    require_roles(*READ_ROLES)
    return success_object(_assignment_or_404(assignment_id))


@bp.post("/inspection/shift-assignments/<assignment_id>/confirm")
def confirm_assignment(assignment_id):
    user_id, _ = require_roles("Inspector")
    assignment = _assignment_or_404(assignment_id)
    require_ownership(user_id, assignment["inspector_id"])
    establishment = store.get("establishments", assignment["establishment_id"])
    require_not_withdrawn(establishment)
    if assignment["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "confirm requires status SCHEDULED")
    assignment["status"] = "CONFIRMED"
    touch(assignment)
    return success_object(assignment)


@bp.post("/inspection/shift-assignments/<assignment_id>/cancel")
def cancel_assignment(assignment_id):
    require_roles("ProgramAdministrator")
    assignment = _assignment_or_404(assignment_id)
    establishment = store.get("establishments", assignment["establishment_id"])
    require_not_withdrawn(establishment)
    if assignment["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "cancel requires status SCHEDULED")
    assignment["status"] = "CANCELLED"
    touch(assignment)
    return success_object(assignment)
