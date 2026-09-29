"""Swaps, the swap allowance and the optimistic-concurrency tokens.

A swap is the only reservation operation guarded by an expected-version token,
and it is also the only way a turn can be attributed half of the plan's
per-turn revenue.  The tests here pin four things: the halved revenue stamped
when a swap turn closes, the behaviour of a stale member token (rejected, and
still rejected on replay), the rental unit's version walking up by exactly one
on every write that touches it, and the monthly swap allowance rejecting at
exact equality rather than one swap later.
"""

from __future__ import annotations

from typing import Tuple

from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers.api_errors import (
    ERR_STALE_MEMBER_VERSION,
    ERR_SWAP_ALLOWANCE_EXHAUSTED,
)
from test_helpers.assertions import (
    assert_created,
    assert_error,
    assert_fields,
    assert_list,
    assert_money,
    assert_ok,
    assert_unit_position,
    canonical_instant,
)
from test_helpers.fixtures import Scenario, standard_catalog

JsonDict = dict


def _swap(
    scenario: Scenario,
    member: JsonDict,
    reservation_id: str,
    style_id: str,
    window: Tuple[str, str],
    expected_member_version: int,
):
    """Post a swap for ``reservation_id`` and hand the raw response back."""
    body = F.swap_payload(
        expected_member_version=expected_member_version,
        style_id=style_id,
        requested_size=K.SIZE_M,
        requested_start_date=window[0],
        requested_end_date=window[1],
    )
    return scenario.client.swap_reservation(
        reservation_id, body, Scenario.member_headers(member)
    )


def test_swap_turn_closes_at_half_the_plan_per_turn_revenue(scenario: Scenario) -> None:
    """A closed swap turn books 1,667 cents, half of the 3,333-cent base.

    PRD §3.5: "If `is_swap` is true, the attributed revenue is half the base figure, again rounded half up — so a base of 3,333 cents becomes 1,667 cents on a swap turn, rounding upward rather than truncating."

    Design: Corner/calculations/calc_swap_turn_attributes_half_the_base_per_turn_revenue
    """
    catalog = standard_catalog(scenario)
    member = catalog.member

    original = scenario.create_reservation(member, catalog.style_id, K.WINDOW_AUG_05_09)
    member_version = scenario.read_member(member)["version"]
    swapped = assert_created(
        _swap(
            scenario,
            member,
            original["id"],
            catalog.style_id,
            K.WINDOW_AUG_06_10,
            member_version,
        )
    )
    assert swapped["allocated_unit_id"] == catalog.unit["id"]

    outbound = scenario.create_outbound_leg(
        swapped["id"], "2026-08-06", K.CARRIER_OUT_AUG_06
    )
    scenario.set_clock(K.CLOCK_AUG_06_0800)
    scenario.dispatch(catalog.inspector, outbound["id"])
    scenario.deliver(catalog.inspector, outbound["id"])

    scenario.set_clock(K.CLOCK_AUG_10_1700)
    inbound = scenario.initiate_return(
        member, swapped["id"], carrier_reference=K.CARRIER_IN_AUG_10
    )
    scenario.dispatch(catalog.inspector, inbound["id"])
    scenario.set_clock(K.CLOCK_AUG_11_0900)
    scenario.receive(catalog.inspector, inbound["id"])

    job = scenario.job_for_reservation(catalog.inspector, swapped["id"])
    scenario.file_inspection(catalog.inspector, job["id"])
    scenario.photograph(catalog.inspector, job["id"])

    restocked = scenario.restock(catalog.repairer, job["id"])
    assert_fields(restocked, state=K.JOB_RESTOCKED)

    closed = scenario.read_reservation(swapped["id"])
    assert_fields(
        closed,
        is_swap=True,
        state=K.RES_CLOSED,
        superseded_reservation_id=original["id"],
        rental_days=5,
        late_days=0,
    )
    assert_money(
        closed,
        revenue_attributed_cents=K.PLAN_SIG4_SWAP_REVENUE_PER_TURN_CENTS,
        late_fee_cents=0,
    )

    superseded = scenario.read_reservation(original["id"])
    assert_fields(superseded, state=K.RES_SUPERSEDED)
    assert_money(superseded, revenue_attributed_cents=0)

    unit = scenario.read_unit(catalog.unit["id"])
    assert_fields(unit, turns_completed=1)
    assert_money(unit, realized_revenue_cents=K.PLAN_SIG4_SWAP_REVENUE_PER_TURN_CENTS)

    assert_list(
        scenario.client.list_fee_ledger_entries(
            scenario.admin, {"member_id": catalog.member_id}
        ),
        total_count=0,
    )


