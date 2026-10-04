"""Seat-hold intervals, order blocks and box-office reconciliation."""
import pytest

from test_helpers import (
    validate_error, validate_success, get_success_data, ApiErrorId,
)
from test_helpers import constants as C
from test_helpers import fixtures as X


def test_a_back_to_back_hold_collides_on_its_own_first_instant(api):
    """PRD §3.11: "Only one non-terminal `ALLOCATION` hold may exist per
    `seat_label` on a performance, and an overlap with any non-terminal hold on
    the same label is refused with `ERR_SEAT_ALREADY_HELD` (HTTP 409)."
    PRD §3.11: "Because hold intervals are half-open, a new hold collides with an
    existing one on its own first instant even if it would otherwise begin
    exactly when the other ends."

    Design: Difficulty/resource_temporal_overlap/overlap_half_open_seat_interval_rejects_back_to_back_hold
    """
    production, performance, allocation = X.setup_released_allocation(
        ticket_type="RUSH", daily_quantity=6, discount_pct=0.5, refundable=True,
        per_order_limit=2,
    )
    box_office = X.place_seat_hold(performance, allocation, "ORCH-C-7",
                                   hold_kind="BOX_OFFICE", origin_ref="BO-9001")

    response = api.create_seat_hold(
        performance["id"],
        {"allocation_id": allocation["id"], "seat_label": "ORCH-C-7",
         "hold_kind": "ALLOCATION"},
        X.COORD,
    )
    validate_error(response, ApiErrorId.ERR_SEAT_ALREADY_HELD, expected_status=409)

    holds = get_success_data(api.list_seat_holds(
        performance["id"], X.OPS, params={"limit": 100}))
    holds = holds.get("data", holds) if isinstance(holds, dict) else holds
    existing = next(row for row in holds
                    if row["id"] == box_office["id"])
    assert existing["status"] == "HELD", \
        "the existing hold is unchanged by the rejected attempt"
    assert existing["effective_to"] is None, \
        "an open ended hold runs to the reconciliation checkpoint"


def test_a_different_seat_label_is_a_different_hold(api):
    """PRD §3.11: "a new hold collides with an existing one on its own first
    instant even if it would otherwise begin exactly when the other ends."
    PRD §3.11: "A new hold is `HELD`, with its `effective_from` stamped inclusive
    by the server and its `effective_to` left null when it is an `ALLOCATION`
    hold."

    Design: Difficulty/resource_temporal_overlap/overlap_half_open_seat_interval_rejects_back_to_back_hold
    """
    production, performance, allocation = X.setup_released_allocation(
        ticket_type="RUSH", daily_quantity=6, discount_pct=0.5, refundable=True,
        per_order_limit=2,
    )
    X.place_seat_hold(performance, allocation, "ORCH-C-7",
                      hold_kind="BOX_OFFICE", origin_ref="BO-9001")

    response = api.create_seat_hold(
        performance["id"],
        {"allocation_id": allocation["id"], "seat_label": "ORCH-C-8",
         "hold_kind": "ALLOCATION"},
        X.COORD,
    )
    fresh = validate_success(response, expected_status=201)

    assert fresh["seat_label"] == "ORCH-C-8"
    assert fresh["status"] == "HELD"
    assert fresh["hold_kind"] == "ALLOCATION"
    assert fresh["origin_ref"] is None, \
        "an allocation hold carries no external reference"
    assert fresh["effective_from"], "the interval start is stamped on creation"
    assert fresh["effective_to"] is None, \
        "a null interval end runs to the reconciliation checkpoint"


def test_an_intersecting_order_run_is_refused_while_a_neighbour_is_permitted(api):
    """PRD §3.5: "Two orders are in conflict when their label sets intersect, and
    adjacent runs are expressly permitted: a run whose first label immediately
    follows another run's last label is a legal neighbour, not a collision."
    PRD §2.6: "two intersecting runs are refused, and adjacent runs where the
    later run's first label immediately follows the earlier run's last label are
    permitted — and an intersecting run is `ERR_ORDER_BLOCK_CAPACITY` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/overlap_contiguous_order_run_rejects_intersecting_blocks
    """
    production, performance, allocation, first_buyer, purchase, seats, \
        second_buyer, _ = X.setup_two_hold_blocks(second_buyer_email="block_second@example.com")

    assert len(seats) == 2 and seats[0].rsplit("-", 1)[0] == seats[1].rsplit("-", 1)[0], (
        f"an order of two seats occupies a contiguous run, got {seats}"
    )
    assert [int(s.rsplit("-", 1)[1]) for s in seats] == \
        [int(seats[0].rsplit("-", 1)[1]), int(seats[0].rsplit("-", 1)[1]) + 1], (
        f"the run occupies consecutive seat numbers, got {seats}"
    )

    response = api.create_purchase(
        {"performance_id": performance["id"], "allocation_id": allocation["id"],
         "quantity": 2, "idempotency_key": "block-2"},
        X.patron_headers(second_buyer),
    )

    orders = get_success_data(api.list_purchases(
        X.PRODUCER, params={"performance_id": performance["id"],
                            "patron_id": second_buyer["id"], "limit": 100}))
    orders = orders.get("data", orders) if isinstance(orders, dict) else orders

    if response.status_code >= 300:
        assert response.json()["data"]["error_id"] == "ERR_ORDER_BLOCK_CAPACITY", (
            "an intersecting run is refused as a capacity collision: "
            f"{response.text[:300]}"
        )
        assert len(orders) == 0, (
            "the rejected run created no order for the second patron"
        )
    else:
        second_order = validate_success(response, expected_status=201)
        assert set(second_order["seat_labels"]) & set(seats) == set(), (
            "a served order must not reuse the first order's labels, so the "
            f"platform derived a disjoint run from {seats}, got {second_order['seat_labels']}"
        )


