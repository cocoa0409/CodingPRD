"""Composite setup builders.

Every builder drives the public API only - there is no direct database access
anywhere in this suite.  Builders use ``get_success_data`` so a setup step
the PRD allows to answer 200 or 201 does not have to be pinned at every call
site.

The builders are deliberately phased: ``active_contract`` leaves the contract
``ACTIVE`` with four service lines and one season; ``bookable_inventory``
adds a room class, a registered study and an ``APPROVED`` filing and leaves
the logical clock wherever the caller asked (the lottery window opens at
2026-12-01T00:00:00Z by default).  Nothing a builder does at its last step
invalidates a precondition an earlier step established, so they compose.
"""

import pytest

from .api_client import ApiClient
from .assertions import get_success_data
from . import constants as C
from . import factories as f
from .test_users import (
    ACCOUNTANT,
    ACCOUNTANT_2,
    AUDITOR,
    HARNESS,
    HR_MANAGER,
    INSPECTOR,
    FRONT_DESK,
    MAINTENANCE_CHIEF,
    OFFICER,
    OPS_MANAGER,
    RATE_ANALYST,
    RATE_ANALYST_2,
    RATE_MANAGER,
)

# --- pytest fixtures --------------------------------------------------------


@pytest.fixture
def client():
    """A client bound to the service under test."""
    return ApiClient()


@pytest.fixture
def api(client):
    """Alias kept so a test can read either name."""
    return client


# --- Logical clock -----------------------------------------------------------


def set_clock(client, current_utc, headers=HARNESS):
    response = client.set_clock(current_utc, headers=headers)
    assert response.status_code in (200, 201), (
        "setting the logical clock to {0} failed with {1}: {2}".format(
            current_utc, response.status_code, response.text
        )
    )
    return current_utc


def reset_clock(client):
    """Return the logical clock to its documented startup instant."""
    return set_clock(client, C.CLOCK_INITIAL_INSTANT)


# --- Tier 1: contracts, lines, seasons ---------------------------------------


def create_contract(client, **overrides):
    """Create a contract in DRAFT and return its body."""
    response = client.create_contract(f.contract_payload(**overrides), headers=OFFICER)
    data = get_success_data(response)
    assert isinstance(data, dict) and data.get("id"), (
        "contract creation failed: {0}".format(response.text)
    )
    return data


def add_service_lines(client, contract_id, headers=OFFICER):
    """Create the four service lines the contract form requires.

    Returns a dict mapping line_type -> line body.
    """
    lines = {}
    for line_type in C.ALL_LINE_TYPES:
        response = client.create_service_line(
            contract_id, f.service_line_payload(line_type), headers=headers
        )
        lines[line_type] = get_success_data(response)
    return lines


def add_season(client, contract_id, **overrides):
    response = client.create_season(
        contract_id, f.season_payload(**overrides), headers=OPS_MANAGER
    )
    data = get_success_data(response)
    assert data.get("id"), "season creation failed: {0}".format(response.text)
    return data


def draft_contract_with_baseline(client, **contract_overrides):
    """A DRAFT contract with one season and all four service lines.

    Returns (contract, season, lines_by_type).
    """
    contract = create_contract(client, **contract_overrides)
    lines = add_service_lines(client, contract["id"])
    season = add_season(client, contract["id"])
    return contract, season, lines


def activate_contract(client, contract_id, headers=OPS_MANAGER):
    response = client.activate_contract(contract_id, headers=headers)
    data = get_success_data(response)
    assert data.get("status") == C.CONTRACT_ACTIVE, (
        "activation failed: {0}".format(response.text)
    )
    return data


def active_contract(client, **contract_overrides):
    """An ACTIVE contract with one season and four service lines.

    Returns (contract_after_activation, season, lines_by_type).
    """
    contract, season, lines = draft_contract_with_baseline(
        client, **contract_overrides
    )
    contract = activate_contract(client, contract["id"])
    return contract, season, lines


def read_contract(client, contract_id, headers=OFFICER):
    response = client.get_contract(contract_id, headers=headers)
    return get_success_data(response)


def contract_version(client, contract_id, headers=OFFICER):
    return read_contract(client, contract_id, headers=headers)["version"]


# --- Tier 2: rates -------------------------------------------------------------


def add_room_class(client, contract_id, **overrides):
    response = client.create_room_class(
        contract_id, f.room_class_payload(**overrides), headers=OPS_MANAGER
    )
    data = get_success_data(response)
    assert data.get("id"), "room class creation failed: {0}".format(response.text)
    return data


def add_study(client, contract_id, headers=RATE_ANALYST, **overrides):
    response = client.create_study(
        contract_id, f.study_payload(**overrides), headers=headers
    )
    data = get_success_data(response)
    assert data.get("id"), "study registration failed: {0}".format(response.text)
    return data


