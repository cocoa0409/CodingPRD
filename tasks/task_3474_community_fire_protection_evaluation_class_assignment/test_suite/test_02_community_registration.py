"""Community registration: defaults, shell seeding, required inputs, listing."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    create_community,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["evaluation_coordinator_headers"]

_BASE = {
    "name": "Shellby", "state_code": "TX", "population": 4000,
    "area_sq_miles": 40, "rural_area_pct": 20, "dept_type": "CAREER",
    "needed_fire_flow_gpm": 1000, "storage_capacity_gal": 0,
    "supply_works_capacity_gpm": 500, "daily_consumption_gpm": 100,
}


def _payload(**overrides):
    payload = dict(_BASE)
    payload.update(overrides)
    return payload


def test_community_create_returns_201_with_defaults_and_shells(api):
    """PRD §3.1: "A freshly registered community is in `REGISTERED` status;
    its `current_class_number`, `current_split_class`,
    `current_premium_modifier`, and `next_evaluation_due_date` are all null
    until a first classification is activated, and its `bound_exposure_cents`
    ledger starts at 0."

    Design: Corner/entities/community_create_returns_201_with_defaults_and_shells
    """
    resp = api.create_community(_payload(), COORD)
    community = validate_success(resp, 201)
    assert community["id"]
    assert community["created_at"]
    assert community["version"] == 1
    assert community["status"] == "REGISTERED"
    assert community["current_class_number"] is None
    assert community["bound_exposure_cents"] == 0
    assert community["comms_attested"] is False

    departments = get_success_data(
        api.list_fire_departments(COORD, params={"community_id": community["id"]})
    )
    assert len(departments) == 1, "registration seeds exactly one department shell"
    assert departments[0]["community_id"] == community["id"]
    assert departments[0]["dept_type"] == "CAREER"
    assert departments[0]["data_submitted"] is False

    systems = get_success_data(
        api.list_water_supply_systems(COORD, params={"community_id": community["id"]})
    )
    assert len(systems) == 1, "registration seeds exactly one water system shell"
    assert systems[0]["community_id"] == community["id"]
    assert systems[0]["needed_fire_flow_gpm"] == 1000
    assert systems[0]["alternate_verified"] is False


def test_community_create_missing_required_field_returns_invalid_request(api):
    """PRD §3.1: registration supplies "its **FireDepartment**, created with
    the `dept_type` supplied at registration (`CAREER`, `VOLUNTEER`, or
    `COMBINATION`, which later selects the staffing scoring variant)" — the
    field has no default, so omitting it fails the structural payload rung
    with ERR_INVALID_REQUEST.

    Design: Corner/entities/community_create_missing_required_field_returns_invalid_request
    """
    payload = _payload()
    del payload["dept_type"]
    resp = api.create_community(payload, COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    rows, meta = validate_paginated(api.list_communities(COORD))
    assert meta["total_count"] == 0, "no Community may be created"


def test_community_create_invalid_enum_returns_invalid_request(api):
    """PRD §3.1: the department is "created with the `dept_type` supplied at
    registration (`CAREER`, `VOLUNTEER`, or `COMBINATION`, which later
    selects the staffing scoring variant)" — a value outside that set is
    rejected with ERR_INVALID_REQUEST.

    Design: Corner/entities/community_create_invalid_enum_returns_invalid_request
    """
    resp = api.create_community(_payload(name="BadEnum", dept_type="PAID"), COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_community_get_not_found_returns_404(api):
    """PRD §2.11: "identifiers are validated in left-to-right order along the
    request, and the first identifier that matches nothing produces that
    resource type's own 404 — respectively `ERR_COMMUNITY_NOT_FOUND`".

    Design: Corner/entities/community_get_not_found_returns_404
    """
    resp = api.get_community(NON_EXISTENT_UUID, COORD)
    validate_error(resp, ApiErrorId.ERR_COMMUNITY_NOT_FOUND)


def test_communities_list_pagination_limit_offset(api):
    """PRD §2.3: "Paginated list responses carry `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/communities_list_pagination_limit_offset
    """
    for name in ("P1", "P2", "P3"):
        create_community(api, name=name, population=1000, area_sq_miles=10,
                         rural_area_pct=10, daily_consumption_gpm=50)
    page1, meta1 = validate_paginated(api.list_communities(COORD, params={"limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    page2, meta2 = validate_paginated(api.list_communities(COORD, params={"limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_community_create_missing_auth_returns_unauthenticated(api):
    """PRD §2.1: "A request that omits either header, or presents a role name
    the server does not recognize, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/validations/community_create_missing_auth_returns_unauthenticated
    """
    resp = api.create_community(_payload(name="NoAuth"), None)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_community_create_nff_below_range_returns_invalid_request(api):
    """PRD §3.1: the water system is seeded with "`needed_fire_flow_gpm`
    (the community's needed fire flow, between 500 and 50000 inclusive)" —
    100 falls below the floor and is rejected with ERR_INVALID_REQUEST.

    Design: Corner/validations/community_create_nff_below_range_returns_invalid_request
    """
    resp = api.create_community(_payload(name="LowFlow", needed_fire_flow_gpm=100), COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
