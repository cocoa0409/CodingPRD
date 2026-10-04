"""Payload factories — one per entity, input fields only (PRD §3 narratives)."""

DEFAULTS = {
    "ORG_NAME": "Test Carrier Lines",
    "ORG_TYPE": "VOCC",
    "COMPANY_NAME": "Test Shippers Inc",
    "CONTACT_EMAIL": "ops@shippers.example",
    "TARIFF_CODE": "DD-TEST-1",
    "CHARGE_SCOPE": "DEMURRAGE",
    "FREE_TIME_DAYS": 2,
    "PER_DIEM_RATE_CENTS": 5000,
    "ACCRUAL_METHOD": "CALENDAR",
    "CHANGE_TYPE": "NEW",
    "EFFECTIVE_DATE": "2026-09-02T00:00:00Z",
    "CONTRACT_REFERENCE": "SC-TEST-1",
    "AGREED_AT": "2026-09-02T00:00:00Z",
    "DURATION_MONTHS": 12,
    "MINIMUM_QUANTITY_COMMITMENT": 100,
    "NEGOTIATED_FREE_TIME_DAYS": 3,
    "NEGOTIATED_PER_DIEM_RATE_CENTS": 12000,
    "NEGOTIATED_ACCRUAL_METHOD": "CALENDAR",
    "AGREEMENT_NUMBER": "AG-TEST-1",
    "AGREEMENT_TYPE": "VESSEL_SHARING",
    "LICENSE_TYPE": "NVOCC",
    "BOND_REF": "B1",
    "SURETY_NAME": "Pacific Surety",
    "COVERAGE_CENTS": 7_500_000,
    "INVOICE_NUMBER": "INV-TEST-1",
    "CONTAINER_NUMBER": "MSKU0000001",
    "PORT_CODE": "USNYC",
    "AVAILABILITY_DATE": "2026-09-04T00:00:00Z",
    "RETURN_DATE": "2026-09-08T00:00:00Z",
    "LAST_ACCRUAL_DATE": "2026-09-08T00:00:00Z",
    "DISPUTE_REASON": "CHARGE_EXCEEDS_PUBLISHED",
    "REPARATIONS_CLAIMED_CENTS": 50_000,
    "PROCEEDING_BASIS": "TARIFF_VIOLATION",
    "TERMINAL_CODE": "TERM-1",
    "WEEK_START": "2026-09-07T00:00:00Z",
    "BERTH_OCCUPANCY_HOURS": 100,
    "GATE_CLOSURES_HOURS": 0,
    "VESSEL_DWELL_HOURS_AVG": 48.0,
}


