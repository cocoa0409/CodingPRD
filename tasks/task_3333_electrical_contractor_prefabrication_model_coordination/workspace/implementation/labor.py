"""Workers, labor-agreement rates, trade activities, crew days and the compliance ledger."""

from core import (CLOCK, DB, fail, new_record, num, rhu, shift_days, to_dt, touch)
from calculations import (APPLICABLE_CONTRACT_HOURS, APPRENTICE_TIER_DEFAULT,
                          OVERTIME_MULTIPLIER, WAIT_TIER_DEFAULT,
                          crew_day_labor_cost, crew_day_adjusted_cost,
                          field_credit_policy, gross_payroll_reconciliation,
                          ratio_limit_resolution, ring_band,
                          productivity_actuals)
from projects import governing_rate, rate_for, refresh_project, refresh_project_soft

ACTIVITY_KINDS = ("ELECTRICAL_INSTALL", "MECHANICAL_ROUGH", "PLUMBING_ROUGH",
                  "SPRINKLER_MAIN", "DRYWALL_CLOSEOUT")
OTHER_TRADE_KINDS = ("MECHANICAL_ROUGH", "PLUMBING_ROUGH", "SPRINKLER_MAIN",
                     "DRYWALL_CLOSEOUT")
BLOCKING_STATUSES = ("PLANNED", "PERMITTED", "ACTIVE", "DISALLOWED")
CLASSIFICATIONS = ("APPRENTICE", "JOURNEYMAN", "FOREMAN", "GENERAL_FOREMAN")

SAFETY_EXPIRY_DAYS = 90


# --------------------------------------------------------------------------
# Worker
# --------------------------------------------------------------------------

def create_worker(body):
    code = body.get("qualification_state_code")
    if code is not None and len(str(code)) > 40:
        fail("ERR_SHIFT_BAND_TOO_LONG")

    classification = body.get("classification")
    if classification not in CLASSIFICATIONS:
        fail("ERR_INVALID_PREFAB_TRANSITION", "classification is required")
    period = body.get("apprentice_period")

    if classification == "APPRENTICE":
        if period is not None and ring_band(period) is None:
            fail("ERR_JURISDICTION_DISPATCH_BAND", "unknown apprentice band")
        try:
            period_value = int(period)
        except (TypeError, ValueError):
            period_value = None
        if period_value is None or period_value < 1 or period_value > 5:
            fail("ERR_APPRENTICE_PERIOD_INVALID")
        period = period_value
    else:
        if period is not None:
            fail("ERR_APPRENTICE_PERIOD_INVALID")
        period = None

    worker = new_record(
        worker_code=body.get("worker_code"),
        full_name=body.get("full_name"),
        classification=classification,
        apprentice_period=period,
        home_jurisdiction_key=body.get("home_jurisdiction_key"),
        qualification_state_code=code,
        shift_band_delta=int(body.get("shift_band_delta") or 0),
        percent_complete_certified=num(body.get("percent_complete_certified"), 0.0),
        percent_complete_verified=num(body.get("percent_complete_verified"), 0.0),
        safety_verified_status=body.get("safety_verified_status") or "UNVERIFIED",
        safety_verification_code=body.get("safety_verification_code"),
        safety_verification_expires_iso=shift_days(CLOCK.now(), SAFETY_EXPIRY_DAYS).strftime(
            "%Y-%m-%dT%H:%M:%S") + ".000Z",
        journey_ring_claim_hours=0.0,
        upgrade_eligible=False,
        credited_field_hours=0.0,
    )
    DB.put("workers", worker)
    return worker


def worker_credited_field_hours(worker):
    from calculations import apprentice_upgrade_projection
    apprentice_upgrade_projection(worker)
    return worker


# --------------------------------------------------------------------------
# TradeContractRate
# --------------------------------------------------------------------------

