"""Business logic: clock-touch cascade, derived counters, funding recompute (PRD §2.4, §3)."""
from datetime import timedelta

import db
from helpers import iso_date, parse_dt, touch


def clock_touch():
    """Runs whenever the logical clock is set (PRD §2.4):
    - CONFIRMED clinics whose start_date has been reached -> IN_PROGRESS
    - COMPLETED screenings whose clinic's conversion_deadline has passed -> EXPIRED
    - year-boundary: recompute every hospital's admissions_ytd for the current year
    """
    now = db.CLOCK
    for clinic in db.clinics.values():
        if clinic["status"] == "CONFIRMED" and now >= parse_dt(clinic["start_date"]):
            clinic["status"] = "IN_PROGRESS"
            touch(clinic)
    for screening in db.screenings.values():
        if screening["status"] == "COMPLETED":
            clinic = db.clinics.get(screening["clinic_id"])
            if clinic and now > parse_dt(clinic["conversion_deadline"]):
                screening["status"] = "EXPIRED"
                touch(screening)
    recompute_admissions_ytd()


def recompute_admissions_ytd():
    """Recompute each hospital's admissions_ytd from ACCEPTED applications whose
    acceptance fell in the logical clock's current calendar year (true recomputation)."""
    year = db.CLOCK.year
    counts = {hid: 0 for hid in db.hospitals}
    for app in db.applications.values():
        if app["status"] != "ACCEPTED" or app.get("accepted_at") is None:
            continue
        if app["accepted_at"].year != year:
            continue
        prog = db.programs.get(app["program_id"])
        if prog and prog["hospital_id"] in counts:
            counts[prog["hospital_id"]] += 1
    for hid, n in counts.items():
        db.hospitals[hid]["admissions_ytd"] = n


def recompute_plan_funding(plan):
    """Recompute a CarePlan's funding_status (scaffold §1.3 care_plan_funding_status)."""
    designated = sum(
        a["amount_cents"] for a in db.allocations.values()
        if a.get("care_plan_id") == plan["id"] and a["status"] == "COMMITTED"
    )
    remaining_need = sum(
        s["estimated_cost_cents"] for s in db.stages.values()
        if s["care_plan_id"] == plan["id"]
        and s["status"] in ("PLANNED", "SCHEDULED", "DEFERRED")
    )
    if designated == 0:
        new_status = "UNFUNDED"
    elif designated >= remaining_need:
        new_status = "FULLY_FUNDED"
    else:
        new_status = "PARTIALLY_FUNDED"
    if new_status != plan["funding_status"]:
        plan["funding_status"] = new_status
        touch(plan)


def conversion_deadline_of(end_date):
    return end_date + timedelta(days=90)
