"""Writes refused because a neighbouring entity is in the wrong state at write time."""

from test_helpers import (
    ApiErrorId,
    CAP_SOURCE_DEMAND,
    CHEF_CERTIFIED,
    CHEF_TRAINEE,
    FEED_RECONCILED,
    FEED_SUBMITTED,
    KIOSK_OPERATING,
    KIOSK_PROVISIONING,
    POS_CONNECTED,
    POS_SUSPENDED,
    POSTURE_CLEAR,
    POSTURE_LOCKDOWN,
    SEVERITY_CRITICAL,
    add_draft_statement,
    add_reverification_request,
    add_submitted_audit,
    add_submitted_feed,
    assert_close,
    base_world,
    commission_payload,
    connect_pos,
    log_training,
    production_plan_payload,
    validate_error,
    validate_list,
    validate_success,
    verify_audit,
)

TWELVE_HOURS = {"hours": 12}
CRITICAL_CODES = ["FS-RODENT-ACTIVITY"]


def test_a_trainee_lead_chef_keeps_the_kiosk_in_provisioning(api):
    """Both certifications in hand and half the training hours is still not certified.

    "the chef named by `lead_chef_id` must have `status` `CERTIFIED` and must actually
    be assigned to this kiosk, or `ERR_CHEF_NOT_CERTIFIED`"

    Design: Difficulty/cross_entity_state_dependency/kiosk_commission_blocked_by_uncertified_lead_chef_rejected
    """
    world = base_world(training_overrides=TWELVE_HOURS, commission=False)
    chef = validate_success(api.get_chef(world["chef_id"], world["ops_headers"]))
    assert chef["status"] == CHEF_TRAINEE
    assert chef["training_hours_logged"] == 12
    assert chef["valid_cert_count"] == 2

    validate_error(
        api.commission_kiosk(
            world["kiosk_id"],
            commission_payload(commissioned_on="2026-08-03"),
            world["ops_headers"],
        ),
        ApiErrorId.ERR_CHEF_NOT_CERTIFIED.value,
        422,
    )

    shell = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert shell["operational_state"] == KIOSK_PROVISIONING
    assert shell["commissioned_on"] is None
    assert shell["certified_chef_count"] == 0
    assert shell["daily_pack_cap"] == 0

    agreement = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert agreement["active_kiosk_count"] == 0


def test_twelve_more_training_hours_unlock_the_identical_commission_call(api):
    """The gate is the chef's status, not the commissioning payload.

    "A chef whose `training_hours_logged` is at least 24 hours **and** who holds a
    valid `FOOD_HANDLER` certification whose `expires_at` is strictly after the
    logical clock **and** a valid `HACCP_RICE_ACIDIFICATION` certification whose
    `expires_at` is strictly after the logical clock becomes `CERTIFIED`; exactly 24
    hours is enough."

    Design: Difficulty/cross_entity_state_dependency/kiosk_commission_blocked_by_uncertified_lead_chef_rejected
    """
    world = base_world(training_overrides=TWELVE_HOURS, commission=False)
    validate_error(
        api.commission_kiosk(
            world["kiosk_id"],
            commission_payload(commissioned_on="2026-08-03"),
            world["ops_headers"],
        ),
        ApiErrorId.ERR_CHEF_NOT_CERTIFIED.value,
        422,
    )

    log_training(world["chef_id"], hours=12)
    promoted = validate_success(api.get_chef(world["chef_id"], world["ops_headers"]))
    assert promoted["status"] == CHEF_CERTIFIED
    assert promoted["training_hours_logged"] == 24

    opened = validate_success(
        api.commission_kiosk(
            world["kiosk_id"],
            commission_payload(commissioned_on="2026-08-03"),
            world["ops_headers"],
        )
    )
    assert opened["operational_state"] == KIOSK_OPERATING
    assert opened["commissioned_on"] == "2026-08-03"
    assert opened["lead_chef_id"] == world["chef_id"]
    assert opened["certified_chef_count"] == 1
    assert opened["daily_pack_cap"] == 180
    assert opened["sanitation_posture"] == POSTURE_CLEAR

    agreement = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert agreement["active_kiosk_count"] == 1