def create_trade_contract_rate(body):
    effective = body.get("effective_from_iso")
    if effective is None:
        fail("ERR_INVALID_PREFAB_TRANSITION", "effective_from_iso is required")
    rate = new_record(
        jurisdiction_key=body.get("jurisdiction_key"),
        classification=body.get("classification"),
        apprentice_period=body.get("apprentice_period"),
        hourly_rate_cents=num(body.get("hourly_rate_cents"), 0.0),
        burden_pct=num(body.get("burden_pct"), 0.0),
        apprentice_ratio_max=body.get("apprentice_ratio_max"),
        wait_ratio_max=body.get("wait_ratio_max"),
        effective_from_iso=effective,
    )
    proposed = num(rate.get("apprentice_ratio_max"), None)
    if proposed is not None:
        check_rate_ratio_impact(rate, proposed)
    DB.put("trade_contract_rates", rate)
    for project in DB.all("projects"):
        if project.get("jurisdiction_key") == rate.get("jurisdiction_key"):
            refresh_project_soft(project)
    return rate


def check_rate_ratio_impact(rate, proposed_ratio_max):
    today = CLOCK.now()
    for project in DB.all("projects"):
        if project.get("jurisdiction_key") != rate.get("jurisdiction_key"):
            continue
        apprentice_hours = 0.0
        journeyman_hours = 0.0
        for day in DB.all("crew_days"):
            if day.get("project_id") != project["id"]:
                continue
            worker = DB.find("workers", day.get("worker_id"))
            if worker is None:
                continue
            if worker.get("classification") == "APPRENTICE":
                apprentice_hours += num(day.get("regular_hours"), 0.0) + OVERTIME_MULTIPLIER * num(day.get("overtime_hours"), 0.0)
            elif worker.get("classification") in ("JOURNEYMAN", "FOREMAN", "GENERAL_FOREMAN"):
                journeyman_hours += num(day.get("regular_hours"), 0.0) + num(day.get("overtime_hours"), 0.0)
        if journeyman_hours > 0 and apprentice_hours > proposed_ratio_max * journeyman_hours:
            fail("ERR_APPRENTICE_RATIO_EXCEEDED")


def filter_rates(args):
    records = DB.all("trade_contract_rates")
    jurisdiction = args.get("jurisdiction_key")
    if jurisdiction:
        records = [r for r in records if r.get("jurisdiction_key") == jurisdiction]
    return records


# --------------------------------------------------------------------------
# TradeActivity
# --------------------------------------------------------------------------

def find_blocking_activity(project_id, work_front_code, bay_code, sequence_index):
    for activity in DB.all("trade_activities"):
        if activity.get("project_id") != project_id:
            continue
        if activity.get("work_front_code") != work_front_code:
            continue
        if activity.get("bay_code") == bay_code:
            continue  # overlapping bay does not block under the agreement
        if activity.get("activity_kind") not in OTHER_TRADE_KINDS:
            continue
        if activity.get("status") not in BLOCKING_STATUSES:
            continue
        other_index = activity.get("written_sequence_index")
        if other_index is None or sequence_index is None:
            continue
        if int(other_index) < int(sequence_index):
            return activity
    return None


def create_trade_activity(body):
    project = require_project(body.get("project_id"))
    for ref, table in (("rate_id", "trade_contract_rates"), ("revision_id", "revisions"), ("permit_id", "trade_activities")):
        ref_id = body.get(ref)
        if ref_id and DB.find(table, ref_id) is None:
            fail("ERR_REFERENCED_ENTITY_NOT_FOUND")

    project_id = project["id"]
    sequence_index = body.get("written_sequence_index")
    work_front = body.get("work_front_code")
    bay = body.get("bay_code")
    if find_blocking_activity(project_id, work_front, bay, sequence_index) is not None:
        fail("ERR_INSTALL_SEQUENCE_VIOLATION")

    activity = new_record(
        project_id=project_id,
        trade_key=body.get("trade_key"),
        activity_kind=body.get("activity_kind"),
        work_front_code=work_front,
        bay_code=bay,
        written_sequence_index=sequence_index,
        planned_start_iso=body.get("planned_start_iso"),
        planned_duration_days=body.get("planned_duration_days"),
        revision_id=body.get("revision_id"),
        rate_id=body.get("rate_id"),
        permit_id=body.get("permit_id"),
        status="PLANNED",
        suspension_reason=None,
        actual_start_iso=None,
        craft_hours_credit=0.0,
        rework_trade_value_cents=0,
        rework_hours=0.0,
    )
    DB.put("trade_activities", activity)
    refresh_project_soft(project)
    return activity


