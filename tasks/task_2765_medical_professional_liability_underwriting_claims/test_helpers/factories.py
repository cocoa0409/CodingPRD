"""Payload factories — one per entity, client-supplied input fields only.

Every monetary amount is emitted as a JSON number, never as a string.
"""

DEFAULTS = {
    "SPECIALTY_CODE": "OBSTETRICS_GYNECOLOGY",
    "BASE_CLASS_CODE": "CLASS_6",
    "BASE_RATE_PER_MILLION": 38000.00,
    "HAZARD_INDEX": 7.0,
    "BENCHMARK_SEVERITY": 640000.00,
    "LEGAL_NAME": "Rivera OBGYN PC",
    "VENUE_CODE": "COOK_IL",
    "HIGH_SEVERITY_PROCEDURE_PCT": 40,
    "YEARS_IN_PRACTICE": 12,
    "LIMIT_PER_CLAIM": 1000000.00,
    "LIMIT_AGGREGATE": 3000000.00,
    "FIRM_NAME": "Aldridge Defence LLP",
    "BLENDED_HOURLY_RATE": 320.00,
    "QUALITY_SCORE": 88,
    "DEMAND_AMOUNT": 800000.00,
    "ALLEGATION_CATEGORY": "OBSTETRIC_INJURY",
}


def specialty_class_payload(**overrides) -> dict:
    payload = {
        "specialty_code": DEFAULTS["SPECIALTY_CODE"],
        "base_class_code": DEFAULTS["BASE_CLASS_CODE"],
        "base_rate_per_million": DEFAULTS["BASE_RATE_PER_MILLION"],
        "hazard_index": DEFAULTS["HAZARD_INDEX"],
        "benchmark_severity": DEFAULTS["BENCHMARK_SEVERITY"],
    }
    payload.update(overrides)
    return payload


def insured_payload(specialty_class_id=None, **overrides) -> dict:
    payload = {
        "entity_type": "PHYSICIAN",
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "specialty_class_id": specialty_class_id,
        "venue_code": DEFAULTS["VENUE_CODE"],
        "high_severity_procedure_pct": DEFAULTS["HIGH_SEVERITY_PROCEDURE_PCT"],
        "years_in_practice": DEFAULTS["YEARS_IN_PRACTICE"],
        "board_certified": True,
    }
    payload.update(overrides)
    return payload


def credentialing_decision_payload(credentialing_status="CREDENTIALED",
                                   credentialing_expires_on="2028-01-01",
                                   **overrides) -> dict:
    payload = {"credentialing_status": credentialing_status}
    if credentialing_expires_on is not None:
        payload["credentialing_expires_on"] = credentialing_expires_on
    payload.update(overrides)
    return payload


def enrollment_payload(program_code="SIM_LAB", enrolled_on="2026-08-05",
                       expected_insured_version=None, **overrides) -> dict:
    payload = {
        "program_code": program_code,
        "enrolled_on": enrolled_on,
        "expected_insured_version": expected_insured_version,
    }
    payload.update(overrides)
    return payload


def enrollment_completion_payload(completed_on="2026-08-10",
                                  attestation_reference="SIM-2026-0001",
                                  **overrides) -> dict:
    payload = {
        "completed_on": completed_on,
        "attestation_reference": attestation_reference,
    }
    payload.update(overrides)
    return payload


def peer_review_case_payload(insured_id=None, trigger_source="SENTINEL_EVENT",
                             referral_note="Referred for sentinel event review.",
                             **overrides) -> dict:
    payload = {
        "insured_id": insured_id,
        "trigger_source": trigger_source,
        "referral_note": referral_note,
    }
    payload.update(overrides)
    return payload


def review_track_payload(review_track="CHART", outcome="CONCERN", **overrides) -> dict:
    payload = {"review_track": review_track, "outcome": outcome}
    payload.update(overrides)
    return payload


def committee_vote_payload(vote_result="DEVIATION_MINOR", votes_for=4,
                          votes_against=1, **overrides) -> dict:
    payload = {
        "vote_result": vote_result,
        "votes_for": votes_for,
        "votes_against": votes_against,
    }
    payload.update(overrides)
    return payload


