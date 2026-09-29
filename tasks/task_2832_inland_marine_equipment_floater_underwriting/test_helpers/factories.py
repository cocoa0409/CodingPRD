"""Payload builders for every write endpoint.

Each builder produces the smallest payload the specification accepts and lets a
caller override any field. Money is always an integer number of cents and never a
string, rates are always integer basis points, calendar dates are always
``YYYY-MM-DD`` strings and instants are always ISO 8601 UTC, because the request
shape check rejects anything else with ERR_INVALID_REQUEST.
"""

from typing import Any, Dict, Optional

from .constants import (
    DEFAULT_DEDUCTIBLE_CENTS,
    TERM_EFFECTIVE_DATE,
    TERM_EXPIRATION_DATE,
)
from .types import (
    EquipmentType,
    LossType,
    Ownership,
    PartType,
    RatingBasis,
    TerritoryCode,
    TheftHazardGrade,
    ValuationBasis,
    VehicleOwnership,
)


def _merge(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides, dropping any key whose override is the sentinel None-drop."""
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not _DROP}


class _Drop:
    """Sentinel: pass ``DROP`` to remove a field from a payload entirely."""

    def __repr__(self) -> str:  # pragma: no cover
        return "<DROP>"


_DROP = _Drop()
DROP = _DROP


# ─── Rate cells ───────────────────────────────────────────────────────────────

def rate_rule(equipment_type: str = EquipmentType.EXCAVATOR,
              territory_code: str = TerritoryCode.T2_URBAN,
              age_band_min_years: int = 0,
              age_band_max_years: int = 5,
              base_rate_bp: int = 180,
              theft_hazard_grade: str = TheftHazardGrade.A,
              **overrides: Any) -> Dict[str, Any]:
    """A drafted rate cell for one equipment class, territory and age band."""
    return _merge({
        "equipment_type": equipment_type,
        "territory_code": territory_code,
        "age_band_min_years": age_band_min_years,
        "age_band_max_years": age_band_max_years,
        "base_rate_bp": base_rate_bp,
        "theft_hazard_grade": theft_hazard_grade,
    }, overrides)


# ─── Policies ─────────────────────────────────────────────────────────────────

def policy(policyholder_name: str = "Canonical Contractors",
           territory_code: str = TerritoryCode.T2_URBAN,
           effective_date: str = TERM_EFFECTIVE_DATE,
           expiration_date: str = TERM_EXPIRATION_DATE,
           minimum_premium_cents: Optional[int] = 100000,
           **overrides: Any) -> Dict[str, Any]:
    """A policy submission: named insured, territory and the two ends of the term."""
    payload: Dict[str, Any] = {
        "policyholder_name": policyholder_name,
        "territory_code": territory_code,
        "effective_date": effective_date,
        "expiration_date": expiration_date,
    }
    if minimum_premium_cents is not None:
        payload["minimum_premium_cents"] = minimum_premium_cents
    return _merge(payload, overrides)


def cancellation(cancellation_reason: str, cancel_effective_date: str,
                 **overrides: Any) -> Dict[str, Any]:
    return _merge({
        "cancellation_reason": cancellation_reason,
        "cancel_effective_date": cancel_effective_date,
    }, overrides)


def referral_decision(decision: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


def referral(referral_note: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if referral_note is not None:
        payload["referral_note"] = referral_note
    return _merge(payload, overrides)


# ─── Coverage parts ───────────────────────────────────────────────────────────

def scheduled_equipment_part(valuation_basis: str = ValuationBasis.ACV,
                             rating_basis: str = RatingBasis.SCHEDULED,
                             deductible_cents: int = DEFAULT_DEDUCTIBLE_CENTS,
                             per_item_limit_cents: Optional[int] = 20000000,
                             aggregate_limit_cents: int = 200000000,
                             **overrides: Any) -> Dict[str, Any]:
    """A scheduled-equipment part: individually rated units under one aggregate."""
    payload: Dict[str, Any] = {
        "part_type": PartType.SCHEDULED_EQUIPMENT,
        "valuation_basis": valuation_basis,
        "rating_basis": rating_basis,
        "deductible_cents": deductible_cents,
        "aggregate_limit_cents": aggregate_limit_cents,
    }
    if per_item_limit_cents is not None:
        payload["per_item_limit_cents"] = per_item_limit_cents
    return _merge(payload, overrides)


def blanket_equipment_part(blanket_limit_cents: int = 10000000,
                           valuation_basis: str = ValuationBasis.ACV,
                           rating_basis: str = RatingBasis.BLANKET,
                           coinsurance_pct_bp: Optional[int] = None,
                           deductible_cents: int = DEFAULT_DEDUCTIBLE_CENTS,
                           aggregate_limit_cents: int = 200000000,
                           **overrides: Any) -> Dict[str, Any]:
    """A blanket-equipment part: one limit over the whole schedule."""
    payload: Dict[str, Any] = {
        "part_type": PartType.BLANKET_EQUIPMENT,
        "valuation_basis": valuation_basis,
        "rating_basis": rating_basis,
        "deductible_cents": deductible_cents,
        "aggregate_limit_cents": aggregate_limit_cents,
        "blanket_limit_cents": blanket_limit_cents,
    }
    if coinsurance_pct_bp is not None:
        payload["coinsurance_pct_bp"] = coinsurance_pct_bp
    return _merge(payload, overrides)


def rented_leased_part(per_item_limit_cents: int = 20000000,
                       loss_of_use_daily_limit_cents: int = 50000,
                       loss_of_use_max_days: int = 10,
                       valuation_basis: str = ValuationBasis.ACV,
                       rating_basis: str = RatingBasis.SCHEDULED,
                       deductible_cents: int = DEFAULT_DEDUCTIBLE_CENTS,
                       aggregate_limit_cents: int = 200000000,
                       **overrides: Any) -> Dict[str, Any]:
    """A rented-and-leased part: the only part the loss-of-use extension pays on."""
    return _merge({
        "part_type": PartType.RENTED_LEASED,
        "valuation_basis": valuation_basis,
        "rating_basis": rating_basis,
        "deductible_cents": deductible_cents,
        "aggregate_limit_cents": aggregate_limit_cents,
        "per_item_limit_cents": per_item_limit_cents,
        "loss_of_use_daily_limit_cents": loss_of_use_daily_limit_cents,
        "loss_of_use_max_days": loss_of_use_max_days,
    }, overrides)


def installation_floater_part(valuation_basis: str = ValuationBasis.ACV,
                              deductible_cents: int = DEFAULT_DEDUCTIBLE_CENTS,
                              aggregate_limit_cents: int = 200000000,
                              **overrides: Any) -> Dict[str, Any]:
    """An installation-floater part: coverage that ends at acceptance or occupancy."""
    return _merge({
        "part_type": PartType.INSTALLATION_FLOATER,
        "valuation_basis": valuation_basis,
        "deductible_cents": deductible_cents,
        "aggregate_limit_cents": aggregate_limit_cents,
    }, overrides)


def transit_part(transit_owned_limit_cents: int = 4000000,
                 transit_hired_limit_cents: int = 3000000,
                 catastrophe_limit_cents: int = 2000000,
                 valuation_basis: str = ValuationBasis.ACV,
                 deductible_cents: int = DEFAULT_DEDUCTIBLE_CENTS,
                 aggregate_limit_cents: int = 200000000,
                 **overrides: Any) -> Dict[str, Any]:
    """A transit part: three competing limits and a catastrophe tier."""
    return _merge({
        "part_type": PartType.TRANSIT,
        "valuation_basis": valuation_basis,
        "deductible_cents": deductible_cents,
        "aggregate_limit_cents": aggregate_limit_cents,
        "transit_owned_limit_cents": transit_owned_limit_cents,
        "transit_hired_limit_cents": transit_hired_limit_cents,
        "catastrophe_limit_cents": catastrophe_limit_cents,
    }, overrides)


def reporting_form_part(reporting_frequency: str = "MONTHLY",
                        reporting_annual_rate_bp: int = 250,
                        reporting_limit_cents: int = 20000000,
                        valuation_basis: str = ValuationBasis.ACV,
                        deductible_cents: int = DEFAULT_DEDUCTIBLE_CENTS,
                        aggregate_limit_cents: int = 200000000,
                        **overrides: Any) -> Dict[str, Any]:
    """A reporting-form part: the insured declares the values at risk each period."""
    return _merge({
        "part_type": PartType.REPORTING_FORM,
        "valuation_basis": valuation_basis,
        "deductible_cents": deductible_cents,
        "aggregate_limit_cents": aggregate_limit_cents,
        "reporting_frequency": reporting_frequency,
        "reporting_annual_rate_bp": reporting_annual_rate_bp,
        "reporting_limit_cents": reporting_limit_cents,
    }, overrides)


def part_endorsement(**fields: Any) -> Dict[str, Any]:
    """An endorsement of a part's terms: only the supplied fields change."""
    return dict(fields)


# ─── Equipment items ──────────────────────────────────────────────────────────

def equipment_item(expected_policy_version: int,
                   description: str = "Excavator E1",
                   equipment_type: str = EquipmentType.EXCAVATOR,
                   model_year: int = 2022,
                   original_cost_cents: int = 12000000,
                   ownership: str = Ownership.OWNED,
                   stated_value_cents: Optional[int] = None,
                   geo_tracker_installed: Optional[bool] = None,
                   valuation_basis: Optional[str] = None,
                   assigned_jobsite_id: Optional[str] = None,
                   **overrides: Any) -> Dict[str, Any]:
    """A unit scheduled onto a part, carrying the required policy version token."""
    payload: Dict[str, Any] = {
        "description": description,
        "equipment_type": equipment_type,
        "model_year": model_year,
        "original_cost_cents": original_cost_cents,
        "ownership": ownership,
        "expected_policy_version": expected_policy_version,
    }
    if stated_value_cents is not None:
        payload["stated_value_cents"] = stated_value_cents
    if geo_tracker_installed is not None:
        payload["geo_tracker_installed"] = geo_tracker_installed
    if valuation_basis is not None:
        payload["valuation_basis"] = valuation_basis
    if assigned_jobsite_id is not None:
        payload["assigned_jobsite_id"] = assigned_jobsite_id
    return _merge(payload, overrides)


def jobsite_assignment(jobsite_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"jobsite_id": jobsite_id}, overrides)


