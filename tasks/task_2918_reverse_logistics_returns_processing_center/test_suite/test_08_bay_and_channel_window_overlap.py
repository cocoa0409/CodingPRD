"""Two overlap rules with deliberately opposite endpoint semantics.

Quarantine occupations of a bay are half-open, so touching ends are admitted.
Channel lot windows are closed on both endpoints, so touching ends collide —
and the channel rule is an aggregate count rather than a pairwise veto.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_BAY_WINDOW_CONFLICT,
    ERR_CHANNEL_WINDOW_CAPACITY_EXCEEDED,
)
from test_helpers.assertions import (
    assert_instant_equals,
    assert_line_states,
    assert_money,
    assert_unit_buckets,
)
from test_helpers.constants import (
    CHANNEL_WINDOW_A_END,
    CHANNEL_WINDOW_A_START,
    CHANNEL_WINDOW_B_END,
    CHANNEL_WINDOW_B_START,
    CHANNEL_WINDOW_C_END,
    CHANNEL_WINDOW_C_START,
    DO_PROPOSED,
    DS_DISPOSITION_ASSIGNED,
    DS_QUARANTINED,
    DS_RECEIVED_UNGRADED,
    GRADE_C,
    HAZARD_LITHIUM_BATTERY,
    QUARANTINE_WINDOW_A_END,
    QUARANTINE_WINDOW_A_START,
    QUARANTINE_WINDOW_B_END,
    QUARANTINE_WINDOW_B_START,
    QUARANTINE_WINDOW_OVERLAP_END,
    QUARANTINE_WINDOW_OVERLAP_START,
    REASON_DEFECTIVE,
)
from test_helpers.test_users import ADMIN, GRADER, SUPERVISOR

THREE_LINES = [
    {"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE},
    {"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE},
    {"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE},
]


def _hazmat_world(api, client_code, bay_code="HZ1"):
    """Three lithium-cell lines awaiting quarantine, plus one zero-buffer bay.

    The bay's `buffer_minutes` is zero on purpose: the buffer widening is a
    refurbishment-test rule and must not reach quarantine occupations.
    """
    world = fx.received_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs(client_code, name="Hazmat Client"),
        items=[
            fx.widget_item_kwargs(
                sku="CELL-1",
                description="Lithium cell pack",
                hazard_class=HAZARD_LITHIUM_BATTERY,
            )
        ],
        lines=THREE_LINES,
    )
    assert world["expected_weight_grams"] == 3800
    world["bay"] = fx.make_hazmat_bay(api, bay_code=bay_code, buffer_minutes=0)
    for line in world["lines"]:
        assert_line_states(line, disposition_state=DS_RECEIVED_UNGRADED)
    return world


def test_an_occupation_starting_exactly_when_another_ends_is_admitted(api):
    """PRD §3.3: "The requested occupation is half-open — it includes its start
    instant and excludes its end instant — and must not overlap any other line's
    occupation of the same bay, which means two occupations collide when the new
    start precedes the existing end and the existing start precedes the new
    end."

    Design: Difficulty/resource_temporal_overlap/quarantine_bay_half_open_windows_admit_touching_ends
    """
    world = _hazmat_world(api, "CLHAZ")
    bay_id = world["bay"]["id"]

    first = fx.quarantine_line(
        api,
        world["lines"][0]["id"],
        bay_id,
        QUARANTINE_WINDOW_A_START,
        QUARANTINE_WINDOW_A_END,
        headers=GRADER,
    )
    assert_line_states(first, disposition_state=DS_QUARANTINED)
    assert first["bay_id"] == bay_id
    assert_instant_equals(
        first["quarantine_start_at"], QUARANTINE_WINDOW_A_START, "quarantine_start_at"
    )
    assert_instant_equals(
        first["quarantine_end_at"], QUARANTINE_WINDOW_A_END, "quarantine_end_at"
    )

    # The second occupation starts at the exact instant the first one ends, and
    # 12:00 preceding 12:00 is false in both directions of the collision test.
    second = fx.quarantine_line(
        api,
        world["lines"][1]["id"],
        bay_id,
        QUARANTINE_WINDOW_B_START,
        QUARANTINE_WINDOW_B_END,
        headers=GRADER,
    )
    assert_line_states(second, disposition_state=DS_QUARANTINED)
    assert second["bay_id"] == bay_id
    assert_instant_equals(
        second["quarantine_start_at"], QUARANTINE_WINDOW_B_START, "quarantine_start_at"
    )
    assert second["version"] > world["lines"][1]["version"]


def test_one_minute_of_overlap_is_enough_to_refuse_a_third_occupation(api):
    """PRD §2.6: "Occupations are half-open on the interval from
    `quarantine_start_at` up to but excluding `quarantine_end_at`: two
    occupations collide when the new start precedes the existing end and the
    existing start precedes the new end, so an occupation that begins exactly
    when another ends is accepted."

    Design: Difficulty/resource_temporal_overlap/quarantine_bay_half_open_windows_admit_touching_ends
    """
    world = _hazmat_world(api, "CLHAZ2")
    bay_id = world["bay"]["id"]
    fx.quarantine_line(
        api,
        world["lines"][0]["id"],
        bay_id,
        QUARANTINE_WINDOW_A_START,
        QUARANTINE_WINDOW_A_END,
        headers=GRADER,
    )
    fx.quarantine_line(
        api,
        world["lines"][1]["id"],
        bay_id,
        QUARANTINE_WINDOW_B_START,
        QUARANTINE_WINDOW_B_END,
        headers=GRADER,
    )

    # 11:59 precedes the first occupation's 12:00 end and its 08:00 start
    # precedes 15:00, so the pair collides on a single minute.
    third = world["lines"][2]
    response = api.quarantine_line(
        third["id"],
        f.quarantine_payload(
            bay_id,
            QUARANTINE_WINDOW_OVERLAP_START,
            QUARANTINE_WINDOW_OVERLAP_END,
        ),
        GRADER,
    )
    validate_error(response, ERR_BAY_WINDOW_CONFLICT, 409)

    unchanged = fx.read_return_line(api, third["id"])
    assert_line_states(unchanged, disposition_state=DS_RECEIVED_UNGRADED)
    assert unchanged["bay_id"] is None
    assert unchanged["quarantine_start_at"] is None
    assert unchanged["quarantine_end_at"] is None
    assert unchanged["version"] == third["version"]


def _lot_window_world(api, client_code, channel_code="AUC2", capacity=2):
    """Three graded-C liquidation lines and one channel of the given capacity."""
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs(
            client_code, name="Lot Window Client"
        ),
        items=[fx.widget_item_kwargs()],
        lines=THREE_LINES,
        condition_grade=GRADE_C,
    )
    assert world["expected_weight_grams"] == 3800
    world["channel"] = fx.make_channel(
        api,
        **fx.auction_channel_kwargs(
            channel_code, name="Two Lot Auction", concurrent_lot_capacity=capacity
        )
    )
    for line in world["lines"]:
        assert_line_states(line, disposition_state=DS_DISPOSITION_ASSIGNED)
        assert_money(line["recovery_value_cents"], 7200, "provisional recovery")
    return world


def _propose_in_window(api, world, line_index, start_at, end_at):
    """Raw disposition-order creation for one line over one lot window."""
    line = fx.read_return_line(api, world["lines"][line_index]["id"])
    return api.create_disposition_order(
        f.disposition_order_payload(
            line["id"],
            line["version"],
            channel_id=world["channel"]["id"],
            channel_window_start_at=start_at,
            channel_window_end_at=end_at,
        ),
        SUPERVISOR,
    )


def test_two_lot_windows_touching_at_an_endpoint_fill_a_capacity_of_two(api):
    """PRD §2.6: "Channel lot windows are closed on the interval from
    `channel_window_start_at` through `channel_window_end_at` inclusive, so two
    windows that merely touch at an endpoint do overlap — unlike bay
    occupations."

    Design: Difficulty/resource_temporal_overlap/channel_lot_windows_closed_endpoints_overlap_and_capacity_counts_the_new_order
    """
    world = _lot_window_world(api, "CLLOT")

    first = validate_success(
        _propose_in_window(api, world, 0, CHANNEL_WINDOW_A_START, CHANNEL_WINDOW_A_END),
        201,
    )
    assert first["status"] == DO_PROPOSED

    # 12:00 is inside both closed windows, so admission is 1 for the new order
    # plus 1 overlapping PROPOSED order, landing exactly on the capacity of two.
    second = validate_success(
        _propose_in_window(api, world, 1, CHANNEL_WINDOW_B_START, CHANNEL_WINDOW_B_END),
        201,
    )
    assert second["status"] == DO_PROPOSED

    on_channel = get_success_data(
        api.list_disposition_orders(
            ADMIN, {"channel_id": world["channel"]["id"], "limit": 100}
        )
    )
    assert len(on_channel) == 2


def test_a_third_overlapping_window_breaks_the_aggregate_capacity(api):
    """PRD §2.6: "Priority 57 enforces channel lot capacity by a pinned
    admission formula: one, for the order being created, plus the count of
    `PROPOSED` or `APPROVED` disposition orders on the resolved channel whose
    lot window overlaps the requested one, must be no greater than the channel's
    `concurrent_lot_capacity`."

    Design: Difficulty/resource_temporal_overlap/channel_lot_windows_closed_endpoints_overlap_and_capacity_counts_the_new_order
    """
    world = _lot_window_world(api, "CLLOT2")
    validate_success(
        _propose_in_window(api, world, 0, CHANNEL_WINDOW_A_START, CHANNEL_WINDOW_A_END),
        201,
    )
    validate_success(
        _propose_in_window(api, world, 1, CHANNEL_WINDOW_B_START, CHANNEL_WINDOW_B_END),
        201,
    )

    # 12:00 through 14:00 touches the first window at 12:00 and lies inside the
    # second, so admission is 1 + 2 == 3 against a capacity of 2.
    response = _propose_in_window(
        api, world, 2, CHANNEL_WINDOW_C_START, CHANNEL_WINDOW_C_END
    )
    validate_error(response, ERR_CHANNEL_WINDOW_CAPACITY_EXCEEDED, 409)

    on_channel = get_success_data(
        api.list_disposition_orders(
            ADMIN, {"channel_id": world["channel"]["id"], "limit": 100}
        )
    )
    assert len(on_channel) == 2, "the refused proposal may not create an order"
    assert fx.orders_for_line(api, world["lines"][2]["id"]) == []

    third = fx.read_return_line(api, world["lines"][2]["id"])
    assert_line_states(third, disposition_state=DS_DISPOSITION_ASSIGNED)
    client = fx.read_client(api, world["client"]["id"])
    assert_unit_buckets(client, received=3, in_process=1, reserved=2, dispositioned=0)


def test_the_refused_window_is_admissible_on_a_channel_of_its_own(api):
    """PRD §2.6: "The check is an aggregate one: each existing order can be
    individually admissible while the collection is not."

    Design: Difficulty/resource_temporal_overlap/channel_lot_windows_closed_endpoints_overlap_and_capacity_counts_the_new_order
    """
    world = _lot_window_world(api, "CLLOT3")
    validate_success(
        _propose_in_window(api, world, 0, CHANNEL_WINDOW_A_START, CHANNEL_WINDOW_A_END),
        201,
    )
    validate_success(
        _propose_in_window(api, world, 1, CHANNEL_WINDOW_B_START, CHANNEL_WINDOW_B_END),
        201,
    )
    validate_error(
        _propose_in_window(
            api, world, 2, CHANNEL_WINDOW_C_START, CHANNEL_WINDOW_C_END
        ),
        ERR_CHANNEL_WINDOW_CAPACITY_EXCEEDED,
        409,
    )

    # An empty channel of the same capacity admits the identical window, so the
    # window itself was never the problem: the tally on the first channel was.
    spare = fx.make_channel(
        api,
        **fx.auction_channel_kwargs(
            "AUC3", name="Spare Auction", concurrent_lot_capacity=2
        )
    )
    line = fx.read_return_line(api, world["lines"][2]["id"])
    admitted = validate_success(
        api.create_disposition_order(
            f.disposition_order_payload(
                line["id"],
                line["version"],
                channel_id=spare["id"],
                channel_window_start_at=CHANNEL_WINDOW_C_START,
                channel_window_end_at=CHANNEL_WINDOW_C_END,
            ),
            SUPERVISOR,
        ),
        201,
    )
    assert admitted["status"] == DO_PROPOSED
    assert admitted["channel_id"] == spare["id"]
    assert_money(admitted["unit_price_cents"], 7200, "frozen unit_price_cents")
