"""Grievance intake, the step ladder, withdrawal / consolidation and the ledger."""

from decimal import Decimal

from flask import Blueprint

from core import (
    ApiError, db, now, base_record, touch, ok, paginated, qp, order_by,
    authenticate, get_body, bad, floor_days, add_days,
    req_string, opt_string, req_enum, opt_enum, req_int, opt_int, opt_number,
    req_dt, req_id, opt_id, opt_bool,
    ROLE_UNION_STEWARD, ROLE_GRIEVANT, ROLE_ANALYST, ROLE_DIRECTOR, READ_ROLES,
)
import derive
from derive import (
    GRIEVANCE_TERMINAL, DISPOSITIONS, COST_CATEGORIES, BEARING_PARTIES,
    ser_grievance, ser_step, ser_cost_entry,
)
import services

bp = Blueprint("grievance", __name__)

GRIEVANCE_READ_ROLES = tuple(READ_ROLES) + (ROLE_GRIEVANT,)


# --------------------------------------------------------------------------
# Intake (PRD 3.2)
# --------------------------------------------------------------------------
@bp.post("/grievances")
def file_grievance():
    user_id, role = authenticate([ROLE_UNION_STEWARD])
    body = get_body()

    # ladder 6 — body schema
    unit_id = req_id(body, "bargaining_unit_id")
    grievant_id = req_id(body, "grievant_id")
    supervisor_id = req_id(body, "respondent_supervisor_id")
    clause_id = req_id(body, "clause_id")
    statement = req_string(body, "statement")
    incident_date = req_dt(body, "incident_date")
    discovery_date = req_dt(body, "discovery_date")
    remedy_requested = opt_int(body, "remedy_requested_cents", 0, minimum=0)
    back_pay_claimed = opt_number(body, "back_pay_hours_claimed", Decimal(0), minimum=0)

    # ladder 7 — body foreign keys, resolved in the declared order
    unit = services.find_unit(unit_id)
    grievant = services.find_employee(grievant_id)
    supervisor = services.find_employee(supervisor_id)
    clause = services.find_clause(clause_id)

    # ladder 10 — the agreement must derive to ACTIVE
    if derive.unit_status(unit) != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_EXPIRED", "The collective agreement has expired.")

    # ladder 17 / 18 — referential rules
    if grievant["bargaining_unit_id"] != unit["id"] or \
            supervisor["bargaining_unit_id"] != unit["id"]:
        raise ApiError("ERR_UNIT_MEMBERSHIP_MISMATCH",
                       "The grievant and the respondent supervisor must belong to the unit.")
    if clause["bargaining_unit_id"] != unit["id"]:
        raise ApiError("ERR_CLAUSE_UNIT_MISMATCH",
                       "The cited clause belongs to a different bargaining unit.")

    # ladder 29 — date ordering
    instant = now()
    if not (incident_date <= discovery_date <= instant):
        raise ApiError("ERR_INVALID_DISCOVERY_DATE",
                       "incident_date must be at or before discovery_date, which must not "
                       "lie in the future.")

    # ladder 30 — the filing window; only the expedited flag reshapes it
    window = derive.filing_window_days(unit, clause)
    elapsed = floor_days(discovery_date, instant)
    if elapsed > window:
        raise ApiError("ERR_GRIEVANCE_UNTIMELY",
                       "The grievance was filed outside the contractual filing window.")

    ordinal = sum(1 for g in db.grievances.values()
                  if g["bargaining_unit_id"] == unit["id"]) + 1
    grievance = base_record()
    grievance.update({
        "bargaining_unit_id": unit["id"],
        "grievant_id": grievant["id"],
        "respondent_supervisor_id": supervisor["id"],
        "clause_id": clause["id"],
        "consolidated_into_id": None,
        "case_number": "GR-%s-%04d" % (unit["local_number"], ordinal),
        "statement": statement,
        "incident_date": incident_date,
        "discovery_date": discovery_date,
        "filed_at": instant,
        "filed_by_steward_employee_id": user_id,
        "current_step": 1,
        "status": "FILED",
        "timeliness_state": "TIMELY",
        "remedy_requested_cents": remedy_requested,
        "back_pay_hours_claimed": back_pay_claimed,
        "settled_amount_cents": 0,
    })
    db.grievances[grievance["id"]] = grievance
    return ok(ser_grievance(grievance), 201)


