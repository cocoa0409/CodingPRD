"""DependentConflict routes: list/read, submit-evidence, analyst resolve."""
from flask import Blueprint, request

from auth import require_roles
from domain import get_conflict, pub, resolve_conflict, touch
from envelope import list_response, ok
from errors import err
from store import DB
from validate import body, opt_str, page, pagination, req_enum

bp = Blueprint("conflicts", __name__)

SIDES = ("FIRST_FILER", "SECOND_FILER")


@bp.get("/identity-protection/dependent-conflicts")
def list_conflicts():
    require_roles(["FraudAnalyst", "TaxpayerAdvocate", "SystemAdmin"])
    limit, offset = pagination()
    rows = list(DB.conflicts.values())
    for param in ("dependent_tin", "status", "return_a_id", "return_b_id"):
        v = request.args.get(param)
        if v is not None:
            rows = [c for c in rows if c.get(param) == v]
    items, total = page(rows, limit, offset)
    return list_response([pub(c) for c in items], total, limit, offset)


@bp.get("/identity-protection/dependent-conflicts/<string:conflict_id>")
def read_conflict(conflict_id):
    require_roles(["FraudAnalyst", "TaxpayerAdvocate", "SystemAdmin"])
    return ok(pub(get_conflict(conflict_id)))


@bp.post("/identity-protection/dependent-conflicts/<string:conflict_id>/submit-evidence")
def submit_evidence(conflict_id):
    uid, role = require_roles(["Taxpayer", "FraudAnalyst"])
    conflict = get_conflict(conflict_id)
    # Priority 6: a RESOLVED conflict rejects further action (late evidence
    # included — the clock sweep resolves expired conflicts before late
    # evidence can arrive).
    if conflict["status"] != "OPEN":
        err("ERR_CONFLICT_ALREADY_RESOLVED")
    b = body()
    side = b.get("side")
    # Priority 3 ownership: a Taxpayer submits only for their own side.
    if role == "Taxpayer":
        filer_ret = None
        if side == "FIRST_FILER":
            filer_ret = DB.returns.get(conflict["return_a_id"])
        elif side == "SECOND_FILER":
            filer_ret = DB.returns.get(conflict["return_b_id"])
        if filer_ret is not None and filer_ret["taxpayer_id"] != uid:
            err("ERR_UNAUTHORIZED")
        if filer_ret is None and side in SIDES:
            err("ERR_UNAUTHORIZED")
    # Priority 14: payload shape.
    side = req_enum(b, "side", SIDES)
    opt_str(b, "note")
    if side == "FIRST_FILER":
        conflict["evidence_a_submitted"] = True
    else:
        conflict["evidence_b_submitted"] = True
    touch(conflict)
    return ok(pub(conflict))


@bp.post("/identity-protection/dependent-conflicts/<string:conflict_id>/resolve")
def resolve(conflict_id):
    require_roles(["FraudAnalyst"])
    conflict = get_conflict(conflict_id)
    if conflict["status"] != "OPEN":
        err("ERR_CONFLICT_ALREADY_RESOLVED")
    winner = req_enum(body(), "winner", SIDES)
    resolve_conflict(conflict, winner, "ANALYST_DECISION")
    return ok(pub(conflict))
