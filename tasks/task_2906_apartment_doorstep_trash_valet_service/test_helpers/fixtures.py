"""Composite setup helpers.

The server is restarted with an empty database before every test, so every
helper here builds the state it needs from scratch through the public API.
Reads and writes use `get_success_data`, which is lenient about the status
code, because setup is not the thing under test: the test's own trigger call
is asserted with the strict validators.

Ownership-gated calls thread the acting identity explicitly — a
`PropertyManager` acts as the community's own id, a `Valet` as its contractor
id and a `Resident` as its resident id — so no helper ever leaves an
entity-backed role acting under an opaque handle.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .constants import CLOCK_EPOCH, TEST_DEFAULTS
from .test_users import (
    ANALYST_DRAFTER,
    ANALYST_ISSUER,
    COMPLIANCE_AUDITOR,
    COMPLIANCE_SCREENER,
    PLATFORM_ADMIN,
    VALET_OPS_MANAGER,
    make_property_manager_headers,
    make_resident_headers,
    make_valet_headers,
)


# --------------------------------------------------------------------- clock
def set_clock(to_iso8601):
    """Reposition the logical clock and return the reported `current_utc`."""
    data = get_success_data(
        api_client.set_clock(factories.clock_payload(to_iso8601), PLATFORM_ADMIN)
    )
    return data.get("current_utc")


def reset_clock():
    return set_clock(CLOCK_EPOCH)


# ---------------------------------------------------------------- properties
def create_property(**kwargs):
    return get_success_data(
        api_client.create_property(factories.property_payload(**kwargs), PLATFORM_ADMIN)
    )


def read_property(property_id):
    return get_success_data(api_client.get_property(property_id, PLATFORM_ADMIN))


def list_properties(params=None):
    body = api_client.list_properties(PLATFORM_ADMIN, params=params).json()
    return body.get("data", [])


# ----------------------------------------------------------------- contracts
def draft_contract(property_id, **kwargs):
    return get_success_data(
        api_client.create_contract(
            property_id, factories.contract_payload(**kwargs), ANALYST_DRAFTER
        )
    )


def activate_contract(contract_id):
    return get_success_data(api_client.activate_contract(contract_id, PLATFORM_ADMIN))


def read_contract(contract_id):
    return get_success_data(api_client.get_contract(contract_id, PLATFORM_ADMIN))


def list_contracts(params=None):
    body = api_client.list_contracts(PLATFORM_ADMIN, params=params).json()
    return body.get("data", [])


def terminate_contract(contract_id, reason="Community sold to another owner"):
    return get_success_data(
        api_client.terminate_contract(
            contract_id,
            PLATFORM_ADMIN,
            factories.terminate_contract_payload(reason),
        )
    )


# ----------------------------------------------------------------- residents
def create_resident(property_id, unit_number, **kwargs):
    return get_success_data(
        api_client.create_resident(
            property_id,
            factories.resident_payload(unit_number, **kwargs),
            PLATFORM_ADMIN,
        )
    )


def read_resident(resident_id):
    return get_success_data(api_client.get_resident(resident_id, PLATFORM_ADMIN))


def list_residents(params=None):
    body = api_client.list_residents(PLATFORM_ADMIN, params=params).json()
    return body.get("data", [])


def move_out_resident(property_id, resident_id, move_out_date):
    return get_success_data(
        api_client.move_out_resident(
            resident_id,
            factories.move_out_payload(move_out_date),
            make_property_manager_headers(property_id),
        )
    )


# --------------------------------------------------------------- contractors
def create_contractor(**kwargs):
    return get_success_data(
        api_client.create_contractor(
            factories.contractor_payload(**kwargs), VALET_OPS_MANAGER
        )
    )


def submit_documents(contractor_id, tax_form_type="W9", direct_deposit_on_file=True):
    return get_success_data(
        api_client.submit_contractor_documents(
            contractor_id,
            factories.contractor_documents_payload(
                tax_form_type, direct_deposit_on_file
            ),
            VALET_OPS_MANAGER,
        )
    )


def record_background_check(contractor_id, result="CLEAR", headers=None):
    return get_success_data(
        api_client.record_background_check(
            contractor_id,
            factories.background_check_payload(result),
            headers or COMPLIANCE_SCREENER,
        )
    )


def classify_contractor(contractor_id, basis="DECLARED", headers=None):
    if headers is None:
        headers = COMPLIANCE_SCREENER if basis == "DECLARED" else COMPLIANCE_AUDITOR
    return get_success_data(
        api_client.run_classification(
            contractor_id, factories.classification_payload(basis), headers
        )
    )


def read_contractor(contractor_id):
    return get_success_data(api_client.get_contractor(contractor_id, PLATFORM_ADMIN))


def list_contractors(params=None):
    body = api_client.list_contractors(PLATFORM_ADMIN, params=params).json()
    return body.get("data", [])


def deactivate_contractor(contractor_id, reason="Left the market"):
    return get_success_data(
        api_client.deactivate_contractor(
            contractor_id,
            factories.deactivate_contractor_payload(reason),
            VALET_OPS_MANAGER,
        )
    )


def create_cleared_contractor(**kwargs):
    """A contractor screened through to CLEARED but never classification-run."""
    contractor = create_contractor(**kwargs)
    submit_documents(contractor["id"])
    record_background_check(contractor["id"], "CLEAR")
    return read_contractor(contractor["id"])


def create_eligible_contractor(basis="DECLARED", **kwargs):
    """A contractor that route dispatch will accept: CLEARED and classified."""
    contractor = create_cleared_contractor(**kwargs)
    classify_contractor(contractor["id"], basis)
    return read_contractor(contractor["id"])


# ------------------------------------------------------------ service nights
def schedule_night(contract_id, service_date, **kwargs):
    return get_success_data(
        api_client.create_service_night(
            contract_id,
            factories.service_night_payload(service_date, **kwargs),
            VALET_OPS_MANAGER,
        )
    )


def read_night(night_id):
    return get_success_data(api_client.get_service_night(night_id, PLATFORM_ADMIN))


def night_version(night_id):
    """The night's current `version`, as the stale-version guard demands."""
    return read_night(night_id)["version"]


