"""Programs, athletes, contributions, the logical clock and the sweep."""
from decimal import Decimal

from flask import Blueprint

import db
import derive
from core import (ALL_ROLES, CONTRIBUTION_STATUSES, CONTRIBUTION_TYPES,
                  CONTRIBUTION_VOID_REASON_CODES, DESIGNATIONS,
                  FAMILY_ENGAGEMENT_MATCH_RATE, GAMES_LEVELS,
                  IN_KIND_GOODS_CAP_CENTS, IN_KIND_SERVICES_RECOGNITION_RATE,
                  MEDICAL_STATUSES, REGISTRATION_STATUSES, SEASON_STATUSES,
                  SPORTS, VOLUNTEER_CLASSES, VOLUNTEER_STATUSES,
                  VOLUNTEER_HOUR_RATE_CENTS, WITHDRAWAL_REASON_CODES, auth,
                  bad_request, clock_str, dec, fail, fmt_date, fmt_ts, get_body,
                  is_num, money, opt_bool, opt_date_field, opt_int, opt_num,
                  ok, paginate, parse_date, query_enum, query_str, req_date_field,
                  req_dt_field, req_enum, req_str, set_clock)
from serialize import (ser_athlete, ser_contribution, ser_program, ser_season,
                       ser_volunteer, volunteer_status)

bp = Blueprint("program", __name__)

# ----------------------------------------------------------------- programs ---


@bp.post("/programs")
def create_program():
    auth(["ProgramManager"])
    body = get_body()
    name = req_str(body, "name", 3, 120)
    region_code = req_str(body, "region_code", 2, 2)
    if not all("A" <= ch <= "Z" for ch in region_code):
        bad_request("region_code must be exactly two uppercase letters A-Z.")
    program = db.new_row("programs", {
        "name": name,
        "region_code": region_code,
        "compliance_posture": "FROZEN",
        "certified_coach_count": 0,
        "credential_denominator_count": 0,
        "expired_credential_count": 0,
        "expired_credential_ratio": 0.0,
        "unresolved_urgent_referral_count": 0,
        "active_athlete_count": 0,
        "program_practice_minutes": 0,
        "recognized_support_cents": 0,
        "pledged_support_cents": 0,
        "family_engagement_credit_cents": 0,
        "sweep_epoch": 0,
        "last_sweep_at": None,
    })
    return ok(ser_program(program), 201)


@bp.get("/programs/<rid>")
def get_program(rid):
    auth(ALL_ROLES, write=False)
    program = derive.require("programs", rid)
    return ok(ser_program(program))


@bp.get("/programs/<rid>/athletes")
def list_program_athletes(rid):
    auth(ALL_ROLES, write=False)
    program = derive.require("programs", rid)
    registration_status = query_enum("registration_status", REGISTRATION_STATUSES)
    medical_status = query_enum("medical_status", MEDICAL_STATUSES)
    rows = derive.program_athletes(program["id"])
    if registration_status:
        rows = [r for r in rows
                if r["registration_status"] == registration_status]
    if medical_status:
        rows = [r for r in rows if r["medical_status"] == medical_status]
    return paginate(rows, ser_athlete)


@bp.post("/programs/<rid>/athletes")
def create_athlete(rid):
    auth(["ProgramManager"])
    program = derive.require("programs", rid)
    body = get_body()
    legal_name = req_str(body, "legal_name", 2, 120)
    birth_date = req_date_field(body, "birth_date")
    sport = req_enum(body, "sport", SPORTS)
    down_syndrome_flag = opt_bool(body, "down_syndrome_flag", default=False)
    athlete = db.new_row("athletes", {
        "program_id": program["id"],
        "legal_name": legal_name,
        "birth_date": fmt_date(birth_date),
        "sport": sport,
        "down_syndrome_flag": bool(down_syndrome_flag),
        "registration_status": "PENDING_MEDICAL",
        "medical_status": "NONE",
        "registration_expires_on": None,
        "current_medical_form_id": None,
        "cumulative_practice_minutes": 0,
        "counted_session_count": 0,
        "withdrawal_reason_code": None,
    })
    derive.recompute_program(program)
    return ok(ser_athlete(athlete), 201)


