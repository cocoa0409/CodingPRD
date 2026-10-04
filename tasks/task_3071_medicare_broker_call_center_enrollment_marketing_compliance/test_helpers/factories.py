"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


# ─── Agency ──────────────────────────────────────────────────

def create_agency_payload(**overrides) -> dict:
    defaults = {
        "name": "Alpine Senior Benefits LLC",
        "service_center_code": "ALP-DAL-01",
        "aep_start_date": "2026-10-15T00:00:00Z",
        "aep_end_date": "2026-12-07T00:00:00Z",
        "aep_daily_submission_capacity": TEST_DEFAULTS["AEP_DAILY_SUBMISSION_CAPACITY"],
        "recording_retention_days": 2555,
        "soa_retention_days": 3650,
        "soa_max_age_days": 30,
        "rapid_disenrollment_day_limit": 90,
    }
    defaults.update(overrides)
    return defaults


# ─── Carrier ─────────────────────────────────────────────────

def create_carrier_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Meridian Health Plan of Texas",
        "naic_number": "60211",
        "contract_type": "CONTRACTED",
        "initial_commission_rate_pct": TEST_DEFAULTS["INITIAL_COMMISSION_RATE_PCT"],
        "renewal_commission_rate_pct": TEST_DEFAULTS["RENEWAL_COMMISSION_RATE_PCT"],
        "chargeback_clawback_pct": TEST_DEFAULTS["CHARGEBACK_CLAWBACK_PCT"],
        "ack_expected_within_days": 5,
        "effectuation_expected_within_days": 30,
    }
    defaults.update(overrides)
    return defaults


# ─── Agent ───────────────────────────────────────────────────

