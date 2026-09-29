"""Pole attachment applications: make-ready pricing, gating and unwinding.

Three separate behaviours meet on this resource. The owner's estimate is priced
in a fixed four-step order whose second step keys the administrative fee tier on
a figure that is deliberately not the total. Acceptance runs two business gates
in a pinned order. And withdrawal is a compensating action that has to give the
route's money back to the cent.
"""

from test_helpers import fixtures as fx, validate_error, validate_success
from test_helpers.assertions import assert_budget_invariant
from test_helpers.factories import make_ready_item, withdraw_payload

_RIDGE_RING = {
    "name": "Ridge Ring",
    "topology_objective": "RING_CLOSURE",
    "target_in_service_date": "2027-03-01",
    "budget_authorized_cents": 250000000,
}
_RIDGE_AVE_250 = {
    "sequence_index": 1,
    "street_name": "Ridge Ave",
    "municipality_code": "MUN-014",
    "length_feet": 250,
    "terrain_class": "URBAN_PAVED",
    "planned_work_start_on": "2026-09-15",
    "planned_work_end_on": "2026-09-20",
    "existing_conduit_available": False,
}
_GRADE_A_POLE = {
    "pole_tag": "P-001",
    "pole_owner": "TELCO",
    "condition_grade": "A",
    "available_vertical_clearance_in": 48,
    "existing_attachment_count": 2,
}

#: Ten transfers on one pole plus a single clearance trim on another.
_TEN_TRANSFERS_AND_A_TRIM = [
    make_ready_item("P-001", "TRANSFER", 10),
    make_ready_item("P-002", "CLEARANCE_TRIM", 1),
]


def _estimated_application_on_a_walked_segment(owner):
    """A TELCO application for ten poles sitting at MAKE_READY_ESTIMATED."""

    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(**_RIDGE_RING)
    segment = fx.create_segment(route["id"], **_RIDGE_AVE_250)
    fx.accepted_walkout(
        segment["id"],
        [_GRADE_A_POLE],
        walked_on="2026-08-11",
        obstruction_count=0,
        conduit_available_confirmed=False,
        surveyor_note="ten poles, all serviceable",
    )
    application = fx.create_pole_application(segment["id"], pole_owner="TELCO", pole_count=10)
    fx.submit_pole_application(application["id"])
    estimated = fx.owner_respond(
        application["id"],
        "ESTIMATED",
        _TEN_TRANSFERS_AND_A_TRIM,
        headers=owner,
        owner_note="ten transfers plus one trim",
    )
    return {
        "route_id": route["id"],
        "segment_id": segment["id"],
        "application_id": estimated["id"],
        "application": estimated,
    }


def test_admin_fee_tier_is_chosen_from_the_subtotal_not_from_the_total(
    api, coordinator_headers, owner_alt_headers
):
    """A 456250 subtotal takes 1200 bp even though the total clears 500000.

    PRD: "The tier is keyed on the subtotal and **never** on the final total;
    re-deriving the tier from `make_ready_cost_cents` is forbidden and does not
    converge."

    Design: Difficulty/combinatorial_formula/make_ready_admin_fee_tier_keyed_on_pre_fee_subtotal
    """
    built = _estimated_application_on_a_walked_segment(owner_alt_headers)
    application = built["application"]

    assert application["status"] == "MAKE_READY_ESTIMATED"
    assert application["make_ready_items_subtotal_cents"] == 456250
    assert application["make_ready_admin_fee_bp"] == 1200, (
        "456250 is strictly below the 500000-cent first ceiling, so the rate is 1200 bp; "
        "keying the tier on the 511000-cent total would wrongly select 900 bp"
    )
    assert application["make_ready_admin_fee_cents"] == 54750
    assert application["make_ready_cost_cents"] == 511000
    assert application["make_ready_cost_cents"] > 500000


