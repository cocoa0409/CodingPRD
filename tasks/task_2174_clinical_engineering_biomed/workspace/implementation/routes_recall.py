"""Recall / hazard-alert governance (PRD 3.7)."""
from __future__ import annotations

from flask import Blueprint

import services
import validate as v
from auth import authenticate, current_user
from common import respond, respond_list
from errors import ApiError
from store import store

bp = Blueprint("recalls", __name__)

HAZARD_CLASSES = ("CLASS_I", "CLASS_II", "CLASS_III")
RECALL_STATUSES = ("DRAFT", "PUBLISHED", "MANDATORY_REMOVAL", "MONITORING", "CLOSED")
DISPOSITIONS = ("PENDING", "REMOVED", "REMEDIATED", "EXEMPTED")
TERMINAL_DISPOSITIONS = ("REMOVED", "REMEDIATED", "EXEMPTED")


@bp.post("/recall-notices")
def create_recall_notice():
    authenticate(["CEManager"])
    payload = v.body(
        required=("facility_id", "device_model_id", "source_reference",
                  "hazard_class", "response_due_at"),
        optional=("affected_lot_numbers",),
    )
    facility_id = v.req_id(payload, "facility_id")
    model_id = v.req_id(payload, "device_model_id")
    source_reference = v.req_str(payload, "source_reference")
    hazard_class = v.req_enum(payload, "hazard_class", HAZARD_CLASSES)
    response_due_at, _ = v.req_dt(payload, "response_due_at")
    lots = v.req_str_array(payload, "affected_lot_numbers", [])

    store.require("Facility", facility_id)
    store.require("DeviceModel", model_id)

    record = store.new_record("RecallNotice", {
        "facility_id": facility_id,
        "device_model_id": model_id,
        "source_reference": source_reference,
        "hazard_class": hazard_class,
        "affected_lot_numbers": lots,
        "response_due_at": response_due_at,
        "published_at": None,
        "status": "DRAFT",
        "matched_device_count": 0,
        "pending_match_count": 0,
    })
    return respond(record, 201)


@bp.get("/recall-notices/<rid>")
def read_recall_notice(rid):
    authenticate(["CEManager", "BiomedTech"])
    return respond(store.require("RecallNotice", rid))


@bp.get("/recall-notices")
def list_recall_notices():
    authenticate(["CEManager", "BiomedTech"])
    limit, offset = v.pagination()
    facility_id = v.query_str("facility_id")
    model_id = v.query_str("device_model_id")
    status = v.query_enum("status", RECALL_STATUSES)
    records = store.ordered([
        n for n in store.all("RecallNotice")
        if (facility_id is None or n["facility_id"] == facility_id)
        and (model_id is None or n["device_model_id"] == model_id)
        and (status is None or n["status"] == status)
    ])
    return respond_list(records, limit, offset)


@bp.post("/recall-notices/<rid>/publish")
def publish_recall_notice(rid):
    authenticate(["CEManager"])
    notice = store.require("RecallNotice", rid)
    v.body()
    if notice["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_RECALL_STATE", "Only a DRAFT notice may be published.")

    candidates = [
        d for d in store.all("Device")
        if d["facility_id"] == notice["facility_id"]
        and d["device_model_id"] == notice["device_model_id"]
        and d["operational_state"] != "RETIRED"
    ]
    lots = notice["affected_lot_numbers"] or []
    if len(lots) == 0:
        matched = candidates
        match_basis = "MODEL_ONLY"
    else:
        matched = [d for d in candidates if d.get("lot_number") in lots]
        match_basis = "MODEL_AND_LOT"
    matched.sort(key=lambda d: (d["acquisition_date"], d["created_at"], d["_seq"]))

    for device in matched:
        store.new_record("RecallMatch", {
            "recall_notice_id": notice["id"],
            "device_id": device["id"],
            "match_basis": match_basis,
            "disposition": "PENDING",
            "disposed_at": None,
            "disposed_by_user_id": None,
        })

    notice["published_at"] = store.now_iso()
    notice["matched_device_count"] = len(matched)
    notice["pending_match_count"] = len(matched)

    if notice["hazard_class"] == "CLASS_I":
        notice["status"] = "MANDATORY_REMOVAL"
        newly_downed = []
        for device in matched:
            device["recall_hold"] = True
            if device["operational_state"] in ("IN_SERVICE", "ON_LOAN"):
                device["operational_state"] = "DOWN"
                newly_downed.append(device)
            store.touch(device)
        for device in newly_downed:
            services.cancel_loaners_lending_device(device["id"])
        for device in matched:
            services.defer_pm_tasks_for_recall(device["id"])
        facility = store.get("Facility", notice["facility_id"])
        if facility is not None:
            facility["open_class_i_recall_count"] = facility["open_class_i_recall_count"] + 1
            services.escalate_posture(facility)
            store.touch(facility)
    else:
        notice["status"] = "MONITORING"
        for device in matched:
            device["recall_hold"] = True
            store.touch(device)

    store.touch(notice)
    return respond(notice)


