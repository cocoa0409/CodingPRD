"""The completion cascade into replenishment, and the purchasing lifecycle."""

from test_helpers import (
    api_client,
    assert_cents,
    assert_ingredient_order,
    assert_instant,
    assert_null,
    assert_order_total_is_sum_of_lines,
    cancel_ingredient_order_payload,
    cancel_order,
    create_ingredient_order_payload,
    drive_run_to_completed,
    find_line,
    list_ingredient_orders_for_department,
    order_line,
    provision_flour,
    provision_second_department,
    raise_ingredient_order,
    read_bake_day,
    read_department,
    read_ingredient,
    read_ingredient_order,
    receive_ingredient_order_payload,
    received_line,
    schedule_scratch_run,
    setup_planned_day,
    setup_reference_data,
    setup_submitted_ingredient_order,
    validate_error,
    validate_success,
)


def _completed_roll_batch(flour_on_hand=200):
    """A four-rack scratch roll batch completed at 100 units."""
    setup = setup_planned_day(flour_on_hand=flour_on_hand)
    run = schedule_scratch_run(setup, rack_count=4, deck_index=0)
    setup["run"] = drive_run_to_completed(run, "SCRATCH", 100)
    return setup


def test_run_completion_consumes_the_recipe_and_re_derives_replenishment():
    """Hops two and three of the cascade: consumption, then reorder state.

    PRD §3.5: "Second, because actual units were posted, the product's recipe is
    consumed — walking `recipe_lines` in array order, each named ingredient's
    `on_hand_units` is reduced by the run's `rack_count` multiplied by that line's
    `units_per_rack`."  Four racks at 25 units a rack draw 100 units of flour out
    of a 200-unit stock, leaving it strictly below its 120-unit reorder point.

    Design: Difficulty/transitive_cascade/run_completion_cascades_consumption_reorder_and_commitment
    """
    setup = _completed_roll_batch()
    run = setup["run"]
    assert_cents(run["ingredient_cost_cents"], 1000, "ingredient_cost_cents")
    assert_cents(run["unit_cost_basis_cents"], 10, "unit_cost_basis_cents")

    flour = read_ingredient(setup["flour"]["id"])
    assert flour["on_hand_units"] == 100
    assert flour["replenishment_state"] == "REORDER_DUE"

    sugar = read_ingredient(setup["sugar"]["id"])
    assert sugar["on_hand_units"] == 500, "An ingredient outside the recipe is untouched"
    assert sugar["replenishment_state"] == "OK"

    day = read_bake_day(setup["bake_day"]["id"])
    assert day["produced_units_total"] == 100
    assert_cents(day["production_cost_cents"], 1000, "production_cost_cents")


def test_run_completion_mints_a_costed_auto_reorder_draft_and_commits_the_spend():
    """Hop four: the automatic draft raises the department's commitment.

    PRD §3.8: "For each surviving ingredient the top-up quantity is the greater of
    zero and twice its `reorder_point_units` less its current `on_hand_units`."
    Twice 120 less 100 is 140 units, which rounds up to four 45-unit cases — 180
    units at 10 cents plus five percent freight, or 1890 cents.

    Design: Difficulty/transitive_cascade/run_completion_cascades_consumption_reorder_and_commitment
    """
    setup = _completed_roll_batch()

    drafts, meta = list_ingredient_orders_for_department(
        setup["department"]["id"], origin="AUTO_REORDER"
    )
    assert meta["total_count"] == 1
    draft = drafts[0]
    assert_ingredient_order(draft)
    assert draft["order_status"] == "DRAFT"
    assert draft["origin"] == "AUTO_REORDER"
    assert_null(draft["target_bake_day_id"], "target_bake_day_id")
    assert_null(draft["submitted_at_utc"], "submitted_at_utc")
    assert len(draft["lines"]) == 1, "Only the flour in the recipe is due"

    line = find_line(draft, setup["flour"]["id"])
    assert line["required_units"] == 140
    assert line["cases"] == 4
    assert line["ordered_units"] == 180
    assert_cents(line["line_cost_cents"], 1890, "line_cost_cents")
    assert_cents(draft["order_total_cents"], 1890, "order_total_cents")

    department = read_department(setup["department"]["id"])
    assert_cents(
        department["open_purchase_commitment_cents"], 1890, "open_purchase_commitment_cents"
    )

    flour = read_ingredient(setup["flour"]["id"])
    assert flour["replenishment_state"] == "REORDER_DUE", (
        "Drafting the order does not move any ingredient to ON_ORDER"
    )


