"""Derived values and JSON serialization.

PRD 2.5: several derived fields are refreshed on READ rather than only on write,
because they depend on the logical clock rather than on any request. Those are
computed here at serialization time and are never persisted, so a read never
bumps a version.
"""
import calc
import clock
import db

MERCHANT_PAYABLE_TYPES = (
    "COMMISSION_ACCRUAL", "COMMISSION_REVERSAL", "PLACEMENT_FEE",
    "PLACEMENT_FEE_REFUND", "DISPUTE_CREDIT_RECOVERY",
)
EMPLOYER_SHARE_TYPES = ("EMPLOYER_SHARE", "EMPLOYER_SHARE_REVERSAL")


def dt(value):
    return clock.fmt(value) if value is not None else None


# ---------------------------------------------------------------------------
# Merchant derivations
# ---------------------------------------------------------------------------

def merchant_fault_disputes(merchant_id):
    return [d for d in db.disputes.values()
            if d["merchant_id"] == merchant_id
            and d["status"] == "RESOLVED_MERCHANT_FAULT"]


def merchant_failure_score(merchant_id):
    return calc.fulfillment_failure_score(merchant_fault_disputes(merchant_id))


def merchant_payable_cents(merchant_id):
    total = 0
    for entry in db.ledger_entries.values():
        if entry["merchant_id"] == merchant_id and entry["entry_type"] in MERCHANT_PAYABLE_TYPES:
            total += entry["amount_cents"]
    return total


def merchant_active_agreements(merchant_id):
    return sum(1 for a in db.agreements.values()
               if a["merchant_id"] == merchant_id and a["status"] == "ACTIVE")


# ---------------------------------------------------------------------------
# Employer derivations
# ---------------------------------------------------------------------------

def program_posture(employer):
    storefront = employer["storefront_status"]
    integration = employer["integration_status"]
    if storefront == "SUSPENDED":
        return "FROZEN"
    if storefront in ("DRAFT", "BRANDED"):
        return "SETUP"
    if storefront == "PUBLISHED" and integration == "SYNCED":
        return "LIVE"
    if storefront == "PUBLISHED" and integration == "STALE":
        return "RESTRICTED"
    return "SETUP"


def eligible_headcount(employer_id):
    now = clock.now()
    count = 0
    for m in db.memberships.values():
        if m["employer_id"] != employer_id:
            continue
        if m["status"] != "ELIGIBLE":
            continue
        if m["employment_status"] not in ("ACTIVE", "LEAVE"):
            continue
        if m["eligibility_valid_from"] <= now < m["eligibility_valid_until"]:
            count += 1
    return count


def employer_accrued_share_cents(employer_id):
    total = 0
    for entry in db.ledger_entries.values():
        if entry["employer_id"] == employer_id and entry["entry_type"] in EMPLOYER_SHARE_TYPES:
            total += entry["amount_cents"]
    return total * -1


# ---------------------------------------------------------------------------
# Membership derivations
# ---------------------------------------------------------------------------

def membership_redemptions(membership_id):
    return [r for r in db.redemptions.values() if r["membership_id"] == membership_id]


def rolling_count(membership_id, days, statuses):
    now = clock.now()
    floor_instant = clock.plus_days(now, -days)
    count = 0
    for r in db.redemptions.values():
        if r["membership_id"] != membership_id:
            continue
        if r["verification_status"] not in statuses:
            continue
        if floor_instant <= r["created_at"] < now:
            count += 1
    return count


# ---------------------------------------------------------------------------
# Offer derivations
# ---------------------------------------------------------------------------

def inventory_reserved(offer_id):
    return sum(1 for r in db.redemptions.values()
               if r["offer_id"] == offer_id and r["verification_status"] == "PENDING")


def inventory_redeemed(offer_id):
    return sum(1 for r in db.redemptions.values()
               if r["offer_id"] == offer_id and r["verification_status"] == "VERIFIED")