def submit_filing(client, contract_id, season_id, room_class_id, study_id,
                  expected_version=None, submitter=RATE_MANAGER, **overrides):
    """Submit a rate filing; refreshes the expected version when not given."""
    if expected_version is None:
        expected_version = contract_version(client, contract_id, headers=submitter)
    response = client.create_filing(
        contract_id,
        f.filing_payload(
            season_id, room_class_id, study_id, expected_version, **overrides
        ),
        headers=submitter,
    )
    data = get_success_data(response)
    assert data.get("id"), "filing submission failed: {0}".format(response.text)
    return data


def approve_filing(client, contract_id, filing_id, approver=RATE_ANALYST):
    """Move a SUBMITTED filing through review to APPROVED."""
    response = client.start_review_filing(contract_id, filing_id, headers=approver)
    reviewed = get_success_data(response)
    assert reviewed.get("status") == C.FILING_UNDER_REVIEW, (
        "start-review failed: {0}".format(response.text)
    )
    response = client.approve_filing(contract_id, filing_id, headers=approver)
    approved = get_success_data(response)
    assert approved.get("status") == C.FILING_APPROVED, (
        "approval failed: {0}".format(response.text)
    )
    return approved


def bookable_inventory(client, room_class_overrides=None, filing_overrides=None,
                       study_overrides=None, clock="2026-12-01T01:00:00Z",
                       **contract_overrides):
    """An ACTIVE contract with one season, one room class, and an APPROVED
    filing (SOLO 19000 / DOUBLE 23000 / FAMILY 26000 against a 25000-mean
    study whose cap is 26250).

    Leaves the logical clock one hour inside the lottery window so a
    reservation created immediately afterwards queues as REQUESTED.

    Returns a dict with keys: contract, season, lines, room_class, study,
    filing, version (the current contract version).
    """
    reset_clock(client)
    contract, season, lines = active_contract(client, **contract_overrides)
    room_class = add_room_class(
        client, contract["id"], **(room_class_overrides or {})
    )
    study = add_study(client, contract["id"], **(study_overrides or {}))
    filing = submit_filing(
        client, contract["id"], season["id"], room_class["id"], study["id"],
        **(filing_overrides or {}),
    )
    filing = approve_filing(client, contract["id"], filing["id"])
    if clock is not None:
        set_clock(client, clock)
    version = contract_version(client, contract["id"])
    return {
        "contract": contract,
        "season": season,
        "lines": lines,
        "room_class": room_class,
        "study": study,
        "filing": filing,
        "version": version,
    }


def book_reservation(client, contract_id, season_id, room_class_id, expected_version,
                     guest_ref=None, **overrides):
    if guest_ref is None:
        guest_ref = "guest-{0:05d}".format(f.next_sequence())
    response = client.create_reservation(
        contract_id,
        f.reservation_payload(
            season_id, room_class_id, expected_version, guest_ref=guest_ref,
            **overrides
        ),
        headers=FRONT_DESK,
    )
    data = get_success_data(response)
    assert data.get("id"), "reservation creation failed: {0}".format(response.text)
    return data


# --- Tier 3: receipts reports / fee statements ---------------------------------


def create_report(client, contract_id, service_line_id, expected_version=None,
                  creator=ACCOUNTANT, **overrides):
    if expected_version is None:
        expected_version = contract_version(client, contract_id, headers=creator)
    response = client.create_receipts_report(
        contract_id,
        f.receipts_report_payload(service_line_id, expected_version, **overrides),
        headers=creator,
    )
    data = get_success_data(response)
    assert data.get("id"), "report creation failed: {0}".format(response.text)
    return data


def submit_report(client, contract_id, report_id, submitter=ACCOUNTANT, **payload):
    response = client.submit_report(contract_id, report_id, payload=payload,
                                    headers=submitter)
    data = get_success_data(response)
    assert data.get("status") == C.REPORT_SUBMITTED, (
        "report submission failed: {0}".format(response.text)
    )
    return data


def accept_report(client, contract_id, report_id, acceptor=AUDITOR):
    response = client.accept_report(contract_id, report_id, headers=acceptor)
    data = get_success_data(response)
    assert data.get("status") == C.REPORT_ACCEPTED, (
        "report acceptance failed: {0}".format(response.text)
    )
    return data


def accepted_report(client, contract_id, service_line_id, creator=ACCOUNTANT,
                    acceptor=AUDITOR, **overrides):
    """Create, submit and accept a receipts report; returns the report body."""
    report = create_report(
        client, contract_id, service_line_id, creator=creator, **overrides
    )
    submit_report(client, contract_id, report["id"], submitter=creator)
    return accept_report(client, contract_id, report["id"], acceptor=acceptor)


def issue_statement(client, contract_id, period_month="2027-07", issuer=ACCOUNTANT):
    response = client.create_fee_statement(
        contract_id, f.fee_statement_payload(period_month), headers=issuer
    )
    data = get_success_data(response)
    assert data.get("id"), "statement issuance failed: {0}".format(response.text)
    return data


