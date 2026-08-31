"""Payload factories — one per entity, input fields only."""

from .constants import TEST_DEFAULTS


def create_site_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["SITE_NAME"],
        "state_code": TEST_DEFAULTS["SITE_STATE_CODE"],
        "host_royalty_pct": TEST_DEFAULTS["HOST_ROYALTY_PCT"],
        "royalty_variant": "GROSS_REVENUE_SHARE",
        "permit_nmoc_limit_lb_per_hr": TEST_DEFAULTS["PERMIT_NMOC_LIMIT_LB_PER_HR"],
    }
    payload.update(overrides)
    return payload


def create_well_payload(site_id: str, **overrides) -> dict:
    payload = {
        "site_id": site_id,
        "well_code": "W-01",
        "target_flow_scfm": TEST_DEFAULTS["WELL_TARGET_FLOW_SCFM"],
    }
    payload.update(overrides)
    return payload


def create_reading_payload(taken_at: str, **overrides) -> dict:
    """A GOOD reading by default: air-intrusion index 1.85, quality_class GOOD."""
    payload = {
        "taken_at": taken_at,
        "methane_pct": 55.0,
        "oxygen_pct": 0.8,
        "nitrogen_pct": 4.0,
        "temperature_f": 118.0,
        "flow_scfm": 480.0,
        "vacuum_inhg": 22.5,
    }
    payload.update(overrides)
    return payload


def good_reading_payload(taken_at: str, flow_scfm: float = 480.0, **overrides) -> dict:
    """Composition that scores 1.85 and classifies GOOD."""
    return create_reading_payload(taken_at, flow_scfm=flow_scfm, **overrides)


def alarm_reading_payload(taken_at: str, **overrides) -> dict:
    """oxygen_pct exactly 5.00 — the inclusive alarm floor — scoring 17.70."""
    payload = {
        "taken_at": taken_at,
        "methane_pct": 60.0,
        "oxygen_pct": 5.00,
        "nitrogen_pct": 2.0,
        "temperature_f": 120.0,
        "flow_scfm": 500.0,
        "vacuum_inhg": 24.0,
    }
    payload.update(overrides)
    return payload


def watch_reading_payload(taken_at: str, **overrides) -> dict:
    """oxygen_pct 4.99 — one hundredth below the alarm floor — scoring 17.66."""
    payload = {
        "taken_at": taken_at,
        "methane_pct": 60.0,
        "oxygen_pct": 4.99,
        "nitrogen_pct": 2.0,
        "temperature_f": 120.0,
        "flow_scfm": 500.0,
        "vacuum_inhg": 24.0,
    }
    payload.update(overrides)
    return payload


def create_work_order_payload(well_id: str, **overrides) -> dict:
    payload = {
        "well_id": well_id,
        "work_type": "WELL_RETUNE",
        "window_start": "2026-08-12T08:00:00Z",
        "window_end": "2026-08-12T12:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_condensate_haul_payload(**overrides) -> dict:
    payload = {
        "gallons": 250.5,
        "disposal_manifest_no": "MAN-4471",
        "hauled_at": "2026-08-10T03:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_plant_payload(site_id: str, **overrides) -> dict:
    payload = {
        "site_id": site_id,
        "plant_code": TEST_DEFAULTS["PLANT_CODE"],
        "receipt_point_code": TEST_DEFAULTS["RECEIPT_POINT_CODE"],
        "receipt_point_mdq_dth_per_day": TEST_DEFAULTS[
            "RECEIPT_POINT_MDQ_DTH_PER_DAY"
        ],
        "min_feed_scfm": TEST_DEFAULTS["MIN_FEED_SCFM"],
    }
    payload.update(overrides)
    return payload


def create_downtime_event_payload(plant_id: str, **overrides) -> dict:
    payload = {
        "plant_id": plant_id,
        "start_at": "2026-08-02T00:00:00Z",
        "cause": "COMPRESSOR_TRIP",
        "disposition": "FLARED",
    }
    payload.update(overrides)
    return payload


def create_offtake_contract_payload(site_id: str, **overrides) -> dict:
    payload = {
        "site_id": site_id,
        "counterparty_name": TEST_DEFAULTS["COUNTERPARTY_NAME"],
        "contract_mdq_dth_per_day": TEST_DEFAULTS["CONTRACT_MDQ_DTH_PER_DAY"],
        "price_usd_per_dth": TEST_DEFAULTS["PRICE_USD_PER_DTH"],
        "term_start": TEST_DEFAULTS["TERM_START"],
        "term_end": TEST_DEFAULTS["TERM_END"],
    }
    payload.update(overrides)
    return payload


def create_nomination_payload(
    contract_id: str, plant_id: str, expected_contract_version: int, **overrides
) -> dict:
    payload = {
        "contract_id": contract_id,
        "plant_id": plant_id,
        "gas_day_start": "2026-08-10T00:00:00Z",
        "gas_day_end": "2026-08-11T00:00:00Z",
        "nominated_dth": TEST_DEFAULTS["NOMINATED_DTH"],
        "expected_contract_version": expected_contract_version,
    }
    payload.update(overrides)
    return payload


def create_injection_batch_payload(plant_id: str, **overrides) -> dict:
    """The canonical three-hour block whose gross_mmbtu is 340.14."""
    payload = {
        "plant_id": plant_id,
        "interval_start": "2026-08-10T02:00:00Z",
        "interval_end": "2026-08-10T05:00:00Z",
        "hourly_volumes_mscf": [115.0, 115.0, 115.0],
        "methane_pct": 97.4,
        "oxygen_pct": 0.1,
        "co2_pct": 1.4,
    }
    payload.update(overrides)
    return payload


def off_spec_batch_payload(plant_id: str, **overrides) -> dict:
    """methane_pct 94.0 is below the 96.0 injection spec: LOW_METHANE."""
    payload = {
        "plant_id": plant_id,
        "interval_start": "2026-08-10T06:00:00Z",
        "interval_end": "2026-08-10T08:00:00Z",
        "hourly_volumes_mscf": [110.0, 110.0],
        "methane_pct": 94.0,
        "oxygen_pct": 0.1,
        "co2_pct": 1.4,
    }
    payload.update(overrides)
    return payload


def create_attribute_batch_payload(injection_batch_id: str, **overrides) -> dict:
    payload = {
        "injection_batch_id": injection_batch_id,
        "program": "RIN_D3",
        "generation_period": "2026-08",
    }
    payload.update(overrides)
    return payload


def create_compliance_report_payload(site_id: str, **overrides) -> dict:
    payload = {
        "site_id": site_id,
        "report_type": "QUARTERLY_RIN_QAP",
        "period": "2026-Q3",
        "nmoc_lb_per_hr_reported": 2.0,
    }
    payload.update(overrides)
    return payload


def create_royalty_statement_payload(
    site_id: str, expected_site_version: int, **overrides
) -> dict:
    payload = {
        "site_id": site_id,
        "period": "2026-08",
        "expected_site_version": expected_site_version,
    }
    payload.update(overrides)
    return payload
