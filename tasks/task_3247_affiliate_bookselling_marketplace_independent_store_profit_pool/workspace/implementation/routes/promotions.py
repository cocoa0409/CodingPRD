"""Clock control and promotion endpoints."""
from flask import Blueprint, request

import db
import helpers
from errors import (
    err_validation, err_commercial_terms, err_promotion_window_conflict,
)
from middleware import require_roles
from response import ok_object, ok_empty

bp = Blueprint("promotions", __name__)

ONE_DAY_SECONDS = 86400


def promotion_view(p):
    return {
        "id": p["id"],
        "book_isbn": p["book_isbn"],
        "discount_pct": p["discount_pct"],
        "window_start": p["window_start"],
        "window_end": p["window_end"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@bp.post("/bookshop/_clock/set_current_utc")
def set_clock():
    require_roles(["PlatformAdmin"])
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_validation("JSON body required")
    to_iso8601 = body.get("to_iso8601")
    dt = helpers.parse_dt(to_iso8601)
    db.set_clock(dt)
    helpers.reevaluate_promotions()
    return ok_empty(200)


@bp.post("/bookshop/promotions")
def create_promotion():
    require_roles(["PlatformAdmin"])
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_validation("JSON body required")
    book_isbn = body.get("book_isbn")
    discount_pct = body.get("discount_pct")
    window_start = body.get("window_start")
    window_end = body.get("window_end")

    if not isinstance(book_isbn, str) or not book_isbn:
        raise err_validation("book_isbn is required")
    book = next((b for b in db.DB.books.values() if b["isbn"] == book_isbn), None)
    if book is None or book["status"] != "LISTED":
        raise err_validation("book_isbn must resolve to an existing LISTED book")
    if not isinstance(discount_pct, (int, float)) or isinstance(discount_pct, bool):
        raise err_validation("discount_pct must be a number")
    ws = helpers.parse_dt(window_start)
    we = helpers.parse_dt(window_end)
    if we < ws:
        raise err_validation("window_end must be >= window_start")

    if not (0.05 <= discount_pct <= 0.40):
        raise err_commercial_terms("discount_pct must be within 0.05-0.40")

    # Window conflict: must leave at least a 1-day gap vs other non-ENDED
    # promotions on the same ISBN. ENDED promotions no longer block.
    helpers.reevaluate_promotions()
    for other in db.DB.promotions.values():
        if other["book_isbn"] != book_isbn or other["status"] == "ENDED":
            continue
        ows = other["_window_start_dt"]
        owe = other["_window_end_dt"]
        clear_after = ws.timestamp() > owe.timestamp() + ONE_DAY_SECONDS
        clear_before = we.timestamp() < ows.timestamp() - ONE_DAY_SECONDS
        if not (clear_after or clear_before):
            raise err_promotion_window_conflict()

    p = helpers.base_resource()
    status = "SCHEDULED"
    now = db.get_clock()
    if now > we:
        status = "ENDED"
    elif ws <= now <= we:
        status = "ACTIVE"
    p.update({
        "book_isbn": book_isbn,
        "discount_pct": discount_pct,
        "window_start": window_start,
        "window_end": window_end,
        "status": status,
        "_window_start_dt": ws,
        "_window_end_dt": we,
    })
    db.DB.promotions[p["id"]] = p
    return ok_object(promotion_view(p), 201)
