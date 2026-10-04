"""RebateSubmission routes: submission, adjudication, resubmission and
certificate issuance (PRD 3.5)."""

from flask import Blueprint

import db
from errors import ApiError
from middleware import (CONTRACTOR, CUSTOMER, FINANCE_ADMIN, FRAUD_ANALYST,
                        GUEST_SERVICE, STORE_ADMIN, authenticate, get_body,
                        opt_string, query_param, req_enum, req_id,
                        require_account_ownership)
from response import object_response
from routes.common import paginated
from serialize import (certificate_out, submission_line_out, submission_out)
from services import core, lookup, temporal

bp = Blueprint("submissions", __name__)

READ_ROLES = [STORE_ADMIN, GUEST_SERVICE, FRAUD_ANALYST, FINANCE_ADMIN]
SUBMISSION_READ = READ_ROLES + [CUSTOMER, CONTRACTOR]
SUBMITTER_ROLES = [CUSTOMER, CONTRACTOR]
DECISIONS = {"APPROVE", "REJECT"}


@bp.route("/stores/<store_id>/rebate-submissions", methods=["POST"])
def create_submission(store_id):
    caller = authenticate(SUBMITTER_ROLES)
    store = lookup.store(store_id)
    body = get_body()
    receipt_id = req_id(body, "receipt_id")

    # Receipt referenced by body: a missing reference is 404.
    receipt = lookup.receipt(receipt_id)

    # Ownership: entity-backed roles act only on their own account's
    # receipts (PRD 2.1).
    require_account_ownership(caller, receipt["account_id"])

    # Ladder 8: submission window (deadline instant included).
    if not temporal.submission_window_open(receipt, store):
        raise ApiError("ERR_SUBMISSION_WINDOW_CLOSED",
                       "The submission window for this receipt has closed")

    # Ladder 10: duplicate-receipt screening (raises and records a flag).
    core.duplicate_scan(store, receipt)

    # Ladder 11: frozen account.
    account = db.accounts.get(receipt["account_id"])
    if account is not None and account["status"] == "FROZEN":
        raise ApiError("ERR_ACCOUNT_FROZEN",
                       "A FROZEN account may not submit rebates")

    provisional, line_results = core.compute_award(store, receipt,
                                                   "provisional")

    submission = db.base_record()
    submission.update({
        "store_id": store_id,
        "account_id": receipt["account_id"],
        "receipt_id": receipt["id"],
        # SUBMITTED -> UNDER_REVIEW inside the same request (PRD 3.5); only
        # UNDER_REVIEW is observable after creation.
        "status": "UNDER_REVIEW",
        "provisional_award_cents": provisional,
        "award_cents": None,
        "rejection_reason": None,
        "submitted_at": db.logical_timestamp(),
        "resubmit_count": 0,
    })
    db.submissions[submission["id"]] = submission
    core.write_submission_lines(submission, line_results)
    return object_response(submission_out(submission), 201)


@bp.route("/stores/<store_id>/rebate-submissions", methods=["GET"])
def list_submissions(store_id):
    authenticate(READ_ROLES)
    lookup.store(store_id)
    account_id = query_param("account_id")
    status = query_param("status")
    records = [s for s in db.ordered(db.submissions)
               if s["store_id"] == store_id]
    if account_id is not None:
        records = [s for s in records if s["account_id"] == account_id]
    if status is not None:
        records = [s for s in records if s["status"] == status]
    return paginated(records, submission_out)


@bp.route("/stores/<store_id>/rebate-submissions/<submission_id>",
          methods=["GET"])
def get_submission(store_id, submission_id):
    caller = authenticate(SUBMISSION_READ)
    lookup.store(store_id)
    submission = lookup.submission_in_store(store_id, submission_id)
    require_account_ownership(caller, submission["account_id"])
    return object_response(submission_out(submission))


@bp.route("/stores/<store_id>/rebate-submissions/<submission_id>/lines",
          methods=["GET"])
