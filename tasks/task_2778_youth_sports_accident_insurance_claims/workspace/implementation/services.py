"""Calculations, derived-state recomputation and the four cascade chains."""

from datetime import timedelta
from decimal import Decimal

import constants as C
import db
import response
import util
from util import round_half_up, apply_bps, ratio_bps


# ------------------------------------------------------------------ row helper

def touch(row, **changes):
    """Apply changes; mark the row for a single version bump when anything moved."""
    changed = False
    for key, value in changes.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    if changed:
        response.mark_dirty(row)
    return changed


# ------------------------------------------------------------------- premium

def gross_premium_cents(n, base_rate_cents, hazard_class):
    """Banded gross premium: round half up PER BAND LINE, then sum."""
    hz = C.HAZARD_LOAD_BPS[hazard_class]
    load = (Decimal(10000) + Decimal(hz)) / Decimal(10000)
    bands = (
        (max(0, min(n, C.PREMIUM_BAND_1_CAP)), C.PREMIUM_BAND_1_FACTOR),
        (max(0, min(n, C.PREMIUM_BAND_2_CAP) - C.PREMIUM_BAND_1_CAP), C.PREMIUM_BAND_2_FACTOR),
        (max(0, n - C.PREMIUM_BAND_2_CAP), C.PREMIUM_BAND_3_FACTOR),
    )
    total = 0
    for head_count, factor in bands:
        line = Decimal(head_count) * Decimal(int(base_rate_cents)) * Decimal(factor) * load
        total += round_half_up(line)
    return total


def volume_credit_bps_for(subtotal_cents):
    for low, high, bps in C.VOLUME_CREDIT_TIERS_BPS:
        if subtotal_cents >= low and (high is None or subtotal_cents <= high):
            return bps
    return 0


def assemble_premium(gross, cat_layer_elected):
    """The six pinned steps of the annual premium assembly."""
    cat = apply_bps(gross, C.CAT_LAYER_RATE_BPS) if cat_layer_elected else 0
    subtotal = gross + cat
    bps = volume_credit_bps_for(subtotal)
    credit = apply_bps(subtotal, bps)
    annual = max(C.MIN_ANNUAL_PREMIUM_CENTS, subtotal - credit)
    return {
        "gross_premium_cents": gross,
        "cat_layer_charge_cents": cat,
        "premium_subtotal_cents": subtotal,
        "volume_credit_bps": bps,
        "volume_credit_cents": credit,
        "annual_premium_cents": annual,
    }


def rate_policy(policy, sport, participant_count=None):
    """Full re-rate of a policy from scratch. Returns the premium figure block."""
    n = policy["enrolled_participant_count"] if participant_count is None else participant_count
    gross = gross_premium_cents(
        n, sport["base_rate_per_participant_cents"], sport["hazard_class"]
    )
    return assemble_premium(gross, bool(policy["cat_layer_elected"]))


def experience_tier_for(ratio_bps_value):
    for low, high, tier in C.EXPERIENCE_TIER_BANDS_BPS:
        if (low is None or ratio_bps_value >= low) and (high is None or ratio_bps_value <= high):
            return tier
    return "PREFERRED"


# --------------------------------------------------------------- provider bill

def reprice_figures(bill, cap_cents, severity_tier):
    billed = bill["billed_charge_cents"]
    sched = bill["fee_schedule_amount_cents"]
    if bill["network_status"] == "IN_NETWORK":
        negotiated = min(billed, sched)
    else:
        negotiated = min(billed, apply_bps(sched, C.OON_FEE_SCHEDULE_MULTIPLIER_BPS))
    scheduled_cap = apply_bps(cap_cents, C.SEVERITY_CAP_FACTOR_BPS[severity_tier])
    allowed = max(0, min(negotiated, scheduled_cap))
    balance = max(0, billed - allowed)
    if bill["network_status"] == "IN_NETWORK":
        family = 0
    else:
        family = min(balance, C.OON_FAMILY_SHARE_CAP_CENTS)
    return {
        "negotiated_amount_cents": negotiated,
        "scheduled_cap_cents": scheduled_cap,
        "allowed_amount_cents": allowed,
        "balance_billed_cents": balance,
        "family_responsibility_cents": family,
    }


def recompute_bill_other_plan_paid(bill):
    total = sum(
        r["other_plan_paid_cents"]
        for r in db.all_rows("coordination_records")
        if r["provider_bill_id"] == bill["id"] and r["status"] == "ACTIVE"
    )
    touch(bill, other_plan_paid_cents=total)


# --------------------------------------------------------------------- claims

def counted_bills(claim):
    return [
        b for b in db.bills_of_claim(claim["id"])
        if b["status"] in C.COUNTED_BILL_STATUSES
    ]


