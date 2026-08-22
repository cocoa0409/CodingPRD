"""Donation acceptance criteria and the truck's pickup calendar."""

import pytest

from test_helpers import (
    INTAKE,
    ApiErrorId,
    create_donation_offer,
    create_truck,
    donation_item_payload,
    list_donation_items,
    schedule_pickup,
    set_clock,
    triage_offer,
    validate_error,
    validate_success,
)
from test_helpers.assertions import assert_donation_item, assert_donation_offer

FOUR_PIECE_OFFER = [
    donation_item_payload("SOFA", "B", True, 40.0),
    donation_item_payload("CRIB", "B", False, 10.0),
    donation_item_payload("LINENS", "A", True, 5.0),
    donation_item_payload("TABLE_SET", "A", False, 20.0),
]


def _offer_with_four_pieces():
    set_clock("2026-08-04T09:00:00Z")
    offer = create_donation_offer(
        FOUR_PIECE_OFFER, donor_name="Ellis Wray", donor_phone="555-0133",
        pickup_county="CENTRAL",
        pickup_window_start="2026-08-04T10:00:00Z",
        pickup_window_end="2026-08-04T12:00:00Z",
    )
    return offer, list_donation_items(offer["id"])


def _triaged_offer_on_truck(truck_id, window_start, window_end, donor_name, phone):
    offer = create_donation_offer(
        [donation_item_payload("DRESSER", "B", False, 20.0)],
        donor_name=donor_name, donor_phone=phone, pickup_county="CENTRAL",
        pickup_window_start=window_start, pickup_window_end=window_end,
    )
    return triage_offer(offer["id"])


# ─── Difficulty: the pinned three-step triage order ────────────────────

def test_soft_surface_rejection_reads_the_pre_decision_ratio(api):
    """PRD §3.4: "Step one takes a pre-decision snapshot over *all* submitted
    pieces of the offer: `declared_soft_ratio` is the number of pieces whose
    `soft_surface` is true divided by the total number of pieces, rounded half
    up to three decimal places."
    PRD §3.4: "Otherwise, if its `soft_surface` is true and the offer's
    `declared_soft_ratio` from step one is at least 0.5, it is refused with
    `reject_reason` `SOFT_SURFACE_RISK`. An offer that is half or more
    upholstered loses all of its upholstery."
    PRD §3.4: "If at least one piece was accepted, the offer moves `OFFERED →
    TRIAGED` and `declared_soft_ratio`, `accepted_item_count`,
    `rejected_item_count` and `bed_bug_risk_score` are all recomputed."

    Design: Difficulty/combinatorial_formula/triage_pinned_three_step_evaluation_order
    """
    offer, _pieces = _offer_with_four_pieces()

    triaged = triage_offer(offer["id"])

    assert_donation_offer(triaged)
    assert triaged["declared_soft_ratio"] == pytest.approx(0.5, abs=0.0005), (
        "two of four submitted pieces are soft-surface"
    )
    assert triaged["status"] == "TRIAGED", "one piece survived, so the offer is triaged"
    assert triaged["accepted_item_count"] == 1
    assert triaged["rejected_item_count"] == 3


def test_risk_score_reads_only_the_post_decision_accepted_set(api):
    """PRD §3.4: "Step three computes the risk score only after every decision
    is final. If no piece was accepted, `bed_bug_risk_score` is 0.0. Otherwise
    it is 100 multiplied by the accepted soft-surface volume divided by the
    total accepted volume, rounded half up to one decimal place — that is, the
    share of accepted cubic feet that is upholstered, expressed on a 0.0 to
    100.0 scale."
    PRD §3.4: "If the piece's `category` is `CRIB` and its `declared_condition`
    is anything other than `A`, it is refused with `reject_reason`
    `RECALLED_CRIB`. A crib that is both non-A-grade and D-grade therefore
    reports `RECALLED_CRIB`, never `CONDITION_BELOW_MIN`."

    Design: Difficulty/combinatorial_formula/triage_pinned_three_step_evaluation_order
    """
    offer, pieces = _offer_with_four_pieces()
    sofa, crib, linens, table_set = pieces

    triaged = triage_offer(offer["id"])

    assert triaged["bed_bug_risk_score"] == pytest.approx(0.0, abs=0.05), (
        "no upholstered piece survived, so the accepted volume carries no soft share"
    )

    decided = {piece["id"]: piece for piece in list_donation_items(offer["id"])}
    for piece in decided.values():
        assert_donation_item(piece)

    assert decided[sofa["id"]]["decision"] == "REJECTED"
    assert decided[sofa["id"]]["reject_reason"] == "SOFT_SURFACE_RISK"
    assert decided[crib["id"]]["decision"] == "REJECTED"
    assert decided[crib["id"]]["reject_reason"] == "RECALLED_CRIB", (
        "a non-A-grade crib reports the recall reason, not a condition reason"
    )
    assert decided[linens["id"]]["decision"] == "REJECTED"
    assert decided[linens["id"]]["reject_reason"] == "SOFT_SURFACE_RISK"
    assert decided[table_set["id"]]["decision"] == "ACCEPTED"
    assert decided[table_set["id"]]["reject_reason"] is None


