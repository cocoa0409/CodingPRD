"""Payload factories (input fields only) and temporal literal helpers.

Instants are written as ISO 8601 UTC with a trailing `Z`; the PRD compares
instants at second resolution, and `to_millis()` canonicalises a
second-resolution literal into the three-fractional-digit form the API returns
so that a request literal can be compared against a response field.
"""
from datetime import datetime, timedelta, timezone

from .constants import CLOCK_EPOCH


# --------------------------------------------------------------------------
# Temporal literal helpers
# --------------------------------------------------------------------------
def _parse(instant: str) -> datetime:
    text = instant.replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def iso(year, month, day, hour=0, minute=0, second=0) -> str:
    """An ISO 8601 UTC instant at second resolution."""
    return (
        f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}Z"
    )


def to_millis(instant: str) -> str:
    """Canonicalise an instant into the three-fractional-digit UTC form the API
    returns (PRD §2.4), so request literals can be compared to response fields."""
    dt = _parse(instant)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def plus_seconds(instant: str, seconds: int) -> str:
    dt = _parse(instant) + timedelta(seconds=seconds)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def plus_minutes(instant: str, minutes: int) -> str:
    return plus_seconds(instant, minutes * 60)


def plus_hours(instant: str, hours: int) -> str:
    return plus_seconds(instant, hours * 3600)


def plus_instant_days(instant: str, days: int) -> str:
    return plus_seconds(instant, days * 86400)


def date_of(instant: str) -> str:
    """The instant's UTC calendar date in YYYY-MM-DD form (PRD §2.5)."""
    return _parse(instant).strftime("%Y-%m-%d")


def plus_days(date_str: str, days: int) -> str:
    dt = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=days)
    return dt.strftime("%Y-%m-%d")


def days_between(earlier_date: str, later_date: str) -> int:
    a = datetime.strptime(earlier_date, "%Y-%m-%d")
    b = datetime.strptime(later_date, "%Y-%m-%d")
    return (b - a).days


# The logical clock's value before it has ever been set (PRD §2.5).
DEFAULT_CLOCK = CLOCK_EPOCH


# --------------------------------------------------------------------------
# Unique-literal support. Every test starts against an empty database, so a
# module-level counter is enough to keep codes distinct inside one test.
# --------------------------------------------------------------------------
_counter = {"n": 0}


def unique_suffix() -> str:
    _counter["n"] += 1
    return f"{_counter['n']:04d}"


# --------------------------------------------------------------------------
# Growing areas (PRD §3.1)
# --------------------------------------------------------------------------
def growing_area_payload(**overrides) -> dict:
    payload = {
        "code": f"GA-{unique_suffix()}",
        "water_body": "Pamlico Sound",
    }
    payload.update(overrides)
    return payload


def classification_decision_payload(classification, expected_area_version,
                                    **overrides) -> dict:
    payload = {
        "classification": classification,
        "expected_area_version": expected_area_version,
    }
    payload.update(overrides)
    return payload


def reopen_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


def water_sample_payload(**overrides) -> dict:
    payload = {
        "station_code": "ST-1",
        "collected_at": iso(2026, 7, 1, 9),
        "fecal_coliform_mpn": 4,
        "water_temp_c": 24.0,
        "salinity_ppt": 30.0,
    }
    payload.update(overrides)
    return payload


