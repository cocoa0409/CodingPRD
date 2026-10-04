"""Organization routes."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import invalid_request, invalid_state, not_found
from middleware import require_roles, pagination_params, paginate
from response import success
from services.domain import recompute_tier
from services.util import (body, org_view, require_str, simple_view,
                           sort_by_created, stamp_new, touch)

bp = Blueprint("organizations", __name__)

READ_ROLES = ("PlatformAdmin", "TrustAnalyst", "TrustLead", "BillingContact", "OrganizationAdmin")


@bp.post("/organizations")
def create_organization():
    require_roles("PlatformAdmin")
    data = body()
    legal_name = require_str(data, "legal_name")
    pinned = data.get("pinned_model_version_id")
    if pinned is not None:
        if not isinstance(pinned, str) or not pinned:
            raise invalid_request("pinned_model_version_id must be a string")
        mv = db.model_versions.get(pinned)
        if mv is None:
            raise not_found("pinned model version does not exist")
        if mv["status"] not in ("ACTIVE", "DEPRECATED"):
            raise invalid_request("pinned model version must be ACTIVE or DEPRECATED")
    org = {
        "legal_name": legal_name,
        "tier": "TIER_1",
        "status": "PROVISIONAL",
        "lifetime_spend_cents": 0,
        "qualifying_payment_count": 0,
        "pinned_model_version_id": pinned,
        "enterprise_agreement_id": None,
        "credit_balance_cents": 0,
    }
    stamp_new(org, common=True)
    db.organizations[org["id"]] = org
    return success(org_view(org), status=201)


@bp.get("/organizations")
def list_organizations():
    user_id, role = require_roles(*READ_ROLES)
    limit, offset = pagination_params()
    items = list(db.organizations.values())
    status_f = request.args.get("status")
    tier_f = request.args.get("tier")
    pin_f = request.args.get("pinned_model_version_id")
    agr_f = request.args.get("enterprise_agreement_id")
    if status_f is not None:
        items = [o for o in items if o["status"] == status_f]
    if tier_f is not None:
        items = [o for o in items if o["tier"] == tier_f]
    if pin_f is not None:
        items = [o for o in items if o.get("pinned_model_version_id") == pin_f]
    if agr_f is not None:
        items = [o for o in items if o.get("enterprise_agreement_id") == agr_f]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([org_view(o) for o in page], response_type="array", pagination=meta)


def _get_org_or_404(org_id: str) -> dict:
    org = db.organizations.get(org_id)
    if org is None:
        raise not_found("organization not found")
    return org


@bp.get("/organizations/<org_id>")
def get_organization(org_id):
    require_roles(*READ_ROLES)
    org = _get_org_or_404(org_id)
    preview = request.args.get("preview", "").lower() in ("true", "1", "yes")
    return success(org_view(org, preview=preview))


@bp.post("/organizations/<org_id>/activate")
def activate_organization(org_id):
    require_roles("PlatformAdmin")
    org = _get_org_or_404(org_id)
    if org["status"] != "PROVISIONAL":
        raise invalid_state("organization is not PROVISIONAL")
    has_settled = any(
        p["organization_id"] == org_id and p["status"] == "SETTLED"
        for p in db.payment_events.values()
    )
    if not has_settled:
        raise invalid_state("activation requires at least one settled payment")
    org["status"] = "ACTIVE"
    recompute_tier(org)
    touch(org)
    return success(org_view(org))


# --- reverse-reachability list endpoints under /organizations/{id}/... ---

@bp.get("/organizations/<org_id>/payment-events")
def list_org_payment_events(org_id):
    require_roles("PlatformAdmin", "BillingContact", "OrganizationAdmin")
    _get_org_or_404(org_id)
    limit, offset = pagination_params()
    items = [p for p in db.payment_events.values() if p["organization_id"] == org_id]
    status_f = request.args.get("status")
    kind_f = request.args.get("kind")
    if status_f is not None:
        items = [p for p in items if p["status"] == status_f]
    if kind_f is not None:
        items = [p for p in items if p["kind"] == kind_f]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([simple_view(p) for p in page], response_type="array", pagination=meta)


@bp.get("/organizations/<org_id>/usage-records")
def list_org_usage_records(org_id):
    require_roles("PlatformAdmin", "BillingContact", "OrganizationAdmin")
    _get_org_or_404(org_id)
    limit, offset = pagination_params()
    items = [u for u in db.usage_records.values() if u["organization_id"] == org_id]
    mv_f = request.args.get("model_version_id")
    batch_f = request.args.get("batch")
    if mv_f is not None:
        items = [u for u in items if u["model_version_id"] == mv_f]
    if batch_f is not None:
        val = batch_f.lower() in ("true", "1", "yes")
        items = [u for u in items if bool(u.get("batch")) == val]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([simple_view(u) for u in page], response_type="array", pagination=meta)


@bp.get("/organizations/<org_id>/invoices")
def list_org_invoices(org_id):
    require_roles("PlatformAdmin", "BillingContact", "OrganizationAdmin")
    _get_org_or_404(org_id)
    limit, offset = pagination_params()
    items = [i for i in db.invoices.values() if i["organization_id"] == org_id]
    status_f = request.args.get("status")
    if status_f is not None:
        items = [i for i in items if i["status"] == status_f]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([simple_view(i) for i in page], response_type="array", pagination=meta)


@bp.get("/organizations/<org_id>/rate-limit-windows")
def list_org_windows(org_id):
    require_roles("PlatformAdmin", "OrganizationAdmin")
    _get_org_or_404(org_id)
    limit, offset = pagination_params()
    items = [w for w in db.rate_limit_windows.values() if w["organization_id"] == org_id]
    mv_f = request.args.get("model_version_id")
    ws_f = request.args.get("window_start")
    if mv_f is not None:
        items = [w for w in items if w["model_version_id"] == mv_f]
    if ws_f is not None:
        items = [w for w in items if w["window_start"] == ws_f]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([simple_view(w) for w in page], response_type="array", pagination=meta)


@bp.get("/organizations/<org_id>/queued-requests")
def list_org_queued(org_id):
    require_roles("PlatformAdmin", "OrganizationAdmin")
    _get_org_or_404(org_id)
    limit, offset = pagination_params()
    items = [q for q in db.queued_requests.values() if q["organization_id"] == org_id]
    mv_f = request.args.get("model_version_id")
    status_f = request.args.get("status")
    if mv_f is not None:
        items = [q for q in items if q["model_version_id"] == mv_f]
    if status_f is not None:
        items = [q for q in items if q["status"] == status_f]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([simple_view(q) for q in page], response_type="array", pagination=meta)


@bp.get("/organizations/<org_id>/abuse-cases")
def list_org_abuse_cases(org_id):
    require_roles("PlatformAdmin", "TrustAnalyst", "TrustLead", "OrganizationAdmin")
    _get_org_or_404(org_id)
    limit, offset = pagination_params()
    items = [c for c in db.abuse_cases.values() if c["organization_id"] == org_id]
    status_f = request.args.get("status")
    if status_f is not None:
        items = [c for c in items if c["status"] == status_f]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([simple_view(c) for c in page], response_type="array", pagination=meta)
