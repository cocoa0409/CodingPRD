"""Regional edition endpoints."""
from __future__ import annotations

from flask import Blueprint

import helpers as H
import services as S
from db import db
from errors import (err_invalid_input, err_invalid_state, err_reference_state,
                    err_sod, err_temporal)
from middleware import require_roles
from response import (body_json, ok_obj, parse_date, require_fields,
                      require_str, stamp_new, touch)

bp = Blueprint("editions", __name__)


@bp.post("/licensing/editions")
def create_edition():
    uid, _ = require_roles("LiveOpsManager")
    body = body_json()
    require_fields(body, ["season_id", "region_code", "censorship_flags",
                          "embargo_until_on"])
    season = H.get_season(body["season_id"])
    region = require_str(body, "region_code")
    flags = body["censorship_flags"]
    if not isinstance(flags, list) or not all(isinstance(f, str) for f in flags):
        raise err_invalid_input("censorship_flags must be an array of strings")
    embargo = parse_date(body["embargo_until_on"], "embargo_until_on")
    rec = {
        "season_id": season["id"],
        "region_code": region,
        "edition_status": "DRAFT",
        "censorship_flags": flags,
        "embargo_until_on": body["embargo_until_on"],
        "_embargo": embargo,
        "_submitted_by": None,
        "_created_by": uid,
    }
    stamp_new(rec)
    db.editions[rec["id"]] = rec
    return ok_obj(H.serialize(rec), 201)


@bp.get("/licensing/editions/<edition_id>")
def get_edition(edition_id):
    require_roles("LicensingAdmin", "LiveOpsManager", "ComplianceReviewer")
    e = H.get_edition(edition_id)
    return ok_obj(H.serialize(e))


@bp.post("/licensing/editions/<edition_id>/submit-review")
def submit_review(edition_id):
    uid, _ = require_roles("LiveOpsManager")
    e = H.get_edition(edition_id)
    if e["edition_status"] != "DRAFT":
        raise err_invalid_state("Edition must be DRAFT to submit for review")
    e["edition_status"] = "IN_REVIEW"
    e["_submitted_by"] = uid
    touch(e)
    return ok_obj(H.serialize(e))


@bp.post("/licensing/editions/<edition_id>/approve")
def approve_edition(edition_id):
    uid, _ = require_roles("ComplianceReviewer")
    e = H.get_edition(edition_id)
    if e["edition_status"] != "IN_REVIEW":
        raise err_invalid_state("Edition must be IN_REVIEW to approve")
    if e.get("_submitted_by") is not None and e["_submitted_by"] == uid:
        raise err_sod("Approving reviewer must differ from submitting operator")
    e["edition_status"] = "APPROVED"
    touch(e)
    return ok_obj(H.serialize(e))


@bp.post("/licensing/editions/<edition_id>/return-to-draft")
def return_to_draft(edition_id):
    require_roles("ComplianceReviewer")
    e = H.get_edition(edition_id)
    if e["edition_status"] != "IN_REVIEW":
        raise err_invalid_state("Edition must be IN_REVIEW to return to draft")
    e["edition_status"] = "DRAFT"
    touch(e)
    return ok_obj(H.serialize(e))


@bp.post("/licensing/editions/<edition_id>/release")
def release_edition(edition_id):
    require_roles("LiveOpsManager")
    e = H.get_edition(edition_id)
    if e["edition_status"] != "APPROVED":
        raise err_invalid_state("Edition must be APPROVED to release")
    season = H.get_season(e["season_id"])
    if season["season_status"] != "LIVE":
        raise err_reference_state("Parent season is not LIVE")
    if db.now_date() < e["_embargo"]:
        raise err_temporal("Embargo date not reached")
    e["edition_status"] = "RELEASED"
    touch(e)
    return ok_obj(H.serialize(e))


@bp.post("/licensing/editions/<edition_id>/withdraw")
def withdraw_edition(edition_id):
    require_roles("ComplianceReviewer")
    e = H.get_edition(edition_id)
    if e["edition_status"] != "RELEASED":
        raise err_invalid_state("Edition must be RELEASED to withdraw")
    e["edition_status"] = "WITHDRAWN"
    touch(e)
    # re-evaluate drops whose content conflicts with this edition's flags
    flags = e.get("censorship_flags") or []
    if "NO_REAL_PLAYER_NAMES" in flags:
        for d in S.drops_of_season(e["season_id"]):
            if d["drop_status"] == "RELEASED" and d["drop_kind"] == "PLAYER_CARD":
                d["drop_status"] = "HELD"
                d["_held_reason"] = "CENSORSHIP"
                touch(d)
    return ok_obj(H.serialize(e))
