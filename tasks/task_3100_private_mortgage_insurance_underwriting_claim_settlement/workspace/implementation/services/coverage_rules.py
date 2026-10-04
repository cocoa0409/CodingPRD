"""Coverage termination, cancellation refunds and the rescission-relief guarantee.

Implements calculations `cancellation_refund`, `coverage_termination_evaluation`,
`rescission_relief_eligibility` and `claim_eligibility_gate` from SCAFFOLD
section 1.3 against the prose of PRD 3.4 / 3.5 / 3.6.
"""

from common import d, days, floor_int, parse_utc, round_half_up_int
from db import touch

# SCAFFOLD constants.
MIN_NOTICE_DAYS = 30
DEFICIENCY_MIN_DAYS = 60
MILESTONE_MIN_DAYS = 30
CYCLE_DAYS = 365
RULE_2_WINDOW_DAYS = 730

PARTICIPATION_REQUIRED = ["OUTREACH_SENT", "INTAKE_COMPLETE"]
PARTICIPATION_COMPLETE_REQUIRED = [
    "OUTREACH_SENT",
    "INTAKE_COMPLETE",
    "EVALUATION_COMPLETE",
    "PROGRAM_ACCEPTED",
]

ACTIVITY_KINDS = (
    "OUTREACH_SENT",
    "INTAKE_COMPLETE",
    "EVALUATION_COMPLETE",
    "PROGRAM_ACCEPTED",
    "COLLATERAL_SALE_LISTING",
)

TERMINATION_LABELS = ("LTV_MILESTONE", "SERVICER_LOSS_MITIGATION_FAILURE", "BORROWER_REQUEST")


# --- loss mitigation ----------------------------------------------------------

def servicer_tier_standard(tier):
    """A TIER_1 or TIER_2 servicer's tier standard is PARTICIPATION; TIER_3 is
    PARTICIPATION_COMPLETE (PRD 3.1 / 3.4)."""
    return "PARTICIPATION_COMPLETE" if tier == "TIER_3" else "PARTICIPATION"


def applicable_standard(policy, servicer):
    """The greater of the policy's standard and the servicer's tier standard."""
    policy_standard = policy["servicer_loss_mitigation_standard"]
    tier_standard = servicer_tier_standard(servicer["tier"])
    if policy_standard == "PARTICIPATION_COMPLETE" or tier_standard == "PARTICIPATION_COMPLETE":
        return "PARTICIPATION_COMPLETE"
    return "PARTICIPATION"


def completed_activities(report):
    completed = set()
    for activity in report.get("loss_mitigation_activities") or []:
        if isinstance(activity, dict):
            kind = activity.get("activity_kind")
            if kind in ACTIVITY_KINDS:
                completed.add(kind)
    return completed


def participation_standard_met(report, policy, servicer):
    """A set-containment test, not a score. COLLATERAL_SALE_LISTING satisfies the
    PARTICIPATION standard on its own; it does not satisfy PARTICIPATION_COMPLETE."""
    standard = applicable_standard(policy, servicer)
    completed = completed_activities(report)
    if standard == "PARTICIPATION_COMPLETE":
        return all(kind in completed for kind in PARTICIPATION_COMPLETE_REQUIRED)
    if "COLLATERAL_SALE_LISTING" in completed:
        return True
    return all(kind in completed for kind in PARTICIPATION_REQUIRED)


# --- delinquency streak -------------------------------------------------------

def _newest_first(reports):
    """PRD 3.4: effective instant descending, ties broken by creation time
    ascending, with a further tie on identifier ascending purely for stability."""
    ordered = sorted(reports, key=lambda r: (r["created_at"], r["id"]))
    ordered.sort(key=lambda r: parse_utc(r["effective_utc"]), reverse=True)
    return ordered


def delinquency_streak(loan, reports):
    """Number of consecutive Class-A reports from the front of the order
    (effective_utc DESC, created_at ASC, id ASC) before the first Class-B report."""
    streak = 0
    for report in _newest_first(reports):
        if report["delinquency_class"] == "A":
            streak += 1
        else:
            break
    return streak


# --- rescission relief --------------------------------------------------------

def rescission_relief_cycle_index(loan, reports, policy):
    """Count of consecutive free cycles walking the loan's Class-A reports newest
    first, stopping at the first report whose cycle is not free.

    A report's cycle is the 365-day window (effective_utc - 365d, effective_utc].
    The cycle is free when it contains no Class-A report other than the one that
    defines the window.
    """
    class_a = [r for r in reports if r["delinquency_class"] == "A"]
    if not class_a:
        return 0, []

    ordered = _newest_first(class_a)

    consecutive = []
    for report in ordered:
        end = parse_utc(report["effective_utc"])
        start = end - days(CYCLE_DAYS)
        free = True
        for other in class_a:
            if other["id"] == report["id"]:
                continue
            moment = parse_utc(other["effective_utc"])
            if start < moment <= end:
                free = False
                break
        if not free:
            break
        consecutive.append(report)
    return len(consecutive), consecutive


