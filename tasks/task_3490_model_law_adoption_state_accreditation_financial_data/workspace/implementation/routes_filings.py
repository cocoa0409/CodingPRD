"""Financial filings, validation edits, and the RBC cascade (PRD 3.4).

The validation edits E101/E103/E106/E107 have no failure conditions defined
anywhere in the PRD or scaffold; with every input guard already enforced at
creation (non-negative integer cents, valid enums), no edit can fail, so
validate always takes the pass branch. (Documented interpretation.)
"""

from flask import Blueprint

import calc
from auth import (
    authenticate,
    require_role,
    forbidden,
    ALL_ROLES,
    ROLE_ASSOCIATION_STAFF,
    ROLE_INSURER_USER,
)
from db import store, base_record, touch
from errors import ApiError
from routes_insurers import get_insurer_or_404
from serialize import serialize_filing, serialize_rbc_report
from util import get_body, req_str, req_int, req_enum, ok_object, paginate
from flask import request

bp = Blueprint("filings", __name__)

FILING_STATUSES = {"DRAFT", "SUBMITTED", "VALIDATED", "EDITS_FAILED", "SUPERSEDED"}


def get_filing_or_404(filing_id):
    f = store.filings.get(filing_id)
    if f is None:
        raise ApiError("ERR_FILING_NOT_FOUND", "Filing not found: %s" % filing_id, 404)
    return f


@bp.post("/naic/filings")
def create_filing():
    principal = authenticate()
    require_role(principal, {ROLE_INSURER_USER})
    body = get_body()
    # Stage 2 ownership (body-derived): insurer_id must equal X-User-ID.
    supplied = body.get("insurer_id")
    if supplied is not None and supplied != principal.user_id:
        forbidden("insurer_id must equal the acting insurer's id")
    # Stage 4 body reference resolution for the valuation standard code.
    if body.get("valuation_standard_code") is not None:
        code = body["valuation_standard_code"]
        found = False
        if isinstance(code, str):
            found = any(s["code"] == code for s in store.standards.values())
        if not found:
            raise ApiError(
                "ERR_VALUATION_STANDARD_NOT_FOUND",
                "valuation_standard_code does not resolve",
                404,
            )
    # Stage 5 shape.
    req_str(body, "insurer_id")
    period_year = req_int(body, "period_year")
    period_quarter = req_enum(body, "period_quarter", {"Q1", "Q2", "Q3", "Q4", "ANNUAL"})
    vs_code = req_str(body, "valuation_standard_code")
    surplus = req_int(body, "reported_surplus_cents", minimum=0)
    asset = req_int(body, "asset_risk_cents", minimum=0)
    underwriting = req_int(body, "underwriting_risk_cents", minimum=0)
    other = req_int(body, "other_risk_cents", minimum=0)
    expected_version = req_int(body, "expected_insurer_version")
    insurer = principal.entity
    # Stage 7 OCC.
    if expected_version != insurer["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_insurer_version does not match the insurer's current version",
            412,
        )
    # Stage 12 valuation standard currency: pin the currently ACTIVE version.
    active = None
    for s in store.standards.values():
        if s["code"] == vs_code and s["status"] == "ACTIVE":
            active = s
            break
    if active is None:
        raise ApiError(
            "ERR_VALUATION_STANDARD_NOT_ACTIVE",
            "No ACTIVE version of valuation standard %s" % vs_code,
            422,
        )
    # Supersede any non-SUPERSEDED filing of the same (insurer, year, quarter).
    superseded_validated = False
    for f in store.filings.values():
        if (
            f["insurer_id"] == insurer["id"]
            and f["period_year"] == period_year
            and f["period_quarter"] == period_quarter
            and f["status"] != "SUPERSEDED"
        ):
            if f["status"] == "VALIDATED":
                superseded_validated = True
            f["status"] = "SUPERSEDED"
            touch(f)
    if superseded_validated:
        # PRD 3.4: recomputed to null until a successor filing validates.
        insurer["latest_rbc_ratio"] = None
        insurer["latest_action_level"] = None
    rec = base_record()
    rec.update({
        "insurer_id": insurer["id"],
        "period_year": period_year,
        "period_quarter": period_quarter,
        "valuation_standard_code": vs_code,
        "valuation_standard_version_label": active["version_label"],
        "reported_surplus_cents": surplus,
        "asset_risk_cents": asset,
        "underwriting_risk_cents": underwriting,
        "other_risk_cents": other,
        "status": "DRAFT",
        "edit_failures": [],
    })
    store.filings[rec["id"]] = rec
    # The insurer's version increments by exactly one for the creation.
    touch(insurer)
    return ok_object(serialize_filing(rec), 201)


