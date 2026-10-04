"""Receipt / ReceiptLine / Return routes (PRD 3.4, 3.8)."""

from flask import Blueprint

import db
from errors import ApiError
from middleware import (FINANCE_ADMIN, FRAUD_ANALYST, GUEST_SERVICE,
                        STORE_ADMIN, authenticate, get_body, opt_id,
                        query_param, req_id, req_string, parse_timestamp)
from response import object_response
from routes.common import paginated
from serialize import (receipt_line_out, receipt_out, return_out,
                       submission_out)
from services import core, lookup, temporal

bp = Blueprint("receipts", __name__)

READ_ROLES = [STORE_ADMIN, GUEST_SERVICE, FRAUD_ANALYST, FINANCE_ADMIN]
TENDER_TYPES = {"CASH", "CARD", "GIFT_CARD", "STORE_CREDIT_CERTIFICATE"}


def _bad_request(message):
    return ApiError("ERR_INVALID_REQUEST", message)


@bp.route("/stores/<store_id>/receipts", methods=["POST"])
def create_receipt(store_id):
    authenticate([GUEST_SERVICE])
    store = lookup.store(store_id)
    body = get_body()

    receipt_number = req_string(body, "receipt_number")
    account_id = req_id(body, "account_id")
    purchase_at = parse_timestamp(body, "purchase_at")
    job_purchase_id = opt_id(body, "job_purchase_id")

    lines_in = body.get("lines")
    if not isinstance(lines_in, list) or not lines_in:
        raise _bad_request("Field 'lines' must be a non-empty array")

    # Structural well-formedness of every line (ladder 4).
    seen_line_numbers = set()
    for raw in lines_in:
        if not isinstance(raw, dict):
            raise _bad_request("Each line must be an object")
        line_number = raw.get("line_number")
        if isinstance(line_number, bool) or not isinstance(line_number, int) \
                or line_number < 1:
            raise _bad_request("Field 'line_number' must be an integer >= 1")
        if line_number in seen_line_numbers:
            raise _bad_request("line_number values must be unique within the "
                               "receipt")
        seen_line_numbers.add(line_number)
        sku = raw.get("sku")
        if not isinstance(sku, str) or not sku:
            raise _bad_request("Field 'sku' must be a non-empty string")
        category = raw.get("category")
        if not isinstance(category, str) or not category:
            raise _bad_request("Field 'category' must be a non-empty string")
        quantity = raw.get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, int) \
                or quantity < 1:
            raise _bad_request("Field 'quantity' must be an integer >= 1")
        unit_price = raw.get("unit_price_cents")
        if isinstance(unit_price, bool) or not isinstance(unit_price, int) \
                or unit_price < 0:
            raise _bad_request("Field 'unit_price_cents' must be an integer "
                               ">= 0")
        splits = raw.get("tender_splits")
        if not isinstance(splits, list) or not splits:
            raise _bad_request("Field 'tender_splits' must be a non-empty "
                               "array")
        for split in splits:
            if not isinstance(split, dict):
                raise _bad_request("Each tender split must be an object")
            if split.get("tender_type") not in TENDER_TYPES:
                raise _bad_request("tender_type must be one of %s"
                                   % sorted(TENDER_TYPES))
            amount = split.get("amount_cents")
            if isinstance(amount, bool) or not isinstance(amount, int) \
                    or amount < 0:
                raise _bad_request("tender amount_cents must be an integer "
                                   ">= 0")

    # Ladder 5: tender splits sum exactly to quantity * unit_price_cents.
    for raw in lines_in:
        total = sum(s["amount_cents"] for s in raw["tender_splits"])
        if total != raw["quantity"] * raw["unit_price_cents"]:
            raise ApiError("ERR_TENDER_SPLIT_MISMATCH",
                           "tender_splits of line %s do not sum to quantity * "
                           "unit_price_cents" % raw["line_number"])

    # Ladder 6: purchase_at must not be in the future.
    if purchase_at > db.clock_now():
        raise ApiError("ERR_RECEIPT_IN_FUTURE",
                       "purchase_at is after the logical clock")

    # Ladder 7: account exists (404 when missing); job purchase referential
    # rules (422).
    account = db.accounts.get(account_id)
    if account is None:
        raise ApiError("ERR_NOT_FOUND", "CreditAccount not found")
    if job_purchase_id is not None:
        job = db.jobs.get(job_purchase_id)
        if (account["account_type"] != "CONTRACTOR" or job is None
                or job["contractor_account_id"] != account_id
                or job["status"] != "OPEN"):
            raise ApiError("ERR_INVALID_JOB_PURCHASE",
                           "job_purchase_id must reference an OPEN job owned "
                           "by the purchasing CONTRACTOR account")

    # receipt_number unique per store.
    for other in db.receipts.values():
        if other["store_id"] == store_id \
                and other["receipt_number"] == receipt_number:
            raise ApiError("ERR_DUPLICATE_RECEIPT_NUMBER",
                           "receipt_number already exists at this store")

    receipt = db.base_record()
    receipt.update({
        "store_id": store_id,
        "receipt_number": receipt_number,
        "account_id": account_id,
        "job_purchase_id": job_purchase_id,
        "purchase_at": _ts(purchase_at),
        "status": "OPEN",
        "total_cents": sum(r["quantity"] * r["unit_price_cents"]
                           for r in lines_in),
    })
    # Temporal comparisons run at second granularity (calculation
    # fraud_screening precision note); the stored purchase_at keeps the
    # caller's precision while _purchase_at_norm is second-truncated.
    receipt["_purchase_at_norm"] = _ts(purchase_at.replace(microsecond=0))
    db.receipts[receipt["id"]] = receipt

    for raw in sorted(lines_in, key=lambda r: r["line_number"]):
        line = db.base_record(versioned=False)
        cert_tendered = sum(s["amount_cents"] for s in raw["tender_splits"]
                            if s["tender_type"] == "STORE_CREDIT_CERTIFICATE")
        line.update({
            "receipt_id": receipt["id"],
            "store_id": store_id,
            "line_number": raw["line_number"],
            "sku": raw["sku"],
            "category": raw["category"],
            "quantity": raw["quantity"],
            "unit_price_cents": raw["unit_price_cents"],
            "returned_quantity": 0,
            "tender_splits": [
                {"tender_type": s["tender_type"],
                 "amount_cents": s["amount_cents"]}
                for s in raw["tender_splits"]
            ],
            "certificate_tendered_cents": cert_tendered,
        })
        db.receipt_lines[line["id"]] = line

    # Split-transaction screening never blocks the sale (PRD 3.4).
    core.split_scan(store, receipt)
    return object_response(receipt_out(receipt), 201)


