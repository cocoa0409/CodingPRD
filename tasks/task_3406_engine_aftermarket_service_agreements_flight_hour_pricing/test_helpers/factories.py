"""Payload factories — one per creatable resource, input fields only (PRD §4).

Defaults are chosen to be valid against the logical clock's initial reading
(2026-09-01T00:00:00Z, PRD §2.4): default periods are "2026-09" and default
dates sit inside an open contract term. Every factory accepts **overrides.
"""


def set_clock_payload(**overrides) -> dict:
    """Payload for POST /api/_clock/set_current_utc (input: to_iso8601)."""
    defaults = {"to_iso8601": "2026-10-01T00:00:00Z"}
    defaults.update(overrides)
    return defaults


def create_operator_payload(**overrides) -> dict:
    """POST /api/operators inputs: name, iata_code, credit_rating (A/B/C)."""
    defaults = {
        "name": "Test Air",
        "iata_code": "TA",
        "credit_rating": "B",
    }
    defaults.update(overrides)
    return defaults


def create_engine_payload(**overrides) -> dict:
    """POST /api/engines inputs: operator_id, esn, engine_model,
    base_severity_tier (BENIGN/MODERATE/HARSH), llp_remaining_cycles."""
    defaults = {
        "operator_id": None,  # caller must supply or override
        "esn": "ESN-T001",
        "engine_model": "CFM56-7B",
        "base_severity_tier": "BENIGN",
        "llp_remaining_cycles": 8000,
    }
    defaults.update(overrides)
    return defaults


def create_flight_hour_report_payload(**overrides) -> dict:
    """POST /api/engines/{id}/flight-hour-reports inputs: period (YYYY-MM,
    not a future month), flight_hours (>= 0), cycles (int >= 0),
    observed_severity (BENIGN/MODERATE/HARSH)."""
    defaults = {
        "period": "2026-09",
        "flight_hours": 100,
        "cycles": 40,
        "observed_severity": "BENIGN",
    }
    defaults.update(overrides)
    return defaults


def create_shop_visit_payload(**overrides) -> dict:
    """POST /api/engines/{id}/shop-visits inputs: planned_induction_date."""
    defaults = {"planned_induction_date": "2026-09-01T00:00:00Z"}
    defaults.update(overrides)
    return defaults


def create_agreement_payload(**overrides) -> dict:
    """POST /api/agreements inputs: contract_ref, base_rate_per_fh_usd (> 0),
    escalation_pct (>= 0), escalation_anchor_date, start_date, end_date,
    allowed_sourcing_classes (non-empty subset of NEW/REPAIRED/USM),
    max_workscope_cost_usd (> 0).

    Default term [2026-09-01, 2027-08-31) contains the initial logical clock,
    so the default agreement can be activated immediately.
    """
    defaults = {
        "contract_ref": "LTSA-T001",
        "base_rate_per_fh_usd": 100.00,
        "escalation_pct": 0.0,
        "escalation_anchor_date": "2026-09-01T00:00:00Z",
        "start_date": "2026-09-01T00:00:00Z",
        "end_date": "2027-08-31T00:00:00Z",
        "allowed_sourcing_classes": ["NEW"],
        "max_workscope_cost_usd": 1000000,
    }
    defaults.update(overrides)
    return defaults


def amend_agreement_payload(expected_agreement_version, **overrides) -> dict:
    """POST /api/agreements/{id}/amend inputs: expected_agreement_version
    (required, OCC) plus any subset of base_rate_per_fh_usd, escalation_pct,
    escalation_anchor_date, end_date, allowed_sourcing_classes,
    max_workscope_cost_usd (pass as overrides)."""
    payload = {"expected_agreement_version": expected_agreement_version}
    payload.update(overrides)
    return payload


def enroll_engine_payload(engine_id, **overrides) -> dict:
    """POST /api/agreements/{id}/enroll inputs: engine_id,
    assumed_annual_hours (> 0), assumed_cycles_per_month (int > 0)."""
    payload = {
        "engine_id": engine_id,
        "assumed_annual_hours": 2400,
        "assumed_cycles_per_month": 100,
    }
    payload.update(overrides)
    return payload


def issue_billing_statement_payload(**overrides) -> dict:
    """POST /api/agreements/{id}/billing-statements inputs: period (YYYY-MM,
    not a future month)."""
    defaults = {"period": "2026-09"}
    defaults.update(overrides)
    return defaults


def workscope_item(**overrides) -> dict:
    """One workscope item: item_code, item_type (MANDATORY_DIRECTIVE /
    LLP_REPLACEMENT / MODULE_OVERHAUL / INSPECTION), estimated_cost_usd,
    restores_cycles (int >= 0), directive_ref (null unless MANDATORY_DIRECTIVE).
    """
    defaults = {
        "item_code": "MO-1",
        "item_type": "MODULE_OVERHAUL",
        "estimated_cost_usd": 100000,
        "restores_cycles": 8000,
        "directive_ref": None,
    }
    defaults.update(overrides)
    return defaults


def create_workscope_payload(expected_shop_visit_version, items=None, **overrides) -> dict:
    """POST /api/shop-visits/{id}/workscopes inputs: expected_shop_visit_version
    (required, OCC) and optional items (defaults to one standard module
    overhaul restoring 8000 cycles so the 18-month life floor passes for an
    engine at 100 assumed cycles/month)."""
    payload = {
        "expected_shop_visit_version": expected_shop_visit_version,
        "items": items if items is not None else [workscope_item()],
    }
    payload.update(overrides)
    return payload


def create_part_requisition_payload(**overrides) -> dict:
    """POST /api/workscopes/{id}/part-requisitions inputs: part_number,
    quantity (int > 0), list_price_usd (> 0), requested_class
    (NEW/REPAIRED/USM), required_by_date."""
    defaults = {
        "part_number": "PN-T1",
        "quantity": 1,
        "list_price_usd": 5000,
        "requested_class": "NEW",
        "required_by_date": "2026-10-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def source_requisition_payload(override=None) -> dict:
    """POST /api/part-requisitions/{id}/source optional input: override
    (ContractManager only). Returns {} when override is None so the field is
    omitted entirely (a plain ShopPlanner sourcing run)."""
    if override is None:
        return {}
    return {"override": bool(override)}


def create_spare_engine_payload(**overrides) -> dict:
    """POST /api/spare-engines inputs: spare_serial (unique), engine_model,
    daily_lease_rate_usd (> 0)."""
    defaults = {
        "spare_serial": "SP-T1",
        "engine_model": "CFM56-7B",
        "daily_lease_rate_usd": 3000,
    }
    defaults.update(overrides)
    return defaults


def create_spare_engine_lease_payload(**overrides) -> dict:
    """POST /api/spare-engine-leases inputs: spare_engine_id, shop_visit_id,
    start_date (inclusive), end_date (exclusive, strictly after start_date)."""
    defaults = {
        "spare_engine_id": None,  # caller must supply or override
        "shop_visit_id": None,  # caller must supply or override
        "start_date": "2026-09-01T00:00:00Z",
        "end_date": "2026-10-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_directive_payload(**overrides) -> dict:
    """POST /api/directives inputs: directive_ref (unique), directive_type
    (AD/SB/ED), applicability_model, mandatory (bool), estimated_cost_usd
    (> 0), and at least one of compliance_cycles (int > 0) / compliance_date.
    """
    defaults = {
        "directive_ref": "AD-2026-0001",
        "directive_type": "AD",
        "applicability_model": "CFM56-7B",
        "mandatory": True,
        "estimated_cost_usd": 100000,
        "compliance_cycles": 50,
    }
    defaults.update(overrides)
    return defaults
