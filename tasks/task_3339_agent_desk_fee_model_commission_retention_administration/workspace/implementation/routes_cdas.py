"""CDA routes: open ladder, get, list, review; closing statement line reads."""
from flask import Blueprint, request

from auth import require_roles, ALL_ROLES
from store import db
from response import ok, ok_list, ApiError, err_not_found, err_invalid_request
from helpers import new_record, touch, paginate, sort_by_created
import views

bp = Blueprint("cdas", __name__)

LADDER = ["COMPLIANCE_REVIEW", "TRUST_REVIEW", "BROKER_SIGNOFF"]
RUNG_ROLES = {0: "ComplianceAuditor", 1: "TrustAccountant", 2: "ManagingBroker"}


def get_txn_or_404(tid):
    t = db["transactions"].get(tid)
    if not t:
        raise err_not_found("Transaction not found")
    return t


def get_cda_or_404(cid):
    c = db["cdas"].get(cid)
    if not c:
        raise err_not_found("CDA not found")
    return c


@bp.route("/transactions/<transactionId>/cdas", methods=["POST"])
def create_cda(transactionId):
    uid, _role = require_roles("ManagingBroker")
    t = get_txn_or_404(transactionId)
    if t["status"] not in ("UNDER_CONTRACT", "PENDING_CLOSE"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "CDA may only be opened on UNDER_CONTRACT or PENDING_CLOSE transactions")
    for c in db["cdas"].values():
        if c["transaction_id"] == t["id"] and c["status"] in ("DRAFT", "IN_REVIEW", "APPROVED"):
            raise ApiError("ERR_CDA_EXISTS", 409, "A live CDA already exists for this transaction")
    body = request.get_json(silent=True) or {}
    ladder = body.get("review_ladder")
    if ladder != LADDER:
        raise err_invalid_request(
            "review_ladder must be exactly [COMPLIANCE_REVIEW, TRUST_REVIEW, BROKER_SIGNOFF]")
    rec = new_record()
    rec.update({
        "transaction_id": t["id"],
        "authorizing_broker_id": uid,
        "review_ladder": list(LADDER),
        "current_rung": 0,
        "status": "IN_REVIEW",
    })
    db["cdas"][rec["id"]] = rec
    return ok(views.cda_view(rec), 201)


@bp.route("/cdas/<cdaId>", methods=["GET"])
def get_cda(cdaId):
    require_roles(*ALL_ROLES)
    c = get_cda_or_404(cdaId)
    return ok(views.cda_view(c))


@bp.route("/transactions/<transactionId>/cdas", methods=["GET"])
def list_txn_cdas(transactionId):
    require_roles(*ALL_ROLES)
    get_txn_or_404(transactionId)
    items = [c for c in db["cdas"].values() if c["transaction_id"] == transactionId]
    if request.args.get("transaction_id") is not None:
        items = [c for c in items if c["transaction_id"] == request.args.get("transaction_id")]
    items = sort_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([views.cda_view(c) for c in page], total, limit, offset)


@bp.route("/cdas", methods=["GET"])
def list_cdas():
    require_roles(*ALL_ROLES)
    items = list(db["cdas"].values())
    args = request.args
    if args.get("transaction_id") is not None:
        items = [c for c in items if c["transaction_id"] == args.get("transaction_id")]
    if args.get("status") is not None:
        items = [c for c in items if c["status"] == args.get("status")]
    items = sort_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([views.cda_view(c) for c in page], total, limit, offset)


@bp.route("/cdas/<cdaId>/review", methods=["POST"])
def review_cda(cdaId):
    uid, role = require_roles("ComplianceAuditor", "TrustAccountant", "ManagingBroker")
    c = get_cda_or_404(cdaId)
    if c["status"] != "IN_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "CDA is not IN_REVIEW")
    body = request.get_json(silent=True) or {}
    verdict = body.get("verdict")
    if verdict not in ("APPROVE", "REJECT"):
        raise err_invalid_request("verdict must be APPROVE or REJECT")
    rung = c["current_rung"]
    if RUNG_ROLES.get(rung) != role:
        raise ApiError("ERR_REVIEW_RUNG_MISMATCH", 409,
                       "Caller role does not own the current rung")
    if verdict == "APPROVE":
        if rung >= 2:
            c["status"] = "APPROVED"
        else:
            c["current_rung"] = rung + 1
    else:  # REJECT cycles back to rung 0
        c["current_rung"] = 0
    touch(c)
    return ok(views.cda_view(c))


# ---------------------------------------------------------------------------
# Closing statement lines
# ---------------------------------------------------------------------------

@bp.route("/closing-statement-lines/<lineId>", methods=["GET"])
def get_closing_line(lineId):
    require_roles(*ALL_ROLES)
    l = db["closing_lines"].get(lineId)
    if not l:
        raise err_not_found("ClosingStatementLine not found")
    return ok(views.closing_line_view(l))


def _filter_closing_lines(items, args):
    if args.get("transaction_id") is not None:
        items = [l for l in items if l["transaction_id"] == args.get("transaction_id")]
    if args.get("agent_id") is not None:
        items = [l for l in items if l.get("agent_id") == args.get("agent_id")]
    if args.get("applied_invoice_line_id") is not None:
        items = [l for l in items if l.get("applied_invoice_line_id") == args.get("applied_invoice_line_id")]
    if args.get("variant") is not None:
        items = [l for l in items if l["variant"] == args.get("variant")]
    if args.get("status") is not None:
        items = [l for l in items if l["status"] == args.get("status")]
    return items


@bp.route("/transactions/<transactionId>/closing-statement-lines", methods=["GET"])
def list_txn_closing_lines(transactionId):
    require_roles(*ALL_ROLES)
    get_txn_or_404(transactionId)
    items = [l for l in db["closing_lines"].values() if l["transaction_id"] == transactionId]
    items = _filter_closing_lines(items, request.args)
    items = sort_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([views.closing_line_view(l) for l in page], total, limit, offset)


@bp.route("/closing-statement-lines", methods=["GET"])
def list_closing_lines():
    require_roles(*ALL_ROLES)
    items = list(db["closing_lines"].values())
    items = _filter_closing_lines(items, request.args)
    items = sort_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([views.closing_line_view(l) for l in page], total, limit, offset)
