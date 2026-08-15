"""MarketSurvey + MarketCut (§3.3)."""
from datetime import date
from flask import Blueprint, request
from db import store, new_id
from middleware import require_roles, get_auth
from response import success_object, success_list
from errors import (
    not_found, invalid_request, invalid_enum, invalid_state_transition,
    already_terminal, cut_too_close,
)
from services.common import (
    now_iso, require_fields, parse_int, parse_iso_date, parse_pagination,
    sort_by_created_at, paginate, bump,
)
from services.pricing import _to_date

bp = Blueprint("market", __name__)

SURVEY_STATES = ["SUBMITTED", "ACCEPTED", "REJECTED"]


def survey_view(s):
    return {k: s[k] for k in ("id", "name", "publisher", "survey_year", "effective_date",
                              "status", "created_at", "updated_at", "version")}


def cut_view(c):
    return {k: c[k] for k in ("id", "market_survey_id", "job_profile_id", "geo_zone_id",
                              "p25_cents", "p50_cents", "p75_cents", "sample_size",
                              "effective_date", "excluded_from_composite",
                              "created_at", "updated_at", "version")}


@bp.route("/comp/market-surveys", methods=["POST"])
def create_survey():
    require_roles("CompAnalyst")
    body = request.get_json(silent=True) or {}
    require_fields(body, ["name", "publisher", "survey_year", "effective_date"])
    name = body["name"]
    if not isinstance(name, str) or not name:
        raise invalid_request("name must be a non-empty string")
    publisher = body["publisher"]
    if not isinstance(publisher, str) or not publisher:
        raise invalid_request("publisher must be a non-empty string")
    year = parse_int(body["survey_year"], "survey_year")
    eff = parse_iso_date(body["effective_date"], "effective_date")
    now = now_iso()
    s = {"id": new_id(), "name": name, "publisher": publisher, "survey_year": year,
         "effective_date": eff, "status": "SUBMITTED",
         "created_at": now, "updated_at": now, "version": 1}
    store.market_surveys[s["id"]] = s
    return success_object(survey_view(s), 201)


@bp.route("/comp/market-surveys", methods=["GET"])
def list_surveys():
    get_auth()
    limit, offset = parse_pagination(request.args)
    rows = list(store.market_surveys.values())
    status_filter = request.args.get("status")
    if status_filter is not None:
        if status_filter not in SURVEY_STATES:
            raise invalid_enum("status is not a declared member")
        rows = [s for s in rows if s["status"] == status_filter]
    rows = sort_by_created_at(rows)
    page, total = paginate(rows, limit, offset)
    return success_list([survey_view(s) for s in page], limit, offset, total)


@bp.route("/comp/market-surveys/<sid>", methods=["GET"])
def get_survey(sid):
    get_auth()
    s = store.market_surveys.get(sid)
    if s is None:
        raise not_found("market survey not found")
    return success_object(survey_view(s))


@bp.route("/comp/market-surveys/<sid>/accept", methods=["POST"])
def accept_survey(sid):
    require_roles("CompManager")
    s = store.market_surveys.get(sid)
    if s is None:
        raise not_found("market survey not found")
    if s["status"] in ("ACCEPTED", "REJECTED"):
        raise already_terminal("survey already terminal")
    if s["status"] != "SUBMITTED":
        raise invalid_state_transition("accept declared only from SUBMITTED")
    s["status"] = "ACCEPTED"
    bump(s)
    return success_object(survey_view(s))


@bp.route("/comp/market-surveys/<sid>/reject", methods=["POST"])
def reject_survey(sid):
    require_roles("CompManager")
    s = store.market_surveys.get(sid)
    if s is None:
        raise not_found("market survey not found")
    if s["status"] in ("ACCEPTED", "REJECTED"):
        raise already_terminal("survey already terminal")
    if s["status"] != "SUBMITTED":
        raise invalid_state_transition("reject declared only from SUBMITTED")
    s["status"] = "REJECTED"
    bump(s)
    return success_object(survey_view(s))


# ---------------- MarketCut ----------------

@bp.route("/comp/market-cuts", methods=["POST"])
def create_cut():
    require_roles("CompAnalyst")
    body = request.get_json(silent=True) or {}
    require_fields(body, ["market_survey_id", "job_profile_id", "geo_zone_id",
                          "p50_cents", "sample_size", "effective_date"])
    survey_id = body["market_survey_id"]
    profile_id = body["job_profile_id"]
    geo_id = body["geo_zone_id"]
    if survey_id not in store.market_surveys:
        raise not_found("market survey not found")
    if profile_id not in store.job_profiles:
        raise not_found("job profile not found")
    if geo_id not in store.geo_zones:
        raise not_found("geo zone not found")
    p50 = parse_int(body["p50_cents"], "p50_cents", minimum=0)
    sample_size = parse_int(body["sample_size"], "sample_size", minimum=1)
    eff = parse_iso_date(body["effective_date"], "effective_date")
    p25 = body.get("p25_cents")
    if p25 is not None:
        p25 = parse_int(p25, "p25_cents", minimum=0)
    p75 = body.get("p75_cents")
    if p75 is not None:
        p75 = parse_int(p75, "p75_cents", minimum=0)
    excluded = body.get("excluded_from_composite", False)
    if not isinstance(excluded, bool):
        raise invalid_request("excluded_from_composite must be a boolean")
    # 30-day separation per (job_profile_id, geo_zone_id)
    new_date = _to_date(eff)
    for c in store.market_cuts.values():
        if c["job_profile_id"] == profile_id and c["geo_zone_id"] == geo_id:
            existing = _to_date(c["effective_date"])
            if abs((new_date - existing).days) < 30:
                raise cut_too_close()
    now = now_iso()
    c = {"id": new_id(), "market_survey_id": survey_id, "job_profile_id": profile_id,
         "geo_zone_id": geo_id, "p25_cents": p25, "p50_cents": p50, "p75_cents": p75,
         "sample_size": sample_size, "effective_date": eff,
         "excluded_from_composite": excluded,
         "created_at": now, "updated_at": now, "version": 1}
    store.market_cuts[c["id"]] = c
    return success_object(cut_view(c), 201)


@bp.route("/comp/market-cuts", methods=["GET"])
def list_cuts():
    get_auth()
    limit, offset = parse_pagination(request.args)
    rows = list(store.market_cuts.values())
    for arg in ("market_survey_id", "job_profile_id", "geo_zone_id"):
        v = request.args.get(arg)
        if v is not None:
            rows = [c for c in rows if c[arg] == v]
    rows = sort_by_created_at(rows)
    page, total = paginate(rows, limit, offset)
    return success_list([cut_view(c) for c in page], limit, offset, total)


@bp.route("/comp/market-cuts/<cid>", methods=["GET"])
def get_cut(cid):
    get_auth()
    c = store.market_cuts.get(cid)
    if c is None:
        raise not_found("market cut not found")
    return success_object(cut_view(c))


@bp.route("/comp/market-cuts/<cid>/set-exclusion", methods=["POST"])
def set_exclusion(cid):
    require_roles("CompAnalyst")
    body = request.get_json(silent=True) or {}
    require_fields(body, ["excluded_from_composite"])
    c = store.market_cuts.get(cid)
    if c is None:
        raise not_found("market cut not found")
    excluded = body["excluded_from_composite"]
    if not isinstance(excluded, bool):
        raise invalid_request("excluded_from_composite must be a boolean")
    c["excluded_from_composite"] = excluded
    bump(c)
    return success_object(cut_view(c))
