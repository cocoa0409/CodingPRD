"""Investigation endpoints: creation, locking, clearance, publication and rehearsal."""
from flask import Blueprint, request as flask_request

import clock
import db
import response
import validation as v
from errors import ApiError
from middleware import (ALL_ROLES, ROLE_DATA_REPORTER, ROLE_LEGAL_COUNSEL,
                        ROLE_MANAGING_EDITOR, authenticate)
from services import calculations
from services import investigation as inv_service
from services import publication as pub_service

bp = Blueprint("investigations", __name__)

PUBLICATION_MODES = ("FULL_DATA_RELEASE", "AGGREGATES_ONLY", "METHODOLOGY_ONLY")
DATA_RELEASE_MODES = ("FULL_DATA_RELEASE", "AGGREGATES_ONLY")
CLEARABLE_STATUSES = ("HOLD_LEGAL_REVIEW", "FINDINGS_LOCKED")


def _invalid_investigation_state(investigation):
    return ApiError(
        "ERR_INVALID_INVESTIGATION_STATE",
        "The operation is not declared from investigation status %s." % investigation["status"],
    )


@bp.post("/investigations")
def create_investigation():
    authenticate([ROLE_MANAGING_EDITOR, ROLE_DATA_REPORTER])
    payload = v.body()
    desk_id = v.field_string(payload, "desk_id", min_len=1, non_blank=True)
    headline = v.field_string(payload, "headline", min_len=1, max_len=200, non_blank=True)
    publication_mode = v.field_enum(payload, "publication_mode", PUBLICATION_MODES)
    db.get_desk(desk_id)
    investigation = db.insert("investigations", {
        "desk_id": desk_id,
        "release_dataset_id": None,
        "headline": headline,
        "publication_mode": publication_mode,
        "status": "DRAFTING",
        "analysis_readiness": "NOT_READY",
        "finding_count": 0,
        "unverified_finding_count": 0,
        "doc_matched_finding_count": 0,
        "sme_confirmed_finding_count": 0,
        "sme_disputed_finding_count": 0,
        "methodology_doc_ref": None,
        "disclosure_risk_score": None,
        "applicable_risk_variant": None,
        "hold_reason_code": None,
        "legal_clearance_at": None,
        "published_at": None,
    })
    return response.created_response(db.serialize(investigation))


@bp.get("/investigations/<investigation_id>")
def get_investigation(investigation_id):
    authenticate(ALL_ROLES)
    return response.object_response(db.serialize(db.get_investigation(investigation_id)))


@bp.get("/investigations")
def list_investigations():
    authenticate(ALL_ROLES)
    limit, offset = v.pagination()
    rows = v.apply_filters(db.ordered("investigations"),
                           ["desk_id", "release_dataset_id", "status"])
    window = rows[offset:offset + limit]
    return response.array_response(db.serialize_all(window), limit, offset, len(rows))


@bp.post("/investigations/<investigation_id>/lock-findings")
def lock_findings(investigation_id):
    authenticate([ROLE_MANAGING_EDITOR])
    investigation = db.get_investigation(investigation_id)
    if investigation["status"] != "ANALYSIS":
        raise _invalid_investigation_state(investigation)
    if investigation["analysis_readiness"] != "READY":
        raise ApiError("ERR_ANALYSIS_NOT_READY",
                       "The investigation's analysis_readiness must be READY before locking.")
    investigation["status"] = "FINDINGS_LOCKED"
    for record in db.subjects_of_investigation(investigation_id):
        if record["status"] == "DRAFT":
            record["status"] = "NOTICE_ELIGIBLE"
            db.touch(record)
    db.touch(investigation)
    return response.object_response(db.serialize(investigation))


@bp.post("/investigations/<investigation_id>/legal-clearance")
def legal_clearance(investigation_id):
    authenticate([ROLE_LEGAL_COUNSEL])
    investigation = db.get_investigation(investigation_id)
    payload = v.body()
    v.field_text(payload, "clearance_note")
    if investigation["status"] not in CLEARABLE_STATUSES:
        raise _invalid_investigation_state(investigation)
    desk = inv_service.desk_of(investigation)
    if desk is not None and desk["security_posture"] == "LOCKDOWN":
        raise ApiError("ERR_DESK_LOCKDOWN",
                       "The desk is in LOCKDOWN; legal clearance is refused.")
    investigation["status"] = "CLEARED"
    investigation["legal_clearance_at"] = clock.now_iso()
    investigation["hold_reason_code"] = None
    db.touch(investigation)
    return response.object_response(db.serialize(investigation))


