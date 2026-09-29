"""Request payload factories.

Every factory returns a payload that satisfies the PRD's shape rules, and
accepts keyword overrides so a test can vary exactly one field. Money is sent
as JSON numbers carried to two decimal places, fuel prices as JSON numbers
carried to four, month strings in `YYYY-MM` form, and every instant as a full
ISO-8601 UTC datetime with a `Z` suffix — never a date-only literal.
"""

from typing import Any, Dict

from .constants import (
    BASIS_STRICT,
    PAYMENT_BASIS_COMPLETED_FLIGHT_PRORATION,
    PETITION_REASON_SERVICE_QUALITY,
    SERVICE_LEVEL_ESSENTIAL_MINIMUM,
    TRIGGER_COST_INCREASE,
    TRIGGER_FUEL_INDEX,
)


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides; a value of ``None`` removes the key entirely."""
    payload = dict(base)
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# ─── clock ───────────────────────────────────────────────────────────

def clock_payload(to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}


# ─── communities ─────────────────────────────────────────────────────

def community_payload(**overrides) -> Dict[str, Any]:
    """A CAPPED-band community with a 12 round-trip / 400 seat service floor."""
    return _merge(
        {
            "code": "HYS",
            "name": "Hays",
            "state_code": "KS",
            "driving_miles_to_nearest_hub": 165.0,
            "enplanements_prior_year": 6200,
            "min_required_weekly_round_trips": 12,
            "min_required_weekly_seats": 400,
        },
        overrides,
    )


def second_community_payload(**overrides) -> Dict[str, Any]:
    """A second CAPPED-band community used as an isolation control."""
    return _merge(
        {
            "code": "DDC",
            "name": "Dodge City",
            "state_code": "KS",
            "driving_miles_to_nearest_hub": 152.0,
            "enplanements_prior_year": 6200,
            "min_required_weekly_round_trips": 12,
            "min_required_weekly_seats": 400,
        },
        overrides,
    )


def determination_payload(**overrides) -> Dict[str, Any]:
    return _merge({"waiver_requested": False}, overrides)


# ─── carriers ────────────────────────────────────────────────────────

def carrier_payload(**overrides) -> Dict[str, Any]:
    return _merge({"name": "Prairie Air", "certificate_number": "CERT-1001"}, overrides)


def second_carrier_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {"name": "Frontier Regional", "certificate_number": "CERT-1002"}, overrides
    )


def carrier_standing_payload(action: str, **overrides) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


# ─── aircraft types ──────────────────────────────────────────────────

def aircraft_type_payload(**overrides) -> Dict[str, Any]:
    """19-seat turboprop: the equipment the canonical proposal offers."""
    return _merge(
        {
            "code": "B190",
            "name": "Beechcraft 1900D",
            "seats": 19,
            "is_jet": False,
            "fuel_burn_gal_per_hour": 68.0,
            "hourly_operating_cost_usd": 1450.00,
        },
        overrides,
    )


def larger_aircraft_type_payload(**overrides) -> Dict[str, Any]:
    """34-seat turboprop."""
    return _merge(
        {
            "code": "SF34",
            "name": "Saab 340B",
            "seats": 34,
            "is_jet": False,
            "fuel_burn_gal_per_hour": 110.0,
            "hourly_operating_cost_usd": 2100.00,
        },
        overrides,
    )


def jet_aircraft_type_payload(**overrides) -> Dict[str, Any]:
    """50-seat regional jet."""
    return _merge(
        {
            "code": "CRJ2",
            "name": "Bombardier CRJ200",
            "seats": 50,
            "is_jet": True,
            "fuel_burn_gal_per_hour": 610.0,
            "hourly_operating_cost_usd": 3900.00,
        },
        overrides,
    )


def retire_payload(**overrides) -> Dict[str, Any]:
    return _merge({"note": "Removed from the approved list."}, overrides)


# ─── fuel indices ────────────────────────────────────────────────────

def fuel_index_payload(index_month: str = "2026-08",
                       price_per_gallon_usd: float = 2.4000,
                       **overrides) -> Dict[str, Any]:
    return _merge(
        {"index_month": index_month, "price_per_gallon_usd": price_per_gallon_usd},
        overrides,
    )


# ─── solicitations ───────────────────────────────────────────────────

def solicitation_payload(community_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {"community_id": community_id, "closes_at": "2026-08-20T00:00:00Z"}, overrides
    )


def solicitation_action_payload(action: str, **overrides) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


def preference_filing_payload(expected_solicitation_version: int,
                              rankings, **overrides) -> Dict[str, Any]:
    """`rankings` is a list of {"proposal_id": ..., "rank": ...} entries."""
    return _merge(
        {
            "expected_solicitation_version": expected_solicitation_version,
            "rankings": list(rankings),
        },
        overrides,
    )


def ranking_entries(*proposal_ids) -> list:
    """Rank the given proposals 1..N in the order supplied."""
    return [
        {"proposal_id": pid, "rank": index}
        for index, pid in enumerate(proposal_ids, start=1)
    ]


def selection_order_payload(**overrides) -> Dict[str, Any]:
    return _merge({"order_note": "Award issued on the ranked candidate set."}, overrides)


# ─── proposals ───────────────────────────────────────────────────────

def proposal_payload(solicitation_id: str, carrier_id: str,
                     aircraft_type_id: str, **overrides) -> Dict[str, Any]:
    """12 round trips on 19 seats for 1,600,000.00 over 24 months."""
    return _merge(
        {
            "solicitation_id": solicitation_id,
            "carrier_id": carrier_id,
            "aircraft_type_id": aircraft_type_id,
            "service_level": SERVICE_LEVEL_ESSENTIAL_MINIMUM,
            "weekly_round_trips": 12,
            "seats_per_departure": 19,
            "annual_subsidy_request_usd": 1600000.00,
            "term_months": 24,
            "payment_basis": PAYMENT_BASIS_COMPLETED_FLIGHT_PRORATION,
        },
        overrides,
    )


def proposal_action_payload(action: str, **overrides) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


# ─── service agreements ──────────────────────────────────────────────

def agreement_status_payload(action: str, **overrides) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


# ─── service periods ─────────────────────────────────────────────────

def service_period_payload(agreement_id: str, period_month: str,
                           **overrides) -> Dict[str, Any]:
    return _merge(
        {"agreement_id": agreement_id, "period_month": period_month}, overrides
    )


def report_payload(scheduled_departures: int = 104,
                   completed_departures: int = 91,
                   cancelled_carrier_departures: int = 5,
                   cancelled_weather_departures: int = 8,
                   seats_offered: int = 1729,
                   passengers_enplaned: int = 620,
                   **overrides) -> Dict[str, Any]:
    """A balanced month: 91 + 5 + 8 == 104 and 620 passengers on 1729 seats."""
    return _merge(
        {
            "scheduled_departures": scheduled_departures,
            "completed_departures": completed_departures,
            "cancelled_carrier_departures": cancelled_carrier_departures,
            "cancelled_weather_departures": cancelled_weather_departures,
            "seats_offered": seats_offered,
            "passengers_enplaned": passengers_enplaned,
        },
        overrides,
    )


def amend_payload(expected_agreement_version: int, **overrides) -> Dict[str, Any]:
    payload = report_payload()
    payload["expected_agreement_version"] = expected_agreement_version
    return _merge(payload, overrides)


def certify_payload(**overrides) -> Dict[str, Any]:
    return _merge({"certification_note": "Month settled."}, overrides)


# ─── subsidy payments ────────────────────────────────────────────────

def payment_action_payload(action: str, **overrides) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


# ─── performance reviews ─────────────────────────────────────────────

def performance_review_payload(agreement_id: str, window_start_month: str,
                               window_end_month: str,
                               basis: str = BASIS_STRICT,
                               **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "agreement_id": agreement_id,
            "basis": basis,
            "window_start_month": window_start_month,
            "window_end_month": window_end_month,
        },
        overrides,
    )


# ─── termination petitions ───────────────────────────────────────────

def petition_payload(community_id: str, agreement_id: str,
                     **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "community_id": community_id,
            "agreement_id": agreement_id,
            "reason_code": PETITION_REASON_SERVICE_QUALITY,
            "narrative": "Service quality has fallen below community expectations.",
            "requested_effective_at": "2026-12-01T00:00:00Z",
        },
        overrides,
    )


def petition_decision_payload(action: str, **overrides) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


def petition_withdraw_payload(**overrides) -> Dict[str, Any]:
    return _merge({"withdraw_note": "No longer pursued."}, overrides)


# ─── rate renegotiations ─────────────────────────────────────────────

def fuel_renegotiation_payload(agreement_id: str, fuel_index_month: str,
                               requested_annual_subsidy_usd: float,
                               **overrides) -> Dict[str, Any]:
    """A FUEL_INDEX filing: carries fuel_index_month and omits the cost field."""
    return _merge(
        {
            "agreement_id": agreement_id,
            "trigger_type": TRIGGER_FUEL_INDEX,
            "fuel_index_month": fuel_index_month,
            "requested_annual_subsidy_usd": requested_annual_subsidy_usd,
            "justification": "Fuel prices have moved against the agreed rate.",
        },
        overrides,
    )


def cost_renegotiation_payload(agreement_id: str,
                               documented_cost_increase_pct: float,
                               requested_annual_subsidy_usd: float,
                               **overrides) -> Dict[str, Any]:
    """A COST_INCREASE filing: carries the pct and omits the fuel month."""
    return _merge(
        {
            "agreement_id": agreement_id,
            "trigger_type": TRIGGER_COST_INCREASE,
            "documented_cost_increase_pct": documented_cost_increase_pct,
            "requested_annual_subsidy_usd": requested_annual_subsidy_usd,
            "justification": "Documented non-fuel cost escalation.",
        },
        overrides,
    )


def renegotiation_action_payload(action: str, **overrides) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)