# ─── Jobsites ─────────────────────────────────────────────────────────────────

def jobsite(name: str = "Canonical Yard",
            territory_code: str = TerritoryCode.T2_URBAN,
            **overrides: Any) -> Dict[str, Any]:
    return _merge({"name": name, "territory_code": territory_code}, overrides)


def security_survey(fenced: bool = False, lighting: bool = False,
                    alarm_monitored: bool = False, guarded_24h: bool = False,
                    **overrides: Any) -> Dict[str, Any]:
    """The four boolean theft controls a survey records."""
    return _merge({
        "fenced": fenced,
        "lighting": lighting,
        "alarm_monitored": alarm_monitored,
        "guarded_24h": guarded_24h,
    }, overrides)


SURVEY_TIER_0 = dict(fenced=False, lighting=False, alarm_monitored=False,
                     guarded_24h=False)
SURVEY_TIER_1 = dict(fenced=True, lighting=False, alarm_monitored=False,
                     guarded_24h=False)
SURVEY_TIER_2 = dict(fenced=True, lighting=True, alarm_monitored=True,
                     guarded_24h=False)
SURVEY_TIER_3 = dict(fenced=True, lighting=True, alarm_monitored=True,
                     guarded_24h=True)


# ─── Installation floaters ────────────────────────────────────────────────────

