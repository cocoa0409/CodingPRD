"""Named refusals from the error catalogue, each with its own precondition."""

from test_helpers import (
    AUDITOR_OPENER_ID,
    AUDIT_CORRECTIVE_ACTION_PENDING,
    AUDIT_IN_PROGRESS,
    AUDIT_REVERIFICATION,
    AUDIT_SCHEDULED,
    ApiErrorId,
    BATCH_APPROVED,
    BATCH_VARIANCE_APPROVED,
    BATCH_VARIANCE_PENDING,
    BATCH_VARIANCE_REQUIRED,
    FEED_RECONCILED,
    FEED_SUBMITTED,
    FINDING_CORRECTED,
    FINDING_OPEN,
    FINDING_WAIVED,
    PACK_ON_SHELF,
    POSTURE_CLEAR,
    POSTURE_LOCKDOWN,
    POS_CONNECTED,
    POS_SUSPENDED,
    SETTLEMENT_ACKNOWLEDGED,
    SETTLEMENT_PAID,
    SEVERITY_CRITICAL,
    SEVERITY_MAJOR,
    SEVERITY_MINOR,
    acidification_reading_payload,
    add_mixing_rice_batch,
    add_released_plan,
    add_submitted_audit,
    add_submitted_feed,
    assert_close,
    assert_instant_equals,
    audit_payload,
    base_world,
    clock_payload,
    correction_payload,
    feed_rejection_payload,
    find_by_id,
    pack_lot_payload,
    payment_payload,
    pos_integration_payload,
    pos_sales_feed_payload,
    production_plan_payload,
    settled_world,
    shelf_ready_world,
    validate_error,
    validate_list,
    validate_success,
    variance_decision_payload,
    variance_request_payload,
    waiver_payload,
)


def test_settlement_payment_must_equal_the_net_amount_due(api):
    """Under- and over-payment are refused alike; only the exact cent closes the bill.

    "The amount must equal `net_due_cents` exactly — under- and over-payment are
    equally refused with `ERR_PAYMENT_AMOUNT_MISMATCH`, and a statement whose net
    due is zero must be paid with exactly zero."

    Design: Corner/errors/error_payment_amount_mismatch_on_pay_rejected
    """
    world = settled_world()
    validate_success(
        api.issue_settlement_statement(
            world["statement_id"], world["ops_issuer_headers"]
        )
    )
    validate_success(
        api.acknowledge_settlement_statement(
            world["statement_id"], world["manager_headers"]
        )
    )
    accrued = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert accrued["lifetime_share_accrued_cents"] == 296000

    validate_error(
        api.pay_settlement_statement(
            world["statement_id"], payment_payload(296001), world["manager_headers"]
        ),
        ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value,
        422,
    )
    validate_error(
        api.pay_settlement_statement(
            world["statement_id"], payment_payload(295999), world["manager_headers"]
        ),
        ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value,
        422,
    )

    unpaid = validate_success(
        api.get_settlement_statement(world["statement_id"], world["ops_headers"])
    )
    assert unpaid["status"] == SETTLEMENT_ACKNOWLEDGED
    assert unpaid["paid_amount_cents"] is None
    assert unpaid["paid_at"] is None
    assert unpaid["net_due_cents"] == 296000

    paid = validate_success(
        api.pay_settlement_statement(
            world["statement_id"], payment_payload(296000), world["manager_headers"]
        )
    )
    assert paid["status"] == SETTLEMENT_PAID
    assert paid["paid_amount_cents"] == 296000
    assert_instant_equals(paid["paid_at"], "2026-08-03T10:00:00Z")

    settled = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert settled["lifetime_share_accrued_cents"] == 296000


