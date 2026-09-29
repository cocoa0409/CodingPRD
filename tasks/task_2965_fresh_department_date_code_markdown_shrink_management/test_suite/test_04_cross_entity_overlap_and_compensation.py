"""Blocking state on other entities, interval reservations and compensating actions."""

from types import SimpleNamespace

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import fixtures as F
from test_helpers.constants import MEAT_FOUR_RUNGS
from test_helpers.test_users import (
    admin_headers,
    auditor_headers,
    clerk_headers,
    make_clerk_headers,
    make_manager_headers,
    make_partner_headers,
    manager_headers,
)


def _build_meat_lot_whose_ladder_was_retired(api):
    """A priceable FRESH lot whose department points at a RETIRED ladder, plus a spare ACTIVE one."""
    chain = F.build_meat_four_rung_chain(api)
    chain.ladder_b = F.build_ladder(
        api,
        name="MEAT-STD-2026-B",
        department_code="MEAT",
        rungs=[dict(rung) for rung in MEAT_FOUR_RUNGS],
        sell_through_floor_pct=60,
        max_total_discount_pct=75,
    )
    F.set_clock(api, "2026-08-12T00:00:00.000Z")
    chain.ladder = validate_success(
        api.retire_markdown_ladder(chain.ladder["id"], admin_headers())
    )
    return chain


def test_a_retired_ladder_on_another_entity_blocks_the_markdown(api):
    """The refusal comes from the MarkdownLadder row, which the markdown request never names.

    PRD 3.1: "retirement requires `status` to be `ACTIVE`, refusing anything else
    with `ERR_LADDER_NOT_ACTIVE`, moves `status` from `ACTIVE` to `RETIRED`, and
    bumps `version` by one. **Retirement never rewrites already-priced lots.** Every
    department still pointing at the retired ladder keeps its existing shelf prices
    exactly as they stand; retirement only closes the pricing gate, so any later
    markdown attempt on those departments' lots is refused with
    `ERR_LADDER_NOT_ACTIVE`."

    PRD 2.11: "The department's ladder is active at pricing time, on markdown
    creation -- `ERR_LADDER_NOT_ACTIVE` (409)."

    The lot itself is untouched by the retirement: it is still a `FRESH`, 24-unit,
    599-cent lot with three days of life left, and only the closed pricing gate stops
    the markdown.

    Design: Difficulty/cross_entity_state_dependency/markdown_blocked_by_retired_ladder_on_other_entity
    """
    chain = _build_meat_lot_whose_ladder_was_retired(api)

    assert chain.ladder["status"] == "RETIRED"

    refused = api.create_markdown(
        chain.lot["id"],
        {"expected_lot_version": chain.lot["version"]},
        manager_headers(),
    )

    validate_error(refused, "ERR_LADDER_NOT_ACTIVE", expected_status=409)

    lot = F.reload_lot(api, chain.lot["id"])
    A.assert_unchanged(chain.lot, lot, "status", "version", "current_price_cents")
    A.assert_fresh_unpriced_lot(lot, 599)


def test_repointing_the_department_at_an_active_ladder_lets_the_same_markdown_through(api):
    """Swapping the department's markdown_ladder_id reopens the gate at 509 cents.

    PRD 2.9: A department is created with "an attached `markdown_ladder_id`", and "An
    administrator may later revise" the department, so the pricing gate is a property
    of the attached ladder rather than of the lot.

    PRD 3.3: "Alongside the label, the markdown rewrites the lot:
    `current_price_cents` becomes the label's `to_price_cents`, `current_rung_index`
    becomes the label's `rung_index`, `total_discount_pct` is recomputed".

    Ladder B carries the identical rungs, so days remaining 3 selects rung 0 at 15
    percent and 599 cents lands on 509 -- a total discount of 15.03 percent once
    rounded half up.

    Design: Difficulty/cross_entity_state_dependency/markdown_blocked_by_retired_ladder_on_other_entity
    """
    chain = _build_meat_lot_whose_ladder_was_retired(api)

    repointed = validate_success(
        api.update_department(
            chain.department["id"],
            {"markdown_ladder_id": chain.ladder_b["id"]},
            admin_headers(),
        )
    )
    assert repointed["markdown_ladder_id"] == chain.ladder_b["id"]

    label = F.cut_markdown(api, chain.lot, headers=manager_headers())

    A.assert_label(
        label,
        status="QUEUED",
        from_price_cents=599,
        to_price_cents=509,
        discount_pct=15.03,
        reason="LADDER_AUTO",
    )
    assert label["rung_index"] == 0

    lot = F.reload_lot(api, chain.lot["id"])
    A.assert_lot_pricing(lot, 509, 0, 15.03, status="MARKED_DOWN")


