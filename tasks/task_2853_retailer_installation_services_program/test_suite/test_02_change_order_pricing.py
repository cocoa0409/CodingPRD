"""Change-order pricing: per-line rounding and the unbounded revision cycle.

A line-itemised change order is priced one line at a time with a pinned rounding
order, and it may bounce between the coordinator and the household without limit,
re-priced from scratch on every pass.
"""

from test_helpers import (
    PROJECT_COORDINATOR,
    ChangeOrderDecision,
    ChangeOrderOrigin,
    ChangeOrderStatus,
    FulfillmentStatus,
    assert_money,
    assert_project_dimensions,
    assert_units,
    assert_version,
    factories as f,
    fixtures as fx,
    get_success_data,
    make_customer_headers,
)

QUOTED = 196673


def _sold_project(api):
    """One project on a category that needs no measurement, so it is sold straight to
    MEASURED and a change order may be raised and submitted at once."""
    base = fx.program_baseline(api, f.service_category_payload(),
                               f.jurisdiction_payload())
    base["project"] = fx.sell_project(api, base, estimated_units=420.00)
    return base


def test_change_order_lines_are_rounded_before_they_are_added(api):
    """Three lines whose raw amounts each carry a fraction of a cent are rounded
    individually, so the total is 10546 and not the 10547 a single final rounding
    would produce.

    PRD 3.4: "**The rounding order is pinned: every line is rounded half up to whole
    cents first, and only the rounded line amounts are added.**"

    Design: Difficulty/combinatorial_formula/change_order_line_rounding_order_shifts_upcharge_by_one_cent
    """
    ctx = _sold_project(api)
    project = ctx["project"]
    assert_money(project["quoted_labor_cents"], QUOTED, "quoted_labor_cents")

    change_order = fx.raise_change_order(
        api, project["id"],
        [f.primary_line(6.00), f.primary_line(6.00), f.trim_line(12.00)],
        expected_project_version=project["version"],
    )

    # 6.00 * 425 * 1.15 * 1.06 = 3108.45 twice, and 12.00 * 296 * 1.15 * 1.06 =
    # 4329.888, which round to 3108, 3108 and 4330 and sum to 10546.
    assert_money(change_order["upcharge_cents"], 10546, "upcharge_cents")
    assert change_order["upcharge_cents"] != 10547, (
        "summing the raw amounts first gives 10546.788, which rounds to the wrong "
        "answer 10547"
    )
    assert_units(change_order["net_primary_units_delta"], 12.00,
                 "net_primary_units_delta")


def test_a_draft_change_order_books_no_money_on_the_project(api):
    """Raising the change order prices it and bumps the project, but the upcharge is
    not on the invoice until the household accepts it.

    PRD 3.4: "The new change order opens at `status` `DRAFT` with `upcharge_cents` and
    `net_primary_units_delta` computed, `revision_count` zero, and `revision_note` and
    `decided_at` null; the project's `version` increments".

    Design: Difficulty/combinatorial_formula/change_order_line_rounding_order_shifts_upcharge_by_one_cent
    """
    ctx = _sold_project(api)
    project = ctx["project"]
    change_order = fx.raise_change_order(
        api, project["id"],
        [f.primary_line(6.00), f.primary_line(6.00), f.trim_line(12.00)],
        expected_project_version=project["version"],
    )

    assert change_order["status"] == ChangeOrderStatus.DRAFT
    assert change_order["origin"] == ChangeOrderOrigin.CUSTOMER_REQUEST
    assert change_order["revision_count"] == 0
    assert change_order["revision_note"] is None
    assert change_order["decided_at"] is None

    project = fx.read_project(api, project["id"])
    assert_money(project["change_order_upcharge_cents"], 0,
                 "change_order_upcharge_cents while the change order is DRAFT")
    assert_money(project["quoted_labor_cents"], QUOTED,
                 "quoted_labor_cents is never recomputed")
    assert_version(project, 2, "project")
    assert_project_dimensions(project, fulfillment=FulfillmentStatus.MEASURED)


