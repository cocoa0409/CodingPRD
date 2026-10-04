"""ComplianceLedger rows and the apprentice ratio cap they enforce."""

from core import DB, new_record, num, rhu, touch
from calculations import (OVERTIME_MULTIPLIER, gross_payroll_reconciliation,
                          ratio_limit_resolution)


def ledger_key(project_id, worker_id, activity_id, rate_id):
    return (project_id, worker_id, activity_id, rate_id)


def find_ledger_row(project_id, worker_id, activity_id, rate_id):
    for row in DB.all("compliance_ledger"):
        if ledger_key(row.get("project_id"), row.get("worker_id"),
                      row.get("trade_activity_id"), row.get("rate_id")) == ledger_key(
                project_id, worker_id, activity_id, rate_id):
            return row
    return None


def ledger_rows_for_activity(activity_id):
    return [r for r in DB.all("compliance_ledger") if r.get("trade_activity_id") == activity_id]


def ledger_rows_for_project(project_id):
    return [r for r in DB.all("compliance_ledger") if r.get("project_id") == project_id]


def _project_wide_hours(project_id, exclude_row=None):
    apprentice = 0.0
    journeyman = 0.0
    for row in ledger_rows_for_project(project_id):
        if exclude_row is not None and row is exclude_row:
            continue
        apprentice += num(row.get("apprentice_hours"), 0.0)
        journeyman += num(row.get("journeyman_hours"), 0.0)
    return apprentice, journeyman


def recompute_ledger_row(row):
    """Cumulative apprentice / journeyman / excess hours for a ledger row.

    PRD §3.6: the row's `apprentice_hours` is "cumulative regular apprentice
    hours plus one and a half times the cumulative overtime apprentice hours on
    the activity", and `journeyman_hours` is "cumulative journeyman and foreman
    hours with overtime counted at 1.0" — both scoped to the activity the row
    accrued on, not to the single worker the row names. That is what makes
    `excess_apprentice_hours` a statement about the crew, which is the figure
    PRD §3.5 suspends the activity on.
    """
    rows = [day for day in DB.all("crew_days")
            if day.get("project_id") == row.get("project_id")
            and day.get("trade_activity_id") == row.get("trade_activity_id")]
    apprentice = 0.0
    journeyman = 0.0
    for day in rows:
        apprentice += num(day.get("apprentice_hours"), 0.0)
        journeyman += num(day.get("journeyman_hours"), 0.0)
    row["apprentice_hours"] = rhu(apprentice, 2)
    row["journeyman_hours"] = rhu(journeyman, 2)
    ratio_limit = num(row.get("ratio_limit"), 1.0)
    excess = apprentice - ratio_limit * journeyman
    row["excess_apprentice_hours"] = rhu(max(0.0, excess), 2)
    # PRD §3.6: "the row's `apprentice_hours` must equal its original apprentice
    # hours plus `adjustment_delta_hours` at all times". A freshly opened row has
    # no corrections yet, so its baseline is the hours it just accumulated.
    original = row.get("original_apprentice_hours")
    if original is None:
        row["original_apprentice_hours"] = rhu(apprentice, 2)
        row["adjustment_delta_hours"] = 0.0
    else:
        row["adjustment_delta_hours"] = rhu(apprentice - num(original, apprentice), 2)
    row["certified_hours"] = rhu(apprentice, 2)
    row["ledger_credit_cents"] = int(round(row["certified_hours"] * num(row.get("pay_rate_cents"), 0.0)
                                          * (1 + num(row.get("burden_pct"), 0.0))))
    return row


def refresh_ledger_for_crew_day(crew_day, project, worker):
    rate_row = None
    activity = DB.find("trade_activities", crew_day.get("trade_activity_id"))
    rate_id = (activity or {}).get("rate_id")
    if rate_id:
        rate_row = DB.find("trade_contract_rates", rate_id)

    row = find_ledger_row(project["id"], worker["id"], crew_day.get("trade_activity_id"), rate_id)
    ratio_limit, wait_ratio_limit = ratio_limit_resolution(project, worker, crew_day.get("work_date_iso"))

    if row is None:
        row = new_record(
            project_id=project["id"],
            worker_id=worker["id"],
            trade_activity_id=crew_day.get("trade_activity_id"),
            rate_id=rate_id,
            jurisdiction_key=project.get("jurisdiction_key"),
            classification=worker.get("classification"),
            regular_hours=0.0,
            overtime_hours=0.0,
            pay_rate_cents=num((rate_row or {}).get("hourly_rate_cents"), 0.0),
            burden_pct=num((rate_row or {}).get("burden_pct"), 0.0),
            projected_ratio=0.0,
            total_cents=0,
            certified_hours=0.0,
            ledger_credit_cents=0,
            gross_payroll_cents=0,
            adjusted_payroll_cents=0,
            apprentice_hours=0.0,
            journeyman_hours=0.0,
            ratio_limit=ratio_limit,
            wait_ratio_limit=wait_ratio_limit,
            excess_apprentice_hours=0.0,
            adjustment_delta_hours=0.0,
            original_apprentice_hours=None,
        )
        DB.put("compliance_ledger", row)
    else:
        row["ratio_limit"] = ratio_limit
        row["wait_ratio_limit"] = wait_ratio_limit

    # the ledger row accumulates the day's hours into its own totals
    row["regular_hours"] = rhu(num(row.get("regular_hours"), 0.0) + num(crew_day.get("regular_hours"), 0.0), 2)
    row["overtime_hours"] = rhu(num(row.get("overtime_hours"), 0.0) + num(crew_day.get("overtime_hours"), 0.0), 2)

    recompute_ledger_row(row)
    gross_payroll_reconciliation(row, project)

    # Every row of the activity carries the same activity-scoped cumulative
    # hours (PRD §3.6), so a crew day reported against any one of them moves the
    # siblings' totals too — otherwise a later acknowledgment could bring the
    # crew back inside the cap while a stale sibling row still reported a breach
    # (PRD §3.5: the activity resumes "when every crew member assigned to it has
    # `excess_apprentice_hours` equal to zero").
    for sibling in ledger_rows_for_activity(row.get("trade_activity_id")):
        if sibling is row:
            continue
        recompute_ledger_row(sibling)
        touch(sibling)

    apprentice_all, journeyman_all = _project_wide_hours(project["id"])
    row["projected_ratio"] = rhu(apprentice_all / journeyman_all, 4) if journeyman_all > 0 else 0.0
    touch(row)

    project["apprentice_ratio_max"] = min(ratio_limit, wait_ratio_limit)
    return row


def refresh_project_ledger(project):
    rows = ledger_rows_for_project(project["id"])
    apprentice_all = sum(num(r.get("apprentice_hours"), 0.0) for r in rows)
    journeyman_all = sum(num(r.get("journeyman_hours"), 0.0) for r in rows)
    if rows:
        first = rows[0]
        project["apprentice_ratio_max"] = min(num(first.get("ratio_limit"), 1.0),
                                              num(first.get("wait_ratio_limit"), 1.0))
    project["apprentice_breach_flag"] = any(num(r.get("excess_apprentice_hours"), 0.0) > 0 for r in rows)
    return apprentice_all, journeyman_all