def create_agent_payload(agency_id: str, **overrides) -> dict:
    defaults = {
        "agency_id": agency_id,
        "full_name": "Marcus Reed",
        "national_producer_number": "8841002",
        "hire_date": "2026-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_license_payload(**overrides) -> dict:
    defaults = {
        "state_code": "TX",
        "license_number": "TX-LIC-77031",
        "issued_on": "2026-08-05T00:00:00Z",
        "expires_on": "2027-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_certification_payload(carrier_id: str, **overrides) -> dict:
    defaults = {
        "carrier_id": carrier_id,
        "product_type": "MAPD",
        "expires_on": "2027-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(carrier_id: str, **overrides) -> dict:
    defaults = {
        "carrier_id": carrier_id,
        "state_code": "TX",
        "requested_on": "2026-09-20T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


# ─── Member ──────────────────────────────────────────────────

def create_member_payload(agency_id: str, **overrides) -> dict:
    defaults = {
        "agency_id": agency_id,
        "full_name": "Ada Whitfield",
        "medicare_beneficiary_id": "1EG4-TE5-MK72",
        "date_of_birth": "1954-03-11T00:00:00Z",
        "state_code": "TX",
        "county_code": "TX-201",
        "drug_list": [
            {"drug_name": "Lisinopril 10mg", "rxcui": "314076", "monthly_fills": 1},
        ],
        "provider_npis": ["1000000001"],
    }
    defaults.update(overrides)
    return defaults


# ─── Scope of appointment ────────────────────────────────────

def create_scope_payload(member_id: str, agent_id: str, member_version: int,
                         **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "agent_id": agent_id,
        "capture_channel": "TELEPHONIC_RECORDED",
        "plan_types_authorized": ["MA", "MAPD"],
        "captured_on": "2026-10-01T00:00:00Z",
        "expected_member_version": member_version,
    }
    defaults.update(overrides)
    return defaults


# ─── Call session ────────────────────────────────────────────

def create_call_session_payload(agent_id: str, member_id: str, scope_id: str,
                                **overrides) -> dict:
    defaults = {
        "agent_id": agent_id,
        "member_id": member_id,
        "scope_of_appointment_id": scope_id,
        "started_at": "2026-10-01T09:00:00Z",
        "scheduled_end_at": "2026-10-01T09:30:00Z",
        "recording_id": "REC-1001",
        "disclaimer_script_code": "CMS-DISC-2026",
        "disclaimer_delivered": True,
        "marketing_rule_set_version": "MKT-2026-V3",
    }
    defaults.update(overrides)
    return defaults


def connect_call_payload(**overrides) -> dict:
    defaults = {
        "disclaimer_delivered": True,
        "plan_type_discussed": "MAPD",
        "recording_id": "REC-1001",
        "disclaimer_script_code": "CMS-DISC-2026",
        "marketing_rule_set_version": "MKT-2026-V3",
    }
    defaults.update(overrides)
    return defaults


def complete_call_payload(**overrides) -> dict:
    defaults = {"recording_id": "REC-1001", "disclaimer_delivered": True}
    defaults.update(overrides)
    return defaults


# ─── Plan ────────────────────────────────────────────────────

def create_plan_payload(carrier_id: str, **overrides) -> dict:
    defaults = {
        "carrier_id": carrier_id,
        "plan_id_code": "MER-H0021-001",
        "plan_type": TEST_DEFAULTS["PLAN_TYPE"],
        "state_code": TEST_DEFAULTS["STATE_CODE"],
        "county_code": TEST_DEFAULTS["COUNTY_CODE"],
        "monthly_premium_cents": TEST_DEFAULTS["MONTHLY_PREMIUM_CENTS"],
        "annual_drug_deductible_cents": TEST_DEFAULTS["ANNUAL_DRUG_DEDUCTIBLE_CENTS"],
        "star_rating": TEST_DEFAULTS["STAR_RATING"],
        "formulary_id": "FORM-2026-V1",
        "pharmacy_network_id": "PHARM-2026-V1",
        "provider_directory_id": "PROV-2026-V1",
    }
    defaults.update(overrides)
    return defaults


def create_formulary_drug_payload(**overrides) -> dict:
    defaults = {
        "drug_name": "Lisinopril 10mg",
        "rxcui": "314076",
        "tier": 1,
        "monthly_copay_cents": 200,
        "prior_authorization_required": False,
        "covered": True,
        "quantity_limit_days": 30,
    }
    defaults.update(overrides)
    return defaults


def create_pharmacy_network_entry_payload(**overrides) -> dict:
    defaults = {
        "pharmacy_npi": "3000000001",
        "pharmacy_name": "Alpine Drug Mart",
        "network_tier": "PREFERRED",
        "cost_share_multiplier_pct": 1.0,
    }
    defaults.update(overrides)
    return defaults


def create_provider_directory_entry_payload(**overrides) -> dict:
    defaults = {
        "provider_npi": "1000000001",
        "provider_name": "Dr Alvarez",
        "specialty": "Internal Medicine",
        "network_status": "IN_NETWORK",
        "accepting_new_patients": True,
        "last_attested_on": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


# ─── Plan comparison ─────────────────────────────────────────

def create_plan_comparison_payload(member_id: str, agent_id: str,
                                   scope_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "agent_id": agent_id,
        "scope_of_appointment_id": scope_id,
    }
    defaults.update(overrides)
    return defaults


# ─── Enrollment ──────────────────────────────────────────────

def create_enrollment_payload(call_session_id: str, member_id: str, plan_id: str,
                              agent_id: str, scope_id: str,
                              call_session_version: int, **overrides) -> dict:
    defaults = {
        "call_session_id": call_session_id,
        "member_id": member_id,
        "plan_id": plan_id,
        "agent_id": agent_id,
        "scope_of_appointment_id": scope_id,
        "effective_date": "2026-11-01T00:00:00Z",
        "plan_type_discussed": "MAPD",
        "expected_call_session_version": call_session_version,
    }
    defaults.update(overrides)
    return defaults


# ─── Commission ledger / reconciliation ──────────────────────

def create_ledger_entry_payload(enrollment_id: str, reconciliation_id: str,
                                **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "carrier_reconciliation_id": reconciliation_id,
        "entry_type": "ADJUSTMENT",
        "period_month": "2026-10",
    }
    defaults.update(overrides)
    return defaults


def create_correction_payload(enrollment_id: str, reconciliation_id: str,
                              **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "carrier_reconciliation_id": reconciliation_id,
        "amount_cents": -500,
        "period_month": "2026-10",
        "memo": "Operator correction",
    }
    defaults.update(overrides)
    return defaults


def create_reconciliation_payload(carrier_id: str, **overrides) -> dict:
    defaults = {
        "carrier_id": carrier_id,
        "period_month": "2026-10",
        "carrier_reported_total_cents": 5000,
        "internal_total_variant": "PROVISIONAL",
    }
    defaults.update(overrides)
    return defaults


# ─── Complaint ───────────────────────────────────────────────

def create_complaint_payload(agent_id: str, **overrides) -> dict:
    defaults = {
        "agent_id": agent_id,
        "complaint_type": "MISREPRESENTATION",
        "source": "CMS",
        "severity": "HIGH",
        "filed_on": "2026-09-28T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


# ─── Coaching ────────────────────────────────────────────────

def create_coaching_assignment_payload(agent_id: str, **overrides) -> dict:
    defaults = {
        "agent_id": agent_id,
        "coaching_type": "SOA_RETRAINING",
    }
    defaults.update(overrides)
    return defaults


__all__ = [name for name in dir() if not name.startswith("_")]