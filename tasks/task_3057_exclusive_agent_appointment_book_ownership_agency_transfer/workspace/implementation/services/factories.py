"""Record construction.

Every factory here is called from a route in response to a client request —
nothing in this module runs at import time or at boot.  The store starts empty.
"""

from decimal import Decimal

import clock
import db
from money import dec, round_cents
from services import calculations as calc
from services.calculations import released_commission_cents


def _stamp(record):
    now = clock.iso()
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    return record


def create_agency(payload):
    record = {
        "id": db.new_id(),
        "agency_code": payload.get("agency_code"),
        "name": payload.get("name"),
        "region_code": payload.get("region_code"),
        "market_need_score": payload.get("market_need_score"),
        "status": "APPROVED",
        "book_open_count": 0,
        "annualized_commission_cents": Decimal(0),
        "exposure_inforce_cents": Decimal(0),
        "agency_level_units": 0,
        "agency_paid_claims_cents": Decimal(0),
        "staffing_reimbursement_cents": Decimal(0),
        "loss_ratio": 0,
        "growth_new_pct": 0,
        "performance_status": "ON_TRACK",
        "agency_valuation_cents": Decimal("2000000"),
        "term_start_date": None,
        "ops_run_index": 0,
        "rolling_base_cents": Decimal(0),
        "allowance_carryover_cents": Decimal(0),
        "marketing_allowance_pool_cents": Decimal(0),
        "marketing_allowance_spent_cents": Decimal(0),
    }
    _stamp(record)
    db.agency_rows()[record["id"]] = record
    return record


def create_agent(payload):
    record = {
        "id": db.new_id(),
        "full_name": payload.get("full_name"),
        "state_code": payload.get("state_code"),
        "market_need_score": payload.get("market_need_score"),
        "license_status": payload.get("license_status") or "NOT_LICENSED",
        "license_expiry_date": payload.get("license_expiry_date"),
        "state_market_need_acknowledged": False,
        "status": payload.get("status") or "CANDIDATE",
        "agency_id": None,
        "is_new_agent": bool(payload.get("is_new_agent", True)),
        "appointment_date": None,
    }
    _stamp(record)
    db.agent_rows()[record["id"]] = record
    return record


def mint_agent_from_application(application):
    """The CONSUMED application mints an APPOINTED agent (PRD §3.2)."""
    return create_agent({
        "full_name": application.get("full_name") or application.get("applicant_name"),
        "state_code": application.get("state_code"),
        "market_need_score": application.get("market_need_score"),
        "license_status": "NOT_LICENSED",
        "status": "APPOINTED",
        "is_new_agent": True,
    })


def create_policy(payload):
    now = clock.iso()
    record = {
        "id": db.new_id(),
        "policy_number": payload.get("policy_number"),
        "product_line": payload.get("product_line"),
        "annual_premium_cents": round_cents(dec(payload.get("annual_premium_cents", 0))),
        "is_new_business": bool(payload.get("is_new_business", False)),
        "status": "OPEN",
        "holder_agent_id": payload.get("holder_agent_id"),
        "owner_agency_id": payload.get("owner_agency_id"),
        "book_transfer_id": None,
        "first_written_at": now,
        "paid_claims_cents": Decimal(0),
        "sub_producer_released_commission_cents": released_commission_cents(),
    }
    _stamp(record)
    db.policy_rows()[record["id"]] = record
    return record


def create_agreement(payload):
    record = {
        "id": db.new_id(),
        "agent_id": payload.get("agent_id"),
        "agency_id": payload.get("agency_id"),
        "agreement_type": payload.get("agreement_type") or "EXCLUSIVE_AGENT",
        "status": "UNDER_REVIEW",
        "commission_schedule": payload.get("commission_schedule"),
        "marketing_allowance_pool_cents": Decimal(0),
        "marketing_allowance_spent_cents": Decimal(0),
        "allowance_carryover_cents": Decimal(0),
        "carryover_input_cents": Decimal(0),
        "license_verified_at": None,
        "termination_initiated_at": None,
        "termination_value_cents": Decimal(0),
        "direct_additions_commission_cents": Decimal(0),
        "renewal_commission_cents": Decimal(0),
        "direct_additions_revenue_cents": Decimal(0),
        "staffing_reimbursement_cents": Decimal(0),
    }
    _stamp(record)
    db.agreement_rows()[record["id"]] = record
    return record


