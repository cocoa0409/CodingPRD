"""Routes: congestion complaints."""

from flask import Blueprint, request

import calcs
import db
from errors import raise_err
from middleware import body_json, require_roles
from response import paginate, sorted_by_created, success

bp = Blueprint("complaints", __name__)

SCORING_VARIANTS = {"EVIDENCE_WEIGHTED", "RECENCY_WEIGHTED"}
CAUSES = {"PLANT", "IN_HOME", "DESTINATION"}


@bp.post("/customer-premises/<rid>/congestion-complaints")
def create_complaint(rid):
    require_roles(["CustomerCare"])
    premise = db.get_or_404(db.customer_premises, rid)
    data = body_json(
        required=[
            ("description", "str", None),
            ("plant_signal", "int", None),
            ("home_signal", "int", None),
            ("destination_signal", "int", None),
        ],
    )
    for f in ("plant_signal", "home_signal", "destination_signal"):
        if data[f] < 0 or data[f] > 100:
            raise_err("ERR_VALIDATION", f"{f} must be in 0..100")
    rec = db.stamp_new({
        "id": db.new_id(),
        "customer_premise_id": premise["id"],
        "description": data["description"],
        "plant_signal": data["plant_signal"],
        "home_signal": data["home_signal"],
        "destination_signal": data["destination_signal"],
        "scoring_variant_used": None,
        "score_plant": None,
        "score_in_home": None,
        "score_destination": None,
        "cause_category": None,
        "status": "INVESTIGATING",
        "resolution_note": None,
        "reopen_count": 0,
    })
    db.congestion_complaints[rec["id"]] = rec
    return success(rec, 201)


@bp.get("/congestion-complaints/<rid>")
def get_complaint(rid):
    require_roles(["Any"])
    rec = db.get_or_404(db.congestion_complaints, rid)
    return success(rec, 200)


@bp.get("/congestion-complaints")
def list_complaints():
    require_roles(["Any"])
    items = list(db.congestion_complaints.values())
    p = request.args.get("customer_premise_id")
    s = request.args.get("status")
    if p:
        items = [c for c in items if c["customer_premise_id"] == p]
    if s:
        items = [c for c in items if c["status"] == s]
    items = sorted_by_created(items)
    page, pag = paginate(items)
    return success(page, 200, is_list=True, pagination=pag)


@bp.post("/congestion-complaints/<rid>/classify")
def classify_complaint(rid):
    require_roles(["CustomerCare"])
    rec = db.get_or_404(db.congestion_complaints, rid)
    data = body_json(
        required=[
            ("scoring_variant", "str", SCORING_VARIANTS),
            ("cause_category", "str", CAUSES),
        ],
    )
    if rec["status"] != "INVESTIGATING":
        raise_err("ERR_INVALID_STATE", "Only INVESTIGATING complaints can be classified")
    sp, sh, sd, cause = calcs.complaint_scores(rec, data["scoring_variant"])
    if data["cause_category"] != cause:
        raise_err("ERR_CAUSE_MISMATCH")
    rec["scoring_variant_used"] = data["scoring_variant"]
    rec["score_plant"] = sp
    rec["score_in_home"] = sh
    rec["score_destination"] = sd
    rec["cause_category"] = cause
    rec["status"] = "CLASSIFIED"
    db.touch(rec)
    return success(rec, 200)


@bp.post("/congestion-complaints/<rid>/resolve")
def resolve_complaint(rid):
    require_roles(["CustomerCare"])
    rec = db.get_or_404(db.congestion_complaints, rid)
    data = body_json(optional=[("resolution_note", "str", None)])
    if rec["status"] != "CLASSIFIED":
        raise_err("ERR_INVALID_STATE", "Only CLASSIFIED complaints can be resolved")
    rec["resolution_note"] = data.get("resolution_note")
    rec["status"] = "RESOLVED"
    db.touch(rec)
    if rec["cause_category"] == "PLANT":
        premise = db.customer_premises[rec["customer_premise_id"]]
        sg_id = premise["service_group_id"]
        if calcs.active_action_for_sg(sg_id) is None:
            action = db.stamp_new({
                "id": db.new_id(),
                "service_group_id": sg_id,
                "action_type": "NODE_SPLIT",
                "origin": "SYSTEM",
                "status": "PROPOSED",
                "target_block_ids": None,
                "target_upstream_config": None,
                "superseded_by_id": None,
                "note": None,
            })
            db.capacity_actions[action["id"]] = action
    return success(rec, 200)


@bp.post("/congestion-complaints/<rid>/reopen")
def reopen_complaint(rid):
    require_roles(["CustomerCare"])
    rec = db.get_or_404(db.congestion_complaints, rid)
    body_json()
    if rec["status"] != "RESOLVED":
        raise_err("ERR_INVALID_STATE", "Only RESOLVED complaints can be reopened")
    rec["status"] = "INVESTIGATING"
    rec["reopen_count"] += 1
    rec["cause_category"] = None
    rec["score_plant"] = None
    rec["score_in_home"] = None
    rec["score_destination"] = None
    db.touch(rec)
    return success(rec, 200)


@bp.post("/congestion-complaints/<rid>/close")
def close_complaint(rid):
    require_roles(["CustomerCare"])
    rec = db.get_or_404(db.congestion_complaints, rid)
    body_json()
    if rec["status"] != "RESOLVED":
        raise_err("ERR_INVALID_STATE", "Only RESOLVED complaints can be closed")
    rec["status"] = "CLOSED"
    db.touch(rec)
    return success(rec, 200)