def test_stale_member_token_on_a_second_swap_is_rejected_and_stays_rejected(
    scenario: Scenario,
) -> None:
    """A member version captured before the first swap never works again.

    PRD §2.6: "the swap is rejected at rank 12 with `ERR_STALE_MEMBER_VERSION` and HTTP status 412, and nothing is superseded, released or allocated"

    Design: Corner/complexity_layers/layer_stale_member_version_on_a_second_swap_is_rejected_and_stays_rejected
    """
    catalog = standard_catalog(
        scenario, unit_codes=(K.UNIT_GOWN_001, K.UNIT_GOWN_002)
    )
    member = catalog.member

    original = scenario.create_reservation(member, catalog.style_id, K.WINDOW_AUG_05_09)
    captured_version = scenario.read_member(member)["version"]
    swapped = assert_created(
        _swap(
            scenario,
            member,
            original["id"],
            catalog.style_id,
            K.WINDOW_AUG_06_10,
            captured_version,
        )
    )

    for _ in range(2):
        assert_error(
            _swap(
                scenario,
                member,
                swapped["id"],
                catalog.style_id,
                K.WINDOW_AUG_14_18,
                captured_version,
            ),
            ERR_STALE_MEMBER_VERSION,
        )

    assert_list(
        scenario.client.list_reservations(
            Scenario.member_headers(member), {"member_id": catalog.member_id}
        ),
        total_count=2,
    )
    assert_fields(scenario.read_reservation(original["id"]), state=K.RES_SUPERSEDED)
    assert_fields(
        scenario.read_reservation(swapped["id"]),
        state=K.RES_MATCHED,
        is_swap=True,
        requested_start_date=K.WINDOW_AUG_06_10[0],
        requested_end_date=K.WINDOW_AUG_06_10[1],
    )
    assert_fields(
        scenario.read_member(member),
        swaps_used_current_month=1,
        units_out_count=1,
    )


def test_rental_unit_version_steps_up_on_every_write_that_touches_it(
    scenario: Scenario,
) -> None:
    """Allocation and release each bump the unit by exactly one version.

    PRD §2.4: "`version` is an integer that starts at 1 when the resource is created and increases by exactly 1 on every mutation of that resource, including mutations applied to it as a downstream effect of an operation aimed at some other resource."

    Design: Corner/complexity_layers/layer_rental_unit_version_increments_on_every_write_that_touches_it
    """
    catalog = standard_catalog(scenario)
    member = catalog.member

    at_rest = scenario.read_unit(catalog.unit["id"])
    assert_fields(at_rest, version=1)
    assert_unit_position(at_rest, availability_state=K.AVAIL_IN_STOCK)

    reservation = scenario.create_reservation(
        member, catalog.style_id, K.WINDOW_AUG_05_09
    )
    assert reservation["allocated_unit_id"] == catalog.unit["id"]

    allocated = scenario.read_unit(catalog.unit["id"])
    assert_fields(allocated, version=2)
    assert_unit_position(allocated, availability_state=K.AVAIL_RESERVED)

    # Move the clock so the release stamps a strictly later ``updated_at``.
    scenario.set_clock(K.CLOCK_AUG_05_0800)
    released = assert_ok(
        scenario.client.release_reservation(
            reservation["id"], Scenario.member_headers(member)
        )
    )
    assert_fields(released, state=K.RES_RELEASED)

    back_on_floor = scenario.read_unit(catalog.unit["id"])
    assert_fields(back_on_floor, version=3)
    assert_unit_position(back_on_floor, availability_state=K.AVAIL_IN_STOCK)
    assert canonical_instant(back_on_floor["created_at"]) == canonical_instant(
        at_rest["created_at"]
    )
    assert canonical_instant(back_on_floor["updated_at"]) > canonical_instant(
        at_rest["updated_at"]
    )


