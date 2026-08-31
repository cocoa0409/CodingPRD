"""Derived-field recomputation and the cascade chains."""
from datetime import timedelta

from core import (D, apply_changes, completed_years, date_at_midnight, date_str,
                  db, iso_ms, parse_date, parse_instant, touch)
from calc import (POOL_STATUSES, RESERVE_STATUSES, SELECTED_STATUSES,
                  MIN_PART_TIME_HOURS, OWBPA_PROTECTED_AGE,
                  warn_determination, window_start_for_site)


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------
def site_employees(site_id):
    return [e for e in db.employees.values() if e["site_id"] == site_id]


def plan_selections(plan_id):
    return [s for s in db.selections.values() if s["plan_id"] == plan_id]


def selection_offers(selection_id):
    return [o for o in db.offers.values() if o["selection_id"] == selection_id]


def employee_offers(employee_id):
    out = []
    for offer in db.offers.values():
        sel = db.selections.get(offer["selection_id"])
        if sel is not None and sel["employee_id"] == employee_id:
            out.append(offer)
    return out


def federal_rule():
    for rule in db.warn_rules.values():
        if rule["jurisdiction"] == "FEDERAL":
            return rule
    return None


def state_rule(state_code):
    for rule in db.warn_rules.values():
        if rule["jurisdiction"] == "STATE" and rule["state_code"] == state_code:
            return rule
    return None


def rule_for(site, jurisdiction):
    if jurisdiction == "FEDERAL":
        return federal_rule()
    return state_rule(site["state_code"])


def latest_analysis(plan_id):
    rows = [a for a in db.analyses.values() if a["plan_id"] == plan_id]
    if not rows:
        return None
    rows.sort(key=lambda r: (r["created_at"], r["version"], r["_seq"]))
    return rows[-1]


def current_disclosure(plan_id):
    rows = [d for d in db.disclosures.values()
            if d["plan_id"] == plan_id and d["status"] in ("ATTACHED", "STALE")]
    if not rows:
        return None
    rows.sort(key=lambda r: r["_seq"])
    return rows[-1]


# ---------------------------------------------------------------------------
# Employee derived fields
# ---------------------------------------------------------------------------
def refresh_employee_derived(employee):
    changes = {"is_part_time": D(employee["weekly_hours"]) < D(MIN_PART_TIME_HOURS)}
    sep = parse_date(employee["separation_date"])
    if sep is None:
        changes["age_at_separation"] = None
        changes["years_of_service"] = None
    else:
        birth = parse_date(employee["birth_date"])
        hire = parse_date(employee["hire_date"])
        changes["age_at_separation"] = completed_years(birth, sep)
        changes["years_of_service"] = (sep - hire).days // 365
    for key, value in changes.items():
        employee[key] = value


# ---------------------------------------------------------------------------
# Site recomputation (+ notice voiding when a site returns to NONE)
# ---------------------------------------------------------------------------
def recompute_site(site):
    employees = site_employees(site["id"])
    active = sum(1 for e in employees if e["employment_status"] == "ACTIVE")
    pending = sum(1 for e in employees if e["employment_status"] == "PENDING_SEPARATION")
    separated = sum(1 for e in employees if e["employment_status"] == "SEPARATED")

    fed = warn_determination(employees, federal_rule())
    sta = warn_determination(employees, state_rule(site["state_code"]))

    triggered = [d for d in (fed, sta) if d["threshold_met"]]
    if any(d["employment_loss_count"] == d["workforce_count"] for d in triggered):
        trigger_status = "PLANT_CLOSING"
    elif triggered:
        trigger_status = "MASS_LAYOFF"
    else:
        trigger_status = "NONE"
    required_notice_days = max([d["required_notice_days"] for d in triggered]) if triggered else 0

    previous_status = site["warn_trigger_status"]
    apply_changes(site, {
        "roster_count": len(employees),
        "active_headcount": active,
        "pending_separation_count": pending,
        "separated_count": separated,
        "federal_loss_count": fed["employment_loss_count"],
        "state_loss_count": sta["employment_loss_count"],
        "warn_trigger_status": trigger_status,
        "required_notice_days": required_notice_days,
        "window_start_date": date_str(window_start_for_site(employees)),
    })

    if previous_status != "NONE" and trigger_status == "NONE":
        for notice in db.notices.values():
            if notice["site_id"] == site["id"] and notice["status"] == "ISSUED":
                notice["status"] = "VOID"
                touch(notice)