def _build_scheduled_pickup_for_a_suspended_partner(api):
    """A SCHEDULED pickup whose collecting partner has since been suspended."""
    F.set_clock(api, "2026-08-10T08:00:00.000Z")
    store = F.build_store(api, dock_door_codes=["D1"], donation_program_enabled=True)
    partner = F.build_partner(api)
    pickup = F.book_pickup(
        api,
        store["id"],
        partner["id"],
        dock_door_code="D1",
        scheduled_window_start="2026-08-12T14:00:00.000Z",
        scheduled_window_end="2026-08-12T16:00:00.000Z",
        headers=admin_headers(),
    )
    suspended = validate_success(
        api.update_food_bank_partner(partner["id"], {"status": "SUSPENDED"}, admin_headers())
    )
    F.set_clock(api, "2026-08-12T13:00:00.000Z")
    return SimpleNamespace(
        store=store, partner=partner, suspended=suspended, pickup=pickup
    )


def test_a_suspended_partner_row_blocks_confirmation_of_its_own_pickup(api):
    """The blocking state sits on FoodBankPartner, not on the pickup being confirmed.

    PRD 3.1: "Suspending a partner does **not** retroactively cancel pickups it has
    already confirmed; it only blocks any further confirmation, which is refused with
    `ERR_PARTNER_NOT_ACTIVE`."

    PRD 3.7: "Confirmation requires `logistics_status` to be `SCHEDULED`, refusing
    anything else with `ERR_PICKUP_NOT_CONFIRMABLE` and HTTP 409, requires the acting
    `X-User-ID` to equal the pickup's `partner_id`, and requires the partner row
    itself to still be `ACTIVE`, refusing a suspended partner with
    `ERR_PARTNER_NOT_ACTIVE`."

    The pickup row is in the one state confirmation accepts and the caller owns it, so
    the only obstacle is the other entity's status.

    Design: Difficulty/cross_entity_state_dependency/pickup_confirm_blocked_by_suspended_partner
    """
    world = _build_scheduled_pickup_for_a_suspended_partner(api)

    assert world.partner["status"] == "ACTIVE"
    assert world.suspended["status"] == "SUSPENDED"

    refused = api.confirm_donation_pickup(
        world.pickup["id"], make_partner_headers(world.partner["id"])
    )

    validate_error(refused, "ERR_PARTNER_NOT_ACTIVE", expected_status=409)

    pickup = F.reload_pickup(api, world.pickup["id"])
    A.assert_fields(pickup, logistics_status="SCHEDULED", manifest_status="DRAFT")


