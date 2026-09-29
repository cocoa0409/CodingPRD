"""Optimistic-concurrency tokens, denormalised counters and same-request visibility."""

from test_helpers import (
    ApiErrorId,
    BATCH_CONSUMED,
    CAP_SOURCE_DEMAND,
    DISCARD_AUDIT_LOCKDOWN,
    DISCARD_SHELF_LIFE_EXPIRED,
    KIOSK_DECOMMISSIONED,
    KIOSK_OPERATING,
    KIOSK_SUSPENDED,
    LICENSE_ACTIVE,
    PACK_DISCARDED,
    PACK_ON_SHELF,
    PLAN_DRAFT,
    PLAN_RELEASED,
    PLAN_VOIDED,
    POSTURE_RESTRICTED,
    POSTURE_WATCH,
    SEVERITY_MAJOR,
    SEVERITY_MINOR,
    VOID_REASON_SUPERSEDED,
    add_approved_rice_batch,
    add_kiosk,
    add_reconciled_feed,
    add_submitted_audit,
    assert_close,
    assert_instant_equals,
    base_world,
    commission_kiosk,
    decommission_payload,
    discard_payload,
    pack_lot_payload,
    parse_instant,
    production_plan_payload,
    set_clock,
    settled_world,
    settlement_statement_payload,
    shelf_ready_world,
    suspension_payload,
    validate_error,
    validate_list,
    validate_success,
    waiver_payload,
)


def test_a_stale_kiosk_version_cannot_supersede_a_plan_it_never_saw(api):
    """The concurrency check runs ahead of the supersede, so nothing is voided.

    "If the kiosk's current `version` differs, the create is rejected with
    `ERR_STALE_KIOSK_VERSION` (HTTP 412). The reason is that a new draft plan
    legitimately supersedes any prior draft plan for the same kiosk and production
    date: without the check, a writer holding an outdated view of the kiosk would
    void a plan it had never seen."

    Design: Corner/cross_cutting_complexity_layers/plan_create_with_stale_kiosk_version_rejected
    """
    world = base_world()
    opening = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    stale_version = opening["version"]

    first_plan = validate_success(
        api.create_production_plan(
            production_plan_payload(world["kiosk_id"], stale_version),
            world["chef_headers"],
        ),
        201,
    )
    assert first_plan["status"] == PLAN_DRAFT
    assert first_plan["superseded_plan_id"] is None

    validate_error(
        api.create_production_plan(
            production_plan_payload(
                world["kiosk_id"], stale_version, traffic_forecast=12000
            ),
            world["chef_headers"],
        ),
        ApiErrorId.ERR_STALE_KIOSK_VERSION.value,
        412,
    )

    validate_list(
        api.list_production_plans(
            world["ops_headers"], {"kiosk_id": world["kiosk_id"]}
        ),
        expected_total=1,
    )
    spared = validate_success(
        api.get_production_plan(first_plan["id"], world["ops_headers"])
    )
    assert spared["status"] == PLAN_DRAFT
    assert spared["void_reason"] is None

    after_refusal = validate_success(
        api.get_kiosk(world["kiosk_id"], world["ops_headers"])
    )
    assert after_refusal["version"] == stale_version + 1

    retried = validate_success(
        api.create_production_plan(
            production_plan_payload(
                world["kiosk_id"], after_refusal["version"], traffic_forecast=12000
            ),
            world["chef_headers"],
        ),
        201,
    )
    assert retried["superseded_plan_id"] == first_plan["id"]

    superseded = validate_success(
        api.get_production_plan(first_plan["id"], world["ops_headers"])
    )
    assert superseded["status"] == PLAN_VOIDED
    assert superseded["void_reason"] == VOID_REASON_SUPERSEDED