# ─── Difficulty: half-open pickup windows on one truck ─────────────────

def test_pickup_window_touching_an_existing_end_instant_is_accepted(api):
    """PRD §3.4: "Under half-open interval semantics, where an interval includes
    its start instant and excludes its end instant, the requested pickup window
    must not overlap any other donation offer in `PICKUP_SCHEDULED` on the same
    truck, nor any delivery run on that truck whose `status` is `PLANNED`,
    `CREWED` or `DISPATCHED`. Touching endpoints do not overlap: a window that
    begins at the exact instant another one ends is accepted."

    Design: Difficulty/resource_temporal_overlap/truck_pickup_windows_half_open_adjacent_ok_overlap_rejected
    """
    set_clock("2026-08-04T09:00:00Z")
    truck = create_truck(label="BOX-10", capacity_cubic_feet=600,
                         home_county="CENTRAL", crew_minimum=1)

    offer_a = _triaged_offer_on_truck(
        truck["id"], "2026-08-05T10:00:00Z", "2026-08-05T12:00:00Z",
        "Donor A", "555-0301",
    )
    schedule_pickup(offer_a["id"], truck["id"])

    offer_b = _triaged_offer_on_truck(
        truck["id"], "2026-08-05T12:00:00Z", "2026-08-05T14:00:00Z",
        "Donor B", "555-0302",
    )
    booked = validate_success(
        api.schedule_pickup(offer_b["id"], {"truck_id": truck["id"]}, INTAKE)
    )

    assert booked["status"] == "PICKUP_SCHEDULED", (
        "a window starting exactly when another ends does not overlap"
    )
    assert booked["truck_id"] == truck["id"]


def test_genuinely_overlapping_pickup_window_is_refused(api):
    """PRD §3.4: "A genuine overlap is rejected with
    `ERR_TRUCK_WINDOW_CONFLICT`."
    PRD §3.4: "Under half-open interval semantics, where an interval includes
    its start instant and excludes its end instant, the requested pickup window
    must not overlap any other donation offer in `PICKUP_SCHEDULED` on the same
    truck, nor any delivery run on that truck whose `status` is `PLANNED`,
    `CREWED` or `DISPATCHED`."

    Design: Difficulty/resource_temporal_overlap/truck_pickup_windows_half_open_adjacent_ok_overlap_rejected
    """
    set_clock("2026-08-04T09:00:00Z")
    truck = create_truck(label="BOX-10", capacity_cubic_feet=600,
                         home_county="CENTRAL", crew_minimum=1)

    offer_a = _triaged_offer_on_truck(
        truck["id"], "2026-08-05T10:00:00Z", "2026-08-05T12:00:00Z",
        "Donor A", "555-0301",
    )
    schedule_pickup(offer_a["id"], truck["id"])
    offer_b = _triaged_offer_on_truck(
        truck["id"], "2026-08-05T12:00:00Z", "2026-08-05T14:00:00Z",
        "Donor B", "555-0302",
    )
    schedule_pickup(offer_b["id"], truck["id"])

    offer_c = _triaged_offer_on_truck(
        truck["id"], "2026-08-05T11:00:00Z", "2026-08-05T13:00:00Z",
        "Donor C", "555-0303",
    )
    response = api.schedule_pickup(offer_c["id"], {"truck_id": truck["id"]}, INTAKE)
    validate_error(response, ApiErrorId.ERR_TRUCK_WINDOW_CONFLICT.value, 409)

    offer_c_now = validate_success(api.get_donation_offer(offer_c["id"], INTAKE))
    assert offer_c_now["status"] == "TRIAGED", "the refused booking leaves the state"
    assert offer_c_now["truck_id"] is None, "no truck is written onto the offer"


# ─── Corner: auto-rejection, idempotency and the capacity rung ─────────

