"""Brewer maintenance: the bounded awaiting-parts cycle, the descale gate on a
preventive sign-off, and the closed-interval loaner calendar with its
one-day sanitation hold.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_client import api_client
from test_helpers.assertions import assert_equipment_asset, assert_work_order
from test_helpers.fixtures import (
    ANCHOR_MONDAY,
    advance_work_order,
    cancel_account,
    create_account,
    create_asset,
    create_site,
    create_work_order,
    list_work_orders,
    loaner_return,
    loaner_swap,
    place_asset_at_site,
    plan_site,
    read_asset,
    read_site,
    read_work_order,
    retrieve_placement,
    set_clock,
    setup_placed_site,
    setup_second_site,
    setup_work_order_in_progress,
)
from test_helpers.test_users import make_route_technician_headers

FIRST_ETA = "2026-08-06T00:00:00Z"
SECOND_ETA = "2026-08-10T00:00:00Z"
THIRD_ETA = "2026-08-14T00:00:00Z"
FOURTH_ETA = "2026-08-18T00:00:00Z"


def _tech(route_id: str) -> dict:
    return make_route_technician_headers(route_id)


def _work_order_at_three_awaiting_parts_entries():
    """A repair order that has bounced into AWAITING_PARTS three times and is
    back at IN_PROGRESS, so its cycle counter stands at the declared cap."""
    base = setup_work_order_in_progress(
        clock=ANCHOR_MONDAY,
        wo_type="REPAIR",
        terms_type="RENTAL",
        minimum_purchase_cents=60000,
        serial_number="URN30-0001",
    )
    route_id = base["route"]["id"]
    wo_id = base["work_order"]["id"]
    for eta in (FIRST_ETA, SECOND_ETA, THIRD_ETA):
        advance_work_order(wo_id, route_id, "AWAITING_PARTS", parts_eta=eta)
        advance_work_order(wo_id, route_id, "IN_PROGRESS")
    base["work_order"] = read_work_order(wo_id)
    return base


def test_awaiting_parts_may_be_entered_three_times_and_the_fourth_is_refused():
    """Three round trips through the waiting-for-parts state are accepted and
    counted; a fourth entry is refused and stamps nothing.

    "Entering `AWAITING_PARTS` requires a `parts_eta` instant recording when the
    parts are expected, stamps it, and increases `awaiting_parts_cycles` by 1.
    That counter is capped: the work order may enter `AWAITING_PARTS` at most
    three times, so a fourth attempt — one made while `awaiting_parts_cycles`
    already stands at 3 — is rejected with `ERR_AWAITING_PARTS_LIMIT_REACHED`
    (HTTP 422)."

    "The middle pair is a true cycle: a technician may bounce between working and
    waiting for parts repeatedly."

    Design: Difficulty/non_linear_state_machine/work_order_awaiting_parts_cycle_bounded_at_three_entries
    """
    base = _work_order_at_three_awaiting_parts_entries()
    work_order = base["work_order"]
    assert_work_order(work_order)
    assert work_order["awaiting_parts_cycles"] == 3
    assert work_order["wo_status"] == "IN_PROGRESS"
    assert work_order["parts_eta"] == THIRD_ETA

    refused = api_client.advance_work_order(
        work_order["id"],
        f.advance_work_order_payload("AWAITING_PARTS", parts_eta=FOURTH_ETA),
        _tech(base["route"]["id"]),
    )
    validate_error(refused, "ERR_AWAITING_PARTS_LIMIT_REACHED", 422)

    after = read_work_order(work_order["id"])
    assert after["awaiting_parts_cycles"] == 3, "the refused entry must not count"
    assert after["wo_status"] == "IN_PROGRESS"
    assert after["parts_eta"] == THIRD_ETA, "the refused fourth entry stamped nothing"
    assert after["loaner_status"] == "NONE"
    assert after["version"] == work_order["version"]


def test_the_parts_eta_is_restamped_on_each_entry_and_the_cap_outranks_it():
    """Each entry overwrites the expected-parts instant, the missing-field check
    fires when the transition genuinely needs it, and once the counter is at the
    cap the cap answers first even though the field is also absent.

    "The `parts_eta` is recorded afresh on **each** entry, so the field always
    reflects the current wait rather than the first one."

    "The two conditionally-required transition fields are checked **after** the
    descale gate and after the cycle cap. `parts_eta` is required when the
    requested status is `AWAITING_PARTS` and `resolution_note` is required when it
    is `RESOLVED`; omitting either where the requested transition needs it yields
    `ERR_MISSING_TRANSITION_FIELD` (HTTP 422)."

    Design: Difficulty/non_linear_state_machine/work_order_awaiting_parts_cycle_bounded_at_three_entries
    """
    base = setup_work_order_in_progress(
        clock=ANCHOR_MONDAY,
        wo_type="REPAIR",
        terms_type="RENTAL",
        minimum_purchase_cents=60000,
        serial_number="URN30-0001",
    )
    route_id = base["route"]["id"]
    wo_id = base["work_order"]["id"]

    # Nothing is waiting yet, so the counter is 0 and the field is null.
    assert base["work_order"]["awaiting_parts_cycles"] == 0
    assert base["work_order"]["parts_eta"] is None

    # The first entry needs the instant, and refusing it changes nothing.
    missing = api_client.advance_work_order(
        wo_id, f.advance_work_order_payload("AWAITING_PARTS"), _tech(route_id)
    )
    validate_error(missing, "ERR_MISSING_TRANSITION_FIELD", 422)
    still_working = read_work_order(wo_id)
    assert still_working["wo_status"] == "IN_PROGRESS"
    assert still_working["awaiting_parts_cycles"] == 0
    assert still_working["parts_eta"] is None

    first = advance_work_order(wo_id, route_id, "AWAITING_PARTS", parts_eta=FIRST_ETA)
    assert first["wo_status"] == "AWAITING_PARTS"
    assert first["awaiting_parts_cycles"] == 1
    assert first["parts_eta"] == FIRST_ETA

    advance_work_order(wo_id, route_id, "IN_PROGRESS")
    second = advance_work_order(wo_id, route_id, "AWAITING_PARTS", parts_eta=SECOND_ETA)
    assert second["awaiting_parts_cycles"] == 2
    assert second["parts_eta"] == SECOND_ETA, "the current wait replaces the first one"

    advance_work_order(wo_id, route_id, "IN_PROGRESS")
    third = advance_work_order(wo_id, route_id, "AWAITING_PARTS", parts_eta=THIRD_ETA)
    assert third["awaiting_parts_cycles"] == 3
    assert third["parts_eta"] == THIRD_ETA

    advance_work_order(wo_id, route_id, "IN_PROGRESS")

    # A fourth entry that ALSO omits the instant surfaces the cap, because the
    # conditionally-required field is checked after the cycle cap.
    both_wrong = api_client.advance_work_order(
        wo_id, f.advance_work_order_payload("AWAITING_PARTS"), _tech(route_id)
    )
    error = validate_error(both_wrong, "ERR_AWAITING_PARTS_LIMIT_REACHED", 422)
    assert error["error_id"] != "ERR_MISSING_TRANSITION_FIELD"

    # The order is still resolvable: the cap bounds only the waiting state.
    resolved = advance_work_order(
        wo_id, route_id, "RESOLVED", resolution_note="Pump seal replaced"
    )
    assert resolved["wo_status"] == "RESOLVED"
    assert resolved["awaiting_parts_cycles"] == 3
    assert resolved["parts_eta"] == THIRD_ETA


DESCALE_OVERDUE_CLOCK = "2026-11-10T08:00:00Z"


def _overdue_brewer(wo_type: str = "PREVENTIVE"):
    """A placed brewer registered ninety-nine days ago, so its ninety-day descale
    clock has run out, carrying one work order of the requested kind in progress."""
    base = setup_placed_site(
        clock=ANCHOR_MONDAY,
        terms_type="RENTAL",
        minimum_purchase_cents=60000,
        serial_number="URN30-0001",
    )
    assert base["asset"]["last_descale_at"] == ANCHOR_MONDAY
    set_clock(DESCALE_OVERDUE_CLOCK)
    route_id = base["route"]["id"]
    work_order = create_work_order(base["asset"]["id"], route_id, wo_type)
    base["work_order"] = advance_work_order(
        work_order["id"], route_id, "IN_PROGRESS"
    )
    return base


def test_a_preventive_signoff_is_blocked_until_a_descale_order_clears_the_clock():
    """The preventive order cannot be signed off while the brewer is
    descale-overdue; resolving a descale order on the same brewer rewrites the
    asset's clock and the identical sign-off then succeeds.

    "Second — and only for a `PREVENTIVE` order — the brewer must not be
    descale-overdue: the elapsed time from the asset's `last_descale_at` to the
    current instant must not exceed the model's `descale_interval_days`. When it
    does, the preventive order cannot be signed off and is rejected with
    `ERR_DESCALE_OVERDUE` (HTTP 422); a `DESCALE` work order must be resolved
    first."

    "Resolving a `DESCALE` order sets the asset's `last_descale_at` to the current
    instant, which is the only way the descale clock is ever reset."

    Design: Difficulty/cross_entity_state_dependency/preventive_work_order_resolution_depends_on_asset_descale_state
    """
    base = _overdue_brewer("PREVENTIVE")
    route_id = base["route"]["id"]
    preventive_id = base["work_order"]["id"]
    note = "Quarterly inspection complete"

    refused = api_client.advance_work_order(
        preventive_id,
        f.advance_work_order_payload("RESOLVED", resolution_note=note),
        _tech(route_id),
    )
    validate_error(refused, "ERR_DESCALE_OVERDUE", 422)

    blocked = read_work_order(preventive_id)
    assert blocked["wo_status"] == "IN_PROGRESS", "the blocked order never changes"
    assert blocked["resolution_note"] is None
    asset = read_asset(base["asset"]["id"])
    assert asset["last_descale_at"] == ANCHOR_MONDAY, "the refusal reset nothing"

    # The sibling entity's field is what unblocks it.
    descale = create_work_order(base["asset"]["id"], route_id, "DESCALE")
    advance_work_order(descale["id"], route_id, "IN_PROGRESS")
    descale = advance_work_order(
        descale["id"], route_id, "RESOLVED", resolution_note="Boiler descaled"
    )
    assert descale["wo_status"] == "RESOLVED"
    descaled_asset = read_asset(base["asset"]["id"])
    assert_equipment_asset(descaled_asset)
    assert descaled_asset["last_descale_at"] == DESCALE_OVERDUE_CLOCK

    accepted = validate_success(
        api_client.advance_work_order(
            preventive_id,
            f.advance_work_order_payload("RESOLVED", resolution_note=note),
            _tech(route_id),
        ),
        200,
    )
    assert accepted["wo_status"] == "RESOLVED"
    assert accepted["resolution_note"] == note

    site = read_site(base["site"]["id"])
    assert float(site["escalation_score"]) == 0.0
    assert site["service_posture"] == "ACTIVE"


def test_a_repair_order_ignores_the_descale_gate_and_scores_the_overdue_clock():
    """Corrective work signs off on the very same overdue brewer that blocks a
    preventive sign-off, and its resolution recomputes the break room's score
    with the overdue descale still counted; a later descale order clears it.

    "`REPAIR` orders are not subject to the descale gate."

    "Any resolution then recomputes the site's `escalation_score`, because
    clearing an overdue descale removes 15.0 points from it; that recomputation
    can move the site `ESCALATED` → `ACTIVE` and from there the account `AT_RISK`
    → `ACTIVE`, restoring the account's deferred price adjustments."

    "The **overdue-descale count** is the number of assets installed at the site
    through a placement whose installation status is `ACTIVE` for which the
    descale clock has run out, meaning the asset's `last_descale_at` advanced by
    the model's `descale_interval_days` is at or before the current instant;
    placements that are `RETRIEVED` or `SUPERSEDED` never contribute."

    Design: Difficulty/cross_entity_state_dependency/preventive_work_order_resolution_depends_on_asset_descale_state
    """
    base = _overdue_brewer("REPAIR")
    route_id = base["route"]["id"]

    repaired = advance_work_order(
        base["work_order"]["id"],
        route_id,
        "RESOLVED",
        resolution_note="Grinder burr replaced",
    )
    assert repaired["wo_status"] == "RESOLVED"
    assert repaired["wo_type"] == "REPAIR"

    # The corrective sign-off did not touch the descale clock.
    asset = read_asset(base["asset"]["id"])
    assert asset["last_descale_at"] == ANCHOR_MONDAY

    # But it did recompute the score, which still carries the overdue descale.
    scored = read_site(base["site"]["id"])
    assert float(scored["escalation_score"]) == 15.0
    assert scored["service_posture"] == "ACTIVE", "15.0 is below the 40.0 threshold"

    # A preventive order on the same brewer is still gated.
    preventive = create_work_order(base["asset"]["id"], route_id, "PREVENTIVE")
    advance_work_order(preventive["id"], route_id, "IN_PROGRESS")
    validate_error(
        api_client.advance_work_order(
            preventive["id"],
            f.advance_work_order_payload("RESOLVED", resolution_note="Inspected"),
            _tech(route_id),
        ),
        "ERR_DESCALE_OVERDUE",
        422,
    )

    descale = create_work_order(base["asset"]["id"], route_id, "DESCALE")
    advance_work_order(descale["id"], route_id, "IN_PROGRESS")
    advance_work_order(
        descale["id"], route_id, "RESOLVED", resolution_note="Boiler descaled"
    )
    assert read_asset(base["asset"]["id"])["last_descale_at"] == DESCALE_OVERDUE_CLOCK

    cleared = read_site(base["site"]["id"])
    assert float(cleared["escalation_score"]) == 0.0
    assert cleared["service_posture"] == "ACTIVE"


OUT_ON_THE_THIRD = "2026-08-03T00:00:00Z"
DUE_BACK_ON_THE_TENTH = "2026-08-10T00:00:00Z"
RETURNED_ON_THE_TENTH = "2026-08-10T00:00:00Z"
RECONDITIONING_UNTIL_THE_ELEVENTH = "2026-08-11T00:00:00Z"


def _loaner_returned_on_the_tenth(second_order_in_progress: bool = True):
    """One substitute brewer held from the third through the tenth and returned on
    the tenth, plus a second work order at another break room that wants it."""
    base = setup_placed_site(
        clock=ANCHOR_MONDAY,
        terms_type="RENTAL",
        minimum_purchase_cents=60000,
        serial_number="URN30-0001",
    )
    route_id = base["route"]["id"]
    site_b = setup_second_site(base, site_name="HQ Floor 4")
    asset_b = create_asset(base["model"]["id"], serial_number="URN30-0002")
    place_asset_at_site(
        site_b, asset_b["id"], terms_type="RENTAL", minimum_purchase_cents=60000
    )
    loaner = create_asset(
        base["model"]["id"], serial_number="LNR-0001", asset_role="LOANER"
    )

    first = create_work_order(base["asset"]["id"], route_id, "REPAIR")
    first = loaner_swap(
        first["id"], route_id, loaner["id"], OUT_ON_THE_THIRD, DUE_BACK_ON_THE_TENTH
    )
    assert first["loaner_status"] == "OUT"

    second = create_work_order(asset_b["id"], route_id, "REPAIR")
    if second_order_in_progress:
        second = advance_work_order(second["id"], route_id, "IN_PROGRESS")

    set_clock("2026-08-10T09:00:00Z")
    first = loaner_return(first["id"], route_id, RETURNED_ON_THE_TENTH)

    base["site_b"] = site_b
    base["asset_b"] = asset_b
    base["loaner"] = loaner
    base["first"] = first
    base["second"] = second
    return base


def test_a_returned_loaner_blocks_the_abutting_reconditioning_day():
    """The day after a return is still held, so a same-day handoff on the
    eleventh is a conflict even though the sanitation hold has itself lapsed.

    "A work order whose loaner is `RETURNED` holds the asset from its
    `loaner_out_date` through its `loaner_returned_on` advanced by one
    reconditioning day, so the trailing sanitation day is blocked too."

    "Because both intervals are closed, an abutting same-day handoff **is** a
    conflict — unlike the route rule, where abutment is free. A loaner returned on
    2026-08-10 is unavailable on 2026-08-11 and free again on 2026-08-12, and the
    asset's `reconditioning_until` carries that same instant for readback."

    Design: Difficulty/resource_temporal_overlap/loaner_asset_closed_date_intervals_block_the_reconditioning_day_and_free_the_day_after
    """
    base = _loaner_returned_on_the_tenth()
    route_id = base["route"]["id"]

    assert base["first"]["loaner_status"] == "RETURNED"
    assert base["first"]["loaner_returned_on"] == RETURNED_ON_THE_TENTH
    returned_loaner = read_asset(base["loaner"]["id"])
    assert_equipment_asset(returned_loaner)
    assert returned_loaner["asset_status"] == "RECONDITIONING"
    assert returned_loaner["reconditioning_until"] == RECONDITIONING_UNTIL_THE_ELEVENTH

    # At this instant the hold no longer applies, so only the closed interval can
    # speak — and it still holds the eleventh.
    set_clock("2026-08-11T09:00:00Z")
    refused = api_client.loaner_swap(
        base["second"]["id"],
        f.loaner_swap_payload(
            base["loaner"]["id"], "2026-08-11T00:00:00Z", "2026-08-18T00:00:00Z"
        ),
        _tech(route_id),
    )
    error = validate_error(refused, "ERR_LOANER_NOT_AVAILABLE", 409)
    assert error["error_id"] != "ERR_ASSET_UNDER_SANITATION_HOLD"

    untouched = read_work_order(base["second"]["id"])
    assert untouched["loaner_status"] == "NONE"
    assert untouched["loaner_asset_id"] is None
    assert untouched["loaner_out_date"] is None
    assert untouched["loaner_due_back_date"] is None
    assert read_asset(base["loaner"]["id"])["asset_status"] == "RECONDITIONING"


def test_the_loaner_is_free_again_the_day_after_the_reconditioning_day():
    """The twelfth is outside the held interval, so the handoff is accepted, the
    hold is cleared on readback and the earlier work order is left alone.

    "The candidate occupancy is a **closed** date interval running from
    `loaner_out_date` through `loaner_due_back_date`, both endpoints included, and
    `loaner_due_back_date` must not precede `loaner_out_date`."

    "A successful swap stamps `loaner_asset_id`, `loaner_out_date` and
    `loaner_due_back_date`, moves `loaner_status` to `OUT`, and moves the loaner
    asset to `ON_LOAN` — passing lazily through `IN_STOCK` first when the asset was
    `RECONDITIONING` with an expired hold."

    Design: Difficulty/resource_temporal_overlap/loaner_asset_closed_date_intervals_block_the_reconditioning_day_and_free_the_day_after
    """
    base = _loaner_returned_on_the_tenth()
    route_id = base["route"]["id"]
    set_clock("2026-08-12T09:00:00Z")

    # A due-back date before the out date is refused on the same identifier.
    validate_error(
        api_client.loaner_swap(
            base["second"]["id"],
            f.loaner_swap_payload(
                base["loaner"]["id"], "2026-08-12T00:00:00Z", "2026-08-11T00:00:00Z"
            ),
            _tech(route_id),
        ),
        "ERR_LOANER_NOT_AVAILABLE",
        409,
    )

    accepted = validate_success(
        api_client.loaner_swap(
            base["second"]["id"],
            f.loaner_swap_payload(
                base["loaner"]["id"], "2026-08-12T00:00:00Z", "2026-08-19T00:00:00Z"
            ),
            _tech(route_id),
        ),
        200,
    )
    assert_work_order(accepted)
    assert accepted["loaner_status"] == "OUT"
    assert accepted["loaner_asset_id"] == base["loaner"]["id"]
    assert accepted["loaner_out_date"] == "2026-08-12T00:00:00Z"
    assert accepted["loaner_due_back_date"] == "2026-08-19T00:00:00Z"
    assert accepted["loaner_returned_on"] is None
    assert accepted["wo_status"] == "IN_PROGRESS", "the service dimension is untouched"

    reissued = read_asset(base["loaner"]["id"])
    assert reissued["asset_status"] == "ON_LOAN"
    assert reissued["reconditioning_until"] is None

    earlier = read_work_order(base["first"]["id"])
    assert earlier["loaner_status"] == "RETURNED"
    assert earlier["loaner_returned_on"] == RETURNED_ON_THE_TENTH
    assert earlier["loaner_asset_id"] == base["loaner"]["id"]

    holders = list_work_orders(loaner_asset_id=base["loaner"]["id"])
    assert len(holders) == 2, "the refused calls created no phantom hold row"
    assert {row["id"] for row in holders} == {
        base["first"]["id"],
        base["second"]["id"],
    }


def test_the_sanitation_hold_outranks_the_loaner_window_conflict():
    """A swap that violates both the one-day sanitation hold and the closed held
    interval answers with the hold, because the safety gate sits above every
    temporal gate.

    "Note also that the two safety gates sit **above** every temporal and fiscal
    gate. A loaner swap that names an asset still inside its sanitation hold **and**
    whose requested window collides with another work order surfaces the sanitation
    hold, not the collision."

    "The requested asset must carry the `LOANER` role (otherwise
    `ERR_ASSET_ROLE_MISMATCH`), and it must not be under sanitation hold: an asset whose
    fleet status is `RECONDITIONING` and whose `reconditioning_until` is still ahead of
    the current instant is refused with `ERR_ASSET_UNDER_SANITATION_HOLD` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/sanitation_hold_beats_loaner_window_conflict
    """
    base = _loaner_returned_on_the_tenth(second_order_in_progress=False)
    route_id = base["route"]["id"]
    assert base["second"]["wo_status"] == "OPEN"

    held = read_asset(base["loaner"]["id"])
    assert held["asset_status"] == "RECONDITIONING"
    assert held["reconditioning_until"] == RECONDITIONING_UNTIL_THE_ELEVENTH

    # Noon on the tenth is inside the hold, and the tenth is also inside the
    # closed held interval 2026-08-03 through 2026-08-11.
    set_clock("2026-08-10T12:00:00Z")
    refused = api_client.loaner_swap(
        base["second"]["id"],
        f.loaner_swap_payload(
            base["loaner"]["id"], "2026-08-10T00:00:00Z", "2026-08-17T00:00:00Z"
        ),
        _tech(route_id),
    )
    error = validate_error(refused, "ERR_ASSET_UNDER_SANITATION_HOLD", 422)
    assert error["error_id"] != "ERR_LOANER_NOT_AVAILABLE"

    untouched = read_work_order(base["second"]["id"])
    assert untouched["loaner_status"] == "NONE"
    assert untouched["loaner_asset_id"] is None
    assert untouched["wo_status"] == "OPEN"

    still_held = read_asset(base["loaner"]["id"])
    assert still_held["asset_status"] == "RECONDITIONING"
    assert still_held["reconditioning_until"] == RECONDITIONING_UNTIL_THE_ELEVENTH

    earlier = read_work_order(base["first"]["id"])
    assert earlier["loaner_status"] == "RETURNED"
    assert earlier["loaner_returned_on"] == RETURNED_ON_THE_TENTH


def _retrieved_brewer_under_hold_and_a_foreign_work_order():
    """A retrieved placement brewer sitting in its sanitation hold, and an
    unrelated work order at another program that reaches for it as a loaner."""
    base = setup_placed_site(
        clock=ANCHOR_MONDAY,
        terms_type="RENTAL",
        minimum_purchase_cents=60000,
        serial_number="URN30-0001",
    )
    route_id = base["route"]["id"]

    other_account = create_account(legal_name="Southgate Partners LLC")
    other_site = create_site(
        other_account["id"], route_id, site_name="Annex Break Room"
    )
    other_site = plan_site(other_site["id"])
    other_asset = create_asset(base["model"]["id"], serial_number="URN30-0002")
    place_asset_at_site(
        other_site, other_asset["id"], terms_type="RENTAL", minimum_purchase_cents=60000
    )
    base["other_account"] = other_account
    base["other_site"] = other_site
    base["work_order"] = create_work_order(other_asset["id"], route_id, "REPAIR")

    # Retrieving a serviceable brewer puts it under a one-day sanitation hold
    # while it keeps its PLACEMENT role.
    cancel_account(base["account"]["id"], retrieval_due_by="2026-08-31T00:00:00Z")
    retrieve_placement(base["placement"]["id"], "SERVICEABLE")
    base["asset"] = read_asset(base["asset"]["id"])
    return base


def test_the_sanitation_hold_also_outranks_the_asset_role_check():
    """A brewer that is both under sanitation hold and carrying the wrong role
    surfaces the hold; once the hold lapses the same request surfaces the role.

    "Note the precedence — the sanitation hold is checked **before** the role
    check, so a `RECONDITIONING` asset carrying the wrong role surfaces the
    sanitation hold."

    "The role is a hard partition: only a `PLACEMENT` asset may be installed at a
    site, and only a `LOANER` asset may be attached to a work order as a substitute
    unit. Using an asset in the wrong capacity in either direction is rejected with
    `ERR_ASSET_ROLE_MISMATCH` (HTTP 422)."

    "Whenever an asset enters `RECONDITIONING`, its `reconditioning_until` is set
    to one day after the moment that put it there — the current instant for a
    retrieved placement asset, the reported return date for a returned loaner."

    Design: Difficulty/priority_pair_validation_conflict/sanitation_hold_beats_loaner_window_conflict
    """
    base = _retrieved_brewer_under_hold_and_a_foreign_work_order()
    route_id = base["route"]["id"]
    wrong_role_asset = base["asset"]
    assert wrong_role_asset["asset_role"] == "PLACEMENT"
    assert wrong_role_asset["asset_status"] == "RECONDITIONING"
    assert wrong_role_asset["reconditioning_until"] == "2026-08-04T08:00:00Z"

    held = api_client.loaner_swap(
        base["work_order"]["id"],
        f.loaner_swap_payload(
            wrong_role_asset["id"], OUT_ON_THE_THIRD, "2026-08-07T00:00:00Z"
        ),
        _tech(route_id),
    )
    error = validate_error(held, "ERR_ASSET_UNDER_SANITATION_HOLD", 422)
    assert error["error_id"] != "ERR_ASSET_ROLE_MISMATCH"
    assert read_work_order(base["work_order"]["id"])["loaner_status"] == "NONE"

    # Past the hold, the role partition is what answers.
    set_clock("2026-08-05T08:00:00Z")
    mismatched = api_client.loaner_swap(
        base["work_order"]["id"],
        f.loaner_swap_payload(
            wrong_role_asset["id"], "2026-08-05T00:00:00Z", "2026-08-12T00:00:00Z"
        ),
        _tech(route_id),
    )
    validate_error(mismatched, "ERR_ASSET_ROLE_MISMATCH", 422)

    after = read_work_order(base["work_order"]["id"])
    assert after["loaner_status"] == "NONE"
    assert after["loaner_asset_id"] is None
    assert list_work_orders(loaner_asset_id=wrong_role_asset["id"]) == []