@bp.get("/programs/<rid>/volunteers")
def list_program_volunteers(rid):
    auth(["ProgramManager", "CredentialingOfficer", "CompetitionDirector"],
         write=False)
    program = derive.require("programs", rid)
    volunteer_class = query_enum("volunteer_class", VOLUNTEER_CLASSES)
    status = query_enum("status", VOLUNTEER_STATUSES)
    rows = derive.program_volunteers(program["id"])
    if volunteer_class:
        rows = [r for r in rows if r["volunteer_class"] == volunteer_class]
    if status:
        rows = [r for r in rows if volunteer_status(r) == status]
    return paginate(rows, ser_volunteer)


@bp.get("/programs/<rid>/seasons")
def list_program_seasons(rid):
    auth(["ProgramManager", "CompetitionDirector", "Coach"], write=False)
    program = derive.require("programs", rid)
    sport = query_enum("sport", SPORTS)
    status = query_enum("status", SEASON_STATUSES)
    rows = derive.program_seasons(program["id"])
    if sport:
        rows = [r for r in rows if r["sport"] == sport]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, ser_season)

# ----------------------------------------------------------------- athletes ---


@bp.get("/athletes/<rid>")
def get_athlete(rid):
    auth(ALL_ROLES, write=False)
    athlete = derive.require("athletes", rid)
    return ok(ser_athlete(athlete))


@bp.post("/athletes/<rid>/withdraw")
def withdraw_athlete(rid):
    auth(["ProgramManager"])
    athlete = derive.require("athletes", rid)
    body = get_body()
    reason = req_enum(body, "withdrawal_reason_code", WITHDRAWAL_REASON_CODES)
    if athlete["registration_status"] == "WITHDRAWN":
        fail("ERR_ATHLETE_ALREADY_WITHDRAWN", 409,
             "This athlete has already been withdrawn.")
    started = athlete["registration_status"]
    athlete["registration_status"] = "WITHDRAWN"
    athlete["withdrawal_reason_code"] = reason
    db.touch(athlete)
    if started in ("ACTIVE", "LAPSED"):
        derive.void_entries_for_athlete(athlete, "ATHLETE_WITHDRAWN")
        derive.recompute_teams_for_athlete(athlete)
    derive.recompute_program(derive.program_of_athlete(athlete))
    return ok(ser_athlete(athlete))

# ------------------------------------------------------------ contributions ---


def _recognized_value(contribution_type, stated_value_cents, volunteer_hours):
    if contribution_type in ("CASH_PLEDGE", "CASH_RECEIPT"):
        return int(stated_value_cents)
    if contribution_type == "IN_KIND_GOODS":
        return min(int(stated_value_cents), IN_KIND_GOODS_CAP_CENTS)
    if contribution_type == "IN_KIND_SERVICES":
        return money(dec(stated_value_cents) * IN_KIND_SERVICES_RECOGNITION_RATE)
    return money(dec(volunteer_hours) * Decimal(VOLUNTEER_HOUR_RATE_CENTS))


def _match_credit(recognized_value_cents):
    return money(dec(recognized_value_cents) * FAMILY_ENGAGEMENT_MATCH_RATE)


@bp.get("/programs/<rid>/contributions")
def list_program_contributions(rid):
    auth(["ProgramManager"], write=False)
    program = derive.require("programs", rid)
    designation = query_enum("designation", DESIGNATIONS)
    status = query_enum("status", CONTRIBUTION_STATUSES)
    rows = derive.program_contributions(program["id"])
    if designation:
        rows = [r for r in rows if r["designation"] == designation]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, ser_contribution)


