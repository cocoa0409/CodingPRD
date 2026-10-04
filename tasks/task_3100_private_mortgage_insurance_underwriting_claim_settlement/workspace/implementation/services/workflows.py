"""Business workflows.

Each function implements one declared operation from SCAFFOLD section 1.5 /
PRD section 4, in the rejection precedence declared by PRD 2.12 (which follows
the priority numbering of SCAFFOLD section 1.4).
"""

from common import (
    clock_dt,
    d,
    days,
    fifth_of_month,
    floor_int,
    fmt_utc,
    months_between,
    now_iso,
    parse_utc,
    round4,
)
from db import db, new_row, touch
from errors import (
    ApiError,
    ERR_CANCELLATION_NOT_PERMITTED,
    ERR_CLAIM_BLOCKED_LOSS_MITIGATION,
    ERR_CLAIM_TIME_BARRED,
    ERR_COVERAGE_NOT_ACTIVE,
    ERR_CURTAILMENT_DISPUTE_OPEN,
    ERR_DISPUTE_DECISION_INVALID,
    ERR_DUPLICATE_OPEN_DISPUTE,
    ERR_DUPLICATE_PERIOD,
    ERR_INSUFFICIENT_EVIDENCE,
    ERR_INVALID_STATE_TRANSITION,
    ERR_LENDER_EXPOSURE_CAP_EXCEEDED,
    ERR_MILESTONE_NOT_REACHED,
    ERR_RATE_CARD_MISMATCH,
    ERR_RATE_CARD_NOT_ELIGIBLE,
    ERR_RESCISSION_BARRED_RELIEF_ATTACHED,
    ERR_SERVICER_INACTIVE,
    ERR_SERVICER_NOT_DESIGNATED,
    ERR_SETTLEMENT_OPTION_UNKNOWN,
    ERR_STALE_VERSION,
    ERR_THIRD_PARTY_SALE_INSUFFICIENT,
    ERR_TREATY_CAP_EXHAUSTED,
    ERR_TREATY_NOT_IN_FORCE,
    ERR_UNDERWRITING_DECLINED,
    ERR_WAIVER_NOT_AVAILABLE,
)
from services import coverage_rules as cov
from services.claim_arithmetic import (
    SETTLEMENT_OPTION_KINDS,
    compute_claim_arithmetic,
    compute_settlement_amounts,
    curtailment_rate_for,
    deductible_rate_for,
    net_proceeds_of,
    third_party_sale_threshold,
)
from services.pricing import (
    ALLOWED_COVERAGE_PERCENTS,
    compute_borrower_monthly_premium,
    compute_single_premium,
    coverage_base_cents,
    effective_coverage_percent,
    grade_worse_than_card,
    loan_to_value,
)
from services.reinsurance import (
    WARN_THRESHOLD_PCT,
    allocate_cession,
    compute_snapshot,
    lender_contribution,
    treaty_in_force_at,
    used_pct,
)
from services.views import (
    claim_options,
    creation_order,
    get_claim,
    get_master_policy,
    get_rate_card,
    loan_cancellation_notices,
    loan_delinquency_reports,
)

MIN_COVERAGE_PERCENT = min(ALLOWED_COVERAGE_PERCENTS)


# =============================================================================
# Coverage application approval
# =============================================================================

def _check_rate_card(application, card):
    """PRD 2.11: the card must belong to the application's master policy, and it
    must actually price the application - coverage percentage and premium plan."""
    if card["master_policy_id"] != application["master_policy_id"]:
        raise ApiError(
            ERR_RATE_CARD_MISMATCH,
            "The pinned rate card does not belong to the application's master policy.",
        )
    if card["coverage_percent"] != application["coverage_percent"]:
        raise ApiError(
            ERR_RATE_CARD_NOT_ELIGIBLE,
            "The pinned rate card does not price the application's coverage percentage.",
        )
    if card["premium_plan"] != application["premium_plan"]:
        raise ApiError(
            ERR_RATE_CARD_NOT_ELIGIBLE,
            "The pinned rate card does not price the application's premium plan.",
        )


def _check_underwriting_decline(application):
    """PRD 3.1 / 3.2: a ratio above 95.0000 has no band, and a requested coverage
    percentage outside the permitted set, both decline rather than approve."""
    ltv = loan_to_value(application["loan_amount_cents"], application["property_value_cents"])
    if ltv is None or ltv > 95.0:
        raise ApiError(
            ERR_UNDERWRITING_DECLINED,
            "The loan-to-value ratio exceeds 95.0 percent.",
        )
    if application["coverage_percent"] not in ALLOWED_COVERAGE_PERCENTS:
        raise ApiError(
            ERR_UNDERWRITING_DECLINED,
            "The requested coverage percentage is outside the master policy's allowed set.",
        )


