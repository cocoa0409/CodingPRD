"""Composite setup fixtures — multi-step preconditions behind one call.

Conventions
-----------
* Every fixture builds its preconditions FROM SCRATCH via the public API:
  the harness restarts the server before every test, so each test starts
  against an empty database with the logical clock at its startup default
  ``CLOCK_START_ISO`` (PRD §2.4: exactly 2026-09-01T00:00:00Z).
* Fixtures use ``get_success_data`` (lenient 2xx) so a broken precondition
  surfaces as a clear "Setup step failed" error, not a confusing assertion.
* IDENTITY THREADING (PRD §2.1): every ownership-gated ClinicManager call
  uses ``make_clinic_manager_headers(clinic["id"])`` — never a shared
  constant whose id matches no clinic.
* CLOCK DISCIPLINE: fixtures that advance the clock say so in their
  docstring and return/record the new clock where relevant. A fixture whose
  name starts ``setup_`` assumes the clock is still at ``CLOCK_START_ISO``
  when entered; if a test has already advanced the clock, pass explicit
  ``base_clock``/date arguments instead of relying on the default.
* VERSION DISCIPLINE: OCC-guarded writes (resolve-renegotiation,
  close-commitment-period) re-read the live agreement version via GET unless
  the caller pins ``expected_agreement_version`` explicitly.
"""
from datetime import datetime, timedelta

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import CLOCK_START_ISO, CLOCK_2026_10_02, CLOCK_2027_01_15, TEST_DEFAULTS
from .factories import (
    clock_set_payload, close_commitment_period_payload, create_analyzer_payload,
    create_clinic_payload, create_group_pricing_agreement_payload,
    create_lease_agreement_payload, create_patient_order_payload,
    create_proficiency_order_payload, create_purchase_agreement_payload,
    create_reagent_commitment_agreement_payload, create_reagent_order_payload,
    create_send_out_order_payload, create_service_case_payload,
    patch_analyzer_payload, patch_clinic_payload, patch_lab_test_order_payload,
    patch_reagent_order_payload, patch_service_case_payload,
    record_payment_payload, reagent_line, resolve_renegotiation_payload,
)
from .test_users import TEST_USERS, make_clinic_manager_headers

__all__ = [
    "iso_hours_after",
    # tier 1: single entities & transitions
    "create_clinic", "get_clinic", "update_caseload", "set_clinic_status",
    "advance_clock", "create_group_pricing_agreement",
    "list_group_pricing_agreements",
    "draft_reagent_commitment_agreement", "draft_purchase_agreement",
    "draft_lease_agreement", "approve_agreement", "activate_agreement",
    "get_agreement", "current_agreement_version",
    "install_analyzer", "get_analyzer", "patch_analyzer", "enter_service",
    "set_connectivity",
    # tier 2: hierarchies
    "setup_clinic_with_active_reagent_commitment",
    "setup_clinic_with_active_purchase",
    "setup_clinic_with_rc_and_purchase_agreements",
    "setup_in_service_analyzer", "setup_online_analyzer",
    "setup_patient_order_ready", "setup_recorded_patient_result",
    # tier 3: lab pipelines
    "place_patient_order", "place_proficiency_order",
    "place_send_out_patient_order", "record_in_clinic_result",
    "record_proficiency_pass", "receive_send_out_order",
    "record_send_out_result", "deliver_test_order", "cancel_test_order",
    "get_test_order", "get_test_order_results",
    # tier 3: reagent orders
    "place_reagent_order", "fulfill_reagent_order", "cancel_reagent_order",
    "get_reagent_order",
    # tier 4: commitment periods, billing, renegotiation, breach
    "list_commitment_periods", "get_period_by_month",
    "close_commitment_period", "close_periods_chronologically",
    "record_exact_payment", "setup_agreement_with_closed_period",
    "request_renegotiation", "resolve_renegotiation",
    "setup_agreement_in_renegotiation", "setup_breached_agreement",
    # tier 5: service cases / uptime
    "open_service_case", "dispatch_service_case", "resolve_service_case",
    "cancel_service_case", "list_service_cases",
    "setup_resolved_downtime_case",
]

