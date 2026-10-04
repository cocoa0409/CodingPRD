"""Payload factories — one per creatable entity plus action/patch bodies.

Only ``source: input`` fields are emitted. Optional fields are OMITTED (not
sent as null) unless the caller supplies them, so the server applies its own
defaults (PRD: optional fields "each defaulting to null when omitted" §3.1).

Field names follow the PRD exactly. OCC-guarded action payloads
(``resolve_renegotiation_payload``, ``close_commitment_period_payload``)
carry the mandatory ``expected_agreement_version`` (PRD §2.8).
"""
import itertools
import uuid

from .constants import CLOCK_START_ISO, TEST_DEFAULTS

__all__ = [
    "unique_serial", "reagent_line", "sku_override",
    "create_clinic_payload", "create_group_pricing_agreement_payload",
    "create_placement_agreement_payload", "create_purchase_agreement_payload",
    "create_lease_agreement_payload", "create_reagent_commitment_agreement_payload",
    "create_analyzer_payload", "create_reagent_order_payload",
    "create_lab_test_order_payload", "create_proficiency_order_payload",
    "create_patient_order_payload", "create_send_out_order_payload",
    "create_service_case_payload",
    "clock_set_payload", "patch_clinic_payload", "patch_analyzer_payload",
    "patch_reagent_order_payload", "patch_service_case_payload",
    "patch_lab_test_order_payload", "resolve_renegotiation_payload",
    "close_commitment_period_payload", "record_payment_payload",
]

_serial_counter = itertools.count(1)


def unique_serial(prefix: str = "SN") -> str:
    """Unique serial_number per call (serial_number must be unique across all
    analyzers, PRD §3.7)."""
    return f"{prefix}-{next(_serial_counter)}-{uuid.uuid4().hex[:8]}"


def reagent_line(sku: str, quantity: int) -> dict:
    """One order line {sku, quantity} (quantity a strictly positive integer)."""
    return {"sku": sku, "quantity": quantity}


def sku_override(sku: str, unit_price_cents: int) -> dict:
    """One GPA sku_overrides entry {sku, unit_price_cents}."""
    return {"sku": sku, "unit_price_cents": unit_price_cents}


# ---------------------------------------------------------------------------
# Resource-creation payloads (POST ... -> 201)
# ---------------------------------------------------------------------------
def create_clinic_payload(**overrides) -> dict:
    """POST /api/clinics body. Optional group codes omitted unless given."""
    defaults = {
        "name": TEST_DEFAULTS["CLINIC_NAME"],
        "caseload_baseline_tests": TEST_DEFAULTS["BASELINE_CASELOAD"],
    }
    defaults.update(overrides)
    # Optional membership codes are omitted unless the caller supplies them,
    # so the server applies its own null default (PRD §3.1). An explicit
    # None passed by the caller is sent through as JSON null.
    for optional in ("corporate_group_code", "buying_group_code"):
        if optional not in overrides:
            defaults.pop(optional, None)
    return defaults


def create_group_pricing_agreement_payload(**overrides) -> dict:
    """POST /api/group-pricing-agreements body.

    Window defaults: opens at the logical-clock startup instant (born ACTIVE)
    and closes one year later. sku_overrides defaults to omitted (server
    defaults to []).
    """
    defaults = {
        "group_type": "CORPORATE",
        "group_code": "CORP-1",
        "effective_from": CLOCK_START_ISO,
        "effective_to": TEST_DEFAULTS["GPA_EFFECTIVE_TO"],
        "discount_pct": 0.10,
    }
    defaults.update(overrides)
    if defaults.get("sku_overrides") is None:
        defaults.pop("sku_overrides", None)
    return defaults