def test_only_minor_findings_may_be_waived(api):
    """Waivers are severity-gated and a refused waiver moves no risk at all.

    "Waivers are restricted to trivia: only `MINOR` findings are waivable, and
    attempting to waive a `MAJOR` or `CRITICAL` finding is refused with
    `ERR_FINDING_NOT_WAIVABLE`."

    Design: Corner/errors/error_finding_not_waivable_for_major_severity_rejected
    """
    world = base_world()
    submitted = add_submitted_audit(
        world,
        severities=(SEVERITY_MINOR, SEVERITY_MAJOR, SEVERITY_CRITICAL),
        codes=["FS-LABEL-WEAR", "FS-SANITISER-CONCENTRATION", "FS-CASE-TEMP-LOG"],
    )
    audit_id = submitted["audit_id"]
    minor, major, critical = submitted["findings"]
    assert submitted["audit"]["status"] == AUDIT_CORRECTIVE_ACTION_PENDING

    loaded = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert loaded["risk_points"] == 15
    assert loaded["sanitation_posture"] == POSTURE_LOCKDOWN

    validate_error(
        api.waive_finding(
            audit_id, major["id"], waiver_payload(), world["auditor_headers"]
        ),
        ApiErrorId.ERR_FINDING_NOT_WAIVABLE.value,
        422,
    )
    validate_error(
        api.waive_finding(
            audit_id, critical["id"], waiver_payload(), world["auditor_headers"]
        ),
        ApiErrorId.ERR_FINDING_NOT_WAIVABLE.value,
        422,
    )

    findings = validate_list(
        api.list_findings(audit_id, world["auditor_headers"]), expected_total=3
    )
    stubborn = find_by_id(findings, major["id"])
    assert stubborn["status"] == FINDING_OPEN
    assert stubborn["waiver_rationale"] is None
    assert find_by_id(findings, critical["id"])["status"] == FINDING_OPEN

    held = validate_success(api.get_audit(audit_id, world["auditor_headers"]))
    assert held["open_finding_count"] == 3
    unchanged = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert unchanged["risk_points"] == 15

    validate_success(
        api.waive_finding(
            audit_id, minor["id"], waiver_payload(), world["auditor_headers"]
        )
    )
    waived = find_by_id(
        validate_list(api.list_findings(audit_id, world["auditor_headers"])),
        minor["id"],
    )
    assert waived["status"] == FINDING_WAIVED

    after = validate_success(api.get_audit(audit_id, world["auditor_headers"]))
    assert after["open_finding_count"] == 2
    lighter = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert lighter["risk_points"] == 14
    assert lighter["sanitation_posture"] == POSTURE_LOCKDOWN


def test_a_second_live_feed_for_the_same_business_date_is_refused(api):
    """Uniqueness is per store and date over live feeds, and a rejection frees the date.

    "Only one feed may exist per store and date unless the earlier one was
    rejected: a second submission while a `SUBMITTED` or `RECONCILED` feed already
    covers that date is refused with `ERR_DUPLICATE_FEED_FOR_DATE`, while a
    `REJECTED` feed leaves the date open for resubmission."

    Design: Corner/errors/error_duplicate_feed_for_date_rejected
    """
    world = base_world()
    first = add_submitted_feed(world)

    validate_error(
        api.create_pos_sales_feed(
            pos_sales_feed_payload(
                world["host_store_id"],
                gross_sales_cents=1000000,
                markdown_sales_cents=0,
                full_price_units=80,
                markdown_units=0,
            ),
            world["manager_headers"],
        ),
        ApiErrorId.ERR_DUPLICATE_FEED_FOR_DATE.value,
        422,
    )

    same_date = api.list_pos_sales_feeds(
        world["ops_headers"],
        {"host_store_id": world["host_store_id"], "business_date": "2026-08-03"},
    )
    validate_list(same_date, expected_total=1)
    intact = validate_success(api.get_pos_sales_feed(first["id"], world["ops_headers"]))
    assert intact["gross_sales_cents"] == 2400000
    assert intact["status"] == FEED_SUBMITTED

    earlier_day = validate_success(
        api.create_pos_sales_feed(
            pos_sales_feed_payload(world["host_store_id"], business_date="2026-08-02"),
            world["manager_headers"],
        ),
        201,
    )
    assert earlier_day["business_date"] == "2026-08-02"

    validate_success(
        api.reject_pos_sales_feed(
            first["id"], feed_rejection_payload(), world["ops_headers"]
        )
    )
    resubmitted = validate_success(
        api.create_pos_sales_feed(
            pos_sales_feed_payload(world["host_store_id"]),
            world["manager_headers"],
        ),
        201,
    )
    assert resubmitted["status"] == FEED_SUBMITTED
    assert resubmitted["business_date"] == "2026-08-03"


