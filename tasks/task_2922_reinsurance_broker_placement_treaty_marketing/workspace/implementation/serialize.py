"""Wire representations.  Only PRD-declared fields leave the process."""
from util import fmt_instant


def _common(row, versioned=True):
    out = {"id": row["id"], "created_at": fmt_instant(row["created_at"])}
    if versioned:
        out["updated_at"] = fmt_instant(row["updated_at"])
        out["version"] = row["version"]
    return out


def cedent(row):
    out = _common(row)
    out.update({
        "name": row["name"],
        "domicile_code": row["domicile_code"],
        "financial_rating": row["financial_rating"],
        "status": row["status"],
        "suspension_reason": row["suspension_reason"],
        "settled_receipts_minor": row["settled_receipts_minor"],
        "outstanding_reinstatement_premium_minor":
            row["outstanding_reinstatement_premium_minor"],
    })
    return out


def reinsurer(row):
    out = _common(row)
    out.update({
        "name": row["name"],
        "security_rating": row["security_rating"],
        "capacity_limit_minor": row["capacity_limit_minor"],
        "max_line_pct": row["max_line_pct"],
        "lead_authorised": row["lead_authorised"],
        "security_status": row["security_status"],
        "committed_capacity_minor": row["committed_capacity_minor"],
        "available_capacity_minor": row["available_capacity_minor"],
    })
    return out


def program(row):
    out = _common(row)
    out.update({
        "cedent_id": row["cedent_id"],
        "prior_program_id": row["prior_program_id"],
        "program_name": row["program_name"],
        "line_of_business": row["line_of_business"],
        "underwriting_year": row["underwriting_year"],
        "inception_date": fmt_instant(row["inception_date"]),
        "expiry_date": fmt_instant(row["expiry_date"]),
        "currency_code": row["currency_code"],
        "estimated_premium_income_minor": row["estimated_premium_income_minor"],
        "brokerage_pct": row["brokerage_pct"],
        "signdown_method": row["signdown_method"],
        "placement_status": row["placement_status"],
        "documentation_status": row["documentation_status"],
        "contract_certainty_deadline": fmt_instant(row["contract_certainty_deadline"]),
        "disclosure_acknowledged": row["disclosure_acknowledged"],
        "gross_written_premium_minor": row["gross_written_premium_minor"],
        "brokerage_earned_minor": row["brokerage_earned_minor"],
        "net_remittance_minor": row["net_remittance_minor"],
        "rounding_residue_minor": row["rounding_residue_minor"],
        "fiduciary_holding_minor": row["fiduciary_holding_minor"],
        "withdrawal_reason": row["withdrawal_reason"],
    })
    return out


def exposure_submission(row):
    out = _common(row)
    out.update({
        "program_id": row["program_id"],
        "package_label": row["package_label"],
        "exposure_records_count": row["exposure_records_count"],
        "data_quality_flags_count": row["data_quality_flags_count"],
        "historical_years_supplied": row["historical_years_supplied"],
        "cat_model_version": row["cat_model_version"],
        "loss_history_completeness_pct": row["loss_history_completeness_pct"],
        "actuarial_report_attached": row["actuarial_report_attached"],
        "completeness_score": row["completeness_score"],
        "status": row["status"],
        "actuary_signoff_user_id": row["actuary_signoff_user_id"],
        "signed_off_at": fmt_instant(row["signed_off_at"]),
        "review_note": row["review_note"],
    })
    return out


def layer(row):
    out = _common(row)
    out.update({
        "program_id": row["program_id"],
        "layer_label": row["layer_label"],
        "layer_type": row["layer_type"],
        "attachment_minor": row["attachment_minor"],
        "limit_minor": row["limit_minor"],
        "cession_pct": row["cession_pct"],
        "base_rate_pct": row["base_rate_pct"],
        "subject_premium_base_minor": row["subject_premium_base_minor"],
        "expected_loss_cost_minor": row["expected_loss_cost_minor"],
        "reinstatements_total": row["reinstatements_total"],
        "reinstatement_premium_pct": row["reinstatement_premium_pct"],
        "sublimit_minor": row["sublimit_minor"],
        "ceding_commission_pct": row["ceding_commission_pct"],
        "excluded_perils": list(row["excluded_perils"]),
        "quoted_gross_premium_minor": row["quoted_gross_premium_minor"],
        "written_line_total_pct": row["written_line_total_pct"],
        "signed_line_total_pct": row["signed_line_total_pct"],
        "limit_eroded_minor": row["limit_eroded_minor"],
        "reinstatements_used": row["reinstatements_used"],
        "incurred_ceded_minor": row["incurred_ceded_minor"],
        "loss_ratio_pct": row["loss_ratio_pct"],
        "provisional_ceding_commission_minor": row["provisional_ceding_commission_minor"],
        "final_ceding_commission_minor": row["final_ceding_commission_minor"],
        "ceding_commission_delta_minor": row["ceding_commission_delta_minor"],
        "status": row["status"],
    })
    return out