def _ts(dt):
    from response import iso_timestamp
    return iso_timestamp(dt)


@bp.route("/stores/<store_id>/receipts", methods=["GET"])
def list_receipts(store_id):
    authenticate(READ_ROLES)
    lookup.store(store_id)
    account_id = query_param("account_id")
    records = [r for r in db.ordered(db.receipts) if r["store_id"] == store_id]
    if account_id is not None:
        records = [r for r in records if r["account_id"] == account_id]
    return paginated(records, receipt_out)


@bp.route("/stores/<store_id>/receipts/<receipt_id>", methods=["GET"])
def get_receipt(store_id, receipt_id):
    authenticate(READ_ROLES)
    lookup.store(store_id)
    return object_response(receipt_out(
        lookup.receipt_in_store(store_id, receipt_id)))


@bp.route("/stores/<store_id>/receipts/<receipt_id>/lines", methods=["GET"])
def list_receipt_lines(store_id, receipt_id):
    authenticate(READ_ROLES)
    lookup.store(store_id)
    receipt = lookup.receipt_in_store(store_id, receipt_id)
    return paginated(core.receipt_lines_of(receipt["id"]), receipt_line_out)


@bp.route("/stores/<store_id>/receipts/<receipt_id>/returns", methods=["POST"])
def create_return(store_id, receipt_id):
    authenticate([GUEST_SERVICE])
    store = lookup.store(store_id)
    receipt = lookup.receipt_in_store(store_id, receipt_id)
    body = get_body()

    lines_in = body.get("lines")
    if not isinstance(lines_in, list) or not lines_in:
        raise _bad_request("Field 'lines' must be a non-empty array")
    for raw in lines_in:
        if not isinstance(raw, dict):
            raise _bad_request("Each return line must be an object")
        line_number = raw.get("line_number")
        if isinstance(line_number, bool) or not isinstance(line_number, int) \
                or line_number < 1:
            raise _bad_request("Field 'line_number' must be an integer >= 1")
        quantity = raw.get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, int) \
                or quantity < 1:
            raise _bad_request("Field 'quantity' must be an integer >= 1")

    if receipt["status"] == "FULLY_RETURNED":
        raise ApiError("ERR_INVALID_STATE",
                       "The receipt has been fully returned")

    by_number = {l["line_number"]: l
                 for l in core.receipt_lines_of(receipt["id"])}

    # Fiscal preconditions checked for ALL lines before ANY mutation
    # (atomicity).
    for raw in lines_in:
        line = by_number.get(raw["line_number"])
        if line is None:
            raise ApiError("ERR_NOT_FOUND",
                           "Receipt line %s not found" % raw["line_number"])
        if line["returned_quantity"] + raw["quantity"] > line["quantity"]:
            raise ApiError("ERR_RETURN_QUANTITY_EXCEEDS_SOLD",
                           "Cumulative returned quantity on line %s would "
                           "exceed sold quantity" % raw["line_number"])

    ret = db.base_record()
    touched_line_ids = []
    for raw in lines_in:
        line = by_number[raw["line_number"]]
        line["returned_quantity"] += raw["quantity"]
        touched_line_ids.append(line["id"])

    # Receipt status re-derived from return activity.
    all_lines = core.receipt_lines_of(receipt["id"])
    if all(l["returned_quantity"] >= l["quantity"] for l in all_lines):
        receipt["status"] = "FULLY_RETURNED"
    else:
        receipt["status"] = "PARTIALLY_RETURNED"
    db.touch(receipt)

    ret.update({
        "store_id": store_id,
        "receipt_id": receipt["id"],
        "lines": [{"line_number": r["line_number"], "quantity": r["quantity"]}
                  for r in lines_in],
        "processed_at": db.logical_timestamp(),
        "reversal_entry_ids": [],
    })
    db.returns[ret["id"]] = ret

    ret["reversal_entry_ids"] = core.process_return_cascade(
        store, ret, receipt, touched_line_ids)
    db.touch(ret)
    return object_response(return_out(ret))