def installation_floater(jobsite_id: str,
                         coverage_start_date: str = "2026-08-01",
                         coverage_end_date: str = "2026-12-01",
                         project_name: str = "Canonical Project",
                         installed_value_limit_cents: int = 15000000,
                         **overrides: Any) -> Dict[str, Any]:
    """A floater on one project on one jobsite over a closed date interval."""
    return _merge({
        "jobsite_id": jobsite_id,
        "project_name": project_name,
        "installed_value_limit_cents": installed_value_limit_cents,
        "coverage_start_date": coverage_start_date,
        "coverage_end_date": coverage_end_date,
    }, overrides)


def floater_termination(termination_reason: str, termination_date: str,
                        **overrides: Any) -> Dict[str, Any]:
    return _merge({
        "termination_reason": termination_reason,
        "termination_date": termination_date,
    }, overrides)


# ─── Conveyances and shipments ────────────────────────────────────────────────

def vehicle(unit_label: str = "Truck 1",
            ownership: str = VehicleOwnership.OWNED,
            per_conveyance_limit_cents: int = 5000000,
            carrier_name: Optional[str] = None,
            approval_expires_on: Optional[str] = None,
            **overrides: Any) -> Dict[str, Any]:
    """A conveyance registered independently of any policy."""
    payload: Dict[str, Any] = {
        "unit_label": unit_label,
        "ownership": ownership,
        "per_conveyance_limit_cents": per_conveyance_limit_cents,
    }
    if carrier_name is not None:
        payload["carrier_name"] = carrier_name
    if approval_expires_on is not None:
        payload["approval_expires_on"] = approval_expires_on
    return _merge(payload, overrides)


