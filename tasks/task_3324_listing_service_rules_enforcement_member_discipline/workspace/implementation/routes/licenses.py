"""Data license endpoints: create/list/get/activate/sync-feed/audit-feed/
cure/terminate + flat read."""

from datetime import timedelta

from flask import Blueprint, request

import calcs
import services
from auth import require_roles
from db import store, now, _parse_iso
from errors import (raise_err, ERR_INVALID_REQUEST, ERR_DUPLICATE_RESOURCE,
                    ERR_INVALID_STATE, ERR_RULESET_MISMATCH,
                    ERR_CURE_WINDOW_CLOSED)
from helpers import (body, mint_common, touch, now_iso_str, get_association,
                     get_license, page)
from response import success_object, success_list
from routes.members import check_not_merged

bp = Blueprint("licenses", __name__)

SCOPES = ("IDX", "VOW", "BACKOFFICE")
CURE_WINDOW_DAYS = 30


@bp.route("/mls/associations/<assoc_id>/data-licenses", methods=["POST"])
def create_license(assoc_id):
    require_roles("AssociationStaff")
    assoc = get_association(assoc_id)
    check_not_merged(assoc)
    data = body()
    for f in ("licensee_name", "scope", "display_ruleset_version",
              "listing_field_allowlist"):
        if data.get(f) is None:
            raise_err(ERR_INVALID_REQUEST, "Missing required field '%s'" % f)
    if data["scope"] not in SCOPES:
        raise_err(ERR_INVALID_REQUEST, "scope must be one of %s"
                  % ", ".join(SCOPES))
    rsv = data["display_ruleset_version"]
    if isinstance(rsv, bool) or not isinstance(rsv, int) or rsv < 0:
        raise_err(ERR_INVALID_REQUEST,
                  "display_ruleset_version must be an integer >= 0")
    if not isinstance(data["listing_field_allowlist"], list):
        raise_err(ERR_INVALID_REQUEST,
                  "listing_field_allowlist must be an array")
    for lic in store.data_licenses.values():
        if lic["association_id"] == assoc_id \
           and lic["licensee_name"] == data["licensee_name"]:
            raise_err(ERR_DUPLICATE_RESOURCE,
                      "licensee_name '%s' already exists in this association"
                      % data["licensee_name"])
    lic = {
        "association_id": assoc_id,
        "licensee_name": data["licensee_name"],
        "scope": data["scope"],
        "display_ruleset_version": rsv,
        "listing_field_allowlist": list(data["listing_field_allowlist"]),
        "status": "PENDING",
        "feed_sync_state": "STALE",
        "last_audit_at": None,
    }
    mint_common(lic)
    store.data_licenses[lic["id"]] = lic
    return success_object(lic, 201)


@bp.route("/mls/associations/<assoc_id>/data-licenses", methods=["GET"])
def list_licenses(assoc_id):
    require_roles("AssociationStaff")
    get_association(assoc_id)
    items = [l for l in store.data_licenses.values()
             if l["association_id"] == assoc_id]
    status = request.args.get("status")
    if status is not None:
        items = [l for l in items if l["status"] == status]
    scope = request.args.get("scope")
    if scope is not None:
        items = [l for l in items if l["scope"] == scope]
    items, limit, offset, total = page(items)
    return success_list(items, limit, offset, total)


@bp.route("/mls/associations/<assoc_id>/data-licenses/<license_id>",
          methods=["GET"])
def get_license_route(assoc_id, license_id):
    require_roles("AssociationStaff")
    get_association(assoc_id)
    return success_object(get_license(license_id, assoc_id))


@bp.route("/mls/data-licenses/<license_id>", methods=["GET"])
def flat_get_license(license_id):
    require_roles("AssociationStaff")
    return success_object(get_license(license_id))


@bp.route("/mls/associations/<assoc_id>/data-licenses/<license_id>/activate",
          methods=["POST"])
