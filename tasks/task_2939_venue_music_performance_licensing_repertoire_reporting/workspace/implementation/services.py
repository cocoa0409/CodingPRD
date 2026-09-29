"""Shared state-transition machinery: venue recomputation, the fee ledger,
the billing dimension, and the two named cascades of PRD 3.2 and 3.8.

Every mutation here is a full mutation in the sense of PRD 2.11: the affected
row's updated_at is refreshed and its version increases by 1, even when the
only change was a derived total nobody asked for.
"""

import calc
import db
from core import (
    DELINQUENCY_TOLERANCE_CENTS,
    DUE_DATE_DAYS,
    GAP_ESCALATION_THRESHOLD_H,
    MAX_REVISION_ROUNDS,
    plus_days,
)

NON_TERMINAL_CASE_STATUSES = ("OPEN", "FINDINGS_ISSUED", "SETTLEMENT_PROPOSED", "DISPUTED")


# ---------------------------------------------------------------------------
# Venue derived state
# ---------------------------------------------------------------------------


def _apply_ledger(venue):
    venue.update(calc.ledger_balances(venue["id"]))


def _apply_coverage(venue):
    share = calc.covered_share_bp(venue["id"])
    venue["covered_share_bp"] = share
    venue["coverage_posture"] = calc.posture_for(share)


def _apply_audit_hold(venue):
    hold = False
    for case in db.cases_of_venue(venue["id"]):
        if case["status"] in NON_TERMINAL_CASE_STATUSES:
            hold = True
            break
    venue["audit_hold"] = hold


def _apply_gap_risk(venue):
    venue["gap_risk_score_h"] = calc.gap_risk_score_h(venue["id"])


def recompute_venue(venue, ledger=False, coverage=False, audit_hold=False, gap_risk=False):
    """Recompute the requested derived groups and count one venue mutation."""
    if ledger:
        _apply_ledger(venue)
    if coverage:
        _apply_coverage(venue)
    if audit_hold:
        _apply_audit_hold(venue)
    if gap_risk:
        _apply_gap_risk(venue)
    db.touch(venue)
    return venue


# ---------------------------------------------------------------------------
# The billing dimension (PRD 2.11)
# ---------------------------------------------------------------------------


def _set_billing(license_row, status, touch=True):
    """Move the billing dimension, optionally without a version increment.

    PRD 2.5 counts one increment per mutation of a row and PRD 2.11 says that
    when one call advances both dimensions of the same licence "each documented
    increment applies" -- activation documents a single increment (the re-rate)
    and termination a single increment (the coverage move), so on those two
    paths the billing move rides along inside the mutation the caller is already
    recording rather than adding a second one.  Everywhere else the billing move
    is the whole mutation and carries its own increment.
    """
    license_row["billing_status"] = status
    if touch:
        db.touch(license_row)


def has_issued_assessment(license_id):
    for row in db.where("assessments", license_id=license_id):
        if row["status"] == "ISSUED":
            return True
    return False


def bill_on_activation(license_row, touch=True):
    """UNBILLED -> INVOICED on an INITIAL or RENEWAL issuance."""
    if license_row["billing_status"] == "UNBILLED":
        _set_billing(license_row, "INVOICED", touch=touch)


def bill_on_extra_assessment(license_row):
    """PAID -> INVOICED when a true-up or rider lands on a settled licence."""
    if license_row["billing_status"] == "PAID":
        _set_billing(license_row, "INVOICED")


def delinquency_sweep(venue):
    """PRD 2.11/3.2 link 4: venue-wide sweep after an issuance."""
    if venue["outstanding_balance_cents"] <= DELINQUENCY_TOLERANCE_CENTS:
        return
    for lic in db.licenses_of_venue(venue["id"]):
        if lic["billing_status"] in ("UNBILLED", "INVOICED"):
            _set_billing(lic, "DELINQUENT")


