"""Payload factories — one per entity, input fields only.

Each factory returns a dict ready to POST. Defaults mirror the shapes the PRD
uses in its own examples so that a caller only states the fields a test cares
about. Overrides are applied last, so ``create_property_payload(market="NM-ALBUQUERQUE")``
is the normal idiom.
"""

from .constants import TEST_DEFAULTS


def create_organization_payload(**overrides) -> dict:
    payload = {
        "legal_name": TEST_DEFAULTS["ORG_LEGAL_NAME"],
        "org_type": "DATA_PROVIDER",
        "home_market": TEST_DEFAULTS["HOME_MARKET"],
        "service_tier": "ENTERPRISE",
    }
    payload.update(overrides)
    return payload


def create_user_payload(**overrides) -> dict:
    payload = {
        "email": "dana.reyes@tarrantresearch.example",
        "full_name": "Dana Reyes",
        "role": "RESEARCH_ANALYST",
        "assigned_market": TEST_DEFAULTS["MARKET"],
    }
    payload.update(overrides)
    return payload


def create_property_payload(**overrides) -> dict:
    payload = {
        "market": TEST_DEFAULTS["MARKET"],
        "address_line": "1400 Ross Ave",
        "property_type": "OFFICE",
        "rentable_sqft": TEST_DEFAULTS["RENTABLE_SQFT"],
        # PRD 3.1: "When the caller omits classification, the record is created
        # as CLASS_B." A factory that injected CLASS_A would manufacture a state
        # no PRD-faithful implementation can produce.
        "classification": "CLASS_B",
    }
    payload.update(overrides)
    return payload


def create_source_document_payload(**overrides) -> dict:
    payload = {
        "source_type": "DEED",
        "source_name": "Dallas County Clerk",
        "contact_method": "RECORDS_REQUEST",
        "obtained_at": "2026-08-25T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_attribute_payload(source_document_id: str, **overrides) -> dict:
    payload = {
        "source_document_id": source_document_id,
        "field_name": "tenant_name",
        "value": "",
        "attribute_market": TEST_DEFAULTS["MARKET"],
    }
    payload.update(overrides)
    return payload


def create_lease_comparable_payload(**overrides) -> dict:
    payload = {
        "tenant_name": "Harborline Logistics Inc",
        "lease_start": "2026-06-01T00:00:00Z",
        "lease_end": "2027-06-01T00:00:00Z",
        "escalated_rent_psf": 34.0,
        "effective_rent_psf": 32.0,
        "renewal_option": False,
    }
    payload.update(overrides)
    return payload


def create_sale_transaction_payload(**overrides) -> dict:
    payload = {
        "buyer_name": "Cedar Point Capital",
        "close_date": "2026-08-15T00:00:00Z",
        "gross_sale_price_cents": TEST_DEFAULTS["GROSS_SALE_PRICE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_contract_payload(subscriber_organization_id: str, **overrides) -> dict:
    payload = {
        "subscriber_organization_id": subscriber_organization_id,
        "product": "CORE_MARKET_DATA",
        "licensed_markets": [TEST_DEFAULTS["MARKET"]],
        "seat_count": TEST_DEFAULTS["SEAT_COUNT"],
        "annual_fee_cents": TEST_DEFAULTS["ANNUAL_FEE_CENTS"],
        "auto_renew": True,
        "renewal_notice_days": 30,
        "term_start": "2026-09-01T00:00:00Z",
        "term_end": "2027-09-01T00:00:00Z",
        "audit_intensity": "STANDARD",
    }
    payload.update(overrides)
    return payload


def create_seat_payload(**overrides) -> dict:
    payload = {
        "market": TEST_DEFAULTS["MARKET"],
        "index_tier": "TIER_2",
        "last_usage_cycle": "2026-09-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_usage_event_payload(**overrides) -> dict:
    payload = {
        "market": TEST_DEFAULTS["MARKET"],
        "event_type": "API_QUERY",
        "record_count": 4,
        "distinguishing_ip": "203.0.113.7",
        "occurred_at": "2026-09-02T09:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_enforcement_case_payload(organization_id: str, contract_id: str, **overrides) -> dict:
    payload = {
        "organization_id": organization_id,
        "contract_id": contract_id,
        "case_type": "AUDIT",
        "finding_cents": 60_000_000,
        "fee_rate_pct": 1.25,
    }
    payload.update(overrides)
    return payload


def create_listing_payload(organization_id: str, **overrides) -> dict:
    payload = {
        "organization_id": organization_id,
        "listing_type": "AVAILABLE",
        "monthly_rent_psf": TEST_DEFAULTS["MONTHLY_RENT_PSF"],
        "available_sqft": TEST_DEFAULTS["AVAILABLE_SQFT"],
        "duration_days": TEST_DEFAULTS["DURATION_DAYS"],
    }
    payload.update(overrides)
    return payload


def create_index_run_payload(**overrides) -> dict:
    payload = {
        "market": TEST_DEFAULTS["MARKET"],
        "window_start": "2026-06-01T00:00:00Z",
        "window_end": "2027-06-01T00:00:00Z",
        "adjustment_mode": "UNADJUSTED",
    }
    payload.update(overrides)
    return payload