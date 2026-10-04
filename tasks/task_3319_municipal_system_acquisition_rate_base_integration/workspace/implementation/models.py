"""Entity construction and serialization helpers.

Every resource carries: id, created_at, updated_at (ISO 8601 UTC, 3 fractional
digits), version (starts at 1, +1 per mutation).
"""
import db
from util import new_id, iso_now, TRANSITION_ITEM_ORDER


def base_record():
    now = iso_now()
    return {"id": new_id(), "created_at": now, "updated_at": now, "version": 1}


def touch(record):
    record["updated_at"] = iso_now()
    record["version"] += 1


def touch_no_version(record):
    record["updated_at"] = iso_now()


def new_target(body):
    rec = base_record()
    rec.update({
        "system_name": body["system_name"],
        "municipality_name": body["municipality_name"],
        "state_code": body["state_code"],
        "system_type": body["system_type"],
        "customer_count": body["customer_count"],
        "permitted_valuation_methods": list(body["permitted_valuation_methods"]),
        "status": "SCREENING",
        "council_approved": False,
        "filing_estimate_cents": 0,
        "selected_value_cents": None,
        "admitted_rate_base_cents": None,
        "disallowed_premium_cents": None,
    })
    db.targets[rec["id"]] = rec
    # Auto-create the four TransitionItems in the fixed scaffold order.
    for category in TRANSITION_ITEM_ORDER:
        item = base_record()
        item.update({
            "target_id": rec["id"],
            "category": category,
            "status": "PENDING",
            "resolution_note": "",
        })
        db.transition_items[item["id"]] = item
    return rec


def new_assessment(target_id, notes, creator):
    rec = base_record()
    rec.update({
        "target_id": target_id,
        "notes": notes,
        "created_by_user_id": creator,
        "revision_count": 0,
        "status": "DRAFT",
        "planning_estimate_cents": 0,
        "filing_estimate_cents": 0,
    })
    db.assessments[rec["id"]] = rec
    return rec


def new_capital_item(assessment_id, body):
    rec = base_record()
    low = body["cost_low_cents"]
    high = body["cost_high_cents"]
    rec.update({
        "assessment_id": assessment_id,
        "category": body["category"],
        "horizon": body["horizon"],
        "description": body["description"],
        "cost_low_cents": low,
        "cost_high_cents": high,
        "midpoint_estimate_cents": midpoint(low, high),
        "crews_required": body["crews_required"],
        "window_start": None,
        "window_end": None,
        "status": "PLANNED",
    })
    db.capital_items[rec["id"]] = rec
    return rec


def midpoint(low, high):
    """round_half_up((low + high) / 2) in integer cents."""
    return (low + high + 1) // 2


def new_valuation_case(target_id):
    rec = base_record()
    rec.update({
        "target_id": target_id,
        "status": "OPEN",
        "selected_entry_id": None,
        "selected_value_cents": None,
        "finalized_by_user_id": None,
    })
    db.valuation_cases[rec["id"]] = rec
    return rec


def new_valuation_entry(case_id, method, value_cents, law_citation, appraiser):
    rec = base_record()
    rec.update({
        "case_id": case_id,
        "method": method,
        "value_cents": value_cents,
        "law_citation": law_citation,
        "appraiser_user_id": appraiser,
        "status": "SUBMITTED",
    })
    db.valuation_entries[rec["id"]] = rec
    return rec


def new_council_event(target_id, kind, start_iso, end_iso):
    rec = base_record()
    rec.update({
        "target_id": target_id,
        "kind": kind,
        "scheduled_start": start_iso,
        "scheduled_end": end_iso,
        "yes_votes": None,
        "no_votes": None,
        "yes_share_pct": None,
        "status": "SCHEDULED",
    })
    db.council_events[rec["id"]] = rec
    return rec


def new_regulatory_application(target_id, purchase_price_cents, rate_base_method,
                               original_cost_less_depreciation_cents):
    rec = base_record()
    rec.update({
        "target_id": target_id,
        "purchase_price_cents": purchase_price_cents,
        "rate_base_method": rate_base_method,
        "original_cost_less_depreciation_cents": original_cost_less_depreciation_cents,
        "filing_round": 1,
        "status": "FILED",
        "admitted_rate_base_cents": None,
        "disallowed_premium_cents": None,
    })
    db.regulatory_applications[rec["id"]] = rec
    return rec


def new_customer_account(target_id, account_ref, deposit_cents, ar_balance_cents):
    rec = base_record()
    rec.update({
        "target_id": target_id,
        "account_ref": account_ref,
        "deposit_cents": deposit_cents,
        "ar_balance_cents": ar_balance_cents,
        "status": "LEGACY",
        "deposit_offset_cents": None,
        "refund_cents": None,
        "new_ar_balance_cents": None,
    })
    db.customer_accounts[rec["id"]] = rec
    return rec


def new_employee_transition(target_id, body):
    rec = base_record()
    rec.update({
        "target_id": target_id,
        "employee_ref": body["employee_ref"],
        "years_of_service": body["years_of_service"],
        "weekly_salary_cents": body["weekly_salary_cents"],
        "union_covered": body["union_covered"],
        "status": "PENDING",
        "severance_weeks": 0,
        "severance_cents": 0,
    })
    db.employee_transitions[rec["id"]] = rec
    return rec


def new_tariff_case(target_id, body):
    rec = base_record()
    rec.update({
        "target_id": target_id,
        "mode": body["mode"],
        "representative_old_bill_cents": body["representative_old_bill_cents"],
        "consolidated_monthly_bill_cents": body["consolidated_monthly_bill_cents"],
        "phase_in_years": None,
        "status": "DRAFT",
    })
    db.tariff_cases[rec["id"]] = rec
    return rec
