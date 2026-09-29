"""World builders and pytest fixtures.

The harness restarts the server before every individual test, so the database is
empty at the top of each one and every precondition below is built from scratch
through PRD-declared endpoints only. Nothing here reaches behind the HTTP
surface.

Setup calls go through `get_success_data`, the lenient validator, so that a
broken precondition reports the API's own error_id instead of a bare status
mismatch.
"""

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import get_success_data

from . import factories as F
from .api_client import StorageApiClient
from .constants import (
    AGENCY_ACCEPTED,
    EMERGENCY_RESPONDING,
    MIT_OUTCOME_FAIL,
    MIT_OUTCOME_PASS,
    SERVICE_CLASS_FIRM,
)
from .test_users import (
    COMPLIANCE_OFFICER,
    COMPLIANCE_OFFICER_B,
    FIELD_OPERATOR,
    INTEGRITY_ENGINEER,
    INTEGRITY_ENGINEER_B,
    SCHEDULING_COORDINATOR,
    make_shipper_headers,
)


# ─── Tier 1: the client and the logical clock ──────────────────────────────

@pytest.fixture
def api() -> StorageApiClient:
    """One client per test, pointed at the harness-managed server."""
    return StorageApiClient()


def set_clock(api: StorageApiClient, to_iso8601: str, headers: Dict[str, str] = None) -> str:
    """Jump the logical clock and return the reported `current_utc`."""
    response = api.set_clock(to_iso8601, headers or FIELD_OPERATOR)
    return get_success_data(response)["current_utc"]


# ─── Tier 2: single-entity builders ────────────────────────────────────────

def create_field(api: StorageApiClient, payload: Optional[Dict] = None, **overrides) -> Dict[str, Any]:
    body = payload if payload is not None else F.storage_field_payload(**overrides)
    return get_success_data(api.create_storage_field(body, FIELD_OPERATOR))


def create_std_field(api: StorageApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_storage_field(F.f_std_field_payload(**overrides), FIELD_OPERATOR)
    )


def create_bound_field(api: StorageApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_storage_field(F.f_bound_field_payload(**overrides), FIELD_OPERATOR)
    )


def create_well(api: StorageApiClient, field_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_well(F.well_payload(field_id, **overrides), FIELD_OPERATOR)
    )


def create_shipper(api: StorageApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_shipper(F.shipper_payload(**overrides), SCHEDULING_COORDINATOR)
    )


def create_second_shipper(api: StorageApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_shipper(F.second_shipper_payload(**overrides), SCHEDULING_COORDINATOR)
    )


def create_contract(
    api: StorageApiClient, shipper_id: str, field_id: str, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_contract(
            F.contract_payload(shipper_id, field_id, **overrides), SCHEDULING_COORDINATOR
        )
    )


def activate_contract(api: StorageApiClient, contract_id: str) -> Dict[str, Any]:
    return get_success_data(api.activate_contract(contract_id, SCHEDULING_COORDINATOR))


def create_active_contract(
    api: StorageApiClient, shipper_id: str, field_id: str, **overrides
) -> Dict[str, Any]:
    contract = create_contract(api, shipper_id, field_id, **overrides)
    return activate_contract(api, contract["id"])


def create_unit(api: StorageApiClient, field_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_compressor_unit(F.compressor_unit_payload(field_id, **overrides), FIELD_OPERATOR)
    )


def book_run(api: StorageApiClient, unit_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_compressor_run(F.compressor_run_payload(unit_id, **overrides), FIELD_OPERATOR)
    )


def complete_run(api: StorageApiClient, run_id: str) -> Dict[str, Any]:
    return get_success_data(api.complete_compressor_run(run_id, FIELD_OPERATOR))


def schedule_mit(api: StorageApiClient, well_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_mit(F.mit_payload(well_id, **overrides), INTEGRITY_ENGINEER)
    )


def record_mit(
    api: StorageApiClient,
    mit_id: str,
    outcome: str,
    result_pressure_psig: Optional[int] = 2000,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.record_mit_result(
            mit_id,
            F.mit_result_payload(outcome, result_pressure_psig),
            headers or INTEGRITY_ENGINEER,
        )
    )


def open_emergency(api: StorageApiClient, field_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_emergency_event(F.emergency_event_payload(field_id, **overrides), FIELD_OPERATOR)
    )


