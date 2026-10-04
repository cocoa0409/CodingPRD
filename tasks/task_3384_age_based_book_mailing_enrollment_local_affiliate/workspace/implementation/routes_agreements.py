"""Affiliate agreements (with OCC and geography overlap) and population stats."""

from flask import Blueprint, request

import db
import domain
from errors import ApiError
from response import ok, created, listing
from validation import (
    require_roles, ALL_ROLES, body, check_allowed, req_int, req_datetime,
    pagination,
)
from routes_admin import get_affiliate_or_404

bp = Blueprint("agreements", __name__, url_prefix="/library")


def get_agreement_or_404(agid):
    agr = db.agreements.get(agid)
    if agr is None:
        raise ApiError(404, "ERR_AGREEMENT_NOT_FOUND",
                       "Referenced agreement id does not exist")
    return agr


@bp.post("/affiliates/<aid>/agreements")
def create_agreement(aid):
    uid, role = require_roles("AffiliateCoordinator", "PlatformAdmin")
    aff = get_affiliate_or_404(aid)
    data = body()
    check_allowed(data, {"effective_from", "effective_to",
                         "local_fundraising_commitment_cents",
                         "expected_affiliate_version"})
    ef_raw, ef = req_datetime(data, "effective_from")
    et_raw, et = req_datetime(data, "effective_to")
    commitment = req_int(data, "local_fundraising_commitment_cents", 0)
    expected = req_int(data, "expected_affiliate_version")
    # Priority 5: entity-backed ownership
    if role == "AffiliateCoordinator" and uid != aid:
        raise ApiError(403, "ERR_FORBIDDEN",
                       "Coordinator may only act on their own affiliate")
    # Priority 6: optimistic concurrency on the affiliate version
    if expected != aff["version"]:
        raise ApiError(412, "ERR_STALE_VERSION",
                       "expected_affiliate_version does not match the affiliate's current version")
    # Priority 9: strictly positive half-open window
    if not (et > ef):
        raise ApiError(422, "ERR_AGREEMENT_WINDOW_INVALID",
                       "effective_to must be strictly after effective_from")
    rec = db.base_record()
    rec.update({
        "affiliate_id": aid,
        "effective_from": ef_raw,
        "effective_to": et_raw,
        "local_fundraising_commitment_cents": commitment,
        "status": "PENDING_APPROVAL",
        "decided_by": None,
        "_from": ef,
        "_to": et,
    })
    db.agreements[rec["id"]] = rec
    # Side effect: creating an agreement increments the owning affiliate's version.
    aff["version"] += 1
    aff["updated_at"] = db.stamp()
    return created(domain.ser_agreement(rec))


@bp.get("/affiliates/<aid>/agreements")
def list_agreements(aid):
    require_roles(*ALL_ROLES)
    get_affiliate_or_404(aid)
    limit, offset = pagination()
    f_status = request.args.get("status")
    rows = [a for a in db.agreements.values()
            if a["affiliate_id"] == aid
            and (f_status is None or a["status"] == f_status)]
    rows.sort(key=lambda r: r["_seq"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return listing([domain.ser_agreement(a) for a in page], limit, offset, total)


@bp.post("/agreements/<agid>/approve")
def approve_agreement(agid):
    uid, role = require_roles("StateProgramOfficer")
    agr = get_agreement_or_404(agid)
    aff = db.affiliates[agr["affiliate_id"]]
    if uid != aff["state_program_id"]:
        raise ApiError(403, "ERR_FORBIDDEN",
                       "Officer's state program does not match the affiliate's program")
    if agr["status"] != "PENDING_APPROVAL":
        raise ApiError(409, "ERR_INVALID_STATE",
                       "Only a PENDING_APPROVAL agreement can be approved")
    # Geography rule: no other PENDING_APPROVAL/ACTIVE agreement whose affiliate's
    # prefix set intersects this affiliate's may overlap the half-open window.
    my_prefixes = set(aff["postal_prefixes"])
    for o in db.agreements.values():
        if o["id"] == agid or o["status"] not in ("PENDING_APPROVAL", "ACTIVE"):
            continue
        oaff = db.affiliates.get(o["affiliate_id"])
        if oaff is None:
            continue
        if not (set(oaff["postal_prefixes"]) & my_prefixes):
            continue
        if agr["_from"] < o["_to"] and o["_from"] < agr["_to"]:
            raise ApiError(409, "ERR_AGREEMENT_GEOGRAPHY_OVERLAP",
                           "Overlapping coverage window with intersecting postal prefixes")
    agr["status"] = "ACTIVE"
    agr["decided_by"] = uid
    db.touch(agr)
    return ok(domain.ser_agreement(agr))


@bp.post("/agreements/<agid>/reject")
def reject_agreement(agid):
    uid, role = require_roles("StateProgramOfficer")
    agr = get_agreement_or_404(agid)
    aff = db.affiliates[agr["affiliate_id"]]
    if uid != aff["state_program_id"]:
        raise ApiError(403, "ERR_FORBIDDEN",
                       "Officer's state program does not match the affiliate's program")
    if agr["status"] != "PENDING_APPROVAL":
        raise ApiError(409, "ERR_INVALID_STATE",
                       "Only a PENDING_APPROVAL agreement can be rejected")
    agr["status"] = "REJECTED"
    agr["decided_by"] = uid
    db.touch(agr)
    return ok(domain.ser_agreement(agr))


@bp.post("/affiliates/<aid>/population-stats")
def create_population_stat(aid):
    uid, role = require_roles("AffiliateCoordinator", "PlatformAdmin")
    get_affiliate_or_404(aid)
    data = body()
    check_allowed(data, {"effective_year", "eligible_population"})
    year = req_int(data, "effective_year", 2000, 2100)
    population = req_int(data, "eligible_population", 1)
    if role == "AffiliateCoordinator" and uid != aid:
        raise ApiError(403, "ERR_FORBIDDEN",
                       "Coordinator may only act on their own affiliate")
    for s in db.population_stats.values():
        if s["affiliate_id"] == aid and s["effective_year"] == year:
            raise ApiError(409, "ERR_POPULATION_YEAR_DUPLICATE",
                           "A population stat already exists for this affiliate and year")
    rec = db.base_record()
    rec.update({
        "affiliate_id": aid,
        "effective_year": year,
        "eligible_population": population,
    })
    db.population_stats[rec["id"]] = rec
    return created(domain.ser_population_stat(rec))


@bp.get("/affiliates/<aid>/population-stats")
def list_population_stats(aid):
    uid, role = require_roles(*ALL_ROLES)
    get_affiliate_or_404(aid)
    if role == "AffiliateCoordinator" and uid != aid:
        raise ApiError(403, "ERR_FORBIDDEN",
                       "Coordinator may only read their own affiliate")
    limit, offset = pagination()
    rows = [s for s in db.population_stats.values() if s["affiliate_id"] == aid]
    rows.sort(key=lambda r: r["_seq"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return listing([domain.ser_population_stat(s) for s in page], limit, offset, total)