def close_night(night_id):
    return get_success_data(
        api_client.close_service_night(night_id, VALET_OPS_MANAGER)
    )


def reschedule_night(night_id, action, makeup_service_date=None, reason=None):
    return get_success_data(
        api_client.reschedule_service_night(
            night_id,
            factories.reschedule_payload(action, makeup_service_date, reason),
            VALET_OPS_MANAGER,
        )
    )


def list_nights(params=None):
    body = api_client.list_service_nights(PLATFORM_ADMIN, params=params).json()
    return body.get("data", [])


def find_makeup_night(original_night_id):
    """Makeup nights are reachable only through the back-reference filter."""
    nights = list_nights({"rescheduled_from_night_id": original_night_id})
    return nights[0] if nights else None


# --------------------------------------------------------- route assignments
def assign_route(night_id, contractor_id, unit_from, unit_to, expected_version=None):
    version = (
        expected_version if expected_version is not None else night_version(night_id)
    )
    return get_success_data(
        api_client.create_route_assignment(
            night_id,
            factories.route_payload(contractor_id, unit_from, unit_to, version),
            VALET_OPS_MANAGER,
        )
    )


def read_route(route_id):
    return get_success_data(api_client.get_route_assignment(route_id, PLATFORM_ADMIN))


def accept_route(route_id, contractor_id):
    return get_success_data(
        api_client.accept_route(route_id, make_valet_headers(contractor_id))
    )


def complete_route(route_id, contractor_id):
    return get_success_data(
        api_client.complete_route(route_id, make_valet_headers(contractor_id))
    )


def abandon_route(route_id, contractor_id, reason="Van broke down"):
    return get_success_data(
        api_client.abandon_route(
            route_id,
            factories.abandon_route_payload(reason),
            make_valet_headers(contractor_id),
        )
    )


def list_routes(params=None):
    body = api_client.list_route_assignments(PLATFORM_ADMIN, params=params).json()
    return body.get("data", [])