@bp.get("/naic/insurers/<insurer_id>/filings")
def list_insurer_filings(insurer_id):
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    insurer = get_insurer_or_404(insurer_id)
    filings = [f for f in store.filings.values() if f["insurer_id"] == insurer["id"]]
    raw_year = request.args.get("period_year")
    if raw_year is not None:
        try:
            year = int(raw_year)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "period_year must be an integer", 400)
        filings = [f for f in filings if f["period_year"] == year]
    raw_status = request.args.get("status")
    if raw_status is not None:
        if raw_status not in FILING_STATUSES:
            raise ApiError("ERR_INVALID_REQUEST", "Unknown filing status filter", 400)
        filings = [f for f in filings if f["status"] == raw_status]
    return paginate(filings, serialize_filing)


@bp.get("/naic/filings/<filing_id>")
def read_filing(filing_id):
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    return ok_object(serialize_filing(get_filing_or_404(filing_id)), 200)


@bp.post("/naic/filings/<filing_id>/submit")
def submit_filing(filing_id):
    principal = authenticate()
    require_role(principal, {ROLE_INSURER_USER})
    filing = get_filing_or_404(filing_id)
    if filing["insurer_id"] != principal.user_id:
        forbidden("X-User-ID must equal the filing's insurer_id")
    if filing["status"] != "DRAFT":
        raise ApiError(
            "ERR_FILING_NOT_DRAFT", "Filing %s is not DRAFT" % filing_id, 409
        )
    filing["status"] = "SUBMITTED"
    touch(filing)
    return ok_object(serialize_filing(filing), 200)


@bp.post("/naic/filings/<filing_id>/validate")
def validate_filing(filing_id):
    principal = authenticate()
    require_role(principal, {ROLE_ASSOCIATION_STAFF})
    filing = get_filing_or_404(filing_id)
    if filing["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_FILING_NOT_SUBMITTED", "Filing %s is not SUBMITTED" % filing_id, 409
        )
    # Checked after the state gate: the pinned version must still be ACTIVE.
    pinned_active = any(
        s["code"] == filing["valuation_standard_code"]
        and s["version_label"] == filing["valuation_standard_version_label"]
        and s["status"] == "ACTIVE"
        for s in store.standards.values()
    )
    if not pinned_active:
        raise ApiError(
            "ERR_VALUATION_STANDARD_NOT_ACTIVE",
            "The pinned valuation standard version is no longer ACTIVE",
            422,
        )
    # Edits E101/E103/E106/E107 pass (no PRD-defined failure conditions).
    filing["status"] = "VALIDATED"
    filing["edit_failures"] = []
    insurer = store.insurers.get(filing["insurer_id"])
    # Hop 1: compute the RBC report (exactly one per validated filing).
    vals = calc.rbc_values(
        filing["reported_surplus_cents"],
        filing["asset_risk_cents"],
        filing["underwriting_risk_cents"],
        filing["other_risk_cents"],
    )
    rec = base_record()
    rec.update({
        "filing_id": filing["id"],
        "insurer_naic_code": insurer["naic_code"],
        "tac_cents": vals["tac_cents"],
        "acl_covariance_cents": vals["acl_covariance_cents"],
        "acl_additive_cents": vals["acl_additive_cents"],
        "ratio_covariance": vals["ratio_covariance"],
        "ratio_additive": vals["ratio_additive"],
        "action_level": vals["action_level"],
    })
    store.rbc_reports[rec["id"]] = rec
    # Hop 2: classify and drive the insurer's supervision posture.
    insurer["latest_rbc_ratio"] = vals["ratio_covariance"]
    insurer["latest_action_level"] = vals["action_level"]
    insurer["status"] = (
        "UNDER_SUPERVISION"
        if vals["action_level"] in ("AUTHORIZED_CONTROL", "MANDATORY_CONTROL")
        else "ACTIVE"
    )
    # Hop 3: escalate the insurer's responses on still-OPEN calls.
    if insurer["status"] == "UNDER_SUPERVISION":
        for r in store.responses.values():
            if r["insurer_naic_code"] != insurer["naic_code"] or r["escalation_flag"]:
                continue
            call = store.calls.get(r["call_id"])
            if call is not None and call["status"] == "OPEN":
                r["escalation_flag"] = True
                touch(r)
    touch(filing)
    touch(insurer)
    return ok_object(serialize_filing(filing), 200)


@bp.get("/naic/filings/<filing_id>/rbc-reports")
def list_filing_rbc_reports(filing_id):
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    filing = get_filing_or_404(filing_id)
    reports = [r for r in store.rbc_reports.values() if r["filing_id"] == filing["id"]]
    return paginate(reports, serialize_rbc_report)
