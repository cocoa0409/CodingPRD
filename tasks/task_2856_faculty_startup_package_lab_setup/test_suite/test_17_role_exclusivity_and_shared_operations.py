"""Which role owns which verb, and where a shared verb is still unit-scoped."""

from test_helpers import (
    api_client,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers.assertions import (
    assert_tranche_balances,
    rows_of_kind,
)
from test_helpers.factories import (
    award_payload,
    create_equipment_order_payload,
    place_equipment_order_payload,
)
from test_helpers.test_users import (
    make_dean_headers,
    make_dean_office_headers,
    make_department_chair_headers,
    make_faculty_headers,
)

CLOCK = "2026-08-01T00:00:00Z"

RENOVATION_ONLY_SPECS = [
    {
        "key": "renovation",
        "category": "RENOVATION",
        "fiscal_year": 2027,
        "amount_cents": 20_000_000,
        "available_on": "2026-07-01T00:00:00Z",
        "expires_on": "2027-07-01T00:00:00Z",
        "carryforward_policy": "NONE",
    },
]

AWARD_PHASE = {
    "sequence_no": 1,
    "name": "Demolition",
    "planned_start": "2026-09-01T00:00:00Z",
    "planned_end": "2026-09-30T00:00:00Z",
    "budget_cents": 6_000_000,
}


def test_only_the_dean_awards_a_construction_contract():
    """The award is the dean's alone, even for the office that drafts the package.

    PRD 2.1: "**Dean** — the college dean, who counters, approves and closes out packages,
    awards construction contracts, and may run the fiscal-year rollover. A Dean can
    neither draft nor endorse."

    Design: Corner/rbac/corner_rbac_dean_office_cannot_award_a_construction_contract
    """
    scenario = fixtures.setup_draft_package(
        tranche_specs=RENOVATION_ONLY_SPECS, clock=CLOCK, proposed_total_cents=20_000_000
    )
    space = fixtures.create_lab_space(building_code="CHEM", room_number="410")
    project = fixtures.create_project(scenario["package_id"], space["id"],
                                      scope_tier="MODERATE", estimate_cents=8_000_000)
    fixtures.create_phase(project["id"], **AWARD_PHASE)
    at_bid = fixtures.solicit_bids(project["id"])
    assert at_bid["status"] == "BID"
    assert at_bid["version"] == 2

    validate_error(
        api_client.award_renovation_project(project["id"], award_payload(6_000_000),
                                            fixtures.DEAN_OFFICE),
        "ERR_UNAUTHORIZED", expected_status=403,
    )
    validate_error(
        api_client.award_renovation_project(project["id"], award_payload(6_000_000),
                                            fixtures.FACILITIES),
        "ERR_UNAUTHORIZED", expected_status=403,
    )

    untouched = fixtures.read_project(project["id"])
    assert untouched["status"] == "BID"
    assert untouched["awarded_on"] is None
    assert untouched["awarded_cents"] is None
    assert untouched["version"] == 2
    assert fixtures.read_space(space["id"])["status"] == "AVAILABLE"
    assert fixtures.read_ledger(scenario["package_id"]) == []
    assert fixtures.read_package(scenario["package_id"])["total_encumbered_cents"] == 0

    validate_error(
        api_client.award_renovation_project(
            project["id"], award_payload(6_000_000),
            make_dean_headers(scenario["college_id"]),
        ),
        "ERR_PACKAGE_SPEND_FROZEN", expected_status=409,
    )


def test_the_chair_cannot_approve_and_the_dean_cannot_endorse():
    """Two adjacent signatures, each reachable only by its own role.

    PRD 2.1: "If the headers are well formed but the declared role is not among the roles
    authorised for the endpoint being called (see the table in §4), the request is
    rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/corner_rbac_chair_cannot_approve_and_dean_cannot_endorse
    """
    scenario = fixtures.setup_draft_package(clock=CLOCK)
    package_id = scenario["package_id"]
    submitted = fixtures.submit_package(package_id)
    assert submitted["negotiation_status"] == "SUBMITTED"

    validate_error(
        api_client.approve_startup_package(
            package_id, make_department_chair_headers(scenario["department_id"])
        ),
        "ERR_UNAUTHORIZED", expected_status=403,
    )
    validate_error(
        api_client.endorse_startup_package(
            package_id, make_dean_headers(scenario["college_id"])
        ),
        "ERR_UNAUTHORIZED", expected_status=403,
    )
    validate_error(
        api_client.endorse_startup_package(package_id, fixtures.DEAN_OFFICE),
        "ERR_UNAUTHORIZED", expected_status=403,
    )
    validate_error(
        api_client.approve_startup_package(package_id, fixtures.DEAN_OFFICE),
        "ERR_UNAUTHORIZED", expected_status=403,
    )

    package = fixtures.read_package(package_id)
    assert package["negotiation_status"] == "SUBMITTED"
    assert package["endorsed_by_user_id"] is None
    assert package["approved_by_user_id"] is None
    assert fixtures.read_unit(scenario["department_id"])["reserved_cents"] == 0

    fixtures.endorse_package(package_id, scenario["department_id"])
    approved = fixtures.approve_package(package_id, scenario["college_id"])
    assert approved["negotiation_status"] == "APPROVED"


def test_the_faculty_member_may_request_equipment_but_never_place_the_order():
    """A shared verb narrowed to the faculty member's own package, and an exclusive one.

    PRD 2.1: "**Faculty** — the recruited or retained faculty member, who may request
    equipment and propose staff against their own package and read their own records, but
    may never place an order, activate an appointment, or touch any negotiation step."

    Design: Corner/rbac/corner_rbac_faculty_can_request_equipment_but_cannot_place_the_order
    """
    scenario = fixtures.setup_mini_active(clock=CLOCK)
    space = fixtures.create_lab_space(building_code="BIOL", room_number="72")
    faculty_headers = make_faculty_headers(scenario["faculty_id"])

    order = validate_success(
        api_client.create_equipment_order(
            create_equipment_order_payload(scenario["package_id"], space["id"],
                                           quoted_cents=3_000_000),
            faculty_headers,
        ),
        expected_status=201,
    )
    assert order["status"] == "REQUESTED"

    package_version = fixtures.read_package(scenario["package_id"], faculty_headers)["version"]
    validate_error(
        api_client.place_equipment_order(
            order["id"], place_equipment_order_payload(package_version), faculty_headers
        ),
        "ERR_UNAUTHORIZED", expected_status=403,
    )

    unplaced = fixtures.read_order(order["id"])
    assert unplaced["status"] == "REQUESTED"
    assert unplaced["placed_on"] is None
    assert unplaced["expected_delivery_on"] is None
    assert_tranche_balances(fixtures.read_tranche(scenario["tranche"]["equipment"]["id"]),
                            encumbered_cents=0, available_balance_cents=20_000_000)
    assert fixtures.read_ledger(scenario["package_id"]) == []
    assert fixtures.read_package(scenario["package_id"])["version"] == package_version

    placed = validate_success(
        api_client.place_equipment_order(
            order["id"], place_equipment_order_payload(package_version),
            fixtures.DEAN_OFFICE,
        )
    )
    assert placed["status"] == "ORDERED"

    colleague = fixtures.create_candidate_faculty(scenario["department_id"],
                                                  full_name="Bo Nakamura")
    colleague_package = fixtures.create_draft_package(colleague["id"],
                                                      scenario["dean_office_id"])
    validate_error(
        api_client.create_equipment_order(
            create_equipment_order_payload(colleague_package["id"], space["id"],
                                           quoted_cents=1_000_000),
            faculty_headers,
        ),
        "ERR_FACULTY_SCOPE_VIOLATION", expected_status=403,
    )


def test_the_year_end_rollover_is_shared_by_the_dean_and_the_dean_office():
    """A shared operation that stays unit-scoped for the entity-backed role.

    PRD 3.9: "**Closing a fiscal year on a package** is a single deliberate operation,
    available to the dean's office and to the dean, that takes a fiscal_year label and
    reclassifies every tranche of that year. A Dean running it must be scoped to the
    package's college_unit_id."

    Design: Corner/rbac/corner_rbac_year_end_rollover_is_shared_by_dean_and_dean_office
    """
    scenario = fixtures.setup_mini_active(clock=CLOCK)
    package_id = scenario["package_id"]
    tranche_id = scenario["tranche"]["equipment"]["id"]
    fixtures.set_clock("2027-07-01T00:00:00Z")

    validate_success(api_client.year_end_rollover(package_id, {"fiscal_year": 2027},
                                                  fixtures.DEAN_OFFICE))
    assert_tranche_balances(fixtures.read_tranche(tranche_id), status="EXPIRED",
                            expired_cents=20_000_000, available_balance_cents=0)

    validate_error(
        api_client.year_end_rollover(package_id, {"fiscal_year": 2027},
                                     make_dean_headers(scenario["college_id"])),
        "ERR_ROLLOVER_ALREADY_RUN", expected_status=409,
    )
    for refused in (
        api_client.year_end_rollover(package_id, {"fiscal_year": 2027},
                                     make_department_chair_headers(scenario["department_id"])),
        api_client.year_end_rollover(package_id, {"fiscal_year": 2027}, fixtures.FACILITIES),
        api_client.year_end_rollover(package_id, {"fiscal_year": 2027},
                                     make_faculty_headers(scenario["faculty_id"])),
    ):
        validate_error(refused, "ERR_UNAUTHORIZED", expected_status=403)

    validate_error(
        api_client.year_end_rollover(package_id, {"fiscal_year": 2027},
                                     make_dean_headers(scenario["department_id"])),
        "ERR_UNIT_SCOPE_VIOLATION", expected_status=403,
    )

    expiries = rows_of_kind(fixtures.read_ledger(package_id), "EXPIRY")
    assert len(expiries) == 1
    assert expiries[0]["amount_cents"] == 20_000_000


def test_the_dean_cannot_approve_a_package_they_submitted_under_their_own_identity():
    """The approving identity must differ from both earlier signatures.

    PRD 2.1: "Segregation of duties is enforced across the three negotiation signatures.
    The user who endorses a package must differ from the proposed_by_user_id recorded at
    submit, and the user who approves it must differ from both proposed_by_user_id and
    endorsed_by_user_id. A violation of either constraint yields ERR_SEGREGATION_OF_DUTIES
    (HTTP 403)."

    Design: Corner/rbac/corner_rbac_same_user_cannot_submit_and_approve_the_same_package
    """
    scenario = fixtures.setup_draft_package(clock=CLOCK)
    package_id = scenario["package_id"]
    college_id = scenario["college_id"]
    department_id = scenario["department_id"]

    submitted = fixtures.submit_package(package_id,
                                        headers=make_dean_office_headers(college_id))
    assert submitted["proposed_by_user_id"] == college_id
    fixtures.endorse_package(package_id, department_id)

    validate_error(
        api_client.approve_startup_package(package_id, make_dean_headers(college_id)),
        "ERR_SEGREGATION_OF_DUTIES", expected_status=403,
    )

    package = fixtures.read_package(package_id)
    assert package["proposed_by_user_id"] == college_id
    assert package["endorsed_by_user_id"] == department_id
    assert package["approved_by_user_id"] is None
    assert package["negotiation_status"] == "DEAN_REVIEW"
    assert package["college_unit_id"] == college_id
    unit = fixtures.read_unit(department_id)
    assert unit["reserved_cents"] == 0
    assert package["spend_status"] == "NOT_YET_AVAILABLE"

    colleague = fixtures.create_candidate_faculty(department_id, full_name="Bo Nakamura")
    clean = fixtures.create_draft_package(colleague["id"], scenario["dean_office_id"])
    fixtures.add_tranche(clean["id"])
    fixtures.submit_package(clean["id"])
    fixtures.endorse_package(clean["id"], department_id)
    approved = validate_success(
        api_client.approve_startup_package(clean["id"], make_dean_headers(college_id))
    )
    assert approved["negotiation_status"] == "APPROVED"
