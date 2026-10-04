"""The conserved prize-pool ledger: draw-down, restoration and physical grants."""
from test_helpers import (
    assert_allocation_invariant,
    current_store,
    get_allocation,
    get_code,
    pass_distribution,
    propose_distribution,
    setup_application,
    setup_pool_with_physical_grants,
    void_distribution,
)


def test_three_local_physical_grants_are_floored_once_each_before_summing(api):
    """PRD §3.11: "The grant's point value is the number of packs for the pool's
    tier multiplied by the pack value ratio of twenty-seven over four, floored
    once to a whole number; the pack count is six for a `LOCAL` pool, twelve for
    a `QUALIFIER` pool and twenty-four for a `CHAMPIONSHIP` pool."
    PRD §2.9: "Where a calculation involves a division, the result is floored to a
    whole number at one single, named point in the computation, and the floored
    value is then carried forward — the arithmetic is never re-rounded at a later
    step, and it is never the case that several unrounded values are summed and
    the total floored afterwards."

    Design: Difficulty/combinatorial_formula/physical_grant_nested_rounding_floor_then_sum
    """
    store, _set_release, _fmt, application, allocation, cards = (
        setup_pool_with_physical_grants(grant_count=3, extra_tp=150, tier="LOCAL")
    )

    from test_helpers import disburse_code

    for card in cards:
        disburse_code(card["id"])

    updated = get_allocation(allocation["id"])
    assert updated["base_tp"] == 166
    assert updated["total_drawn_tp"] == 120, (
        "three LOCAL grants floored once each at 40 (6 * 27 / 4) sum to 120; "
        "summing the unrounded 40.5 grants and flooring once would give 121"
    )
    assert updated["total_restored_tp"] == 120
    assert updated["remaining_tp"] == 166
    assert_allocation_invariant(updated)

    first = get_code(cards[0]["id"])
    assert first["physical_grant_status"] == "DISBURSED"
    assert first["status"] == "REDEEMED"


def test_two_local_physical_grants_do_not_round_up_at_the_second_grant(api):
    """PRD §3.11: "The grant's point value is the number of packs for the pool's
    tier multiplied by the pack value ratio of twenty-seven over four, floored
    once to a whole number; the pack count is six for a `LOCAL` pool, twelve for
    a `QUALIFIER` pool and twenty-four for a `CHAMPIONSHIP` pool."
    PRD §2.9: "A physical prize grant's point value is floored exactly once for
    that grant and only then added into the allocation's counters."

    Design: Difficulty/combinatorial_formula/physical_grant_nested_rounding_floor_then_sum
    """
    store, _set_release, _fmt, application, allocation, cards = (
        setup_pool_with_physical_grants(grant_count=2, extra_tp=150, tier="LOCAL")
    )

    from test_helpers import disburse_code

    for card in cards:
        disburse_code(card["id"])

    updated = get_allocation(allocation["id"])
    assert updated["total_drawn_tp"] == 80, (
        "two floored LOCAL grants are 40 + 40; flooring the 81-point raw sum "
        "once would give 81"
    )
    assert updated["total_restored_tp"] == 80
    assert updated["remaining_tp"] == 166
    assert_allocation_invariant(updated)


def test_physical_grant_draw_and_restore_are_one_symmetric_movement(api):
    """PRD §3.11: "That single floored figure is then added to the pool's
    `total_drawn_tp` and, in the same transaction, added to the pool's
    `total_restored_tp`, and the pool's `remaining_tp` is re-derived. The floored
    figure is computed once for the grant and used for both sides — the grant's
    two counter movements are bit-for-bit identical, so the conserved invariant
    over the pool is exactly what it was before the disbursement."

    Design: Difficulty/compensating_invariant/physical_grant_points_conserved_within_draw_and_restore
    """
    store, _set_release, _fmt, application, allocation, cards = (
        setup_pool_with_physical_grants(grant_count=1, extra_tp=150, tier="LOCAL")
    )

    from test_helpers import disburse_code

    disbursed = disburse_code(cards[0]["id"])
    assert disbursed.status_code == 200, (
        "a physical grant is always covered because it restores as much as it draws"
    )

    updated = get_allocation(allocation["id"])
    assert updated["total_drawn_tp"] == 40
    assert updated["total_restored_tp"] == 40
    assert updated["remaining_tp"] == 166
    assert updated["status"] == "OPEN"
    assert_allocation_invariant(updated)

    card = get_code(cards[0]["id"])
    assert card["physical_grant_status"] == "DISBURSED"
    assert card["status"] == "REDEEMED"
    assert card["prize_allocation_id"] == allocation["id"]


def test_pass_then_void_of_one_distribution_leaves_the_pool_untouched(api):
    """PRD §2.4: "That symmetry is why the same quantity can be moved out of a
    pool and back again without the pool appearing to have changed."
    PRD §3.5: "If a passed distribution is voided and then passed again, the void
    first raises `total_restored_tp` by the quantity and the later pass raises
    `total_drawn_tp` by the same quantity, so the balance returns to precisely
    the figure it held before the void."

    Design: Difficulty/compensating_invariant/pool_points_conserved_across_pass_void_pair
    """
    store, _set_release, _fmt, application, allocation = setup_application(
        tier="QUALIFIER"
    )
    assert allocation["base_tp"] == 48

    distribution = propose_distribution(
        allocation["id"], store["id"], quantity=20, recipient_ref="PLAYER-20"
    )

    pass_distribution(distribution["id"])
    after_pass = get_allocation(allocation["id"])
    assert after_pass["total_drawn_tp"] == 20
    assert after_pass["remaining_tp"] == 28
    assert_allocation_invariant(after_pass)

    void_distribution(distribution["id"])
    after_void = get_allocation(allocation["id"])
    assert after_void["total_restored_tp"] == 20
    assert after_void["remaining_tp"] == 48

    invariant = (
        after_void["base_tp"]
        - after_void["total_drawn_tp"]
        + after_void["total_restored_tp"]
    )
    assert invariant == 48
    assert invariant == (allocation["base_tp"]), "the conserved invariant shows zero drift"
    assert current_store(store["id"])["tp_balance"] == 48