def vehicle_approval(approval_expires_on: Optional[str] = None,
                     **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if approval_expires_on is not None:
        payload["approval_expires_on"] = approval_expires_on
    return _merge(payload, overrides)


def transit_shipment(vehicle_id: str,
                     origin_territory_code: str = TerritoryCode.T3_INLAND,
                     destination_territory_code: str = TerritoryCode.T2_URBAN,
                     departure_at: str = "2026-08-05T08:00:00Z",
                     arrival_at: str = "2026-08-05T18:00:00Z",
                     declared_value_cents: int = 1000000,
                     **overrides: Any) -> Dict[str, Any]:
    """A planned movement on a half-open instant window."""
    return _merge({
        "vehicle_id": vehicle_id,
        "origin_territory_code": origin_territory_code,
        "destination_territory_code": destination_territory_code,
        "departure_at": departure_at,
        "arrival_at": arrival_at,
        "declared_value_cents": declared_value_cents,
    }, overrides)


# ─── Value reports ────────────────────────────────────────────────────────────

def value_report(period_start_date: str, period_end_date: str,
                 reported_value_cents: int,
                 expected_coverage_part_version: int,
                 **overrides: Any) -> Dict[str, Any]:
    """A periodic declared-value filing, carrying the part version token."""
    return _merge({
        "period_start_date": period_start_date,
        "period_end_date": period_end_date,
        "reported_value_cents": reported_value_cents,
        "expected_coverage_part_version": expected_coverage_part_version,
    }, overrides)


# ─── Claims ───────────────────────────────────────────────────────────────────

def claim(coverage_part_id: str,
          loss_date: str = "2026-08-01",
          loss_type: str = LossType.FIRE,
          equipment_item_id: Optional[str] = None,
          transit_shipment_id: Optional[str] = None,
          installation_floater_id: Optional[str] = None,
          **overrides: Any) -> Dict[str, Any]:
    """A loss report naming one coverage part and exactly one loss subject."""
    payload: Dict[str, Any] = {
        "coverage_part_id": coverage_part_id,
        "loss_date": loss_date,
        "loss_type": loss_type,
    }
    if equipment_item_id is not None:
        payload["equipment_item_id"] = equipment_item_id
    if transit_shipment_id is not None:
        payload["transit_shipment_id"] = transit_shipment_id
    if installation_floater_id is not None:
        payload["installation_floater_id"] = installation_floater_id
    return _merge(payload, overrides)


def inspection(repair_estimate_cents: int, actual_value_at_loss_cents: int,
               **overrides: Any) -> Dict[str, Any]:
    return _merge({
        "repair_estimate_cents": repair_estimate_cents,
        "actual_value_at_loss_cents": actual_value_at_loss_cents,
    }, overrides)


def adjustment(adjustment_basis: str,
               loss_of_use_days_claimed: Optional[int] = None,
               **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"adjustment_basis": adjustment_basis}
    if loss_of_use_days_claimed is not None:
        payload["loss_of_use_days_claimed"] = loss_of_use_days_claimed
    return _merge(payload, overrides)


def salvage(salvage_proceeds_cents: int, **overrides: Any) -> Dict[str, Any]:
    return _merge({"salvage_proceeds_cents": salvage_proceeds_cents}, overrides)