def test_a_stale_agreement_version_cannot_draft_a_settlement(api):
    """The settlement token is the agreement's version, not the kiosk's.

    "If the agreement's current `version` differs, the create is rejected with
    `ERR_STALE_LICENSE_VERSION` (HTTP 412) … so a stale writer would compute a
    statement against superseded terms."

    Design: Corner/cross_cutting_complexity_layers/settlement_create_with_stale_license_version_rejected
    """
    world = base_world()
    add_reconciled_feed(world)
    observed = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    stale_version = observed["version"]

    validate_success(
        api.suspend_license_agreement(
            world["agreement_id"], suspension_payload(), world["ops_headers"]
        )
    )
    validate_success(
        api.reinstate_license_agreement(world["agreement_id"], world["ops_headers"])
    )

    validate_error(
        api.create_settlement_statement(
            settlement_statement_payload(world["agreement_id"], stale_version),
            world["ops_headers"],
        ),
        ApiErrorId.ERR_STALE_LICENSE_VERSION.value,
        412,
    )

    validate_list(
        api.list_settlement_statements(
            world["ops_headers"], {"license_agreement_id": world["agreement_id"]}
        ),
        expected_total=0,
    )
    intact = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert intact["status"] == LICENSE_ACTIVE
    assert intact["lifetime_share_accrued_cents"] == 0
    assert intact["version"] == stale_version + 2

    drafted = validate_success(
        api.create_settlement_statement(
            settlement_statement_payload(world["agreement_id"], intact["version"]),
            world["ops_headers"],
        ),
        201,
    )
    assert drafted["binding_share_cents"] == 296000


def test_the_kiosk_version_moves_on_writes_and_stands_still_on_reads(api):
    """Two mutations advance the token by exactly one each; the reads never touch it.

    "`version`, an integer that starts at 1 when the row is created and increments
    by exactly 1 on every mutation of that row" and `updated_at` is "refreshed to
    the current logical instant on every mutation".

    Design: Corner/cross_cutting_complexity_layers/kiosk_version_increments_on_every_write
    """
    world = base_world()
    baseline = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    opening_version = baseline["version"]
    created_at = baseline["created_at"]

    suspended = validate_success(
        api.suspend_kiosk(
            world["kiosk_id"],
            suspension_payload(suspension_reason="DEEP_CLEAN_WINDOW"),
            world["ops_headers"],
        )
    )
    assert suspended["version"] == opening_version + 1
    assert suspended["operational_state"] == KIOSK_SUSPENDED
    assert_instant_equals(suspended["updated_at"], "2026-08-03T11:00:00Z")

    read_back = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert read_back["version"] == opening_version + 1

    set_clock("2026-08-03T12:00:00Z")
    reinstated = validate_success(
        api.reinstate_kiosk(world["kiosk_id"], world["ops_headers"])
    )
    assert reinstated["version"] == opening_version + 2
    assert reinstated["operational_state"] == KIOSK_OPERATING
    assert reinstated["created_at"] == created_at
    assert parse_instant(reinstated["updated_at"]) > parse_instant(
        suspended["updated_at"]
    )

    validate_success(
        api.get_kiosk_risk_summary(world["kiosk_id"], world["ops_headers"])
    )
    final = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert final["version"] == opening_version + 2
    assert final["created_at"] == created_at


