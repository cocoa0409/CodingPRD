"""Request-body shape checks (PRD 2.8 rank 6) and entity lookup helpers
(ranks 3 and 4)."""
from flask import request

import clock
import db
from errors import ApiError

INVALID = "ERR_INVALID_REQUEST"

# ---------------------------------------------------------------- enum sets
PAYER_TYPES = ("MEDICARE", "MEDICAID", "COMMERCIAL", "TRICARE", "SELF_PAY")
STATE_CODES = ("CA", "TX", "NY", "FL")
FINANCIAL_CLASSES = ("INPATIENT", "OUTPATIENT", "EMERGENCY")
ACCOUNT_STATUSES = ("OPEN", "CLOSED", "BAD_DEBT")
POSTABLE_TXN_TYPES = ("CHARGE", "PAYMENT", "CONTRACTUAL_ADJUSTMENT")
ALL_TXN_TYPES = ("CHARGE", "PAYMENT", "CONTRACTUAL_ADJUSTMENT", "REFUND_DISBURSEMENT",
                 "TAKE_BACK_OFFSET", "ESCHEAT_REMITTANCE", "REVERSAL")
TXN_SOURCES = ("PATIENT", "PAYER", "SYSTEM")
ATTRIBUTION_METHODS = ("PROPORTIONAL", "REVERSE_CHRONOLOGICAL")
CAUSE_CODES = ("DUPLICATE_PAYMENT", "CONTRACTUAL_UNDER_ADJUSTMENT", "WRONG_ACCOUNT_POSTING",
               "COB_PRIMARY_SECONDARY", "ESTIMATE_OVERCOLLECTION", "RETRO_ELIGIBILITY_CHANGE")
CORRECTIVE_ACTIONS = ("REPOST_TRANSACTION", "UPDATE_CONTRACT_TERMS", "STAFF_RETRAINING",
                      "PAYER_ESCALATION", "NONE")
PAYEE_TYPES = ("PATIENT", "PAYER")
DECISIONS = ("APPROVED", "REJECTED", "RETURNED")
BANK_ACCOUNT_CODES = ("OPERATING", "TRUST", "ESCROW")
VOID_REASONS = ("STALE_DATED", "WRONG_PAYEE", "BATCH_ERROR", "PAYER_REQUEST")
ESCHEAT_BASES = ("ISSUE_DATE", "LAST_CONTACT")
CONTACT_METHODS = ("FIRST_CLASS_MAIL", "CERTIFIED_MAIL", "EMAIL")
REPORT_TYPES = ("CREDIT_BALANCE_LIABILITY", "MEDICARE_CBR", "ESCHEAT_HOLDER_REPORT")


def body():
    raw = request.get_json(silent=True)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ApiError(INVALID, "Request body must be a JSON object.")
    return raw


# ---------------------------------------------------------------- scalars
def _present(data, name):
    return name in data and data[name] is not None


def req_str(data, name, min_len=1, max_len=None):
    if not _present(data, name):
        raise ApiError(INVALID, "Field '%s' is required." % name)
    value = data[name]
    if not isinstance(value, str):
        raise ApiError(INVALID, "Field '%s' must be a string." % name)
    if len(value) < min_len or (max_len is not None and len(value) > max_len):
        raise ApiError(INVALID, "Field '%s' has an illegal length." % name)
    return value


def opt_str(data, name, default=None, min_len=0, max_len=None):
    if not _present(data, name):
        return default
    value = data[name]
    if not isinstance(value, str):
        raise ApiError(INVALID, "Field '%s' must be a string." % name)
    if len(value) < min_len or (max_len is not None and len(value) > max_len):
        raise ApiError(INVALID, "Field '%s' has an illegal length." % name)
    return value


def req_enum(data, name, members):
    value = req_str(data, name)
    if value not in members:
        raise ApiError(INVALID, "Field '%s' must be one of %s." % (name, ", ".join(members)))
    return value


def opt_enum(data, name, members, default=None):
    if not _present(data, name):
        return default
    value = data[name]
    if not isinstance(value, str) or value not in members:
        raise ApiError(INVALID, "Field '%s' must be one of %s." % (name, ", ".join(members)))
    return value


