"""ValuationSeries endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from db import DB, CLOCK
from errors import (
    not_found, invalid_input, invalid_state, duplicate_key,
    region_archived, stale_version,
)
from middleware import require_roles
from response import success
from services.calculations import parse_iso8601, compute_confidence, CONFIDENCE_GATE
from services.entity import stamp_new, touch


bp = Blueprint("series", __name__)

ALL_ROLES = ("ValuationAdmin", "DataOps", "DealerPartner", "Consumer", "Licensee")


def _series_view(s):
    return {
        "id": s["id"],
        "configuration_id": s["configuration_id"],
        "region_id": s["region_id"],
        "effective_from": s["effective_from"],
        "cadence": s["cadence"],
        "status": s["status"],
        "confidence_score": s["confidence_score"],
        "external_key": s["external_key"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


@bp.route("/valuation-series", methods=["POST"])
def create_series():
    require_roles("ValuationAdmin")
    body = request.get_json(silent=True) or {}
    configuration_id = body.get("configuration_id")
    region_id = body.get("region_id")
    effective_from = body.get("effective_from")
    cadence = body.get("cadence")
    external_key = body.get("external_key")
    expected_version = body.get("expected_version")

    # Priority 3: existence
    cfg = DB.configurations.get(configuration_id) if isinstance(configuration_id, str) else None
    if cfg is None:
        raise not_found("configuration not found")
    region = DB.regions.get(region_id) if isinstance(region_id, str) else None
    if region is None:
        raise not_found("region not found")

    # Priority 4: idempotency replay
    if isinstance(external_key, str) and external_key in DB._series_external_keys:
        existing = DB.series[DB._series_external_keys[external_key]]
        if (existing["configuration_id"] == configuration_id
                and existing["region_id"] == region_id
                and existing["effective_from"] == effective_from
                and existing["cadence"] == cadence):
            return success(_series_view(existing), 201)
        raise duplicate_key("external_key reused with different payload")

    # Priority 13: region must be ACTIVE
    if region["status"] != "ACTIVE":
        raise region_archived("region is archived")

    # Priority 14: input shape
    if cadence != "WEEKLY":
        raise invalid_input("cadence must be WEEKLY")
    if not isinstance(effective_from, str):
        raise invalid_input("effective_from is required")
    try:
        eff_dt = parse_iso8601(effective_from)
    except Exception:
        raise invalid_input("effective_from must be ISO 8601")
    if not isinstance(external_key, str) or not external_key:
        raise invalid_input("external_key is required")

    # OCC check + supersession (priority 15)
    # Find any non-SUPERSEDED series for the same (configuration_id, region_id)
    incumbent = None
    for s in DB.series.values():
        if (s["configuration_id"] == configuration_id
                and s["region_id"] == region_id
                and s["status"] != "SUPERSEDED"):
            incumbent = s
            break

    if incumbent is not None:
        # Must be ACTIVE for supersession path; if it's DRAFT/SUSPENDED we still
        # reject — only one non-SUPERSEDED series per pair is allowed.
        if incumbent["status"] == "ACTIVE":
            # Require OCC match
            if expected_version is None:
                raise stale_version("expected_version required to supersede ACTIVE series")
            try:
                ev = int(expected_version)
            except (TypeError, ValueError):
                raise invalid_input("expected_version must be integer")
            if ev != incumbent["version"]:
                raise stale_version("expected_version does not match current version")
            # Supersede: PENDING editions -> WITHDRAWN
            for ed in DB.editions.values():
                if ed["series_id"] == incumbent["id"] and ed["status"] == "PENDING":
                    ed["status"] = "WITHDRAWN"
                    touch(ed)
            incumbent["status"] = "SUPERSEDED"
            touch(incumbent)
        else:
            # Non-active incumbent blocks creation
            raise invalid_state("a non-SUPERSEDED series already exists for this pair")

    s = stamp_new({
        "configuration_id": configuration_id,
        "region_id": region_id,
        "effective_from": effective_from,
        "effective_from_dt": eff_dt,
        "cadence": cadence,
        "status": "DRAFT",
        "confidence_score": 0.0,
        "external_key": external_key,
    })
    DB.series[s["id"]] = s
    DB._series_external_keys[external_key] = s["id"]
    return success(_series_view(s), 201)


@bp.route("/valuation-series", methods=["GET"])
def list_series():
    require_roles(*ALL_ROLES)
    items = list(DB.series.values())
    cid = request.args.get("configuration_id")
    rid = request.args.get("region_id")
    status_filter = request.args.get("status")
    if cid:
        items = [s for s in items if s["configuration_id"] == cid]
    if rid:
        items = [s for s in items if s["region_id"] == rid]
    if status_filter:
        items = [s for s in items if s["status"] == status_filter]
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except (TypeError, ValueError):
        raise invalid_input("limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise invalid_input("pagination out of range")
    items.sort(key=lambda s: s["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success([_series_view(s) for s in page], 200,
                   response_type="array",
                   limit=limit, offset=offset, total_count=total,
                   has_more=(offset + limit) < total)


@bp.route("/valuation-series/<series_id>", methods=["GET"])
def get_series(series_id):
    require_roles(*ALL_ROLES)
    s = DB.series.get(series_id)
    if s is None:
        raise not_found("series not found")
    return success(_series_view(s), 200)


@bp.route("/valuation-series/<series_id>/activate", methods=["POST"])
def activate_series(series_id):
    require_roles("ValuationAdmin")
    s = DB.series.get(series_id)
    if s is None:
        raise not_found("series not found")
    if s["status"] != "DRAFT":
        raise invalid_state("series not in DRAFT")
    # Recompute confidence on activation per §3.3
    s["confidence_score"] = compute_confidence(s["configuration_id"],
                                               s["region_id"], CLOCK.now())
    s["status"] = "ACTIVE"
    touch(s)
    return success(_series_view(s), 200)