def test_triage_rejecting_every_piece_moves_the_offer_to_rejected(api):
    """PRD §3.4: "If nothing was accepted, every piece is refused with a reason
    and the offer moves `OFFERED → REJECTED` instead, with `declared_soft_ratio`
    and `rejected_item_count` recomputed and `bed_bug_risk_score` set to 0.0."
    PRD §3.4: "If the piece's `category` is `CRIB` and its `declared_condition`
    is anything other than `A`, it is refused with `reject_reason`
    `RECALLED_CRIB`."

    Design: Corner/state_machines/corner_triage_rejecting_every_piece_auto_rejects_the_offer
    """
    set_clock("2026-08-04T09:00:00Z")
    offer = create_donation_offer(
        [donation_item_payload("CRIB", "C", False, 10.0)],
        donor_name="Silas Turner", donor_phone="555-0521",
    )
    piece = list_donation_items(offer["id"])[0]

    triaged = triage_offer(offer["id"])

    assert triaged["status"] == "REJECTED", "nothing was accepted"
    assert triaged["accepted_item_count"] == 0
    assert triaged["rejected_item_count"] == 1
    assert triaged["declared_soft_ratio"] == pytest.approx(0.0, abs=0.0005)
    assert triaged["bed_bug_risk_score"] == pytest.approx(0.0, abs=0.05)

    piece_now = list_donation_items(offer["id"])[0]
    assert piece_now["id"] == piece["id"]
    assert piece_now["decision"] == "REJECTED"
    assert piece_now["reject_reason"] == "RECALLED_CRIB"


def test_second_triage_on_the_same_offer_is_refused(api):
    """PRD §3.4: "Triaging an offer that is not in `OFFERED` is rejected with
    `ERR_OFFER_INVALID_STATE`."

    Design: Corner/state_machines/corner_second_triage_on_same_offer_rejected
    """
    set_clock("2026-08-04T09:00:00Z")
    offer = create_donation_offer(
        [donation_item_payload("DRESSER", "B", False, 20.0)],
        donor_name="Tanvi Rao", donor_phone="555-0531",
    )
    triaged = triage_offer(offer["id"])

    response = api.triage_donation_offer(offer["id"], INTAKE)
    validate_error(response, ApiErrorId.ERR_OFFER_INVALID_STATE.value, 409)

    offer_now = validate_success(api.get_donation_offer(offer["id"], INTAKE))
    assert offer_now["status"] == "TRIAGED"
    assert offer_now["accepted_item_count"] == 1
    assert offer_now["version"] == triaged["version"], (
        "a refused triage bumps no version"
    )


def test_capacity_rung_rejects_the_piece_that_would_exceed_the_headroom(api):
    """PRD §3.4: "Before the walk begins the system measures the warehouse:
    current occupancy is the sum of `cubic_feet` over every inventory unit whose
    `status` is `QUARANTINED`, `AVAILABLE`, `RESERVED` or `STAGED` — units that
    are `DELIVERED` or `DISPOSED` have left the building and are excluded — and
    headroom is the warehouse's total floor space of 400 cubic feet minus that
    occupancy."
    PRD §3.4: "Otherwise, if the running total of accepted volume plus this
    piece's `cubic_feet` would strictly exceed the headroom, it is refused with
    `reject_reason` `CAPACITY`."

    Design: Corner/calculations/corner_triage_capacity_reject_at_exact_warehouse_headroom
    """
    set_clock("2026-08-04T09:00:00Z")
    offer = create_donation_offer(
        [
            donation_item_payload("DRESSER", "B", False, 200.0),
            donation_item_payload("TABLE_SET", "B", False, 200.0),
            donation_item_payload("KITCHEN_KIT", "B", False, 10.0),
        ],
        donor_name="Xiomara Reyes", donor_phone="555-0631",
    )
    first, second, third = list_donation_items(offer["id"])

    triaged = triage_offer(offer["id"])

    assert triaged["status"] == "TRIAGED"
    assert triaged["accepted_item_count"] == 2, (
        "200.0 plus 200.0 is exactly the 400 cubic feet of headroom"
    )
    assert triaged["rejected_item_count"] == 1
    assert triaged["bed_bug_risk_score"] == pytest.approx(0.0, abs=0.05)

    decided = {piece["id"]: piece for piece in list_donation_items(offer["id"])}
    assert decided[first["id"]]["decision"] == "ACCEPTED"
    assert decided[second["id"]]["decision"] == "ACCEPTED"
    assert decided[third["id"]]["decision"] == "REJECTED", (
        "410.0 strictly exceeds the 400.0 headroom"
    )
    assert decided[third["id"]]["reject_reason"] == "CAPACITY"