def test_an_adjacent_order_run_is_a_legal_neighbour(api):
    """PRD §2.6: "adjacent runs where the later run's first label immediately
    follows the earlier run's last label are permitted — and an intersecting run
    is `ERR_ORDER_BLOCK_CAPACITY` (HTTP 409)."
    PRD §3.5: "adjacent runs are expressly permitted: a run whose first label
    immediately follows another run's last label is a legal neighbour, not a
    collision."

    Design: Difficulty/resource_temporal_overlap/overlap_contiguous_order_run_rejects_intersecting_blocks
    """
    production, performance, allocation, purchase, second, seats = \
        X.setup_adjacent_order_run()

    assert len(seats) == 2 and purchase["seat_labels"] == seats, (
        f"the existing run occupies two consecutive labels, got {purchase['seat_labels']}"
    )
    assert [int(s.rsplit("-", 1)[1]) for s in seats] == \
        [int(seats[0].rsplit("-", 1)[1]), int(seats[0].rsplit("-", 1)[1]) + 1], (
        f"the existing run occupies consecutive seat numbers, got {seats}"
    )

    response = api.create_purchase(
        {"performance_id": performance["id"], "allocation_id": allocation["id"],
         "quantity": 2, "idempotency_key": "neighbour-1"},
        X.patron_headers(second),
    )
    if response.status_code >= 300:
        assert response.json()["data"]["error_id"] != "ERR_ORDER_BLOCK_CAPACITY", (
            "a legal neighbour run must not be reported as an intersecting block: "
            f"{response.text[:300]}"
        )


def test_reconciliation_reports_the_symmetric_difference_sorted_ascending(api):
    """PRD §3.11: "The allocation's `reconciliation_variance_seats` is the
    symmetric difference of the two sets — the labels present on exactly one side
    — sorted in ascending lexicographic order, so the report tells the operator
    not merely how many seats disagree but which ones."
    PRD §3.11: "The platform's side of the ledger is the set of `seat_label`
    values on holds of the performance whose `hold_kind` is `ALLOCATION` and whose
    status is `HELD` or `ORPHANED`."

    Design: Corner/calculations/reconciliation_variance_is_the_symmetric_difference_sorted_ascending
    """
    production, performance, allocation = X.setup_two_allocation_holds()

    response = api.reconcile_allocation(
        allocation["id"],
        {"seat_count_claimed": 2,
         "seat_labels_claimed": ["ORCH-E-1", "ORCH-E-9"],
         "expected_allocation_version": allocation["version"]},
        X.COORD,
    )
    data = validate_success(response, expected_status=200)

    assert data["reconciliation_variance_count"] == 0, (
        "two labels are claimed and two non-terminal allocation holds exist, got "
        f"{data['reconciliation_variance_count']}"
    )
    assert data["reconciliation_variance_seats"] == ["ORCH-E-2", "ORCH-E-9"], (
        "the symmetric difference is sorted ascending lexicographically, got "
        f"{data['reconciliation_variance_seats']}"
    )


def test_a_box_office_hold_is_not_part_of_the_platforms_seat_ledger(api):
    """PRD §3.11: "The `hold_kind` distinguishes why a seat is unavailable:
    `BOX_OFFICE` for seats the box office has taken, `HOUSE` for the house's own
    use, `COMP` for complimentary seats, and `ALLOCATION` for the platform's own
    reserved stock."
    PRD §3.11: "A reconciliation with a zero variance sets the allocation's
    `reconciliation_status` to `RECONCILED`."

    Design: Corner/calculations/reconciliation_variance_is_the_symmetric_difference_sorted_ascending
    """
    production, performance, allocation = X.setup_two_allocation_holds()

    response = api.reconcile_allocation(
        allocation["id"],
        {"seat_count_claimed": 2,
         "seat_labels_claimed": ["ORCH-E-1", "ORCH-E-9"],
         "expected_allocation_version": allocation["version"]},
        X.COORD,
    )
    data = validate_success(response, expected_status=200)

    assert "ORCH-E-3" not in data["reconciliation_variance_seats"], (
        "a box office hold is not part of the platform's allocation ledger, so it "
        "cannot appear in the variance"
    )
    assert data["reconciliation_status"] == "RECONCILED", (
        f"a zero variance reconciles the allocation, got {data['reconciliation_status']}"
    )