def test_make_ready_lines_price_per_item_and_the_schedule_uses_pole_count(
    api, coordinator_headers, owner_alt_headers
):
    """Each line is rounded on its own, and the day count adds two per pole.

    PRD: "Take the greatest `lead_days` among the application's items — the
    longest single piece of work on the critical path — and add two days of
    pole-handling labour for each pole in the application, that is, twice the
    application's `pole_count`."

    Design: Difficulty/combinatorial_formula/make_ready_admin_fee_tier_keyed_on_pre_fee_subtotal
    """
    built = _estimated_application_on_a_walked_segment(owner_alt_headers)

    rows = validate_success(
        api.list_make_ready_items(built["application_id"], headers=coordinator_headers)
    )
    assert len(rows) == 2
    by_class = {row["work_class"]: row for row in rows}

    transfer = by_class["TRANSFER"]
    assert transfer["pole_tag"] == "P-001"
    assert transfer["quantity"] == 10
    assert transfer["extended_cost_cents"] == 425000
    assert transfer["lead_days"] == 30

    trim = by_class["CLEARANCE_TRIM"]
    assert trim["pole_tag"] == "P-002"
    assert trim["quantity"] == 1
    assert trim["extended_cost_cents"] == 31250
    assert trim["lead_days"] == 15

    assert transfer["extended_cost_cents"] + trim["extended_cost_cents"] == 456250
    assert built["application"]["make_ready_days"] == 50

    route = fx.read_route(built["route_id"])
    assert route["budget_committed_cents"] == 0, "An estimate alone commits nothing"


# ---------------------------------------------------------------------------
# The two acceptance gates, in the order the specification pins them
# ---------------------------------------------------------------------------


def _grade_d_estimate_that_also_busts_the_budget(owner):
    """A trim-only estimate of 35000 cents on a route authorized for only 10000,
    filed on a segment whose accepted walkout found a grade-D pole.
    """
    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(
        name="Shoestring Loop",
        topology_objective="SPUR",
        target_in_service_date="2027-07-01",
        budget_authorized_cents=10000,
    )
    segment = fx.create_segment(
        route["id"],
        sequence_index=1,
        street_name="Mill Street",
        municipality_code="MUN-014",
        length_feet=250,
        terrain_class="URBAN_PAVED",
        planned_work_start_on="2026-10-05",
        planned_work_end_on="2026-10-12",
        existing_conduit_available=False,
    )
    fx.accepted_walkout(
        segment["id"],
        [
            {
                "pole_tag": "P-002",
                "pole_owner": "TELCO",
                "condition_grade": "D",
                "available_vertical_clearance_in": 30,
                "existing_attachment_count": 3,
            }
        ],
        walked_on="2026-08-11",
        obstruction_count=0,
        conduit_available_confirmed=False,
        surveyor_note="one rotted pole at mid-span",
    )
    application = fx.create_pole_application(segment["id"], pole_owner="TELCO", pole_count=1)
    fx.submit_pole_application(application["id"])
    estimated = fx.owner_respond(
        application["id"],
        "ESTIMATED",
        [make_ready_item("P-002", "CLEARANCE_TRIM", 1)],
        headers=owner,
        owner_note="trim only",
    )
    return {"route_id": route["id"], "application": estimated}


def test_grade_d_gate_reports_before_the_budget_gate_when_both_are_violated(
    api, coordinator_headers, owner_alt_headers
):
    """An estimate that is both unsafe and unaffordable reports the safety failure.

    PRD: "Likewise, make-ready acceptance evaluates the grade-D make-ready
    requirement (priority 14) **before** budget sufficiency (priority 26), so an
    application missing its pole-replacement line reports
    `ERR_MAKE_READY_REQUIRED` even when it also exceeds the route's available
    budget."

    Design: Difficulty/priority_pair_validation_conflict/make_ready_safety_gate_precedes_budget_gate
    """
    built = _grade_d_estimate_that_also_busts_the_budget(owner_alt_headers)
    estimated = built["application"]
    assert estimated["make_ready_cost_cents"] == 35000
    assert estimated["make_ready_admin_fee_bp"] == 1200
    assert estimated["make_ready_days"] == 17
    assert fx.read_route(built["route_id"])["budget_available_cents"] == 10000

    response = api.accept_make_ready(estimated["id"], headers=coordinator_headers)
    validate_error(response, "ERR_MAKE_READY_REQUIRED", 422)
    assert response.status_code != 402, (
        "402 ERR_BUDGET_EXCEEDED is the lower-priority failure and must not surface here"
    )


