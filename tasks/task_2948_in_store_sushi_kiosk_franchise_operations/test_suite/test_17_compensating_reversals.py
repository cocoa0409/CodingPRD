"""Reversals that must give back exactly what they took: fish mass and accrued cents."""

from test_helpers import (
    ApiErrorId,
    BATCH_CONSUMED,
    FISH_CONSUMED,
    FISH_RELEASED,
    OPS_CREATOR_ID,
    OPS_ISSUER_ID,
    PACK_MARKED_DOWN,
    PACK_ON_SHELF,
    PACK_VOIDED,
    SETTLEMENT_DISPUTED,
    SETTLEMENT_DRAFT,
    SETTLEMENT_ISSUED,
    SETTLEMENT_VOID,
    add_approved_rice_batch,
    add_draft_statement,
    add_pack_lot,
    assert_close,
    dispute_payload,
    pack_lot_void_payload,
    packed_world,
    settled_world,
    settlement_void_payload,
    shelf_ready_world,
    validate_error,
    validate_list,
    validate_success,
)

LEAN_LOT = {"net_weight_kg": 7.2}
SECOND_RUN = {"sku_code": "SPICY-6", "produced_at": "2026-08-03T09:00:00Z"}


def test_voiding_the_run_hands_every_gram_of_fish_back_to_its_lot(api):
    """A lot drawn down to nothing comes back to its full net weight and to RELEASED.

    "The void hands `consumed_fish_kg` back to the source lot exactly, decreasing its
    `allocated_kg` and increasing its `remaining_kg` by that precise figure and
    returning a `CONSUMED` source to `RELEASED`, and the owning plan recomputes
    `actual_pack_count`."

    Design: Difficulty/compensating_invariant/pack_void_restores_fish_lot_mass_exactly
    """
    world = packed_world(lot_overrides=LEAN_LOT)
    drawn = validate_success(
        api.get_fish_lot(world["fish_lot_id"], world["ops_headers"])
    )
    assert drawn["status"] == FISH_CONSUMED
    assert_close(drawn["allocated_kg"], 7.200, places=3)
    assert_close(drawn["remaining_kg"], 0.000, places=3)
    assert_close(drawn["allocated_kg"] + drawn["remaining_kg"], 7.200, places=3)

    voided = validate_success(
        api.void_pack_lot(
            world["pack_lot_id"], pack_lot_void_payload(), world["ops_headers"]
        )
    )
    assert voided["status"] == PACK_VOIDED
    assert voided["void_reason"] is not None
    assert voided["discarded_count"] == 0
    assert (
        voided["sold_count"] + voided["discarded_count"] + voided["unsold_count"]
        == voided["pack_count"]
    )
    validate_list(
        api.list_discard_events(world["pack_lot_id"], world["ops_headers"]),
        expected_total=0,
    )

    restored = validate_success(
        api.get_fish_lot(world["fish_lot_id"], world["ops_headers"])
    )
    assert restored["status"] == FISH_RELEASED
    assert_close(restored["allocated_kg"], 0.000, places=3)
    assert_close(restored["remaining_kg"], 7.200, places=3)
    assert_close(restored["allocated_kg"] + restored["remaining_kg"], 7.200, places=3)

    emptied = validate_success(
        api.get_production_plan(world["plan_id"], world["ops_headers"])
    )
    assert emptied["actual_pack_count"] == 0
    spent = validate_success(
        api.get_rice_batch(world["rice_batch_id"], world["ops_headers"])
    )
    assert spent["status"] == BATCH_CONSUMED

    validate_error(
        api.void_pack_lot(
            world["pack_lot_id"], pack_lot_void_payload(), world["ops_headers"]
        ),
        ApiErrorId.ERR_PACK_LOT_INVALID_STATE.value,
        409,
    )
    uncredited_twice = validate_success(
        api.get_fish_lot(world["fish_lot_id"], world["ops_headers"])
    )
    assert_close(uncredited_twice["remaining_kg"], 7.200, places=3)
    assert_close(uncredited_twice["allocated_kg"], 0.000, places=3)