_ADMIN = TEST_USERS["platform_admin_headers"]
_FINANCE = TEST_USERS["finance_reviewer_headers"]
_ENGINEER = TEST_USERS["field_service_engineer_headers"]
_LABTECH = TEST_USERS["laboratory_technician_headers"]


def _cm(clinic_id: str) -> dict:
    """Ownership-correct ClinicManager headers for the given clinic id."""
    return make_clinic_manager_headers(clinic_id)


def iso_hours_after(base_iso: str, hours: float) -> str:
    """Derive an ISO timestamp ``hours`` after ``base_iso`` (same Z form).

    Derived, never invented: use with CLOCK_START_ISO or a clock value a
    fixture returned, so every advance stays strictly forward (PRD §2.4).
    """
    base = datetime.strptime(base_iso, "%Y-%m-%dT%H:%M:%SZ")
    return (base + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


# ===========================================================================
# Tier 1 — single entities and simple transitions
# ===========================================================================
def create_clinic(name: str = TEST_DEFAULTS["CLINIC_NAME"],
                  caseload_baseline_tests: int = TEST_DEFAULTS["BASELINE_CASELOAD"],
                  corporate_group_code=None, buying_group_code=None) -> dict:
    """Onboard a clinic (PlatformAdmin). Born ACTIVE with
    caseload_current_tests == caseload_baseline_tests (PRD §3.1)."""
    overrides = {"name": name, "caseload_baseline_tests": caseload_baseline_tests}
    if corporate_group_code is not None:
        overrides["corporate_group_code"] = corporate_group_code
    if buying_group_code is not None:
        overrides["buying_group_code"] = buying_group_code
    return get_success_data(api_client.create_clinic(create_clinic_payload(**overrides), _ADMIN))


def get_clinic(clinic_id: str) -> dict:
    return get_success_data(api_client.get_clinic(clinic_id, _ADMIN))


def update_caseload(clinic_id: str, caseload_current_tests: int) -> dict:
    """PATCH caseload_current_tests as the owning ClinicManager (ACTIVE only)."""
    return get_success_data(api_client.update_clinic(
        clinic_id, patch_clinic_payload(caseload_current_tests=caseload_current_tests),
        _cm(clinic_id),
    ))


def set_clinic_status(clinic_id: str, status: str) -> dict:
    """Drive a clinic status transition as PlatformAdmin (PRD §3.1)."""
    return get_success_data(api_client.update_clinic(
        clinic_id, patch_clinic_payload(status=status), _ADMIN,
    ))


def advance_clock(to_iso8601: str) -> str:
    """Advance the logical clock (must be strictly forward). Returns current_utc."""
    data = get_success_data(api_client.set_clock(to_iso8601, _ADMIN))
    return data["current_utc"]


def create_group_pricing_agreement(group_type: str = "CORPORATE", group_code: str = "CORP-1",
                                   effective_from: str = CLOCK_START_ISO,
                                   effective_to: str = TEST_DEFAULTS["GPA_EFFECTIVE_TO"],
                                   discount_pct: float = 0.10, sku_overrides=None) -> dict:
    """Create a group pricing agreement (PlatformAdmin, PRD §3.2)."""
    overrides = {
        "group_type": group_type, "group_code": group_code,
        "effective_from": effective_from, "effective_to": effective_to,
        "discount_pct": discount_pct,
    }
    if sku_overrides is not None:
        overrides["sku_overrides"] = sku_overrides
    return get_success_data(api_client.create_group_pricing_agreement(
        create_group_pricing_agreement_payload(**overrides), _ADMIN,
    ))


def list_group_pricing_agreements(group_code=None, status=None) -> list:
    params = {}
    if group_code is not None:
        params["group_code"] = group_code
    if status is not None:
        params["status"] = status
    return get_success_data(api_client.list_group_pricing_agreements(_ADMIN, params=params or None))


# ---------------------------------------------------------------------------
# Placement agreement lifecycle (DRAFT -> APPROVED -> ACTIVE)
# ---------------------------------------------------------------------------
def draft_reagent_commitment_agreement(clinic_id: str, **overrides) -> dict:
    """Draft a REAGENT_COMMITMENT agreement as the owning ClinicManager."""
    return get_success_data(api_client.create_placement_agreement(
        create_reagent_commitment_agreement_payload(clinic_id, **overrides), _cm(clinic_id),
    ))


def draft_purchase_agreement(clinic_id: str, **overrides) -> dict:
    """Draft a PURCHASE agreement as the owning ClinicManager."""
    return get_success_data(api_client.create_placement_agreement(
        create_purchase_agreement_payload(clinic_id, **overrides), _cm(clinic_id),
    ))


def draft_lease_agreement(clinic_id: str, **overrides) -> dict:
    """Draft a LEASE agreement as the owning ClinicManager."""
    return get_success_data(api_client.create_placement_agreement(
        create_lease_agreement_payload(clinic_id, **overrides), _cm(clinic_id),
    ))


def approve_agreement(agreement_id: str) -> dict:
    """DRAFT -> APPROVED (FinanceReviewer)."""
    return get_success_data(api_client.approve_placement_agreement(agreement_id, _FINANCE))


def activate_agreement(agreement_id: str) -> dict:
    """APPROVED -> ACTIVE (PlatformAdmin): snapshots baseline caseload and
    creates one OPEN CommitmentPeriod per term month (PRD §3.3)."""
    return get_success_data(api_client.activate_placement_agreement(agreement_id, _ADMIN))


def get_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.get_placement_agreement(agreement_id, _ADMIN))


