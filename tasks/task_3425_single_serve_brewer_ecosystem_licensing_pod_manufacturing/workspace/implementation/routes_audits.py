"""Quality audits: record and list. A FAIL on an ACTIVE agreement fires the
suspension cascade."""
import uuid

from flask import Blueprint

from store import db, get_clock, next_seq
from helpers import (
    ApiError, body, created, find, fmt_dt, list_ok, need, now_iso,
    parse_dt_val, require_roles, v_int,
)
from calc import DEFECT_HARD_MAX_PPM
from routes_licensing import agreement_write_gate, suspend_cascade
from serializers import audit_out

bp = Blueprint("audits", __name__)


@bp.post("/license-agreements/<rid>/quality-audits")
@require_roles("QualityAuditor")
def create_audit(rid):
    agr = find("agreements", rid)
    b = body()
    audited_dt = parse_dt_val(need(b, "audited_at"))
    cup = v_int(b, "cup_score", minv=0, maxv=100)
    ppm = v_int(b, "defect_rate_ppm")
    if audited_dt > get_clock():
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "audited_at must not be later than the logical clock")
    agreement_write_gate(agr)
    if agr["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Audits require an ACTIVE or SUSPENDED agreement")
    result = "PASS" if (cup >= agr["quality_min_cup_score"]
                        and ppm <= DEFECT_HARD_MAX_PPM) else "FAIL"
    audit = {
        "id": str(uuid.uuid4()),
        "agreement_id": agr["id"],
        "audited_at": fmt_dt(audited_dt),
        "cup_score": cup,
        "defect_rate_ppm": ppm,
        "result": result,
        "created_at": now_iso(),
        "_seq": next_seq(),
        "_audited_dt": audited_dt,
    }
    db["audits"][audit["id"]] = audit
    if result == "FAIL" and agr["status"] == "ACTIVE":
        suspend_cascade(agr)
    return created(audit_out(audit))


@bp.get("/license-agreements/<rid>/quality-audits")
@require_roles("QualityAuditor", "LicensingManager")
def list_audits(rid):
    agr = find("agreements", rid)
    items = [a for a in db["audits"].values() if a["agreement_id"] == agr["id"]]
    items.sort(key=lambda a: (a["_audited_dt"], a["created_at"], a["_seq"]),
               reverse=True)
    return list_ok(items, audit_out)
