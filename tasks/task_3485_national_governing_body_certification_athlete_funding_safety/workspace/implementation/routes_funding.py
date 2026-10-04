"""Funding agreements: stipends, insurance, science hours (PRD 3.5)."""
from flask import Blueprint, request

import calc
import cascades
import db
import timeutil
from constants import ALL_ROLES_READ
from envelope import respond_list, respond_object
from errors import ApiError, ERR_ATHLETE_NOT_ELIGIBLE, \
    ERR_AGREEMENT_WINDOW_OVERLAP, ERR_CYCLE_WINDOW_INVALID, \
    ERR_FUNDING_BUDGET_EXCEEDED, ERR_INSURANCE_NOT_ELIGIBLE, ERR_INVALID_STATE, \
    already_terminal, invalid_state, not_found
from routes_athletes import get_athlete_or_404
from validate import auth, body_json, check_athlete_ownership, \
    check_gb_ownership, req_datetime, req_enum, require_roles

bp = Blueprint("funding", __name__)

AGREEMENT_TRANSITION_STATES = ["ACTIVE", "SUSPENDED", "TERMINATED",
                               "INS_ENROLLED"]
POINTS_METHODS = ["TRAILING_365", "CALENDAR_SEASON"]


def get_agreement_or_404(fa_id):
    fa = db.get("funding_agreements", fa_id)
    if fa is None:
        raise not_found("funding agreement not found")
    return fa


@bp.route("/api/athletes/<athlete_id>/funding-agreements", methods=["POST"])
def create_agreement(athlete_id):
    _, role = auth()
    require_roles(role, ["CommitteeAdmin"])
    get_athlete_or_404(athlete_id)
    body = body_json()
    coverage_start = req_datetime(body, "coverage_start")
    coverage_end = req_datetime(body, "coverage_end")
    points_method = req_enum(body, "points_method", POINTS_METHODS)
    if coverage_end <= coverage_start:
        raise ApiError(ERR_CYCLE_WINDOW_INVALID, 422,
                       "coverage_end must be strictly after coverage_start")
    for other in db.all_of("funding_agreements"):
        if other["athlete_id"] != athlete_id \
                or other["status"] not in ("OFFERED", "ACTIVE", "SUSPENDED"):
            continue
        if coverage_start < other["coverage_end"] \
                and other["coverage_start"] < coverage_end:
            raise ApiError(ERR_AGREEMENT_WINDOW_OVERLAP, 409,
                           "coverage window overlaps another non-terminal "
                           "agreement of this athlete")
    now = timeutil.now()
    trailing, season = calc.funding_points(athlete_id, now)
    tier = calc.tier_for(trailing if points_method == "TRAILING_365" else season)
    fa = db.create("funding_agreements", {
        "athlete_id": athlete_id,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "points_method": points_method,
        "trailing_points": trailing,
        "season_points": season,
        "tier": tier,
        "monthly_stipend_cents": calc.stipend_for(tier),
        "status": "OFFERED",
        "insurance_status": "INS_NONE",
        "insurance_enrolled_at": None,
        "activated_at": None,
        "science_hours_allocated": 0,
    })
    return respond_object(fa, 201)


@bp.route("/api/athletes/<athlete_id>/funding-agreements", methods=["GET"])
def list_agreements(athlete_id):
    uid, role = auth()
    require_roles(role, ALL_ROLES_READ)
    check_athlete_ownership(uid, role, athlete_id)
    athlete = get_athlete_or_404(athlete_id)
    check_gb_ownership(uid, role, athlete["governing_body_id"])
    status = request.args.get("status") or None
    items = [fa for fa in db.all_of("funding_agreements")
             if fa["athlete_id"] == athlete_id
             and (status is None or fa["status"] == status)]
    return respond_list(db.sorted_created(items))


@bp.route("/api/funding-agreements/<fa_id>", methods=["GET"])
def read_agreement(fa_id):
    uid, role = auth()
    require_roles(role, ALL_ROLES_READ)
    fa = get_agreement_or_404(fa_id)
    check_athlete_ownership(uid, role, fa["athlete_id"])
    if role == "NGBAdmin":
        gb = cascades.gb_of_athlete(fa["athlete_id"])
        check_gb_ownership(uid, role, gb["id"] if gb else None)
    return respond_object(fa)


