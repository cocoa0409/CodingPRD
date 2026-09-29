"""Comparative analyses: drafting, supersession, submission, review, reopening (PRD 3.4)."""

from flask import Blueprint

import calc
import recompute
import serialize
import shape
from auth import actor, guard
from enums import (ALL_ROLES, REVIEW_OUTCOMES, STRINGENCY_FINDINGS,
                   SUPERSEDABLE_ANALYSIS_STATUSES)
from envelope import success
from errors import ApiError
from helpers import list_response
from store import db, lookup_path, new_row, touch

bp = Blueprint("analyses", __name__)


@bp.route("/comparative-analyses", methods=["POST"])
@guard("PlanSponsor", "Administrator")
def create_analysis():
    payload = shape.body()
    # Step 5: nqtl_item_id is declared before supersedes_analysis_id.
    raw_item = shape.raw_fk(payload, "nqtl_item_id")
    if raw_item is not None and raw_item not in db.nqtl_items:
        raise ApiError("ERR_NQTL_ITEM_NOT_FOUND")
    raw_supersedes = shape.raw_fk(payload, "supersedes_analysis_id")
    if raw_supersedes is not None and raw_supersedes not in db.analyses:
        raise ApiError("ERR_ANALYSIS_NOT_FOUND")

    item_id = shape.req_string(payload, "nqtl_item_id", 1, None)
    supersedes_id = shape.opt_string(payload, "supersedes_analysis_id", 1, None)
    factor_count = shape.req_int(payload, "factor_count", 0, None)
    evidentiary_standard_count = shape.req_int(payload, "evidentiary_standard_count", 0, None)
    written_finding = shape.req_enum(payload, "stringency_written_finding", STRINGENCY_FINDINGS)
    operation_finding = shape.req_enum(payload, "stringency_operation_finding",
                                       STRINGENCY_FINDINGS)
    expected_version = shape.req_int(payload, "expected_nqtl_item_version", 1, None)

    item = db.nqtl_items[item_id]
    superseded = db.analyses[supersedes_id] if supersedes_id else None

    # Step 12: a superseding analysis must document the same NQTL item.
    if superseded is not None and superseded["nqtl_item_id"] != item_id:
        raise ApiError("ERR_CROSS_PLAN_YEAR_REFERENCE")
    # Step 13: the named analysis must still be supersedable.
    if superseded is not None and superseded["status"] not in SUPERSEDABLE_ANALYSIS_STATUSES:
        raise ApiError("ERR_ANALYSIS_ALREADY_SUPERSEDED")
    # Step 14.
    plan_year = recompute.plan_year_of_item(item)
    recompute.gate_not_closed(plan_year)
    # Step 17: optimistic concurrency against the parent NQTL item.
    if expected_version != item["version"]:
        raise ApiError("ERR_STALE_NQTL_ITEM_VERSION")

    superseded_from = None
    if superseded is not None:
        superseded_from = superseded["status"]
        superseded["status"] = "WITHDRAWN"
        touch(superseded)

    row = new_row({
        "nqtl_item_id": item_id,
        "supersedes_analysis_id": supersedes_id,
        "authored_by_user_id": actor(),
        "certified_by_user_id": None,
        "factor_count": factor_count,
        "evidentiary_standard_count": evidentiary_standard_count,
        "stringency_written_finding": written_finding,
        "stringency_operation_finding": operation_finding,
        "revision_round": 0,
        "status": "DRAFT",
    })
    db.analyses[row["id"]] = row

    recompute.recompute_stringency(item, bump=False)
    if item["status"] == "INVENTORIED":
        item["status"] = "ANALYSIS_DRAFTED"
    elif superseded_from == "SUBMITTED" and item["status"] == "ANALYSIS_SUBMITTED":
        item["status"] = "ANALYSIS_DRAFTED"
    touch(item)
    if plan_year is not None:
        recompute.recompute_plan_year(plan_year)
    return success(serialize.comparative_analysis(row), 201)


@bp.route("/comparative-analyses/<analysis_id>", methods=["GET"])
@guard(*ALL_ROLES)
def read_analysis(analysis_id):
    row = lookup_path(db.analyses, analysis_id, "ERR_ANALYSIS_NOT_FOUND")
    return success(serialize.comparative_analysis(row))


@bp.route("/comparative-analyses", methods=["GET"])
@guard(*ALL_ROLES)
def list_analyses():
    return list_response(db.analyses.values(), serialize.comparative_analysis,
                         ("nqtl_item_id", "supersedes_analysis_id", "status"))


