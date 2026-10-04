"""Athlete endpoints."""
from __future__ import annotations

from flask import Blueprint, request

import helpers as H
import services as S
from db import db
from errors import err_invalid_input
from middleware import require_roles
from response import (body_json, ok_list, ok_obj, pagination_params,
                      require_enum, require_fields, require_str, stamp_new)

bp = Blueprint("athletes", __name__)

ATHLETE_CLASSES = {"ACTIVE_PRO", "RETIRED", "COLLEGE"}


@bp.post("/licensing/athletes")
def create_athlete():
    require_roles("RightsOfficer")
    body = body_json()
    require_fields(body, ["full_name", "sport_category", "athlete_class", "college_opt_in"])
    name = require_str(body, "full_name")
    sport = require_str(body, "sport_category")
    klass = require_enum(body, "athlete_class", ATHLETE_CLASSES)
    opt_in = body["college_opt_in"]
    if not isinstance(opt_in, bool):
        raise err_invalid_input("college_opt_in must be boolean")
    if klass != "COLLEGE" and opt_in:
        raise err_invalid_input("college_opt_in must be false unless athlete_class is COLLEGE")
    rec = {
        "full_name": name,
        "sport_category": sport,
        "athlete_class": klass,
        "college_opt_in": opt_in,
        "athlete_status": "INELIGIBLE",
        "current_overall_rating": None,
    }
    stamp_new(rec)
    db.athletes[rec["id"]] = rec
    return ok_obj(H.serialize(rec), 201)


@bp.get("/licensing/athletes/<athlete_id>")
def get_athlete(athlete_id):
    require_roles("LicensingAdmin", "RightsOfficer", "RosterOperator",
                  "RosterReviewer", "LiveOpsManager", "FinanceController")
    a = H.get_athlete(athlete_id)
    return ok_obj(H.serialize(a))


@bp.get("/licensing/athletes")
def list_athletes():
    require_roles("LicensingAdmin", "RightsOfficer", "RosterOperator",
                  "RosterReviewer", "LiveOpsManager")
    limit, offset = pagination_params()
    sport = request.args.get("sport_category")
    klass = request.args.get("athlete_class")
    status = request.args.get("athlete_status")
    items, total = H.list_paginated(
        db.athletes.values(),
        [(sport, "sport_category"), (klass, "athlete_class"), (status, "athlete_status")],
        limit, offset)
    return ok_list(items, limit, offset, total)


@bp.get("/licensing/athletes/<athlete_id>/likeness-grants")
def athlete_grants(athlete_id):
    require_roles("LicensingAdmin", "RightsOfficer", "FinanceController")
    a = H.get_athlete(athlete_id)
    limit, offset = pagination_params()
    items, total = H.list_paginated(S.grants_of_athlete(a["id"]), [], limit, offset)
    return ok_list(items, limit, offset, total)


@bp.get("/licensing/athletes/<athlete_id>/roster-entries")
def athlete_roster_entries(athlete_id):
    require_roles("LicensingAdmin", "RightsOfficer", "RosterOperator", "RosterReviewer")
    a = H.get_athlete(athlete_id)
    limit, offset = pagination_params()
    rows = [e for e in db.roster_entries.values() if e["athlete_id"] == a["id"]]
    items, total = H.list_paginated(rows, [], limit, offset)
    return ok_list(items, limit, offset, total)


@bp.get("/licensing/athletes/<athlete_id>/content-drops")
def athlete_drops(athlete_id):
    require_roles("LicensingAdmin", "RightsOfficer", "LiveOpsManager")
    a = H.get_athlete(athlete_id)
    limit, offset = pagination_params()
    items, total = H.list_paginated(S.drops_featuring(a["id"]), [], limit, offset)
    return ok_list(items, limit, offset, total)
