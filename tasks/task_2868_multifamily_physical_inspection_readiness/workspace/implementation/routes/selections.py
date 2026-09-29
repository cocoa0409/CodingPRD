"""Tenant notice, access coordination and refusal replacement (PRD 3.5)."""

from flask import Blueprint

import auth
import calc
import derive
import envelope
import shapes
import store
from errors import ApiError
from routes import common

bp = Blueprint("selections", __name__)


def _inspection_of(slot):
    return store.inspections.get(slot["inspection_id"])


def _entry_window_conflict(slot, start, end):
    """Half-open intersection, no buffer, over ACTIVE slots of the same unit."""
    for other in store.selections.values():
        if other["id"] == slot["id"]:
            continue
        if other["unit_id"] != slot["unit_id"]:
            continue
        if other["selection_status"] != "ACTIVE":
            continue
        if not other["access_window_start"] or not other["access_window_end"]:
            continue
        other_start = store.parse_instant(other["access_window_start"])
        other_end = store.parse_instant(other["access_window_end"])
        if calc.half_open_overlap(start, end, other_start, other_end):
            return True
    return False


@bp.get("/sample-selections/<selection_id>")
def read_selection(selection_id):
    user_id, role = auth.authenticate(auth.ANY_ROLE)
    slot = common.fetch("selection", selection_id)
    auth.require_owner(role, user_id, auth.property_of_selection(slot))
    return envelope.ok(slot)


@bp.get("/sample-selections")
def list_selections():
    user_id, role = auth.authenticate(auth.ANY_ROLE)
    return common.listing(
        store.selections.values(),
        [
            "inspection_id",
            "unit_id",
            "replaced_selection_id",
            "selection_basis",
            "selection_status",
            "access_status",
        ],
        role=role,
        user_id=user_id,
        property_getter=auth.property_of_selection,
    )


@bp.post("/sample-selections/<selection_id>/notice")
def record_notice(selection_id):
    user_id, role = auth.authenticate([auth.OWNER])
    values = shapes.validate(
        [
            shapes.F("notice_method", "enum", values=shapes.NOTICE_METHOD),
            shapes.F("notified_at", "datetime"),
            shapes.F("access_window_start", "datetime"),
            shapes.F("access_window_end", "datetime"),
        ]
    )
    slot = common.fetch("selection", selection_id)
    auth.require_owner(role, user_id, auth.property_of_selection(slot))
    if slot["access_status"] != "NOT_NOTIFIED" or slot["selection_status"] != "ACTIVE":
        raise ApiError(
            "ERR_SELECTION_INVALID_STATE",
            "The notice may only be recorded on an ACTIVE, NOT_NOTIFIED slot.",
        )
    insp = _inspection_of(slot)
    if insp is None or insp["status"] not in ("SAMPLED", "NOTIFIED", "IN_PROGRESS"):
        raise ApiError(
            "ERR_INSPECTION_INVALID_STATE",
            "The owning inspection does not admit a tenant notice.",
        )
    start = shapes.instant(values, "access_window_start")
    end = shapes.instant(values, "access_window_end")
    if end <= start:
        raise ApiError(
            "ERR_INVALID_TIME_WINDOW",
            "access_window_end must be strictly after access_window_start.",
        )
    if _entry_window_conflict(slot, start, end):
        raise ApiError(
            "ERR_UNIT_ACCESS_WINDOW_CONFLICT",
            "The entry window overlaps another active slot's window on this unit.",
        )

    slot["access_status"] = "NOTIFIED"
    slot["notice_method"] = values["notice_method"]
    slot["notified_at"] = values["notified_at"]
    slot["access_window_start"] = values["access_window_start"]
    slot["access_window_end"] = values["access_window_end"]
    slot["notice_lead_hours"] = calc.notice_lead_hours(
        store.parse_instant(insp["scheduled_start"]),
        store.parse_instant(values["notified_at"]),
    )
    store.touch(slot, bump_version=True)

    if insp["status"] == "SAMPLED":
        active = [
            s
            for s in derive.inspection_selections(insp["id"])
            if s["selection_status"] == "ACTIVE"
        ]
        if active and all(s["access_status"] == "NOTIFIED" for s in active):
            insp["status"] = "NOTIFIED"
            store.touch(insp, bump_version=True)
    return envelope.ok(slot)


@bp.post("/sample-selections/<selection_id>/access")
def record_access(selection_id):
    auth.authenticate([auth.INSPECTOR])
    values = shapes.validate(
        [
            shapes.F("access_result", "enum", values=shapes.ACCESS_RESULT),
            shapes.F("recorded_at", "datetime"),
            shapes.F("refusal_reason", "string", required=False),
        ]
    )
    slot = common.fetch("selection", selection_id)
    if slot["access_status"] != "NOTIFIED" or slot["selection_status"] != "ACTIVE":
        raise ApiError(
            "ERR_SELECTION_INVALID_STATE",
            "The access outcome may only be recorded on an ACTIVE, NOTIFIED slot.",
        )
    insp = _inspection_of(slot)
    if insp is None or insp["status"] != "IN_PROGRESS":
        raise ApiError(
            "ERR_INSPECTION_INVALID_STATE",
            "Access outcomes may only be recorded on an IN_PROGRESS inspection.",
        )

    if values["access_result"] == "GRANTED":
        slot["access_status"] = "GRANTED"
        slot["access_recorded_at"] = values["recorded_at"]
        store.touch(slot, bump_version=True)
        active = [
            s
            for s in derive.inspection_selections(insp["id"])
            if s["selection_status"] == "ACTIVE"
        ]
        insp["inspected_unit_count"] = len(
            [s for s in active if s["access_status"] == "GRANTED"]
        )
        store.touch(insp, bump_version=True)
        return envelope.ok(slot)

    slot["access_status"] = "REFUSED"
    slot["access_recorded_at"] = values["recorded_at"]
    slot["refusal_reason"] = values.get("refusal_reason")
    candidates = derive.eligible_candidates(insp)
    if candidates:
        highest = 0
        for other in derive.inspection_selections(insp["id"]):
            if other["selection_rank"] > highest:
                highest = other["selection_rank"]
        slot["selection_status"] = "REPLACED"
        replacement = {
            "inspection_id": insp["id"],
            "unit_id": candidates[0]["id"],
            "replaced_selection_id": slot["id"],
            "selection_rank": highest + 1,
            "selection_basis": "REPLACEMENT",
            "selection_status": "ACTIVE",
            "access_status": "NOT_NOTIFIED",
            "notice_method": None,
            "notified_at": None,
            "access_window_start": None,
            "access_window_end": None,
            "notice_lead_hours": None,
            "access_recorded_at": None,
            "refusal_reason": None,
        }
        store.stamp_new(replacement)
        store.selections[replacement["id"]] = replacement
    store.touch(slot, bump_version=True)

    active = [
        s
        for s in derive.inspection_selections(insp["id"])
        if s["selection_status"] == "ACTIVE"
    ]
    insp["refused_unit_count"] = len(
        [s for s in active if s["access_status"] == "REFUSED"]
    )
    insp["sample_size"] = len(active)
    store.touch(insp, bump_version=True)
    return envelope.ok(slot)
