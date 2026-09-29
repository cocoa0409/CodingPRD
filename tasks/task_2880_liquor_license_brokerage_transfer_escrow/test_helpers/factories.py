"""Payload factories — one per creating operation, input fields only.

All monetary amounts are integer counts of whole cents sent as JSON numbers;
no amount is ever transported as a string. All instants are full ISO 8601 UTC
instants; ``last_active_date`` is the only date-only field in the API and uses
``YYYY-MM-DD``.
"""

DEFAULTS = {
    "COUNTY_CODE": "SON",
    "COUNTY_NAME": "Sonoma",
    "STATE_CODE": "CA",
    "QUOTA_LICENSES_TOTAL": 100,
    "SELLER_LEGAL_NAME": "Vine Holdings LLC",
    "SELLER_CONTACT_EMAIL": "seller@example.com",
    "BUYER_LEGAL_NAME": "Harbor Hospitality LLC",
    "FIRM_NAME": "Bay Brokers",
    "STATE_BROKER_LICENSE_NO": "BRK-0001",
    "COMMISSION_RATE_BPS": 575,
    "LICENSE_NUMBER": "SON-47-1",
    "LICENSE_CLASS": "CLASS_47_ONSALE_GENERAL",
    "ANNUAL_GROSS_RECEIPTS_CENTS": 120000000,
    "LAST_ACTIVE_DATE": "2026-07-01",
    "ADDRESS_LINE": "12 Vine St",
    "ZONING_CODE": "C1",
    "DISTANCE_FEET": 900,
    "ASK_PRICE_CENTS": 18500000,
    "PURCHASE_PRICE_CENTS": 18500010,
    "DEPOSIT_PCT_BPS": 1000,
    "CLOSING_WINDOW_START": "2026-09-01T00:00:00Z",
    "PROTESTANT_NAME": "Neighbourhood Association",
    "PROTEST_GROUNDS": "PUBLIC_WELFARE",
    "REQUESTED_MONTHS": 12,
}


def create_county_payload(**overrides) -> dict:
    payload = {
        "county_code": DEFAULTS["COUNTY_CODE"],
        "name": DEFAULTS["COUNTY_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
        "quota_licenses_total": DEFAULTS["QUOTA_LICENSES_TOTAL"],
    }
    payload.update(overrides)
    return payload


def create_seller_profile_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["SELLER_LEGAL_NAME"],
        "contact_email": DEFAULTS["SELLER_CONTACT_EMAIL"],
        "tax_clearance_status": "CLEARED",
    }
    payload.update(overrides)
    return payload


def create_buyer_profile_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["BUYER_LEGAL_NAME"],
        "entity_type": "LLC",
        "residency_state": DEFAULTS["STATE_CODE"],
        "citizenship_verified": True,
    }
    payload.update(overrides)
    return payload


def qualification_review_payload(premises_id: str, review_mode: str = "FINAL_REVIEW",
                                 **overrides) -> dict:
    payload = {"review_mode": review_mode, "premises_id": premises_id}
    payload.update(overrides)
    return payload


def create_brokerage_payload(**overrides) -> dict:
    payload = {
        "firm_name": DEFAULTS["FIRM_NAME"],
        "state_broker_license_no": DEFAULTS["STATE_BROKER_LICENSE_NO"],
        "commission_rate_bps": DEFAULTS["COMMISSION_RATE_BPS"],
    }
    payload.update(overrides)
    return payload


def create_license_payload(county_id: str, owner_seller_id: str, **overrides) -> dict:
    payload = {
        "county_id": county_id,
        "owner_seller_id": owner_seller_id,
        "license_number": DEFAULTS["LICENSE_NUMBER"],
        "license_class": DEFAULTS["LICENSE_CLASS"],
        "annual_gross_receipts_cents": DEFAULTS["ANNUAL_GROSS_RECEIPTS_CENTS"],
        "last_active_date": DEFAULTS["LAST_ACTIVE_DATE"],
    }
    payload.update(overrides)
    return payload


