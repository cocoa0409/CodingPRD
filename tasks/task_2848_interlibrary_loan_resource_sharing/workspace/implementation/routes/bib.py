"""Bibliographic item endpoints (PRD 3.3)."""
from flask import Blueprint

from db import base_row, db, touch
from middleware import (ACQUISITIONS, ADMIN, ILL_STAFF, PATRON, auth, get_bib_item)
from response import ok_row
from routes.common import filter_eq, list_response
from validate import (bad, body, opt_enum, opt_int, opt_str, q_enum, q_str,
                      req_enum, req_int, req_str)

bp = Blueprint("bib", __name__)

ITEM_TYPES = ("BOOK", "ARTICLE", "CHAPTER", "THESIS", "MEDIA")
HOLDING_STATUSES = ("NONE", "HELD_AVAILABLE", "HELD_CHECKED_OUT", "ON_ORDER")
LICENSED_STATUSES = ("NONE", "LICENSED_FULL", "LICENSED_EMBARGOED")


@bp.route("/ill/bib-items", methods=["POST"])
def create_bib_item():
    auth(ADMIN, ILL_STAFF, ACQUISITIONS)
    data = body()
    title = req_str(data, "title")
    item_type = req_enum(data, "item_type", ITEM_TYPES)
    publication_year = req_int(data, "publication_year", 1500, 2100)
    issn = opt_str(data, "issn")
    isbn = opt_str(data, "isbn")
    journal_title = opt_str(data, "journal_title")
    holding = opt_enum(data, "local_holding_status", HOLDING_STATUSES, "NONE")
    licensed = opt_enum(data, "licensed_access_status", LICENSED_STATUSES, "NONE")
    embargo_months = opt_int(data, "embargo_months", 0, 0)
    list_price = opt_int(data, "list_price_cents", 0, 0)
    if item_type == "ARTICLE" and issn is None:
        bad("Field 'issn' is required when item_type is ARTICLE.")
    row = base_row()
    row.update({
        "title": title,
        "item_type": item_type,
        "issn": issn,
        "isbn": isbn,
        "journal_title": journal_title,
        "publication_year": publication_year,
        "local_holding_status": holding,
        "licensed_access_status": licensed,
        "embargo_months": embargo_months,
        "list_price_cents": list_price,
    })
    db.bib_items[row["id"]] = row
    return ok_row(row, 201)


@bp.route("/ill/bib-items/<bib_id>", methods=["PATCH"])
def patch_bib_item(bib_id):
    auth(ADMIN, ACQUISITIONS)
    bib = get_bib_item(bib_id)
    data = body()
    holding = opt_enum(data, "local_holding_status", HOLDING_STATUSES)
    licensed = opt_enum(data, "licensed_access_status", LICENSED_STATUSES)
    embargo_months = opt_int(data, "embargo_months", None, 0)
    list_price = opt_int(data, "list_price_cents", None, 0)
    for field, value in (("local_holding_status", holding),
                         ("licensed_access_status", licensed),
                         ("embargo_months", embargo_months),
                         ("list_price_cents", list_price)):
        if value is not None:
            bib[field] = value
    touch(bib)
    return ok_row(bib)


@bp.route("/ill/bib-items/<bib_id>", methods=["GET"])
def get_one_bib_item(bib_id):
    auth(PATRON, ILL_STAFF, ACQUISITIONS, ADMIN)
    return ok_row(get_bib_item(bib_id))


@bp.route("/ill/bib-items", methods=["GET"])
def list_bib_items():
    auth(ILL_STAFF, ACQUISITIONS, ADMIN)
    rows = list(db.bib_items.values())
    rows = filter_eq(rows, "issn", q_str("issn"))
    rows = filter_eq(rows, "item_type", q_enum("item_type", ITEM_TYPES))
    rows = filter_eq(rows, "local_holding_status",
                     q_enum("local_holding_status", HOLDING_STATUSES))
    return list_response(rows)