def recompute_claim_balance_totals(claim):
    bills = counted_bills(claim)
    touch(
        claim,
        balance_billed_total_cents=sum(b["balance_billed_cents"] or 0 for b in bills),
        family_responsibility_total_cents=sum(
            b["family_responsibility_cents"] or 0 for b in bills
        ),
    )


def recompute_claim_payment_totals(claim):
    payments = [p for p in db.payments_of_claim(claim["id"]) if p["status"] == "ISSUED"]
    base = sum(p["amount_cents"] for p in payments if p["layer"] == "BASE")
    cat = sum(p["amount_cents"] for p in payments if p["layer"] == "CATASTROPHIC")
    touch(claim, paid_base_cents=base, paid_cat_cents=cat, paid_to_date_cents=base + cat)


def recompute_claim_determination(claim):
    """The benefit waterfall. Never runs again once the claim has been adjudicated."""
    if claim.get("_determination_frozen"):
        return
    policy = db.get("league_policies", claim["league_policy_id"])
    enrollment = db.get("enrollments", claim["enrollment_id"])
    bills = counted_bills(claim)
    bill_ids = {b["id"] for b in bills}
    allowed_total = sum(b["allowed_amount_cents"] or 0 for b in bills)
    other_paid = sum(
        r["other_plan_paid_cents"]
        for r in db.coordination_records_of_claim(claim["id"])
        if r["status"] == "ACTIVE" and r["provider_bill_id"] in bill_ids
    )
    basis = claim["coordination_basis"]
    offset = other_paid if basis == "EXCESS_OF_OTHER" else 0
    if basis == "EXCESS_OF_OTHER":
        deductible_basis = policy["deductible_cents"]
    else:
        deductible_basis = apply_bps(
            policy["deductible_cents"], C.FULL_EXCESS_DEDUCTIBLE_FACTOR_BPS
        )
    net_after_other = max(0, allowed_total - offset)
    deductible_applied = min(net_after_other, deductible_basis)
    benefit_before_limit = max(0, net_after_other - deductible_applied)
    base_layer = min(benefit_before_limit, policy["per_injury_limit_cents"])
    cat_eligible = max(0, benefit_before_limit - policy["cat_attachment_point_cents"])
    cat_remaining = max(
        0, policy["cat_lifetime_max_cents"] - enrollment["lifetime_cat_benefit_used_cents"]
    )
    if policy["cat_layer_elected"] and claim["cat_certification_status"] == "CERTIFIED":
        cat_layer = min(cat_eligible, cat_remaining)
    else:
        cat_layer = 0
    touch(
        claim,
        allowed_amount_total_cents=allowed_total,
        other_insurance_paid_cents=other_paid,
        deductible_applied_cents=deductible_applied,
        benefit_before_limit_cents=benefit_before_limit,
        base_layer_benefit_cents=base_layer,
        cat_layer_benefit_cents=cat_layer,
        benefit_payable_cents=base_layer + cat_layer,
    )


def reserve_amount_for(policy, severity_tier):
    exposure_cap = policy["per_injury_limit_cents"] + (
        policy["cat_lifetime_max_cents"] if policy["cat_layer_elected"] else 0
    )
    return min(C.RESERVE_BY_SEVERITY_CENTS[severity_tier], exposure_cap)


def coordination_basis_for(coordination_status):
    if coordination_status == "NO_OTHER_COVERAGE_CONFIRMED":
        return "FULL_EXCESS"
    if coordination_status in ("EOB_RECEIVED", "EOB_WAIVED"):
        return "EXCESS_OF_OTHER"
    return None


# ------------------------------------------------------------ league / roster

def recompute_league_in_force(league):
    count = sum(
        1 for p in db.policies_of_league(league["id"])
        if p["status"] in C.IN_FORCE_COUNTED_STATUSES
    )
    touch(league, in_force_policy_count=count)


def recompute_participant(participant):
    rows = [
        e for e in db.all_rows("enrollments")
        if e["participant_id"] == participant["id"]
    ]
    enrolled = [e for e in rows if e["status"] == "ENROLLED"]
    if not rows:
        roster_status = "ROSTERED"
    elif enrolled:
        roster_status = "ROSTERED"
    else:
        roster_status = "INACTIVE"
    touch(
        participant,
        enrolled_policy_count=len(enrolled),
        roster_status=roster_status,
    )


def plan_coverage_state(plan):
    clock = db.now()
    effective = util.parse_datetime(plan["effective_date"])
    if effective > clock:
        return "TERMINATED"
    if plan["termination_date"] is not None:
        termination = util.parse_datetime(plan["termination_date"])
        if clock >= termination:
            return "TERMINATED"
    return "ACTIVE"


def recompute_plan_coverage_state(plan):
    touch(plan, coverage_state=plan_coverage_state(plan))


def recompute_all_plan_coverage_states():
    for plan in db.all_rows("family_health_plans"):
        recompute_plan_coverage_state(plan)


