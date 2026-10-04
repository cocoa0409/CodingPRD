"""Comparability study endpoints (PRD 3.7)."""
from flask import Blueprint, request

import calc_quality
import envelope
import serialize
import store
from auth import require_auth
from constants import AUTHORITIES, CHANGE_TYPES, STUDY_ACTIONS
from errors import err
from validate import action_value, body, must_get, paginate, req_enum

bp = Blueprint("comparability", __name__)


@bp.route("/products/<pid>/comparability-studies", methods=["POST"])
def create_study(pid):
    require_auth(("RegulatoryAffairsSpecialist",))
    product = must_get("product", pid)
    d = body()
    # Existence of body-supplied candidate batch references (stage 3) runs
    # before the remaining well-formedness checks (stage 4).
    raw_candidates = d.get("candidate_batch_ids")
    if isinstance(raw_candidates, list):
        for bid in raw_candidates:
            if isinstance(bid, str):
                must_get("batch", bid)
    change_type = req_enum(d, "change_type", CHANGE_TYPES)
    baseline = d.get("baseline_attribute_values")
    if not isinstance(baseline, list) or len(baseline) < 3:
        err("ERR_INVALID_REQUEST", "baseline_attribute_values needs at least 3 entries")
    for v in baseline:
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            err("ERR_INVALID_REQUEST", "baseline_attribute_values must be numbers")
    if not isinstance(raw_candidates, list) or len(raw_candidates) < 1:
        err("ERR_INVALID_REQUEST", "candidate_batch_ids needs at least 1 entry")
    for bid in raw_candidates:
        if not isinstance(bid, str):
            err("ERR_INVALID_REQUEST", "candidate_batch_ids must be strings")
        must_get("batch", bid)
    rec = store.create_rec("studies", {
        "product_id": product["id"],
        "change_type": change_type,
        "baseline_attribute_values": list(baseline),
        "candidate_batch_ids": list(raw_candidates),
        "status": "PLANNED",
        "authority": None,
        "baseline_mean": None,
        "equivalence_margin": None,
    })
    return envelope.ok(serialize.study(rec), 201)


@bp.route("/products/<pid>/comparability-studies", methods=["GET"])
def list_studies(pid):
    require_auth(("Any",))
    must_get("product", pid)
    recs = [s for s in store.all_recs("studies") if s["product_id"] == pid]
    status_f = request.args.get("status")
    if status_f is not None:
        recs = [s for s in recs if s["status"] == status_f]
    page, total, limit, offset = paginate(recs)
    return envelope.ok_list([serialize.study(s) for s in page], total, limit, offset)


@bp.route("/comparability-studies/<sid>/action", methods=["POST"])
def study_action(sid):
    require_auth(("RegulatoryAffairsSpecialist",))
    rec = must_get("study", sid)
    d = body()
    act = action_value(d, "action", STUDY_ACTIONS)
    if act == "SUBMIT_FILING":
        authority = req_enum(d, "authority", AUTHORITIES)  # stage-4 check first
        if rec["status"] != "COMPARABLE":
            err("ERR_INVALID_STUDY_STATE", "SUBMIT_FILING requires COMPARABLE")
        rec["authority"] = authority
        rec["status"] = "FILED"
        store.touch(rec)
    elif act == "APPROVE_PROTOCOL":
        if rec["status"] not in ("PLANNED", "NOT_COMPARABLE"):
            err("ERR_INVALID_STUDY_STATE",
                "APPROVE_PROTOCOL requires PLANNED or NOT_COMPARABLE")
        rec["status"] = "PROTOCOL_APPROVED"
        store.touch(rec)
    else:  # RECORD_ASSESSMENT
        if rec["status"] != "PROTOCOL_APPROVED":
            err("ERR_INVALID_STUDY_STATE", "RECORD_ASSESSMENT requires PROTOCOL_APPROVED")
        mu1, margin, comparable = calc_quality.comparability_assessment(rec)
        rec["baseline_mean"] = mu1
        rec["equivalence_margin"] = margin
        rec["status"] = "COMPARABLE" if comparable else "NOT_COMPARABLE"
        store.touch(rec)
    return envelope.ok(serialize.study(rec), 200)