def test_restoring_the_partner_to_active_lets_the_same_confirmation_through(api):
    """Confirmation moves only the logistics dimension and leaves the manifest DRAFT.

    PRD 3.7: "Confirmation moves `logistics_status` from `SCHEDULED` to `CONFIRMED`,
    leaves `manifest_status` exactly as it was -- a pickup may be confirmed while its
    manifest is still `DRAFT` -- and increments `version` by one."

    PRD 3.1: "`pickups_completed_count`, the number of this partner's pickups whose
    `logistics_status` has reached `COMPLETED`".  A confirmation is not a completion,
    so that counter stays 0.

    Design: Difficulty/cross_entity_state_dependency/pickup_confirm_blocked_by_suspended_partner
    """
    world = _build_scheduled_pickup_for_a_suspended_partner(api)

    restored = validate_success(
        api.update_food_bank_partner(
            world.partner["id"], {"status": "ACTIVE"}, admin_headers()
        )
    )
    assert restored["status"] == "ACTIVE"

    confirmed = F.confirm_pickup(api, world.pickup["id"], world.partner["id"])

    A.assert_fields(confirmed, logistics_status="CONFIRMED", manifest_status="DRAFT")

    partner = validate_success(
        api.get_food_bank_partner(world.partner["id"], admin_headers())
    )
    assert partner["pickups_completed_count"] == 0


def _pickups_for_store(api, store_id):
    rows, _meta = validate_paginated(
        api.list_donation_pickups(admin_headers(), params={"store_id": store_id, "limit": 100})
    )
    return rows


def _build_store_with_one_scheduled_d1_window(api):
    """Store 0412 with docks D1 and D2 and one SCHEDULED pickup holding D1 from 14:00 to 16:00."""
    F.set_clock(api, "2026-08-11T09:00:00.000Z")
    store = F.build_store(api, dock_door_codes=["D1", "D2"], donation_program_enabled=True)
    partner = F.build_partner(api)
    pickup_p = F.book_pickup(
        api,
        store["id"],
        partner["id"],
        dock_door_code="D1",
        scheduled_window_start="2026-08-12T14:00:00.000Z",
        scheduled_window_end="2026-08-12T16:00:00.000Z",
        headers=admin_headers(),
    )
    return SimpleNamespace(store=store, partner=partner, pickup_p=pickup_p)


def _book(api, world, dock_door_code, start, end):
    return api.create_donation_pickup(
        {
            "store_id": world.store["id"],
            "partner_id": world.partner["id"],
            "dock_door_code": dock_door_code,
            "scheduled_window_start": start,
            "scheduled_window_end": end,
        },
        admin_headers(),
    )


def test_a_window_starting_exactly_thirty_minutes_after_the_last_one_still_conflicts(api):
    """The dock comparison is fully closed and widened by the full 30-minute buffer.

    PRD 2.10: "A conflict exists when the new window's `scheduled_window_start` is at
    or before the existing window's `scheduled_window_end` plus 30 minutes **and** the
    existing window's `scheduled_window_start` is at or before the new window's
    `scheduled_window_end` plus 30 minutes. Both comparisons are inclusive: a new
    window starting exactly 30 minutes after an existing window ends still conflicts,
    while one starting a single second later does not."

    PRD 2.11: "Dock window availability, on pickup creation --
    `ERR_DOCK_WINDOW_OVERLAP` (409)."

    The held window ends at 16:00:00.000Z, so the buffered edge falls on
    16:30:00.000Z; a new window starting on that exact instant is inside the closed
    comparison and is refused.

    Design: Difficulty/resource_temporal_overlap/dock_window_closed_interval_with_thirty_minute_buffer
    """
    world = _build_store_with_one_scheduled_d1_window(api)

    assert world.pickup_p["logistics_status"] == "SCHEDULED"

    refused = _book(
        api, world, "D1", "2026-08-12T16:30:00.000Z", "2026-08-12T18:00:00.000Z"
    )

    validate_error(refused, "ERR_DOCK_WINDOW_OVERLAP", expected_status=409)
    A.assert_ids_equal(_pickups_for_store(api, world.store["id"]), [world.pickup_p["id"]])