def test_reconciliation_reads_the_integration_status_at_reconcile_time(api):
    """A feed accepted while the register was linked still fails once the link drops.

    "It requires the host store's `pos_integration_status` to be `CONNECTED` — a
    store that never completed integration, or whose integration is disconnected,
    gets `ERR_POS_NOT_CONNECTED`."

    Design: Corner/errors/error_pos_not_connected_on_reconcile_rejected
    """
    world = base_world()
    feed = add_submitted_feed(world)

    validate_success(
        api.set_pos_integration(
            world["host_store_id"],
            pos_integration_payload(pos_integration_status=POS_SUSPENDED),
            world["manager_headers"],
        )
    )
    dropped = validate_success(
        api.get_host_store(world["host_store_id"], world["ops_headers"])
    )
    assert dropped["pos_integration_status"] == POS_SUSPENDED

    validate_error(
        api.reconcile_pos_sales_feed(feed["id"], world["ops_headers"]),
        ApiErrorId.ERR_POS_NOT_CONNECTED.value,
        422,
    )
    stalled = validate_success(api.get_pos_sales_feed(feed["id"], world["ops_headers"]))
    assert stalled["status"] == FEED_SUBMITTED
    assert stalled["reconciled_unit_total"] == 0

    validate_success(
        api.set_pos_integration(
            world["host_store_id"],
            pos_integration_payload(pos_integration_status=POS_CONNECTED),
            world["manager_headers"],
        )
    )
    reconciled = validate_success(
        api.reconcile_pos_sales_feed(feed["id"], world["ops_headers"])
    )
    assert reconciled["status"] == FEED_RECONCILED

    never_linked = base_world(
        suffix="B", connect=False, activate=False, place=False, commission=False
    )
    validate_error(
        api.create_pos_sales_feed(
            pos_sales_feed_payload(never_linked["host_store_id"]),
            never_linked["manager_headers"],
        ),
        ApiErrorId.ERR_POS_NOT_CONNECTED.value,
        422,
    )


def test_an_audit_cannot_be_started_before_the_date_it_was_scheduled_for(api):
    """The start edge is gated on the logical clock reaching the scheduled date.

    "Starting the audit opens it for finding entry, requires the logical clock to
    be at or after `scheduled_for` — starting early is refused with
    `ERR_AUDIT_NOT_YET_DUE`, while starting exactly on the scheduled date is
    allowed."

    Design: Corner/errors/error_audit_not_yet_due_on_start_rejected
    """
    world = base_world()
    audit = validate_success(
        api.create_audit(
            audit_payload(world["kiosk_id"], scheduled_for="2026-08-04"),
            world["auditor_headers"],
        ),
        201,
    )
    assert audit["status"] == AUDIT_SCHEDULED
    assert audit["round_count"] == 0
    assert audit["score"] == 100
    assert audit["opened_by_user_id"] is None

    validate_error(
        api.start_audit(audit["id"], world["auditor_headers"]),
        ApiErrorId.ERR_AUDIT_NOT_YET_DUE.value,
        422,
    )
    waiting = validate_success(api.get_audit(audit["id"], world["auditor_headers"]))
    assert waiting["status"] == AUDIT_SCHEDULED
    assert waiting["opened_by_user_id"] is None
    kiosk = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert kiosk["risk_points"] == 0
    assert kiosk["sanitation_posture"] == POSTURE_CLEAR

    validate_success(
        api.set_clock(clock_payload("2026-08-04T09:00:00Z"), world["ops_headers"])
    )
    started = validate_success(api.start_audit(audit["id"], world["auditor_headers"]))
    assert started["status"] == AUDIT_IN_PROGRESS
    assert started["opened_by_user_id"] == AUDITOR_OPENER_ID


