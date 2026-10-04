"""Accident reporting, investigation, and public projection (PRD section 3.7)."""
from datetime import timedelta

from flask import Blueprint, g, request

import clock
import services_penalty
import store
from constants import (
    ABATEMENT_BASE_DAYS,
    ACCIDENT_SEVERITIES,
    ALL_ROLES,
    BUSINESS_READ_ROLES,
    FATAL_LIMIT_SECONDS,
    LATE_REPORT_STANDARD_CODE,
    OTHER_LIMIT_SECONDS,
    ROLE_MSHA_ADMIN,
    ROLE_OPERATOR_REP,
)
from envelope import list_response, ok_object
from errors import (
    ApiError,
    ERR_ACCIDENT_INVESTIGATION_INCOMPLETE,
    ERR_INVALID_STATE,
    ERR_MINE_NOT_ACTIVE,
    ERR_NOT_FOUND,
    ERR_OPERATOR_MISMATCH,
)
from serialize import accident as ser_accident
from validate import get_or_404, parse_body, require_roles

bp = Blueprint("accidents", __name__, url_prefix="/msha")


def _issue_late_report_citation(mine):
    """System-issued citation for a late accident report (fixed factors)."""
    now = clock.now()
    base_days = ABATEMENT_BASE_DAYS["NO_INJURY"]
    draft = {
        "inspection_id": None,
        "mine_id": mine["id"],
        "issued_by_inspector_id": None,
        "standard_code": LATE_REPORT_STANDARD_CODE,
        "kind": "CITATION",
        "negligence": "MODERATE",
        "gravity_likelihood": "UNLIKELY",
        "gravity_severity": "NO_INJURY",
        "persons_affected": 1,
        "significant_and_substantial": False,
        "repeat_violation": False,
        "issued_at": now,
    }
    points_total = services_penalty.compute_points_total(draft)
    draft.update({
        "abatement_base_days": base_days,
        "abatement_deadline": now + timedelta(days=base_days),
        "abatement_extended": False,
        "abated_at": None,
        "verified_at": None,
        "verified_by_inspector_id": None,
        "abatement_status": "OPEN",
        "contest_status": "UNCONTESTED",
        "system_issued": True,
    })
    citation = store.new_entity(store.citations, draft)
    services_penalty.create_assessment(citation, points_total)
    return citation


@bp.route("/accidents", methods=["POST"])
def report_accident():
    require_roles(ROLE_OPERATOR_REP)
    body = parse_body({
        "mine_id": ("str", True),
        "occurred_at": ("datetime", True),
        "severity": ("enum", True, ACCIDENT_SEVERITIES),
        "description": ("str", True),
    })
    mine = get_or_404(store.mines, body["mine_id"], "mine")
    if g.uid != mine["operator_id"]:
        raise ApiError(ERR_OPERATOR_MISMATCH, "X-User-ID must be the operator of this mine")
    if mine["status"] != "ACTIVE":
        raise ApiError(ERR_MINE_NOT_ACTIVE, "an IDLED mine cannot accept an accident report")
    reported_at = clock.now()
    limit_seconds = FATAL_LIMIT_SECONDS if body["severity"] == "FATAL" else OTHER_LIMIT_SECONDS
    # Strict greater-than: a gap exactly at the limit is timely.
    late_report = (reported_at - body["occurred_at"]) > timedelta(seconds=limit_seconds)
    accident = store.new_entity(store.accidents, {
        "mine_id": mine["id"],
        "occurred_at": body["occurred_at"],
        "reported_at": reported_at,
        "severity": body["severity"],
        "description": body["description"],
        "late_report": late_report,
        "root_cause": None,
        "report_text": None,
        "published_at": None,
        "status": "REPORTED",
    })
    if late_report:
        _issue_late_report_citation(mine)
    return ok_object(ser_accident(accident), 201)


@bp.route("/accidents/<accidentId>", methods=["GET"])
def get_accident(accidentId):
    require_roles(*BUSINESS_READ_ROLES)
    return ok_object(ser_accident(get_or_404(store.accidents, accidentId, "accident")))


@bp.route("/accidents", methods=["GET"])
def list_accidents():
    require_roles(*BUSINESS_READ_ROLES)
    items = list(store.accidents.values())
    for param in ("mine_id", "severity", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [a for a in items if a.get(param) is not None and a[param] == value]
    return list_response(items, ser_accident)


@bp.route("/accidents/<accidentId>/publish-report", methods=["POST"])
def publish_report(accidentId):
    require_roles(ROLE_MSHA_ADMIN)
    body = parse_body({
        "root_cause": ("str", True),
        "report_text": ("str", True),
    })
    accident = get_or_404(store.accidents, accidentId, "accident")
    if accident["status"] != "UNDER_INVESTIGATION":
        raise ApiError(ERR_INVALID_STATE, "publication requires UNDER_INVESTIGATION status")
    completed = any(
        i["accident_id"] == accident["id"]
        and i["kind"] == "ACCIDENT_INVESTIGATION"
        and i["status"] == "COMPLETED"
        for i in store.inspections.values()
    )
    if not completed:
        raise ApiError(
            ERR_ACCIDENT_INVESTIGATION_INCOMPLETE,
            "a COMPLETED ACCIDENT_INVESTIGATION inspection is required before publication",
        )
    accident["root_cause"] = body["root_cause"]
    accident["report_text"] = body["report_text"]
    accident["published_at"] = clock.now()
    accident["status"] = "REPORT_PUBLISHED"
    store.touch(accident)
    return ok_object(ser_accident(accident))


@bp.route("/accidents/<accidentId>/public-report", methods=["GET"])
def public_report(accidentId):
    require_roles(*ALL_ROLES)
    accident = store.accidents.get(accidentId)
    # Unpublished accidents answer 404 exactly as if absent (PRD 2.10).
    if accident is None or accident["status"] != "REPORT_PUBLISHED":
        raise ApiError(ERR_NOT_FOUND, "accident '{}' was not found".format(accidentId))
    return ok_object(ser_accident(accident))