def _pin_approval(application, approved_percent, card):
    plan_rate = card["rate_bps"]
    rate_bps = plan_rate if application["borrower_paid"] else 0
    application["approved_coverage_percent"] = approved_percent
    application["rate_bps_applied"] = rate_bps
    application["coverage_base_upb_cents"] = coverage_base_cents(
        application["loan_amount_cents"], approved_percent
    )
    application["underwritten_utc"] = now_iso()
    application["status"] = "APPROVED"
    touch(application)


def approve_non_delegated(application):
    """POST /coverage-applications/{id}/approve (Underwriter)."""
    card = get_rate_card(application["rate_card_id"])
    _check_rate_card(application, card)
    _check_underwriting_decline(application)

    grade_worse = grade_worse_than_card(application["credit_grade"], card["credit_grade"])
    reserves_short = application["borrower_reserves_months"] < card["min_borrower_reserves_months"]
    approved = effective_coverage_percent(
        application,
        card,
        grade_worse,
        reserves_short,
        MIN_COVERAGE_PERCENT,
        application["coverage_percent"],
    )

    application["underwriting_path"] = "NON_DELEGATED"
    _pin_approval(application, approved, card)
    return application


def approve_delegated(application):
    """POST /coverage-applications/{id}/delegated-approve (Lender)."""
    card = get_rate_card(application["rate_card_id"])
    _check_rate_card(application, card)
    _check_underwriting_decline(application)

    application["underwriting_path"] = "DELEGATED"
    # The requested coverage percentage is taken without any step-down.
    _pin_approval(application, application["coverage_percent"], card)
    return application


# =============================================================================
# Loan issuance
# =============================================================================

def issue_loan(application, servicer, treaty):
    """POST /loans (MasterPolicyAdmin). PRD 3.3."""
    loan = new_row()
    loan_amount = application["loan_amount_cents"]
    coverage_percent = application["approved_coverage_percent"]
    current_coverage_base = coverage_base_cents(loan_amount, coverage_percent)

    annual, monthly, final = compute_borrower_monthly_premium(
        application["coverage_base_upb_cents"], application["rate_bps_applied"]
    )
    if application["premium_plan"] == "SPM" and application["borrower_paid"]:
        single = compute_single_premium(
            application["coverage_base_upb_cents"],
            application["rate_bps_applied"],
            application["financed_premium"],
        )
    else:
        single = 0

    loan.update({
        "application_id": application["id"],
        "servicer_id": servicer["id"],
        "reinsurance_treaty_id": treaty["id"] if treaty is not None else None,
        "lender_id": application["lender_id"],
        "master_policy_id": application["master_policy_id"],
        "coverage_percent": coverage_percent,
        "premium_plan": application["premium_plan"],
        "borrower_paid": application["borrower_paid"],
        "underwriting_path": application["underwriting_path"],
        "rate_bps_applied": application["rate_bps_applied"],
        "coverage_base_upb_cents": application["coverage_base_upb_cents"],
        "current_upb_cents": loan_amount,
        "current_coverage_base_cents": current_coverage_base,
        "annual_premium_cents": annual,
        "monthly_period_cents": monthly,
        "final_period_cents": final,
        "single_premium_cents": single,
        "origination_property_value_cents": application["property_value_cents"],
        "verified_property_value_cents": None,
        "verified_loan_amount_cents": None,
        "credit_grade": application["credit_grade"],
        "county_code": application["county_code"],
        "term_months": application["term_months"],
        "approval_credit_grade": application["credit_grade"],
        "coverage_status": "ACTIVE",
        "termination_reason": "NONE",
        "cancellation_effective_utc": None,
        "amortization_status": "IN_AMORTIZATION",
        "milestone_78_reached_utc": None,
        "delinquency_streak": 0,
        "last_loss_mitigation_deficient_utc": None,
        "rescission_relief_status": "NONE",
        "rescission_relief_cycle_index": 0,
        "claim_blocked": False,
        "aggregate_ceded_cents": 0,
        # Not serialized: the note amount as reported at origination, used by the
        # independent-validation variance comparison (PRD 3.6).
        "_origination_loan_amount_cents": loan_amount,
    })
    db.loans[loan["id"]] = loan
    return loan


