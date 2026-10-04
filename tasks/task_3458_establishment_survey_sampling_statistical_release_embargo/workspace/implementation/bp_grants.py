"""/survey/embargo-grants: list, read, bulletin, report-breach (PRD 3.9)."""
from flask import Blueprint, request

from authz import get_auth, require_role, require_ownership
from envelope import ok, ok_list, paginate
from errors import (
    raise_err, ERR_GRANT_NOT_FOUND, ERR_OUTLET_NOT_FOUND, ERR_INVALID_STATE,
    ERR_EMBARGO_NOT_OPEN,
)
from releases_util import revoke_grants, recompute_grant_count
from store import (
    DB, sorted_entities, touch, now, serialize,
    ACTIVE_GRANT_STATUSES, INDUSTRIES, SIZE_CLASSES,
)

bp = Blueprint("grants", __name__)


@bp.get("/embargo-grants")
def list_grants():
    get_auth()
    items = sorted_entities("grants")
    for param in ("release_event_id", "media_outlet_id", "grant_status"):
        value = request.args.get(param)
        if value is not None:
            items = [g for g in items if g[param] == value]
    page, pagination = paginate(items)
    return ok_list(page, pagination)


def _load_grant(gid):
    grant = DB["grants"].get(gid)
    if grant is None:
        raise_err(ERR_GRANT_NOT_FOUND, "embargo grant not found")
    return grant


@bp.get("/embargo-grants/<gid>")
def get_grant(gid):
    get_auth()
    return ok(_load_grant(gid))


def _bulletin_payload(release):
    cycle = DB["cycles"].get(release["cycle_id"])
    cells = [
        c for c in DB["cells"].values() if c["cycle_id"] == release["cycle_id"]
    ]
    cells.sort(key=lambda c: (INDUSTRIES.index(c["industry_code"]),
                              SIZE_CLASSES.index(c["size_class"])))

    masked_cells = []
    for c in cells:
        view = serialize(c)
        if c["suppression_status"] in ("PRIMARY", "COMPLEMENTARY"):
            # Masking nulls the estimate and both seasonally adjusted values;
            # totals still reflect the full cell set.
            view["employment_estimate"] = None
            view["seasonally_adjusted_concurrent"] = None
            view["seasonally_adjusted_revised"] = None
        masked_cells.append(view)

    industry_totals = []
    for ind in INDUSTRIES:
        group = [c for c in cells if c["industry_code"] == ind]
        if group:
            industry_totals.append({
                "industry_code": ind,
                "employment_total": sum(c["employment_estimate"] for c in group),
            })
    size_totals = []
    for size in SIZE_CLASSES:
        group = [c for c in cells if c["size_class"] == size]
        if group:
            size_totals.append({
                "size_class": size,
                "employment_total": sum(c["employment_estimate"] for c in group),
            })

    return {
        "release_event_id": release["id"],
        "reference_month": cycle["reference_month"] if cycle else None,
        "release_status": release["pub_status"],
        "embargoed": now() < release["release_at"],
        "cells": masked_cells,
        "industry_totals": industry_totals,
        "size_totals": size_totals,
    }


@bp.get("/embargo-grants/<gid>/bulletin")
def read_bulletin(gid):
    user, role = get_auth()
    require_role(role, {"AccreditedMedia"})
    grant = _load_grant(gid)
    require_ownership(user, grant["media_outlet_id"], "grant")
    if grant["grant_status"] not in ACTIVE_GRANT_STATUSES:
        raise_err(ERR_INVALID_STATE,
                  f"cannot read a bulletin on a grant in {grant['grant_status']}")
    release = DB["releases"].get(grant["release_event_id"])
    if now() < release["embargo_open_at"]:
        raise_err(ERR_EMBARGO_NOT_OPEN, "the embargo window has not opened yet")

    if grant["grant_status"] == "ISSUED":
        grant["grant_status"] = "ACCESSED"
        grant["first_accessed_at"] = now()
        touch(grant)
    return ok(_bulletin_payload(release))


@bp.post("/embargo-grants/<gid>/report-breach")
def report_breach(gid):
    _user, role = get_auth()
    require_role(role, {"ReleaseManager"})
    grant = _load_grant(gid)
    if grant["grant_status"] not in ACTIVE_GRANT_STATUSES:
        raise_err(ERR_INVALID_STATE,
                  f"cannot report a breach on a grant in {grant['grant_status']}")

    grant["grant_status"] = "BREACHED"
    touch(grant)

    # Breach cascade: outlet ACCREDITED -> SUSPENDED; the outlet's OTHER live
    # grants -> REVOKED; every affected release's counter recomputed.
    outlet = DB["outlets"].get(grant["media_outlet_id"])
    if outlet is None:
        raise_err(ERR_OUTLET_NOT_FOUND, "media outlet not found")
    if outlet["accreditation_status"] == "ACCREDITED":
        outlet["accreditation_status"] = "SUSPENDED"
        touch(outlet)
    revoke_grants([
        g for g in DB["grants"].values()
        if g["media_outlet_id"] == outlet["id"] and g["id"] != grant["id"]
    ])
    release = DB["releases"].get(grant["release_event_id"])
    if release is not None:
        recompute_grant_count(release)
    return ok(grant)
