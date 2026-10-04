"""Sale endpoints: create/list/get, lines, apply-coupon, complete, void, returns."""
from datetime import timedelta
from flask import Blueprint, request
from db import DB, fmt_iso, parse_iso
from response import success, success_list, parse_pagination, paginate
from middleware import require_roles
from entities import stamp_new, touch, get_or_404, lazy_coupon, effective_member
from errors import raise_err
from calc import (basket_cents, coupon_discount_amount, margin_floor_ok,
                  nonwarranty_lines)
from savings import recompute_membership_savings

bp = Blueprint("sales", __name__)

SALE_READ = ("StoreClerk", "Customer", "WarrantyAdjuster", "OpsAdmin")
SALE_LIST = ("StoreClerk", "OpsAdmin", "WarrantyAdjuster")
LINE_LIST = ("StoreClerk", "Customer", "WarrantyAdjuster", "OpsAdmin")
LINE_GLOBAL_LIST = ("StoreClerk", "WarrantyAdjuster", "OpsAdmin")


def s_view(s):
    return dict(s)


def _sale_lines(sale_id):
    return sorted(
        [l for l in DB.sale_lines.values() if l["sale_id"] == sale_id],
        key=lambda l: l["created_at"],
    )


def _recompute_subtotal(sale):
    sale["subtotal_cents"] = sum(l["line_total_cents"] for l in _sale_lines(sale["id"]))
    sale["total_cents"] = (sale["subtotal_cents"] - sale["coupon_discount_cents"]
                           - sale["store_credit_applied_cents"])


def _resolve_price(customer_id, item):
    m = effective_member(customer_id)
    if m:
        return min(item["member_price_cents"], item["unit_retail_cents"])
    return item["unit_retail_cents"]


@bp.route("/sales", methods=["POST"])
@require_roles("StoreClerk")
def create_sale():
    b = request.get_json(silent=True) or {}
    if not b.get("store_id") or not b.get("customer_id"):
        raise_err("ERR_VALIDATION", "store_id and customer_id required")
    store = DB.stores.get(b["store_id"])
    if not store:
        raise_err("ERR_NOT_FOUND", "Store not found")
    customer = DB.customers.get(b["customer_id"])
    if not customer:
        raise_err("ERR_NOT_FOUND", "Customer not found")
    rec = stamp_new({
        "store_id": store["id"],
        "customer_id": customer["id"],
        "status": "OPEN",
        "applied_coupon_id": None,
        "subtotal_cents": 0,
        "coupon_discount_cents": 0,
        "total_cents": 0,
        "store_credit_applied_cents": 0,
        "completed_at": None,
        "returned_line_quantities": {},
    })
    DB.sales[rec["id"]] = rec
    return success(s_view(rec), status=201)


@bp.route("/sales", methods=["GET"])
@require_roles(*SALE_LIST)
def list_sales():
    limit, offset = parse_pagination(request.args)
    rows = sorted(DB.sales.values(), key=lambda r: r["created_at"])
    sid = request.args.get("store_id")
    cid = request.args.get("customer_id")
    st = request.args.get("status")
    if sid:
        rows = [r for r in rows if r["store_id"] == sid]
    if cid:
        rows = [r for r in rows if r["customer_id"] == cid]
    if st:
        rows = [r for r in rows if r["status"] == st]
    page, total = paginate(rows, limit, offset)
    return success_list([s_view(r) for r in page], limit, offset, total)


@bp.route("/sales/<saleId>", methods=["GET"])
@require_roles(*SALE_READ)
def get_sale(saleId):
    return success(s_view(get_or_404(DB.sales, saleId)))


@bp.route("/sales/<saleId>/lines", methods=["POST"])
@require_roles("StoreClerk")
def add_line(saleId):
    sale = get_or_404(DB.sales, saleId)
    if sale["status"] != "OPEN":
        raise_err("ERR_INVALID_STATE", "Sale not OPEN")
    b = request.get_json(silent=True) or {}
    if not b.get("item_id"):
        raise_err("ERR_VALIDATION", "item_id required")
    item = DB.items.get(b["item_id"])
    if not item:
        raise_err("ERR_NOT_FOUND", "Item not found")
    qty = b.get("quantity")
    if not isinstance(qty, int) or qty < 1:
        raise_err("ERR_VALIDATION", "quantity must be >= 1")
    is_warranty = bool(b.get("is_warranty_line", False))
    if item["lifecycle_status"] != "ACTIVE":
        raise_err("ERR_ITEM_NOT_ACTIVE", "Item not ACTIVE")
    if is_warranty:
        covered = b.get("covered_item_id")
        wprice = b.get("warranty_price_cents")
        if covered is None or wprice is None:
            raise_err("ERR_VALIDATION", "warranty line requires covered_item_id and warranty_price_cents")
        if not isinstance(wprice, int) or wprice <= 0:
            raise_err("ERR_VALIDATION", "warranty_price_cents must be > 0")
        # covered item must be a merchandise line's item on the same sale
        merch_items = {l["item_id"] for l in _sale_lines(sale["id"]) if not l.get("is_warranty_line")}
        if covered not in merch_items:
            raise_err("ERR_INVALID_REFERENCE", "covered_item_id not a merchandise line on this sale")
        rec = stamp_new({
            "sale_id": sale["id"],
            "item_id": item["id"],
            "quantity": qty,
            "is_warranty_line": True,
            "covered_item_id": covered,
            "warranty_price_cents": wprice,
            "unit_price_cents": wprice,
            "line_total_cents": wprice * qty,
        })
    else:
        if not margin_floor_ok(item, _resolve_price(sale["customer_id"], item)):
            raise_err("ERR_MARGIN_FLOOR_VIOLATION", "Line price below margin floor")
        price = _resolve_price(sale["customer_id"], item)
        rec = stamp_new({
            "sale_id": sale["id"],
            "item_id": item["id"],
            "quantity": qty,
            "is_warranty_line": False,
            "covered_item_id": None,
            "warranty_price_cents": None,
            "unit_price_cents": price,
            "line_total_cents": price * qty,
        })
    DB.sale_lines[rec["id"]] = rec
    _recompute_subtotal(sale)
    touch(sale)
    return success(dict(rec), status=201)


@bp.route("/sales/<id>/lines", methods=["GET"])
@require_roles(*LINE_LIST)
def list_sale_lines(id):
    get_or_404(DB.sales, id)
    limit, offset = parse_pagination(request.args)
    rows = _sale_lines(id)
    page, total = paginate(rows, limit, offset)
    return success_list([dict(r) for r in page], limit, offset, total)


@bp.route("/sale-lines/<lineId>", methods=["GET"])
@require_roles(*LINE_LIST)
def get_sale_line(lineId):
    return success(dict(get_or_404(DB.sale_lines, lineId)))


@bp.route("/sale-lines", methods=["GET"])
@require_roles(*LINE_GLOBAL_LIST)
def list_sale_lines_global():
    limit, offset = parse_pagination(request.args)
    rows = sorted(DB.sale_lines.values(), key=lambda r: r["created_at"])
    sid = request.args.get("sale_id")
    iid = request.args.get("item_id")
    if sid:
        rows = [r for r in rows if r["sale_id"] == sid]
    if iid:
        rows = [r for r in rows if r["item_id"] == iid]
    page, total = paginate(rows, limit, offset)
    return success_list([dict(r) for r in page], limit, offset, total)
