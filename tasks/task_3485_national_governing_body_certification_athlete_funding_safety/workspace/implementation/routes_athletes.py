"""Athletes (PRD 3.3) and performance results (PRD 3.4)."""
from flask import Blueprint, request

import calc
import cascades
import db
import timeutil
from constants import ALL_ROLES_READ, SCREENING_VALIDITY_DAYS, \
    TRAINING_VALIDITY_DAYS
from envelope import respond_list, respond_object
from errors import ApiError, ERR_ATHLETE_NOT_ELIGIBLE, ERR_INVALID_REQUEST, \
    ERR_INVALID_STATE, ERR_SCORE_OUT_OF_RANGE, ERR_SEGREGATION_OF_DUTIES, \
    already_terminal, invalid_state, not_found, unauthorized
from validate import auth, body_json, check_athlete_ownership, \
    check_gb_ownership, opt_bool, req_date, req_datetime, req_enum, req_int, \
    req_str, require_roles

bp = Blueprint("athletes", __name__)

ATHLETE_TRANSITION_STATES = ["SCREENING_CLEARED", "SCREENING_FLAGGED",
                             "TRAINING_CURRENT", "ELIGIBLE", "SUSPENDED",
                             "RETIRED"]
RESULT_TRANSITION_STATES = ["VERIFIED", "REJECTED", "SUBMITTED"]
EVENT_GRADES = ["A", "B", "C"]


def get_athlete_or_404(athlete_id):
    athlete = db.get("athletes", athlete_id)
    if athlete is None:
        raise not_found("athlete not found")
    return athlete


def get_result_or_404(result_id):
    result = db.get("results", result_id)
    if result is None:
        raise not_found("performance result not found")
    return result


# --- Athletes ---------------------------------------------------------------------
@bp.route("/api/athletes", methods=["POST"])
def create_athlete():
    uid, role = auth()
    require_roles(role, ["CommitteeAdmin", "NGBAdmin"])
    body = body_json()
    gb_id = req_str(body, "governing_body_id")
    if role == "NGBAdmin" and uid != gb_id:
        raise unauthorized("NGBAdmin may only register athletes with their own "
                           "governing body")
    if db.get("governing_bodies", gb_id) is None:
        raise not_found("governing body not found")
    full_name = req_str(body, "full_name")
    dob = req_date(body, "date_of_birth")
    team_sport = opt_bool(body, "team_sport", False)
    athlete = db.create("athletes", {
        "governing_body_id": gb_id,
        "full_name": full_name,
        "date_of_birth": dob,
        "team_sport": team_sport,
        "eligibility_status": "REGISTERED",
        "screening_status": "SCREENING_PENDING",
        "screening_expires_at": None,
        "training_completed_at": None,
    })
    return respond_object(athlete, 201)


@bp.route("/api/athletes", methods=["GET"])
def list_athletes():
    _, role = auth()
    require_roles(role, ALL_ROLES_READ)
    gb_filter = request.args.get("governing_body_id") or None
    elig_filter = request.args.get("eligibility_status") or None
    now = timeutil.now()
    items = []
    for athlete in db.all_of("athletes"):
        cascades.due_athlete(athlete, now)
        if gb_filter is not None and athlete["governing_body_id"] != gb_filter:
            continue
        if elig_filter is not None and athlete["eligibility_status"] != elig_filter:
            continue
        items.append(athlete)
    return respond_list(db.sorted_created(items))


@bp.route("/api/athletes/<athlete_id>", methods=["GET"])
def read_athlete(athlete_id):
    uid, role = auth()
    require_roles(role, ALL_ROLES_READ)
    check_athlete_ownership(uid, role, athlete_id)  # Athlete: self only
    athlete = get_athlete_or_404(athlete_id)
    check_gb_ownership(uid, role, athlete["governing_body_id"])
    cascades.due_athlete(athlete, timeutil.now())
    return respond_object(athlete)