def test_the_dock_buffer_is_per_door_and_releases_one_second_later(api):
    """The refused interval is fine on D2, and one second later it is fine on D1 too.

    PRD 2.10: "A requested pickup window is compared against the store's other
    pickups on the same dock door whose `logistics_status` is `SCHEDULED` or
    `CONFIRMED`, after widening the comparison by a 30-minute turnaround buffer on
    both sides."

    PRD 3.7: "A newly booked pickup starts with `logistics_status` `SCHEDULED`,
    `manifest_status` `DRAFT`, `assignment_count` 0".

    Because the comparison is scoped to one dock door, the identical 16:30 interval is
    accepted on D2; and because the closed comparison releases immediately after the
    buffered edge, 16:30:01.000Z is accepted on D1.

    Design: Difficulty/resource_temporal_overlap/dock_window_closed_interval_with_thirty_minute_buffer
    """
    world = _build_store_with_one_scheduled_d1_window(api)

    on_d2 = validate_success(
        _book(api, world, "D2", "2026-08-12T16:30:00.000Z", "2026-08-12T18:00:00.000Z"),
        expected_status=201,
    )
    late_on_d1 = validate_success(
        _book(api, world, "D1", "2026-08-12T16:30:01.000Z", "2026-08-12T18:30:00.000Z"),
        expected_status=201,
    )

    assert on_d2["dock_door_code"] == "D2"
    A.assert_instant_equals(
        late_on_d1["scheduled_window_start"],
        "2026-08-12T16:30:01.000Z",
        "scheduled_window_start",
    )
    A.assert_fields(
        late_on_d1, logistics_status="SCHEDULED", manifest_status="DRAFT", assignment_count=0
    )
    A.assert_contains_ids(
        _pickups_for_store(api, world.store["id"]),
        [world.pickup_p["id"], on_d2["id"], late_on_d1["id"]],
    )
    assert len(_pickups_for_store(api, world.store["id"])) == 3


def _audits_for_department(api, department_id):
    rows, _meta = validate_paginated(
        api.list_compliance_audits(
            auditor_headers(), params={"department_id": department_id, "limit": 100}
        )
    )
    return rows


def _build_department_with_one_pending_audit(api):
    """A BAKERY department holding one PENDING audit over [2026-08-17, 2026-08-20)."""
    chain = F.build_bakery_chain(
        api,
        department_overrides={"shelf_life_days_default": 10},
        with_lot=False,
    )
    F.set_clock(api, "2026-08-18T00:00:00.000Z")
    chain.audit_a = F.open_audit(
        api,
        chain.department["id"],
        "2026-08-17T00:00:00.000Z",
        "2026-08-20T00:00:00.000Z",
    )
    return chain


def test_an_audit_window_starting_one_millisecond_before_the_end_overlaps(api):
    """The audit comparison is half-open and unbuffered, so the last millisecond still collides.

    PRD 2.10: "A conflict exists when the new window's `window_start_at` is strictly
    before the existing window's `window_end_at` **and** the existing window's
    `window_start_at` is strictly before the new window's `window_end_at`."

    PRD 2.11: "Audit window availability, on audit opening --
    `ERR_AUDIT_WINDOW_OVERLAP` (409)."

    The held window ends at 2026-08-20T00:00:00.000Z, and 2026-08-19T23:59:59.999Z is
    strictly before that instant, so the two windows truly overlap.

    Design: Difficulty/resource_temporal_overlap/audit_window_half_open_touching_end_is_allowed
    """
    chain = _build_department_with_one_pending_audit(api)

    A.assert_fields(chain.audit_a, disposition_status="PENDING", sweep_status="NOT_STARTED")

    refused = api.create_compliance_audit(
        {
            "department_id": chain.department["id"],
            "window_start_at": "2026-08-19T23:59:59.999Z",
            "window_end_at": "2026-08-22T00:00:00.000Z",
        },
        auditor_headers(),
    )

    validate_error(refused, "ERR_AUDIT_WINDOW_OVERLAP", expected_status=409)
    A.assert_ids_equal(
        _audits_for_department(api, chain.department["id"]), [chain.audit_a["id"]]
    )


