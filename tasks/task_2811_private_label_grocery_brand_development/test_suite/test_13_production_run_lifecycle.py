"""Running the line: the sibling states that block approval, the four-eyes rule,
the elapsed-window gate and the run a launch must stand on."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_budget_ledger,
    assert_item_state,
    assert_money_cents,
    assert_settlement,
    assert_status,
    assert_supplier_status,
)
from test_helpers.constants import (
    CLAIM_APPROVED,
    DECISION_ACCEPT,
    HOLD_SUPPLIER_SUSPENDED,
    ITEM_SPEC_LOCKED,
    NUTRITION_VALID,
    POSTURE_GREEN,
    POSTURE_SUSPENDED,
    RUN_APPROVED,
    RUN_HOLD,
    RUN_SCHEDULED,
    SPEC_LOCKED,
    SPEC_SUPERSEDE_PENDING,
    SUPPLIER_SUSPENDED,
    TIER_T1,
)
from test_helpers.fixtures import (
    build_chain,
    open_change_request,
    read_artwork_round,
    read_budget_ledger,
    read_claim,
    read_cost_model,
    read_item,
    read_run,
    read_specification,
    read_supplier,
    suspend_supplier,
)
from test_helpers.test_users import (
    DIRECTOR_1,
    DIRECTOR_2,
    DIRECTOR_2_HEADERS,
    DIRECTOR_3_HEADERS,
    DIRECTOR_HEADERS,
    QUALITY_HEADERS,
    SOURCING_HEADERS,
)


def _accept_a_t1_cost_change(api, ctx):
    """Settle a 147/31/48 request with no substitution: T1, net 4 cents."""
    request = open_change_request(
        api,
        ctx,
        requested_ingredient_cost_cents_per_unit=147,
        requested_packaging_cost_cents_per_unit=31,
        requested_conversion_cost_cents_per_unit=48,
    )
    return validate_success(
        api.decide_change_request(
            request["id"], f.decision_payload(DECISION_ACCEPT), SOURCING_HEADERS
        )
    )


def test_a_superseded_pending_specification_blocks_approval_of_its_run(api):
    """The run never moved; the document underneath it did.

    PRD 3.7: "It requires the run to be `SCHEDULED` — from any other status it is
    refused with `ERR_RUN_STATE_INVALID` (HTTP 409) — the governing specification to
    still be `LOCKED`, so that a specification which slipped to `SUPERSEDE_PENDING`
    blocks approval with `ERR_SPECIFICATION_NOT_LOCKED` (HTTP 409)"

    PRD 3.9: "**Hop two**: because the pinned cost model changed, the item's
    specification standing at `LOCKED` whose `pinned_cost_model_id` is this cost model
    transitions `LOCKED → SUPERSEDE_PENDING`, with its `version` incremented"

    Design: Difficulty/cross_entity_state_dependency/run_approve_requires_spec_locked
    """
    ctx = build_chain(api, upto=26)
    assert_status(ctx["run"], RUN_SCHEDULED, "production run")
    _accept_a_t1_cost_change(api, ctx)

    response = api.approve_production_run(ctx["run_id"], DIRECTOR_2_HEADERS)
    validate_error(response, ApiErrorId.ERR_SPECIFICATION_NOT_LOCKED.value, 409)

    assert_status(
        read_specification(api, ctx["specification_id"]),
        SPEC_SUPERSEDE_PENDING,
        "specification",
    )
    run = read_run(api, ctx["run_id"])
    assert_status(run, RUN_SCHEDULED, "production run")
    assert run["approved_by_user_id"] is None, "a refused approval stamps no approver"
    assert_money_cents(
        run["committed_tooling_cents"], 400000, "committed_tooling_cents"
    )
    assert read_item(api, ctx["item_id"])["development_status"] == ITEM_SPEC_LOCKED


def test_a_t1_settlement_moves_the_base_but_leaves_the_printed_panel_valid(api):
    """Four net cents are enough to supersede the pin without touching the label.

    PRD 3.9: "Fifth, `escalation_tier` is `T1` when that percentage is at most 3.00,
    `T2` when it is at most 8.00, and `T3` above that."

    PRD 3.9: "Eighth, `offset_fee_cents` is the capped increase multiplied by 12.50,
    divided by 100, and rounded half up to a whole cent — an agency offset charged on
    the capped increase, not on the raw one. Ninth, `net_increase_cents` is the capped
    increase minus that offset fee."

    PRD 3.9: "A `PACKAGING_MATERIAL` or `NONE` substitution stops the cascade here,
    leaving the panel `VALID`."

    PRD 3.7: "the governing specification to still be `LOCKED`, so that a
    specification which slipped to `SUPERSEDE_PENDING` blocks approval with
    `ERR_SPECIFICATION_NOT_LOCKED` (HTTP 409)"

    Design: Difficulty/cross_entity_state_dependency/run_approve_requires_spec_locked
    """
    ctx = build_chain(api, upto=26)

    settled = _accept_a_t1_cost_change(api, ctx)

    assert_settlement(
        settled,
        raw_increase_cents=5,
        increase_pct=2.26,
        escalation_tier=TIER_T1,
        capped_increase_cents=5,
        offset_fee_cents=1,
        net_increase_cents=4,
    )
    cost_model = read_cost_model(api, ctx["cost_model_id"])
    assert_money_cents(
        cost_model["effective_base_cents"], 225, "effective_base_cents"
    )
    assert_money_cents(
        cost_model["landed_unit_cost_cents_as_quoted"],
        273,
        "landed_unit_cost_cents_as_quoted",
    )
    assert_money_cents(
        cost_model["landed_unit_cost_cents_audited"],
        287,
        "landed_unit_cost_cents_audited",
    )
    assert (
        read_artwork_round(api, ctx["artwork_round_id"])["nutrition_status"]
        == NUTRITION_VALID
    ), "a NONE-scope substitution never reaches the nutrition panel"
    assert_status(read_claim(api, ctx["claim_id"]), CLAIM_APPROVED, "label claim")

    response = api.approve_production_run(ctx["run_id"], DIRECTOR_2_HEADERS)
    validate_error(response, ApiErrorId.ERR_SPECIFICATION_NOT_LOCKED.value, 409)

    assert_status(
        read_specification(api, ctx["specification_id"]),
        SPEC_SUPERSEDE_PENDING,
        "specification",
    )
    assert_status(read_run(api, ctx["run_id"]), RUN_SCHEDULED, "production run")


def test_approving_a_run_that_is_already_approved_is_rejected(api):
    """The second director cannot re-approve, and the tooling is not booked twice.

    PRD 3.7: "Approval belongs to a `ProgramDirector`, moves the run `SCHEDULED →
    APPROVED` and stamps `approved_by_user_id`. It requires the run to be `SCHEDULED`
    — from any other status it is refused with `ERR_RUN_STATE_INVALID` (HTTP 409)"

    PRD 3.7: "`committed_tooling_cents` is snapshotted from the pinned cost model's
    `tooling_cents` as it stands at that instant, and the program's
    `committed_budget_cents` and `lifetime_committed_cents` both increase by that
    amount"

    Design: Corner/state_machines/run_approve_twice_rejected
    """
    ctx = build_chain(api, upto=27)
    assert_status(ctx["run"], RUN_APPROVED, "production run")

    response = api.approve_production_run(ctx["run_id"], DIRECTOR_3_HEADERS)
    validate_error(response, ApiErrorId.ERR_RUN_STATE_INVALID.value, 409)

    run = read_run(api, ctx["run_id"])
    assert_status(run, RUN_APPROVED, "production run")
    assert run["approved_by_user_id"] == DIRECTOR_2, (
        "the first approver keeps the stamp"
    )
    assert_money_cents(
        run["committed_tooling_cents"], 400000, "committed_tooling_cents"
    )
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]),
        committed_budget_cents=666980,
        lifetime_committed_cents=666980,
        lifetime_released_cents=0,
    )


def test_completing_a_run_before_its_window_has_elapsed_is_rejected(api):
    """The clock still reads August; the window closes in September.

    PRD 3.7: "Completion is refused with `ERR_RUN_STATE_INVALID` (HTTP 409) from any
    status other than `APPROVED`, and refused with `ERR_RUN_WINDOW_NOT_ELAPSED` (HTTP
    409) while the logical clock is still strictly before the run's `window_end`; a
    clock sitting exactly at `window_end` is late enough."

    PRD 3.7: "On completion `completed_at` is stamped with the logical clock's current
    instant and the supplier's `composite_score_cached` is refreshed under the
    rolling-twelve-month window."

    Design: Corner/state_machines/run_complete_before_window_end_rejected
    """
    ctx = build_chain(api, upto=27)
    before = read_supplier(api, ctx["supplier_id"])

    response = api.complete_production_run(
        ctx["run_id"], f.run_complete_payload(), QUALITY_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_RUN_WINDOW_NOT_ELAPSED.value, 409)

    run = read_run(api, ctx["run_id"])
    assert_status(run, RUN_APPROVED, "production run")
    assert run["produced_units"] is None
    assert run["completed_on_time"] is None
    assert run["completed_at"] is None
    assert (
        read_supplier(api, ctx["supplier_id"])["composite_score_cached"]
        == before["composite_score_cached"]
    ), "a refused completion does not refresh the cached composite score"


def test_the_director_who_locked_the_specification_may_not_approve_its_run(api):
    """Both acts are director-only, so four eyes are carried by X-User-ID alone.

    PRD 3.7: "Segregation of duties applies: the approving director may not be the
    user recorded in the specification's `locked_by_user_id`, and an attempt to be both
    is refused with `ERR_RUN_SELF_APPROVAL` (HTTP 403)."

    PRD 3.6: "`locked_by_user_id` records the acting director — a field that later
    forbids that same user from approving a production run against this specification."

    Design: Corner/rbac/run_approver_cannot_be_the_user_who_locked_the_specification
    """
    ctx = build_chain(api, upto=26)
    assert (
        read_specification(api, ctx["specification_id"])["locked_by_user_id"]
        == DIRECTOR_1
    )

    response = api.approve_production_run(ctx["run_id"], DIRECTOR_HEADERS)
    validate_error(response, ApiErrorId.ERR_RUN_SELF_APPROVAL.value, 403)

    run = read_run(api, ctx["run_id"])
    assert_status(run, RUN_SCHEDULED, "production run")
    assert run["approved_by_user_id"] is None
    assert_money_cents(
        run["committed_tooling_cents"], 400000, "committed_tooling_cents"
    )
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]), committed_budget_cents=666980
    )

    seconded = validate_success(
        api.approve_production_run(ctx["run_id"], DIRECTOR_2_HEADERS)
    )
    assert_status(seconded, RUN_APPROVED, "production run")
    assert seconded["approved_by_user_id"] == DIRECTOR_2, (
        "a director who did not lock the specification may approve"
    )


def test_releasing_a_hold_is_refused_while_the_item_posture_is_suspended(api):
    """The suspension cascade does not release itself, and posture is checked first.

    PRD 3.7: "Release requires the run to be at `HOLD`, refused with
    `ERR_RUN_STATE_INVALID` (HTTP 409) otherwise; requires the supplier to stand at
    `QUALIFIED`, where `CONDITIONAL` is not enough and the refusal is
    `ERR_SUPPLIER_NOT_QUALIFIED` (HTTP 422); and requires the item's `quality_posture`
    not to be `SUSPENDED`, refused with `ERR_ITEM_QUALITY_SUSPENDED` (HTTP 422)."

    PRD 2.9: "the addressed resource's own transition state; item quality suspension;
    awarded-supplier qualification; GFSI certificate validity"

    PRD 3.7: "Releasing a hold is open to a `SourcingManager` or a `ProgramDirector`,
    moves the run `HOLD → SCHEDULED`, and retains `hold_reason` for the audit trail
    rather than clearing it."

    Design: Corner/endpoints/release_hold_refused_while_item_posture_suspended
    """
    ctx = build_chain(api, upto=26)
    suspend_supplier(api, ctx["supplier_id"])
    assert_status(read_run(api, ctx["run_id"]), RUN_HOLD, "production run")

    response = api.release_hold_production_run(ctx["run_id"], SOURCING_HEADERS)
    validate_error(response, ApiErrorId.ERR_ITEM_QUALITY_SUSPENDED.value, 422)

    run = read_run(api, ctx["run_id"])
    assert_status(run, RUN_HOLD, "production run")
    assert run["hold_reason"] == HOLD_SUPPLIER_SUSPENDED
    assert_money_cents(
        run["committed_tooling_cents"], 400000, "committed_tooling_cents"
    )
    assert_item_state(
        read_item(api, ctx["item_id"]), ITEM_SPEC_LOCKED, POSTURE_SUSPENDED
    )
    assert_supplier_status(
        read_supplier(api, ctx["supplier_id"]), SUPPLIER_SUSPENDED
    )


def test_launching_an_item_with_no_completed_first_production_run_is_rejected(api):
    """The retail price is already published; the shelf still waits on the plant.

    PRD 3.7: "From `SPEC_LOCKED`, launching moves the item `SPEC_LOCKED → LAUNCHED`
    and requires a completed first-production run: at least one run of the item with
    `run_type` `FIRST_PRODUCTION` and status `COMPLETED` must exist, or the launch is
    refused with `ERR_FIRST_PRODUCTION_INCOMPLETE` (HTTP 409)."

    PRD 3.6: "The computed fee lands in `slotting_fee_cents` and the computed price
    lands in the item's `retail_price_cents`."

    Design: Corner/state_machines/item_launch_without_completed_first_production_run_rejected
    """
    ctx = build_chain(api, upto=25)

    response = api.launch_item(ctx["item_id"], DIRECTOR_HEADERS)
    validate_error(response, ApiErrorId.ERR_FIRST_PRODUCTION_INCOMPLETE.value, 409)

    assert_item_state(read_item(api, ctx["item_id"]), ITEM_SPEC_LOCKED, POSTURE_GREEN)
    assert_money_cents(
        read_item(api, ctx["item_id"])["retail_price_cents"], 409, "retail_price_cents"
    )
    spec = read_specification(api, ctx["specification_id"])
    assert_status(spec, SPEC_LOCKED, "specification")
    assert_money_cents(spec["slotting_fee_cents"], 266980, "slotting_fee_cents")
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]), committed_budget_cents=266980
    )
