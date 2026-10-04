"""Payee endpoints (member-scoped + flat alias)."""
from flask import Blueprint, request

import db
from auth import require_roles
from errors import err
from lookups import get_member, get_payee, check_child
from response import ok_list, ok_object
from util import body_json, make_record, touch

bp = Blueprint("payees", __name__)

METHODS = ("ACH", "WIRE", "CHECK")
READ = ("MLCAdministrator", "MemberUser")
WRITE = ("MemberUser", "MLCAdministrator")
ADMIN = ("MLCAdministrator",)


def payee_view(p):
    return {k: v for k, v in p.items() if not k.startswith("_")}


def _aba_ok(rn):
    if not isinstance(rn, str) or len(rn) != 9 or not rn.isdigit():
        return False
    d = [int(c) for c in rn]
    return (3 * (d[0] + d[3] + d[6]) + 7 * (d[1] + d[4] + d[7]) + (d[2] + d[5] + d[8])) % 10 == 0


@bp.route("/mlc/members/<member_id>/payees", methods=["POST"])
@require_roles(*WRITE)
def create_payee(member_id, _user_id, _role):
    member = get_member(member_id)
    body = body_json(required=("payee_legal_name", "payment_method", "tax_id"))
    if member["status"] != "ACTIVE":
        raise err("ERR_DSP_NOT_ACTIVE")
    method = body["payment_method"]
    if method not in METHODS:
        raise err("ERR_INVALID_REQUEST", "payment_method invalid")
    rn = body.get("routing_number")
    acct = body.get("account_number")
    tax_id = body["tax_id"]
    if not isinstance(tax_id, str) or len(tax_id) != 9 or not tax_id.isdigit():
        raise err("ERR_INVALID_REQUEST", "tax_id must be 9 digits")
    if method in ("ACH", "WIRE"):
        if rn is None or acct is None:
            raise err("ERR_PAYEE_ROUTING_INVALID")
        if not _aba_ok(rn):
            raise err("ERR_PAYEE_ROUTING_INVALID")
    else:  # CHECK
        if rn is not None or acct is not None:
            raise err("ERR_PAYEE_ROUTING_INVALID")
    rec = make_record()
    rec.update({
        "member_id": member_id,
        "payee_legal_name": body["payee_legal_name"],
        "payment_method": method,
        "routing_number": rn,
        "account_number": acct,
        "tax_id": tax_id,
        "status": "ACTIVE",
    })
    db.payees[rec["id"]] = rec
    return ok_object(payee_view(rec), 201)


@bp.route("/mlc/members/<member_id>/payees", methods=["GET"])
@require_roles(*READ)
def list_payees(member_id, _user_id, _role):
    get_member(member_id)
    items = sorted(
        (p for p in db.payees.values() if p["member_id"] == member_id),
        key=lambda p: p["created_at"])
    status = request.args.get("status")
    if status:
        items = [p for p in items if p["status"] == status]
    return ok_list([payee_view(p) for p in items])


@bp.route("/mlc/members/<member_id>/payees/<payee_id>", methods=["GET"])
@require_roles(*READ)
def get_one_payee(member_id, payee_id, _user_id, _role):
    get_member(member_id)
    p = get_payee(payee_id)
    check_child(p, "member_id", member_id, "ERR_PAYEE_NOT_FOUND")
    return ok_object(payee_view(p))


@bp.route("/mlc/payees/<payee_id>", methods=["GET"])
@require_roles(*READ)
def get_payee_flat(payee_id, _user_id, _role):
    return ok_object(payee_view(get_payee(payee_id)))


def _payee_transition(member_id, payee_id, target, allowed_from):
    member = get_member(member_id)
    p = get_payee(payee_id)
    check_child(p, "member_id", member_id, "ERR_PAYEE_NOT_FOUND")
    if p["status"] not in allowed_from:
        raise err("ERR_INVALID_STATE")
    return member, p


@bp.route("/mlc/members/<member_id>/payees/<payee_id>/suspend", methods=["POST"])
@require_roles(*ADMIN)
def suspend_payee(member_id, payee_id, _user_id, _role):
    _, p = _payee_transition(member_id, payee_id, "SUSPENDED", ("ACTIVE",))
    p["status"] = "SUSPENDED"
    touch(p)
    return ok_object(payee_view(p))


@bp.route("/mlc/members/<member_id>/payees/<payee_id>/reinstate", methods=["POST"])
@require_roles(*ADMIN)
def reinstate_payee(member_id, payee_id, _user_id, _role):
    _, p = _payee_transition(member_id, payee_id, "ACTIVE", ("SUSPENDED",))
    p["status"] = "ACTIVE"
    touch(p)
    return ok_object(payee_view(p))


@bp.route("/mlc/members/<member_id>/payees/<payee_id>/terminate", methods=["POST"])
@require_roles(*ADMIN)
def terminate_payee(member_id, payee_id, _user_id, _role):
    _, p = _payee_transition(member_id, payee_id, "TERMINATED", ("ACTIVE", "SUSPENDED"))
    others = [
        q for q in db.payees.values()
        if q["member_id"] == member_id and q["id"] != payee_id
        and q["status"] in ("ACTIVE", "SUSPENDED")
    ]
    if not others:
        raise err("ERR_LAST_PAYEE_TERMINATION")
    p["status"] = "TERMINATED"
    touch(p)
    return ok_object(payee_view(p))
