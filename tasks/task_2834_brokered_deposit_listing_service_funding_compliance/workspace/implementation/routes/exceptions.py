from flask import Blueprint

import calc
import cascades
import db
import middleware as mw
import response
import util
from errors import ApiError

bp = Blueprint("exceptions", __name__)

BASES = ("TWENTY_FIVE_PERCENT_TEST", "ENABLING_TRANSACTIONS_TEST", "OTHER_APPLICATION")
FILING_ACTIONS = ("SUBMIT", "WITHDRAW")
REVIEW_ACTIONS = ("REQUEST_INFO", "RESUME_REVIEW", "GRANT", "DENY", "REVOKE")
TERMINAL = ("DENIED", "WITHDRAWN", "REVOKED")

READ_ROLES = ("SystemAdmin", "FundingDeskOfficer", "ComplianceReviewer",
              "TreasuryController", "Examiner")


def find_exception(exception_id):
    record = db.exceptions.get(exception_id)
    if record is None:
        raise ApiError("ERR_EXCEPTION_NOT_FOUND")
    return record


def _due_date():
    return util.add_days(util.clock_date().isoformat(), calc.REPORT_INTERVAL_DAYS)


@bp.post("/primary-purpose-exceptions")
def create_exception():
    user_id, _role = mw.auth("SystemAdmin", "FundingDeskOfficer")
    data = mw.body()
    broker_id = mw.req_id(data, "broker_id")
    institution_id = mw.req_id(data, "institution_id")
    basis = mw.req_enum(data, "exception_basis", BASES)
    business_line = mw.req_str(data, "designated_business_line")
    total_assets = mw.req_int(data, "total_customer_assets_cents", minimum=0)
    placed = mw.req_int(data, "deposits_placed_at_ifs_cents", minimum=0)
    enabling = mw.opt_int(data, "enabling_transaction_count", 0, minimum=0)
    total_txn = mw.opt_int(data, "total_transaction_count", 0, minimum=0)

    if institution_id not in db.institutions:
        raise ApiError("ERR_INSTITUTION_NOT_FOUND")
    if broker_id not in db.brokers:
        raise ApiError("ERR_BROKER_NOT_FOUND")

    if total_assets <= 0 or placed > total_assets:
        raise ApiError("ERR_EXCEPTION_INPUTS_INCOHERENT")
    if basis == "ENABLING_TRANSACTIONS_TEST" and total_txn <= 0:
        raise ApiError("ERR_EXCEPTION_INPUTS_INCOHERENT")
    if enabling > total_txn:
        raise ApiError("ERR_EXCEPTION_INPUTS_INCOHERENT")

    record = {
        "broker_id": broker_id,
        "institution_id": institution_id,
        "exception_basis": basis,
        "filing_type": "APPLICATION" if basis == "OTHER_APPLICATION" else "NOTICE",
        "designated_business_line": business_line,
        "total_customer_assets_cents": total_assets,
        "deposits_placed_at_ifs_cents": placed,
        "enabling_transaction_count": enabling,
        "total_transaction_count": total_txn,
        "business_line_deposit_ratio_bps": 0,
        "enabling_transaction_ratio_bps": 0,
        "test_outcome": "NOT_EVALUATED",
        "status": "DRAFT",
        "info_request_round_count": 0,
        "reporting_due_date": _due_date(),
        "reliant_program_count": 0,
        "prepared_by_user_id": user_id,
        "reviewed_by_user_id": None,
    }
    calc.primary_purpose_tests(record)
    db.stamp_new(record)
    db.exceptions[record["id"]] = record
    return response.created(db.public(record))


@bp.get("/primary-purpose-exceptions/<exception_id>")
def read_exception(exception_id):
    mw.auth(*READ_ROLES)
    return response.ok(db.public(find_exception(exception_id)))