def activate_license(assoc_id, license_id):
    require_roles("AssociationStaff")
    assoc = get_association(assoc_id)
    lic = get_license(license_id, assoc_id)
    check_not_merged(assoc)
    if lic["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, "Only a PENDING license may be activated")
    if lic["display_ruleset_version"] != calcs.ruleset_version(assoc_id):
        raise_err(ERR_RULESET_MISMATCH,
                  "License display_ruleset_version != association ruleset_version")
    lic["status"] = "ACTIVE"
    lic["feed_sync_state"] = "STALE"
    touch(lic)
    return success_object(lic)


@bp.route("/mls/associations/<assoc_id>/data-licenses/<license_id>/sync-feed",
          methods=["POST"])
def sync_feed(assoc_id, license_id):
    require_roles("AssociationStaff")
    assoc = get_association(assoc_id)
    lic = get_license(license_id, assoc_id)
    check_not_merged(assoc)
    if lic["status"] not in ("ACTIVE",):
        raise_err(ERR_INVALID_STATE, "Only an ACTIVE license may sync its feed")
    rows, count, stripped = calcs.project_feed(lic)
    lic["feed_sync_state"] = "CURRENT"
    lic["last_synced_listing_count"] = count
    touch(lic)
    return success_object({
        "projected_listing_count": count,
        "comp_fields_stripped": stripped,
        "feed_sync_state": lic["feed_sync_state"],
        "listings": rows,
    })


@bp.route("/mls/associations/<assoc_id>/data-licenses/<license_id>/audit-feed",
          methods=["POST"])
def audit_feed(assoc_id, license_id):
    require_roles("AssociationStaff")
    assoc = get_association(assoc_id)
    lic = get_license(license_id, assoc_id)
    check_not_merged(assoc)
    if lic["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Only an ACTIVE license may be audited")
    lic["last_audit_at"] = now_iso_str()
    violation = not calcs.license_is_compliant(lic)
    auto_citation_id = None
    if violation:
        lic["status"] = "SUSPENDED"
        # Deterministic cited member: broker of the office owning the
        # most-recently-activated ACTIVE listing of the association
        # (tie-break created_at ASC).
        office_ids = {o["id"]: o for o in store.offices.values()
                      if o["association_id"] == assoc_id}
        actives = [l for l in store.listings.values()
                   if l["office_id"] in office_ids and l["status"] == "ACTIVE"
                   and l.get("activated_at")]
        target_member_id = None
        if actives:
            actives.sort(key=lambda l: (l["activated_at"],),
                         reverse=True)
            best_act = actives[0]["activated_at"]
            tied = [l for l in actives if l["activated_at"] == best_act]
            tied.sort(key=lambda l: l["created_at"])
            office = office_ids[tied[0]["office_id"]]
            target_member_id = office["broker_member_id"]
        else:
            # No ACTIVE listing: fall back to the broker of the earliest
            # office of the association (deterministic).
            offices = sorted(office_ids.values(),
                             key=lambda o: (o["created_at"], o["id"]))
            if offices:
                target_member_id = offices[0]["broker_member_id"]
        if target_member_id is not None:
            cit = services.create_citation(assoc_id, target_member_id,
                                           "FEED_ABUSE", "STAFF")
            auto_citation_id = cit["id"]
    touch(lic)
    return success_object({
        "violation_found": violation,
        "auto_citation_id": auto_citation_id,
    })


@bp.route("/mls/associations/<assoc_id>/data-licenses/<license_id>/cure",
          methods=["POST"])
def cure_license(assoc_id, license_id):
    require_roles("AssociationStaff")
    assoc = get_association(assoc_id)
    lic = get_license(license_id, assoc_id)
    check_not_merged(assoc)
    if lic["status"] != "SUSPENDED":
        raise_err(ERR_INVALID_STATE, "Only a SUSPENDED license may be cured")
    if lic.get("last_audit_at") is None:
        raise_err(ERR_INVALID_STATE, "License has no audit to cure")
    if now() > _parse_iso(lic["last_audit_at"]) + timedelta(days=CURE_WINDOW_DAYS):
        raise_err(ERR_CURE_WINDOW_CLOSED,
                  "Cure submitted after audit + 30 days")
    # The cure request logically re-runs the compliance check; it must pass.
    if not calcs.license_is_compliant(lic):
        raise_err(ERR_RULESET_MISMATCH,
                  "Compliance check still failing; cure rejected")
    lic["status"] = "ACTIVE"
    lic["feed_sync_state"] = "STALE"
    touch(lic)
    return success_object(lic)


@bp.route("/mls/associations/<assoc_id>/data-licenses/<license_id>/terminate",
          methods=["POST"])
def terminate_license(assoc_id, license_id):
    require_roles("AssociationStaff")
    assoc = get_association(assoc_id)
    lic = get_license(license_id, assoc_id)
    check_not_merged(assoc)
    if lic["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Only an ACTIVE license may be terminated")
    lic["status"] = "TERMINATED"
    touch(lic)
    return success_object(lic)