def create_reagent_commitment_agreement_payload(clinic_id: str, **overrides) -> dict:
    """POST /api/placement-agreements body for a REAGENT_COMMITMENT draft."""
    defaults = {
        "clinic_id": clinic_id,
        "model": TEST_DEFAULTS["MODEL_RC"],
        "program_type": "REAGENT_COMMITMENT",
        "term_months": TEST_DEFAULTS["TERM_MONTHS"],
        "start_date": TEST_DEFAULTS["START_DATE"],
        "monthly_minimum_cents": TEST_DEFAULTS["MONTHLY_MINIMUM_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_purchase_agreement_payload(clinic_id: str, **overrides) -> dict:
    """POST /api/placement-agreements body for a PURCHASE draft."""
    defaults = {
        "clinic_id": clinic_id,
        "model": TEST_DEFAULTS["MODEL_PURCHASE"],
        "program_type": "PURCHASE",
        "term_months": TEST_DEFAULTS["TERM_MONTHS"],
        "start_date": TEST_DEFAULTS["START_DATE"],
        "purchase_price_cents": TEST_DEFAULTS["PURCHASE_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_lease_agreement_payload(clinic_id: str, **overrides) -> dict:
    """POST /api/placement-agreements body for a LEASE draft."""
    defaults = {
        "clinic_id": clinic_id,
        "model": "VETURINE_200",
        "program_type": "LEASE",
        "term_months": TEST_DEFAULTS["TERM_MONTHS"],
        "start_date": TEST_DEFAULTS["START_DATE"],
        "lease_rate_cents": TEST_DEFAULTS["LEASE_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_placement_agreement_payload(clinic_id: str, **overrides) -> dict:
    """Generic placement-agreement draft (defaults to REAGENT_COMMITMENT).

    For other program types prefer the dedicated factories above so the
    program-conditional field (PRD §3.3) is always the matching one.
    """
    return create_reagent_commitment_agreement_payload(clinic_id, **overrides)


def create_analyzer_payload(clinic_id: str, agreement_id: str, **overrides) -> dict:
    """POST /api/analyzers body. serial_number auto-generated when omitted;
    is_loaner_unit omitted unless truthy (server default false)."""
    defaults = {
        "clinic_id": clinic_id,
        "agreement_id": agreement_id,
        "serial_number": unique_serial(),
    }
    defaults.update(overrides)
    if not defaults.get("is_loaner_unit"):
        defaults.pop("is_loaner_unit", None)
    return defaults


def create_reagent_order_payload(clinic_id: str, agreement_id: str, **overrides) -> dict:
    """POST /api/reagent-orders body. Default: 100 VC300_CHEM_SLIDE for the
    agreement's first month (2026-09)."""
    defaults = {
        "clinic_id": clinic_id,
        "agreement_id": agreement_id,
        "order_month": "2026-09",
        "lines": [reagent_line("VC300_CHEM_SLIDE", 100)],
    }
    defaults.update(overrides)
    return defaults


def create_lab_test_order_payload(clinic_id: str, **overrides) -> dict:
    """POST /api/lab-test-orders body (generic). Prefer the branch-specific
    factories below; conditional fields: analyzer_id iff IN_CLINIC,
    expected_result iff PROFICIENCY (PRD §3.8)."""
    defaults = {
        "clinic_id": clinic_id,
        "origin": "SEND_OUT",
        "order_kind": "PATIENT",
        "test_code": TEST_DEFAULTS["TEST_CODE_SEND_OUT"],
    }
    defaults.update(overrides)
    for optional in ("analyzer_id", "expected_result"):
        if defaults.get(optional) is None:
            defaults.pop(optional, None)
    return defaults


def create_patient_order_payload(clinic_id: str, analyzer_id: str, **overrides) -> dict:
    """IN_CLINIC PATIENT order on a specific analyzer."""
    defaults = {
        "clinic_id": clinic_id,
        "origin": "IN_CLINIC",
        "order_kind": "PATIENT",
        "test_code": TEST_DEFAULTS["TEST_CODE_PATIENT"],
        "analyzer_id": analyzer_id,
    }
    defaults.update(overrides)
    return defaults


def create_proficiency_order_payload(clinic_id: str, analyzer_id: str, **overrides) -> dict:
    """IN_CLINIC PROFICIENCY order (expected_result required, PRD §3.8)."""
    defaults = {
        "clinic_id": clinic_id,
        "origin": "IN_CLINIC",
        "order_kind": "PROFICIENCY",
        "test_code": TEST_DEFAULTS["TEST_CODE_PROFICIENCY"],
        "analyzer_id": analyzer_id,
        "expected_result": TEST_DEFAULTS["EXPECTED_RESULT"],
    }
    defaults.update(overrides)
    return defaults


def create_send_out_order_payload(clinic_id: str, **overrides) -> dict:
    """SEND_OUT PATIENT order (analyzer_id must be null — omitted here)."""
    defaults = {
        "clinic_id": clinic_id,
        "origin": "SEND_OUT",
        "order_kind": "PATIENT",
        "test_code": TEST_DEFAULTS["TEST_CODE_SEND_OUT"],
    }
    defaults.update(overrides)
    if defaults.get("analyzer_id") is None:
        defaults.pop("analyzer_id", None)
    return defaults


def create_service_case_payload(analyzer_id: str, **overrides) -> dict:
    """POST /api/service-cases body (REPAIR default; PROFICIENCY_REMEDIATION
    is system-created only and must never be sent through the API, PRD §3.7)."""
    defaults = {
        "analyzer_id": analyzer_id,
        "case_type": "REPAIR",
    }
    defaults.update(overrides)
    if defaults.get("loaner_analyzer_id") is None:
        defaults.pop("loaner_analyzer_id", None)
    return defaults


# ---------------------------------------------------------------------------
# Action / patch payloads (POST|PATCH ... -> 200)
# ---------------------------------------------------------------------------
def clock_set_payload(to_iso8601: str) -> dict:
    """POST /api/_clock/set_current_utc body (strictly forward, PRD §2.4)."""
    return {"to_iso8601": to_iso8601}


def patch_clinic_payload(caseload_current_tests=None, status=None) -> dict:
    """PATCH /api/clinics/{id} body; status is PlatformAdmin-only (PRD §2.1)."""
    payload = {}
    if caseload_current_tests is not None:
        payload["caseload_current_tests"] = caseload_current_tests
    if status is not None:
        payload["status"] = status
    return payload


def patch_analyzer_payload(operational_status=None, connectivity_status=None) -> dict:
    """PATCH /api/analyzers/{id} body; both dimensions may ride one call."""
    payload = {}
    if operational_status is not None:
        payload["operational_status"] = operational_status
    if connectivity_status is not None:
        payload["connectivity_status"] = connectivity_status
    return payload


def patch_reagent_order_payload(status: str) -> dict:
    """PATCH /api/reagent-orders/{id} body: status FULFILLED | CANCELLED."""
    return {"status": status}


def patch_service_case_payload(action: str, resolution_note=None) -> dict:
    """PATCH /api/service-cases/{id} body: action DISPATCH | RESOLVE | CANCEL."""
    payload = {"action": action}
    if resolution_note is not None:
        payload["resolution_note"] = resolution_note
    return payload


def patch_lab_test_order_payload(action: str, result_value=None) -> dict:
    """PATCH /api/lab-test-orders/{id} body: action RECEIVE | RECORD_RESULT |
    DELIVER | CANCEL; result_value required for RECORD_RESULT."""
    payload = {"action": action}
    if result_value is not None:
        payload["result_value"] = result_value
    return payload


def resolve_renegotiation_payload(accept: bool, expected_agreement_version: int,
                                  new_minimum_cents=None, waive_period_ids=None) -> dict:
    """POST .../resolve-renegotiation body (OCC-guarded, PRD §2.8, §3.6).

    ``accept`` and ``expected_agreement_version`` are mandatory. Accepting
    additionally requires ``new_minimum_cents`` >= 50000.
    """
    payload = {
        "accept": accept,
        "expected_agreement_version": expected_agreement_version,
    }
    if new_minimum_cents is not None:
        payload["new_minimum_cents"] = new_minimum_cents
    if waive_period_ids is not None:
        payload["waive_period_ids"] = waive_period_ids
    return payload


def close_commitment_period_payload(period_month: str, expected_agreement_version: int) -> dict:
    """POST .../close-commitment-period body (OCC-guarded, PRD §2.8, §3.5)."""
    return {
        "period_month": period_month,
        "expected_agreement_version": expected_agreement_version,
    }


def record_payment_payload(amount_cents: int) -> dict:
    """POST /api/commitment-periods/{id}/record-payment body; the amount must
    equal the period's billed_cents exactly (PRD §3.5)."""
    return {"amount_cents": amount_cents}
