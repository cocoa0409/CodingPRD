"""Request-payload builders.

Two rules govern every builder here:

* money is an integer count of cents, emitted as a JSON number — never a string
  and never a float;
* every instant is a full ISO 8601 UTC string with exactly three fractional
  digits — never a date-only literal.

Each builder accepts ``**overrides`` so a test can vary exactly the field it is
about without restating the rest.
"""

from typing import Any, Dict, List, Optional

from .types import (
    ChangeOrderOrigin,
    PermitPolicy,
    PermitResponsibleParty,
    SubfloorCondition,
    TradeCode,
    UnitKind,
    UnitOfMeasure,
)


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Service categories
# ---------------------------------------------------------------------------
def service_category_payload(**overrides) -> Dict[str, Any]:
    """A flooring category that needs no in-home visit and never needs a permit."""
    return _merge(
        {
            "code": "FLOOR-DIRECT",
            "name": "Direct-Ship Flooring Install",
            "trade_code": TradeCode.FLOORING,
            "unit_of_measure": UnitOfMeasure.SQFT,
            "base_labor_rate_cents_per_unit": 425,
            "minimum_billable_units": 150.00,
            "measurement_required": False,
            "permit_policy": PermitPolicy.NEVER,
            "deposit_pct": 0.30,
            "status": "ACTIVE",
        },
        overrides,
    )


def measured_category_payload(**overrides) -> Dict[str, Any]:
    """A flooring category that requires an in-home measurement, permit by jurisdiction."""
    return _merge(
        {
            "code": "FLOOR-LVP",
            "name": "LVP Flooring Install",
            "trade_code": TradeCode.FLOORING,
            "unit_of_measure": UnitOfMeasure.SQFT,
            "base_labor_rate_cents_per_unit": 425,
            "minimum_billable_units": 150.00,
            "measurement_required": True,
            "measurement_validity_days": 45,
            "permit_policy": PermitPolicy.BY_JURISDICTION,
            "deposit_pct": 0.30,
            "status": "ACTIVE",
        },
        overrides,
    )


def quick_category_payload(**overrides) -> Dict[str, Any]:
    """No measurement, but permit necessity is settled by the jurisdiction."""
    return _merge(
        {
            "code": "FLOOR-QUICK",
            "name": "Quick-Ship Flooring Install",
            "trade_code": TradeCode.FLOORING,
            "unit_of_measure": UnitOfMeasure.SQFT,
            "base_labor_rate_cents_per_unit": 425,
            "minimum_billable_units": 150.00,
            "measurement_required": False,
            "permit_policy": PermitPolicy.BY_JURISDICTION,
            "deposit_pct": 0.30,
            "status": "ACTIVE",
        },
        overrides,
    )


def measured_never_permit_category_payload(**overrides) -> Dict[str, Any]:
    """Measurement mandatory, permit never needed."""
    return _merge(
        {
            "code": "FLOOR-MEASURED",
            "name": "Measured Flooring Install",
            "trade_code": TradeCode.FLOORING,
            "unit_of_measure": UnitOfMeasure.SQFT,
            "base_labor_rate_cents_per_unit": 425,
            "minimum_billable_units": 150.00,
            "measurement_required": True,
            "permit_policy": PermitPolicy.NEVER,
            "deposit_pct": 0.30,
            "status": "ACTIVE",
        },
        overrides,
    )


def small_fix_category_payload(**overrides) -> Dict[str, Any]:
    """A low-rate category whose minimum billable units and the programme minimum
    labour charge both bite."""
    return _merge(
        {
            "code": "SMALL-FIX",
            "name": "Small Repair Install",
            "trade_code": TradeCode.MILLWORK,
            "unit_of_measure": UnitOfMeasure.EACH,
            "base_labor_rate_cents_per_unit": 50,
            "minimum_billable_units": 100.00,
            "measurement_required": False,
            "permit_policy": PermitPolicy.NEVER,
            "deposit_pct": 0.30,
            "status": "ACTIVE",
        },
        overrides,
    )