def current_agreement_version(agreement_id: str) -> int:
    """Live version of the agreement (for OCC-guarded writes, PRD §2.8)."""
    return int(get_agreement(agreement_id)["version"])


def _activate_fresh_agreement(draft: dict) -> dict:
    approve_agreement(draft["id"])
    return activate_agreement(draft["id"])


# ---------------------------------------------------------------------------
# Analyzers
# ---------------------------------------------------------------------------
def install_analyzer(clinic_id: str, agreement_id: str, serial_number=None,
                     is_loaner_unit: bool = False) -> dict:
    """Install an analyzer (FieldServiceEngineer). Born INSTALLED /
    NOT_CONFIGURED / LAPSED with model copied from the agreement (PRD §3.7)."""
    overrides = {}
    if serial_number is not None:
        overrides["serial_number"] = serial_number
    if is_loaner_unit:
        overrides["is_loaner_unit"] = True
    return get_success_data(api_client.create_analyzer(
        create_analyzer_payload(clinic_id, agreement_id, **overrides), _ENGINEER,
    ))


def get_analyzer(analyzer_id: str) -> dict:
    return get_success_data(api_client.get_analyzer(analyzer_id, _ENGINEER))


def patch_analyzer(analyzer_id: str, operational_status=None, connectivity_status=None) -> dict:
    """Drive analyzer dimensions (FieldServiceEngineer, PRD §3.7)."""
    return get_success_data(api_client.update_analyzer(
        analyzer_id,
        patch_analyzer_payload(operational_status=operational_status,
                               connectivity_status=connectivity_status),
        _ENGINEER,
    ))


def enter_service(analyzer_id: str) -> dict:
    """INSTALLED -> IN_SERVICE."""
    return patch_analyzer(analyzer_id, operational_status="IN_SERVICE")


def set_connectivity(analyzer_id: str, connectivity_status: str) -> dict:
    """Drive connectivity NOT_CONFIGURED->ACTIVE, ACTIVE<->DEGRADED."""
    return patch_analyzer(analyzer_id, connectivity_status=connectivity_status)


# ===========================================================================
# Tier 2 — composite hierarchies
# ===========================================================================
def setup_clinic_with_active_reagent_commitment(
        baseline: int = TEST_DEFAULTS["BASELINE_CASELOAD"],
        monthly_minimum_cents: int = TEST_DEFAULTS["MONTHLY_MINIMUM_CENTS"],
        term_months: int = TEST_DEFAULTS["TERM_MONTHS"],
        start_date: str = TEST_DEFAULTS["START_DATE"],
        model: str = TEST_DEFAULTS["MODEL_RC"],
        clinic_kwargs: dict = None) -> dict:
    """Clinic + REAGENT_COMMITMENT agreement walked DRAFT->APPROVED->ACTIVE
    (agreement at version 3, 24 OPEN periods by default).
    Returns {"clinic", "agreement"}. Clock untouched."""
    clinic_kwargs = dict(clinic_kwargs or {})
    clinic = create_clinic(caseload_baseline_tests=baseline, **clinic_kwargs)
    draft = draft_reagent_commitment_agreement(
        clinic["id"], model=model, term_months=term_months,
        start_date=start_date, monthly_minimum_cents=monthly_minimum_cents,
    )
    agreement = _activate_fresh_agreement(draft)
    return {"clinic": clinic, "agreement": agreement}


