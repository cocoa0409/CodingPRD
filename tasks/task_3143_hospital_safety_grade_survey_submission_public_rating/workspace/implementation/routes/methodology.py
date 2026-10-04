"""Methodology version and pending-change routes."""

from flask import Blueprint

from db import store
from errors import ERR_INVALID_REQUEST, ApiError
from middleware import VERIFICATION_ANALYST, body_json, require_read, authorize
from routes.common import filter_value, ok_list, ok_object
from services import methodology as methodology_service

bp = Blueprint("methodology", __name__, url_prefix="/hospital-safety-rating")


@bp.post("/methodology-versions")
def create_version():
    authorize(["RatingAdmin"])
    version = methodology_service.create_methodology_version(body_json())
    return ok_object(version), 201


@bp.get("/methodology-versions")
def list_versions():
    require_read()
    status = filter_value("status")
    previous = filter_value("previous_version_id")
    rows = list(store.methodology_versions.values())
    if status is not None:
        rows = [row for row in rows if row.get("status") == status]
    if previous is not None:
        rows = [row for row in rows if row.get("previous_version_id") == previous]
    return ok_list(rows)


@bp.get("/methodology-versions/<version_id>")
def read_version(version_id):
    require_read()
    return ok_object(methodology_service.get_methodology_version(version_id))


@bp.post("/methodology-versions/<version_id>/publish")
def publish_version(version_id):
    authorize(["RatingAdmin"])
    version = methodology_service.get_methodology_version(version_id)
    return ok_object(methodology_service.publish_methodology_version(version))


# --- Pending methodology changes --------------------------------------------

@bp.get("/pending-methodology-changes")
def list_pending_changes():
    require_read()
    hospital_id = filter_value("hospital_id")
    to_version = filter_value("to_methodology_version_id")
    from_row = filter_value("from_hospital_methodology_version_id")
    status = filter_value("status")
    rows = list(store.pending_methodology_changes.values())
    if hospital_id is not None:
        rows = [row for row in rows if row.get("hospital_id") == hospital_id]
    if to_version is not None:
        rows = [row for row in rows if row.get("to_methodology_version_id") == to_version]
    if from_row is not None:
        rows = [row for row in rows if row.get("from_hospital_methodology_version_id") == from_row]
    if status is not None:
        rows = [row for row in rows if row.get("status") == status]
    return ok_list(rows)


@bp.get("/pending-methodology-changes/<change_id>")
def read_pending_change(change_id):
    require_read()
    return ok_object(methodology_service.get_pending_change(change_id))


@bp.post("/pending-methodology-changes/<change_id>/review")
def review_pending_change(change_id):
    user_id, _role = authorize([VERIFICATION_ANALYST])
    change = methodology_service.get_pending_change(change_id)
    payload = body_json()
    decision = payload.get("decision")
    if not isinstance(decision, str) or decision.strip() == "":
        raise ApiError(ERR_INVALID_REQUEST)
    updated = methodology_service.review_pending_change(change, decision, user_id)
    return ok_object(updated)


# --- Hospital methodology pins ----------------------------------------------

@bp.get("/hospital-methodology-versions")
def list_pins():
    require_read()
    hospital_id = filter_value("hospital_id")
    version_id = filter_value("methodology_version_id")
    is_current = filter_value("is_current")
    rows = list(store.hospital_methodology_versions.values())
    if hospital_id is not None:
        rows = [row for row in rows if row.get("hospital_id") == hospital_id]
    if version_id is not None:
        rows = [row for row in rows if row.get("methodology_version_id") == version_id]
    if is_current is not None:
        desired = is_current.lower() in ("true", "1")
        rows = [row for row in rows if bool(row.get("is_current")) == desired]
    return ok_list(rows)


@bp.get("/hospital-methodology-versions/<row_id>")
def read_pin(row_id):
    require_read()
    return ok_object(methodology_service.get_hospital_methodology_version(row_id))