def full_deposit_category_payload(**overrides) -> Dict[str, Any]:
    """Deposit is the whole quote, which is how a deposit can exceed an invoice."""
    return _merge(
        {
            "code": "MEAS-FULL",
            "name": "Measured Full-Deposit Install",
            "trade_code": TradeCode.MILLWORK,
            "unit_of_measure": UnitOfMeasure.EACH,
            "base_labor_rate_cents_per_unit": 50,
            "minimum_billable_units": 100.00,
            "measurement_required": True,
            "measurement_validity_days": 45,
            "permit_policy": PermitPolicy.NEVER,
            "deposit_pct": 1.00,
            "status": "ACTIVE",
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Jurisdictions
# ---------------------------------------------------------------------------
def jurisdiction_payload(**overrides) -> Dict[str, Any]:
    """Metro County: flooring needs a permit at or above 250.00 units, retailer pulls
    it, licence required, labour multiplier 1.15."""
    return _merge(
        {
            "code": "METRO-01",
            "name": "Metro County",
            "permit_required_trades": [TradeCode.FLOORING, TradeCode.HVAC,
                                       TradeCode.ROOFING],
            "permit_responsible_party": PermitResponsibleParty.RETAILER,
            "inspection_required": False,
            "min_liability_coverage_cents": 100000000,
            "permit_unit_threshold": 250.00,
            "inspection_lead_days": 3,
            "max_concurrent_inspections": 2,
            "background_check_recency_days": 365,
            "license_required": True,
            "labor_complexity_multiplier": 1.15,
            "status": "ACTIVE",
        },
        overrides,
    )


def plain_jurisdiction_payload(**overrides) -> Dict[str, Any]:
    """Harbor District: no permit trades and a multiplier of exactly 1.00."""
    return _merge(
        {
            "code": "METRO-02",
            "name": "Harbor District",
            "permit_required_trades": [],
            "permit_responsible_party": PermitResponsibleParty.RETAILER,
            "inspection_required": False,
            "min_liability_coverage_cents": 100000000,
            "permit_unit_threshold": 0,
            "inspection_lead_days": 3,
            "max_concurrent_inspections": 2,
            "background_check_recency_days": 365,
            "license_required": True,
            "labor_complexity_multiplier": 1.00,
            "status": "ACTIVE",
        },
        overrides,
    )


def unlicensed_jurisdiction_payload(**overrides) -> Dict[str, Any]:
    """Open Trades County: `license_required` false, so no trade licence is demanded."""
    return _merge(
        plain_jurisdiction_payload(
            code="METRO-03",
            name="Open Trades County",
            license_required=False,
        ),
        overrides,
    )


def licensed_jurisdiction_payload(**overrides) -> Dict[str, Any]:
    """Licensed Trades County: `license_required` true, multiplier 1.00."""
    return _merge(
        plain_jurisdiction_payload(code="METRO-04", name="Licensed Trades County"),
        overrides,
    )


def insured_jurisdiction_payload(**overrides) -> Dict[str, Any]:
    """Insured County: the liability floor is the interesting setting."""
    return _merge(
        plain_jurisdiction_payload(code="METRO-05", name="Insured County"),
        overrides,
    )


def inspected_jurisdiction_payload(**overrides) -> Dict[str, Any]:
    """Inspected County: flooring always needs a permit and an inspection."""
    return _merge(
        {
            "code": "METRO-06",
            "name": "Inspected County",
            "permit_required_trades": [TradeCode.FLOORING],
            "permit_responsible_party": PermitResponsibleParty.RETAILER,
            "inspection_required": True,
            "min_liability_coverage_cents": 100000000,
            "permit_unit_threshold": 0,
            "inspection_lead_days": 3,
            "max_concurrent_inspections": 2,
            "background_check_recency_days": 365,
            "license_required": True,
            "labor_complexity_multiplier": 1.00,
            "status": "ACTIVE",
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Customers, installers, credentials
# ---------------------------------------------------------------------------
def customer_payload(jurisdiction_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "full_name": "Dana Reyes",
            "email": "dana@example.com",
            "jurisdiction_id": jurisdiction_id,
        },
        overrides,
    )


def second_customer_payload(jurisdiction_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "full_name": "Miles Okafor",
            "email": "miles@example.com",
            "jurisdiction_id": jurisdiction_id,
        },
        overrides,
    )


def installer_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "legal_name": "Northside Flooring LLC",
            "contact_email": "ops@northside.example",
            "primary_trade_code": TradeCode.FLOORING,
            "liability_coverage_cents": 200000000,
            "insurance_expires_on": "2027-06-30T00:00:00.000Z",
        },
        overrides,
    )


def second_installer_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "legal_name": "Southbank Interiors LLC",
            "contact_email": "ops@southbank.example",
            "primary_trade_code": TradeCode.FLOORING,
            "liability_coverage_cents": 200000000,
            "insurance_expires_on": "2027-06-30T00:00:00.000Z",
        },
        overrides,
    )


