"""PlacementPermit endpoints."""
from flask import Blueprint, g

from auth import ALL_ROLES, endpoint
import clock
import constants as C
from db import db, insert, serialize, touch
from errors import fail
from responses import created, ok
from routes.common import resolve
import services
import validation as V

bp = Blueprint("permits", __name__)


@bp.post("/placement-permits")
@endpoint(["PermitCoordinator"])
def create_permit():
    body = V.body()
    site_id = V.str_field(body, "site_id", 1)
    permit_kind = V.enum_field(body, "permit_kind", C.PERMIT_KINDS)
    authority_ref = V.str_field(body, "authority_ref", 1, 64)
    effective_from = V.date_field(body, "effective_from")
    effective_to = V.date_field(body, "effective_to")
    V.ordering(effective_from, effective_to, "effective_from", "effective_to")

    site = resolve("service_sites", site_id)

    row = insert("placement_permits", {
        "site_id": site["id"],
        "permit_kind": permit_kind,
        "authority_ref": authority_ref,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "DRAFT",
        "revision_round": 0,
        "rejection_reason": None,
        "submitted_by_user_id": None,
    })
    services.recompute_site_posture(site)
    return created(serialize(row))


@bp.get("/placement-permits/<permit_id>")
@endpoint(ALL_ROLES)
def read_permit(permit_id):
    permit = resolve("placement_permits", permit_id)
    return ok(serialize(permit))


@bp.post("/placement-permits/<permit_id>/submit")
@endpoint(["PermitCoordinator"])
def submit_permit(permit_id):
    body = V.body()
    V.str_field(body, "submission_note", 1, None, required=False)
    permit = resolve("placement_permits", permit_id)

    if permit["status"] not in ("DRAFT", "REJECTED"):
        fail("ERR_INVALID_STATE_TRANSITION")
    if (permit["status"] == "REJECTED"
            and permit["revision_round"] >= C.PERMIT_MAX_REVISION_ROUNDS):
        fail("ERR_PERMIT_REVISION_LIMIT")

    permit["status"] = "SUBMITTED"
    permit["revision_round"] += 1
    permit["submitted_by_user_id"] = g.user_id
    touch(permit)

    site = db.service_sites.get(permit["site_id"])
    if site is not None:
        services.recompute_site_posture(site)
    return ok(serialize(permit))


@bp.post("/placement-permits/<permit_id>/approve")
@endpoint(["ComplianceOfficer"])
def approve_permit(permit_id):
    body = V.body()
    V.str_field(body, "authority_decision_ref", 1)
    permit = resolve("placement_permits", permit_id)

    if permit["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE_TRANSITION")
    if clock.today() > permit["effective_to"]:
        fail("ERR_INVALID_STATE_TRANSITION",
             "The permit validity window has already elapsed.")

    permit["status"] = "APPROVED"
    touch(permit)

    site = db.service_sites.get(permit["site_id"])
    if site is not None:
        # Resumption is never automatic: SUSPENDED schedules are left untouched.
        services.recompute_site_posture(site)
    return ok(serialize(permit))


@bp.post("/placement-permits/<permit_id>/reject")
@endpoint(["ComplianceOfficer"])
def reject_permit(permit_id):
    body = V.body()
    V.str_field(body, "authority_decision_ref", 1)
    rejection_reason = V.str_field(body, "rejection_reason", 1)
    permit = resolve("placement_permits", permit_id)

    if permit["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE_TRANSITION")

    permit["status"] = "REJECTED"
    permit["rejection_reason"] = rejection_reason
    touch(permit)

    site = db.service_sites.get(permit["site_id"])
    if site is not None:
        services.recompute_site_posture(site)
    return ok(serialize(permit))
