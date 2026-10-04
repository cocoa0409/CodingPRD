"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "DEALER_CODE": "D-TEST",
    "LEGAL_NAME": "Test Dealer LLC",
    "HOLDBACK_RATE": 0.10,
    "QUALITY_TIER": "TIER_1",
    "FULL_NAME": "Test Subscriber",
    "EMAIL": "test.subscriber@example.com",
    "PHONE": "+15550009999",
    "PACKAGE_REFERENCE": "PKG-TEST",
    "EQUIPMENT_CONFIG_CODE": "PREMIUM",
    "CREDIT_SCORE": 700,
    "CONTRACT_TERM_MONTHS": 60,
    "MONTHLY_MONITORING_CENTS": 4999,
    "ADDRESS_LINE": "1 Test St",
    "CITY": "Dallas",
    "STATE_CODE": "TX",
    "POSTAL_CODE": "75001",
    "ENGINEER_ID": "ENG-1",
    "TECHNICIAN_ID": "TECH-1",
}


def create_dealer_payload(**overrides) -> dict:
    defaults = {
        "dealer_code": DEFAULTS["DEALER_CODE"],
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "holdback_rate": DEFAULTS["HOLDBACK_RATE"],
        "quality_tier": DEFAULTS["QUALITY_TIER"],
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["FULL_NAME"],
        "email": DEFAULTS["EMAIL"],
        "phone": DEFAULTS["PHONE"],
    }
    defaults.update(overrides)
    return defaults


def create_package_payload(dealer_id=None, **overrides) -> dict:
    defaults = {"package_reference": DEFAULTS["PACKAGE_REFERENCE"]}
    if dealer_id is not None:
        defaults["dealer_id"] = dealer_id
    defaults.update(overrides)
    return defaults


def create_contract_payload(customer_id, **overrides) -> dict:
    """Origination payload shared by the DIRECT route and the package-declaration route."""
    defaults = {
        "customer_id": customer_id,
        "equipment_config_code": DEFAULTS["EQUIPMENT_CONFIG_CODE"],
        "credit_score": DEFAULTS["CREDIT_SCORE"],
        "contract_term_months": DEFAULTS["CONTRACT_TERM_MONTHS"],
        "monthly_monitoring_cents": DEFAULTS["MONTHLY_MONITORING_CENTS"],
        "premises_address_line": DEFAULTS["ADDRESS_LINE"],
        "premises_city": DEFAULTS["CITY"],
        "premises_state_code": DEFAULTS["STATE_CODE"],
        "premises_postal_code": DEFAULTS["POSTAL_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_installation_payload(contract_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "scheduled_at": "2026-09-02T00:00:00Z",
        "installation_engineer_id": DEFAULTS["ENGINEER_ID"],
    }
    defaults.update(overrides)
    return defaults


def create_alarm_event_payload(monitoring_account_id, **overrides) -> dict:
    defaults = {
        "monitoring_account_id": monitoring_account_id,
        "signal_source": "ZONE-1",
        "occurred_at": "2026-09-03T00:00:00Z",
        "entered_at_utc": "2026-09-03T00:00:30Z",
    }
    defaults.update(overrides)
    return defaults


def create_dispatch_payload(alarm_event_id, **overrides) -> dict:
    defaults = {"alarm_event_id": alarm_event_id}
    defaults.update(overrides)
    return defaults


def create_reduction_action_payload(monitoring_account_id, **overrides) -> dict:
    defaults = {
        "monitoring_account_id": monitoring_account_id,
        "action_type": "SERVICE_REQUIRED",
    }
    defaults.update(overrides)
    return defaults


def create_service_visit_payload(contract_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "scheduled_at": "2026-09-10T00:00:00Z",
        "work_type": "REPAIR",
        "technician_id": DEFAULTS["TECHNICIAN_ID"],
    }
    defaults.update(overrides)
    return defaults


def create_assumption_request_payload(contract_id, incoming_customer_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "incoming_customer_id": incoming_customer_id,
        "incoming_credit_score": DEFAULTS["CREDIT_SCORE"],
        "residence_state_code": DEFAULTS["STATE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_rescission_request_payload(contract_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "operator_id": "ops-requestor-1",
    }
    defaults.update(overrides)
    return defaults


def create_waiver_payload(**overrides) -> dict:
    defaults = {"requested_by": "ops-requester-1", "onsite_install": True}
    defaults.update(overrides)
    return defaults


def create_attrition_sweep_payload(sweep_month, **overrides) -> dict:
    defaults = {"sweep_month": sweep_month}
    defaults.update(overrides)
    return defaults


def create_chargeback_recompute_payload(expected_dealer_version, **overrides) -> dict:
    defaults = {"expected_dealer_version": expected_dealer_version}
    defaults.update(overrides)
    return defaults