"""Entity serializers. Computed-on-read fields (PRD/SCAFFOLD `source:
computed`) are resolved here against the current store and logical clock:
Worker.age_months, EarningsYear.indexed_earnings_cents,
Relationship.marriage_months, BenefitClaim.total_paid_cents,
OverpaymentCase.remaining_cents. WageReport and RecomputationEvent carry no
updated_at/version (PRD §2.6).
"""

import calc
import timeutil as tu
from db import store


def _common(e):
    return {
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def worker_dict(w):
    d = {
        "id": w["id"],
        "full_name": w["full_name"],
        "birth_year": w["birth_year"],
        "birth_month": w["birth_month"],
        "noncovered_pension_monthly_cents": w["noncovered_pension_monthly_cents"],
        "noncovered_pension_start_month": w["noncovered_pension_start_month"],
        "status": w["status"],
        "death_date": w["death_date"],
        "fra_months": w["fra_months"],
        "age_months": tu.age_months_at(w["birth_year"], w["birth_month"], store.clock_month()),
        "eligibility_year": w["eligibility_year"],
        "withdrawal_used": w["withdrawal_used"],
    }
    d.update(_common(w))
    return d


def earnings_year_dict(r):
    worker = store.workers.get(r["worker_id"])
    indexed = calc.indexed_earnings_cents(worker, r) if worker else r["posted_earnings_cents"]
    d = {
        "id": r["id"],
        "worker_id": r["worker_id"],
        "tax_year": r["tax_year"],
        "posted_earnings_cents": r["posted_earnings_cents"],
        "noncovered_earnings_cents": r["noncovered_earnings_cents"],
        "corrected": r["corrected"],
        "indexed_earnings_cents": indexed,
    }
    d.update(_common(r))
    return d


def wage_report_dict(r):
    return {
        "id": r["id"],
        "worker_id": r["worker_id"],
        "employer_name": r["employer_name"],
        "tax_year": r["tax_year"],
        "amount_cents": r["amount_cents"],
        "covered_employment": r["covered_employment"],
        "posted_amount_cents": r["posted_amount_cents"],
        "status": r["status"],
        "created_at": r["created_at"],
    }


def correction_dict(c):
    d = {
        "id": c["id"],
        "worker_id": c["worker_id"],
        "tax_year": c["tax_year"],
        "claimed_earnings_cents": c["claimed_earnings_cents"],
        "evidence_type": c["evidence_type"],
        "status": c["status"],
        "statute_deadline": c["statute_deadline"],
        "decided_by": c["decided_by"],
        "decided_at": c["decided_at"],
        "denial_reason": c["denial_reason"],
    }
    d.update(_common(c))
    return d


def relationship_marriage_months(rel):
    """Whole months from marriage_date to the earliest of divorce_date, the
    covered worker's death_date, or the logical clock."""
    start = tu.parse_date_str(rel["marriage_date"])
    end = store.clock_date()
    if rel["divorce_date"]:
        div = tu.parse_date_str(rel["divorce_date"])
        if div < end:
            end = div
    covered = store.workers.get(rel["worker_id"])
    if covered and covered["death_date"]:
        dd = tu.parse_date_str(covered["death_date"])
        if dd < end:
            end = dd
    return max(0, tu.months_between_dates(start, end))


def relationship_dict(rel):
    d = {
        "id": rel["id"],
        "worker_id": rel["worker_id"],
        "spouse_worker_id": rel["spouse_worker_id"],
        "relationship_type": rel["relationship_type"],
        "marriage_date": rel["marriage_date"],
        "divorce_date": rel["divorce_date"],
        "status": rel["status"],
        "marriage_months": relationship_marriage_months(rel),
        "verified_at": rel["verified_at"],
    }
    d.update(_common(rel))
    return d


def claim_total_paid_cents(claim_id):
    return sum(
        p["net_paid_cents"]
        for p in store.payments.values()
        if p["claim_id"] == claim_id and p["status"] in ("PAID", "WITHHELD_FULL")
    )


def claim_dict(c):
    d = {
        "id": c["id"],
        "worker_id": c["worker_id"],
        "claim_type": c["claim_type"],
        "entitlement_month": c["entitlement_month"],
        "relationship_id": c["relationship_id"],
        "status": c["status"],
        "claiming_age_months": c["claiming_age_months"],
        "aime_cents": c["aime_cents"],
        "pia_cents": c["pia_cents"],
        "reduction_months": c["reduction_months"],
        "drc_months": c["drc_months"],
        "monthly_benefit_cents": c["monthly_benefit_cents"],
        "total_paid_cents": claim_total_paid_cents(c["id"]),
        "underpayment_credit_cents": c["underpayment_credit_cents"],
        "recovery_mode": c["recovery_mode"],
        "has_active_payee": c["has_active_payee"],
        "suspended_since": c["suspended_since"],
        "decided_by": c["decided_by"],
        "decided_at": c["decided_at"],
        "denial_reason": c["denial_reason"],
    }
    d.update(_common(c))
    return d


def payment_dict(p):
    d = {
        "id": p["id"],
        "claim_id": p["claim_id"],
        "month": p["month"],
        "gross_cents": p["gross_cents"],
        "withheld_cents": p["withheld_cents"],
        "underpayment_credit_cents": p["underpayment_credit_cents"],
        "net_paid_cents": p["net_paid_cents"],
        "paid_to": p["paid_to"],
        "status": p["status"],
    }
    d.update(_common(p))
    return d


def overpayment_dict(o):
    remaining = 0 if o["status"] == "WAIVED" else o["amount_cents"] - o["recovered_cents"]
    d = {
        "id": o["id"],
        "claim_id": o["claim_id"],
        "amount_cents": o["amount_cents"],
        "period_start_month": o["period_start_month"],
        "period_end_month": o["period_end_month"],
        "reason": o["reason"],
        "status": o["status"],
        "created_by": o["created_by"],
        "recovered_cents": o["recovered_cents"],
        "remaining_cents": remaining,
        "waiver_grounds": o["waiver_grounds"],
        "waiver_decided_by": o["waiver_decided_by"],
    }
    d.update(_common(o))
    return d


def payee_dict(p):
    d = {
        "id": p["id"],
        "claim_id": p["claim_id"],
        "payee_name": p["payee_name"],
        "determination_basis": p["determination_basis"],
        "status": p["status"],
        "created_by": p["created_by"],
        "decided_by": p["decided_by"],
    }
    d.update(_common(p))
    return d


def recomputation_dict(r):
    return {
        "id": r["id"],
        "claim_id": r["claim_id"],
        "trigger": r["trigger"],
        "old_pia_cents": r["old_pia_cents"],
        "new_pia_cents": r["new_pia_cents"],
        "old_monthly_benefit_cents": r["old_monthly_benefit_cents"],
        "new_monthly_benefit_cents": r["new_monthly_benefit_cents"],
        "retro_delta_cents": r["retro_delta_cents"],
        "resolution": r["resolution"],
        "created_at": r["created_at"],
    }
