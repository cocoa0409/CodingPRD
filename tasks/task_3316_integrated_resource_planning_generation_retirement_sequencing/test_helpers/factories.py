"""Payload factories — one per entity, input fields only (PRD §4)."""
import itertools

_name_counter = itertools.count(1)


def _unique(prefix: str) -> str:
    return f"{prefix}-{next(_name_counter)}"


def create_plan_payload(**overrides) -> dict:
    defaults = {
        "plan_name": _unique("IRP"),
        "cycle_year": 2026,
        "planning_horizon_years": 15,
    }
    defaults.update(overrides)
    return defaults


def create_forecast_payload(**overrides) -> dict:
    defaults = {
        "scenario_tag": "BASE",
        "forecast_year": 2030,
        "residential_mw": 10,
        "commercial_mw": 0,
        "industrial_mw": 0,
        "electrification_mw": 0,
    }
    defaults.update(overrides)
    return defaults


def create_resource_payload(**overrides) -> dict:
    defaults = {
        "unit_name": _unique("UNIT"),
        "resource_type": "COAL",
        "nameplate_mw": 300,
        "in_service_year": 1990,
        "fuel_type": "COAL",
    }
    defaults.update(overrides)
    return defaults


def create_portfolio_payload(**overrides) -> dict:
    defaults = {
        "portfolio_name": _unique("PF"),
    }
    defaults.update(overrides)
    return defaults


def create_candidate_payload(**overrides) -> dict:
    defaults = {
        "candidate_name": _unique("K"),
        "resource_type": "SOLAR",
        "nameplate_mw": 100,
        "online_year": 2028,
        "capex_usd_per_kw": 900,
        "fixed_om_usd_per_kw_year": 10,
        "fuel_type": "SUN",
        "build_lead_years": 2,
    }
    defaults.update(overrides)
    return defaults


def create_position_payload(candidate_id: str, **overrides) -> dict:
    defaults = {
        "candidate_id": candidate_id,
        "committed_mw": 50,
    }
    defaults.update(overrides)
    return defaults


def create_snapshot_payload(expected_portfolio_version: int, **overrides) -> dict:
    defaults = {
        "forecast_year": 2030,
        "scenario_tag": "BASE",
        "fuel_price_usd_per_mmbtu": 4.00,
        "expected_portfolio_version": expected_portfolio_version,
    }
    defaults.update(overrides)
    return defaults


def create_retirement_analysis_payload(plan_id: str, snapshot_id: str, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "snapshot_id": snapshot_id,
    }
    defaults.update(overrides)
    return defaults


def create_comment_payload(**overrides) -> dict:
    defaults = {
        "commenter_name": "Jane Public",
        "commenter_email": "jane@example.org",
        "body": "A public comment on the plan.",
    }
    defaults.update(overrides)
    return defaults


def create_intervenor_payload(**overrides) -> dict:
    defaults = {
        "legal_name": _unique("Intervenor"),
        "party_type": "CONSUMER_ADVOCATE",
    }
    defaults.update(overrides)
    return defaults


def create_testimony_payload(intervenor_id: str, **overrides) -> dict:
    defaults = {
        "intervenor_id": intervenor_id,
        "topic": "Load forecast",
        "body": "The electrification adder is understated.",
    }
    defaults.update(overrides)
    return defaults


def create_sensitivity_payload(snapshot_id: str, **overrides) -> dict:
    defaults = {
        "snapshot_id": snapshot_id,
        "dimension": "FUEL_PRICE",
        "delta_pct": 0.25,
    }
    defaults.update(overrides)
    return defaults


def create_commitment_payload(**overrides) -> dict:
    defaults = {
        "committed_mw": 50,
        "solicitation_type": "RFP",
    }
    defaults.update(overrides)
    return defaults


def create_deviation_report_payload(**overrides) -> dict:
    defaults = {
        "report_year": 2031,
        "actual_load_mw": 400,
    }
    defaults.update(overrides)
    return defaults


def create_condition_element(**overrides) -> dict:
    """One element of the commission-review conditions[] payload."""
    defaults = {
        "description": "Procure additional capacity",
        "required_procurement_mw": 50,
    }
    defaults.update(overrides)
    return defaults
