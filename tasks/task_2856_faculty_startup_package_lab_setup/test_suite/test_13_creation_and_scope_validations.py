"""Payload, uniqueness, sequencing and role-scope rules of the validation ladder."""

from test_helpers import (
    api_client,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    create_lab_space_payload,
    create_renovation_phase_payload,
    create_startup_package_payload,
)
from test_helpers.test_users import (
    make_dean_office_headers,
    make_department_chair_headers,
    make_faculty_headers,
)

CLOCK = "2026-08-01T00:00:00Z"


def test_share_percentages_that_do_not_sum_to_one_hundred_are_refused():
    """The three cost shares must close on exactly 100 before a package exists.

    PRD 2.13: "ERR_SHARE_PCT_SUM_INVALID (422) — dept_share_pct plus college_share_pct
    plus dean_share_pct equals exactly 100."

    Design: Corner/validations/corner_val_share_percentages_not_summing_to_100_are_rejected
    """
    units = fixtures.setup_mini_units(CLOCK)
    faculty = fixtures.create_candidate_faculty(units["department"]["id"])

    def create(dean_share_pct):
        return api_client.create_startup_package(
            create_startup_package_payload(faculty["id"], units["dean_office"]["id"],
                                           dean_share_pct=dean_share_pct),
            fixtures.DEAN_OFFICE,
        )

    validate_error(create(25), "ERR_SHARE_PCT_SUM_INVALID", expected_status=422)

    listed, meta = validate_paginated(api_client.list_startup_packages(fixtures.DEAN_OFFICE))
    assert meta["total_count"] == 0
    assert listed == []

    accepted = validate_success(create(20), expected_status=201)
    assert accepted["dept_share_pct"] + accepted["college_share_pct"] \
        + accepted["dean_share_pct"] == 100


def test_a_second_room_with_the_same_building_and_number_is_refused():
    """Uniqueness is on the pair, so neither component alone blocks a registration.

    PRD 2.13: "ERR_SPACE_ALREADY_REGISTERED (409) — the combination of building_code and
    room_number is unique across all rooms."

    Design: Corner/validations/corner_val_duplicate_building_and_room_returns_space_already_registered
    """
    fixtures.set_clock(CLOCK)
    first = fixtures.create_lab_space(building_code="CHEM", room_number="101")

    duplicate = api_client.create_lab_space(
        create_lab_space_payload(building_code="CHEM", room_number="101", net_sq_ft=640,
                                 space_class="DRY", power_kw_capacity=60.0,
                                 chilled_water_available=False, fume_hood_count=0,
                                 floor_load_psf=200),
        fixtures.FACILITIES,
    )
    validate_error(duplicate, "ERR_SPACE_ALREADY_REGISTERED", expected_status=409)

    _, meta = validate_paginated(api_client.list_lab_spaces(fixtures.FACILITIES))
    assert meta["total_count"] == 1
    stored = fixtures.read_space(first["id"])
    assert stored["net_sq_ft"] == 900
    assert stored["space_class"] == "WET"

    other_building = fixtures.create_lab_space(building_code="BIOL", room_number="101")
    other_room = fixtures.create_lab_space(building_code="CHEM", room_number="102")
    assert other_building["id"] != other_room["id"]


FIRST_PHASE = {
    "sequence_no": 1,
    "name": "Demolition",
    "planned_start": "2026-09-01T00:00:00Z",
    "planned_end": "2026-09-10T00:00:00Z",
    "budget_cents": 3_000_000,
}


def test_a_phase_that_skips_a_sequence_number_is_refused():
    """The sequence must be contiguous even when the windows are far apart.

    PRD 2.13: "ERR_PHASE_SEQUENCE_GAP (422) — the project's sequence_no values form the
    contiguous run from 1 to the phase count, with no gap and no duplicate."

    Design: Corner/validations/corner_val_phase_sequence_gap_is_rejected
    """
    scenario = fixtures.setup_draft_package()
    space = fixtures.create_lab_space()
    project = fixtures.create_project(scenario["package_id"], space["id"])
    first = fixtures.create_phase(project["id"], **FIRST_PHASE)

    gapped = create_renovation_phase_payload(
        sequence_no=3, name="Casework", planned_start="2026-09-20T00:00:00Z",
        planned_end="2026-09-30T00:00:00Z", budget_cents=3_000_000,
    )
    validate_error(
        api_client.create_renovation_phase(project["id"], gapped, fixtures.FACILITIES),
        "ERR_PHASE_SEQUENCE_GAP", expected_status=422,
    )

    phases = fixtures.read_phases(project["id"])
    assert [phase["id"] for phase in phases] == [first["id"]]

    contiguous = dict(gapped, sequence_no=2)
    accepted = validate_success(
        api_client.create_renovation_phase(project["id"], contiguous, fixtures.FACILITIES),
        expected_status=201,
    )
    assert accepted["sequence_no"] == 2


