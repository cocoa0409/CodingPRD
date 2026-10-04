"""Sponsors and sponsorship commitments (PRD 3.1)."""
from flask import Blueprint, request

from db import STORES, new_record, get_clock
from helpers import (
    body, require_roles, ok_obj, list_response, get_or_404, req_str, req_int,
    opt_enum, opt_dt, raise_err, now_iso,
)
from errors import (
    E_INVALID_REQUEST, E_INVALID_STATE, E_NOT_OWNER, E_SPONSOR_NOT_FOUND,
    E_CYCLE_NOT_FOUND, E_COMMITMENT_NOT_FOUND,
)
from logic import bump
from cascades import funding_withdrawal_cascade
from serializers import ser_sponsor, ser_commitment

bp = Blueprint("sponsors", __name__)

SPONSOR_TIERS = ("COMMUNITY", "REGIONAL", "NATIONAL")
COMMITMENT_STATUSES = ("PLEDGED", "RECEIVED", "ALLOCATED", "WITHDRAWN")


@bp.post("/rebuild/sponsors")
def create_sponsor():
    require_roles("PlatformAdmin")
    b = body()
    rec = new_record("sponsors", {
        "name": req_str(b, "name"),
        "contact_email": req_str(b, "contact_email"),
        "sponsor_tier": opt_enum(b, "sponsor_tier", SPONSOR_TIERS,
                                 default="COMMUNITY"),
    }, now_iso)
    return ok_obj(ser_sponsor(rec), 201)


@bp.get("/rebuild/sponsors/<sponsorId>")
def get_sponsor(sponsorId):
    require_roles("Any")
    rec = get_or_404("sponsors", sponsorId, E_SPONSOR_NOT_FOUND)
    return ok_obj(ser_sponsor(rec))


@bp.post("/rebuild/commitments")
def create_commitment():
    uid, role = require_roles("SponsorRep", "AffiliateStaff")
    b = body()
    sponsor_id = b.get("sponsor_id")
    # Tier 3 ownership: a SponsorRep pledges only for its own sponsor.
    if role == "SponsorRep":
        if sponsor_id is None:
            raise_err(E_INVALID_REQUEST, 400, "sponsor_id is required")
        if sponsor_id != uid:
            raise_err(E_NOT_OWNER, 403,
                      "SponsorRep may pledge only for its own sponsor")
    # Tier 4 body FK existence (canonical order: cycle, then sponsor).
    funding_cycle_id = b.get("funding_cycle_id")
    if funding_cycle_id is None:
        raise_err(E_INVALID_REQUEST, 400, "funding_cycle_id is required")
    get_or_404("funding_cycles", funding_cycle_id, E_CYCLE_NOT_FOUND)
    if sponsor_id is None:
        raise_err(E_INVALID_REQUEST, 400, "sponsor_id is required")
    get_or_404("sponsors", sponsor_id, E_SPONSOR_NOT_FOUND)
    amount = req_int(b, "amount_cents", lo=1)
    team_date = opt_dt(b, "team_build_event_date", default=None)
    rec = new_record("commitments", {
        "sponsor_id": sponsor_id,
        "funding_cycle_id": funding_cycle_id,
        "amount_cents": amount,
        "team_build_event_date": team_date,
        "status": "PLEDGED",
        "received_at": None,
        "allocated_amount_cents": 0,
        "withdrawn_at": None,
    }, now_iso)
    return ok_obj(ser_commitment(rec), 201)


@bp.get("/rebuild/commitments")
def list_commitments():
    require_roles("Any")
    recs = list(STORES["commitments"].values())
    sp = request.args.get("sponsor_id")
    if sp is not None:
        recs = [r for r in recs if r["sponsor_id"] == sp]
    fc = request.args.get("funding_cycle_id")
    if fc is not None:
        recs = [r for r in recs if r["funding_cycle_id"] == fc]
    return list_response(recs, ser_commitment)


@bp.get("/rebuild/commitments/<commitmentId>")
def get_commitment(commitmentId):
    require_roles("Any")
    rec = get_or_404("commitments", commitmentId, E_COMMITMENT_NOT_FOUND)
    return ok_obj(ser_commitment(rec))


@bp.patch("/rebuild/commitments/<commitmentId>")
def patch_commitment(commitmentId):
    require_roles("AffiliateStaff")
    rec = get_or_404("commitments", commitmentId, E_COMMITMENT_NOT_FOUND)
    b = body()
    if "status" not in b:
        raise_err(E_INVALID_REQUEST, 400, "status is required")
    target = b["status"]
    if not isinstance(target, str) or target not in COMMITMENT_STATUSES:
        raise_err(E_INVALID_REQUEST, 400,
                  "status must be one of " + ", ".join(COMMITMENT_STATUSES))
    if target == "RECEIVED":
        if rec["status"] != "PLEDGED":
            raise_err(E_INVALID_STATE, 409,
                      "only a PLEDGED commitment can be received")
        rec["status"] = "RECEIVED"
        rec["received_at"] = get_clock()
        bump(rec)
    elif target == "WITHDRAWN":
        if rec["status"] not in ("PLEDGED", "RECEIVED", "ALLOCATED"):
            raise_err(E_INVALID_STATE, 409,
                      "only PLEDGED, RECEIVED or ALLOCATED commitments can "
                      "be withdrawn")
        was_live = rec["status"] in ("RECEIVED", "ALLOCATED")
        rec["status"] = "WITHDRAWN"
        rec["withdrawn_at"] = get_clock()
        if was_live:
            rec["allocated_amount_cents"] = 0
        bump(rec)
        if was_live:
            # Received money leaving the pool may force project cancellations.
            funding_withdrawal_cascade(rec["funding_cycle_id"])
    else:  # PLEDGED / ALLOCATED are not operator-drivable targets
        raise_err(E_INVALID_STATE, 409, "no transition to %s" % target)
    return ok_obj(ser_commitment(rec))
