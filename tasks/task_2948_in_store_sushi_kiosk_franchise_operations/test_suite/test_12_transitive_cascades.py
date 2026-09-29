"""Cascades whose every link is caused strictly by the link before it."""

from test_helpers import (
    AUDIT_ESCALATED_CLOSURE,
    BATCH_CONSUMED,
    BATCH_REJECTED,
    CLOSURE_ESCALATED,
    DISCARD_AUDIT_LOCKDOWN,
    DISCARD_TEMP_ABUSE,
    FISH_QUARANTINED,
    FISH_RELEASED,
    KIOSK_OPERATING,
    KIOSK_SUSPENDED,
    KIOSK_SUSPENSION_AUDIT_ESCALATION,
    PACK_DISCARDED,
    PACK_MARKED_DOWN,
    PLAN_VOIDED,
    POSTURE_CLEAR,
    POSTURE_LOCKDOWN,
    QUARANTINE_REASON_COLD_CHAIN_BREACH,
    REJECTION_PLAN_VOIDED,
    SEVERITY_MAJOR,
    VERIFY_OUTCOME_FAIL,
    VOID_REASON_KIOSK_SUSPENDED,
    add_cold_chain_readings,
    add_draft_statement,
    add_mixing_rice_batch,
    add_reconciled_feed,
    add_released_plan,
    assert_close,
    base_world,
    drive_audit_to_second_round,
    packed_world,
    settled_world,
    validate_list,
    validate_success,
    verify_audit,
)


def test_an_escalated_audit_reaches_all_four_links_of_the_cascade(api):
    """One failing verification suspends, voids, discards and re-prices in one call.

    "it drives the full four-link cascade of §2.10: the audited kiosk moves
    `OPERATING → SUSPENDED` … its plans in `DRAFT`, `RELEASED` or `LOCKED` move to
    `VOIDED` … every pack lot of those plans' rice batches that is `ON_SHELF` or
    `MARKED_DOWN` moves to `DISCARDED` … and every `DRAFT` settlement statement
    covering the discard date recomputes `period_discard_value_cents`,
    `discard_credit_cents` and `net_due_cents`."

    Design: Difficulty/transitive_cascade/audit_escalation_four_link_cascade_to_settlement_credit
    """
    world = settled_world()
    assert world["statement"]["period_discard_value_cents"] == 0
    assert world["statement"]["net_due_cents"] == 296000

    cycled = drive_audit_to_second_round(world, severities=(SEVERITY_MAJOR,))
    escalated = verify_audit(world, cycled["audit_id"], VERIFY_OUTCOME_FAIL)
    assert escalated["status"] == AUDIT_ESCALATED_CLOSURE
    assert escalated["closure_outcome"] == CLOSURE_ESCALATED
    assert escalated["round_count"] == 2

    shut = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert shut["operational_state"] == KIOSK_SUSPENDED
    assert shut["suspension_reason"] == KIOSK_SUSPENSION_AUDIT_ESCALATION
    assert shut["sanitation_posture"] == POSTURE_LOCKDOWN

    voided = validate_success(
        api.get_production_plan(world["plan_id"], world["ops_headers"])
    )
    assert voided["status"] == PLAN_VOIDED
    assert voided["void_reason"] == VOID_REASON_KIOSK_SUSPENDED
    assert voided["actual_pack_count"] == 0

    stripped = validate_success(
        api.get_pack_lot(world["pack_lot_id"], world["ops_headers"])
    )
    assert stripped["status"] == PACK_DISCARDED
    assert stripped["discarded_count"] == 160
    assert stripped["unsold_count"] == 0

    events = validate_list(
        api.list_discard_events(world["pack_lot_id"], world["ops_headers"]),
        expected_total=1,
    )
    assert events[0]["reason"] == DISCARD_AUDIT_LOCKDOWN
    assert events[0]["unit_value_cents"] == 900
    assert events[0]["discard_value_cents"] == 144000
    assert events[0]["settlement_credit_eligible"] is False

    restated = validate_success(
        api.get_settlement_statement(world["statement_id"], world["ops_headers"])
    )
    assert restated["period_discard_value_cents"] == 144000
    assert restated["discard_credit_cents"] == 0
    assert restated["binding_share_cents"] == 296000
    assert restated["net_due_cents"] == 296000

    spared = validate_success(
        api.get_rice_batch(world["rice_batch_id"], world["ops_headers"])
    )
    assert spared["status"] == BATCH_CONSUMED
    assert spared["rejection_reason"] is None

    agreement = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert agreement["active_kiosk_count"] == 0