def test_ingredient_order_freight_is_rounded_per_line_before_the_lines_are_summed():
    """Two lines that each land on a half cent prove the rounding order.

    PRD §3.8: "`order_total_cents` is the sum of the `line_cost_cents` values —
    that is, the sum of the already-rounded lines. Applying the freight surcharge
    to a summed base and rounding once at the end produces a different order total
    for the same input and is wrong."  Both lines cost 1350 base cents, so each
    rounds 1417.5 up to 1418 and the order totals 2836, not the 2835 a single
    end-of-order rounding would give.

    Design: Difficulty/combinatorial_formula/ingredient_order_freight_rounds_per_line_then_sums
    """
    setup = setup_reference_data()
    order = raise_ingredient_order(
        setup["department"],
        [
            order_line(setup["flour"]["id"], 100),
            order_line(setup["sugar"]["id"], 75),
        ],
    )

    flour_line = find_line(order, setup["flour"]["id"])
    assert flour_line["cases"] == 3, "100 units of a 45-unit case pack rounds up to 3"
    assert flour_line["ordered_units"] == 135
    assert_cents(flour_line["line_cost_cents"], 1418, "flour line_cost_cents")

    sugar_line = find_line(order, setup["sugar"]["id"])
    assert sugar_line["cases"] == 3, "75 units of a 30-unit case pack rounds up to 3"
    assert sugar_line["ordered_units"] == 90
    assert_cents(sugar_line["line_cost_cents"], 1418, "sugar line_cost_cents")

    assert_order_total_is_sum_of_lines(order)
    assert_cents(order["order_total_cents"], 2836, "order_total_cents")
    assert order["order_total_cents"] != 2835, (
        "2835 is what rounding a summed base once at the end would produce"
    )


def test_a_raised_ingredient_order_opens_as_a_manual_draft_and_commits_the_spend():
    """The same two lines in the opposite order total the same and commit at once.

    PRD §3.8: "A newly raised order answers with 201, opens in `DRAFT` with an
    `origin` of `MANUAL`, immediately raises the department's
    `open_purchase_commitment_cents` by its `order_total_cents`, and increments the
    department's `version` by 1."  Raising an order buys nothing yet, so on-hand
    stock is untouched.

    Design: Difficulty/combinatorial_formula/ingredient_order_freight_rounds_per_line_then_sums
    """
    setup = setup_reference_data()
    version_before = read_department(setup["department"]["id"])["version"]

    response = api_client.create_ingredient_order(
        create_ingredient_order_payload(
            setup["department"]["id"],
            version_before,
            [
                order_line(setup["sugar"]["id"], 75),
                order_line(setup["flour"]["id"], 100),
            ],
        ),
        setup["manager"],
    )
    order = validate_success(response, 201)

    assert order["order_status"] == "DRAFT"
    assert order["origin"] == "MANUAL"
    assert order["version"] == 1
    assert [line["ingredient_id"] for line in order["lines"]] == [
        setup["sugar"]["id"],
        setup["flour"]["id"],
    ], "Lines are costed and stored in the order the request supplied them"
    assert_cents(order["order_total_cents"], 2836, "order_total_cents")
    assert_order_total_is_sum_of_lines(order)

    department = read_department(setup["department"]["id"])
    assert_cents(
        department["open_purchase_commitment_cents"], 2836, "open_purchase_commitment_cents"
    )
    assert department["version"] == version_before + 1

    assert read_ingredient(setup["flour"]["id"])["on_hand_units"] == 2000
    assert read_ingredient(setup["sugar"]["id"])["on_hand_units"] == 500