def sold_out(offer, reserved=None, redeemed=None):
    limit = offer.get("inventory_limit")
    if limit is None:
        return False
    if reserved is None:
        reserved = inventory_reserved(offer["id"])
    if redeemed is None:
        redeemed = inventory_redeemed(offer["id"])
    return (reserved + redeemed) >= limit


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def merchant_json(row):
    return {
        "id": row["id"],
        "legal_name": row["legal_name"],
        "contact_email": row["contact_email"],
        "primary_category": row["primary_category"],
        "region_codes": list(row["region_codes"]),
        "status": row["status"],
        "fault_event_count": row["fault_event_count"],
        # Recomputed against the clock on every read so decay is observable.
        "fulfillment_failure_score": merchant_failure_score(row["id"]),
        "accrued_commission_payable_cents": merchant_payable_cents(row["id"]),
        "active_agreement_count": merchant_active_agreements(row["id"]),
        "suspended_at": dt(row["suspended_at"]),
        "last_fault_at": dt(row.get("last_fault_at")),
        "created_at": dt(row["created_at"]),
        "updated_at": dt(row["updated_at"]),
        "version": row["version"],
    }


def agreement_json(row):
    return {
        "id": row["id"],
        "merchant_id": row["merchant_id"],
        "category": row["category"],
        "region_code": row["region_code"],
        "status": row["status"],
        "round_count": row["round_count"],
        "commission_rate_bps": row["commission_rate_bps"],
        "placement_fee_base_cents": row["placement_fee_base_cents"],
        "employer_revenue_share_bps": row["employer_revenue_share_bps"],
        "exclusivity_requested": row["exclusivity_requested"],
        "exclusivity_window_start": dt(row["exclusivity_window_start"]),
        "exclusivity_window_end": dt(row["exclusivity_window_end"]),
        "exclusivity_granted": row["exclusivity_granted"],
        "accepted_by_role": row["accepted_by_role"],
        "activated_at": dt(row["activated_at"]),
        "terminated_reason": row["terminated_reason"],
        "created_at": dt(row["created_at"]),
        "updated_at": dt(row["updated_at"]),
        "version": row["version"],
    }


def round_json(row):
    # Append-only: no updated_at and no version (PRD 2.5).
    return {
        "id": row["id"],
        "agreement_id": row["agreement_id"],
        "round_number": row["round_number"],
        "proposer_role": row["proposer_role"],
        "commission_rate_bps": row["commission_rate_bps"],
        "placement_fee_base_cents": row["placement_fee_base_cents"],
        "employer_revenue_share_bps": row["employer_revenue_share_bps"],
        "exclusivity_window_start": dt(row["exclusivity_window_start"]),
        "exclusivity_window_end": dt(row["exclusivity_window_end"]),
        "note": row["note"],
        "created_at": dt(row["created_at"]),
    }


def employer_json(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "region_code": row["region_code"],
        "employee_count_declared": row["employee_count_declared"],
        "revenue_share_enabled": row["revenue_share_enabled"],
        "privacy_min_cohort_size": row["privacy_min_cohort_size"],
        "integration_status": row["integration_status"],
        "storefront_status": row["storefront_status"],
        "program_posture": program_posture(row),
        "brand_color_hex": row["brand_color_hex"],
        "logo_url": row["logo_url"],
        "hero_headline": row["hero_headline"],
        "featured_categories": (list(row["featured_categories"])
                                if row["featured_categories"] is not None else None),
        "eligible_headcount": eligible_headcount(row["id"]),
        "last_sync_at": dt(row["last_sync_at"]),
        "accrued_share_cents": employer_accrued_share_cents(row["id"]),
        "suspension_reason": row["suspension_reason"],
        "created_at": dt(row["created_at"]),
        "updated_at": dt(row["updated_at"]),
        "version": row["version"],
    }


