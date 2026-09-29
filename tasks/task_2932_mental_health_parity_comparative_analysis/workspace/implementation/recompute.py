"""Derived-value recomputation and cascade propagation (PRD 2.8)."""

import calc
from errors import ApiError
from store import clock_now, clock_now_iso, db, new_append_only_row, touch


# --- gates (ladder steps 14 and 15) ---------------------------------------

def gate_not_closed(plan_year):
    if plan_year is not None and plan_year["status"] == "CLOSED":
        raise ApiError("ERR_PLAN_YEAR_CLOSED")


def gate_open(plan_year):
    if plan_year is not None and plan_year["status"] != "OPEN":
        raise ApiError("ERR_PLAN_YEAR_NOT_OPEN")


# --- parent resolution ----------------------------------------------------

def plan_year_of_classification(classification):
    return db.plan_years.get(classification["plan_year_id"])


def plan_year_of_item(item):
    return db.plan_years.get(item["plan_year_id"])


def plan_year_of_analysis(analysis):
    item = db.nqtl_items.get(analysis["nqtl_item_id"])
    if item is None:
        return None
    return plan_year_of_item(item)


def plan_year_of_cap(cap):
    item = db.nqtl_items.get(cap["nqtl_item_id"])
    if item is None:
        return None
    return plan_year_of_item(item)


# --- administrator --------------------------------------------------------

def recompute_administrator(admin, bump=None):
    """Re-derive the obligation counters and both cooperation-score variants."""
    before = (admin.get("outstanding_request_count"), admin.get("late_request_count"),
              admin.get("regulator_reportable_late_count"), admin.get("breach_count"),
              admin.get("cooperation_score"), admin.get("regulatory_basis_cooperation_score"),
              admin.get("cooperation_status"))
    outstanding, late, regulator_late, breaches = calc.cooperation_counters(
        admin["id"], clock_now())
    admin["outstanding_request_count"] = outstanding
    admin["late_request_count"] = late
    admin["regulator_reportable_late_count"] = regulator_late
    admin["breach_count"] = breaches
    score = calc.cooperation_score(late, breaches)
    admin["cooperation_score"] = score
    admin["regulatory_basis_cooperation_score"] = calc.cooperation_score(
        regulator_late, breaches)
    admin["cooperation_status"] = calc.cooperation_status(score)
    after = (admin["outstanding_request_count"], admin["late_request_count"],
             admin["regulator_reportable_late_count"], admin["breach_count"],
             admin["cooperation_score"], admin["regulatory_basis_cooperation_score"],
             admin["cooperation_status"])
    changed = before != after
    if bump is True or (bump is None and changed):
        touch(admin)
    return changed


# --- plan year ------------------------------------------------------------

def recompute_plan_year(plan_year, bump=None):
    """Re-derive counters, ledger and posture, then apply the status the posture implies."""
    before = (plan_year.get("open_violation_count"), plan_year.get("notified_violation_count"),
              plan_year.get("failing_parity_test_count"),
              plan_year.get("remediation_liability_cents"),
              plan_year.get("compliance_posture"), plan_year.get("status"))
    inputs = calc.posture_inputs(plan_year["id"])
    plan_year["open_violation_count"] = inputs["open_violation_count"]
    plan_year["notified_violation_count"] = inputs["notified_violation_count"]
    plan_year["failing_parity_test_count"] = inputs["failing_parity_test_count"]
    plan_year["remediation_liability_cents"] = inputs["remediation_liability_cents"]
    admin = db.administrators.get(plan_year["administrator_id"])
    admin_status = admin["cooperation_status"] if admin else "COOPERATIVE"
    posture = calc.compliance_posture(
        inputs["open_violation_count"], inputs["failing_parity_test_count"],
        admin_status, inputs["inventoried_count"])
    plan_year["compliance_posture"] = posture
    status = plan_year["status"]
    if status != "CLOSED":
        if posture == "VIOLATION" and status in ("OPEN", "UNDER_REGULATOR_REVIEW"):
            plan_year["status"] = "REMEDIATION"
        elif posture != "VIOLATION" and status == "REMEDIATION":
            plan_year["status"] = "OPEN"
    after = (plan_year["open_violation_count"], plan_year["notified_violation_count"],
             plan_year["failing_parity_test_count"], plan_year["remediation_liability_cents"],
             plan_year["compliance_posture"], plan_year["status"])
    changed = before != after
    if bump is True or (bump is None and changed):
        touch(plan_year)
    return changed


# --- NQTL item ------------------------------------------------------------

def recompute_stringency(item, bump=False):
    index, flag = calc.stringency_in_operation_index(item)
    changed = (item.get("stringency_in_operation_index") != index
               or item.get("stringency_flag") != flag)
    item["stringency_in_operation_index"] = index
    item["stringency_flag"] = flag
    if bump is True or (bump is None and changed):
        touch(item)
    return changed


# --- participant notices --------------------------------------------------

def create_participant_notice(item, notice_type, source):
    classification = db.classifications.get(item["classification_id"])
    plan_year = plan_year_of_item(item)
    summary = "%s in %s/%s: %s" % (
        item["nqtl_type"],
        classification["benefit_category"] if classification else "",
        classification["network_tier"] if classification else "",
        notice_type,
    )
    notice = new_append_only_row({
        "nqtl_item_id": item["id"],
        "notice_type": notice_type,
        "recipient_count": plan_year["covered_participant_count"] if plan_year else 0,
        "disclosure_summary": summary,
        "issued_at": clock_now_iso(),
        "source": source,
    })
    db.notices[notice["id"]] = notice
    return notice


# --- clock cascade --------------------------------------------------------

def recompute_world():
    """Advancing the clock re-derives every deadline-dependent value (PRD 2.5)."""
    for admin in list(db.administrators.values()):
        recompute_administrator(admin)
    for plan_year in list(db.plan_years.values()):
        recompute_plan_year(plan_year)
    return len(db.administrators), len(db.plan_years)