# =============================================================================
# Amortization milestones (PRD 3.5)
# =============================================================================

def record_amortization_milestone(loan, current_upb_cents):
    if current_upb_cents <= 0:
        raise ApiError(ERR_MILESTONE_NOT_REACHED, "The submitted balance is not a valid amount.")

    origination_value = loan["origination_property_value_cents"]
    eighty = floor_int(d(origination_value) * d("0.80"))
    if current_upb_cents > eighty:
        raise ApiError(
            ERR_MILESTONE_NOT_REACHED,
            "The loan's current balance still exceeds the eighty percent milestone.",
        )

    loan["current_upb_cents"] = current_upb_cents
    loan["current_coverage_base_cents"] = coverage_base_cents(
        current_upb_cents, loan["coverage_percent"]
    )

    seventy_eight = floor_int(d(origination_value) * d("0.78"))
    if current_upb_cents <= seventy_eight:
        reached = "AT_78"
    else:
        reached = "AT_80"

    # The axis is monotonic and never regresses.
    if loan["amortization_status"] != "AT_78":
        loan["amortization_status"] = reached

    if loan["amortization_status"] == "AT_78" and loan["milestone_78_reached_utc"] is None:
        loan["milestone_78_reached_utc"] = now_iso()

    # The premium schedule is recomputed whenever a milestone is recorded.
    annual, monthly, final = compute_borrower_monthly_premium(
        loan["coverage_base_upb_cents"], loan["rate_bps_applied"]
    )
    loan["annual_premium_cents"] = annual
    loan["monthly_period_cents"] = monthly
    loan["final_period_cents"] = final

    notices = loan_cancellation_notices(loan["id"])
    # One recording is one mutation of the loan row: the automatic termination
    # it may trigger sets the fields in place rather than mutating again.
    if _auto_transition_on_milestone(loan, notices):
        pass
    touch(loan)
    return loan


def _auto_transition_on_milestone(loan, notices):
    """Skipped when a cancellation is already pending (PRD 3.5)."""
    if loan["coverage_status"] != "ACTIVE":
        return False
    if loan["amortization_status"] != "AT_78":
        return False
    seventy_eight = floor_int(d(loan["origination_property_value_cents"]) * d("0.78"))
    if loan["current_upb_cents"] > seventy_eight:
        return False

    milestone_reached = parse_utc(loan["milestone_78_reached_utc"])
    effective = max(clock_dt(), milestone_reached + days(cov.MILESTONE_MIN_DAYS))
    loan["coverage_status"] = "PENDING_CANCELLATION"
    loan["termination_reason"] = "LTV_MILESTONE"
    loan["cancellation_effective_utc"] = fmt_utc(effective)
    return True


# =============================================================================
# Cancellation notices (PRD 3.6)
# =============================================================================

def file_cancellation_notice(loan, request_kind, requested_by_role, notice_utc,
                             applied_utc, evidence_cents):
    """The declared transition runs from ACTIVE only (SCAFFOLD Loan machine), so
    the state check precedes the admissibility rules (PRD 2.12)."""
    if loan["coverage_status"] != "ACTIVE":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "A cancellation notice is only declared from an ACTIVE coverage axis.",
        )

    if request_kind == "SERVICER_LOSS_MITIGATION_FAILURE" and not loan["claim_blocked"]:
        raise ApiError(
            ERR_CANCELLATION_NOT_PERMITTED,
            "A servicer loss-mitigation cancellation requires the loan's claim_blocked flag.",
        )

    maximum = cov.max_refund_cents(loan)
    if maximum <= 0:
        raise ApiError(
            ERR_CANCELLATION_NOT_PERMITTED,
            "A cancellation ground with a zero maximum refund is not admissible.",
        )
    if evidence_cents < maximum:
        raise ApiError(
            ERR_INSUFFICIENT_EVIDENCE,
            "The supplied evidence amount is below the computed maximum refund.",
        )

    refund = max(0, min(evidence_cents, maximum))
    effective = cov.effective_instant(applied_utc, notice_utc)

    notice = new_row()
    notice.update({
        "loan_id": loan["id"],
        "request_kind": request_kind,
        "requested_by_role": requested_by_role,
        "notice_utc": fmt_utc(parse_utc(notice_utc)),
        "evidence_cents": evidence_cents,
        "applied_utc": fmt_utc(parse_utc(applied_utc)),
        "refund_cents": refund,
        "effective_utc": fmt_utc(effective),
        "status": "APPLIED",
    })
    db.cancellation_notices[notice["id"]] = notice

    loan["coverage_status"] = "PENDING_CANCELLATION"
    loan["termination_reason"] = "BORROWER_REQUEST"
    loan["cancellation_effective_utc"] = fmt_utc(effective)
    touch(loan)
    return notice


