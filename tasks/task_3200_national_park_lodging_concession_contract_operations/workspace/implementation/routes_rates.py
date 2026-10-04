"""Comparability studies and rate filings."""
from flask import Blueprint, request

from db import store
from errors import err, not_found
from helpers import (new_entity, serialize, paginate, require_fields, req_int,
                     parse_dt, round_half_up, touch)
from middleware import require_role, require_read_role
from response import ok
from routes_contracts import get_contract, require_operational
from routes_setup import get_season

bp = Blueprint("rates", __name__)

RATE_CAP_MULTIPLIER = 1.05
BANDS = {"SOLO", "DOUBLE", "FAMILY"}


def get_study(cid, sid):
    st = store.studies.get(sid)
    if not st or st["contract_id"] != cid:
        raise not_found("study")
    return st


def get_filing(cid, fid):
    f = store.filings.get(fid)
    if not f or f["contract_id"] != cid:
        raise not_found("filing")
    return f


# ----- Studies -----

@bp.post("/contracts/<cid>/comparability-studies")
def create_study(cid):
    require_role("AgencyRateAnalyst")
    c = get_contract(cid)
    require_operational(c)
    body = request.get_json(silent=True)
    require_fields(body, ["title", "comparables", "prepared_at", "valid_through"])
    if not isinstance(body["title"], str) or not body["title"]:
        raise err("ERR_INVALID_REQUEST", 400, "title required")
    comps = body["comparables"]
    if not isinstance(comps, list) or len(comps) < 3:
        raise err("ERR_INVALID_REQUEST", 400, "at least 3 comparables required")
    num = 0
    den = 0.0
    for comp in comps:
        if not isinstance(comp, dict):
            raise err("ERR_INVALID_REQUEST", 400, "invalid comparable")
        rate = comp.get("nightly_rate_cents")
        w = comp.get("weight")
        if isinstance(rate, bool) or not isinstance(rate, int) or rate <= 0:
            raise err("ERR_INVALID_REQUEST", 400, "nightly_rate_cents must be positive integer")
        if isinstance(w, bool) or not isinstance(w, (int, float)) or w <= 0:
            raise err("ERR_INVALID_REQUEST", 400, "weight must be > 0")
        if not isinstance(comp.get("property_name"), str) or not comp["property_name"]:
            raise err("ERR_INVALID_REQUEST", 400, "property_name required")
        num += rate * w
        den += w
    prepared = parse_dt(body["prepared_at"], "prepared_at")
    valid = parse_dt(body["valid_through"], "valid_through")
    if valid <= prepared:
        raise err("ERR_INVALID_DATE_RANGE", 422, "valid_through must be after prepared_at")
    from decimal import Decimal
    wm = round_half_up(Decimal(str(num)) / Decimal(str(den)))
    st = new_entity({
        "contract_id": cid,
        "title": body["title"],
        "comparables": comps,
        "weighted_mean_cents": wm,
        "prepared_at": body["prepared_at"],
        "valid_through": body["valid_through"],
        "status": "REGISTERED",
    })
    store.studies[st["id"]] = st
    return ok(serialize(st), 201)


@bp.get("/contracts/<cid>/comparability-studies")
def list_studies(cid):
    require_read_role()
    get_contract(cid)
    items = [s for s in store.studies.values() if s["contract_id"] == cid]
    page, limit, offset, total = paginate(items)
    return ok(page, 200, True, limit, offset, total)


@bp.get("/contracts/<cid>/comparability-studies/<sid>")
def get_study_route(cid, sid):
    require_read_role()
    get_contract(cid)
    return ok(serialize(get_study(cid, sid)))


# ----- Rate filings -----

def _validate_rates(rates):
    if not isinstance(rates, list) or len(rates) != 3:
        raise err("ERR_INVALID_REQUEST", 400, "submitted_rates must have exactly three entries")
    seen = {}
    for e in rates:
        if not isinstance(e, dict):
            raise err("ERR_INVALID_REQUEST", 400, "invalid rate entry")
        band = e.get("occupancy_band")
        rate = e.get("nightly_rate_cents")
        if band not in BANDS:
            raise err("ERR_INVALID_REQUEST", 400, "occupancy_band must be SOLO/DOUBLE/FAMILY")
        if isinstance(rate, bool) or not isinstance(rate, int) or rate <= 0:
            raise err("ERR_INVALID_REQUEST", 400, "nightly_rate_cents must be positive integer")
        if band in seen:
            raise err("ERR_INVALID_REQUEST", 400, "one entry per band")
        seen[band] = rate
    if set(seen) != BANDS:
        raise err("ERR_INVALID_REQUEST", 400, "one entry per band")
    return seen


