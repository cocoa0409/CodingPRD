"""Derived arithmetic: yield ceilings, tier ladders, risk points and markdown prices."""

from test_helpers import (
    AUDIT_CLOSED,
    CLOSURE_PASS,
    FISH_RECEIVED,
    MARKDOWN_POLICY_PRORATED,
    PACK_DISCARDED,
    PACK_MARKED_DOWN,
    POSTURE_CLEAR,
    POSTURE_LOCKDOWN,
    SEVERITY_CRITICAL,
    SEVERITY_MAJOR,
    SEVERITY_MINOR,
    add_cold_chain_readings,
    add_draft_statement,
    add_mixing_rice_batch,
    add_received_fish_lot,
    add_rejected_feed,
    add_released_plan,
    add_submitted_audit,
    add_submitted_feed,
    assert_risk_summary,
    base_world,
    discard_payload,
    DISCARD_SHELF_LIFE_EXPIRED,
    packed_world,
    validate_list,
    validate_success,
)


def test_rice_yield_ceiling_floors_the_pack_count_from_rice_mass(api):
    """The yield ceiling divides rice mass by the per-pack rice and floors it.

    "the batch … immediately computes `max_pack_yield`, the ceiling on how many
    packs may ever be drawn from it, as `rice_kg` divided by 0.12 kilograms of
    rice per pack, rounded down to a whole pack."

    Design: Corner/calculations/rice_yield_ceiling_floors_pack_yield_from_rice_mass
    """
    world = base_world()
    plan = add_released_plan(world)

    exact = add_mixing_rice_batch(world, plan["id"], rice_kg=21.6)
    assert exact["max_pack_yield"] == 180

    fractional = add_mixing_rice_batch(
        world,
        plan["id"],
        rice_kg=12.5,
        hold_start_at="2026-08-03T07:00:00Z",
        hold_end_at="2026-08-03T09:00:00Z",
    )
    assert fractional["max_pack_yield"] == 104

    tiny = add_mixing_rice_batch(
        world,
        plan["id"],
        rice_kg=0.11,
        hold_start_at="2026-08-03T09:00:00Z",
        hold_end_at="2026-08-03T10:00:00Z",
    )
    assert tiny["max_pack_yield"] == 0


def test_settlement_counts_only_reconciled_feeds(api):
    """Submitted and rejected feeds contribute nothing to the statement.

    "Only feeds of the agreement's host store whose `status` is `RECONCILED` and
    whose `business_date` falls inside the closed period contribute. … `SUBMITTED`
    and `REJECTED` feeds contribute nothing at all."

    Design: Corner/calculations/settlement_ignores_submitted_and_rejected_feeds
    """
    world = base_world()
    reconciled = validate_success(
        api.reconcile_pos_sales_feed(
            add_submitted_feed(world)["id"], world["ops_headers"]
        )
    )
    assert reconciled["gross_sales_cents"] == 2400000
    add_submitted_feed(
        world, business_date="2026-08-04", gross_sales_cents=1000000, markdown_sales_cents=0
    )
    add_rejected_feed(
        world, business_date="2026-08-05", gross_sales_cents=900000, markdown_sales_cents=0
    )
    validate_list(api.list_pos_sales_feeds(world["ops_headers"]), expected_total=3)

    statement = add_draft_statement(world)

    assert statement["gross_sales_cents"] == 2400000
    assert statement["markdown_sales_cents"] == 300000
    assert statement["settlement_base_cents"] == 2400000
    assert statement["binding_share_cents"] == 296000
    assert statement["net_due_cents"] == 296000


