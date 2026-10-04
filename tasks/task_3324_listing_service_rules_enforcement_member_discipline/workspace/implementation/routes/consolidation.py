"""Consolidation endpoints: schedule/list/get/execute/cancel + flat routes,
plus the compliance checkpoint."""

from flask import Blueprint, request

import services
from auth import require_roles
from db import store, now, _parse_iso
from errors import (raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_ASSOCIATION_MERGED, ERR_CONSOLIDATION_NOT_DUE,
                    ERR_CROSS_ASSOCIATION_REFERENCE)
from helpers import (body, mint_consolidation, touch, get_association,
                     get_consolidation, page, parse_dt)
from response import success_object, success_list
from routes.members import check_not_merged

bp = Blueprint("consolidation", __name__)


@bp.route("/mls/associations/<assoc_id>/consolidations", methods=["POST"])
def schedule_consolidation(assoc_id):
    require_roles("AssociationStaff")
    survivor = get_association(assoc_id)
    check_not_merged(survivor)
    data = body()
    for f in ("absorbed_association_id", "effective_at"):
        if data.get(f) is None:
            raise_err(ERR_INVALID_REQUEST, "Missing required field '%s'" % f)
    absorbed_id = data["absorbed_association_id"]
    if absorbed_id == assoc_id:
        raise_err(ERR_INVALID_REQUEST,
                  "absorbed_association_id must differ from the survivor")
    effective_at = parse_dt(data["effective_at"], "effective_at")
    absorbed = store.associations.get(absorbed_id)
    if absorbed is None:
        raise_err(ERR_CROSS_ASSOCIATION_REFERENCE,
                  "absorbed_association_id does not reference an association")
    if absorbed["consolidation_state"] in ("MERGING", "MERGED"):
        raise_err(ERR_ASSOCIATION_MERGED,
                  "Absorbed association is MERGING or MERGED")
    if effective_at <= now():
        raise_err(ERR_INVALID_REQUEST,
                  "effective_at must be a future instant")
    event = {
        "survivor_association_id": assoc_id,
        "absorbed_association_id": absorbed_id,
        "effective_at": data["effective_at"],
        "status": "SCHEDULED",
    }
    mint_consolidation(event)
    store.consolidation_events[event["id"]] = event
    absorbed["consolidation_state"] = "MERGING"
    touch(absorbed)
    return success_object(event, 201)


@bp.route("/mls/associations/<assoc_id>/consolidations", methods=["GET"])
def list_consolidations(assoc_id):
    require_roles("AssociationStaff")
    get_association(assoc_id)
    items = [e for e in store.consolidation_events.values()
             if e["survivor_association_id"] == assoc_id
             or e["absorbed_association_id"] == assoc_id]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    surv = request.args.get("survivor_association_id")
    if surv is not None:
        items = [e for e in items if e["survivor_association_id"] == surv]
    abso = request.args.get("absorbed_association_id")
    if abso is not None:
        items = [e for e in items if e["absorbed_association_id"] == abso]
    items, limit, offset, total = page(items)
    return success_list(items, limit, offset, total)


@bp.route("/mls/consolidations", methods=["GET"])
def flat_list_consolidations():
    require_roles("AssociationStaff")
    items = list(store.consolidation_events.values())
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    surv = request.args.get("survivor_association_id")
    if surv is not None:
        items = [e for e in items if e["survivor_association_id"] == surv]
    abso = request.args.get("absorbed_association_id")
    if abso is not None:
        items = [e for e in items if e["absorbed_association_id"] == abso]
    items, limit, offset, total = page(items)
    return success_list(items, limit, offset, total)


@bp.route("/mls/consolidations/<event_id>", methods=["GET"])
def flat_get_consolidation(event_id):
    require_roles("AssociationStaff")
    return success_object(get_consolidation(event_id))


@bp.route("/mls/associations/<assoc_id>/consolidations/<event_id>/execute",
          methods=["POST"])
