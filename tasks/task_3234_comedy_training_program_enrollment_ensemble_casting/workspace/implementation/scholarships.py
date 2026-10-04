"""ScholarshipAward routes."""
from flask import Blueprint, request
from store import store, fresh, stamp
from middleware import auth, json_body, require_fields, pagination_params, require_student_owner
from response import success_obj, success_list
from errors import (
    not_found, invalid_request, raise_err, ERR_INVALID_STATE, ERR_SCHOLARSHIP_NOT_REVOCABLE,
)

bp = Blueprint("scholarships", __name__)

KINDS = {"NEED_BASED", "DIVERSITY", "MERIT"}


def _get(sid):
    s = store.scholarships.get(sid)
    if not s:
        not_found("scholarship not found")
    return s


@bp.post("/scholarships")
def create_scholarship():
    user_id, role = auth(["Student", "FinanceOfficer"])
    body = json_body()
    require_fields(body, ["student_id", "kind", "amount_cents"])
    if role == "Student":
        require_student_owner(user_id, role, body["student_id"])
    if body["student_id"] not in store.students:
        not_found("student not found")
    if body["kind"] not in KINDS:
        invalid_request("invalid kind")
    if not isinstance(body["amount_cents"], int) or isinstance(body["amount_cents"], bool) or body["amount_cents"] <= 0:
        invalid_request("amount_cents must be a positive integer")
    s = fresh({
        "student_id": body["student_id"],
        "kind": body["kind"],
        "amount_cents": body["amount_cents"],
        "disbursed_cents": 0,
        "status": "APPLIED",
    })
    store.scholarships[s["id"]] = s
    return success_obj(s, 201)


@bp.get("/scholarships")
def list_scholarships():
    auth(["FinanceOfficer", "ProgramDirector"])
    limit, offset = pagination_params()
    items = list(store.scholarships.values())
    for f in ("student_id", "kind", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [x for x in items if x.get(f) == v]
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    return success_list(items[offset:offset + limit], limit, offset, total)


@bp.get("/scholarships/<sid>")
def get_scholarship(sid):
    auth(["FinanceOfficer", "ProgramDirector"])
    return success_obj(_get(sid))


@bp.post("/scholarships/<sid>/award")
def award(sid):
    auth(["FinanceOfficer"])
    s = _get(sid)
    if s["status"] != "APPLIED":
        raise_err(ERR_INVALID_STATE, "scholarship must be APPLIED")
    s["status"] = "AWARDED"
    stamp(s)
    # immediate disbursement cascade: student has outstanding invoices
    has_outstanding = any(
        inv["student_id"] == s["student_id"] and inv["status"] in ("ISSUED", "PARTIALLY_PAID")
        for inv in store.invoices.values()
    )
    if has_outstanding:
        from services import disburse_scholarships
        for inv in store.invoices.values():
            if inv["student_id"] == s["student_id"] and inv["status"] in ("ISSUED", "PARTIALLY_PAID"):
                disburse_scholarships(inv)
                stamp(inv)
    return success_obj(s)


@bp.post("/scholarships/<sid>/deny")
def deny(sid):
    auth(["FinanceOfficer"])
    s = _get(sid)
    if s["status"] != "APPLIED":
        raise_err(ERR_INVALID_STATE, "scholarship must be APPLIED")
    s["status"] = "DENIED"
    stamp(s)
    return success_obj(s)


@bp.post("/scholarships/<sid>/revoke")
def revoke(sid):
    auth(["FinanceOfficer"])
    s = _get(sid)
    # §3.4: revocation is possible only while nothing has been disbursed; an
    # AWARDED-or-DISBURSED award with non-zero disbursed_cents reports the
    # balance guard rather than the state gate (revoke exists precisely to
    # reclaim a disbursing award).
    if s["status"] in ("AWARDED", "DISBURSED") and s["disbursed_cents"] != 0:
        raise_err(ERR_SCHOLARSHIP_NOT_REVOCABLE, "award has non-zero disbursed_cents")
    if s["status"] != "AWARDED":
        raise_err(ERR_INVALID_STATE, "scholarship must be AWARDED")
    s["status"] = "REVOKED"
    stamp(s)
    return success_obj(s)