def require_project(project_id):
    if not project_id:
        fail("ERR_PROJECT_NOT_FOUND")
    project = DB.find("projects", project_id)
    if project is None:
        fail("ERR_PROJECT_NOT_FOUND")
    return project


def require_activity(activity_id):
    if not activity_id:
        fail("ERR_REFERENCED_ENTITY_NOT_FOUND")
    activity = DB.find("trade_activities", activity_id)
    if activity is None:
        fail("ERR_REFERENCED_ENTITY_NOT_FOUND")
    return activity


ACTIVITY_TRANSITIONS = {
    ("PLANNED", "PERMITTED"): "permit",
    ("PERMITTED", "ACTIVE"): "activate",
    ("ACTIVE", "COMPLETE"): "complete",
    ("ACTIVE", "DISALLOWED"): "suspend",
    ("DISALLOWED", "ACTIVE"): "resume",
}


def activity_crew(activity_id):
    return [day for day in DB.all("crew_days") if day.get("trade_activity_id") == activity_id]


def activity_crew_excess(activity_id):
    from compliance import ledger_rows_for_activity
    total = 0.0
    for row in ledger_rows_for_activity(activity_id):
        total += num(row.get("excess_apprentice_hours"), 0.0)
    return total


def set_activity_status(activity, target):
    if target is None:
        fail("ERR_INVALID_PREFAB_TRANSITION", "status is required")
    project = DB.find("projects", activity.get("project_id"))
    current = activity.get("status")
    key = (current, target)
    if key not in ACTIVITY_TRANSITIONS:
        fail("ERR_INVALID_PREFAB_TRANSITION")
    handler = ACTIVITY_TRANSITIONS[key]

    if handler == "permit":
        permit_id = activity.get("permit_id")
        if permit_id:
            permit = DB.find("trade_activities", permit_id)
            if permit is None:
                fail("ERR_REFERENCED_ENTITY_NOT_FOUND")
            if permit.get("status") != "COMPLETE":
                fail("ERR_INSTALL_SEQUENCE_VIOLATION")
        if find_blocking_activity(activity.get("project_id"), activity.get("work_front_code"),
                                  activity.get("bay_code"), activity.get("written_sequence_index")) is not None:
            fail("ERR_INSTALL_SEQUENCE_VIOLATION")
        activity["status"] = "PERMITTED"
    elif handler == "activate":
        if project is not None:
            for day in activity_crew(activity["id"]):
                worker = DB.find("workers", day.get("worker_id"))
                if worker is None:
                    fail("ERR_REFERENCED_ENTITY_NOT_FOUND")
                if worker.get("home_jurisdiction_key") != project.get("jurisdiction_key"):
                    fail("ERR_JURISDICTION_DISPATCH_BAND")
        activity["status"] = "ACTIVE"
        activity["actual_start_iso"] = CLOCK.now_iso()
        activity["craft_hours_credit"] = rhu(num(activity.get("rework_hours"), 0.0), 2)
    elif handler == "complete":
        if activity_crew_excess(activity["id"]) > 0:
            fail("ERR_APPRENTICE_RATIO_EXCEEDED")
        activity["status"] = "COMPLETE"
        activity["suspension_reason"] = None
        if project is not None:
            productivity_actuals(project)
    elif handler == "suspend":
        if activity_crew_excess(activity["id"]) <= 0:
            fail("ERR_INVALID_PREFAB_TRANSITION")
        activity["status"] = "DISALLOWED"
        activity["suspension_reason"] = "Apprenticeship ratio breach"
        if project is not None:
            project["apprentice_breach_flag"] = True
    elif handler == "resume":
        if activity_crew_excess(activity["id"]) > 0:
            fail("ERR_APPRENTICE_RATIO_EXCEEDED")
        activity["status"] = "ACTIVE"
        activity["suspension_reason"] = None

    touch(activity)
    if project is not None:
        refresh_project_soft(project)
    return activity