@bp.route("/api/funding-agreements/<fa_id>/transitions", methods=["POST"])
def agreement_transition(fa_id):
    _, role = auth()
    require_roles(role, ["CommitteeAdmin"])
    fa = get_agreement_or_404(fa_id)
    if fa["status"] == "TERMINATED":
        raise already_terminal("funding agreement is TERMINATED")
    body = body_json()
    to_state = req_enum(body, "to_state", AGREEMENT_TRANSITION_STATES)
    now = timeutil.now()
    athlete = get_athlete_or_404(fa["athlete_id"])
    gb = cascades.gb_of_athlete(fa["athlete_id"])

    if to_state == "ACTIVE":
        if fa["status"] == "ACTIVE":
            # Reassessment self-loop.
            old_stipend = fa["monthly_stipend_cents"]
            calc.recompute_agreement_points(fa, now)
            if fa["tier"] == "NONE":
                fa["status"] = "SUSPENDED"
                if fa["insurance_status"] == "INS_ENROLLED":
                    fa["insurance_status"] = "INS_LAPSED"
                db.mark("funding_agreements", fa)
                if gb is not None:
                    gb["committed_monthly_stipend_cents"] -= old_stipend
                    db.mark("governing_bodies", gb)
                    calc.run_waterfall(gb)
            else:
                new_stipend = fa["monthly_stipend_cents"]
                db.mark("funding_agreements", fa)
                if gb is not None:
                    gb["committed_monthly_stipend_cents"] += (new_stipend
                                                              - old_stipend)
                    db.mark("governing_bodies", gb)
                    calc.run_waterfall(gb)
            return respond_object(fa)
        # OFFERED -> ACTIVE (activate) or SUSPENDED -> ACTIVE (resume)
        if fa["status"] not in ("OFFERED", "SUSPENDED"):
            raise invalid_state("ACTIVE is only reachable from OFFERED, ACTIVE "
                                "(reassess) or SUSPENDED (resume)")
        if athlete["eligibility_status"] != "ELIGIBLE":
            raise ApiError(ERR_ATHLETE_NOT_ELIGIBLE, 409,
                           "athlete eligibility_status must be ELIGIBLE")
        if gb is not None and gb["status"] == "DECERTIFIED":
            raise invalid_state("athlete's governing body is DECERTIFIED")
        if fa["tier"] == "NONE":
            raise invalid_state("agreement tier is NONE")
        if fa["status"] == "OFFERED" and gb is not None:
            if (gb["committed_monthly_stipend_cents"]
                    + fa["monthly_stipend_cents"]) * 12 \
                    > gb["funding_budget_cents"]:
                raise ApiError(ERR_FUNDING_BUDGET_EXCEEDED, 422,
                               "activation exceeds the body's annual stipend "
                               "budget")
        if fa["status"] == "OFFERED":
            fa["activated_at"] = now
        cascades.resume_agreement(fa)  # committed += stipend, waterfall
        return respond_object(fa)

    if to_state == "SUSPENDED":
        raise invalid_state("SUSPENDED is cascade-only")

    if to_state == "TERMINATED":
        cascades.terminate_agreement(fa)
        return respond_object(fa)

    # INS_ENROLLED (insurance dimension)
    if fa["status"] != "ACTIVE":
        raise invalid_state("insurance enrollment requires an ACTIVE agreement")
    if fa["insurance_status"] not in ("INS_NONE", "INS_LAPSED"):
        raise invalid_state("insurance is already enrolled")
    if not calc.insurance_eligible(fa, now):
        raise ApiError(ERR_INSURANCE_NOT_ELIGIBLE, 422,
                       "insurance eligibility requires operative points >= 60 "
                       "and the 30-day wait from activation")
    fa["insurance_status"] = "INS_ENROLLED"
    fa["insurance_enrolled_at"] = now
    db.mark("funding_agreements", fa)
    return respond_object(fa)
