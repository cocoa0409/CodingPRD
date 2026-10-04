"""Composite setup helpers — batch processing, testing, disposition, distribution.

The canonical identity threading (PRD §2.10): batches are manufactured by
operator op-1, tests are recorded by op-1 and verified by analyst qc-1
(four-eyes), and disposition is performed by reviewer qa-1, who is neither
the manufacturer nor a verifier (segregation of duties). Pass different
user ids only when a test deliberately violates those controls.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_batch_payload, create_test_payload, create_deviation_payload,
    create_shipment_payload, create_reading_payload,
)
from .fixtures_core import iso_shift, setup_campaign_in_production
from .test_users import (
    USER_IDS, TEST_USERS, make_manufacturing_operator_headers,
    make_quality_control_analyst_headers, make_quality_assurance_reviewer_headers,
    make_supply_planner_headers,
)

_ADMIN = TEST_USERS["platform_admin_headers"]

DEFAULT_TITER_VALUES = (2.4, 2.6)


# ---------------------------------------------------------------------------
# Batch creation and process advance
# ---------------------------------------------------------------------------

def create_batch_entity(campaign_id: str, lot_number: str = "LOT-0001",
                        operator_user_id: str = USER_IDS["operator"]) -> dict:
    headers = make_manufacturing_operator_headers(operator_user_id)
    return get_success_data(
        api_client.create_batch(campaign_id, create_batch_payload(lot_number=lot_number), headers))


def get_batch_entity(batch_id: str) -> dict:
    return get_success_data(api_client.get_batch(batch_id, _ADMIN))


def advance_batch(batch_id: str, to_status: str,
                  operator_user_id: str = USER_IDS["operator"]) -> dict:
    headers = make_manufacturing_operator_headers(operator_user_id)
    return get_success_data(api_client.advance_batch(batch_id, to_status, headers))


# ---------------------------------------------------------------------------
# In-process tests (OCC: version threaded explicitly or re-read fresh)
# ---------------------------------------------------------------------------

def record_test(batch_id: str, batch_version=None,
                operator_user_id: str = USER_IDS["operator"], **overrides) -> dict:
    """Record a test. batch_version=None re-reads the batch for a fresh OCC version."""
    if batch_version is None:
        batch_version = get_batch_entity(batch_id)["version"]
    payload = create_test_payload(expected_batch_version=batch_version, **overrides)
    headers = make_manufacturing_operator_headers(operator_user_id)
    return get_success_data(api_client.create_test(batch_id, payload, headers))


def verify_test_entity(test_id: str, analyst_user_id: str = USER_IDS["analyst"]) -> dict:
    headers = make_quality_control_analyst_headers(analyst_user_id)
    return get_success_data(api_client.verify_test(test_id, headers))


def record_and_verify_test(batch_id: str, batch_version=None, **overrides):
    """Record then verify (four-eyes: recorder op-1, verifier qc-1).
    Returns (verified_test, new_batch_version)."""
    test = record_test(batch_id, batch_version=batch_version, **overrides)
    verified = verify_test_entity(test["id"])
    return verified, get_batch_entity(batch_id)["version"]


# ---------------------------------------------------------------------------
# Batch lifecycle chains
# ---------------------------------------------------------------------------

def setup_batch_upstream(**chain_kwargs) -> dict:
    """Campaign in PRODUCTION_IN_PROGRESS + batch created (UPSTREAM/IN_TESTING)."""
    env = setup_campaign_in_production(**chain_kwargs)
    env["batch"] = create_batch_entity(env["campaign"]["id"])
    return env


def setup_batch_with_verified_upstream(**chain_kwargs) -> dict:
    """Batch with one VERIFIED UPSTREAM viability test; env['batch'] refreshed."""
    env = setup_batch_upstream(**chain_kwargs)
    test, _version = record_and_verify_test(
        env["batch"]["id"], batch_version=env["batch"]["version"],
        test_type="CELL_VIABILITY", phase="UPSTREAM",
        measured_value=85.0, unit="PCT", spec_min=80.0, spec_max=100.0)
    env["upstream_test"] = test
    env["batch"] = get_batch_entity(env["batch"]["id"])
    return env


def setup_batch_downstream(**chain_kwargs) -> dict:
    """Batch advanced to DOWNSTREAM (upstream evidence complete)."""
    env = setup_batch_with_verified_upstream(**chain_kwargs)
    env["batch"] = advance_batch(env["batch"]["id"], "DOWNSTREAM")
    return env


def setup_batch_process_complete(titer_values=DEFAULT_TITER_VALUES, **chain_kwargs) -> dict:
    """Batch advanced to PROCESS_COMPLETE with VERIFIED DOWNSTREAM TITER tests.

    Default titers 2.4 and 2.6 on a 2000 L train yield final 625000 while the
    provisional figure is 400000. env gains 'titer_tests'; env['batch'] is the
    post-completion batch (with final_yield_units, process_completed_at,
    expiry_utc and quality_status READY_FOR_REVIEW).
    """
    env = setup_batch_downstream(**chain_kwargs)
    version = env["batch"]["version"]
    titer_tests = []
    for value in titer_values:
        test, version = record_and_verify_test(
            env["batch"]["id"], batch_version=version,
            test_type="TITER", phase="DOWNSTREAM",
            measured_value=value, unit="G/L", spec_min=2.0, spec_max=4.0)
        titer_tests.append(test)
    env["titer_tests"] = titer_tests
    env["batch"] = advance_batch(env["batch"]["id"], "PROCESS_COMPLETE")
    return env


def setup_batch_pending_disposition(**chain_kwargs) -> dict:
    """Batch at PROCESS_COMPLETE + submitted for review (PENDING_DISPOSITION)."""
    env = setup_batch_process_complete(**chain_kwargs)
    env["batch"] = submit_batch_for_review(env["batch"]["id"])
    return env


def setup_released_batch(**chain_kwargs) -> dict:
    """Batch fully RELEASED by reviewer qa-1 (satisfies segregation of duties)."""
    env = setup_batch_pending_disposition(**chain_kwargs)
    env["batch"] = disposition_batch(env["batch"]["id"], decision="RELEASED")
    return env


# ---------------------------------------------------------------------------
# Quality review and disposition
# ---------------------------------------------------------------------------

def submit_batch_for_review(batch_id: str, reviewer_user_id: str = USER_IDS["reviewer"]) -> dict:
    headers = make_quality_assurance_reviewer_headers(reviewer_user_id)
    return get_success_data(api_client.submit_batch_for_review(batch_id, headers))


def disposition_batch(batch_id: str, decision: str = "RELEASED",
                      rationale: str = "All specifications met",
                      reviewer_user_id: str = USER_IDS["reviewer"]) -> dict:
    headers = make_quality_assurance_reviewer_headers(reviewer_user_id)
    payload = {"decision": decision, "rationale": rationale}
    return get_success_data(api_client.disposition_batch(batch_id, payload, headers))


# ---------------------------------------------------------------------------
# Deviations
# ---------------------------------------------------------------------------

def create_deviation_entity(batch_id: str, kind: str = "PROCESS", severity: str = "MINOR",
                            description: str = "Deviation under test",
                            headers=None) -> dict:
    """Raise a PROCESS deviation or register a COMPLAINT (OOS is system-created only)."""
    if headers is None:
        headers = make_manufacturing_operator_headers(USER_IDS["operator"])
    payload = create_deviation_payload(kind=kind, severity=severity, description=description)
    return get_success_data(api_client.create_deviation(batch_id, payload, headers))


def deviation_action(deviation_id: str, payload: dict,
                     reviewer_user_id: str = USER_IDS["reviewer"]) -> dict:
    headers = make_quality_assurance_reviewer_headers(reviewer_user_id)
    return get_success_data(api_client.deviation_action(deviation_id, payload, headers))


def close_deviation(deviation_id: str, conclusion: str, capa_summary=None,
                    reviewer_user_id: str = USER_IDS["reviewer"]) -> dict:
    payload = {"action": "CLOSE", "conclusion": conclusion}
    if capa_summary is not None:
        payload["capa_summary"] = capa_summary
    return deviation_action(deviation_id, payload, reviewer_user_id)


def reopen_deviation(deviation_id: str, justification: str = "New information received",
                     reviewer_user_id: str = USER_IDS["reviewer"]) -> dict:
    payload = {"action": "REOPEN", "justification": justification}
    return deviation_action(deviation_id, payload, reviewer_user_id)


# ---------------------------------------------------------------------------
# Shipments, temperature readings, excursions
# ---------------------------------------------------------------------------

def create_shipment_entity(batch_id: str, quantity_units: int = 1000,
                           market_type: str = "COMMERCIAL",
                           destination_region: str = "IE-DUB",
                           planner_user_id: str = USER_IDS["planner"]) -> dict:
    headers = make_supply_planner_headers(planner_user_id)
    payload = create_shipment_payload(destination_region=destination_region,
                                      market_type=market_type, quantity_units=quantity_units)
    return get_success_data(api_client.create_shipment(batch_id, payload, headers))


def shipment_action(shipment_id: str, action: str,
                    planner_user_id: str = USER_IDS["planner"]) -> dict:
    headers = make_supply_planner_headers(planner_user_id)
    return get_success_data(api_client.shipment_action(shipment_id, action, headers))


def create_reading_entity(shipment_id: str, temperature_c: float,
                          recorded_at: str = "2026-10-02T01:00:00Z",
                          planner_user_id: str = USER_IDS["planner"]) -> dict:
    headers = make_supply_planner_headers(planner_user_id)
    payload = create_reading_payload(recorded_at=recorded_at, temperature_c=temperature_c)
    return get_success_data(api_client.create_reading(shipment_id, payload, headers))


def record_readings(shipment_id: str, temperatures, start_utc: str = "2026-10-02T01:00:00Z",
                    step_hours: float = 1) -> list:
    """Record a series of readings one hour apart. Returns the reading dicts."""
    readings = []
    for index, temp in enumerate(temperatures):
        readings.append(create_reading_entity(
            shipment_id, temp, iso_shift(start_utc, hours=index * step_hours)))
    return readings


def evaluate_excursion(shipment_id: str, reviewer_user_id: str = USER_IDS["reviewer_2"]) -> dict:
    headers = make_quality_assurance_reviewer_headers(reviewer_user_id)
    return get_success_data(api_client.evaluate_excursion(shipment_id, headers))


def setup_shipment_in_transit(quantity_units: int = 1000, market_type: str = "COMMERCIAL",
                              **chain_kwargs) -> dict:
    """RELEASED batch + one shipment moved PLANNED -> IN_TRANSIT."""
    env = setup_released_batch(**chain_kwargs)
    env["shipment"] = create_shipment_entity(
        env["batch"]["id"], quantity_units=quantity_units, market_type=market_type)
    env["shipment"] = shipment_action(env["shipment"]["id"], "SHIP")
    return env