def market_submission(row):
    out = _common(row)
    out.update({
        "layer_id": row["layer_id"],
        "reinsurer_id": row["reinsurer_id"],
        "response_deadline": fmt_instant(row["response_deadline"]),
        "submitted_by_user_id": row["submitted_by_user_id"],
        "sent_at": fmt_instant(row["sent_at"]),
        "status": row["status"],
    })
    return out


def quote(row):
    out = _common(row)
    out.update({
        "market_submission_id": row["market_submission_id"],
        "layer_id": row["layer_id"],
        "reinsurer_id": row["reinsurer_id"],
        "offered_line_pct": row["offered_line_pct"],
        "quoted_rate_pct": row["quoted_rate_pct"],
        "ceding_commission_pct": row["ceding_commission_pct"],
        "reinstatements_offered": row["reinstatements_offered"],
        "sublimit_minor": row["sublimit_minor"],
        "additional_exclusions": list(row["additional_exclusions"]),
        "is_lead": row["is_lead"],
        "expires_at": fmt_instant(row["expires_at"]),
        "negotiation_round": row["negotiation_round"],
        "last_counter_note": row["last_counter_note"],
        "accepted_line_pct": row["accepted_line_pct"],
        "status": row["status"],
    })
    return out


def signing_line(row):
    out = _common(row)
    out.update({
        "layer_id": row["layer_id"],
        "quote_id": row["quote_id"],
        "reinsurer_id": row["reinsurer_id"],
        "written_line_pct": row["written_line_pct"],
        "signed_line_pct": row["signed_line_pct"],
        "effective_line_pct": row["effective_line_pct"],
        "committed_capacity_minor": row["committed_capacity_minor"],
        "status": row["status"],
        "release_reason": row["release_reason"],
    })
    return out


def contract_document(row):
    out = _common(row, versioned=False)
    out.update({
        "program_id": row["program_id"],
        "document_type": row["document_type"],
        "wording_reference": row["wording_reference"],
        "issued_at": fmt_instant(row["issued_at"]),
        "days_from_inception": row["days_from_inception"],
        "filed_by_user_id": row["filed_by_user_id"],
    })
    return out


def brokerage_disclosure(row):
    out = _common(row)
    out.update({
        "program_id": row["program_id"],
        "brokerage_pct": row["brokerage_pct"],
        "contingent_commission_pct": row["contingent_commission_pct"],
        "market_service_fee_minor": row["market_service_fee_minor"],
        "disclosed_by_user_id": row["disclosed_by_user_id"],
        "acknowledged_by_user_id": row["acknowledged_by_user_id"],
        "decision_note": row["decision_note"],
        "status": row["status"],
    })
    return out


def fiduciary_transaction(row):
    out = _common(row)
    out.update({
        "program_id": row["program_id"],
        "signing_line_id": row["signing_line_id"],
        "reverses_transaction_id": row["reverses_transaction_id"],
        "txn_type": row["txn_type"],
        "amount_minor": row["amount_minor"],
        "created_by_user_id": row["created_by_user_id"],
        "approved_by_user_id": row["approved_by_user_id"],
        "value_date": fmt_instant(row["value_date"]),
        "hold_reason": row["hold_reason"],
        "status": row["status"],
    })
    return out


def claim_advocacy(row):
    out = _common(row)
    out.update({
        "layer_id": row["layer_id"],
        "claim_reference": row["claim_reference"],
        "event_date": fmt_instant(row["event_date"]),
        "gross_claim_minor": row["gross_claim_minor"],
        "ceded_claim_minor": row["ceded_claim_minor"],
        "disputed_minor": row["disputed_minor"],
        "collected_minor": row["collected_minor"],
        "collectible_minor": row["collectible_minor"],
        "advocacy_route": row["advocacy_route"],
        "arbitration_cost_minor": row["arbitration_cost_minor"],
        "reinstatement_triggered": row["reinstatement_triggered"],
        "status": row["status"],
    })
    return out


def cession_dispute(row):
    out = _common(row)
    out.update({
        "claim_advocacy_id": row["claim_advocacy_id"],
        "signing_line_id": row["signing_line_id"],
        "disputed_minor": row["disputed_minor"],
        "dispute_reason": row["dispute_reason"],
        "settled_minor": row["settled_minor"],
        "resolution_note": row["resolution_note"],
        "status": row["status"],
    })
    return out


def renewal_report(row):
    out = _common(row, versioned=False)
    out.update({
        "program_id": row["program_id"],
        "current_rate_on_line_pct": row["current_rate_on_line_pct"],
        "prior_rate_on_line_pct": row["prior_rate_on_line_pct"],
        "rate_change_pct": row["rate_change_pct"],
        "exposure_change_pct": row["exposure_change_pct"],
        "risk_adjusted_rate_change_pct": row["risk_adjusted_rate_change_pct"],
        "placement_efficiency_pct": row["placement_efficiency_pct"],
        "market_condition_index": row["market_condition_index"],
        "generated_by_user_id": row["generated_by_user_id"],
        "as_of": fmt_instant(row["as_of"]),
    })
    return out