def test_receiving_every_ordered_unit_lands_the_order_in_received_full():
    """The full branch zeroes the shortfall and still runs every other effect.

    PRD §3.8: "When every line's `received_units` is at least its `ordered_units`,
    the order lands in `RECEIVED_FULL` and `shortfall_units_total` is set to 0."
    Stock rises by what arrived, both ingredients leave `ON_ORDER`, and the
    commitment is released.

    Design: Difficulty/non_linear_state_machine/ingredient_order_receive_forks_to_full_or_short
    """
    setup = setup_submitted_ingredient_order(flour_units=135, sugar_units=90)
    order = setup["ingredient_order"]
    assert order["order_status"] == "SUBMITTED"
    assert_instant(order["submitted_at_utc"], setup["clock"], "submitted_at_utc")
    assert_cents(order["order_total_cents"], 2836, "order_total_cents")
    assert read_ingredient(setup["flour"]["id"])["replenishment_state"] == "ON_ORDER"
    assert read_ingredient(setup["sugar"]["id"])["replenishment_state"] == "ON_ORDER"

    received = validate_success(
        api_client.receive_ingredient_order(
            order["id"],
            receive_ingredient_order_payload(
                [
                    received_line(setup["flour"]["id"], 135),
                    received_line(setup["sugar"]["id"], 90),
                ]
            ),
            setup["manager"],
        ),
        200,
    )
    assert received["order_status"] == "RECEIVED_FULL"
    assert received["shortfall_units_total"] == 0
    assert_cents(received["order_total_cents"], 2836, "order_total_cents")

    flour = read_ingredient(setup["flour"]["id"])
    assert flour["on_hand_units"] == 2135
    assert flour["replenishment_state"] == "OK"
    sugar = read_ingredient(setup["sugar"]["id"])
    assert sugar["on_hand_units"] == 590
    assert sugar["replenishment_state"] == "OK"

    department = read_department(setup["department"]["id"])
    assert_cents(
        department["open_purchase_commitment_cents"], 0, "open_purchase_commitment_cents"
    )


def test_one_short_line_lands_the_whole_order_in_received_short():
    """The short branch sums the per-line shortfalls and changes nothing else.

    PRD §3.8: "When at least one line came in short of its `ordered_units`, the
    order lands in `RECEIVED_SHORT` and `shortfall_units_total` is set to the sum,
    over all lines, of the greater of zero and that line's `ordered_units` less its
    `received_units`".  Ninety ordered units of sugar against eighty delivered is a
    shortfall of ten, while the flour line arrives complete.

    Design: Difficulty/non_linear_state_machine/ingredient_order_receive_forks_to_full_or_short
    """
    setup = setup_submitted_ingredient_order(flour_units=135, sugar_units=90)
    order = setup["ingredient_order"]

    received = validate_success(
        api_client.receive_ingredient_order(
            order["id"],
            receive_ingredient_order_payload(
                [
                    received_line(setup["flour"]["id"], 135),
                    received_line(setup["sugar"]["id"], 80),
                ]
            ),
            setup["manager"],
        ),
        200,
    )
    assert received["order_status"] == "RECEIVED_SHORT"
    assert received["shortfall_units_total"] == 10

    assert read_ingredient(setup["flour"]["id"])["on_hand_units"] == 2135
    sugar = read_ingredient(setup["sugar"]["id"])
    assert sugar["on_hand_units"] == 580, "Stock rises by what actually arrived"
    assert sugar["replenishment_state"] == "OK"

    department = read_department(setup["department"]["id"])
    assert_cents(
        department["open_purchase_commitment_cents"],
        0,
        "the commitment is released on both branches alike",
    )


