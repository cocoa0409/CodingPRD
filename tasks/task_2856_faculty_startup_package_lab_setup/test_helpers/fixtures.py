"""Composite setup helpers.

Every test starts against an empty database, so each helper here builds its
preconditions from scratch using only endpoints the PRD declares.  All setup
calls go through the lenient validator so a broken precondition reports as a
setup failure rather than as a confusing assertion error.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_STARTUP_DEFAULT,
    FY2027_AVAILABLE_ON,
    FY2027_EXPIRES_ON,
    FY2028_AVAILABLE_ON,
    FY2028_EXPIRES_ON,
    TEST_DEFAULTS,
)
from .factories import (
    create_commitment_tranche_payload,
    create_equipment_order_payload,
    create_faculty_payload,
    create_funding_unit_payload,
    create_lab_space_payload,
    create_renovation_phase_payload,
    create_renovation_project_payload,
    create_space_assignment_payload,
    create_staff_appointment_payload,
    create_startup_package_payload,
    place_equipment_order_payload,
    utility_upgrade_payload,
)
from .test_users import (
    TEST_USERS,
    make_dean_headers,
    make_dean_office_headers,
    make_department_chair_headers,
    make_faculty_headers,
    make_facilities_manager_headers,
)

DEAN_OFFICE = TEST_USERS["dean_office_headers"]
FACILITIES = TEST_USERS["facilities_manager_headers"]

# The six-tranche schedule used by the larger money-movement scenarios: three
# EQUIPMENT tranches with deliberately different expiry instants so the
# waterfall ordering is observable, plus one tranche per remaining category.
BASE_TRANCHE_SPECS = [
    {
        "key": "equipment_capped",
        "category": "EQUIPMENT",
        "fiscal_year": 2027,
        "amount_cents": 25_000_000,
        "available_on": FY2027_AVAILABLE_ON,
        "expires_on": "2027-01-01T00:00:00Z",
        "carryforward_policy": "CAPPED",
        "carryforward_cap_pct": 50,
    },
    {
        "key": "equipment_full",
        "category": "EQUIPMENT",
        "fiscal_year": 2027,
        "amount_cents": 15_000_000,
        "available_on": FY2027_AVAILABLE_ON,
        "expires_on": FY2027_EXPIRES_ON,
        "carryforward_policy": "FULL",
    },
    {
        "key": "equipment_next_year",
        "category": "EQUIPMENT",
        "fiscal_year": 2028,
        "amount_cents": 8_000_000,
        "available_on": FY2028_AVAILABLE_ON,
        "expires_on": FY2028_EXPIRES_ON,
        "carryforward_policy": "NONE",
    },
    {
        "key": "renovation",
        "category": "RENOVATION",
        "fiscal_year": 2027,
        "amount_cents": 12_000_000,
        "available_on": FY2027_AVAILABLE_ON,
        "expires_on": FY2027_EXPIRES_ON,
        "carryforward_policy": "NONE",
    },
    {
        "key": "personnel",
        "category": "PERSONNEL",
        "fiscal_year": 2027,
        "amount_cents": 9_600_000,
        "available_on": FY2027_AVAILABLE_ON,
        "expires_on": FY2027_EXPIRES_ON,
        "carryforward_policy": "FULL",
    },
    {
        "key": "discretionary",
        "category": "DISCRETIONARY",
        "fiscal_year": 2027,
        "amount_cents": 2_400_000,
        "available_on": FY2027_AVAILABLE_ON,
        "expires_on": FY2027_EXPIRES_ON,
        "carryforward_policy": "NONE",
    },
]

BASE_PROPOSED_TOTAL_CENTS = 72_000_000

# The single-tranche schedule used by the smaller scenarios.
MINI_TRANCHE_SPECS = [
    {
        "key": "equipment",
        "category": "EQUIPMENT",
        "fiscal_year": 2027,
        "amount_cents": 20_000_000,
        "available_on": FY2027_AVAILABLE_ON,
        "expires_on": FY2027_EXPIRES_ON,
        "carryforward_policy": "NONE",
    },
]


# --- primitive steps ---------------------------------------------------------

def set_clock(current_utc: str, headers: dict = None) -> dict:
    """Move the server's logical UTC clock."""
    return get_success_data(api_client.set_clock(current_utc, headers or DEAN_OFFICE))


def create_funding_unit(**overrides) -> dict:
    return get_success_data(
        api_client.create_funding_unit(create_funding_unit_payload(**overrides), DEAN_OFFICE)
    )


