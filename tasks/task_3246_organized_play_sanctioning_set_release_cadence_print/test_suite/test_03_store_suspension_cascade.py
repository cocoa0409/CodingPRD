"""Store suspension, the four-hop cascade it drives, and the fact that
reinstatement is not an undo."""
from test_helpers import (
    get_allocation,
    get_application,
    get_distribution,
    pass_distribution,
    propose_distribution,
    reinstate_store,
    setup_application,
    suspend_store,
)


def test_suspension_denies_releases_voids_and_returns_the_invariant(api):
    """PRD §3.1: "When a store is suspended, every application of that store
    still standing in `SUBMITTED`, `APPROVED` or `COMPLETED` is denied, and —
    importantly — each such application keeps whatever `prizing_report_status` it
    already had rather than being reset. Every still-open allocation of the store
    is released, and every distribution that had passed under those allocations
    is voided, with each affected allocation's `total_restored_tp` re-derived
    from the voided distributions and the submitted reports rather than
    incremented, so the conserved invariant lands back on the figure it held
    before the allocation's first draw."

    Design: Difficulty/transitive_cascade/store_suspension_four_hop_cascade
    """
    store, _set_release, _fmt, application, allocation = setup_application(tier="LOCAL")
    distribution = propose_distribution(
        allocation["id"], store["id"], quantity=10, recipient_ref="PLAYER-77"
    )
    pass_distribution(distribution["id"])

    drawn = get_allocation(allocation["id"])
    assert drawn["total_drawn_tp"] == 10
    assert drawn["remaining_tp"] == 6

    suspend_store(store["id"])

    assert get_application(application["id"])["status"] == "DENIED"
    released = get_allocation(allocation["id"])
    assert released["status"] == "RELEASED"
    assert get_distribution(distribution["id"])["status"] == "VOIDED"
    assert released["total_drawn_tp"] == 10
    assert released["total_restored_tp"] == 10
    assert released["remaining_tp"] == 16, (
        "the invariant returns to the pre-draw figure of the 16-point LOCAL pool"
    )


def test_suspension_cascade_reaches_the_store_derived_tp_balance(api):
    """PRD §2.7: "The store's `tp_balance` is the sum of `remaining_tp` across
    every prize allocation the store owns, so it falls as prizes are drawn and
    rises again as points are restored."
    PRD §3.1: "Every still-open allocation of the store is released, and every
    distribution that had passed under those allocations is voided, with each
    affected allocation's `total_restored_tp` re-derived from the voided
    distributions and the submitted reports rather than incremented, so the
    conserved invariant lands back on the figure it held before the allocation's
    first draw."

    Design: Difficulty/transitive_cascade/store_suspension_four_hop_cascade
    """
    store, _set_release, _fmt, application, allocation = setup_application(tier="LOCAL")
    distribution = propose_distribution(
        allocation["id"], store["id"], quantity=10, recipient_ref="PLAYER-78"
    )
    pass_distribution(distribution["id"])

    suspend_store(store["id"])
    assert get_allocation(allocation["id"])["remaining_tp"] == 16

    from test_helpers import current_store

    store_row = current_store(store["id"])
    assert store_row["status"] == "SUSPENDED"
    assert store_row["tp_balance"] == 16, (
        "the store's rolled-up balance tracks the restored allocation"
    )


def test_reinstatement_does_not_reopen_the_released_allocation(api):
    """PRD §3.1: "Reinstating a suspended store restores nothing: no application
    and no allocation is re-opened, and the store simply resumes from `ACTIVE`
    with its history intact."
    PRD §2.7: "Restoring a suspended store to `ACTIVE` reverses none of this —
    reinstatement is not an undo, and no allocation and no application is
    re-opened by it."

    Design: Corner/state_machines/allocation_released_by_suspension_cannot_be_reinstated_in_place
    """
    store, _set_release, _fmt, application, allocation = setup_application(tier="LOCAL")
    distribution = propose_distribution(
        allocation["id"], store["id"], quantity=4, recipient_ref="PLAYER-4"
    )
    pass_distribution(distribution["id"])

    suspend_store(store["id"])
    reinstate_store(store["id"])

    from test_helpers import current_store

    store_row = current_store(store["id"])
    assert store_row["status"] == "ACTIVE"
    assert get_allocation(allocation["id"])["status"] == "RELEASED", (
        "the released allocation does not return to OPEN"
    )
    assert get_distribution(distribution["id"])["status"] == "VOIDED"
    assert get_application(application["id"])["status"] == "DENIED"
    assert get_allocation(allocation["id"])["total_restored_tp"] == 4