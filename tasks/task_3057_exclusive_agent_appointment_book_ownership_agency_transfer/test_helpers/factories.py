"""Payload factories — one per entity, input fields only."""

COMMISSION_SCHEDULE = {
    "AUTO": {"new": 0.15, "renewal": 0.10},
    "HOME": {"new": 0.12, "renewal": 0.08},
    "LIFE": {"new": 0.25, "renewal": 0.15},
}

# An intentionally incomplete schedule (LIFE omitted) for schedule-coverage checks.
COMMISSION_SCHEDULE_INCOMPLETE = {
    "AUTO": {"new": 0.15, "renewal": 0.10},
    "HOME": {"new": 0.12, "renewal": 0.08},
}


def create_agency_payload(**overrides) -> dict:
    defaults = {
        "agency_code": "CA-900",
        "name": "Test Agency",
        "region_code": "W",
        "market_need_score": 60,
    }
    defaults.update(overrides)
    return defaults


def create_appointment_application_payload(**overrides) -> dict:
    defaults = {
        "state_code": "CA",
        "market_need_score": 55,
        "candidate_assessment_score": 80,
        "market_odds_score": 80,
        "creation_channel": "FIELD",
    }
    defaults.update(overrides)
    default_territory = {
        "territory_subtype": "SUPPORT" if defaults["market_need_score"] <= 40 else "STANDARD",
    }
    for key, value in default_territory.items():
        defaults.setdefault(key, value)
    return defaults


def create_agreement_payload(agent_id: str, agency_id: str, **overrides) -> dict:
    defaults = {
        "agent_id": agent_id,
        "agency_id": agency_id,
        "agreement_type": "EXCLUSIVE_AGENT",
        "commission_schedule": dict(COMMISSION_SCHEDULE),
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(holder_agent_id: str, owner_agency_id: str, **overrides) -> dict:
    defaults = {
        "policy_number": "T-P1",
        "product_line": "AUTO",
        "annual_premium_cents": 500_000,
        "is_new_business": False,
        "holder_agent_id": holder_agent_id,
        "owner_agency_id": owner_agency_id,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(policy_id: str, **overrides) -> dict:
    defaults = {
        "policy_id": policy_id,
        "claim_amount_cents": 40_000,
    }
    defaults.update(overrides)
    return defaults


def create_campaign_payload(**overrides) -> dict:
    defaults = {
        "campaign_type": "LEAD_PROGRAM",
        "marketing_allowance_cents": 10_000,
        "expected_leads": 10,
        "start_date": "2026-09-02T00:00:00Z",
        "end_date": "2026-09-30T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_staff_payload(sponsoring_agreement_id: str, **overrides) -> dict:
    defaults = {
        "full_name": "Test Member",
        "role_title": "CSR",
        "allocation_units": 8,
        "sponsoring_agreement_id": sponsoring_agreement_id,
    }
    defaults.update(overrides)
    return defaults


def create_book_transfer_payload(from_agency_id: str, to_agency_id: str, **overrides) -> dict:
    defaults = {
        "from_agency_id": from_agency_id,
        "to_agency_id": to_agency_id,
    }
    defaults.update(overrides)
    return defaults


def inject_agent_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Injected Agent",
        "state_code": "CA",
        "license_status": "LICENSED",
        "is_new_agent": False,
        "status": "ACTIVE",
    }
    defaults.update(overrides)
    return defaults


def license_record_payload(full_name="Licensed Person", state_code="CA", **overrides) -> dict:
    defaults = {
        "full_name": full_name,
        "state_code": state_code,
        "product_lines": ["AUTO", "HOME", "LIFE"],
        "license_expiry_date": "2028-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def read_license_payload(**overrides) -> dict:
    defaults = {
        "license_expiry_date": "2028-01-01T00:00:00Z",
        "product_lines": ["AUTO", "HOME", "LIFE"],
    }
    defaults.update(overrides)
    return defaults