"""Payment posting reads (PRD 3.5)."""
from flask import Blueprint

import db
import lookups
import response
import serialize
import validate
from constants import (
    POSTING_TYPES, ROLE_COLLECTIONS_OFFICER, ROLE_CUSTOMER, ROLE_PROGRAM_ADMIN,
    ROLE_RETAIL_ASSOCIATE,
)
from middleware import require_owner, require_roles

bp = Blueprint("postings", __name__)

READ_ROLES = (ROLE_CUSTOMER, ROLE_RETAIL_ASSOCIATE, ROLE_COLLECTIONS_OFFICER,
              ROLE_PROGRAM_ADMIN)


@bp.get("/payment-postings")
def list_postings():
    require_roles(*READ_ROLES)
    limit, offset = validate.pagination()
    loan_id = validate.query_str("loan_id")
    reverses_posting_id = validate.query_str("reverses_posting_id")
    posting_type = validate.query_enum("posting_type", POSTING_TYPES)
    rows = db.values(db.payment_postings)
    if loan_id is not None:
        rows = [r for r in rows if r["loan_id"] == loan_id]
    if reverses_posting_id is not None:
        rows = [r for r in rows if r["reverses_posting_id"] == reverses_posting_id]
    if posting_type is not None:
        rows = [r for r in rows if r["posting_type"] == posting_type]
    page, total = validate.paginate(rows, limit, offset)
    return response.list_response([serialize.payment_posting(r) for r in page],
                                  limit, offset, total)


@bp.get("/payment-postings/<posting_id>")
def read_posting(posting_id):
    require_roles(*READ_ROLES)
    existing = db.payment_postings.get(posting_id)
    owner = None
    if existing is not None:
        loan = db.loans.get(existing["loan_id"])
        owner = loan["customer_id"] if loan is not None else None
    require_owner(owner)
    record = lookups.payment_posting(posting_id)
    return response.object_response(serialize.payment_posting(record))
