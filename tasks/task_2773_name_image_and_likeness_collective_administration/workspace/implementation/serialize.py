"""Resource serialization. Every timestamp is rendered in the canonical form."""

import clock
import derive
import store

ts = clock.format_ts


def collective(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "institution_name": row["institution_name"],
        "institution_ipeds_code": row["institution_ipeds_code"],
        "home_state_code": row["home_state_code"],
        "association_ruleset": row["association_ruleset"],
        "entity_structure": row["entity_structure"],
        "communication_policy": row["communication_policy"],
        "charitable_deduction_enabled": row["charitable_deduction_enabled"],
        "structure_effective_at": ts(row["structure_effective_at"]),
        "structure_change_count": row["structure_change_count"],
        "funding_posture": row["funding_posture"],
        "settled_net_funds_cents": row["settled_net_funds_cents"],
        "committed_unreleased_cents": row["committed_unreleased_cents"],
        "released_total_cents": row["released_total_cents"],
        "reversed_total_cents": row["reversed_total_cents"],
        "created_at": ts(row["created_at"]),
        "updated_at": ts(row["updated_at"]),
        "version": row["version"],
    }


def membership_tier(row):
    return {
        "id": row["id"],
        "collective_id": row["collective_id"],
        "tier_code": row["tier_code"],
        "tier_name": row["tier_name"],
        "annual_dues_cents": row["annual_dues_cents"],
        "benefit_rank": row["benefit_rank"],
        "tier_status": row["tier_status"],
        "active_commitment_count": derive.tier_active_commitment_count(row),
        "sequence_no": row["sequence_no"],
        "created_at": ts(row["created_at"]),
        "updated_at": ts(row["updated_at"]),
        "version": row["version"],
    }


def donor_member(row):
    return {
        "id": row["id"],
        "collective_id": row["collective_id"],
        "membership_tier_id": row["membership_tier_id"],
        "display_name": row["display_name"],
        "email": row["email"],
        "donor_kind": row["donor_kind"],
        "annual_agi_cents": row["annual_agi_cents"],
        "status": row["status"],
        "lifetime_settled_cents": row["lifetime_settled_cents"],
        "lifetime_deductible_cents": row["lifetime_deductible_cents"],
        "sequence_no": row["sequence_no"],
        "created_at": ts(row["created_at"]),
        "updated_at": ts(row["updated_at"]),
        "version": row["version"],
    }


def commitment(row):
    return {
        "id": row["id"],
        "donor_member_id": row["donor_member_id"],
        "kind": row["kind"],
        "amount_cents": row["amount_cents"],
        "billing_interval": row["billing_interval"],
        "installments_total": row["installments_total"],
        "installments_charged": row["installments_charged"],
        "status": row["status"],
        "pause_reason": row["pause_reason"],
        "superseded_by_commitment_id": row["superseded_by_commitment_id"],
        "sequence_no": row["sequence_no"],
        "created_at": ts(row["created_at"]),
        "updated_at": ts(row["updated_at"]),
        "version": row["version"],
    }


def contribution(row):
    return {
        "id": row["id"],
        "donor_member_id": row["donor_member_id"],
        "commitment_id": row["commitment_id"],
        "gross_amount_cents": row["gross_amount_cents"],
        "source_kind": row["source_kind"],
        "designation": row["designation"],
        "processor_outcome": row["processor_outcome"],
        "status": row["status"],
        "processing_fee_cents": row["processing_fee_cents"],
        "net_amount_cents": row["net_amount_cents"],
        "deductible_amount_cents": row["deductible_amount_cents"],
        "deduction_variant": row["deduction_variant"],
        "received_at": ts(row["received_at"]),
        "sequence_no": row["sequence_no"],
        "created_at": ts(row["created_at"]),
        "updated_at": ts(row["updated_at"]),
        "version": row["version"],
    }


def athlete(row):
    gross, withheld = derive.athlete_tax_year_figures(row["id"])
    import calc
    return {
        "id": row["id"],
        "collective_id": row["collective_id"],
        "full_name": row["full_name"],
        "portal_user_id": row["portal_user_id"],
        "sport": row["sport"],
        "class_year": row["class_year"],
        "roster_weight": row["roster_weight"],
        "tax_person_kind": row["tax_person_kind"],
        "taxpayer_doc_on_file": row["taxpayer_doc_on_file"],
        "treaty_exempt_claimed": row["treaty_exempt_claimed"],
        "eligibility_status": row["eligibility_status"],
        "annual_committed_value_cents": derive.athlete_annual_committed(row["id"]),
        "tax_year_gross_paid_cents": gross,
        "tax_year_withheld_cents": withheld,
        "tax_form_required": calc.tax_form_required(gross, row["tax_person_kind"]),
        "sequence_no": row["sequence_no"],
        "created_at": ts(row["created_at"]),
        "updated_at": ts(row["updated_at"]),
        "version": row["version"],
    }