def filter_activities(args):
    records = DB.all("trade_activities")
    for key in ("project_id", "revision_id", "rate_id", "permit_id"):
        value = args.get(key)
        if value:
            records = [r for r in records if r.get(key) == value]
    work_front = args.get("work_front_code")
    if work_front:
        records = [r for r in records if r.get("work_front_code") == work_front]
    return records


# --------------------------------------------------------------------------
# CrewDay
# --------------------------------------------------------------------------

def create_crew_day(body):
    project = require_project(body.get("project_id"))
    worker = DB.find("workers", body.get("worker_id"))
    if worker is None:
        fail("ERR_REFERENCED_ENTITY_NOT_FOUND")
    activity = DB.find("trade_activities", body.get("trade_activity_id"))
    if activity is None:
        fail("ERR_REFERENCED_ENTITY_NOT_FOUND")
    foreman_id = body.get("foreman_id")
    if foreman_id and DB.find("workers", foreman_id) is None:
        fail("ERR_REFERENCED_ENTITY_NOT_FOUND")
    if body.get("acknowledge_mode") not in ("RELEASE", "FINAL"):
        fail("ERR_INVALID_PREFAB_TRANSITION", "acknowledge_mode is required")

    regular = num(body.get("regular_hours"), 0.0)
    overtime = num(body.get("overtime_hours"), 0.0)
    apprentice_hours = (regular + OVERTIME_MULTIPLIER * overtime) if worker.get("classification") == "APPRENTICE" else 0.0
    journeyman_hours = (regular + overtime) if worker.get("classification") in ("JOURNEYMAN", "FOREMAN", "GENERAL_FOREMAN") else 0.0

    enforce_ratio_cap(project, worker, apprentice_hours,
                      work_date_iso=body.get("work_date_iso"))
    enforce_dispatch_band(project, worker)

    crew_day = new_record(
        project_id=project["id"],
        worker_id=worker["id"],
        foreman_id=foreman_id,
        trade_activity_id=activity["id"],
        work_date_iso=body.get("work_date_iso"),
        regular_hours=regular,
        overtime_hours=overtime,
        report_sequence=body.get("report_sequence"),
        acknowledge_mode=body.get("acknowledge_mode"),
        accepted_for_credit=False,
        guilt_added=False,
        credited_hours=0.0,
        labor_cost_cents=0,
        adjusted_value_cents=0,
        apprentice_hours=apprentice_hours,
        journeyman_hours=journeyman_hours,
        acknowledged=False,
    )
    DB.put("crew_days", crew_day)
    field_credit_policy(project, crew_day["worker_id"], crew_day["work_date_iso"])
    crew_day["labor_cost_cents"] = crew_day_labor_cost(crew_day)
    crew_day["adjusted_value_cents"] = crew_day_adjusted_cost(crew_day, project)
    return crew_day


def enforce_dispatch_band(project, worker):
    if worker.get("home_jurisdiction_key") != project.get("jurisdiction_key"):
        fail("ERR_JURISDICTION_DISPATCH_BAND")
    if worker.get("classification") == "APPRENTICE" and ring_band(worker.get("apprentice_period")) is None:
        fail("ERR_JURISDICTION_DISPATCH_BAND")


def project_hours(project_id):
    apprentice = 0.0
    journeyman = 0.0
    for day in DB.all("crew_days"):
        if day.get("project_id") != project_id:
            continue
        apprentice += num(day.get("apprentice_hours"), 0.0)
        journeyman += num(day.get("journeyman_hours"), 0.0)
    return apprentice, journeyman


