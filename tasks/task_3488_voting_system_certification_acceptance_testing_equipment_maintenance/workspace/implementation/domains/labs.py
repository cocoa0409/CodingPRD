"""TestLaboratory endpoints (PRD 3.1).

ACCREDITED on creation; CertificationAuthority suspends / reinstates.
lab_code is globally unique (ERR_DUPLICATE_LAB_CODE, pipeline priority 13).
"""
from flask import Blueprint

from auth import auth_context, peek_to_state, require_role, require_transition_actor
from constants import LAB_DEFAULT_MAX_CONCURRENT, LAB_MAX_CONCURRENT_MAX, LAB_MAX_CONCURRENT_MIN
from envelope import ok_object
from errors import err_invalid_state, err_not_found, raise_err
from store import db
from util import stamp_new, touch
from validation import body_json, no_extra, opt_int, req_enum, req_str

bp = Blueprint("labs", __name__)

LAB_SCOPES = {"FEDERAL", "STATE", "DUAL"}
LAB_STATES = {"ACCREDITED", "SUSPENDED"}
LAB_ACTORS = {"SUSPENDED": {"CertificationAuthority"}, "ACCREDITED": {"CertificationAuthority"}}


@bp.post("/evote/test-laboratories")
def create_laboratory():
    _, role = auth_context()
    require_role(role, {"PlatformAdmin"})
    body = body_json()
    no_extra(body, {"lab_code", "lab_name", "accreditation_scope", "max_concurrent_campaigns"})
    lab_code = req_str(body, "lab_code")
    lab_name = req_str(body, "lab_name")
    scope = req_enum(body, "accreditation_scope", LAB_SCOPES)
    capacity = opt_int(
        body, "max_concurrent_campaigns",
        minv=LAB_MAX_CONCURRENT_MIN, maxv=LAB_MAX_CONCURRENT_MAX,
    )
    if capacity is None:
        capacity = LAB_DEFAULT_MAX_CONCURRENT
    for lab in db.test_laboratories.values():
        if lab["lab_code"] == lab_code:
            raise_err("ERR_DUPLICATE_LAB_CODE", 409, "lab_code already registered")
    rec = stamp_new({})
    rec.update({
        "lab_code": lab_code,
        "lab_name": lab_name,
        "accreditation_scope": scope,
        "max_concurrent_campaigns": capacity,
        "status": "ACCREDITED",
    })
    db.test_laboratories[rec["id"]] = rec
    return ok_object(rec, 201)


def get_lab_or_404(lab_id):
    lab = db.test_laboratories.get(lab_id)
    if lab is None:
        err_not_found("test laboratory not found")
    return lab


@bp.get("/evote/test-laboratories/<lab_id>")
def get_laboratory(lab_id):
    auth_context()
    return ok_object(get_lab_or_404(lab_id), 200)


@bp.post("/evote/test-laboratories/<lab_id>/transitions")
def laboratory_transition(lab_id):
    _, role = auth_context()
    require_role(role, {"CertificationAuthority"})
    ts = peek_to_state()
    require_transition_actor(role, ts, LAB_ACTORS)
    lab = get_lab_or_404(lab_id)
    body = body_json()
    no_extra(body, {"to_state"})
    to_state = req_enum(body, "to_state", LAB_STATES)
    legal = {"ACCREDITED": {"SUSPENDED"}, "SUSPENDED": {"ACCREDITED"}}
    if lab["status"] not in legal[to_state]:
        err_invalid_state("laboratory cannot transition from %s to %s" % (lab["status"], to_state))
    lab["status"] = to_state
    touch(lab)
    return ok_object(lab, 200)
