"""Scope version endpoints. Half-open [effective_from, effective_to)
intervals per program must not overlap; adjacency allowed."""
from flask import Blueprint, request

import clock
import db
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_SCOPE_WINDOW_OVERLAP,
)
from helpers import (
    base_entity, get_body, require_fields, reject_unknown_fields, parse_pagination,
)
from middleware import require_roles
from response import success_object, success_list
from serializers import scope_version_out

bp = Blueprint("scope_versions", __name__)

CREATE_FIELDS = {"program_id", "effective_from", "effective_to",
                 "in_scope_asset_ids", "safe_harbor_text"}


@bp.route("/api/scope-versions", methods=["POST"])
def create_scope_version():
    require_roles({"ProgramAdmin"})
    body = get_body()
    reject_unknown_fields(body, CREATE_FIELDS)
    require_fields(body, ["program_id", "effective_from", "in_scope_asset_ids"])
    if body["program_id"] not in db.programs:
        raise_err(ERR_NOT_FOUND, f"Program {body['program_id']} not found")
    try:
        ef = clock.parse_iso(body["effective_from"])
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "effective_from malformed")
    et = None
    if body.get("effective_to") is not None:
        try:
            et = clock.parse_iso(body["effective_to"])
        except Exception:
            raise_err(ERR_INVALID_REQUEST, "effective_to malformed")
        if et <= ef:
            raise_err(ERR_INVALID_REQUEST, "effective_to must be after effective_from")
    if not isinstance(body["in_scope_asset_ids"], list):
        raise_err(ERR_INVALID_REQUEST, "in_scope_asset_ids must be an array")

    # half-open interval non-overlap for the same program
    for v in db.scope_versions.values():
        if v["program_id"] != body["program_id"]:
            continue
        oef = clock.parse_iso(v["effective_from"])
        oet = v.get("effective_to")
        oet = clock.parse_iso(oet) if oet else None
        # [ef, et) vs [oef, oet) intersect iff ef < oet(open) and oef < et(open)
        new_end_ok = (oet is None) or (ef < oet)
        old_end_ok = (et is None) or (oef < et)
        if new_end_ok and old_end_ok:
            raise_err(
                ERR_SCOPE_WINDOW_OVERLAP,
                "Scope version window overlaps an existing window for this program",
            )

    seqs = [
        v["version_seq"] for v in db.scope_versions.values()
        if v["program_id"] == body["program_id"]
    ]
    v = base_entity()
    v.update(
        {
            "program_id": body["program_id"],
            "effective_from": clock.iso(ef),
            "effective_to": clock.iso(et) if et else None,
            "in_scope_asset_ids": list(body["in_scope_asset_ids"]),
            "safe_harbor_text": body.get("safe_harbor_text"),
            "version_seq": (max(seqs) + 1) if seqs else 1,
        }
    )
    db.scope_versions[v["id"]] = v
    return success_object(scope_version_out(v), 201)


@bp.route("/api/scope-versions/<scope_version_id>", methods=["GET"])
def read_scope_version(scope_version_id):
    require_roles({"PlatformAdmin", "ProgramAdmin", "Triager", "Researcher"})
    v = db.scope_versions.get(scope_version_id)
    if v is None:
        raise_err(ERR_NOT_FOUND, f"ScopeVersion {scope_version_id} not found")
    return success_object(scope_version_out(v))


@bp.route("/api/scope-versions", methods=["GET"])
def list_scope_versions():
    require_roles({"PlatformAdmin", "ProgramAdmin", "Triager", "Researcher"})
    limit, offset = parse_pagination(request.args)
    items = list(db.scope_versions.values())
    pid = request.args.get("program_id")
    if pid is not None:
        items = [v for v in items if v["program_id"] == pid]
    items.sort(key=lambda v: v["_created_dt"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([scope_version_out(v) for v in page], limit, offset, total)
