"""Record -> JSON views.

Views expose exactly the field names the PRD/scaffold declare, no more.  Derived
monetary figures are serialised through money.as_number so the cent values come
out as JSON numbers with two-decimal arithmetic already applied.
"""

import money


def common(record):
    """The four system-managed properties shared by every top-level record
    (PRD §2.4): id, created_at, updated_at, version."""
    return {
        "id": record["id"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "version": record["version"],
    }


def view_agency(a):
    body = common(a)
    body.update({
        "agency_code": a["agency_code"],
        "name": a["name"],
        "region_code": a["region_code"],
        "market_need_score": a["market_need_score"],
        "status": a["status"],
        "book_open_count": a["book_open_count"],
        "annualized_commission_cents": money.as_number(a["annualized_commission_cents"]),
        "exposure_inforce_cents": money.as_number(a["exposure_inforce_cents"]),
        "agency_level_units": a["agency_level_units"],
        "agency_paid_claims_cents": money.as_number(a["agency_paid_claims_cents"]),
        "staffing_reimbursement_cents":
            money.as_number(a.get("staffing_reimbursement_cents", 0)),
        "loss_ratio": a["loss_ratio"],
        "growth_new_pct": a["growth_new_pct"],
        "performance_status": a["performance_status"],
        "agency_valuation_cents": money.as_number(a["agency_valuation_cents"]),
        "term_start_date": a["term_start_date"],
        "ops_run_index": a["ops_run_index"],
    })
    if a.get("rolling_base_cents") is not None:
        body["rolling_base_cents"] = money.as_number(a["rolling_base_cents"])
    return body


def view_agent(g):
    body = common(g)
    body.update({
        "full_name": g["full_name"],
        "state_code": g["state_code"],
        "market_need_score": g["market_need_score"],
        "license_status": g["license_status"],
        "license_expiry_date": g["license_expiry_date"],
        "state_market_need_acknowledged": g["state_market_need_acknowledged"],
        "status": g["status"],
        "agency_id": g["agency_id"],
        "is_new_agent": g["is_new_agent"],
        "appointment_date": g["appointment_date"],
    })
    return body


def view_policy(p):
    body = common(p)
    body.update({
        "policy_number": p["policy_number"],
        "product_line": p["product_line"],
        "annual_premium_cents": money.as_number(p["annual_premium_cents"]),
        "is_new_business": p["is_new_business"],
        "status": p["status"],
        "holder_agent_id": p["holder_agent_id"],
        "owner_agency_id": p["owner_agency_id"],
        "book_transfer_id": p["book_transfer_id"],
        "first_written_at": p["first_written_at"],
        "paid_claims_cents": money.as_number(p["paid_claims_cents"]),
        "sub_producer_released_commission_cents":
            money.as_number(p["sub_producer_released_commission_cents"]),
    })
    return body


def view_agreement(ag):
    body = common(ag)
    body.update({
        "agent_id": ag["agent_id"],
        "agency_id": ag["agency_id"],
        "agreement_type": ag["agreement_type"],
        "status": ag["status"],
        "commission_schedule": ag["commission_schedule"],
        "marketing_allowance_pool_cents":
            money.as_number(ag["marketing_allowance_pool_cents"]),
        "marketing_allowance_spent_cents":
            money.as_number(ag["marketing_allowance_spent_cents"]),
        "allowance_carryover_cents": money.as_number(ag["allowance_carryover_cents"]),
        "license_verified_at": ag["license_verified_at"],
        "termination_initiated_at": ag["termination_initiated_at"],
        "termination_value_cents": money.as_number(ag["termination_value_cents"]),
        # computed aggregates exposed alongside the contract terms
        "direct_additions_commission_cents":
            money.as_number(ag.get("direct_additions_commission_cents", 0)),
        "renewal_commission_cents":
            money.as_number(ag.get("renewal_commission_cents", 0)),
        "direct_additions_revenue_cents":
            money.as_number(ag.get("direct_additions_revenue_cents", 0)),
        "staffing_reimbursement_cents":
            money.as_number(ag.get("staffing_reimbursement_cents", 0)),
    })
    return body


def view_staff(s):
    body = common(s)
    body.update({
        "full_name": s["full_name"],
        "role_title": s["role_title"],
        "allocation_units": s["allocation_units"],
        "agency_id": s["agency_id"],
        "sponsoring_agreement_id": s["sponsoring_agreement_id"],
        "status": s["status"],
        "allocated_agent_id": s["allocated_agent_id"],
        "assignment_start_date": s["assignment_start_date"],
        "assignment_end_date": s["assignment_end_date"],
    })
    return body


def view_campaign(c):
    body = common(c)
    body.update({
        "agency_id": c["agency_id"],
        "campaign_type": c["campaign_type"],
        "marketing_allowance_cents": money.as_number(c["marketing_allowance_cents"]),
        "expected_leads": c["expected_leads"],
        "status": c["status"],
        "participation_posture": c["participation_posture"],
        "start_date": c["start_date"],
        "end_date": c["end_date"],
    })
    return body


def view_claim(c):
    body = common(c)
    paid = c.get("policy_paid_cents")
    body.update({
        "policy_id": c["policy_id"],
        "claim_amount_cents": money.as_number(c["claim_amount_cents"]),
        # An OPEN claim that has never been compensated reads as unset.
        "policy_paid_cents": None if paid is None else money.as_number(paid),
        "status": c["status"],
    })
    return body


def view_transfer(t):
    body = common(t)
    body.update({
        "agent_id": t["agent_id"],
        "from_agency_id": t["from_agency_id"],
        "to_agency_id": t["to_agency_id"],
        "successor_agent_id": t["successor_agent_id"],
        "transferred_policy_count": t["transferred_policy_count"],
        "retained_policy_count": t["retained_policy_count"],
        "retention_pct": t["retention_pct"],
        "retention_met": t["retention_met"],
        "settlement_payable_cents": money.as_number(t["settlement_payable_cents"]),
        "status": t["status"],
    })
    return body


def view_license(l):
    """LicenseRecord is immutable after posting: id and created_at only."""
    return {
        "id": l["id"],
        "created_at": l["created_at"],
        "agent_id": l["agent_id"],
        "full_name": l["full_name"],
        "state_code": l["state_code"],
        "product_lines": l["product_lines"],
        "license_expiry_date": l["license_expiry_date"],
    }


def view_application(a):
    body = common(a)
    body.update({
        "state_code": a["state_code"],
        "market_need_score": a["market_need_score"],
        "candidate_assessment_score": a["candidate_assessment_score"],
        "market_odds_score": a["market_odds_score"],
        "status": a["status"],
        "required_action": a["required_action"],
        "appointment_priority": a["appointment_priority"],
        "application_value_tier": a["application_value_tier"],
        "creation_channel": a["creation_channel"],
        "agent_id": a["agent_id"],
        "closure_note": a["closure_note"],
    })
    return body