def test_two_draws_and_one_reversal_keep_the_lot_ledger_balanced(api):
    """Reversing the smaller run leaves precisely the larger run's mass allocated.

    "`allocated_kg` is the sum of `consumed_fish_kg` over the lot's pack lots that are
    not `VOIDED`, and `remaining_kg` is `net_weight_kg` minus `allocated_kg` rounded
    half up to three decimal places, conserved against the net weight at all times."

    Design: Difficulty/compensating_invariant/pack_void_restores_fish_lot_mass_exactly
    """
    world = shelf_ready_world()
    bigger = add_pack_lot(
        world, world["rice_batch_id"], world["fish_lot_id"], pack_count=100
    )
    # A rice batch is spent by exactly one pack lot, so the second draw on the
    # same fish lot comes off its own approved batch, held in a window that only
    # touches the first one's end instant and therefore does not overlap it.
    second_batch = add_approved_rice_batch(
        world,
        world["plan_id"],
        hold_start_at="2026-08-03T07:00:00Z",
        hold_end_at="2026-08-03T09:00:00Z",
    )
    smaller = add_pack_lot(
        world,
        second_batch["id"],
        world["fish_lot_id"],
        pack_count=60,
        **SECOND_RUN,
    )
    assert_close(bigger["consumed_fish_kg"], 4.500, places=3)
    assert_close(smaller["consumed_fish_kg"], 2.700, places=3)

    drawn = validate_success(
        api.get_fish_lot(world["fish_lot_id"], world["ops_headers"])
    )
    assert drawn["status"] == FISH_RELEASED
    assert_close(drawn["allocated_kg"], 7.200, places=3)
    assert_close(drawn["remaining_kg"], 4.800, places=3)
    assert_close(drawn["allocated_kg"] + drawn["remaining_kg"], 12.000, places=3)

    voided = validate_success(
        api.void_pack_lot(smaller["id"], pack_lot_void_payload(), world["ops_headers"])
    )
    assert voided["status"] == PACK_VOIDED

    rebalanced = validate_success(
        api.get_fish_lot(world["fish_lot_id"], world["ops_headers"])
    )
    assert rebalanced["status"] == FISH_RELEASED
    assert_close(rebalanced["allocated_kg"], 4.500, places=3)
    assert_close(rebalanced["remaining_kg"], 7.500, places=3)
    assert_close(
        rebalanced["allocated_kg"] + rebalanced["remaining_kg"], 12.000, places=3
    )

    untouched = validate_success(api.get_pack_lot(bigger["id"], world["ops_headers"]))
    assert untouched["status"] == PACK_ON_SHELF
    assert untouched["unsold_count"] == 100
    reduced = validate_success(
        api.get_production_plan(world["plan_id"], world["ops_headers"])
    )
    assert reduced["actual_pack_count"] == 100


def test_a_marked_down_run_cannot_be_voided_so_the_mass_stays_drawn(api):
    """With the compensation unavailable the lot keeps every gram it had allocated.

    "Voiding, by contrast, is a franchisor correction for packs that should never have
    been built: it takes a `void_reason`, is available only from `ON_SHELF`, and only
    while `sold_count` is exactly zero — a lot that has sold even one pack cannot be
    voided, and neither can a marked-down one."

    Design: Difficulty/compensating_invariant/pack_void_restores_fish_lot_mass_exactly
    """
    world = packed_world(lot_overrides=LEAN_LOT)
    marked = validate_success(
        api.markdown_pack_lot(world["pack_lot_id"], world["chef_headers"])
    )
    assert marked["status"] == PACK_MARKED_DOWN

    validate_error(
        api.void_pack_lot(
            world["pack_lot_id"], pack_lot_void_payload(), world["ops_headers"]
        ),
        ApiErrorId.ERR_PACK_LOT_INVALID_STATE.value,
        409,
    )

    held = validate_success(api.get_fish_lot(world["fish_lot_id"], world["ops_headers"]))
    assert held["status"] == FISH_CONSUMED
    assert_close(held["allocated_kg"], 7.200, places=3)
    assert_close(held["remaining_kg"], 0.000, places=3)

    unchanged = validate_success(
        api.get_pack_lot(world["pack_lot_id"], world["ops_headers"])
    )
    assert unchanged["status"] == PACK_MARKED_DOWN
    assert unchanged["unsold_count"] == 160
    booked = validate_success(
        api.get_production_plan(world["plan_id"], world["ops_headers"])
    )
    assert booked["actual_pack_count"] == 160