@bp.get("/primary-purpose-exceptions")
def list_exceptions():
    mw.auth(*READ_ROLES)
    limit, offset = mw.page()
    rows = list(db.exceptions.values())
    for field in ("broker_id", "institution_id", "status"):
        wanted = mw.q(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    outcome = mw.q("test_outcome") or mw.q("test_type")
    if outcome is not None:
        rows = [r for r in rows if r["test_outcome"] == outcome]
    return response.listing(db.public_list(db.by_created(rows)), limit, offset)


@bp.post("/primary-purpose-exceptions/<exception_id>/filing-actions")
def filing_action(exception_id):
    mw.auth("SystemAdmin", "FundingDeskOfficer")
    filing = find_exception(exception_id)
    data = mw.body()
    action = mw.req_enum(data, "action", FILING_ACTIONS)
    mw.opt_str(data, "note")

    if action == "SUBMIT":
        if filing["status"] != "DRAFT":
            raise ApiError("ERR_EXCEPTION_STATE_INVALID")
        calc.primary_purpose_tests(filing)
        if filing["filing_type"] == "NOTICE" and filing["test_outcome"] != "QUALIFIED":
            raise ApiError("ERR_PRIMARY_PURPOSE_TEST_NOT_MET")
        today = util.clock_date().isoformat()
        if filing["reporting_due_date"] is not None and today > filing["reporting_due_date"]:
            raise ApiError("ERR_FILING_WINDOW_CLOSED")
        if filing["filing_type"] == "NOTICE":
            filing["status"] = "ACKNOWLEDGED"
            filing["reporting_due_date"] = _due_date()
        else:
            filing["status"] = "UNDER_REVIEW"
        db.bump(filing)
    else:  # WITHDRAW
        if filing["status"] not in ("DRAFT", "ACKNOWLEDGED", "UNDER_REVIEW", "INFO_REQUESTED"):
            raise ApiError("ERR_EXCEPTION_STATE_INVALID")
        if filing["reliant_program_count"] != 0:
            raise ApiError("ERR_EXCEPTION_STATE_INVALID",
                           "A filing still relied upon by a program cannot be withdrawn.")
        filing["status"] = "WITHDRAWN"
        filing["reporting_due_date"] = None
        db.bump(filing)
    return response.ok(db.public(filing))


@bp.post("/primary-purpose-exceptions/<exception_id>/review-actions")
def review_action(exception_id):
    user_id, _role = mw.auth("SystemAdmin", "ComplianceReviewer", "Examiner")
    filing = find_exception(exception_id)
    data = mw.body()
    action = mw.req_enum(data, "action", REVIEW_ACTIONS)
    mw.opt_str(data, "note")
    status = filing["status"]

    if action == "REQUEST_INFO":
        if status != "UNDER_REVIEW":
            raise ApiError("ERR_EXCEPTION_STATE_INVALID")
        if filing["info_request_round_count"] >= calc.MAX_INFO_REQUEST_ROUNDS:
            raise ApiError("ERR_REVIEW_ROUND_LIMIT")
        filing["status"] = "INFO_REQUESTED"
        filing["info_request_round_count"] += 1
        filing["reviewed_by_user_id"] = user_id
        db.bump(filing)

    elif action == "RESUME_REVIEW":
        if status != "INFO_REQUESTED":
            raise ApiError("ERR_EXCEPTION_STATE_INVALID")
        filing["status"] = "UNDER_REVIEW"
        filing["reviewed_by_user_id"] = user_id
        db.bump(filing)

    elif action == "GRANT":
        if status != "UNDER_REVIEW":
            raise ApiError("ERR_EXCEPTION_STATE_INVALID")
        if user_id == filing["prepared_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        filing["status"] = "GRANTED"
        filing["reporting_due_date"] = _due_date()
        filing["reviewed_by_user_id"] = user_id
        db.bump(filing)

    elif action == "DENY":
        if status != "UNDER_REVIEW":
            raise ApiError("ERR_EXCEPTION_STATE_INVALID")
        if user_id == filing["prepared_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        filing["status"] = "DENIED"
        filing["reporting_due_date"] = None
        filing["reviewed_by_user_id"] = user_id
        db.bump(filing)

    else:  # REVOKE
        if status not in ("ACKNOWLEDGED", "GRANTED"):
            raise ApiError("ERR_EXCEPTION_STATE_INVALID")
        if user_id == filing["prepared_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        filing["reviewed_by_user_id"] = user_id
        cascades.revoke_exception(filing)
        db.bump(filing)

    return response.ok(db.public(filing))
