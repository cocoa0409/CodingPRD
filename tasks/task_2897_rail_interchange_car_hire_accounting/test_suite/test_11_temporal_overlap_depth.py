"""Two interval families with deliberately opposite endpoint conventions.

Reclaim windows are half-open, so one beginning exactly where another ends is a
second lawful claim; embargo intervals are closed and additionally demand a
24-hour gap, so two orders that merely touch already collide.
"""

from test_helpers import (
    ERR_EMBARGO_WINDOW_CONFLICT,
    ERR_RECLAIM_WINDOW_OVERLAP,
    ApiClient,
    assert_error_envelope,
    assert_hours,
    assert_instant_equals,
    assert_money,
    bad_order_band_world,
    file_reclaim,
    ids_of,
    issue_embargo,
    read_movement,
    register_car_type,
    set_clock,
    standard_world,
    validate_success,
)
import test_helpers.factories as f

BAND_FROM = "2026-08-24T12:00:00Z"
BAND_TO = "2026-08-27T12:00:00Z"
WINDOW_A_FROM = "2026-08-25T00:00:00Z"
WINDOW_A_TO = "2026-08-26T00:00:00Z"
WINDOW_B_FROM = "2026-08-26T00:00:00Z"
WINDOW_B_TO = "2026-08-27T00:00:00Z"
STRADDLING_FROM = "2026-08-25T12:00:00Z"
STRADDLING_TO = "2026-08-26T12:00:00Z"


def _two_touching_claims(api):
    """The 11464 segment carrying two abutting 24-hour BAD_ORDER claims."""
    world, movement = bad_order_band_world(api, report_at=BAND_FROM,
                                          release_at=BAND_TO)
    first = file_reclaim(api, world, movement, "BAD_ORDER",
                        WINDOW_A_FROM, WINDOW_A_TO)
    movement = read_movement(api, world, movement["id"])
    second = file_reclaim(api, world, movement, "BAD_ORDER",
                         WINDOW_B_FROM, WINDOW_B_TO)
    movement = read_movement(api, world, movement["id"])
    return world, movement, first, second


def _claims_on(api, world, movement_id):
    rows = validate_success(api.list_reclaim_claims(
        world.accountant(world.bn), params={"movement_id": movement_id}))
    return rows if isinstance(rows, list) else rows["items"]


class TestReclaimWindowsAreHalfOpen:
    """A window starting exactly where another ends does not overlap it."""

    def test_two_abutting_windows_both_survive_as_filed(self, api: ApiClient):
        """Claims over 08-25 to 08-26 and 08-26 to 08-27 coexist, 24.00 hours each.

        PRD: "The window must not overlap the window of any existing claim on the same segment whose `status` is `FILED` or `ALLOWED`; because windows are half-open, a claim beginning exactly when another ends does not overlap and is accepted, while one minute of genuine intersection is `ERR_RECLAIM_WINDOW_OVERLAP` — and claims that ended up `DISALLOWED` or `WITHDRAWN` release their window for re-filing."

        Design: Difficulty/resource_temporal_overlap/reclaim_windows_are_half_open_so_touching_endpoints_coexist
        """
        world, movement, first, second = _two_touching_claims(api)

        assert first["status"] == "FILED"
        assert second["status"] == "FILED"
        assert first["id"] != second["id"]
        assert_hours(first["claimed_hours"], 24.00, "first claimed_hours")
        assert_hours(second["claimed_hours"], 24.00, "second claimed_hours")
        assert_instant_equals(first["window_to"], second["window_from"],
                              "abutting endpoint")

        rows = _claims_on(api, world, movement["id"])
        assert len(rows) == 2
        assert ids_of(rows) == [first["id"], second["id"]]

        assert_money(movement["reclaim_credit_cents"], 0, "reclaim_credit_cents")
        assert_money(movement["net_hire_cents"], 11464, "net_hire_cents")

    def test_a_window_genuinely_intersecting_both_is_refused(self, api: ApiClient):
        """A window from 08-25T12:00 to 08-26T12:00 straddles both and is refused.

        PRD: "The window must not overlap the window of any existing claim on the same segment whose `status` is `FILED` or `ALLOWED`; because windows are half-open, a claim beginning exactly when another ends does not overlap and is accepted, while one minute of genuine intersection is `ERR_RECLAIM_WINDOW_OVERLAP` — and claims that ended up `DISALLOWED` or `WITHDRAWN` release their window for re-filing."

        Design: Difficulty/resource_temporal_overlap/reclaim_windows_are_half_open_so_touching_endpoints_coexist
        """
        world, movement, first, second = _two_touching_claims(api)

        refused = api.create_reclaim_claim(
            f.reclaim_payload(movement["id"], "BAD_ORDER", STRADDLING_FROM,
                              STRADDLING_TO, movement["version"]),
            world.accountant(world.bn),
        )
        assert_error_envelope(refused, ERR_RECLAIM_WINDOW_OVERLAP, 409)

        rows = _claims_on(api, world, movement["id"])
        assert len(rows) == 2
        assert ids_of(rows) == [first["id"], second["id"]]

        unchanged = read_movement(api, world, movement["id"])
        assert_money(unchanged["reclaim_credit_cents"], 0, "reclaim_credit_cents")
        assert_money(unchanged["net_hire_cents"], 11464, "net_hire_cents")


