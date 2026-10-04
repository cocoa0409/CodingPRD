"""Usage record and queued request routes."""
from __future__ import annotations

import db
from errors import (invalid_request, model_unavailable, not_found,
                    org_status_blocked, queue_full, rate_limited)
from middleware import require_roles
from response import success
from services import domain
from services.util import (body, require_datetime, require_int, require_str,
                           simple_view, stamp_new)

from flask import Blueprint

bp = Blueprint("usage", __name__)


@bp.post("/usage-records")
def create_usage_record():
    require_roles("OrganizationAdmin", "PlatformAdmin")
    data = body()
    org_id = require_str(data, "organization_id")
    mv_id = require_str(data, "model_version_id")
    window_dt = require_datetime(data, "minute_window_start")
    requests_n = require_int(data, "requests", minimum=0)
    input_tokens = require_int(data, "input_tokens", minimum=0)
    output_tokens = require_int(data, "output_tokens", minimum=0)
    cached_tokens = require_int(data, "cached_tokens", minimum=0)
    batch = data.get("batch", False)
    if not isinstance(batch, bool):
        raise invalid_request("batch must be a boolean")

    org = db.organizations.get(org_id)
    if org is None:
        raise not_found("organization not found")
    mv = db.model_versions.get(mv_id)
    if mv is None:
        raise not_found("model version not found")

    if org["status"] in ("TERMINATED", "SUSPENDED"):
        raise org_status_blocked("organization status blocks new usage")

    # truncate to the minute
    minute = window_dt.replace(second=0, microsecond=0)
    window_start_iso = db.fmt_clock(minute)

    if not domain.check_model_available(org, mv):
        raise model_unavailable()

    tokens_cost = input_tokens + output_tokens + cached_tokens
    admitted, _window = domain.admit(org, mv_id, window_start_iso, requests_n, tokens_cost)
    if not admitted:
        raise rate_limited()

    record = {
        "organization_id": org_id,
        "model_version_id": mv_id,
        "minute_window_start": window_start_iso,
        "requests": requests_n,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached_tokens,
        "batch": batch,
    }
    stamp_new(record, common=False)
    record["created_at"] = db.fmt_clock(db.now())
    db.usage_records[record["id"]] = record
    return success(simple_view(record), status=201)


@bp.post("/queued-requests")
def create_queued_request():
    require_roles("OrganizationAdmin", "PlatformAdmin")
    data = body()
    org_id = require_str(data, "organization_id")
    mv_id = require_str(data, "model_version_id")
    requests_cost = require_int(data, "requests_cost", minimum=1)
    tokens_cost = require_int(data, "tokens_cost", minimum=1)

    org = db.organizations.get(org_id)
    if org is None:
        raise not_found("organization not found")
    mv = db.model_versions.get(mv_id)
    if mv is None:
        raise not_found("model version not found")

    if org["status"] in ("TERMINATED", "SUSPENDED", "RESTRICTED"):
        raise org_status_blocked("organization status blocks new queued admissions")

    if domain.queue_depth(org_id, mv_id) >= domain.QUEUE_MAX_DEPTH:
        raise queue_full()

    q = {
        "organization_id": org_id,
        "model_version_id": mv_id,
        "requests_cost": requests_cost,
        "tokens_cost": tokens_cost,
        "status": "QUEUED",
        "enqueued_at": db.fmt_clock(db.now()),
    }
    stamp_new(q, common=True)
    db.queued_requests[q["id"]] = q
    return success(simple_view(q), status=201)