def relieve_license_billing(venue, license_row):
    """Post-payment relief for one licence (PRD 2.11, 3.9)."""
    if license_row is None:
        return
    outstanding = venue["outstanding_balance_cents"]
    billing = license_row["billing_status"]
    if billing not in ("INVOICED", "DELINQUENT"):
        return
    if outstanding == 0 and not has_issued_assessment(license_row["id"]):
        if billing != "PAID":
            _set_billing(license_row, "PAID")
        return
    if billing == "DELINQUENT" and outstanding <= DELINQUENCY_TOLERANCE_CENTS:
        _set_billing(license_row, "INVOICED")


def relieve_venue_billing(venue):
    """Venue-wide relief after an audit settlement (PRD 3.9)."""
    if venue["outstanding_balance_cents"] > DELINQUENCY_TOLERANCE_CENTS:
        return
    for lic in db.licenses_of_venue(venue["id"]):
        if lic["billing_status"] != "DELINQUENT":
            continue
        if venue["outstanding_balance_cents"] == 0 and not has_issued_assessment(lic["id"]):
            _set_billing(lic, "PAID")
        else:
            _set_billing(lic, "INVOICED")


# ---------------------------------------------------------------------------
# Fee assessments
# ---------------------------------------------------------------------------


def issue_assessment(venue, license_id, audit_case_id, kind, amount_cents):
    """Create an ISSUED assessment.  Callers guarantee amount_cents >= 1."""
    return db.new_row(
        "assessments",
        {
            "venue_id": venue["id"],
            "license_id": license_id,
            "audit_case_id": audit_case_id,
            "assessment_kind": kind,
            "amount_cents": amount_cents,
            "paid_amount_cents": 0,
            "due_date": plus_days(db.now(), DUE_DATE_DAYS),
            "status": "ISSUED",
        },
    )


# ---------------------------------------------------------------------------
# CASCADE-A -- rate-schedule publication (PRD 3.2)
# ---------------------------------------------------------------------------


def publish_schedule(schedule):
    """Publish a DRAFT schedule and run the four causally chained links."""
    # LINK 1's candidate set is resolved before this schedule joins EFFECTIVE.
    incumbent = calc.incumbent_effective(schedule["society_id"], schedule["venue_category"])

    schedule["status"] = "EFFECTIVE"
    db.touch(schedule)

    if incumbent is None or incumbent["id"] == schedule["id"]:
        # First publication for the pair: no supersession, links 2-4 do not run.
        return schedule

    # LINK 1 -- supersession.
    incumbent["status"] = "SUPERSEDED"
    db.touch(incumbent)

    # LINK 2 -- re-pinning and re-rating, oldest licence first.
    society = db.society(schedule["society_id"])
    affected = [
        lic
        for lic in db.ordered("licenses")
        if lic["rate_schedule_id"] == incumbent["id"] and lic["coverage_status"] == "ACTIVE"
    ]
    for lic in affected:
        venue = db.venue(lic["venue_id"])
        previous_fee = lic["annual_fee_cents"]
        lic["rate_schedule_id"] = schedule["id"]
        lic["pinned_schedule_version"] = schedule["schedule_version"]
        lic["annual_fee_cents"] = calc.verified_fee(schedule, society, venue, lic["license_type"])
        lic["verified_fee_delta_cents"] = (
            lic["annual_fee_cents"] - lic["provisional_annual_fee_cents"]
        )
        db.touch(lic)

        # LINK 3 -- the prorated true-up invoice.
        amount = calc.trueup_amount(lic["annual_fee_cents"], previous_fee, lic["term_end"])
        if amount <= 0:
            continue
        issue_assessment(venue, lic["id"], None, "RATE_CHANGE_TRUEUP", amount)

        # LINK 4 -- the ledger and the delinquency sweep.
        recompute_venue(venue, ledger=True)
        delinquency_sweep(venue)
        bill_on_extra_assessment(lic)

    return schedule


# ---------------------------------------------------------------------------
# CASCADE-B -- performance-report submission (PRD 3.8)
# ---------------------------------------------------------------------------


def _pushback_applications(venue):
    """LINK 4: applications caught by a freshly raised audit hold."""
    for application in db.where("applications", venue_id=venue["id"]):
        if application["status"] not in ("SUBMITTED", "UNDER_REVIEW"):
            continue
        if application["revision_round"] >= MAX_REVISION_ROUNDS:
            application["status"] = "DECLINED"
            application["decline_reason"] = "REVISION_LIMIT_EXCEEDED"
        else:
            application["status"] = "RETURNED_FOR_REVISION"
            application["return_reason"] = "AUDIT_HOLD"
            application["revision_round"] += 1
        db.touch(application)