def policy_payload(insured_id=None, coverage_form="CLAIMS_MADE",
                   retroactive_date="2026-08-01",
                   consent_to_settle_clause="NONE", **overrides) -> dict:
    payload = {
        "insured_id": insured_id,
        "coverage_form": coverage_form,
        "limit_per_claim": DEFAULTS["LIMIT_PER_CLAIM"],
        "limit_aggregate": DEFAULTS["LIMIT_AGGREGATE"],
        "prior_acts_step_credit": 0,
        "consent_to_settle_clause": consent_to_settle_clause,
    }
    if retroactive_date is not None:
        payload["retroactive_date"] = retroactive_date
    payload.update(overrides)
    return payload


def policy_term_payload(effective_date="2026-09-01", expiration_date="2027-09-01",
                        expected_policy_version=None, predecessor_term_id=None,
                        **overrides) -> dict:
    payload = {
        "effective_date": effective_date,
        "expiration_date": expiration_date,
        "expected_policy_version": expected_policy_version,
    }
    if predecessor_term_id is not None:
        payload["predecessor_term_id"] = predecessor_term_id
    payload.update(overrides)
    return payload


def cancellation_payload(cancel_type="PRO_RATA", cancel_effective_date="2027-03-01",
                         **overrides) -> dict:
    payload = {
        "cancel_type": cancel_type,
        "cancel_effective_date": cancel_effective_date,
    }
    payload.update(overrides)
    return payload


def tail_endorsement_payload(triggering_term_id=None, tail_type="ERP_5YR",
                             trigger_reason="RETIREMENT",
                             effective_date="2027-09-01", **overrides) -> dict:
    payload = {
        "triggering_term_id": triggering_term_id,
        "tail_type": tail_type,
        "trigger_reason": trigger_reason,
        "effective_date": effective_date,
    }
    payload.update(overrides)
    return payload


def claim_payload(insured_id=None, incident_date="2026-10-01",
                  report_date="2026-11-01", venue_code=None,
                  allegation_category=None, demand_amount=None,
                  **overrides) -> dict:
    payload = {
        "insured_id": insured_id,
        "incident_date": incident_date,
        "report_date": report_date,
        "venue_code": venue_code or DEFAULTS["VENUE_CODE"],
        "allegation_category": allegation_category or DEFAULTS["ALLEGATION_CATEGORY"],
        "demand_amount": DEFAULTS["DEMAND_AMOUNT"] if demand_amount is None
        else demand_amount,
    }
    payload.update(overrides)
    return payload


def coverage_decision_payload(coverage_status="COVERED",
                              reserved_rights_reason=None, **overrides) -> dict:
    payload = {"coverage_status": coverage_status}
    if reserved_rights_reason is not None:
        payload["reserved_rights_reason"] = reserved_rights_reason
    payload.update(overrides)
    return payload


def reserve_entry_payload(method="FORMULA_BASIS", effective_at="2026-11-05T00:00:00Z",
                          rationale="Initial projection.",
                          expected_claim_version=None,
                          indemnity_amount=None, expense_amount=None,
                          **overrides) -> dict:
    payload = {
        "method": method,
        "effective_at": effective_at,
        "rationale": rationale,
        "expected_claim_version": expected_claim_version,
    }
    if indemnity_amount is not None:
        payload["indemnity_amount"] = indemnity_amount
    if expense_amount is not None:
        payload["expense_amount"] = expense_amount
    payload.update(overrides)
    return payload


def litigation_payload(suit_filed_on="2026-12-01", **overrides) -> dict:
    payload = {"suit_filed_on": suit_filed_on}
    payload.update(overrides)
    return payload


def expense_payment_payload(amount=20000.00, invoice_reference="INV-0001",
                            counsel_assignment_id=None, **overrides) -> dict:
    payload = {
        "amount": amount,
        "invoice_reference": invoice_reference,
        "counsel_assignment_id": counsel_assignment_id,
    }
    payload.update(overrides)
    return payload


def disposition_payload(disposition="DEFENSE_VERDICT", resolved_on="2027-02-01",
                        verdict_amount=None, **overrides) -> dict:
    payload = {"disposition": disposition, "resolved_on": resolved_on}
    if verdict_amount is not None:
        payload["verdict_amount"] = verdict_amount
    payload.update(overrides)
    return payload


