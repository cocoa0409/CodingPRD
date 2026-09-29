"""Request payload builders.

Two conventions hold throughout. Every money and quantity field is emitted as a
JSON number, never as a string, because PRD §2.6 declares cents as whole
integers and barrel/ounce figures as decimals. Every datetime field is emitted
as a full ISO-8601 instant with an explicit ``Z``, never as a bare date,
because §2.5 says the clock and every window bound is an instant.
"""

import itertools
from typing import Any, Dict, Optional

from .constants import (
    BASIS_METERED_POUR,
    BEER_LABEL_FIELDS,
    CONTAINER_PINT_16OZ,
    CROWLER_LABEL_FIELDS,
    DESTINATION_DISTRIBUTION,
    FILING_FORMULA,
    FILING_LABEL,
    GROWLER_LABEL_FIELDS,
    KEG_SIZE_HALF_BBL,
    LICENSE_SELF_DISTRIBUTION,
    MOVEMENT_RETURN,
    MOVEMENT_TAP,
    NOTICE_ACTION_ACTIVATE,
    PACKAGE_HALF_BBL_KEG,
    PERMIT_FESTIVAL,
    SANITIZER_PPM_MIN,
    TANK_ACTION_CIP,
    TANK_TYPE_FERMENTER,
    TERMINATION_REQUEST,
)

_counter = itertools.count(1)


def unique_suffix() -> str:
    """A short monotonically increasing suffix for unique code fields."""
    return f"{next(_counter):04d}"


# ---------------------------------------------------------------------------
# Brewery (§3.1)
# ---------------------------------------------------------------------------
def brewery_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": "Cascade Fog Brewing Company",
        "home_state_code": "OR",
        "ttb_brewers_notice_number": "BR-OR-19472",
    }
    payload.update(overrides)
    return payload


def notice_payload(action: str = NOTICE_ACTION_ACTIVATE, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


def brewery_ytd_payload(
    carry_in_taproom_bbl: float = 0.000,
    carry_in_distribution_bbl: float = 0.000,
    **overrides: Any,
) -> Dict[str, Any]:
    """§3.1: the carry-in call names carry_in_taproom_bbl and carry_in_distribution_bbl."""
    payload: Dict[str, Any] = {
        "carry_in_taproom_bbl": carry_in_taproom_bbl,
        "carry_in_distribution_bbl": carry_in_distribution_bbl,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Beers (§3.1)
# ---------------------------------------------------------------------------
def beer_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": f"Cascade Fog IPA {unique_suffix()}",
        "style": "West Coast IPA",
        "abv_pct": 6.5,
        "price_per_bbl_cents": 40000,
    }
    payload.update(overrides)
    return payload


def exempt_beer_payload(**overrides: Any) -> Dict[str, Any]:
    """A beer minted straight into FORMULA_EXEMPT (§3.1)."""
    payload = beer_payload(requires_formula=False)
    payload.update(overrides)
    return payload


def formula_filing_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "filing_type": FILING_FORMULA,
        "ingredient_list": ["malted barley", "cascade hops", "water", "ale yeast"],
    }
    payload.update(overrides)
    return payload


def label_filing_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "filing_type": FILING_LABEL,
        "label_fields": dict(BEER_LABEL_FIELDS),
    }
    payload.update(overrides)
    return payload


def filing_decision_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Tanks (§3.2)
# ---------------------------------------------------------------------------
def tank_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": f"FV-{unique_suffix()}",
        "tank_type": TANK_TYPE_FERMENTER,
        "capacity_bbl": 30.00,
    }
    payload.update(overrides)
    return payload


