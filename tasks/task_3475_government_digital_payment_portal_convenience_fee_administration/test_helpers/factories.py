"""Payload factories — one per creation/action endpoint, input fields only.

Optional fields (``fee_model`` on a service, ``supersedes_account_id`` on a
settlement account, ``card_brand``/``card_cost_bucket`` on an instrument) are
omitted from the payload entirely when set to None, so tests can exercise both
the omitted and supplied forms. Money is always integer cents.
"""

DEFAULTS = {
    # agency
    "LEGAL_NAME": "Department of Public Safety",
    "AGENCY_TYPE": "STATE",
    "DEFAULT_FEE_MODEL": "CONVENIENCE_FEE",
    # settlement account
    "ROUTING_NUMBER": "021000021",
    "ACCOUNT_NUMBER_LAST4": "4321",
    "ACCOUNT_EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    # attestation
    "ATTESTATION_TYPE": "PCI_DSS_AOC",
    "ISSUED_AT": "2026-08-01T00:00:00Z",
    "ATTESTATION_EXPIRES_AT": "2027-08-01T00:00:00Z",
    # service
    "SERVICE_CODE": "DL-RENEW",
    "SERVICE_NAME": "Driver License Renewal",
    "ALLOWED_METHODS": ["CARD", "ECHECK", "WALLET"],
    "MIN_AMOUNT_CENTS": 100,
    "MAX_AMOUNT_CENTS": 1000000,
    "GL_CODE": "4110",
    # statutory authorization
    "STATUTE_CITATION": "62 O.S. 34.9",
    "DISCLOSURE_TEXT_VERSION": "D1",
    "FEE_CAP_CENTS": 5000,
    "AUTHZ_EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "AUTHZ_EFFECTIVE_TO": "2027-12-31T00:00:00Z",
    # payer
    "FULL_NAME": "Pat Parker",
    "EMAIL": "pat@example.com",
    "BILLING_ZIP": "73102",
    # refund / chargeback
    "REFUND_REASON": "overpayment",
    "EVIDENCE_NOTE": "Signed receipt and delivery log attached",
    "RESOLUTION_NOTE": "reconciled after treasury review",
}


def create_agency_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "agency_type": DEFAULTS["AGENCY_TYPE"],
        "default_fee_model": DEFAULTS["DEFAULT_FEE_MODEL"],
    }
    payload.update(overrides)
    return payload


def create_settlement_account_payload(agency_id, expected_agency_version, **overrides) -> dict:
    """``expected_agency_version`` is a non-optional OCC input per the PRD."""
    payload = {
        "agency_id": agency_id,
        "routing_number": DEFAULTS["ROUTING_NUMBER"],
        "account_number_last4": DEFAULTS["ACCOUNT_NUMBER_LAST4"],
        "effective_from": DEFAULTS["ACCOUNT_EFFECTIVE_FROM"],
        "expected_agency_version": expected_agency_version,
    }
    payload.update(overrides)
    if payload.get("supersedes_account_id") is None:
        payload.pop("supersedes_account_id", None)
    return payload


