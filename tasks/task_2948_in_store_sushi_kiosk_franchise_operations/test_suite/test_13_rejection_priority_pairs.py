"""Requests that break two rules at once, where only the higher rung is reported."""

from test_helpers import (
    ApiErrorId,
    BATCH_APPROVED,
    BATCH_REJECTED,
    FISH_RELEASED,
    PACK_ON_SHELF,
    REJECTION_TTC_HARD_FAIL,
    SETTLEMENT_DRAFT,
    SETTLEMENT_VOID,
    acidification_reading_payload,
    add_approved_rice_batch,
    add_draft_statement,
    add_mixing_rice_batch,
    add_reconciled_feed,
    add_released_fish_lot,
    add_released_plan,
    assert_close,
    base_world,
    pack_lot_payload,
    settlement_void_payload,
    validate_error,
    validate_list,
    validate_success,
)

OTHER_SUPPLIER = "SUP-9931"
TRIGGER_PRODUCED_AT = "2026-08-03T09:00:00Z"


def test_a_superseded_draft_reports_its_void_state_not_its_missing_sales(api):
    """A period with no register day at all still answers with the 409, not the 422.

    "**state beats fiscal**: issuing a settlement statement that is `VOID` *and* has
    zero reconciled feeds in its period returns `ERR_SETTLEMENT_INVALID_STATE`
    (rung 6, HTTP 409), never `ERR_NO_SETTLEABLE_SALES` (rung 12, HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_settlement_issue_rejected
    """
    world = base_world()
    superseded = add_draft_statement(world)
    replacement = add_draft_statement(world)
    assert replacement["status"] == SETTLEMENT_DRAFT
    assert replacement["superseded_statement_id"] == superseded["id"]

    voided = validate_success(
        api.get_settlement_statement(superseded["id"], world["ops_headers"])
    )
    assert voided["status"] == SETTLEMENT_VOID
    assert voided["void_reason"] is not None
    assert voided["issued_by_user_id"] is None

    validate_error(
        api.issue_settlement_statement(superseded["id"], world["ops_issuer_headers"]),
        ApiErrorId.ERR_SETTLEMENT_INVALID_STATE.value,
        409,
    )
    unbooked = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert unbooked["lifetime_share_accrued_cents"] == 0

    validate_error(
        api.issue_settlement_statement(replacement["id"], world["ops_issuer_headers"]),
        ApiErrorId.ERR_NO_SETTLEABLE_SALES.value,
        422,
    )
    still_draft = validate_success(
        api.get_settlement_statement(replacement["id"], world["ops_headers"])
    )
    assert still_draft["status"] == SETTLEMENT_DRAFT
    assert still_draft["issued_by_user_id"] is None


def test_a_superseded_draft_reports_state_even_when_the_period_did_sell(api):
    """Filling the period with reconciled sales does not rescue the voided statement.

    "A prior `DRAFT` statement for the same agreement and identical period is not an
    overlap but a supersede: it moves to `VOID` with a `void_reason` recorded, and
    the new statement records its identifier in `superseded_statement_id`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_settlement_issue_rejected
    """
    world = base_world()
    add_reconciled_feed(world)
    superseded = add_draft_statement(world)
    replacement = add_draft_statement(world)
    assert superseded["binding_share_cents"] == 296000

    validate_error(
        api.issue_settlement_statement(superseded["id"], world["ops_issuer_headers"]),
        ApiErrorId.ERR_SETTLEMENT_INVALID_STATE.value,
        409,
    )
    issued = validate_success(
        api.issue_settlement_statement(replacement["id"], world["ops_issuer_headers"])
    )
    assert issued["binding_share_cents"] == 296000

    booked = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert booked["lifetime_share_accrued_cents"] == 296000

    rejected_twice = validate_success(
        api.get_settlement_statement(superseded["id"], world["ops_headers"])
    )
    assert rejected_twice["status"] == SETTLEMENT_VOID
    assert rejected_twice["issued_by_user_id"] is None