def test_pack_lot_needs_enough_fish_mass_left_in_the_source_lot(api):
    """The fish gate is independent of the rice yield gate.

    "For every line the … a fish allocation may not exceed the source lot's
    remaining mass." The build debits "`pack_count` multiplied by 0.045 kilograms
    of fish per pack, rounded half up to three decimal places" from the lot.

    Design: Corner/errors/error_insufficient_fish_inventory_on_pack_lot_rejected
    """
    world = shelf_ready_world(lot_overrides={"net_weight_kg": 4.0})
    batch = validate_success(
        api.get_rice_batch(world["rice_batch_id"], world["ops_headers"])
    )
    assert batch["max_pack_yield"] == 180

    validate_error(
        api.create_pack_lot(
            pack_lot_payload(
                world["rice_batch_id"], world["fish_lot_id"], pack_count=100
            ),
            world["chef_headers"],
        ),
        ApiErrorId.ERR_INSUFFICIENT_FISH_INVENTORY.value,
        422,
    )

    untouched = validate_success(
        api.get_fish_lot(world["fish_lot_id"], world["ops_headers"])
    )
    assert_close(untouched["allocated_kg"], 0.0)
    assert_close(untouched["remaining_kg"], 4.0)
    spared = validate_success(
        api.get_rice_batch(world["rice_batch_id"], world["ops_headers"])
    )
    assert spared["status"] == BATCH_APPROVED
    plan = validate_success(
        api.get_production_plan(world["plan_id"], world["ops_headers"])
    )
    assert plan["actual_pack_count"] == 0

    affordable = validate_success(
        api.create_pack_lot(
            pack_lot_payload(
                world["rice_batch_id"], world["fish_lot_id"], pack_count=88
            ),
            world["chef_headers"],
        ),
        201,
    )
    assert affordable["status"] == PACK_ON_SHELF
    assert_close(affordable["consumed_fish_kg"], 3.960)

    drained = validate_success(
        api.get_fish_lot(world["fish_lot_id"], world["ops_headers"])
    )
    assert_close(drained["allocated_kg"], 3.960)
    assert_close(drained["remaining_kg"], 0.040)


def test_one_open_finding_blocks_the_reverification_request(api):
    """Reverification needs a zero open count, and a corrected finding keeps its risk.

    "Every finding of the audit must be `CORRECTED` or `WAIVED`; a single
    still-`OPEN` finding blocks the request with
    `ERR_OPEN_FINDINGS_BLOCK_REVERIFICATION`." Correcting one "does *not* remove
    its `risk_points` from the kiosk."

    Design: Corner/errors/error_open_findings_block_reverification_rejected
    """
    world = base_world()
    submitted = add_submitted_audit(
        world,
        severities=(SEVERITY_MAJOR, SEVERITY_MAJOR),
        codes=["FS-CASE-TEMP-LOG", "FS-SANITISER-CONCENTRATION"],
    )
    audit_id = submitted["audit_id"]
    first, second = submitted["findings"]

    validate_success(
        api.correct_finding(
            audit_id, first["id"], correction_payload(), world["manager_headers"]
        )
    )

    validate_error(
        api.request_reverification(audit_id, world["manager_headers"]),
        ApiErrorId.ERR_OPEN_FINDINGS_BLOCK_REVERIFICATION.value,
        422,
    )

    blocked = validate_success(api.get_audit(audit_id, world["auditor_headers"]))
    assert blocked["status"] == AUDIT_CORRECTIVE_ACTION_PENDING
    assert blocked["round_count"] == 0
    assert blocked["open_finding_count"] == 1

    findings = validate_list(
        api.list_findings(audit_id, world["auditor_headers"]), expected_total=2
    )
    assert find_by_id(findings, first["id"])["status"] == FINDING_CORRECTED
    assert find_by_id(findings, second["id"])["status"] == FINDING_OPEN

    kiosk = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert kiosk["risk_points"] == 8

    validate_success(
        api.correct_finding(
            audit_id, second["id"], correction_payload(), world["manager_headers"]
        )
    )
    requested = validate_success(
        api.request_reverification(audit_id, world["manager_headers"])
    )
    assert requested["status"] == AUDIT_REVERIFICATION
    assert requested["round_count"] == 1
    assert requested["open_finding_count"] == 0