def setup_clinic_with_active_purchase(
        baseline: int = TEST_DEFAULTS["BASELINE_CASELOAD"],
        purchase_price_cents: int = TEST_DEFAULTS["PURCHASE_PRICE_CENTS"],
        term_months: int = TEST_DEFAULTS["TERM_MONTHS"],
        start_date: str = TEST_DEFAULTS["START_DATE"],
        model: str = TEST_DEFAULTS["MODEL_PURCHASE"],
        clinic_kwargs: dict = None) -> dict:
    """Clinic + PURCHASE agreement walked to ACTIVE.
    Returns {"clinic", "agreement"}. Clock untouched."""
    clinic_kwargs = dict(clinic_kwargs or {})
    clinic = create_clinic(caseload_baseline_tests=baseline, **clinic_kwargs)
    draft = draft_purchase_agreement(
        clinic["id"], model=model, term_months=term_months,
        start_date=start_date, purchase_price_cents=purchase_price_cents,
    )
    agreement = _activate_fresh_agreement(draft)
    return {"clinic": clinic, "agreement": agreement}


def setup_clinic_with_rc_and_purchase_agreements(**kwargs) -> dict:
    """One clinic carrying TWO ACTIVE agreements of different models (so no
    term-overlap conflict): REAGENT_COMMITMENT VETCHEM_300 + PURCHASE
    VETHEMAT_500. Returns {"clinic", "rc_agreement", "purchase_agreement"}."""
    clinic = create_clinic(**kwargs)
    rc = _activate_fresh_agreement(draft_reagent_commitment_agreement(clinic["id"]))
    purchase = _activate_fresh_agreement(draft_purchase_agreement(clinic["id"]))
    return {"clinic": clinic, "rc_agreement": rc, "purchase_agreement": purchase}


def setup_in_service_analyzer(serial_number=None, **scenario_kwargs) -> dict:
    """PURCHASE scenario with the analyzer driven INSTALLED -> IN_SERVICE.
    Returns {"clinic", "agreement", "analyzer"}. Clock untouched."""
    scenario = setup_clinic_with_active_purchase(**scenario_kwargs)
    analyzer = install_analyzer(
        scenario["clinic"]["id"], scenario["agreement"]["id"], serial_number=serial_number,
    )
    analyzer = enter_service(analyzer["id"])
    return {**scenario, "analyzer": analyzer}


def setup_online_analyzer(serial_number=None,
                          expected_result: float = TEST_DEFAULTS["EXPECTED_RESULT"],
                          pass_result: float = TEST_DEFAULTS["PROF_PASS_RESULT"],
                          **scenario_kwargs) -> dict:
    """Fully online analyzer: IN_SERVICE + connectivity ACTIVE + proficiency
    CURRENT (one PROFICIENCY PASS recorded at the CURRENT clock, so
    qc_valid_until = resulted_at + 30 days, PRD §3.9).
    Returns {"clinic", "agreement", "analyzer", "proficiency_order"}.
    Clock untouched."""
    scenario = setup_in_service_analyzer(serial_number=serial_number, **scenario_kwargs)
    analyzer = set_connectivity(scenario["analyzer"]["id"], "ACTIVE")
    proficiency_order = record_proficiency_pass(
        scenario["clinic"]["id"], analyzer["id"],
        expected_result=expected_result, result=pass_result,
    )
    analyzer = get_analyzer(analyzer["id"])
    return {**scenario, "analyzer": analyzer, "proficiency_order": proficiency_order}