# =============================================================================
# Rescission relief / loss-mitigation waiver (PRD 3.6)
# =============================================================================

def record_rescission_relief(loan, relief_status, waiver_evidence_code):
    policy = get_master_policy(loan["master_policy_id"])

    if relief_status == "ATTACHED":
        loan["rescission_relief_status"] = "GUARANTEED"
        touch(loan)
        return loan

    # REVOKED is the loss-mitigation waiver, and it is also the operation that
    # revokes a pending termination (PRD 3.5 / 3.6).
    standard_ok = policy["servicer_loss_mitigation_standard"] == "PARTICIPATION"
    code_ok = bool(waiver_evidence_code) and isinstance(waiver_evidence_code, str)
    if not (standard_ok and code_ok):
        raise ApiError(
            ERR_WAIVER_NOT_AVAILABLE,
            "The loss-mitigation waiver requires a PARTICIPATION standard and an "
            "attached evidence code.",
        )

    loan["claim_blocked"] = False
    # Clearing the claim_blocked flag while a servicer-loss-mitigation
    # cancellation is pending revokes that pending termination too.
    if (loan["coverage_status"] == "PENDING_CANCELLATION"
            and loan["termination_reason"] == "SERVICER_LOSS_MITIGATION_FAILURE"):
        loan["coverage_status"] = "ACTIVE"
        loan["termination_reason"] = "NONE"
        loan["cancellation_effective_utc"] = None
    touch(loan)
    return loan


# =============================================================================
# Independent validation reports (PRD 3.6)
# =============================================================================

def file_external_report(loan, payload, verified_loan_amount_cents,
                         verified_property_value_cents, post_origination_value_cents,
                         occupancy_reported, completed_dt):
    policy = get_master_policy(loan["master_policy_id"])

    validated_ltv = round4(
        d(verified_loan_amount_cents) * 100 / d(verified_property_value_cents)
    )
    occupancy_materially_differs = occupancy_reported == "INVESTMENT"

    report = new_row()
    report.update({
        "loan_id": loan["id"],
        "verified_loan_amount_cents": verified_loan_amount_cents,
        "verified_property_value_cents": verified_property_value_cents,
        "post_origination_value_cents": post_origination_value_cents,
        "occupancy_reported": occupancy_reported,
        "independent_validation_completed_utc": fmt_utc(completed_dt),
        "validated_ltv": validated_ltv,
        "occupancy_materially_differs": occupancy_materially_differs,
    })
    db.external_reports[report["id"]] = report

    loan["verified_property_value_cents"] = verified_property_value_cents
    loan["verified_loan_amount_cents"] = verified_loan_amount_cents

    # --- the rescission review ------------------------------------------------
    original_ltv = (
        d(loan["_origination_loan_amount_cents"]) * 100
        / d(loan["origination_property_value_cents"])
    )
    ltv_variance_fraction = (d(validated_ltv) - original_ltv) / original_ltv
    variance_exceeds_tolerance = ltv_variance_fraction > d(policy["ltv_variance_tolerance"])
    value_reset_pathway_present = (
        post_origination_value_cents > loan["origination_property_value_cents"]
    )
    rescission_persists = (not variance_exceeds_tolerance) and not (
        occupancy_materially_differs and value_reset_pathway_present
    )
    report["_rescission_review"] = (
        "PERSISTS" if rescission_persists else "PERMITTED_RESCISSION"
    )

    # The relief standing is recomputed alongside the review.
    cov.recompute_loan_relief(loan, loan_delinquency_reports(loan["id"]), policy)
    touch(loan)
    return report


# =============================================================================
# Delinquency reports (PRD 3.4)
# =============================================================================

