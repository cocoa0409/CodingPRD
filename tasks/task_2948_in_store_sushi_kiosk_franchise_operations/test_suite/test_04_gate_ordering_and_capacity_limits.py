"""Validation gates: yield ceilings, aggregate caps, auth precedence and space credits."""

from test_helpers import (
    ApiErrorId,
    BATCH_CONSUMED,
    CHEF_SUSPENDED,
    KIOSK_OPERATING,
    NON_EXISTENT_UUID,
    NO_HEADERS,
    PACK_ON_SHELF,
    SPACE_COMPLIANT,
    SPACE_DEFICIENT,
    add_approved_rice_batch,
    add_draft_statement,
    add_pack_lot,
    add_released_plan,
    add_submitted_feed,
    assert_close,
    base_world,
    make_franchise_chef_headers,
    make_headers_without_identity,
    pack_lot_payload,
    revocation_payload,
    rice_batch_payload,
    shelf_ready_world,
    suspension_payload,
    validate_error,
    validate_list,
    validate_success,
)


def test_pack_count_above_the_batch_yield_is_refused(api):
    """One pack more than the batch can yield is a capacity failure.

    "`pack_count` must not exceed the batch's `max_pack_yield`; equality is
    allowed and one pack more is `ERR_RICE_YIELD_EXCEEDED`."

    Design: Corner/validations/pack_lot_pack_count_above_rice_yield_rejected
    """
    world = shelf_ready_world(batch_overrides={"rice_kg": 12.0})
    batch = validate_success(
        api.get_rice_batch(world["rice_batch_id"], world["ops_headers"])
    )
    assert batch["max_pack_yield"] == 100

    validate_error(
        api.create_pack_lot(
            pack_lot_payload(
                world["rice_batch_id"], world["fish_lot_id"], pack_count=101
            ),
            world["chef_headers"],
        ),
        ApiErrorId.ERR_RICE_YIELD_EXCEEDED.value,
        422,
    )

    validate_list(api.list_pack_lots(world["ops_headers"]), expected_total=0)
    untouched = validate_success(
        api.get_fish_lot(world["fish_lot_id"], world["ops_headers"])
    )
    assert_close(untouched["allocated_kg"], 0.0)


def test_pack_count_exactly_at_the_batch_yield_is_accepted(api):
    """Equality with the yield ceiling is allowed.

    "`pack_count` must not exceed the batch's `max_pack_yield`; equality is
    allowed and one pack more is `ERR_RICE_YIELD_EXCEEDED`."

    Design: Corner/validations/pack_lot_at_exact_rice_yield_succeeds
    """
    world = shelf_ready_world(batch_overrides={"rice_kg": 12.0})

    lot = validate_success(
        api.create_pack_lot(
            pack_lot_payload(
                world["rice_batch_id"], world["fish_lot_id"], pack_count=100
            ),
            world["chef_headers"],
        ),
        201,
    )
    assert lot["pack_count"] == 100
    assert lot["status"] == PACK_ON_SHELF
    assert lot["unsold_count"] == 100
    assert_close(lot["consumed_fish_kg"], 4.500)

    batch = validate_success(
        api.get_rice_batch(world["rice_batch_id"], world["ops_headers"])
    )
    assert batch["status"] == BATCH_CONSUMED

    plan = validate_success(
        api.get_production_plan(world["plan_id"], world["ops_headers"])
    )
    assert plan["actual_pack_count"] == 100


