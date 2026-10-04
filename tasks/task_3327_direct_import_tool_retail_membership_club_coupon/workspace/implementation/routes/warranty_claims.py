"""WarrantyClaim endpoints."""
from flask import Blueprint, request
from db import DB
from response import success, success_list, parse_pagination, paginate
from middleware import require_roles
from entities import stamp_new, touch, get_or_404
from errors import raise_err
from calc import recompute_claim_rate

bp = Blueprint("warranty_claims", __name__)

READ_ROLES = ("WarrantyAdjuster", "OpsAdmin", "StoreClerk")
GET_ROLES = ("WarrantyAdjuster", "OpsAdmin", "StoreClerk", "Customer")


def w_view(w):
    return dict(w)


def _refresh_rate_for_claim(claim):
    line = DB.sale_lines.get(claim["sale_line_id"])
    if not line:
        return
    covered = line.get("covered_item_id")
    if covered and covered in DB.items:
        item = DB.items[covered]
        item["warranty_claim_rate"] = recompute_claim_rate(covered)
        touch(item)


@bp.route("/warranty-claims", methods=["POST"])
@require_roles("Customer", "StoreClerk")
def create_claim():
    b = request.get_json(silent=True) or {}
    for f in ("sale_line_id", "reason", "claim_amount_cents"):
        if b.get(f) is None:
            raise_err("ERR_VALIDATION", f"Missing field: {f}")
    line = DB.sale_lines.get(b["sale_line_id"])
    if not line:
        raise_err("ERR_NOT_FOUND", "Sale line not found")
    if not isinstance(b["claim_amount_cents"], int) or b["claim_amount_cents"] <= 0:
        raise_err("ERR_VALIDATION", "claim_amount_cents must be > 0")
    if not line.get("is_warranty_line"):
        raise_err("ERR_VALIDATION", "sale_line must be a warranty line")
    sale = DB.sales.get(line["sale_id"])
    if not sale or sale["status"] not in ("COMPLETED", "RETURNED_PARTIAL"):
        raise_err("ERR_INVALID_STATE", "Warranty line's sale not COMPLETED/RETURNED_PARTIAL")
    rec = stamp_new({
        "sale_line_id": line["id"],
        "reason": b["reason"],
        "claim_amount_cents": b["claim_amount_cents"],
        "settled_amount_cents": None,
        "appeal_count": 0,
        "status": "FILED",
    })
    DB.warranty_claims[rec["id"]] = rec
    _refresh_rate_for_claim(rec)
    return success(w_view(rec), status=201)


@bp.route("/warranty-claims", methods=["GET"])
@require_roles(*READ_ROLES)
def list_claims():
    limit, offset = parse_pagination(request.args)
    rows = sorted(DB.warranty_claims.values(), key=lambda r: r["created_at"])
    st = request.args.get("status")
    slid = request.args.get("sale_line_id")
    if st:
        rows = [r for r in rows if r["status"] == st]
    if slid:
        rows = [r for r in rows if r["sale_line_id"] == slid]
    page, total = paginate(rows, limit, offset)
    return success_list([w_view(r) for r in page], limit, offset, total)


@bp.route("/warranty-claims/<claimId>", methods=["GET"])
@require_roles(*GET_ROLES)
def get_claim(claimId):
    return success(w_view(get_or_404(DB.warranty_claims, claimId)))


def _transition(claimId, from_states, to_state):
    c = get_or_404(DB.warranty_claims, claimId)
    if c["status"] not in from_states:
        raise_err("ERR_INVALID_STATE", "Invalid claim transition")
    c["status"] = to_state
    touch(c)
    _refresh_rate_for_claim(c)
    return c


@bp.route("/warranty-claims/<claimId>/start-review", methods=["POST"])
@require_roles("WarrantyAdjuster")
def start_review(claimId):
    return success(w_view(_transition(claimId, ("FILED",), "UNDER_REVIEW")))


@bp.route("/warranty-claims/<claimId>/approve", methods=["POST"])
@require_roles("WarrantyAdjuster")
def approve(claimId):
    return success(w_view(_transition(claimId, ("UNDER_REVIEW",), "APPROVED")))


@bp.route("/warranty-claims/<claimId>/deny", methods=["POST"])
@require_roles("WarrantyAdjuster")
def deny(claimId):
    return success(w_view(_transition(claimId, ("UNDER_REVIEW",), "DENIED")))


@bp.route("/warranty-claims/<claimId>/appeal", methods=["POST"])
@require_roles("Customer")
def appeal(claimId):
    c = get_or_404(DB.warranty_claims, claimId)
    if c["status"] != "DENIED":
        raise_err("ERR_INVALID_STATE", "Claim not DENIED")
    if c["appeal_count"] >= 1:
        raise_err("ERR_CLAIM_APPEAL_EXHAUSTED", "Appeal already used")
    if c["claim_amount_cents"] > 100000:
        raise_err("ERR_CLAIM_FINAL", "Claim is final on first denial")
    c["appeal_count"] += 1
    c["status"] = "UNDER_REVIEW"
    touch(c)
    _refresh_rate_for_claim(c)
    return success(w_view(c))


@bp.route("/warranty-claims/<claimId>/settle", methods=["POST"])
@require_roles("WarrantyAdjuster")
def settle(claimId):
    c = get_or_404(DB.warranty_claims, claimId)
    if c["status"] != "APPROVED":
        raise_err("ERR_INVALID_STATE", "Claim not APPROVED")
    b = request.get_json(silent=True) or {}
    amt = b.get("settled_amount_cents")
    if not isinstance(amt, int) or amt < 0:
        raise_err("ERR_VALIDATION", "settled_amount_cents must be >= 0")
    if amt > c["claim_amount_cents"]:
        raise_err("ERR_SETTLEMENT_EXCEEDS_CLAIM", "Settlement exceeds claim")
    c["settled_amount_cents"] = amt
    c["status"] = "SETTLED"
    touch(c)
    line = DB.sale_lines.get(c["sale_line_id"])
    if line:
        sale = DB.sales.get(line["sale_id"])
        if sale:
            customer = DB.customers.get(sale["customer_id"])
            if customer:
                customer["store_credit_cents"] += amt
                touch(customer)
    _refresh_rate_for_claim(c)
    return success(w_view(c))
