"""Payload factories — one per entity, input fields only (PRD §3/§4)."""
import itertools
import uuid

_code_counter = itertools.count(1)
_store_counter = itertools.count(1)


def _seq(counter):
    return next(counter)


def create_territory_payload(**overrides) -> dict:
    defaults = {
        "code": f"T-{uuid.uuid4().hex[:8].upper()}",
        "region": "North East",
        "royalty_rate_pct": 0.08,
        "development_quota_stores": 3,
    }
    defaults.update(overrides)
    return defaults


def create_development_agent_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Keystone Development Partners",
        "contact_email": f"da-{uuid.uuid4().hex[:8]}@example.com",
        "agreement_start": "2026-01-01T00:00:00Z",
        "agreement_end": "2031-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_franchisee_payload(**overrides) -> dict:
    defaults = {
        "legal_name": f"Franchisee {_seq(_code_counter)} LLC",
        "contact_email": f"f-{uuid.uuid4().hex[:8]}@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_store_payload(territory_id, franchisee_id, **overrides) -> dict:
    defaults = {
        "store_number": f"S-{_seq(_store_counter):04d}",
        "territory_id": territory_id,
        "franchisee_id": franchisee_id,
        "address": "1 Main St",
        "geo_lat": 40.0,
        "geo_lng": -75.0,
        "opened_on": "2020-01-01T00:00:00Z",
        "estimated_weekly_sales_cents": 1_000_000,
        "actual_avg_weekly_sales_cents": 1_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_site_application_payload(territory_id, applicant_franchisee_id,
                                    expected_territory_version, **overrides) -> dict:
    defaults = {
        "territory_id": territory_id,
        "applicant_franchisee_id": applicant_franchisee_id,
        "proposed_address": "9 Oak Ave",
        "proposed_lat": 40.012,
        "proposed_lng": -75.0,
        "proposed_open_date": "2027-01-01T00:00:00Z",
        "expected_territory_version": expected_territory_version,
    }
    defaults.update(overrides)
    return defaults


def create_impact_study_payload(**overrides) -> dict:
    defaults = {"radius_miles": 2.0}
    defaults.update(overrides)
    return defaults


def create_protest_payload(site_application_id, protesting_store_id, **overrides) -> dict:
    defaults = {
        "site_application_id": site_application_id,
        "protesting_store_id": protesting_store_id,
        "grounds": "encroachment",
    }
    defaults.update(overrides)
    return defaults


def create_transfer_request_payload(store_id, buyer_franchisee_id,
                                    expected_store_version, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "buyer_franchisee_id": buyer_franchisee_id,
        "sale_price_cents": 40_000_000,
        "expected_store_version": expected_store_version,
    }
    defaults.update(overrides)
    return defaults


def create_training_enrollment_payload(franchisee_id, **overrides) -> dict:
    defaults = {
        "franchisee_id": franchisee_id,
        "program_code": "TRANSFER_BUYER",
        "expires_on": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_remodel_mandate_payload(store_id, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "due_by": "2026-12-31T00:00:00Z",
        "financing_option": "SELF_FINANCED",
        "estimated_cost_cents": 5_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(store_id, inspector_ref, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "scheduled_on": "2026-09-02T00:00:00Z",
        "inspector_ref": inspector_ref,
    }
    defaults.update(overrides)
    return defaults


def create_promotion_payload(**overrides) -> dict:
    defaults = {
        "name": f"Promo {uuid.uuid4().hex[:6]}",
        "voting_open": "2026-09-01T00:00:00Z",
        "voting_close": "2026-09-10T00:00:00Z",
        "active_start": "2026-10-01T00:00:00Z",
        "active_end": "2026-11-01T00:00:00Z",
        "base_cost_per_store_cents": 200_000,
    }
    defaults.update(overrides)
    return defaults


def create_vote_payload(store_id, ballot="FOR", **overrides) -> dict:
    defaults = {"store_id": store_id, "ballot": ballot}
    defaults.update(overrides)
    return defaults


def create_funding_dispute_payload(promotion_id, store_id, disputed_amount_cents,
                                   **overrides) -> dict:
    defaults = {
        "promotion_id": promotion_id,
        "store_id": store_id,
        "disputed_amount_cents": disputed_amount_cents,
        "reason": "disputed share",
    }
    defaults.update(overrides)
    return defaults


def create_fee_statement_payload(development_agent_id, territory_id, **overrides) -> dict:
    defaults = {
        "development_agent_id": development_agent_id,
        "territory_id": territory_id,
        "period_start": "2026-09-01T00:00:00Z",
        "period_end": "2026-09-29T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
