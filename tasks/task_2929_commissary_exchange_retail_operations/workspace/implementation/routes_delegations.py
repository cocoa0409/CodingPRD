"""Authorized-shopper delegations: granting, superseding and retiring
(PRD 3.3)."""

from flask import Blueprint

import constants as C
import lookups
import service_patron
import serialize
import validation as V
from db import db, new_record, sorted_records, touch
from envelope import array_response, object_response
from errors import ApiError

bp = Blueprint("delegations", __name__)


def _overlaps(a_from, a_to, b_from, b_to):
    """Half-open intervals: adjacency at an endpoint is not an overlap."""
    return a_from < b_to and b_from < a_to


@bp.post("/shopper-delegations")
def create_delegation():
    V.authenticate(("ComplianceOfficer",))
    body = V.raw_body()
    sponsor_patron_id = V.want_string(body, "sponsor_patron_id", required=True)
    delegate_patron_id = V.want_string(body, "delegate_patron_id", required=True)
    valid_from = V.want_instant(body, "valid_from", required=True)
    valid_to = V.want_instant(body, "valid_to", required=True)
    cap = V.want_int(body, "per_sale_spend_cap_cents", required=True, minimum=1)
    expected_version = V.want_int(body, "expected_delegate_patron_version", required=True)
    if valid_to <= valid_from:
        raise ApiError(
            "ERR_INVALID_REQUEST", "Field 'valid_to' must be strictly later than 'valid_from'."
        )

    lookups.patron(sponsor_patron_id)
    delegate = lookups.patron(delegate_patron_id)

    # Doctrine step 8: the stale-view check precedes the same-sponsor overlap
    # test, so a client with an out-of-date delegate view hears about the
    # version rather than about the window.
    if delegate["version"] != expected_version:
        raise ApiError("ERR_STALE_PATRON_VERSION")

    for existing in sorted_records(db.delegations):
        if existing["status"] != "ACTIVE":
            continue
        if existing["delegate_patron_id"] != delegate_patron_id:
            continue
        if existing["sponsor_patron_id"] != sponsor_patron_id:
            continue
        if _overlaps(valid_from, valid_to, existing["valid_from"], existing["valid_to"]):
            raise ApiError("ERR_DELEGATION_WINDOW_OVERLAP")

    delegation = new_record()
    delegation.update({
        "sponsor_patron_id": sponsor_patron_id,
        "delegate_patron_id": delegate_patron_id,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "per_sale_spend_cap_cents": cap,
        "status": "ACTIVE",
        "superseded_by_delegation_id": None,
    })
    db.delegations[delegation["id"]] = delegation

    # A grant from a different sponsor displaces rather than collides: a
    # delegate may only shop for one sponsor at a time.
    displaced_ids = set()
    for existing in sorted_records(db.delegations):
        if existing["id"] == delegation["id"]:
            continue
        if existing["status"] != "ACTIVE":
            continue
        if existing["delegate_patron_id"] != delegate_patron_id:
            continue
        if existing["sponsor_patron_id"] == sponsor_patron_id:
            continue
        if _overlaps(valid_from, valid_to, existing["valid_from"], existing["valid_to"]):
            existing["status"] = "SUPERSEDED"
            existing["superseded_by_delegation_id"] = delegation["id"]
            touch(existing)
            displaced_ids.add(existing["id"])
    if displaced_ids:
        service_patron.flag_open_sales_of_delegations(displaced_ids)

    # A successful grant advances the delegate patron's version by 1.
    touch(delegate)
    return object_response(serialize.delegation_out(delegation), 201)


@bp.get("/shopper-delegations")
def list_delegations():
    V.authenticate(("ComplianceOfficer", "StoreCashier"))
    limit, offset = V.pagination()
    sponsor_patron_id = V.query_string("sponsor_patron_id")
    delegate_patron_id = V.query_string("delegate_patron_id")
    status = V.query_enum("status", C.DELEGATION_STATUSES)
    superseded_by = V.query_string("superseded_by_delegation_id")
    rows = sorted_records(db.delegations)
    if sponsor_patron_id is not None:
        rows = [r for r in rows if r["sponsor_patron_id"] == sponsor_patron_id]
    if delegate_patron_id is not None:
        rows = [r for r in rows if r["delegate_patron_id"] == delegate_patron_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if superseded_by is not None:
        rows = [r for r in rows if r["superseded_by_delegation_id"] == superseded_by]
    page, total = V.paginate(rows, limit, offset)
    return array_response([serialize.delegation_out(r) for r in page], limit, offset, total)


@bp.get("/shopper-delegations/<delegation_id>")
def read_delegation(delegation_id):
    V.authenticate(("ComplianceOfficer", "StoreCashier"))
    delegation = lookups.delegation(delegation_id)
    return object_response(serialize.delegation_out(delegation), 200)


@bp.post("/shopper-delegations/<delegation_id>/revoke")
def revoke_delegation(delegation_id):
    V.authenticate(("ComplianceOfficer",))
    delegation = lookups.delegation(delegation_id)
    body = V.raw_body()
    V.want_string(body, "reason", required=False)
    if delegation["status"] not in ("ACTIVE", "SUSPENDED_BY_SPONSOR"):
        raise ApiError("ERR_DELEGATION_NOT_ACTIVE")
    delegation["status"] = "REVOKED"
    touch(delegation)
    service_patron.flag_open_sales_of_delegations({delegation["id"]})
    return object_response(serialize.delegation_out(delegation), 200)
