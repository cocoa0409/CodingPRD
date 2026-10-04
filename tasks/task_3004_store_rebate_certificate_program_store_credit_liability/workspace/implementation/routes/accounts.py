"""CreditAccount / JobPurchase routes (PRD 3.3)."""

from flask import Blueprint

import db
from errors import ApiError
from middleware import (CONTRACTOR, CUSTOMER, FINANCE_ADMIN, FRAUD_ANALYST,
                        GUEST_SERVICE, STORE_ADMIN, authenticate, get_body,
                        query_param, req_enum, req_string,
                        require_account_ownership)
from response import object_response
from routes.common import paginated
from serialize import account_out, job_out
from services import core, lookup

bp = Blueprint("accounts", __name__)

STAFF_READ = [STORE_ADMIN, GUEST_SERVICE, FRAUD_ANALYST, FINANCE_ADMIN]
ACCOUNT_READ = STAFF_READ + [CUSTOMER, CONTRACTOR]
ACCOUNT_TYPES = {"RETAIL", "CONTRACTOR"}


# ---------------------------------------------------------------------------
# Store-scoped account surface
# ---------------------------------------------------------------------------
@bp.route("/stores/<store_id>/credit-accounts", methods=["POST"])
def create_account(store_id):
    authenticate([GUEST_SERVICE])
    store = lookup.store(store_id)
    body = get_body()

    owner_name = req_string(body, "owner_name")
    account_type = req_enum(body, "account_type", ACCOUNT_TYPES)

    account = db.base_record()
    account.update({
        "store_id": store["id"],
        "owner_name": owner_name,
        "account_type": account_type,
        "status": "ACTIVE",
        "credit_balance_cents": 0,
        "pending_award_cents": 0,
        "lifetime_rebate_cents": 0,
    })
    db.accounts[account["id"]] = account
    return object_response(account_out(account), 201)


@bp.route("/stores/<store_id>/credit-accounts/<account_id>", methods=["GET"])
def get_account(store_id, account_id):
    caller = authenticate(ACCOUNT_READ)
    lookup.store(store_id)
    account = lookup.account_in_store(store_id, account_id)
    require_account_ownership(caller, account["id"])
    return object_response(account_out(account))


@bp.route("/stores/<store_id>/credit-accounts/<account_id>/freeze",
          methods=["POST"])
def freeze_account(store_id, account_id):
    authenticate([FRAUD_ANALYST])
    lookup.store(store_id)
    account = lookup.account_in_store(store_id, account_id)
    get_body()
    if account["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE",
                       "Only an ACTIVE account may be frozen")
    account["status"] = "FROZEN"
    db.touch(account)
    return object_response(account_out(account))


@bp.route("/stores/<store_id>/credit-accounts/<account_id>/unfreeze",
          methods=["POST"])
def unfreeze_account(store_id, account_id):
    authenticate([FRAUD_ANALYST])
    lookup.store(store_id)
    account = lookup.account_in_store(store_id, account_id)
    get_body()
    if account["status"] != "FROZEN":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a FROZEN account may be unfrozen")
    for flag in core.account_flags(account["id"]):
        if flag["flag_type"] == "DUPLICATE_RECEIPT" and flag["status"] == "OPEN":
            raise ApiError("ERR_FRAUD_FLAG_OPEN",
                           "A DUPLICATE_RECEIPT fraud flag is OPEN on this "
                           "account")
    account["status"] = "ACTIVE"
    db.touch(account)
    return object_response(account_out(account))


@bp.route("/stores/<store_id>/credit-accounts/<account_id>/close",
          methods=["POST"])
def close_account(store_id, account_id):
    authenticate([STORE_ADMIN])
    lookup.store(store_id)
    account = lookup.account_in_store(store_id, account_id)
    get_body()
    if account["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE",
                       "Only an ACTIVE account may be closed")
    if account["credit_balance_cents"] != 0 or account["pending_award_cents"] != 0:
        raise ApiError("ERR_ACCOUNT_BALANCE_NONZERO",
                       "Account close requires zero credit and pending award "
                       "balances")
    account["status"] = "CLOSED"
    db.touch(account)
    return object_response(account_out(account))


# ---------------------------------------------------------------------------
# Job purchases
# ---------------------------------------------------------------------------
@bp.route("/stores/<store_id>/credit-accounts/<account_id>/job-purchases",
          methods=["POST"])
def create_job(store_id, account_id):
    caller = authenticate([CONTRACTOR])
    lookup.store(store_id)
    account = lookup.account_in_store(store_id, account_id)
    require_account_ownership(caller, account["id"])
    body = get_body()
    job_reference = req_string(body, "job_reference")

    if account["account_type"] != "CONTRACTOR" or account["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE",
                       "Job purchases require a CONTRACTOR account in ACTIVE "
                       "status")

    job = db.base_record()
    job.update({
        "store_id": store_id,
        "contractor_account_id": account["id"],
        "job_reference": job_reference,
        "status": "OPEN",
    })
    db.jobs[job["id"]] = job
    return object_response(job_out(job), 201)


@bp.route("/stores/<store_id>/credit-accounts/<account_id>/jobs",
          methods=["GET"])
def list_account_jobs(store_id, account_id):
    caller = authenticate([STORE_ADMIN, GUEST_SERVICE, CONTRACTOR,
                           FINANCE_ADMIN])
    lookup.store(store_id)
    account = lookup.account_in_store(store_id, account_id)
    require_account_ownership(caller, account["id"])
    jobs = [j for j in db.ordered(db.jobs)
            if j["contractor_account_id"] == account["id"]]
    return paginated(jobs, job_out)