def test_the_agreement_recounts_its_operating_kiosks_after_every_change(api):
    """The live-kiosk counter is recomputed, not decremented one way.

    Commissioning "increments the agreement's `active_kiosk_count` by 1"; suspension
    decrements it by 1; decommissioning "sets the agreement's `active_kiosk_count`
    to a fresh recount of that agreement's kiosks that are still `OPERATING`"; and
    reinstatement "increments `active_kiosk_count` by 1".

    Design: Corner/cross_cutting_complexity_layers/license_agreement_active_kiosk_count_reconciles_over_kiosk_lifecycle
    """
    world = base_world(commission=False)
    empty = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert empty["active_kiosk_count"] == 0

    commission_kiosk(world["kiosk_id"])
    one_live = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert one_live["active_kiosk_count"] == 1

    second = add_kiosk(world, "K-418-B", "Mika Sato")
    both_live = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert both_live["active_kiosk_count"] == 2

    down = validate_success(
        api.suspend_kiosk(
            second["kiosk_id"],
            suspension_payload(suspension_reason="CASE_COMPRESSOR_FAULT"),
            world["ops_headers"],
        )
    )
    assert down["operational_state"] == KIOSK_SUSPENDED
    after_suspend = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert after_suspend["active_kiosk_count"] == 1

    sibling = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert sibling["operational_state"] == KIOSK_OPERATING

    retired = validate_success(
        api.decommission_kiosk(
            world["kiosk_id"], decommission_payload(), world["ops_headers"]
        )
    )
    assert retired["operational_state"] == KIOSK_DECOMMISSIONED
    assert retired["lead_chef_id"] is None
    unassigned = validate_success(api.get_chef(world["chef_id"], world["ops_headers"]))
    assert unassigned["assigned_kiosk_id"] is None

    emptied = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert emptied["active_kiosk_count"] == 0

    back_up = validate_success(
        api.reinstate_kiosk(second["kiosk_id"], world["ops_headers"])
    )
    assert back_up["operational_state"] == KIOSK_OPERATING
    recounted = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert recounted["active_kiosk_count"] == 1


def test_eighteen_risk_points_lands_in_restricted_and_halves_the_next_plan(api):
    """Exactly eighteen is the restricted band, and the halving lands after the minimum.

    "a total of at least 18 but below 30 is `RESTRICTED` … so exactly 8 is `WATCH`
    and exactly 18 is `RESTRICTED`", and "0.50 when it is `RESTRICTED` and 0.00 when
    it is `LOCKDOWN`; `planned_pack_count` is the binding ceiling multiplied by that
    factor and rounded down to a whole pack."

    Design: Corner/cross_cutting_complexity_layers/kiosk_risk_points_at_restricted_threshold_boundary
    """
    world = base_world()
    submitted = add_submitted_audit(
        world,
        severities=(
            SEVERITY_MAJOR,
            SEVERITY_MAJOR,
            SEVERITY_MAJOR,
            SEVERITY_MAJOR,
            SEVERITY_MINOR,
            SEVERITY_MINOR,
        ),
    )
    assert submitted["audit"]["score"] == 64
    assert submitted["audit"]["open_finding_count"] == 6

    at_the_threshold = validate_success(
        api.get_kiosk(world["kiosk_id"], world["ops_headers"])
    )
    assert at_the_threshold["risk_points"] == 18
    assert at_the_threshold["sanitation_posture"] == POSTURE_RESTRICTED

    halved = validate_success(
        api.create_production_plan(
            production_plan_payload(
                world["kiosk_id"], at_the_threshold["version"], traffic_forecast=9000
            ),
            world["chef_headers"],
        ),
        201,
    )
    assert_close(halved["posture_factor_applied"], 0.50, places=2)
    assert halved["binding_cap_source"] == CAP_SOURCE_DEMAND
    assert halved["planned_pack_count"] == 81
    assert_close(halved["planned_rice_kg"], 9.72, places=2)

    minor = next(
        finding
        for finding in submitted["findings"]
        if finding["severity"] == SEVERITY_MINOR
    )
    validate_success(
        api.waive_finding(
            submitted["audit_id"], minor["id"], waiver_payload(), world["auditor_headers"]
        )
    )

    below_the_threshold = validate_success(
        api.get_kiosk(world["kiosk_id"], world["ops_headers"])
    )
    assert below_the_threshold["risk_points"] == 17
    assert below_the_threshold["sanitation_posture"] == POSTURE_WATCH


