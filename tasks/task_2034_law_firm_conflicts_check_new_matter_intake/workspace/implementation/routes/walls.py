"""Ethical wall endpoints (PRD 3.5)."""

from flask import Blueprint, request

import db
from db import stamp_new, bump, now_iso
from errors import (
    ApiError, invalid, ERR_MATTER_TERMINAL, ERR_WALL_INVALID_STATE,
    ERR_ATTORNEY_ALREADY_EXCLUDED, ERR_ATTORNEY_NOT_EXCLUDED,
)
from middleware import caller, admit, body
from response import ok_object, paginate, sort_by_created
from services.validate import WALL_REASONS, resolve

bp = Blueprint("walls", __name__)


@bp.post("/intake/matters/<mid>/ethical-walls")
def create_wall(mid):
    _, role = caller()
    admit(role, ("ConflictsPartner",))
    matter = resolve(db.store.matters, mid)
    data = body()

    # Tier 6: wall creation rejected on terminal matters.
    if matter["lifecycle_status"] in ("CLOSED", "DECLINED"):
        raise ApiError(ERR_MATTER_TERMINAL, 409,
                       "Cannot create an ethical wall on a CLOSED or "
                       "DECLINED matter")

    # Tier 10: at most one ACTIVE wall per matter.
    for wall in db.store.ethical_walls.values():
        if wall["matter_id"] == matter["id"] and wall["status"] == "ACTIVE":
            raise ApiError(ERR_WALL_INVALID_STATE, 409,
                           "An ACTIVE ethical wall already exists for this "
                           "matter")

    # Tier 12: request shape.
    reason = data.get("reason")
    if reason not in WALL_REASONS:
        raise invalid("reason must be one of " + ", ".join(WALL_REASONS))
    excluded = data.get("excluded_attorney_ids")
    if (not isinstance(excluded, list) or len(excluded) == 0
            or any(not isinstance(a, str) for a in excluded)):
        raise invalid("excluded_attorney_ids must be a non-empty list")
    memo = data.get("memo", "")
    if not isinstance(memo, str):
        raise invalid("memo must be a string")

    # Deduplicated server-side, given order preserved.
    deduped = list(dict.fromkeys(excluded))

    wall = stamp_new({
        "matter_id": matter["id"],
        "reason": reason,
        "memo": memo,
        "excluded_attorney_ids": deduped,
        "status": "ACTIVE",
        "lifted_at": None,
    })
    db.store.ethical_walls[wall["id"]] = wall
    return ok_object(wall, 201)


@bp.get("/intake/matters/<mid>/ethical-walls")
def list_walls(mid):
    _, role = caller()
    # Wall existence is itself confidential: ConflictsPartner + FirmAdmin.
    admit(role, ("ConflictsPartner", "FirmAdmin"))
    resolve(db.store.matters, mid)
    rows = [w for w in db.store.ethical_walls.values()
            if w["matter_id"] == mid]
    return paginate(sort_by_created(rows), request.args)


@bp.post("/intake/ethical-walls/<wid>/transition")
def wall_transition(wid):
    _, role = caller()
    admit(role, ("ConflictsPartner",))
    data = body()
    action = data.get("action")

    wall = resolve(db.store.ethical_walls, wid)

    # Tier 3: attorney_id FK resolution for EXCLUDE/RELEASE.
    attorney_id = data.get("attorney_id")
    if action in ("EXCLUDE", "RELEASE") and attorney_id is not None:
        resolve(db.store.attorneys, attorney_id)

    if action == "LIFT":
        # Tier 6: ACTIVE only (also covers a second LIFT).
        if wall["status"] != "ACTIVE":
            raise ApiError(ERR_WALL_INVALID_STATE, 409,
                           "Only an ACTIVE wall can be lifted")
        wall["status"] = "LIFTED"
        wall["lifted_at"] = now_iso()
        bump(wall)
        return ok_object(wall)

    if action == "EXCLUDE":
        # Tier 6: EXCLUDE after LIFT is rejected as invalid wall state.
        if wall["status"] != "ACTIVE":
            raise ApiError(ERR_WALL_INVALID_STATE, 409,
                           "Cannot exclude on a non-ACTIVE wall")
        if attorney_id is None:
            raise invalid("attorney_id is required for EXCLUDE")
        # Tier 10: already excluded.
        if attorney_id in wall["excluded_attorney_ids"]:
            raise ApiError(ERR_ATTORNEY_ALREADY_EXCLUDED, 409,
                           "Attorney is already excluded by this wall")
        wall["excluded_attorney_ids"].append(attorney_id)
        bump(wall)
        return ok_object(wall)

    if action == "RELEASE":
        if wall["status"] != "ACTIVE":
            raise ApiError(ERR_WALL_INVALID_STATE, 409,
                           "Cannot release on a non-ACTIVE wall")
        if attorney_id is None:
            raise invalid("attorney_id is required for RELEASE")
        # Tier 10: not currently excluded.
        if attorney_id not in wall["excluded_attorney_ids"]:
            raise ApiError(ERR_ATTORNEY_NOT_EXCLUDED, 409,
                           "Attorney is not excluded by this wall")
        wall["excluded_attorney_ids"].remove(attorney_id)
        bump(wall)
        return ok_object(wall)

    raise invalid("action must be EXCLUDE, RELEASE, or LIFT")