def test_refused_acceptance_neither_grants_the_attachment_nor_spends_money(
    api, coordinator_headers, owner_alt_headers
):
    """The refusal is total: no GRANTED status, no commitment, no budget movement.

    PRD: "A successful acceptance moves the application `MAKE_READY_ESTIMATED →
    GRANTED`, sets `committed` to true, raises the route's
    `budget_committed_cents` by the application's `make_ready_cost_cents` and
    lowers its `budget_available_cents` by the same amount so that authorized
    always equals committed plus available"

    Design: Difficulty/priority_pair_validation_conflict/make_ready_safety_gate_precedes_budget_gate
    """
    built = _grade_d_estimate_that_also_busts_the_budget(owner_alt_headers)

    refusal = api.accept_make_ready(built["application"]["id"], headers=coordinator_headers)
    assert refusal.status_code == 422, f"expected a 422 refusal, got {refusal.status_code}"

    application = fx.read_pole_application(built["application"]["id"])
    assert application["status"] == "MAKE_READY_ESTIMATED"
    assert application["committed"] is False
    assert application["make_ready_cost_cents"] == 35000

    route = fx.read_route(built["route_id"])
    assert route["budget_committed_cents"] == 0
    assert route["budget_available_cents"] == 10000
    assert_budget_invariant(route)


# ---------------------------------------------------------------------------
# Withdrawal as an exact compensating action
# ---------------------------------------------------------------------------


def _granted_application_on_a_design_locked_segment(owner):
    """A GRANTED 511000-cent attachment against a DESIGN_LOCKED 250-foot segment."""

    built = _estimated_application_on_a_walked_segment(owner)
    fx.select_method_on_route(built["route_id"], built["segment_id"], "AERIAL")
    fx.request_bid_ready(built["segment_id"])
    built["bid_before_grant"] = fx.read_segment(built["segment_id"])["bid_ready_cost_cents"]
    built["granted"] = fx.accept_make_ready(built["application_id"])
    return built


