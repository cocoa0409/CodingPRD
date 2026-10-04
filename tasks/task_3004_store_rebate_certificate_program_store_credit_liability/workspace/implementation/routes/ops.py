"""Ledger, breakage-run and fraud-flag routes (PRD 2.7, 3.7, 3.9)."""

from flask import Blueprint

import db
from errors import ApiError
from middleware import (FINANCE_ADMIN, FRAUD_ANALYST, GUEST_SERVICE,
                        STORE_ADMIN, authenticate, get_body, query_param,
                        req_enum, req_int)
from response import iso_timestamp, object_response
from routes.common import paginated
from serialize import breakage_run_out, flag_out, ledger_entry_out
from services import core, lookup, temporal

bp = Blueprint("ops", __name__)

STAFF_READ = [STORE_ADMIN, GUEST_SERVICE, FRAUD_ANALYST, FINANCE_ADMIN]
FLAG_READ = [STORE_ADMIN, FRAUD_ANALYST]
RUN_READ = [STORE_ADMIN, FINANCE_ADMIN]
RESOLUTIONS = {"CONFIRM", "CLEAR"}


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------
@bp.route("/stores/<store_id>/credit-accounts/<account_id>/ledger",
          methods=["GET"])
def account_ledger(store_id, account_id):
    authenticate(STAFF_READ)
    lookup.store(store_id)
    account = lookup.account_in_store(store_id, account_id)
    certificate_id = query_param("certificate_id")
    entries = [e for e in db.ordered(db.ledger_entries)
               if e["account_id"] == account["id"]]
    if certificate_id is not None:
        entries = [e for e in entries if e["certificate_id"] == certificate_id]
    return paginated(entries, ledger_entry_out)


@bp.route("/ledger-entries", methods=["GET"])
def list_all_ledger_entries():
    authenticate(STAFF_READ)
    account_id = query_param("account_id")
    certificate_id = query_param("certificate_id")
    entry_type = query_param("entry_type")
    records = db.ordered(db.ledger_entries)
    if account_id is not None:
        records = [e for e in records if e["account_id"] == account_id]
    if certificate_id is not None:
        records = [e for e in records if e["certificate_id"] == certificate_id]
    if entry_type is not None:
        records = [e for e in records if e["entry_type"] == entry_type]
    return paginated(records, ledger_entry_out)


@bp.route("/ledger-entries/<entry_id>", methods=["GET"])
def get_ledger_entry(entry_id):
    authenticate(STAFF_READ)
    return object_response(ledger_entry_out(lookup.ledger_entry(entry_id)))


# ---------------------------------------------------------------------------
# Breakage runs (calculation breakage_recognition; PRD 3.7)
# ---------------------------------------------------------------------------
@bp.route("/stores/<store_id>/breakage-runs", methods=["POST"])
def create_breakage_run(store_id):
    authenticate([FINANCE_ADMIN])
    store = lookup.store(store_id)
    body = get_body()
    expected = req_int(body, "expected_store_version")

    if expected != store["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_store_version %s does not match current "
                       "version %s" % (expected, store["version"]))

    run_at = db.clock_now()

    # Atomic run: RUNNING internally, only COMPLETED ever observable.
    new_epoch = store["liability_epoch"] + 1

    sweep = [c for c in core.store_certificates(store["id"])
             if c["status"] in ("ACTIVE", "PARTIALLY_REDEEMED")
             and temporal.parse_timestamp_iso(c["expires_at"]) <= run_at]
    sweep.sort(key=lambda c: (temporal.parse_timestamp_iso(c["expires_at"]),
                              db.sort_key(c)))

    run = db.base_record()
    run.update({
        "store_id": store["id"],
        "status": "RUNNING",
        "run_at": iso_timestamp(run_at),
        "expired_count": 0,
        "breakage_recognized_cents": 0,
        "epoch": new_epoch,
    })
    db.breakage_runs[run["id"]] = run

    store["liability_epoch"] = new_epoch

    swept_total = 0
    touched_accounts = set()
    for cert in sweep:
        amount = cert["remaining_balance_cents"]
        cert["status"] = "EXPIRED"
        db.touch(cert)
        core.post_ledger(store, cert["account_id"], cert["id"],
                         "BREAKAGE_EXPIRY", -amount,
                         "breakage run %s" % run["id"])
        swept_total += amount
        touched_accounts.add(cert["account_id"])

    store["accrued_breakage_income_cents"] = (
        store["accrued_breakage_income_cents"] + swept_total)
    run["expired_count"] = len(sweep)
    run["breakage_recognized_cents"] = swept_total
    run["status"] = "COMPLETED"

    for account_id in touched_accounts:
        account = db.accounts.get(account_id)
        if account is not None:
            core.recompute_account(account)
    core.recompute_store(store)  # also advances Store.version by 1
    db.touch(run)
    return object_response(breakage_run_out(run), 201)


@bp.route("/stores/<store_id>/breakage-runs", methods=["GET"])
def list_store_breakage_runs(store_id):
    authenticate(RUN_READ)
    lookup.store(store_id)
    runs = [r for r in db.ordered(db.breakage_runs)
            if r["store_id"] == store_id]
    return paginated(runs, breakage_run_out)


@bp.route("/stores/<store_id>/breakage-runs/<run_id>", methods=["GET"])
def get_store_breakage_run(store_id, run_id):
    authenticate(RUN_READ)
    lookup.store(store_id)
    return object_response(breakage_run_out(
        lookup.breakage_run_in_store(store_id, run_id)))


@bp.route("/breakage-runs", methods=["GET"])
def list_all_breakage_runs():
    authenticate(RUN_READ)
    store_id = query_param("store_id")
    records = db.ordered(db.breakage_runs)
    if store_id is not None:
        records = [r for r in records if r["store_id"] == store_id]
    return paginated(records, breakage_run_out)


@bp.route("/breakage-runs/<run_id>", methods=["GET"])
def get_breakage_run_flat(run_id):
    authenticate(RUN_READ)
    return object_response(breakage_run_out(lookup.breakage_run(run_id)))


# ---------------------------------------------------------------------------
# Fraud flags (PRD 3.9)
# ---------------------------------------------------------------------------
@bp.route("/stores/<store_id>/fraud-flags", methods=["GET"])
def list_store_flags(store_id):
    authenticate(FLAG_READ)
    lookup.store(store_id)
    account_id = query_param("account_id")
    flag_type = query_param("flag_type")
    status = query_param("status")
    records = [f for f in db.ordered(db.flags) if f["store_id"] == store_id]
    if account_id is not None:
        records = [f for f in records if f["account_id"] == account_id]
    if flag_type is not None:
        records = [f for f in records if f["flag_type"] == flag_type]
    if status is not None:
        records = [f for f in records if f["status"] == status]
    return paginated(records, flag_out)


@bp.route("/stores/<store_id>/fraud-flags/<flag_id>/resolve", methods=["POST"])
def resolve_flag(store_id, flag_id):
    authenticate([FRAUD_ANALYST])
    lookup.store(store_id)
    flag = lookup.flag_in_store(store_id, flag_id)
    body = get_body()
    resolution = req_enum(body, "resolution", RESOLUTIONS)

    if flag["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE",
                       "Only an OPEN fraud flag may be resolved")

    if resolution == "CONFIRM":
        flag["status"] = "CONFIRMED"
        db.touch(flag)
        # Every certificate of the account with fraud_hold NONE -> HELD.
        for cert in core.account_certificates(flag["account_id"]):
            if cert["fraud_hold"] == "NONE":
                cert["fraud_hold"] = "HELD"
                db.touch(cert)
    else:
        # CLEAR releases no holds automatically.
        flag["status"] = "CLEARED"
        db.touch(flag)
    return object_response(flag_out(flag))


@bp.route("/stores/<store_id>/fraud-flags/<flag_id>/reopen", methods=["POST"])
def reopen_flag(store_id, flag_id):
    authenticate([FRAUD_ANALYST])
    lookup.store(store_id)
    flag = lookup.flag_in_store(store_id, flag_id)
    get_body()
    if flag["status"] != "CLEARED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a CLEARED fraud flag may be reopened")
    flag["status"] = "OPEN"
    db.touch(flag)
    return object_response(flag_out(flag))


@bp.route("/fraud-flags", methods=["GET"])
def list_all_flags():
    authenticate(FLAG_READ)
    account_id = query_param("account_id")
    flag_type = query_param("flag_type")
    status = query_param("status")
    records = db.ordered(db.flags)
    if account_id is not None:
        records = [f for f in records if f["account_id"] == account_id]
    if flag_type is not None:
        records = [f for f in records if f["flag_type"] == flag_type]
    if status is not None:
        records = [f for f in records if f["status"] == status]
    return paginated(records, flag_out)


@bp.route("/fraud-flags/<flag_id>", methods=["GET"])
def get_flag_flat(flag_id):
    authenticate(FLAG_READ)
    return object_response(flag_out(lookup.flag(flag_id)))
