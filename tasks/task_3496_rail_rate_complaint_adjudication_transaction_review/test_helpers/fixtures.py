"""Composite setup helpers (PRD §3 workflows).

Every fixture builds preconditions from scratch via PRD-declared endpoints;
each test runs against a freshly restarted server with an empty database and
the logical clock at 2026-09-01T00:00:00Z. Setup calls use the lenient
get_success_data validator so failures surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    CLOCK_DEFAULT_UTC,
    FINDING_2025_SINGLE,
    FINDINGS_2021_2025,
    SHIPPER_ADA,
    SHIPPER_GAL,
)
from .factories import (
    create_abandonment_payload,
    create_carrier_payload,
    create_evidence_payload,
    create_finding_payload,
    create_merger_application_payload,
    create_petition_payload,
    create_rate_complaint_payload,
    create_service_assurance_plan_payload,
    create_service_complaint_payload,
    decide_abandonment_payload,
    decide_rate_complaint_payload,
    determine_market_dominance_payload,
    escalate_payload,
    verify_evidence_payload,
)
from .test_users import (
    TEST_USERS,
    make_carrier_operator_headers,
    make_shipper_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BOARD = TEST_USERS["board_adjudicator_headers"]


# --- clock -------------------------------------------------------------------

def set_clock(current_utc: str):
    """Advance the logical clock (PlatformAdmin-only test-driving capability)."""
    resp = api_client.set_clock({"current_utc": current_utc}, ADMIN)
    get_success_data(resp, 200)


# --- carriers and findings ----------------------------------------------------

def register_carrier(**overrides) -> dict:
    """Register a carrier; returns the carrier resource (201)."""
    resp = api_client.create_carrier(create_carrier_payload(**overrides), ADMIN)
    return get_success_data(resp, 201)


def file_finding(carrier_id: str, **overrides) -> dict:
    """File one annual revenue adequacy finding (BoardAdjudicator, 201)."""
    resp = api_client.create_finding(carrier_id, create_finding_payload(**overrides), BOARD)
    return get_success_data(resp, 201)


def file_findings(carrier_id: str, findings) -> list:
    return [file_finding(carrier_id, **f) for f in findings]


def register_carrier_with_inadequate_2025(**carrier_overrides) -> dict:
    """Carrier whose only finding (2025, 1000 bps) lands INADEQUATE."""
    carrier = register_carrier(**carrier_overrides)
    file_finding(carrier["id"], **FINDING_2025_SINGLE)
    return get_carrier_data(carrier["id"])


def register_carrier_with_adequate_history(**carrier_overrides) -> dict:
    """Carrier with findings 2021-2025; five-year average 1180 bps -> ADEQUATE."""
    carrier = register_carrier(**carrier_overrides)
    file_findings(carrier["id"], FINDINGS_2021_2025)
    return get_carrier_data(carrier["id"])


def get_carrier_data(carrier_id: str) -> dict:
    return get_success_data(api_client.get_carrier(carrier_id, BOARD), 200)


# --- rate complaints ----------------------------------------------------------

def file_rate_complaint(carrier_id: str, shipper_id: str = SHIPPER_ADA, **overrides) -> dict:
    """Shipper files a rate complaint (201); complaint lands in FILED."""
    payload = create_rate_complaint_payload(
        shipper_id=shipper_id, carrier_id=carrier_id, **overrides)
    resp = api_client.create_rate_complaint(payload, make_shipper_headers(shipper_id))
    return get_success_data(resp, 201)


def determine_dominance(complaint_id: str, **overrides) -> dict:
    """Board issues the market dominance determination (200)."""
    resp = api_client.determine_market_dominance(
        complaint_id, determine_market_dominance_payload(**overrides), BOARD)
    return get_success_data(resp, 200)


def submit_evidence_as_shipper(complaint_id: str, shipper_id: str = SHIPPER_ADA,
                               **overrides) -> dict:
    """Shipper submits evidence on its own complaint (201)."""
    payload = create_evidence_payload(submitted_by_party="SHIPPER", **overrides)
    resp = api_client.submit_evidence(
        complaint_id, payload, make_shipper_headers(shipper_id))
    return get_success_data(resp, 201)


def submit_evidence_as_carrier(complaint_id: str, carrier_id: str, **overrides) -> dict:
    """CarrierOperator submits evidence on a complaint against its carrier (201)."""
    payload = create_evidence_payload(
        submission_type="REBUTTAL", submitted_by_party="CARRIER", **overrides)
    resp = api_client.submit_evidence(
        complaint_id, payload, make_carrier_operator_headers(carrier_id))
    return get_success_data(resp, 201)


def verify_submission(evidence_id: str, outcome: str = "VERIFIED") -> dict:
    """Board reviews an evidence submission (200)."""
    resp = api_client.verify_evidence(evidence_id, verify_evidence_payload(outcome), BOARD)
    return get_success_data(resp, 200)


def setup_evidentiary_complaint(carrier_id: str, shipper_id: str = SHIPPER_ADA,
                                complaint_overrides=None, evidence_overrides=None):
    """Complaint walked FILED -> EVIDENTIARY_PHASE with one VERIFIED submission.

    Returns (complaint, evidence): complaint re-read after verification, so its
    adjudicated_rvc_ratio reflects the verified cost figure.
    """
    complaint = file_rate_complaint(carrier_id, shipper_id, **(complaint_overrides or {}))
    determine_dominance(complaint["id"])
    evidence = submit_evidence_as_shipper(
        complaint["id"], shipper_id, **(evidence_overrides or {}))
    verify_submission(evidence["id"])
    return get_rate_complaint_data(complaint["id"]), evidence


def decide_upheld(complaint_id: str, shipments=None) -> dict:
    """Board decides UPHELD (200); default single 10.000-ton shipment."""
    if shipments is None:
        shipments = [{"shipment_ref": "S-1", "tons": 10.000}]
    resp = api_client.decide_rate_complaint(
        complaint_id, decide_rate_complaint_payload("UPHELD", shipments), BOARD)
    return get_success_data(resp, 200)


def get_rate_complaint_data(complaint_id: str) -> dict:
    return get_success_data(api_client.get_rate_complaint(complaint_id, BOARD), 200)


def list_evidence_data(complaint_id: str) -> list:
    resp = api_client.list_evidence(complaint_id, BOARD)
    data, _meta = validate_paginated(resp)
    return data


# --- service complaints / emergency service orders ----------------------------

def file_service_complaint(carrier_id: str, shipper_id: str = SHIPPER_GAL,
                           **overrides) -> dict:
    payload = create_service_complaint_payload(
        shipper_id=shipper_id, carrier_id=carrier_id, **overrides)
    resp = api_client.create_service_complaint(payload, make_shipper_headers(shipper_id))
    return get_success_data(resp, 201)


def escalate(sc_id: str, directive: str = "Restore service within 72 hours") -> dict:
    """Board escalates an OPEN service complaint; returns the new ESO (201)."""
    resp = api_client.escalate_service_complaint(
        sc_id, escalate_payload(directive=directive), BOARD)
    return get_success_data(resp, 201)


def setup_escalated_service_complaint(carrier_id: str, shipper_id: str = SHIPPER_GAL,
                                      **sc_overrides):
    """Service complaint escalated to an ACTIVE emergency service order."""
    sc = file_service_complaint(carrier_id, shipper_id, **sc_overrides)
    eso = escalate(sc["id"])
    return sc, eso


def get_service_complaint_data(sc_id: str) -> dict:
    return get_success_data(api_client.get_service_complaint(sc_id, BOARD), 200)


def list_carrier_eso_data(carrier_id: str, params=None) -> tuple:
    resp = api_client.list_carrier_esos(carrier_id, BOARD, params=params)
    return validate_paginated(resp)


# --- mergers ------------------------------------------------------------------

def register_merger_pair(acquirer_code="CSXT", target_code="NSOR"):
    """Two carriers usable as acquirer/target of a merger application."""
    acquirer = register_carrier(
        carrier_code=acquirer_code, legal_name="Crescent South Extension Transport",
        carrier_class="I", base_route_miles=2100)
    target = register_carrier(
        carrier_code=target_code, legal_name="Northern & Southern Railway",
        carrier_class="II", base_route_miles=640)
    return acquirer, target


def create_merger(acquiring_carrier_id: str, target_carrier_id: str, **overrides) -> dict:
    """Acquiring carrier files a merger application (201, COMMENT_PERIOD)."""
    payload = create_merger_application_payload(
        acquiring_carrier_id=acquiring_carrier_id,
        target_carrier_id=target_carrier_id, **overrides)
    resp = api_client.create_merger_application(
        payload, make_carrier_operator_headers(acquiring_carrier_id))
    return get_success_data(resp, 201)


def add_service_assurance_plan(merger_id: str, acquirer_id: str, **overrides) -> dict:
    resp = api_client.create_service_assurance_plan(
        merger_id, create_service_assurance_plan_payload(**overrides),
        make_carrier_operator_headers(acquirer_id))
    return get_success_data(resp, 201)


def setup_merger_with_plan(acquirer_id: str, target_id: str,
                           merger_overrides=None, plan_overrides=None):
    merger = create_merger(acquirer_id, target_id, **(merger_overrides or {}))
    plan = add_service_assurance_plan(merger["id"], acquirer_id, **(plan_overrides or {}))
    return merger, plan


def get_merger_data(merger_id: str) -> dict:
    return get_success_data(api_client.get_merger_application(merger_id, BOARD), 200)


def get_plan_data(merger_id: str, plan_id: str) -> dict:
    resp = api_client.list_service_assurance_plans(merger_id, BOARD)
    data, _meta = validate_paginated(resp)
    for plan in data:
        if plan["id"] == plan_id:
            return plan
    raise AssertionError(f"plan {plan_id} not found on merger {merger_id}")


# --- abandonment applications -------------------------------------------------

def file_abandonment(carrier_id: str, **overrides) -> dict:
    payload = create_abandonment_payload(carrier_id=carrier_id, **overrides)
    resp = api_client.create_abandonment_application(
        payload, make_carrier_operator_headers(carrier_id))
    return get_success_data(resp, 201)


def grant_abandonment(ab_id: str, finding: str = "SERVED") -> dict:
    resp = api_client.decide_abandonment(
        ab_id, decide_abandonment_payload("GRANTED", finding), BOARD)
    return get_success_data(resp, 200)


def get_abandonment_data(ab_id: str) -> dict:
    return get_success_data(api_client.get_abandonment_application(ab_id, BOARD), 200)


# --- reciprocal switching petitions -------------------------------------------

def file_petition(shipper_id: str, carrier_id: str, evidence_sc_id: str,
                  **overrides) -> dict:
    payload = create_petition_payload(
        shipper_id=shipper_id, incumbent_carrier_id=carrier_id,
        evidence_service_complaint_id=evidence_sc_id, **overrides)
    resp = api_client.create_petition(payload, make_shipper_headers(shipper_id))
    return get_success_data(resp, 201)


def grant_petition(petition_id: str) -> dict:
    resp = api_client.decide_petition(petition_id, {"outcome": "GRANTED"}, BOARD)
    return get_success_data(resp, 200)


def get_petition_data(carrier_id: str, petition_id: str) -> dict:
    """Petitions are read via the incumbent carrier's nested list view."""
    resp = api_client.list_carrier_petitions(carrier_id, BOARD)
    data, _meta = validate_paginated(resp)
    for petition in data:
        if petition["id"] == petition_id:
            return petition
    raise AssertionError(f"petition {petition_id} not found under carrier {carrier_id}")
