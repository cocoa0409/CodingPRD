"""Metrics sitting exactly on their limits, and one increment past them."""

from test_helpers import (
    ApiErrorId,
    BATCH_APPROVED,
    BATCH_REJECTED,
    BATCH_VARIANCE_REQUIRED,
    FISH_QUARANTINED,
    FISH_RECEIVED,
    FISH_RELEASED,
    OPS_ISSUER_ID,
    POSTURE_CLEAR,
    QUARANTINE_REASON_COLD_CHAIN_BREACH,
    REJECTION_TTC_HARD_FAIL,
    SETTLEMENT_DRAFT,
    SETTLEMENT_ISSUED,
    acidification_reading_payload,
    add_cold_chain_readings,
    add_draft_statement,
    add_mixing_rice_batch,
    add_received_fish_lot,
    add_reconciled_feed,
    add_rejected_feed,
    add_released_plan,
    assert_close,
    base_world,
    validate_error,
    validate_list,
    validate_success,
    variance_request_payload,
)

FOUR_HOUR_HOLD = {
    "hold_start_at": "2026-08-03T07:00:00Z",
    "hold_end_at": "2026-08-03T11:00:00Z",
}
AT_THE_LIMITS = {
    "measured_ph": 4.20,
    "ph_measured_at": "2026-08-03T11:00:00Z",
    "max_temp_c": 21.0,
}
SEVEN_OCLOCK_RECEIPT = {"received_at": "2026-08-03T07:00:00Z"}


def test_all_three_acidification_parameters_pass_sitting_exactly_on_their_limits(api):
    """A four-hour hold at 21.0 degrees and pH 4.20 is approved without a variance.

    "the pH passes when `measured_ph` is at most 4.20, so exactly 4.20 passes; the
    time passes when `exposure_minutes` is at most 240 minutes, so exactly 240
    passes; and the temperature passes when `max_temp_c` is at most 21.0 degrees
    Celsius, so exactly 21.0 passes."

    Design: Difficulty/boundary_precision_check/rice_ph_exactly_at_limit_passes
    """
    world = base_world()
    plan = add_released_plan(world)
    batch = add_mixing_rice_batch(world, plan["id"], **FOUR_HOUR_HOLD)
    assert batch["max_pack_yield"] == 180

    validate_success(
        api.record_acidification_reading(
            batch["id"],
            acidification_reading_payload(**AT_THE_LIMITS),
            world["chef_headers"],
        )
    )
    verified = validate_success(api.verify_ttc(batch["id"], world["chef_headers"]))
    assert verified["status"] == BATCH_APPROVED
    assert verified["exposure_minutes"] == 240
    assert verified["rejection_reason"] is None

    unpenalised = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert unpenalised["risk_points"] == 0
    assert unpenalised["sanitation_posture"] == POSTURE_CLEAR


def test_a_hundredth_of_ph_or_one_extra_minute_demands_a_documented_variance(api):
    """Either single parameter one step out of spec lands in VARIANCE_REQUIRED.

    "When the pH is the *only* failing parameter and it is still at most 4.60 — the
    documentable ceiling — with both time and temperature in spec, the batch moves
    `ACIDIFYING → VARIANCE_REQUIRED`."

    Design: Difficulty/boundary_precision_check/rice_ph_exactly_at_limit_passes
    """
    world = base_world()
    plan = add_released_plan(world)

    sour = add_mixing_rice_batch(
        world,
        plan["id"],
        hold_start_at="2026-08-03T02:00:00Z",
        hold_end_at="2026-08-03T06:00:00Z",
    )
    validate_success(
        api.record_acidification_reading(
            sour["id"],
            acidification_reading_payload(
                measured_ph=4.21,
                ph_measured_at="2026-08-03T06:00:00Z",
                max_temp_c=21.0,
            ),
            world["chef_headers"],
        )
    )
    ph_documentable = validate_success(api.verify_ttc(sour["id"], world["chef_headers"]))
    assert ph_documentable["status"] == BATCH_VARIANCE_REQUIRED
    assert ph_documentable["exposure_minutes"] == 240

    slow = add_mixing_rice_batch(
        world,
        plan["id"],
        hold_start_at="2026-08-03T06:00:00Z",
        hold_end_at="2026-08-03T10:01:00Z",
    )
    validate_success(
        api.record_acidification_reading(
            slow["id"],
            acidification_reading_payload(
                measured_ph=4.20,
                ph_measured_at="2026-08-03T10:01:00Z",
                max_temp_c=21.0,
            ),
            world["chef_headers"],
        )
    )
    time_documentable = validate_success(api.verify_ttc(slow["id"], world["chef_headers"]))
    assert time_documentable["status"] == BATCH_VARIANCE_REQUIRED
    assert time_documentable["exposure_minutes"] == 241
    assert time_documentable["rejection_reason"] is None