def file_json(row):
    return {
        "id": row["id"],
        "employer_id": row["employer_id"],
        "effective_from": dt(row["effective_from"]),
        "checksum": row["checksum"],
        "records": row["records"],
        "record_count": row["record_count"],
        "invalid_record_count": row["invalid_record_count"],
        "valid_record_count": row["valid_record_count"],
        "status": row["status"],
        "rejection_reason": row["rejection_reason"],
        "created_membership_count": row["created_membership_count"],
        "updated_membership_count": row["updated_membership_count"],
        "suspended_membership_count": row["suspended_membership_count"],
        "applied_at": dt(row["applied_at"]),
        "created_at": dt(row["created_at"]),
        "updated_at": dt(row["updated_at"]),
        "version": row["version"],
    }


def membership_json(row):
    return {
        "id": row["id"],
        "employer_id": row["employer_id"],
        "source_file_id": row["source_file_id"],
        "external_employee_ref": row["external_employee_ref"],
        "employment_status": row["employment_status"],
        "status": row["status"],
        "region_code": row["region_code"],
        "eligibility_valid_from": dt(row["eligibility_valid_from"]),
        "eligibility_valid_until": dt(row["eligibility_valid_until"]),
        "redemption_count_7d": rolling_count(row["id"], 7, ("PENDING", "VERIFIED")),
        "redemption_count_30d": rolling_count(
            row["id"], 30, ("PENDING", "VERIFIED", "FAILED", "VOID")),
        "last_employment_change_at": dt(row["last_employment_change_at"]),
        "created_at": dt(row["created_at"]),
        "updated_at": dt(row["updated_at"]),
        "version": row["version"],
    }


def offer_json(row):
    reserved = inventory_reserved(row["id"])
    redeemed = inventory_redeemed(row["id"])
    return {
        "id": row["id"],
        "agreement_id": row["agreement_id"],
        "merchant_id": row["merchant_id"],
        "title": row["title"],
        "category": row["category"],
        "discount_type": row["discount_type"],
        "discount_value_bps": row["discount_value_bps"],
        "discount_value_cents": row["discount_value_cents"],
        "min_spend_cents": row["min_spend_cents"],
        "region_codes": list(row["region_codes"]),
        "window_start": dt(row["window_start"]),
        "window_end": dt(row["window_end"]),
        "inventory_limit": row["inventory_limit"],
        "inventory_reserved": reserved,
        "inventory_redeemed": redeemed,
        "per_member_limit": row["per_member_limit"],
        "sold_out": sold_out(row, reserved, redeemed),
        "status": row["status"],
        "review_note": row["review_note"],
        "paused_reason": row["paused_reason"],
        "expired_at": dt(row["expired_at"]),
        "created_at": dt(row["created_at"]),
        "updated_at": dt(row["updated_at"]),
        "version": row["version"],
    }


def slot_json(row):
    return {
        "id": row["id"],
        "offer_id": row["offer_id"],
        "merchant_id": row["merchant_id"],
        "employer_id": row["employer_id"],
        "placement_tier": row["placement_tier"],
        "slot_window_start": dt(row["slot_window_start"]),
        "slot_window_end": dt(row["slot_window_end"]),
        "slot_duration_days": row["slot_duration_days"],
        "base_fee_cents": row["base_fee_cents"],
        "reach_surcharge_bps": row["reach_surcharge_bps"],
        "reach_surcharge_cents": row["reach_surcharge_cents"],
        "gross_fee_cents": row["gross_fee_cents"],
        "volume_discount_bps": row["volume_discount_bps"],
        "volume_discount_cents": row["volume_discount_cents"],
        "placement_fee_cents": row["placement_fee_cents"],
        "status": row["status"],
        "confirmed_at": dt(row["confirmed_at"]),
        "released_at": dt(row["released_at"]),
        "release_reason": row["release_reason"],
        "created_at": dt(row["created_at"]),
        "updated_at": dt(row["updated_at"]),
        "version": row["version"],
    }


