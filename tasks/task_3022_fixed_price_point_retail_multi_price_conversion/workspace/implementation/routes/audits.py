"""Price integrity audits (PRD §3.11)."""

from db import db
from errors import (
    ApiError,
    ERR_AUDIT_ALREADY_RESOLVED,
    ERR_INVALID_REQUEST,
    ERR_MIXED_PRICE_POINT_OPEN_VIOLATION,
)
from common import (
    apply_eq,
    as_int_opt,
    body,
    get_ok,
    get_row,
    insert,
    new_row,
    paginate,
    query,
    require,
    route,
)
from response import ok_object
from derivations import (
    MISMATCH_TOLERANCE_PCT,
    dec,
    refresh_store,
    round_half_up,
    serialize_audit,
)


def compute_result(observed_item_count, mismatched_item_count):
    """price_integrity_result — the branch runs on the ROUNDED ratio."""
    if observed_item_count == 0:
        return 0.0, "WITHIN_TOLERANCE"
    ratio = round_half_up(dec(mismatched_item_count) / dec(observed_item_count), 3)
    result = "VIOLATION" if dec(ratio) > MISMATCH_TOLERANCE_PCT else "WITHIN_TOLERANCE"
    return float(ratio), result


@route("/merchandise/price-integrity-audits", ["POST"], ["StoreOperationsManager"])
def create_audit():
    data = body()
    require(data, ["store_id", "price_point_id", "audited_at", "observed_item_count",
                   "mismatched_item_count"])
    store = get_row("store", data["store_id"])
    price_point = get_row("price_point", data["price_point_id"])

    observed_item_count = as_int_opt(data, "observed_item_count")
    mismatched_item_count = as_int_opt(data, "mismatched_item_count")
    if observed_item_count is None or observed_item_count < 0:
        invalid("observed_item_count must not be negative.")
    if mismatched_item_count is None or mismatched_item_count < 0:
        invalid("mismatched_item_count must not be negative.")
    if mismatched_item_count > observed_item_count:
        invalid("mismatched_item_count must not exceed observed_item_count.")

    # A second price point may not be opened against a store that already
    # carries an unresolved violation under a different price point.
    for audit in db.audits.values():
        if (
            audit["store_id"] == store["id"]
            and audit["status"] == "OPEN"
            and audit["result"] == "VIOLATION"
            and audit["price_point_id"] != price_point["id"]
        ):
            raise ApiError(ERR_MIXED_PRICE_POINT_OPEN_VIOLATION)

    ratio, result = compute_result(observed_item_count, mismatched_item_count)
    row = new_row("audit", {
        "store_id": store["id"],
        "price_point_id": price_point["id"],
        "audited_at": data["audited_at"],
        "observed_item_count": observed_item_count,
        "mismatched_item_count": mismatched_item_count,
        "result": result,
        "mismatch_ratio": ratio,
        "status": "OPEN",
    }, has_common=False)  # §2.5 — event log: id and created_at only.
    insert("audit", row)
    refresh_store(store)
    return ok_object(serialize_audit(row), 201)


@route("/merchandise/price-integrity-audits", ["GET"],
       ["StoreOperationsManager", "MerchandiseAnalyst", "LegalCostEngineer"])
def list_audits():
    rows = db.creation_order(db.audits)
    rows = apply_eq(rows, "store_id", query("store_id"))
    rows = apply_eq(rows, "price_point_id", query("price_point_id"))
    rows = apply_eq(rows, "result", query("result"))
    rows = apply_eq(rows, "status", query("status"))
    return paginate([serialize_audit(r) for r in rows])


@route("/merchandise/price-integrity-audits/<audit_id>", ["GET"],
       ["StoreOperationsManager", "MerchandiseAnalyst", "LegalCostEngineer"])
def read_audit(audit_id):
    return get_ok("audit", audit_id)


@route("/merchandise/price-integrity-audits/<audit_id>/resolve", ["POST"],
       ["StoreOperationsManager"])
def resolve_audit(audit_id):
    row = get_row("audit", audit_id)
    if row["status"] != "OPEN":
        raise ApiError(ERR_AUDIT_ALREADY_RESOLVED)
    row["status"] = "RESOLVED"
    store = get_row("store", row["store_id"])
    refresh_store(store)
    return ok_object(serialize_audit(row))


def invalid(message):
    raise ApiError(ERR_INVALID_REQUEST, message)