@bp.post("/contracts/<cid>/rate-filings")
def create_filing(cid):
    uid, _ = require_role("ConcessionerRateManager")
    c = get_contract(cid)
    body = request.get_json(silent=True)
    require_fields(body, ["season_id", "room_class_id", "submitted_rates", "reference_study_id",
                          "expected_contract_version"])
    # body FK existence within contract
    season = store.seasons.get(body["season_id"])
    if not season or season["contract_id"] != cid:
        raise not_found("season")
    rc = store.room_classes.get(body["room_class_id"])
    if not rc or rc["contract_id"] != cid:
        raise not_found("room_class")
    study = store.studies.get(body["reference_study_id"])
    if not study or study["contract_id"] != cid:
        raise not_found("study")
    revision_of_id = body.get("revision_of_id")
    prior = None
    if revision_of_id is not None:
        prior = store.filings.get(revision_of_id)
        if not prior or prior["contract_id"] != cid:
            raise not_found("filing")
    require_operational(c)
    rates = _validate_rates(body["submitted_rates"])
    # revision rules
    if revision_of_id is not None:
        if prior["status"] != "REJECTED":
            raise err("ERR_INVALID_STATE", 409, "revision_of_id must reference a REJECTED filing")
        if prior["season_id"] != body["season_id"] or prior["room_class_id"] != body["room_class_id"]:
            raise err("ERR_INVALID_REQUEST", 400, "revision must cover the same season and room class")
    # cross-entity state
    if season["status"] not in ("PLANNED", "OPEN"):
        raise err("ERR_SEASON_NOT_OPEN_FOR_FILING", 409, "Filings only accepted while season is PLANNED or OPEN")
    if rc["status"] != "ACTIVE":
        raise err("ERR_ROOM_CLASS_INACTIVE", 409, "Room class inactive")
    # temporal: study validity vs season open
    if parse_dt(study["valid_through"]) < parse_dt(season["open_date"]):
        raise err("ERR_STUDY_EXPIRED", 422, "Study valid_through is before the season open_date")
    # OCC
    ev = body["expected_contract_version"]
    if isinstance(ev, bool) or not isinstance(ev, int):
        raise err("ERR_INVALID_REQUEST", 400, "expected_contract_version must be an integer")
    if ev != c["version"]:
        raise err("ERR_STALE_CONTRACT_VERSION", 412, "Stale contract version")
    # supersede any prior SUBMITTED filing for the same slot
    for f in store.filings.values():
        if (f["contract_id"] == cid and f["season_id"] == body["season_id"]
                and f["room_class_id"] == body["room_class_id"] and f["status"] == "SUBMITTED"):
            f["status"] = "SUPERSEDED"
            touch(f)
    f = new_entity({
        "contract_id": cid,
        "season_id": body["season_id"],
        "room_class_id": body["room_class_id"],
        "submitted_rates": body["submitted_rates"],
        "reference_study_id": body["reference_study_id"],
        "status": "SUBMITTED",
        "effective_date": None,
        "approved_weighted_mean_cents": None,
        "revision_of_id": revision_of_id,
        "_submitted_by_user_id": uid,
    })
    store.filings[f["id"]] = f
    touch(c)
    return ok(serialize(f), 201)


@bp.get("/contracts/<cid>/rate-filings")
def list_filings(cid):
    require_read_role()
    get_contract(cid)
    items = [f for f in store.filings.values() if f["contract_id"] == cid]
    for key in ("season_id", "room_class_id", "reference_study_id", "revision_of_id", "status"):
        v = request.args.get(key)
        if v:
            items = [f for f in items if str(f.get(key)) == v]
    page, limit, offset, total = paginate(items)
    return ok(page, 200, True, limit, offset, total)


@bp.get("/contracts/<cid>/rate-filings/<fid>")
def get_filing_route(cid, fid):
    require_read_role()
    get_contract(cid)
    return ok(serialize(get_filing(cid, fid)))


@bp.post("/contracts/<cid>/rate-filings/<fid>/start-review")
def start_review(cid, fid):
    require_role("AgencyRateAnalyst")
    get_contract(cid)
    f = get_filing(cid, fid)
    if f["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", 409, "Filing must be SUBMITTED")
    study = store.studies.get(f["reference_study_id"])
    if not study or study["status"] != "REGISTERED":
        raise err("ERR_STUDY_NOT_CURRENT", 409, "Cited study is not REGISTERED")
    f["status"] = "UNDER_REVIEW"
    touch(f)
    return ok(serialize(f))


@bp.post("/contracts/<cid>/rate-filings/<fid>/approve")
def approve_filing(cid, fid):
    uid, _ = require_role("AgencyRateAnalyst")
    c = get_contract(cid)
    f = get_filing(cid, fid)
    if f["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", 409, "Filing must be UNDER_REVIEW")
    study = store.studies.get(f["reference_study_id"])
    if not study or study["status"] != "REGISTERED":
        raise err("ERR_STUDY_NOT_CURRENT", 409, "Cited study is not REGISTERED at approval")
    # rate cap
    from decimal import Decimal
    cap = round_half_up(Decimal(study["weighted_mean_cents"]) * Decimal("1.05"))
    for e in f["submitted_rates"]:
        if e["nightly_rate_cents"] > cap:
            raise err("ERR_RATE_EXCEEDS_COMPARABILITY", 422, "A band rate exceeds the comparability cap")
    # SoD
    if f.get("_submitted_by_user_id") == uid:
        raise err("ERR_SEGREGATION_OF_DUTIES", 403, "Approver must differ from submitter")
    season = store.seasons.get(f["season_id"])
    f["status"] = "APPROVED"
    f["effective_date"] = season["open_date"] if season else None
    f["approved_weighted_mean_cents"] = study["weighted_mean_cents"]
    touch(f)
    for other in store.filings.values():
        if (other["id"] != f["id"] and other["contract_id"] == cid
                and other["season_id"] == f["season_id"] and other["room_class_id"] == f["room_class_id"]
                and other["status"] == "APPROVED"):
            other["status"] = "SUPERSEDED"
            touch(other)
    touch(c)
    return ok(serialize(f))


@bp.post("/contracts/<cid>/rate-filings/<fid>/reject")
def reject_filing(cid, fid):
    require_role("AgencyRateAnalyst")
    get_contract(cid)
    f = get_filing(cid, fid)
    if f["status"] not in ("SUBMITTED", "UNDER_REVIEW"):
        raise err("ERR_INVALID_STATE", 409, "Filing must be SUBMITTED or UNDER_REVIEW")
    body = request.get_json(silent=True) or {}
    if not isinstance(body.get("reason"), str) or not body["reason"]:
        raise err("ERR_INVALID_REQUEST", 400, "reason required")
    f["status"] = "REJECTED"
    touch(f)
    return ok(serialize(f))
