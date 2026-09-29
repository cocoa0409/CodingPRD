"""The top of the validation ladder: identity, role and existence.

Each test drives one triggerable error code and pins the successful call that
proves the request was otherwise well formed.
"""

from test_helpers import (
    api_client,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    counter_payload,
    create_renovation_phase_payload,
    place_equipment_order_payload,
    rescope_payload,
)
from test_helpers.test_users import (
    TEST_USERS,
    make_department_chair_headers,
    make_role_only_headers,
)

CLOCK = "2026-08-01T00:00:00Z"


def test_a_request_without_an_acting_identity_is_unauthenticated():
    """Both headers are mandatory, so an absent identity never reaches the resource.

    PRD 2.13: "ERR_UNAUTHENTICATED (401) — both X-User-Role and X-User-ID are present and
    X-User-Role is one of the five declared roles. Applies to every endpoint."

    Design: Corner/errors/corner_err_missing_x_user_id_header_returns_unauthenticated
    """
    scenario = fixtures.setup_draft_package(clock=CLOCK)
    package_id = scenario["package_id"]
    department_id = scenario["department_id"]

    validate_error(
        api_client.get_startup_package(package_id, make_role_only_headers("DepartmentChair")),
        "ERR_UNAUTHENTICATED", expected_status=401,
    )
    validate_error(
        api_client.get_startup_package(package_id, {"X-User-ID": department_id}),
        "ERR_UNAUTHENTICATED", expected_status=401,
    )
    validate_error(
        api_client.get_startup_package(
            package_id, {"X-User-ID": department_id, "X-User-Role": "Provost"}
        ),
        "ERR_UNAUTHENTICATED", expected_status=401,
    )

    with_identity = validate_success(
        api_client.get_startup_package(package_id, make_department_chair_headers(department_id))
    )
    assert with_identity["id"] == package_id
    assert with_identity["department_unit_id"] == department_id


def test_the_facilities_manager_is_not_a_signatory_on_the_negotiation():
    """A well-formed request from a role outside the endpoint's list is unauthorized.

    PRD 2.13: "ERR_UNAUTHORIZED (403) — the acting role appears in the called endpoint's
    authorised-role list. Applies to every endpoint."

    Design: Corner/errors/corner_err_facilities_manager_approving_a_package_returns_unauthorized
    """
    scenario = fixtures.setup_draft_package(clock=CLOCK)
    package_id = scenario["package_id"]
    fixtures.submit_package(package_id)
    endorsed = fixtures.endorse_package(package_id, scenario["department_id"])
    assert endorsed["negotiation_status"] == "DEAN_REVIEW"

    validate_error(
        api_client.approve_startup_package(package_id, fixtures.FACILITIES),
        "ERR_UNAUTHORIZED", expected_status=403,
    )
    for refused in (
        api_client.submit_startup_package(package_id, fixtures.FACILITIES),
        api_client.endorse_startup_package(package_id, fixtures.FACILITIES),
        api_client.counter_startup_package(package_id, counter_payload(15_000_000),
                                           fixtures.FACILITIES),
        api_client.close_out_startup_package(package_id, fixtures.FACILITIES),
    ):
        validate_error(refused, "ERR_UNAUTHORIZED", expected_status=403)

    package = fixtures.read_package(package_id)
    assert package["negotiation_status"] == "DEAN_REVIEW"
    assert package["approved_by_user_id"] is None
    assert fixtures.read_unit(scenario["department_id"])["reserved_cents"] == 0

    approved = fixtures.approve_package(package_id, scenario["college_id"])
    assert approved["negotiation_status"] == "APPROVED"
    assert fixtures.read_unit(scenario["department_id"])["reserved_cents"] == 9_000_000


UNKNOWN_PROJECT_ID = "11111111-1111-4111-8111-111111111111"
UNKNOWN_ORDER_ID = "22222222-2222-4222-8222-222222222222"


def test_an_unknown_renovation_project_is_reported_with_its_own_not_found_code():
    """Every verb under the project path resolves the project before anything else.

    PRD 2.13: "ERR_PROJECT_NOT_FOUND (404) — the RenovationProject named by the path id
    exists, and the RenovationPhase named by phase_id belongs to it. Applies to every
    /renovation-projects/{id}/... endpoint."

    Design: Corner/errors/corner_err_unknown_project_id_returns_project_not_found
    """
    fixtures.set_clock(CLOCK)

    validate_error(
        api_client.get_renovation_project(UNKNOWN_PROJECT_ID, fixtures.FACILITIES),
        "ERR_PROJECT_NOT_FOUND", expected_status=404,
    )
    for refused in (
        api_client.solicit_renovation_bids(UNKNOWN_PROJECT_ID, fixtures.FACILITIES),
        api_client.rescope_renovation_project(
            UNKNOWN_PROJECT_ID, rescope_payload(9_000_000, "GUT"), fixtures.FACILITIES
        ),
        api_client.create_renovation_phase(
            UNKNOWN_PROJECT_ID, create_renovation_phase_payload(), fixtures.FACILITIES
        ),
        api_client.substantial_completion(UNKNOWN_PROJECT_ID, fixtures.FACILITIES),
        api_client.list_renovation_phases(UNKNOWN_PROJECT_ID, fixtures.FACILITIES),
        api_client.award_renovation_project(
            UNKNOWN_PROJECT_ID, {"awarded_cents": 6_000_000}, TEST_USERS["dean_headers"]
        ),
    ):
        validate_error(refused, "ERR_PROJECT_NOT_FOUND", expected_status=404)

    listed, meta = validate_paginated(
        api_client.list_renovation_projects(fixtures.FACILITIES)
    )
    assert listed == []
    assert meta["total_count"] == 0


def test_an_unknown_equipment_order_is_reported_before_its_concurrency_guard():
    """The order is resolved at priority 11, long before the version guard at 16.

    PRD 2.13: "ERR_ORDER_NOT_FOUND (404) — the EquipmentOrder, StaffAppointment or
    SpaceAssignment named by the path id exists. Applies to every
    /equipment-orders/{id}/..., /staff-appointments/{id}/... and
    /space-assignments/{id}/... endpoint."

    Design: Corner/errors/corner_err_unknown_order_id_returns_order_not_found
    """
    fixtures.set_clock(CLOCK)

    validate_error(
        api_client.get_equipment_order(UNKNOWN_ORDER_ID, fixtures.FACILITIES),
        "ERR_ORDER_NOT_FOUND", expected_status=404,
    )
    for refused in (
        api_client.receive_equipment_order(UNKNOWN_ORDER_ID, fixtures.FACILITIES),
        api_client.install_equipment_order(UNKNOWN_ORDER_ID, fixtures.FACILITIES),
        api_client.cancel_equipment_order(UNKNOWN_ORDER_ID, fixtures.DEAN_OFFICE),
        api_client.place_equipment_order(
            UNKNOWN_ORDER_ID, place_equipment_order_payload(1), fixtures.DEAN_OFFICE
        ),
    ):
        validate_error(refused, "ERR_ORDER_NOT_FOUND", expected_status=404)

    listed, meta = validate_paginated(api_client.list_equipment_orders(fixtures.DEAN_OFFICE))
    assert listed == []
    assert meta["total_count"] == 0