def test_a_tenth_of_a_degree_of_excursion_is_never_documentable(api):
    """21.1 degrees hard-fails the batch even with pH and time exactly in spec.

    "In every other case the batch moves `ACIDIFYING → REJECTED` with
    `rejection_reason` `TTC_HARD_FAIL`: a pH above the documentable ceiling, any
    temperature excursion at all, or more than one failing parameter
    simultaneously."

    Design: Difficulty/boundary_precision_check/rice_ph_exactly_at_limit_passes
    """
    world = base_world()
    plan = add_released_plan(world)
    batch = add_mixing_rice_batch(world, plan["id"], **FOUR_HOUR_HOLD)
    validate_success(
        api.record_acidification_reading(
            batch["id"],
            acidification_reading_payload(
                measured_ph=4.20,
                ph_measured_at="2026-08-03T11:00:00Z",
                max_temp_c=21.1,
            ),
            world["chef_headers"],
        )
    )
    hard_failed = validate_success(api.verify_ttc(batch["id"], world["chef_headers"]))
    assert hard_failed["status"] == BATCH_REJECTED
    assert hard_failed["rejection_reason"] == REJECTION_TTC_HARD_FAIL
    assert hard_failed["exposure_minutes"] == 240

    validate_error(
        api.request_variance(
            batch["id"],
            variance_request_payload(documented_ph=4.20, documented_hold_minutes=240),
            world["chef_headers"],
        ),
        ApiErrorId.ERR_RICE_BATCH_INVALID_STATE.value,
        409,
    )


def test_exactly_thirty_breach_minutes_leaves_the_lot_receivable(api):
    """A ten-minute half-breach and a twenty-minute whole one land on the limit itself.

    "A total strictly greater than 30 minutes moves the lot to `QUARANTINED` with
    `quarantine_reason` `COLD_CHAIN_BREACH` and adds six risk points to the kiosk
    before re-deriving its posture; a total of exactly 30 minutes does not
    quarantine."

    Design: Difficulty/boundary_precision_check/cold_chain_exactly_at_quarantine_limit_stays_received
    """
    world = base_world()
    lot = add_received_fish_lot(world, **SEVEN_OCLOCK_RECEIPT)
    readings = add_cold_chain_readings(
        world,
        lot["id"],
        [("2026-08-03T07:20:00Z", 5.0), ("2026-08-03T07:40:00Z", 6.0)],
    )
    assert readings[0]["breach_minutes_attributed"] == 10
    assert readings[0]["interval_minutes_from_previous"] is None
    assert readings[1]["breach_minutes_attributed"] == 20
    assert readings[1]["interval_minutes_from_previous"] == 20
    assert readings[1]["lot_breach_minutes_after"] == 30

    on_the_limit = validate_success(api.get_fish_lot(lot["id"], world["ops_headers"]))
    assert on_the_limit["cold_chain_breach_minutes"] == 30
    assert on_the_limit["status"] == FISH_RECEIVED
    assert on_the_limit["quarantine_reason"] is None

    unpenalised = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert unpenalised["risk_points"] == 0
    assert unpenalised["sanitation_posture"] == POSTURE_CLEAR

    released = validate_success(
        api.release_fish_lot(lot["id"], world["auditor_headers"])
    )
    assert released["status"] == FISH_RELEASED
    assert released["cold_chain_breach_minutes"] == 30
    assert_close(released["remaining_kg"], 12.000, places=3)