def test_building_packs_settles_every_cascade_inside_the_create_response(api):
    """Nothing about a pack lot build is deferred to a later read.

    "Its `consumed_fish_kg` is `pack_count` multiplied by 0.045 kilograms of fish per
    pack, rounded half up to three decimal places, and that mass is immediately
    debited from the source lot … The owning plan recomputes `actual_pack_count` in
    the same breath, so a plan's actual figure is live from the moment packs are
    built rather than deferred to reconciliation."

    Design: Corner/consistency_model/pack_lot_create_reflects_every_cascade_in_the_same_response
    """
    world = shelf_ready_world()

    built = validate_success(
        api.create_pack_lot(
            pack_lot_payload(
                world["rice_batch_id"], world["fish_lot_id"], pack_count=160
            ),
            world["chef_headers"],
        ),
        201,
    )
    assert_close(built["consumed_fish_kg"], 7.200, places=3)
    assert_instant_equals(built["shelf_expiry_at"], "2026-08-03T20:00:00Z")
    assert built["status"] == PACK_ON_SHELF
    assert built["unsold_count"] == 160
    assert built["sold_count"] == 0
    assert built["discarded_count"] == 0

    batch = validate_success(
        api.get_rice_batch(world["rice_batch_id"], world["ops_headers"])
    )
    assert batch["status"] == BATCH_CONSUMED

    source = validate_success(
        api.get_fish_lot(world["fish_lot_id"], world["ops_headers"])
    )
    assert_close(source["allocated_kg"], 7.200, places=3)
    assert_close(source["remaining_kg"], 4.800, places=3)

    plan = validate_success(
        api.get_production_plan(world["plan_id"], world["ops_headers"])
    )
    assert plan["actual_pack_count"] == 160
    assert plan["status"] == PLAN_RELEASED


def test_one_discard_reaches_the_plan_and_the_draft_statement_at_once(api):
    """The credit is already netted on the very next read, with no reconcile step.

    "every `DRAFT` settlement statement whose period covers the discard date
    recomputes `period_discard_value_cents` and — only when the event was
    credit-eligible — `discard_credit_cents` and `net_due_cents` too."

    Design: Corner/consistency_model/discard_updates_plan_and_draft_statement_in_the_same_request
    """
    world = settled_world()

    validate_success(
        api.discard_pack_lot(
            world["pack_lot_id"],
            discard_payload(DISCARD_SHELF_LIFE_EXPIRED),
            world["auditor_headers"],
        )
    )
    emptied = validate_success(
        api.get_pack_lot(world["pack_lot_id"], world["ops_headers"])
    )
    assert emptied["status"] == PACK_DISCARDED
    assert emptied["discarded_count"] == 160
    assert emptied["unsold_count"] == 0

    events = validate_list(
        api.list_discard_events(world["pack_lot_id"], world["ops_headers"]),
        expected_total=1,
    )
    assert events[0]["unit_value_cents"] == 900
    assert events[0]["discard_value_cents"] == 144000
    assert events[0]["settlement_credit_eligible"] is True

    plan = validate_success(
        api.get_production_plan(world["plan_id"], world["ops_headers"])
    )
    assert plan["actual_pack_count"] == 0

    credited = validate_success(
        api.get_settlement_statement(world["statement_id"], world["ops_headers"])
    )
    assert credited["binding_share_cents"] == 296000
    assert credited["period_discard_value_cents"] == 144000
    assert credited["discard_credit_cents"] == 29600
    assert credited["net_due_cents"] == 266400

    second_batch = add_approved_rice_batch(
        world,
        world["plan_id"],
        hold_start_at="2026-08-03T07:00:00Z",
        hold_end_at="2026-08-03T09:00:00Z",
    )
    compliance_loss = validate_success(
        api.create_pack_lot(
            pack_lot_payload(
                second_batch["id"], world["fish_lot_id"], pack_count=100
            ),
            world["chef_headers"],
        ),
        201,
    )
    validate_success(
        api.discard_pack_lot(
            compliance_loss["id"],
            discard_payload(DISCARD_AUDIT_LOCKDOWN),
            world["auditor_headers"],
        )
    )

    disclosed = validate_success(
        api.get_settlement_statement(world["statement_id"], world["ops_headers"])
    )
    assert disclosed["period_discard_value_cents"] == 234000
    assert disclosed["discard_credit_cents"] == 29600
    assert disclosed["net_due_cents"] == 266400
