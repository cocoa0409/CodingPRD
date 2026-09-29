"""Coverage trigger resolution, reserving, incurred losses and the resolution cascade.

PRD 3.6 (intake and coverage), 3.7 (reserves and incurred), 3.9 (resolution,
data bank reporting).
"""
from decimal import Decimal

import constants as C
from store import db, new_record, sorted_records, touch
from val import ZERO, add_days, d, parse_instant, r2

from services import counsel, rating


# --- PRD 3.6: severity band -------------------------------------------------
def severity_band(demand):
    if demand < C.SEVERITY_BAND_2_MIN:
        band = "BAND_1"
    elif demand < C.SEVERITY_BAND_3_MIN:
        band = "BAND_2"
    elif demand < C.SEVERITY_BAND_4_MIN:
        band = "BAND_3"
    else:
        band = "BAND_4"
    return band, C.SEVERITY_BAND_FACTOR[band]


# --- PRD 3.6: coverage trigger resolution ----------------------------------
CANDIDATE_TERM_STATUSES = ("IN_FORCE", "EXPIRED", "CANCELLED_PRO_RATA")


def _latest_effective(records):
    """Latest effective_date, ties broken by the earlier creation timestamp."""
    chosen = None
    for record in records:
        if chosen is None or d(record["effective_date"]) > d(chosen["effective_date"]):
            chosen = record
    return chosen


def resolve_coverage(claim):
    insured_id = claim["insured_id"]
    incident = d(claim["incident_date"])
    report = d(claim["report_date"])

    responders = []
    for policy in rating.policies_of(insured_id):
        for term in rating.terms_of(policy["id"]):
            if term["status"] not in CANDIDATE_TERM_STATUSES:
                continue
            effective = d(term["effective_date"])
            expiration = d(term["expiration_date"])
            if policy["coverage_form"] == "CLAIMS_MADE":
                if effective <= report < expiration:
                    responders.append(term)
            else:
                if effective <= incident < expiration:
                    responders.append(term)

    claim["tail_endorsement_id"] = None
    if responders:
        winner = _latest_effective(responders)
        policy = db.policies[winner["policy_id"]]
        retro = policy.get("retroactive_date")
        if policy["coverage_form"] == "CLAIMS_MADE" and retro and incident < d(retro):
            claim["policy_term_id"] = None
            claim["coverage_status"] = "DENIED"
            claim["denial_reason"] = "PRIOR_ACTS_EXCLUDED"
            return
        claim["policy_term_id"] = winner["id"]
        claim["coverage_status"] = "UNDER_REVIEW"
        claim["denial_reason"] = None
        return

    tails = []
    for policy in rating.policies_of(insured_id):
        for tail in rating.tails_of(policy["id"]):
            if tail["status"] != "ISSUED":
                continue
            if not (d(tail["effective_date"]) <= report <= d(tail["reporting_window_end"])):
                continue
            trigger = db.policy_terms.get(tail["triggering_term_id"])
            if trigger is None:
                continue
            if not (d(trigger["effective_date"]) <= incident < d(trigger["expiration_date"])):
                continue
            tails.append(tail)

    if tails:
        winner = _latest_effective(tails)
        claim["tail_endorsement_id"] = winner["id"]
        claim["policy_term_id"] = winner["triggering_term_id"]
        claim["coverage_status"] = "UNDER_REVIEW"
        claim["denial_reason"] = None
        return

    claim["policy_term_id"] = None
    claim["coverage_status"] = "DENIED"
    claim["denial_reason"] = "NO_RESPONDING_COVERAGE"


# --- PRD 3.7: reserve postings ---------------------------------------------
def reserve_entries_of(claim_id):
    return sorted_records(
        [e for e in db.reserve_entries.values() if e["claim_id"] == claim_id]
    )


def formula_reserve(claim):
    policy = rating.responding_policy(claim)
    venue_factor = C.VENUE_SEVERITY_FACTOR[claim["venue_code"]]
    raw = r2(claim["demand_amount"] * claim["severity_band_factor"] * venue_factor)
    indemnity = raw
    if policy is not None and raw > policy["limit_per_claim"]:
        indemnity = r2(policy["limit_per_claim"])
    expense = max(r2(indemnity * C.EXPENSE_RATIO), C.EXPENSE_RESERVE_FLOOR)
    return indemnity, expense


def reserve_of_record(claim_id):
    entries = reserve_entries_of(claim_id)
    if not entries:
        return None
    return sorted(
        entries, key=lambda e: (e["_effective_dt"], e["created_at"], e["_seq"])
    )[-1]