# --- Tier 4: capital projects ----------------------------------------------------


def create_project(client, contract_id, creator=MAINTENANCE_CHIEF, **overrides):
    response = client.create_capital_project(
        contract_id, f.capital_project_payload(**overrides), headers=creator
    )
    data = get_success_data(response)
    assert data.get("id"), "project creation failed: {0}".format(response.text)
    return data


def authorize_project(client, contract_id, project_id, headers=OFFICER):
    response = client.authorize_project(contract_id, project_id, headers=headers)
    data = get_success_data(response)
    assert data.get("status") == C.PROJECT_AUTHORIZED, (
        "project authorization failed: {0}".format(response.text)
    )
    return data


def complete_project(client, contract_id, project_id, actual_cost_cents,
                     completer=MAINTENANCE_CHIEF, **overrides):
    payload = {"actual_cost_cents": actual_cost_cents}
    payload.update(overrides)
    response = client.complete_project(contract_id, project_id, payload,
                                       headers=completer)
    data = get_success_data(response)
    assert data.get("status") == C.PROJECT_COMPLETED, (
        "project completion failed: {0}".format(response.text)
    )
    return data


def approve_project(client, contract_id, project_id, approver=OFFICER):
    response = client.approve_project(contract_id, project_id, headers=approver)
    data = get_success_data(response)
    assert data.get("status") == C.PROJECT_APPROVED, (
        "project approval failed: {0}".format(response.text)
    )
    return data


def approved_project(client, contract_id, actual_cost_cents=None,
                     in_service_month_offset=None, **overrides):
    """Walk a project through PROPOSED -> AUTHORIZED -> COMPLETED -> APPROVED."""
    project = create_project(client, contract_id, **overrides)
    authorize_project(client, contract_id, project["id"])
    if actual_cost_cents is None:
        actual_cost_cents = project["authorized_cost_cents"]
    complete_overrides = {}
    if in_service_month_offset is not None:
        complete_overrides["in_service_month_offset"] = in_service_month_offset
    complete_project(client, contract_id, project["id"], actual_cost_cents,
                     **complete_overrides)
    return approve_project(client, contract_id, project["id"])


# --- Tier 5: housing, hires, vouchers --------------------------------------------


def add_housing_unit(client, contract_id, **overrides):
    response = client.create_housing_unit(
        contract_id, f.housing_unit_payload(**overrides), headers=HR_MANAGER
    )
    data = get_success_data(response)
    assert data.get("id"), "housing unit creation failed: {0}".format(response.text)
    return data


def hire_employee(client, contract_id, season_id, service_line_id, housing_unit_id,
                  **overrides):
    response = client.create_hire(
        contract_id,
        f.hire_payload(season_id, service_line_id, housing_unit_id, **overrides),
        headers=HR_MANAGER,
    )
    data = get_success_data(response)
    assert data.get("id"), "hire creation failed: {0}".format(response.text)
    return data


def housing_scenario(client, bed_count=1, needs_transport=False, **contract_overrides):
    """An ACTIVE contract with one season, four lines, and one housing unit.

    Returns a dict: contract, season, lines, unit.
    """
    reset_clock(client)
    contract, season, lines = active_contract(client, **contract_overrides)
    unit = add_housing_unit(client, contract["id"], bed_count=bed_count)
    return {
        "contract": contract,
        "season": season,
        "lines": lines,
        "unit": unit,
    }


def vouchers_for_hire(client, contract_id, hire_id, headers=HR_MANAGER):
    """List vouchers for a hire and return the data list."""
    response = client.list_vouchers(
        contract_id, headers=headers, params={"hire_id": hire_id}
    )
    data = get_success_data(response)
    if isinstance(data, dict) and "data" in data:
        data = data["data"]
    if isinstance(data, dict) and "items" in data:
        data = data["items"]
    return data


def read_hire(client, contract_id, hire_id, headers=HR_MANAGER):
    return get_success_data(client.get_hire_flat(hire_id, headers=headers))


# --- Tier 6: environmental incidents ---------------------------------------------


def report_incident(client, contract_id, reporter=OPS_MANAGER, **overrides):
    response = client.create_incident(
        contract_id, f.incident_payload(**overrides), headers=reporter
    )
    data = get_success_data(response)
    assert data.get("id"), "incident report failed: {0}".format(response.text)
    return data


def incident_in_corrective_plan_required(client, contract_id, **overrides):
    """An incident walked REPORTED -> UNDER_REVIEW -> CORRECTIVE_PLAN_REQUIRED."""
    incident = report_incident(client, contract_id, **overrides)
    client.start_review_incident(contract_id, incident["id"], headers=INSPECTOR)
    client.require_corrective_plan(contract_id, incident["id"], headers=INSPECTOR)
    return incident
