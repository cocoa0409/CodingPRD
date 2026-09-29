"""Non-linear lifecycles and the pinned order of rejection."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import fixtures as F
from test_helpers.test_users import (
    MANAGER_2_USER_ID,
    clerk_headers,
    make_partner_headers,
    manager_headers,
)


def _labels_for_lot(api, lot_id):
    rows, _meta = validate_paginated(
        api.list_markdown_labels(manager_headers(), params={"lot_id": lot_id, "limit": 100})
    )
    return rows


def test_markdown_void_returns_the_lot_to_fresh_and_clears_the_liability(api):
    """The FRESH -> MARKED_DOWN -> FRESH loop closes with no residue.

    PRD 3.3: "The void is the exact compensating action for the markdown: every
    label on the lot in `QUEUED`, `PRINTED` or `APPLIED` transitions to `VOIDED`,
    `current_price_cents` is restored to the item's `base_retail_cents`,
    `current_rung_index` returns to -1, `total_discount_pct` returns to 0,
    `expected_sell_through_pct` is recomputed, and the lot's `version` is
    incremented by one."

    PRD 3.3: "Because liability is recomputed from lot state rather than adjusted
    incrementally, the department's `markdown_liability_cents` returns to precisely
    the value it held before the lot's first markdown -- the `FRESH` ->
    `MARKED_DOWN` -> `FRESH` cycle closes exactly, with no residue."

    At 3 days remaining the calendar reading prices 599 at 509 cents, so the
    department's exposure is 24 units times 90 cents of giveback, which is 2,160
    cents, and the void takes it back to 0.  The lot has been written twice -- once
    by the markdown and once by the void -- so its version is 3.

    Design: Difficulty/non_linear_state_machine/lot_marked_down_then_voided_back_to_fresh_then_remarked_deeper
    """
    chain = F.build_meat_four_rung_chain(api)
    F.set_clock(api, "2026-08-12T00:00:00.000Z")

    label = F.cut_markdown(
        api, chain.lot, pricing_variant="LADDER_DAYS", headers=manager_headers()
    )
    assert label["to_price_cents"] == 509
    assert label["rung_index"] == 0
    after_markdown = F.reload_department(api, chain.department["id"])
    A.assert_money_cents(
        after_markdown["markdown_liability_cents"], 2160, "markdown_liability_cents"
    )

    voided_lot = validate_success(
        api.void_markdown(
            chain.lot["id"],
            {"reason_note": "tag pulled, shelf price restored"},
            manager_headers(),
        )
    )

    A.assert_fresh_unpriced_lot(voided_lot, 599)
    assert voided_lot["version"] == 3
    assert F.reload_label(api, label["id"])["status"] == "VOIDED"
    after_void = F.reload_department(api, chain.department["id"])
    A.assert_money_cents(
        after_void["markdown_liability_cents"], 0, "markdown_liability_cents"
    )


def test_remarking_a_voided_lot_is_a_fresh_entry_not_a_re_ladder(api):
    """A lot re-entering MARKED_DOWN after a void supersedes nothing.

    PRD 3.3: "On a re-ladder the new label's `supersedes_label_id` is set to the
    `id` of the lot's newest label still in `QUEUED`, `PRINTED` or `APPLIED` [...]
    if the lot has no such label the field stays null."

    PRD 3.3: "The comparison boundary is inclusive, so a lot with exactly as many
    days remaining as a rung's `days_remaining_max` does select that rung."

    The void already retired label 1, so there is no live label to supersede.  One
    clock-day later the lot has 2 days remaining, selecting rung 1 at 30 percent:
    599 reduced by 30 percent is 419.3, which rounds half up to 419, a 30.05 percent
    total discount, and the department's exposure becomes 24 times 180, so 4,320.

    Design: Difficulty/non_linear_state_machine/lot_marked_down_then_voided_back_to_fresh_then_remarked_deeper
    """
    chain = F.build_meat_four_rung_chain(api)
    F.set_clock(api, "2026-08-12T00:00:00.000Z")

    F.cut_markdown(api, chain.lot, pricing_variant="LADDER_DAYS", headers=manager_headers())
    voided_lot = validate_success(
        api.void_markdown(
            chain.lot["id"],
            {"reason_note": "tag pulled, shelf price restored"},
            manager_headers(),
        )
    )

    F.set_clock(api, "2026-08-13T00:00:00.000Z")
    second = F.cut_markdown(
        api,
        voided_lot,
        pricing_variant="LADDER_DAYS",
        headers=manager_headers(),
    )

    A.assert_label(
        second,
        status="QUEUED",
        from_price_cents=599,
        to_price_cents=419,
        discount_pct=30.05,
        reason="LADDER_AUTO",
        barcode="MD-000111222333-00419",
    )
    assert second["rung_index"] == 1
    A.assert_absent_or_none(second, "supersedes_label_id")

    lot = F.reload_lot(api, chain.lot["id"])
    A.assert_lot_pricing(lot, 419, 1, 30.05, status="MARKED_DOWN")
    department = F.reload_department(api, chain.department["id"])
    A.assert_money_cents(
        department["markdown_liability_cents"], 4320, "markdown_liability_cents"
    )


def _build_confirmable_pickup(api):
    """A PRODUCE pickup with one 20-unit line, clock inside the dock window."""
    chain = F.build_produce_chain(
        api,
        store_overrides={"dock_door_codes": ["D1", "D2"], "donation_program_enabled": True},
        department_overrides={"shelf_life_days_default": 8},
        item_overrides={
            "upc": "000555666777",
            "description": "Salad Kit",
            "base_retail_cents": 599,
            "unit_cost_cents": 250,
            "daily_forecast_units": 8.00,
            "donation_eligible": True,
        },
        lot_overrides={"production_date": "2026-08-05", "quantity_original": 20},
    )
    F.set_clock(api, "2026-08-12T00:00:00.000Z")
    chain.pickup = F.book_pickup(
        api,
        chain.store["id"],
        chain.partner["id"],
        dock_door_code="D1",
        scheduled_window_start="2026-08-12T14:00:00.000Z",
        scheduled_window_end="2026-08-12T16:00:00.000Z",
        headers=manager_headers(),
    )
    chain.line = F.pledge_lot(api, chain.pickup["id"], chain.lot["id"], 20)
    F.set_clock(api, "2026-08-12T14:30:00.000Z")
    return chain


def test_confirming_a_pickup_leaves_its_manifest_draft_and_blocks_completion(api):
    """The two pickup dimensions move independently, and completion needs both.

    PRD 3.7: "Confirmation moves `logistics_status` from `SCHEDULED` to
    `CONFIRMED`, leaves `manifest_status` exactly as it was -- a pickup may be
    confirmed while its manifest is still `DRAFT` -- and increments `version` by
    one."

    PRD 3.7: "Completion requires `logistics_status` to be `CONFIRMED`, refusing
    anything else with `ERR_PICKUP_NOT_COMPLETABLE`, requires `manifest_status` to
    be `SEALED`, refusing a still-draft manifest with `ERR_MANIFEST_NOT_SEALED` and
    HTTP 409, and requires ownership."

    Design: Difficulty/non_linear_state_machine/donation_pickup_parallel_dimensions_confirm_before_seal
    """
    chain = _build_confirmable_pickup(api)

    confirmed = F.confirm_pickup(api, chain.pickup["id"], chain.partner["id"])
    A.assert_fields(confirmed, logistics_status="CONFIRMED", manifest_status="DRAFT")

    refused = api.complete_donation_pickup(
        chain.pickup["id"], make_partner_headers(chain.partner["id"])
    )
    validate_error(refused, "ERR_MANIFEST_NOT_SEALED", expected_status=409)

    still_confirmed = F.reload_pickup(api, chain.pickup["id"])
    A.assert_fields(
        still_confirmed, logistics_status="CONFIRMED", manifest_status="DRAFT"
    )


def test_sealing_after_confirmation_lets_the_same_completion_succeed(api):
    """Sealing moves only the manifest dimension, unblocking the collection.

    PRD 3.7: "Sealing moves `manifest_status` from `DRAFT` to `SEALED`, leaves
    `logistics_status` untouched".

    PRD 3.7: "A lot whose line took its whole remaining balance -- that is, a line
    whose `quantity_units` equalled the lot's `quantity_on_hand` -- is drained to
    zero and becomes `DONATED`" and "Completion also sets `completed_at` to the
    current logical clock and `units_picked_up_total` to the sum of
    `quantity_units` over the pickup's `PICKED_UP` lines, increments the partner's
    `pickups_completed_count` and adds those units to the partner's
    `units_received_total`".

    A single 20-unit line at 599 cents is a provisional 11,980 cents, below the
    50,000-cent boundary, so the credit rate is 62.50 percent and the line credit is
    7,487.5 rounded half up to 7,488.

    Design: Difficulty/non_linear_state_machine/donation_pickup_parallel_dimensions_confirm_before_seal
    """
    chain = _build_confirmable_pickup(api)
    F.confirm_pickup(api, chain.pickup["id"], chain.partner["id"])

    sealed = F.seal_pickup(api, chain.pickup["id"], headers=manager_headers())
    A.assert_fields(
        sealed,
        manifest_status="SEALED",
        logistics_status="CONFIRMED",
        credit_rate_pct=62.5,
        provisional_value_cents=11980,
        manifest_credit_cents=7488,
    )

    completed = F.complete_pickup(api, chain.pickup["id"], chain.partner["id"])
    A.assert_fields(
        completed,
        logistics_status="COMPLETED",
        manifest_status="SEALED",
        units_picked_up_total=20,
    )
    A.assert_instant_equals(
        completed["completed_at"], "2026-08-12T14:30:00.000Z", "completed_at"
    )

    line = validate_success(api.get_donation_assignment(chain.line["id"], manager_headers()))
    A.assert_fields(line, status="PICKED_UP", line_credit_cents=7488)

    lot = F.reload_lot(api, chain.lot["id"])
    A.assert_fields(lot, status="DONATED", quantity_on_hand=0, units_donated=20)
    A.assert_lot_units_conservation(lot)

    partner = validate_success(
        api.get_food_bank_partner(chain.partner["id"], manager_headers())
    )
    A.assert_fields(partner, pickups_completed_count=1, units_received_total=20)


def _build_withdrawn_and_fresh_siblings(api):
    """Two 24-unit lots of one item: one withdrawn, one still FRESH as the control."""
    chain = F.build_meat_four_rung_chain(api)
    chain.lot_fresh = F.build_lot(
        api, chain.item["id"], production_date="2026-08-05", quantity_original=24
    )
    F.set_clock(api, "2026-08-12T00:00:00.000Z")
    chain.lot_withdrawn = F.withdraw_lot(
        api,
        chain.lot["id"],
        reason_note="cooler temperature excursion",
        headers=manager_headers(),
    )
    return chain


def test_withdrawn_lot_state_outranks_the_cost_floor_on_an_override(api):
    """A withdrawn lot refuses the markdown on state, not on the fiscal floor.

    PRD 2.11: "8. Lot state suitability for the requested operation --
    `ERR_LOT_NOT_PRICEABLE` (409) -- on markdown creation, markdown void,
    withdrawal, sale posting and manifest-line creation." and "42. Override price at
    or above the cost floor, on markdown creation -- `ERR_PRICE_BELOW_COST_FLOOR`
    (422)."

    PRD 2.11: "Checks run in the following order, and the **first** violated check
    decides the response -- no later check can mask an earlier one."

    The override of 160 cents is below the 168-cent cost floor (40 percent of the
    420-cent unit cost), so both checks are armed; state suitability sits at 8 and
    the fiscal floor at 42, so the 409 wins.

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_withdrawn_lot_override_markdown
    """
    chain = _build_withdrawn_and_fresh_siblings(api)
    assert chain.lot_withdrawn["status"] == "WITHDRAWN"

    response = api.create_markdown(
        chain.lot_withdrawn["id"],
        {
            "expected_lot_version": chain.lot_withdrawn["version"],
            "override_price_cents": 160,
            "approval_manager_user_id": MANAGER_2_USER_ID,
        },
        manager_headers(),
    )

    validate_error(response, "ERR_LOT_NOT_PRICEABLE", expected_status=409)
    assert _labels_for_lot(api, chain.lot_withdrawn["id"]) == []


def test_the_same_override_on_a_fresh_sibling_is_refused_on_the_cost_floor(api):
    """The fiscal rule was armed all along: the FRESH control returns the 422.

    PRD 3.3: "The cost floor is a hard fiscal boundary derived from the item's
    landed cost: it is 40 percent of `unit_cost_cents`, rounded half up to whole
    cents." and "an override below the cost floor is refused with
    `ERR_PRICE_BELOW_COST_FLOOR` and HTTP 422".

    PRD 3.3: "If that figure exceeds the ladder's `max_total_discount_pct` the
    markdown is refused with `ERR_MAX_DISCOUNT_EXCEEDED` and HTTP 422."  Pricing 599
    at 160 is a 73.29 percent total discount, inside the ladder's 75 percent cap, so
    the cap is not the reason for the refusal.

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_withdrawn_lot_override_markdown
    """
    chain = _build_withdrawn_and_fresh_siblings(api)

    response = api.create_markdown(
        chain.lot_fresh["id"],
        {
            "expected_lot_version": chain.lot_fresh["version"],
            "override_price_cents": 160,
            "approval_manager_user_id": MANAGER_2_USER_ID,
        },
        manager_headers(),
    )

    validate_error(response, "ERR_PRICE_BELOW_COST_FLOOR", expected_status=422)
    assert _labels_for_lot(api, chain.lot_fresh["id"]) == []
    control = F.reload_lot(api, chain.lot_fresh["id"])
    A.assert_fresh_unpriced_lot(control, 599)


def _build_bakery_pickup_for_a_produce_only_partner(api):
    """A BAKERY lot and a pickup whose partner accepts PRODUCE only."""
    chain = F.build_bakery_chain(
        api,
        store_overrides={"dock_door_codes": ["D1"], "donation_program_enabled": True},
        department_overrides={"shelf_life_days_default": 10},
        item_overrides={
            "upc": "000333222111",
            "description": "Artisan Sourdough Loaf",
            "base_retail_cents": 449,
            "unit_cost_cents": 200,
            "daily_forecast_units": 6.00,
            "donation_eligible": True,
        },
        lot_overrides={"production_date": "2026-08-05", "quantity_original": 20},
    )
    chain.partner = F.build_partner(
        api,
        name="Produce Only Pantry",
        contact_email="pantry@example.org",
        service_region_code="MID-ATL",
        accepted_department_codes=["PRODUCE"],
    )
    F.set_clock(api, "2026-08-16T00:00:00.000Z")
    chain.pickup = F.book_pickup(
        api,
        chain.store["id"],
        chain.partner["id"],
        dock_door_code="D1",
        scheduled_window_start="2026-08-16T09:00:00.000Z",
        scheduled_window_end="2026-08-16T11:00:00.000Z",
        headers=manager_headers(),
    )
    return chain


def test_past_date_safety_outranks_the_unaccepted_department_check(api):
    """A past-date lot is refused on its date code, not on the partner's catalogue.

    PRD 2.11: "14. Donated product still inside its date code, on manifest-line
    creation -- `ERR_PAST_DATE_NOT_DONATABLE` (422)." and "20. Partner accepts the
    department's product, on manifest-line creation --
    `ERR_PARTNER_DEPARTMENT_NOT_ACCEPTED` (422)."

    PRD 3.7: "The logical clock is strictly before the lot's `sell_by_at`. Product
    that has reached or passed its date code may not be given away, and the attempt
    is refused with `ERR_PAST_DATE_NOT_DONATABLE` and HTTP 422."

    The lot sells by 2026-08-15T00:00:00.000Z and the clock stands at 2026-08-16, so
    the date-code check at 14 fires before the catalogue check at 20.

    Design: Difficulty/priority_pair_validation_conflict/safety_before_referential_on_past_date_unaccepted_partner_assignment
    """
    chain = _build_bakery_pickup_for_a_produce_only_partner(api)

    response = api.create_donation_assignment(
        chain.pickup["id"],
        {"lot_id": chain.lot["id"], "quantity_units": 20},
        clerk_headers(),
    )

    validate_error(response, "ERR_PAST_DATE_NOT_DONATABLE", expected_status=422)


def test_inside_the_window_the_unaccepted_department_refusal_surfaces(api):
    """With the date code intact, the partner's catalogue becomes the deciding rule.

    PRD 3.7: "The lot's department `code` appears in the partner's
    `accepted_department_codes`, else `ERR_PARTNER_DEPARTMENT_NOT_ACCEPTED` and HTTP
    422."

    PRD 3.7: "The pickup's `assignment_count` is incremented, its
    `provisional_value_cents` is recomputed, and the lot's `version` is incremented
    by one" describes a successful pledge only, so a refused pledge leaves the pickup
    at zero lines and the lot untouched.

    At 2026-08-14T00:00:00.000Z the clock sits inside the half-open window
    [2026-08-13T00:00:00.000Z, 2026-08-15T00:00:00.000Z), so only the BAKERY-versus-
    PRODUCE mismatch remains.

    Design: Difficulty/priority_pair_validation_conflict/safety_before_referential_on_past_date_unaccepted_partner_assignment
    """
    chain = _build_bakery_pickup_for_a_produce_only_partner(api)
    F.set_clock(api, "2026-08-14T00:00:00.000Z")

    response = api.create_donation_assignment(
        chain.pickup["id"],
        {"lot_id": chain.lot["id"], "quantity_units": 20},
        clerk_headers(),
    )

    validate_error(response, "ERR_PARTNER_DEPARTMENT_NOT_ACCEPTED", expected_status=422)
    pickup = F.reload_pickup(api, chain.pickup["id"])
    A.assert_fields(pickup, assignment_count=0, provisional_value_cents=0)
    lot = F.reload_lot(api, chain.lot["id"])
    A.assert_fields(lot, status="FRESH", quantity_on_hand=20)