def file_delinquency_report(loan, servicer, as_of_period, delinquency_class,
                            months_delinquent, activities):
    existing = loan_delinquency_reports(loan["id"])
    for report in existing:
        if report["as_of_period"] == as_of_period:
            raise ApiError(
                ERR_DUPLICATE_PERIOD,
                "A delinquency report already exists for this loan and period.",
            )

    if servicer["status"] != "ACTIVE":
        raise ApiError(ERR_SERVICER_INACTIVE, "The reporting servicer is not ACTIVE.")

    if loan["servicer_id"] != servicer["id"]:
        raise ApiError(
            ERR_SERVICER_NOT_DESIGNATED,
            "The reporting servicer is not the loan's designated servicer.",
        )

    policy = get_master_policy(loan["master_policy_id"])
    effective = fifth_of_month(as_of_period)

    report = new_row()
    report.update({
        "loan_id": loan["id"],
        "servicer_id": servicer["id"],
        "as_of_period": as_of_period,
        "delinquency_class": delinquency_class,
        "months_delinquent": months_delinquent,
        "loss_mitigation_activities": activities,
        "reported_utc": now_iso(),
        "effective_utc": fmt_utc(effective),
        "participation_standard_met": cov.participation_standard_met(
            {"loss_mitigation_activities": activities}, policy, servicer
        ),
        "status": "FILED",
    })
    db.delinquency_reports[report["id"]] = report

    if delinquency_class == "A" and report["participation_standard_met"] is False:
        loan["claim_blocked"] = True
        loan["last_loss_mitigation_deficient_utc"] = report["effective_utc"]

    reports = loan_delinquency_reports(loan["id"])
    loan["delinquency_streak"] = cov.delinquency_streak(loan, reports)
    cov.recompute_loan_relief(loan, reports, policy)

    # One recording is one mutation of the loan row: the recomputations above and
    # the automatic termination they may trigger share a single version bump.
    _auto_transition_on_delinquency(loan, policy)
    touch(loan)
    return report


def _auto_transition_on_delinquency(loan, policy):
    """PRD 3.5: when the streak reaches three or more and claim_blocked is true,
    and no cancellation is already pending."""
    if loan["coverage_status"] != "ACTIVE":
        return False
    if not loan["claim_blocked"] or loan["delinquency_streak"] < 3:
        return False
    deficient = loan.get("last_loss_mitigation_deficient_utc")
    if not deficient:
        return False

    effective = parse_utc(deficient) + days(cov.DEFICIENCY_MIN_DAYS)
    loan["coverage_status"] = "PENDING_CANCELLATION"
    loan["termination_reason"] = "SERVICER_LOSS_MITIGATION_FAILURE"
    loan["cancellation_effective_utc"] = fmt_utc(effective)

    notice = new_row()
    notice.update({
        "loan_id": loan["id"],
        "request_kind": "SERVICER_LOSS_MITIGATION_FAILURE",
        "requested_by_role": "SERVICER",
        "notice_utc": now_iso(),
        "evidence_cents": 0,
        "applied_utc": now_iso(),
        "refund_cents": 0,
        "effective_utc": fmt_utc(effective),
        "status": "APPLIED",
    })
    db.cancellation_notices[notice["id"]] = notice
    return True


# =============================================================================
# Claims (PRD 3.7 - 3.10)
# =============================================================================

def _assert_claim_time_bar(claim, loan):
    filed = parse_utc(claim["filed_utc"])
    event = parse_utc(claim["event_completed_utc"])
    elapsed = months_between(event, filed)
    if elapsed > loan["term_months"]:
        raise ApiError(
            ERR_CLAIM_TIME_BARRED,
            "The claim was filed later than the loan's term in months after the event.",
        )


def _assert_no_open_blocking_dispute(claim):
    for dispute in db.curtailment_disputes.values():
        if dispute["target_claim_id"] != claim["id"]:
            continue
        if dispute["status"] == "RESOLVED":
            continue
        if dispute["grounds"] == "LOSS_MITIGATION_EXCUSE":
            continue
        raise ApiError(
            ERR_CURTAILMENT_DISPUTE_OPEN,
            "A non-LOSS_MITIGATION_EXCUSE dispute is open against this claim.",
        )


def approve_claim(claim, loan):
    _assert_claim_time_bar(claim, loan)

    if loan["claim_blocked"]:
        raise ApiError(
            ERR_CLAIM_BLOCKED_LOSS_MITIGATION,
            "The loan's last Class-A delinquency report failed the loss-mitigation standard.",
        )

    if loan["coverage_status"] != "ACTIVE":
        raise ApiError(
            ERR_COVERAGE_NOT_ACTIVE,
            "Coverage was not in force at the claim's event instant.",
        )

    policy = get_master_policy(loan["master_policy_id"])
    claim["curtailment_rate_applied"] = curtailment_rate_for(policy, loan["underwriting_path"])

    _recompute_claim(claim, loan, policy)
    _price_settlement_options(claim, loan, policy)

    claim["status"] = "APPROVED"
    touch(claim)
    return claim