def test_audit_score_uses_the_hundred_point_deduction_weights(api):
    """The score deducts 2, 8 and 20 while the kiosk's risk total uses 1, 4 and 10.

    "`score` is 100 less two points per `MINOR`, eight per `MAJOR` and twenty per
    `CRITICAL`, floored at zero. Note that the score's deduction weights are
    deliberately *not* the same numbers as a finding's `risk_points`."

    Design: Corner/calculations/audit_score_uses_declared_severity_weights
    """
    world = base_world()
    submitted = add_submitted_audit(
        world,
        severities=(SEVERITY_MINOR, SEVERITY_MAJOR, SEVERITY_CRITICAL),
        codes=["FS-LABEL-WEAR", "FS-SANITISER-CONCENTRATION", "FS-CASE-TEMP-LOG"],
    )
    audit = submitted["audit"]

    assert audit["score"] == 70
    assert audit["critical_finding_count"] == 1
    assert audit["open_finding_count"] == 3

    summary = validate_success(
        api.get_kiosk_risk_summary(world["kiosk_id"], world["ops_headers"])
    )
    assert_risk_summary(summary)
    assert summary["minor_open"] == 1
    assert summary["major_open"] == 1
    assert summary["critical_open"] == 1
    assert summary["raw_risk_points"] == 15
    assert summary["risk_points"] == 15
    assert summary["sanitation_posture"] == POSTURE_LOCKDOWN
    assert summary["posture_forced_by_critical"] is True


def test_clean_audit_credit_cannot_push_risk_points_below_zero(api):
    """The clean-audit credit shows in the raw total but the stored total clamps at zero.

    "The sum is then clamped into the range 0 through 40 inclusive, and that
    clamped value is what `risk_points` holds."

    Design: Corner/calculations/kiosk_risk_points_floor_clamps_at_zero_after_clean_audit
    """
    world = base_world()
    first = add_submitted_audit(world, severities=())
    assert first["audit"]["status"] == AUDIT_CLOSED
    assert first["audit"]["closure_outcome"] == CLOSURE_PASS
    assert first["audit"]["score"] == 100

    kiosk = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert kiosk["consecutive_clean_audits"] == 1
    assert kiosk["risk_points"] == 0
    assert kiosk["sanitation_posture"] == POSTURE_CLEAR

    summary = validate_success(
        api.get_kiosk_risk_summary(world["kiosk_id"], world["ops_headers"])
    )
    assert summary["clean_audit_credit"] == 2
    assert summary["raw_risk_points"] == -2
    assert summary["risk_points"] == 0

    add_submitted_audit(world, severities=())
    second_kiosk = validate_success(
        api.get_kiosk(world["kiosk_id"], world["ops_headers"])
    )
    assert second_kiosk["consecutive_clean_audits"] == 2
    assert second_kiosk["risk_points"] == 0

    second_summary = validate_success(
        api.get_kiosk_risk_summary(world["kiosk_id"], world["ops_headers"])
    )
    assert second_summary["clean_audit_credit"] == 4
    assert second_summary["raw_risk_points"] == -4
    assert second_summary["risk_points"] == 0
    assert second_summary["sanitation_posture"] == POSTURE_CLEAR


def test_tier_ladder_is_marginal_at_the_second_tier_ceiling(api):
    """A base sitting exactly on the second ceiling earns the two lower tiers only.

    "the first 2,000,000 cents of base earn 12 percent, the portion from 2,000,000
    up to 5,000,000 cents earns 14 percent, and everything above 5,000,000 cents
    earns 16 percent. The three tier products are summed and only then rounded
    half up to whole cents."

    Design: Corner/calculations/settlement_share_at_tier_two_ceiling_boundary
    """
    at_ceiling = base_world()
    validate_success(
        api.reconcile_pos_sales_feed(
            add_submitted_feed(
                at_ceiling, gross_sales_cents=5000000, markdown_sales_cents=0
            )["id"],
            at_ceiling["ops_headers"],
        )
    )
    boundary_statement = add_draft_statement(at_ceiling)
    assert boundary_statement["settlement_base_cents"] == 5000000
    assert boundary_statement["binding_share_cents"] == 660000

    just_above = base_world(suffix="B")
    validate_success(
        api.reconcile_pos_sales_feed(
            add_submitted_feed(
                just_above, gross_sales_cents=5000001, markdown_sales_cents=0
            )["id"],
            just_above["ops_headers"],
        )
    )
    above_statement = add_draft_statement(just_above)
    assert above_statement["settlement_base_cents"] == 5000001
    assert above_statement["binding_share_cents"] == 660000


