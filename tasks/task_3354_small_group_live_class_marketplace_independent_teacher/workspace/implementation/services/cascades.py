"""Cascading side effects: suspension, refund clawback and the risk cascade."""

from core import clock, constants as C, store
from core.errors import fail

from . import calc


# ---------------------------------------------------------------------------
# Enrollment refund resolution
# ---------------------------------------------------------------------------
def write_refund(enrollment, learner, tier, cancelled_by):
    refund = calc.refund_cents_for(tier, enrollment["discounted_price_cents"])
    enrollment["refund_category"] = tier
    enrollment["refund_cents"] = refund
    applied = min(refund, learner["confirmation_credit_cents"]) if learner else 0
    enrollment["credit_applied_cents"] = applied
    enrollment["cash_refund_cents"] = refund - applied
    enrollment["cancelled_by"] = cancelled_by
    store.touch(enrollment)


# ---------------------------------------------------------------------------
# Section / listing suspension cascade
# ---------------------------------------------------------------------------
def cancel_section_and_enrollments(section, outcome, cancelled_by, enroll_status,
                                   refund_tier_name):
    """Cancel a section and resolve every live enrollment of it."""
    listing = calc.listing_of_section(section)
    if section["outcome"] is None:
        section["outcome"] = outcome
    section["status"] = "CANCELLED"
    store.touch(section)
    for enrollment in calc.enrollments_of_section(section["id"]):
        if enrollment["status"] not in ("RESERVED", "CONFIRMED"):
            continue
        learner = store.find("learners", enrollment["learner_id"])
        enrollment["status"] = enroll_status
        write_refund(enrollment, learner, refund_tier_name, cancelled_by)
    return listing


def suspension_cascade(teacher):
    """Listings -> SUSPENDED; their SCHEDULED/OPEN sections -> CANCELLED."""
    for listing in store.all_of("listings"):
        if listing["teacher_id"] != teacher["id"]:
            continue
        if listing["lifecycle_state"] == "PUBLISHED":
            listing["lifecycle_state"] = "SUSPENDED"
            store.touch(listing)
    for section in store.all_of("sections"):
        listing = calc.listing_of_section(section)
        if listing is None or listing["teacher_id"] != teacher["id"]:
            continue
        if section["status"] in ("SCHEDULED", "OPEN_FOR_ENROLLMENT", "MIN_ENROLLMENT_MET"):
            cancel_section_and_enrollments(
                section, "CANCELLED_BY_TEACHER", "platform", "CANCELLED_BY_TEACHER", "FULL"
            )


def archive_listing_sections(listing):
    for section in store.all_of("sections"):
        if section["class_listing_id"] != listing["id"]:
            continue
        if section["status"] in ("SCHEDULED", "OPEN_FOR_ENROLLMENT", "MIN_ENROLLMENT_MET"):
            cancel_section_and_enrollments(
                section, "CANCELLED_BY_TEACHER", "platform", "CANCELLED_BY_TEACHER", "FULL"
            )


# ---------------------------------------------------------------------------
# Teacher-fault refund clawback (HOP 1 -> HOP 2 -> HOP 3)
# ---------------------------------------------------------------------------
def teacher_fault_clawback(teacher, refunded_sections):
    """`refunded_sections` is a list of (section, original_discounted_total_cents)."""
    if not refunded_sections:
        return []
    touched_payouts = []
    for payout in store.all_of("payouts"):
        if payout["teacher_id"] != teacher["id"]:
            continue
        if payout["status"] != "REQUESTED":
            continue
        covers = False
        for section, _total in refunded_sections:
            start = section["start_utc_dt"]
            if payout["period_start_dt"] <= start < payout["period_end_dt"]:
                covers = True
                break
        if not covers:
            continue
        # The rate actually charged on this settlement, captured before the recompute and
        # then held fixed. Re-banding the smaller post-refund gross would change the fee on
        # sections that were not refunded, so the teacher's lifetime earnings would move for
        # a reason unrelated to the refund and the compensating pair would no longer leave
        # (refund - reversed fee) equal to the refunded section's net.
        original_rate = payout["fee_rate_applied"]
        remaining = calc.accrual_sections(
            teacher["id"], payout["period_start_dt"], payout["period_end_dt"]
        )
        gross = sum(calc.section_discounted_total(s["id"]) for s in remaining)
        fee = sum(
            calc.floor_cents(calc.section_discounted_total(s["id"]) * original_rate)
            for s in remaining
        )
        figures = {
            "gross_earnings_cents": gross,
            "platform_fee_cents": fee,
            "net_payout_cents": gross - fee,
        }
        rate = original_rate
        reversed_total = 0
        liability = 0
        for _section, total in refunded_sections:
            fee_on_section = calc.floor_cents(total * original_rate)
            reversed_total += fee_on_section
            liability += calc.floor_cents(
                (total - fee_on_section) * C.REFUND_TEACHER_LIABILITY_RATE
            )
        payout["gross_earnings_cents"] = figures["gross_earnings_cents"]
        payout["fee_rate_applied"] = rate
        payout["platform_fee_cents"] = figures["platform_fee_cents"]
        payout["net_payout_cents"] = figures["net_payout_cents"]
        payout["platform_fee_reversed_cents"] = reversed_total
        payout["teacher_liability_cents"] = liability
        payout["net_after_refunds_cents"] = (
            figures["gross_earnings_cents"] - figures["platform_fee_cents"] - reversed_total
        )
        payout["refund_period_index"] = clock.period()
        payout["status"] = "FAILED"
        payout["approval_status"] = "pending_approval"
        store.touch(payout)
        touched_payouts.append(payout)
    # HOP 2 / HOP 3 roll-ups: the teacher's lifetime aggregates are re-derived
    # from the payout rows, so the refund moves fee-reversed, liability,
    # unpaid earnings and the tax-document standing in one step.
    store.touch(teacher)
    return touched_payouts


# ---------------------------------------------------------------------------
# Risk cascade
# ---------------------------------------------------------------------------
def apply_risk_cascade(teacher):
    scores = calc.risk_scores(teacher["id"])
    if scores["actionable_risk_score"] > teacher["peak_actionable_risk_score"]:
        teacher["peak_actionable_risk_score"] = scores["actionable_risk_score"]
    store.touch(teacher)
    if (
        teacher["status"] == "ACTIVE"
        and scores["actionable_risk_score"] >= C.RISK_SUSPENSION_THRESHOLD
    ):
        teacher["status"] = "SUSPENDED"
        teacher["suspension_reason"] = "automatic policy suspension"
        teacher["suspension_trigger"] = "POLICY"
        store.touch(teacher)
        suspension_cascade(teacher)


def require_active_teacher(teacher, role):
    """Ladder 34 — the owning teacher must be ACTIVE unless PlatformAdmin acts."""
    if role == "PlatformAdmin":
        return
    if teacher is None or teacher["status"] != "ACTIVE":
        fail("ERR_TEACHER_NOT_ACTIVE", "The owning teacher is not ACTIVE")