def _recompute_claim(claim, loan, policy):
    rate = claim.get("curtailment_rate_applied")
    if rate is None:
        # A claim that was never approved carries no frozen factor; derive it for
        # the comparison without freezing anything on the claim.
        rate = curtailment_rate_for(policy, loan["underwriting_path"])
    arithmetic = compute_claim_arithmetic(
        claim,
        loan,
        policy,
        rate,
        deductible_rate_for(loan["approval_credit_grade"]),
    )
    if claim.get("curtailment_rate_applied") is not None:
        claim["curtailment_rate_applied"] = rate
    for name, value in arithmetic.items():
        claim[name] = value
    claim["_arithmetic"] = arithmetic
    return arithmetic


def _price_settlement_options(claim, loan, policy):
    arithmetic = claim["_arithmetic"]
    amounts = compute_settlement_amounts(claim, loan, policy, arithmetic)
    for option in list(db.claim_settlement_options.values()):
        if option["claim_id"] == claim["id"]:
            del db.claim_settlement_options[option["id"]]
    for kind in SETTLEMENT_OPTION_KINDS:
        row = new_row()
        row.update({
            "claim_id": claim["id"],
            "option_kind": kind,
            "computed_amount_cents": amounts[kind],
        })
        db.claim_settlement_options[row["id"]] = row
    return amounts


def _settlement_option_amount(claim, loan, policy, kind):
    """Re-price at this instant: settlement recomputes the whole claim arithmetic
    against the loan and claim state as it stands now, and then sets the
    settlement amount to the recomputed figure for the selected option."""
    arithmetic = _recompute_claim(claim, loan, policy)
    amounts = compute_settlement_amounts(claim, loan, policy, arithmetic)
    return arithmetic, amounts[kind]


def settle_claim(claim, loan, settlement_option_kind, expected_claim_version,
                 expected_loan_version):
    policy = get_master_policy(loan["master_policy_id"])

    if loan["coverage_status"] == "CANCELLED":
        raise ApiError(
            ERR_COVERAGE_NOT_ACTIVE,
            "Coverage was not in force at the claim's event instant.",
        )

    _assert_no_open_blocking_dispute(claim)

    priced = {option["option_kind"] for option in claim_options(claim["id"])}
    if settlement_option_kind not in priced:
        raise ApiError(
            ERR_SETTLEMENT_OPTION_UNKNOWN,
            "The named settlement option is not one of the claim's four priced options.",
        )

    arithmetic, amount = _settlement_option_amount(claim, loan, policy, settlement_option_kind)

    if settlement_option_kind == "THIRD_PARTY_SALE":
        threshold = third_party_sale_threshold(arithmetic["net_claim_amount_cents"])
        if net_proceeds_of(claim) < threshold:
            raise ApiError(
                ERR_THIRD_PARTY_SALE_INSUFFICIENT,
                "The third-party sale net proceeds fall below eighty-five percent of "
                "the claim's net amount.",
            )

    # The optimistic-concurrency checks are evaluated last (PRD 2.12).
    if expected_claim_version is not None and expected_claim_version != claim["version"]:
        raise ApiError(ERR_STALE_VERSION, "expected_claim_version does not match the claim.")
    if expected_loan_version is not None and expected_loan_version != loan["version"]:
        raise ApiError(ERR_STALE_VERSION, "expected_loan_version does not match the loan.")

    claim["settlement_option_kind"] = settlement_option_kind
    claim["settlement_amount_cents"] = amount
    claim["status"] = "SETTLED"
    touch(claim)

    if settlement_option_kind in ("CASH", "THIRD_PARTY_SALE"):
        allocate_cession(db, claim, loan, amount, now_iso())

    touch(loan)
    return claim


def target_claim_can_be_rescinded(claim):
    return claim["status"] in ("DENIED", "SETTLED")


# =============================================================================
# Coverage disputes (PRD 3.11)
# =============================================================================

def file_dispute(loan, lender, target_claim, grounds, asserted_coverage_percent):
    for dispute in db.curtailment_disputes.values():
        if dispute["target_claim_id"] == target_claim["id"] and dispute["status"] != "RESOLVED":
            raise ApiError(
                ERR_DUPLICATE_OPEN_DISPUTE,
                "An open coverage dispute already targets this claim.",
            )

    dispute = new_row()
    dispute.update({
        "loan_id": loan["id"],
        "lender_id": lender["id"],
        "target_claim_id": target_claim["id"],
        "grounds": grounds,
        "asserted_coverage_percent": asserted_coverage_percent,
        "filed_utc": now_iso(),
        "decision": None,
        "decision_utc": None,
        "status": "OPEN",
    })
    db.curtailment_disputes[dispute["id"]] = dispute
    return dispute