def test_granting_then_withdrawing_returns_the_route_budget_to_the_cent(
    api, coordinator_headers, owner_alt_headers
):
    """511000 cents are committed, then released exactly, leaving no residue.

    PRD: "Hop 2, caused by hop 1, drops the route's `budget_committed_cents` by
    that application's `make_ready_cost_cents` where the application had in fact
    been committed, and raises `budget_available_cents` by the same amount."

    Design: Difficulty/compensating_invariant/attachment_withdrawal_restores_route_budget_exactly
    """
    built = _granted_application_on_a_design_locked_segment(owner_alt_headers)
    assert built["granted"]["status"] == "GRANTED"
    assert built["granted"]["committed"] is True

    committed_route = fx.read_route(built["route_id"])
    assert committed_route["budget_committed_cents"] == 511000
    assert committed_route["budget_available_cents"] == 249489000
    assert_budget_invariant(committed_route)

    withdrawn = validate_success(
        api.withdraw_pole_attachment_application(
            built["application_id"],
            withdraw_payload(reason="owner rescinded the estimate, re-bidding the make-ready"),
            headers=coordinator_headers,
        )
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["committed"] is False
    assert withdrawn["make_ready_cost_cents"] == 511000, (
        "the breakdown is retained on the withdrawn row for audit"
    )

    route = fx.read_route(built["route_id"])
    assert route["budget_committed_cents"] == 0
    assert route["budget_available_cents"] == 250000000
    assert_budget_invariant(route)


def test_withdrawal_rederives_the_segment_bid_cost_without_the_make_ready(
    api, coordinator_headers, owner_alt_headers
):
    """Hops 3 and 4 walk the make-ready contribution back out of both rollups.

    PRD: "Hop 3, caused by hop 2, re-derives the segment's `bid_ready_cost_cents`
    without that application's make-ready contribution, again only while the
    segment is at `DESIGN_LOCKED`."

    Design: Difficulty/compensating_invariant/attachment_withdrawal_restores_route_budget_exactly
    """
    built = _granted_application_on_a_design_locked_segment(owner_alt_headers)
    assert built["bid_before_grant"] == 394295

    granted_segment = fx.read_segment(built["segment_id"])
    assert granted_segment["bid_ready_cost_cents"] == 905295

    validate_success(
        api.withdraw_pole_attachment_application(
            built["application_id"],
            withdraw_payload(reason="owner rescinded the estimate, re-bidding the make-ready"),
            headers=coordinator_headers,
        )
    )

    segment = fx.read_segment(built["segment_id"])
    assert segment["bid_ready_cost_cents"] == 394295
    assert segment["engineering_status"] == "DESIGN_LOCKED"
    assert segment["preliminary_cost_cents"] == 394294

    route = fx.read_route(built["route_id"])
    assert route["total_bid_ready_cost_cents"] == 394295


_TIGHT_BUDGET_SPUR = {
    "name": "Tight Budget Spur",
    "topology_objective": "SPUR",
    "target_in_service_date": "2027-06-01",
    "budget_authorized_cents": 165983,
}
_GRADE_B_MUNICIPAL_POLE = {
    "pole_tag": "P-001",
    "pole_owner": "MUNICIPAL_LIGHT",
    "condition_grade": "B",
    "available_vertical_clearance_in": 45,
    "existing_attachment_count": 2,
}
_GRADE_B_ELECTRIC_POLE = {
    "pole_tag": "P-101",
    "pole_owner": "ELECTRIC_UTILITY",
    "condition_grade": "B",
    "available_vertical_clearance_in": 45,
    "existing_attachment_count": 2,
}


def _submitted_application(route_spec, pole, pole_owner, pole_count):
    """A walked segment carrying one application that is waiting on the owner."""

    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(**route_spec)
    segment = fx.create_segment(route["id"], **_RIDGE_AVE_250)
    fx.accepted_walkout(
        segment["id"],
        [pole],
        walked_on="2026-08-11",
        obstruction_count=0,
        conduit_available_confirmed=False,
        surveyor_note="poles serviceable",
    )
    application = fx.create_pole_application(
        segment["id"], pole_owner=pole_owner, pole_count=pole_count
    )
    submitted = fx.submit_pole_application(application["id"])
    return {
        "route_id": route["id"],
        "segment_id": segment["id"],
        "application_id": application["id"],
        "application": submitted,
    }


def test_acceptance_before_the_owner_has_answered_is_refused(api, coordinator_headers):
    """There is no estimate to accept while the application is still SUBMITTED.

    PRD: "Accepting the estimate is what actually grants the attachment and spends
    money. Acceptance requires the application at `MAKE_READY_ESTIMATED` and enforces
    two business rules in the order given."

    Design: Corner/state_machines/attachment_accept_make_ready_from_submitted_returns_invalid_pole_application_state
    """
    built = _submitted_application(_RIDGE_RING, _GRADE_A_POLE, "TELCO", 4)
    assert built["application"]["status"] == "SUBMITTED"

    premature = api.accept_make_ready(built["application_id"], headers=coordinator_headers)
    validate_error(premature, "ERR_INVALID_POLE_APPLICATION_STATE", 409)

    application = fx.read_pole_application(built["application_id"])
    assert application["status"] == "SUBMITTED"
    assert application["committed"] is False
    assert application["make_ready_cost_cents"] is None
    assert application["make_ready_days"] is None
    assert (
        validate_success(
            api.list_make_ready_items(built["application_id"], headers=coordinator_headers)
        )
        == []
    )

    route = fx.read_route(built["route_id"])
    assert route["budget_committed_cents"] == 0
    assert route["budget_available_cents"] == 250000000
    assert_budget_invariant(route)


def test_a_grant_that_misses_the_available_balance_by_one_cent_is_refused(
    api, coordinator_headers, owner_municipal_headers, admin_headers
):
    """165984 against 165983 is strictly greater, so the money stays where it is.

    PRD: "The rejection is strict — a cost strictly greater than the available
    balance is refused with `ERR_BUDGET_EXCEEDED`, and an exact fit that drives
    `budget_available_cents` to precisely zero is allowed."

    Design: Corner/validations/accept_make_ready_above_available_budget_returns_budget_exceeded
    """
    built = _submitted_application(
        _TIGHT_BUDGET_SPUR, _GRADE_B_MUNICIPAL_POLE, "MUNICIPAL_LIGHT", 4
    )
    estimated = fx.owner_respond(
        built["application_id"],
        "ESTIMATED",
        [make_ready_item("P-001", "GUYING", 2)],
        headers=owner_municipal_headers,
        owner_note="two down guys",
    )
    assert estimated["make_ready_cost_cents"] == 165984
    before = fx.read_route(built["route_id"])
    assert before["budget_available_cents"] == 165983

    refused = api.accept_make_ready(built["application_id"], headers=coordinator_headers)
    validate_error(refused, "ERR_BUDGET_EXCEEDED", 402)

    application = fx.read_pole_application(built["application_id"])
    assert application["status"] == "MAKE_READY_ESTIMATED"
    assert application["committed"] is False

    untouched = fx.read_route(built["route_id"])
    assert untouched["budget_committed_cents"] == 0
    assert untouched["budget_available_cents"] == 165983
    assert_budget_invariant(untouched)

    fx.adjust_budget(built["route_id"], 1, reason="one more authorized cent")
    granted = validate_success(
        api.accept_make_ready(built["application_id"], headers=coordinator_headers)
    )
    assert granted["status"] == "GRANTED"
    assert granted["committed"] is True

    funded = fx.read_route(built["route_id"])
    assert funded["budget_committed_cents"] == 165984
    assert funded["budget_available_cents"] == 0
    assert_budget_invariant(funded)


def test_a_subtotal_of_exactly_five_thousand_dollars_falls_into_the_middle_tier(
    api, coordinator_headers, owner_headers
):
    """The first tier is strictly below 500000, and 500000 is not below itself.

    PRD: "The administrative fee rate `make_ready_admin_fee_bp` is chosen by
    comparing `make_ready_items_subtotal_cents` against two ceilings: a subtotal
    strictly below 5,000 dollars takes 1,200 basis points; a subtotal that is at
    least 5,000 dollars but strictly below 20,000 dollars takes 900 basis points; a
    subtotal of 20,000 dollars or more takes 600 basis points."

    Design: Corner/cross_cutting_complexity_layers/admin_fee_tier_at_a_subtotal_of_exactly_500000_uses_the_upper_tier_rate
    """
    built = _submitted_application(_RIDGE_RING, _GRADE_A_POLE, "TELCO", 16)

    estimated = fx.owner_respond(
        built["application_id"],
        "ESTIMATED",
        [make_ready_item("P-001", "CLEARANCE_TRIM", 16)],
        headers=owner_headers,
        owner_note="sixteen trims",
    )
    assert estimated["make_ready_items_subtotal_cents"] == 500000, (
        "sixteen trims at 31250 cents each, at the telco multiplier of exactly par"
    )
    assert estimated["make_ready_admin_fee_bp"] == 900
    assert estimated["make_ready_admin_fee_cents"] == 45000
    assert estimated["make_ready_cost_cents"] == 545000
    assert estimated["make_ready_days"] == 47, (
        "a clearance trim leads by 15 days, plus two days for each of sixteen poles"
    )
    assert estimated["status"] == "MAKE_READY_ESTIMATED"
    assert estimated["committed"] is False

    route = fx.read_route(built["route_id"])
    assert route["budget_committed_cents"] == 0
    assert_budget_invariant(route)


def test_a_schedule_that_would_run_one_hundred_and_thirty_days_is_clipped_to_the_cap(
    api, coordinator_headers, owner_electric_headers
):
    """The cap trims the day count and leaves every cost figure alone.

    PRD: "The resulting day count is then capped at 120 days: `make_ready_days` is
    the lesser of that sum and 120."

    Design: Corner/cross_cutting_complexity_layers/make_ready_days_are_capped_at_120_when_the_raw_schedule_reaches_130
    """
    built = _submitted_application(_RIDGE_RING, _GRADE_B_ELECTRIC_POLE, "ELECTRIC_UTILITY", 20)

    estimated = fx.owner_respond(
        built["application_id"],
        "ESTIMATED",
        [make_ready_item("P-101", "POLE_REPLACEMENT", 1)],
        headers=owner_electric_headers,
        owner_note="one replacement, twenty poles handled",
    )
    assert estimated["make_ready_items_subtotal_cents"] == 672750, (
        "585000 cents at the electric-utility multiplier of 11500 basis points"
    )
    assert estimated["make_ready_admin_fee_bp"] == 900
    assert estimated["make_ready_admin_fee_cents"] == 60548
    assert estimated["make_ready_cost_cents"] == 733298
    assert estimated["make_ready_days"] == 120, (
        "the raw schedule is 90 lead days plus 40 handling days, which the cap clips"
    )

    rows = validate_success(
        api.list_make_ready_items(built["application_id"], headers=coordinator_headers)
    )
    assert len(rows) == 1
    assert rows[0]["lead_days"] == 90, "the per-line lead time is stored uncapped"
    assert rows[0]["extended_cost_cents"] == 672750
