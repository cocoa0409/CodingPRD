"""Ownership instruments. Immutable once written: only id and created_at."""

from flask import Blueprint, request

from db import base_row, by_created_at, db, insert
from errors import ApiError
from middleware import endpoint, require_one_of
from response import object_response, paginate
from routes import lookup
from validation import SPECIES_CLASSES, body, opt_str, req_dt, req_enum, req_id, req_int, req_str

bp = Blueprint("bills_of_sale", __name__)


@bp.post("/bills-of-sale")
@endpoint("LivestockOwner")
def create_bill_of_sale():
    payload = body()
    seller_owner_id = req_id(payload, "seller_owner_id")
    buyer_owner_id = req_id(payload, "buyer_owner_id")
    document_number = req_str(payload, "document_number")
    sale_date = req_dt(payload, "sale_date")
    head_count = req_int(payload, "head_count", minimum=1)
    species_class = req_enum(payload, "species_class", SPECIES_CLASSES)
    brand_symbol_declared = opt_str(payload, "brand_symbol_declared")

    lookup.owner(seller_owner_id)
    lookup.owner(buyer_owner_id)

    require_one_of((seller_owner_id, buyer_owner_id))

    for existing in db.bills.values():
        if existing["document_number"] == document_number:
            raise ApiError("ERR_DUPLICATE_DOCUMENT_NUMBER", "document_number is already on file.")

    row = base_row(common_fields=False)
    row.update(
        {
            "seller_owner_id": seller_owner_id,
            "buyer_owner_id": buyer_owner_id,
            "document_number": document_number,
            "sale_date": sale_date,
            "head_count": head_count,
            "species_class": species_class,
            "brand_symbol_declared": brand_symbol_declared,
        }
    )
    insert(db.bills, row)
    return object_response(row, 201)


@bp.get("/bills-of-sale/<bill_id>")
@endpoint("LivestockOwner", "FieldInspector", "BoardAdmin")
def read_bill_of_sale(bill_id):
    return object_response(lookup.bill_of_sale(bill_id))


@bp.get("/bills-of-sale")
@endpoint("LivestockOwner", "FieldInspector", "BoardAdmin")
def list_bills_of_sale():
    rows = lookup.filtered(
        db.bills,
        {
            "seller_owner_id": request.args.get("seller_owner_id"),
            "buyer_owner_id": request.args.get("buyer_owner_id"),
        },
    )
    return paginate(by_created_at(rows))