def test_with_nothing_on_the_shelf_the_cascade_stops_at_the_rejected_batch(api):
    """No live packs means no discard event, so the money never moves at all.

    "the rice batches of those voided plans that are not already `REJECTED` or
    `CONSUMED` move to `REJECTED` with `rejection_reason` `PLAN_VOIDED`" and only a
    lot that "is `ON_SHELF` or `MARKED_DOWN` moves to `DISCARDED`".

    Design: Difficulty/transitive_cascade/audit_escalation_four_link_cascade_to_settlement_credit
    """
    world = base_world()
    plan = add_released_plan(world)
    batch = add_mixing_rice_batch(world, plan["id"])
    add_reconciled_feed(world)
    statement = add_draft_statement(world)
    assert statement["net_due_cents"] == 296000

    cycled = drive_audit_to_second_round(world, severities=(SEVERITY_MAJOR,))
    escalated = verify_audit(world, cycled["audit_id"], VERIFY_OUTCOME_FAIL)
    assert escalated["status"] == AUDIT_ESCALATED_CLOSURE

    shut = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert shut["operational_state"] == KIOSK_SUSPENDED
    assert shut["sanitation_posture"] == POSTURE_LOCKDOWN

    voided = validate_success(api.get_production_plan(plan["id"], world["ops_headers"]))
    assert voided["status"] == PLAN_VOIDED
    assert voided["void_reason"] == VOID_REASON_KIOSK_SUSPENDED
    assert voided["actual_pack_count"] == 0

    rejected = validate_success(api.get_rice_batch(batch["id"], world["ops_headers"]))
    assert rejected["status"] == BATCH_REJECTED
    assert rejected["rejection_reason"] == REJECTION_PLAN_VOIDED

    validate_list(
        api.list_pack_lots(world["ops_headers"], {"rice_batch_id": batch["id"]}),
        expected_total=0,
    )
    untouched = validate_success(
        api.get_settlement_statement(statement["id"], world["ops_headers"])
    )
    assert untouched["period_discard_value_cents"] == 0
    assert untouched["discard_credit_cents"] == 0
    assert untouched["net_due_cents"] == 296000


def test_the_escalation_values_a_marked_down_lot_at_its_marked_down_price(api):
    """The third link prices the loss with the markdown, not the list price.

    "its `unit_value_cents` is `markdown_price_cents` when the lot was
    `MARKED_DOWN` and `list_price_cents` otherwise, and its `discard_value_cents`
    is the product of the two."

    Design: Difficulty/transitive_cascade/audit_escalation_four_link_cascade_to_settlement_credit
    """
    world = settled_world()
    marked = validate_success(
        api.markdown_pack_lot(world["pack_lot_id"], world["chef_headers"])
    )
    assert marked["status"] == PACK_MARKED_DOWN
    assert marked["markdown_price_cents"] == 675

    cycled = drive_audit_to_second_round(world, severities=(SEVERITY_MAJOR,))
    verify_audit(world, cycled["audit_id"], VERIFY_OUTCOME_FAIL)

    events = validate_list(
        api.list_discard_events(world["pack_lot_id"], world["ops_headers"]),
        expected_total=1,
    )
    assert events[0]["reason"] == DISCARD_AUDIT_LOCKDOWN
    assert events[0]["unit_value_cents"] == 675
    assert events[0]["discard_value_cents"] == 108000
    assert events[0]["settlement_credit_eligible"] is False

    restated = validate_success(
        api.get_settlement_statement(world["statement_id"], world["ops_headers"])
    )
    assert restated["period_discard_value_cents"] == 108000
    assert restated["discard_credit_cents"] == 0
    assert restated["net_due_cents"] == 296000