def submit_report(report):
    """LINK 1 through LINK 4 of the repertoire gap cascade."""
    license_row = db.license_row(report["license_id"])
    venue = db.venue(license_row["venue_id"])

    # LINK 1 -- matching, coverage-testing and the two gap shares.
    report["status"] = "SUBMITTED"
    entries = db.entries_of_report(report["id"])
    total_weight = 0
    unmatched_weight = 0
    uncovered_weight = 0
    matched_count = 0
    uncovered_count = 0
    for entry in entries:
        work = calc.match_work(entry)
        entry["is_matched"] = work is not None
        entry["matched_work_id"] = work["id"] if work is not None else None
        entry["is_covered"] = calc.entry_covered(entry, venue["id"])
        weight = calc.entry_weight(entry)
        total_weight += weight
        if entry["is_matched"]:
            matched_count += 1
        else:
            unmatched_weight += weight
        if not entry["is_covered"]:
            uncovered_count += 1
            uncovered_weight += weight

    report["reported_entry_count"] = len(entries)
    report["matched_entry_count"] = matched_count
    report["uncovered_entry_count"] = uncovered_count
    report["unmatched_share_pct_h"] = calc.share_pct_h(unmatched_weight, total_weight)
    report["uncovered_share_pct_h"] = calc.share_pct_h(uncovered_weight, total_weight)
    report["gap_exposure_cents"] = calc.gap_exposure(
        license_row["annual_fee_cents"], report["uncovered_share_pct_h"]
    )
    db.touch(report)

    # LINK 2 -- the venue's gap risk score.
    recompute_venue(venue, gap_risk=True)

    # LINK 3 -- escalation into an audit case.
    if venue["gap_risk_score_h"] < GAP_ESCALATION_THRESHOLD_H:
        return report

    society_ids = []
    seen = set()
    uncovered_affiliations = set()
    for entry in db.entries_of_report(report["id"]):
        if not entry["is_covered"]:
            uncovered_affiliations.add(entry["society_affiliation"])
    for society in db.ordered("societies"):
        if society["repertoire_share_bp"] <= 0:
            continue
        if society["society_code"] in uncovered_affiliations and society["id"] not in seen:
            seen.add(society["id"])
            society_ids.append(society["id"])

    db.new_row(
        "audit_cases",
        {
            "venue_id": venue["id"],
            "audit_trigger": "GAP_RISK_ESCALATION",
            "lookback_start": report["period_start"],
            "lookback_end": report["period_end"],
            "society_ids": society_ids,
            "status": "OPEN",
            "unlicensed_month_count": 0,
            "back_license_exposure_cents": 0,
            "penalty_cents": 0,
            "pre_credit_total_cents": 0,
            "goodwill_credit_cents": 0,
            "settlement_total_cents": 0,
            "settlement_floor_cents": 0,
            "offered_amount_cents": None,
            "payment_plan_months": None,
            "dispute_round": 0,
            "findings_issued_by_user_id": None,
            "settlement_proposed_by_user_id": None,
            "settled_by_user_id": None,
            "closed_reason": None,
        },
    )
    recompute_venue(venue, audit_hold=True)

    # LINK 4 -- applications caught by the hold.
    _pushback_applications(venue)
    return report


def reopen_report(report):
    """Appending to a REJECTED report reopens it (PRD 3.8)."""
    report["status"] = "DRAFT"
    report["rejection_reason"] = None
    report["matched_entry_count"] = 0
    report["uncovered_entry_count"] = 0
    report["unmatched_share_pct_h"] = 0
    report["uncovered_share_pct_h"] = 0
    report["gap_exposure_cents"] = 0
    for entry in db.entries_of_report(report["id"]):
        entry["is_matched"] = False
        entry["matched_work_id"] = None
        entry["is_covered"] = False
    db.touch(report)
    return report
