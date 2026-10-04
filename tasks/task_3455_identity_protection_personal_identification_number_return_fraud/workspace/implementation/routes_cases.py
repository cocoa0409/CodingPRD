"""IdentityVerificationCase routes: open, list, read, request-documents,
document submission with coverage auto-advance, verify, fail (with the
third-failure fraud cascade), and per-case appointment listing."""
from flask import Blueprint, request

import calc
from auth import require_roles
from domain import (fraud_cascade, get_case, get_return, get_taxpayer,
                    new_record, open_case_for_return, open_hold_for_return,
                    pub, touch, deadline_plus)
from envelope import created, list_response, ok
from errors import err
from store import DB, parse_ts
from validate import body, invalid, page, pagination, req_enum, req_str

bp = Blueprint("cases", __name__)

CHANNELS = ("ONLINE", "PHONE", "IN_PERSON")
DOC_TYPES = ("PHOTO_ID", "PRIOR_YEAR_RETURN", "W2", "SSA_CARD", "UTILITY_BILL")
CASE_TERMINAL = ("VERIFIED", "EXPIRED")


def _own_case(uid, role, case):
    if role == "Taxpayer" and case["taxpayer_id"] != uid:
        err("ERR_UNAUTHORIZED")


@bp.post("/identity-protection/verification-cases")
def open_case():
    require_roles(["FraudAnalyst", "VerificationAgent"])
    b = body()
    # Priority 4: body-carried identifiers resolve (taxpayer, then return).
    taxpayer = None
    tid = b.get("taxpayer_id")
    if tid is not None:
        taxpayer = get_taxpayer(tid)
    ret = None
    rid = b.get("return_id")
    if rid is not None:
        ret = get_return(rid)
    channel = b.get("channel")
    if ret is not None:
        # Priority 8: no second non-terminal case per return.
        if open_case_for_return(ret["id"]) is not None:
            err("ERR_CASE_ALREADY_OPEN")
        # Priority 11: the return must be FILTER_HELD; GRAY-zone holds are
        # remote-only (ONLINE).
        if ret["status"] != "FILTER_HELD":
            err("ERR_RETURN_NOT_HELD")
        hold = open_hold_for_return(ret["id"])
        if hold is not None and hold["zone"] == "GRAY" and channel != "ONLINE":
            err("ERR_CHANNEL_NOT_ALLOWED")
    # Priority 14: payload shape.
    tid = req_str(b, "taxpayer_id")
    if taxpayer is None:
        err("ERR_TAXPAYER_NOT_FOUND")
    channel = req_enum(b, "channel", CHANNELS)
    if rid is not None and not isinstance(rid, str):
        invalid("return_id must be a string")
    rec = new_record(DB.cases, {
        "return_id": rid,
        "taxpayer_id": tid,
        "channel": channel,
        "attempts_count": 0,
        "required_document_types": list(calc.REQUIRED_DOCS[channel]),
        "deadline_at": deadline_plus(calc.CASE_DEADLINE_DAYS),
        "status": "OPENED",
    })
    return created(pub(rec))


@bp.get("/identity-protection/verification-cases")
def list_cases():
    require_roles(["FraudAnalyst", "VerificationAgent", "TaxpayerAdvocate", "SystemAdmin"])
    limit, offset = pagination()
    rows = list(DB.cases.values())
    for param in ("return_id", "taxpayer_id", "status"):
        v = request.args.get(param)
        if v is not None:
            rows = [c for c in rows if c.get(param) == v]
    items, total = page(rows, limit, offset)
    return list_response([pub(c) for c in items], total, limit, offset)


@bp.get("/identity-protection/verification-cases/<string:case_id>")
def read_case(case_id):
    uid, role = require_roles(
        ["FraudAnalyst", "VerificationAgent", "TaxpayerAdvocate", "SystemAdmin", "Taxpayer"])
    case = get_case(case_id)
    _own_case(uid, role, case)
    return ok(pub(case))


@bp.post("/identity-protection/verification-cases/<string:case_id>/request-documents")
def request_documents(case_id):
    require_roles(["VerificationAgent"])
    case = get_case(case_id)
    if case["status"] in CASE_TERMINAL:
        err("ERR_ALREADY_TERMINAL")
    if case["status"] not in ("OPENED", "FAILED"):
        err("ERR_INVALID_STATE", "Documents can be requested only from OPENED or FAILED.")
    case["status"] = "DOCS_REQUESTED"
    touch(case)
    return ok(pub(case))