def test_the_endorsing_chair_may_not_be_the_user_who_submitted():
    """The three negotiation signatures must come from three distinct identities.

    PRD 2.13: "ERR_SEGREGATION_OF_DUTIES (403) — the three negotiation steps are performed
    by three distinct user identifiers: the endorsing user differs from
    proposed_by_user_id, and the approving user differs from both proposed_by_user_id and
    endorsed_by_user_id."

    Design: Corner/validations/corner_val_same_user_submitting_and_endorsing_breaches_segregation_of_duties
    """
    scenario = fixtures.setup_draft_package()
    department_id = scenario["department_id"]
    fixtures.submit_package(scenario["package_id"],
                            headers=make_dean_office_headers(department_id))

    validate_error(
        api_client.endorse_startup_package(
            scenario["package_id"], make_department_chair_headers(department_id)
        ),
        "ERR_SEGREGATION_OF_DUTIES", expected_status=403,
    )

    package = fixtures.read_package(scenario["package_id"])
    assert package["negotiation_status"] == "SUBMITTED"
    assert package["endorsed_by_user_id"] is None
    assert package["proposed_by_user_id"] == department_id

    other_faculty = fixtures.create_candidate_faculty(department_id, full_name="Bo Nakamura")
    other_package = fixtures.create_draft_package(other_faculty["id"],
                                                  scenario["dean_office_id"])
    fixtures.add_tranche(other_package["id"])
    fixtures.submit_package(other_package["id"])
    endorsed = fixtures.endorse_package(other_package["id"], department_id)
    assert endorsed["negotiation_status"] == "DEAN_REVIEW"
    assert endorsed["endorsed_by_user_id"] == department_id


def test_a_chair_of_another_department_cannot_endorse_this_package():
    """The chair's identity must be the package's own department unit.

    PRD 2.13: "ERR_UNIT_SCOPE_VIOLATION (403) — when the acting role is DepartmentChair or
    Dean, X-User-ID equals the identifier of the funding unit that funds the target
    resource: the package's department_unit_id for a DepartmentChair, its college_unit_id
    for a Dean; for funding-unit-scoped reads, the unit itself or one of its descendants."

    Design: Corner/validations/corner_val_chair_endorsing_another_departments_package_returns_unit_scope_violation
    """
    scenario = fixtures.setup_draft_package()
    physics = fixtures.create_sibling_department(scenario["college_id"],
                                                 name="Department of Physics")
    fixtures.submit_package(scenario["package_id"])

    validate_error(
        api_client.endorse_startup_package(
            scenario["package_id"], make_department_chair_headers(physics["id"])
        ),
        "ERR_UNIT_SCOPE_VIOLATION", expected_status=403,
    )

    package = fixtures.read_package(scenario["package_id"])
    assert package["negotiation_status"] == "SUBMITTED"
    assert package["endorsed_by_user_id"] is None
    assert package["proposed_by_user_id"] != physics["id"]

    endorsed = fixtures.endorse_package(scenario["package_id"], scenario["department_id"])
    assert endorsed["negotiation_status"] == "DEAN_REVIEW"


def test_a_faculty_member_cannot_read_a_colleagues_package():
    """The faculty scope rule is role-conditional and reports 403 rather than 404.

    PRD 2.13: "ERR_FACULTY_SCOPE_VIOLATION (403) — when the acting role is Faculty,
    X-User-ID equals the faculty_id that owns the target resource, whether that is the
    package's faculty_id, the assignment's faculty_id, or the faculty_id of the package
    owning an order, appointment or project."

    Design: Corner/validations/corner_val_faculty_reading_another_faculty_package_returns_faculty_scope_violation
    """
    units = fixtures.setup_mini_units(CLOCK)
    department_id = units["department"]["id"]
    dean_unit_id = units["dean_office"]["id"]

    faculty_a = fixtures.create_candidate_faculty(department_id, full_name="Ada Reyes")
    faculty_b = fixtures.create_candidate_faculty(department_id, full_name="Bo Nakamura")
    package_a = fixtures.create_draft_package(faculty_a["id"], dean_unit_id)
    package_b = fixtures.create_draft_package(faculty_b["id"], dean_unit_id)

    validate_error(
        api_client.get_startup_package(package_b["id"], make_faculty_headers(faculty_a["id"])),
        "ERR_FACULTY_SCOPE_VIOLATION", expected_status=403,
    )

    own = validate_success(
        api_client.get_startup_package(package_a["id"], make_faculty_headers(faculty_a["id"]))
    )
    assert own["faculty_id"] == faculty_a["id"]

    as_office = validate_success(
        api_client.get_startup_package(package_b["id"], fixtures.DEAN_OFFICE)
    )
    assert as_office["faculty_id"] == faculty_b["id"]
