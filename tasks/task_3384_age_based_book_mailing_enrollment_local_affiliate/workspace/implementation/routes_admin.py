"""PlatformAdmin surface: logical clock, state programs, affiliates, penetration."""

from flask import Blueprint, request

import db
import domain
from errors import ApiError
from response import ok, created, listing
from validation import (
    require_roles, ALL_ROLES, body, check_allowed, req_string, req_int,
    opt_int, req_prefixes, check_month, parse_dt_raw, pagination,
)

bp = Blueprint("admin", __name__, url_prefix="/library")


def get_affiliate_or_404(aid):
    aff = db.affiliates.get(aid)
    if aff is None:
        raise ApiError(404, "ERR_AFFILIATE_NOT_FOUND", "Referenced affiliate id does not exist")
    return aff


def run_sweep():
    """Graduate over-age children and expire ACTIVE agreements past their window."""
    current_month = db.logical_month()
    now = db.get_clock()
    graduated = []
    for c in db.children.values():
        if (c["enrollment_status"] in domain.ACTIVE_CHILD_STATES
                and current_month > c["expected_final_mailing_month"]):
            c["enrollment_status"] = "GRADUATED"
            db.touch(c)
            graduated.append(c["id"])
    expired = []
    for a in db.agreements.values():
        if a["status"] == "ACTIVE" and now >= a["_to"]:
            a["status"] = "EXPIRED"
            db.touch(a)
            expired.append(a["id"])
    return graduated, expired


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles("PlatformAdmin")
    data = body()
    check_allowed(data, {"current_utc"})
    raw = req_string(data, "current_utc")
    dt = parse_dt_raw(raw)
    db.set_clock(dt)
    graduated, expired = run_sweep()
    return ok({
        "current_utc": raw,
        "graduated_child_ids": graduated,
        "expired_agreement_ids": expired,
    })


@bp.post("/state-programs")
def create_state_program():
    require_roles("PlatformAdmin")
    data = body()
    check_allowed(data, {"state_code", "name", "funding_share_bp",
                         "max_state_share_per_book_cents"})
    state_code = req_string(data, "state_code")
    name = req_string(data, "name")
    share_bp = req_int(data, "funding_share_bp", 0, 10000)
    cap = opt_int(data, "max_state_share_per_book_cents", 300, 0)
    for p in db.state_programs.values():
        if p["state_code"] == state_code:
            raise ApiError(400, "ERR_INVALID_REQUEST",
                           "state_code must be unique across state programs")
    rec = db.base_record()
    rec.update({
        "state_code": state_code,
        "name": name,
        "funding_share_bp": share_bp,
        "max_state_share_per_book_cents": cap,
    })
    db.state_programs[rec["id"]] = rec
    return created(domain.ser_state_program(rec))


@bp.post("/affiliates")
def create_affiliate():
    require_roles("PlatformAdmin")
    data = body()
    check_allowed(data, {"name", "state_program_id", "postal_prefixes", "contact_email"})
    name = req_string(data, "name")
    state_program_id = req_string(data, "state_program_id")
    prefixes = req_prefixes(data, "postal_prefixes")
    contact_email = req_string(data, "contact_email")
    if state_program_id not in db.state_programs:
        raise ApiError(404, "ERR_STATE_PROGRAM_NOT_FOUND",
                       "Referenced state program id does not exist")
    rec = db.base_record()
    rec.update({
        "name": name,
        "state_program_id": state_program_id,
        "postal_prefixes": prefixes,
        "contact_email": contact_email,
    })
    db.affiliates[rec["id"]] = rec
    return created(domain.ser_affiliate(rec))


@bp.get("/affiliates/<aid>")
def get_affiliate(aid):
    require_roles(*ALL_ROLES)
    return ok(domain.ser_affiliate(get_affiliate_or_404(aid)))


@bp.get("/affiliates")
def list_affiliates():
    require_roles(*ALL_ROLES)
    limit, offset = pagination()
    f_sp = request.args.get("state_program_id")
    f_name = request.args.get("name")
    rows = [a for a in db.affiliates.values()
            if (f_sp is None or a["state_program_id"] == f_sp)
            and (f_name is None or a["name"] == f_name)]
    rows.sort(key=lambda r: r["_seq"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return listing([domain.ser_affiliate(a) for a in page], limit, offset, total)


@bp.get("/affiliates/<aid>/penetration")
def penetration(aid):
    uid, role = require_roles(*ALL_ROLES)
    get_affiliate_or_404(aid)
    if role == "AffiliateCoordinator" and uid != aid:
        raise ApiError(403, "ERR_FORBIDDEN",
                       "Coordinator may only read their own affiliate")
    month = request.args.get("month")
    if month is None:
        month = db.logical_month()
    else:
        month = check_month(month)
    year = int(month[0:4])

    stats = [s for s in db.population_stats.values() if s["affiliate_id"] == aid]
    if stats:
        prior = [s for s in stats if s["effective_year"] <= year]
        if prior:
            chosen = max(prior, key=lambda s: s["effective_year"])
        else:
            chosen = min(stats, key=lambda s: s["effective_year"])
        eligible = chosen["eligible_population"]
        stat_year = chosen["effective_year"]
    else:
        eligible = 0
        stat_year = None

    enrolled = domain.enrolled_count(aid)
    snap_bp = (domain.round_half_up_ratio(enrolled * 10000, eligible)
               if eligible > 0 else None)

    lo = domain.month_add(month, -11)
    served = set()
    for it in db.items.values():
        if it["affiliate_id"] == aid and lo <= it["mailing_month"] <= month:
            served.add(it["child_id"])
    t12 = len(served)
    t12_bp = (domain.round_half_up_ratio(t12 * 10000, eligible)
              if eligible > 0 else None)

    return ok({
        "affiliate_id": aid,
        "month": month,
        "enrolled_count": enrolled,
        "eligible_population": eligible,
        "population_stat_year": stat_year,
        "penetration_snapshot_bp": snap_bp,
        "trailing_12_unique_children": t12,
        "penetration_trailing_12_bp": t12_bp,
    })