def create_funding_hierarchy(
    college_pool_cents: int = TEST_DEFAULTS["COLLEGE_POOL_CENTS"],
    department_pool_cents: int = TEST_DEFAULTS["DEPARTMENT_POOL_CENTS"],
    dean_office_pool_cents: int = TEST_DEFAULTS["DEAN_OFFICE_POOL_CENTS"],
) -> dict:
    """One COLLEGE with one DEPARTMENT and one DEAN_OFFICE pool hanging off it."""
    college = create_funding_unit(
        name="College of Natural Sciences",
        unit_type="COLLEGE",
        cost_share_pool_cents=college_pool_cents,
    )
    department = create_funding_unit(
        name="Department of Chemistry",
        unit_type="DEPARTMENT",
        parent_unit_id=college["id"],
        cost_share_pool_cents=department_pool_cents,
    )
    dean_office = create_funding_unit(
        name="Dean Office Strategic Pool",
        unit_type="DEAN_OFFICE",
        parent_unit_id=college["id"],
        cost_share_pool_cents=dean_office_pool_cents,
    )
    return {"college": college, "department": department, "dean_office": dean_office}


def setup_mini_units(clock: str = CLOCK_STARTUP_DEFAULT, **pool_overrides) -> dict:
    """Clock at a known instant plus the three funder units."""
    set_clock(clock)
    return create_funding_hierarchy(**pool_overrides)


def create_sibling_department(college_id: str, name: str = "Department of Biochemistry",
                              cost_share_pool_cents: int = 100_000_000) -> dict:
    """A second DEPARTMENT under the same college, for internal-transfer tests."""
    return create_funding_unit(
        name=name,
        unit_type="DEPARTMENT",
        parent_unit_id=college_id,
        cost_share_pool_cents=cost_share_pool_cents,
    )


def create_candidate_faculty(department_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_faculty(create_faculty_payload(department_id, **overrides), DEAN_OFFICE)
    )


def activate_faculty(faculty_id: str) -> dict:
    return get_success_data(api_client.activate_faculty(faculty_id, DEAN_OFFICE))


def record_departure_notice(faculty_id: str, departure_intent: str,
                            departure_effective_on: str,
                            target_funding_unit_id: str = None,
                            headers: dict = None) -> dict:
    payload = {
        "departure_intent": departure_intent,
        "departure_effective_on": departure_effective_on,
    }
    if target_funding_unit_id is not None:
        payload["target_funding_unit_id"] = target_funding_unit_id
    return get_success_data(
        api_client.record_departure_notice(faculty_id, payload, headers or DEAN_OFFICE)
    )


def separate_faculty(faculty_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.separate_faculty(faculty_id, headers or DEAN_OFFICE)
    )


def end_staff_appointment(appointment_id: str, end_date: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.end_staff_appointment(
            appointment_id, {"end_date": end_date}, headers or DEAN_OFFICE
        )
    )


def receive_order(order_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.receive_equipment_order(order_id, headers or FACILITIES)
    )


def install_order(order_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.install_equipment_order(order_id, headers or FACILITIES)
    )


def cancel_order(order_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.cancel_equipment_order(order_id, headers or DEAN_OFFICE)
    )


def upgrade_utilities(space_id: str, headers: dict = None, **overrides) -> dict:
    return get_success_data(
        api_client.upgrade_lab_space_utilities(
            space_id, utility_upgrade_payload(**overrides), headers or FACILITIES
        )
    )


def rollover_fiscal_year(package_id: str, fiscal_year: int, headers: dict = None) -> dict:
    return get_success_data(
        api_client.year_end_rollover(
            package_id, {"fiscal_year": fiscal_year}, headers or DEAN_OFFICE
        )
    )


def create_lab_space(**overrides) -> dict:
    return get_success_data(
        api_client.create_lab_space(create_lab_space_payload(**overrides), FACILITIES)
    )


def create_draft_package(faculty_id: str, dean_unit_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_startup_package(
            create_startup_package_payload(faculty_id, dean_unit_id, **overrides), DEAN_OFFICE
        )
    )


def add_tranche(package_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_commitment_tranche(
            package_id, create_commitment_tranche_payload(**overrides), DEAN_OFFICE
        )
    )


def add_tranches(package_id: str, specs: list) -> dict:
    """Add every spec in order; returns {key: tranche} plus an ordered list."""
    created = {}
    ordered = []
    for spec in specs:
        payload = {key: value for key, value in spec.items() if key != "key"}
        tranche = add_tranche(package_id, **payload)
        ordered.append(tranche)
        if "key" in spec:
            created[spec["key"]] = tranche
    created["_ordered"] = ordered
    return created


# --- negotiation -------------------------------------------------------------

