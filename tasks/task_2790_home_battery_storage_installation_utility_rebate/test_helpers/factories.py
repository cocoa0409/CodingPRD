"""
Payload builders.

Each function returns a plain dict that satisfies the mandatory field set of one
create or transition endpoint, with every optional field either omitted or set to a
value that keeps the record on the happy path. Tests pass keyword overrides to move
exactly the one field under examination and leave the rest alone, which keeps the
intent of a test visible in its call site.

Numeric discipline: cents fields are Python ints, kilowatt and kilowatt-hour fields
are floats, and basis-point fields are ints. Nothing here ever sends a number as a
JSON string — a quoted amount turns a business-rule assertion into an unrelated
validation error and hides whatever the test was really about.
"""

from typing import Any, Dict, List

from .types import (
    AlertCode,
    AlertSeverity,
    ApplicationDecision,
    BackupScope,
    CertificationLevel,
    ClaimDecision,
    EventType,
    ExportMode,
    InspectionResult,
    InverterModel,
    JurisdictionCode,
    LoadCalcDecision,
    LoadMethod,
    ModelCode,
    PermitDecision,
    ProgramType,
    Season,
    TerritoryCode,
    TestType,
)

Json = Dict[str, Any]


def _merge(base: Json, overrides: Json) -> Json:
    """Apply overrides, and drop any key whose override is the sentinel `_OMIT`."""
    merged = dict(base)
    merged.update(overrides)
    return {k: v for k, v in merged.items() if v is not OMIT}


