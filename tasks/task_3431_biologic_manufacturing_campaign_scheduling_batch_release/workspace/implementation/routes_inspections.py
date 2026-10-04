"""Regulatory inspection endpoints (PRD 3.7)."""
from flask import Blueprint, request

import envelope
import posture
import serialize
import store
from auth import require_auth
from constants import AUTHORITIES, FINDING_SEVERITIES, INSPECTION_ACTIONS
from errors import err
from validate import action_value, body, must_get, paginate, req_enum, req_str

bp = Blueprint("inspections", __name__)


@bp.route("/sites/<sid>/inspections", methods=["POST"])
def create_inspection(sid):
    require_auth(("RegulatoryAffairsSpecialist",))
    site_rec = must_get("site", sid)
    d = body()
    auth = req_enum(d, "authority", AUTHORITIES)
    if auth not in site_rec["licensed_authorities"]:
        err("ERR_INVALID_REQUEST", "authority must be one of the site's licensed_authorities")
    rec = store.create_rec("inspections", {
        "site_id": site_rec["id"],
        "authority": auth,
        "status": "ANNOUNCED",
        "findings": [],
        "open_critical_finding_count": 0,
        "response_summary": None,
    })
    return envelope.ok(serialize.inspection(rec), 201)


@bp.route("/sites/<sid>/inspections", methods=["GET"])
def list_inspections(sid):
    require_auth(("Any",))
    must_get("site", sid)
    recs = [i for i in store.all_recs("inspections") if i["site_id"] == sid]
    status_f = request.args.get("status")
    if status_f is not None:
        recs = [i for i in recs if i["status"] == status_f]
    page, total, limit, offset = paginate(recs)
    return envelope.ok_list([serialize.inspection(i) for i in page], total, limit, offset)


def _validate_findings(findings):
    if not isinstance(findings, list) or len(findings) == 0:
        err("ERR_INVALID_REQUEST", "findings must be a non-empty array")
    for f in findings:
        if not isinstance(f, dict) or f.get("severity") not in FINDING_SEVERITIES \
                or not isinstance(f.get("note"), str):
            err("ERR_INVALID_REQUEST",
                "each finding must have severity CRITICAL|MAJOR|MINOR and a note")


@bp.route("/inspections/<iid>/action", methods=["POST"])
def inspection_action(iid):
    require_auth(("RegulatoryAffairsSpecialist",))
    rec = must_get("inspection", iid)
    d = body()
    act = action_value(d, "action", INSPECTION_ACTIONS)
    if act == "ISSUE_FINDINGS":
        _validate_findings(d.get("findings"))
        if rec["status"] != "ANNOUNCED":
            err("ERR_INVALID_INSPECTION_STATE", "ISSUE_FINDINGS requires ANNOUNCED")
        rec["findings"] = [{"severity": f["severity"], "note": f["note"]} for f in d["findings"]]
        rec["open_critical_finding_count"] = sum(
            1 for f in rec["findings"] if f["severity"] == "CRITICAL")
        rec["status"] = "FINDINGS_ISSUED"
        store.touch(rec)
        posture.recompute_site(rec["site_id"])
    else:  # CLOSE
        summary = req_str(d, "response_summary")
        if rec["status"] != "FINDINGS_ISSUED":
            err("ERR_INVALID_INSPECTION_STATE", "CLOSE requires FINDINGS_ISSUED")
        rec["response_summary"] = summary
        rec["open_critical_finding_count"] = 0
        rec["status"] = "CLOSED"
        store.touch(rec)
        posture.recompute_site(rec["site_id"])
    return envelope.ok(serialize.inspection(rec), 200)