def test_missing_headers_outrank_a_forbidden_role_on_kiosk_suspension(api):
    """Authentication is the first rung and pre-empts role and existence checks.

    "**Authentication.** Both headers present and non-empty, or
    `ERR_UNAUTHENTICATED` (401). This precedes path-parameter existence, so a
    request with no headers against a non-existent resource is a 401, not a 404."

    Design: Corner/validations/kiosk_suspend_with_missing_auth_headers_beats_forbidden_role
    """
    world = base_world()

    validate_error(
        api.suspend_kiosk(world["kiosk_id"], suspension_payload(), NO_HEADERS),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )
    validate_error(
        api.suspend_kiosk(
            world["kiosk_id"], suspension_payload(), make_headers_without_identity()
        ),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )
    validate_error(
        api.suspend_kiosk(NON_EXISTENT_UUID, suspension_payload(), NO_HEADERS),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )
    validate_error(
        api.suspend_kiosk(
            world["kiosk_id"],
            suspension_payload(),
            make_franchise_chef_headers(world["chef_id"]),
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        403,
    )

    kiosk = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert kiosk["operational_state"] == KIOSK_OPERATING
    assert kiosk["suspension_reason"] is None


def test_rice_batch_started_by_a_suspended_chef_is_refused(api):
    """The mixing chef must be certified at the moment the batch starts.

    "The plan must be `RELEASED` — starting a batch against a plan in any other
    state returns `ERR_PLAN_INVALID_STATE` — and the mixing chef must be
    `CERTIFIED`, or the batch is refused with `ERR_CHEF_NOT_CERTIFIED`."

    Design: Corner/validations/rice_batch_create_by_suspended_chef_rejected
    """
    world = base_world()
    plan = add_released_plan(world)

    validate_success(
        api.revoke_certification(
            world["chef_id"],
            world["certifications"]["haccp"]["id"],
            revocation_payload(),
            world["auditor_headers"],
        )
    )
    chef = validate_success(api.get_chef(world["chef_id"], world["ops_headers"]))
    assert chef["status"] == CHEF_SUSPENDED

    validate_error(
        api.create_rice_batch(
            rice_batch_payload(plan["id"], world["chef_id"]), world["chef_headers"]
        ),
        ApiErrorId.ERR_CHEF_NOT_CERTIFIED.value,
        422,
    )

    validate_list(api.list_rice_batches(world["ops_headers"]), expected_total=0)


def test_pack_lots_may_not_collectively_exceed_the_planned_count(api):
    """The plan's pack target is an aggregate ceiling across every live lot.

    "The packs live against the plan must not exceed the plan's
    `planned_pack_count`, and the kiosk's live pack total must not exceed its
    frozen `daily_pack_cap`; either overrun is `ERR_PACK_CAP_EXCEEDED`."

    Design: Corner/validations/pack_lots_collectively_exceeding_planned_count_rejected
    """
    world = shelf_ready_world()
    plan = validate_success(
        api.get_production_plan(world["plan_id"], world["ops_headers"])
    )
    assert plan["planned_pack_count"] == 162

    add_pack_lot(world, world["rice_batch_id"], world["fish_lot_id"], pack_count=100)
    second_batch = add_approved_rice_batch(
        world,
        world["plan_id"],
        hold_start_at="2026-08-03T07:00:00Z",
        hold_end_at="2026-08-03T09:00:00Z",
    )

    validate_error(
        api.create_pack_lot(
            pack_lot_payload(second_batch["id"], world["fish_lot_id"], pack_count=63),
            world["chef_headers"],
        ),
        ApiErrorId.ERR_PACK_CAP_EXCEEDED.value,
        422,
    )

    filling = validate_success(
        api.create_pack_lot(
            pack_lot_payload(second_batch["id"], world["fish_lot_id"], pack_count=62),
            world["chef_headers"],
        ),
        201,
    )
    assert filling["pack_count"] == 62

    reread = validate_success(
        api.get_production_plan(world["plan_id"], world["ops_headers"])
    )
    assert reread["actual_pack_count"] == 162


def test_space_credit_appears_only_when_the_attestation_falls_short(api):
    """A store meeting its obligation earns no credit; a short store earns the priced one.

    "The raw credit is the store's `space_shortfall_sqft` multiplied by the
    agreement's `space_credit_cents_per_sqft`. Its cap is 25 percent of
    `binding_share_cents`, rounded half up to whole cents, and
    `space_shortfall_credit_cents` is the smaller of the two. A store attesting
    its full obligation has a zero shortfall and therefore a zero credit."

    Design: Corner/validations/settlement_space_credit_applies_only_below_the_obligation
    """
    compliant = base_world()
    store = validate_success(
        api.get_host_store(compliant["host_store_id"], compliant["ops_headers"])
    )
    assert store["space_compliance_state"] == SPACE_COMPLIANT
    validate_success(
        api.reconcile_pos_sales_feed(
            add_submitted_feed(compliant)["id"], compliant["ops_headers"]
        )
    )
    full_bill = add_draft_statement(compliant)
    assert full_bill["space_shortfall_credit_cents"] == 0
    assert full_bill["net_due_cents"] == 296000

    short = base_world(
        suffix="B",
        attestation_overrides={"attested_sushi_space_sqft": 200},
        place=False,
        commission=False,
    )
    short_store = validate_success(
        api.get_host_store(short["host_store_id"], short["ops_headers"])
    )
    assert short_store["space_compliance_state"] == SPACE_DEFICIENT
    short_agreement = validate_success(
        api.get_license_agreement(short["agreement_id"], short["ops_headers"])
    )
    assert short_agreement["space_shortfall_sqft"] == 20

    validate_success(
        api.reconcile_pos_sales_feed(
            add_submitted_feed(short)["id"], short["ops_headers"]
        )
    )
    credited = add_draft_statement(short)
    assert credited["binding_share_cents"] == 296000
    assert credited["space_shortfall_credit_cents"] == 25000
    assert credited["net_due_cents"] == 271000
