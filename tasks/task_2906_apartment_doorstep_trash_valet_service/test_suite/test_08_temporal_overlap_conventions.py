"""Two interval rules with opposite endpoint conventions: valet windows and contract periods."""

from test_helpers import (
    ANALYST_DRAFTER,
    VALET_OPS_MANAGER,
    ApiErrorId,
    api_client,
    factories,
    fixtures,
    validate_error,
    validate_success,
)

WINDOW_A = ("2026-09-01T18:00:00.000Z", "2026-09-02T04:00:00.000Z")
WINDOW_B = ("2026-09-02T02:00:00.000Z", "2026-09-02T10:00:00.000Z")
WINDOW_C = ("2026-09-02T04:00:00.000Z", "2026-09-02T12:00:00.000Z")


# --------------------------------------------------------------------------
# A valet's service windows are half-open [start, end)
# --------------------------------------------------------------------------
def _three_windows_one_of_them_walked(name="Harbour Lofts"):
    """Night A is being walked; nights B and C differ only in their start instant."""
    world = fixtures.build_active_community(
        name=name, unit_count=4, resident_units=()
    )
    nights = {}
    for key, service_date, window in (
        ("a", "2026-09-01", WINDOW_A),
        ("b", "2026-09-02", WINDOW_B),
        ("c", "2026-09-02", WINDOW_C),
    ):
        nights[key] = fixtures.schedule_night(
            world["contract"]["id"],
            service_date,
            service_window_start=window[0],
            service_window_end=window[1],
        )
    world["route_a"] = fixtures.assign_route(
        nights["a"]["id"], world["contractor"]["id"], 101, 104
    )
    world["nights"] = nights
    return world


def _dispatch(world, night, expected_version=None):
    return api_client.create_route_assignment(
        night["id"],
        factories.route_payload(
            world["contractor"]["id"],
            101,
            104,
            expected_version if expected_version is not None else night["version"],
        ),
        VALET_OPS_MANAGER,
    )


def test_a_window_starting_strictly_inside_a_walked_window_conflicts():
    """02:00 lies inside [18:00, 04:00), so the same valet cannot take night B.

    PRD 2.5: "**Contractor window conflict.** The contractor must hold no other
    route assignment in `ASSIGNED`, `ACCEPTED` or `IN_PROGRESS` whose night's
    service window intersects this night's window — otherwise
    `ERR_CONTRACTOR_WINDOW_CONFLICT` (409). Applies to route-assignment
    creation."

    Design: Difficulty/resource_temporal_overlap/contractor_service_windows_are_half_open_so_touching_boundary_is_allowed
    """
    world = _three_windows_one_of_them_walked()
    night_b = world["nights"]["b"]

    response = _dispatch(world, night_b)

    validate_error(response, ApiErrorId.ERR_CONTRACTOR_WINDOW_CONFLICT.value, 409)
    refused = fixtures.read_night(night_b["id"])
    assert refused["assigned_unit_coverage_count"] == 0
    assert refused["version"] == night_b["version"]


def test_a_window_starting_at_the_excluded_upper_endpoint_is_accepted():
    """04:00 is the instant night A's window ends, so touching is not overlapping.

    PRD 3.5: "The valet must not already hold a route in `ASSIGNED`, `ACCEPTED`
    or `IN_PROGRESS` on a night whose half-open service window intersects this
    night's window, or `ERR_CONTRACTOR_WINDOW_CONFLICT` — and because the windows
    are half-open, back-to-back rounds where one ends at the exact instant the
    next begins do not conflict."

    Design: Difficulty/resource_temporal_overlap/contractor_service_windows_are_half_open_so_touching_boundary_is_allowed
    """
    world = _three_windows_one_of_them_walked()
    night_c = world["nights"]["c"]

    route_c = validate_success(_dispatch(world, night_c), expected_status=201)

    assert route_c["status"] == "ASSIGNED"
    assert fixtures.read_night(night_c["id"])["assigned_unit_coverage_count"] == 4
    held = {
        route["id"]
        for route in fixtures.list_routes(
            {"contractor_id": world["contractor"]["id"]}
        )
    }
    assert held == {world["route_a"]["id"], route_c["id"]}


# --------------------------------------------------------------------------
# A contract's effective period is closed on both ends
# --------------------------------------------------------------------------
def _incumbent_contract_through_next_august(name="Sequoia Place"):
    fixtures.set_clock("2026-08-15T00:00:00Z")
    prop = fixtures.create_property(name=name, unit_count=4)
    contract = fixtures.draft_contract(
        prop["id"], effective_from="2026-09-01", effective_to="2027-08-31"
    )
    fixtures.activate_contract(contract["id"])
    return {"property": prop, "contract": fixtures.read_contract(contract["id"])}


def _draft_successor(property_id, effective_from, effective_to="2028-08-30"):
    return api_client.create_contract(
        property_id,
        factories.contract_payload(
            per_unit_monthly_fee_cents=3695,
            property_revenue_share_bps=1600,
            effective_from=effective_from,
            effective_to=effective_to,
        ),
        ANALYST_DRAFTER,
    )


def test_a_successor_starting_on_the_incumbents_final_day_overlaps():
    """One shared calendar day is an intersection because both endpoints are inclusive.

    PRD 3.1: "Because both interval endpoints are inclusive, two contracts of the
    same community that merely share a single boundary date do overlap. A draft
    whose closed period intersects the closed period of any existing contract of
    that community whose `status` is `DRAFT` or `ACTIVE` is rejected with
    `ERR_CONTRACT_PERIOD_OVERLAP`; a new period starting on the exact day an
    existing period ends is an intersection, not an adjacency."

    Design: Difficulty/resource_temporal_overlap/contract_effective_intervals_are_closed_so_shared_endpoint_date_collides
    """
    world = _incumbent_contract_through_next_august()

    response = _draft_successor(world["property"]["id"], "2027-08-31")

    validate_error(response, ApiErrorId.ERR_CONTRACT_PERIOD_OVERLAP.value, 409)
    incumbent = fixtures.read_contract(world["contract"]["id"])
    assert incumbent["effective_to"] == "2027-08-31"
    assert incumbent["version"] == world["contract"]["version"]
    assert len(fixtures.list_contracts({"property_id": world["property"]["id"]})) == 1


def test_a_successor_starting_the_day_after_is_accepted():
    """Moving the start one day later removes the shared endpoint and the collision.

    PRD 2.5: "**Contract period overlap.** The new contract's closed date
    interval must not intersect the interval of any existing contract of the same
    property whose `status` is `DRAFT` or `ACTIVE` — otherwise
    `ERR_CONTRACT_PERIOD_OVERLAP` (409). Applies to contract drafting."

    Design: Difficulty/resource_temporal_overlap/contract_effective_intervals_are_closed_so_shared_endpoint_date_collides
    """
    world = _incumbent_contract_through_next_august()
    _draft_successor(world["property"]["id"], "2027-08-31")

    successor = validate_success(
        _draft_successor(world["property"]["id"], "2027-09-01"), expected_status=201
    )

    assert successor["status"] == "DRAFT"
    assert successor["effective_from"] == "2027-09-01"
    assert successor["effective_to"] == "2028-08-30"
    by_id = {
        contract["id"]: contract["status"]
        for contract in fixtures.list_contracts(
            {"property_id": world["property"]["id"]}
        )
    }
    assert by_id == {
        world["contract"]["id"]: "ACTIVE",
        successor["id"]: "DRAFT",
    }