@bp.get("/grievances/<grievance_id>")
def read_grievance(grievance_id):
    user_id, role = authenticate(GRIEVANCE_READ_ROLES)
    grievance = services.find_grievance(grievance_id)
    if role == ROLE_GRIEVANT:
        services.require_case_participant(grievance, user_id)
    return ok(ser_grievance(grievance))


@bp.get("/grievances")
def list_grievances():
    authenticate(READ_ROLES)
    rows = list(db.grievances.values())
    for field, param in (
        ("bargaining_unit_id", "bargaining_unit_id"),
        ("grievant_id", "grievant_id"),
        ("respondent_supervisor_id", "respondent_supervisor_id"),
        ("clause_id", "clause_id"),
        ("consolidated_into_id", "consolidated_into_id"),
        ("status", "status"),
    ):
        value = qp(param)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    timeliness = qp("timeliness_state")
    if timeliness is not None:
        rows = [r for r in rows if derive.refresh_timeliness(r) == timeliness]
    rows = order_by(rows, "created_at", "case_number")
    return paginated(rows, ser_grievance)


# --------------------------------------------------------------------------
# The step ladder (PRD 3.3)
# --------------------------------------------------------------------------
@bp.post("/grievances/<grievance_id>/steps")
def schedule_step(grievance_id):
    authenticate([ROLE_ANALYST])
    grievance = services.find_grievance(grievance_id)
    body = get_body()

    meeting_scheduled_at = req_dt(body, "meeting_scheduled_at")
    extension_days = opt_int(body, "extension_days", 0, minimum=0)

    # ladder 9
    if grievance["status"] not in ("FILED", "APPEALED"):
        raise ApiError("ERR_INVALID_GRIEVANCE_STATE",
                       "A step meeting may only be scheduled from FILED or APPEALED.")
    unit = db.bargaining_units[grievance["bargaining_unit_id"]]
    # ladder 10
    if derive.unit_status(unit) != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_EXPIRED", "The collective agreement has expired.")
    # ladder 27
    if extension_days > 0 and not unit["tolling_enabled"]:
        raise ApiError("ERR_TOLLING_NOT_PERMITTED",
                       "The agreement does not permit tolling of the response window.")
    # ladder 31
    if meeting_scheduled_at <= now():
        raise ApiError("ERR_MEETING_DATE_IN_PAST",
                       "meeting_scheduled_at must be strictly after the current instant.")

    step = base_record()
    step.update({
        "grievance_id": grievance["id"],
        "step_number": grievance["current_step"],
        "status": "SCHEDULED",
        "meeting_scheduled_at": meeting_scheduled_at,
        "extension_days": extension_days,
        "meeting_held_at": None,
        "response_due_at": None,
        "responded_at": None,
        "disposition": None,
        "response_summary": None,
        "granted_amount_cents": 0,
        "responded_by_user_id": None,
        "late_by_days": 0,
    })
    db.grievance_steps[step["id"]] = step

    grievance["status"] = "STEP_MEETING_SCHEDULED"
    touch(grievance)
    derive.refresh_timeliness(grievance)
    return ok(ser_step(step), 201)