def assign_and_accept_route(night_id, contractor_id, unit_from, unit_to):
    route = assign_route(night_id, contractor_id, unit_from, unit_to)
    accept_route(route["id"], contractor_id)
    return read_route(route["id"])


# --------------------------------------------------------------------- scans
def record_scan(route_id, contractor_id, resident_id, scan_result="SERVICED",
                container_type="TRASH_BIN", non_compliance_type=None):
    return get_success_data(
        api_client.record_scan(
            route_id,
            factories.scan_payload(
                resident_id, scan_result, container_type, non_compliance_type
            ),
            make_valet_headers(contractor_id),
        )
    )


def read_scan(scan_id):
    return get_success_data(api_client.get_scan(scan_id, PLATFORM_ADMIN))


def list_scans(params=None):
    body = api_client.list_scans(PLATFORM_ADMIN, params=params).json()
    return body.get("data", [])


def assess_manual_fine(property_id, scan_id, note=None):
    return get_success_data(
        api_client.assess_fine(
            scan_id,
            factories.manual_fine_payload(note),
            make_property_manager_headers(property_id),
        )
    )


def void_tag(property_id, scan_id, reason="Tagged the wrong door"):
    return get_success_data(
        api_client.void_tag(
            scan_id,
            factories.void_tag_payload(reason),
            make_property_manager_headers(property_id),
        )
    )


# --------------------------------------------------------------------- fines
def list_fines(params=None):
    body = api_client.list_fines(PLATFORM_ADMIN, params=params).json()
    return body.get("data", [])


def find_fine_for_scan(scan_id):
    """Automatic fines are discoverable only through the scan filter."""
    fines = list_fines({"scan_id": scan_id})
    return fines[0] if fines else None


def read_fine(fine_id):
    return get_success_data(api_client.get_fine(fine_id, PLATFORM_ADMIN))


def dispute_fine(resident_id, fine_id, reason="The bin was not mine"):
    return get_success_data(
        api_client.dispute_fine(
            fine_id,
            factories.dispute_payload(reason),
            make_resident_headers(resident_id),
        )
    )


def adjudicate_fine(property_id, fine_id, outcome, note=None):
    return get_success_data(
        api_client.adjudicate_fine(
            fine_id,
            factories.adjudicate_payload(outcome, note),
            make_property_manager_headers(property_id),
        )
    )


# ---------------------------------------------------------------- incidents
def report_incident(property_id, incident_type="JAM", description=None, headers=None):
    return get_success_data(
        api_client.create_compactor_incident(
            property_id,
            factories.incident_payload(incident_type, description),
            headers or VALET_OPS_MANAGER,
        )
    )


def read_incident(incident_id):
    return get_success_data(
        api_client.get_compactor_incident(incident_id, PLATFORM_ADMIN)
    )


def acknowledge_incident(property_id, incident_id):
    return get_success_data(
        api_client.acknowledge_incident(
            incident_id, make_property_manager_headers(property_id)
        )
    )


def escalate_incident(incident_id):
    return get_success_data(
        api_client.escalate_incident(incident_id, VALET_OPS_MANAGER)
    )


def resolve_incident(incident_id, resolution_note="Compactor cleared by the vendor"):
    return get_success_data(
        api_client.resolve_incident(
            incident_id,
            factories.resolve_incident_payload(resolution_note),
            VALET_OPS_MANAGER,
        )
    )


def list_incidents(params=None):
    body = api_client.list_compactor_incidents(PLATFORM_ADMIN, params=params).json()
    return body.get("data", [])


# --------------------------------------------------------------- statements
def draft_statement(contract_id, billing_period=None, expected_contract_version=None,
                    headers=None):
    period = billing_period or TEST_DEFAULTS["BILLING_PERIOD"]
    version = (
        expected_contract_version
        if expected_contract_version is not None
        else read_contract(contract_id)["version"]
    )
    return get_success_data(
        api_client.create_statement(
            contract_id,
            factories.statement_payload(period, version),
            headers or ANALYST_DRAFTER,
        )
    )


def issue_statement(statement_id, headers=None):
    return get_success_data(
        api_client.issue_statement(statement_id, headers or ANALYST_ISSUER)
    )


