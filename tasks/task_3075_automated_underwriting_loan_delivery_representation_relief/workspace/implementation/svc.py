"""Business services: calculations, state-machine cascades, shared logic."""
from datetime import timedelta

from core import (
    ApiError,
    db,
    new_row,
    now,
    rhu_int,
    touch,
)

# ---------------------------------------------------------------------------
# Constants (PRD sections 2.4, 3.4, 3.6, 3.8)
# ---------------------------------------------------------------------------
MIN_NET_WORTH_CENTS = 2500000
MAX_QC_DEFECT_BPS = 150
MAX_LTV_BP = 9500
MIN_CREDIT_SCORE = 620
REFER_CREDIT_SCORE_LT = 680
REFER_LTV_BP_GT = 9000
PAYMENT_HISTORY_MILESTONE = 36
APPEAL_WINDOW_DAYS = 30
MIN_OVERSIGHT_SCORE_FOR_TRANSFER = 60
PENDING_ISSUE_PENALTY = 5
FINDING_PENALTY = 2

MISREP_CATEGORIES = ("INCOME_MISREP", "ASSET_MISREP", "EMPLOYMENT_MISREP")
SERVICE_TYPES = ("INCOME", "ASSET", "EMPLOYMENT")


# ---------------------------------------------------------------------------
# Time-dependent transitions (logical clock)
# ---------------------------------------------------------------------------
def advance_dependent_transitions():
    """Re-evaluate time-gated transitions after a clock set (PRD 2.6)."""
    ts = now()
    for agreement in db.agreements.values():
        if agreement["status"] == "ACTIVE" and ts >= agreement["expiration_date"]:
            agreement["status"] = "EXPIRED"
            touch(agreement)
    for transfer in db.transfers.values():
        if transfer["status"] == "APPROVED" and ts >= transfer["effective_date"]:
            loan = db.loans.get(transfer["loan_id"])
            if loan is not None and loan["status"] == "REPURCHASED":
                transfer["status"] = "CANCELLED"
                touch(transfer)
            else:
                transfer["status"] = "COMPLETED"
                touch(transfer)
                if loan is not None:
                    loan["servicer_id"] = transfer["to_servicer_id"]
                    touch(loan)


def recompute_all_oversight_scores():
    for servicer in db.servicers.values():
        recompute_oversight_score(servicer)


# ---------------------------------------------------------------------------
# Oversight score (PRD 3.8)
# ---------------------------------------------------------------------------
def recompute_oversight_score(servicer):
    pending_issues = 0
    for demand in db.demands.values():
        if demand["status"] not in ("ISSUED", "APPEALED"):
            continue
        loan = db.loans.get(demand["loan_id"])
        if loan is not None and loan["servicer_id"] == servicer["id"]:
            pending_issues += 1
    oversight_findings = 0
    for record in db.oversight.values():
        if record["servicer_id"] == servicer["id"] and record["status"] == "OPEN":
            oversight_findings += int(record.get("findings_count") or 0)
    score = 100 - PENDING_ISSUE_PENALTY * pending_issues - FINDING_PENALTY * oversight_findings
    score = max(0, min(100, score))
    if servicer.get("oversight_score") != score:
        servicer["oversight_score"] = score
        touch(servicer)
    return score


def recompute_all_scores():
    for servicer in db.servicers.values():
        recompute_oversight_score(servicer)


# ---------------------------------------------------------------------------
# Pricing (PRD 2.10, 3.5, 3.7)
# ---------------------------------------------------------------------------
def active_matrix():
    for matrix in db.matrices.values():
        if matrix["status"] == "ACTIVE":
            return matrix
    return None


def match_pricing_row(loan, matrix):
    """Return the single row matching this loan, or None."""
    if matrix is None:
        return None
    match = None
    for row in matrix.get("rows") or []:
        if row.get("occupancy") != loan["occupancy"]:
            continue
        if row.get("product_type") != loan["product_type"]:
            continue
        if not (int(row.get("ltv_min_bp", 0)) < int(loan["ltv_bp"]) <= int(row.get("ltv_max_bp", 0))):
            continue
        if not (int(row.get("credit_min", 0)) <= int(loan["credit_score"]) <= int(row.get("credit_max", 0))):
            continue
        if match is not None:
            return None  # ambiguous: more than one row matches
        match = row
    return match


def provisional_price(loan, matrix):
    """Provisional price under the given grid; 0 when no row matches."""
    row = match_pricing_row(loan, matrix)
    if row is None:
        return 0
    adjustment = rhu_int(loan["unpaid_principal_balance_cents"] * int(row["llpa_bps"]) / 10000)
    return int(loan["unpaid_principal_balance_cents"]) - adjustment


def pipeline_value(seller_id, matrix):
    total = 0
    for loan in db.loans.values():
        if loan["seller_id"] != seller_id:
            continue
        if loan["status"] not in ("DRAFT", "UNDERWRITTEN"):
            continue
        total += provisional_price(loan, matrix)
    return total


def revalue_pipeline(seller_id):
    """Refresh the projected value of the seller's pipeline, if one exists."""
    pipeline = find_pipeline(seller_id)
    if pipeline is None:
        return None
    new_value = pipeline_value(seller_id, active_matrix())
    if pipeline.get("projected_value_cents") != new_value:
        pipeline["projected_value_cents"] = new_value
        touch(pipeline)
    return pipeline


def find_pipeline(seller_id):
    for pipeline in db.pipelines.values():
        if pipeline["seller_id"] == seller_id:
            return pipeline
    return None


