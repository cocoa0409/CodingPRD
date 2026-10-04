"""Policy revision endpoints: schedule/list/get + flat list/read."""

from flask import Blueprint, request

from db import store
from auth import require_roles
from errors import (raise_err, ERR_INVALID_REQUEST, ERR_DUPLICATE_RESOURCE,
                    ERR_STALE_VERSION)
from helpers import (body, mint_common, touch, get_association,
                     get_policy_revision, page, parse_dt)
from response import success_object, success_list
from routes.members import check_not_merged

bp = Blueprint("policy", __name__)

COMP_MODES = ("COMP_DISPLAY_ON", "COMP_DISPLAY_OFF")


@bp.route("/mls/associations/<assoc_id>/policy-revisions", methods=["POST"])
def create_revision(assoc_id):
    require_roles("AssociationStaff")
    assoc = get_association(assoc_id)
    check_not_merged(assoc)
    data = body()
    for f in ("revision_code", "effective_at", "comp_display_mode",
              "expected_association_version"):
        if data.get(f) is None:
            raise_err(ERR_INVALID_REQUEST, "Missing required field '%s'" % f)
    if data["comp_display_mode"] not in COMP_MODES:
        raise_err(ERR_INVALID_REQUEST, "comp_display_mode must be one of %s"
                  % ", ".join(COMP_MODES))
    parse_dt(data["effective_at"], "effective_at")
    expected = data["expected_association_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_err(ERR_INVALID_REQUEST,
                  "expected_association_version must be an integer")
    if expected != assoc["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_association_version does not match current version")
    for r in store.policy_revisions.values():
        if r["association_id"] == assoc_id \
           and r["revision_code"] == data["revision_code"]:
            raise_err(ERR_DUPLICATE_RESOURCE,
                      "revision_code '%s' already exists in this association"
                      % data["revision_code"])
    rev = {
        "association_id": assoc_id,
        "revision_code": data["revision_code"],
        "effective_at": data["effective_at"],
        "comp_display_mode": data["comp_display_mode"],
        "status": "SCHEDULED",
    }
    mint_common(rev)
    store.policy_revisions[rev["id"]] = rev
    # Scheduling a revision increments the parent association's version.
    touch(assoc)
    # If effective_at is already at/before the current clock, activate now.
    from db import now, _parse_iso
    if _parse_iso(rev["effective_at"]) <= now():
        import services
        services.activate_policy_revision(rev)
    return success_object(rev, 201)


@bp.route("/mls/associations/<assoc_id>/policy-revisions", methods=["GET"])
def list_revisions(assoc_id):
    require_roles("AssociationStaff", "Member")
    get_association(assoc_id)
    items = [r for r in store.policy_revisions.values()
             if r["association_id"] == assoc_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items, limit, offset, total = page(items)
    return success_list(items, limit, offset, total)


@bp.route("/mls/associations/<assoc_id>/policy-revisions/<revision_id>",
          methods=["GET"])
def get_revision_route(assoc_id, revision_id):
    require_roles("AssociationStaff", "Member")
    get_association(assoc_id)
    return success_object(get_policy_revision(revision_id, assoc_id))


@bp.route("/mls/policy-revisions", methods=["GET"])
def flat_list_revisions():
    require_roles("AssociationStaff", "Member")
    items = list(store.policy_revisions.values())
    assoc_id = request.args.get("association_id")
    if assoc_id is not None:
        items = [r for r in items if r["association_id"] == assoc_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items, limit, offset, total = page(items)
    return success_list(items, limit, offset, total)


@bp.route("/mls/policy-revisions/<revision_id>", methods=["GET"])
def flat_get_revision(revision_id):
    require_roles("AssociationStaff", "Member")
    return success_object(get_policy_revision(revision_id))