def setup_patient_order_ready(test_code: str = TEST_DEFAULTS["TEST_CODE_PATIENT"],
                              **kwargs) -> dict:
    """Online analyzer plus an IN_CLINIC PATIENT order in ORDERED.
    Returns setup_online_analyzer() keys plus "patient_order"."""
    scenario = setup_online_analyzer(**kwargs)
    patient_order = place_patient_order(
        scenario["clinic"]["id"], scenario["analyzer"]["id"], test_code=test_code,
    )
    return {**scenario, "patient_order": patient_order}


def setup_recorded_patient_result(result_value: float = TEST_DEFAULTS["PATIENT_RESULT"],
                                  **kwargs) -> dict:
    """Online analyzer plus a PATIENT order already RESULT_RECORDED
    (delivery_status PENDING). Returns setup_patient_order_ready() keys plus
    "results" (the 1-element LabResult array)."""
    scenario = setup_patient_order_ready(**kwargs)
    order = record_in_clinic_result(
        scenario["patient_order"]["id"], scenario["clinic"]["id"], result_value,
    )
    results = get_test_order_results(order["id"])
    return {**scenario, "patient_order": order, "results": results}


# ===========================================================================
# Tier 3 — lab test pipelines (PRD §3.8)
# ===========================================================================
def place_patient_order(clinic_id: str, analyzer_id: str,
                        test_code: str = TEST_DEFAULTS["TEST_CODE_PATIENT"]) -> dict:
    """IN_CLINIC PATIENT order by the owning ClinicManager (clinic ACTIVE)."""
    return get_success_data(api_client.create_lab_test_order(
        create_patient_order_payload(clinic_id, analyzer_id, test_code=test_code), _cm(clinic_id),
    ))


def place_proficiency_order(clinic_id: str, analyzer_id: str,
                            expected_result: float = TEST_DEFAULTS["EXPECTED_RESULT"],
                            test_code: str = TEST_DEFAULTS["TEST_CODE_PROFICIENCY"]) -> dict:
    """IN_CLINIC PROFICIENCY order (expected_result mandatory, PRD §3.8)."""
    return get_success_data(api_client.create_lab_test_order(
        create_proficiency_order_payload(
            clinic_id, analyzer_id, expected_result=expected_result, test_code=test_code,
        ),
        _cm(clinic_id),
    ))


def place_send_out_patient_order(clinic_id: str,
                                 test_code: str = TEST_DEFAULTS["TEST_CODE_SEND_OUT"]) -> dict:
    """SEND_OUT PATIENT order (no analyzer)."""
    return get_success_data(api_client.create_lab_test_order(
        create_send_out_order_payload(clinic_id, test_code=test_code), _cm(clinic_id),
    ))


def record_in_clinic_result(order_id: str, clinic_id: str, result_value: float) -> dict:
    """RECORD_RESULT on the IN_CLINIC branch (owning ClinicManager; analyzer
    safety gates apply, PRD §3.8). ORDERED -> RESULT_RECORDED."""
    return get_success_data(api_client.update_lab_test_order(
        order_id, patch_lab_test_order_payload("RECORD_RESULT", result_value=result_value),
        _cm(clinic_id),
    ))


def record_proficiency_pass(clinic_id: str, analyzer_id: str,
                            expected_result: float = TEST_DEFAULTS["EXPECTED_RESULT"],
                            result: float = TEST_DEFAULTS["PROF_PASS_RESULT"]) -> dict:
    """Create a PROFICIENCY order and record a passing result; flips the
    analyzer to proficiency CURRENT (PRD §3.9). Returns the order."""
    order = place_proficiency_order(clinic_id, analyzer_id, expected_result=expected_result)
    return record_in_clinic_result(order["id"], clinic_id, result)


def receive_send_out_order(order_id: str) -> dict:
    """RECEIVE on the SEND_OUT branch (LaboratoryTechnician)."""
    return get_success_data(api_client.update_lab_test_order(
        order_id, patch_lab_test_order_payload("RECEIVE"), _LABTECH,
    ))


def record_send_out_result(order_id: str, result_value: float) -> dict:
    """RECORD_RESULT on the SEND_OUT branch (LaboratoryTechnician, from RECEIVED)."""
    return get_success_data(api_client.update_lab_test_order(
        order_id, patch_lab_test_order_payload("RECORD_RESULT", result_value=result_value),
        _LABTECH,
    ))