@bp.post("/recall-notices/<rid>/close")
def close_recall_notice(rid):
    authenticate(["CEManager"])
    notice = store.require("RecallNotice", rid)
    v.body()
    if notice["status"] not in ("MANDATORY_REMOVAL", "MONITORING"):
        raise ApiError("ERR_INVALID_RECALL_STATE",
                       "Only a MANDATORY_REMOVAL or MONITORING notice may be closed.")
    if notice["pending_match_count"] > 0:
        raise ApiError("ERR_RECALL_MATCHES_PENDING",
                       "Every recall match must carry a terminal disposition first.")
    came_from_mandatory = notice["status"] == "MANDATORY_REMOVAL"
    notice["status"] = "CLOSED"
    store.touch(notice)
    if came_from_mandatory:
        facility = store.get("Facility", notice["facility_id"])
        if facility is not None:
            facility["open_class_i_recall_count"] = facility["open_class_i_recall_count"] - 1
            store.touch(facility)
    return respond(notice)


# -------------------------------------------------------------- RecallMatch
@bp.get("/recall-matches/<mid>")
def read_recall_match(mid):
    authenticate(["CEManager", "BiomedTech"])
    return respond(store.require("RecallMatch", mid))


@bp.get("/recall-matches")
def list_recall_matches():
    authenticate(["CEManager", "BiomedTech"])
    limit, offset = v.pagination()
    notice_id = v.query_str("recall_notice_id")
    device_id = v.query_str("device_id")
    disposition = v.query_enum("disposition", DISPOSITIONS)
    records = store.ordered([
        m for m in store.all("RecallMatch")
        if (notice_id is None or m["recall_notice_id"] == notice_id)
        and (device_id is None or m["device_id"] == device_id)
        and (disposition is None or m["disposition"] == disposition)
    ])
    return respond_list(records, limit, offset)


@bp.post("/recall-matches/<mid>/disposition")
def set_disposition(mid):
    authenticate(["CEManager", "BiomedTech"])
    match = store.require("RecallMatch", mid)
    payload = v.body(required=("disposition",), optional=("note",))
    disposition = v.req_enum(payload, "disposition", TERMINAL_DISPOSITIONS)
    v.opt_str(payload, "note")
    if match["disposition"] != "PENDING":
        raise ApiError("ERR_INVALID_RECALL_MATCH_STATE",
                       "This recall match already carries a terminal disposition.")

    match["disposition"] = disposition
    match["disposed_at"] = store.now_iso()
    match["disposed_by_user_id"] = current_user()
    store.touch(match)

    notice = store.get("RecallNotice", match["recall_notice_id"])
    if notice is not None:
        notice["pending_match_count"] = notice["pending_match_count"] - 1
        store.touch(notice)

    device = store.get("Device", match["device_id"])
    if device is not None:
        if disposition == "REMOVED":
            device["operational_state"] = "RETIRED"
            store.touch(device)
        else:
            still_pending = any(
                m["device_id"] == device["id"] and m["disposition"] == "PENDING"
                for m in store.all("RecallMatch")
            )
            changed = False
            if not still_pending and device["recall_hold"]:
                device["recall_hold"] = False
                changed = True
            if services.conditional_restore(device):
                changed = True
            if changed:
                store.touch(device)
    return respond(match)