def advance_emergency(
    api: StorageApiClient,
    event_id: str,
    to_status: str,
    responder_notes: Optional[str] = None,
    evacuation_radius_m: Optional[int] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.advance_emergency_event(
            event_id,
            F.advance_payload(to_status, responder_notes, evacuation_radius_m),
            FIELD_OPERATOR,
        )
    )


def create_report(
    api: StorageApiClient, field_id: str, measured_inventory_dth: float, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_regulatory_report(
            F.regulatory_report_payload(field_id, measured_inventory_dth, **overrides),
            COMPLIANCE_OFFICER,
        )
    )


def submit_report(api: StorageApiClient, report_id: str) -> Dict[str, Any]:
    """Submission requires a second officer, so the B identity files it."""
    return get_success_data(api.submit_regulatory_report(report_id, COMPLIANCE_OFFICER_B))


def accept_report(api: StorageApiClient, report_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.record_agency_response(
            report_id, F.agency_response_payload(AGENCY_ACCEPTED), COMPLIANCE_OFFICER
        )
    )


# ─── Tier 3: readers ───────────────────────────────────────────────────────

def read_field(api: StorageApiClient, field_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.get_storage_field(field_id, headers or FIELD_OPERATOR))


def read_well(api: StorageApiClient, well_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.get_well(well_id, headers or FIELD_OPERATOR))


def read_contract(api: StorageApiClient, contract_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.get_contract(contract_id, headers or SCHEDULING_COORDINATOR))


def read_shipper(api: StorageApiClient, shipper_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.get_shipper(shipper_id, headers or SCHEDULING_COORDINATOR))


def read_nomination(api: StorageApiClient, nomination_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.get_nomination(nomination_id, headers or SCHEDULING_COORDINATOR))


def read_ticket(api: StorageApiClient, ticket_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.get_ticket(ticket_id, headers or FIELD_OPERATOR))


def read_unit(api: StorageApiClient, unit_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.get_compressor_unit(unit_id, headers or FIELD_OPERATOR))


def read_program(api: StorageApiClient, program_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.get_remediation_program(program_id, headers or INTEGRITY_ENGINEER))


def read_event(api: StorageApiClient, event_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.get_emergency_event(event_id, headers or FIELD_OPERATOR))


def field_version(api: StorageApiClient, field_id: str) -> int:
    return read_field(api, field_id)["version"]


def contract_version(api: StorageApiClient, contract_id: str) -> int:
    return read_contract(api, contract_id)["version"]


def ledger_entries(
    api: StorageApiClient, contract_id: str, **params
) -> List[Dict[str, Any]]:
    query = {"limit": 100}
    query.update(params)
    response = api.list_ledger_entries(contract_id, SCHEDULING_COORDINATOR, query)
    return get_success_data(response)


def programs_on_well(api: StorageApiClient, well_id: str) -> List[Dict[str, Any]]:
    response = api.list_remediation_programs(INTEGRITY_ENGINEER, {"well_id": well_id, "limit": 100})
    return get_success_data(response)


def only_program_on_well(api: StorageApiClient, well_id: str) -> Dict[str, Any]:
    rows = programs_on_well(api, well_id)
    assert len(rows) == 1, f"Expected exactly one remediation program, got {len(rows)}"
    return rows[0]


# ─── Tier 4: nomination and ticket chains ──────────────────────────────────