@bp.route("/comparative-analyses/<analysis_id>/submit", methods=["POST"])
@guard("PlanSponsor", "Administrator")
def submit_analysis(analysis_id):
    analysis = lookup_path(db.analyses, analysis_id, "ERR_ANALYSIS_NOT_FOUND")
    shape.body()
    item = db.nqtl_items.get(analysis["nqtl_item_id"])
    plan_year = recompute.plan_year_of_analysis(analysis)
    # Step 14.
    recompute.gate_not_closed(plan_year)
    # Step 16.
    if analysis["status"] != "DRAFT":
        raise ApiError("ERR_ANALYSIS_NOT_DRAFT")
    # Step 21: the documentation must be minimally complete.
    if (analysis["factor_count"] < calc.MIN_FACTORS
            or analysis["evidentiary_standard_count"] < calc.MIN_EVIDENTIARY_STANDARDS):
        raise ApiError("ERR_INSUFFICIENT_COMPARATIVE_ANALYSIS")

    analysis["status"] = "SUBMITTED"
    touch(analysis)
    if item is not None:
        recompute.recompute_stringency(item, bump=False)
        item["status"] = "ANALYSIS_SUBMITTED"
        touch(item)
        if plan_year is not None:
            recompute.recompute_plan_year(plan_year)
    return success(serialize.comparative_analysis(analysis))


@bp.route("/comparative-analyses/<analysis_id>/review", methods=["POST"])
@guard("ComplianceOfficer")
def review_analysis(analysis_id):
    analysis = lookup_path(db.analyses, analysis_id, "ERR_ANALYSIS_NOT_FOUND")
    payload = shape.body()
    outcome = shape.req_enum(payload, "outcome", REVIEW_OUTCOMES)
    shape.opt_string(payload, "review_note", 1, None)

    item = db.nqtl_items.get(analysis["nqtl_item_id"])
    plan_year = recompute.plan_year_of_analysis(analysis)
    # Step 14.
    recompute.gate_not_closed(plan_year)
    # Step 16.
    if analysis["status"] != "SUBMITTED":
        raise ApiError("ERR_ANALYSIS_NOT_SUBMITTED")
    # Step 18: the author may never review their own analysis, on either branch.
    if actor() == analysis["authored_by_user_id"]:
        raise ApiError("ERR_SELF_CERTIFICATION")
    # Step 20: certification demands as-applied evidence.
    if outcome == "CERTIFIED" and not _has_denial_rate_evidence(item):
        raise ApiError("ERR_IN_OPERATION_DATA_MISSING")

    if outcome == "CERTIFIED":
        analysis["status"] = "CERTIFIED"
        analysis["certified_by_user_id"] = actor()
        touch(analysis)
        if item is not None:
            recompute.recompute_stringency(item, bump=None)
    else:
        analysis["status"] = "INSUFFICIENT"
        touch(analysis)
        if item is not None:
            recompute.recompute_stringency(item, bump=False)
            if item["status"] == "ANALYSIS_SUBMITTED":
                item["status"] = "ANALYSIS_DRAFTED"
            touch(item)
            if plan_year is not None:
                recompute.recompute_plan_year(plan_year)
    return success(serialize.comparative_analysis(analysis))


def _has_denial_rate_evidence(item):
    if item is None:
        return False
    for submission in db.data_submissions.values():
        if (submission["status"] == "VALIDATED"
                and submission["submission_type"] == "DENIAL_RATES"
                and submission["classification_id"] == item["classification_id"]):
            return True
    return False


@bp.route("/comparative-analyses/<analysis_id>/reopen", methods=["POST"])
@guard("PlanSponsor", "Administrator")
def reopen_analysis(analysis_id):
    analysis = lookup_path(db.analyses, analysis_id, "ERR_ANALYSIS_NOT_FOUND")
    shape.body()
    plan_year = recompute.plan_year_of_analysis(analysis)
    # Step 14.
    recompute.gate_not_closed(plan_year)
    # Step 16.
    if analysis["status"] != "INSUFFICIENT":
        raise ApiError("ERR_ANALYSIS_NOT_INSUFFICIENT")
    # Step 26: the revision loop is bounded.
    if analysis["revision_round"] >= calc.MAX_REVISION_ROUNDS:
        raise ApiError("ERR_REVISION_LIMIT_REACHED")

    analysis["status"] = "DRAFT"
    analysis["revision_round"] = analysis["revision_round"] + 1
    touch(analysis)
    return success(serialize.comparative_analysis(analysis))
