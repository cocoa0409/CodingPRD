from datetime import timedelta

from flask import Blueprint

import constants
import db
import services
from errors import fail
from middleware import (
    auth_context,
    require_role,
    body,
    locked,
    req_str,
    req_int,
    req_bool,
    req_date,
    opt_str,
    opt_list_str,
)
from response import success
from util import serialize

bp = Blueprint("records", __name__)


def _get_match_or_404(match_id):
    match = db.store.matches.get(match_id)
    if match is None:
        fail("ERR_MATCH_NOT_FOUND", "InternshipMatch %s does not exist" % match_id)
    return match


@bp.route("/supervision-reports", methods=["POST"])
@locked
def create_supervision_report():
    uid, role = auth_context()
    data = body()
    match_id = req_str(data, "internship_match_id")
    week_start = req_date(data, "week_start_date")
    hours = req_int(data, "hours_supervised", min_value=0)
    supervisor_name = req_str(data, "supervisor_name")
    attestation_text = req_str(data, "attestation_text")
    achieved = opt_list_str(data, "objectives_achieved")
    excused = opt_list_str(data, "objectives_excused")
    if set(achieved) & set(excused):
        fail("ERR_VALIDATION", "objectives_achieved and objectives_excused must be disjoint")
    require_role(role, ["EmployerRep"])
    match = _get_match_or_404(match_id)
    if uid != match["employer_id"]:
        fail("ERR_FORBIDDEN_OWNERSHIP", "X-User-ID must equal the match's employer_id")
    if match["match_status"] != "ACTIVE":
        fail("ERR_MATCH_NOT_ACTIVE", "Match is not ACTIVE")
    if not (match["start_date"] <= week_start <= match["end_date"]):
        fail("ERR_VALIDATION", "week_start_date lies outside the match's date window")
    plan_codes = {o["objective_code"] for o in match["learning_objectives"]}
    for code in list(achieved) + list(excused):
        if code not in plan_codes:
            fail("ERR_VALIDATION", "objective code %s is not in the match's plan" % code)
    for r in db.store.supervision_reports.values():
        if r["internship_match_id"] == match["id"] and r["week_start_date"] == week_start:
            fail("ERR_DUPLICATE_WEEK_REPORT", "A report already exists for this match and week")
    ent = db.ledger_entity()
    ent.update(
        {
            "internship_match_id": match["id"],
            "week_start_date": week_start,
            "hours_supervised": hours,
            "objectives_achieved": achieved,
            "objectives_excused": excused,
            "supervisor_name": supervisor_name,
            "attestation_text": attestation_text,
        }
    )
    db.store.supervision_reports[ent["id"]] = ent
    for o in match["learning_objectives"]:
        if o["objective_code"] in achieved:
            o["status"] = "ACHIEVED"
        elif o["objective_code"] in excused:
            o["status"] = "EXCUSED"
    services.recompute_ratios(match)
    services.touch(match)
    return success(serialize(ent), status=201)


@bp.route("/wage-records", methods=["POST"])
@locked
def create_wage_record():
    uid, role = auth_context()
    data = body()
    match_id = req_str(data, "internship_match_id")
    period_start = req_date(data, "period_start_date")
    period_end = req_date(data, "period_end_date")
    amount_cents = req_int(data, "amount_cents", min_value=0)
    memo = opt_str(data, "memo")
    if period_start > period_end:
        fail("ERR_VALIDATION", "period_start_date must not fall after period_end_date")
    require_role(role, ["EmployerRep"])
    match = _get_match_or_404(match_id)
    if uid != match["employer_id"]:
        fail("ERR_FORBIDDEN_OWNERSHIP", "X-User-ID must equal the match's employer_id")
    if match["match_status"] != "ACTIVE":
        fail("ERR_WAGE_RECORD_NOT_ALLOWED", "Wage records are accepted only while the match is ACTIVE")
    if not (match["start_date"] <= period_start <= match["end_date"]):
        fail("ERR_VALIDATION", "period_start_date lies outside the match's date window")
    if not (match["start_date"] <= period_end <= match["end_date"]):
        fail("ERR_VALIDATION", "period_end_date lies outside the match's date window")
    is_violation = amount_cents > 0
    ent = db.ledger_entity()
    ent.update(
        {
            "internship_match_id": match["id"],
            "period_start_date": period_start,
            "period_end_date": period_end,
            "amount_cents": amount_cents,
            "memo": memo,
            "is_violation": is_violation,
        }
    )
    db.store.wage_records[ent["id"]] = ent
    if is_violation:
        match["flagged_wage_violation"] = True
        services.touch(match)
        employer = db.store.employers.get(match["employer_id"])
        if employer is not None:
            employer["pending_violations"] += 1
            if (
                employer["pending_violations"] >= constants.WAGE_VIOLATION_SUSPEND_THRESHOLD
                and employer["authorization_status"] in ("AUTHORIZED", "AUTHORIZATION_LAPSED")
            ):
                employer["authorization_status"] = "SUSPENDED"
            services.touch(employer)
    return success(serialize(ent), status=201)


@bp.route("/conversion-records", methods=["POST"])
@locked
def create_conversion_record():
    uid, role = auth_context()
    data = body()
    match_id = req_str(data, "internship_match_id")
    conversion_date = req_date(data, "conversion_date")
    offer_made = req_bool(data, "offer_made")
    offer_accepted = req_bool(data, "offer_accepted")
    if offer_accepted and not offer_made:
        fail("ERR_VALIDATION", "offer_accepted=true requires offer_made=true")
    require_role(role, ["EmployerRep"])
    match = _get_match_or_404(match_id)
    if uid != match["employer_id"]:
        fail("ERR_FORBIDDEN_OWNERSHIP", "X-User-ID must equal the match's employer_id")
    if match["match_status"] != "COMPLETED":
        fail("ERR_MATCH_NOT_COMPLETED", "Match is not COMPLETED")
    member = db.store.members.get(match["service_member_id"])
    if member is None:
        fail("ERR_MEMBER_NOT_FOUND", "Match ServiceMember does not exist")
    sep = member["separation_date"]
    if conversion_date < sep or conversion_date > sep + timedelta(days=constants.CONVERSION_WINDOW_DAYS):
        fail("ERR_CONVERSION_WINDOW_EXPIRED", "conversion_date is outside the 90-day window")
    for c in db.store.conversions.values():
        if c["internship_match_id"] == match["id"]:
            fail("ERR_CONVERSION_ALREADY_RECORDED", "A ConversionRecord already exists for this match")
    ent = db.ledger_entity()
    ent.update(
        {
            "internship_match_id": match["id"],
            "conversion_date": conversion_date,
            "offer_made": offer_made,
            "offer_accepted": offer_accepted,
            "hired": bool(offer_made and offer_accepted),
        }
    )
    db.store.conversions[ent["id"]] = ent
    return success(serialize(ent), status=201)