def test_voiding_an_issued_statement_unbooks_exactly_what_it_booked(api):
    """The lifetime ledger walks zero to 296000 and back to zero without drift.

    "When the voided statement had reached `ISSUED` or `ACKNOWLEDGED` — and so had
    booked an accrual that was not already reversed by a dispute — its
    `binding_share_cents` is subtracted from `lifetime_share_accrued_cents`, and the
    requirement is exactness"

    Design: Difficulty/compensating_invariant/settlement_void_restores_license_lifetime_accrual_exactly
    """
    world = settled_world()
    assert world["statement"]["binding_share_cents"] == 296000
    assert world["statement"]["net_due_cents"] == 296000

    unbooked = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert unbooked["lifetime_share_accrued_cents"] == 0

    issued = validate_success(
        api.issue_settlement_statement(world["statement_id"], world["ops_issuer_headers"])
    )
    assert issued["status"] == SETTLEMENT_ISSUED
    booked = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert booked["lifetime_share_accrued_cents"] == 296000

    scrapped = validate_success(
        api.void_settlement_statement(
            world["statement_id"], settlement_void_payload(), world["ops_headers"]
        )
    )
    assert scrapped["status"] == SETTLEMENT_VOID
    assert scrapped["void_reason"] is not None
    assert scrapped["binding_share_cents"] == 296000
    assert scrapped["net_due_cents"] == 296000
    assert scrapped["created_by_user_id"] == OPS_CREATOR_ID
    assert scrapped["issued_by_user_id"] == OPS_ISSUER_ID

    reversed_out = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert reversed_out["lifetime_share_accrued_cents"] == 0


def test_the_freed_period_can_be_settled_again_without_double_booking(api):
    """Re-billing the same month books the share once, not twice.

    "Throughout its life the agreement carries `lifetime_share_accrued_cents`, a
    conserved ledger that at all times equals the sum of `binding_share_cents` over the
    statements of this agreement whose `status` is `ISSUED`, `ACKNOWLEDGED` or `PAID`"

    Design: Difficulty/compensating_invariant/settlement_void_restores_license_lifetime_accrual_exactly
    """
    world = settled_world()
    validate_success(
        api.issue_settlement_statement(world["statement_id"], world["ops_issuer_headers"])
    )
    validate_success(
        api.void_settlement_statement(
            world["statement_id"], settlement_void_payload(), world["ops_headers"]
        )
    )
    cleared = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert cleared["lifetime_share_accrued_cents"] == 0

    fresh = add_draft_statement(world)
    assert fresh["status"] == SETTLEMENT_DRAFT
    assert fresh["superseded_statement_id"] is None
    assert fresh["binding_share_cents"] == 296000

    reissued = validate_success(
        api.issue_settlement_statement(fresh["id"], world["ops_issuer_headers"])
    )
    assert reissued["status"] == SETTLEMENT_ISSUED
    assert reissued["binding_share_cents"] == 296000

    rebooked = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert rebooked["lifetime_share_accrued_cents"] == 296000

    validate_list(
        api.list_settlement_statements(
            world["ops_headers"], {"license_agreement_id": world["agreement_id"]}
        ),
        expected_total=2,
    )


def test_a_dispute_already_reversed_the_accrual_so_the_void_leaves_it_alone(api):
    """Two reversals of one booking would drive the ledger negative, so only one lands.

    "A dispute records `dispute_reason` and subtracts `binding_share_cents` back out of
    `lifetime_share_accrued_cents`, so a contested bill stops counting as accrued
    revenue while it is contested."

    Design: Difficulty/compensating_invariant/settlement_void_restores_license_lifetime_accrual_exactly
    """
    world = settled_world()
    validate_success(
        api.issue_settlement_statement(world["statement_id"], world["ops_issuer_headers"])
    )
    booked = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert booked["lifetime_share_accrued_cents"] == 296000

    contested = validate_success(
        api.dispute_settlement_statement(
            world["statement_id"], dispute_payload(), world["manager_headers"]
        )
    )
    assert contested["status"] == SETTLEMENT_DISPUTED

    reversed_once = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert reversed_once["lifetime_share_accrued_cents"] == 0

    scrapped = validate_success(
        api.void_settlement_statement(
            world["statement_id"], settlement_void_payload(), world["ops_headers"]
        )
    )
    assert scrapped["status"] == SETTLEMENT_VOID
    assert scrapped["binding_share_cents"] == 296000

    still_zero = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert still_zero["lifetime_share_accrued_cents"] == 0