def other_coverage_on_file(participant_id):
    """Plans of the athlete with ACTIVE coverage_state not attested as no-coverage."""
    return [
        p for p in db.plans_of_participant(participant_id)
        if plan_coverage_state(p) == "ACTIVE" and p["verification_status"] != "NO_COVERAGE_ATTESTED"
    ]


def active_coverage_plans(participant_id):
    return [
        p for p in db.plans_of_participant(participant_id)
        if plan_coverage_state(p) == "ACTIVE"
    ]


# ------------------------------------------------------------------ enrollment

def recompute_enrollment(enrollment):
    """Lifetime catastrophic accumulation and the three ordered coverage tests."""
    policy = db.get("league_policies", enrollment["league_policy_id"])
    used = 0
    for claim in db.claims_of_enrollment(enrollment["id"]):
        for payment in db.payments_of_claim(claim["id"]):
            if payment["status"] == "ISSUED" and payment["layer"] == "CATASTROPHIC":
                used += payment["amount_cents"]
    if enrollment["status"] == "WITHDRAWN":
        coverage_status = "WITHDRAWN_NO_COVERAGE"
    elif used >= policy["cat_lifetime_max_cents"]:
        coverage_status = "LIFETIME_EXHAUSTED"
    else:
        coverage_status = "COVERED"
    was = enrollment["coverage_status"]
    touch(
        enrollment,
        lifetime_cat_benefit_used_cents=used,
        coverage_status=coverage_status,
    )
    if coverage_status == "LIFETIME_EXHAUSTED" and was != "LIFETIME_EXHAUSTED":
        reject_reports_of_enrollment(enrollment, "LIFETIME_BENEFIT_EXHAUSTED")


# -------------------------------------------------------------------- cascades

def reject_reports_of_activity(activity):
    for report in db.all_rows("injury_reports"):
        if report["sanctioned_activity_id"] != activity["id"]:
            continue
        if report["status"] in ("PENDING_VERIFICATION", "RETURNED_FOR_CORRECTION"):
            touch(report, status="REJECTED", rejection_reason="ACTIVITY_NOT_SANCTIONED")


def reject_reports_of_enrollment(enrollment, reason):
    for report in db.all_rows("injury_reports"):
        if report["enrollment_id"] != enrollment["id"]:
            continue
        if report["status"] in ("PENDING_VERIFICATION", "RETURNED_FOR_CORRECTION"):
            touch(report, status="REJECTED", rejection_reason=reason)


def reject_pending_activities(policy):
    for activity in db.activities_of_policy(policy["id"]):
        if activity["status"] != "PENDING_SANCTION":
            continue
        touch(activity, status="REJECTED", rejection_reason="POLICY_FROZEN")
        reject_reports_of_activity(activity)


# ------------------------------------------------------- policy loss + posture

def open_claims_of_policy(policy):
    return [
        c for c in db.claims_of_policy(policy["id"])
        if c["adjudication_status"] in C.OPEN_ADJUDICATION_STATUSES
    ]


def _posture_for(policy, league):
    if policy["status"] in ("CLOSED", "CANCELLED"):
        return "FROZEN", "STATUS"
    if league["sanctioning_status"] == "SUSPENDED":
        return "FROZEN", "LEAGUE_SUSPENDED"
    if policy["incurred_loss_cents"] >= policy["aggregate_limit_cents"]:
        return "FROZEN", "AGGREGATE_LIMIT"
    if policy["open_claim_count"] >= C.POSTURE_CLAIMS_REVIEW_OPEN_CLAIMS:
        return "CLAIMS_REVIEW", "OPEN_CLAIMS"
    if policy["incurred_loss_ratio_bps"] >= C.POSTURE_CLAIMS_REVIEW_LOSS_RATIO_BPS:
        return "CLAIMS_REVIEW", "LOSS_RATIO"
    return "OPEN", None


def recompute_policy(policy, force_activity_sweep=False, allow_auto_close=True):
    """Loss experience, the RUN_OFF -> CLOSED self-transition and coverage posture."""
    league = db.get("leagues", policy["league_id"])
    claims = db.claims_of_policy(policy["id"])
    open_set = [c for c in claims if c["adjudication_status"] in C.OPEN_ADJUDICATION_STATUSES]
    paid_loss = 0
    for claim in claims:
        for payment in db.payments_of_claim(claim["id"]):
            if payment["status"] == "ISSUED":
                paid_loss += payment["amount_cents"]
    reserve = sum(c["reserve_amount_cents"] or 0 for c in open_set)
    incurred = paid_loss + reserve
    annual = policy["annual_premium_cents"] or 0
    incurred_bps = ratio_bps(incurred, annual)
    paid_bps = ratio_bps(paid_loss, annual)
    touch(
        policy,
        paid_loss_cents=paid_loss,
        reserve_cents=reserve,
        incurred_loss_cents=incurred,
        open_claim_count=len(open_set),
        incurred_loss_ratio_bps=incurred_bps,
        paid_loss_ratio_bps=paid_bps,
        experience_tier=experience_tier_for(incurred_bps),
    )
    if allow_auto_close and policy["status"] == "RUN_OFF" and policy["open_claim_count"] == 0:
        touch(policy, status="CLOSED")
        recompute_league_in_force(league)
    was_posture = policy["coverage_posture"]
    posture, reason = _posture_for(policy, league)
    touch(policy, coverage_posture=posture)
    sweep = force_activity_sweep or (
        posture == "FROZEN"
        and was_posture != "FROZEN"
        and reason in ("LEAGUE_SUSPENDED", "AGGREGATE_LIMIT")
    )
    if sweep:
        reject_pending_activities(policy)