def deliver_test_order(order_id: str, clinic_id: str) -> dict:
    """DELIVER (owning ClinicManager; IN_CLINIC requires connectivity ACTIVE)."""
    return get_success_data(api_client.update_lab_test_order(
        order_id, patch_lab_test_order_payload("DELIVER"), _cm(clinic_id),
    ))


def cancel_test_order(order_id: str, clinic_id: str) -> dict:
    """CANCEL from ORDERED or RECEIVED (owning ClinicManager)."""
    return get_success_data(api_client.update_lab_test_order(
        order_id, patch_lab_test_order_payload("CANCEL"), _cm(clinic_id),
    ))


def get_test_order(order_id: str) -> dict:
    return get_success_data(api_client.get_lab_test_order(order_id, _ADMIN))


def get_test_order_results(order_id: str) -> list:
    """The unified result record array (length 0 before recording, 1 after)."""
    return get_success_data(api_client.list_lab_test_results(order_id, _ADMIN))


# ===========================================================================
# Tier 3 — reagent orders (PRD §3.4)
# ===========================================================================
def place_reagent_order(clinic_id: str, agreement_id: str, order_month: str = "2026-09",
                        lines=None) -> dict:
    """Submit a reagent order (owning ClinicManager; pricing locked at creation).
    Default: 100 x VC300_CHEM_SLIDE for the agreement's first month."""
    return get_success_data(api_client.create_reagent_order(
        create_reagent_order_payload(
            clinic_id, agreement_id, order_month=order_month,
            lines=lines if lines is not None else [reagent_line("VC300_CHEM_SLIDE", 100)],
        ),
        _cm(clinic_id),
    ))


def fulfill_reagent_order(order_id: str, clinic_id: str) -> dict:
    """SUBMITTED -> FULFILLED (owning ClinicManager; stamps fulfilled_at)."""
    return get_success_data(api_client.update_reagent_order(
        order_id, patch_reagent_order_payload("FULFILLED"), _cm(clinic_id),
    ))


def cancel_reagent_order(order_id: str, clinic_id: str) -> dict:
    """SUBMITTED -> CANCELLED (owning ClinicManager; conserves all commitment
    totals, PRD §3.4)."""
    return get_success_data(api_client.update_reagent_order(
        order_id, patch_reagent_order_payload("CANCELLED"), _cm(clinic_id),
    ))


def get_reagent_order(order_id: str) -> dict:
    return get_success_data(api_client.get_reagent_order(order_id, _ADMIN))


# ===========================================================================
# Tier 4 — commitment periods, billing, renegotiation, breach (PRD §3.5/§3.6)
# ===========================================================================
def list_commitment_periods(agreement_id: str, period_status=None) -> list:
    """The agreement's periods, ordered by period_month ASC (all pages).

    PRD §2.3 paginates list endpoints with a default limit of 10, so the
    full 24-month term requires walking `offset` until `has_more` clears.
    """
    items: list = []
    offset = 0
    while True:
        params = {"limit": 100, "offset": offset}
        if period_status is not None:
            params["period_status"] = period_status
        page, meta = validate_paginated(
            api_client.list_commitment_periods(agreement_id, _FINANCE, params=params)
        )
        items.extend(page)
        if not meta["has_more"]:
            return items
        offset += meta["limit"]


def get_period_by_month(agreement_id: str, period_month: str) -> dict:
    """Exactly one period row for the named YYYY-MM month of this agreement."""
    matches = [p for p in list_commitment_periods(agreement_id) if p["period_month"] == period_month]
    assert len(matches) == 1, (
        f"expected exactly one period {period_month}, found {len(matches)}"
    )
    return matches[0]


def close_commitment_period(agreement_id: str, period_month: str,
                            expected_agreement_version: int = None) -> dict:
    """Close one period (PlatformAdmin, OCC-guarded). When the expected
    version is omitted, the live version is read first. Returns the CLOSED
    period."""
    if expected_agreement_version is None:
        expected_agreement_version = current_agreement_version(agreement_id)
    return get_success_data(api_client.close_commitment_period(
        agreement_id,
        close_commitment_period_payload(period_month, expected_agreement_version),
        _ADMIN,
    ))