def redemption_json(row, include_token=False):
    # PRD 3.7: the verification_token is returned ONLY in the creation response.
    return {
        "id": row["id"],
        "offer_id": row["offer_id"],
        "membership_id": row["membership_id"],
        "employer_id": row["employer_id"],
        "merchant_id": row["merchant_id"],
        "statement_id": row["statement_id"],
        "intended_gross_amount_cents": row["intended_gross_amount_cents"],
        "gross_amount_cents": row["gross_amount_cents"],
        "discount_amount_cents": row["discount_amount_cents"],
        "net_charged_cents": row["net_charged_cents"],
        "commission_amount_cents": row["commission_amount_cents"],
        "employer_share_cents": row["employer_share_cents"],
        "provider_net_cents": row["provider_net_cents"],
        "verification_token": row["verification_token"] if include_token else None,
        "verification_expires_at": dt(row["verification_expires_at"]),
        "verification_status": row["verification_status"],
        "fulfillment_status": row["fulfillment_status"],
        "screening_risk_score": row["screening_risk_score"],
        "audit_risk_score": row["audit_risk_score"],
        "risk_block_reason": row["risk_block_reason"],
        "verified_at": dt(row["verified_at"]),
        "fulfilled_at": dt(row["fulfilled_at"]),
        "refunded_at": dt(row["refunded_at"]),
        "voided_at": dt(row["voided_at"]),
        "void_reason": row["void_reason"],
        "created_at": dt(row["created_at"]),
        "updated_at": dt(row["updated_at"]),
        "version": row["version"],
    }


def dispute_json(row):
    return {
        "id": row["id"],
        "redemption_id": row["redemption_id"],
        "raised_by_membership_id": row["raised_by_membership_id"],
        "merchant_id": row["merchant_id"],
        "reason": row["reason"],
        "description": row["description"],
        "status": row["status"],
        "response_note": row["response_note"],
        "remedy_offered_cents": row["remedy_offered_cents"],
        "info_request_count": row["info_request_count"],
        "response_deadline_at": dt(row["response_deadline_at"]),
        "outcome_credit_cents": row["outcome_credit_cents"],
        "default_judged": row["default_judged"],
        "resolved_at": dt(row["resolved_at"]),
        "created_at": dt(row["created_at"]),
        "updated_at": dt(row["updated_at"]),
        "version": row["version"],
    }


def statement_json(row):
    return {
        "id": row["id"],
        "employer_id": row["employer_id"],
        "period_start": dt(row["period_start"]),
        "period_end": dt(row["period_end"]),
        "basis": row["basis"],
        "included_redemption_count": row["included_redemption_count"],
        "gross_commission_cents": row["gross_commission_cents"],
        "employer_share_cents": row["employer_share_cents"],
        "provider_retained_cents": row["provider_retained_cents"],
        "reversal_adjustment_cents": row["reversal_adjustment_cents"],
        "status": row["status"],
        "finalized_at": dt(row["finalized_at"]),
        "reopened_at": dt(row["reopened_at"]),
        "reopen_reason": row["reopen_reason"],
        "paid_at": dt(row["paid_at"]),
        "payment_reference": row["payment_reference"],
        "created_at": dt(row["created_at"]),
        "updated_at": dt(row["updated_at"]),
        "version": row["version"],
    }


def ledger_json(row):
    # Append-only: no updated_at and no version (PRD 2.5 / 3.9).
    return {
        "id": row["id"],
        "redemption_id": row["redemption_id"],
        "placement_slot_id": row["placement_slot_id"],
        "statement_id": row["statement_id"],
        "employer_id": row["employer_id"],
        "merchant_id": row["merchant_id"],
        "entry_type": row["entry_type"],
        "amount_cents": row["amount_cents"],
        "memo": row["memo"],
        "created_at": dt(row["created_at"]),
    }