@bp.route("/api/athletes/<athlete_id>/transitions", methods=["POST"])
def athlete_transition(athlete_id):
    uid, role = auth()
    require_roles(role, ["SafeSportOfficer", "Athlete"])
    athlete = get_athlete_or_404(athlete_id)
    if athlete["eligibility_status"] == "RETIRED":
        raise already_terminal("athlete is RETIRED")
    body = body_json()
    to_state = req_enum(body, "to_state", ATHLETE_TRANSITION_STATES)
    if to_state == "RETIRED":
        if role != "Athlete" or uid != athlete["id"]:
            raise unauthorized("retirement is the athlete's own act")
    else:
        if role != "SafeSportOfficer":
            raise unauthorized("only a SafeSportOfficer may drive this transition")
    now = timeutil.now()

    if to_state == "SCREENING_CLEARED":
        if athlete["screening_status"] not in (
                "SCREENING_PENDING", "SCREENING_FLAGGED", "SCREENING_EXPIRED"):
            raise invalid_state(
                "screening cannot be cleared from %s" % athlete["screening_status"])
        was_flagged = athlete["screening_status"] == "SCREENING_FLAGGED"
        athlete["screening_status"] = "SCREENING_CLEARED"
        athlete["screening_expires_at"] = now + timeutil.days(SCREENING_VALIDITY_DAYS)
        db.mark("athletes", athlete)
        if was_flagged and athlete["eligibility_status"] == "SUSPENDED" \
                and not cascades.unresolved_abuse(athlete["id"]):
            athlete["eligibility_status"] = "ELIGIBLE"
            db.mark("athletes", athlete)
            cascades.athlete_reinstate_cascade(athlete)
        return respond_object(athlete)

    if to_state == "SCREENING_FLAGGED":
        if athlete["screening_status"] not in ("SCREENING_PENDING",
                                               "SCREENING_CLEARED"):
            raise invalid_state(
                "screening cannot be flagged from %s" % athlete["screening_status"])
        cascades.flag_athlete(athlete)
        return respond_object(athlete)

    if to_state == "TRAINING_CURRENT":
        athlete["training_completed_at"] = now
        db.mark("athletes", athlete)
        return respond_object(athlete)

    if to_state == "ELIGIBLE":
        if athlete["eligibility_status"] not in ("REGISTERED", "SUSPENDED"):
            raise invalid_state(
                "ELIGIBLE is only reachable from REGISTERED or SUSPENDED")
        if not calc.screening_clear(athlete, now):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "screening is not cleared and current")
        if not calc.training_current(athlete, now):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "safe-sport training is missing or expired")
        if athlete["eligibility_status"] == "SUSPENDED" \
                and cascades.unresolved_abuse(athlete["id"]):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "unresolved abuse report blocks reinstatement")
        was_suspended = athlete["eligibility_status"] == "SUSPENDED"
        athlete["eligibility_status"] = "ELIGIBLE"
        db.mark("athletes", athlete)
        if was_suspended:
            cascades.athlete_reinstate_cascade(athlete)
        return respond_object(athlete)

    if to_state == "SUSPENDED":
        if athlete["eligibility_status"] != "ELIGIBLE":
            raise invalid_state("SUSPENDED is only reachable from ELIGIBLE")
        athlete["eligibility_status"] = "SUSPENDED"
        db.mark("athletes", athlete)
        cascades.athlete_suspend_cascade(athlete)
        return respond_object(athlete)

    # RETIRED (self-service; role checked above)
    athlete["eligibility_status"] = "RETIRED"
    db.mark("athletes", athlete)
    cascades.athlete_retire_cascade(athlete)
    return respond_object(athlete)


# --- Performance results -------------------------------------------------------------
@bp.route("/api/athletes/<athlete_id>/results", methods=["POST"])
def create_result(athlete_id):
    uid, role = auth()
    require_roles(role, ["Athlete"])
    check_athlete_ownership(uid, role, athlete_id)
    get_athlete_or_404(athlete_id)
    body = body_json()
    event_name = req_str(body, "event_name")
    event_grade = req_enum(body, "event_grade", EVENT_GRADES)
    placing = body.get("placing")
    if isinstance(placing, bool) or not isinstance(placing, int):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "placing is required and must be an integer")
    if placing < 1 or placing > 8:
        raise ApiError(ERR_SCORE_OUT_OF_RANGE, 422,
                       "placing must be within 1..8")
    event_date = req_datetime(body, "event_date")
    result = db.create("results", {
        "athlete_id": athlete_id,
        "event_name": event_name,
        "event_grade": event_grade,
        "placing": placing,
        "event_date": event_date,
        "base_points": None,
        "status": "SUBMITTED",
        "verified_by_user_id": None,
    })
    return respond_object(result, 201)


