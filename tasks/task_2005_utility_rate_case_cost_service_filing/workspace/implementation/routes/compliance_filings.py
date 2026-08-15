"""ComplianceFiling endpoints (PRD 3.8): OCC-guarded create-with-supersede,
true-up freeze at submit, staff review."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_REMAND_NOTES_REQUIRED,
    ERR_INVALID_CASE_STATE,
    ERR_INVALID_FILING_STATE,
    ERR_FILING_NOT_SUPERSEDABLE,
    ERR_INCOMPLETE_CLASS_REVENUE,
    ERR_STALE_VERSION,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, query_arg
from services.calculations import compute_true_up
from services.core import new_record, public, touch
from validate import (
    get_body,
    no_unknown_fields,
    req_enum,
    req_int,
    req_str,
    require_fk,
    require_path_resource,
)

bp = Blueprint("compliance_filings", __name__)


def _req_actuals(body):
    v = body.get("actual_revenue_by_class")
    if v is None or not isinstance(v, list):
        raise_error(ERR_INVALID_REQUEST, "actual_revenue_by_class must be an array")
    out = []
    for i, ln in enumerate(v):
        if not isinstance(ln, dict):
            raise_error(ERR_INVALID_REQUEST, f"actuals line {i} must be an object")
        for key in ln:
            if key not in ("class_code", "actual_revenue_cents"):
                raise_error(ERR_INVALID_REQUEST, f"actuals line {i} has unknown field: {key}")
        code = ln.get("class_code")
        amt = ln.get("actual_revenue_cents")
        if code is None or not isinstance(code, str) or code.strip() == "":
            raise_error(ERR_INVALID_REQUEST, f"actuals line {i} requires class_code")
        if amt is None or isinstance(amt, bool) or not isinstance(amt, int):
            raise_error(ERR_INVALID_REQUEST, f"actuals line {i} requires integer actual_revenue_cents")
        out.append({"class_code": code, "actual_revenue_cents": amt})
    return out


def _filings_of_case(case_id):
    return [f for f in db["compliance_filings"].values() if f["rate_case_id"] == case_id]


@bp.post("/compliance-filings")
def create_filing():
    body = get_body()
    no_unknown_fields(body, {
        "rate_case_id", "period_label", "actual_revenue_by_class",
        "expected_rate_case_version",
    })
    rate_case_id = req_str(body, "rate_case_id")
    period_label = req_str(body, "period_label")
    actuals = _req_actuals(body)
    expected_version = req_int(body, "expected_rate_case_version")
    authorized(["UtilityFiler"])
    case = require_fk("rate_cases", rate_case_id, "rate_case_id")
    # State guards (p6): phase, then supersede-ability of the incumbent filing
    if case["status"] != "COMPLIANCE_MONITORING":
        raise_error(ERR_INVALID_CASE_STATE,
                    "compliance filings require the case in COMPLIANCE_MONITORING")
    for f in _filings_of_case(case["id"]):
        if f["status"] in ("SUBMITTED", "ACCEPTED"):
            raise_error(ERR_FILING_NOT_SUPERSEDABLE,
                        "a filing in SUBMITTED or ACCEPTED blocks a new filing")
    # Referential (p9): the actuals must cover every class of the case exactly once
    case_codes = sorted(c["class_code"] for c in db["customer_classes"].values()
                        if c["rate_case_id"] == case["id"])
    seen = [l["class_code"] for l in actuals]
    if len(seen) != len(set(seen)) or sorted(seen) != case_codes:
        raise_error(ERR_INCOMPLETE_CLASS_REVENUE,
                    "actual_revenue_by_class must cover every class of the case exactly once")
    # OCC (p12)
    if expected_version != case["version"]:
        raise_error(ERR_STALE_VERSION,
                    "expected_rate_case_version does not match the case's current version")
    # Supersede the incumbent DRAFT / REMANDED filing
    superseded = None
    for f in _filings_of_case(case["id"]):
        if f["status"] in ("DRAFT", "REMANDED"):
            f["status"] = "SUPERSEDED"
            touch(f)
            superseded = f
    rec = new_record("compliance_filings", {
        "rate_case_id": rate_case_id,
        "period_label": period_label,
        "actual_revenue_by_class": actuals,
        "actual_total_revenue_cents": sum(l["actual_revenue_cents"] for l in actuals),
        "true_up_delta_cents": None,
        "true_up_action": None,
        "class_true_up_lines": None,
        "supersedes_filing_id": superseded["id"] if superseded is not None else None,
        "status": "DRAFT",
    })
    touch(case)
    return success_object(public(rec), status=201)


@bp.get("/compliance-filings")
def list_filings():
    filters = {
        "rate_case_id": query_arg("rate_case_id"),
        "status": query_arg("status"),
        "supersedes_filing_id": query_arg("supersedes_filing_id"),
    }
    return list_response("compliance_filings", filters)


@bp.get("/compliance-filings/<filing_id>")
def get_filing(filing_id):
    return get_one("compliance_filings", filing_id)


@bp.post("/compliance-filings/<filing_id>/submit")
def submit_filing(filing_id):
    body = get_body()
    no_unknown_fields(body, set())
    authorized(["UtilityFiler"])
    filing = require_path_resource("compliance_filings", filing_id)
    if filing["status"] != "DRAFT":
        raise_error(ERR_INVALID_FILING_STATE, "submit requires DRAFT")
    case = db["rate_cases"].get(filing["rate_case_id"])
    if case is None or case["status"] != "COMPLIANCE_MONITORING":
        raise_error(ERR_INVALID_CASE_STATE,
                    "submit requires the case in COMPLIANCE_MONITORING")
    result = compute_true_up(
        filing["actual_revenue_by_class"], case["authorized_revenue_requirement_cents"])
    filing["true_up_delta_cents"] = result["true_up_delta_cents"]
    filing["true_up_action"] = result["true_up_action"]
    filing["class_true_up_lines"] = result["class_true_up_lines"]
    filing["status"] = "SUBMITTED"
    touch(filing)
    return success_object(public(filing))


@bp.post("/compliance-filings/<filing_id>/review")
def review_filing(filing_id):
    body = get_body()
    no_unknown_fields(body, {"outcome", "remand_notes"})
    outcome = req_enum(body, "outcome", ("ACCEPT", "REMAND"))
    notes = body.get("remand_notes")
    if outcome == "REMAND" and (notes is None or not isinstance(notes, str) or notes.strip() == ""):
        raise_error(ERR_REMAND_NOTES_REQUIRED, "remand_notes required when outcome is REMAND")
    authorized(["CommissionStaff"])
    filing = require_path_resource("compliance_filings", filing_id)
    if filing["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_FILING_STATE, "review requires SUBMITTED")
    filing["status"] = "ACCEPTED" if outcome == "ACCEPT" else "REMANDED"
    touch(filing)
    return success_object(public(filing))