def test_one_further_breaching_minute_tips_the_lot_into_quarantine(api):
    """The boundary is one minute wide: thirty-one minutes quarantines and costs six points.

    "one point for each of the kiosk's audit findings of severity `MINOR` whose
    `status` is `OPEN` or `CORRECTED` … six points for each of the kiosk's fish lots
    currently `QUARANTINED` with `quarantine_reason` `COLD_CHAIN_BREACH`"

    Design: Difficulty/boundary_precision_check/cold_chain_exactly_at_quarantine_limit_stays_received
    """
    world = base_world()
    lot = add_received_fish_lot(world, **SEVEN_OCLOCK_RECEIPT)
    add_cold_chain_readings(
        world,
        lot["id"],
        [("2026-08-03T07:20:00Z", 5.0), ("2026-08-03T07:40:00Z", 6.0)],
    )

    tipping = add_cold_chain_readings(
        world, lot["id"], [("2026-08-03T07:41:00Z", 6.0)]
    )
    assert tipping[0]["interval_minutes_from_previous"] == 1
    assert tipping[0]["breach_minutes_attributed"] == 1
    assert tipping[0]["lot_breach_minutes_after"] == 31

    quarantined = validate_success(api.get_fish_lot(lot["id"], world["ops_headers"]))
    assert quarantined["cold_chain_breach_minutes"] == 31
    assert quarantined["status"] == FISH_QUARANTINED
    assert quarantined["quarantine_reason"] == QUARANTINE_REASON_COLD_CHAIN_BREACH

    charged = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert charged["risk_points"] == 6
    assert charged["sanitation_posture"] == POSTURE_CLEAR

    validate_error(
        api.release_fish_lot(lot["id"], world["auditor_headers"]),
        ApiErrorId.ERR_COLD_CHAIN_BREACH_BLOCKS_RELEASE.value,
        422,
    )
    validate_list(
        api.list_cold_chain_readings(lot["id"], world["ops_headers"]), expected_total=3
    )


def test_a_rejected_register_day_leaves_the_period_with_nothing_to_settle(api):
    """One feed exists for the date, but a rejected one contributes exactly zero.

    "It requires the statement to be `DRAFT`, requires at least one `RECONCILED` feed
    inside the closed period — a period with no settleable sales is refused with
    `ERR_NO_SETTLEABLE_SALES`"

    Design: Difficulty/boundary_precision_check/settlement_issue_with_empty_reconciled_feed_set_rejected
    """
    world = base_world()
    add_rejected_feed(world)
    statement = add_draft_statement(world)
    assert statement["gross_sales_cents"] == 0
    assert statement["binding_share_cents"] == 0
    assert statement["net_due_cents"] == 0

    validate_error(
        api.issue_settlement_statement(statement["id"], world["ops_issuer_headers"]),
        ApiErrorId.ERR_NO_SETTLEABLE_SALES.value,
        422,
    )
    unissued = validate_success(
        api.get_settlement_statement(statement["id"], world["ops_headers"])
    )
    assert unissued["status"] == SETTLEMENT_DRAFT
    assert unissued["issued_by_user_id"] is None

    unbooked = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert unbooked["lifetime_share_accrued_cents"] == 0


def test_a_single_reconciled_day_carries_the_period_over_the_cardinality_line(api):
    """Taking the reconciled input set from zero rows to one makes the issue succeed.

    "a rejected feed contributes exactly zero to any settlement, yet it still counts
    as a terminal feed for the purposes of the plan-reconciliation precondition in
    §3.4, so a bad register day does not strand its production plan forever."

    Design: Difficulty/boundary_precision_check/settlement_issue_with_empty_reconciled_feed_set_rejected
    """
    world = base_world()
    add_rejected_feed(world)
    empty_period = add_draft_statement(world)
    assert empty_period["binding_share_cents"] == 0

    add_reconciled_feed(world)
    settleable = add_draft_statement(world)
    assert settleable["superseded_statement_id"] == empty_period["id"]
    assert settleable["gross_sales_cents"] == 2400000
    assert settleable["binding_share_cents"] == 296000

    issued = validate_success(
        api.issue_settlement_statement(settleable["id"], world["ops_issuer_headers"])
    )
    assert issued["status"] == SETTLEMENT_ISSUED
    assert issued["issued_by_user_id"] == OPS_ISSUER_ID
    assert issued["binding_share_cents"] == 296000

    booked = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert booked["lifetime_share_accrued_cents"] == 296000
