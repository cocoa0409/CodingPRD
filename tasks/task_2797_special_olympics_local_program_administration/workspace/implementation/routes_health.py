"""Healthy Athletes screenings and referral follow-up."""
from flask import Blueprint

import db
import derive
from core import (ADVISORY_REFERRAL_DUE_DAYS, FINDING_SEVERITIES,
                  FOLLOWUP_OUTCOMES, REFERRAL_STATUSES, SCREENING_DISCIPLINES,
                  URGENT_REFERRAL_DUE_DAYS, add_days, auth, bad_request,
                  clock_date, fail, fmt_date, get_body, ok, opt_str, paginate,
                  parse_date, query_enum, req_date_field, req_enum, req_str)
from serialize import ser_screening

bp = Blueprint("health", __name__)

LIVE_REFERRAL_STATUSES = ("REFERRED", "FOLLOW_UP_LOGGED", "ESCALATED")


def _unresolved_urgent(athlete, excluding_id=None):
    for row in db.screenings.values():
        if row["athlete_id"] != athlete["id"]:
            continue
        if excluding_id is not None and row["id"] == excluding_id:
            continue
        if (row["finding_severity"] == "URGENT"
                and row["referral_status"] in LIVE_REFERRAL_STATUSES):
            return True
    return False


@bp.get("/athletes/<rid>/health-screenings")
def list_athlete_screenings(rid):
    auth(["ProgramManager", "MedicalReviewer", "HealthScreeningLead"],
         write=False)
    athlete = derive.require("athletes", rid)
    discipline = query_enum("discipline", SCREENING_DISCIPLINES)
    severity = query_enum("finding_severity", FINDING_SEVERITIES)
    referral_status = query_enum("referral_status", REFERRAL_STATUSES)
    rows = [s for s in db.screenings.values()
            if s["athlete_id"] == athlete["id"]]
    if discipline:
        rows = [s for s in rows if s["discipline"] == discipline]
    if severity:
        rows = [s for s in rows if s["finding_severity"] == severity]
    if referral_status:
        rows = [s for s in rows if s["referral_status"] == referral_status]
    return paginate(rows, ser_screening)


@bp.post("/health-screenings")
def create_screening():
    auth(["HealthScreeningLead"])
    body = get_body()
    athlete_id = body.get("athlete_id")
    if not isinstance(athlete_id, str) or athlete_id == "":
        bad_request("Field 'athlete_id' must be a resource id string.")
    athlete = derive.require("athletes", athlete_id)
    event_name = req_str(body, "event_name", 3, 120)
    discipline = req_enum(body, "discipline", SCREENING_DISCIPLINES)
    screened_on = req_date_field(body, "screened_on")
    finding_severity = req_enum(body, "finding_severity", FINDING_SEVERITIES)
    finding_note = opt_str(body, "finding_note", 0, 500)
    if screened_on > clock_date():
        bad_request("screened_on may not fall after the logical clock date.")
    if athlete["registration_status"] == "WITHDRAWN":
        fail("ERR_ATHLETE_ALREADY_WITHDRAWN", 409,
             "A withdrawn athlete may not be screened.")

    if finding_severity == "ROUTINE":
        referral_status = "NOT_REQUIRED"
        referral_due_on = None
    elif finding_severity == "ADVISORY":
        referral_status = "REFERRED"
        referral_due_on = fmt_date(add_days(screened_on,
                                            ADVISORY_REFERRAL_DUE_DAYS))
    else:
        referral_status = "REFERRED"
        referral_due_on = fmt_date(add_days(screened_on,
                                            URGENT_REFERRAL_DUE_DAYS))
    screening = db.new_row("screenings", {
        "athlete_id": athlete["id"],
        "event_name": event_name,
        "discipline": discipline,
        "screened_on": fmt_date(screened_on),
        "finding_severity": finding_severity,
        "finding_note": finding_note,
        "referral_status": referral_status,
        "referral_due_on": referral_due_on,
        "followup_count": 0,
        "last_followup_note": None,
    })
    if finding_severity == "URGENT":
        if athlete["medical_status"] in ("CLEARED", "RESTRICTED"):
            db.apply_changes(athlete, {"medical_status": "HOLD"})
        derive.void_entries_for_athlete(athlete, "ATHLETE_MEDICAL_HOLD")
        derive.recompute_teams_for_athlete(athlete)
        derive.recompute_program(derive.program_of_athlete(athlete))
    return ok(ser_screening(screening), 201)


@bp.post("/health-screenings/<rid>/referral-followup")
def referral_followup(rid):
    auth(["HealthScreeningLead", "MedicalReviewer"])
    screening = derive.require("screenings", rid)
    body = get_body()
    outcome = req_enum(body, "outcome", FOLLOWUP_OUTCOMES)
    note = opt_str(body, "note", 0, 500)
    if screening["referral_status"] not in LIVE_REFERRAL_STATUSES:
        fail("ERR_SCREENING_STATE_INVALID", 409,
             "This referral is not live and cannot take a follow-up.")
    athlete = db.athletes[screening["athlete_id"]]
    if outcome == "LOGGED":
        screening["referral_status"] = "FOLLOW_UP_LOGGED"
        screening["followup_count"] = screening["followup_count"] + 1
        screening["last_followup_note"] = note
        db.touch(screening)
    elif outcome == "REREFER":
        screening["referral_status"] = "REFERRED"
        screening["followup_count"] = screening["followup_count"] + 1
        screening["referral_due_on"] = fmt_date(
            add_days(clock_date(), URGENT_REFERRAL_DUE_DAYS))
        db.touch(screening)
    else:
        screening["referral_status"] = "RESOLVED"
        db.touch(screening)
        if (screening["finding_severity"] == "URGENT"
                and athlete["medical_status"] == "HOLD"
                and not _unresolved_urgent(athlete)):
            form = db.medical_forms.get(athlete.get("current_medical_form_id"))
            if form is None:
                target = "NONE"
            else:
                restrictions = form.get("restrictions")
                if restrictions is None or list(restrictions) == ["NONE"]:
                    target = "CLEARED"
                else:
                    target = "RESTRICTED"
            db.apply_changes(athlete, {"medical_status": target})
            derive.recompute_teams_for_athlete(athlete)
    derive.recompute_program(derive.program_of_athlete(athlete))
    return ok(ser_screening(screening))