def close_periods_chronologically(agreement_id: str, period_months) -> list:
    """Close several periods in order, re-reading the agreement version before
    each close. Returns the CLOSED period dicts in close order."""
    closed = []
    for month in period_months:
        closed.append(close_commitment_period(agreement_id, month))
    return closed


def record_exact_payment(period_id: str, amount_cents: int) -> dict:
    """Record an exact payment on an ISSUED period (FinanceReviewer)."""
    return get_success_data(api_client.record_payment(
        period_id, record_payment_payload(amount_cents), _FINANCE,
    ))


def setup_agreement_with_closed_period(period_month: str = "2026-09",
                                       clock_to: str = CLOCK_2026_10_02,
                                       order_specs=(),
                                       fulfill_after_clock_advance: bool = False) -> dict:
    """RC agreement (minimum 100000c) with one period CLOSED.

    Sequence: clinic + agreement ACTIVE -> optional orders created (BEFORE the
    clock advance) -> clock advanced to ``clock_to`` (must sit in a month
    strictly after ``period_month``) -> orders optionally fulfilled (only when
    ``fulfill_after_clock_advance``) -> the named period closed.

    With no orders the period closes at fulfilled_cents 0 / billed_cents
    80000 / billing_status ISSUED. ``fulfill_after_clock_advance=True`` with a
    September order makes the provisional and final attribution variants
    diverge (fulfilled in October, order_month September).

    Returns {"clinic", "agreement", "orders", "period", "periods"} where
    "agreement" is re-read AFTER the close. Clock ends at ``clock_to``.
    """
    scenario = setup_clinic_with_active_reagent_commitment()
    clinic = scenario["clinic"]
    agreement = scenario["agreement"]
    orders = []
    for spec in order_specs:
        orders.append(place_reagent_order(
            clinic["id"], agreement["id"],
            order_month=spec.get("order_month", period_month),
            lines=spec.get("lines"),
        ))
    advance_clock(clock_to)
    if fulfill_after_clock_advance:
        orders = [fulfill_reagent_order(o["id"], clinic["id"]) for o in orders]
    period = close_commitment_period(agreement["id"], period_month)
    agreement = get_agreement(agreement["id"])
    return {
        "clinic": clinic, "agreement": agreement, "orders": orders,
        "period": period, "periods": list_commitment_periods(agreement["id"]),
    }


def request_renegotiation(agreement_id: str, clinic_id: str) -> dict:
    """ACTIVE -> RENEGOTIATION (owning ClinicManager; caseload-delta gate
    applies, PRD §3.6). Returns the agreement with proposed_minimum_cents."""
    return get_success_data(api_client.request_renegotiation(agreement_id, _cm(clinic_id)))


def resolve_renegotiation(agreement_id: str, accept: bool, expected_agreement_version: int,
                          new_minimum_cents=None, waive_period_ids=None) -> dict:
    """RENEGOTIATION -> ACTIVE (FinanceReviewer, OCC-guarded, PRD §3.6)."""
    return get_success_data(api_client.resolve_renegotiation(
        agreement_id,
        resolve_renegotiation_payload(
            accept, expected_agreement_version,
            new_minimum_cents=new_minimum_cents, waive_period_ids=waive_period_ids,
        ),
        _FINANCE,
    ))


def setup_agreement_in_renegotiation(
        current_caseload: int = 1400,
        baseline: int = TEST_DEFAULTS["BASELINE_CASELOAD"],
        monthly_minimum_cents: int = TEST_DEFAULTS["MONTHLY_MINIMUM_CENTS"]) -> dict:
    """ACTIVE RC agreement (snapshot == baseline) whose clinic caseload has
    moved to ``current_caseload`` (default +40% >= the 0.30 gate) and whose
    renegotiation has been requested. Returns {"clinic", "agreement"} with
    the agreement in RENEGOTIATION. Clock untouched."""
    scenario = setup_clinic_with_active_reagent_commitment(
        baseline=baseline, monthly_minimum_cents=monthly_minimum_cents,
    )
    clinic = update_caseload(scenario["clinic"]["id"], current_caseload)
    agreement = request_renegotiation(scenario["agreement"]["id"], clinic["id"])
    return {"clinic": clinic, "agreement": agreement}