def file_nomination(
    api: StorageApiClient,
    contract_id: str,
    shipper_id: str,
    expected_contract_version: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    """File a nomination, reading the contract's current version unless the
    caller wants to pin a specific -- possibly stale -- token."""
    version = (
        expected_contract_version
        if expected_contract_version is not None
        else contract_version(api, contract_id)
    )
    payload = F.nomination_payload(contract_id, version, **overrides)
    return get_success_data(api.create_nomination(payload, make_shipper_headers(shipper_id)))


def submit_nomination(
    api: StorageApiClient,
    nomination_id: str,
    shipper_id: str,
    nominated_volume_dth: Optional[int] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.submit_nomination(
            nomination_id,
            make_shipper_headers(shipper_id),
            F.submit_nomination_payload(nominated_volume_dth),
        )
    )


def confirm_nomination(api: StorageApiClient, nomination_id: str) -> Dict[str, Any]:
    return get_success_data(api.confirm_nomination(nomination_id, SCHEDULING_COORDINATOR))


def file_and_submit_nomination(
    api: StorageApiClient, contract_id: str, shipper_id: str, **overrides
) -> Dict[str, Any]:
    nomination = file_nomination(api, contract_id, shipper_id, **overrides)
    return submit_nomination(api, nomination["id"], shipper_id)


def confirmed_nomination(
    api: StorageApiClient, contract_id: str, shipper_id: str, **overrides
) -> Dict[str, Any]:
    """File, submit and run the allocation waterfall in one step."""
    nomination = file_and_submit_nomination(api, contract_id, shipper_id, **overrides)
    return confirm_nomination(api, nomination["id"])


def open_ticket(
    api: StorageApiClient, nomination_id: str, well_id: str, actual_volume_dth: int
) -> Dict[str, Any]:
    return get_success_data(
        api.create_ticket(
            F.ticket_payload(nomination_id, well_id, actual_volume_dth), FIELD_OPERATOR
        )
    )


def confirm_ticket(
    api: StorageApiClient,
    ticket_id: str,
    field_id: str,
    expected_storage_field_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Confirm a metered movement, reading the reservoir's current version
    unless the caller wants to pin a specific token."""
    version = (
        expected_storage_field_version
        if expected_storage_field_version is not None
        else field_version(api, field_id)
    )
    return get_success_data(
        api.confirm_ticket(ticket_id, F.ticket_confirm_payload(version), FIELD_OPERATOR)
    )


def reverse_ticket(
    api: StorageApiClient, ticket_id: str, reversal_reason: str = "Metering error found on the chart"
) -> Dict[str, Any]:
    return get_success_data(
        api.reverse_ticket(ticket_id, F.ticket_reversal_payload(reversal_reason), FIELD_OPERATOR)
    )


def moved_gas(
    api: StorageApiClient,
    contract_id: str,
    shipper_id: str,
    field_id: str,
    well_id: str,
    actual_volume_dth: int,
    **nomination_overrides,
) -> SimpleNamespace:
    """The full commercial-to-physical chain: file, submit, confirm, meter and
    confirm one movement. Returns the nomination and the confirmed ticket."""
    nomination = confirmed_nomination(api, contract_id, shipper_id, **nomination_overrides)
    ticket = open_ticket(api, nomination["id"], well_id, actual_volume_dth)
    confirmed = confirm_ticket(api, ticket["id"], field_id)
    return SimpleNamespace(nomination=nomination, ticket=confirmed)


# ─── Tier 5: composite worlds ──────────────────────────────────────────────

def build_world(
    api: StorageApiClient,
    field_payload: Optional[Dict] = None,
    *,
    well_names: Optional[List[str]] = None,
    well_rate_dth_per_day: int = 600000,
    service_class: str = SERVICE_CLASS_FIRM,
    penalty_threshold_usd: float = 500000.00,
    contract_overrides: Optional[Dict] = None,
    activate: bool = True,
) -> SimpleNamespace:
    """Reservoir + wellbores + shipper + one storage contract.

    The wellbores are registered before the contract so the reservoir has left
    `FROZEN` by the time activation runs.
    """
    field = create_field(api, field_payload)
    wells = [
        create_well(
            api,
            field["id"],
            well_name=name,
            rated_rate_dth_per_day=well_rate_dth_per_day,
        )
        for name in (well_names or ["MINI-1"])
    ]
    shipper = create_shipper(api, penalty_threshold_usd=penalty_threshold_usd)
    overrides = {"service_class": service_class}
    overrides.update(contract_overrides or {})
    contract = create_contract(api, shipper["id"], field["id"], **overrides)
    if activate:
        contract = activate_contract(api, contract["id"])
    return SimpleNamespace(
        field=field,
        field_id=field["id"],
        wells=wells,
        well=wells[0] if wells else None,
        well_id=wells[0]["id"] if wells else None,
        shipper=shipper,
        shipper_id=shipper["id"],
        shipper_headers=make_shipper_headers(shipper["id"]),
        contract=contract,
        contract_id=contract["id"],
    )


def build_mini_world(api: StorageApiClient, **kwargs) -> SimpleNamespace:
    """F_MINI: 500,000 working gas ceiling opening at 250,000, so inventory sits
    at 50.00% and the two-point curve yields 150,000 each way."""
    return build_world(api, F.storage_field_payload(), **kwargs)


def build_std_world(api: StorageApiClient, **kwargs) -> SimpleNamespace:
    """F_STD: 8,000,000 working gas ceiling opening at 3,000,000 -> 37.50%."""
    return build_world(api, F.f_std_field_payload(), **kwargs)


def build_bound_world(api: StorageApiClient, **kwargs) -> SimpleNamespace:
    """F_BOUND: only 100,000 of working gas above a 900,000 cushion, opening
    empty, so both the cushion floor and the working-gas ceiling are close."""
    return build_world(api, F.f_bound_field_payload(), **kwargs)


def add_sibling_contract(
    api: StorageApiClient,
    world: SimpleNamespace,
    contract_code: str = "CN-2",
    *,
    activate: bool = True,
    **overrides,
) -> Dict[str, Any]:
    """A second contract for the same shipper on the same reservoir."""
    contract = create_contract(
        api, world.shipper_id, world.field_id, contract_code=contract_code, **overrides
    )
    if activate:
        contract = activate_contract(api, contract["id"])
    return contract


# ─── Tier 5: cascades that only the server can produce ─────────────────────

def fail_mit_on_well(
    api: StorageApiClient,
    well_id: str,
    *,
    scheduled_start_at: str = "2026-08-02T00:00:00Z",
    scheduled_end_at: str = "2026-08-02T06:00:00Z",
    record_at: str = "2026-08-02T06:00:00Z",
    result_pressure_psig: int = 2900,
    headers: Optional[Dict[str, str]] = None,
) -> SimpleNamespace:
    """Book a test, let its window elapse and record a FAIL, which is the only
    way a remediation program comes into existence."""
    test = schedule_mit(
        api, well_id, scheduled_start_at=scheduled_start_at, scheduled_end_at=scheduled_end_at
    )
    set_clock(api, record_at)
    recorded = record_mit(api, test["id"], MIT_OUTCOME_FAIL, result_pressure_psig, headers)
    program = only_program_on_well(api, well_id)
    return SimpleNamespace(test=recorded, program=program)


def pass_mit_on_well(
    api: StorageApiClient,
    well_id: str,
    *,
    scheduled_start_at: str = "2026-08-02T00:00:00Z",
    scheduled_end_at: str = "2026-08-02T06:00:00Z",
    record_at: str = "2026-08-02T06:00:00Z",
    result_pressure_psig: int = 2000,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    test = schedule_mit(
        api, well_id, scheduled_start_at=scheduled_start_at, scheduled_end_at=scheduled_end_at
    )
    set_clock(api, record_at)
    return record_mit(api, test["id"], MIT_OUTCOME_PASS, result_pressure_psig, headers)


def remediate_well(api: StorageApiClient, program_id: str, notes: str = "Casing patch verified") -> Dict[str, Any]:
    """Close a remediation program as an independent engineer -- the B identity,
    because the A identity recorded the failing result."""
    return get_success_data(
        api.complete_remediation_program(
            program_id, F.remediation_completion_payload(notes), INTEGRITY_ENGINEER_B
        )
    )


def freeze_field_by_emergency(api: StorageApiClient, field_id: str, **overrides) -> Dict[str, Any]:
    """Open an event and advance it to `RESPONDING`, which is the point at which
    posture is forced to FROZEN regardless of the reservoir's other inputs."""
    event = open_emergency(api, field_id, **overrides)
    return advance_emergency(
        api, event["id"], EMERGENCY_RESPONDING, responder_notes="Crew dispatched"
    )


def lock_gas_days_by_report(
    api: StorageApiClient, field_id: str, measured_inventory_dth: float, **overrides
) -> Dict[str, Any]:
    """Prepare and submit a report so its covered gas days stand locked."""
    report = create_report(api, field_id, measured_inventory_dth, **overrides)
    return submit_report(api, report["id"])


# ─── Pytest fixtures over the composites ───────────────────────────────────

@pytest.fixture
def mini_world(api: StorageApiClient) -> SimpleNamespace:
    return build_mini_world(api)


@pytest.fixture
def std_world(api: StorageApiClient) -> SimpleNamespace:
    return build_std_world(api)


@pytest.fixture
def bound_world(api: StorageApiClient) -> SimpleNamespace:
    return build_bound_world(api)


@pytest.fixture
def bare_field(api: StorageApiClient) -> Dict[str, Any]:
    """A reservoir with no wellbores at all."""
    return create_field(api)