def enforce_ratio_cap(project, worker, extra_apprentice_hours, work_date_iso=None):
    apprentice_hours, journeyman_hours = project_hours(project["id"])
    # PRD §3.6: the governing rate row is the latest one whose `effective_from_iso`
    # is at or before the crew day's `work_date_iso`, so the cap is resolved as of
    # the work date rather than as of the logical clock.
    ratio_limit, _wait = ratio_limit_resolution(project, worker, work_date_iso)
    apprentice_hours += num(extra_apprentice_hours, 0.0)
    if journeyman_hours <= 0:
        if apprentice_hours > 0:
            fail("ERR_APPRENTICE_RATIO_EXCEEDED")
        return
    if apprentice_hours > ratio_limit * journeyman_hours:
        fail("ERR_APPRENTICE_RATIO_EXCEEDED")


def acknowledge_crew_day(crew_day, body):
    expected = body.get("expected_crew_day_version")
    if expected is None:
        fail("ERR_STALE_VERSION")
    if int(expected) != int(crew_day.get("version", 0)):
        fail("ERR_STALE_VERSION")

    project = DB.find("projects", crew_day.get("project_id"))
    worker = DB.find("workers", crew_day.get("worker_id"))
    if project is None or worker is None:
        fail("ERR_REFERENCED_ENTITY_NOT_FOUND")

    mode = body.get("acknowledge_mode")
    if mode is not None:
        if mode not in ("RELEASE", "FINAL"):
            fail("ERR_INVALID_PREFAB_TRANSITION")
        crew_day["acknowledge_mode"] = mode

    winner = field_credit_policy(project, crew_day["worker_id"], crew_day["work_date_iso"])
    crew_day["guilt_added"] = bool(winner is not None and winner["id"] == crew_day["id"])
    crew_day["labor_cost_cents"] = crew_day_labor_cost(crew_day)
    crew_day["adjusted_value_cents"] = crew_day_adjusted_cost(crew_day, project)

    from compliance import refresh_ledger_for_crew_day
    refresh_ledger_for_crew_day(crew_day, project, worker)

    crew_day["acknowledged"] = True
    touch(crew_day)

    from calculations import apprentice_upgrade_projection
    apprentice_upgrade_projection(worker)

    activity = DB.find("trade_activities", crew_day.get("trade_activity_id"))
    if activity is not None:
        excess = activity_crew_excess(activity["id"])
        # PRD §3.5: "An `ACTIVE` activity moves to `DISALLOWED` when at least one
        # crew member on it carries a compliance-ledger row with
        # `excess_apprentice_hours` greater than zero" and "The activity resumes
        # when every crew member assigned to it has `excess_apprentice_hours`
        # equal to zero — which happens when later crew-day acknowledgments bring
        # the ratio back inside the cap".
        if activity.get("status") == "ACTIVE" and excess > 0:
            activity["status"] = "DISALLOWED"
            activity["suspension_reason"] = "Apprenticeship ratio breach"
            touch(activity)
        elif activity.get("status") == "DISALLOWED" and excess <= 0:
            activity["status"] = "ACTIVE"
            activity["suspension_reason"] = None
            touch(activity)
    productivity_actuals(project)
    refresh_project_soft(project)
    project["apprentice_breach_flag"] = any(
        num(row.get("excess_apprentice_hours"), 0.0) > 0
        for row in DB.all("compliance_ledger")
        if row.get("project_id") == project["id"])
    return crew_day


def filter_crew_days(args):
    records = DB.all("crew_days")
    for key in ("project_id", "worker_id", "foreman_id", "trade_activity_id"):
        value = args.get(key)
        if value:
            records = [r for r in records if r.get(key) == value]
    work_date = args.get("work_date_iso")
    if work_date:
        records = [r for r in records if r.get("work_date_iso") == work_date]
    return records


def filter_ledger(args):
    records = DB.all("compliance_ledger")
    for key in ("project_id", "worker_id", "trade_activity_id", "rate_id"):
        value = args.get(key)
        if value:
            records = [r for r in records if r.get(key) == value]
    return records