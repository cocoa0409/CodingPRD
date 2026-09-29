"""Compliance determinations and public notifications (PRD section 3.5)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import constants as C
import db
from db import store, touch, now
from errors import ApiError, invalid
from middleware import authenticate
from numeric import ceil_int, divide
from response import created_response, object_response
from routes.common import (
    apply_scalar_filters,
    detail,
    filter_fk,
    page,
    pagination,
    resolve,
)
from services import compliance
from shape import Body

bp = Blueprint("determinations", __name__)


def _verdict(determination_lraa, hazard, quarters_used, entry_point, contaminant):
    individual = determination_lraa > contaminant["mcl_ng_per_l"]
    mixture = bool(contaminant["hazard_index_member"]) and hazard > C.HAZARD_INDEX_MCL
    if (
        quarters_used < C.LRAA_WINDOW_QUARTERS
        and entry_point["monitoring_status"] == "QUARTERLY"
        and not individual
        and not mixture
    ):
        return "MONITORING_VIOLATION"
    if individual or mixture:
        return "MCL_VIOLATION"
    if determination_lraa >= contaminant["trigger_level_ng_per_l"]:
        return "TRIGGER_EXCEEDED"
    return "NO_VIOLATION"


def _violation_type(verdict, determination_lraa, hazard, entry_point, contaminant):
    if verdict == "MONITORING_VIOLATION":
        return "MONITORING_AND_REPORTING"
    if verdict != "MCL_VIOLATION":
        return "NONE"
    magnitude = (
        determination_lraa >= C.ACUTE_MULTIPLIER * contaminant["mcl_ng_per_l"]
        or hazard >= C.HAZARD_TERM_CAP
    )
    populous = entry_point["population_served"] >= C.ACUTE_MIN_POPULATION
    return "ACUTE" if (magnitude and populous) else "NON_ACUTE"


# ------------------------------------------------------------------ determinations
@bp.route("/compliance-determinations", methods=["POST"])
def create_determination():
    user_id, _role = authenticate(("ComplianceOfficer",))
    body = Body(["entry_point_id", "contaminant_id", "period_end", "expected_entry_point_version"])
    entry_point_id = body.string("entry_point_id")
    contaminant_id = body.string("contaminant_id")
    period_end = body.period("period_end")
    expected_version = body.integer("expected_entry_point_version")

    entry_point = resolve("entry_points", entry_point_id)
    contaminant = resolve("contaminants", contaminant_id)

    if entry_point["version"] != expected_version:
        raise ApiError("ERR_STALE_ENTRY_POINT_VERSION")

    lraa, planning_lraa, quarters_used = compliance.lraa_pair(entry_point_id, contaminant_id)
    hazard = entry_point["hazard_index"]
    verdict = _verdict(lraa, hazard, quarters_used, entry_point, contaminant)
    violation_type = _violation_type(verdict, lraa, hazard, entry_point, contaminant)

    row = db.insert(
        "determinations",
        {
            "entry_point_id": entry_point_id,
            "contaminant_id": contaminant_id,
            "period_end": period_end,
            "lraa_ng_per_l": lraa,
            "planning_lraa_ng_per_l": planning_lraa,
            "quarters_used": quarters_used,
            "hazard_index": hazard,
            "determination": verdict,
            "violation_type": violation_type,
            "status": "DRAFT",
            "determined_by_user_id": user_id,
            "issued_at": None,
            "rescind_reason": None,
        },
    )
    return created_response(db.public(row))


@bp.route("/compliance-determinations", methods=["GET"])
def list_determinations():
    authenticate(C.ANY_ROLE)
    limit, offset = pagination()
    rows = db.sorted_rows("determinations")
    rows = filter_fk(rows, "entry_point_id", "entry_points")
    rows = filter_fk(rows, "contaminant_id", "contaminants")
    rows = apply_scalar_filters(rows, ["status", "determination"])
    return page(rows, limit, offset)


@bp.route("/compliance-determinations/<row_id>", methods=["GET"])
def get_determination(row_id):
    authenticate(C.ANY_ROLE)
    return detail("determinations", row_id)


@bp.route("/compliance-determinations/<row_id>/issue", methods=["POST"])
def issue_determination(row_id):
    authenticate(("ComplianceOfficer",))
    determination = resolve("determinations", row_id)
    Body([])
    if determination["status"] != "DRAFT":
        raise ApiError("ERR_DETERMINATION_STATE_INVALID")
    if determination["quarters_used"] < 1:
        raise ApiError("ERR_NO_QUALIFYING_RESULTS")

    determination["status"] = "ISSUED"
    determination["issued_at"] = now()
    touch(determination)

    entry_point = store.entry_points.get(determination["entry_point_id"])
    if determination["determination"] == "MCL_VIOLATION" and entry_point is not None:
        entry_point["open_violation_count"] = compliance.open_violation_count(entry_point["id"])
        touch(entry_point)

    if determination["determination"] in ("MCL_VIOLATION", "MONITORING_VIOLATION"):
        contaminant = store.contaminants.get(determination["contaminant_id"])
        if determination["violation_type"] == "ACUTE":
            tier = "TIER_1"
        elif determination["determination"] == "MONITORING_VIOLATION":
            tier = "TIER_3"
        else:
            tier = contaminant["notification_tier"] if contaminant else "TIER_2"
        db.insert(
            "notifications",
            {
                "determination_id": determination["id"],
                "tier": tier,
                "required_by_at": determination["issued_at"]
                + timedelta(hours=C.TIER_DEADLINE_HOURS[tier]),
                "content_elements": [],
                "delivery_methods": [],
                "status": "DRAFT",
                "revision_count": 0,
                "drafted_by_user_id": None,
                "certified_by_user_id": None,
                "distributed_at": None,
                "late_by_hours": None,
                "delivery_evidence_ref": None,
                "review_note": None,
            },
        )
    return object_response(db.public(determination))


@bp.route("/compliance-determinations/<row_id>/rescind", methods=["POST"])
def rescind_determination(row_id):
    authenticate(("StateRegulator",))
    determination = resolve("determinations", row_id)
    body = Body(["rescind_reason"])
    reason = body.string("rescind_reason", nonblank=True)
    if determination["status"] != "ISSUED":
        raise ApiError("ERR_DETERMINATION_STATE_INVALID")

    was_mcl = determination["determination"] == "MCL_VIOLATION"
    determination["status"] = "RESCINDED"
    determination["rescind_reason"] = reason
    touch(determination)

    entry_point = store.entry_points.get(determination["entry_point_id"])
    if was_mcl and entry_point is not None:
        entry_point["open_violation_count"] = compliance.open_violation_count(entry_point["id"])
        touch(entry_point)

    for notification in db.sorted_rows("notifications"):
        if notification["determination_id"] != determination["id"]:
            continue
        if notification["status"] in ("DRAFT", "SUBMITTED", "APPROVED"):
            notification["status"] = "VOIDED"
            touch(notification)
    return object_response(db.public(determination))


# ----------------------------------------------------------------- notifications
@bp.route("/public-notifications", methods=["GET"])
def list_notifications():
    authenticate(C.ANY_ROLE)
    limit, offset = pagination()
    rows = db.sorted_rows("notifications")
    rows = filter_fk(rows, "determination_id", "determinations")
    rows = apply_scalar_filters(rows, ["status", "tier"])
    return page(rows, limit, offset)


@bp.route("/public-notifications/<row_id>", methods=["GET"])
def get_notification(row_id):
    authenticate(C.ANY_ROLE)
    return detail("notifications", row_id)


@bp.route("/public-notifications/<row_id>/submit", methods=["POST"])
def submit_notification(row_id):
    user_id, _role = authenticate(("ComplianceOfficer",))
    notification = resolve("notifications", row_id)
    body = Body(["content_elements", "delivery_methods"])
    content_elements = body.string_list("content_elements", non_empty=False)
    delivery_methods = body.string_list(
        "delivery_methods", choices=C.DELIVERY_METHODS, non_empty=False
    )

    if notification["status"] != "DRAFT":
        raise ApiError("ERR_NOTIFICATION_STATE_INVALID")
    if notification["revision_count"] > C.MAX_NOTIFICATION_REVISIONS:
        raise ApiError("ERR_NOTIFICATION_REVISION_LIMIT")
    for element in C.MANDATORY_CONTENT_ELEMENTS:
        if element not in content_elements:
            raise ApiError("ERR_NOTIFICATION_CONTENT_INCOMPLETE")
    for channel in C.REQUIRED_DELIVERY_METHODS_BY_TIER[notification["tier"]]:
        if channel not in delivery_methods:
            raise ApiError("ERR_DELIVERY_METHOD_INSUFFICIENT")

    notification["content_elements"] = content_elements
    notification["delivery_methods"] = delivery_methods
    notification["status"] = "SUBMITTED"
    notification["drafted_by_user_id"] = user_id
    touch(notification)
    return object_response(db.public(notification))


@bp.route("/public-notifications/<row_id>/review", methods=["POST"])
def review_notification(row_id):
    authenticate(("StateRegulator",))
    notification = resolve("notifications", row_id)
    body = Body(["approve", "review_note"])
    approve = body.boolean("approve")
    review_note = body.string("review_note", required=False, default=None)
    if not approve and (review_note is None or review_note.strip() == ""):
        raise invalid("review_note is required when returning a notification for revision")

    if notification["status"] != "SUBMITTED":
        raise ApiError("ERR_NOTIFICATION_STATE_INVALID")

    notification["review_note"] = review_note
    if approve:
        notification["status"] = "APPROVED"
    else:
        notification["status"] = "DRAFT"
        notification["revision_count"] = notification["revision_count"] + 1
        notification["content_elements"] = []
        notification["delivery_methods"] = []
    touch(notification)
    return object_response(db.public(notification))


@bp.route("/public-notifications/<row_id>/certify-distribution", methods=["POST"])
def certify_notification(row_id):
    user_id, _role = authenticate(("ComplianceOfficer",))
    notification = resolve("notifications", row_id)
    body = Body(["delivery_evidence_ref"])
    evidence = body.string("delivery_evidence_ref", nonblank=True)

    if notification["status"] != "APPROVED":
        raise ApiError("ERR_NOTIFICATION_STATE_INVALID")
    if notification["drafted_by_user_id"] is not None and user_id == notification["drafted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    clock = now()
    notification["delivery_evidence_ref"] = evidence
    notification["certified_by_user_id"] = user_id
    notification["distributed_at"] = clock
    if clock <= notification["required_by_at"]:
        notification["status"] = "DISTRIBUTED"
        notification["late_by_hours"] = 0
    else:
        overrun = divide(
            Decimal((clock - notification["required_by_at"]).total_seconds()), Decimal(3600)
        )
        hours = ceil_int(overrun)
        notification["status"] = "LATE_DISTRIBUTED"
        notification["late_by_hours"] = hours if hours >= 1 else 1
    touch(notification)
    return object_response(db.public(notification))