# ---------------------------------------------------------------------------
# Flat canonical reads + FK reverse reachability
# ---------------------------------------------------------------------------
@bp.route("/receipts", methods=["GET"])
def list_all_receipts():
    authenticate(READ_ROLES)
    store_id = query_param("store_id")
    account_id = query_param("account_id")
    job_purchase_id = query_param("job_purchase_id")
    records = db.ordered(db.receipts)
    if store_id is not None:
        records = [r for r in records if r["store_id"] == store_id]
    if account_id is not None:
        records = [r for r in records if r["account_id"] == account_id]
    if job_purchase_id is not None:
        records = [r for r in records
                   if r.get("job_purchase_id") == job_purchase_id]
    return paginated(records, receipt_out)


@bp.route("/receipts/<receipt_id>", methods=["GET"])
def get_receipt_flat(receipt_id):
    authenticate(READ_ROLES)
    return object_response(receipt_out(lookup.receipt(receipt_id)))


@bp.route("/receipts/<receipt_id>/returns", methods=["GET"])
def receipt_returns(receipt_id):
    authenticate(READ_ROLES)
    receipt = lookup.receipt(receipt_id)
    returns = [r for r in db.ordered(db.returns)
               if r["receipt_id"] == receipt["id"]]
    return paginated(returns, return_out)


@bp.route("/receipts/<receipt_id>/rebate-submissions", methods=["GET"])
def receipt_submissions(receipt_id):
    authenticate(READ_ROLES)
    receipt = lookup.receipt(receipt_id)
    subs = [s for s in db.ordered(db.submissions)
            if s["receipt_id"] == receipt["id"]]
    return paginated(subs, submission_out)


@bp.route("/receipt-lines", methods=["GET"])
def list_all_receipt_lines():
    authenticate(READ_ROLES)
    receipt_id = query_param("receipt_id")
    records = db.ordered(db.receipt_lines)
    if receipt_id is not None:
        records = [l for l in records if l["receipt_id"] == receipt_id]
    return paginated(records, receipt_line_out)


@bp.route("/receipt-lines/<line_id>", methods=["GET"])
def get_receipt_line_flat(line_id):
    authenticate(READ_ROLES)
    return object_response(receipt_line_out(lookup.receipt_line(line_id)))


@bp.route("/returns", methods=["GET"])
def list_all_returns():
    authenticate(READ_ROLES)
    receipt_id = query_param("receipt_id")
    records = db.ordered(db.returns)
    if receipt_id is not None:
        records = [r for r in records if r["receipt_id"] == receipt_id]
    return paginated(records, return_out)


@bp.route("/returns/<return_id>", methods=["GET"])
def get_return_flat(return_id):
    authenticate(READ_ROLES)
    return object_response(return_out(lookup.return_record(return_id)))