def read_statement(statement_id):
    return get_success_data(api_client.get_statement(statement_id, PLATFORM_ADMIN))


def void_statement(statement_id, reason="Cut against the wrong terms"):
    return get_success_data(
        api_client.void_statement(
            statement_id, factories.void_statement_payload(reason), PLATFORM_ADMIN
        )
    )


def list_statements(params=None):
    body = api_client.list_statements(PLATFORM_ADMIN, params=params).json()
    return body.get("data", [])


# --------------------------------------------------------------------------
# Worlds
# --------------------------------------------------------------------------
def build_active_community(name=None, unit_count=None, resident_units=(101,),
                           clock=None, contract=None, resident_kwargs=None,
                           with_contractor=True, contractor_kwargs=None,
                           contractor_basis="DECLARED"):
    """Build a live community: clock, community, active contract, residents.

    Residents are added before the contract is activated and before any night
    is scheduled, so each night's `expected_door_count` sees the intended
    occupancy picture. `resident_kwargs` maps a unit number to the extra
    resident payload fields for that door.
    """
    set_clock(clock or TEST_DEFAULTS["SETUP_CLOCK"])
    prop = create_property(name=name, unit_count=unit_count)
    contract_row = draft_contract(prop["id"], **(contract or {}))
    residents = {}
    for unit in resident_units:
        extra = (resident_kwargs or {}).get(unit, {})
        residents[unit] = create_resident(prop["id"], unit, **extra)
    activate_contract(contract_row["id"])
    world = {
        "property": read_property(prop["id"]),
        "contract": read_contract(contract_row["id"]),
        "residents": residents,
        "contractor": None,
    }
    if with_contractor:
        world["contractor"] = create_eligible_contractor(
            basis=contractor_basis, **(contractor_kwargs or {})
        )
    return world


def build_scan_ready_night(world=None, service_date=None, unit_from=101, unit_to=None,
                           night_kwargs=None, **world_kwargs):
    """A live community with one night whose route is ACCEPTED and scannable."""
    if world is None:
        world = build_active_community(**world_kwargs)
    date = service_date or TEST_DEFAULTS["NIGHT_1_DATE"]
    night = schedule_night(
        world["contract"]["id"], date, **(night_kwargs or {})
    )
    last_unit = unit_to if unit_to is not None else 100 + world["property"]["unit_count"]
    route = assign_and_accept_route(
        night["id"], world["contractor"]["id"], unit_from, last_unit
    )
    world["night"] = read_night(night["id"])
    world["route"] = route
    return world


def add_scan_ready_night(world, service_date, unit_from=101, unit_to=None,
                         night_kwargs=None):
    """Add one more scannable night to an existing community.

    Returns the (night, route) pair rather than mutating the world's own
    `night` and `route` keys, so a test can hold several nights at once.
    """
    night = schedule_night(
        world["contract"]["id"], service_date, **(night_kwargs or {})
    )
    last_unit = unit_to if unit_to is not None else 100 + world["property"]["unit_count"]
    route = assign_and_accept_route(
        night["id"], world["contractor"]["id"], unit_from, last_unit
    )
    return read_night(night["id"]), route


def record_violation_scan(world, night_and_route, unit,
                          non_compliance_type="RECYCLING_CONTAMINATION"):
    """Record one tagged scan for the resident at `unit` on the given route."""
    _, route = night_and_route
    return record_scan(
        route["id"],
        world["contractor"]["id"],
        world["residents"][unit]["id"],
        scan_result="TAGGED_NOT_SERVICED",
        container_type="RECYCLING_BIN",
        non_compliance_type=non_compliance_type,
    )


def build_escalated_jam(world, incident_count=1):
    """Report and escalate `incident_count` compactor jams on the community.

    The jams are filed at the community's current clock position and the clock
    is then advanced to the acknowledgement deadline, which is the earliest
    instant at which escalation is permitted.
    """
    incidents = [
        report_incident(world["property"]["id"], "JAM")
        for _ in range(incident_count)
    ]
    set_clock(incidents[0]["ack_deadline_at"])
    escalated = [escalate_incident(incident["id"]) for incident in incidents]
    return escalated