def test_documented_variance_above_the_documentable_band_cannot_be_approved(api):
    """Approval is the rung where the documented pH and hold time are measured.

    "Approval additionally requires the documented figures to stay inside the
    documentable band: `documented_ph` must be at most 4.60 and
    `documented_hold_minutes` must be at most 240, and a filing that breaches
    either is refused with `ERR_VARIANCE_PH_ABOVE_CEILING`."

    Design: Corner/errors/error_variance_ph_above_ceiling_rejected
    """
    world = base_world()
    plan = add_released_plan(world)

    def file_variance(hold_start_at, hold_end_at, **variance):
        batch = add_mixing_rice_batch(
            world, plan["id"], hold_start_at=hold_start_at, hold_end_at=hold_end_at
        )
        validate_success(
            api.record_acidification_reading(
                batch["id"],
                acidification_reading_payload(measured_ph=4.35),
                world["chef_headers"],
            )
        )
        documentable = validate_success(
            api.verify_ttc(batch["id"], world["chef_headers"])
        )
        assert documentable["status"] == BATCH_VARIANCE_REQUIRED
        filed = validate_success(
            api.request_variance(
                batch["id"], variance_request_payload(**variance), world["chef_headers"]
            )
        )
        assert filed["status"] == BATCH_VARIANCE_PENDING
        return batch["id"]

    too_acidic = file_variance(
        "2026-08-03T05:00:00Z", "2026-08-03T07:00:00Z", documented_ph=4.7
    )
    validate_error(
        api.decide_variance(
            too_acidic, variance_decision_payload(), world["auditor_headers"]
        ),
        ApiErrorId.ERR_VARIANCE_PH_ABOVE_CEILING.value,
        422,
    )
    pending = validate_success(api.get_rice_batch(too_acidic, world["ops_headers"]))
    assert pending["status"] == BATCH_VARIANCE_PENDING
    assert pending["variance_submitted_by_chef_id"] == world["chef_id"]
    quiet = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert quiet["risk_points"] == 0

    too_long = file_variance(
        "2026-08-03T07:00:00Z",
        "2026-08-03T09:00:00Z",
        documented_ph=4.6,
        documented_hold_minutes=400,
    )
    validate_error(
        api.decide_variance(
            too_long, variance_decision_payload(), world["auditor_headers"]
        ),
        ApiErrorId.ERR_VARIANCE_PH_ABOVE_CEILING.value,
        422,
    )

    at_the_ceiling = file_variance(
        "2026-08-03T09:00:00Z",
        "2026-08-03T11:00:00Z",
        documented_ph=4.6,
        documented_hold_minutes=240,
    )
    approved = validate_success(
        api.decide_variance(
            at_the_ceiling, variance_decision_payload(), world["auditor_headers"]
        )
    )
    assert approved["status"] == BATCH_VARIANCE_APPROVED
    assert approved["variance_reviewed_by_user_id"] == AUDITOR_OPENER_ID
    priced = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert priced["risk_points"] == 3


def test_production_date_must_fall_inside_the_agreement_term(api):
    """The term is closed at both ends and a date outside it is refused, not clamped.

    "The `production_date` must fall inside the agreement's closed term, from
    `effective_from` through `effective_to` inclusive; a date outside it is refused
    with `ERR_PLAN_DATE_OUTSIDE_AGREEMENT`."

    Design: Corner/errors/error_plan_date_outside_agreement_rejected
    """
    world = base_world()
    kiosk = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    opening_version = kiosk["version"]

    validate_error(
        api.create_production_plan(
            production_plan_payload(
                world["kiosk_id"], opening_version, production_date="2027-08-01"
            ),
            world["chef_headers"],
        ),
        ApiErrorId.ERR_PLAN_DATE_OUTSIDE_AGREEMENT.value,
        422,
    )
    validate_error(
        api.create_production_plan(
            production_plan_payload(
                world["kiosk_id"], opening_version, production_date="2026-07-31"
            ),
            world["chef_headers"],
        ),
        ApiErrorId.ERR_PLAN_DATE_OUTSIDE_AGREEMENT.value,
        422,
    )

    validate_list(
        api.list_production_plans(
            world["ops_headers"], {"kiosk_id": world["kiosk_id"]}
        ),
        expected_total=0,
    )
    unspent = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert unspent["version"] == opening_version

    last_day = validate_success(
        api.create_production_plan(
            production_plan_payload(
                world["kiosk_id"], opening_version, production_date="2027-07-31"
            ),
            world["chef_headers"],
        ),
        201,
    )
    assert last_day["production_date"] == "2027-07-31"
    bumped = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert bumped["version"] == opening_version + 1
