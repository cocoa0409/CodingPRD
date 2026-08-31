"""Drive-cycle phases, cadence gating, and the two independent site dimensions."""

from test_helpers import (
    ApiErrorId,
    create_active_corporate_site,
    create_active_site,
    create_collecting_cycle,
    create_inspected_batch,
    create_pencil,
    create_scheduled_session,
    create_site,
    create_year_round_cycle,
    move_batch,
    move_cycle,
    move_site_operational,
    move_site_pledge,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

PD = TEST_USERS["program_director_headers"]
WL = TEST_USERS["warehouse_lead_headers"]


def test_year_round_cycle_may_reopen_collection_from_distribution(api):
    """PRD §3.2: "Returning a cycle from `DISTRIBUTION` to `COLLECTING` requires the
    cycle to be in `DISTRIBUTION` and requires its `cadence` to be `YEAR_ROUND`."
    PRD §3.2: "`CLOSED` is terminal, and every one of these seven moves increments the
    cycle's `version` by 1."

    Design: Corner/state_machines/year_round_cycle_reopens_collection_from_distribution
    """
    cycle = create_year_round_cycle()
    validate_success(move_cycle(cycle["id"], "COLLECTING"))
    validate_success(move_cycle(cycle["id"], "SORTING"))
    validate_success(move_cycle(cycle["id"], "DISTRIBUTION"))

    reopened = validate_success(move_cycle(cycle["id"], "COLLECTING"))
    assert reopened["status"] == "COLLECTING"
    assert reopened["version"] == 5, (
        "created at 1, then four accepted moves each add exactly 1"
    )


def test_back_to_school_cadence_forbids_reopening_collection(api):
    """PRD §3.2: "A `BACK_TO_SCHOOL` cycle may never make that move, and the attempt is
    rejected with `ERR_CADENCE_FORBIDS_REOPEN`."

    Design: Corner/state_machines/back_to_school_cadence_forbids_reopening_collection
    """
    cycle = create_collecting_cycle(cadence="BACK_TO_SCHOOL")
    validate_success(move_cycle(cycle["id"], "SORTING"))
    validate_success(move_cycle(cycle["id"], "DISTRIBUTION"))

    response = move_cycle(cycle["id"], "COLLECTING")
    validate_error(response, ApiErrorId.ERR_CADENCE_FORBIDS_REOPEN.value, expected_status=409)

    reread = validate_success(api.get_drive_cycle(cycle["id"], PD))
    assert reread["status"] == "DISTRIBUTION"


def test_cycle_cannot_enter_distribution_while_a_batch_is_unresolved(api):
    """PRD §3.2: "Moving from `SORTING` to `DISTRIBUTION` additionally requires that no
    donation batch at any of the cycle's sites still be sitting in `RECEIVED`,
    `INSPECTED` or `REMEDIATED`; an unresolved batch blocks the move with
    `ERR_INVALID_CYCLE_STATE`."

    Design: Corner/state_machines/cycle_cannot_enter_distribution_with_open_batches
    """
    cycle = create_collecting_cycle()
    pencil = create_pencil()
    site = create_active_site(cycle["id"])
    batch = create_inspected_batch(site["id"], pencil["id"], qty_declared=10)
    validate_success(move_cycle(cycle["id"], "SORTING"))

    response = move_cycle(cycle["id"], "DISTRIBUTION")
    validate_error(response, ApiErrorId.ERR_INVALID_CYCLE_STATE.value, expected_status=409)

    assert validate_success(api.get_drive_cycle(cycle["id"], PD))["status"] == "SORTING"
    assert validate_success(api.get_donation_batch(batch["id"], WL))["status"] == "INSPECTED"


def test_pausing_a_site_cancels_its_scheduled_volunteer_sessions(api):
    """PRD §3.2: "Pausing an `ACTIVE` site cancels every volunteer session of that site
    still in `SCHEDULED`, moving each to `CANCELLED`."

    Design: Corner/state_machines/pausing_a_site_cancels_its_scheduled_volunteer_sessions
    """
    cycle = create_collecting_cycle()
    site = create_active_site(cycle["id"], bin_capacity=10)
    session = create_scheduled_session(
        site["id"],
        event_type="ASSEMBLY",
        window_start="2026-08-05T09:00:00Z",
        window_end="2026-08-05T12:00:00Z",
        volunteer_count=6,
        minor_volunteer_count=0,
        adult_supervisor_count=1,
    )

    paused = validate_success(move_site_operational(site["id"], "PAUSED"))
    assert paused["operational_status"] == "PAUSED"

    rows, _ = validate_paginated(api.list_site_volunteer_events(site["id"], PD))
    assert len(rows) == 1
    assert rows[0]["id"] == session["id"]
    assert rows[0]["status"] == "CANCELLED"


def test_corporate_site_cannot_be_activated_before_it_is_pledged(api):
    """PRD §3.2: "It requires `operational_status` to be `PENDING`, requires the
    governing cycle to be in `COLLECTING` or `SORTING`, and — when the site's
    `site_type` is `CORPORATE` — additionally requires its `pledge_status` to already
    be `PLEDGED` or `PLEDGE_ACTIVE`. All three of these guards report
    `ERR_INVALID_SITE_STATE`."

    Design: Corner/state_machines/corporate_site_activation_without_a_pledge_is_rejected
    """
    cycle = create_collecting_cycle()
    site = create_site(
        cycle["id"],
        name="Beacon Insurance",
        site_type="CORPORATE",
        bin_capacity=6,
        pledged_item_count=50,
    )

    response = move_site_operational(site["id"], "ACTIVE")
    validate_error(response, ApiErrorId.ERR_INVALID_SITE_STATE.value, expected_status=409)

    reread = validate_success(api.get_collection_site(site["id"], PD))
    assert reread["operational_status"] == "PENDING"
    assert reread["pledge_status"] == "NONE"


def test_pledge_cannot_be_fulfilled_below_the_committed_unit_count(api):
    """PRD §3.2: "Marking a pledge `FULFILLED` requires it to be at `PLEDGE_ACTIVE` and
    requires `accepted_item_count` to be greater than or equal to `pledged_item_count`;
    a partner that came up short is rejected with `ERR_PLEDGE_SHORTFALL`."
    PRD §3.3: "Hop three, caused by hop two, recomputes the cycle's
    `total_items_on_hand` and adds `qty_accepted` to the site's `accepted_item_count`."

    Design: Corner/state_machines/pledge_cannot_be_fulfilled_below_the_committed_unit_count
    """
    cycle = create_collecting_cycle()
    pencil = create_pencil()
    site = create_active_corporate_site(cycle["id"], pledged_item_count=50)
    batch = create_inspected_batch(
        site["id"], pencil["id"], qty_declared=10, condition="NEW", sealed=True
    )
    validate_success(move_batch(batch["id"], "ACCEPTED", headers=WL, qty_rejected=0))

    response = move_site_pledge(site["id"], "FULFILLED")
    validate_error(response, ApiErrorId.ERR_PLEDGE_SHORTFALL.value, expected_status=409)

    reread = validate_success(api.get_collection_site(site["id"], PD))
    assert reread["pledge_status"] == "PLEDGE_ACTIVE"
    assert reread["accepted_item_count"] == 10


def test_pledge_advances_while_the_operational_dimension_is_still_pending(api):
    """PRD §3.2: "On the pledge axis, a corporate partner's commitment is registered by
    moving `NONE` to `PLEDGED`, which requires the pledge dimension to be at `NONE`,
    requires `site_type` to be `CORPORATE`, and requires `pledged_item_count` to be at
    least 1."
    PRD §3.2: "The pledge advances regardless of where the operational dimension
    stands, so a site still in `PENDING` may already be `PLEDGED` — indeed for a
    corporate site that is the required order."

    Design: Difficulty/non_linear_state_machine/collection_site_pledge_and_operational_dimensions_advance_independently
    """
    cycle = create_collecting_cycle()
    site = create_site(
        cycle["id"],
        name="Beacon Insurance",
        site_type="CORPORATE",
        bin_capacity=6,
        pledged_item_count=50,
    )

    pledged = validate_success(move_site_pledge(site["id"], "PLEDGED"))
    assert pledged["pledge_status"] == "PLEDGED"
    assert pledged["operational_status"] == "PENDING", (
        "moving the pledge axis must not move the operational axis"
    )
    assert pledged["pledged_item_count"] == 50


def test_the_two_site_dimensions_advance_without_overwriting_each_other(api):
    """PRD §3.2: "What makes a site interesting is that it carries **two independent
    status dimensions that advance separately**."
    PRD §3.2: "Moving `PLEDGED` to `PLEDGE_ACTIVE` requires the pledge to be at
    `PLEDGED` and requires `operational_status` to be `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/collection_site_pledge_and_operational_dimensions_advance_independently
    """
    cycle = create_collecting_cycle()
    site = create_site(
        cycle["id"],
        name="Beacon Insurance",
        site_type="CORPORATE",
        bin_capacity=6,
        pledged_item_count=50,
    )

    validate_success(move_site_pledge(site["id"], "PLEDGED"))
    activated = validate_success(move_site_operational(site["id"], "ACTIVE"))
    assert activated["operational_status"] == "ACTIVE"
    assert activated["pledge_status"] == "PLEDGED", (
        "activating the site must not disturb the pledge dimension"
    )

    final = validate_success(move_site_pledge(site["id"], "PLEDGE_ACTIVE"))
    assert final["operational_status"] == "ACTIVE"
    assert final["pledge_status"] == "PLEDGE_ACTIVE"
    assert final["pledged_item_count"] == 50
