"""Post-close audits, findings, rebuttals and adjudication."""
from flask import Blueprint, request

from core import (ApiError, Field, authenticate, ordered, paginate, raw_body,
                  respond_collection, respond_created, respond_object, validate_body)
from store import Tx, db, resolve_fk
import services

bp = Blueprint("audits", __name__)

SAMPLE_REASONS = ("RANDOM", "DISCRETIONARY", "INVESTOR_REQUEST")
FINDING_CATEGORIES = ("INCOME_CALCULATION", "ATR_DOCUMENTATION", "POINTS_AND_FEES",
                      "APPRAISAL", "SEASONING", "OVERLAY_EXCEPTION")
SEVERITIES = ("MINOR", "SIGNIFICANT", "MATERIAL")
AUDIT_READERS = ("PostCloseAuditor", "Underwriter", "ChiefCreditOfficer",
                 "SecuritizationAnalyst")
FINDING_READERS = ("PostCloseAuditor", "Underwriter", "LoanOfficer", "ChiefCreditOfficer")


def finding_state(condition, message):
    if not condition:
        raise ApiError("ERR_FINDING_STATE_INVALID", message)


@bp.post("/post-close-audits")
def create_audit():
    authenticate(("PostCloseAuditor",))
    raw = raw_body()
    loan_file = resolve_fk(raw, "loan_file_id", "loan_files")
    values = validate_body([
        Field("loan_file_id", "str", True),
        Field("sample_reason", "enum", True, SAMPLE_REASONS),
    ])
    # priority 10
    if loan_file["status"] not in ("CLOSED", "AUDIT_DEFECT"):
        raise ApiError("ERR_LOAN_FILE_STATE_INVALID",
                       "only a closed loan file may be audited")

    row = db.insert("audits", {
        "loan_file_id": loan_file["id"],
        "sample_reason": values["sample_reason"],
        "status": "OPEN",
        "defect_score": 0,
        "grade": "NOT_GRADED",
        "open_finding_count": 0,
    })
    return respond_created(row)


@bp.get("/post-close-audits/<ident>")
def read_audit(ident):
    authenticate(AUDIT_READERS)
    return respond_object(db.fetch("audits", ident))


@bp.get("/loan-files/<ident>/post-close-audits")
def list_audits(ident):
    authenticate(AUDIT_READERS)
    loan_file = db.fetch("loan_files", ident)
    rows = services.audits_of(loan_file)
    wanted = request.args.get("grade")
    if wanted:
        rows = [r for r in rows if r["grade"] == wanted]
    page, limit, offset, total = paginate(ordered(rows))
    return respond_collection(page, limit, offset, total)


@bp.post("/audit-findings")
def create_finding():
    authenticate(("PostCloseAuditor",))
    raw = raw_body()
    audit = resolve_fk(raw, "audit_id", "audits")
    values = validate_body([
        Field("audit_id", "str", True),
        Field("finding_code", "str", True),
        Field("category", "enum", True, FINDING_CATEGORIES),
        Field("severity", "enum", True, SEVERITIES),
    ])
    # priority 15
    finding_state(audit["status"] in ("OPEN", "FINDINGS_ISSUED"),
                  "audit status %s is closed to new findings" % audit["status"])
    loan_file = db.find("loan_files", audit["loan_file_id"])
    finding_state(loan_file["status"] in ("CLOSED", "AUDIT_DEFECT"),
                  "the loan file is not in an auditable state")
    # priority 28
    for existing in services.findings_of(audit):
        if existing["finding_code"] == values["finding_code"]:
            raise ApiError("ERR_DUPLICATE_CODE",
                           "finding_code must be unique within the audit")

    tx = Tx()
    row = db.insert("findings", {
        "audit_id": audit["id"],
        "finding_code": values["finding_code"],
        "category": values["category"],
        "severity": values["severity"],
        "status": "ISSUED",
        "rebuttal_text": None,
        "rebuttal_round": 0,
        "adjudication_note": None,
    })
    tx.watch(audit)
    if audit["status"] == "OPEN":
        audit["status"] = "FINDINGS_ISSUED"
    services.audit_regrade(audit, tx)
    tx.commit()
    return respond_created(row)


@bp.get("/post-close-audits/<ident>/findings")
def list_findings(ident):
    authenticate(FINDING_READERS)
    audit = db.fetch("audits", ident)
    rows = services.findings_of(audit)
    for key in ("status", "severity"):
        wanted = request.args.get(key)
        if wanted:
            rows = [r for r in rows if r[key] == wanted]
    page, limit, offset, total = paginate(ordered(rows))
    return respond_collection(page, limit, offset, total)


@bp.post("/audit-findings/<ident>/rebut")
def rebut_finding(ident):
    authenticate(("LoanOfficer", "Underwriter"))
    finding = db.fetch("findings", ident)
    values = validate_body([Field("rebuttal_text", "str", True)])
    # priority 15
    finding_state(finding["status"] == "ISSUED",
                  "finding status %s does not accept a rebuttal" % finding["status"])

    tx = Tx()
    tx.watch(finding)
    finding["status"] = "REBUTTED"
    finding["rebuttal_text"] = values["rebuttal_text"]
    finding["rebuttal_round"] = int(finding["rebuttal_round"]) + 1
    audit = db.find("audits", finding["audit_id"])
    services.audit_regrade(audit, tx)
    tx.commit()
    return respond_object(finding)


@bp.post("/audit-findings/<ident>/adjudicate")
def adjudicate_finding(ident):
    authenticate(("PostCloseAuditor",))
    finding = db.fetch("findings", ident)
    values = validate_body([
        Field("decision", "enum", True, ("UPHOLD", "WAIVE", "RETURN_FOR_MORE_INFO")),
        Field("adjudication_note", "str"),
    ])
    decision = values["decision"]
    # priority 15
    finding_state(finding["status"] in ("ISSUED", "REBUTTED"),
                  "finding status %s is terminal" % finding["status"])
    if decision == "RETURN_FOR_MORE_INFO":
        finding_state(finding["status"] == "REBUTTED",
                      "there is no rebuttal to return")

    tx = Tx()
    tx.watch(finding)
    if "adjudication_note" in values:
        finding["adjudication_note"] = values["adjudication_note"]
    if decision == "UPHOLD":
        finding["status"] = "UPHELD"
    elif decision == "WAIVE":
        finding["status"] = "WAIVED"
    else:
        finding["status"] = "ISSUED"
    audit = db.find("audits", finding["audit_id"])
    services.audit_regrade(audit, tx)
    tx.commit()
    return respond_object(finding)
