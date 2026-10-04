"""Publishers and books endpoints."""
from flask import Blueprint, request

import db
import helpers
from errors import err_validation, err_reference_not_found, err_commercial_terms
from middleware import require_roles
from response import ok_object, ok_list, paginate

bp = Blueprint("catalog", __name__)


def publisher_view(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "discount_pct": p["discount_pct"],
        "returns_allowed": p["returns_allowed"],
        "return_window_days": p["return_window_days"],
        "return_credit_pct": p["return_credit_pct"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def book_view(b):
    return {
        "id": b["id"],
        "publisher_id": b["publisher_id"],
        "isbn": b["isbn"],
        "title": b["title"],
        "format": b["format"],
        "list_price_cents": b["list_price_cents"],
        "ebook_partner_rev_share_pct": b.get("ebook_partner_rev_share_pct"),
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


@bp.post("/bookshop/publishers")
def create_publisher():
    require_roles(["PlatformAdmin"])
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_validation("JSON body required")
    name = body.get("name")
    discount_pct = body.get("discount_pct")
    returns_allowed = body.get("returns_allowed")
    return_window_days = body.get("return_window_days")
    return_credit_pct = body.get("return_credit_pct")

    if not isinstance(name, str) or not name:
        raise err_validation("name is required")
    if not isinstance(discount_pct, (int, float)) or isinstance(discount_pct, bool):
        raise err_validation("discount_pct must be a number")
    if not isinstance(returns_allowed, bool):
        raise err_validation("returns_allowed must be a boolean")
    if not isinstance(return_window_days, int) or isinstance(return_window_days, bool):
        raise err_validation("return_window_days must be an integer")
    if not isinstance(return_credit_pct, (int, float)) or isinstance(return_credit_pct, bool):
        raise err_validation("return_credit_pct must be a number")

    if not (0.0 <= discount_pct <= 0.60):
        raise err_commercial_terms("discount_pct must be within 0.00-0.60")
    if not (0.0 <= return_credit_pct <= 1.0):
        raise err_commercial_terms("return_credit_pct must be within 0.00-1.00")

    p = helpers.base_resource()
    p.update({
        "name": name,
        "discount_pct": discount_pct,
        "returns_allowed": returns_allowed,
        "return_window_days": return_window_days,
        "return_credit_pct": return_credit_pct,
        "status": "ACTIVE",
    })
    db.DB.publishers[p["id"]] = p
    return ok_object(publisher_view(p), 201)


@bp.get("/bookshop/publishers/<pid>")
def get_publisher(pid):
    require_roles(["PlatformAdmin", "WholesalerOps", "FinanceOps"])
    p = helpers.get_or_404(db.DB.publishers, pid)
    return ok_object(publisher_view(p))


@bp.get("/bookshop/publishers/<pid>/books")
def list_publisher_books(pid):
    require_roles(["PlatformAdmin", "WholesalerOps", "StoreManager", "Partner", "Customer"])
    helpers.get_or_404(db.DB.publishers, pid)
    books = [b for b in db.DB.books.values() if b["publisher_id"] == pid]
    page, limit, offset, total = paginate([book_view(b) for b in books], request.args)
    return ok_list(page, limit, offset, total)


@bp.post("/bookshop/books")
def create_book():
    require_roles(["PlatformAdmin"])
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_validation("JSON body required")
    publisher_id = body.get("publisher_id")
    isbn = body.get("isbn")
    title = body.get("title")
    fmt = body.get("format")
    list_price_cents = body.get("list_price_cents")
    rev_share = body.get("ebook_partner_rev_share_pct")

    # Body FK existence (priority 5)
    if publisher_id is not None and not isinstance(publisher_id, str):
        raise err_validation("publisher_id must be a string")
    if not isinstance(publisher_id, str) or publisher_id not in db.DB.publishers:
        raise err_reference_not_found("publisher_id does not resolve")

    # Body shape (priority 6)
    if not isinstance(isbn, str) or not isbn:
        raise err_validation("isbn is required")
    if not isinstance(title, str) or not title:
        raise err_validation("title is required")
    if fmt not in ("PRINT", "EBOOK", "AUDIOBOOK"):
        raise err_validation("format must be PRINT, EBOOK, or AUDIOBOOK")
    if not isinstance(list_price_cents, int) or isinstance(list_price_cents, bool):
        raise err_validation("list_price_cents must be an integer")

    # isbn uniqueness
    if any(b["isbn"] == isbn for b in db.DB.books.values()):
        raise err_validation("isbn must be unique")

    if fmt == "PRINT":
        if rev_share is not None:
            raise err_validation("ebook_partner_rev_share_pct must be null/absent for PRINT")
    else:
        if rev_share is None:
            raise err_validation("ebook_partner_rev_share_pct is required for digital formats")
        if not isinstance(rev_share, (int, float)) or isinstance(rev_share, bool):
            raise err_validation("ebook_partner_rev_share_pct must be a number")

    if list_price_cents <= 0:
        raise err_commercial_terms("list_price_cents must be > 0")
    if fmt in ("EBOOK", "AUDIOBOOK") and not (0.0 <= rev_share <= 0.50):
        raise err_commercial_terms("ebook_partner_rev_share_pct must be within 0.00-0.50")

    b = helpers.base_resource()
    b.update({
        "publisher_id": publisher_id,
        "isbn": isbn,
        "title": title,
        "format": fmt,
        "list_price_cents": list_price_cents,
        "ebook_partner_rev_share_pct": rev_share if fmt != "PRINT" else None,
        "status": "LISTED",
    })
    db.DB.books[b["id"]] = b
    return ok_object(book_view(b), 201)
