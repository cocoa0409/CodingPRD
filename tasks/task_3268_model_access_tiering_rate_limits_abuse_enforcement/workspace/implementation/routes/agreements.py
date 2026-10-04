"""Enterprise agreement routes."""
from __future__ import annotations

import db
from errors import (agreement_conflict, invalid_request, invalid_state,
                    not_found)
from middleware import require_roles, pagination_params, paginate
from response import success
from services.util import (body, require_datetime, require_int, require_str,
                           simple_view, sort_by_created, stamp_new, touch)

from flask import Blueprint, request

bp = Blueprint("agreements", __name__)

PRICING_KEYS = ("input_per_mtok_cents", "output_per_mtok_cents", "cached_per_mtok_cents")


def _validate_price_override(data):
    po = data.get("price_override")
    if po is None:
        return None
    if not isinstance(po, dict):
        raise invalid_request("price_override must be an object")
    out = {}
    for k in PRICING_KEYS:
        v = po.get(k)
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise invalid_request(f"price_override.{k} must be a non-negative integer")
        out[k] = v
    return out


@bp.post("/enterprise-agreements")
def create_agreement():
    require_roles("PlatformAdmin")
    data = body()
    org_id = require_str(data, "organization_id")
    committed_tpm = require_int(data, "committed_tpm", minimum=1)
    dedicated = require_int(data, "dedicated_capacity_pct", minimum=1, maximum=100)
    effective_at = require_datetime(data, "effective_at")
    expires_at = require_datetime(data, "expires_at")
    price_override = _validate_price_override(data)

    org = db.organizations.get(org_id)
    if org is None:
        raise not_found("organization not found")

    if effective_at >= expires_at:
        raise agreement_conflict("effective_at must be strictly before expires_at")
    for a in db.enterprise_agreements.values():
        if a["organization_id"] == org_id and a["status"] == "ACTIVE":
            raise agreement_conflict("organization already has an ACTIVE agreement")

    agr = {
        "organization_id": org_id,
        "status": "DRAFT",
        "committed_tpm": committed_tpm,
        "dedicated_capacity_pct": dedicated,
        "effective_at": db.fmt_clock(effective_at),
        "expires_at": db.fmt_clock(expires_at),
        "price_override": price_override,
    }
    stamp_new(agr, common=True)
    db.enterprise_agreements[agr["id"]] = agr
    return success(simple_view(agr), status=201)


@bp.get("/enterprise-agreements")
def list_agreements():
    require_roles("PlatformAdmin", "BillingContact", "OrganizationAdmin")
    limit, offset = pagination_params()
    items = list(db.enterprise_agreements.values())
    org_f = request.args.get("organization_id")
    status_f = request.args.get("status")
    if org_f is not None:
        items = [a for a in items if a["organization_id"] == org_f]
    if status_f is not None:
        items = [a for a in items if a["status"] == status_f]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([simple_view(a) for a in page], response_type="array", pagination=meta)


@bp.get("/enterprise-agreements/<agr_id>")
def get_agreement(agr_id):
    require_roles("PlatformAdmin", "BillingContact", "OrganizationAdmin", "TrustLead")
    agr = db.enterprise_agreements.get(agr_id)
    if agr is None:
        raise not_found("agreement not found")
    return success(simple_view(agr))


@bp.post("/enterprise-agreements/<agr_id>/countersign")
def countersign(agr_id):
    require_roles("PlatformAdmin")
    agr = db.enterprise_agreements.get(agr_id)
    if agr is None:
        raise not_found("agreement not found")
    if agr["status"] != "DRAFT":
        raise invalid_state("agreement is not DRAFT")
    org = db.organizations.get(agr["organization_id"])
    if org is None:
        raise not_found("organization not found")
    if org["status"] != "ACTIVE":
        raise invalid_state("organization is not ACTIVE")
    now = db.now()
    if not (db.parse_iso(agr["effective_at"]) <= now < db.parse_iso(agr["expires_at"])):
        raise invalid_state("current time is outside the agreement's effective window")
    for a in db.enterprise_agreements.values():
        if (a["organization_id"] == agr["organization_id"]
                and a["status"] == "ACTIVE" and a["id"] != agr["id"]):
            raise agreement_conflict("organization already has an ACTIVE agreement")
    agr["status"] = "ACTIVE"
    touch(agr)
    org["enterprise_agreement_id"] = agr["id"]
    org["tier"] = "ENTERPRISE"
    touch(org)
    return success(simple_view(agr))
