"""Offset read endpoints (PRD §3.4)."""
from flask import Blueprint, request

from db import STORE
from errors import err_not_found
from middleware import authenticate, list_page
from response import ok, ok_list
from serializers import serialize_offset

bp = Blueprint("offsets", __name__)


@bp.get("/offsets/<string:offsetId>")
def get_offset(offsetId):
    authenticate()
    offset = STORE["offsets"].get(offsetId)
    if offset is None:
        raise err_not_found("Offset not found")
    return ok(serialize_offset(offset))


@bp.get("/offsets")
def list_offsets():
    authenticate()
    items = list(STORE["offsets"].values())
    payment_id = request.args.get("payment_id")
    debt_id = request.args.get("debt_id")
    status = request.args.get("status")
    if payment_id is not None:
        items = [o for o in items if o["payment_id"] == payment_id]
    if debt_id is not None:
        items = [o for o in items if o["debt_id"] == debt_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    page, limit, offset_n, total = list_page(items)
    return ok_list([serialize_offset(o) for o in page], limit, offset_n, total)