def counsel_firm_payload(firm_name=None, admitted_venue_codes=None,
                         allegation_specialties=None, blended_hourly_rate=None,
                         quality_score=None, **overrides) -> dict:
    payload = {
        "firm_name": firm_name or DEFAULTS["FIRM_NAME"],
        "admitted_venue_codes": admitted_venue_codes or ["COOK_IL"],
        "allegation_specialties": allegation_specialties or ["OBSTETRIC_INJURY"],
        "blended_hourly_rate": DEFAULTS["BLENDED_HOURLY_RATE"]
        if blended_hourly_rate is None else blended_hourly_rate,
        "quality_score": DEFAULTS["QUALITY_SCORE"] if quality_score is None
        else quality_score,
    }
    payload.update(overrides)
    return payload


def panel_status_payload(panel_status="REMOVED", reason="Panel audit finding.",
                         **overrides) -> dict:
    payload = {"panel_status": panel_status, "reason": reason}
    payload.update(overrides)
    return payload


def decline_payload(decline_reason="CONFLICT_OF_INTEREST", **overrides) -> dict:
    payload = {"decline_reason": decline_reason}
    payload.update(overrides)
    return payload


def negotiation_payload(proposed_amount=400000.00, authority_requested=400000.00,
                       expected_claim_version=None, **overrides) -> dict:
    payload = {
        "proposed_amount": proposed_amount,
        "authority_requested": authority_requested,
        "expected_claim_version": expected_claim_version,
    }
    payload.update(overrides)
    return payload


def authority_decision_payload(decision="GRANT", granted_amount=400000.00,
                               approver_note="Authority granted.", **overrides) -> dict:
    payload = {"decision": decision, "approver_note": approver_note}
    if decision == "GRANT" and granted_amount is not None:
        payload["granted_amount"] = granted_amount
    payload.update(overrides)
    return payload


def consent_response_payload(response="CONSENTED", veto_reason=None,
                             **overrides) -> dict:
    payload = {"response": response}
    if veto_reason is not None:
        payload["veto_reason"] = veto_reason
    payload.update(overrides)
    return payload


def revision_payload(proposed_amount=300000.00, authority_requested=300000.00,
                     **overrides) -> dict:
    payload = {
        "proposed_amount": proposed_amount,
        "authority_requested": authority_requested,
    }
    payload.update(overrides)
    return payload


def hammer_invocation_payload(notice_sent_on="2027-01-15", **overrides) -> dict:
    payload = {"notice_sent_on": notice_sent_on}
    payload.update(overrides)
    return payload


def settlement_payment_payload(payment_date="2027-02-01", **overrides) -> dict:
    payload = {"payment_date": payment_date}
    payload.update(overrides)
    return payload


def npdb_submission_payload(submitted_on="2027-02-15",
                            submitter_note="Transmitted to the data bank.",
                            **overrides) -> dict:
    payload = {"submitted_on": submitted_on, "submitter_note": submitter_note}
    payload.update(overrides)
    return payload


def npdb_void_payload(void_reason="Duplicate obligation.", **overrides) -> dict:
    payload = {"void_reason": void_reason}
    payload.update(overrides)
    return payload


def rate_filing_payload(specialty_class_id=None,
                        indication_method="LOSS_RATIO_METHOD",
                        proposed_rate_change_pct=10.00,
                        experience_period_start="2026-08-01",
                        experience_period_end="2027-06-30",
                        effective_date="2027-07-01", **overrides) -> dict:
    payload = {
        "specialty_class_id": specialty_class_id,
        "indication_method": indication_method,
        "proposed_rate_change_pct": proposed_rate_change_pct,
        "experience_period_start": experience_period_start,
        "experience_period_end": experience_period_end,
        "effective_date": effective_date,
    }
    payload.update(overrides)
    return payload


def filing_decision_payload(decision="APPROVE", decision_note="Approved.",
                            **overrides) -> dict:
    payload = {"decision": decision, "decision_note": decision_note}
    payload.update(overrides)
    return payload
