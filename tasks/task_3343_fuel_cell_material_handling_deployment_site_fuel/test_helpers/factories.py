"""Payload factories — one per entity, input fields only (PRD §3, §4)."""


def create_site_payload(**overrides) -> dict:
    defaults = {
        "code": "S-001",
        "name": "Test Site",
        "address": "1 Industrial Pkwy",
        "baseline_labor_rate_per_hour": 30.0,
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(**overrides) -> dict:
    defaults = {
        "forklift_count": 5,
        "duty_cycle_hours_per_day": 8.0,
        "peak_shift_hours": 8,
        "safety_findings_json": "{\"ok\": true}",
    }
    defaults.update(overrides)
    return defaults


def create_supply_contract_payload(**overrides) -> dict:
    defaults = {
        "supply_mode": "PIPELINE",
        "start_date": "2026-10-01",
        "end_date": "2026-12-31",
        "base_price_per_kg": 2.5,
        "reliability_sla_pct": 99.0,
        "committed_monthly_kg": 100,
    }
    defaults.update(overrides)
    return defaults


def create_station_payload(**overrides) -> dict:
    defaults = {
        "station_code": "ST-1",
        "location_type": "OUTDOOR",
        "capacity_kg_per_day": 500,
        "storage_capacity_kg": 1000,
        "construction_start": "2026-10-01",
        "construction_end": "2026-10-05",
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(**overrides) -> dict:
    defaults = {
        "permit_type": "CONSTRUCTION",
        "issued_date": "2026-10-01",
        "expiry_date": "2027-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Tech",
        "certification_level": "MASTER",
        "certified_until": "2027-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_conversion_plan_payload(**overrides) -> dict:
    defaults = {
        "name": "Wave 1",
        "target_forklift_count": 1,
        "transition_mode": "CUTOVER",
        "start_date": "2026-10-01",
        "end_date": "2026-10-10",
        "baseline_productivity_units_per_hour": 50.0,
        "expected_productivity_gain_pct": 10,
    }
    defaults.update(overrides)
    return defaults


def create_conversion_event_payload(**overrides) -> dict:
    defaults = {
        "forklift_id": "FL-1",
        "scheduled_start": "2026-10-02T08:00:00Z",
        "scheduled_end": "2026-10-02T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_service_agreement_payload(**overrides) -> dict:
    defaults = {
        "coverage_start": "2026-10-01",
        "coverage_end": "2027-09-30",
        "availability_guarantee_pct": 90.0,
        "monthly_fee_cents": 2000000,
    }
    defaults.update(overrides)
    return defaults


def create_downtime_report_payload(**overrides) -> dict:
    defaults = {
        "month": "2026-10",
        "forklift_id": "FL-1",
        "downtime_hours": 10.0,
    }
    defaults.update(overrides)
    return defaults


def create_fueling_event_payload(**overrides) -> dict:
    defaults = {
        "forklift_id": "FL-1",
        "occurred_at": "2026-10-05T08:00:00Z",
        "kg_dispensed": 10,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(**overrides) -> dict:
    defaults = {
        "period_start": "2026-10-01",
        "period_end": "2026-11-01",
    }
    defaults.update(overrides)
    return defaults


def create_incentive_claim_payload(**overrides) -> dict:
    defaults = {
        "incentive_type": "FEDERAL_ITC",
        "claimed_amount_cents": 100000,
        "qualification_date": "2026-10-05",
    }
    defaults.update(overrides)
    return defaults


def create_training_record_payload(**overrides) -> dict:
    defaults = {
        "trainee_employee_id": "EMP-1",
        "course_code": "H2_BASIC",
        "completed_at": "2026-09-01",
        "expires_at": "2027-09-01",
    }
    defaults.update(overrides)
    return defaults