def _revision_cycle(api):
    """Submit, revise, resubmit, revise and resubmit one change order, returning the
    prices seen on each pass alongside the context."""
    ctx = _sold_project(api)
    project = ctx["project"]
    customer_headers = make_customer_headers(ctx["customer"]["id"])
    change_order = fx.raise_change_order(
        api, project["id"],
        [f.primary_line(6.00), f.primary_line(6.00), f.trim_line(12.00)],
        expected_project_version=project["version"],
    )
    prices = []

    first = get_success_data(
        api.submit_change_order(change_order["id"], PROJECT_COORDINATOR)
    )
    prices.append(first["upcharge_cents"])

    get_success_data(
        api.decide_change_order(
            change_order["id"],
            f.decision_payload(ChangeOrderDecision.REQUEST_REVISION,
                               revision_note="Reduce the trim run"),
            customer_headers,
        )
    )
    second = get_success_data(
        api.submit_change_order(
            change_order["id"], PROJECT_COORDINATOR,
            f.submit_payload([f.primary_line(6.00), f.trim_line(12.00)]),
        )
    )
    prices.append(second["upcharge_cents"])

    get_success_data(
        api.decide_change_order(
            change_order["id"],
            f.decision_payload(ChangeOrderDecision.REQUEST_REVISION,
                               revision_note="Swap the trim for two fixtures"),
            customer_headers,
        )
    )
    third = get_success_data(
        api.submit_change_order(
            change_order["id"], PROJECT_COORDINATOR,
            f.submit_payload([f.fixture_line(2.00)]),
        )
    )
    prices.append(third["upcharge_cents"])

    ctx["change_order"] = third
    ctx["prices"] = prices
    ctx["customer_headers"] = customer_headers
    return ctx


def test_every_pass_through_the_revision_cycle_reprices_from_scratch(api):
    """Two trips round the revision loop leave three different prices behind, each one
    computed from the lines of that pass alone.

    PRD 3.4: "The cycle `PENDING_CUSTOMER → REVISION_REQUESTED → PENDING_CUSTOMER` may
    repeat without limit, and every pass through it re-prices from scratch, so a change
    of jurisdiction multiplier or category rate between passes is reflected in the new
    figure."

    Design: Difficulty/non_linear_state_machine/change_order_revision_cycle_repriced_twice_before_acceptance
    """
    ctx = _revision_cycle(api)
    first, second, third = ctx["prices"]

    # Pass one: 3108 + 3108 + 4330.
    assert_money(first, 10546, "upcharge_cents on the first submission")
    # Pass two: 3108 + 4330 with one primary line dropped.
    assert_money(second, 7438, "upcharge_cents after the first revision")
    # Pass three: 2.00 * 7350 * 1.15 * 1.06 = 17919.3 alone.
    assert_money(third, 17919, "upcharge_cents after the second revision")

    change_order = ctx["change_order"]
    assert change_order["status"] == ChangeOrderStatus.PENDING_CUSTOMER
    assert change_order["revision_count"] == 2
    assert_units(change_order["net_primary_units_delta"], 0.00,
                 "net_primary_units_delta after the second revision")


def test_acceptance_books_only_the_last_price_the_cycle_produced(api):
    """Accepting after two revisions adds the third price, and nothing else, to the
    project's booked upcharges.

    PRD 3.4: "An `ACCEPT` sets `status` to `ACCEPTED`, stamps `decided_at` with the
    clock, and moves the project `CHANGE_PENDING → MEASURED`; for `CUSTOMER_REQUEST`
    and `SITE_CONDITION` origins it adds `upcharge_cents` to the project's
    `change_order_upcharge_cents` and recomputes `total_due_cents` and
    `balance_due_cents`".

    Design: Difficulty/non_linear_state_machine/change_order_revision_cycle_repriced_twice_before_acceptance
    """
    ctx = _revision_cycle(api)
    accepted = get_success_data(
        api.decide_change_order(
            ctx["change_order"]["id"],
            f.decision_payload(ChangeOrderDecision.ACCEPT),
            ctx["customer_headers"],
        )
    )
    assert accepted["status"] == ChangeOrderStatus.ACCEPTED
    assert accepted["revision_count"] == 2
    assert_money(accepted["upcharge_cents"], 17919, "accepted upcharge_cents")
    assert accepted["decided_at"] is not None

    project = fx.read_project(api, ctx["project"]["id"])
    assert_money(project["change_order_upcharge_cents"], 17919,
                 "change_order_upcharge_cents")
    assert_money(project["quoted_labor_cents"], QUOTED, "quoted_labor_cents")
    # total_due_cents is zero while final_labor_cents is still null, so booking the
    # upcharge does not put a balance on the invoice yet.
    assert_money(project["total_due_cents"], 0, "total_due_cents")
    assert_project_dimensions(project, fulfillment=FulfillmentStatus.MEASURED)