def proposer_headers() -> dict:
    """The DeanOffice actor that proposes and submits packages."""
    return make_dean_office_headers(TEST_DEFAULTS["DEAN_OFFICE_USER_ID"])


def scenario_headers(units: dict, faculty_id: str = None) -> dict:
    """One header set per role, each carrying the identity that role is bound to."""
    headers = {
        "dean_office": proposer_headers(),
        "facilities": make_facilities_manager_headers(TEST_DEFAULTS["FACILITIES_USER_ID"]),
        "chair": make_department_chair_headers(units["department"]["id"]),
        "dean": make_dean_headers(units["college"]["id"]),
    }
    if faculty_id is not None:
        headers["faculty"] = make_faculty_headers(faculty_id)
    return headers


def submit_package(package_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.submit_startup_package(package_id, headers or proposer_headers())
    )


def endorse_package(package_id: str, department_id: str) -> dict:
    return get_success_data(
        api_client.endorse_startup_package(
            package_id, make_department_chair_headers(department_id)
        )
    )


def approve_package(package_id: str, college_id: str) -> dict:
    return get_success_data(
        api_client.approve_startup_package(package_id, make_dean_headers(college_id))
    )


def negotiate_to_approved(package_id: str, units: dict) -> dict:
    """Submit, endorse and approve with three distinct actors."""
    submit_package(package_id)
    endorse_package(package_id, units["department"]["id"])
    return approve_package(package_id, units["college"]["id"])


def activate_package(package_id: str) -> dict:
    return get_success_data(
        api_client.activate_startup_package(package_id, proposer_headers())
    )


def counter_package(package_id: str, counter_total_cents: int, dean_headers: dict) -> dict:
    return get_success_data(
        api_client.counter_startup_package(
            package_id, {"counter_total_cents": counter_total_cents}, dean_headers
        )
    )


def revise_package(package_id: str, revised_total_cents: int, headers: dict = None) -> dict:
    return get_success_data(
        api_client.revise_startup_package(
            package_id, {"revised_total_cents": revised_total_cents},
            headers or proposer_headers(),
        )
    )


def withdraw_tranche(package_id: str, tranche_id: str, headers: dict = None) -> None:
    """Withdrawal returns no body, so only the 204 is observable."""
    response = api_client.delete_commitment_tranche(
        package_id, tranche_id, headers or DEAN_OFFICE
    )
    assert response.status_code == 204, (
        f"expected 204 from a tranche withdrawal, got {response.status_code}: {response.text}"
    )


def close_out_package(package_id: str, dean_headers: dict) -> dict:
    return get_success_data(
        api_client.close_out_startup_package(package_id, dean_headers)
    )


def release_assignment(assignment_id: str, released_on: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.release_space_assignment(
            assignment_id, {"released_on": released_on}, headers or FACILITIES
        )
    )


# --- composite scenarios -----------------------------------------------------

def _build_scenario(units: dict, faculty: dict, package: dict, tranches: dict) -> dict:
    ordered = tranches.get("_ordered", []) if tranches else []
    by_key = {k: v for k, v in (tranches or {}).items() if k != "_ordered"}
    return {
        "units": units,
        "college": units["college"],
        "department": units["department"],
        "dean_office": units["dean_office"],
        "college_id": units["college"]["id"],
        "department_id": units["department"]["id"],
        "dean_office_id": units["dean_office"]["id"],
        "faculty": faculty,
        "faculty_id": faculty["id"],
        "package": package,
        "package_id": package["id"],
        "tranche": by_key,
        "tranches": ordered,
        "headers": scenario_headers(units, faculty["id"]),
    }


def setup_draft_package(
    tranche_specs: list = None,
    clock: str = CLOCK_STARTUP_DEFAULT,
    proposed_total_cents: int = None,
    faculty_overrides: dict = None,
    package_overrides: dict = None,
    pool_overrides: dict = None,
) -> dict:
    """Units, a CANDIDATE faculty and a DRAFT package with its tranches loaded."""
    specs = MINI_TRANCHE_SPECS if tranche_specs is None else tranche_specs
    units = setup_mini_units(clock, **(pool_overrides or {}))
    faculty = create_candidate_faculty(units["department"]["id"], **(faculty_overrides or {}))
    overrides = dict(package_overrides or {})
    if proposed_total_cents is not None:
        overrides["proposed_total_cents"] = proposed_total_cents
    package = create_draft_package(faculty["id"], units["dean_office"]["id"], **overrides)
    tranches = add_tranches(package["id"], specs)
    # Every tranche create re-derives the package's rollups, which per PRD 2.4 is a
    # mutation that bumps the package's version, so the creation-time snapshot is
    # already stale. Re-read so the scenario carries the package's true current state.
    return _build_scenario(units, faculty, read_package(package["id"]), tranches)


