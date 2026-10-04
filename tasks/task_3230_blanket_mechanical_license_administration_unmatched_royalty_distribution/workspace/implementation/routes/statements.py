"""Statement + StatementLine endpoints."""
from flask import Blueprint, request

import db
from auth import require_roles
from errors import err
from lookups import get_member, get_statement, check_child
from response import ok_list, ok_object
from util import body_json, make_record, month_bounds

bp = Blueprint("statements", __name__)

ADMIN = ("MLCAdministrator",)
READ = ("MLCAdministrator", "MemberUser")


def statement_view(s):
    return {k: v for k, v in s.items() if not k.startswith("_")}


def line_view(l):
    return {k: v for k, v in l.items() if not k.startswith("_")}


def _recompute(stmt):
    lines = [l for l in db.statement_lines.values()
             if l["statement_id"] == stmt["id"]]
    stmt["gross_cents"] = sum(l["allocated_cents"] for l in lines)
    stmt["adjustments_cents"] = sum(
        l["allocated_cents"] for l in lines if l["line_type"] == "ADJUSTMENT")
    stmt["net_cents"] = stmt["gross_cents"] + stmt["adjustments_cents"]


@bp.route("/mlc/members/<member_id>/statements", methods=["POST"])
@require_roles(*ADMIN)
def create_statement(member_id, _user_id, _role):
    member = get_member(member_id)
    body = body_json(required=("period_month",))
    period = body["period_month"]
    month_bounds(period)
    rec = make_record(full_common=False)
    rec.update({
        "member_id": member_id,
        "period_month": period,
        "gross_cents": 0,
        "adjustments_cents": 0,
        "net_cents": 0,
        "status": "DRAFT",
    })
    db.statements[rec["id"]] = rec
    # Materialize queued postings for this member+period as StatementLines
    remaining = []
    for p in db.postings:
        if p["member_id"] == member_id and p["period_month"] == period:
            line = make_record(full_common=False)
            line.update({
                "statement_id": rec["id"],
                "usage_line_id": p["usage_line_id"],
                "member_id": member_id,
                "allocated_cents": p["allocated_cents"],
                "line_type": p["line_type"],
                "payee_id": None,
            })
            db.statement_lines[line["id"]] = line
        else:
            remaining.append(p)
    db.postings[:] = remaining
    _recompute(rec)
    return ok_object(statement_view(rec), 201)


@bp.route("/mlc/members/<member_id>/statements", methods=["GET"])
@require_roles(*READ)
def list_statements(member_id, _user_id, _role):
    get_member(member_id)
    items = sorted(
        (s for s in db.statements.values() if s["member_id"] == member_id),
        key=lambda s: s["created_at"])
    status = request.args.get("status")
    if status:
        items = [s for s in items if s["status"] == status]
    return ok_list([statement_view(s) for s in items])


@bp.route("/mlc/members/<member_id>/statements/<statement_id>", methods=["GET"])
@require_roles(*READ)
def get_one_statement(member_id, statement_id, _user_id, _role):
    get_member(member_id)
    s = get_statement(statement_id)
    check_child(s, "member_id", member_id, "ERR_STATEMENT_NOT_FOUND")
    return ok_object(statement_view(s))


@bp.route("/mlc/statements/<statement_id>", methods=["GET"])
@require_roles(*READ)
def get_statement_flat(statement_id, _user_id, _role):
    return ok_object(statement_view(get_statement(statement_id)))


@bp.route("/mlc/members/<member_id>/statements/<statement_id>/lines",
          methods=["GET"])
@require_roles(*READ)
def list_statement_lines(member_id, statement_id, _user_id, _role):
    get_member(member_id)
    s = get_statement(statement_id)
    check_child(s, "member_id", member_id, "ERR_STATEMENT_NOT_FOUND")
    items = sorted(
        (l for l in db.statement_lines.values()
         if l["statement_id"] == statement_id),
        key=lambda l: l["created_at"])
    lt = request.args.get("line_type")
    if lt:
        items = [l for l in items if l["line_type"] == lt]
    return ok_list([line_view(l) for l in items])


@bp.route("/mlc/statement-lines", methods=["GET"])
@require_roles(*READ)
def list_statement_lines_flat(_user_id, _role):
    items = sorted(db.statement_lines.values(), key=lambda l: l["created_at"])
    for field in ("statement_id", "usage_line_id", "member_id",
                  "line_type", "payee_id"):
        v = request.args.get(field)
        if v:
            items = [l for l in items if l.get(field) == v]
    return ok_list([line_view(l) for l in items])


@bp.route("/mlc/statement-lines/<line_id>", methods=["GET"])
@require_roles(*READ)
def get_statement_line(line_id, _user_id, _role):
    line = db.statement_lines.get(line_id)
    if line is None:
        raise err("ERR_STATEMENT_NOT_FOUND")
    return ok_object(line_view(line))


@bp.route("/mlc/members/<member_id>/statements/<statement_id>/finalize",
          methods=["POST"])
@require_roles(*ADMIN)
def finalize_statement(member_id, statement_id, _user_id, _role):
    get_member(member_id)
    s = get_statement(statement_id)
    check_child(s, "member_id", member_id, "ERR_STATEMENT_NOT_FOUND")
    body_json()
    if s["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE")
    active_payees = sorted(
        (p for p in db.payees.values()
         if p["member_id"] == member_id and p["status"] == "ACTIVE"),
        key=lambda p: p["created_at"])
    if not active_payees:
        raise err("ERR_NO_ACTIVE_PAYEE")
    payee = active_payees[0]
    _recompute(s)
    for l in db.statement_lines.values():
        if l["statement_id"] == statement_id:
            l["payee_id"] = payee["id"]
    s["status"] = "FINALIZED"
    return ok_object(statement_view(s))


@bp.route("/mlc/members/<member_id>/statements/<statement_id>/reopen",
          methods=["POST"])
@require_roles(*ADMIN)
def reopen_statement(member_id, statement_id, _user_id, _role):
    get_member(member_id)
    s = get_statement(statement_id)
    check_child(s, "member_id", member_id, "ERR_STATEMENT_NOT_FOUND")
    body_json()
    if s["status"] != "FINALIZED":
        raise err("ERR_INVALID_STATE")
    newer = any(
        other["member_id"] == member_id and other["id"] != statement_id
        and other["status"] in ("FINALIZED", "DELIVERED")
        and other["period_month"] > s["period_month"]
        for other in db.statements.values())
    if newer:
        raise err("ERR_STATEMENT_SUPERSEDED")
    s["status"] = "DRAFT"
    return ok_object(statement_view(s))


@bp.route("/mlc/members/<member_id>/statements/<statement_id>/deliver",
          methods=["POST"])
@require_roles(*ADMIN)
def deliver_statement(member_id, statement_id, _user_id, _role):
    get_member(member_id)
    s = get_statement(statement_id)
    check_child(s, "member_id", member_id, "ERR_STATEMENT_NOT_FOUND")
    body_json()
    if s["status"] != "FINALIZED":
        raise err("ERR_INVALID_STATE")
    s["status"] = "DELIVERED"
    return ok_object(statement_view(s))