class _Omit:
    """Sentinel: `factory(field=OMIT)` removes the field from the payload entirely."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "OMIT"


OMIT = _Omit()


# ── Installer accounts ───────────────────────────────
def installer_payload(**overrides: Any) -> Json:
    """A manufacturer-certified installation company covering three model codes."""
    return _merge(
        {
            "company_name": "Volt Home Energy",
            "certification_level": CertificationLevel.ADVANCED,
            "certified_model_codes": [ModelCode.PWX_A, ModelCode.PWX_B, ModelCode.PWX_C],
            "certification_expires_on": "2027-06-30T00:00:00.000Z",
        },
        overrides,
    )


def certification_amendment_payload(**overrides: Any) -> Json:
    """An amendment that only renews the expiry date, unless told otherwise."""
    return _merge({"certification_expires_on": "2028-06-30T00:00:00.000Z"}, overrides)


# ── Sites ────────────────────────────────────────────
def site_payload(**overrides: Any) -> Json:
    """A 2400 square-foot premises on a 200 amp panel in the western territory."""
    return _merge(
        {
            "homeowner_name": "R. Ito",
            "utility_territory_code": TerritoryCode.TER_WEST,
            "service_panel_amps": 200,
            "floor_area_sqft": 2400,
            "postal_code": "94110",
            "existing_pv_kw_dc": 6.0,
        },
        overrides,
    )


# ── Load calculations ────────────────────────────────
def essential_circuits(**_: Any) -> List[Json]:
    """The four-circuit essential list used by the essential-loads scope."""
    return [
        {"label": "KITCHEN", "load_kw": 3.5, "has_motor": False},
        {"label": "WELL_PUMP", "load_kw": 2.5, "has_motor": True},
        {"label": "LIGHTS", "load_kw": 1.2, "has_motor": False},
        {"label": "FRIDGE", "load_kw": 0.8, "has_motor": False},
    ]


def load_calculation_payload(site_id: str, **overrides: Any) -> Json:
    """A standard-method calculation with an essential-loads backup scope."""
    return _merge(
        {
            "site_id": site_id,
            "method": LoadMethod.STANDARD,
            "backup_scope": BackupScope.ESSENTIAL_LOADS,
            "lighting_area_sqft": 2400,
            "appliance_load_va": 18000,
            "heating_va": 9600,
            "cooling_va": 7200,
            "essential_circuits": essential_circuits(),
        },
        overrides,
    )


def whole_home_load_calculation_payload(site_id: str, **overrides: Any) -> Json:
    """A standard-method calculation backing the whole home.

    Whole-home scoping requires an empty essential-circuit list, so the list is
    cleared rather than inherited from the essential-loads default.
    """
    base = dict(backup_scope=BackupScope.WHOLE_HOME, essential_circuits=[])
    base.update(overrides)
    return load_calculation_payload(site_id, **base)


def measured_load_calculation_payload(
    site_id: str, measured_peak_kw: float = 14.0, **overrides: Any
) -> Json:
    """A measured-method calculation, which sizes from the metered peak.

    The measured method requires `measured_peak_kw` and ignores every nameplate
    volt-ampere input.
    """
    base = dict(
        method=LoadMethod.MEASURED,
        backup_scope=BackupScope.WHOLE_HOME,
        essential_circuits=[],
        measured_peak_kw=measured_peak_kw,
    )
    base.update(overrides)
    return load_calculation_payload(site_id, **base)


def load_calc_approval_payload(**overrides: Any) -> Json:
    return _merge(
        {"decision": LoadCalcDecision.APPROVE, "reviewer_notes": "Sizing verified."},
        overrides,
    )


def load_calc_revision_payload(**overrides: Any) -> Json:
    return _merge(
        {
            "decision": LoadCalcDecision.REQUEST_REVISION,
            "reviewer_notes": "Recheck the heating figure.",
        },
        overrides,
    )


# ── Battery systems ──────────────────────────────────
def battery_system_payload(
    site_id: str, installer_id: str, load_calculation_id: str, **overrides: Any
) -> Json:
    """A two-unit PWX_A bank on a GW2_HOME inverter, costing 32000 dollars."""
    return _merge(
        {
            "site_id": site_id,
            "installer_id": installer_id,
            "load_calculation_id": load_calculation_id,
            "model_code": ModelCode.PWX_A,
            "unit_count": 2,
            "inverter_model": InverterModel.GW2_HOME,
            "firmware_version": "24.6.0",
            "installed_cost_cents": 3200000,
        },
        overrides,
    )


def warranty_registration_payload(unit_count: int = 2, **overrides: Any) -> Json:
    """A ten-year term with one serial per unit, as the count rule requires."""
    return _merge(
        {
            "coverage_years": 10,
            "serial_numbers": [
                "SN-PWX-{:04d}".format(n + 1) for n in range(unit_count)
            ],
        },
        overrides,
    )


def expansion_payload(expected_battery_system_version: int, **overrides: Any) -> Json:
    """Add one unit to a commissioned bank, guarded on the base bank's version.

    `installed_cost_cents` here is the incremental cost of the added units, not the
    new total.
    """
    return _merge(
        {
            "additional_unit_count": 1,
            "inverter_model": InverterModel.GW2_HOME,
            "firmware_version": "24.6.0",
            "installed_cost_cents": 1200000,
            "expected_battery_system_version": expected_battery_system_version,
        },
        overrides,
    )


# ── Permits ──────────────────────────────────────────
def permit_payload(battery_system_id: str, **overrides: Any) -> Json:
    return _merge(
        {
            "battery_system_id": battery_system_id,
            "jurisdiction_code": JurisdictionCode.AHJ_CITY,
            "plan_set_ref": "PS-2790-A",
        },
        overrides,
    )


def permit_resubmission_payload(**overrides: Any) -> Json:
    """A resubmission from corrections, carrying the updated plan set reference."""
    return _merge({"plan_set_ref": "PS-2790-B"}, overrides)


def permit_issue_payload(expires_on: str = "2027-06-30T00:00:00.000Z", **overrides: Any) -> Json:
    return _merge({"decision": PermitDecision.ISSUE, "expires_on": expires_on}, overrides)


def permit_corrections_payload(**overrides: Any) -> Json:
    return _merge(
        {
            "decision": PermitDecision.REQUEST_CORRECTIONS,
            "inspection_findings": "Single-line diagram missing.",
        },
        overrides,
    )


def inspection_pass_payload(**overrides: Any) -> Json:
    return _merge(
        {"result": InspectionResult.PASS, "inspection_findings": "No deficiencies."},
        overrides,
    )


def inspection_fail_payload(**overrides: Any) -> Json:
    return _merge(
        {
            "result": InspectionResult.FAIL,
            "inspection_findings": "Disconnect labelling absent.",
        },
        overrides,
    )


# ── Interconnection applications ─────────────────────
def application_payload(battery_system_id: str, **overrides: Any) -> Json:
    return _merge(
        {
            "battery_system_id": battery_system_id,
            "export_mode": ExportMode.LIMITED_EXPORT,
            "requested_export_kw": 8.0,
        },
        overrides,
    )


def application_approval_payload(approved_export_kw: float = 8.0, **overrides: Any) -> Json:
    return _merge(
        {
            "decision": ApplicationDecision.APPROVE_TO_INSTALL,
            "approved_export_kw": approved_export_kw,
        },
        overrides,
    )


def application_supplemental_payload(**overrides: Any) -> Json:
    return _merge({"decision": ApplicationDecision.REQUEST_SUPPLEMENTAL}, overrides)


def application_denial_payload(**overrides: Any) -> Json:
    return _merge({"decision": ApplicationDecision.DENY}, overrides)


# ── Incentive programs ───────────────────────────────
def state_program_payload(**overrides: Any) -> Json:
    """The wide-ceiling state capacity program: 50000 dollars, two tiers, priority 1."""
    return _merge(
        {
            "name": "State Storage Capacity Incentive",
            "program_type": ProgramType.STATE_CAPACITY,
            "total_budget_cents": 5000000,
            "tier1_limit_kwh": 20,
            "tier1_rate_cents_per_kwh": 20000,
            "tier2_rate_cents_per_kwh": 10000,
            "per_project_cap_cents": 1500000,
            "stack_priority": 1,
            "max_stack_pct_of_cost_bp": 5000,
            "requires_export_commitment": False,
            "min_capacity_commitment_kw": 5.0,
        },
        overrides,
    )


def utility_program_payload(**overrides: Any) -> Json:
    """A second, lower-priority program for the stacking-waterfall scenarios."""
    return _merge(
        {
            "name": "Utility Upfront Storage Rebate",
            "program_type": ProgramType.UTILITY_UPFRONT,
            "total_budget_cents": 4000000,
            "tier1_limit_kwh": 10,
            "tier1_rate_cents_per_kwh": 8000,
            "tier2_rate_cents_per_kwh": 4000,
            "per_project_cap_cents": 1000000,
            "stack_priority": 2,
            "max_stack_pct_of_cost_bp": 4000,
            "requires_export_commitment": True,
            "min_capacity_commitment_kw": 4.0,
        },
        overrides,
    )


def federal_program_payload(**overrides: Any) -> Json:
    """A third program, for filter and priority-ordering scenarios."""
    return _merge(
        {
            "name": "Federal Storage Adder",
            "program_type": ProgramType.FEDERAL_ADDER,
            "total_budget_cents": 9000000,
            "tier1_limit_kwh": 30,
            "tier1_rate_cents_per_kwh": 5000,
            "tier2_rate_cents_per_kwh": 2500,
            "per_project_cap_cents": 2000000,
            "stack_priority": 3,
            "max_stack_pct_of_cost_bp": 6000,
            "requires_export_commitment": False,
            "min_capacity_commitment_kw": 1.0,
        },
        overrides,
    )


# ── Rebate claims ────────────────────────────────────
def claim_payload(
    battery_system_id: str,
    program_id: str,
    expected_battery_system_version: int,
    **overrides: Any
) -> Json:
    return _merge(
        {
            "battery_system_id": battery_system_id,
            "program_id": program_id,
            "capacity_commitment_kw": 8.0,
            "export_commitment": ExportMode.LIMITED_EXPORT,
            "expected_battery_system_version": expected_battery_system_version,
        },
        overrides,
    )


def claim_approval_payload(**overrides: Any) -> Json:
    return _merge({"decision": ClaimDecision.APPROVE}, overrides)


def claim_denial_payload(**overrides: Any) -> Json:
    return _merge({"decision": ClaimDecision.DENY}, overrides)


def void_payload(**overrides: Any) -> Json:
    return _merge({"reason": "Household cancelled the project."}, overrides)


def clawback_payload(**overrides: Any) -> Json:
    return _merge({"clawback_reason": "Capacity test evidence withdrawn."}, overrides)


# ── Commissioning tests ──────────────────────────────
def commissioning_test_payload(
    battery_system_id: str,
    test_type: str,
    window_start: str,
    window_end: str,
    **overrides: Any
) -> Json:
    """One booking in a half-open window: start inclusive, end exclusive."""
    return _merge(
        {
            "battery_system_id": battery_system_id,
            "test_type": test_type,
            "window_start": window_start,
            "window_end": window_end,
        },
        overrides,
    )


# The four bookings that clear the commissioning gate, an hour apart so that the
# thirty-minute travel buffer between consecutive windows is comfortably satisfied.
FOUR_TEST_WINDOWS = [
    (TestType.BACKUP_TRANSITION, "2026-08-10T09:00:00Z", "2026-08-10T10:00:00Z"),
    (TestType.CAPACITY_DISCHARGE, "2026-08-10T11:00:00Z", "2026-08-10T12:00:00Z"),
    (TestType.ANTI_ISLANDING, "2026-08-10T13:00:00Z", "2026-08-10T14:00:00Z"),
    (TestType.FIRMWARE_BASELINE, "2026-08-10T15:00:00Z", "2026-08-10T16:00:00Z"),
]


def backup_transition_result_payload(transition_ms: int = 150, **overrides: Any) -> Json:
    """A transition inside the 200 millisecond ceiling, so the verdict is a pass."""
    return _merge({"transition_ms": transition_ms}, overrides)


def capacity_discharge_result_payload(delivered_kwh: float = 25.65, **overrides: Any) -> Json:
    """25.65 kWh against a 27.00 kWh design bank: exactly 95 percent, a pass."""
    return _merge({"delivered_kwh": delivered_kwh}, overrides)


def anti_islanding_result_payload(anti_islanding_trip_ms: int = 1200, **overrides: Any) -> Json:
    """A trip inside the 2000 millisecond ceiling, so the verdict is a pass."""
    return _merge({"anti_islanding_trip_ms": anti_islanding_trip_ms}, overrides)


def firmware_baseline_result_payload(
    reported_firmware_version: str = "24.6.0", **overrides: Any
) -> Json:
    """Firmware no older than the PWX_A catalog minimum of 24.4.0, so a pass."""
    return _merge({"reported_firmware_version": reported_firmware_version}, overrides)


def result_payload_for(test_type: str, **overrides: Any) -> Json:
    """The measured figure that belongs to the given test type."""
    builders = {
        TestType.BACKUP_TRANSITION: backup_transition_result_payload,
        TestType.CAPACITY_DISCHARGE: capacity_discharge_result_payload,
        TestType.ANTI_ISLANDING: anti_islanding_result_payload,
        TestType.FIRMWARE_BASELINE: firmware_baseline_result_payload,
    }
    return builders[test_type](**overrides)


# ── Monitoring alerts ────────────────────────────────
def alert_payload(battery_system_id: str, **overrides: Any) -> Json:
    return _merge(
        {
            "battery_system_id": battery_system_id,
            "alert_code": AlertCode.CELL_IMBALANCE,
            "severity": AlertSeverity.WARNING,
            "reported_firmware_version": "24.6.0",
        },
        overrides,
    )


def file_claim_payload(**overrides: Any) -> Json:
    return _merge(
        {
            "claimed_component": "BATTERY_MODULE_2",
            "resolution_notes": "Cell imbalance persists after balancing cycle.",
        },
        overrides,
    )


def warranty_claim_approval_payload(**overrides: Any) -> Json:
    return _merge(
        {"decision": "APPROVE", "resolution_notes": "Module replacement authorized."},
        overrides,
    )


def warranty_claim_denial_payload(**overrides: Any) -> Json:
    return _merge({"decision": "DENY", "resolution_notes": "Outside coverage."}, overrides)


def warranty_claim_info_request_payload(**overrides: Any) -> Json:
    return _merge(
        {"decision": "REQUEST_INFO", "resolution_notes": "Send the cell voltage log."},
        overrides,
    )


# ── BYOD enrollments ─────────────────────────────────
def enrollment_payload(battery_system_id: str, **overrides: Any) -> Json:
    """A 5 kW pledge with a 20 percent reserve floor for the summer season."""
    return _merge(
        {
            "battery_system_id": battery_system_id,
            "pledged_kw": 5.0,
            "reserve_soc_pct": 20,
            "season": Season.SUMMER_2026,
        },
        overrides,
    )


def withdrawal_payload(**overrides: Any) -> Json:
    return _merge({"reason": "Household leaving the program."}, overrides)


# ── Dispatch events, participations and delivery ─────
def dispatch_event_payload(**overrides: Any) -> Json:
    """A two-hour economic event in the western territory calling for 500 kW."""
    return _merge(
        {
            "territory_code": TerritoryCode.TER_WEST,
            "window_start": "2026-09-15T17:00:00Z",
            "window_end": "2026-09-15T19:00:00Z",
            "event_type": EventType.ECONOMIC,
            "target_kw": 500,
            "payment_rate_cents_per_kw": 850,
        },
        overrides,
    )


def participation_payload(
    byod_enrollment_id: str, expected_dispatch_event_version: int, **overrides: Any
) -> Json:
    return _merge(
        {
            "byod_enrollment_id": byod_enrollment_id,
            "expected_dispatch_event_version": expected_dispatch_event_version,
        },
        overrides,
    )


def delivery_payload(delivered_kwh: float, **overrides: Any) -> Json:
    return _merge({"delivered_kwh": delivered_kwh}, overrides)
