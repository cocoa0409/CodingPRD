"""Member endpoints."""
from flask import Blueprint, request

import db
from auth import require_roles
from errors import err
from lookups import get_member
from response import ok_list, ok_object
from util import body_json, make_record, touch

bp = Blueprint("members", __name__)

ADMIN = ("MLCAdministrator",)
READ_ROLES = ("MLCAdministrator", "ServiceProviderUser", "MemberUser", "PublicSearcher")
MEMBER_TYPES = ("PUBLISHER", "SELF_PUBLISHED_SONGWRITER", "ADMINISTRATOR")


def member_view(m):
    return {k: v for k, v in m.items() if not k.startswith("_")}


@bp.route("/mlc/members", methods=["POST"])
@require_roles(*ADMIN)
def create_member(_user_id, _role):
    body = body_json(required=("legal_name", "member_type"))
    if body["member_type"] not in MEMBER_TYPES:
        raise err("ERR_INVALID_REQUEST", "member_type invalid")
    ipi = body.get("ipi_number")
    if ipi is not None:
        dup = any(m.get("ipi_number") == ipi for m in db.members.values())
        if dup:
            raise err("ERR_INVALID_REQUEST", "ipi_number must be unique")
    rec = make_record()
    rec.update({
        "legal_name": body["legal_name"],
        "member_type": body["member_type"],
        "ipi_number": ipi,
        "is_signatory": bool(body.get("is_signatory", False)),
        "status": "ACTIVE",
        "prior_market_share_numerator": 0,
        "prior_market_share_denominator": 0,
    })
    db.members[rec["id"]] = rec
    return ok_object(member_view(rec), 201)


@bp.route("/mlc/members", methods=["GET"])
@require_roles(*READ_ROLES)
def list_members(_user_id, _role):
    items = sorted(db.members.values(), key=lambda m: m["created_at"])
    status = request.args.get("status")
    if status:
        items = [m for m in items if m["status"] == status]
    mtype = request.args.get("member_type")
    if mtype:
        items = [m for m in items if m["member_type"] == mtype]
    return ok_list([member_view(m) for m in items])


@bp.route("/mlc/members/<member_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_one_member(member_id, _user_id, _role):
    return ok_object(member_view(get_member(member_id)))


@bp.route("/mlc/members/<member_id>/suspend", methods=["POST"])
@require_roles(*ADMIN)
def suspend_member(member_id, _user_id, _role):
    m = get_member(member_id)
    if m["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE")
    m["status"] = "SUSPENDED"
    touch(m)
    return ok_object(member_view(m))


@bp.route("/mlc/members/<member_id>/reinstate", methods=["POST"])
@require_roles(*ADMIN)
def reinstate_member(member_id, _user_id, _role):
    m = get_member(member_id)
    if m["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE")
    m["status"] = "ACTIVE"
    touch(m)
    return ok_object(member_view(m))


@bp.route("/mlc/members/<member_id>/terminate", methods=["POST"])
@require_roles(*ADMIN)
def terminate_member(member_id, _user_id, _role):
    m = get_member(member_id)
    if m["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_INVALID_STATE")
    active_shares = any(
        s["claimant_member_id"] == member_id and s["status"] in ("ACTIVE", "DISPUTED")
        for s in db.work_shares.values())
    if active_shares:
        raise err("ERR_MEMBER_HAS_ACTIVE_SHARES")
    open_claims = any(
        c["claimant_member_id"] == member_id and c["status"] in ("PENDING", "DISPUTED")
        for c in db.claims.values())
    if open_claims:
        raise err("ERR_CLAIM_NOT_PENDING", "Member has open claims")
    m["status"] = "TERMINATED"
    touch(m)
    # Cascade: ACTIVE payees -> TERMINATED
    for p in db.payees.values():
        if p["member_id"] == member_id and p["status"] == "ACTIVE":
            p["status"] = "TERMINATED"
            touch(p)
    return ok_object(member_view(m))
