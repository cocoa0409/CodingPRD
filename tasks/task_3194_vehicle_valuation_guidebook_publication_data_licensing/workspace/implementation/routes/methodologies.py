"""Methodology endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from db import DB, CLOCK
from errors import not_found, invalid_input, invalid_state, duplicate_key
from middleware import require_roles
from response import success
from services.calculations import to_iso8601_ms
from services.entity import stamp_new, touch


bp = Blueprint("methodologies", __name__)

ALL_ROLES = ("ValuationAdmin", "DataOps", "DealerPartner", "Consumer", "Licensee")


def _methodology_view(m):
    return {
        "id": m["id"],
        "version_label": m["version_label"],
        "formula_hash": m["formula_hash"],
        "published_at": m.get("published_at"),
        "status": m["status"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


@bp.route("/methodologies", methods=["POST"])
def create_methodology():
    require_roles("ValuationAdmin")
    body = request.get_json(silent=True) or {}
    version_label = body.get("version_label")
    formula_hash = body.get("formula_hash")
    if not isinstance(version_label, str) or not version_label:
        raise invalid_input("version_label is required")
    if not isinstance(formula_hash, str) or not formula_hash:
        raise invalid_input("formula_hash is required")
    if version_label in DB._methodology_labels:
        raise duplicate_key("version_label already exists")
    m = stamp_new({
        "version_label": version_label,
        "formula_hash": formula_hash,
        "published_at": None,
        "status": "DRAFT",
    })
    DB.methodologies[m["id"]] = m
    DB._methodology_labels[version_label] = m["id"]
    return success(_methodology_view(m), 201)


@bp.route("/methodologies", methods=["GET"])
def list_methodologies():
    require_roles(*ALL_ROLES)
    items = list(DB.methodologies.values())
    status_filter = request.args.get("status")
    if status_filter:
        items = [m for m in items if m["status"] == status_filter]
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except (TypeError, ValueError):
        raise invalid_input("limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise invalid_input("pagination out of range")
    items.sort(key=lambda m: m["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success([_methodology_view(m) for m in page], 200,
                   response_type="array",
                   limit=limit, offset=offset, total_count=total,
                   has_more=(offset + limit) < total)


@bp.route("/methodologies/<methodology_id>/publish", methods=["POST"])
def publish_methodology(methodology_id):
    require_roles("ValuationAdmin")
    m = DB.methodologies.get(methodology_id)
    if m is None:
        raise not_found("methodology not found")
    if m["status"] != "DRAFT":
        raise invalid_state("methodology not in DRAFT")
    # supersede other PUBLISHED methodologies
    for other in DB.methodologies.values():
        if other["id"] != m["id"] and other["status"] == "PUBLISHED":
            other["status"] = "SUPERSEDED"
            touch(other)
    m["status"] = "PUBLISHED"
    m["published_at"] = to_iso8601_ms(CLOCK.now())
    touch(m)
    return success(_methodology_view(m), 200)
