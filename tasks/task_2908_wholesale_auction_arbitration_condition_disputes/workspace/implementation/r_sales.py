"""The block: sale records, condition announcements and proceeds release."""
from flask import Blueprint

import services as S
import store as C
from authz import ALL_ROLES, authenticate
from envelope import arr, created, obj, unpaginated
from errors import fail
from store import store
from util import iso, public, public_list
from validators import (json_body, q_enum, q_pagination, q_str, req_dt, req_enum,
                        req_int, req_str)

bp = Blueprint("sales", __name__)

_VIN_ALPHABET = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")


def _vin(body):
    value = req_str(body, "vin", 17, 17)
    for char in value:
        if char not in _VIN_ALPHABET:
            fail("ERR_INVALID_REQUEST", "Field 'vin' must be uppercase alphanumeric.")
    return value


@bp.route("/arbitration/sales", methods=["POST"])
def create_sale():
    authenticate(["BlockClerk"])
    body = json_body()
    vin = _vin(body)
    seller_id = req_str(body, "seller_id")
    buyer_id = req_str(body, "buyer_id")
    sale_price_cents = req_int(body, "sale_price_cents", 1)
    hammer_time = req_dt(body, "hammer_time_utc")
    announced_odometer_miles = req_int(body, "announced_odometer_miles", 0)
    light_channel = req_enum(body, "light_channel", C.LIGHT_CHANNELS)
    title_status = req_enum(body, "title_status", C.TITLE_STATUSES)
    if hammer_time > store.now():
        fail("ERR_INVALID_REQUEST",
             "Field 'hammer_time_utc' may not be later than the current logical clock.")
    seller = S.get_seller(seller_id)
    buyer = S.get_buyer(buyer_id)
    row = {
        "vin": vin,
        "seller_id": seller["id"],
        "buyer_id": buyer["id"],
        "sale_price_cents": sale_price_cents,
        "hammer_time_utc": iso(hammer_time),
        "announced_odometer_miles": announced_odometer_miles,
        "light_channel": light_channel,
        "title_status": title_status,
        "settlement_status": "UNSETTLED",
        "settled_at_utc": None,
        "arbitration_status": "NONE",
        "open_case_count": 0,
        "settlement_hold": False,
    }
    store.insert("sales", row, mutable=True)
    return created(public(row))


@bp.route("/arbitration/sales/<sale_id>", methods=["GET"])
def read_sale(sale_id):
    authenticate(ALL_ROLES)
    return obj(public(S.get_sale(sale_id)))


@bp.route("/arbitration/sales", methods=["GET"])
def list_sales():
    authenticate(ALL_ROLES)
    limit, offset = q_pagination()
    seller_id = q_str("seller_id")
    buyer_id = q_str("buyer_id")
    settlement_status = q_enum("settlement_status", C.SETTLEMENT_STATUSES)
    rows = store.rows("sales")
    if seller_id is not None:
        rows = [r for r in rows if r["seller_id"] == seller_id]
    if buyer_id is not None:
        rows = [r for r in rows if r["buyer_id"] == buyer_id]
    if settlement_status is not None:
        rows = [r for r in rows if r["settlement_status"] == settlement_status]
    total = len(rows)
    page = rows[offset:offset + limit]
    return arr(public_list(page), limit, offset, total)


@bp.route("/arbitration/sales/<sale_id>/announcements", methods=["POST"])
def create_announcement(sale_id):
    authenticate(["BlockClerk"])
    body = json_body()
    defect_class = req_enum(body, "defect_class", C.DEFECT_CLASSES)
    disclosure_text = req_str(body, "disclosure_text", 1, 500)
    sale = S.get_sale(sale_id)
    row = {
        "sale_id": sale["id"],
        "defect_class": defect_class,
        "disclosure_text": disclosure_text,
        "announced_at_utc": store.now_iso(),
    }
    store.insert("announcements", row, mutable=False)
    return created(public(row))


@bp.route("/arbitration/sales/<sale_id>/announcements", methods=["GET"])
def list_announcements(sale_id):
    authenticate(ALL_ROLES)
    sale = S.get_sale(sale_id)
    return unpaginated(public_list(S.children("announcements", "sale_id", sale["id"])))


@bp.route("/arbitration/sales/<sale_id>/settle", methods=["POST"])
def settle_sale(sale_id):
    authenticate(["AuctionAdmin"])
    sale = S.get_sale(sale_id)
    if sale["settlement_status"] != "UNSETTLED":
        fail("ERR_SALE_ALREADY_SETTLED")
    seller = store.sellers.get(sale["seller_id"])
    if (seller is not None and seller["policy_tier"] == "BLOCKED") or sale["settlement_hold"]:
        fail("ERR_SELLER_BLOCKED")
    price = int(sale["sale_price_cents"])
    sale["settlement_status"] = "SETTLED"
    sale["settled_at_utc"] = store.now_iso()
    S.post_ledger(sale["id"], None, "SELLER", "SALE_PROCEEDS", price)
    S.post_ledger(sale["id"], None, "BUYER", "SALE_PROCEEDS", -price)
    S.touch(sale)
    return obj(public(sale))


@bp.route("/arbitration/sales/<sale_id>/ledger-entries", methods=["GET"])
def list_sale_ledger(sale_id):
    authenticate(ALL_ROLES)
    sale = S.get_sale(sale_id)
    return unpaginated(public_list(S.children("ledger", "sale_id", sale["id"])))


@bp.route("/arbitration/sales/<sale_id>/post-sale-inspections", methods=["GET"])
def list_sale_inspections(sale_id):
    authenticate(ALL_ROLES)
    sale = S.get_sale(sale_id)
    return unpaginated(public_list(S.children("inspections", "sale_id", sale["id"])))
