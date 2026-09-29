"""Referral intake, coordinator assignment, eligibility, outcomes and exit."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g, request

import domain as D
from auth import STAFF_READ, endpoint, require_owner
from envelope import paginate, single
from errors import fail
from helpers import (get_child, get_coordinator, get_referral, not_future,
                     ordered_dates, ser_referral)
from services import cascades, compute
from store import (clock_date, db, dec, flush, iso_date, mark, new_row, ordered,
                   pd, q, q4, set_field, set_fields)
from validate import (Field, parse_body, v_bool, v_date, v_enum, v_id, v_int,
                      v_str, v_token)

bp = Blueprint("referrals", __name__)


def bump_referral(referral):
    mark(referral, bump=True)


# --------------------------------------------------------------------- create

@bp.route("/ei/referrals", methods=["POST"])
@endpoint(["IntakeSpecialist"])
def create_referral():
    payload = parse_body([
        Field("child_id", v_id()),
        Field("primary_referral_source", v_enum(D.REFERRAL_SOURCES)),
        Field("referral_received_date", v_date()),
        Field("county_code", v_token()),
        Field("presenting_concern", v_str()),
        Field("interpreter_required", v_bool(), required=False, default=False),
    ])
    child = get_child(payload["child_id"])
    received = pd(payload["referral_received_date"])
    third_birthday = pd(child["third_birthday_date"])
    if not (third_birthday > received):
        fail("ERR_CHILD_AGE_INELIGIBLE",
             "The child is no longer under three on the referral date.")
    for existing in db.referrals.values():
        if (existing["child_id"] == child["id"]
                and existing["status"] not in D.REFERRAL_TERMINAL):
            fail("ERR_DUPLICATE_REFERRAL",
                 "The child already has an open referral.")
    not_future(payload["referral_received_date"], "referral_received_date")
    referral = new_row({
        "child_id": child["id"],
        "primary_referral_source": payload["primary_referral_source"],
        "referral_received_date": payload["referral_received_date"],
        "county_code": payload["county_code"],
        "presenting_concern": payload["presenting_concern"],
        "interpreter_required": payload["interpreter_required"],
        "coordinator_id": None,
        "assignment_date": None,
        "statutory_deadline_date": iso_date(
            received + timedelta(days=D.STATUTORY_TIMELINE_DAYS)),
        "status": "INTAKE",
        "eligibility_status": "PENDING",
        "eligibility_determination_date": None,
        "initial_ifsp_meeting_date": None,
        "excluded_delay_days": 0,
        "gross_elapsed_days": 0,
        "net_elapsed_days": 0,
        "initial_timeline_status": "IN_PROGRESS",
        "case_weight_points": 0.00,
        "entry_rating_social": None,
        "entry_rating_knowledge": None,
        "entry_rating_needs": None,
        "entry_outcomes_date": None,
        "exit_rating_social": None,
        "exit_rating_knowledge": None,
        "exit_rating_needs": None,
        "services_start_date": None,
        "exit_date": None,
        "exit_reason": None,
        "service_duration_days": 0,
        "progress_category_social": None,
        "progress_category_knowledge": None,
        "progress_category_needs": None,
        "last_qualifying_contact_date": None,
        "monthly_contact_status": "NOT_APPLICABLE",
        "service_gap_flag": False,
    })
    db.referrals[referral["id"]] = referral
    compute.recompute_child_count(child)
    flush()
    return single(ser_referral(referral), 201)


@bp.route("/ei/referrals/<referral_id>", methods=["GET"])
@endpoint(STAFF_READ)
def read_referral(referral_id):
    return single(ser_referral(get_referral(referral_id)))


@bp.route("/ei/referrals", methods=["GET"])
@endpoint(STAFF_READ)
def list_referrals():
    rows = ordered(db.referrals)
    child_id = request.args.get("child_id")
    coordinator_id = request.args.get("coordinator_id")
    status = request.args.get("status")
    if child_id is not None:
        rows = [r for r in rows if r["child_id"] == child_id]
    if coordinator_id is not None:
        rows = [r for r in rows if r["coordinator_id"] == coordinator_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, ser_referral)


# --------------------------------------------------------- coordinator assign

def _language_covered(coordinator, referral):
    child = compute.child_of(referral)
    language = child["primary_language"] if child else None
    return language in (coordinator["language_codes"] or [])


def _non_capacity_eligible(coordinator, referral):
    if coordinator["status"] != "ACTIVE":
        return False
    if coordinator["county_code"] != referral["county_code"]:
        return False
    if referral["interpreter_required"] and not _language_covered(coordinator,
                                                                 referral):
        return False
    return True


def _fits_capacity(coordinator, projected):
    weighted = dec(coordinator["weighted_caseload_points"] or 0)
    maximum = dec(coordinator["max_weighted_caseload_points"])
    return weighted + dec(projected) <= maximum


def _projected_utilization(coordinator, projected):
    weighted = dec(coordinator["weighted_caseload_points"] or 0)
    maximum = dec(coordinator["max_weighted_caseload_points"])
    if maximum == 0:
        return Decimal("0.0000")
    return q((weighted + dec(projected)) / maximum, 4)


@bp.route("/ei/referrals/<referral_id>/assign-coordinator", methods=["POST"])
@endpoint(["ProgramAdmin"])
def assign_coordinator(referral_id):
    payload = parse_body([Field("coordinator_id", v_id(), required=False)])
    referral = get_referral(referral_id)
    named = None
    if payload["coordinator_id"] is not None:
        named = get_coordinator(payload["coordinator_id"])
    if referral["status"] != "INTAKE":
        fail("ERR_REFERRAL_STATE_INVALID",
             "Only a case in INTAKE may be assigned a coordinator.")
    projected = compute.compute_case_weight(referral)
    if named is not None:
        if not _non_capacity_eligible(named, referral):
            fail("ERR_COORDINATOR_NOT_ELIGIBLE",
                 "The named coordinator fails the eligibility filter.")
        if not _fits_capacity(named, projected):
            fail("ERR_CASELOAD_CAP_EXCEEDED",
                 "The named coordinator has no headroom for this case.")
        chosen = named
    else:
        candidates = [c for c in ordered(db.coordinators)
                      if _non_capacity_eligible(c, referral)
                      and _fits_capacity(c, projected)]
        if not candidates:
            fail("ERR_NO_ELIGIBLE_COORDINATOR",
                 "No coordinator on the roster can take this case.")
        candidates.sort(key=lambda c: (_projected_utilization(c, projected),
                                       c["created_at"], c["_seq"]))
        chosen = candidates[0]
    set_fields(referral, {
        "coordinator_id": chosen["id"],
        "assignment_date": iso_date(clock_date()),
        "status": "EVALUATION_PENDING",
    }, bump=False)
    compute.recompute_case_weight(referral)
    compute.recompute_monthly_contact(referral)
    compute.recompute_coordinator(chosen)
    bump_referral(referral)
    flush()
    return single(ser_referral(referral))


# ------------------------------------------------------------ eligibility fork

@bp.route("/ei/referrals/<referral_id>/eligibility-determination",
          methods=["POST"])
@endpoint(["ProgramAdmin"])
def eligibility_determination(referral_id):
    payload = parse_body([
        Field("is_eligible", v_bool()),
        Field("determination_date", v_date()),
    ])
    referral = get_referral(referral_id)
    if referral["status"] != "EVALUATION_PENDING":
        fail("ERR_REFERRAL_STATE_INVALID",
             "Only a case in EVALUATION_PENDING may be determined.")
    completed = [a for a in compute.referral_assessments(referral["id"])
                 if a["status"] == "COMPLETED"]
    types = set(a["assessment_type"] for a in completed)
    if not ("INITIAL_EVALUATION" in types and "FAMILY_ASSESSMENT" in types):
        fail("ERR_REQUIRED_ASSESSMENTS_INCOMPLETE",
             "A completed initial evaluation and family assessment are required.")
    not_future(payload["determination_date"], "determination_date")
    ordered_dates(referral["referral_received_date"], payload["determination_date"],
                  "determination_date must be on or after referral_received_date.")
    if payload["is_eligible"]:
        set_fields(referral, {
            "status": "ELIGIBILITY_DETERMINED",
            "eligibility_status": "ELIGIBLE",
            "eligibility_determination_date": payload["determination_date"],
        }, bump=False)
        compute.recompute_timeline(referral)
        compute.recompute_monthly_contact(referral)
    else:
        set_fields(referral, {
            "status": "NOT_ELIGIBLE",
            "eligibility_status": "NOT_ELIGIBLE",
            "eligibility_determination_date": payload["determination_date"],
            "case_weight_points": 0.00,
            "monthly_contact_status": "NOT_APPLICABLE",
        }, bump=False)
        cascades.cancel_scheduled_assessments(referral)
        compute.recompute_coordinator(db.coordinators.get(referral["coordinator_id"]))
        compute.recompute_child_count(compute.child_of(referral))
    bump_referral(referral)
    flush()
    return single(ser_referral(referral))


# ------------------------------------------------------------- entry outcomes

@bp.route("/ei/referrals/<referral_id>/entry-outcomes", methods=["POST"])
@endpoint(["Evaluator"])
def entry_outcomes(referral_id):
    payload = parse_body([
        Field("measurement_date", v_date()),
        Field("rating_social", v_int(1, 7)),
        Field("rating_knowledge", v_int(1, 7)),
        Field("rating_needs", v_int(1, 7)),
    ])
    referral = get_referral(referral_id)
    if referral["status"] != "ELIGIBILITY_DETERMINED":
        fail("ERR_REFERRAL_STATE_INVALID",
             "Only a case in ELIGIBILITY_DETERMINED may record entry outcomes.")
    not_future(payload["measurement_date"], "measurement_date")
    ordered_dates(referral["eligibility_determination_date"],
                  payload["measurement_date"],
                  "measurement_date must be on or after "
                  "eligibility_determination_date.")
    set_fields(referral, {
        "entry_rating_social": payload["rating_social"],
        "entry_rating_knowledge": payload["rating_knowledge"],
        "entry_rating_needs": payload["rating_needs"],
        "entry_outcomes_date": payload["measurement_date"],
        "status": "IFSP_PENDING",
    }, bump=False)
    compute.recompute_case_weight(referral)
    compute.recompute_monthly_contact(referral)
    compute.recompute_coordinator(db.coordinators.get(referral["coordinator_id"]))
    bump_referral(referral)
    flush()
    return single(ser_referral(referral))


# ------------------------------------------------------------------- case exit

@bp.route("/ei/referrals/<referral_id>/exit", methods=["POST"])
@endpoint(["ServiceCoordinator"])
def exit_referral(referral_id):
    payload = parse_body([
        Field("exit_date", v_date()),
        Field("exit_reason", v_enum(D.EXIT_REASONS)),
        Field("exit_rating_social", v_int(1, 7), required=False),
        Field("exit_rating_knowledge", v_int(1, 7), required=False),
        Field("exit_rating_needs", v_int(1, 7), required=False),
    ])
    referral = get_referral(referral_id)
    require_owner(referral["coordinator_id"])
    status = referral["status"]
    pre_service = ("EVALUATION_PENDING", "ELIGIBILITY_DETERMINED", "IFSP_PENDING")
    if status == "ACTIVE_SERVICES":
        pass
    elif status in pre_service:
        if payload["exit_reason"] not in ("FAMILY_WITHDREW", "MOVED_OUT_OF_STATE"):
            fail("ERR_REFERRAL_STATE_INVALID",
                 "That exit reason is not available before services start.")
    else:
        fail("ERR_REFERRAL_STATE_INVALID",
             "A case in %s may not be exited." % status)
    if status == "ACTIVE_SERVICES":
        if (payload["exit_rating_social"] is None
                or payload["exit_rating_knowledge"] is None
                or payload["exit_rating_needs"] is None):
            fail("ERR_EXIT_OUTCOMES_REQUIRED",
                 "All three exit ratings are required when exiting active services.")
        if payload["exit_reason"] == "REACHED_AGE_THREE":
            plan = compute.active_ifsp(referral)
            plans = compute.ifsp_transition_plans(plan["id"]) if plan else []
            if not any(t["status"] in ("NOTIFIED", "OPT_OUT") for t in plans):
                fail("ERR_EXIT_OUTCOMES_REQUIRED",
                     "A notified or opted-out transition plan is required to age out.")
    not_future(payload["exit_date"], "exit_date")
    if referral["services_start_date"]:
        ordered_dates(referral["services_start_date"], payload["exit_date"],
                      "exit_date must be on or after services_start_date.")
    updates = {
        "exit_date": payload["exit_date"],
        "exit_reason": payload["exit_reason"],
        "status": "EXITED",
        "case_weight_points": 0.00,
        "monthly_contact_status": "NOT_APPLICABLE",
    }
    for area in ("social", "knowledge", "needs"):
        supplied = payload["exit_rating_%s" % area]
        if supplied is not None:
            updates["exit_rating_%s" % area] = supplied
    set_fields(referral, updates, bump=False)
    if status == "ACTIVE_SERVICES":
        duration, categories = compute.compute_outcomes(referral,
                                                        payload["exit_date"])
        set_fields(referral, {
            "service_duration_days": duration or 0,
            "progress_category_social": categories[0],
            "progress_category_knowledge": categories[1],
            "progress_category_needs": categories[2],
        }, bump=False)
        cascades.exit_service_cascade(referral)
        set_field(referral, "service_gap_flag", False, bump=False)
    else:
        if status in ("EVALUATION_PENDING", "ELIGIBILITY_DETERMINED"):
            cascades.cancel_scheduled_assessments(referral)
        if status == "IFSP_PENDING":
            cascades.withdraw_draft_plans(referral)
        set_field(referral, "service_gap_flag", False, bump=False)
    compute.recompute_child_count(compute.child_of(referral))
    compute.recompute_coordinator(db.coordinators.get(referral["coordinator_id"]))
    bump_referral(referral)
    flush()
    return single(ser_referral(referral))


# ------------------------------------------------------- compliance computed read

@bp.route("/ei/referrals/<referral_id>/timeline-compliance", methods=["GET"])
@endpoint(STAFF_READ)
def timeline_compliance(referral_id):
    referral = get_referral(referral_id)
    result = compute.compute_timeline(referral)
    return single({
        "referral_id": referral["id"],
        "referral_received_date": referral["referral_received_date"],
        "statutory_deadline_date": referral["statutory_deadline_date"],
        "stop_date": result["stop_date"],
        "gross_elapsed_days": result["gross_elapsed_days"],
        "excluded_delay_days": result["excluded_delay_days"],
        "net_elapsed_days": result["net_elapsed_days"],
        "initial_timeline_status": result["initial_timeline_status"],
        "monthly_contact_status": referral["monthly_contact_status"],
        "last_qualifying_contact_date": referral["last_qualifying_contact_date"],
    })