def create_premises_payload(buyer_id: str, county_id: str, **overrides) -> dict:
    payload = {
        "buyer_id": buyer_id,
        "county_id": county_id,
        "address_line": DEFAULTS["ADDRESS_LINE"],
        "zoning_code": DEFAULTS["ZONING_CODE"],
        "distance_to_nearest_school_feet": DEFAULTS["DISTANCE_FEET"],
        "distance_to_nearest_church_feet": DEFAULTS["DISTANCE_FEET"],
    }
    payload.update(overrides)
    return payload


def zoning_verification_payload(conditional_use_permit_status: str = "GRANTED",
                                **overrides) -> dict:
    payload = {"conditional_use_permit_status": conditional_use_permit_status}
    payload.update(overrides)
    return payload


def landlord_consent_payload(landlord_consent_status: str = "GRANTED",
                             **overrides) -> dict:
    payload = {"landlord_consent_status": landlord_consent_status}
    payload.update(overrides)
    return payload


def create_listing_payload(license_id: str, brokerage_id: str, **overrides) -> dict:
    payload = {
        "license_id": license_id,
        "brokerage_id": brokerage_id,
        "ask_price_cents": DEFAULTS["ASK_PRICE_CENTS"],
    }
    payload.update(overrides)
    return payload


def activate_listing_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


def withdraw_listing_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


def create_purchase_agreement_payload(listing_id: str, buyer_id: str, premises_id: str,
                                      expected_listing_version: int,
                                      **overrides) -> dict:
    payload = {
        "listing_id": listing_id,
        "buyer_id": buyer_id,
        "premises_id": premises_id,
        "purchase_price_cents": DEFAULTS["PURCHASE_PRICE_CENTS"],
        "deposit_pct_bps": DEFAULTS["DEPOSIT_PCT_BPS"],
        "closing_window_start": DEFAULTS["CLOSING_WINDOW_START"],
        "expected_listing_version": expected_listing_version,
    }
    payload.update(overrides)
    return payload


def escrow_deposit_payload(amount_cents: int, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def terminate_agreement_payload(reason: str = "buyer withdrew", **overrides) -> dict:
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


def escrow_settlement_payload(disposition: str, **overrides) -> dict:
    payload = {"disposition": disposition}
    payload.update(overrides)
    return payload


def create_disclosure_payload(agreement_id: str, represents_seller: bool = True,
                              represents_buyer: bool = False, **overrides) -> dict:
    payload = {
        "agreement_id": agreement_id,
        "represents_seller": represents_seller,
        "represents_buyer": represents_buyer,
    }
    payload.update(overrides)
    return payload


def acknowledge_disclosure_payload(party: str, **overrides) -> dict:
    payload = {"party": party}
    payload.update(overrides)
    return payload


def create_transfer_application_payload(agreement_id: str, fee_paid_cents: int,
                                        **overrides) -> dict:
    payload = {"agreement_id": agreement_id, "fee_paid_cents": fee_paid_cents}
    payload.update(overrides)
    return payload


def deficiency_payload(deficiency_codes=None, **overrides) -> dict:
    payload = {"deficiency_codes": list(deficiency_codes or ["MISSING_LEASE"])}
    payload.update(overrides)
    return payload


def resubmit_application_payload(fee_paid_cents: int, **overrides) -> dict:
    payload = {"fee_paid_cents": fee_paid_cents}
    payload.update(overrides)
    return payload


def decision_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_protest_payload(application_id: str, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "protestant_name": DEFAULTS["PROTESTANT_NAME"],
        "grounds": DEFAULTS["PROTEST_GROUNDS"],
    }
    payload.update(overrides)
    return payload


def protest_response_payload(response_text_ref: str = "resp-1", **overrides) -> dict:
    payload = {"response_text_ref": response_text_ref}
    payload.update(overrides)
    return payload


def create_safekeeping_filing_payload(license_id: str, expected_license_version: int,
                                      filing_type: str = "INITIAL",
                                      requested_months: int = None,
                                      **overrides) -> dict:
    payload = {
        "license_id": license_id,
        "filing_type": filing_type,
        "requested_months": (
            DEFAULTS["REQUESTED_MONTHS"] if requested_months is None
            else requested_months
        ),
        "expected_license_version": expected_license_version,
    }
    payload.update(overrides)
    return payload


def safekeeping_decision_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601: str, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
