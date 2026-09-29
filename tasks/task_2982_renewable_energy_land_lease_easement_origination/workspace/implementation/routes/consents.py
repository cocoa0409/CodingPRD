"""Neighbor consents (PRD section 3.3, second half)."""

from flask import Blueprint

import access
import cascades
import serializers as ser
import validation as v
from auth import LAND_AGENT, PORTFOLIO_MANAGER, TITLE_COUNSEL, require
from envelope import ok, ok_list
from errors import ERR_CONSENT_EXPIRED, ERR_INVALID_STATE, fail
from store import db, insert, now, ordered, touch
from util import D, add_days

bp = Blueprint("consents", __name__, url_prefix="/land-origination")

READERS = (LAND_AGENT, TITLE_COUNSEL, PORTFOLIO_MANAGER)


@bp.get("/neighbor-consents/<consent_id>")
@require(*READERS)
def get_consent(consent_id):
    return ok(ser.consent(access.consent(consent_id)))


@bp.get("/neighbor-consents")
@require(*READERS)
def list_consents():
    limit, offset = v.pagination()
    rows = ordered(db.consents.values())
    rows = v.apply_filters(rows, [
        ("parcel_id", v.query_str("parcel_id")),
        ("setback_rule_id", v.query_str("setback_rule_id")),
        ("status", v.query_str("status")),
    ])
    page, total = v.paginate(rows, limit, offset)
    return ok_list(ser.many(ser.consent, page), limit, offset, total)


@bp.post("/neighbor-consents")
@require(LAND_AGENT)
def create_consent():
    body = v.json_body()
    # Rungs 4 and 5 resolve before the rung-14 shape pass, and in that order.
    parcel_id = v.lookup_fk(body, "parcel_id")
    parcel = access.parcel(parcel_id) if parcel_id else None
    rule_id = v.lookup_fk(body, "setback_rule_id")
    rule = access.setback_rule(rule_id) if rule_id else None

    v.req_fk(body, "parcel_id")
    v.req_fk(body, "setback_rule_id")
    neighbor_name = v.req_str(body, "neighbor_name", min_len=1, max_len=200)
    days = v.opt_int(body, "consent_expiry_days", 60, lo=1, hi=365)

    requested_at = now()
    row = insert("consents", {
        "parcel_id": parcel["id"],
        "setback_rule_id": rule["id"],
        "neighbor_name": neighbor_name,
        "consent_expiry_days": days,
        "requested_at": requested_at,
        "consent_expiry_at": add_days(requested_at, days),
        "granted_at": None,
        "revoked_at": None,
        "released_acres": D("0.00"),
        "status": "REQUESTED",
    })
    return ok(ser.consent(row), 201)


@bp.post("/neighbor-consents/<consent_id>/grant")
@require(LAND_AGENT)
def grant_consent(consent_id):
    row = access.consent(consent_id)
    parcel = db.parcels.get(row["parcel_id"])

    # Rung 21 sits above the generic state rung on purpose.
    if row["consent_expiry_at"] is not None and now() >= row["consent_expiry_at"]:
        fail(ERR_CONSENT_EXPIRED)
    if row["status"] != "REQUESTED":
        fail(ERR_INVALID_STATE)
    if parcel is None or parcel["status"] in ("DISQUALIFIED", "LEASED"):
        fail(ERR_INVALID_STATE)

    before = row["version"]
    row["status"] = "GRANTED"
    row["granted_at"] = now()

    # Three hops only (PRD 3.3): acreage, qualification, posture. Screening is
    # deliberately NOT re-computed — the formula is blind to acreage.
    cascades.recompute_parcel_acreage(parcel)
    cascades.reevaluate_parcel_qualification(parcel)
    cascades.sync_landowner_posture(db.landowners.get(parcel["landowner_id"]))

    # The acreage procedure may already have bumped this consent when it wrote
    # released_acres; the row must end up exactly one version higher.
    if row["version"] == before:
        touch(row)
    return ok(ser.consent(row))


@bp.post("/neighbor-consents/<consent_id>/revoke")
@require(LAND_AGENT)
def revoke_consent(consent_id):
    row = access.consent(consent_id)
    parcel = db.parcels.get(row["parcel_id"])

    if row["status"] != "GRANTED":
        fail(ERR_INVALID_STATE)
    if parcel is None or parcel["status"] == "LEASED":
        fail(ERR_INVALID_STATE)

    before = row["version"]
    row["status"] = "REVOKED"
    row["revoked_at"] = now()
    row["released_acres"] = D("0.00")

    # The compensating cascade mirrors the grant: three hops, no screening.
    cascades.recompute_parcel_acreage(parcel)
    cascades.reevaluate_parcel_qualification(parcel)
    cascades.sync_landowner_posture(db.landowners.get(parcel["landowner_id"]))

    if row["version"] == before:
        touch(row)
    return ok(ser.consent(row))