@bp.route("/api/athletes/<athlete_id>/results", methods=["GET"])
def list_results(athlete_id):
    uid, role = auth()
    require_roles(role, ALL_ROLES_READ)
    check_athlete_ownership(uid, role, athlete_id)
    athlete = get_athlete_or_404(athlete_id)
    check_gb_ownership(uid, role, athlete["governing_body_id"])
    status = request.args.get("status") or None
    items = [r for r in db.all_of("results")
             if r["athlete_id"] == athlete_id
             and (status is None or r["status"] == status)]
    return respond_list(db.sorted_created(items))


@bp.route("/api/results/<result_id>/transitions", methods=["POST"])
def result_transition(result_id):
    uid, role = auth()
    require_roles(role, ["ResultsOfficial", "Athlete"])
    result = get_result_or_404(result_id)
    body = body_json()
    to_state = req_enum(body, "to_state", RESULT_TRANSITION_STATES)

    if to_state in ("VERIFIED", "REJECTED"):
        if role != "ResultsOfficial":
            # role == Athlete (endpoint role list already enforced):
            # cross-athlete access is a tier-2 ownership denial; the owning
            # athlete attempting to judge their own result is the
            # self-verification half of the submit/verify segregated pair
            # (PRD 3.4) — tier-4 state legality still precedes the tier-7
            # segregation check per the §2.6 ladder.
            if uid != result["athlete_id"]:
                raise unauthorized("cross-athlete access is denied")
            if result["status"] != "SUBMITTED":
                raise invalid_state(
                    "%s is only reachable from SUBMITTED" % to_state)
            raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                           "verifier must differ from the submitting athlete")
        if result["status"] != "SUBMITTED":
            raise invalid_state(
                "%s is only reachable from SUBMITTED" % to_state)
        if uid == result["athlete_id"]:
            raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                           "verifier must differ from the submitting athlete")
        result["status"] = to_state
        if to_state == "VERIFIED":
            result["base_points"] = calc.base_points(result["placing"],
                                                     result["event_grade"])
            result["verified_by_user_id"] = uid
        db.mark("results", result)
        if to_state == "VERIFIED":
            _recompute_agreements(result["athlete_id"])
        return respond_object(result)

    # SUBMITTED resubmission loop from REJECTED, owning athlete only
    if role != "Athlete" or uid != result["athlete_id"]:
        raise unauthorized("only the owning athlete may resubmit")
    if result["status"] != "REJECTED":
        raise invalid_state("SUBMITTED resubmission is only reachable from "
                            "REJECTED")
    result["status"] = "SUBMITTED"
    db.mark("results", result)
    return respond_object(result)


def _recompute_agreements(athlete_id):
    """funding_points + tier_assignment on every non-terminal agreement;
    an ACTIVE agreement's stipend delta is reconciled against the body's
    committed total (computed-field invariant) and the waterfall reruns."""
    now = timeutil.now()
    for fa in db.all_of("funding_agreements"):
        if fa["athlete_id"] != athlete_id or fa["status"] == "TERMINATED":
            continue
        old_stipend = fa["monthly_stipend_cents"]
        calc.recompute_agreement_points(fa, now)
        if fa["status"] == "ACTIVE":
            delta = fa["monthly_stipend_cents"] - old_stipend
            if delta != 0:
                gb = cascades.gb_of_athlete(athlete_id)
                if gb is not None:
                    gb["committed_monthly_stipend_cents"] += delta
                    db.mark("governing_bodies", gb)
                    calc.run_waterfall(gb)