def apply_reserve_of_record(claim):
    governing = reserve_of_record(claim["id"])
    if governing is None:
        claim["indemnity_reserve"] = r2(ZERO)
        claim["expense_reserve"] = r2(ZERO)
        claim["reserve_method_current"] = None
    else:
        claim["indemnity_reserve"] = governing["computed_indemnity_amount"]
        claim["expense_reserve"] = governing["computed_expense_amount"]
        claim["reserve_method_current"] = governing["method"]
    recompute_incurred(claim)


def recompute_incurred(claim):
    paid_indemnity = claim["paid_indemnity"]
    paid_expense = claim["paid_expense"]
    indemnity_reserve = claim["indemnity_reserve"]
    expense_reserve = claim["expense_reserve"]
    case = (
        paid_indemnity
        + paid_expense
        + max(ZERO, indemnity_reserve - paid_indemnity)
        + max(ZERO, expense_reserve - paid_expense)
    )
    claim["case_incurred"] = r2(case)
    claim["actuarial_incurred"] = r2(
        paid_indemnity + paid_expense + indemnity_reserve + expense_reserve
    )
    touch(claim)


# --- PRD 3.9: data bank reporting obligation --------------------------------
def create_npdb_report(claim, negotiation, payment_amount, payment_date):
    insured = db.insureds[claim["insured_id"]]
    reportable = (
        payment_amount > ZERO
        and insured["entity_type"] == "PHYSICIAN"
        and claim["disposition"] in ("SETTLED", "PLAINTIFF_VERDICT")
    )
    non_reportable_reason = None
    status = "PENDING"
    void_reason = None
    if not reportable:
        if insured["entity_type"] != "PHYSICIAN":
            non_reportable_reason = "NON_PRACTITIONER_PAYMENT"
        else:
            non_reportable_reason = "ZERO_DOLLAR_RESOLUTION"
        status = "VOID"
        void_reason = non_reportable_reason
    report = new_record(
        {
            "claim_id": claim["id"],
            "settlement_negotiation_id": negotiation["id"] if negotiation else None,
            "insured_id": insured["id"],
            "payment_amount": r2(payment_amount),
            "payment_date": payment_date,
            "reportable": reportable,
            "non_reportable_reason": non_reportable_reason,
            "due_date": add_days(payment_date, C.NPDB_REPORTING_DAYS),
            "report_status": status,
            "submitted_on": None,
            "submitted_late": False,
            "days_late": 0,
            "submitter_note": None,
            "void_reason": void_reason,
        }
    )
    db.npdb_reports[report["id"]] = report
    return report


# --- PRD 3.9: the resolution cascade ---------------------------------------
def resolve_claim(
    claim,
    disposition,
    resolved_on,
    verdict_amount=None,
    negotiation=None,
    paid_amount=None,
):
    """Identical whether resolution arrives by disposition or by settlement."""
    claim["claim_status"] = "RESOLVED"
    claim["resolved_on"] = resolved_on
    claim["disposition"] = disposition
    if verdict_amount is not None:
        claim["verdict_amount"] = verdict_amount

    policy = rating.responding_policy(claim)
    term = rating.responding_term(claim)

    disbursed = r2(ZERO)
    if disposition == "PLAINTIFF_VERDICT":
        gross = verdict_amount if verdict_amount is not None else ZERO
        if policy is not None and gross > policy["limit_per_claim"]:
            gross = policy["limit_per_claim"]
        disbursed = r2(gross)
    elif disposition == "SETTLED":
        disbursed = r2(paid_amount if paid_amount is not None else ZERO)

    if disposition in ("PLAINTIFF_VERDICT", "SETTLED"):
        claim["paid_indemnity"] = r2(claim["paid_indemnity"] + disbursed)
        if term is not None and disbursed > ZERO:
            term["aggregate_limit_remaining"] = r2(
                term["aggregate_limit_remaining"] - disbursed
            )
            touch(term)

    claim["indemnity_reserve"] = r2(ZERO)
    claim["expense_reserve"] = r2(ZERO)
    recompute_incurred(claim)

    counsel.close_assignments_on_resolution(claim)

    insured = db.insureds[claim["insured_id"]]
    rating.recompute_claim_counters(insured)

    if disposition in ("PLAINTIFF_VERDICT", "SETTLED"):
        create_npdb_report(claim, negotiation, disbursed, resolved_on)

    if disposition == "SETTLED":
        rating.rerate_drafts(insured["id"], "RENEWAL_PROSPECTIVE")
    return claim