def test_a_manually_voided_statement_pre_empts_the_no_sales_complaint(api):
    """Reaching VOID by the escape hatch rather than by supersede changes nothing.

    "Because state outranks fiscal checks, issuing a statement that is both already
    `VOID` *and* has no reconciled feeds in its period reports
    `ERR_SETTLEMENT_INVALID_STATE` at 409, never the 422 fiscal complaint."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_settlement_issue_rejected
    """
    world = base_world()
    statement = add_draft_statement(world)
    scrapped = validate_success(
        api.void_settlement_statement(
            statement["id"], settlement_void_payload(), world["ops_headers"]
        )
    )
    assert scrapped["status"] == SETTLEMENT_VOID
    assert scrapped["superseded_statement_id"] is None

    validate_error(
        api.issue_settlement_statement(statement["id"], world["ops_issuer_headers"]),
        ApiErrorId.ERR_SETTLEMENT_INVALID_STATE.value,
        409,
    )
    unbooked = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert unbooked["lifetime_share_accrued_cents"] == 0

    listed = validate_list(
        api.list_settlement_statements(
            world["ops_headers"], {"license_agreement_id": world["agreement_id"]}
        ),
        expected_total=1,
    )
    assert listed[0]["status"] == SETTLEMENT_VOID


def test_a_rejected_rice_batch_outranks_the_cross_kiosk_fish_lot(api):
    """Rice that failed its acidification record is reported before the wrong kiosk is.

    "Because safety outranks referential coherence, a body that is *both* backed by a
    rejected batch *and* crosses kiosks reports `ERR_RICE_BATCH_NOT_APPROVED`; both
    are 422, so only the error identifier distinguishes them."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_pack_lot_create_rejected
    """
    world = base_world()
    plan = add_released_plan(world)
    batch = add_mixing_rice_batch(world, plan["id"])
    validate_success(
        api.record_acidification_reading(
            batch["id"],
            acidification_reading_payload(measured_ph=4.85),
            world["chef_headers"],
        )
    )
    hard_failed = validate_success(api.verify_ttc(batch["id"], world["chef_headers"]))
    assert hard_failed["status"] == BATCH_REJECTED
    assert hard_failed["rejection_reason"] == REJECTION_TTC_HARD_FAIL

    neighbour = base_world(suffix="_b")
    foreign_lot = add_released_fish_lot(neighbour, supplier_code=OTHER_SUPPLIER)
    assert foreign_lot["status"] == FISH_RELEASED

    validate_error(
        api.create_pack_lot(
            pack_lot_payload(
                batch["id"],
                foreign_lot["id"],
                pack_count=100,
                produced_at=TRIGGER_PRODUCED_AT,
            ),
            world["chef_headers"],
        ),
        ApiErrorId.ERR_RICE_BATCH_NOT_APPROVED.value,
        422,
    )

    unallocated = validate_success(
        api.get_fish_lot(foreign_lot["id"], neighbour["ops_headers"])
    )
    assert_close(unallocated["allocated_kg"], 0.000, places=3)
    assert_close(unallocated["remaining_kg"], 12.000, places=3)
    validate_list(
        api.list_pack_lots(world["ops_headers"], {"rice_batch_id": batch["id"]}),
        expected_total=0,
    )


def test_an_approved_batch_lets_the_cross_kiosk_complaint_surface(api):
    """With the safety gate satisfied the lower-ranked coherence rule does the refusing.

    "The rice batch and the fish lot must resolve to the same kiosk — the batch
    through its plan, the lot directly — or the build is refused with
    `ERR_CROSS_KIOSK_REFERENCE`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_pack_lot_create_rejected
    """
    world = base_world()
    plan = add_released_plan(world)
    batch = add_approved_rice_batch(world, plan["id"])
    assert batch["status"] == BATCH_APPROVED

    neighbour = base_world(suffix="_b")
    foreign_lot = add_released_fish_lot(neighbour, supplier_code=OTHER_SUPPLIER)

    validate_error(
        api.create_pack_lot(
            pack_lot_payload(
                batch["id"],
                foreign_lot["id"],
                pack_count=100,
                produced_at=TRIGGER_PRODUCED_AT,
            ),
            world["chef_headers"],
        ),
        ApiErrorId.ERR_CROSS_KIOSK_REFERENCE.value,
        422,
    )

    unspent = validate_success(api.get_rice_batch(batch["id"], world["ops_headers"]))
    assert unspent["status"] == BATCH_APPROVED
    unallocated = validate_success(
        api.get_fish_lot(foreign_lot["id"], neighbour["ops_headers"])
    )
    assert_close(unallocated["allocated_kg"], 0.000, places=3)

    own_lot = add_released_fish_lot(world)
    built = validate_success(
        api.create_pack_lot(
            pack_lot_payload(
                batch["id"],
                own_lot["id"],
                pack_count=100,
                produced_at=TRIGGER_PRODUCED_AT,
            ),
            world["chef_headers"],
        ),
        201,
    )
    assert built["status"] == PACK_ON_SHELF
    assert built["unsold_count"] == 100
    assert_close(built["consumed_fish_kg"], 4.500, places=3)