def decide_dispute(dispute, decision, decision_reason):
    if decision not in ("UPHELD", "DENIED", "RESCISSION_GRANTED", "RESCISSION_DENIED"):
        raise ApiError(
            ERR_DISPUTE_DECISION_INVALID,
            "The decision value is not one of UPHELD, DENIED, RESCISSION_GRANTED, "
            "RESCISSION_DENIED.",
        )

    claim = get_claim(dispute["target_claim_id"])
    loan = db.loans.get(claim["loan_id"])

    if decision == "RESCISSION_GRANTED":
        if not target_claim_can_be_rescinded(claim):
            raise ApiError(
                ERR_INVALID_STATE_TRANSITION,
                "A RESCISSION_GRANTED decision requires the targeted claim to be DENIED "
                "or SETTLED.",
            )
        if loan is None or loan["rescission_relief_status"] != "NONE":
            raise ApiError(
                ERR_RESCISSION_BARRED_RELIEF_ATTACHED,
                "The rescission-relief guarantee has attached and bars rescission.",
            )

    policy = get_master_policy(loan["master_policy_id"]) if loan is not None else None

    if decision == "UPHELD" and loan is not None:
        # The insurer re-runs the whole claim computation and adds whatever
        # positive difference the recomputation produced, so a dispute can raise
        # a claim's figure but can never lower it.
        frozen = claim.get("net_claim_amount_cents")
        if frozen is None:
            # Nothing was frozen yet (the claim was never approved); the
            # recomputation becomes the figure, which is itself the raise.
            _recompute_claim(claim, loan, policy)
        else:
            _recompute_claim(claim, loan, policy)
            gain = max(0, claim["net_claim_amount_cents"] - frozen)
            claim["net_claim_amount_cents"] = frozen + gain
            claim["_arithmetic"]["net_claim_amount_cents"] = frozen + gain
        if claim["status"] in ("APPROVED", "SETTLED"):
            _price_settlement_options(claim, loan, policy)
        touch(claim)

    if decision == "RESCISSION_GRANTED":
        was_settled = claim["status"] == "SETTLED"
        claim["status"] = "RESCINDED"
        touch(claim)

        if was_settled:
            # Void the previously accepted cession and restore the loan's ceded
            # total exactly (settlement_reversal_invariant).
            for cession in db.reinsurance_cessions.values():
                if cession["claim_id"] != claim["id"]:
                    continue
                if cession["status"] != "ACCEPTED":
                    continue
                loan["aggregate_ceded_cents"] -= cession["ceded_amount_cents"]
                cession["status"] = "REJECTED"
                cession["rejected_reason"] = None
                touch(cession)

        loan["coverage_status"] = "CANCELLED"
        loan["termination_reason"] = "NONE"
        loan["rescission_relief_status"] = "NONE"
        loan["cancellation_effective_utc"] = None
        touch(loan)

    dispute["decision"] = decision
    dispute["decision_utc"] = now_iso()
    dispute["status"] = "RESOLVED"
    touch(dispute)
    return dispute


# =============================================================================
# Reinsurance cessions recorded directly (PRD 3.10)
# =============================================================================