@bp.get("/grievances/<grievance_id>/steps")
def list_steps(grievance_id):
    user_id, role = authenticate(GRIEVANCE_READ_ROLES)
    grievance = services.find_grievance(grievance_id)
    if role == ROLE_GRIEVANT:
        services.require_case_participant(grievance, user_id)
    rows = derive.steps_of(grievance["id"])
    status = qp("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = order_by(rows, "step_number", "created_at")
    return paginated(rows, ser_step)


@bp.post("/grievance-steps/<step_id>/hold")
def hold_step(step_id):
    authenticate([ROLE_ANALYST])
    step = services.find_step(step_id)
    grievance = db.grievances[step["grievance_id"]]

    if step["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STEP_STATE", "Only a SCHEDULED step may be held.")
    if grievance["status"] != "STEP_MEETING_SCHEDULED":
        raise ApiError("ERR_INVALID_GRIEVANCE_STATE",
                       "The grievance is not awaiting a scheduled step meeting.")

    unit = db.bargaining_units[grievance["bargaining_unit_id"]]
    clause = db.contract_clauses[grievance["clause_id"]]

    step["status"] = "HELD"
    step["meeting_held_at"] = now()
    step["response_due_at"] = derive.step_response_deadline(step, grievance, unit, clause)
    touch(step)

    grievance["status"] = "AWAITING_RESPONSE"
    touch(grievance)
    derive.refresh_timeliness(grievance)
    return ok(ser_step(step))


@bp.post("/grievance-steps/<step_id>/respond")
def respond_step(step_id):
    user_id, role = authenticate([ROLE_ANALYST])
    step = services.find_step(step_id)
    grievance = db.grievances[step["grievance_id"]]
    body = get_body()

    disposition = req_enum(body, "disposition", DISPOSITIONS)
    response_summary = req_string(body, "response_summary")
    granted_supplied = "granted_amount_cents" in body and body["granted_amount_cents"] is not None
    granted_amount = opt_int(body, "granted_amount_cents", 0, minimum=0)
    if granted_supplied and disposition == "DENIED":
        bad("granted_amount_cents",
            "may only be supplied alongside a GRANTED or PARTIAL disposition")

    if step["status"] != "HELD":
        raise ApiError("ERR_INVALID_STEP_STATE", "Only a HELD step may be answered.")
    if grievance["status"] != "AWAITING_RESPONSE":
        raise ApiError("ERR_INVALID_GRIEVANCE_STATE",
                       "The grievance is not awaiting an employer answer.")

    instant = now()
    step["status"] = "ANSWERED"
    step["responded_at"] = instant
    step["responded_by_user_id"] = user_id
    step["disposition"] = disposition
    step["response_summary"] = response_summary
    step["granted_amount_cents"] = granted_amount if disposition != "DENIED" else 0
    step["late_by_days"] = max(0, floor_days(step["response_due_at"], instant))
    touch(step)

    if disposition == "GRANTED":
        grievance["settled_amount_cents"] = step["granted_amount_cents"]
        services.terminal_cascade(grievance, "SETTLED")
        touch(grievance)
    else:
        if disposition == "PARTIAL":
            grievance["settled_amount_cents"] = (
                grievance["settled_amount_cents"] + step["granted_amount_cents"])
        grievance["status"] = "ANSWERED"
        touch(grievance)
        derive.refresh_timeliness(grievance)

    return ok(ser_step(step))


@bp.post("/grievances/<grievance_id>/appeal")
def appeal_grievance(grievance_id):
    user_id, role = authenticate([ROLE_UNION_STEWARD])
    grievance = services.find_grievance(grievance_id)
    services.require_filing_steward(grievance, user_id)
    body = get_body()
    req_string(body, "appeal_statement")

    instant = now()
    step = derive.latest_step(grievance["id"])
    deemed_denied_route = False
    if grievance["status"] == "ANSWERED":
        pass
    elif (grievance["status"] == "AWAITING_RESPONSE"
          and step is not None
          and step["status"] == "HELD"
          and step["response_due_at"] is not None
          and instant > step["response_due_at"]):
        deemed_denied_route = True
    else:
        raise ApiError("ERR_INVALID_GRIEVANCE_STATE",
                       "The grievance is not in a state from which an appeal may be taken.")

    unit = db.bargaining_units[grievance["bargaining_unit_id"]]
    if derive.unit_status(unit) != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_EXPIRED", "The collective agreement has expired.")

    if grievance["current_step"] >= 3:
        raise ApiError("ERR_STEP_LADDER_EXHAUSTED",
                       "The step ladder is exhausted; no appeal may be taken from step 3.")

    if not deemed_denied_route:
        deadline = derive.appeal_deadline_at(grievance)
        if deadline is not None and instant > deadline:
            raise ApiError("ERR_APPEAL_WINDOW_EXPIRED", "The appeal window has closed.")

    if deemed_denied_route:
        step["status"] = "DEEMED_DENIED"
        touch(step)

    grievance["current_step"] = grievance["current_step"] + 1
    grievance["status"] = "APPEALED"
    touch(grievance)
    if deemed_denied_route:
        grievance["timeliness_state"] = "EMPLOYER_DEFAULT"
    else:
        derive.refresh_timeliness(grievance)
    return ok(ser_grievance(grievance))


@bp.post("/grievances/<grievance_id>/withdraw")
def withdraw_grievance(grievance_id):
    user_id, role = authenticate([ROLE_UNION_STEWARD])
    grievance = services.find_grievance(grievance_id)
    services.require_filing_steward(grievance, user_id)
    body = get_body()

    req_string(body, "reason")
    target_id = opt_id(body, "consolidated_into_grievance_id")

    target = None
    if target_id is not None:
        target = services.find_grievance(target_id)
        if target["id"] == grievance["id"]:
            bad("consolidated_into_grievance_id",
                "may not name the grievance being withdrawn")
        if target["bargaining_unit_id"] != grievance["bargaining_unit_id"]:
            bad("consolidated_into_grievance_id",
                "must name a grievance of the same bargaining unit")
        if target["clause_id"] != grievance["clause_id"]:
            bad("consolidated_into_grievance_id",
                "must name a grievance citing the same contract clause")

    if grievance["status"] in GRIEVANCE_TERMINAL:
        raise ApiError("ERR_INVALID_GRIEVANCE_STATE", "The grievance is already terminal.")
    if target is not None and target["status"] in GRIEVANCE_TERMINAL:
        raise ApiError("ERR_INVALID_GRIEVANCE_STATE",
                       "The surviving grievance is already terminal.")

    if target is None:
        services.terminal_cascade(grievance, "WITHDRAWN")
        touch(grievance)
    else:
        grievance["consolidated_into_id"] = target["id"]
        services.terminal_cascade(grievance, "CONSOLIDATED")
        touch(grievance)
        target["remedy_requested_cents"] = (
            target["remedy_requested_cents"] + grievance["remedy_requested_cents"])
        target["back_pay_hours_claimed"] = (
            target["back_pay_hours_claimed"] + grievance["back_pay_hours_claimed"])
        touch(target)

    return ok(ser_grievance(grievance))


# --------------------------------------------------------------------------
# The case cost ledger (PRD 3.9)
# --------------------------------------------------------------------------
@bp.post("/grievances/<grievance_id>/cost-entries")
def post_cost_entry(grievance_id):
    authenticate([ROLE_ANALYST])
    grievance = services.find_grievance(grievance_id)
    body = get_body()

    category = req_enum(body, "category", COST_CATEGORIES)
    amount_cents = req_int(body, "amount_cents", minimum=1)
    bearing_party = req_enum(body, "bearing_party", BEARING_PARTIES)

    if grievance["status"] in GRIEVANCE_TERMINAL:
        raise ApiError("ERR_INVALID_GRIEVANCE_STATE",
                       "Costs may not be posted against a terminal grievance.")

    entry = services.create_cost_entry(
        grievance["id"], category, amount_cents, bearing_party, "MANUAL")
    return ok(ser_cost_entry(entry), 201)


@bp.get("/grievances/<grievance_id>/cost-entries")
def list_cost_entries(grievance_id):
    authenticate(READ_ROLES)
    grievance = services.find_grievance(grievance_id)
    rows = derive.cost_entries_of(grievance["id"])
    for field in ("category", "status", "bearing_party"):
        value = qp(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    rows = order_by(rows, "incurred_at", "created_at")
    return paginated(rows, ser_cost_entry)


@bp.post("/cost-entries/<entry_id>/void")
def void_cost_entry(entry_id):
    user_id, role = authenticate([ROLE_DIRECTOR])
    entry = services.find_cost_entry(entry_id)
    body = get_body()
    reason = req_string(body, "void_reason")

    if entry["status"] != "POSTED":
        raise ApiError("ERR_COST_ENTRY_ALREADY_VOIDED", "The cost entry is already voided.")

    services.void_cost_entry(entry, reason, user_id)
    return ok(ser_cost_entry(entry))