E1_FROM = "2026-08-20T00:00:00Z"
E1_TO = "2026-08-22T00:00:00Z"
TOUCHING_FROM = "2026-08-22T00:00:00Z"
TOUCHING_TO = "2026-08-23T00:00:00Z"
INSIDE_GAP_FROM = "2026-08-22T12:00:00Z"
INSIDE_GAP_TO = "2026-08-23T00:00:00Z"
CLEAR_OF_GAP_FROM = "2026-08-23T00:00:00Z"
CLEAR_OF_GAP_TO = "2026-08-24T00:00:00Z"


def _embargo_world(api):
    """Two car types at one junction with one ACTIVE XM order already standing."""
    world = standard_world(api, register_first_car=False)
    register_car_type(api, world, payload=f.flat_car_type_payload())
    set_clock(api, E1_FROM, world)
    first = issue_embargo(api, world, world.cx, world.jct, E1_FROM, E1_TO,
                         car_type_id=world.xm, reason="E1 yard congestion")
    return world, first


def _orders_for(api, world, car_type_id):
    rows = validate_success(api.list_embargo_orders(
        world.clerk(world.cx),
        params={"junction_id": world.jct, "car_type_id": car_type_id}))
    return rows if isinstance(rows, list) else rows["items"]


class TestEmbargoIntervalsAreClosedWithACoolingGap:
    """Touching endpoints collide, and so does anything inside the 24-hour gap."""

    def test_touching_and_gap_conflicts_yield_to_a_start_a_full_day_later(self, api: ApiClient):
        """08-22 and 08-22T12:00 starts are refused while the 08-23 start is ACTIVE.

        PRD: "A new order conflicts with an existing `ACTIVE` order for the same junction and car type when their closed intervals intersect, and also when the new interval starts within 24 hours of the existing order's `effective_to` — embargo orders carry a mandatory 24-hour cooling gap, so two orders that merely touch at their endpoints do conflict, even though two reclaim windows that touch do not."

        Design: Difficulty/resource_temporal_overlap/embargo_intervals_are_closed_and_carry_a_24_hour_cooling_gap
        """
        world, first = _embargo_world(api)
        assert first["status"] == "ACTIVE"
        assert_instant_equals(first["effective_to"], E1_TO, "effective_to")

        touching = api.create_embargo_order(
            f.embargo_payload(world.cx, world.jct, TOUCHING_FROM, TOUCHING_TO,
                              reason="E2 touching E1 effective_to",
                              car_type_id=world.xm),
            world.clerk(world.cx))
        assert_error_envelope(touching, ERR_EMBARGO_WINDOW_CONFLICT, 409)

        inside_gap = api.create_embargo_order(
            f.embargo_payload(world.cx, world.jct, INSIDE_GAP_FROM, INSIDE_GAP_TO,
                              reason="E3 inside the cooling gap",
                              car_type_id=world.xm),
            world.clerk(world.cx))
        assert_error_envelope(inside_gap, ERR_EMBARGO_WINDOW_CONFLICT, 409)

        clear = issue_embargo(api, world, world.cx, world.jct, CLEAR_OF_GAP_FROM,
                             CLEAR_OF_GAP_TO, car_type_id=world.xm,
                             reason="E4 a full cooling gap after E1")
        assert clear["status"] == "ACTIVE"
        assert_instant_equals(clear["effective_from"], CLEAR_OF_GAP_FROM,
                              "effective_from")

        rows = _orders_for(api, world, world.xm)
        assert ids_of(rows) == [first["id"], clear["id"]]

    def test_the_conflict_is_scoped_to_the_junction_and_car_type_pair(self, api: ApiClient):
        """The window refused for XM is granted for FB at the same junction.

        PRD: "An `InterchangeClerk` files it with the `issuing_road_id` — which must be the acting railroad and must be one of the junction's two connected roads, otherwise `ERR_EMBARGO_SELF_ISSUED` — the `junction_id` being closed, a `car_type_id` scoping the order to one mechanical type or left null to embargo every type at that junction, the interval bounds `effective_from` and `effective_to`, and the operating `reason` cited."

        Design: Difficulty/resource_temporal_overlap/embargo_intervals_are_closed_and_carry_a_24_hour_cooling_gap
        """
        world, first = _embargo_world(api)
        flat = world.car_types["FB"]
        assert flat != world.xm

        refused = api.create_embargo_order(
            f.embargo_payload(world.cx, world.jct, TOUCHING_FROM, TOUCHING_TO,
                              reason="E2 touching E1 effective_to",
                              car_type_id=world.xm),
            world.clerk(world.cx))
        assert_error_envelope(refused, ERR_EMBARGO_WINDOW_CONFLICT, 409)

        granted = issue_embargo(api, world, world.cx, world.jct, TOUCHING_FROM,
                                TOUCHING_TO, car_type_id=flat,
                                reason="E5 same window, other car type")
        assert granted["status"] == "ACTIVE"
        assert granted["car_type_id"] == flat

        assert ids_of(_orders_for(api, world, world.xm)) == [first["id"]]
        assert ids_of(_orders_for(api, world, flat)) == [granted["id"]]