def credential_payload(jurisdiction_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "jurisdiction_id": jurisdiction_id,
            "trade_code": TradeCode.FLOORING,
            "license_number": "FL-99213",
            "license_expires_on": "2027-05-31T00:00:00.000Z",
            "permit_pulling_authorized": True,
        },
        overrides,
    )


def verify_payload(**overrides) -> Dict[str, Any]:
    return _merge({"verification_decision": "VERIFY"}, overrides)


def reject_payload(reason: str = "Licence number is not on the state register",
                   **overrides) -> Dict[str, Any]:
    return _merge(
        {"verification_decision": "REJECT", "rejection_reason": reason}, overrides
    )


def background_check_payload(completed_at: str = "2026-07-15T00:00:00.000Z",
                             result: str = "PASS", **overrides) -> Dict[str, Any]:
    return _merge({"result": result, "completed_at": completed_at}, overrides)


# ---------------------------------------------------------------------------
# Projects and money
# ---------------------------------------------------------------------------
def project_payload(customer_id: str, service_category_id: str, jurisdiction_id: str,
                    estimated_units: float = 420.00, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "customer_id": customer_id,
            "service_category_id": service_category_id,
            "jurisdiction_id": jurisdiction_id,
            "site_address": "18 Larch Way",
            "estimated_units": estimated_units,
            "requested_install_date": "2026-08-25T13:00:00.000Z",
        },
        overrides,
    )


def deposit_payload(amount_cents: int, **overrides) -> Dict[str, Any]:
    """`amount_cents` is an integer count of cents, sent as a JSON number."""
    assert isinstance(amount_cents, int), "money must be an integer count of cents"
    return _merge({"amount_cents": amount_cents}, overrides)


def balance_payload(amount_cents: int, **overrides) -> Dict[str, Any]:
    assert isinstance(amount_cents, int), "money must be an integer count of cents"
    return _merge({"amount_cents": amount_cents}, overrides)


def cancel_payload(reason: str = "Customer is moving out of state",
                   **overrides) -> Dict[str, Any]:
    return _merge({"cancel_reason": reason}, overrides)


