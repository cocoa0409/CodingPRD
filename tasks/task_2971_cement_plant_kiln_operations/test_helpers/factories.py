"""Request payload builders.

Every numeric field is emitted as a JSON number and every instant as a full
ISO 8601 UTC instant, matching the granularity the PRD declares for that field.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    BATCH_BLAINE_TARGET,
    BATCH_CLINKER_DRAWN,
    BATCH_GYPSUM_PCT,
    BATCH_LIMESTONE_PCT,
    CEMENT_SILO_CAPACITY,
    CEMENT_SILO_DRAW_RATE,
    CEMENT_SILO_SPOUTS,
    CLAY_ANALYSIS,
    CLINKER_SILO_CAPACITY,
    CLINKER_SILO_DRAW_RATE,
    COAL_ANALYSIS,
    IRON_ORE_ANALYSIS,
    KILN_COOLDOWN_BUFFER_HOURS,
    KILN_NOMINAL_SHC,
    KILN_RELINE_DUE_HOURS,
    LIMESTONE_ANALYSIS,
    NATURAL_GAS_ANALYSIS,
    PLANT_ANNUAL_NOX_BUDGET_KG,
    PLANT_FREE_LIME_MAX_PCT,
    PLANT_MAX_CHLORINE_KG_PER_RUN,
    PLANT_MAX_TSR_PCT,
    PLANT_NOX_INTENSITY_CAP,
    PLANT_PEAK_SEASON_MONTHS,
    PLANT_REGION_CODE,
    RDF_ANALYSIS,
    TDF_ANALYSIS,
)


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Plant
# ---------------------------------------------------------------------------
def plant_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "name": "Ash Grove West",
            "region_code": PLANT_REGION_CODE,
            "permit_nox_kg_per_tonne_clinker_cap": PLANT_NOX_INTENSITY_CAP,
            "permit_annual_nox_budget_kg": PLANT_ANNUAL_NOX_BUDGET_KG,
            "permit_max_tsr_pct": PLANT_MAX_TSR_PCT,
            "permit_max_chlorine_kg_per_run": PLANT_MAX_CHLORINE_KG_PER_RUN,
            "peak_season_months": list(PLANT_PEAK_SEASON_MONTHS),
            "clinker_free_lime_max_pct": PLANT_FREE_LIME_MAX_PCT,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Raw materials
# ---------------------------------------------------------------------------
def limestone_payload(code: str = "LS-1", **overrides: Any) -> Dict[str, Any]:
    return _merge(_merge({"code": code}, LIMESTONE_ANALYSIS), overrides)


def clay_payload(code: str = "CL-1", **overrides: Any) -> Dict[str, Any]:
    return _merge(_merge({"code": code}, CLAY_ANALYSIS), overrides)


def iron_ore_payload(code: str = "IR-1", **overrides: Any) -> Dict[str, Any]:
    return _merge(_merge({"code": code}, IRON_ORE_ANALYSIS), overrides)


def alt_raw_payload(
    code: str = "FA-1", max_substitution_pct: float = 10.00, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "code": code,
            "category": "ALT_RAW",
            "cao_pct": 4.0,
            "sio2_pct": 50.0,
            "al2o3_pct": 25.0,
            "fe2o3_pct": 6.0,
            "so3_pct": 0.50,
            "moisture_pct": 1.0,
            "cost_per_tonne": 5.00,
            "is_alternative": True,
            "max_substitution_pct": max_substitution_pct,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Fuels
# ---------------------------------------------------------------------------
def natural_gas_payload(code: str = "GAS-1", **overrides: Any) -> Dict[str, Any]:
    return _merge(_merge({"code": code}, NATURAL_GAS_ANALYSIS), overrides)


def coal_payload(code: str = "COAL-1", **overrides: Any) -> Dict[str, Any]:
    return _merge(_merge({"code": code}, COAL_ANALYSIS), overrides)


def rdf_payload(code: str = "RDF-1", **overrides: Any) -> Dict[str, Any]:
    return _merge(_merge({"code": code}, RDF_ANALYSIS), overrides)


def tdf_payload(code: str = "TDF-1", **overrides: Any) -> Dict[str, Any]:
    return _merge(_merge({"code": code}, TDF_ANALYSIS), overrides)


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------
def kiln_payload(plant_id: str, code: str = "K1", **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "plant_id": plant_id,
            "code": code,
            "nominal_shc_gj_per_tonne": KILN_NOMINAL_SHC,
            "cooldown_buffer_hours": KILN_COOLDOWN_BUFFER_HOURS,
            "reline_due_hours": KILN_RELINE_DUE_HOURS,
        },
        overrides,
    )


def clinker_silo_payload(
    plant_id: str, code: str = "SC1", **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "plant_id": plant_id,
            "code": code,
            "material_kind": "CLINKER",
            "capacity_tonnes": CLINKER_SILO_CAPACITY,
            "draw_rate_tonnes_per_hour": CLINKER_SILO_DRAW_RATE,
        },
        overrides,
    )


def cement_silo_payload(
    plant_id: str, code: str = "SM1", **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "plant_id": plant_id,
            "code": code,
            "material_kind": "CEMENT",
            "capacity_tonnes": CEMENT_SILO_CAPACITY,
            "draw_rate_tonnes_per_hour": CEMENT_SILO_DRAW_RATE,
            "loadout_spouts": CEMENT_SILO_SPOUTS,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Designs and piles
# ---------------------------------------------------------------------------
def design_payload(
    plant_id: str,
    components: List[Dict[str, Any]],
    code: str = "D2",
    target_lsf: float = 97.00,
    target_sm: float = 2.40,
    target_am: float = 2.45,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "plant_id": plant_id,
            "code": code,
            "target_lsf": target_lsf,
            "target_sm": target_sm,
            "target_am": target_am,
            "components": components,
        },
        overrides,
    )


def component(raw_material_id: str, mass_fraction_pct: float) -> Dict[str, Any]:
    return {"raw_material_id": raw_material_id, "mass_fraction_pct": mass_fraction_pct}


def pile_payload(
    plant_id: str,
    raw_mix_design_id: str,
    expected_raw_mix_design_version: int,
    pile_code: str = "PA",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "plant_id": plant_id,
            "raw_mix_design_id": raw_mix_design_id,
            "pile_code": pile_code,
            "expected_raw_mix_design_version": expected_raw_mix_design_version,
        },
        overrides,
    )


def addition_payload(
    raw_material_id: str, tonnes_as_received: float, moisture_pct: float
) -> Dict[str, Any]:
    return {
        "raw_material_id": raw_material_id,
        "tonnes_as_received": tonnes_as_received,
        "moisture_pct": moisture_pct,
    }


# ---------------------------------------------------------------------------
# Burn tests
# ---------------------------------------------------------------------------
def burn_test_payload(
    plant_id: str,
    fuel_id: str,
    requested_max_tsr_pct: float = 25.00,
    valid_days: int = 30,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "plant_id": plant_id,
            "fuel_id": fuel_id,
            "requested_max_tsr_pct": requested_max_tsr_pct,
            "valid_days": valid_days,
        },
        overrides,
    )


def burn_result_payload(
    measured_chlorine_pct: float = 0.80,
    measured_nox_kg_per_gj: float = 0.22,
    stack_compliant: bool = True,
) -> Dict[str, Any]:
    return {
        "measured_chlorine_pct": measured_chlorine_pct,
        "measured_nox_kg_per_gj": measured_nox_kg_per_gj,
        "stack_compliant": stack_compliant,
    }


def adjudication_payload(
    decision: str = "AUTHORIZED",
    authorized_max_tsr_pct: Optional[float] = 25.00,
    decision_reason: str = "stack test passed",
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision, "decision_reason": decision_reason}
    if authorized_max_tsr_pct is not None:
        payload["authorized_max_tsr_pct"] = authorized_max_tsr_pct
    return payload


# ---------------------------------------------------------------------------
# Kiln runs and outages
# ---------------------------------------------------------------------------
def kiln_run_payload(
    kiln_id: str,
    blended_pile_id: str,
    clinker_silo_id: str,
    window_start: str = "2026-08-01T00:00:00Z",
    window_end: str = "2026-08-01T12:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "kiln_id": kiln_id,
            "blended_pile_id": blended_pile_id,
            "clinker_silo_id": clinker_silo_id,
            "window_start": window_start,
            "window_end": window_end,
        },
        overrides,
    )


def fuel_charge_payload(fuel_id: str, tonnes: float) -> Dict[str, Any]:
    return {"fuel_id": fuel_id, "tonnes": tonnes}


def outage_payload(
    kiln_id: str,
    window_start: str,
    window_end: str,
    scope: str = "MECHANICAL",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "kiln_id": kiln_id,
            "window_start": window_start,
            "window_end": window_end,
            "scope": scope,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Cement batches and laboratory tests
# ---------------------------------------------------------------------------
def cement_batch_payload(
    plant_id: str,
    clinker_silo_id: str,
    cement_silo_id: str,
    expected_clinker_silo_version: int,
    cement_type: str = "TYPE_IL",
    clinker_tonnes_drawn: float = BATCH_CLINKER_DRAWN,
    gypsum_pct: float = BATCH_GYPSUM_PCT,
    limestone_pct: float = BATCH_LIMESTONE_PCT,
    blaine_target_m2_per_kg: int = BATCH_BLAINE_TARGET,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "plant_id": plant_id,
            "clinker_silo_id": clinker_silo_id,
            "cement_silo_id": cement_silo_id,
            "cement_type": cement_type,
            "clinker_tonnes_drawn": clinker_tonnes_drawn,
            "gypsum_pct": gypsum_pct,
            "limestone_pct": limestone_pct,
            "blaine_target_m2_per_kg": blaine_target_m2_per_kg,
            "expected_clinker_silo_version": expected_clinker_silo_version,
        },
        overrides,
    )


def lab_test_payload(
    test_type: str,
    value: float,
    kiln_run_id: Optional[str] = None,
    cement_batch_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"test_type": test_type, "value": value}
    if kiln_run_id is not None:
        payload["kiln_run_id"] = kiln_run_id
    if cement_batch_id is not None:
        payload["cement_batch_id"] = cement_batch_id
    return payload


# ---------------------------------------------------------------------------
# Customers, certificates and loadout orders
# ---------------------------------------------------------------------------
def customer_payload(
    name: str = "Midwest Ready-Mix",
    region_code: str = PLANT_REGION_CODE,
    contract_priority: int = 10,
    contract_monthly_tonnes: float = 4000.00,
    required_cement_type: str = "TYPE_IL",
    max_so3_pct: float = 3.00,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "name": name,
            "region_code": region_code,
            "contract_priority": contract_priority,
            "contract_monthly_tonnes": contract_monthly_tonnes,
            "required_cement_type": required_cement_type,
            "max_so3_pct": max_so3_pct,
        },
        overrides,
    )


def mill_certificate_payload(
    cement_batch_id: str, customer_id: str, certified_tonnes: float, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "cement_batch_id": cement_batch_id,
            "customer_id": customer_id,
            "certified_tonnes": certified_tonnes,
        },
        overrides,
    )


def loadout_order_payload(
    customer_id: str,
    cement_silo_id: str,
    mill_certificate_id: str,
    expected_mill_certificate_version: int,
    window_start: str = "2026-08-05T06:00:00Z",
    window_end: str = "2026-08-05T08:00:00Z",
    tonnes: float = 120.00,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "customer_id": customer_id,
            "cement_silo_id": cement_silo_id,
            "mill_certificate_id": mill_certificate_id,
            "window_start": window_start,
            "window_end": window_end,
            "tonnes": tonnes,
            "expected_mill_certificate_version": expected_mill_certificate_version,
        },
        overrides,
    )