def test_one_warm_reading_pulls_the_packs_off_the_shelf_and_zeroes_the_actuals(api):
    """Crossing the limit by twenty minutes drags the product down with the lot.

    "a lot quarantined out of `RELEASED` also drags its product off the shelf —
    every pack lot built from it that is `ON_SHELF` or `MARKED_DOWN` moves to
    `DISCARDED` with a discard event whose `reason` is `TEMP_ABUSE`, and because
    those lots left the shelf each affected plan recomputes `actual_pack_count`."

    Design: Difficulty/transitive_cascade/cold_chain_quarantine_cascade_to_plan_actuals
    """
    world = packed_world(lot_overrides={"received_at": "2026-08-03T07:00:00Z"})
    live = validate_success(api.get_production_plan(world["plan_id"], world["ops_headers"]))
    assert live["actual_pack_count"] == 160

    warming = add_cold_chain_readings(
        world,
        world["fish_lot_id"],
        [("2026-08-03T07:20:00Z", 5.0), ("2026-08-03T07:40:00Z", 6.0)],
    )
    assert warming[0]["breach_minutes_attributed"] == 10
    assert warming[1]["breach_minutes_attributed"] == 20
    assert warming[1]["lot_breach_minutes_after"] == 30

    at_the_limit = validate_success(
        api.get_fish_lot(world["fish_lot_id"], world["ops_headers"])
    )
    assert at_the_limit["status"] == FISH_RELEASED
    assert at_the_limit["cold_chain_breach_minutes"] == 30

    over = add_cold_chain_readings(
        world, world["fish_lot_id"], [("2026-08-03T08:00:00Z", 6.0)]
    )
    assert over[0]["breach_minutes_attributed"] == 20
    assert over[0]["lot_breach_minutes_after"] == 50

    quarantined = validate_success(
        api.get_fish_lot(world["fish_lot_id"], world["ops_headers"])
    )
    assert quarantined["status"] == FISH_QUARANTINED
    assert quarantined["quarantine_reason"] == QUARANTINE_REASON_COLD_CHAIN_BREACH
    assert quarantined["cold_chain_breach_minutes"] == 50
    assert_close(quarantined["allocated_kg"], 7.200, places=3)
    assert_close(quarantined["remaining_kg"], 4.800, places=3)

    stripped = validate_success(
        api.get_pack_lot(world["pack_lot_id"], world["ops_headers"])
    )
    assert stripped["status"] == PACK_DISCARDED
    assert stripped["discarded_count"] == 160
    assert stripped["unsold_count"] == 0

    events = validate_list(
        api.list_discard_events(world["pack_lot_id"], world["ops_headers"]),
        expected_total=1,
    )
    assert events[0]["reason"] == DISCARD_TEMP_ABUSE
    assert events[0]["unit_value_cents"] == 900
    assert events[0]["discard_value_cents"] == 144000
    assert events[0]["settlement_credit_eligible"] is True

    emptied = validate_success(
        api.get_production_plan(world["plan_id"], world["ops_headers"])
    )
    assert emptied["actual_pack_count"] == 0

    kiosk = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert kiosk["risk_points"] == 6
    assert kiosk["sanitation_posture"] == POSTURE_CLEAR
    assert kiosk["operational_state"] == KIOSK_OPERATING


def test_a_temp_abuse_loss_earns_the_credit_an_audit_lockdown_never_would(api):
    """The same 144000 cent loss is shared when the cause is temperature, not compliance.

    "`settlement_credit_eligible` is true when the `reason` is `SHELF_LIFE_EXPIRED`
    or `TEMP_ABUSE` — ordinary spoilage and cold-chain loss, which the franchisor
    shares in — and false when it is `AUDIT_LOCKDOWN` or `VARIANCE_REJECTED`."

    Design: Difficulty/transitive_cascade/cold_chain_quarantine_cascade_to_plan_actuals
    """
    world = settled_world(lot_overrides={"received_at": "2026-08-03T07:00:00Z"})
    assert world["statement"]["net_due_cents"] == 296000

    add_cold_chain_readings(
        world,
        world["fish_lot_id"],
        [
            ("2026-08-03T07:20:00Z", 5.0),
            ("2026-08-03T07:40:00Z", 6.0),
            ("2026-08-03T08:00:00Z", 6.0),
        ],
    )

    events = validate_list(
        api.list_discard_events(world["pack_lot_id"], world["ops_headers"]),
        expected_total=1,
    )
    assert events[0]["reason"] == DISCARD_TEMP_ABUSE
    assert events[0]["settlement_credit_eligible"] is True

    credited = validate_success(
        api.get_settlement_statement(world["statement_id"], world["ops_headers"])
    )
    assert credited["binding_share_cents"] == 296000
    assert credited["period_discard_value_cents"] == 144000
    assert credited["discard_credit_cents"] == 29600
    assert credited["net_due_cents"] == 266400