def test_cold_chain_totals_chronologically_whatever_the_append_order(api):
    """Readings are processed in recorded_at order, not in arrival order.

    "Readings are processed in `recorded_at` ascending order with ties broken by
    `created_at` ascending" and "each interval is rounded to a whole minute
    *before* the intervals are summed."

    Design: Corner/calculations/cold_chain_out_of_order_reading_still_totals_chronologically
    """
    world = base_world()
    lot = add_received_fish_lot(
        world, received_at="2026-08-03T06:00:00Z", receiving_temp_c=2.0
    )

    add_cold_chain_readings(world, lot["id"], [("2026-08-03T08:00:00Z", 2.0)])
    add_cold_chain_readings(world, lot["id"], [("2026-08-03T08:40:00Z", 4.4)])
    late_arrival = add_cold_chain_readings(
        world, lot["id"], [("2026-08-03T08:30:00Z", 6.0)]
    )[0]

    assert late_arrival["interval_minutes_from_previous"] == 30

    stored = validate_success(api.get_fish_lot(lot["id"], world["ops_headers"]))
    assert stored["cold_chain_breach_minutes"] == 20
    assert stored["status"] == FISH_RECEIVED

    readings = validate_list(
        api.list_cold_chain_readings(lot["id"], world["ops_headers"]), expected_total=3
    )
    assert [reading["recorded_at"][11:16] for reading in readings] == [
        "08:00",
        "08:40",
        "08:30",
    ]


def test_markdown_binding_variant_comes_from_the_agreement_policy(api):
    """The agreement's markdown policy names which computed variant is binding.

    "The binding number is the variant named by `markdown_policy` on the license
    agreement reached from the lot through its rice batch, that batch's plan, the
    plan's kiosk and the kiosk's agreement; it is written to
    `markdown_price_cents`, the other variant is written to
    `advisory_markdown_price_cents`, and `markdown_variant_applied` records which
    policy was binding."

    Design: Corner/calculations/pack_markdown_variant_selected_from_agreement_policy
    """
    world = packed_world()

    marked = validate_success(
        api.markdown_pack_lot(world["pack_lot_id"], world["chef_headers"])
    )

    assert marked["status"] == PACK_MARKED_DOWN
    assert marked["markdown_price_cents"] == 675
    assert marked["advisory_markdown_price_cents"] == 450
    assert marked["markdown_variant_applied"] == MARKDOWN_POLICY_PRORATED


def test_discard_after_markdown_is_valued_at_the_markdown_price(api):
    """The discard event values packs at the marked-down price, not the list price.

    "its `unit_value_cents` is `markdown_price_cents` when the lot was
    `MARKED_DOWN` and `list_price_cents` otherwise, and its `discard_value_cents`
    is the product of the two."

    Design: Corner/calculations/discard_valuation_uses_markdown_price_after_markdown
    """
    world = packed_world()
    validate_success(api.markdown_pack_lot(world["pack_lot_id"], world["chef_headers"]))

    validate_success(
        api.discard_pack_lot(
            world["pack_lot_id"],
            discard_payload(DISCARD_SHELF_LIFE_EXPIRED),
            world["chef_headers"],
        )
    )
    event = validate_list(
        api.list_discard_events(world["pack_lot_id"], world["ops_headers"]),
        expected_total=1,
    )[0]

    assert event["discarded_count"] == 160
    assert event["unit_value_cents"] == 675
    assert event["discard_value_cents"] == 108000
    assert event["settlement_credit_eligible"] is True
    assert event["reason"] == DISCARD_SHELF_LIFE_EXPIRED

    lot = validate_success(api.get_pack_lot(world["pack_lot_id"], world["ops_headers"]))
    assert lot["status"] == PACK_DISCARDED
    assert lot["unsold_count"] == 0