def deal_contract(row):
    return {
        "id": row["id"],
        "collective_id": row["collective_id"],
        "athlete_id": row["athlete_id"],
        "deal_kind": row["deal_kind"],
        "allocation_batch_code": row["allocation_batch_code"],
        "total_value_cents": row["total_value_cents"],
        "funding_designation": row["funding_designation"],
        "exclusivity_category": row["exclusivity_category"],
        "effective_start_at": ts(row["effective_start_at"]),
        "effective_end_at": ts(row["effective_end_at"]),
        "lifecycle_status": row["lifecycle_status"],
        "payment_status": row["payment_status"],
        "disclosure_status": row["disclosure_status"],
        "disclosure_due_at": ts(row["disclosure_due_at"]),
        "disclosure_submitted_at": ts(row["disclosure_submitted_at"]),
        "disclosure_return_count": row["disclosure_return_count"],
        "deliverable_value_total_cents": derive.contract_deliverable_value_total(row),
        "released_total_cents": derive.contract_released_total(row),
        "clawback_amount_cents": (row["clawback_amount_cents"]
                                  if row["lifecycle_status"] == "TERMINATED" else 0),
        "termination_reason": row["termination_reason"],
        "sequence_no": row["sequence_no"],
        "created_at": ts(row["created_at"]),
        "updated_at": ts(row["updated_at"]),
        "version": row["version"],
    }


def evidence_record(item):
    return {
        "evidence_kind": item["evidence_kind"],
        "reference_label": item["reference_label"],
        "recorded_at": ts(item["recorded_at"]),
        "sequence_no": item["sequence_no"],
    }


def deliverable(row):
    contract = store.deal_contracts.get(row["deal_contract_id"])
    return {
        "id": row["id"],
        "deal_contract_id": row["deal_contract_id"],
        "deliverable_kind": row["deliverable_kind"],
        "unit_value_cents": row["unit_value_cents"],
        "due_at": ts(row["due_at"]),
        "required_charity_hours_tenths": row["required_charity_hours_tenths"],
        "charity_hours_tenths": row["charity_hours_tenths"],
        "status": row["status"],
        "evidence_records": [evidence_record(i) for i in row["evidence_records"]],
        "evidence_count": len(row["evidence_records"]),
        "submission_count": row["submission_count"],
        "performed_at": ts(row["performed_at"]),
        "submitted_at": ts(row["submitted_at"]),
        "late_flag": row["late_flag"],
        "verified_by_user_id": row["verified_by_user_id"],
        "verified_at": ts(row["verified_at"]),
        "payout_basis": derive.deliverable_payout_basis(row, contract),
        "payout_eligible_cents": derive.deliverable_payout_eligible(row, contract),
        "sequence_no": row["sequence_no"],
        "created_at": ts(row["created_at"]),
        "updated_at": ts(row["updated_at"]),
        "version": row["version"],
    }


def payment_release(row):
    return {
        "id": row["id"],
        "deal_contract_id": row["deal_contract_id"],
        "deliverable_id": row["deliverable_id"],
        "release_kind": row["release_kind"],
        "requested_amount_cents": row["requested_amount_cents"],
        "withholding_basis": row["withholding_basis"],
        "withholding_amount_cents": row["withholding_amount_cents"],
        "net_payable_cents": row["net_payable_cents"],
        "status": row["status"],
        "initiated_by_user_id": row["initiated_by_user_id"],
        "released_at": ts(row["released_at"]),
        "reversal_reason": row["reversal_reason"],
        "sequence_no": row["sequence_no"],
        "created_at": ts(row["created_at"]),
        "updated_at": ts(row["updated_at"]),
        "version": row["version"],
    }


def communication_log(row):
    return {
        "id": row["id"],
        "collective_id": row["collective_id"],
        "athlete_id": row["athlete_id"],
        "actor_role": row["actor_role"],
        "channel": row["channel"],
        "topic": row["topic"],
        "note": row["note"],
        "verdict": row["verdict"],
        "rationale_code": row["rationale_code"],
        "logged_at": ts(row["logged_at"]),
        "sequence_no": row["sequence_no"],
        "created_at": ts(row["created_at"]),
    }
