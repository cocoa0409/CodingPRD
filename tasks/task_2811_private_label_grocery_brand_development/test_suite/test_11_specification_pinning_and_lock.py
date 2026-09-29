"""Freezing the basis: pin currency, the qualification bar the lock raises, and
the two figures lock pricing computes."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_artwork_state,
    assert_budget_ledger,
    assert_instant_equals,
    assert_landed_costs,
    assert_money_cents,
    assert_retail_price_ends_in_nine,
    assert_status,
    assert_supplier_status,
    assert_version_is,
)
from test_helpers.constants import (
    ARTWORK_APPROVED,
    ARTWORK_DRAFT,
    AUDIT_RESULT_CONDITIONAL,
    COST_MODEL_ACCEPTED,
    DECISION_CONDITIONAL,
    DEFAULT_CLOCK,
    ITEM_PACKAGING_APPROVED,
    ITEM_SPEC_LOCKED,
    NUTRITION_VALID,
    SPEC_DRAFT,
    SPEC_LOCKED,
    SUPPLIER_CONDITIONAL,
)
from test_helpers.fixtures import (
    build_chain,
    read_artwork_round,
    read_budget_ledger,
    read_cost_model,
    read_item,
    read_specification,
    read_supplier,
)
from test_helpers.test_users import (
    DESIGNER_HEADERS,
    DIRECTOR_1,
    DIRECTOR_HEADERS,
    QUALITY_HEADERS,
    SOURCING_HEADERS,
)


def _conditional_result_chain(api, upto=24):
    """A chain whose capability audit itself came back CONDITIONAL."""
    return build_chain(
        api,
        upto=upto,
        audit_finalize_factory=f.conditional_audit_finalize_payload,
        qualification_decision=DECISION_CONDITIONAL,
    )


def _specifications_for(api, item_id):
    rows, meta = validate_paginated(
        api.list_specifications(SOURCING_HEADERS, params={"item_id": item_id})
    )
    return rows, meta


def test_locking_against_a_conditional_supplier_is_refused(api):
    """Every pin, the panel and the budget are in order; the standing is not.

    PRD 3.6: "The item's awarded supplier must stand at `QUALIFIED` — and here,
    unlike quote acceptance, `CONDITIONAL` is not sufficient: a lock against a
    supplier that is `PROSPECT`, `CONDITIONAL`, `SUSPENDED` or `DISQUALIFIED` is
    refused with `ERR_SUPPLIER_NOT_QUALIFIED` (HTTP 422)."

    PRD 3.6: "The specification itself opens at `DRAFT` with `slotting_fee_cents`,
    `locked_at` and `locked_by_user_id` all null."

    Design: Difficulty/cross_entity_state_dependency/spec_lock_requires_supplier_qualified
    """
    ctx = _conditional_result_chain(api)
    assert ctx["audit"]["result"] == AUDIT_RESULT_CONDITIONAL
    assert_supplier_status(ctx["supplier"], SUPPLIER_CONDITIONAL)

    response = api.lock_specification(ctx["specification_id"], DIRECTOR_HEADERS)
    validate_error(response, ApiErrorId.ERR_SUPPLIER_NOT_QUALIFIED.value, 422)

    spec = read_specification(api, ctx["specification_id"])
    assert_status(spec, SPEC_DRAFT, "specification")
    assert spec["slotting_fee_cents"] is None, "a refused lock commits no fee"
    assert spec["locked_at"] is None
    assert spec["locked_by_user_id"] is None

    item = read_item(api, ctx["item_id"])
    assert item["development_status"] == ITEM_PACKAGING_APPROVED
    assert item["retail_price_cents"] is None
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]),
        committed_budget_cents=0,
        lifetime_committed_cents=0,
    )


def test_conditional_standing_wins_the_award_but_cannot_lock(api):
    """The same standing that carried the quote is rejected one step later.

    PRD 3.3: "Acceptance requires the item to be at `CONCEPT` and the quoting
    supplier to stand at `QUALIFIED` or `CONDITIONAL`; a quote from a supplier that
    is `PROSPECT`, `SUSPENDED` or `DISQUALIFIED` cannot be awarded and is refused
    with `ERR_SUPPLIER_STATE_INVALID` (HTTP 409). Conditional standing is enough to
    win the business, though — as §3.6 shows, it is not enough to lock a
    specification."

    PRD 3.3: "The **audited-actual** variant selects the `audited_yield_pct`
    measured by an audit and a scrap allowance of zero cents when that audit's
    `result` is `PASS` or 3 cents when the result is `CONDITIONAL`"

    PRD 3.6: "The item's awarded supplier must stand at `QUALIFIED` — and here,
    unlike quote acceptance, `CONDITIONAL` is not sufficient: a lock against a
    supplier that is `PROSPECT`, `CONDITIONAL`, `SUSPENDED` or `DISQUALIFIED` is
    refused with `ERR_SUPPLIER_NOT_QUALIFIED` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/spec_lock_requires_supplier_qualified
    """
    ctx = _conditional_result_chain(api)

    cost_model = read_cost_model(api, ctx["cost_model_id"])
    assert_status(cost_model, COST_MODEL_ACCEPTED, "cost model")
    assert cost_model["supplier_id"] == ctx["supplier_id"]
    assert_landed_costs(cost_model, as_quoted=269, audited=286)
    assert read_item(api, ctx["item_id"])["supplier_id"] == ctx["supplier_id"], (
        "the CONDITIONAL supplier did win the award"
    )

    response = api.lock_specification(ctx["specification_id"], DIRECTOR_HEADERS)
    validate_error(response, ApiErrorId.ERR_SUPPLIER_NOT_QUALIFIED.value, 422)

    assert_supplier_status(
        read_supplier(api, ctx["supplier_id"]), SUPPLIER_CONDITIONAL
    )
    assert_status(
        read_specification(api, ctx["specification_id"]), SPEC_DRAFT, "specification"
    )
    assert read_item(api, ctx["item_id"])["retail_price_cents"] is None


def test_a_conditional_decision_on_a_passing_audit_still_blocks_the_lock(api):
    """CONDITIONAL is a decision, not only an audit result, and the bar is the same.

    PRD 3.2: "`PROSPECT → CONDITIONAL` is the softer landing, accepting a basis
    audit whose result is `PASS` or `CONDITIONAL`, and it likewise stamps
    `qualified_at` — but it does not refresh the cached score."

    PRD 3.6: "The item's awarded supplier must stand at `QUALIFIED` — and here,
    unlike quote acceptance, `CONDITIONAL` is not sufficient: a lock against a
    supplier that is `PROSPECT`, `CONDITIONAL`, `SUSPENDED` or `DISQUALIFIED` is
    refused with `ERR_SUPPLIER_NOT_QUALIFIED` (HTTP 422)."

    Design: Corner/validations/spec_lock_with_conditional_supplier_rejected
    """
    ctx = build_chain(api, upto=24, qualification_decision=DECISION_CONDITIONAL)
    assert_supplier_status(ctx["supplier"], SUPPLIER_CONDITIONAL)
    assert_landed_costs(read_cost_model(api, ctx["cost_model_id"]), audited=283)

    response = api.lock_specification(ctx["specification_id"], DIRECTOR_HEADERS)
    validate_error(response, ApiErrorId.ERR_SUPPLIER_NOT_QUALIFIED.value, 422)

    spec = read_specification(api, ctx["specification_id"])
    assert_status(spec, SPEC_DRAFT, "specification")
    assert spec["slotting_fee_cents"] is None
    item = read_item(api, ctx["item_id"])
    assert item["development_status"] == ITEM_PACKAGING_APPROVED
    assert item["retail_price_cents"] is None
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]), committed_budget_cents=0
    )


def test_lock_pricing_uses_the_audited_cost_and_walks_the_retail_price_up_to_nine(api):
    """283, not 269, drives both figures, and 404 is walked up to 409.

    PRD 3.6: "That input, the effective landed cost, is the pinned cost model's
    `landed_unit_cost_cents_audited` whenever that field is not null, and its
    `landed_unit_cost_cents_as_quoted` otherwise — the audited number always wins
    where it exists, which is why the same specification locks at a different retail
    price depending on whether an audit has refreshed the model."

    PRD 3.6: "An `NBE` item with an effective landed cost of 283 cents and a
    minimum order of 12,000 units therefore locks at a slotting fee of 250,000 plus
    16,980, or 266,980 cents, and a retail price of 409 cents — the rounded quotient
    being 404 and the next price ending in 9 being 409."

    PRD 3.6: "The item's `spec_revision_count` increases by 1 and the new
    specification's `revision_no` is set to the resulting count, so revision numbers
    are per-item ordinals"

    Design: Corner/calculations/spec_lock_pricing_nbe_audited_cost_drives_slotting_and_ceil_to_nine_retail
    """
    ctx = build_chain(api, upto=24)
    assert_landed_costs(
        read_cost_model(api, ctx["cost_model_id"]), as_quoted=269, audited=283
    )

    locked = validate_success(
        api.lock_specification(ctx["specification_id"], DIRECTOR_HEADERS)
    )

    assert_status(locked, SPEC_LOCKED, "specification")
    assert_money_cents(locked["slotting_fee_cents"], 266980, "slotting_fee_cents")
    assert locked["revision_no"] == 1
    assert locked["locked_by_user_id"] == DIRECTOR_1

    item = read_item(api, ctx["item_id"])
    assert_money_cents(item["retail_price_cents"], 409, "retail_price_cents")
    assert_retail_price_ends_in_nine(item["retail_price_cents"])
    assert item["development_status"] == ITEM_SPEC_LOCKED
    assert item["spec_revision_count"] == 1
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]), committed_budget_cents=266980
    )


def test_the_lock_response_and_an_immediate_ledger_read_already_agree(api):
    """No settle step: the fee, the price and the ledger land in the same request.

    PRD 3.6: "The computed fee lands in `slotting_fee_cents` and the computed price
    lands in the item's `retail_price_cents`. The specification moves `DRAFT →
    LOCKED`, `locked_at` is stamped with the logical clock's current instant, and
    `locked_by_user_id` records the acting director"

    PRD 3.6: "The program's `committed_budget_cents` and `lifetime_committed_cents`
    both increase by the slotting fee."

    Design: Corner/consistency_model/specification_lock_response_already_shows_the_committed_ledger
    """
    ctx = build_chain(api, upto=24)

    locked = validate_success(
        api.lock_specification(ctx["specification_id"], DIRECTOR_HEADERS)
    )
    ledger = read_budget_ledger(api, ctx["program_id"])

    assert_status(locked, SPEC_LOCKED, "specification")
    assert_money_cents(locked["slotting_fee_cents"], 266980, "slotting_fee_cents")
    assert_instant_equals(locked["locked_at"], DEFAULT_CLOCK, "locked_at")
    assert locked["locked_by_user_id"] == DIRECTOR_1
    assert_budget_ledger(
        ledger,
        dev_budget_cents=5000000,
        committed_budget_cents=266980,
        available_budget_cents=4733020,
        lifetime_committed_cents=266980,
        lifetime_released_cents=0,
    )
    item = read_item(api, ctx["item_id"])
    assert item["development_status"] == ITEM_SPEC_LOCKED
    assert_money_cents(item["retail_price_cents"], 409, "retail_price_cents")


def test_a_lock_whose_slotting_fee_would_overrun_the_budget_is_refused(api):
    """The fiscal gate is checked against the fee this lock would compute.

    PRD 3.6: "And the money must be there: the program's `committed_budget_cents`
    plus the slotting fee this lock would compute must not exceed
    `dev_budget_cents`, or the lock is refused with `ERR_PROGRAM_BUDGET_EXCEEDED`
    (HTTP 422)."

    Design: Corner/validations/spec_lock_beyond_program_budget_rejected
    """
    ctx = build_chain(api, upto=24, program={"dev_budget_cents": 200000})

    response = api.lock_specification(ctx["specification_id"], DIRECTOR_HEADERS)
    validate_error(response, ApiErrorId.ERR_PROGRAM_BUDGET_EXCEEDED.value, 422)

    spec = read_specification(api, ctx["specification_id"])
    assert_status(spec, SPEC_DRAFT, "specification")
    assert spec["slotting_fee_cents"] is None, (
        "a partial write would leave the ledger unreconcilable"
    )
    item = read_item(api, ctx["item_id"])
    assert item["development_status"] == ITEM_PACKAGING_APPROVED
    assert item["retail_price_cents"] is None
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]),
        dev_budget_cents=200000,
        committed_budget_cents=0,
        lifetime_committed_cents=0,
    )


def test_a_pin_left_stale_by_a_later_audit_blocks_the_lock(api):
    """Finalizing a second audit moves the cost model out from under the pin.

    PRD 3.6: "Both pins must still be current: if `pinned_cost_model_version` no
    longer equals the cost model's `version`, or `pinned_artwork_version` no longer
    equals the artwork round's `version`, the lock is refused with
    `ERR_PIN_VERSION_STALE` (HTTP 409) — which is exactly what happens when a plant
    audit was finalized between drafting and locking."

    PRD 3.6: "Creation records the exact versions it observed.
    `pinned_cost_model_version` receives the cost model's current `version` and
    `pinned_artwork_version` receives the artwork round's current `version`, both as
    read at that instant."

    Design: Corner/validations/spec_lock_after_pinned_cost_model_version_moved_rejected
    """
    ctx = build_chain(api, upto=24)
    assert read_specification(api, ctx["specification_id"])["pinned_cost_model_version"] == 2

    late = validate_success(
        api.create_plant_audit(
            f.plant_audit_payload(
                ctx["supplier_id"],
                window_start="2026-07-25T08:00:00Z",
                window_end="2026-07-26T17:00:00Z",
            ),
            QUALITY_HEADERS,
        ),
        expected_status=201,
    )
    validate_success(
        api.finalize_plant_audit(
            late["id"],
            f.audit_finalize_payload(
                food_safety_score=95,
                sanitation_score=90,
                capacity_score=88,
                traceability_score=92,
                audited_yield_pct=88.0,
            ),
            QUALITY_HEADERS,
        )
    )

    response = api.lock_specification(ctx["specification_id"], DIRECTOR_HEADERS)
    validate_error(response, ApiErrorId.ERR_PIN_VERSION_STALE.value, 409)

    cost_model = read_cost_model(api, ctx["cost_model_id"])
    assert_version_is(cost_model, 3, "cost model")
    assert_landed_costs(cost_model, audited=291)
    spec = read_specification(api, ctx["specification_id"])
    assert spec["pinned_cost_model_version"] == 2, "the pin itself never moves"
    assert_status(spec, SPEC_DRAFT, "specification")
    assert spec["slotting_fee_cents"] is None
    assert (
        read_item(api, ctx["item_id"])["development_status"] == ITEM_PACKAGING_APPROVED
    )


def test_pinning_an_artwork_round_that_is_still_draft_is_rejected(api):
    """A VALID panel clears the nutrition gate; the round is still not APPROVED.

    PRD 3.6: "The pinned rows must genuinely belong to the item and must be in the
    right standing: the pinned cost model must be `ACCEPTED` and its `item_id` must
    equal the specification's `item_id`, and the pinned artwork round must be
    `APPROVED` and likewise belong to the same item. A mismatch on either count is
    refused with `ERR_PIN_ITEM_MISMATCH` (HTTP 409)."

    Design: Corner/validations/specification_pinning_unapproved_artwork_round_rejected
    """
    ctx = build_chain(api, upto=22)
    second = validate_success(
        api.create_artwork_round(
            f.artwork_round_payload(ctx["item_id"]), DESIGNER_HEADERS
        ),
        expected_status=201,
    )
    second = validate_success(
        api.generate_nutrition_panel(second["id"], DESIGNER_HEADERS)
    )
    assert_artwork_state(second, ARTWORK_DRAFT, NUTRITION_VALID)
    item_version = read_item(api, ctx["item_id"])["version"]

    response = api.create_specification(
        f.specification_payload(
            ctx["item_id"], ctx["cost_model_id"], second["id"], item_version
        ),
        SOURCING_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_PIN_ITEM_MISMATCH.value, 409)

    assert_artwork_state(
        read_artwork_round(api, second["id"]), ARTWORK_DRAFT, NUTRITION_VALID
    )
    assert_status(
        read_artwork_round(api, ctx["artwork_round_id"]), ARTWORK_APPROVED, "round"
    )
    _rows, meta = _specifications_for(api, ctx["item_id"])
    assert meta["total_count"] == 0, "a refused create persists no specification"
    assert read_item(api, ctx["item_id"])["spec_revision_count"] == 0


def test_a_second_draft_specification_for_the_same_item_is_rejected(api):
    """One draft at a time, even when both pins and the item version are current.

    PRD 3.6: "Only one draft may be open at a time: a second specification created
    for an item that already has one at `DRAFT` is refused with
    `ERR_DRAFT_SPECIFICATION_EXISTS` (HTTP 409)."

    Design: Corner/validations/second_draft_specification_for_same_item_rejected
    """
    ctx = build_chain(api, upto=24)
    item_version = read_item(api, ctx["item_id"])["version"]

    response = api.create_specification(
        f.specification_payload(
            ctx["item_id"],
            ctx["cost_model_id"],
            ctx["artwork_round_id"],
            item_version,
        ),
        SOURCING_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_DRAFT_SPECIFICATION_EXISTS.value, 409)

    _rows, meta = _specifications_for(api, ctx["item_id"])
    assert meta["total_count"] == 1
    spec = read_specification(api, ctx["specification_id"])
    assert_status(spec, SPEC_DRAFT, "specification")
    assert spec["revision_no"] == 1
    assert (
        read_item(api, ctx["item_id"])["development_status"] == ITEM_PACKAGING_APPROVED
    )


def test_a_packaging_designer_may_not_lock_a_specification(api):
    """Owning the pinned artwork is not authority over the lock.

    PRD 3.6: "Locking the specification belongs to a `ProgramDirector` alone and is
    the most heavily gated operation in the system."

    PRD 2.1: "A `PackagingDesigner` staffs the artwork studio, creating rounds,
    generating nutrition panels, drafting claims and submitting rounds for review, and
    never reviews anything."

    Design: Corner/rbac/packaging_designer_cannot_lock_a_specification
    """
    ctx = build_chain(api, upto=24)

    response = api.lock_specification(ctx["specification_id"], DESIGNER_HEADERS)
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    spec = read_specification(api, ctx["specification_id"])
    assert_status(spec, SPEC_DRAFT, "specification")
    assert spec["slotting_fee_cents"] is None
    assert_version_is(spec, 1, "specification")
    assert (
        read_item(api, ctx["item_id"])["development_status"] == ITEM_PACKAGING_APPROVED
    )
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]), committed_budget_cents=0
    )
