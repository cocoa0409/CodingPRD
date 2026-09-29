"""Points-and-fees schedule items."""
from flask import Blueprint, request

from core import (ApiError, Field, authenticate, ordered, paginate, raw_body,
                  require_range, respond_collection, respond_created, respond_object,
                  validate_body)
from store import Tx, db, resolve_fk
import services

bp = Blueprint("fees", __name__)

FEE_CATEGORIES = ("ORIGINATION_POINTS", "DISCOUNT_POINTS", "AFFILIATE_TITLE",
                  "THIRD_PARTY_UNAFFILIATED", "PMI_UPFRONT", "ESCROW_TAXES",
                  "PREPAYMENT_PENALTY", "LOAN_LEVEL_PRICE_ADJUSTMENT")
WRITE_ROLES = ("LoanOfficer", "Underwriter")
FEE_READERS = ("LoanOfficer", "Underwriter", "CreditCommittee", "ChiefCreditOfficer",
               "PostCloseAuditor")

FEE_FIELDS = [
    Field("loan_file_id", "str", True),
    Field("fee_code", "str", True),
    Field("fee_category", "enum", True, FEE_CATEGORIES),
    Field("amount_cents", "int", True),
    Field("paid_to_affiliate_flag", "bool"),
    Field("prepaid_finance_charge_flag", "bool"),
    Field("bona_fide_discount_flag", "bool"),
]


@bp.post("/points-and-fees-items")
def create_fee_item():
    authenticate(WRITE_ROLES)
    raw = raw_body()
    loan_file = resolve_fk(raw, "loan_file_id", "loan_files")
    values = validate_body(FEE_FIELDS)
    # priority 7
    require_range(values["amount_cents"] > 0, "amount_cents must be greater than zero")
    # priority 10
    if loan_file["status"] == "DENIED":
        raise ApiError("ERR_LOAN_FILE_STATE_INVALID",
                       "a denied loan file accepts no fee items")
    # priority 28
    for existing in services.fee_items_of(loan_file):
        if existing["fee_code"] == values["fee_code"]:
            raise ApiError("ERR_DUPLICATE_CODE",
                           "fee_code must be unique within the loan file")

    tx = Tx()
    row = db.insert("fee_items", {
        "loan_file_id": loan_file["id"],
        "fee_code": values["fee_code"],
        "fee_category": values["fee_category"],
        "amount_cents": values["amount_cents"],
        "paid_to_affiliate_flag": values.get("paid_to_affiliate_flag", False),
        "prepaid_finance_charge_flag": values.get("prepaid_finance_charge_flag", False),
        "bona_fide_discount_flag": values.get("bona_fide_discount_flag", False),
        "inclusion_in_test": "EXCLUDED",
        "status": "ACTIVE",
        "void_reason": None,
    })
    # PRD 2.4 names exactly two cross-resource loan-file version bumps (opening and
    # accepting a worksheet), so a fee write recomputes the file's fee aggregates
    # without moving its `version`.
    services.points_and_fees_recompute(loan_file, tx)
    tx.commit()
    return respond_created(row)


@bp.get("/loan-files/<ident>/points-and-fees-items")
def list_fee_items(ident):
    authenticate(FEE_READERS)
    loan_file = db.fetch("loan_files", ident)
    rows = services.fee_items_of(loan_file)
    for key in ("status", "inclusion_in_test"):
        wanted = request.args.get(key)
        if wanted:
            rows = [r for r in rows if r[key] == wanted]
    page, limit, offset, total = paginate(ordered(rows))
    return respond_collection(page, limit, offset, total)


@bp.post("/points-and-fees-items/<ident>/void")
def void_fee_item(ident):
    authenticate(WRITE_ROLES)
    item = db.fetch("fee_items", ident)
    values = validate_body([Field("void_reason", "str", True)])
    if item["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_REQUEST", "the fee item is already VOIDED")

    tx = Tx()
    tx.watch(item)
    item["status"] = "VOIDED"
    item["void_reason"] = values["void_reason"]
    loan_file = db.find("loan_files", item["loan_file_id"])
    # PRD 2.4: a fee write is not one of the two mutations that move the loan file's
    # `version`.
    services.points_and_fees_recompute(loan_file, tx)
    tx.commit()
    return respond_object(item)