def test_cancelling_a_submitted_order_releases_the_purchase_commitment():
    """The compensating half of the commitment invariant fires on cancellation.

    PRD §3.8: "The reason is stored, the order moves to `CANCELLED`, and the
    compensating half of the commitment invariant fires: the department's
    `open_purchase_commitment_cents` falls by exactly this order's
    `order_total_cents` and the department's `version` increments by 1."  Nothing
    was ever delivered, so on-hand stock never moves.

    Design: Difficulty/compensating_invariant/cancelling_an_ingredient_order_releases_the_purchase_commitment
    """
    setup = setup_submitted_ingredient_order(flour_units=100, sugar_units=75)
    order = setup["ingredient_order"]
    before = read_department(setup["department"]["id"])
    assert_cents(
        before["open_purchase_commitment_cents"],
        2836,
        "submission leaves the commitment unchanged",
    )

    cancelled = validate_success(
        api_client.cancel_ingredient_order(
            order["id"],
            cancel_ingredient_order_payload("Supplier outage"),
            setup["manager"],
        ),
        200,
    )
    assert cancelled["order_status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "Supplier outage"
    assert_cents(
        cancelled["order_total_cents"],
        2836,
        "a cancelled order keeps the total it was costed at",
    )

    after = read_department(setup["department"]["id"])
    assert_cents(
        after["open_purchase_commitment_cents"], 0, "open_purchase_commitment_cents"
    )
    assert after["version"] == before["version"] + 1

    flour = read_ingredient(setup["flour"]["id"])
    assert flour["replenishment_state"] == "OK", "ON_ORDER is released by the cancellation"
    assert flour["on_hand_units"] == 2000
    sugar = read_ingredient(setup["sugar"]["id"])
    assert sugar["replenishment_state"] == "OK"
    assert sugar["on_hand_units"] == 500


def test_cancelling_a_draft_order_releases_the_commitment_the_same_way():
    """Cancellation from DRAFT has identical effects and re-derives stock state.

    PRD §3.8: "A `DepartmentManager` may cancel an order from either `DRAFT` or
    `SUBMITTED`, supplying a `cancel_reason`, and the two paths have identical
    effects."  A flour still sitting below its reorder point reads `REORDER_DUE`
    again once the order that would have covered it is gone.

    Design: Difficulty/compensating_invariant/cancelling_an_ingredient_order_releases_the_purchase_commitment
    """
    setup = setup_reference_data(flour_on_hand=100)
    order = raise_ingredient_order(
        setup["department"], [order_line(setup["flour"]["id"], 100)]
    )
    assert order["order_status"] == "DRAFT"
    assert_cents(order["order_total_cents"], 1418, "order_total_cents")
    committed = read_department(setup["department"]["id"])
    assert_cents(
        committed["open_purchase_commitment_cents"], 1418, "open_purchase_commitment_cents"
    )

    cancelled = cancel_order(order["id"], setup["department"], "Duplicate raise")
    assert cancelled["order_status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "Duplicate raise"

    released = read_department(setup["department"]["id"])
    assert_cents(
        released["open_purchase_commitment_cents"], 0, "open_purchase_commitment_cents"
    )
    assert released["version"] == committed["version"] + 1

    flour = read_ingredient(setup["flour"]["id"])
    assert flour["on_hand_units"] == 100, "Cancelling an order never moves stock"
    assert flour["replenishment_state"] == "REORDER_DUE"


def test_the_shelf_life_cap_is_compared_against_case_pack_rounded_units():
    """The cap bites after the rounding-up step, not before it.

    PRD §3.8: "The cap is compared against the line's `ordered_units` *after*
    case-pack rounding, never against the `required_units` the client asked for, so
    a request that looks compliant can still be pushed over the cap by the
    rounding-up step."  A sugar used at 20 units a day with a ten-day life caps at
    200 units, and 190 required units round up to 210, so the line is rejected with
    `ERR_SHELF_LIFE_OVERSTOCK`.

    Design: Corner/calculations/shelf_life_cap_is_compared_against_case_pack_rounded_units
    """
    setup = setup_reference_data()
    version_before = read_department(setup["department"]["id"])["version"]

    over_the_cap = api_client.create_ingredient_order(
        create_ingredient_order_payload(
            setup["department"]["id"],
            version_before,
            [order_line(setup["sugar"]["id"], 190)],
        ),
        setup["manager"],
    )
    validate_error(over_the_cap, "ERR_SHELF_LIFE_OVERSTOCK", 422)

    _, meta = list_ingredient_orders_for_department(setup["department"]["id"])
    assert meta["total_count"] == 0, "A rejected order is never created"
    unchanged = read_department(setup["department"]["id"])
    assert unchanged["version"] == version_before
    assert_cents(
        unchanged["open_purchase_commitment_cents"], 0, "open_purchase_commitment_cents"
    )

    exactly_inside = raise_ingredient_order(
        setup["department"], [order_line(setup["sugar"]["id"], 180)]
    )
    line = find_line(exactly_inside, setup["sugar"]["id"])
    assert line["cases"] == 6
    assert line["ordered_units"] == 180
    assert_cents(line["line_cost_cents"], 2835, "line_cost_cents")
    assert_cents(exactly_inside["order_total_cents"], 2835, "order_total_cents")
    assert_cents(
        read_department(setup["department"]["id"])["open_purchase_commitment_cents"],
        2835,
        "open_purchase_commitment_cents",
    )


def test_submitting_an_ingredient_order_twice_is_rejected_on_the_second_call():
    """Submission is declared only out of DRAFT.

    PRD §3.8: "Submitting anything that is not in `DRAFT` is rejected with
    `ERR_INVALID_INGREDIENT_ORDER_STATE`."  The first submission's
    `submitted_at_utc` stamp survives the refusal, and a cancelled order cannot be
    submitted either.

    Design: Corner/errors/submitting_an_ingredient_order_twice_is_rejected_on_the_second_call
    """
    setup = setup_submitted_ingredient_order()
    order = setup["ingredient_order"]

    second_call = api_client.submit_ingredient_order(order["id"], setup["manager"])
    validate_error(second_call, "ERR_INVALID_INGREDIENT_ORDER_STATE", 409)

    unchanged = read_ingredient_order(order["id"])
    assert unchanged["order_status"] == "SUBMITTED"
    assert_instant(unchanged["submitted_at_utc"], setup["clock"], "submitted_at_utc")
    assert unchanged["version"] == order["version"]

    cancelled = cancel_order(order["id"], setup["department"], "Supplier outage")
    assert cancelled["order_status"] == "CANCELLED"

    after_cancellation = api_client.submit_ingredient_order(
        order["id"], setup["manager"]
    )
    validate_error(after_cancellation, "ERR_INVALID_INGREDIENT_ORDER_STATE", 409)

    assert read_ingredient(setup["flour"]["id"])["replenishment_state"] == "OK"
    assert_cents(
        read_department(setup["department"]["id"])["open_purchase_commitment_cents"],
        0,
        "open_purchase_commitment_cents",
    )


def test_ingredient_order_creation_rejects_a_stale_department_version():
    """Each raised order invalidates the version the client held.

    PRD §2.5: "If that number does not equal the department's current `version`,
    the request is rejected with `ERR_STALE_DEPARTMENT_VERSION` (HTTP 412)."  The
    first order bumps the department, so replaying its version fails and the
    refreshed version is exactly one higher.

    Design: Corner/complexity_layers/ingredient_order_creation_rejects_a_stale_department_version
    """
    setup = setup_reference_data()
    stale_version = read_department(setup["department"]["id"])["version"]

    first = raise_ingredient_order(
        setup["department"],
        [order_line(setup["flour"]["id"], 90)],
        expected_version=stale_version,
    )
    first_line = find_line(first, setup["flour"]["id"])
    assert first_line["cases"] == 2
    assert first_line["ordered_units"] == 90
    assert_cents(first["order_total_cents"], 945, "order_total_cents")

    replayed = api_client.create_ingredient_order(
        create_ingredient_order_payload(
            setup["department"]["id"],
            stale_version,
            [order_line(setup["flour"]["id"], 45)],
        ),
        setup["manager"],
    )
    validate_error(replayed, "ERR_STALE_DEPARTMENT_VERSION", 412)

    _, meta = list_ingredient_orders_for_department(setup["department"]["id"])
    assert meta["total_count"] == 1, "The stale attempt created nothing"

    fresh_version = read_department(setup["department"]["id"])["version"]
    assert fresh_version == stale_version + 1

    second = raise_ingredient_order(
        setup["department"],
        [order_line(setup["flour"]["id"], 45)],
        expected_version=fresh_version,
    )
    second_line = find_line(second, setup["flour"]["id"])
    assert second_line["cases"] == 1
    assert second_line["ordered_units"] == 45
    assert_cents(second["order_total_cents"], 473, "order_total_cents")

    assert_cents(
        read_department(setup["department"]["id"])["open_purchase_commitment_cents"],
        1418,
        "open_purchase_commitment_cents",
    )


def test_an_order_line_naming_another_departments_ingredient_is_rejected():
    """An ingredient that exists elsewhere is a referential fault, not a 404.

    PRD §2.10 band 12: "**Referential** — every referenced product, ingredient,
    oven and pickup slot belongs to the same department or the same bake day as the
    target (`ERR_INGREDIENT_NOT_IN_DEPARTMENT`)".  The refusal is not a mutation, so
    the version the client held is still good for the retry.

    Design: Corner/validations/ingredient_order_line_naming_another_departments_ingredient_is_rejected
    """
    setup = setup_reference_data()
    other_department = provision_second_department()
    other_flour = provision_flour(other_department["id"])
    version = read_department(setup["department"]["id"])["version"]

    trespassing = api_client.create_ingredient_order(
        create_ingredient_order_payload(
            setup["department"]["id"], version, [order_line(other_flour["id"], 90)]
        ),
        setup["manager"],
    )
    validate_error(trespassing, "ERR_INGREDIENT_NOT_IN_DEPARTMENT", 422)

    retried = validate_success(
        api_client.create_ingredient_order(
            create_ingredient_order_payload(
                setup["department"]["id"],
                version,
                [order_line(setup["flour"]["id"], 90)],
            ),
            setup["manager"],
        ),
        201,
    )
    assert retried["order_status"] == "DRAFT"
    line = find_line(retried, setup["flour"]["id"])
    assert line["cases"] == 2
    assert line["ordered_units"] == 90

    assert_cents(
        read_department(other_department["id"])["open_purchase_commitment_cents"],
        0,
        "the other department is untouched",
    )
    _, meta = list_ingredient_orders_for_department(other_department["id"])
    assert meta["total_count"] == 0
