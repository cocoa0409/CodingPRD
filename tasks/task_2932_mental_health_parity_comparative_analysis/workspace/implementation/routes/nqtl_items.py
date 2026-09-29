"""The NQTL inventory, parity determinations and participant notices (PRD 3.4, 3.7)."""

from decimal import Decimal

from flask import Blueprint

import calc
import recompute
import serialize
import shape
from auth import actor, guard
from enums import ALL_ROLES, APPLIED_TO, DETERMINATION_OUTCOMES, NOTICE_TYPES, NQTL_TYPES
from envelope import success
from errors import ApiError
from helpers import list_response
from store import db, lookup_path, new_row, touch

bp = Blueprint("nqtl_items", __name__)


@bp.route("/nqtl-items", methods=["POST"])
@guard("PlanSponsor", "ComplianceOfficer")
def create_nqtl_item():
    payload = shape.body()
    # Step 5: plan_year_id is declared before classification_id.
    raw_plan_year = shape.raw_fk(payload, "plan_year_id")
    if raw_plan_year is not None and raw_plan_year not in db.plan_years:
        raise ApiError("ERR_PLAN_YEAR_NOT_FOUND")
    raw_classification = shape.raw_fk(payload, "classification_id")
    if raw_classification is not None and raw_classification not in db.classifications:
        raise ApiError("ERR_CLASSIFICATION_NOT_FOUND")

    plan_year_id = shape.req_string(payload, "plan_year_id", 1, None)
    classification_id = shape.req_string(payload, "classification_id", 1, None)
    nqtl_type = shape.req_enum(payload, "nqtl_type", NQTL_TYPES)
    applied_to = shape.req_enum(payload, "applied_to", APPLIED_TO)
    description = shape.req_string(payload, "description", 1, 400)

    plan_year = db.plan_years[plan_year_id]
    classification = db.classifications[classification_id]

    # Step 12: the classification must belong to the named plan year.
    if classification["plan_year_id"] != plan_year_id:
        raise ApiError("ERR_CROSS_PLAN_YEAR_REFERENCE")
    # Step 14.
    recompute.gate_not_closed(plan_year)
    # Step 24: the classification must actually offer the benefits being protected.
    if not classification["mh_su_benefits_covered"]:
        raise ApiError("ERR_MH_BENEFITS_NOT_COVERED")
    # Step 25: one live row per limitation.
    for existing in db.nqtl_items.values():
        if (existing["plan_year_id"] == plan_year_id
                and existing["classification_id"] == classification_id
                and existing["nqtl_type"] == nqtl_type
                and existing["status"] != "REMEDIATED"):
            raise ApiError("ERR_DUPLICATE_NQTL_ITEM")

    row = new_row({
        "plan_year_id": plan_year_id,
        "classification_id": classification_id,
        "nqtl_type": nqtl_type,
        "applied_to": applied_to,
        "description": description,
        "stringency_in_operation_index": Decimal("0.00"),
        "stringency_flag": False,
        "determination_recorded_by_user_id": None,
        "status": "INVENTORIED",
    })
    db.nqtl_items[row["id"]] = row
    recompute.recompute_stringency(row, bump=False)
    recompute.recompute_plan_year(plan_year)
    return success(serialize.nqtl_item(row), 201)


@bp.route("/nqtl-items/<item_id>", methods=["GET"])
@guard(*ALL_ROLES)
def read_nqtl_item(item_id):
    row = lookup_path(db.nqtl_items, item_id, "ERR_NQTL_ITEM_NOT_FOUND")
    return success(serialize.nqtl_item(row))


@bp.route("/nqtl-items", methods=["GET"])
@guard(*ALL_ROLES)
def list_nqtl_items():
    return list_response(db.nqtl_items.values(), serialize.nqtl_item,
                         ("plan_year_id", "classification_id", "nqtl_type", "status"))


@bp.route("/nqtl-items/<item_id>/determinations", methods=["POST"])
@guard("ComplianceOfficer")
def record_determination(item_id):
    item = lookup_path(db.nqtl_items, item_id, "ERR_NQTL_ITEM_NOT_FOUND")
    payload = shape.body()
    outcome = shape.req_enum(payload, "outcome", DETERMINATION_OUTCOMES)
    shape.req_string(payload, "rationale", 1, None)
    expected_version = shape.req_int(payload, "expected_plan_year_version", 1, None)

    plan_year = recompute.plan_year_of_item(item)
    # Step 14.
    recompute.gate_not_closed(plan_year)
    # Step 16: only two starting states admit a determination.
    if item["status"] not in ("ANALYSIS_SUBMITTED", "COMPLIANT"):
        raise ApiError("ERR_ITEM_NOT_AWAITING_DETERMINATION")
    # Step 17: optimistic concurrency against the parent plan year.
    if plan_year is not None and expected_version != plan_year["version"]:
        raise ApiError("ERR_STALE_PLAN_YEAR_VERSION")

    # The index is recomputed from current evidence immediately before the checks.
    recompute.recompute_stringency(item, bump=False)
    index = item["stringency_in_operation_index"]

    # Step 22: a certified analysis must stand behind a compliant determination.
    if outcome == "COMPLIANT":
        latest = calc.latest_analysis(item["id"])
        if latest is None or latest["status"] != "CERTIFIED":
            raise ApiError("ERR_ANALYSIS_NOT_CERTIFIED")
    # Step 23: the outcome must agree with the recomputed evidence.
    if outcome == "COMPLIANT" and index >= calc.STRINGENCY_VIOLATION_THRESHOLD:
        raise ApiError("ERR_STRINGENCY_CONTRADICTS_EVIDENCE")
    if outcome == "VIOLATION" and index < calc.STRINGENCY_VIOLATION_THRESHOLD:
        raise ApiError("ERR_STRINGENCY_CONTRADICTS_EVIDENCE")

    # Cascade, deepest fact first.
    item["status"] = outcome
    item["determination_recorded_by_user_id"] = actor()
    touch(item)
    if outcome == "VIOLATION":
        recompute.create_participant_notice(item, "VIOLATION_DISCLOSURE",
                                           "DETERMINATION_CASCADE")
    if plan_year is not None:
        recompute.recompute_plan_year(plan_year, bump=True)
    return success(serialize.nqtl_item(item), 201)


@bp.route("/nqtl-items/<item_id>/participant-notices", methods=["GET"])
@guard(*ALL_ROLES)
def list_participant_notices(item_id):
    lookup_path(db.nqtl_items, item_id, "ERR_NQTL_ITEM_NOT_FOUND")
    rows = [n for n in db.notices.values() if n["nqtl_item_id"] == item_id]
    return list_response(rows, serialize.participant_notice, ("notice_type",))
