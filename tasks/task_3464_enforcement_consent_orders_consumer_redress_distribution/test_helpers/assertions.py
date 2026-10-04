"""Entity assertions and domain invariant checkers.

Every resource carries id / created_at / updated_at / version (PRD section 2.4).
Nullable system fields are checked for key presence but may hold None until
the lifecycle stage that populates them.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    RiskTier, InvestigationOrigin, InvestigationStatus, CidStatus,
    ConsentOrderStatus, CommentPeriodStatus, ComplianceReportStatus,
    PenaltySeverity, ViolationPenaltyStatus, CollectionStatus, SuspensionStatus,
    RedressFundStatus, ResidualDisposition, IdentifiedFrom, ClaimantStatus,
    ClaimStatus, RefundCheckStatus,
)

_MISSING = object()


def _assert_common(data: dict, entity_name: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_name}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity_name}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be an integer >= 1, got {data.get('version')!r}"
    )


def _assert_present(data: dict, field: str, entity_name: str):
    value = data.get(field, _MISSING)
    assert value is not _MISSING, f"{entity_name}.{field} must be present"
    return value


def _assert_optional_timestamp(data: dict, field: str, entity_name: str):
    value = _assert_present(data, field, entity_name)
    if value is not None:
        assert is_iso8601_timestamp(value), f"{entity_name}.{field} must be ISO 8601 when set"


def assert_subject_company(data: dict):
    _assert_common(data, "SubjectCompany")
    assert isinstance(_assert_present(data, "legal_name", "SubjectCompany"), str)
    count = _assert_present(data, "complaint_count_90d", "SubjectCompany")
    assert isinstance(count, int) and count >= 0
    assert data.get("risk_tier") in {t.value for t in RiskTier}


def assert_investigation(data: dict):
    _assert_common(data, "Investigation")
    assert is_valid_uuid(_assert_present(data, "subject_company_id", "Investigation"))
    assert data.get("origin") in {o.value for o in InvestigationOrigin}
    assert isinstance(_assert_present(data, "summary", "Investigation"), str)
    assert isinstance(_assert_present(data, "opened_by_user_id", "Investigation"), str)
    assert data.get("status") in {s.value for s in InvestigationStatus}


def assert_cid(data: dict):
    _assert_common(data, "CivilInvestigativeDemand")
    assert is_valid_uuid(_assert_present(data, "investigation_id", "CivilInvestigativeDemand"))
    assert isinstance(_assert_present(data, "subject_matter", "CivilInvestigativeDemand"), str)
    due = _assert_present(data, "response_due_date", "CivilInvestigativeDemand")
    assert is_iso8601_timestamp(due)
    _assert_present(data, "response_document_ref", "CivilInvestigativeDemand")
    _assert_optional_timestamp(data, "responded_at", "CivilInvestigativeDemand")
    assert data.get("status") in {s.value for s in CidStatus}


def assert_consent_order(data: dict):
    _assert_common(data, "ConsentOrder")
    assert is_valid_uuid(_assert_present(data, "investigation_id", "ConsentOrder"))
    assert isinstance(_assert_present(data, "subject_company_id", "ConsentOrder"), str)
    assert isinstance(_assert_present(data, "negotiating_attorney_user_id", "ConsentOrder"), str)
    relief = _assert_present(data, "monetary_relief_cents", "ConsentOrder")
    assert isinstance(relief, int) and relief > 0
    cap = _assert_present(data, "max_penalty_cents", "ConsentOrder")
    assert isinstance(cap, int) and cap > 0
    assert data.get("reporting_frequency_months") in (3, 6, 12)
    term = data.get("monitoring_term_years")
    assert isinstance(term, int) and 1 <= term <= 20
    prohibitions = _assert_present(data, "conduct_prohibitions", "ConsentOrder")
    assert isinstance(prohibitions, list) and len(prohibitions) > 0
    round_no = _assert_present(data, "proposal_round", "ConsentOrder")
    assert isinstance(round_no, int) and round_no >= 1
    _assert_optional_timestamp(data, "monitoring_started_at", "ConsentOrder")
    _assert_optional_timestamp(data, "monitoring_ends_at", "ConsentOrder")
    _assert_optional_timestamp(data, "finalized_at", "ConsentOrder")
    _assert_present(data, "finalized_by_user_id", "ConsentOrder")
    assert data.get("status") in {s.value for s in ConsentOrderStatus}


def assert_comment_period(data: dict):
    _assert_common(data, "PublicCommentPeriod")
    assert is_valid_uuid(_assert_present(data, "consent_order_id", "PublicCommentPeriod"))
    round_no = _assert_present(data, "round", "PublicCommentPeriod")
    assert isinstance(round_no, int) and round_no >= 1
    opened = _assert_present(data, "opened_at", "PublicCommentPeriod")
    assert is_iso8601_timestamp(opened)
    closes = _assert_present(data, "closes_at", "PublicCommentPeriod")
    assert is_iso8601_timestamp(closes)
    comments = _assert_present(data, "comments", "PublicCommentPeriod")
    assert isinstance(comments, list)
    count = _assert_present(data, "comment_count", "PublicCommentPeriod")
    assert isinstance(count, int) and count == len(comments)
    for entry in comments:
        assert isinstance(entry.get("author_email"), str)
        assert isinstance(entry.get("body"), str)
        assert is_iso8601_timestamp(entry.get("submitted_at", ""))
    assert data.get("status") in {s.value for s in CommentPeriodStatus}


def assert_compliance_report(data: dict):
    _assert_common(data, "ComplianceReport")
    assert is_valid_uuid(_assert_present(data, "consent_order_id", "ComplianceReport"))
    assert isinstance(_assert_present(data, "submitted_by_company_id", "ComplianceReport"), str)
    start = _assert_present(data, "period_start", "ComplianceReport")
    end = _assert_present(data, "period_end", "ComplianceReport")
    assert is_iso8601_timestamp(start) and is_iso8601_timestamp(end)
    assert isinstance(_assert_present(data, "report_document_ref", "ComplianceReport"), str)
    _assert_present(data, "deficiency_notes", "ComplianceReport")
    resub = _assert_present(data, "resubmission_count", "ComplianceReport")
    assert isinstance(resub, int) and resub >= 0
    _assert_present(data, "reviewed_by_user_id", "ComplianceReport")
    assert data.get("status") in {s.value for s in ComplianceReportStatus}


def assert_violation_penalty(data: dict):
    _assert_common(data, "ViolationPenalty")
    assert is_valid_uuid(_assert_present(data, "consent_order_id", "ViolationPenalty"))
    assert data.get("severity") in {s.value for s in PenaltySeverity}
    detected = _assert_present(data, "detected_on", "ViolationPenalty")
    assert is_iso8601_timestamp(detected)
    assert isinstance(_assert_present(data, "description", "ViolationPenalty"), str)
    assert isinstance(_assert_present(data, "assessed_by_user_id", "ViolationPenalty"), str)
    days = _assert_present(data, "provisional_days", "ViolationPenalty")
    assert isinstance(days, int) and days > 0
    amount = _assert_present(data, "provisional_amount_cents", "ViolationPenalty")
    assert isinstance(amount, int) and amount > 0
    _assert_present(data, "cured_on", "ViolationPenalty")
    _assert_present(data, "final_days", "ViolationPenalty")
    _assert_present(data, "final_amount_cents", "ViolationPenalty")
    _assert_present(data, "confirmed_by_user_id", "ViolationPenalty")
    assert data.get("status") in {s.value for s in ViolationPenaltyStatus}


def assert_monetary_judgment(data: dict):
    _assert_common(data, "MonetaryJudgment")
    assert is_valid_uuid(_assert_present(data, "consent_order_id", "MonetaryJudgment"))
    amount = _assert_present(data, "amount_cents", "MonetaryJudgment")
    assert isinstance(amount, int) and amount > 0
    collected = _assert_present(data, "collected_cents", "MonetaryJudgment")
    assert isinstance(collected, int) and collected >= 0
    outstanding = _assert_present(data, "outstanding_cents", "MonetaryJudgment")
    assert isinstance(outstanding, int) and outstanding >= 0
    assert data.get("collection_status") in {s.value for s in CollectionStatus}
    assert data.get("suspension_status") in {s.value for s in SuspensionStatus}
    _assert_present(data, "sworn_total_assets_cents", "MonetaryJudgment")
    log = _assert_present(data, "asset_trace_log", "MonetaryJudgment")
    assert isinstance(log, list)
    for entry in log:
        assert isinstance(entry.get("found_assets_cents"), int)
        assert isinstance(entry.get("trace_ref"), str)
        assert is_iso8601_timestamp(entry.get("traced_at", ""))


def assert_redress_fund(data: dict):
    _assert_common(data, "RedressFund")
    assert is_valid_uuid(_assert_present(data, "judgment_id", "RedressFund"))
    assert is_valid_uuid(_assert_present(data, "consent_order_id", "RedressFund"))
    for field in (
        "total_collected_cents", "admin_reserve_cents", "distributable_pool_cents",
        "allocated_cents", "disbursed_cents", "available_cents", "residual_cents",
    ):
        value = _assert_present(data, field, "RedressFund")
        assert isinstance(value, int) and value >= 0, f"RedressFund.{field} must be a non-negative integer"
    assert data.get("residual_disposition") in {d.value for d in ResidualDisposition}
    _assert_present(data, "residual_recipient_name", "RedressFund")
    assert data.get("status") in {s.value for s in RedressFundStatus}


def assert_claimant(data: dict):
    _assert_common(data, "Claimant")
    assert is_valid_uuid(_assert_present(data, "redress_fund_id", "Claimant"))
    assert isinstance(_assert_present(data, "full_name", "Claimant"), str)
    assert isinstance(_assert_present(data, "email", "Claimant"), str)
    assert data.get("identified_from") in {f.value for f in IdentifiedFrom}
    _assert_optional_timestamp(data, "notified_at", "Claimant")
    assert data.get("status") in {s.value for s in ClaimantStatus}


def assert_claim(data: dict):
    _assert_common(data, "Claim")
    assert is_valid_uuid(_assert_present(data, "claimant_id", "Claim"))
    assert is_valid_uuid(_assert_present(data, "redress_fund_id", "Claim"))
    loss = _assert_present(data, "documented_loss_cents", "Claim")
    assert isinstance(loss, int) and loss > 0
    _assert_present(data, "eligible_loss_cents", "Claim")
    _assert_present(data, "provisional_award_cents", "Claim")
    _assert_present(data, "final_award_cents", "Claim")
    _assert_present(data, "approved_by_user_id", "Claim")
    _assert_present(data, "denial_reason", "Claim")
    assert data.get("status") in {s.value for s in ClaimStatus}


def assert_refund_check(data: dict):
    _assert_common(data, "RefundCheck")
    assert is_valid_uuid(_assert_present(data, "claim_id", "RefundCheck"))
    assert is_valid_uuid(_assert_present(data, "redress_fund_id", "RefundCheck"))
    amount = _assert_present(data, "amount_cents", "RefundCheck")
    assert isinstance(amount, int) and amount > 0
    for field in ("issued_at", "stale_after", "reissue_deadline"):
        value = _assert_present(data, field, "RefundCheck")
        assert is_iso8601_timestamp(value), f"RefundCheck.{field} must be ISO 8601"
    _assert_present(data, "original_check_id", "RefundCheck")
    warning = _assert_present(data, "fraud_warning_text", "RefundCheck")
    assert isinstance(warning, str) and len(warning) > 0
    _assert_optional_timestamp(data, "cashed_at", "RefundCheck")
    _assert_present(data, "voided_reason", "RefundCheck")
    assert data.get("status") in {s.value for s in RefundCheckStatus}


# --- Domain invariant checkers ---------------------------------------------------

def assert_judgment_balance_invariants(data: dict):
    """collected + outstanding always equals the judgment amount (PRD 3.5)."""
    assert_monetary_judgment(data)
    assert data["collected_cents"] + data["outstanding_cents"] == data["amount_cents"], (
        f"judgment balance broken: {data['collected_cents']} + "
        f"{data['outstanding_cents']} != {data['amount_cents']}"
    )


def assert_fund_ledger_invariants(data: dict):
    """Fund money identity (PRD 3.6-3.8): every collected cent is accounted for.

    available + allocated + disbursed + admin_reserve + residual == total_collected.
    """
    assert_redress_fund(data)
    total = (
        data["available_cents"] + data["allocated_cents"] + data["disbursed_cents"]
        + data["admin_reserve_cents"] + data["residual_cents"]
    )
    assert total == data["total_collected_cents"], (
        f"fund ledger leaks money: available {data['available_cents']} + allocated "
        f"{data['allocated_cents']} + disbursed {data['disbursed_cents']} + reserve "
        f"{data['admin_reserve_cents']} + residual {data['residual_cents']} "
        f"!= total_collected {data['total_collected_cents']}"
    )