def list_submission_lines(store_id, submission_id):
    caller = authenticate(SUBMISSION_READ)
    lookup.store(store_id)
    submission = lookup.submission_in_store(store_id, submission_id)
    require_account_ownership(caller, submission["account_id"])
    return paginated(core.submission_lines_of(submission["id"]),
                     submission_line_out)


@bp.route("/stores/<store_id>/rebate-submissions/<submission_id>/adjudicate",
          methods=["POST"])
def adjudicate_submission(store_id, submission_id):
    authenticate([GUEST_SERVICE])
    store = lookup.store(store_id)
    submission = lookup.submission_in_store(store_id, submission_id)
    body = get_body()
    decision = req_enum(body, "decision", DECISIONS)
    rejection_reason = opt_string(body, "rejection_reason")

    if submission["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE",
                       "Adjudication requires an UNDER_REVIEW submission")

    receipt = lookup.receipt(submission["receipt_id"])

    if decision == "APPROVE":
        # Window first (422), then frozen account (409) per PRD 3.5.
        if not temporal.submission_window_open(receipt, store):
            raise ApiError("ERR_SUBMISSION_WINDOW_CLOSED",
                           "The submission window for this receipt has "
                           "closed")
        account = lookup.account(submission["account_id"])
        if account["status"] == "FROZEN":
            raise ApiError("ERR_ACCOUNT_FROZEN",
                           "A FROZEN account may not be adjudicated")

        award, line_results = core.compute_award(store, receipt,
                                                 "adjudicated")
        core.write_submission_lines(submission, line_results)
        submission["award_cents"] = award
        submission["status"] = "APPROVED"
        submission["rejection_reason"] = None
        db.touch(submission)

        # Recompute account balances: pending_award_cents += award_cents;
        # lifetime_rebate_cents += award_cents (never decremented later).
        account["lifetime_rebate_cents"] = (
            account["lifetime_rebate_cents"] + award)
        core.recompute_account(account)
        core.recompute_store(store)
    else:
        submission["status"] = "REJECTED"
        submission["rejection_reason"] = rejection_reason
        db.touch(submission)

    return object_response(submission_out(submission))


@bp.route("/stores/<store_id>/rebate-submissions/<submission_id>/resubmit",
          methods=["POST"])
def resubmit_submission(store_id, submission_id):
    caller = authenticate(SUBMITTER_ROLES)
    store = lookup.store(store_id)
    submission = lookup.submission_in_store(store_id, submission_id)
    get_body()
    require_account_ownership(caller, submission["account_id"])

    if submission["status"] != "REJECTED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a REJECTED submission may be resubmitted")

    if submission["resubmit_count"] >= temporal.MAX_RESUBMITS:
        raise ApiError("ERR_RESUBMIT_LIMIT_REACHED",
                       "The resubmission cap of %d has been reached"
                       % temporal.MAX_RESUBMITS)

    receipt = lookup.receipt(submission["receipt_id"])
    if not temporal.submission_window_open(receipt, store):
        raise ApiError("ERR_SUBMISSION_WINDOW_CLOSED",
                       "The submission window for this receipt has closed")

    account = lookup.account(submission["account_id"])
    if account["status"] == "FROZEN":
        raise ApiError("ERR_ACCOUNT_FROZEN",
                       "A FROZEN account may not submit rebates")

    provisional, line_results = core.compute_award(store, receipt,
                                                   "provisional")
    core.write_submission_lines(submission, line_results)
    submission["resubmit_count"] += 1
    submission["submitted_at"] = db.logical_timestamp()
    submission["rejection_reason"] = None
    submission["provisional_award_cents"] = provisional
    # REJECTED -> SUBMITTED -> UNDER_REVIEW within the same request.
    submission["status"] = "UNDER_REVIEW"
    db.touch(submission)
    return object_response(submission_out(submission))


@bp.route("/stores/<store_id>/rebate-submissions/<submission_id>/issue-certificate",
          methods=["POST"])