def create_carrier_payload(**overrides) -> dict:
    defaults = {
        "org_name": DEFAULTS["ORG_NAME"],
        "org_type": DEFAULTS["ORG_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_shipper_payload(**overrides) -> dict:
    defaults = {
        "company_name": DEFAULTS["COMPANY_NAME"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_tariff_payload(expected_carrier_version, **overrides) -> dict:
    defaults = {
        "tariff_code": DEFAULTS["TARIFF_CODE"],
        "charge_scope": DEFAULTS["CHARGE_SCOPE"],
        "free_time_days": DEFAULTS["FREE_TIME_DAYS"],
        "per_diem_rate_cents": DEFAULTS["PER_DIEM_RATE_CENTS"],
        "accrual_method": DEFAULTS["ACCRUAL_METHOD"],
        "change_type": DEFAULTS["CHANGE_TYPE"],
        "effective_date": DEFAULTS["EFFECTIVE_DATE"],
        "expected_carrier_version": expected_carrier_version,
    }
    defaults.update(overrides)
    return defaults


def create_service_contract_payload(shipper_id, **overrides) -> dict:
    defaults = {
        "contract_reference": DEFAULTS["CONTRACT_REFERENCE"],
        "shipper_id": shipper_id,
        "agreed_at": DEFAULTS["AGREED_AT"],
        "duration_months": DEFAULTS["DURATION_MONTHS"],
        "minimum_quantity_commitment": DEFAULTS["MINIMUM_QUANTITY_COMMITMENT"],
        "negotiated_free_time_days": DEFAULTS["NEGOTIATED_FREE_TIME_DAYS"],
        "negotiated_per_diem_rate_cents": DEFAULTS["NEGOTIATED_PER_DIEM_RATE_CENTS"],
        "negotiated_accrual_method": DEFAULTS["NEGOTIATED_ACCRUAL_METHOD"],
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(member_carrier_ids, **overrides) -> dict:
    defaults = {
        "agreement_number": DEFAULTS["AGREEMENT_NUMBER"],
        "agreement_type": DEFAULTS["AGREEMENT_TYPE"],
        "member_carrier_ids": list(member_carrier_ids),
    }
    defaults.update(overrides)
    return defaults


def create_monitoring_report_payload(total_market_teus, member_volumes, **overrides) -> dict:
    defaults = {
        "reporting_period_start": "2026-01-01T00:00:00Z",
        "reporting_period_end": "2026-04-01T00:00:00Z",
        "total_market_teus": total_market_teus,
        "member_volumes": member_volumes,
    }
    defaults.update(overrides)
    return defaults


def create_oti_license_payload(**overrides) -> dict:
    defaults = {"license_type": DEFAULTS["LICENSE_TYPE"]}
    defaults.update(overrides)
    return defaults


def create_bond_payload(**overrides) -> dict:
    defaults = {
        "bond_ref": DEFAULTS["BOND_REF"],
        "surety_name": DEFAULTS["SURETY_NAME"],
        "coverage_cents": DEFAULTS["COVERAGE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_draw_payload(bond_ref, amount_cents, expected_license_version, **overrides) -> dict:
    defaults = {
        "bond_ref": bond_ref,
        "amount_cents": amount_cents,
        "reason": "claim",
        "expected_license_version": expected_license_version,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(tariff_id=None, service_contract_id=None,
                           billed_party_shipper_id=None, **overrides) -> dict:
    if (tariff_id is None) == (service_contract_id is None):
        raise ValueError("exactly one of tariff_id / service_contract_id is required")
    defaults = {
        "invoice_number": DEFAULTS["INVOICE_NUMBER"],
        "charge_basis": "TARIFF" if tariff_id is not None else "SERVICE_CONTRACT",
        "billed_party_shipper_id": billed_party_shipper_id,
        "container_number": DEFAULTS["CONTAINER_NUMBER"],
        "port_code": DEFAULTS["PORT_CODE"],
        "availability_date": DEFAULTS["AVAILABILITY_DATE"],
        "return_date": DEFAULTS["RETURN_DATE"],
        "last_accrual_date": DEFAULTS["LAST_ACCRUAL_DATE"],
    }
    if tariff_id is not None:
        defaults["tariff_id"] = tariff_id
    if service_contract_id is not None:
        defaults["service_contract_id"] = service_contract_id
    defaults.update(overrides)
    return defaults


def create_dispute_payload(**overrides) -> dict:
    defaults = {"dispute_reason": DEFAULTS["DISPUTE_REASON"]}
    defaults.update(overrides)
    return defaults


def create_complaint_payload(respondent_carrier_id, subject_invoice_ids, **overrides) -> dict:
    defaults = {
        "respondent_carrier_id": respondent_carrier_id,
        "subject_invoice_ids": list(subject_invoice_ids),
        "reparations_claimed_cents": DEFAULTS["REPARATIONS_CLAIMED_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_proceeding_payload(target_carrier_id, **overrides) -> dict:
    defaults = {
        "target_carrier_id": target_carrier_id,
        "basis": DEFAULTS["PROCEEDING_BASIS"],
    }
    defaults.update(overrides)
    return defaults


def create_congestion_report_payload(**overrides) -> dict:
    defaults = {
        "port_code": DEFAULTS["PORT_CODE"],
        "terminal_code": DEFAULTS["TERMINAL_CODE"],
        "week_start": DEFAULTS["WEEK_START"],
        "berth_occupancy_hours": DEFAULTS["BERTH_OCCUPANCY_HOURS"],
        "gate_closures_hours": DEFAULTS["GATE_CLOSURES_HOURS"],
        "vessel_dwell_hours_avg": DEFAULTS["VESSEL_DWELL_HOURS_AVG"],
    }
    defaults.update(overrides)
    return defaults