@bp.post("/identity-protection/verification-cases/<string:case_id>/documents")
def submit_document(case_id):
    uid, role = require_roles(["Taxpayer", "VerificationAgent"])
    case = get_case(case_id)
    _own_case(uid, role, case)
    if case["status"] in CASE_TERMINAL:
        err("ERR_ALREADY_TERMINAL")
    if case["status"] != "DOCS_REQUESTED":
        err("ERR_INVALID_STATE", "Documents are accepted only while DOCS_REQUESTED.")
    # Priority 10: document deadline gate.
    if DB.now() > parse_ts(case["deadline_at"]):
        err("ERR_VERIFICATION_WINDOW_EXPIRED")
    # Priority 14: payload shape.
    doc_type = req_enum(body(), "doc_type", DOC_TYPES)
    doc = new_record(DB.documents, {
        "case_id": case["id"],
        "doc_type": doc_type,
        "received_at": DB.now_iso(),
    }, common=False)
    # Coverage: advance to DOCS_SUBMITTED exactly when the received doc_type
    # set covers required_document_types (extras accepted, no effect).
    received = {d["doc_type"] for d in DB.documents.values() if d["case_id"] == case["id"]}
    if set(case["required_document_types"]) <= received:
        case["status"] = "DOCS_SUBMITTED"
        touch(case)
    return created(pub(doc))


@bp.get("/identity-protection/verification-cases/<string:case_id>/documents")
def list_documents(case_id):
    uid, role = require_roles(["VerificationAgent", "FraudAnalyst", "Taxpayer", "SystemAdmin"])
    case = get_case(case_id)
    _own_case(uid, role, case)
    limit, offset = pagination()
    rows = [d for d in DB.documents.values() if d["case_id"] == case["id"]]
    items, total = page(rows, limit, offset)
    return list_response([pub(d) for d in items], total, limit, offset)


@bp.post("/identity-protection/verification-cases/<string:case_id>/verify")
def verify_case(case_id):
    require_roles(["VerificationAgent"])
    case = get_case(case_id)
    if case["status"] in CASE_TERMINAL:
        err("ERR_ALREADY_TERMINAL")
    if case["status"] != "DOCS_SUBMITTED":
        err("ERR_INVALID_STATE", "Only a DOCS_SUBMITTED case can be verified.")
    case["status"] = "VERIFIED"
    touch(case)
    if case["return_id"] is not None:
        ret = DB.returns.get(case["return_id"])
        if ret is not None and ret["status"] == "FILTER_HELD":
            ret["status"] = "FILTER_PASSED"
            touch(ret)
            hold = open_hold_for_return(ret["id"])
            if hold is not None:
                hold["status"] = "RESOLVED_VERIFIED"
                touch(hold)
    return ok(pub(case))


@bp.post("/identity-protection/verification-cases/<string:case_id>/fail")
def fail_case(case_id):
    require_roles(["VerificationAgent"])
    case = get_case(case_id)
    if case["status"] in CASE_TERMINAL:
        err("ERR_ALREADY_TERMINAL")
    if case["status"] not in ("DOCS_REQUESTED", "DOCS_SUBMITTED"):
        err("ERR_INVALID_STATE",
            "Failures are recorded only from DOCS_REQUESTED or DOCS_SUBMITTED.")
    attempts = case["attempts_count"] + 1
    if attempts >= calc.MAX_VERIFICATION_ATTEMPTS:
        # Third failure: EXPIRED (not FAILED), attempts pinned at 3, and a
        # return-linked FILTER_HELD return cascades to FRAUD_CONFIRMED.
        case["attempts_count"] = calc.MAX_VERIFICATION_ATTEMPTS
        case["status"] = "EXPIRED"
        touch(case)
        if case["return_id"] is not None:
            ret = DB.returns.get(case["return_id"])
            if ret is not None and ret["status"] == "FILTER_HELD":
                ret["status"] = "FRAUD_CONFIRMED"
                touch(ret)
                fraud_cascade(ret)
    else:
        case["attempts_count"] = attempts
        case["status"] = "FAILED"
        touch(case)
    return ok(pub(case))


@bp.get("/identity-protection/verification-cases/<string:case_id>/appointments")
def list_case_appointments(case_id):
    uid, role = require_roles(["VerificationAgent", "FraudAnalyst", "SystemAdmin", "Taxpayer"])
    case = get_case(case_id)
    _own_case(uid, role, case)
    limit, offset = pagination()
    rows = [a for a in DB.appointments.values() if a["case_id"] == case["id"]]
    items, total = page(rows, limit, offset)
    return list_response([pub(a) for a in items], total, limit, offset)