def setup_approved_package(**kwargs) -> dict:
    """A DRAFT scenario carried through submit, endorse and approve."""
    scenario = setup_draft_package(**kwargs)
    scenario["package"] = negotiate_to_approved(scenario["package_id"], scenario["units"])
    return scenario


def setup_active_package(**kwargs) -> dict:
    """An APPROVED scenario with the faculty ACTIVE and the package activated."""
    scenario = setup_approved_package(**kwargs)
    scenario["faculty"] = activate_faculty(scenario["faculty_id"])
    scenario["package"] = activate_package(scenario["package_id"])
    return scenario


def setup_mini_active(**kwargs) -> dict:
    """Smallest spendable scenario: one 20,000,000 cent EQUIPMENT tranche."""
    return setup_active_package(**kwargs)


def setup_base_package() -> dict:
    """The six-tranche 72,000,000 cent scenario, active and spending."""
    return setup_active_package(
        tranche_specs=BASE_TRANCHE_SPECS,
        proposed_total_cents=BASE_PROPOSED_TOTAL_CENTS,
    )


def setup_base_draft() -> dict:
    """The six-tranche schedule left in DRAFT."""
    return setup_draft_package(
        tranche_specs=BASE_TRANCHE_SPECS,
        proposed_total_cents=BASE_PROPOSED_TOTAL_CENTS,
    )


# --- space assignments -------------------------------------------------------

def propose_space_assignment(space: dict, faculty_id: str, headers: dict = None,
                            **overrides) -> dict:
    """Propose an assignment using the space's current version as the guard."""
    payload = create_space_assignment_payload(
        space["id"], faculty_id, space["version"], **overrides
    )
    return get_success_data(
        api_client.create_space_assignment(payload, headers or DEAN_OFFICE)
    )


def activate_space_assignment(assignment_id: str) -> dict:
    return get_success_data(api_client.activate_space_assignment(assignment_id, FACILITIES))


def create_active_assignment(space: dict, faculty_id: str, **overrides) -> dict:
    assignment = propose_space_assignment(space, faculty_id, **overrides)
    return activate_space_assignment(assignment["id"])


def setup_assigned_space(scenario: dict, space_overrides: dict = None, **assignment_overrides):
    """A fresh lab space with one ACTIVE assignment to the scenario's faculty."""
    space = create_lab_space(**(space_overrides or {}))
    assignment = create_active_assignment(space, scenario["faculty_id"], **assignment_overrides)
    return space, assignment


# --- renovation projects -----------------------------------------------------

def create_project(package_id: str, space_id: str, headers: dict = None, **overrides) -> dict:
    return get_success_data(
        api_client.create_renovation_project(
            create_renovation_project_payload(package_id, space_id, **overrides),
            headers or FACILITIES,
        )
    )


def create_phase(project_id: str, headers: dict = None, **overrides) -> dict:
    return get_success_data(
        api_client.create_renovation_phase(
            project_id, create_renovation_phase_payload(**overrides), headers or FACILITIES
        )
    )


def add_phases(project_id: str, specs: list, headers: dict = None) -> list:
    return [create_phase(project_id, headers, **spec) for spec in specs]


def solicit_bids(project_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.solicit_renovation_bids(project_id, headers or FACILITIES)
    )


def award_project(project_id: str, awarded_cents: int, dean_headers: dict) -> dict:
    """The award is the dean's act, so the dean identity must be supplied."""
    return get_success_data(
        api_client.award_renovation_project(
            project_id, {"awarded_cents": awarded_cents}, dean_headers
        )
    )


def setup_scoped_project(
    package_id: str,
    space_id: str,
    phase_specs: list = None,
    project_overrides: dict = None,
):
    """A project with its phases, left in SCOPING."""
    project = create_project(package_id, space_id, **(project_overrides or {}))
    phases = add_phases(project["id"], phase_specs or [{}])
    return project, phases


def setup_awarded_project(
    package_id: str,
    space_id: str,
    awarded_cents: int,
    dean_headers: dict,
    phase_specs: list = None,
    project_overrides: dict = None,
):
    """A project with phases, taken through bid solicitation to award."""
    project, phases = setup_scoped_project(
        package_id, space_id, phase_specs, project_overrides
    )
    solicit_bids(project["id"])
    project = award_project(project["id"], awarded_cents, dean_headers)
    return project, phases