def issue_certificate(store_id, submission_id):
    authenticate([GUEST_SERVICE])
    store = lookup.store(store_id)
    submission = lookup.submission_in_store(store_id, submission_id)
    get_body()

    if submission["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE",
                       "Certificate issuance requires an APPROVED submission")

    account = lookup.account(submission["account_id"])
    if account["status"] == "FROZEN":
        raise ApiError("ERR_ACCOUNT_FROZEN",
                       "A FROZEN account blocks certificate issuance")

    issued_at = db.clock_now()
    expires_at = temporal.expiry_instant(store, issued_at)

    cert = db.base_record()
    cert.update({
        "store_id": store_id,
        "account_id": account["id"],
        "submission_id": submission["id"],
        "issued_amount_cents": submission["award_cents"],
        "remaining_balance_cents": submission["award_cents"],
        "status": "ACTIVE",
        "fraud_hold": "NONE",
        "issued_at": db.logical_timestamp(),
        "expires_at": _iso(expires_at),
        "reissued_from_id": None,
    })
    db.certificates[cert["id"]] = cert

    core.post_ledger(store, account["id"], cert["id"], "ISSUANCE_ACCRUAL",
                     cert["issued_amount_cents"],
                     "issuance for submission %s" % submission["id"])

    # Pinned order (PRD 3.5): pending_award_cents is decremented BEFORE
    # credit_balance_cents is incremented so a certificate never
    # double-counts in the same request.  The submission stays APPROVED
    # (still reversible by a later return); the derived figures treat an
    # APPROVED submission with an issued certificate as settled and count
    # it only through the certificate leg.
    core.recompute_account(account)
    core.recompute_store(store)
    return object_response(certificate_out(cert))


def _iso(dt):
    from response import iso_timestamp
    return iso_timestamp(dt)


# ---------------------------------------------------------------------------
# Flat canonical reads + FK reverse reachability
# ---------------------------------------------------------------------------
@bp.route("/rebate-submissions", methods=["GET"])
def list_all_submissions():
    authenticate(READ_ROLES)
    account_id = query_param("account_id")
    receipt_id = query_param("receipt_id")
    status = query_param("status")
    records = db.ordered(db.submissions)
    if account_id is not None:
        records = [s for s in records if s["account_id"] == account_id]
    if receipt_id is not None:
        records = [s for s in records if s["receipt_id"] == receipt_id]
    if status is not None:
        records = [s for s in records if s["status"] == status]
    return paginated(records, submission_out)


@bp.route("/rebate-submissions/<submission_id>", methods=["GET"])
def get_submission_flat(submission_id):
    caller = authenticate(SUBMISSION_READ)
    submission = lookup.submission(submission_id)
    require_account_ownership(caller, submission["account_id"])
    return object_response(submission_out(submission))


@bp.route("/rebate-submissions/<submission_id>/certificates", methods=["GET"])
def submission_certificates(submission_id):
    authenticate(READ_ROLES)
    submission = lookup.submission(submission_id)
    certs = [c for c in db.ordered(db.certificates)
             if c["submission_id"] == submission["id"]]
    return paginated(certs, certificate_out)


@bp.route("/submission-lines", methods=["GET"])
def list_all_submission_lines():
    authenticate(READ_ROLES)
    submission_id = query_param("submission_id")
    receipt_line_id = query_param("receipt_line_id")
    program_item_id = query_param("program_item_id")
    records = db.ordered(db.submission_lines)
    if submission_id is not None:
        records = [l for l in records if l["submission_id"] == submission_id]
    if receipt_line_id is not None:
        records = [l for l in records if l["receipt_line_id"] == receipt_line_id]
    if program_item_id is not None:
        records = [l for l in records if l["program_item_id"] == program_item_id]
    return paginated(records, submission_line_out)


@bp.route("/submission-lines/<line_id>", methods=["GET"])
def get_submission_line_flat(line_id):
    authenticate(READ_ROLES)
    return object_response(submission_line_out(
        lookup.submission_line(line_id)))
