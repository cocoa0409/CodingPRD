"""License agreement endpoints."""
from __future__ import annotations

from flask import Blueprint, request

import helpers as H
import services as S
from db import db
from errors import (err_audit_blocks_termination, err_exclusivity,
                    err_invalid_input, err_invalid_state, err_temporal)
from middleware import require_roles
from response import (body_json, ok_list, ok_obj, pagination_params,
                      parse_date, require_enum, require_fields, require_int,
                      require_str, stamp_new, touch)
import errors as E

bp = Blueprint("agreements", __name__)

LICENSOR_TYPES = {"LEAGUE", "PLAYERS_ASSOCIATION", "COLLEGE_BODY"}
EXCL_SCOPES = {"NONE", "CATEGORY", "FULL"}
ROYALTY_MODELS = {"PERCENT_OF_NET", "PER_UNIT", "HYBRID"}
ADMIN = ("LicensingAdmin",)


def _exclusivity_conflict(ag) -> bool:
    if ag["exclusivity_scope"] == "NONE":
        return False
    for other in db.agreements.values():
        if other["id"] == ag["id"]:
            continue
        if other["sport_category"] != ag["sport_category"]:
            continue
        if other["exclusivity_scope"] == "NONE":
            continue
        if other["agreement_status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        lo = max(ag["_term_start"], other["_term_start"])
        hi = min(ag["_term_end"], other["_term_end"])
        if (hi - lo).days + 1 > 0:  # inclusive intersection length in days
            return True
    return False


@bp.post("/licensing/agreements")
def create_agreement():
    require_roles(*ADMIN)
    body = body_json()
    require_fields(body, ["licensor_type", "licensor_name", "exclusivity_scope",
                          "sport_category", "term_start_on", "term_end_on",
                          "royalty_model", "royalty_rate_bps",
                          "minimum_guarantee_cents", "mg_recoupable",
                          "audit_window_days"])
    licensor_type = require_enum(body, "licensor_type", LICENSOR_TYPES)
    licensor_name = require_str(body, "licensor_name")
    scope = require_enum(body, "exclusivity_scope", EXCL_SCOPES)
    sport = require_str(body, "sport_category")
    ts = parse_date(body["term_start_on"], "term_start_on")
    te = parse_date(body["term_end_on"], "term_end_on")
    model = require_enum(body, "royalty_model", ROYALTY_MODELS)
    rate = require_int(body, "royalty_rate_bps", 0)
    mg = require_int(body, "minimum_guarantee_cents", 0)
    recoup = body["mg_recoupable"]
    if not isinstance(recoup, bool):
        raise err_invalid_input("mg_recoupable must be boolean")
    window = require_int(body, "audit_window_days", 0)
    if te < ts:
        raise err_invalid_input("term_end_on must be >= term_start_on")
    rec = {
        "licensor_type": licensor_type,
        "licensor_name": licensor_name,
        "exclusivity_scope": scope,
        "sport_category": sport,
        "term_start_on": body["term_start_on"],
        "term_end_on": body["term_end_on"],
        "royalty_model": model,
        "royalty_rate_bps": rate,
        "minimum_guarantee_cents": mg,
        "mg_recoupable": recoup,
        "audit_window_days": window,
        "agreement_status": "DRAFT",
        "outstanding_royalty_cents": 0,
        "recouped_against_mg_cents": 0,
        "_term_start": ts,
        "_term_end": te,
    }
    stamp_new(rec)
    db.agreements[rec["id"]] = rec
    return ok_obj(H.serialize(rec), 201)


@bp.get("/licensing/agreements/<agreement_id>")
def get_agreement(agreement_id):
    require_roles("LicensingAdmin", "RightsOfficer", "FinanceController",
                  "LeagueAuditor", "UnionAuditor", "RosterOperator",
                  "RosterReviewer", "LiveOpsManager", "ComplianceReviewer")
    ag = H.get_agreement(agreement_id)
    return ok_obj(H.serialize(ag))


@bp.get("/licensing/agreements")
def list_agreements():
    require_roles("LicensingAdmin", "RightsOfficer", "FinanceController",
                  "LeagueAuditor", "UnionAuditor")
    limit, offset = pagination_params()
    from flask import request as req
    status = req.args.get("agreement_status")
    sport = req.args.get("sport_category")
    items, total = H.list_paginated(
        db.agreements.values(),
        [(status, "agreement_status"), (sport, "sport_category")],
        limit, offset)
    return ok_list(items, limit, offset, total)


@bp.post("/licensing/agreements/<agreement_id>/activate")
def activate_agreement(agreement_id):
    require_roles(*ADMIN)
    ag = H.get_agreement(agreement_id)
    if ag["agreement_status"] != "DRAFT":
        raise err_invalid_state("Agreement must be DRAFT to activate")
    today = db.now_date()
    if not (ag["_term_start"] <= today <= ag["_term_end"]):
        raise err_temporal("Clock date outside agreement term")
    if _exclusivity_conflict(ag):
        raise err_exclusivity()
    ag["agreement_status"] = "ACTIVE"
    touch(ag)
    return ok_obj(H.serialize(ag))


@bp.post("/licensing/agreements/<agreement_id>/suspend")
def suspend_agreement(agreement_id):
    require_roles(*ADMIN)
    ag = H.get_agreement(agreement_id)
    if ag["agreement_status"] != "ACTIVE":
        raise err_invalid_state("Agreement must be ACTIVE to suspend")
    ag["agreement_status"] = "SUSPENDED"
    touch(ag)
    for g in S.grants_of_agreement(ag["id"]):
        if g["grant_status"] == "GRANTED":
            S.suspend_grant(g, "AGREEMENT_SUSPENDED")
    return ok_obj(H.serialize(ag))


@bp.post("/licensing/agreements/<agreement_id>/reinstate")
def reinstate_agreement(agreement_id):
    require_roles(*ADMIN)
    ag = H.get_agreement(agreement_id)
    if ag["agreement_status"] != "SUSPENDED":
        raise err_invalid_state("Agreement must be SUSPENDED to reinstate")
    if db.now_date() > ag["_term_end"]:
        raise err_temporal("Clock date past term_end_on")
    ag["agreement_status"] = "ACTIVE"
    touch(ag)
    for g in S.grants_of_agreement(ag["id"]):
        if g["grant_status"] == "SUSPENDED" and g["suspended_reason"] == "AGREEMENT_SUSPENDED":
            S.reinstate_grant(g)
    return ok_obj(H.serialize(ag))


@bp.post("/licensing/agreements/<agreement_id>/terminate")
def terminate_agreement(agreement_id):
    require_roles(*ADMIN)
    ag = H.get_agreement(agreement_id)
    if ag["agreement_status"] != "SUSPENDED":
        raise err_invalid_state("Agreement must be SUSPENDED to terminate")
    for c in S.cases_of_agreement(ag["id"]):
        if c["audit_status"] in ("OPEN", "FINDINGS_FILED"):
            raise err_audit_blocks_termination()
    ag["agreement_status"] = "TERMINATED"
    touch(ag)
    S.cascade_agreement_terminate(ag)
    return ok_obj(H.serialize(ag))


# --- nested collection endpoints ------------------------------------------

@bp.get("/licensing/agreements/<agreement_id>/royalty-statements")
def list_agreement_statements(agreement_id):
    require_roles("LicensingAdmin", "FinanceController", "LeagueAuditor", "UnionAuditor")
    ag = H.get_agreement(agreement_id)
    limit, offset = pagination_params()
    items, total = H.list_paginated(S.statements_of_agreement(ag["id"]), [], limit, offset)
    return ok_list(items, limit, offset, total)


@bp.get("/licensing/agreements/<agreement_id>/audit-cases")
def list_agreement_cases(agreement_id):
    require_roles("LicensingAdmin", "FinanceController", "LeagueAuditor", "UnionAuditor")
    ag = H.get_agreement(agreement_id)
    limit, offset = pagination_params()
    items, total = H.list_paginated(S.cases_of_agreement(ag["id"]), [], limit, offset)
    return ok_list(items, limit, offset, total)


@bp.get("/licensing/agreements/<agreement_id>/likeness-grants")
def list_agreement_grants(agreement_id):
    require_roles("LicensingAdmin", "RightsOfficer", "FinanceController")
    ag = H.get_agreement(agreement_id)
    limit, offset = pagination_params()
    items, total = H.list_paginated(S.grants_of_agreement(ag["id"]), [], limit, offset)
    return ok_list(items, limit, offset, total)


@bp.get("/licensing/agreements/<agreement_id>/seasons")
def list_agreement_seasons(agreement_id):
    require_roles("LicensingAdmin", "LiveOpsManager", "FinanceController")
    ag = H.get_agreement(agreement_id)
    limit, offset = pagination_params()
    items, total = H.list_paginated(S.seasons_of_agreement(ag["id"]), [], limit, offset)
    return ok_list(items, limit, offset, total)