@bp.post("/programs/<rid>/contributions")
def create_contribution(rid):
    auth(["ProgramManager"])
    program = derive.require("programs", rid)
    body = get_body()
    donor_name = req_str(body, "donor_name", 2, 120)
    contribution_type = req_enum(body, "contribution_type", CONTRIBUTION_TYPES)
    designation = req_enum(body, "designation", DESIGNATIONS)
    stated_value_cents = opt_int(body, "stated_value_cents", 0, 100000000)
    received_on = opt_date_field(body, "received_on")
    hours_given = "volunteer_hours" in body and body.get("volunteer_hours") is not None
    if contribution_type == "VOLUNTEER_HOURS":
        volunteer_hours = body.get("volunteer_hours")
        if (not hours_given or not is_num(volunteer_hours)
                or dec(volunteer_hours) <= 0):
            fail("ERR_VOLUNTEER_HOURS_REQUIRED", 400,
                 "volunteer_hours greater than zero is required for a "
                 "VOLUNTEER_HOURS contribution.")
    else:
        volunteer_hours = None
        if hours_given:
            bad_request("volunteer_hours may only be supplied for a "
                        "VOLUNTEER_HOURS contribution.")
        if stated_value_cents is None:
            bad_request("stated_value_cents is required for a %s contribution."
                        % contribution_type)
    recognized = _recognized_value(contribution_type, stated_value_cents,
                                   volunteer_hours)
    status = "PLEDGED" if contribution_type == "CASH_PLEDGE" else "RECEIVED"
    match_credit = 0
    if designation == "FAMILY_ENGAGEMENT" and status == "RECEIVED":
        match_credit = _match_credit(recognized)
    contribution = db.new_row("contributions", {
        "program_id": program["id"],
        "donor_name": donor_name,
        "contribution_type": contribution_type,
        "designation": designation,
        "stated_value_cents": stated_value_cents,
        "volunteer_hours": volunteer_hours,
        "recognized_value_cents": recognized,
        "match_credit_cents": match_credit,
        "received_on": fmt_date(received_on),
        "status": status,
        "void_reason_code": None,
    })
    derive.recompute_program(program)
    return ok(ser_contribution(contribution), 201)


@bp.post("/contributions/<rid>/fulfill")
def fulfill_contribution(rid):
    auth(["ProgramManager"])
    contribution = derive.require("contributions", rid)
    body = get_body()
    received_on = req_date_field(body, "received_on")
    from core import clock_date
    if received_on > clock_date():
        bad_request("received_on may not fall after the clock date.")
    if contribution["status"] != "PLEDGED":
        fail("ERR_CONTRIBUTION_STATE_INVALID", 409,
             "Only a PLEDGED contribution may be fulfilled.")
    contribution["status"] = "RECEIVED"
    contribution["received_on"] = fmt_date(received_on)
    if contribution["designation"] == "FAMILY_ENGAGEMENT":
        contribution["match_credit_cents"] = _match_credit(
            contribution["recognized_value_cents"])
    db.touch(contribution)
    derive.recompute_program(db.programs[contribution["program_id"]])
    return ok(ser_contribution(contribution))


@bp.post("/contributions/<rid>/void")
def void_contribution(rid):
    auth(["ProgramManager"])
    contribution = derive.require("contributions", rid)
    body = get_body()
    reason = req_enum(body, "void_reason_code", CONTRIBUTION_VOID_REASON_CODES)
    if contribution["status"] not in ("PLEDGED", "RECEIVED"):
        fail("ERR_CONTRIBUTION_STATE_INVALID", 409,
             "This contribution has already been voided.")
    contribution["status"] = "VOID"
    contribution["void_reason_code"] = reason
    contribution["recognized_value_cents"] = 0
    contribution["match_credit_cents"] = 0
    db.touch(contribution)
    derive.recompute_program(db.programs[contribution["program_id"]])
    return ok(ser_contribution(contribution))

# ----------------------------------------------------------- logical clock ---


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    role = None
    from core import authenticate, authorize
    role, _user = authenticate(False)
    authorize(role, ALL_ROLES)
    body = get_body()
    instant = req_dt_field(body, "to_iso8601")
    set_clock(instant)
    return ok({"current_utc": fmt_ts(instant)})