def rainfall_event_payload(**overrides) -> dict:
    payload = {
        "gauge_code": "RG-1",
        "observed_at": iso(2026, 7, 20),
        "inches_24h": 1.50,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Leases (PRD §3.4)
# --------------------------------------------------------------------------
def lease_payload(growing_area_id, **overrides) -> dict:
    payload = {
        "growing_area_id": growing_area_id,
        "lease_code": f"LS-{unique_suffix()}",
        "requested_acreage": 5.0,
        "plot_codes": ["P1", "P2"],
        "gear_types_permitted": ["BOTTOM", "RACK_AND_BAG", "FLOATING_BAG"],
        "authorized_gear_units": 100,
    }
    payload.update(overrides)
    return payload


def submit_lease_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


def review_payload(decision, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def lease_decision_payload(decision, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Hatcheries and seed lots (PRD §3.5)
# --------------------------------------------------------------------------
def hatchery_payload(**overrides) -> dict:
    payload = {
        "name": "Coastal Hatchery",
        "state_code": "NC",
        "ncsp_certificate_no": f"NCSP-{unique_suffix()}",
        "certificate_expires_on": "2027-12-31",
        "pathogen_free_species": [
            "CRASSOSTREA_VIRGINICA",
            "MERCENARIA_MERCENARIA",
        ],
    }
    payload.update(overrides)
    return payload


def seed_lot_payload(hatchery_id, lease_id, **overrides) -> dict:
    payload = {
        "hatchery_id": hatchery_id,
        "lease_id": lease_id,
        "species": "CRASSOSTREA_VIRGINICA",
        "received_seed_count": 10000,
        "disease_certificate_no": f"DC-{unique_suffix()}",
        "disease_cert_issued_on": "2026-05-20",
        "shipped_on": "2026-06-01",
    }
    payload.update(overrides)
    return payload


def screening_payload(result, screened_on, **overrides) -> dict:
    payload = {"result": result, "screened_on": screened_on}
    payload.update(overrides)
    return payload


def nursery_start_payload(nursery_started_on, nursery_system="UPWELLER",
                          **overrides) -> dict:
    payload = {
        "nursery_started_on": nursery_started_on,
        "nursery_system": nursery_system,
    }
    payload.update(overrides)
    return payload


def nursery_complete_payload(nursery_completed_on, surviving_seed_count,
                             **overrides) -> dict:
    payload = {
        "nursery_completed_on": nursery_completed_on,
        "surviving_seed_count": surviving_seed_count,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Grow-out gear and husbandry (PRD §3.6)
# --------------------------------------------------------------------------
def growout_unit_payload(lease_id, seed_lot_id, **overrides) -> dict:
    payload = {
        "lease_id": lease_id,
        "seed_lot_id": seed_lot_id,
        "plot_code": "P1",
        "gear_type": "FLOATING_BAG",
        "gear_units": 10,
        "seed_count_planted": 1000,
        "deployed_on": "2026-07-01",
        "planned_retrieval_on": "2026-10-01",
    }
    payload.update(overrides)
    return payload


def husbandry_log_payload(log_type, performed_at, **overrides) -> dict:
    payload = {"log_type": log_type, "performed_at": performed_at}
    if log_type == "PREDATOR_CONTROL":
        payload["predator_species"] = "OYSTER_DRILL"
        payload["control_method"] = "TRAPPING"
    payload.update(overrides)
    return payload


def retrieve_payload(retrieved_on, **overrides) -> dict:
    payload = {"retrieved_on": retrieved_on}
    payload.update(overrides)
    return payload


def void_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Vessels and authorizations (PRD §3.7)
# --------------------------------------------------------------------------
def harvest_vessel_payload(**overrides) -> dict:
    payload = {
        "name": "FV Tidewater",
        "registration_no": f"REG-{unique_suffix()}",
        "refrigeration_type": "ICE_SLURRY",
    }
    payload.update(overrides)
    return payload


def harvest_authorization_payload(lease_id, growout_unit_id, vessel_id, dealer_id,
                                  window_start, window_end, **overrides) -> dict:
    payload = {
        "lease_id": lease_id,
        "growout_unit_id": growout_unit_id,
        "vessel_id": vessel_id,
        "dealer_id": dealer_id,
        "window_start": window_start,
        "window_end": window_end,
        "projected_bushels": 100,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Harvest lots (PRD §3.8)
# --------------------------------------------------------------------------
def harvest_lot_payload(first_out_of_water_at, last_out_of_water_at,
                        placed_in_temperature_control_at, **overrides) -> dict:
    payload = {
        "lot_code": f"LOT-{unique_suffix()}",
        "bushels": 10,
        "first_out_of_water_at": first_out_of_water_at,
        "last_out_of_water_at": last_out_of_water_at,
        "placed_in_temperature_control_at": placed_in_temperature_control_at,
        "water_temp_c": 20.0,
    }
    payload.update(overrides)
    return payload


def tag_payload(harvest_date, dealer_certification_no, **overrides) -> dict:
    payload = {
        "harvest_date": harvest_date,
        "dealer_certification_no": dealer_certification_no,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Dealers, shipments, investigations, vibrio plans (PRD §3.9, §3.8)
# --------------------------------------------------------------------------
def dealer_payload(**overrides) -> dict:
    payload = {
        "name": "Harbor Seafood",
        "state_code": "NC",
        "certification_category": "SHELLSTOCK_SHIPPER",
        "certification_no": f"CERT-{unique_suffix()}",
        "certified_through": "2027-06-30",
    }
    payload.update(overrides)
    return payload


def dealer_renewal_payload(expected_dealer_version, certified_through,
                           **overrides) -> dict:
    payload = {
        "expected_dealer_version": expected_dealer_version,
        "certified_through": certified_through,
    }
    payload.update(overrides)
    return payload


def suspend_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


def reinstate_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


def shipment_payload(dealer_id, lot_ids, **overrides) -> dict:
    payload = {
        "dealer_id": dealer_id,
        "destination_state": "NC",
        "carrier": "Coastal Freight",
        "lot_ids": list(lot_ids),
    }
    payload.update(overrides)
    return payload


def ship_payload(shipped_at, **overrides) -> dict:
    payload = {"shipped_at": shipped_at}
    payload.update(overrides)
    return payload


def illness_investigation_payload(reported_at, **overrides) -> dict:
    payload = {
        "reported_at": reported_at,
        "illness_count": 3,
        "pathogen": "VIBRIO_PARAHAEMOLYTICUS",
    }
    payload.update(overrides)
    return payload


def traceback_payload(scope_variant, **overrides) -> dict:
    payload = {"scope_variant": scope_variant}
    payload.update(overrides)
    return payload


def confirm_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


def close_investigation_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


def vibrio_control_plan_payload(season_month, **overrides) -> dict:
    payload = {
        "season_month": season_month,
        "max_time_to_temperature_minutes": 300,
        "high_water_temp_c": 27.0,
        "high_temp_reduction_minutes": 60,
    }
    payload.update(overrides)
    return payload