def setup_breached_agreement(
        close_months=("2026-09", "2026-10", "2026-11", "2026-12"),
        clock_to: str = CLOCK_2027_01_15) -> dict:
    """RC agreement with no orders; clock advanced to ``clock_to`` (a month
    after every ``close_months`` entry); the months closed chronologically.

    Each close bills 80000c; the FOURTH close crosses the 250000c breach
    threshold (320000 unpaid), cascading agreement ACTIVE -> BREACHED and
    clinic ACTIVE -> SUSPENDED (PRD §3.5).

    Returns {"clinic", "agreement", "closed_periods"} with both entities
    re-read after the final close. Clock ends at ``clock_to``.
    """
    scenario = setup_clinic_with_active_reagent_commitment()
    clinic = scenario["clinic"]
    agreement = scenario["agreement"]
    advance_clock(clock_to)
    closed = close_periods_chronologically(agreement["id"], list(close_months))
    return {
        "clinic": get_clinic(clinic["id"]),
        "agreement": get_agreement(agreement["id"]),
        "closed_periods": closed,
    }


# ===========================================================================
# Tier 5 — service cases and uptime (PRD §3.7, §3.9)
# ===========================================================================
def open_service_case(analyzer_id: str, case_type: str = "REPAIR",
                      loaner_analyzer_id=None) -> dict:
    """Open a REPAIR/PREVENTIVE_CALIBRATION case (FieldServiceEngineer); moves
    the serviced unit IN_SERVICE -> UNDER_SERVICE and any loaner to ON_LOAN."""
    overrides = {"case_type": case_type}
    if loaner_analyzer_id is not None:
        overrides["loaner_analyzer_id"] = loaner_analyzer_id
    return get_success_data(api_client.create_service_case(
        create_service_case_payload(analyzer_id, **overrides), _ENGINEER,
    ))


def dispatch_service_case(case_id: str) -> dict:
    """OPEN -> DISPATCHED."""
    return get_success_data(api_client.update_service_case(
        case_id, patch_service_case_payload("DISPATCH"), _ENGINEER,
    ))


def resolve_service_case(case_id: str, resolution_note=None) -> dict:
    """DISPATCHED -> RESOLVED: downtime/sla computed, units returned, uptime
    recomputed, service-credit cascade evaluated (PRD §3.7, §3.9)."""
    return get_success_data(api_client.update_service_case(
        case_id, patch_service_case_payload("RESOLVE", resolution_note=resolution_note), _ENGINEER,
    ))


def cancel_service_case(case_id: str) -> dict:
    """OPEN|DISPATCHED -> CANCELLED with unit-return compensation (no downtime)."""
    return get_success_data(api_client.update_service_case(
        case_id, patch_service_case_payload("CANCEL"), _ENGINEER,
    ))


def list_service_cases(analyzer_id: str, status=None) -> list:
    """Service cases involving the analyzer as serviced unit OR loaner."""
    params = {"status": status} if status else None
    return get_success_data(api_client.list_service_cases(analyzer_id, _ENGINEER, params=params))


def setup_resolved_downtime_case(case_type: str = "REPAIR", downtime_hours: int = 20,
                                 base_clock: str = CLOCK_START_ISO,
                                 resolution_note: str = None) -> dict:
    """PURCHASE scenario; analyzer IN_SERVICE; a case opened AT ``base_clock``,
    dispatched, the clock advanced ``downtime_hours``, then resolved.

    PRECONDITION: the logical clock must still equal ``base_clock`` when this
    fixture opens the case (fresh test), otherwise the advance is rejected as
    non-forward and downtime math breaks. Clock ends at
    ``base_clock + downtime_hours``.

    Returns {"clinic", "agreement", "analyzer", "service_case"} with the
    analyzer re-read after resolution.
    """
    scenario = setup_in_service_analyzer()
    analyzer = scenario["analyzer"]
    case = open_service_case(analyzer["id"], case_type=case_type)
    case = dispatch_service_case(case["id"])
    advance_clock(iso_hours_after(base_clock, downtime_hours))
    case = resolve_service_case(case["id"], resolution_note=resolution_note)
    return {
        **scenario,
        "analyzer": get_analyzer(analyzer["id"]),
        "service_case": case,
    }