def execute_consolidation(assoc_id, event_id):
    require_roles("AssociationStaff")
    survivor = get_association(assoc_id)
    event = get_consolidation(event_id)
    if event["survivor_association_id"] != assoc_id:
        from errors import ERR_NOT_FOUND
        raise_err(ERR_NOT_FOUND, "ConsolidationEvent not found under this association")
    check_not_merged(survivor)
    if event["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "Only a SCHEDULED consolidation may be executed")
    if now() < _parse_iso(event["effective_at"]):
        raise_err(ERR_CONSOLIDATION_NOT_DUE,
                  "Execute before effective_at is not permitted")
    absorbed = store.associations[event["absorbed_association_id"]]
    if absorbed["consolidation_state"] != "MERGING":
        raise_err(ERR_INVALID_STATE,
                  "Absorbed association must be in MERGING state")

    event["status"] = "EXECUTED"
    absorbed["consolidation_state"] = "MERGED"
    absorbed["consolidated_into_id"] = assoc_id
    touch(absorbed)

    # Re-point every member of the absorbed association to the survivor.
    for member in store.members.values():
        if member["association_id"] == absorbed["id"]:
            member["association_id"] = assoc_id
            touch(member)
    # Terminate every ACTIVE data license of the absorbed association.
    for lic in store.data_licenses.values():
        if lic["association_id"] == absorbed["id"] and lic["status"] == "ACTIVE":
            lic["status"] = "TERMINATED"
            touch(lic)
    # Dues periods: BILLED -> RECONCILED; OPEN stays OPEN (frozen).
    for period in store.dues_periods.values():
        if period["association_id"] == absorbed["id"]:
            if period["status"] == "BILLED":
                period["status"] = "RECONCILED"
                touch(period)
    return success_object(event)


@bp.route("/mls/associations/<assoc_id>/consolidations/<event_id>/cancel",
          methods=["POST"])
def cancel_consolidation(assoc_id, event_id):
    require_roles("AssociationStaff")
    survivor = get_association(assoc_id)
    event = get_consolidation(event_id)
    if event["survivor_association_id"] != assoc_id:
        from errors import ERR_NOT_FOUND
        raise_err(ERR_NOT_FOUND, "ConsolidationEvent not found under this association")
    check_not_merged(survivor)
    if event["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "Only a SCHEDULED consolidation may be cancelled")
    if now() >= _parse_iso(event["effective_at"]):
        raise_err(ERR_CONSOLIDATION_NOT_DUE,
                  "Cancellation is permitted only before effective_at")
    event["status"] = "CANCELLED"
    absorbed = store.associations[event["absorbed_association_id"]]
    if absorbed["consolidation_state"] == "MERGING":
        absorbed["consolidation_state"] = "ACTIVE"
        touch(absorbed)
    return success_object(event)


@bp.route("/mls/associations/<assoc_id>/run-compliance-checkpoint",
          methods=["POST"])
def run_checkpoint(assoc_id):
    require_roles("AssociationStaff")
    assoc = get_association(assoc_id)
    check_not_merged(assoc)
    # Expire only listings whose office belongs to THIS association.
    office_ids = {o["id"] for o in store.offices.values()
                  if o["association_id"] == assoc_id}
    from datetime import timedelta
    from helpers import now_iso_str
    current = now()
    count = 0
    for listing in list(store.listings.values()):
        if listing["office_id"] not in office_ids:
            continue
        if listing["status"] != "ACTIVE" or not listing.get("activated_at"):
            continue
        if current - _parse_iso(listing["activated_at"]) > timedelta(days=365):
            services.record_status_change(listing, "ACTIVE", "EXPIRED",
                                          business_effective_at=now_iso_str(),
                                          audit=False)
            listing["status"] = "EXPIRED"
            listing["status_changed_at"] = now_iso_str()
            touch(listing)
            count += 1
    return success_object({"expired_listing_count": count})
