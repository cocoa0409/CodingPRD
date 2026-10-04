"""Settlement: windows (schedule/open/reconcile/close/lines/positions) and
lines (draft/commit/reverse)."""

import re

from flask import Blueprint, request

import db
from errors import raise_err
from helpers import (
    base_record, exists_or_404, get_json, get_or_404, is_currency, logical_now,
    logical_now_iso, paginate, parse_iso, req_int, req_str, sort_by_created, touch,
)
from middleware import require_roles
from response import iso3, ok

bp = Blueprint("settlement", __name__)

READ_ROLES = {"NetworkOperator", "SettlementOperator"}
WINDOW_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


# ---------------- Settlement windows ----------------

@bp.post("/network/settlement-windows")
def create_window():
    require_roles({"SettlementOperator"})
    body = get_json()
    window_date = req_str(body, "window_date")
    if "opens_at" not in body:
        raise_err("ERR_INVALID_REQUEST", "opens_at is required")
    if "closes_at" not in body:
        raise_err("ERR_INVALID_REQUEST", "closes_at is required")
    opens_dt = parse_iso(body["opens_at"], "opens_at")
    closes_dt = parse_iso(body["closes_at"], "closes_at")
    if not WINDOW_DATE_RE.fullmatch(window_date):
        raise_err("ERR_VALIDATION", "window_date must be YYYY-MM-DD")
    if closes_dt <= opens_dt:
        raise_err("ERR_VALIDATION", "closes_at must be strictly after opens_at")
    opens_iso = iso3(opens_dt)
    closes_iso = iso3(closes_dt)
    for w in db.settlement_windows.values():
        if w["window_date"] == window_date:
            raise_err("ERR_DUPLICATE", "A settlement window with this window_date already exists")
        if w["opens_at"] == opens_iso:
            raise_err("ERR_DUPLICATE", "A settlement window with this opens_at already exists")
    rec = base_record()
    rec.update({
        "window_date": window_date,
        "opens_at": opens_iso,
        "closes_at": closes_iso,
        "status": "SCHEDULED",
        "total_settled_cents": 0,
    })
    db.settlement_windows[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/network/settlement-windows")
def list_windows():
    require_roles(READ_ROLES)
    items = list(db.settlement_windows.values())
    status = request.args.get("status")
    if status is not None:
        items = [w for w in items if w["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok(page, 200, meta)


@bp.get("/network/settlement-windows/<wid>")
def get_window(wid):
    require_roles(READ_ROLES)
    rec = get_or_404(db.settlement_windows, wid)
    return ok(rec, 200)


@bp.post("/network/settlement-windows/<wid>/open")
def open_window(wid):
    require_roles({"SettlementOperator"})
    rec = get_or_404(db.settlement_windows, wid)
    if rec["status"] != "SCHEDULED":
        raise_err("ERR_INVALID_STATE", "Window is not SCHEDULED")
    for w in db.settlement_windows.values():
        if w["id"] != wid and w["status"] == "OPEN":
            raise_err("ERR_WINDOW_NOT_OPEN", "Another settlement window is already OPEN")
    if logical_now() < parse_iso(rec["opens_at"]):
        raise_err("ERR_WINDOW_EXPIRED", "Logical clock has not reached opens_at")
    rec["status"] = "OPEN"
    touch(rec)
    return ok(rec, 200)


@bp.post("/network/settlement-windows/<wid>/reconcile")
def reconcile_window(wid):
    require_roles({"SettlementOperator"})
    rec = get_or_404(db.settlement_windows, wid)
    if rec["status"] != "OPEN":
        raise_err("ERR_INVALID_STATE", "Window is not OPEN")
    for line in db.settlement_lines.values():
        if line["window_id"] == wid and line["status"] == "DRAFT":
            raise_err("ERR_DRAFT_LINES_REMAIN", "DRAFT settlement lines remain in this window")
    rec["status"] = "RECONCILED"
    touch(rec)
    return ok(rec, 200)


@bp.post("/network/settlement-windows/<wid>/close")
def close_window(wid):
    require_roles({"SettlementOperator"})
    rec = get_or_404(db.settlement_windows, wid)
    if rec["status"] != "RECONCILED":
        raise_err("ERR_INVALID_STATE", "Window is not RECONCILED")
    rec["status"] = "CLOSED"
    touch(rec)
    return ok(rec, 200)


@bp.get("/network/settlement-windows/<wid>/lines")
def list_window_lines(wid):
    require_roles(READ_ROLES)
    get_or_404(db.settlement_windows, wid)
    items = [l for l in db.settlement_lines.values() if l["window_id"] == wid]
    status = request.args.get("status")
    if status is not None:
        items = [l for l in items if l["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok(page, 200, meta)


@bp.get("/network/settlement-windows/<wid>/positions")
def window_positions(wid):
    require_roles(READ_ROLES)
    get_or_404(db.settlement_windows, wid)
    nets = {}
    for line in db.settlement_lines.values():
        if line["window_id"] != wid or line["status"] != "COMMITTED":
            continue
        nets[line["to_member_id"]] = nets.get(line["to_member_id"], 0) + line["amount_cents"]
        nets[line["from_member_id"]] = nets.get(line["from_member_id"], 0) - line["amount_cents"]
    positions = []
    for member_id, net in nets.items():
        member = db.members[member_id]
        positions.append({
            "member_id": member_id,
            "net_cents": net,
        })
    positions.sort(key=lambda p: (p["net_cents"], db.members[p["member_id"]]["created_at"]))
    return ok({
        "positions": positions,
        "total_check_cents": sum(p["net_cents"] for p in positions),
    }, 200)


# ---------------- Settlement lines ----------------

def _fiscal_checks(from_member, to_member, amount):
    if amount <= 0:
        raise_err("ERR_SETTLEMENT_INVALID", "amount_cents must be strictly positive")
    if from_member["id"] == to_member["id"]:
        raise_err("ERR_SETTLEMENT_INVALID", "from_member and to_member must differ")
    if from_member["status"] != "ACTIVE" or to_member["status"] != "ACTIVE":
        raise_err("ERR_SETTLEMENT_INVALID", "Both members must be ACTIVE")


@bp.post("/network/settlement-lines")
def create_line():
    require_roles({"SettlementOperator"})
    body = get_json()
    window_id = req_str(body, "window_id")
    from_member_id = req_str(body, "from_member_id")
    to_member_id = req_str(body, "to_member_id")
    amount = req_int(body, "amount_cents")
    currency = req_str(body, "currency")
    reference = req_str(body, "reference")

    exists_or_404(db.settlement_windows, window_id, "settlement window")
    from_member = exists_or_404(db.members, from_member_id, "from member")
    to_member = exists_or_404(db.members, to_member_id, "to member")

    if not is_currency(currency):
        raise_err("ERR_VALIDATION", "currency must be a 3-letter uppercase ISO 4217 code")
    _fiscal_checks(from_member, to_member, amount)

    rec = base_record()
    rec.update({
        "window_id": window_id,
        "from_member_id": from_member_id,
        "to_member_id": to_member_id,
        "amount_cents": amount,
        "currency": currency,
        "reference": reference,
        "status": "DRAFT",
        "committed_at": None,
    })
    db.settlement_lines[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/network/settlement-lines")
def list_lines():
    require_roles(READ_ROLES)
    items = list(db.settlement_lines.values())
    window_id = request.args.get("window_id")
    from_member_id = request.args.get("from_member_id")
    to_member_id = request.args.get("to_member_id")
    status = request.args.get("status")
    if window_id is not None:
        items = [l for l in items if l["window_id"] == window_id]
    if from_member_id is not None:
        items = [l for l in items if l["from_member_id"] == from_member_id]
    if to_member_id is not None:
        items = [l for l in items if l["to_member_id"] == to_member_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok(page, 200, meta)


@bp.get("/network/settlement-lines/<lid>")
def get_line(lid):
    require_roles(READ_ROLES)
    rec = get_or_404(db.settlement_lines, lid)
    return ok(rec, 200)


@bp.post("/network/settlement-lines/<lid>/commit")
def commit_line(lid):
    require_roles({"SettlementOperator"})
    rec = get_or_404(db.settlement_lines, lid)
    if rec["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", "SettlementLine is not DRAFT")
    window = db.settlement_windows.get(rec["window_id"])
    if window is None or window["status"] != "OPEN":
        raise_err("ERR_WINDOW_NOT_OPEN", "Settlement window is not OPEN")
    from_member = db.members[rec["from_member_id"]]
    to_member = db.members[rec["to_member_id"]]
    _fiscal_checks(from_member, to_member, rec["amount_cents"])
    now = logical_now()
    if not (parse_iso(window["opens_at"]) <= now < parse_iso(window["closes_at"])):
        raise_err("ERR_WINDOW_EXPIRED", "Commit is outside the window bounds")
    rec["status"] = "COMMITTED"
    rec["committed_at"] = logical_now_iso()
    touch(rec)
    from_member["settled_balance_cents"] -= rec["amount_cents"]
    touch(from_member)
    to_member["settled_balance_cents"] += rec["amount_cents"]
    touch(to_member)
    window["total_settled_cents"] += rec["amount_cents"]
    touch(window)
    return ok(rec, 200)


@bp.post("/network/settlement-lines/<lid>/reverse")
def reverse_line(lid):
    require_roles({"SettlementOperator"})
    rec = get_or_404(db.settlement_lines, lid)
    if rec["status"] != "COMMITTED":
        raise_err("ERR_INVALID_STATE", "SettlementLine is not COMMITTED")
    window = db.settlement_windows.get(rec["window_id"])
    if window is None or window["status"] != "OPEN":
        raise_err("ERR_WINDOW_NOT_OPEN", "Settlement window is not OPEN")
    from_member = db.members[rec["from_member_id"]]
    to_member = db.members[rec["to_member_id"]]
    rec["status"] = "REVERSED"
    touch(rec)
    from_member["settled_balance_cents"] += rec["amount_cents"]
    touch(from_member)
    to_member["settled_balance_cents"] -= rec["amount_cents"]
    touch(to_member)
    window["total_settled_cents"] -= rec["amount_cents"]
    touch(window)
    return ok(rec, 200)
