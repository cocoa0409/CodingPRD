"""Payload factories — one per entity, input fields only."""

DEFAULT_CARRIER = {"legal_name": "Test Carrier Mutual", "naic_code": "99001"}

DEFAULT_CONSUMER = {
    "full_name": "Test Person",
    "date_of_birth": "1985-01-01",
    "address_line": "1 Test St, Austin TX",
    "driver_license_number": "TEST-DL-1",
}

DEFAULT_CLAIM_ROW = {
    "policy_number": "POL-1",
    "claim_number": "CLM-001",
    "loss_date": "2025-01-15",
    "loss_type": "COLLISION",
    "cause_of_loss_code": "COL1",
    "paid_amount_cents": 10000,
    "claim_status_code": "CLOSED_WITH_PAYMENT",
    "vehicle_identifier": "",
}

DEFAULT_INQUIRY = {
    "subject_name": "Test Person",
    "subject_dob": "1985-01-01",
    "subject_address": "1 Test St, Austin TX",
    "subject_driver_license": "TEST-DL-1",
    "subject_vehicle_identifier": "",
    "permissible_purpose": "UNDERWRITING",
}

DEFAULT_DISPUTE = {
    "dispute_reason": "WRONG_AMOUNT",
    "dispute_statement": "The recorded amount is wrong.",
}

DEFAULT_NOTICE = {
    "action_type": "RATE_INCREASE",
    "notice_reason_codes": ["LOSS-FREQ"],
    "report_influence_rank": 1,
}


def create_carrier_payload(**overrides) -> dict:
    payload = dict(DEFAULT_CARRIER)
    payload.update(overrides)
    return payload


def create_consumer_payload(**overrides) -> dict:
    payload = dict(DEFAULT_CONSUMER)
    payload.update(overrides)
    return payload


def create_claim_row_payload(**overrides) -> dict:
    payload = dict(DEFAULT_CLAIM_ROW)
    payload.update(overrides)
    return payload


def create_batch_payload(claims=None, **overrides) -> dict:
    payload = {"claims": claims if claims is not None else [create_claim_row_payload()]}
    payload.update(overrides)
    return payload


def create_inquiry_payload(**overrides) -> dict:
    payload = dict(DEFAULT_INQUIRY)
    payload.update(overrides)
    return payload


def create_dispute_payload(**overrides) -> dict:
    payload = dict(DEFAULT_DISPUTE)
    payload.update(overrides)
    return payload


def create_notice_payload(**overrides) -> dict:
    payload = dict(DEFAULT_NOTICE)
    payload.update(overrides)
    return payload
