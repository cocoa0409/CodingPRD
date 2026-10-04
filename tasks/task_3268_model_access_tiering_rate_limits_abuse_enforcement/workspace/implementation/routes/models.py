"""Model version + safety evaluation routes."""
from __future__ import annotations

from datetime import timedelta

import db
from errors import (duplicate_model_version, invalid_request, invalid_state,
                    not_found, segregation_of_duties)
from middleware import require_roles, pagination_params, paginate
from response import success
from services.domain import MIGRATION_WINDOW_DAYS, PASS_THRESHOLDS
from services.util import (body, require_enum, require_int, require_number,
                           require_str, simple_view, sort_by_created, stamp_new,
                           touch)

from flask import Blueprint, request

bp = Blueprint("models", __name__)

READ_ROLES = ("PlatformAdmin", "TrustAnalyst", "TrustLead", "BillingContact", "OrganizationAdmin")

PRICING_KEYS = ("input_per_mtok_cents", "output_per_mtok_cents", "cached_per_mtok_cents")


def _validate_pricing(data) -> dict:
    pricing = data.get("pricing")
    if not isinstance(pricing, dict):
        raise invalid_request("pricing must be an object")
    out = {}
    for k in PRICING_KEYS:
        v = pricing.get(k)
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise invalid_request(f"pricing.{k} must be a non-negative integer")
        out[k] = v
    if out["cached_per_mtok_cents"] >= out["input_per_mtok_cents"]:
        raise invalid_request("cached rate must be strictly less than input rate")
    return out


@bp.post("/model-versions")
def create_model_version():
    require_roles("PlatformAdmin")
    data = body()
    slug = require_str(data, "model_slug")
    tag = require_str(data, "version_tag")
    pricing = _validate_pricing(data)
    for m in db.model_versions.values():
        if (m["model_slug"] == slug and m["version_tag"] == tag
                and m["status"] != "SUNSET"):
            raise duplicate_model_version()
    mv = {
        "model_slug": slug,
        "version_tag": tag,
        "status": "DRAFT",
        "deprecation_announced_at": None,
        "sunset_at": None,
        "pricing": pricing,
        "safety_evaluation_id": None,
    }
    stamp_new(mv, common=True)
    db.model_versions[mv["id"]] = mv
    return success(simple_view(mv), status=201)


@bp.get("/model-versions")
def list_model_versions():
    require_roles(*READ_ROLES)
    limit, offset = pagination_params()
    items = list(db.model_versions.values())
    status_f = request.args.get("status")
    slug_f = request.args.get("model_slug")
    se_f = request.args.get("safety_evaluation_id")
    if status_f is not None:
        items = [m for m in items if m["status"] == status_f]
    if slug_f is not None:
        items = [m for m in items if m["model_slug"] == slug_f]
    if se_f is not None:
        items = [m for m in items if m.get("safety_evaluation_id") == se_f]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([simple_view(m) for m in page], response_type="array", pagination=meta)


def _get_mv_or_404(mv_id: str) -> dict:
    mv = db.model_versions.get(mv_id)
    if mv is None:
        raise not_found("model version not found")
    return mv


@bp.get("/model-versions/<mv_id>")
def get_model_version(mv_id):
    require_roles(*READ_ROLES)
    mv = _get_mv_or_404(mv_id)
    return success(simple_view(mv))


@bp.post("/model-versions/<mv_id>/deprecate")
def deprecate_model_version(mv_id):
    require_roles("PlatformAdmin")
    mv = _get_mv_or_404(mv_id)
    if mv["status"] != "ACTIVE":
        raise invalid_state("model version is not ACTIVE")
    now = db.now()
    mv["status"] = "DEPRECATED"
    mv["deprecation_announced_at"] = db.fmt_clock(now)
    mv["sunset_at"] = db.fmt_clock(now + timedelta(days=MIGRATION_WINDOW_DAYS))
    touch(mv)
    return success(simple_view(mv))


@bp.get("/model-versions/<mv_id>/safety-evaluations")
def list_model_evaluations(mv_id):
    require_roles("PlatformAdmin", "TrustAnalyst", "TrustLead")
    _get_mv_or_404(mv_id)
    limit, offset = pagination_params()
    items = [e for e in db.safety_evaluations.values() if e["model_version_id"] == mv_id]
    status_f = request.args.get("status")
    if status_f is not None:
        items = [e for e in items if e["status"] == status_f]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([simple_view(e) for e in page], response_type="array", pagination=meta)


@bp.get("/model-versions/<mv_id>/usage-records")
def list_model_usage(mv_id):
    require_roles("PlatformAdmin", "BillingContact")
    _get_mv_or_404(mv_id)
    limit, offset = pagination_params()
    items = [u for u in db.usage_records.values() if u["model_version_id"] == mv_id]
    org_f = request.args.get("organization_id")
    batch_f = request.args.get("batch")
    if org_f is not None:
        items = [u for u in items if u["organization_id"] == org_f]
    if batch_f is not None:
        val = batch_f.lower() in ("true", "1", "yes")
        items = [u for u in items if bool(u.get("batch")) == val]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([simple_view(u) for u in page], response_type="array", pagination=meta)


@bp.post("/model-versions/<mv_id>/safety-evaluations")
def open_safety_evaluation(mv_id):
    user_id, _ = require_roles("TrustAnalyst")
    mv = _get_mv_or_404(mv_id)
    data = body()
    capability = require_enum(data, "capability_class", {"STANDARD", "ELEVATED", "FRONTIER"})
    if mv["status"] != "DRAFT":
        raise invalid_state("model version is not DRAFT")
    for e in db.safety_evaluations.values():
        if e["model_version_id"] == mv_id and e["status"] == "OPEN":
            raise invalid_state("an OPEN evaluation already exists for this model version")
    ev = {
        "model_version_id": mv_id,
        "capability_class": capability,
        "status": "OPEN",
        "score": None,
        "verdict_by": None,
        "_opened_by": user_id,  # internal: segregation-of-duties reference
    }
    stamp_new(ev, common=True)
    db.safety_evaluations[ev["id"]] = ev
    mv["status"] = "GATED"
    mv["safety_evaluation_id"] = ev["id"]
    touch(mv)
    return success(simple_view(ev), status=201)


@bp.post("/safety-evaluations/<ev_id>/submit-verdict")
def submit_verdict(ev_id):
    user_id, _ = require_roles("TrustLead")
    ev = db.safety_evaluations.get(ev_id)
    if ev is None:
        raise not_found("safety evaluation not found")
    data = body()
    score = require_number(data, "score", lo=0.0, hi=1.0)
    if ev["status"] != "OPEN":
        raise invalid_state("evaluation is not OPEN")
    if user_id == ev.get("_opened_by"):
        raise segregation_of_duties("verdict_by must differ from the evaluation opener")
    threshold = PASS_THRESHOLDS[ev["capability_class"]]
    ev["score"] = score
    ev["verdict_by"] = user_id
    mv = db.model_versions.get(ev["model_version_id"])
    if score >= threshold:
        ev["status"] = "PASSED"
        if mv is not None and mv["status"] == "GATED":
            mv["status"] = "ACTIVE"
    else:
        ev["status"] = "FAILED"
        if mv is not None and mv["status"] == "GATED":
            mv["status"] = "DRAFT"
    touch(ev)
    if mv is not None:
        touch(mv)
    return success(simple_view(ev))
