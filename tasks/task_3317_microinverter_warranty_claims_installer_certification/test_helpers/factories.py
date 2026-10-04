"""Payload factories — one per entity, input fields only (PRD §4)."""
from datetime import datetime, timedelta

DEFAULTS = {
    "COMPANY_NAME": "Test Solar Co",
    "SITE_ADDRESS": "1 Test Way",
    "SITE_POSTAL_CODE": "94000",
    "MODULE_COUNT": 20,
    "DC_CAPACITY_WATTS": 10000,
    "MANUFACTURE_MONTH": "2026-01",
    "LOT_CODE": "LOT-TEST",
    "HOMEOWNER_NAME": "T. Tester",
    "HOMEOWNER_EMAIL": "t@test.example",
    "COMMISSIONED_AT": "2026-04-01T00:00:00Z",
}


def create_installer_payload(**overrides) -> dict:
    payload = {
        "installer_code": "INST-TEST",
        "company_name": DEFAULTS["COMPANY_NAME"],
    }
    payload.update(overrides)
    return payload


def create_design_project_payload(**overrides) -> dict:
    payload = {
        "installer_id": overrides.pop("installer_id", None),
        "site_address": DEFAULTS["SITE_ADDRESS"],
        "site_postal_code": DEFAULTS["SITE_POSTAL_CODE"],
        "module_count": DEFAULTS["MODULE_COUNT"],
        "dc_capacity_watts": DEFAULTS["DC_CAPACITY_WATTS"],
    }
    payload.update(overrides)
    return payload


def create_production_lot_payload(**overrides) -> dict:
    payload = {
        "lot_code": DEFAULTS["LOT_CODE"],
        "manufacture_month": DEFAULTS["MANUFACTURE_MONTH"],
        "embed_model_code": "IQ8",
        "defect_threshold_pct": 5.0,
        "replacement_model_code": "IQ8",
    }
    payload.update(overrides)
    return payload


def commission_unit_entry(serial_number, model_code="IQ8", installed_at=None,
                          production_lot_code=None) -> dict:
    return {
        "serial_number": serial_number,
        "model_code": model_code,
        "installed_at": installed_at or DEFAULTS["COMMISSIONED_AT"],
        "production_lot_code": production_lot_code or DEFAULTS["LOT_CODE"],
    }


def create_system_registration_payload(**overrides) -> dict:
    payload = {
        "installer_id": overrides.pop("installer_id", None),
        "design_project_id": overrides.pop("design_project_id", None),
        "site_address": DEFAULTS["SITE_ADDRESS"],
        "site_postal_code": DEFAULTS["SITE_POSTAL_CODE"],
        "homeowner_name": DEFAULTS["HOMEOWNER_NAME"],
        "homeowner_email": DEFAULTS["HOMEOWNER_EMAIL"],
        "commissioned_at": DEFAULTS["COMMISSIONED_AT"],
        "units": [commission_unit_entry("TEST-U1")],
    }
    payload.update(overrides)
    return payload


def create_claim_payload(**overrides) -> dict:
    payload = {
        "unit_id": overrides.pop("unit_id", None),
        "installer_id": overrides.pop("installer_id", None),
        "claim_kind": "DEFECT",
        "remote_diagnostic_ref": "DIAG-TEST",
        "expected_unit_version": overrides.pop("expected_unit_version", 1),
    }
    payload.update(overrides)
    return payload


def create_labor_reimbursement_payload(**overrides) -> dict:
    payload = {
        "claim_id": overrides.pop("claim_id", None),
        "claimed_hours": 2.0,
    }
    payload.update(overrides)
    return payload


def create_warranty_transfer_payload(**overrides) -> dict:
    payload = {
        "system_id": overrides.pop("system_id", None),
        "transfer_kind": "SALE",
        "new_owner_name": "N. Owner",
        "new_owner_email": "n@owner.example",
        "effective_date": "2026-08-15T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_campaign_payload(**overrides) -> dict:
    payload = {
        "lot_id": overrides.pop("lot_id", None),
        "replacement_model_code": "IQ8",
        "max_units": 3,
    }
    payload.update(overrides)
    return payload


def create_replacement_order_payload(**overrides) -> dict:
    payload = {
        "unit_id": overrides.pop("unit_id", None),
        "replacement_model_code": "IQ8",
        "expected_unit_version": overrides.pop("expected_unit_version", 1),
    }
    payload.update(overrides)
    return payload


def observation_payload(performance_ratio, observed_at, **overrides) -> dict:
    payload = {
        "performance_ratio": performance_ratio,
        "observed_at": observed_at,
    }
    payload.update(overrides)
    return payload


def diagnostics_payload(observed_at, performance_ratio=None, **overrides) -> dict:
    payload = {"observed_at": observed_at}
    if performance_ratio is not None:
        payload["performance_ratio"] = performance_ratio
    payload.update(overrides)
    return payload


def add_months(iso_instant: str, months: int) -> str:
    """Calendar-exact month advance on an ISO-8601 instant (PRD §3.3)."""
    dt = datetime.strptime(iso_instant[:19], "%Y-%m-%dT%H:%M:%S")
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = min(dt.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                       31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    shifted = dt.replace(year=year, month=month, day=day)
    return shifted.strftime("%Y-%m-%dT%H:%M:%SZ")


def days_after(iso_instant: str, days: int) -> str:
    dt = datetime.strptime(iso_instant[:19], "%Y-%m-%dT%H:%M:%S")
    return (dt + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")