def test_an_audit_window_abutting_the_end_exactly_is_accepted(api):
    """Because the end is exclusive, a window starting on that instant merely abuts.

    PRD 2.10: "Because both comparisons are strict, two windows may abut exactly -- an
    audit starting at the precise instant another ends is accepted -- while a single
    second of true overlap is rejected."

    PRD 3.8: "A new audit starts with `sweep_status` `NOT_STARTED`,
    `disposition_status` `PENDING`, `severity` `NONE`, `past_date_lot_count`,
    `past_date_units_total` and `severity_points_total` all 0, `swept_at` null".

    PRD 2.8 clause 2 only bites on a `MAJOR` or `CRITICAL` audit, and neither audit
    here has been swept, so both still carry `severity` `NONE` and the department stays
    `COMPLIANT`.

    Design: Difficulty/resource_temporal_overlap/audit_window_half_open_touching_end_is_allowed
    """
    chain = _build_department_with_one_pending_audit(api)

    audit_b = F.open_audit(
        api,
        chain.department["id"],
        "2026-08-20T00:00:00.000Z",
        "2026-08-22T00:00:00.000Z",
    )

    A.assert_instant_equals(
        audit_b["window_start_at"], "2026-08-20T00:00:00.000Z", "window_start_at"
    )
    A.assert_fields(
        audit_b,
        severity="NONE",
        sweep_status="NOT_STARTED",
        disposition_status="PENDING",
        past_date_lot_count=0,
        past_date_units_total=0,
        severity_points_total=0,
    )
    A.assert_contains_ids(
        _audits_for_department(api, chain.department["id"]),
        [chain.audit_a["id"], audit_b["id"]],
    )
    assert len(_audits_for_department(api, chain.department["id"])) == 2
    A.assert_department_posture(
        F.reload_department(api, chain.department["id"]), "COMPLIANT"
    )


RECORDER_USER_ID = "clerk-4"
VERIFIER_USER_ID = "mgr-2"


def _build_partly_sold_meat_lot_with_recorded_damage(api):
    """A 24-unit MEAT lot with 4 units sold and a 6-unit DAMAGE event still in RECORDED."""
    chain = F.build_meat_four_rung_chain(
        api,
        department_overrides={"shelf_life_days_default": 10, "shrink_budget_pct": 2.5},
    )
    F.set_clock(api, "2026-08-12T00:00:00.000Z")
    F.post_sale(api, chain.lot["id"], 4, register_lane_code="L03", headers=clerk_headers())
    chain.after_sale = F.reload_lot(api, chain.lot["id"])
    chain.shrink = F.record_shrink(
        api,
        chain.lot["id"],
        6,
        "DAMAGE",
        note="case dropped on the dock",
        headers=make_clerk_headers(RECORDER_USER_ID),
    )
    return chain


def test_verifying_the_damage_event_balances_the_lot_at_fourteen_units(api):
    """While the event is VERIFIED the lot balances as 24 == 14 + 4 + 6 + 0.

    PRD 1: "**money and units are conserved, not estimated**: a lot's received
    quantity always equals what remains on the shelf plus what was sold, shrunk, and
    donated".

    PRD 3.5: "`revenue_cents` grows by the units sold multiplied by the lot's
    `current_price_cents` at call time."

    PRD 3.6: "First, the lot's `units_shrunk` grows by the event's `quantity_units`
    and its `quantity_on_hand` shrinks by the same amount."

    Four units at the full 599-cent shelf price is 2,396 cents of revenue.  Six units
    at the 420-cent cost snapshot is 2,520 cents, which the 3.5 percent surcharge lifts
    to 2,608.2 and rounds half up to 2,608; the same six units at 599 is 3,594.  Cost of
    goods on the four sold units is 1,739 after the same surcharge and rounding, so the
    trailing-seven-day ratio is 2,608 over 4,347, which is 60.00 percent -- above the
    2.50 percent budget.

    Design: Difficulty/compensating_invariant/units_conservation_restored_by_disputing_verified_shrink
    """
    chain = _build_partly_sold_meat_lot_with_recorded_damage(api)

    A.assert_fields(chain.after_sale, quantity_on_hand=20, revenue_cents=2396)
    A.assert_fields(chain.shrink, cost_value_cents=2608, retail_value_cents=3594)

    verified = F.verify_shrink(
        api, chain.shrink["id"], headers=make_manager_headers(VERIFIER_USER_ID)
    )

    A.assert_fields(verified, status="VERIFIED", verified_by_user_id=VERIFIER_USER_ID)

    lot = F.reload_lot(api, chain.lot["id"])
    A.assert_fields(
        lot,
        quantity_on_hand=14,
        units_sold=4,
        units_shrunk=6,
        units_donated=0,
        status="FRESH",
    )
    A.assert_lot_units_conservation(lot)
    A.assert_department_posture(
        F.reload_department(api, chain.department["id"]),
        "WATCH",
        shrink_cost_ratio_pct=60.00,
    )