@bp.post("/investigations/<investigation_id>/publication")
def publish(investigation_id):
    authenticate([ROLE_MANAGING_EDITOR])
    investigation = db.get_investigation(investigation_id)
    payload = v.body()
    methodology_doc_ref = v.field_string(payload, "methodology_doc_ref", min_len=1,
                                         non_blank=True)
    release_dataset_id = v.field_string(payload, "release_dataset_id", min_len=1,
                                        non_blank=True, optional=True, default=None,
                                        nullable=True)
    release_dataset = None
    if release_dataset_id is not None:
        release_dataset = db.get_dataset(release_dataset_id)
    # Rung 10 -- declared from FINDINGS_LOCKED and CLEARED only
    if investigation["status"] not in pub_service.PUBLISHABLE_STATUSES:
        raise _invalid_investigation_state(investigation)
    # Pre-step: lapse notified records whose response deadline has passed
    pub_service.lapse_notice_deadlines(investigation_id, persist=True)
    desk = inv_service.desk_of(investigation)
    blocking = pub_service.evaluate_gates(
        investigation, desk, release_dataset,
        release_dataset_named=release_dataset_id is not None,
        check_release_required=True,
    )
    if blocking is not None:
        raise ApiError(blocking, "Publication is refused by gate %s." % blocking)
    aggregate_max, composite, _ = calculations.disclosure_risk_scores(release_dataset)
    variant, score = calculations.applicable_risk(
        investigation["publication_mode"], aggregate_max, composite
    )
    investigation["status"] = "PUBLISHED"
    investigation["methodology_doc_ref"] = methodology_doc_ref
    investigation["release_dataset_id"] = release_dataset_id
    investigation["published_at"] = clock.now_iso()
    investigation["disclosure_risk_score"] = score
    investigation["applicable_risk_variant"] = variant
    db.touch(investigation)
    return response.object_response(db.serialize(investigation))


@bp.get("/investigations/<investigation_id>/disclosure-risk-preview")
def disclosure_risk_preview(investigation_id):
    authenticate(ALL_ROLES)
    investigation = db.get_investigation(investigation_id)
    requested_id = flask_request.args.get("release_dataset_id")
    release_dataset = None
    if requested_id is not None and requested_id != "":
        release_dataset = db.get_dataset(requested_id)
        if release_dataset.get("investigation_id") != investigation["id"]:
            raise ApiError("ERR_DATASET_NOT_LINKED",
                           "The named dataset belongs to a different investigation.")
    elif investigation.get("release_dataset_id"):
        release_dataset = db.find("datasets", investigation["release_dataset_id"])
    if release_dataset is None and investigation["publication_mode"] in DATA_RELEASE_MODES:
        raise ApiError("ERR_RELEASE_DATASET_REQUIRED",
                       "A data-release mode needs a release dataset to rehearse against.")
    aggregate_max, composite, _ = calculations.disclosure_risk_scores(release_dataset)
    variant, score = calculations.applicable_risk(
        investigation["publication_mode"], aggregate_max, composite
    )
    desk = inv_service.desk_of(investigation)
    # The rehearsal persists nothing, so the lapse pre-step is simulated only.
    pub_service.lapse_notice_deadlines(investigation_id, persist=False)
    blocking = pub_service.evaluate_gates(
        investigation, desk, release_dataset,
        release_dataset_named=release_dataset is not None,
        check_release_required=False,
    )
    return response.object_response({
        "aggregate_max_score": aggregate_max,
        "composite_weighted_score": composite,
        "applicable_variant": variant,
        "applicable_score": score,
        "notice_window_hours": pub_service.notice_window_hours(investigation_id),
        "blocking_reason_code": blocking if blocking is not None else "NONE",
    })
