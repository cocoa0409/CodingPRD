"""Membership status transitions, fiscal preconditions and styling preferences.

Covers the member's own lifecycle: the pause and resume round trip, the terminal
lockdown that follows cancellation, the two preconditions that gate leaving the
active state — nothing held and nothing owed — the targeted preferences patch,
and the priority conflict between the active-status rung and the slot ceiling.
"""

from __future__ import annotations

from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers.api_errors import (
    ERR_ITEM_SLOTS_EXHAUSTED,
    ERR_MEMBER_NOT_ACTIVE,
    ERR_OUTSTANDING_BALANCE,
    ERR_RESOURCE_TERMINAL,
    ERR_UNITS_STILL_OUT,
)
from test_helpers.assertions import (
    assert_common_fields,
    assert_created,
    assert_error,
    assert_fields,
    assert_list,
    assert_money,
    assert_ok,
)
from test_helpers.fixtures import (
    Scenario,
    standard_catalog,
    turn_to_delivery,
    turn_to_receipt,
)


def test_member_pause_and_resume_round_trip_bumps_version_twice(
    scenario: Scenario,
) -> None:
    """Two mutations of the same member move its version from 1 to 3, one step each.

    PRD §2.4: "`version` is an integer that starts at 1 when the resource is created and increases by exactly 1 on every mutation of that resource"

    Design: Corner/state_machines/state_member_pause_and_resume_round_trip_bumps_version_twice
    """
    scenario.set_clock(K.CLOCK_AUG_03)
    plan = scenario.create_plan()
    member = scenario.enrol_member(plan["id"])
    assert_common_fields(member, expected_version=1)
    headers = Scenario.member_headers(member)

    paused = assert_ok(scenario.client.pause_member(member["id"], headers))
    resumed = assert_ok(scenario.client.resume_member(member["id"], headers))

    assert_fields(paused, status=K.MEMBER_PAUSED, units_out_count=0)
    assert_common_fields(paused, expected_version=2)
    assert_fields(resumed, status=K.MEMBER_ACTIVE, units_out_count=0)
    assert_common_fields(resumed, expected_version=3)


def test_resume_after_cancellation_returns_resource_terminal(scenario: Scenario) -> None:
    """Once the membership has ended, no further action reaches the state machine.

    PRD §3.2: "Because `CANCELLED` is terminal, any subsequent action on the member is refused at rank 16 with `ERR_RESOURCE_TERMINAL`."

    Design: Corner/state_machines/state_resume_after_cancellation_returns_resource_terminal
    """
    scenario.set_clock(K.CLOCK_AUG_03)
    plan = scenario.create_plan()
    member = scenario.enrol_member(plan["id"])
    headers = Scenario.member_headers(member)
    cancelled = assert_ok(scenario.client.cancel_member(member["id"], headers))
    assert_fields(cancelled, status=K.MEMBER_CANCELLED)

    response = scenario.client.resume_member(member["id"], headers)

    assert_error(response, ERR_RESOURCE_TERMINAL)
    assert_fields(scenario.read_member(member), status=K.MEMBER_CANCELLED)


def test_cancellation_is_blocked_until_the_balance_is_cleared(scenario: Scenario) -> None:
    """A charged damage fee blocks cancellation until the member settles it in full.

    PRD §3.2: "`outstanding_fee_cents` must be exactly zero, otherwise the request is refused at rank 56 with `ERR_OUTSTANDING_BALANCE`"

    Design: Corner/validations/validation_cancellation_is_blocked_until_the_balance_is_cleared
    """
    catalog = standard_catalog(scenario)
    turn = turn_to_delivery(scenario, catalog)
    turn_to_receipt(scenario, catalog, turn)
    scenario.file_inspection(
        catalog.inspector,
        turn.job_id,
        soil_level=K.SOIL_LIGHT,
        damage_severity=K.DAMAGE_MODERATE,
        condition_grade_after=K.GRADE_B,
    )
    claim = scenario.claim_for_reservation(turn.reservation_id)
    scenario.assess(claim["id"])
    scenario.charge(claim["id"])
    headers = Scenario.member_headers(catalog.member)

    blocked = scenario.client.cancel_member(catalog.member_id, headers)
    assert_error(blocked, ERR_OUTSTANDING_BALANCE)
    assert_fields(scenario.read_member(catalog.member), status=K.MEMBER_ACTIVE)

    settlement = scenario.settle(catalog.member, 9000)
    assert_money(settlement, balance_after_cents=0)

    cancelled = assert_ok(scenario.client.cancel_member(catalog.member_id, headers))
    assert_fields(cancelled, status=K.MEMBER_CANCELLED)
    rows, _ = assert_list(
        scenario.client.list_reservations(headers, {"member_id": catalog.member_id}),
        total_count=1,
    )
    assert_fields(rows[0], state=K.RES_RETURNED)


def test_pause_is_blocked_while_a_unit_is_in_the_member_possession(
    scenario: Scenario,
) -> None:
    """Pausing waits until the held garment is back at the warehouse.

    PRD §3.2: "their `units_out_count` — the number of their reservations sitting in `MATCHED`, `SHIPPED`, `IN_POSSESSION` or `RETURN_INITIATED` — must be exactly zero"

    Design: Corner/validations/validation_pause_is_blocked_while_a_unit_is_in_the_member_possession
    """
    catalog = standard_catalog(scenario)
    turn = turn_to_delivery(scenario, catalog)
    headers = Scenario.member_headers(catalog.member)

    blocked = scenario.client.pause_member(catalog.member_id, headers)
    assert_error(blocked, ERR_UNITS_STILL_OUT)
    assert_fields(
        scenario.read_member(catalog.member),
        status=K.MEMBER_ACTIVE,
        units_out_count=1,
    )

    turn_to_receipt(scenario, catalog, turn)

    paused = assert_ok(scenario.client.pause_member(catalog.member_id, headers))
    assert_fields(paused, status=K.MEMBER_PAUSED, units_out_count=0)
    assert_fields(scenario.read_reservation(turn.reservation_id), state=K.RES_RETURNED)


