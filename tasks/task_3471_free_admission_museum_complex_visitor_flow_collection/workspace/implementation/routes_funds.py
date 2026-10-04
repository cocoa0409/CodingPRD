"""Fund accounts (PRD 3.7): create, read with computed receipts and
settled/committed availability, freeze/unfreeze."""

from flask import Blueprint

import db
import serializers
import util
from envelope import success
from errors import fail
from middleware import auth, get_or_404, require_role

bp = Blueprint("funds", __name__)

FUND_READ_ROLES = [
    "PlatformAdmin",
    "FinanceOfficer",
    "CommitteeChair",
    "Registrar",
    "Curator",
    "ExhibitionManager",
]


@bp.post("/campus/funds")
def create_fund():
    _uid, role = auth()
    require_role(role, ["PlatformAdmin"])
    b = util.body()
    fund_code = util.req_str(b, "fund_code")
    fund_type = util.req_enum(b, "fund_type", ("FEDERAL", "TRUST"))
    appropriation_cents = util.req_int(b, "appropriation_cents", minimum=0)
    for f in db.STORE["funds"].values():
        if f["fund_code"] == fund_code:
            fail("ERR_INVALID_REQUEST", "fund_code must be unique")
    f = db.new_entity(
        {
            "fund_code": fund_code,
            "fund_type": fund_type,
            "appropriation_cents": appropriation_cents,
            "status": "ACTIVE",
        }
    )
    db.STORE["funds"][f["id"]] = f
    return success(serializers.fund_account(f), 201)


@bp.get("/campus/funds/<fid>")
def get_fund(fid):
    _uid, role = auth()
    require_role(role, FUND_READ_ROLES)
    f = get_or_404("funds", fid, "FundAccount")
    return success(serializers.fund_account(f))


@bp.post("/campus/funds/<fid>/set-status")
def set_fund_status(fid):
    _uid, role = auth()
    require_role(role, ["PlatformAdmin"])
    f = get_or_404("funds", fid, "FundAccount")
    b = util.body()
    target = b.get("status")
    # (5) transition legality: the machine has ACTIVE -> FROZEN and
    # FROZEN -> ACTIVE only; a same-state request has no transition.
    if target in ("ACTIVE", "FROZEN") and target == f["status"]:
        fail("ERR_INVALID_STATE", f"The fund is already {target}")
    # (9) request shape
    if target not in ("ACTIVE", "FROZEN"):
        fail("ERR_INVALID_REQUEST", "status must be ACTIVE or FROZEN")
    f["status"] = target
    db.touch(f)
    return success(serializers.fund_account(f))
