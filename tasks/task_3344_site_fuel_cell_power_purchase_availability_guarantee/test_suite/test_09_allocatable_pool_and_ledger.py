"""Conservation over the physical fuel pool and over the signed accrual ledger."""
from test_helpers import api_client, validate_success
from test_helpers.fixtures import (
    ANALYST,
    OPERATOR,
    create_settlement_line,
    get_site,
    list_transitions,
    post_accrual,
    schedule_delivery,
    set_clock,
    setup_active_ppa,
)
from test_helpers.fixtures import create_site, cancel_delivery, take_resource_hold


def test_cancelling_a_scheduled_delivery_returns_its_volume_to_the_pool():
    """PRD §3.3: "cancellation returns the canceled
    `volume_therms` to the site's `draw_position_therms`".
    PRD §2.6: "because a delivery is a reservation before it is a physical event, the
    system treats scheduling a delivery as an immediate draw against the pool and treats
    cancelling one as an immediate restoration."

    Design: Difficulty/compensating_invariant/canceled_delivery_restores_the_allocatable_therm_pool
    """
    set_clock()
    site = create_site()
    opening = site["draw_position_therms"]
    delivery = schedule_delivery(
        site["id"],
        volume_therms=60000,
        delivered_at="2026-03-12T00:00:00Z",
        confirm_after_iso8601="2026-03-13T00:00:00Z",
    )
    assert get_site(site["id"])["draw_position_therms"] == opening - 60000

    cancelled = cancel_delivery(site["id"], delivery["id"])

    assert cancelled["lifecycle_state"] == "DELIVERY_CANCELLED"
    after = get_site(site["id"])
    assert after["draw_position_therms"] == opening, (
        f"the forward/reserve pair must leave zero drift; expected {opening}, "
        f"got {after['draw_position_therms']}"
    )


def test_the_restored_pool_lands_exactly_on_the_opening_inventory():
    """PRD §3.1: "its `draw_position_therms`
    set from the operator-funded `initial_fuel_inventory_therms` the registration records".

    Design: Difficulty/compensating_invariant/canceled_delivery_restores_the_allocatable_therm_pool
    """
    set_clock()
    site = create_site()
    delivery = schedule_delivery(site["id"], volume_therms=60000)
    cancel_delivery(site["id"], delivery["id"])

    after = get_site(site["id"])
    assert after["draw_position_therms"] == after["initial_fuel_inventory_therms"], (
        "after the cancellation the pool is back to the opening inventory it started from"
    )


def test_cancelling_the_only_commitment_releases_the_resource_dimension():
    """PRD §3.3: "A scheduled load may be cancelled at any time by its
    sourcing coordinator, moving `DELIVERY_SCHEDULED` to `DELIVERY_CANCELLED`".
    PRD §3.3: "Releasing a hold moves `RESOURCE_DRAWING` back to `RESOURCE_AVAILABLE` and requires the site
    to have no live contracts left."

    Design: Difficulty/compensating_invariant/canceled_delivery_restores_the_allocatable_therm_pool
    """
    set_clock()
    site = create_site()
    hold = take_resource_hold(
        site["id"],
        requested_therms=60000,
        window_start_iso8601="2026-04-01T00:00:00Z",
        window_end_iso8601="2026-04-04T00:00:00Z",
    )
    drawing = get_site(site["id"])
    assert drawing["lifecycle_state"] == "RESOURCE_DRAWING"

    validate_success(
        api_client.release_resource_hold(
            site["id"], OPERATOR, {"delivery_id": hold["id"]}
        )
    )

    released = get_site(site["id"])
    assert released["lifecycle_state"] == "RESOURCE_AVAILABLE", (
        "with no live contract the site declares itself resource-free again"
    )
    assert released["draw_position_therms"] == released["initial_fuel_inventory_therms"]


def test_a_charge_and_an_equal_guarantee_accrual_net_the_open_signed_sum_to_zero():
    """PRD §3.3: "A posted accrual opens in `ACCRUAL_OPEN` and its
    `signed_amount_cents` is derived from its type: a `CHARGE_ACCRUAL` and a `CAPACITY_ACCRUAL`
    both carry their `amount_cents` forward positively, while an `OUTPUT_GUARANTEE_ACCRUAL`
    carries the negation of its `amount_cents`."

    Design: Difficulty/compensating_invariant/accrual_charge_and_guarantee_pair_leaves_the_signed_ledger_balanced
    """
    ctx = setup_active_ppa()
    charge = post_accrual(
        ctx["ppa_id"], ctx["site_id"], accrual_type="CHARGE_ACCRUAL", amount_cents=100000
    )
    guarantee = post_accrual(
        ctx["ppa_id"],
        ctx["site_id"],
        accrual_type="OUTPUT_GUARANTEE_ACCRUAL",
        amount_cents=100000,
    )

    assert charge["signed_amount_cents"] == 100000
    assert guarantee["signed_amount_cents"] == -100000

    line = create_settlement_line(ctx["ppa_id"])
    assert line["cap_side_pool_cents"] == 0, (
        "the two posts are the compensating pair over money; the open pool must read zero"
    )


def test_a_trueup_post_moves_the_same_open_sum_by_its_full_amount():
    """PRD §3.3: "a true-up accrual's
    `signed_amount_cents` is its `amount_cents`
    carried positively."

    Design: Difficulty/compensating_invariant/accrual_charge_and_guarantee_pair_leaves_the_signed_ledger_balanced
    """
    ctx = setup_active_ppa()
    post_accrual(
        ctx["ppa_id"], ctx["site_id"], accrual_type="CHARGE_ACCRUAL", amount_cents=100000
    )
    post_accrual(
        ctx["ppa_id"],
        ctx["site_id"],
        accrual_type="OUTPUT_GUARANTEE_ACCRUAL",
        amount_cents=100000,
    )
    trueup = post_accrual(
        ctx["ppa_id"], ctx["site_id"], accrual_type="TRUEUP_ACCRUAL", amount_cents=75000
    )

    assert trueup["signed_amount_cents"] == 75000, (
        "a true-up carries its amount positively, unlike an output-guarantee accrual"
    )
    line = create_settlement_line(ctx["ppa_id"])
    # PRD §3.5: "The `cap_side_pool_cents` is the sum of the contract's open
    # accruals whose type is `CHARGE_ACCRUAL` or `OUTPUT_GUARANTEE_ACCRUAL`".
    # A true-up is neither, so the charge and its equal guarantee still net the
    # pool to zero however large the true-up is.
    assert line["cap_side_pool_cents"] == 0, (
        "a true-up is not a cap-side accrual type; got "
        f"{line['cap_side_pool_cents']}"
    )