# ---------------------------------------------------------------------------
# Plan recomputation (rollups + the warn_status axis)
# ---------------------------------------------------------------------------
def recompute_plan(plan, sync_warn=True):
    selections = plan_selections(plan["id"])
    selected = [s for s in selections if s["status"] in SELECTED_STATUSES]
    pool = [s for s in selections if s["status"] in POOL_STATUSES]

    selected_count = len(selected)
    pool_count = len(pool)

    dates = [parse_date(s["proposed_separation_date"]) for s in selected]
    earliest = min(dates) if dates else None

    owbpa_required = False
    for sel in selected:
        emp = db.employees.get(sel["employee_id"])
        if emp is None:
            continue
        age = completed_years(parse_date(emp["birth_date"]),
                              parse_date(sel["proposed_separation_date"]))
        if age is not None and age >= OWBPA_PROTECTED_AGE:
            owbpa_required = True
            break

    site_ids = []
    for sel in selected:
        emp = db.employees.get(sel["employee_id"])
        if emp is not None and emp["site_id"] not in site_ids:
            site_ids.append(emp["site_id"])
    notice_days = [db.sites[sid]["required_notice_days"] for sid in site_ids if sid in db.sites]
    required_notice_days = max(notice_days) if notice_days else 0

    if required_notice_days == 0 or earliest is None:
        notice_deadline_utc = None
    else:
        notice_deadline_utc = iso_ms(date_at_midnight(earliest) - timedelta(days=required_notice_days))

    reserve = sum(o["total_separation_cost_cents"] for o in db.offers.values()
                  if o["plan_id"] == plan["id"] and o["status"] in RESERVE_STATUSES)

    plan_employee_ids = set(s["employee_id"] for s in selections)
    liability = 0
    for employee_id in plan_employee_ids:
        emp = db.employees.get(employee_id)
        if emp is not None and emp["benefit_continuation_status"] == "ACTIVE":
            liability += emp["benefit_subsidy_cents"]

    changes = {
        "selected_count": selected_count,
        "pool_count": pool_count,
        "earliest_separation_date": date_str(earliest),
        "owbpa_required": owbpa_required,
        "owbpa_consideration_days": 45 if selected_count >= 2 else 21,
        "required_notice_days": required_notice_days,
        "notice_deadline_utc": notice_deadline_utc,
        "severance_reserve_cents": reserve,
        "benefit_liability_cents": liability,
    }

    if sync_warn:
        selected_sites = []
        live_sites = []
        for sel in selections:
            if sel["status"] not in ("SELECTED", "SEPARATED"):
                continue
            emp = db.employees.get(sel["employee_id"])
            if emp is None:
                continue
            if emp["site_id"] not in live_sites:
                live_sites.append(emp["site_id"])
            if sel["status"] == "SELECTED" and emp["site_id"] not in selected_sites:
                selected_sites.append(emp["site_id"])

        def _triggered(site_ids):
            return any(db.sites[sid]["warn_trigger_status"] != "NONE"
                       for sid in site_ids if sid in db.sites)

        if plan["warn_status"] == "NOT_ASSESSED" and _triggered(selected_sites):
            changes["warn_status"] = "THRESHOLD_PENDING"
        elif plan["warn_status"] == "THRESHOLD_PENDING" and not _triggered(live_sites):
            changes["warn_status"] = "NOT_ASSESSED"

    return apply_changes(plan, changes)


def recompute_plans_touching_site(site_id):
    """Cross-aggregate hop: every plan holding a selection at this site."""
    for plan in list(db.plans.values()):
        for sel in plan_selections(plan["id"]):
            emp = db.employees.get(sel["employee_id"])
            if emp is not None and emp["site_id"] == site_id:
                recompute_plan(plan)
                break


# ---------------------------------------------------------------------------
# Compliance-paperwork staleness
# ---------------------------------------------------------------------------
def stale_analyses(plan_id):
    for analysis in db.analyses.values():
        if analysis["plan_id"] == plan_id and analysis["status"] == "CLEARED":
            analysis["status"] = "STALE"
            touch(analysis)


def stale_disclosures(plan):
    for disclosure in db.disclosures.values():
        if disclosure["plan_id"] != plan["id"] or disclosure["status"] != "ATTACHED":
            continue
        if (disclosure["snapshot_selected_count"] != plan["selected_count"]
                or disclosure["snapshot_pool_count"] != plan["pool_count"]):
            disclosure["status"] = "STALE"
            touch(disclosure)


# ---------------------------------------------------------------------------
# Rehire restrictions
# ---------------------------------------------------------------------------
def release_expired_restrictions():
    clock = db.clock
    for restriction in db.restrictions.values():
        if restriction["restriction_status"] != "RESTRICTED":
            continue
        until = parse_instant(restriction["restricted_until_utc"])
        if until is not None and clock > until:
            restriction["restriction_status"] = "RELEASED"
            touch(restriction)


def backfill_blocked(site_id, job_title):
    for restriction in db.restrictions.values():
        if (restriction["restriction_status"] == "RESTRICTED"
                and restriction["site_id"] == site_id
                and restriction["job_title"] == job_title):
            return True
    return False


# ---------------------------------------------------------------------------
# Offer blocking window
# ---------------------------------------------------------------------------
def blocking_window_end_utc(offer):
    status = offer["status"]
    if status == "ISSUED":
        return offer["consideration_deadline_utc"]
    if status == "SIGNED":
        return offer["revocation_deadline_utc"]
    if status == "REVOKED":
        return offer["revoked_utc"]
    if status == "EXPIRED":
        return offer["consideration_deadline_utc"]
    return None


def offer_window_conflict(employee_id, exclude_offer_id=None, include_self=None):
    """True while any relevant offer's blocking window plus one day still stands."""
    clock = db.clock
    for offer in employee_offers(employee_id):
        if exclude_offer_id is not None and offer["id"] == exclude_offer_id:
            if include_self is not True:
                continue
        end = blocking_window_end_utc(offer)
        if end is None:
            continue
        end_dt = parse_instant(end)
        if end_dt is None:
            continue
        if clock <= end_dt + timedelta(days=1):
            return True
    return False
