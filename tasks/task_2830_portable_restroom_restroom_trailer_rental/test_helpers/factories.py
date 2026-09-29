"""Request payload factories — one per write operation, input fields only.

Money is always emitted as an integer number of whole cents (a JSON number,
never a string). Calendar-date fields are `YYYY-MM-DD` strings and the only
instant a client ever sends is the logical clock's `to_iso8601`.

Pass ``OMIT`` as an override value to drop a key from the payload entirely,
which is how tests probe the PRD's declared defaults and required fields.
"""

from typing import Any, Dict, List, Optional


class _Omit:
    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "OMIT"


OMIT = _Omit()


def _finalize(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload.update(overrides)
    return {k: v for k, v in payload.items() if not isinstance(v, _Omit)}


# ─── Reference data ───────────────────────────────────────────────────────

def rental_account_payload(**overrides) -> Dict[str, Any]:
    return _finalize(
        {
            "legal_name": "Test Rentals LLC",
            "account_type": "CONSTRUCTION",
            "credit_terms_days": 30,
        },
        overrides,
    )


def service_site_payload(account_id: str, **overrides) -> Dict[str, Any]:
    return _finalize(
        {
            "account_id": account_id,
            "site_label": "Test Placement Site",
            "jurisdiction_code": "CA-SD-CITY",
            "access_class": "OPEN_LOT",
            "right_of_way_required": False,
            "gate_open_minute": 360,
            "gate_close_minute": 1080,
            "max_truck_length_ft": 40,
        },
        overrides,
    )


def placement_permit_payload(site_id: str, **overrides) -> Dict[str, Any]:
    return _finalize(
        {
            "site_id": site_id,
            "permit_kind": "PLACEMENT",
            "authority_ref": "PL-0001",
            "effective_from": "2026-08-01",
            "effective_to": "2026-12-31",
        },
        overrides,
    )


def permit_approval_payload(authority_decision_ref: str = "AD-0001", **overrides):
    return _finalize({"authority_decision_ref": authority_decision_ref}, overrides)


def permit_rejection_payload(
    authority_decision_ref: str = "AD-0001",
    rejection_reason: str = "insufficient traffic control plan",
    **overrides,
) -> Dict[str, Any]:
    return _finalize(
        {
            "authority_decision_ref": authority_decision_ref,
            "rejection_reason": rejection_reason,
        },
        overrides,
    )


def asset_unit_payload(**overrides) -> Dict[str, Any]:
    return _finalize(
        {
            "asset_tag": "SP-0001",
            "unit_class": "STANDARD_PORTABLE",
            "yard_code": "YD-1",
            "tare_length_ft": 8,
        },
        overrides,
    )


def disposal_site_payload(**overrides) -> Dict[str, Any]:
    return _finalize(
        {
            "site_code": "DS-0001",
            "daily_gallon_cap": 5000,
            "accepted_waste_classes": ["BLACKWATER"],
            "status": "ACCEPTING",
        },
        overrides,
    )


def route_payload(**overrides) -> Dict[str, Any]:
    return _finalize(
        {
            "route_code": "RT-MON-1",
            "service_day": "MON",
            "truck_capacity_units": 20,
            "waste_capacity_gallons": 3000,
        },
        overrides,
    )


# ─── Contracts and quoting ────────────────────────────────────────────────

def rental_contract_payload(account_id: str, site_id: str, **overrides):
    """CONSTRUCTION shape: headcount 40, three visits a week, no accessible units.

    Quotes to five standard portables plus two handwash stations — seven units
    on the route, 91500 cents.
    """
    return _finalize(
        {
            "account_id": account_id,
            "site_id": site_id,
            "contract_kind": "CONSTRUCTION",
            "term_start": "2026-08-03",
            "term_end": "2026-09-30",
            "headcount": 40,
            "event_duration_hours": 8,
            "service_frequency_per_week": 3,
            "season_code": "OFF",
            "construction_phase": "SITEWORK",
            "ada_required": False,
        },
        overrides,
    )


def thirteen_unit_contract_payload(account_id: str, site_id: str, **overrides):
    """CONSTRUCTION shape: headcount 60, twice a week, accessible units required.

    Quotes to nine standard portables, one accessible unit and three handwash
    stations — thirteen units on the route, 181500 cents.
    """
    defaults = {
        "account_id": account_id,
        "site_id": site_id,
        "contract_kind": "CONSTRUCTION",
        "term_start": "2026-08-03",
        "term_end": "2026-09-30",
        "headcount": 60,
        "event_duration_hours": 8,
        "service_frequency_per_week": 2,
        "season_code": "SHOULDER",
        "construction_phase": "VERTICAL",
        "ada_required": True,
    }
    return _finalize(defaults, overrides)


def event_contract_payload(account_id: str, site_id: str, **overrides):
    """EVENT shape; an EVENT contract must carry `EVENT_NA` as its phase."""
    return _finalize(
        {
            "account_id": account_id,
            "site_id": site_id,
            "contract_kind": "EVENT",
            "term_start": "2026-08-03",
            "term_end": "2026-08-20",
            "headcount": 399,
            "event_duration_hours": 12,
            "service_frequency_per_week": 3,
            "season_code": "PEAK",
            "construction_phase": "EVENT_NA",
            "ada_required": True,
        },
        overrides,
    )


def quote_payload(expected_contract_version: int, quote_note: Any = OMIT):
    return _finalize(
        {
            "expected_contract_version": expected_contract_version,
            "quote_note": quote_note,
        },
        {},
    )


# ─── Field commitments ────────────────────────────────────────────────────

def unit_deployment_payload(
    contract_id: str, asset_unit_id: str, **overrides
) -> Dict[str, Any]:
    return _finalize(
        {
            "contract_id": contract_id,
            "asset_unit_id": asset_unit_id,
            "deploy_from": "2026-08-03",
            "deploy_to": "2026-09-30",
        },
        overrides,
    )


def relocation_payload(
    destination_site_id: str,
    effective_date: str,
    relocation_reason: Any = OMIT,
    **overrides,
) -> Dict[str, Any]:
    return _finalize(
        {
            "destination_site_id": destination_site_id,
            "effective_date": effective_date,
            "relocation_reason": relocation_reason,
        },
        overrides,
    )


def service_schedule_payload(
    contract_id: str, route_id: str, **overrides
) -> Dict[str, Any]:
    return _finalize(
        {
            "contract_id": contract_id,
            "route_id": route_id,
            "service_day": "MON",
            "window_start_minute": 480,
            "window_end_minute": 600,
        },
        overrides,
    )


def schedule_suspension_payload(suspension_reason: Any = OMIT) -> Dict[str, Any]:
    return _finalize({"suspension_reason": suspension_reason}, {})


def service_visit_payload(schedule_id: str, **overrides) -> Dict[str, Any]:
    return _finalize(
        {
            "schedule_id": schedule_id,
            "visit_kind": "SERVICE",
            "scheduled_date": "2026-08-10",
            "window_start_minute": 480,
            "window_end_minute": 540,
        },
        overrides,
    )


def visit_completion_payload(gallons_pumped: int, **overrides) -> Dict[str, Any]:
    return _finalize({"gallons_pumped": gallons_pumped}, overrides)


def missed_visit_payload(
    missed_reason: str = "truck breakdown", **overrides
) -> Dict[str, Any]:
    return _finalize({"missed_reason": missed_reason}, overrides)


def rerun_payload(
    rerun_date: str,
    window_start_minute: int = 480,
    window_end_minute: int = 540,
    **overrides,
) -> Dict[str, Any]:
    return _finalize(
        {
            "rerun_date": rerun_date,
            "window_start_minute": window_start_minute,
            "window_end_minute": window_end_minute,
        },
        overrides,
    )


# ─── Waste hauling ────────────────────────────────────────────────────────

def waste_manifest_payload(
    route_id: str, disposal_site_id: str, **overrides
) -> Dict[str, Any]:
    return _finalize(
        {
            "route_id": route_id,
            "disposal_site_id": disposal_site_id,
            "manifest_date": "2026-08-10",
            "waste_class": "BLACKWATER",
        },
        overrides,
    )


def manifest_seal_payload(
    expected_route_version: int, seal_note: Any = OMIT
) -> Dict[str, Any]:
    return _finalize(
        {
            "expected_route_version": expected_route_version,
            "seal_note": seal_note,
        },
        {},
    )


def manifest_acceptance_payload(acceptance_note: Any = OMIT) -> Dict[str, Any]:
    return _finalize({"acceptance_note": acceptance_note}, {})


# ─── Charges ──────────────────────────────────────────────────────────────

def charge_event_payload(
    contract_id: str,
    asset_unit_id: str,
    charge_kind: str = "DAMAGE",
    severity: Any = OMIT,
    **overrides,
) -> Dict[str, Any]:
    return _finalize(
        {
            "contract_id": contract_id,
            "asset_unit_id": asset_unit_id,
            "charge_kind": charge_kind,
            "severity": severity,
        },
        overrides,
    )


def damage_charge_payload(
    contract_id: str, asset_unit_id: str, severity: str = "MODERATE", **overrides
) -> Dict[str, Any]:
    return charge_event_payload(
        contract_id, asset_unit_id, "DAMAGE", severity, **overrides
    )


def tip_over_charge_payload(
    contract_id: str, asset_unit_id: str, **overrides
) -> Dict[str, Any]:
    return charge_event_payload(
        contract_id, asset_unit_id, "TIP_OVER", OMIT, **overrides
    )


def dispute_payload(
    dispute_reason: str = "the unit was already damaged on delivery", **overrides
) -> Dict[str, Any]:
    return _finalize({"dispute_reason": dispute_reason}, overrides)


def resolution_payload(resolution_note: Any = OMIT) -> Dict[str, Any]:
    return _finalize({"resolution_note": resolution_note}, {})


def demobilization_payload(demobilization_note: Any = OMIT) -> Dict[str, Any]:
    return _finalize({"demobilization_note": demobilization_note}, {})


def settlement_payload(payment_reference: Any = OMIT) -> Dict[str, Any]:
    return _finalize({"payment_reference": payment_reference}, {})


def accepted_waste_classes(*classes: str) -> List[str]:
    """Non-empty array of distinct waste classes."""
    return list(dict.fromkeys(classes))


def optional_or_omit(value: Optional[Any]) -> Any:
    """Pass a value through, mapping ``None`` onto ``OMIT``."""
    return OMIT if value is None else value