@bp.route("/stores/<store_id>/job-purchases/<job_id>/settle", methods=["POST"])
def settle_job(store_id, job_id):
    caller = authenticate([CONTRACTOR])
    lookup.store(store_id)
    job = lookup.job_in_store(store_id, job_id)
    get_body()
    require_account_ownership(caller, job["contractor_account_id"])
    if job["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE",
                       "Only an OPEN job purchase may be settled")
    job["status"] = "SETTLED"
    db.touch(job)
    return object_response(job_out(job))


@bp.route("/stores/<store_id>/credit-accounts/<account_id>/contractor-summary",
          methods=["GET"])
def contractor_summary(store_id, account_id):
    caller = authenticate([STORE_ADMIN, FINANCE_ADMIN, CONTRACTOR])
    lookup.store(store_id)
    account = lookup.account_in_store(store_id, account_id)
    require_account_ownership(caller, account["id"])
    if account["account_type"] != "CONTRACTOR":
        raise ApiError("ERR_INVALID_REQUEST",
                       "Contractor summary requires a CONTRACTOR account")
    return object_response(core.contractor_summary(account))


# ---------------------------------------------------------------------------
# Flat canonical reads + FK reverse reachability
# ---------------------------------------------------------------------------
@bp.route("/credit-accounts/<account_id>", methods=["GET"])
def get_account_flat(account_id):
    caller = authenticate(ACCOUNT_READ)
    account = lookup.account(account_id)
    require_account_ownership(caller, account["id"])
    return object_response(account_out(account))


@bp.route("/credit-accounts/<account_id>/receipts", methods=["GET"])
def account_receipts(account_id):
    authenticate(STAFF_READ)
    account = lookup.account(account_id)
    receipts = [r for r in db.ordered(db.receipts)
                if r["account_id"] == account["id"]]
    from serialize import receipt_out
    return paginated(receipts, receipt_out)


@bp.route("/credit-accounts/<account_id>/rebate-submissions", methods=["GET"])
def account_submissions(account_id):
    caller = authenticate(ACCOUNT_READ)
    account = lookup.account(account_id)
    require_account_ownership(caller, account["id"])
    subs = [s for s in db.ordered(db.submissions)
            if s["account_id"] == account["id"]]
    from serialize import submission_out
    return paginated(subs, submission_out)


@bp.route("/credit-accounts/<account_id>/certificates", methods=["GET"])
def account_certificates(account_id):
    caller = authenticate(ACCOUNT_READ)
    account = lookup.account(account_id)
    require_account_ownership(caller, account["id"])
    certs = [c for c in db.ordered(db.certificates)
             if c["account_id"] == account["id"]]
    from serialize import certificate_out
    return paginated(certs, certificate_out)


@bp.route("/credit-accounts/<account_id>/fraud-flags", methods=["GET"])
def account_flags(account_id):
    authenticate([STORE_ADMIN, FRAUD_ANALYST])
    account = lookup.account(account_id)
    flags = [f for f in db.ordered(db.flags)
             if f["account_id"] == account["id"]]
    from serialize import flag_out
    return paginated(flags, flag_out)


@bp.route("/credit-accounts/<account_id>/ledger-entries", methods=["GET"])
def account_ledger_entries(account_id):
    authenticate(STAFF_READ)
    account = lookup.account(account_id)
    entries = [e for e in db.ordered(db.ledger_entries)
               if e["account_id"] == account["id"]]
    from serialize import ledger_entry_out
    return paginated(entries, ledger_entry_out)


@bp.route("/credit-accounts/<account_id>/jobs", methods=["GET"])
def account_jobs_flat(account_id):
    caller = authenticate([STORE_ADMIN, GUEST_SERVICE, CONTRACTOR,
                           FINANCE_ADMIN])
    account = lookup.account(account_id)
    require_account_ownership(caller, account["id"])
    jobs = [j for j in db.ordered(db.jobs)
            if j["contractor_account_id"] == account["id"]]
    return paginated(jobs, job_out)


@bp.route("/job-purchases", methods=["GET"])
def list_jobs():
    caller = authenticate([STORE_ADMIN, GUEST_SERVICE, CONTRACTOR,
                           FINANCE_ADMIN])
    contractor_account_id = query_param("contractor_account_id")
    status = query_param("status")
    jobs = db.ordered(db.jobs)
    if contractor_account_id is not None:
        require_account_ownership(caller, contractor_account_id)
        jobs = [j for j in jobs
                if j["contractor_account_id"] == contractor_account_id]
    elif caller.role == CONTRACTOR:
        require_account_ownership(caller, "")
    if status is not None:
        jobs = [j for j in jobs if j["status"] == status]
    return paginated(jobs, job_out)


@bp.route("/job-purchases/<job_id>", methods=["GET"])
def get_job_flat(job_id):
    caller = authenticate([STORE_ADMIN, GUEST_SERVICE, CONTRACTOR,
                           FINANCE_ADMIN])
    job = lookup.job(job_id)
    require_account_ownership(caller, job["contractor_account_id"])
    return object_response(job_out(job))


@bp.route("/job-purchases/<job_id>/receipts", methods=["GET"])
def job_receipts(job_id):
    caller = authenticate([STORE_ADMIN, GUEST_SERVICE, CONTRACTOR,
                           FINANCE_ADMIN])
    job = lookup.job(job_id)
    require_account_ownership(caller, job["contractor_account_id"])
    receipts = [r for r in db.ordered(db.receipts)
                if r.get("job_purchase_id") == job["id"]]
    from serialize import receipt_out
    return paginated(receipts, receipt_out)
