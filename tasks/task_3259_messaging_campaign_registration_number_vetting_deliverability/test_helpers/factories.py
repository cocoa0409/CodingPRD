"""Payload factories — input fields only, sensible defaults per profile.

The named brand profiles encode the PRD section 3.2 identity-score
formula so that a test can request a brand that scores a known value:
  - profile "high95":     PUBLIC_PROFIT + website + valid EIN + valid US
                          ZIP + WEB_FORM = 50+10+10+10+10+5 = 95
  - profile "charity90":  NON_PROFIT + website + valid EIN + valid US
                          ZIP + POINT_OF_SALE = 50+10+5+10+10+5 = 90
  - profile "high75":     PUBLIC_PROFIT + website + WEB_FORM,
                          invalid tax/postal = 50+10+10+5 = 75
  - profile "mid70":      PUBLIC_PROFIT + website + KEYWORD,
                          invalid tax/postal = 50+10+10 = 70
  - profile "low50":      PRIVATE_PROFIT, empty website, invalid
                          tax/postal, KEYWORD = 50
"""

from .constants import (
    BUSINESS_NON_PROFIT,
    BUSINESS_PRIVATE_PROFIT,
    BUSINESS_PUBLIC_PROFIT,
    CARRIER_VZW,
    CLOCK_INITIAL_INSTANT,
    COUNTRY_US,
    OPT_IN_KEYWORD,
    OPT_IN_POINT_OF_SALE,
    OPT_IN_WEB_FORM,
    PATH_TEN_DLC,
    PLAN_PREMIUM,
    PLAN_STANDARD,
    USE_CASE_MARKETING,
)

_BRAND_PROFILES = {
    "high95": {
        "legal_name": "Acme Corp",
        "tax_id": "12-3456789",
        "business_type": BUSINESS_PUBLIC_PROFIT,
        "address_line1": "1 Main St",
        "city": "Springfield",
        "region_code": "IL",
        "postal_code": "62701",
        "country_code": COUNTRY_US,
        "website_url": "https://acme.example",
        "opt_in_mechanism": OPT_IN_WEB_FORM,
    },
    "charity90": {
        "legal_name": "Charity Inc",
        "tax_id": "98-7654321",
        "business_type": BUSINESS_NON_PROFIT,
        "address_line1": "2 Oak St",
        "city": "Springfield",
        "region_code": "IL",
        "postal_code": "62702",
        "country_code": COUNTRY_US,
        "website_url": "https://charity.example",
        "opt_in_mechanism": OPT_IN_POINT_OF_SALE,
    },
    "high75": {
        "legal_name": "High Corp",
        "tax_id": "X",
        "business_type": BUSINESS_PUBLIC_PROFIT,
        "address_line1": "1 Main",
        "city": "SF",
        "region_code": "CA",
        "postal_code": "X",
        "country_code": COUNTRY_US,
        "website_url": "https://h.example",
        "opt_in_mechanism": OPT_IN_WEB_FORM,
    },
    "mid70": {
        "legal_name": "Mid Corp",
        "tax_id": "X",
        "business_type": BUSINESS_PUBLIC_PROFIT,
        "address_line1": "2 Main",
        "city": "SF",
        "region_code": "CA",
        "postal_code": "X",
        "country_code": COUNTRY_US,
        "website_url": "https://m.example",
        "opt_in_mechanism": OPT_IN_KEYWORD,
    },
    "low50": {
        "legal_name": "Mystery LLC",
        "tax_id": "X",
        "business_type": BUSINESS_PRIVATE_PROFIT,
        "address_line1": "1 Main St",
        "city": "Springfield",
        "region_code": "IL",
        "postal_code": "X",
        "country_code": COUNTRY_US,
        "website_url": "",
        "opt_in_mechanism": OPT_IN_KEYWORD,
    },
}


def account_payload(**overrides):
    """Defaults: PREMIUM US account."""
    payload = {
        "name": "Acme",
        "plan_tier": PLAN_PREMIUM,
        "country_code": COUNTRY_US,
    }
    payload.update(overrides)
    return payload


def standard_account_payload(**overrides):
    """STANDARD-tier US account."""
    payload = account_payload(plan_tier=PLAN_STANDARD)
    payload.update(overrides)
    return payload


def brand_payload(profile="high95", **overrides):
    """Brand payload from a named scoring profile."""
    payload = dict(_BRAND_PROFILES[profile])
    payload.update(overrides)
    return payload


def campaign_payload(brand_id, path_kind=PATH_TEN_DLC, **overrides):
    """Defaults: MARKETING TEN_DLC campaign with valid review content."""
    payload = {
        "brand_id": brand_id,
        "use_case": USE_CASE_MARKETING,
        "description": "Promos",
        "sample_messages": ["Hi"],
        "help_message": "Reply HELP",
        "stop_message": "Reply STOP",
        "path_kind": path_kind,
    }
    payload.update(overrides)
    return payload


def number_payload(number_type="TEN_DLC", **overrides):
    """Defaults: new-purchase US TEN_DLC number."""
    payload = {
        "phone_number": "+15551234567",
        "number_type": number_type,
        "country_code": COUNTRY_US,
    }
    payload.update(overrides)
    return payload


def port_in_payload(**overrides):
    """A complete port-in request payload."""
    payload = {
        "phone_number": "+15551230000",
        "number_type": "TEN_DLC",
        "country_code": COUNTRY_US,
        "port_phone_number": "+15551230000",
        "port_letter_of_agency": "loa-ref-1",
        "port_losing_carrier": "OldCarrier",
    }
    payload.update(overrides)
    return payload


def consent_payload(brand_id, phone_number, **overrides):
    """Defaults: WEB_FORM consent captured at the initial clock instant."""
    payload = {
        "brand_id": brand_id,
        "phone_number": phone_number,
        "evidence_url": "https://evidence/1",
        "evidence_text": "web form",
        "captured_at": CLOCK_INITIAL_INSTANT,
        "consent_method": OPT_IN_WEB_FORM,
    }
    payload.update(overrides)
    return payload


def message_payload(campaign_id, sender_number_id, to_number, **overrides):
    """Defaults: short GSM-7 body over VZW."""
    payload = {
        "campaign_id": campaign_id,
        "sender_number_id": sender_number_id,
        "to_number": to_number,
        "body": "Hello",
        "carrier_code": CARRIER_VZW,
    }
    payload.update(overrides)
    return payload


def feedback_payload(campaign_id, kind, **overrides):
    payload = {"campaign_id": campaign_id, "kind": kind}
    payload.update(overrides)
    return payload