def start_phase(project_id: str, phase_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.start_renovation_phase(project_id, phase_id, headers or FACILITIES)
    )


def substantial_completion(project_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.substantial_completion(project_id, headers or FACILITIES)
    )


def complete_phase(project_id: str, phase_id: str, actual_cost_cents: int,
                   headers: dict = None) -> dict:
    return get_success_data(
        api_client.complete_renovation_phase(
            project_id,
            phase_id,
            {"actual_cost_cents": actual_cost_cents},
            headers or FACILITIES,
        )
    )


# --- equipment orders --------------------------------------------------------

def create_order(package_id: str, install_space_id: str, headers: dict = None, **overrides) -> dict:
    return get_success_data(
        api_client.create_equipment_order(
            create_equipment_order_payload(package_id, install_space_id, **overrides),
            headers or DEAN_OFFICE,
        )
    )


def place_order(order_id: str, package_id: str, headers: dict = None) -> dict:
    """Place an order, reading the package's current version for the guard."""
    package = read_package(package_id)
    return get_success_data(
        api_client.place_equipment_order(
            order_id,
            place_equipment_order_payload(package["version"]),
            headers or DEAN_OFFICE,
        )
    )


def setup_placed_order(package_id: str, install_space_id: str, **overrides) -> dict:
    order = create_order(package_id, install_space_id, **overrides)
    return place_order(order["id"], package_id)


def setup_received_order(package_id: str, install_space_id: str, **overrides) -> dict:
    order = setup_placed_order(package_id, install_space_id, **overrides)
    return receive_order(order["id"])


def setup_installed_order(package_id: str, install_space_id: str, **overrides) -> dict:
    order = setup_received_order(package_id, install_space_id, **overrides)
    return install_order(order["id"])


# --- staff appointments ------------------------------------------------------

def create_staff_appointment(package_id: str, headers: dict = None, **overrides) -> dict:
    return get_success_data(
        api_client.create_staff_appointment(
            create_staff_appointment_payload(package_id, **overrides), headers or DEAN_OFFICE
        )
    )


def activate_staff_appointment(appointment_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.activate_staff_appointment(appointment_id, headers or DEAN_OFFICE)
    )


def setup_active_staff_appointment(package_id: str, **overrides) -> dict:
    appointment = create_staff_appointment(package_id, **overrides)
    return activate_staff_appointment(appointment["id"])


# --- readers -----------------------------------------------------------------

def read_unit(unit_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.get_funding_unit(unit_id, headers or DEAN_OFFICE))


def read_faculty(faculty_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.get_faculty(faculty_id, headers or DEAN_OFFICE))


def read_package(package_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_startup_package(package_id, headers or DEAN_OFFICE)
    )


def read_tranche(tranche_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_commitment_tranche(tranche_id, headers or DEAN_OFFICE)
    )


def read_space(space_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.get_lab_space(space_id, headers or FACILITIES))


def read_assignment(assignment_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_space_assignment(assignment_id, headers or FACILITIES)
    )


def read_project(project_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_renovation_project(project_id, headers or FACILITIES)
    )


def read_phases(project_id: str, headers: dict = None) -> list:
    data = get_success_data(
        api_client.list_renovation_phases(project_id, headers or FACILITIES)
    )
    return data


def read_order(order_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.get_equipment_order(order_id, headers or DEAN_OFFICE))


def read_appointment(appointment_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_staff_appointment(appointment_id, headers or DEAN_OFFICE)
    )


def read_spend_summary(package_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_package_spend_summary(package_id, headers or DEAN_OFFICE)
    )


def read_ledger(package_id: str, headers: dict = None, params: dict = None) -> list:
    """The package's SpendTransaction rows, oldest first."""
    all_params = {"limit": 100}
    if params:
        all_params.update(params)
    return get_success_data(
        api_client.list_package_spend_transactions(
            package_id, headers or DEAN_OFFICE, all_params
        )
    )


def read_tranche_ledger(tranche_id: str, headers: dict = None, params: dict = None) -> list:
    all_params = {"limit": 100}
    if params:
        all_params.update(params)
    return get_success_data(
        api_client.list_tranche_spend_transactions(
            tranche_id, headers or DEAN_OFFICE, all_params
        )
    )


def read_package_tranches(package_id: str, headers: dict = None, params: dict = None) -> list:
    all_params = {"limit": 100}
    if params:
        all_params.update(params)
    return get_success_data(
        api_client.list_package_tranches(package_id, headers or DEAN_OFFICE, all_params)
    )


def tranches_by_id(package_id: str, headers: dict = None) -> dict:
    return {row["id"]: row for row in read_package_tranches(package_id, headers)}
