"""Capacity windows and the reservations held against them."""
from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers.fixtures import (
    CLOCK_START,
    FULFILLMENT,
    create_capacity,
    create_design,
    create_licensor,
    create_run,
    get_capacity,
    reserve_capacity,
    set_clock,
)


def test_a_new_window_opens_with_all_of_its_capacity_available(api):
    """PRD §2.9: "A new window starts with `reserved_qty` at 0 and `available_qty`
    equal to its `capacity_qty`."

    Design: Corner/entities/print_capacity_defaults_capacity_floor
    """
    set_clock(api)
    window = create_capacity(api, capacity_qty=20)

    assert window["reserved_qty"] == 0
    assert window["available_qty"] == 20
    assert window["capacity_qty"] == 20
    assert window["rush_sla_hours"] == 24

    read = get_capacity(api, window["id"])
    assert read["reserved_qty"] == 0
    assert read["available_qty"] == 20


def test_a_reservation_within_the_window_start_is_classified_rush(api):
    """PRD §3.4: "when that span is 24 hours or fewer the reservation is a rush
    reservation and its units join the rush total; when the span is longer the
    reservation is a standard one and its units join the standard total — the
    24-hour boundary belongs to rush"

    Design: Difficulty/boundary_precision_check/reservation_hour_boundary_at_rush_sla_edge
    """
    set_clock(api)
    window = create_capacity(
        api, city_code="ATL", print_type="BASE",
        window_start="2026-09-01T01:00:00Z", window_end="2026-09-02T01:00:00Z",
        capacity_qty=40, rush_sla_hours=24,
    )

    rush = reserve_capacity(
        api, window["id"], quantity=20, rush_flag=True,
        needed_by="2026-09-02T00:00:00Z",
    )

    assert rush["reservation_state"] == "HELD"
    assert rush["quantity"] == 20
    assert rush["print_capacity_id"] == window["id"]


def test_a_reservation_beyond_the_window_start_is_accepted_as_standard(api):
    """PRD §2.9: "A window whose `window_end` is not strictly after its
    `window_start`, whose `capacity_qty` is not strictly positive, or whose
    `rush_sla_hours` is not strictly positive is a request-shape failure."
    PRD §3.4: "the 24-hour boundary belongs to rush, and 72 hours is the standard
    window length the classification is calibrated against"

    Design: Difficulty/boundary_precision_check/reservation_hour_boundary_at_rush_sla_edge
    """
    set_clock(api)
    window = create_capacity(
        api, city_code="ATL", print_type="BASE",
        window_start="2026-09-01T01:00:00Z", window_end="2026-09-02T01:00:00Z",
        capacity_qty=40, rush_sla_hours=24,
    )

    reserve_capacity(api, window["id"], quantity=20, rush_flag=True,
                     needed_by="2026-09-02T00:00:00Z")
    standard = reserve_capacity(api, window["id"], quantity=20, rush_flag=False,
                                needed_by="2026-09-02T02:00:00Z")

    assert standard["reservation_state"] == "HELD"
    assert standard["quantity"] == 20

    capacity = get_capacity(api, window["id"])
    assert capacity["reserved_qty"] == 40
    assert capacity["available_qty"] == 0


def test_a_reservation_whose_needed_by_precedes_the_window_start_is_refused(api):
    """PRD §3.4: "a reservation that no window can start early enough to serve
    under the rush service level is refused with `ERR_RUSH_COMMITMENT_BREACH`
    (HTTP 422)"

    Design: Difficulty/resource_temporal_overlap/reservation_needed_by_buffer_convention
    """
    set_clock(api)
    window = create_capacity(
        api, city_code="BOS", print_type="EMBROIDER",
        window_start="2026-09-01T02:00:00Z", window_end="2026-09-01T10:00:00Z",
        capacity_qty=40, rush_sla_hours=6,
    )

    accepted = reserve_capacity(
        api, window["id"], quantity=10, rush_flag=True,
        needed_by="2026-09-01T08:00:00Z",
    )
    assert accepted["reservation_state"] == "HELD"
    assert accepted["needed_by"] == "2026-09-01T08:00:00Z"

    resp = api.reserve_capacity(
        {
            "print_capacity_id": window["id"],
            "quantity": 10,
            "rush_flag": True,
            "needed_by": "2026-09-01T01:00:00Z",
        },
        FULFILLMENT,
    )
    validate_error(resp, ApiErrorId.ERR_RUSH_COMMITMENT_BREACH,
                   expected_status=422)

    assert get_capacity(api, window["id"])["reserved_qty"] == 10


