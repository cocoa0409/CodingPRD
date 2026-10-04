"""Roster batch and entry endpoints."""
from __future__ import annotations

from flask import Blueprint, request

import helpers as H
import services as S
from db import db
from errors import (err_athlete_not_eligible, err_empty_batch,
                    err_invalid_input, err_invalid_state, err_rollback_not_head,
                    err_sod, err_stale_season)
from middleware import require_roles
from response import (body_json, ok_list, ok_obj, opt_int, pagination_params,
                      require_enum, require_fields, require_int, require_str,
                      stamp_new, touch)

bp = Blueprint("roster", __name__)

ENTRY_KINDS = {"ADD", "UPDATE_ATTRIBUTE", "TRANSACTION", "REMOVE", "APPEARANCE"}
OPERATOR = ("RosterOperator",)
REVIEWER = ("RosterReviewer",)
ROSTER_READERS = ("LicensingAdmin", "LiveOpsManager", "RosterOperator", "RosterReviewer")


@bp.post("/licensing/roster-batches")
def create_batch():
    uid, _ = require_roles(*OPERATOR)
    body = body_json()
    require_fields(body, ["season_id", "batch_label", "submitted_by"])
    season = H.get_season(body["season_id"])
    label = require_str(body, "batch_label")
    submitted_by = require_str(body, "submitted_by")
    rec = {
        "season_id": season["id"],
        "batch_label": label,
        "batch_status": "DRAFT",
        "submitted_by": submitted_by,
        "supersedes_batch_id": None,
        "published_epoch": None,
    }
    stamp_new(rec)
    db.roster_batches[rec["id"]] = rec
    return ok_obj(H.serialize(rec), 201)


@bp.get("/licensing/roster-batches/<batch_id>")
def get_batch(batch_id):
    require_roles(*ROSTER_READERS)
    b = H.get_batch(batch_id)
    return ok_obj(H.serialize(b))


@bp.get("/licensing/roster-batches")
def list_batches():
    require_roles(*ROSTER_READERS)
    limit, offset = pagination_params()
    season_id = request.args.get("season_id")
    status = request.args.get("batch_status")
    supersedes = request.args.get("supersedes_batch_id")
    items, total = H.list_paginated(
        db.roster_batches.values(),
        [(season_id, "season_id"), (status, "batch_status"),
         (supersedes, "supersedes_batch_id")],
        limit, offset)
    return ok_list(items, limit, offset, total)


@bp.post("/licensing/roster-batches/<batch_id>/entries")
def add_entry(batch_id):
    require_roles(*OPERATOR)
    batch = H.get_batch(batch_id)
    body = body_json()
    require_fields(body, ["athlete_id", "entry_kind"])
    athlete = H.get_athlete(body["athlete_id"])
    kind = require_enum(body, "entry_kind", ENTRY_KINDS)
    if batch["batch_status"] != "DRAFT":
        raise err_invalid_state("Entries may only be added to a DRAFT batch")
    rating = opt_int(body, "overall_rating")
    detail = body.get("transaction_detail")
    if detail is not None and not isinstance(detail, str):
        raise err_invalid_input("transaction_detail must be a string")
    if kind in ("ADD", "UPDATE_ATTRIBUTE"):
        if rating is None:
            raise err_invalid_input("overall_rating required for ADD/UPDATE_ATTRIBUTE")
        if rating < 40 or rating > 99:
            raise err_invalid_input("overall_rating must be in 40..99")
    rec = {
        "batch_id": batch["id"],
        "athlete_id": athlete["id"],
        "entry_kind": kind,
        "overall_rating": rating,
        "transaction_detail": detail,
        "entry_status": "STAGED",
        "_seq": batch.get("_entry_seq", 0) + 1,
    }
    batch["_entry_seq"] = rec["_seq"]
    stamp_new(rec)
    db.roster_entries[rec["id"]] = rec
    return ok_obj(H.serialize(rec), 201)


@bp.get("/licensing/roster-batches/<batch_id>/entries")
def list_entries(batch_id):
    require_roles(*ROSTER_READERS)
    batch = H.get_batch(batch_id)
    limit, offset = pagination_params()
    rows = [e for e in db.roster_entries.values() if e["batch_id"] == batch["id"]]
    items, total = H.list_paginated(rows, [], limit, offset)
    return ok_list(items, limit, offset, total)


def _batch_entries(batch_id):
    rows = [e for e in db.roster_entries.values() if e["batch_id"] == batch_id]
    rows.sort(key=lambda e: (e.get("created_at", ""), e.get("_seq", 0)))
    return rows


