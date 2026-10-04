"""Existence and nesting lookups (validation ladder step 3).

Path identifiers are validated left to right (PRD 2.9): each id must exist
and must nest correctly under its parent; the first failure raises
ERR_NOT_FOUND (404) before any business rule runs.
"""

import db
from errors import ApiError


def _get(collection, entity_id, what):
    rec = collection.get(entity_id)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "%s not found" % what)
    return rec


def store(store_id):
    return _get(db.stores, store_id, "Store")


def program(program_id):
    return _get(db.programs, program_id, "RebateProgram")


def program_in_store(store_id, program_id):
    prog = _get(db.programs, program_id, "RebateProgram")
    if prog["store_id"] != store_id:
        raise ApiError("ERR_NOT_FOUND",
                       "RebateProgram does not belong to this store")
    return prog


def program_item(item_id):
    return _get(db.program_items, item_id, "ProgramItem")


def account(account_id):
    return _get(db.accounts, account_id, "CreditAccount")


def account_in_store(store_id, account_id):
    acct = _get(db.accounts, account_id, "CreditAccount")
    if acct["store_id"] != store_id:
        raise ApiError("ERR_NOT_FOUND",
                       "CreditAccount does not belong to this store")
    return acct


def job(job_id):
    return _get(db.jobs, job_id, "JobPurchase")


def job_in_store(store_id, job_id):
    jb = _get(db.jobs, job_id, "JobPurchase")
    if jb["store_id"] != store_id:
        raise ApiError("ERR_NOT_FOUND",
                       "JobPurchase does not belong to this store")
    return jb


def receipt(receipt_id):
    return _get(db.receipts, receipt_id, "Receipt")


def receipt_in_store(store_id, receipt_id):
    rcpt = _get(db.receipts, receipt_id, "Receipt")
    if rcpt["store_id"] != store_id:
        raise ApiError("ERR_NOT_FOUND", "Receipt does not belong to this store")
    return rcpt


def receipt_line(line_id):
    return _get(db.receipt_lines, line_id, "ReceiptLine")


def submission(submission_id):
    return _get(db.submissions, submission_id, "RebateSubmission")


def submission_in_store(store_id, submission_id):
    sub = _get(db.submissions, submission_id, "RebateSubmission")
    if sub["store_id"] != store_id:
        raise ApiError("ERR_NOT_FOUND",
                       "RebateSubmission does not belong to this store")
    return sub


def submission_line(line_id):
    return _get(db.submission_lines, line_id, "SubmissionLine")


def certificate(certificate_id):
    return _get(db.certificates, certificate_id, "RebateCertificate")


def certificate_in_store(store_id, certificate_id):
    cert = _get(db.certificates, certificate_id, "RebateCertificate")
    if cert["store_id"] != store_id:
        raise ApiError("ERR_NOT_FOUND",
                       "RebateCertificate does not belong to this store")
    return cert


def ledger_entry(entry_id):
    return _get(db.ledger_entries, entry_id, "CreditLedgerEntry")


def flag(flag_id):
    return _get(db.flags, flag_id, "FraudFlag")


def flag_in_store(store_id, flag_id):
    flg = _get(db.flags, flag_id, "FraudFlag")
    if flg["store_id"] != store_id:
        raise ApiError("ERR_NOT_FOUND",
                       "FraudFlag does not belong to this store")
    return flg


def breakage_run(run_id):
    return _get(db.breakage_runs, run_id, "BreakageRun")


def breakage_run_in_store(store_id, run_id):
    run = _get(db.breakage_runs, run_id, "BreakageRun")
    if run["store_id"] != store_id:
        raise ApiError("ERR_NOT_FOUND",
                       "BreakageRun does not belong to this store")
    return run


def return_record(return_id):
    return _get(db.returns, return_id, "Return")