def reinstate_payload(expected_project_version: int,
                      note: str = "Move fell through; customer wants the original install",
                      **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "expected_project_version": expected_project_version,
            "reinstate_note": note,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Measurements
# ---------------------------------------------------------------------------
def measurement_payload(scheduled_at: str = "2026-08-05T09:00:00.000Z",
                        technician_name: str = "R. Vance",
                        **overrides) -> Dict[str, Any]:
    return _merge(
        {"scheduled_at": scheduled_at, "technician_name": technician_name}, overrides
    )


def measurement_completion_payload(measured_units: float,
                                   subfloor_condition: str = SubfloorCondition.NONE,
                                   obstruction_count: int = 0,
                                   stair_flight_count: int = 0,
                                   **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "measured_units": measured_units,
            "subfloor_condition": subfloor_condition,
            "obstruction_count": obstruction_count,
            "stair_flight_count": stair_flight_count,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Change orders
# ---------------------------------------------------------------------------
def line(unit_kind: str, units_delta: float) -> Dict[str, Any]:
    return {"unit_kind": unit_kind, "units_delta": units_delta}


def primary_line(units_delta: float) -> Dict[str, Any]:
    return line(UnitKind.PRIMARY_UNITS, units_delta)


def trim_line(units_delta: float) -> Dict[str, Any]:
    return line(UnitKind.TRIM_LINEAR_FT, units_delta)


def fixture_line(units_delta: float) -> Dict[str, Any]:
    return line(UnitKind.FIXTURE_EACH, units_delta)


def change_order_payload(project_id: str, expected_project_version: int,
                         lines: Optional[List[Dict[str, Any]]] = None,
                         origin: str = ChangeOrderOrigin.CUSTOMER_REQUEST,
                         **overrides) -> Dict[str, Any]:
    payload = {
        "project_id": project_id,
        "origin": origin,
        "lines": lines if lines is not None else [primary_line(6.00)],
        "expected_project_version": expected_project_version,
    }
    return _merge(payload, overrides)


def submit_payload(lines: Optional[List[Dict[str, Any]]] = None,
                   **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if lines is not None:
        payload["lines"] = lines
    return _merge(payload, overrides)


def decision_payload(decision: str, **overrides) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


# ---------------------------------------------------------------------------
# Material deliveries
# ---------------------------------------------------------------------------
def delivery_payload(promised_window_start: str = "2026-08-22T08:00:00.000Z",
                     promised_window_end: str = "2026-08-24T08:00:00.000Z",
                     sku_count: int = 6,
                     material_cost_cents: int = 250000,
                     **overrides) -> Dict[str, Any]:
    assert isinstance(material_cost_cents, int), (
        "money must be an integer count of cents"
    )
    return _merge(
        {
            "promised_window_start": promised_window_start,
            "promised_window_end": promised_window_end,
            "sku_count": sku_count,
            "material_cost_cents": material_cost_cents,
        },
        overrides,
    )


def delivery_status_payload(new_status: str,
                            actual_delivered_at: Optional[str] = None,
                            **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"new_status": new_status}
    if actual_delivered_at is not None:
        payload["actual_delivered_at"] = actual_delivered_at
    return _merge(payload, overrides)


# ---------------------------------------------------------------------------
# Assignments
# ---------------------------------------------------------------------------
def assignment_payload(project_id: str, installer_id: str,
                       expected_project_version: int,
                       window_start: str = "2026-08-25T08:00:00.000Z",
                       window_end: str = "2026-08-25T16:00:00.000Z",
                       **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "project_id": project_id,
            "installer_id": installer_id,
            "window_start": window_start,
            "window_end": window_end,
            "expected_project_version": expected_project_version,
        },
        overrides,
    )


def release_payload(reason: str = "Crew reassigned to a storm-damage backlog",
                    **overrides) -> Dict[str, Any]:
    return _merge({"release_reason": reason}, overrides)


def completion_payload(completed_at: str, **overrides) -> Dict[str, Any]:
    return _merge({"completed_at": completed_at}, overrides)


# ---------------------------------------------------------------------------
# Permits and inspections
# ---------------------------------------------------------------------------
def permit_apply_payload(reference: str = "PA-2026-0001", **overrides) -> Dict[str, Any]:
    return _merge({"permit_application_reference": reference}, overrides)


def permit_issue_payload(permit_fee_cents: int = 18500,
                         permit_issued_on: str = "2026-08-01T00:00:00.000Z",
                         **overrides) -> Dict[str, Any]:
    assert isinstance(permit_fee_cents, int), "money must be an integer count of cents"
    return _merge(
        {"permit_fee_cents": permit_fee_cents, "permit_issued_on": permit_issued_on},
        overrides,
    )


def inspection_slot_payload(inspection_slot_start: str, inspection_slot_end: str,
                            **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "inspection_slot_start": inspection_slot_start,
            "inspection_slot_end": inspection_slot_end,
        },
        overrides,
    )


def inspection_result_payload(result: str, **overrides) -> Dict[str, Any]:
    return _merge({"result": result}, overrides)


# ---------------------------------------------------------------------------
# Quality, punch list, warranty, scorecard
# ---------------------------------------------------------------------------
def defect(severity: str, description: str,
           due_at: str = "2026-08-28T00:00:00.000Z") -> Dict[str, Any]:
    return {"severity": severity, "description": description, "due_at": due_at}


def quality_inspection_payload(quality_result: str, workmanship_score: int,
                               defects: Optional[List[Dict[str, Any]]] = None,
                               **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "quality_result": quality_result,
            "workmanship_score": workmanship_score,
            "defects": defects if defects is not None else [],
        },
        overrides,
    )


def resolution_payload(note: str = "Quarter-round replaced and caulked",
                       **overrides) -> Dict[str, Any]:
    return _merge({"resolution_note": note}, overrides)


def escalation_payload(reason: str = "Exposed nail plate under the threshold",
                       **overrides) -> Dict[str, Any]:
    return _merge({"escalation_reason": reason}, overrides)


def warranty_claim_payload(project_id: str, claim_type: str = "LABOR_DEFECT",
                           description: str = "Seam lifted along the hallway run",
                           **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "project_id": project_id,
            "claim_type": claim_type,
            "description": description,
        },
        overrides,
    )


def triage_payload(decision: str, **overrides) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


def scorecard_event_payload(event_type: str, occurred_at: str,
                            **overrides) -> Dict[str, Any]:
    return _merge({"event_type": event_type, "occurred_at": occurred_at}, overrides)


def csat_event_payload(csat_score: int, occurred_at: str,
                       **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "event_type": "CSAT_SURVEY",
            "occurred_at": occurred_at,
            "csat_score": csat_score,
        },
        overrides,
    )


def removal_payload(expected_installer_version: int,
                    reason: str = "Sustained quality failures across the county",
                    **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "removal_reason": reason,
            "expected_installer_version": expected_installer_version,
        },
        overrides,
    )