def tank_service_payload(
    action: str = TANK_ACTION_CIP,
    sanitizer_ppm: Optional[int] = None,
    contact_time_seconds: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """A CIP action carries the sanitation reading; the other two do not."""
    payload: Dict[str, Any] = {"action": action}
    if action == TANK_ACTION_CIP:
        payload["sanitizer_ppm"] = (
            SANITIZER_PPM_MIN if sanitizer_ppm is None else sanitizer_ppm
        )
        payload["contact_time_seconds"] = (
            120 if contact_time_seconds is None else contact_time_seconds
        )
    else:
        if sanitizer_ppm is not None:
            payload["sanitizer_ppm"] = sanitizer_ppm
        if contact_time_seconds is not None:
            payload["contact_time_seconds"] = contact_time_seconds
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Batches (§3.2)
# ---------------------------------------------------------------------------
def batch_payload(beer_id: str, tank_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "beer_id": beer_id,
        "tank_id": tank_id,
        "batch_code": f"B-{unique_suffix()}",
        "planned_volume_bbl": 20.00,
        "brew_start_utc": "2026-08-01T00:00:00Z",
        "brew_end_utc": "2026-08-05T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def condition_payload(actual_yield_bbl: float = 16.000, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"actual_yield_bbl": actual_yield_bbl}
    payload.update(overrides)
    return payload


def dump_payload(reason: str = "Infected wort", **overrides: Any) -> Dict[str, Any]:
    """§3.2: dumping requires a ``reason``, stored as ``dumped_reason``."""
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Packaging runs (§3.3)
# ---------------------------------------------------------------------------
def packaging_run_payload(
    batch_id: str,
    expected_batch_version: int,
    package_type: str = PACKAGE_HALF_BBL_KEG,
    destination: str = DESTINATION_DISTRIBUTION,
    units_planned: int = 10,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "batch_id": batch_id,
        "run_code": f"R-{unique_suffix()}",
        "package_type": package_type,
        "destination": destination,
        "units_planned": units_planned,
        "expected_batch_version": expected_batch_version,
    }
    payload.update(overrides)
    return payload


def complete_run_payload(units_produced: int = 10, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"units_produced": units_produced}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Keg assets (§3.4)
# ---------------------------------------------------------------------------
def keg_asset_payload(size_bbl: float = KEG_SIZE_HALF_BBL, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "keg_serial": f"KEG-{unique_suffix()}",
        "size_bbl": size_bbl,
    }
    payload.update(overrides)
    return payload


def keg_clean_payload(
    sanitizer_ppm: int = 200, contact_time_seconds: int = 90, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "sanitizer_ppm": sanitizer_ppm,
        "contact_time_seconds": contact_time_seconds,
    }
    payload.update(overrides)
    return payload


def keg_fill_payload(packaging_run_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"packaging_run_id": packaging_run_id}
    payload.update(overrides)
    return payload


def keg_movement_payload(
    movement_type: str = MOVEMENT_TAP, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"movement_type": movement_type}
    payload.update(overrides)
    return payload


def keg_return_payload(returned_volume_gal: float, **overrides: Any) -> Dict[str, Any]:
    """§3.4: a RETURN movement requires ``returned_volume_gal`` in US gallons."""
    payload: Dict[str, Any] = {
        "movement_type": MOVEMENT_RETURN,
        "returned_volume_gal": returned_volume_gal,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Taproom pours (§3.5)
# ---------------------------------------------------------------------------
def pour_payload(
    keg_asset_id: str,
    container_type: str = CONTAINER_PINT_16OZ,
    price_cents: int = 700,
    **overrides: Any,
) -> Dict[str, Any]:
    """A draft pour: none of the five sealed-container fields may be supplied."""
    payload: Dict[str, Any] = {
        "keg_asset_id": keg_asset_id,
        "container_type": container_type,
        "price_cents": price_cents,
    }
    payload.update(overrides)
    return payload


def growler_payload(
    keg_asset_id: str,
    attested_by_user_id: str,
    sanitizer_ppm: int = 200,
    contact_time_seconds: int = 90,
    price_cents: int = 2400,
    **overrides: Any,
) -> Dict[str, Any]:
    """A GROWLER_64OZ fill: all five sealed-container fields are required."""
    payload: Dict[str, Any] = {
        "keg_asset_id": keg_asset_id,
        "container_type": "GROWLER_64OZ",
        "price_cents": price_cents,
        "container_sanitized": True,
        "sanitizer_ppm": sanitizer_ppm,
        "contact_time_seconds": contact_time_seconds,
        "attested_by_user_id": attested_by_user_id,
        "label_fields": dict(GROWLER_LABEL_FIELDS),
    }
    payload.update(overrides)
    return payload


def crowler_payload(
    keg_asset_id: str,
    attested_by_user_id: str,
    sanitizer_ppm: int = 200,
    contact_time_seconds: int = 90,
    price_cents: int = 1400,
    **overrides: Any,
) -> Dict[str, Any]:
    """A CROWLER_32OZ fill: all five sealed-container fields are required."""
    payload: Dict[str, Any] = {
        "keg_asset_id": keg_asset_id,
        "container_type": "CROWLER_32OZ",
        "price_cents": price_cents,
        "container_sanitized": True,
        "sanitizer_ppm": sanitizer_ppm,
        "contact_time_seconds": contact_time_seconds,
        "attested_by_user_id": attested_by_user_id,
        "label_fields": dict(CROWLER_LABEL_FIELDS),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# State licences (§3.6)
# ---------------------------------------------------------------------------
def state_license_payload(
    state_code: str = "WA",
    license_type: str = LICENSE_SELF_DISTRIBUTION,
    annual_barrel_cap: float = 100.00,
    franchise_state: bool = False,
    effective_from_utc: str = "2026-07-01T00:00:00Z",
    expires_at_utc: str = "2027-07-01T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "state_code": state_code,
        "license_type": license_type,
        "annual_barrel_cap": annual_barrel_cap,
        "franchise_state": franchise_state,
        "effective_from_utc": effective_from_utc,
        "expires_at_utc": expires_at_utc,
    }
    payload.update(overrides)
    return payload


def license_ytd_payload(carry_in_barrels_ytd: float, **overrides: Any) -> Dict[str, Any]:
    """§3.6: the licence carry-in call names ``carry_in_barrels_ytd``."""
    payload: Dict[str, Any] = {"carry_in_barrels_ytd": carry_in_barrels_ytd}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Distributor appointments (§3.6)
# ---------------------------------------------------------------------------
def appointment_payload(
    state_license_id: str,
    expected_state_license_version: int,
    distributor_name: str = "Evergreen Beverage Distributors",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "state_license_id": state_license_id,
        "distributor_name": distributor_name,
        "expected_state_license_version": expected_state_license_version,
    }
    payload.update(overrides)
    return payload


def termination_payload(
    phase: str = TERMINATION_REQUEST, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"phase": phase}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Distribution orders (§3.7)
# ---------------------------------------------------------------------------
def order_payload(
    beer_id: str,
    state_license_id: str,
    bbl_requested: float = 2.00,
    ship_to_state_code: str = "WA",
    distance_miles: int = 240,
    requested_ship_utc: str = "2026-08-10T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "beer_id": beer_id,
        "state_license_id": state_license_id,
        "order_code": f"O-{unique_suffix()}",
        "bbl_requested": bbl_requested,
        "ship_to_state_code": ship_to_state_code,
        "distance_miles": distance_miles,
        "requested_ship_utc": requested_ship_utc,
    }
    payload.update(overrides)
    return payload


def cancel_order_payload(reason: str = "Customer withdrew", **overrides: Any) -> Dict[str, Any]:
    """§3.7: cancellation requires a ``reason``, stored as ``cancel_reason``."""
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Excise reports (§3.8)
# ---------------------------------------------------------------------------
def excise_report_payload(
    period_start_utc: str = "2026-08-01T00:00:00Z",
    period_end_utc: str = "2026-09-01T00:00:00Z",
    taproom_basis: str = BASIS_METERED_POUR,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "period_start_utc": period_start_utc,
        "period_end_utc": period_end_utc,
        "taproom_basis": taproom_basis,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Event permits (§3.9)
# ---------------------------------------------------------------------------
def event_permit_payload(
    featured_beer_id: str,
    venue_state_code: str = "WA",
    requested_bbl: float = 2.00,
    event_start_utc: str = "2026-08-15T12:00:00Z",
    event_end_utc: str = "2026-08-15T22:00:00Z",
    permit_type: str = PERMIT_FESTIVAL,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "featured_beer_id": featured_beer_id,
        "event_name": f"Harvest Fest {unique_suffix()}",
        "permit_type": permit_type,
        "venue_state_code": venue_state_code,
        "event_start_utc": event_start_utc,
        "event_end_utc": event_end_utc,
        "requested_bbl": requested_bbl,
    }
    payload.update(overrides)
    return payload


def permit_decision_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload
