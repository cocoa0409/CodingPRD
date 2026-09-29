"""Request-payload factories.

Each factory emits only the fields the client is permitted to write for that
operation, with defaults that sit inside every declared range so a test only has
to name the one value it cares about. Cent and millilitre fields are always
emitted as JSON numbers.

Pass `_omit=("field", ...)` to drop a key entirely — that is how the missing
required field cases are built — and any keyword override to change a value.
"""

from typing import Any, Dict, Iterable, Optional

from .types import (
    ClinicalAcuity,
    DeferralReason,
    DeferralType,
    Disposition,
    MilkClass,
    PatientType,
    RecallScope,
    SerologyResult,
    TargetMilkClass,
    ZoneCode,
)


def _finish(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    omit: Iterable[str] = overrides.pop("_omit", ())
    payload.update(overrides)
    for key in omit:
        payload.pop(key, None)
    return payload


# ---------------------------------------------------------------------------
# Donor lifecycle
# ---------------------------------------------------------------------------
def donor(
    donor_code: str = "DNR-0001",
    full_name: str = "Ana Ruiz",
    email: str = "ana.ruiz@example.org",
    zone_code: str = ZoneCode.Z2,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {
            "donor_code": donor_code,
            "full_name": full_name,
            "email": email,
            "zone_code": zone_code,
        },
        overrides,
    )


def health_history(
    medication_flag_count: int = 0,
    travel_risk_flag: bool = False,
    tobacco_use: bool = False,
    alcohol_units_per_week: int = 0,
    months_postpartum: int = 6,
    **overrides: Any,
) -> Dict[str, Any]:
    """A questionnaire. The defaults score 0 base risk points."""
    return _finish(
        {
            "medication_flag_count": medication_flag_count,
            "travel_risk_flag": travel_risk_flag,
            "tobacco_use": tobacco_use,
            "alcohol_units_per_week": alcohol_units_per_week,
            "months_postpartum": months_postpartum,
        },
        overrides,
    )


def serology_panel(
    collected_on: str = "2026-07-20",
    hiv_result: str = SerologyResult.NON_REACTIVE,
    htlv_result: str = SerologyResult.NON_REACTIVE,
    hbv_result: str = SerologyResult.NON_REACTIVE,
    hcv_result: str = SerologyResult.NON_REACTIVE,
    syphilis_result: str = SerologyResult.NON_REACTIVE,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {
            "collected_on": collected_on,
            "hiv_result": hiv_result,
            "htlv_result": htlv_result,
            "hbv_result": hbv_result,
            "hcv_result": hcv_result,
            "syphilis_result": syphilis_result,
        },
        overrides,
    )


def physician_approval(
    physician_npi: str = "1234567893",
    approved_on: str = "2026-07-15",
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {"physician_npi": physician_npi, "approved_on": approved_on},
        overrides,
    )


def deferral(
    reason_code: str = DeferralReason.ILLNESS,
    deferral_type: str = DeferralType.TEMPORARY,
    effective_from: str = "2026-08-05",
    deferral_days: int = 30,
    lookback_days: int = 0,
    recall_scope: str = RecallScope.NONE,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {
            "reason_code": reason_code,
            "deferral_type": deferral_type,
            "effective_from": effective_from,
            "deferral_days": deferral_days,
            "lookback_days": lookback_days,
            "recall_scope": recall_scope,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Cold chain
# ---------------------------------------------------------------------------
def shipment(
    donor_id: str,
    tracking_code: str = "TRK-0001",
    container_count: int = 1,
    uses_dry_ice: bool = False,
    declared_volume_ml: int = 800,
    shipped_on: str = "2026-08-02",
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {
            "donor_id": donor_id,
            "tracking_code": tracking_code,
            "container_count": container_count,
            "uses_dry_ice": uses_dry_ice,
            "declared_volume_ml": declared_volume_ml,
            "shipped_on": shipped_on,
        },
        overrides,
    )


def receipt(
    excursion_minutes: int = 0,
    arrival_max_temp_celsius: float = -18.0,
    verified_volume_ml: int = 800,
    **overrides: Any,
) -> Dict[str, Any]:
    """Logger figures for a cooler that arrives cleanly inside both thresholds."""
    return _finish(
        {
            "excursion_minutes": excursion_minutes,
            "arrival_max_temp_celsius": arrival_max_temp_celsius,
            "verified_volume_ml": verified_volume_ml,
        },
        overrides,
    )


def disposition(disposition_value: str = Disposition.ACCEPT, **overrides: Any) -> Dict[str, Any]:
    return _finish({"disposition": disposition_value}, overrides)


def donation(
    expected_shipment_version: int,
    container_label: str = "A1",
    expressed_on: str = "2026-07-05",
    volume_ml: int = 800,
    kcal_per_oz: float = 20.0,
    milk_class: str = MilkClass.TERM,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {
            "container_label": container_label,
            "expressed_on": expressed_on,
            "volume_ml": volume_ml,
            "kcal_per_oz": kcal_per_oz,
            "milk_class": milk_class,
            "expected_shipment_version": expected_shipment_version,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Pooling
# ---------------------------------------------------------------------------
def pool(
    pool_code: str = "POOL-0001",
    target_milk_class: str = TargetMilkClass.TERM,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {"pool_code": pool_code, "target_milk_class": target_milk_class},
        overrides,
    )


def pool_component(
    donation_id: str,
    allocated_volume_ml: int,
    expected_pool_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {
            "donation_id": donation_id,
            "allocated_volume_ml": allocated_volume_ml,
            "expected_pool_version": expected_pool_version,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Pasteurization
# ---------------------------------------------------------------------------
def pasteurization_run(
    pool_id: str,
    pasteurizer_id: str = "PAST-01",
    scheduled_start_at: str = "2026-08-10T09:00:00Z",
    cycle_minutes: int = 60,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {
            "pool_id": pool_id,
            "pasteurizer_id": pasteurizer_id,
            "scheduled_start_at": scheduled_start_at,
            "cycle_minutes": cycle_minutes,
        },
        overrides,
    )


def temperature_reading(
    offset_seconds: int, celsius: float, **overrides: Any
) -> Dict[str, Any]:
    return _finish({"offset_seconds": offset_seconds, "celsius": celsius}, overrides)


def culture(
    culture_cfu_per_ml: int = 0, culture_organism: str = "NONE", **overrides: Any
) -> Dict[str, Any]:
    return _finish(
        {"culture_cfu_per_ml": culture_cfu_per_ml, "culture_organism": culture_organism},
        overrides,
    )


def milk_lot(bottle_count: int = 21, bottle_volume_ml: int = 100, **overrides: Any) -> Dict[str, Any]:
    return _finish(
        {"bottle_count": bottle_count, "bottle_volume_ml": bottle_volume_ml},
        overrides,
    )


# ---------------------------------------------------------------------------
# Demand and money
# ---------------------------------------------------------------------------
def subsidy_program(
    program_code: str = "SUB-0001",
    name: str = "Neonatal Charitable Fund",
    coverage_pct: float = 0.60,
    annual_cap_cents: int = 100000,
    **overrides: Any,
) -> Dict[str, Any]:
    return _finish(
        {
            "program_code": program_code,
            "name": name,
            "coverage_pct": coverage_pct,
            "annual_cap_cents": annual_cap_cents,
        },
        overrides,
    )


def prescription(
    prescription_code: str = "RX-0001",
    patient_reference: str = "PT-001",
    patient_type: str = PatientType.NICU_INPATIENT,
    clinical_acuity: str = ClinicalAcuity.CRITICAL,
    prescribed_ml: int = 500,
    needed_by_date: str = "2026-09-30",
    subsidy_program_id: Optional[str] = None,
    requires_preterm_milk: Optional[bool] = None,
    subsidy_required: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """An order. The two optional flags and the program link are omitted unless
    given, so the declared defaults can be observed."""
    payload: Dict[str, Any] = {
        "prescription_code": prescription_code,
        "patient_reference": patient_reference,
        "patient_type": patient_type,
        "clinical_acuity": clinical_acuity,
        "prescribed_ml": prescribed_ml,
        "needed_by_date": needed_by_date,
    }
    if subsidy_program_id is not None:
        payload["subsidy_program_id"] = subsidy_program_id
    if requires_preterm_milk is not None:
        payload["requires_preterm_milk"] = requires_preterm_milk
    if subsidy_required is not None:
        payload["subsidy_required"] = subsidy_required
    return _finish(payload, overrides)


def dispense(
    lot_id: str, volume_ml: int, expected_lot_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _finish(
        {
            "lot_id": lot_id,
            "volume_ml": volume_ml,
            "expected_lot_version": expected_lot_version,
        },
        overrides,
    )
