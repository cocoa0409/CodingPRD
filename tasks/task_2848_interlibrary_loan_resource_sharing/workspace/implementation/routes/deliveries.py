"""Electronic delivery of article scans (PRD 3.8)."""
from flask import Blueprint

from db import add_days, base_row, db, now, touch
from errors import ApiError
from middleware import (ADMIN, ILL_STAFF, PARTNER_AGENT, PATRON, auth, get_delivery,
                        get_request, own_delivery, own_request)
from response import ok_row
from services import calc, derive
from validate import body, req_int, req_str

bp = Blueprint("deliveries", __name__)


@bp.route("/ill/requests/<request_id>/electronic-deliveries", methods=["POST"])
def create_delivery(request_id):
    user_id, role = auth(PARTNER_AGENT, ILL_STAFF)
    req = get_request(request_id)
    own_request(req, user_id, role, partner_side=True)
    data = body()
    file_token = req_str(data, "file_token")
    pages_delivered = req_int(data, "pages_delivered", 1, 200)
    partner = db.partners.get(req.get("committed_partner_id")) or {}
    # rung 40: the request transition SUPPLY_COMMITTED -> DELIVERED_ELECTRONIC
    # carries both of its preconditions under this one error id
    if req["status"] != "SUPPLY_COMMITTED" or req["service_type"] != "COPY" \
            or not partner.get("supplies_electronic"):
        raise ApiError("ERR_REQUEST_INVALID_STATE")
    row = base_row()
    row.update({
        "request_id": req["id"],
        "file_token": file_token,
        "pages_delivered": pages_delivered,
        "delivered_at": now(),
        "expires_at": add_days(now(), calc.DELIVERY_ACCESS_DAYS),
        "max_downloads": calc.DELIVERY_MAX_DOWNLOADS,
        "download_count": 0,
        "status": "AVAILABLE",
    })
    db.deliveries[row["id"]] = row
    req["status"] = "DELIVERED_ELECTRONIC"
    req["fulfilled_at"] = now()
    touch(req)
    bib = db.bib_items.get(req["bib_item_id"]) or {}
    derive.notify(req, "ELECTRONIC_DELIVERY_READY",
                  "Your scan is ready: %s" % bib.get("title", ""))
    return ok_row(row, 201)


@bp.route("/ill/electronic-deliveries/<delivery_id>/downloads", methods=["POST"])
def download_delivery(delivery_id):
    user_id, role = auth(PATRON, ILL_STAFF)
    delivery = get_delivery(delivery_id)
    own_delivery(delivery, user_id, role)
    # rung 44: only an EXPIRED row is stopped here; EXHAUSTED falls to rung 73
    if delivery["status"] == "EXPIRED":
        raise ApiError("ERR_DELIVERY_NOT_AVAILABLE")
    # rung 66: a lapsed but unswept window is closed to the patron
    if now() >= delivery["expires_at"]:
        raise ApiError("ERR_DELIVERY_EXPIRED")
    # rung 73
    if delivery["download_count"] >= delivery["max_downloads"]:
        raise ApiError("ERR_DELIVERY_DOWNLOAD_CAP_REACHED")
    delivery["download_count"] += 1
    if delivery["download_count"] >= delivery["max_downloads"]:
        delivery["status"] = "EXHAUSTED"
    touch(delivery)
    return ok_row(delivery)


@bp.route("/ill/electronic-deliveries/<delivery_id>", methods=["GET"])
def get_one_delivery(delivery_id):
    user_id, role = auth(PATRON, PARTNER_AGENT, ILL_STAFF, ADMIN)
    delivery = get_delivery(delivery_id)
    own_delivery(delivery, user_id, role)
    return ok_row(delivery)