def test_style_preferences_patch_updates_only_the_supplied_keys(
    scenario: Scenario,
) -> None:
    """A patch carrying only the size profile leaves the stored categories intact.

    PRD §3.2: "A member may revise their own styling preferences at any time, supplying either or both of `preferred_categories` and `size_profile`; omitted fields keep their stored values."

    Design: Corner/endpoints/endpoint_style_preferences_patch_updates_only_the_supplied_keys
    """
    scenario.set_clock(K.CLOCK_AUG_03)
    plan = scenario.create_plan()
    member = scenario.enrol_member(
        plan["id"],
        preferred_categories=[K.CATEGORY_GOWN, K.CATEGORY_DRESS],
        size_profile=K.SIZE_M,
    )
    headers = Scenario.member_headers(member)

    both = assert_ok(
        scenario.client.update_style_preferences(
            member["id"],
            F.style_preferences_payload(
                preferred_categories=[K.CATEGORY_KNITWEAR, K.CATEGORY_ACCESSORY],
                size_profile=K.SIZE_S,
            ),
            headers,
        )
    )
    assert_fields(
        both,
        preferred_categories=[K.CATEGORY_KNITWEAR, K.CATEGORY_ACCESSORY],
        size_profile=K.SIZE_S,
    )

    partial = assert_ok(
        scenario.client.update_style_preferences(
            member["id"], F.style_preferences_payload(size_profile=K.SIZE_L), headers
        )
    )
    assert_fields(
        partial,
        size_profile=K.SIZE_L,
        preferred_categories=[K.CATEGORY_KNITWEAR, K.CATEGORY_ACCESSORY],
        status=K.MEMBER_ACTIVE,
    )

    summary = assert_ok(
        scenario.client.get_personalization_summary(member["id"], headers)
    )
    assert_fields(
        summary,
        preferred_categories=[K.CATEGORY_KNITWEAR, K.CATEGORY_ACCESSORY],
        size_profile=K.SIZE_L,
        feedback_count=0,
        fit_confidence_score=50,
        dominant_fit_rating=None,
    )


def _waitlisted_and_paused(scenario: Scenario):
    """A single-slot member whose only slot is held by a waitlisted reservation."""
    scenario.set_clock(K.CLOCK_AUG_03)
    plan = scenario.create_plan(F.solo1_plan_payload())
    style = scenario.create_style(F.dress_style_payload())
    member = scenario.enrol_member(plan["id"])
    waitlisted = scenario.create_reservation(member, style["id"], K.WINDOW_AUG_10_16)
    assert_fields(waitlisted, state=K.RES_WAITLISTED, waitlist_position=1)
    assert_ok(
        scenario.client.pause_member(member["id"], Scenario.member_headers(member))
    )
    return style, member, waitlisted


def test_paused_member_with_a_waitlist_held_slot_reports_member_not_active(
    scenario: Scenario,
) -> None:
    """The active-status rung fires first even though the slot ceiling is also breached.

    PRD §3.2: "Being `ACTIVE` is a precondition for a great deal, and rank 14 enforces it on exactly five operations: creating a reservation, swapping a reservation, initiating a return, creating a shipping leg, and dispatching an outbound leg."

    Design: Difficulty/priority_pair_validation_conflict/paused_member_with_slot_held_by_waitlist_returns_member_not_active
    """
    style, member, waitlisted = _waitlisted_and_paused(scenario)
    headers = Scenario.member_headers(member)

    response = scenario.client.create_reservation(
        F.reservation_payload(style["id"], K.SIZE_M, *K.WINDOW_AUG_20_24), headers
    )

    assert_error(response, ERR_MEMBER_NOT_ACTIVE)
    rows, _ = assert_list(
        scenario.client.list_reservations(headers, {"member_id": member["id"]}),
        total_count=1,
    )
    assert_fields(rows[0], id=waitlisted["id"], state=K.RES_WAITLISTED, waitlist_position=1)
    assert_fields(
        scenario.read_member(member), status=K.MEMBER_PAUSED, units_out_count=0
    )


def test_resumed_member_with_a_waitlist_held_slot_reports_item_slots_exhausted(
    scenario: Scenario,
) -> None:
    """Resuming exposes the fiscal rule the status rung had merely outranked.

    PRD §3.3: "At rank 50, before any unit is allocated, the member's `units_out_count` plus the count of their `WAITLISTED` reservations must be strictly less than the plan's `item_slots`"

    Design: Difficulty/priority_pair_validation_conflict/paused_member_with_slot_held_by_waitlist_returns_member_not_active
    """
    style, member, _ = _waitlisted_and_paused(scenario)
    headers = Scenario.member_headers(member)
    body = F.reservation_payload(style["id"], K.SIZE_M, *K.WINDOW_AUG_20_24)

    assert_error(
        scenario.client.create_reservation(body, headers), ERR_MEMBER_NOT_ACTIVE
    )
    resumed = assert_ok(scenario.client.resume_member(member["id"], headers))
    assert_fields(resumed, status=K.MEMBER_ACTIVE)

    response = scenario.client.create_reservation(body, headers)

    assert_error(response, ERR_ITEM_SLOTS_EXHAUSTED)
    assert_list(
        scenario.client.list_reservations(headers, {"member_id": member["id"]}),
        total_count=1,
    )