def test_disputing_the_verified_event_restores_every_unit_and_aggregate(api):
    """The compensating dispute puts the lot back to 24 == 20 + 4 + 0 + 0 with no drift.

    PRD 3.6: "Disputing a `VERIFIED` event whose `origin` is `MANUAL` is the
    compensating case: the event's `quantity_units` are subtracted from the lot's
    `units_shrunk` and added back to its `quantity_on_hand`, restoring the
    unit-conservation invariant exactly [...] the department's
    `markdown_liability_cents`, `shrink_cost_ratio_pct` and `compliance_status` are all
    recomputed; `verified_by_user_id` and `verified_at` are cleared to null".

    PRD 3.6: "`unit_cost_cents_snapshot` freezes the item's `unit_cost_cents` as it
    stands, so the cost basis of this write-off can never be re-dated afterwards."

    With no shrink left in the window the ratio's numerator is 0, so the ratio returns
    to exactly 0 and clause 3 of 2.8 no longer bites; the sale's own revenue and
    giveback figures are untouched by either shrink transition.

    Design: Difficulty/compensating_invariant/units_conservation_restored_by_disputing_verified_shrink
    """
    chain = _build_partly_sold_meat_lot_with_recorded_damage(api)
    F.verify_shrink(api, chain.shrink["id"], headers=make_manager_headers(VERIFIER_USER_ID))

    disputed = F.dispute_shrink(
        api, chain.shrink["id"], headers=make_manager_headers(VERIFIER_USER_ID)
    )

    assert disputed["status"] == "DISPUTED"
    A.assert_absent_or_none(disputed, "verified_by_user_id", "verified_at")
    A.assert_money_cents(disputed["cost_value_cents"], 2608, "cost_value_cents")

    lot = F.reload_lot(api, chain.lot["id"])
    A.assert_fields(
        lot,
        quantity_on_hand=20,
        units_sold=4,
        units_shrunk=0,
        units_donated=0,
        revenue_cents=2396,
        markdown_giveback_cents=0,
    )
    A.assert_lot_units_conservation(lot)
    A.assert_department_posture(
        F.reload_department(api, chain.department["id"]),
        "COMPLIANT",
        shrink_cost_ratio_pct=0,
    )


def _build_marked_down_meat_lot_with_liability(api):
    """A pristine 24-unit MEAT lot marked down to 509, carrying a 2,160-cent liability."""
    chain = F.build_meat_four_rung_chain(api)
    chain.department_before = F.reload_department(api, chain.department["id"])
    F.set_clock(api, "2026-08-12T00:00:00.000Z")
    chain.label = F.cut_markdown(api, chain.lot, headers=manager_headers())
    chain.department_marked = F.reload_department(api, chain.department["id"])
    chain.lot_marked = F.reload_lot(api, chain.lot["id"])
    return chain