def create_staff(payload):
    record = {
        "id": db.new_id(),
        "full_name": payload.get("full_name"),
        "role_title": payload.get("role_title"),
        "allocation_units": payload.get("allocation_units"),
        "agency_id": payload.get("agency_id"),
        "sponsoring_agreement_id": payload.get("sponsoring_agreement_id"),
        "status": "PENDING",
        "allocated_agent_id": payload.get("allocated_agent_id"),
        "assignment_start_date": payload.get("assignment_start_date"),
        "assignment_end_date": payload.get("assignment_end_date"),
    }
    _stamp(record)
    db.staff_rows()[record["id"]] = record
    return record


def create_campaign(agency, payload):
    record = {
        "id": db.new_id(),
        "agency_id": agency["id"],
        "campaign_type": payload.get("campaign_type"),
        "marketing_allowance_cents": round_cents(
            dec(payload.get("marketing_allowance_cents", 0))),
        "expected_leads": payload.get("expected_leads"),
        "status": "PLANNED",
        "participation_posture": participation_posture(agency),
        "start_date": payload.get("start_date"),
        "end_date": payload.get("end_date"),
    }
    _stamp(record)
    db.campaign_rows()[record["id"]] = record
    return record


def participation_posture(agency):
    """Derived from the parent agency's status; gates every campaign write."""
    status = agency.get("status")
    if status in ("APPROVED", "ACTIVE"):
        return "OPEN"
    if status == "TERMINATED":
        return "FROZEN"
    return "RESTRICTED"


def create_claim(payload):
    record = {
        "id": db.new_id(),
        "policy_id": payload.get("policy_id"),
        "claim_amount_cents": round_cents(dec(payload.get("claim_amount_cents", 0))),
        # A freshly filed claim opens with no amount paid: policy_paid_cents is
        # as yet unset (PRD §3.8).
        "policy_paid_cents": None,
        "status": "OPEN",
    }
    _stamp(record)
    db.claim_rows()[record["id"]] = record
    return record


def create_book_transfer(payload):
    record = {
        "id": db.new_id(),
        "agent_id": payload.get("agent_id"),
        "from_agency_id": payload.get("from_agency_id"),
        "to_agency_id": payload.get("to_agency_id"),
        "successor_agent_id": None,
        "transferred_policy_count": 0,
        "retained_policy_count": 0,
        "retention_pct": 0,
        "retention_met": False,
        "settlement_payable_cents": Decimal(0),
        "status": "PENDING",
        "for_cause": bool(payload.get("for_cause", False)),
    }
    _stamp(record)
    db.transfer_rows()[record["id"]] = record
    return record


def create_license_record(payload):
    """LicenseRecord is immutable after posting: id and created_at only."""
    record = {
        "id": db.new_id(),
        "created_at": clock.iso(),
        "agent_id": payload.get("agent_id"),
        "full_name": payload.get("full_name"),
        "state_code": payload.get("state_code"),
        "product_lines": payload.get("product_lines") or [],
        "license_expiry_date": payload.get("license_expiry_date"),
    }
    db.license_rows()[record["id"]] = record
    return record


def create_application(payload):
    record = {
        "id": db.new_id(),
        "state_code": payload.get("state_code"),
        "market_need_score": payload.get("market_need_score"),
        "candidate_assessment_score": payload.get("candidate_assessment_score"),
        "market_odds_score": payload.get("market_odds_score"),
        "status": "SUBMITTED",
        "required_action": None,
        "appointment_priority": None,
        "application_value_tier": None,
        "creation_channel": payload.get("creation_channel"),
        "agent_id": None,
        "closure_note": payload.get("closure_note"),
        "full_name": payload.get("full_name") or payload.get("applicant_name"),
        "territory_subtype": payload.get("territory_subtype")
        or payload.get("subtype") or payload.get("territory_type"),
    }
    _stamp(record)
    db.application_rows()[record["id"]] = record
    return record