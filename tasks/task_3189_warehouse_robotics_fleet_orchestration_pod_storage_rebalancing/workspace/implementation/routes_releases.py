"""Software releases blueprint."""

from flask import Blueprint, request

import errors
from cascades import entity_out, list_out
from db import store
from middleware import require_roles
from models import base_entity, bump, get_or_404, req_enum, req_str
from response import parse_pagination, success_list, success_object

bp = Blueprint("software_releases", __name__)

READ_ROLES = {"FleetAdmin", "ReleaseEngineer", "SafetyOfficer"}


@bp.route("/software-releases", methods=["POST"])
def create_release():
    require_roles({"ReleaseEngineer"})
    body = request.get_json(silent=True) or {}
    release_code = req_str(body, "release_code")
    for r in store.software_releases.values():
        if r["release_code"] == release_code:
            raise errors.validation(f"release_code already exists: {release_code}")
    release = base_entity()
    release.update(
        {
            "release_code": release_code,
            "status": "DRAFT",
            "safety_check_passed": False,
            "defect_notes": None,
        }
    )
    store.software_releases[release["id"]] = release
    return success_object(entity_out(release), status=201)


@bp.route("/software-releases", methods=["GET"])
def list_releases():
    require_roles(READ_ROLES)
    limit, offset = parse_pagination()
    status_f = request.args.get("status")
    items = list(store.software_releases.values())
    if status_f is not None:
        items = [r for r in items if r["status"] == status_f]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    return success_list(list_out(items[offset : offset + limit]), limit, offset, total)


@bp.route("/software-releases/<release_id>", methods=["GET"])
def get_release(release_id):
    require_roles(READ_ROLES)
    release = get_or_404(store.software_releases, release_id, "software release")
    return success_object(entity_out(release))


@bp.route("/software-releases/<release_id>/validate", methods=["POST"])
def validate_release(release_id):
    user_id, role = require_roles({"ReleaseEngineer"})
    release = get_or_404(store.software_releases, release_id, "software release")
    if release["status"] != "DRAFT":
        raise errors.invalid_state("release is not DRAFT")
    for r in store.software_releases.values():
        if r["id"] != release_id and r["status"] == "VALIDATING":
            raise errors.invalid_state("another release is already VALIDATING")
    release["status"] = "VALIDATING"
    release["_validation_initiated_by"] = user_id
    bump(release)
    return success_object(entity_out(release))


@bp.route("/software-releases/<release_id>/record-validation", methods=["POST"])
def record_validation(release_id):
    user_id, role = require_roles({"SafetyOfficer"})
    release = get_or_404(store.software_releases, release_id, "software release")
    body = request.get_json(silent=True) or {}
    outcome = req_enum(body, "outcome", {"PASS", "FAIL"})
    if release["status"] != "VALIDATING":
        raise errors.invalid_state("release is not VALIDATING")
    # Segregation of duties: SafetyOfficer must differ from initiating ReleaseEngineer.
    initiated_by = release.get("_validation_initiated_by")
    if initiated_by is not None and initiated_by == user_id:
        raise errors.safety_interlock(
            "segregation of duties: officer must differ from initiating engineer"
        )
    if outcome == "PASS":
        release["status"] = "VALIDATED"
        release["safety_check_passed"] = True
    else:
        defect_notes = body.get("defect_notes")
        if not isinstance(defect_notes, str) or defect_notes == "":
            raise errors.validation("defect_notes required when outcome is FAIL")
        release["status"] = "FAILED"
        release["safety_check_passed"] = False
        release["defect_notes"] = defect_notes
    bump(release)
    return success_object(entity_out(release))


@bp.route("/software-releases/<release_id>/revise", methods=["POST"])
def revise_release(release_id):
    require_roles({"ReleaseEngineer"})
    release = get_or_404(store.software_releases, release_id, "software release")
    if release["status"] != "FAILED":
        raise errors.invalid_state("release is not FAILED")
    release["status"] = "DRAFT"
    bump(release)
    return success_object(entity_out(release))


@bp.route("/software-releases/<release_id>/promote", methods=["POST"])
def promote_release(release_id):
    require_roles({"FleetAdmin"})
    release = get_or_404(store.software_releases, release_id, "software release")
    if release["status"] != "VALIDATED":
        raise errors.invalid_state("release is not VALIDATED")
    if not release.get("safety_check_passed"):
        raise errors.safety_interlock("safety check not passed")
    for e in store.floor_exceptions.values():
        if e["status"] in {"OPEN", "TRIAGED_HUMAN"}:
            raise errors.safety_interlock("floor exception gating promotion")
    for u in store.drive_units.values():
        if u["status"] == "STRANDED":
            raise errors.safety_interlock("stranded drive unit on the floor")
    previous_live = None
    for r in store.software_releases.values():
        if r["id"] != release_id and r["status"] == "FLOOR_LIVE":
            previous_live = r
            break
    if previous_live is not None:
        previous_live["status"] = "ROLLED_BACK"
        bump(previous_live)
    release["status"] = "FLOOR_LIVE"
    release["_previous_live_id"] = previous_live["id"] if previous_live else None
    bump(release)
    for unit in store.drive_units.values():
        unit["firmware_release_id"] = release["id"]
        bump(unit)
    return success_object(entity_out(release))


@bp.route("/software-releases/<release_id>/rollback", methods=["POST"])
def rollback_release(release_id):
    require_roles({"FleetAdmin"})
    release = get_or_404(store.software_releases, release_id, "software release")
    if release["status"] != "FLOOR_LIVE":
        raise errors.invalid_state("release is not FLOOR_LIVE")
    previous_live_id = release.get("_previous_live_id")
    release["status"] = "ROLLED_BACK"
    bump(release)
    if previous_live_id is not None:
        previous = store.software_releases.get(previous_live_id)
        if previous is not None:
            for unit in store.drive_units.values():
                unit["firmware_release_id"] = previous["id"]
                bump(unit)
    return success_object(entity_out(release))