def recompute_after_claim_change(claim):
    policy = db.get("league_policies", claim["league_policy_id"])
    recompute_policy(policy)


# ------------------------------------------------------------------ eob sweep

def eob_sweep(claim):
    """Lazy 45-day waiver, run before anything else in a request that touches a claim."""
    if claim["coordination_status"] != "EOB_REQUESTED":
        return
    requested = util.parse_datetime(claim["eob_requested_at"])
    if requested is None:
        return
    if util.day_diff(db.now(), requested) > C.EOB_WINDOW_DAYS:
        touch(
            claim,
            coordination_status="EOB_WAIVED",
            coordination_basis="EXCESS_OF_OTHER",
        )
        recompute_claim_determination(claim)


def eob_sweep_all():
    for claim in db.all_rows("claims"):
        eob_sweep(claim)


# ------------------------------------------------------- activity conflicts

def _window(starts_at, ends_at, buffer_minutes):
    delta = timedelta(minutes=buffer_minutes)
    return starts_at - delta, ends_at + delta


def conflicting_activity(policy_id, starts_at, ends_at, buffer_minutes):
    """Per-athlete buffered conflict check across every policy sharing an athlete."""
    cand_start, cand_end = _window(starts_at, ends_at, buffer_minutes)
    athletes = {
        e["participant_id"]
        for e in db.enrollments_of_policy(policy_id)
        if e["status"] == "ENROLLED"
    }
    if not athletes:
        return None
    policy_ids = set()
    for enrollment in db.all_rows("enrollments"):
        if enrollment["status"] == "ENROLLED" and enrollment["participant_id"] in athletes:
            policy_ids.add(enrollment["league_policy_id"])
    for activity in db.all_rows("sanctioned_activities"):
        if activity["league_policy_id"] not in policy_ids:
            continue
        if activity["status"] not in ("PENDING_SANCTION", "SANCTIONED"):
            continue
        other_start, other_end = _window(
            util.parse_datetime(activity["starts_at"]),
            util.parse_datetime(activity["ends_at"]),
            activity["travel_buffer_minutes"],
        )
        if cand_start <= other_end and other_start <= cand_end:
            return activity
    return None


# ------------------------------------------------------------ claim creation

def open_claim_from_report(report, enrollment, policy):
    """Link 2 of the verification chain: exactly one claim per verified report."""
    return db.new_row("claims", {
        "injury_report_id": report["id"],
        "league_policy_id": enrollment["league_policy_id"],
        "enrollment_id": enrollment["id"],
        "adjudication_status": "PENDING_COORDINATION",
        "coordination_status": "NOT_STARTED",
        "eob_requested_at": None,
        "coordination_basis": None,
        "reserve_amount_cents": reserve_amount_for(policy, report["severity_tier"]),
        "allowed_amount_total_cents": 0,
        "other_insurance_paid_cents": 0,
        "deductible_applied_cents": 0,
        "benefit_before_limit_cents": 0,
        "base_layer_benefit_cents": 0,
        "cat_layer_benefit_cents": 0,
        "benefit_payable_cents": 0,
        "paid_base_cents": 0,
        "paid_cat_cents": 0,
        "paid_to_date_cents": 0,
        "balance_billed_total_cents": 0,
        "family_responsibility_total_cents": 0,
        "cat_certification_status": "NONE",
        "cat_certified_at": None,
        "cat_certified_by_user_id": None,
        "cat_certification_note": None,
        "cat_revocation_reason": None,
        "adjudicated_at": None,
        "adjudicated_by_user_id": None,
        "denial_reason": None,
        "withdrawal_reason": None,
    })


def reserve_from_report(claim):
    """Re-strike the reserve when the originating report's severity_tier changes."""
    report = db.get("injury_reports", claim["injury_report_id"])
    policy = db.get("league_policies", claim["league_policy_id"])
    touch(claim, reserve_amount_cents=reserve_amount_for(policy, report["severity_tier"]))