def record_cession(claim, loan, ceded_amount_cents, expected_loan_version):
    treaty = None
    rejected_reason = None

    treaty_id = loan.get("reinsurance_treaty_id")
    if not treaty_id or treaty_id not in db.reinsurance_treaties:
        rejected_reason = "NO_TREATY"
    else:
        treaty = db.reinsurance_treaties[treaty_id]
        if treaty["status"] != "ACTIVE":
            rejected_reason = "TREATY_NOT_IN_FORCE_AT_EVENT"
            # Cancelling a treaty stops all further cessions against it.
            raise ApiError(
                ERR_TREATY_NOT_IN_FORCE,
                "The treaty is not ACTIVE and cannot accept further cessions.",
            )
        if not treaty_in_force_at(treaty, parse_utc(claim["event_completed_utc"])):
            rejected_reason = "TREATY_NOT_IN_FORCE_AT_EVENT"

    if rejected_reason is None:
        remaining = max(0, treaty["aggregate_ceded_cap_cents"] - loan["aggregate_ceded_cents"])
        if ceded_amount_cents > remaining:
            # A caller stating an amount is asking for that amount, so the manual
            # path is refused outright where a settlement would merely be capped.
            raise ApiError(
                ERR_TREATY_CAP_EXHAUSTED,
                "The requested ceded amount exceeds the treaty's remaining aggregate "
                "capacity.",
            )

    # Optimistic concurrency is evaluated last (PRD 2.12).
    if expected_loan_version is not None and expected_loan_version != loan["version"]:
        raise ApiError(ERR_STALE_VERSION, "expected_loan_version does not match the loan.")

    record = new_row()
    record.update({
        "claim_id": claim["id"],
        "loan_id": loan["id"],
        "treaty_id": treaty["id"] if treaty is not None else None,
    })
    if rejected_reason is not None:
        record.update({
            "ceded_amount_cents": 0,
            "retained_amount_cents": claim.get("settlement_amount_cents") or 0,
            "aggregate_ceded_after_cents": loan["aggregate_ceded_cents"],
            "status": "REJECTED",
            "rejected_reason": rejected_reason,
        })
    else:
        record.update({
            "ceded_amount_cents": ceded_amount_cents,
            "retained_amount_cents": (claim.get("settlement_amount_cents") or 0) - ceded_amount_cents,
            "aggregate_ceded_after_cents": loan["aggregate_ceded_cents"] + ceded_amount_cents,
            "status": "ACCEPTED",
            "rejected_reason": None,
        })
        loan["aggregate_ceded_cents"] = record["aggregate_ceded_after_cents"]

    db.reinsurance_cessions[record["id"]] = record
    touch(loan)
    return record


# =============================================================================
# Lender exposure reconciliation (PRD 3.12)
# =============================================================================

def reconcile_lender_exposure(lender, loan, expected_loan_version):
    contribution = lender_contribution(db, lender)
    cap = lender["policy_exposure_cap_cents"]

    if contribution > cap:
        lender["status"] = "SUSPENDED"
        touch(lender)
        raise ApiError(
            ERR_LENDER_EXPOSURE_CAP_EXCEEDED,
            "The lender's aggregate in-force contribution exceeds its exposure cap.",
        )

    utilisation = used_pct(contribution, cap)
    warn = utilisation >= WARN_THRESHOLD_PCT

    if expected_loan_version is not None and expected_loan_version != loan["version"]:
        raise ApiError(ERR_STALE_VERSION, "expected_loan_version does not match the loan.")

    loan["_reconciled_at_utc"] = now_iso()
    touch(loan)

    return {
        "lender_id": lender["id"],
        "lender_contribution_cents": contribution,
        "used_pct": utilisation,
        "warn": warn,
    }


# =============================================================================
# Portfolio snapshots (PRD 3.12)
# =============================================================================

def create_portfolio_snapshot(snapshot_utc, cluster_in_force_threshold_cents):
    computed = compute_snapshot(db, snapshot_utc, cluster_in_force_threshold_cents)

    for existing in db.portfolio_snapshots.values():
        if existing["status"] == "COMPUTED":
            existing["status"] = "SUPERSEDED"
            touch(existing)

    snapshot = new_row()
    snapshot.update({
        "snapshot_utc": fmt_utc(parse_utc(snapshot_utc)),
        "cluster_in_force_threshold_cents": cluster_in_force_threshold_cents,
        "lender_concentration_index": computed["lender_concentration_index"],
        "geography_totals": computed["geography_totals"],
        "aggregate_ceded_cents": computed["aggregate_ceded_cents"],
        "segment_statuses": computed["segment_statuses"],
        "status": "COMPUTED",
    })
    db.portfolio_snapshots[snapshot["id"]] = snapshot
    return snapshot


# =============================================================================
# Logical clock (PRD 2.5)
# =============================================================================

def advance_clock_and_fire_transitions(new_clock_iso):
    for loan in creation_order(list(db.loans.values())):
        if loan["coverage_status"] == "CANCELLED":
            continue
        notices = loan_cancellation_notices(loan["id"])
        if loan["coverage_status"] == "PENDING_CANCELLATION":
            effective = loan.get("cancellation_effective_utc")
            if effective is not None and parse_utc(effective) <= parse_utc(new_clock_iso):
                loan["coverage_status"] = "CANCELLED"
                for notice in notices:
                    if notice["status"] == "SUBMITTED":
                        notice["status"] = "APPLIED"
                        touch(notice)
                touch(loan)
        else:
            cov.apply_termination_evaluation(
                loan, notices, new_clock_iso, apply_early=False
            )