def test_a_reservation_that_overflows_the_window_is_refused(api):
    """PRD §2.9: "when the requested `quantity` exceeds the window's remaining
    `available_qty`, the request fails with `ERR_CAPACITY_EXCEEDED` (HTTP 409)"
    PRD §2.9: "A window's `reserved_qty` is the sum of the `quantity` of its
    `HELD` reservations processed in that order, and `available_qty` is its
    `capacity_qty` less its `reserved_qty`."

    Design: Difficulty/resource_temporal_overlap/print_capacity_aggregate_ceiling
    """
    set_clock(api)
    window = create_capacity(
        api, city_code="PHI", print_type="BASE",
        window_start="2026-09-01T01:00:00Z", window_end="2026-09-02T01:00:00Z",
        capacity_qty=20, rush_sla_hours=24,
    )
    first = reserve_capacity(api, window["id"], quantity=15, rush_flag=True,
                             needed_by="2026-09-01T20:00:00Z")
    assert first["reservation_state"] == "HELD"

    resp = api.reserve_capacity(
        {
            "print_capacity_id": window["id"],
            "quantity": 10,
            "rush_flag": True,
            "needed_by": "2026-09-01T20:00:00Z",
        },
        FULFILLMENT,
    )
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED, expected_status=409)

    capacity = get_capacity(api, window["id"])
    assert capacity["reserved_qty"] == 15
    assert capacity["available_qty"] == 5


def test_a_run_created_before_any_reservation_holds_zero_rush_points(api):
    """PRD §3.4: "It is written at run creation from whatever reservations are
    already held — zero when none are — and recomputed whenever a reservation is
    placed and on every re-evaluation of a printing run's delivery commitment."

    Design: Corner/calculations/rush_or_standard_commitment_ignores_unheld_reservations
    """
    set_clock(api, CLOCK_START)
    licensor = create_licensor(api, name="Licensor Q", royalty_rate_pct=0.1)
    design = create_design(api, licensor, team_code="PHI", garment_sku="CAP",
                           design_name="Q Cap")
    window = create_capacity(api, city_code="PHI", print_type="BASE",
                             capacity_qty=100, rush_sla_hours=24)

    run = create_run(
        api, licensor, design, team_code="PHI", trigger_type="CHAMPIONSHIP_WIN",
        event_outcome="WIN_FAVORED_TEAM", expected_demand_qty=2000,
        unit_cost_cents=900, win_probability_pct=0.5,
        outcome_at="2026-09-01T06:00:00Z",
    )

    assert run["rush_delivery_points"] == 0
    capacity = get_capacity(api, window["id"])
    assert capacity["reserved_qty"] == 0
    assert capacity["available_qty"] == 100


def test_a_reservation_immediately_consumes_its_window_capacity(api):
    """PRD §2.9: "A reservation is created with its `reservation_state` in `HELD`,
    stamped with `reserved_at`, and immediately adds its `quantity` to the
    window's `reserved_qty` with `available_qty` recomputed."

    Design: Difficulty/resource_temporal_overlap/reservation_needed_by_buffer_convention
    """
    set_clock(api)
    window = create_capacity(
        api, city_code="BOS", print_type="EMBROIDER",
        window_start="2026-09-01T02:00:00Z", window_end="2026-09-01T10:00:00Z",
        capacity_qty=40, rush_sla_hours=6,
    )

    reserved = reserve_capacity(api, window["id"], quantity=10, rush_flag=True,
                                needed_by="2026-09-01T02:00:00Z")
    assert reserved["reservation_state"] == "HELD"

    capacity = get_capacity(api, window["id"])
    assert capacity["reserved_qty"] == 10
    assert capacity["available_qty"] == 30


def test_a_window_whose_end_is_not_after_its_start_is_a_shape_failure(api):
    """PRD §2.9: "A window whose `window_end` is not strictly after its
    `window_start` ... is a request-shape failure."
    PRD §2.10: "a failure is reported as `ERR_INVALID_REQUEST` (HTTP 400)"

    Design: Corner/entities/print_capacity_defaults_capacity_floor
    """
    set_clock(api)

    resp = api.create_print_capacity(
        {
            "city_code": "ATL",
            "print_type": "BASE",
            "window_start": "2026-09-01T10:00:00Z",
            "window_end": "2026-09-01T01:00:00Z",
            "capacity_qty": 20,
            "rush_sla_hours": 24,
        },
        FULFILLMENT,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_reservations_are_listed_against_their_window(api):
    """PRD §4: "GET | `/print-capacity/{id}/reservations` | List the reservations
    held against one capacity window | FulfillmentCoordinator, AuditOnly"

    Design: Difficulty/resource_temporal_overlap/print_capacity_aggregate_ceiling
    """
    set_clock(api)
    window = create_capacity(api, capacity_qty=40)
    first = reserve_capacity(api, window["id"], quantity=15, rush_flag=True,
                             needed_by="2026-09-01T20:00:00Z")

    resp = validate_success(
        api.list_reservations(window["id"], FULFILLMENT), expected_status=200,
    )
    assert isinstance(resp, list)
    assert first["id"] in [row["id"] for row in resp]