def _swap_twice_up_to_the_cap(scenario: Scenario):
    """Book a garment on SIG4 and swap it twice, re-reading the token each time.

    SIG4 allows two swaps a month, so the second swap lands the member exactly
    on the cap without crossing it.  Two units are stocked so the superseding
    allocation always finds a garment.
    """
    catalog = standard_catalog(scenario, unit_codes=(K.UNIT_GOWN_001, K.UNIT_GOWN_002))
    member = catalog.member

    first = scenario.create_reservation(member, catalog.style_id, K.WINDOW_AUG_10_16)
    assert_fields(first, state=K.RES_MATCHED)

    second = assert_created(
        _swap(
            scenario,
            member,
            first["id"],
            catalog.style_id,
            K.WINDOW_AUG_11_17,
            scenario.read_member(member)["version"],
        )
    )
    used_after_first = scenario.read_member(member)["swaps_used_current_month"]

    third = assert_created(
        _swap(
            scenario,
            member,
            second["id"],
            catalog.style_id,
            K.WINDOW_AUG_12_18,
            scenario.read_member(member)["version"],
        )
    )
    used_after_second = scenario.read_member(member)["swaps_used_current_month"]

    return catalog, member, first, second, third, used_after_first, used_after_second


def test_swap_below_the_monthly_cap_succeeds_up_to_exact_equality(
    scenario: Scenario,
) -> None:
    """Two swaps on a two-swap plan both succeed, taking the count to the cap.

    PRD §3.3: "Equality rejects — a member whose plan allows two swaps per month and who already has two swap-created reservations this month is refused, while a member sitting at one succeeds."

    Design: Difficulty/boundary_precision_check/swap_allowance_rejects_at_exact_monthly_cap
    """
    (
        _catalog,
        _member,
        first,
        second,
        third,
        used_after_first,
        used_after_second,
    ) = _swap_twice_up_to_the_cap(scenario)

    # Each swap supersedes the reservation it was aimed at, so the replacement
    # the first swap produced is itself SUPERSEDED once the second swap lands,
    # and only the newest replacement rests in MATCHED.
    assert_fields(
        scenario.read_reservation(second["id"]),
        is_swap=True,
        state=K.RES_SUPERSEDED,
        superseded_reservation_id=first["id"],
    )
    assert_fields(scenario.read_reservation(first["id"]), state=K.RES_SUPERSEDED)
    assert_fields(
        scenario.read_reservation(third["id"]),
        is_swap=True,
        state=K.RES_MATCHED,
        superseded_reservation_id=second["id"],
    )

    assert used_after_first == 1
    assert used_after_first < K.PLAN_SIG4_SWAPS_ALLOWED
    assert used_after_second == K.PLAN_SIG4_SWAPS_ALLOWED


def test_swap_at_exact_monthly_cap_is_refused_as_allowance_exhausted(
    scenario: Scenario,
) -> None:
    """Sitting exactly on the cap, a third swap with a fresh token is refused.

    PRD §3.3: "The swap allowance is checked at rank 51: the member's `swaps_used_current_month` must be strictly less than the plan's `monthly_swaps_allowed`, otherwise the request is refused with `ERR_SWAP_ALLOWANCE_EXHAUSTED` (409)."

    Design: Difficulty/boundary_precision_check/swap_allowance_rejects_at_exact_monthly_cap
    """
    (
        catalog,
        member,
        _first,
        _second,
        third,
        _used_after_first,
        used_after_second,
    ) = _swap_twice_up_to_the_cap(scenario)
    assert used_after_second == K.PLAN_SIG4_SWAPS_ALLOWED

    refused = _swap(
        scenario,
        member,
        third["id"],
        catalog.style_id,
        K.WINDOW_AUG_13_19,
        scenario.read_member(member)["version"],
    )
    assert_error(refused, ERR_SWAP_ALLOWANCE_EXHAUSTED)

    assert_fields(
        scenario.read_member(member),
        swaps_used_current_month=K.PLAN_SIG4_SWAPS_ALLOWED,
    )
    assert_fields(scenario.read_reservation(third["id"]), state=K.RES_MATCHED)
    assert_list(
        scenario.client.list_reservations(
            Scenario.member_headers(member), {"member_id": catalog.member_id}
        ),
        total_count=3,
    )
