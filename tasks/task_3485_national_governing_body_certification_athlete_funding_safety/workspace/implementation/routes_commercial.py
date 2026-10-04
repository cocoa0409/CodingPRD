"""Commercial deals licensing athlete image rights (PRD 3.7, OCC per 2.7)."""
from flask import Blueprint, request

import calc
import cascades
import db
import timeutil
from constants import ALL_ROLES_READ, BODY_STANDING_OK, \
    DEAL_EXCLUSIVITY_MIN_GAP_DAYS
from envelope import respond_list, respond_object
from errors import ApiError, ERR_CYCLE_WINDOW_INVALID, \
    ERR_DEAL_CONSENT_REQUIRED, ERR_DEAL_EXCLUSIVITY_OVERLAP, ERR_INVALID_STATE, \
    ERR_STALE_VERSION, already_terminal, invalid_state, not_found, unauthorized
from routes_athletes import get_athlete_or_404
from validate import auth, body_json, check_athlete_ownership, \
    check_gb_ownership, req_datetime, req_enum, req_int, req_str, \
    req_version, require_roles

bp = Blueprint("commercial", __name__)

DEAL_BASES = ["GROSS_BASIS", "NET_BASIS"]
DEAL_TRANSITION_STATES = ["CONSENT_GRANTED", "ACTIVE", "TERMINATED"]
DEAL_NON_TERMINAL = ("PROPOSED", "CONSENT_GRANTED", "ACTIVE")


def get_deal_or_404(deal_id):
    deal = db.get("commercial_deals", deal_id)
    if deal is None:
        raise not_found("commercial deal not found")
    return deal


@bp.route("/api/athletes/<athlete_id>/commercial-deals", methods=["POST"])
def create_deal(athlete_id):
    uid, role = auth()
    require_roles(role, ["CommitteeAdmin", "NGBAdmin"])
    athlete = get_athlete_or_404(athlete_id)
    check_gb_ownership(uid, role, athlete["governing_body_id"])
    body = body_json()
    sponsor_name = req_str(body, "sponsor_name")
    gross_value_cents = req_int(body, "gross_value_cents")
    basis = req_enum(body, "basis", DEAL_BASES)
    exclusivity_start = req_datetime(body, "exclusivity_start")
    exclusivity_end = req_datetime(body, "exclusivity_end")
    if exclusivity_end < exclusivity_start:
        raise ApiError(ERR_CYCLE_WINDOW_INVALID, 422,
                       "exclusivity_end must be at or after exclusivity_start")
    gap = timeutil.days(DEAL_EXCLUSIVITY_MIN_GAP_DAYS)
    for other in db.all_of("commercial_deals"):
        if other["athlete_id"] != athlete_id \
                or other["status"] not in DEAL_NON_TERMINAL:
            continue
        # Closed intervals: overlap OR gap smaller than one full day rejects.
        if not (exclusivity_start >= other["exclusivity_end"] + gap
                or other["exclusivity_start"] >= exclusivity_end + gap):
            raise ApiError(ERR_DEAL_EXCLUSIVITY_OVERLAP, 409,
                           "exclusivity window overlaps or sits within one day "
                           "of another non-terminal deal of this athlete")
    deal = db.create("commercial_deals", {
        "athlete_id": athlete_id,
        "sponsor_name": sponsor_name,
        "gross_value_cents": gross_value_cents,
        "basis": basis,
        "exclusivity_start": exclusivity_start,
        "exclusivity_end": exclusivity_end,
        "status": "PROPOSED",
        "committee_share_cents": None,
        "ngb_share_cents": None,
        "athlete_share_cents": None,
        "consented_at": None,
        "activated_at": None,
    })
    return respond_object(deal, 201)


@bp.route("/api/athletes/<athlete_id>/commercial-deals", methods=["GET"])
def list_deals(athlete_id):
    uid, role = auth()
    require_roles(role, ALL_ROLES_READ)
    check_athlete_ownership(uid, role, athlete_id)
    athlete = get_athlete_or_404(athlete_id)
    check_gb_ownership(uid, role, athlete["governing_body_id"])
    status = request.args.get("status") or None
    now = timeutil.now()
    items = []
    for deal in db.all_of("commercial_deals"):
        if deal["athlete_id"] != athlete_id:
            continue
        cascades.due_deal(deal, now)
        if status is not None and deal["status"] != status:
            continue
        items.append(deal)
    return respond_list(db.sorted_created(items))


@bp.route("/api/commercial-deals/<deal_id>/transitions", methods=["POST"])
def deal_transition(deal_id):
    uid, role = auth()
    require_roles(role, ["Athlete", "CommitteeAdmin"])
    deal = get_deal_or_404(deal_id)
    if deal["status"] in ("EXPIRED", "TERMINATED"):
        raise already_terminal("commercial deal is terminal")
    body = body_json()
    to_state = req_enum(body, "to_state", DEAL_TRANSITION_STATES)
    now = timeutil.now()

    if to_state == "CONSENT_GRANTED":
        if role != "Athlete" or uid != deal["athlete_id"]:
            raise unauthorized("only the subject athlete may consent")
    else:
        if role != "CommitteeAdmin":
            raise unauthorized("only a CommitteeAdmin may %s a deal"
                               % ("activate" if to_state == "ACTIVE"
                                  else "terminate"))

    if to_state == "CONSENT_GRANTED":
        if deal["status"] != "PROPOSED":
            raise invalid_state("CONSENT_GRANTED is only reachable from "
                                "PROPOSED")
        athlete = db.get("athletes", deal["athlete_id"])
        if athlete is not None and athlete["eligibility_status"] == "RETIRED":
            raise invalid_state("a retired athlete cannot consent")
    elif to_state == "ACTIVE":
        if deal["status"] == "PROPOSED":
            raise ApiError(ERR_DEAL_CONSENT_REQUIRED, 409,
                           "athlete consent is required before activation")
        if deal["status"] != "CONSENT_GRANTED":
            raise invalid_state("ACTIVE is only reachable from "
                                "CONSENT_GRANTED")
        gb = cascades.gb_of_athlete(deal["athlete_id"])
        if gb is None or gb["status"] not in BODY_STANDING_OK:
            raise invalid_state("athlete's governing body standing does not "
                                "permit activation")
    else:  # TERMINATED
        if deal["status"] not in DEAL_NON_TERMINAL:
            raise invalid_state("deal is already terminal")

    # Tier 7/10: the OCC field is non-optional; the match check is last.
    expected = req_version(body, "expected_deal_version")
    if expected != deal["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_deal_version does not match the deal's "
                       "current version")

    if to_state == "CONSENT_GRANTED":
        deal["consented_at"] = now
        deal["status"] = "CONSENT_GRANTED"
    elif to_state == "ACTIVE":
        committee, ngb, athlete_share = calc.revenue_split(
            deal["gross_value_cents"], deal["basis"])
        deal["committee_share_cents"] = committee
        deal["ngb_share_cents"] = ngb
        deal["athlete_share_cents"] = athlete_share
        deal["activated_at"] = now
        deal["status"] = "ACTIVE"
    else:
        deal["status"] = "TERMINATED"
    db.mark("commercial_deals", deal)
    return respond_object(deal)