def req_int(data, name, minimum=None, maximum=None):
    if not _present(data, name):
        raise ApiError(INVALID, "Field '%s' is required." % name)
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(INVALID, "Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise ApiError(INVALID, "Field '%s' is below its minimum." % name)
    if maximum is not None and value > maximum:
        raise ApiError(INVALID, "Field '%s' is above its maximum." % name)
    return value


def opt_int(data, name, default=None, minimum=None, maximum=None):
    if not _present(data, name):
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(INVALID, "Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise ApiError(INVALID, "Field '%s' is below its minimum." % name)
    if maximum is not None and value > maximum:
        raise ApiError(INVALID, "Field '%s' is above its maximum." % name)
    return value


def opt_bool(data, name, default=None):
    if not _present(data, name):
        return default
    value = data[name]
    if not isinstance(value, bool):
        raise ApiError(INVALID, "Field '%s' must be a boolean." % name)
    return value


def req_dt(data, name):
    if not _present(data, name):
        raise ApiError(INVALID, "Field '%s' is required." % name)
    parsed = clock.parse_iso(data[name])
    if parsed is None:
        raise ApiError(INVALID, "Field '%s' must be an ISO 8601 instant." % name)
    return parsed


def opt_dt(data, name, default=None):
    if not _present(data, name):
        return default
    parsed = clock.parse_iso(data[name])
    if parsed is None:
        raise ApiError(INVALID, "Field '%s' must be an ISO 8601 instant." % name)
    return parsed


def req_str_array(data, name, allow_empty=False):
    if not _present(data, name):
        raise ApiError(INVALID, "Field '%s' is required." % name)
    value = data[name]
    if not isinstance(value, list):
        raise ApiError(INVALID, "Field '%s' must be an array." % name)
    if not value and not allow_empty:
        raise ApiError(INVALID, "Field '%s' must not be empty." % name)
    for member in value:
        if not isinstance(member, str):
            raise ApiError(INVALID, "Field '%s' must contain strings." % name)
    return value


def opt_str_array(data, name, default=None):
    if not _present(data, name):
        return list(default) if default is not None else None
    value = data[name]
    if not isinstance(value, list):
        raise ApiError(INVALID, "Field '%s' must be an array." % name)
    for member in value:
        if not isinstance(member, str):
            raise ApiError(INVALID, "Field '%s' must contain strings." % name)
    return value


# ---------------------------------------------------------------- lookups
_STORES = {
    "payer": (lambda: db.payers, "ERR_PAYER_NOT_FOUND"),
    "account": (lambda: db.patient_accounts, "ERR_ACCOUNT_NOT_FOUND"),
    "transaction": (lambda: db.account_transactions, "ERR_TRANSACTION_NOT_FOUND"),
    "credit_balance": (lambda: db.credit_balances, "ERR_CREDIT_BALANCE_NOT_FOUND"),
    "finding": (lambda: db.root_cause_findings, "ERR_ROOT_CAUSE_FINDING_NOT_FOUND"),
    "refund_request": (lambda: db.refund_requests, "ERR_REFUND_REQUEST_NOT_FOUND"),
    "refund_approval": (lambda: db.refund_approvals, "ERR_REFUND_APPROVAL_NOT_FOUND"),
    "refund_batch": (lambda: db.refund_batches, "ERR_REFUND_BATCH_NOT_FOUND"),
    "check": (lambda: db.check_disbursements, "ERR_CHECK_NOT_FOUND"),
    "notice": (lambda: db.take_back_notices, "ERR_TAKE_BACK_NOTICE_NOT_FOUND"),
    "offset": (lambda: db.offset_applications, "ERR_OFFSET_APPLICATION_NOT_FOUND"),
    "obligation": (lambda: db.medicare_obligations, "ERR_MEDICARE_OBLIGATION_NOT_FOUND"),
    "escheatment": (lambda: db.escheatment_records, "ERR_ESCHEATMENT_RECORD_NOT_FOUND"),
    "report": (lambda: db.compliance_reports, "ERR_COMPLIANCE_REPORT_NOT_FOUND"),
}


def must_exist(kind, row_id):
    store, err = _STORES[kind]
    if not isinstance(row_id, str):
        raise ApiError(err)
    found = store().get(row_id)
    if found is None:
        raise ApiError(err)
    return found


def fk_exists(kind, data, name):
    """Rank 4: a foreign key supplied in the body must resolve. A missing or
    non-string value falls through to the rank 6 shape check."""
    if not _present(data, name):
        return None
    value = data[name]
    if not isinstance(value, str):
        return None
    store, err = _STORES[kind]
    found = store().get(value)
    if found is None:
        raise ApiError(err)
    return found