def verify_account_payload(outcome="SUCCESS", **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def create_pricing_tier_payload(agency_id, **overrides) -> dict:
    payload = {
        "agency_id": agency_id,
        "volume_min_cents": 0,
        "volume_max_cents": 500000,
        "rate_bp": 250,
        "per_txn_cents": 20,
        "effective_month": "2026-09",
    }
    payload.update(overrides)
    return payload


def create_attestation_payload(agency_id, **overrides) -> dict:
    payload = {
        "agency_id": agency_id,
        "attestation_type": DEFAULTS["ATTESTATION_TYPE"],
        "issued_at": DEFAULTS["ISSUED_AT"],
        "expires_at": DEFAULTS["ATTESTATION_EXPIRES_AT"],
    }
    payload.update(overrides)
    return payload


def create_service_payload(agency_id, **overrides) -> dict:
    """``fee_model`` omitted means the service inherits the agency default."""
    payload = {
        "agency_id": agency_id,
        "service_code": DEFAULTS["SERVICE_CODE"],
        "name": DEFAULTS["SERVICE_NAME"],
        "allowed_methods": list(DEFAULTS["ALLOWED_METHODS"]),
        "min_amount_cents": DEFAULTS["MIN_AMOUNT_CENTS"],
        "max_amount_cents": DEFAULTS["MAX_AMOUNT_CENTS"],
        "gl_code": DEFAULTS["GL_CODE"],
    }
    payload.update(overrides)
    if payload.get("fee_model") is None:
        payload.pop("fee_model", None)
    return payload


def update_service_payload(expected_service_version, **overrides) -> dict:
    """Repricing update; ``expected_service_version`` is the OCC input."""
    payload = {"expected_service_version": expected_service_version}
    payload.update(overrides)
    return payload


def create_statutory_authorization_payload(service_id, **overrides) -> dict:
    payload = {
        "service_id": service_id,
        "statute_citation": DEFAULTS["STATUTE_CITATION"],
        "disclosure_text_version": DEFAULTS["DISCLOSURE_TEXT_VERSION"],
        "fee_cap_cents": DEFAULTS["FEE_CAP_CENTS"],
        "effective_from": DEFAULTS["AUTHZ_EFFECTIVE_FROM"],
        "effective_to": DEFAULTS["AUTHZ_EFFECTIVE_TO"],
    }
    payload.update(overrides)
    return payload


def create_payer_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["FULL_NAME"],
        "email": DEFAULTS["EMAIL"],
        "billing_zip": DEFAULTS["BILLING_ZIP"],
    }
    payload.update(overrides)
    return payload


def create_instrument_payload(method="CARD", last4="4242", **overrides) -> dict:
    """card_brand / card_cost_bucket are required iff method == CARD and
    forbidden otherwise; they are only emitted when supplied."""
    payload = {"method": method, "last4": last4}
    payload.update(overrides)
    if payload.get("card_brand") is None:
        payload.pop("card_brand", None)
    if payload.get("card_cost_bucket") is None:
        payload.pop("card_cost_bucket", None)
    return payload


def verify_ach_payload(outcome="SUCCESS", **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def create_fee_quote_payload(service_id, amount_cents, method, **overrides) -> dict:
    payload = {
        "service_id": service_id,
        "amount_cents": amount_cents,
        "method": method,
    }
    payload.update(overrides)
    return payload


def authorize_payment_payload(quote_id, instrument_id, **overrides) -> dict:
    payload = {"quote_id": quote_id, "instrument_id": instrument_id}
    payload.update(overrides)
    return payload


def create_settlement_batch_payload(agency_id, business_date, **overrides) -> dict:
    payload = {"agency_id": agency_id, "business_date": business_date}
    payload.update(overrides)
    return payload


def confirm_deposit_payload(actual_deposit_cents, **overrides) -> dict:
    payload = {"actual_deposit_cents": actual_deposit_cents}
    payload.update(overrides)
    return payload


def resolve_exception_payload(resolution_note=None, **overrides) -> dict:
    payload = {"resolution_note": resolution_note or DEFAULTS["RESOLUTION_NOTE"]}
    payload.update(overrides)
    return payload


def create_refund_payload(transaction_id, amount_cents, **overrides) -> dict:
    payload = {
        "transaction_id": transaction_id,
        "amount_cents": amount_cents,
        "reason": DEFAULTS["REFUND_REASON"],
    }
    payload.update(overrides)
    return payload


def decide_refund_payload(decision="APPROVE", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_chargeback_payload(transaction_id, reason_code="FRAUD", **overrides) -> dict:
    payload = {"transaction_id": transaction_id, "reason_code": reason_code}
    payload.update(overrides)
    return payload


def contest_chargeback_payload(evidence_note=None, **overrides) -> dict:
    payload = {"evidence_note": evidence_note or DEFAULTS["EVIDENCE_NOTE"]}
    payload.update(overrides)
    return payload


def record_outcome_payload(outcome="WON", **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def close_period_payload(period="2026-09", **overrides) -> dict:
    payload = {"period": period}
    payload.update(overrides)
    return payload
