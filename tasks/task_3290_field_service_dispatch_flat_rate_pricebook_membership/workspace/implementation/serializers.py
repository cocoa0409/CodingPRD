"""Resource serializers — computed fields are reconciled on every read (PRD 2.4)."""

import store
from constants import (ROLE_DISPATCHER, ROLE_TECHNICIAN, ROLE_MANAGER,
                       ROLE_CUSTOMER_SERVICE, ROLE_PLATFORM_ADMIN)
from store import iso
import calc


# ------------------------------------------------------------- config rows
def branch(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "postal_code": row["postal_code"],
        "daily_dispatch_capacity_hours": row["daily_dispatch_capacity_hours"],
        "capacity_consumed_hours": calc.branch_capacity_consumed(row["id"]),
        "membership_count_active": calc.branch_membership_count(row["id"]),
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def membership_plan(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "annual_price_cents": row["annual_price_cents"],
        "included_service_visit_count": row["included_service_visit_count"],
        "maintenance_visit_interval_days": row["maintenance_visit_interval_days"],
        "included_labor_discount_pct": row["included_labor_discount_pct"],
        "status": row["status"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def campaign(row, include_attribution=False, variant=None):
    data = {
        "id": row["id"],
        "name": row["name"],
        "channel": row["channel"],
        "spend_cents": row["spend_cents"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }
    if include_attribution:
        slug = calc.attribution_variant_slug(variant)
        attributed = calc.campaign_attribution(row["id"], slug)
        data["attributed_job_count"] = attributed["attributed_job_count"]
        data["attributed_revenue_cents"] = attributed["attributed_revenue_cents"]
        data["cac_cents"] = attributed["cac_cents"]
        data["conversion_rate"] = calc.marketing_attribution_denominator(
            attributed["attributed_job_count"])
    else:
        data["attributed_job_count"] = 0
        data["attributed_revenue_cents"] = 0
        data["conversion_rate"] = None
    return data


def pricebook_task(row):
    options = row.get("options") or []
    return {
        "id": row["id"],
        "code": row["code"],
        "revision": row["revision"],
        "category": row["category"],
        "display_name": row["display_name"],
        "required_skill_code": row["required_skill_code"],
        "estimated_hours": row["estimated_hours"],
        "flat_rate_cents": row["flat_rate_cents"],
        "status": row["status"],
        "published_at_utc": iso(row.get("published_at_utc")),
        "options": [
            {
                "tier": opt.get("tier"),
                "label": opt.get("label"),
                "price_cents": opt.get("price_cents"),
                "included_materials_cents": opt.get("included_materials_cents"),
                "warranty_months": opt.get("warranty_months"),
            }
            for opt in options
        ],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def technician(row):
    review = calc.technician_performance_review(row["id"])
    return {
        "id": row["id"],
        "home_branch_id": row["home_branch_id"],
        "name": row["name"],
        "postal_code": row["postal_code"],
        "skill_codes": list(row["skill_codes"]),
        "shift_segments": [
            {"start_utc": iso(seg["start_utc"]), "end_utc": iso(seg["end_utc"])}
            for seg in row["shift_segments"]
        ],
        "daily_capacity_hours": row["daily_capacity_hours"],
        "status": row["status"],
        "performance_status": row["performance_status"],
        "sales_coaching_strike_count": row["sales_coaching_strike_count"],
        "scheduled_hours": calc.technician_scheduled_hours(row["id"]),
        "dispatched_hours": calc.technician_dispatched_hours(row["id"]),
        "technician_revenue_ledger_cents": calc.ledger_total(row["id"]),
        "revenue_window_cents": review["window_revenue_cents"],
        "performance_grade": review["grade"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def revenue_ledger_entry(row):
    return {
        "id": row["id"],
        "technician_id": row["technician_id"],
        "appointment_id": row["appointment_id"],
        "entry_type": row["entry_type"],
        "amount_cents": row["amount_cents"],
        "running_total_cents": row["running_total_cents"],
        "recorded_at_utc": iso(row["recorded_at_utc"]),
        "created_at": iso(row["created_at"]),
    }


# ----------------------------------------------------------- resource rows
def appointment(row):
    return {
        "id": row["id"],
        "branch_id": row["branch_id"],
        "technician_id": row.get("technician_id"),
        "membership_agreement_id": row.get("membership_agreement_id"),
        "membership_visit_sequence_number": row.get("membership_visit_sequence_number"),
        "campaign_id": row.get("campaign_id"),
        "call_record_id": row.get("call_record_id"),
        "customer_name": row["customer_name"],
        "postal_code": row["postal_code"],
        "window_start_utc": iso(row["window_start_utc"]),
        "window_end_utc": iso(row["window_end_utc"]),
        "estimated_hours": calc.appointment_estimated_hours(row["id"]),
        "labor_base_cents": calc.appointment_labor_base(row["id"]),
        "quoted_price_cents": row["quoted_price_cents"],
        "authorization_required": row["authorization_required"],
        "current_pricebook_version_id": row.get("current_pricebook_version_id"),
        "repriced_at": iso(row.get("repriced_at")),
        "load_units_trace": list(row.get("load_units_trace") or []),
        "sold_price_cents": calc.appointment_sold_price(row["id"]),
        "pricing_status": row["pricing_status"],
        "status": row["status"],
        "dispatch_status": row["dispatch_status"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def appointment_line(row):
    return {
        "id": row["id"],
        "appointment_id": row["appointment_id"],
        "pricebook_task_id": row["pricebook_task_id"],
        "option_tier": row.get("option_tier"),
        "status": row["status"],
        "flat_rate_cents": row["flat_rate_cents"],
        "sold_price_cents": calc.line_sold_price(row),
        "created_at": iso(row["created_at"]),
    }


def override_request(row):
    return {
        "id": row["id"],
        "appointment_id": row["appointment_id"],
        "original_quote_cents": row["original_quote_cents"],
        "requested_price_cents": row["requested_price_cents"],
        "max_approved_price_cents": row["max_approved_price_cents"],
        "status": row["status"],
        "decided_by_user_id": row.get("decided_by_user_id"),
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def membership_agreement(row):
    return {
        "id": row["id"],
        "membership_plan_id": row["membership_plan_id"],
        "branch_id": row["branch_id"],
        "homeowner_name": row["homeowner_name"],
        "homeowner_postal_code": row["homeowner_postal_code"],
        "status": row["status"],
        "term_months": row["term_months"],
        "agreement_start_utc": iso(row.get("agreement_start_utc")),
        "annual_price_cents": row["annual_price_cents"],
        "collected_amount_cents": row["collected_amount_cents"],
        "revenue_recognized_cents": row["revenue_recognized_cents"],
        "unearned_revenue_balance_cents": row["unearned_revenue_balance_cents"],
        "visits_fulfilled_count": calc.visits_fulfilled_count(row["id"]),
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def membership_visit(row):
    return {
        "id": row["id"],
        "membership_agreement_id": row["membership_agreement_id"],
        "branch_id": row["branch_id"],
        "sequence_number": row["sequence_number"],
        "scheduled_date": iso(row["scheduled_date"]),
        "status": row["status"],
        "completed_appointment_id": row.get("completed_appointment_id"),
        "completed_at_utc": iso(row.get("completed_at_utc")),
        "deferred_revenue_cents": row["deferred_revenue_cents"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def call_record(row):
    return {
        "id": row["id"],
        "campaign_id": row["campaign_id"],
        "cs_user_id": row["cs_user_id"],
        "started_at_utc": iso(row["started_at_utc"]),
        "duration_seconds": row["duration_seconds"],
        "recording_uri": row["recording_uri"],
        "coaching_status": row["coaching_status"],
        "attributed_appointment_id": row.get("attributed_appointment_id"),
        "coached_by_user_id": row.get("coached_by_user_id"),
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }