"""Composite setup helpers (PRD §3 workflows).

Every helper builds preconditions from scratch against an empty database via
PRD-declared endpoints; the harness restarts the server before each test.
Setup calls use get_success_data() so a failing precondition surfaces as a
clear "Setup step failed" error naming the endpoint.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_START_UTC,
    CONTRACT_WINDOW_CLOSE,
    CONTRACT_WINDOW_OPEN,
    LAUNCH_INSTANT_UTC,
    MISSION_WINDOW_CLOSE,
    MISSION_WINDOW_OPEN,
)
from .factories import (
    assignment_payload,
    contract_payload,
    customer_license_payload,
    customer_payload,
    delay_payload,
    dispenser_port_payload,
    exclusion_window_payload,
    mission_license_payload,
    mission_payload,
    payload_entry,
    range_slot_payload,
    rebook_payload,
    safety_review_payload,
    verification_payload,
)
from .test_users import TEST_USERS, make_customer_headers, make_engineer_headers, make_safety_headers

ADMIN = TEST_USERS["admin_headers"]
MOPS = TEST_USERS["mission_ops_headers"]
CM = TEST_USERS["contract_manager_headers"]
RO = TEST_USERS["range_officer_headers"]
REG = TEST_USERS["regulator_headers"]


# ---------------------------------------------------------------------------
# Tier 0: atomic creators
# ---------------------------------------------------------------------------

def set_clock(current_utc=CLOCK_START_UTC):
    """PRD §2.4: restate the logical clock (startup default 2026-09-01)."""
    return get_success_data(api_client.set_clock(current_utc, ADMIN))


def create_customer(**overrides) -> dict:
    return get_success_data(api_client.create_customer(customer_payload(**overrides), ADMIN))


def create_mission(**overrides) -> dict:
    return get_success_data(api_client.create_mission(mission_payload(**overrides), MOPS))


def create_port(mission_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_dispenser_port(mission_id, dispenser_port_payload(**overrides), MOPS)
    )


def create_contract(customer_id, payloads, **overrides) -> dict:
    return get_success_data(
        api_client.create_contract(contract_payload(customer_id, payloads, **overrides), CM)
    )


def sign_contract(contract_id, customer_id) -> dict:
    """PRD §3.2: signing belongs to the owning customer (X-User-ID == customer_id)."""
    return get_success_data(
        api_client.sign_contract(contract_id, make_customer_headers(customer_id))
    )


def list_payloads(contract_id) -> list:
    return get_success_data(api_client.list_contract_payloads(contract_id, MOPS))


def create_signed_contract(customer_id, payloads, **overrides):
    """Create + sign. Returns (contract, payloads-in-declaration-order)."""
    contract = create_contract(customer_id, payloads, **overrides)
    contract = sign_contract(contract["id"], customer_id)
    return contract, list_payloads(contract["id"])


def file_customer_license(customer_id, **overrides) -> dict:
    """PRD §3.4: PAYLOAD_OPERATOR filings come from the customer itself."""
    return get_success_data(
        api_client.create_license(
            customer_license_payload(customer_id, **overrides),
            make_customer_headers(customer_id),
        )
    )


def file_mission_license(mission_id, **overrides) -> dict:
    """PRD §3.4: LAUNCH_AUTHORIZATION filings come from MissionOps."""
    return get_success_data(
        api_client.create_license(mission_license_payload(mission_id, **overrides), MOPS)
    )


def transition_license(license_id, to_state) -> dict:
    return get_success_data(api_client.transition_license(license_id, to_state, REG))


def create_granted_customer_license(customer_id, **overrides) -> dict:
    lic = file_customer_license(customer_id, **overrides)
    return transition_license(lic["id"], "GRANTED")


def create_granted_mission_license(mission_id, **overrides) -> dict:
    lic = file_mission_license(mission_id, **overrides)
    return transition_license(lic["id"], "GRANTED")


def mission_version(mission_id) -> int:
    return get_success_data(api_client.get_mission(mission_id, MOPS))["version"]


def get_mission(mission_id) -> dict:
    return get_success_data(api_client.get_mission(mission_id, MOPS))


def get_contract(contract_id, headers=None) -> dict:
    return get_success_data(api_client.get_contract(contract_id, headers or CM))


def create_assignment(mission_id, payload_id, port_id, expected_mission_version=None) -> dict:
    """PRD §2.8: reads the live mission version when the caller does not pin one."""
    if expected_mission_version is None:
        expected_mission_version = mission_version(mission_id)
    return get_success_data(
        api_client.create_assignment(
            assignment_payload(mission_id, payload_id, port_id, expected_mission_version),
            MOPS,
        )
    )


def get_assignment(assignment_id) -> dict:
    return get_success_data(api_client.get_assignment(assignment_id, MOPS))


def verify_assignment(assignment_id, engineer_id="eng-1", outcome="PASSED"):
    """Record PASSED (default) MECHANICAL + ELECTRICAL verifications."""
    headers = make_engineer_headers(engineer_id)
    v_mech = get_success_data(
        api_client.create_verification(
            assignment_id,
            verification_payload(check_type="MECHANICAL", outcome=outcome),
            headers,
        )
    )
    v_elec = get_success_data(
        api_client.create_verification(
            assignment_id,
            verification_payload(check_type="ELECTRICAL", outcome=outcome),
            headers,
        )
    )
    return v_mech, v_elec


def review_assignment(assignment_id, decision="APPROVE", officer_id="so-1", rationale="interfaces nominal") -> dict:
    return get_success_data(
        api_client.create_safety_review(
            assignment_id,
            safety_review_payload(decision=decision, rationale=rationale),
            make_safety_headers(officer_id),
        )
    )


def confirm_assignment(assignment_id) -> dict:
    return get_success_data(api_client.confirm_assignment(assignment_id, MOPS))


def lock_manifest(mission_id) -> dict:
    return get_success_data(api_client.lock_manifest(mission_id, MOPS))


def create_range_slot(mission_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_range_slot(range_slot_payload(mission_id, **overrides), RO)
    )


def reserve_slot(slot_id) -> dict:
    return get_success_data(api_client.reserve_range_slot(slot_id, RO))


def confirm_slot(slot_id) -> dict:
    return get_success_data(api_client.confirm_range_slot(slot_id, RO))


def publish_exclusion_window(**overrides) -> dict:
    return get_success_data(
        api_client.create_exclusion_window(exclusion_window_payload(**overrides), RO)
    )


def delay_mission(mission_id, **overrides) -> dict:
    return get_success_data(api_client.delay_mission(mission_id, delay_payload(**overrides), MOPS))


def scrub_mission(mission_id, reason_code="VEHICLE_GROUNDED") -> dict:
    return get_success_data(api_client.scrub_mission(mission_id, reason_code, MOPS))


def rebook_contract(contract_id, customer_id, to_mission_id, expected_contract_version) -> dict:
    return get_success_data(
        api_client.rebook_contract(
            contract_id,
            rebook_payload(to_mission_id, expected_contract_version),
            make_customer_headers(customer_id),
        )
    )


def launch_mission(mission_id) -> dict:
    return get_success_data(api_client.launch_mission(mission_id, MOPS))


def list_separation_events(mission_id) -> list:
    return get_success_data(
        api_client.list_separation_events(MOPS, params={"mission_id": mission_id})
    )


# ---------------------------------------------------------------------------
# Tier 2/3 composites: manifest scenarios
# ---------------------------------------------------------------------------

def setup_provisional_assignments(
    payload_specs=None,
    port_specs=None,
    mission_overrides=None,
    contract_overrides=None,
    with_customer_license=True,
):
    """Customer + mission + ports + signed contract + PROVISIONAL assignments.

    payload_specs: list of payload_entry override dicts (default: one 100 kg
        RING_15 SSO payload).
    port_specs: list of dispenser_port_payload override dicts, paired 1:1 with
        payload_specs by index (default: DSP-A stack 4, RING_15+RING_24).
    Returns a context dict:
        customer, mission, ports, contract, payloads, assignments,
        customer_license (or None)
    """
    payload_specs = payload_specs if payload_specs is not None else [{}]
    port_specs = port_specs if port_specs is not None else [{}]
    assert len(payload_specs) == len(port_specs), "payloads and ports pair 1:1"

    set_clock()
    customer = create_customer()
    mission = create_mission(**(mission_overrides or {}))
    ports = [create_port(mission["id"], **spec) for spec in port_specs]
    entries = [payload_entry(**spec) for spec in payload_specs]
    contract, payloads = create_signed_contract(
        customer["id"], entries, **(contract_overrides or {})
    )
    customer_license = (
        create_granted_customer_license(customer["id"]) if with_customer_license else None
    )
    assignments = [
        create_assignment(mission["id"], payloads[i]["id"], ports[i]["id"])
        for i in range(len(payloads))
    ]
    return {
        "customer": customer,
        "mission": mission,
        "ports": ports,
        "contract": contract,
        "payloads": payloads,
        "assignments": assignments,
        "customer_license": customer_license,
    }


def setup_confirmed_mission(**kwargs):
    """PROVISIONAL setup + every assignment verified, safety-approved, CONFIRMED."""
    ctx = setup_provisional_assignments(**kwargs)
    for assignment in ctx["assignments"]:
        verify_assignment(assignment["id"])
        review_assignment(assignment["id"])
        ctx_assignment = confirm_assignment(assignment["id"])
        assignment.update(ctx_assignment)
    return ctx


def setup_locked_mission(**kwargs):
    """CONFIRMED setup + manifest lock (assignments flip to INTEGRATED)."""
    ctx = setup_confirmed_mission(**kwargs)
    ctx["mission"] = lock_manifest(ctx["mission"]["id"])
    for i, assignment in enumerate(ctx["assignments"]):
        ctx["assignments"][i] = get_assignment(assignment["id"])
    return ctx


def setup_range_scheduled_mission(slot_overrides=None, **kwargs):
    """LOCKED setup + GRANTED launch license + slot reserved & confirmed.

    Mission ends in RANGE_SCHEDULED. Adds keys: mission_license, slot.
    """
    ctx = setup_locked_mission(**kwargs)
    ctx["mission_license"] = create_granted_mission_license(ctx["mission"]["id"])
    slot = create_range_slot(ctx["mission"]["id"], **(slot_overrides or {}))
    reserve_slot(slot["id"])
    ctx["slot"] = confirm_slot(slot["id"])
    ctx["mission"] = get_mission(ctx["mission"]["id"])
    return ctx


def setup_launched_mission(launch_instant=LAUNCH_INSTANT_UTC, **kwargs):
    """RANGE_SCHEDULED setup + clock into the window + launch.

    Adds key: separation_events (list, sequence_index ASC).
    """
    ctx = setup_range_scheduled_mission(**kwargs)
    set_clock(launch_instant)
    ctx["mission"] = launch_mission(ctx["mission"]["id"])
    ctx["separation_events"] = list_separation_events(ctx["mission"]["id"])
    return ctx