def rescission_relief_status(loan, reports, policy, previous_status):
    """Rule 1 -> PROVISIONAL when the cycle index reaches one or more.
    Rule 2 -> GUARANTEED when the index has reached the policy's
    rescission_relief_cycles, two_year_effective_flag is true, and every counted
    cycle's defining instant falls within (anniversary_utc, anniversary_utc + 730d].
    GUARANTEED is absorbing.
    """
    index, cycles = rescission_relief_cycle_index(loan, reports, policy)

    if previous_status == "GUARANTEED":
        return "GUARANTEED", index

    anniversary = parse_utc(policy["anniversary_utc"])
    window_end = anniversary + days(RULE_2_WINDOW_DAYS)

    guaranteed = (
        index >= policy["rescission_relief_cycles"]
        and policy["two_year_effective_flag"] is True
        and all(
            anniversary < parse_utc(r["effective_utc"]) <= window_end for r in cycles
        )
    )
    if guaranteed:
        return "GUARANTEED", index
    if index >= 1:
        return "PROVISIONAL", index
    return "NONE", index


def recompute_loan_relief(loan, reports, policy):
    status, index = rescission_relief_status(
        loan, reports, policy, loan.get("rescission_relief_status", "NONE")
    )
    loan["rescission_relief_status"] = status
    loan["rescission_relief_cycle_index"] = index


# --- cancellation refund ------------------------------------------------------

def current_coverage_base_cents(loan):
    """floor(current_upb_cents * coverage_percent / 100)."""
    return floor_int(d(loan["current_upb_cents"]) * d(loan["coverage_percent"]) / 100)


def max_refund_cents(loan):
    """round_half_up(10000 * (coverage_base_upb_cents - current_coverage_base_cents)
    / coverage_base_upb_cents)."""
    original = loan["coverage_base_upb_cents"]
    if not original:
        return 0
    current = current_coverage_base_cents(loan)
    value = d(10000) * d(original - current) / d(original)
    return round_half_up_int(value)


def refund_for(loan, evidence_cents):
    return max(0, min(evidence_cents, max_refund_cents(loan)))


def effective_instant(applied_utc, notice_utc):
    """max(applied_utc, notice_utc + 30 days) - clamped forward, never accepted
    as requested."""
    return max(parse_utc(applied_utc), parse_utc(notice_utc) + days(MIN_NOTICE_DAYS))


# --- coverage termination arbitration -----------------------------------------

def evaluate_termination(loan, clock_now, applied_notices):
    """Evaluate every satisfied trigger and take the earliest effective instant,
    breaking instant ties in the fixed label order LTV_MILESTONE >
    SERVICER_LOSS_MITIGATION_FAILURE > BORROWER_REQUEST. Returns
    (label, effective_dt) or (None, None) when no trigger is satisfied.
    """
    clock = parse_utc(clock_now)
    candidates = []

    if loan.get("amortization_status") == "AT_78" and loan.get("milestone_78_reached_utc"):
        milestone = parse_utc(loan["milestone_78_reached_utc"]) + days(MILESTONE_MIN_DAYS)
        candidates.append(("LTV_MILESTONE", max(clock, milestone)))

    if loan.get("claim_blocked") and loan.get("delinquency_streak", 0) >= 3:
        deficient = loan.get("last_loss_mitigation_deficient_utc")
        if deficient:
            candidates.append(
                ("SERVICER_LOSS_MITIGATION_FAILURE",
                 parse_utc(deficient) + days(DEFICIENCY_MIN_DAYS))
            )

    for notice in applied_notices:
        if notice["status"] != "APPLIED":
            continue
        if notice["request_kind"] != "BORROWER_REQUEST":
            continue
        candidates.append(
            ("BORROWER_REQUEST", effective_instant(notice["applied_utc"], notice["notice_utc"]))
        )

    if not candidates:
        return None, None

    best_label, best_instant = None, None
    for label, instant in candidates:
        if best_instant is None or instant < best_instant:
            best_label, best_instant = label, instant
        elif instant == best_instant:
            if TERMINATION_LABELS.index(label) < TERMINATION_LABELS.index(best_label):
                best_label = label
            else:
                pass
    return best_label, best_instant


def apply_termination_evaluation(loan, notices, clock_now, apply_early=True):
    """Drive the coverage axis from the arbitration above.

    When coverage is ACTIVE the earliest satisfied trigger moves it to
    PENDING_CANCELLATION. When it is already PENDING_CANCELLATION the axis moves
    to CANCELLED once the logical clock has reached the effective instant.
    """
    if loan["coverage_status"] == "CANCELLED":
        return

    if loan["coverage_status"] == "ACTIVE":
        label, instant = evaluate_termination(loan, clock_now, notices)
        if label is not None:
            loan["coverage_status"] = "PENDING_CANCELLATION"
            loan["termination_reason"] = label
            loan["cancellation_effective_utc"] = instant
            touch(loan)

    if loan["coverage_status"] == "PENDING_CANCELLATION":
        effective = loan.get("cancellation_effective_utc")
        if effective is not None and parse_utc(effective) <= parse_utc(clock_now):
            loan["coverage_status"] = "CANCELLED"
            for notice in notices:
                if notice["status"] == "SUBMITTED":
                    notice["status"] = "APPLIED"
                    touch(notice)
            touch(loan)