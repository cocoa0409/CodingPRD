"""The rush queue: admission quota, ranking key and one position per patron."""
import pytest

from test_helpers import validate_error, get_success_data, ApiErrorId
from test_helpers import constants as C
from test_helpers import fixtures as X


def test_admission_quota_is_half_the_release_ceiling_rounded_up(api):
    """PRD §3.6: "Where the release ceiling is two seats or more, the quota is
    one half of that ceiling, multiplied out and rounded upward to a whole slot.
    So a ceiling of four admits two, a ceiling of five admits three, and a
    ceiling that falls in the floor band admits at most one."
    PRD §3.6: "The system takes the positions of the performance that are
    currently `WAITING`, orders them as described, and admits a prefix of that
    order."

    Design: Corner/calculations/queue_rank_admits_half_the_released_cap_rounded_up
    """
    production, performance, allocation, patrons, positions = \
        X.setup_queue_of_four(daily_quantity=5)

    sweep = X.ops_run("2026-09-12T09:05:00Z")

    assert sweep["admissions_issued_count"] == 3, (
        f"a released ceiling of five admits ceil(5 / 2) == 3, got {sweep['admissions_issued_count']}"
    )


def test_the_admitted_prefix_is_the_earliest_joins(api):
    """PRD §3.6: "Positions are ordered by `joined_at` ascending, with
    `created_at` ascending as the sole tie-break between positions that joined at
    the identical instant; queue position identifiers never break a tie."

    Design: Corner/calculations/queue_rank_admits_half_the_released_cap_rounded_up
    """
    production, performance, allocation, patrons, positions = \
        X.setup_queue_of_four(daily_quantity=5)
    X.ops_run("2026-09-12T09:05:00Z")

    rows = get_success_data(api.list_queue_positions(
        performance["id"], X.OPS, params={"limit": 100}))
    rows = rows.get("data", rows) if isinstance(rows, dict) else rows
    by_id = {row["id"]: row for row in rows}

    assert by_id[positions[0]["id"]]["status"] == "ADMITTED"
    assert by_id[positions[1]["id"]]["status"] == "ADMITTED"
    assert by_id[positions[2]["id"]]["status"] == "ADMITTED"
    assert by_id[positions[3]["id"]]["status"] == "WAITING", (
        "the fourth position falls outside the quota and must stay WAITING, got "
        f"{by_id[positions[3]['id']]['status']}"
    )


def test_a_second_join_while_a_position_is_active_is_refused(api):
    """PRD §3.6: "A patron may hold only one active position per performance at a
    time, where active means `WAITING` or `ADMITTED`; a second attempt while
    either is held is refused with `ERR_QUEUE_POSITION_EXISTS` (HTTP 409)."

    Design: Corner/state_machines/second_join_while_queue_position_active_is_rejected
    """
    production, performance, allocation = X.setup_released_allocation(
        daily_quantity=5, per_order_limit=2,
    )
    patron = X.register_patron(email="queue_once@example.com")
    X.join_queue(performance, allocation, patron)

    response = api.join_queue(performance["id"],
                              {"allocation_id": allocation["id"]},
                              X.patron_headers(patron))
    validate_error(response, ApiErrorId.ERR_QUEUE_POSITION_EXISTS, expected_status=409)

    rows = get_success_data(api.list_queue_positions(
        performance["id"], X.OPS,
        params={"patron_id": patron["id"], "limit": 100}))
    entries = rows.get("data", rows) if isinstance(rows, dict) else rows
    assert len(entries) == 1, f"the rejected attempt must not add a position, got {len(entries)}"
    assert entries[0]["status"] == "WAITING", \
        "the existing position is unchanged by the rejected attempt"


def test_expiry_of_an_admission_is_irreversible(api):
    """PRD §3.6: "When the sweep at the next operational epoch finds an admitted
    position whose expiry has passed, the position moves to `EXPIRED`, and — this
    is the operative word — expiry is irreversible. No subsequent act revives an
    expired admission; the patron's only route back into the queue is the rejoin
    that restamps `joined_at`."

    Design: Difficulty/non_linear_state_machine/non_linear_draw_waitlist_promotion_cycle_on_draw_entry
    """
    production, performance, allocation = X.setup_released_allocation(
        daily_quantity=5, per_order_limit=2,
    )
    patron = X.register_patron(email="lapse@example.com")
    X.join_queue(performance, allocation, patron)
    X.ops_run("2026-09-12T09:05:00Z")
    X.set_clock("2026-09-12T09:40:00Z")
    X.ops_run("2026-09-12T09:40:00Z")

    rows = get_success_data(api.list_queue_positions(
        performance["id"], X.OPS,
        params={"patron_id": patron["id"], "limit": 100}))
    rows = rows.get("data", rows) if isinstance(rows, dict) else rows
    entry = rows[0]
    assert entry["status"] == "EXPIRED", \
        f"a lapsed admission must expire, got {entry['status']}"
    assert entry["admit_expires_at"] is not None, \
        "an admitted position carries the expiry instant it lapsed against"


def test_a_rejoin_restamps_the_joining_instant(api):
    """PRD §3.6: "the design anticipates a `ADMITTED` position returning to
    `WAITING` for a patron whose admission lapsed after the queue head had
    already moved past them, and a rejoin is what restamps `joined_at` and moves
    the patron to the back of the order."
    PRD §3.6: "Abandoned positions never return to the queue under their original
    `joined_at`."

    Design: Difficulty/non_linear_state_machine/non_linear_draw_waitlist_promotion_cycle_on_draw_entry
    """
    production, performance, allocation, patrons, positions = \
        X.setup_queue_of_four(daily_quantity=5)
    X.ops_run("2026-09-12T09:05:00Z")

    latecomer = X.register_patron(email="latecomer@example.com")
    X.join_queue(performance, allocation, latecomer)

    rows = get_success_data(api.list_queue_positions(
        performance["id"], X.OPS, params={"limit": 100}))
    rows = rows.get("data", rows) if isinstance(rows, dict) else rows
    joined = {row["id"]: row["joined_at"] for row in rows}
    late_position = next(row for row in rows
                         if row["patron_id"] == latecomer["id"])
    rank_keys = sorted(joined.values())
    assert rank_keys[-1] == late_position["joined_at"], (
        "a rejoin restamps the ranking instant and puts the patron at the back of "
        "the order"
    )