def test_a_single_critical_finding_locks_planning_out_of_an_operating_kiosk(api):
    """Ten risk points would only mean WATCH, but the critical override says LOCKDOWN.

    "If `open_critical_finding_count` is greater than zero the posture is `LOCKDOWN`,
    whatever the total says."

    Design: Difficulty/cross_entity_state_dependency/plan_creation_blocked_by_lockdown_posture_rejected
    """
    world = base_world()
    add_submitted_audit(world, severities=(SEVERITY_CRITICAL,), codes=CRITICAL_CODES)

    locked = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert locked["open_critical_finding_count"] == 1
    assert locked["risk_points"] == 10
    assert locked["sanitation_posture"] == POSTURE_LOCKDOWN
    assert locked["operational_state"] == KIOSK_OPERATING

    validate_error(
        api.create_production_plan(
            production_plan_payload(world["kiosk_id"], locked["version"]),
            world["chef_headers"],
        ),
        ApiErrorId.ERR_KIOSK_POSTURE_LOCKDOWN.value,
        422,
    )
    validate_list(
        api.list_production_plans(world["ops_headers"], {"kiosk_id": world["kiosk_id"]}),
        expected_total=0,
    )


def test_passing_reverification_reopens_planning_at_the_same_kiosk(api):
    """Clearing the critical finding is the only route back to a plannable kiosk.

    "The kiosk's posture is then re-derived from the reduced total, which is how a
    kiosk in `LOCKDOWN` with no remaining open critical findings returns to
    `RESTRICTED`, `WATCH` or `CLEAR`."

    Design: Difficulty/cross_entity_state_dependency/plan_creation_blocked_by_lockdown_posture_rejected
    """
    world = base_world()
    submitted = add_submitted_audit(
        world, severities=(SEVERITY_CRITICAL,), codes=CRITICAL_CODES
    )
    add_reverification_request(world, submitted["audit_id"], submitted["findings"])
    verify_audit(world, submitted["audit_id"])

    cleared = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert cleared["open_critical_finding_count"] == 0
    assert cleared["risk_points"] == 0
    assert cleared["sanitation_posture"] == POSTURE_CLEAR

    plan = validate_success(
        api.create_production_plan(
            production_plan_payload(world["kiosk_id"], cleared["version"]),
            world["chef_headers"],
        ),
        201,
    )
    assert plan["binding_cap_source"] == CAP_SOURCE_DEMAND
    assert plan["planned_pack_count"] == 162
    assert_close(plan["posture_factor_applied"], 1.00, places=2)
    assert_close(plan["planned_rice_kg"], 19.44, places=2)


def test_a_suspended_register_link_blocks_the_feed_it_had_already_accepted(api):
    """The integration state is read at reconcile time, not at submit time.

    "It requires the host store's `pos_integration_status` to be `CONNECTED` — a store
    that never completed integration, or whose integration is disconnected, gets
    `ERR_POS_NOT_CONNECTED`."

    Design: Difficulty/cross_entity_state_dependency/pos_feed_reconcile_blocked_by_disconnected_host_store_rejected
    """
    world = base_world()
    feed = add_submitted_feed(world)
    assert feed["status"] == FEED_SUBMITTED

    dropped = connect_pos(world["host_store_id"], pos_integration_status=POS_SUSPENDED)
    assert dropped["pos_integration_status"] == POS_SUSPENDED

    validate_error(
        api.reconcile_pos_sales_feed(feed["id"], world["ops_headers"]),
        ApiErrorId.ERR_POS_NOT_CONNECTED.value,
        422,
    )
    unreconciled = validate_success(
        api.get_pos_sales_feed(feed["id"], world["ops_headers"])
    )
    assert unreconciled["status"] == FEED_SUBMITTED
    assert unreconciled["reconciled_unit_total"] == 0

    statement = add_draft_statement(world)
    assert statement["gross_sales_cents"] == 0
    assert statement["binding_share_cents"] == 0


def test_restoring_the_register_link_lets_the_same_feed_reconcile(api):
    """Nothing about the extract changes; only the parent store's integration does.

    "The first is the register link: the manager sets `pos_integration_status` to
    `NOT_CONNECTED`, `CONNECTED` or `SUSPENDED` and reports how many lanes are wired
    to the kiosk in `pos_terminal_count`."

    Design: Difficulty/cross_entity_state_dependency/pos_feed_reconcile_blocked_by_disconnected_host_store_rejected
    """
    world = base_world()
    feed = add_submitted_feed(world)
    connect_pos(world["host_store_id"], pos_integration_status=POS_SUSPENDED)
    validate_error(
        api.reconcile_pos_sales_feed(feed["id"], world["ops_headers"]),
        ApiErrorId.ERR_POS_NOT_CONNECTED.value,
        422,
    )

    restored = connect_pos(world["host_store_id"], pos_integration_status=POS_CONNECTED)
    assert restored["pos_integration_status"] == POS_CONNECTED

    reconciled = validate_success(
        api.reconcile_pos_sales_feed(feed["id"], world["ops_headers"])
    )
    assert reconciled["status"] == FEED_RECONCILED
    assert reconciled["reconciled_unit_total"] == 0

    statement = add_draft_statement(world)
    assert statement["gross_sales_cents"] == 2400000
    assert statement["binding_share_cents"] == 296000