def on_matrix_swap(old_matrix, new_matrix):
    """Grid swap: revalue every pipeline and record an update event per pipeline."""
    for pipeline in db.pipelines.values():
        before = pipeline_value(pipeline["seller_id"], old_matrix)
        after = pipeline_value(pipeline["seller_id"], new_matrix)
        impacted = 0
        for loan in db.loans.values():
            if loan["seller_id"] != pipeline["seller_id"]:
                continue
            if loan["status"] not in ("DRAFT", "UNDERWRITTEN"):
                continue
            if provisional_price(loan, old_matrix) != provisional_price(loan, new_matrix):
                impacted += 1
        pipeline["projected_value_cents"] = after
        touch(pipeline)
        event = new_row(
            "llpa_update_event",
            audited=False,
            pipeline_id=pipeline["id"],
            old_matrix_id=old_matrix["id"] if old_matrix else None,
            new_matrix_id=new_matrix["id"],
            projected_value_before_cents=before,
            projected_value_after_cents=after,
            delta_cents=after - before,
            impacted_loan_count=impacted,
        )
        db.update_events[event["id"]] = event


# ---------------------------------------------------------------------------
# Relief tier (PRD 3.6)
# ---------------------------------------------------------------------------
def recompute_relief_tier(loan):
    if loan["independent_validation_complete"]:
        raw = "INDEPENDENT_VALIDATION"
    elif int(loan["consecutive_on_time_payments"]) >= PAYMENT_HISTORY_MILESTONE:
        raw = "PAYMENT_HISTORY_36"
    else:
        raw = "NONE"
    seller = db.sellers.get(loan["seller_id"])
    if seller is not None and seller.get("probation_relief_enabled"):
        if raw == "INDEPENDENT_VALIDATION":
            raw = "PAYMENT_HISTORY_36"
    if loan.get("relief_tier") != raw:
        loan["relief_tier"] = raw
        touch(loan)
    return raw


# ---------------------------------------------------------------------------
# Pool balance conservation (PRD 2.11)
# ---------------------------------------------------------------------------
def recompute_pool_balance(pool):
    balance = 0
    count = 0
    for loan in db.loans.values():
        if loan.get("pool_id") == pool["id"] and loan["status"] == "DELIVERED":
            balance += int(loan["unpaid_principal_balance_cents"])
            count += 1
    changed = (
        pool.get("current_balance_cents") != balance
        or pool.get("loan_count") != count
    )
    pool["current_balance_cents"] = balance
    pool["loan_count"] = count
    if changed:
        touch(pool)


# ---------------------------------------------------------------------------
# Underwriting cascades (PRD 3.4)
# ---------------------------------------------------------------------------
def case_reports_for_round(case, round_number):
    return [
        r for r in db.reports.values()
        if r["case_id"] == case["id"] and r["round"] == round_number
    ]


def maybe_transition_case(case):
    """Auto transitions on report outcomes (PRD 3.4)."""
    if case["case_status"] != "VALIDATING":
        return
    reports = case_reports_for_round(case, case["submission_round"])
    if any(r["result"] == "NOT_VALIDATED" for r in reports):
        case["case_status"] = "FAILED"
        case["submission_round"] += 1
        touch(case)
        return
    validated_types = {r["service_type"] for r in reports if r["result"] == "VALIDATED"}
    if all(t in validated_types for t in SERVICE_TYPES):
        case["case_status"] = "VALIDATED"
        touch(case)


def finalize_case(case):
    """Eligibility computation + loan cascade (PRD 3.4)."""
    loan = db.loans.get(case["loan_id"])
    eligible = (
        int(loan["ltv_bp"]) <= MAX_LTV_BP
        and int(loan["credit_score"]) >= MIN_CREDIT_SCORE
        and loan["occupancy"] in ("PRIMARY_RESIDENCE", "SECOND_HOME", "INVESTMENT")
        and loan["product_type"] in ("FIXED_30", "FIXED_15", "ARM_5_1")
    )
    if not eligible:
        case["final_outcome"] = "FAIL"
        case["case_status"] = "FINALIZED"
        touch(case)
        loan["status"] = "REJECTED"
        loan["au_status"] = "INELIGIBLE"
        touch(loan)
        revalue_pipeline(loan["seller_id"])
        return
    case["final_outcome"] = "PASS"
    if int(loan["credit_score"]) < REFER_CREDIT_SCORE_LT or int(loan["ltv_bp"]) > REFER_LTV_BP_GT:
        case["recommendation"] = "REFER_WITH_CAUTION"
        case["case_status"] = "FINALIZED"
        touch(case)
        loan["au_status"] = "RECOMMEND_REFER"
        loan["independent_validation_complete"] = True
        touch(loan)
        recompute_relief_tier(loan)
        revalue_pipeline(loan["seller_id"])
        return
    case["recommendation"] = "APPROVE_ELIGIBLE"
    case["case_status"] = "FINALIZED"
    touch(case)
    loan["status"] = "UNDERWRITTEN"
    loan["au_status"] = "RECOMMEND_APPROVE"
    loan["independent_validation_complete"] = True
    touch(loan)
    recompute_relief_tier(loan)
    revalue_pipeline(loan["seller_id"])


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
def appeal_deadline_from(issued_at):
    return issued_at + timedelta(days=APPEAL_WINDOW_DAYS)


def assert_seller_officer_owns(seller_id):
    """Entity-backed ownership: SellerOfficer's X-User-ID must be the seller id."""
    from flask import g
    if g.role == "SellerOfficer" and g.user_id != seller_id:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE", "SellerOfficer may only act on their own seller's resources.")