# ------------------------------------------------------- compliance sweep ---


@bp.post("/programs/<rid>/compliance-sweep")
def compliance_sweep(rid):
    auth(["ProgramManager"])
    program = derive.require("programs", rid)
    from core import clock_date, clock_now, parse_dt
    today = clock_date()

    # Step one: expire certified credentials whose effective expiry has passed.
    for credential in sorted(derive.program_credentials(program["id"]),
                             key=lambda c: (c["created_at"], c["_seq"])):
        if credential["status"] != "CERTIFIED":
            continue
        expires = parse_date(credential.get("expires_on"))
        if expires is None or not expires < today:
            continue
        credential["status"] = "EXPIRED"
        db.touch(credential)
        derive.void_sessions_for_credential(
            credential, "CREDENTIAL_EXPIRED", future_scheduled_only=True)
        volunteer = db.volunteers.get(credential["volunteer_id"])
        if volunteer is not None:
            derive.recompute_teams_for_volunteer(volunteer)

    # Step two: expire approved medical forms past their shelf life.
    athlete_ids = {a["id"] for a in derive.program_athletes(program["id"])}
    for form in sorted(db.medical_forms.values(),
                       key=lambda f: (f["created_at"], f["_seq"])):
        if form["athlete_id"] not in athlete_ids or form["status"] != "APPROVED":
            continue
        expires = parse_date(form.get("expires_on"))
        if expires is None or not expires < today:
            continue
        form["status"] = "EXPIRED"
        db.touch(form)
        athlete = db.athletes[form["athlete_id"]]
        changes = {}
        if athlete["current_medical_form_id"] == form["id"]:
            changes["current_medical_form_id"] = None
        if athlete["medical_status"] in ("CLEARED", "RESTRICTED"):
            changes["medical_status"] = "NONE"
        if changes:
            db.apply_changes(athlete, changes)
            derive.recompute_teams_for_athlete(athlete)

    # Step three: lapse registrations whose horizon has passed.
    for athlete in sorted(derive.program_athletes(program["id"]),
                          key=lambda a: (a["created_at"], a["_seq"])):
        if athlete["registration_status"] != "ACTIVE":
            continue
        expires = parse_date(athlete.get("registration_expires_on"))
        overdue = expires is not None and expires < today
        if not overdue and athlete["current_medical_form_id"] is not None:
            continue
        athlete["registration_status"] = "LAPSED"
        db.touch(athlete)
        derive.recompute_teams_for_athlete(athlete)

    # Step four: escalate referrals that have gone overdue.
    for screening in sorted(derive.program_screenings(program["id"]),
                            key=lambda s: (s["created_at"], s["_seq"])):
        if screening["referral_status"] != "REFERRED":
            continue
        due = parse_date(screening.get("referral_due_on"))
        if due is None or not due < today:
            continue
        screening["referral_status"] = "ESCALATED"
        db.touch(screening)

    # Step five: complete seasons whose games have finished reporting.
    for season in sorted(derive.program_seasons(program["id"]),
                         key=lambda s: (s["created_at"], s["_seq"])):
        if season["status"] != "ENTRIES_LOCKED":
            continue
        competition_date = parse_date(season["competition_date"])
        if competition_date is None or not today > competition_date:
            continue
        live = [e for e in db.entries.values()
                if e["season_id"] == season["id"] and e["status"] != "VOIDED"]
        if any(e["status"] not in ("RESULTED", "ADVANCED", "DISQUALIFIED")
               for e in live):
            continue
        season["status"] = "COMPLETED"
        db.touch(season)

    # Step six: re-derive every counter, then stamp the checkpoint.
    for athlete in derive.program_athletes(program["id"]):
        derive.recompute_athlete_ledger(athlete)
    counters = derive.compute_program_counters(program)
    counters["sweep_epoch"] = program["sweep_epoch"] + 1
    counters["last_sweep_at"] = clock_str()
    db.apply_changes(program, counters)
    return ok(ser_program(program))