@bp.post("/licensing/roster-batches/<batch_id>/validate")
def validate_batch(batch_id):
    require_roles(*OPERATOR)
    batch = H.get_batch(batch_id)
    if batch["batch_status"] != "DRAFT":
        raise err_invalid_state("Batch must be DRAFT to validate")
    entries = _batch_entries(batch["id"])
    if not entries:
        raise err_empty_batch()
    for e in entries:
        athlete = H.get_athlete(e["athlete_id"])
        if e["entry_kind"] in ("ADD", "UPDATE_ATTRIBUTE"):
            if athlete["athlete_status"] != "ELIGIBLE":
                raise err_athlete_not_eligible(
                    f"Athlete {athlete['id']} is not ELIGIBLE")
            r = e.get("overall_rating")
            if r is None or r < 40 or r > 99:
                raise err_invalid_input("overall_rating must be in 40..99")
    batch["batch_status"] = "VALIDATED"
    touch(batch)
    return ok_obj(H.serialize(batch))


@bp.post("/licensing/roster-batches/<batch_id>/reject")
def reject_batch(batch_id):
    require_roles(*REVIEWER)
    batch = H.get_batch(batch_id)
    if batch["batch_status"] not in ("DRAFT", "VALIDATED"):
        raise err_invalid_state("Batch must be DRAFT or VALIDATED to reject")
    batch["batch_status"] = "REJECTED"
    touch(batch)
    for e in _batch_entries(batch["id"]):
        if e["entry_status"] == "STAGED":
            e["entry_status"] = "DROPPED"
            touch(e)
    return ok_obj(H.serialize(batch))


@bp.post("/licensing/roster-batches/<batch_id>/publish")
def publish_batch(batch_id):
    uid, _ = require_roles(*REVIEWER)
    batch = H.get_batch(batch_id)
    body = body_json()
    esv = body.get("expected_season_version")
    if isinstance(esv, bool) or not isinstance(esv, int):
        raise err_invalid_input("expected_season_version is required and must be an integer")
    season = H.get_season(batch["season_id"])
    if batch["batch_status"] != "VALIDATED":
        raise err_invalid_state("Batch must be VALIDATED to publish")
    entries = _batch_entries(batch["id"])
    if not entries:
        raise err_empty_batch()
    if batch["submitted_by"] == uid:
        raise err_sod("Publishing reviewer must differ from submitting operator")
    if esv != season["version"]:
        raise err_stale_season()
    # publish
    prior = None
    for b in db.roster_batches.values():
        if (b["season_id"] == season["id"] and b["batch_status"] == "PUBLISHED"
                and b["id"] != batch["id"]):
            prior = b
            break
    season["roster_epoch"] = season["roster_epoch"] + 1
    batch["published_epoch"] = season["roster_epoch"]
    if prior is not None:
        prior["batch_status"] = "SUPERSEDED"
        touch(prior)
        batch["supersedes_batch_id"] = prior["id"]
    else:
        batch["supersedes_batch_id"] = None
    batch["batch_status"] = "PUBLISHED"
    touch(batch)
    # apply entries in created_at ASC order; last write wins per athlete
    for e in entries:
        if e["entry_status"] == "STAGED":
            e["entry_status"] = "APPLIED"
            touch(e)
        if e["entry_kind"] in ("ADD", "UPDATE_ATTRIBUTE"):
            athlete = db.athletes.get(e["athlete_id"])
            if athlete is not None:
                athlete["current_overall_rating"] = e["overall_rating"]
                touch(athlete)
    touch(season)
    return ok_obj(H.serialize(batch))


@bp.post("/licensing/roster-batches/<batch_id>/rollback")
def rollback_batch(batch_id):
    require_roles(*REVIEWER)
    batch = H.get_batch(batch_id)
    season = H.get_season(batch["season_id"])
    if batch["batch_status"] != "PUBLISHED":
        raise err_rollback_not_head("Batch is not PUBLISHED")
    if batch["published_epoch"] != season["roster_epoch"]:
        raise err_rollback_not_head("Batch is not the most recently published batch")
    # capture applied ratings of this batch before flipping status
    batch_ratings = {}
    for e in _batch_entries(batch["id"]):
        if e["entry_kind"] in ("ADD", "UPDATE_ATTRIBUTE") and e["entry_status"] == "APPLIED":
            batch_ratings[e["athlete_id"]] = e["overall_rating"]
    batch["batch_status"] = "ROLLED_BACK"
    touch(batch)
    prev = None
    if batch.get("supersedes_batch_id"):
        prev = db.roster_batches.get(batch["supersedes_batch_id"])
    if prev is not None and prev["batch_status"] == "SUPERSEDED":
        prev["batch_status"] = "PUBLISHED"
        touch(prev)
    # revert ratings: restore from superseded batch's applied values
    for athlete_id in batch_ratings:
        new_rating = None
        if prev is not None:
            for e in _batch_entries(prev["id"]):
                if (e["athlete_id"] == athlete_id
                        and e["entry_kind"] in ("ADD", "UPDATE_ATTRIBUTE")
                        and e["entry_status"] == "APPLIED"):
                    new_rating = e["overall_rating"]
        athlete = db.athletes.get(athlete_id)
        if athlete is not None and athlete["current_overall_rating"] != new_rating:
            athlete["current_overall_rating"] = new_rating
            touch(athlete)
    season["roster_epoch"] = season["roster_epoch"] - 1
    touch(season)
    return ok_obj(H.serialize(batch))