def test_marking_the_lot_down_books_exactly_the_giveback_exposure(api):
    """The money aggregate moves from 0 to 24 * (599 - 509), which is 2,160 cents.

    PRD 2.9: "`markdown_liability_cents` is the department's open markdown giveback
    exposure. It is the sum, over every lot belonging to the department's items whose
    `status` is `FRESH`, `MARKED_DOWN` or `DONATION_PENDING`, of that lot's
    `quantity_on_hand` multiplied by the difference between its item's
    `base_retail_cents` and the lot's `current_price_cents`."

    PRD 3.2: "Third, the calendar: the item's `daily_forecast_units` multiplied by the
    velocity multiplier multiplied by days remaining".

    At receipt the clock reads 2026-08-10T08:00:00.000Z, leaving four whole days before
    the 2026-08-15T00:00:00.000Z sell-by, so 4.00 forecast units over 4 days project 16 of
    the 24 units, which is 66.67 percent; at the parked 2026-08-12 clock the same
    arithmetic over 3 days projects 12 units, which is exactly 50.00 percent.  Nothing
    was sold or shrunk, so the pre-markdown exposure is 0.

    Design: Difficulty/compensating_invariant/markdown_liability_restored_by_markdown_void
    """
    chain = _build_marked_down_meat_lot_with_liability(api)

    A.assert_percent(
        chain.lot["expected_sell_through_pct"], 66.67, "expected_sell_through_pct"
    )
    A.assert_money_cents(
        chain.department_before["markdown_liability_cents"], 0, "markdown_liability_cents"
    )
    A.assert_fields(chain.label, to_price_cents=509, status="QUEUED")
    A.assert_money_cents(
        chain.department_marked["markdown_liability_cents"],
        2160,
        "markdown_liability_cents",
    )
    A.assert_percent(
        chain.lot_marked["expected_sell_through_pct"], 50.00, "expected_sell_through_pct"
    )
    assert chain.lot_marked["quantity_on_hand"] == 24


def test_voiding_the_markdown_returns_the_liability_to_zero_with_no_residue(api):
    """The void is the exact compensating action: price, rung, discount and money all reset.

    PRD 3.3: "The void is the exact compensating action for the markdown: every label
    on the lot in `QUEUED`, `PRINTED` or `APPLIED` transitions to `VOIDED`,
    `current_price_cents` is restored to the item's `base_retail_cents`,
    `current_rung_index` returns to -1, `total_discount_pct` returns to 0,
    `expected_sell_through_pct` is recomputed, and the lot's `version` is incremented by
    one. Because liability is recomputed from lot state rather than adjusted
    incrementally, the department's `markdown_liability_cents` returns to precisely the
    value it held before the lot's first markdown -- the `FRESH` -> `MARKED_DOWN` ->
    `FRESH` cycle closes exactly, with no residue."

    PRD 3.5: "`markdown_giveback_cents` grows by the units sold multiplied by the
    difference between the item's `base_retail_cents` and the lot's `current_price_cents`
    at call time".  No unit was ever sold at the marked-down price, so the giveback stays
    0, and the recomputed sell-through is still 50.00 percent because no units moved.

    Design: Difficulty/compensating_invariant/markdown_liability_restored_by_markdown_void
    """
    chain = _build_marked_down_meat_lot_with_liability(api)

    voided = validate_success(
        api.void_markdown(
            chain.lot["id"],
            {"reason_note": "priced in error, restoring base retail"},
            manager_headers(),
        )
    )

    A.assert_fresh_unpriced_lot(voided, 599)
    A.assert_percent(
        voided["expected_sell_through_pct"], 50.00, "expected_sell_through_pct"
    )
    A.assert_fields(
        voided,
        quantity_on_hand=24,
        units_sold=0,
        units_shrunk=0,
        markdown_giveback_cents=0,
    )
    A.assert_lot_units_conservation(voided)

    assert F.reload_label(api, chain.label["id"])["status"] == "VOIDED"
    A.assert_money_cents(
        F.reload_department(api, chain.department["id"])["markdown_liability_cents"],
        0,
        "markdown_liability_cents",
    )
