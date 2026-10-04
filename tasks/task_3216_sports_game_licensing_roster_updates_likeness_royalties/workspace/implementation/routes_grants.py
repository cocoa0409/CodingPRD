"""Likeness grant endpoints."""
from __future__ import annotations

from flask import Blueprint

import helpers as H
import services as S
from db import db
from errors import (err_college_opt_in, err_grant_term, err_invalid_input,
                    err_invalid_state, err_reference_state)
from middleware import require_roles
from response import (body_json, ok_obj, parse_date, require_enum,
                      require_fields, require_int, require_str, stamp_new)

bp = Blueprint("grants", __name__)

GRANT_KINDS = {"GROUP_PA", "INDIVIDUAL_RETIRED", "NIL_COLLEGE"}
RO = ("RightsOfficer",)


@bp.post("/licensing/likeness-grants")
def create_grant():
    require_roles(*RO)
    body = body_json()
    require_fields(body, ["athlete_id", "agreement_id", "grant_kind",
                          "term_start_on", "term_end_on", "royalty_share_bps",
                          "payment_destination"])
    athlete = H.get_athlete(body["athlete_id"])
    agreement = H.get_agreement(body["agreement_id"])
    kind = require_enum(body, "grant_kind", GRANT_KINDS)
    ts = parse_date(body["term_start_on"], "term_start_on")
    te = parse_date(body["term_end_on"], "term_end_on")
    share = require_int(body, "royalty_share_bps", 0)
    dest = require_str(body, "payment_destination")
    if te < ts:
        raise err_invalid_input("term_end_on must be >= term_start_on")
    rec = {
        "athlete_id": athlete["id"],
        "agreement_id": agreement["id"],
        "grant_kind": kind,
        "term_start_on": body["term_start_on"],
        "term_end_on": body["term_end_on"],
        "royalty_share_bps": share,
        "payment_destination": dest,
        "grant_status": "PENDING",
        "suspended_reason": None,
        "_term_start": ts,
        "_term_end": te,
        "_held_amount": 0,
    }
    stamp_new(rec)
    db.likeness_grants[rec["id"]] = rec
    return ok_obj(H.serialize(rec), 201)


@bp.get("/licensing/likeness-grants/<grant_id>")
def get_grant(grant_id):
    require_roles("LicensingAdmin", "RightsOfficer", "FinanceController",
                  "LeagueAuditor", "UnionAuditor")
    g = H.get_grant(grant_id)
    return ok_obj(H.serialize(g))


@bp.post("/licensing/likeness-grants/<grant_id>/grant")
def grant_grant(grant_id):
    require_roles(*RO)
    g = H.get_grant(grant_id)
    if g["grant_status"] != "PENDING":
        raise err_invalid_state("Grant must be PENDING")
    athlete = H.get_athlete(g["athlete_id"])
    agreement = H.get_agreement(g["agreement_id"])
    if agreement["agreement_status"] != "ACTIVE":
        raise err_reference_state("Referenced agreement is not ACTIVE")
    if athlete["athlete_class"] == "COLLEGE" and not athlete["college_opt_in"]:
        raise err_college_opt_in()
    if g["_term_start"] < agreement["_term_start"] or g["_term_end"] > agreement["_term_end"]:
        raise err_grant_term()
    g["grant_status"] = "GRANTED"
    from response import touch
    touch(g)
    S.athlete_eligibility_refresh(athlete["id"])
    return ok_obj(H.serialize(g))


@bp.post("/licensing/likeness-grants/<grant_id>/suspend")
def suspend_grant_ep(grant_id):
    require_roles(*RO)
    g = H.get_grant(grant_id)
    body = body_json()
    reason = body.get("suspended_reason")
    if not isinstance(reason, str) or not reason:
        raise err_invalid_input("suspended_reason is required")
    if g["grant_status"] != "GRANTED":
        raise err_invalid_state("Grant must be GRANTED to suspend")
    S.suspend_grant(g, reason)
    return ok_obj(H.serialize(g))


@bp.post("/licensing/likeness-grants/<grant_id>/reinstate")
def reinstate_grant_ep(grant_id):
    require_roles(*RO)
    g = H.get_grant(grant_id)
    if g["grant_status"] != "SUSPENDED":
        raise err_invalid_state("Grant must be SUSPENDED to reinstate")
    agreement = H.get_agreement(g["agreement_id"])
    if agreement["agreement_status"] != "ACTIVE":
        raise err_reference_state("Referenced agreement is not ACTIVE")
    S.reinstate_grant(g)
    return ok_obj(H.serialize(g))


@bp.post("/licensing/likeness-grants/<grant_id>/revoke")
def revoke_grant_ep(grant_id):
    require_roles(*RO)
    g = H.get_grant(grant_id)
    if g["grant_status"] != "SUSPENDED":
        raise err_invalid_state("Grant must be SUSPENDED to revoke")
    S.revoke_grant(g)
    return ok_obj(H.serialize(g))
