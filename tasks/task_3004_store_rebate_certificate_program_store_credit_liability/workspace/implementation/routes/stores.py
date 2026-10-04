"""Store routes: provisioning and OCC-guarded policy configuration
(PRD 3.1, SCAFFOLD concurrency_rules)."""

from flask import Blueprint

import db
from errors import ApiError
from middleware import (FINANCE_ADMIN, FRAUD_ANALYST, GUEST_SERVICE,
                        STORE_ADMIN, authenticate, get_body, opt_int,
                        opt_number, req_int, req_number, req_string)
from response import object_response
from routes.common import paginated
from serialize import store_out
from services import core, lookup

bp = Blueprint("stores", __name__)

READ_ROLES = [STORE_ADMIN, GUEST_SERVICE, FRAUD_ANALYST, FINANCE_ADMIN]


@bp.route("/stores", methods=["POST"])
def create_store():
    authenticate([STORE_ADMIN])
    body = get_body()

    store_code = req_string(body, "store_code")
    submission_window_days = req_int(body, "submission_window_days")
    certificate_validity_months = req_int(body, "certificate_validity_months")
    expected_breakage_rate = req_number(body, "expected_breakage_rate",
                                        minimum=0, maximum=1)
    split_txn_window_hours = req_int(body, "split_txn_window_hours")
    split_txn_min_receipts = req_int(body, "split_txn_min_receipts")

    store = db.base_record()
    store.update({
        "store_code": store_code,
        "submission_window_days": submission_window_days,
        "certificate_validity_months": certificate_validity_months,
        "expected_breakage_rate": expected_breakage_rate,
        "split_txn_window_hours": split_txn_window_hours,
        "split_txn_min_receipts": split_txn_min_receipts,
        "outstanding_liability_cents": 0,
        "net_liability_cents": 0,
        "accrued_breakage_income_cents": 0,
        "liability_epoch": 0,
    })
    db.stores[store["id"]] = store
    return object_response(store_out(store), 201)


@bp.route("/stores", methods=["GET"])
def list_stores():
    authenticate(READ_ROLES)
    return paginated(db.ordered(db.stores), store_out)


@bp.route("/stores/<store_id>", methods=["GET"])
def get_store(store_id):
    authenticate(READ_ROLES)
    store = lookup.store(store_id)
    return object_response(store_out(store))


@bp.route("/stores/<store_id>", methods=["PATCH"])
def update_store(store_id):
    authenticate([STORE_ADMIN])
    store = lookup.store(store_id)
    body = get_body()

    # Structural shape (ladder 4) is validated before the OCC check
    # (ladder 17): expected_store_version must be a present integer.
    expected = req_int(body, "expected_store_version")

    fields = {}
    if "submission_window_days" in body and body["submission_window_days"] is not None:
        fields["submission_window_days"] = req_int(body, "submission_window_days")
    if "certificate_validity_months" in body and body["certificate_validity_months"] is not None:
        fields["certificate_validity_months"] = req_int(
            body, "certificate_validity_months")
    if "expected_breakage_rate" in body and body["expected_breakage_rate"] is not None:
        fields["expected_breakage_rate"] = req_number(
            body, "expected_breakage_rate", minimum=0, maximum=1)
    if "split_txn_window_hours" in body and body["split_txn_window_hours"] is not None:
        fields["split_txn_window_hours"] = req_int(body, "split_txn_window_hours")
    if "split_txn_min_receipts" in body and body["split_txn_min_receipts"] is not None:
        fields["split_txn_min_receipts"] = req_int(body, "split_txn_min_receipts")

    if expected != store["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_store_version %s does not match current "
                       "version %s" % (expected, store["version"]))

    rate_changed = ("expected_breakage_rate" in fields
                    and fields["expected_breakage_rate"]
                    != store["expected_breakage_rate"])

    store.update(fields)
    if rate_changed:
        # Net liability recomputed immediately from the unchanged gross
        # liability (PRD 3.1).
        core.recompute_store(store)
    else:
        db.touch(store)
    return object_response(store_out(store))
