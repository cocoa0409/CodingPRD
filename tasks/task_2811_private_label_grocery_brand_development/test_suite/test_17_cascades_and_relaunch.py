"""The long cascades: five hops from one accepted cost change, a complaint that
reaches the supplier's runs, and the two item dimensions moving apart."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_artwork_state,
    assert_budget_ledger,
    assert_item_state,
    assert_landed_costs,
    assert_money_cents,
    assert_retail_price_ends_in_nine,
    assert_settlement,
    assert_status,
    assert_supplier_status,
    assert_two_decimal_value,
    assert_version_advanced_by,
)
from test_helpers.constants import (
    ACTION_COMPLETE_RELAUNCH,
    ARTWORK_APPROVED,
    CCR_ACCEPTED,
    CLAIM_APPROVED,
    CLAIM_RESCINDED,
    DECISION_ACCEPT,
    HOLD_SUPPLIER_CONDITIONAL,
    ITEM_LAUNCHED,
    ITEM_RELAUNCH_PENDING,
    ITEM_SOURCED,
    ITEM_SPEC_LOCKED,
    NUTRITION_INVALIDATED,
    NUTRITION_VALID,
    POSTURE_GREEN,
    POSTURE_PROBATION,
    POSTURE_WATCH,
    PROGRAM_RELAUNCH_FREEZE,
    RUN_COMPLETED,
    RUN_HOLD,
    RUN_SCHEDULED,
    SCOPE_NONE,
    SPEC_LOCKED,
    SPEC_SUPERSEDE_PENDING,
    SUPPLIER_CONDITIONAL,
    SUPPLIER_QUALIFIED,
    TIER_T3,
)
from test_helpers.fixtures import (
    add_complaint,
    add_second_item,
    build_chain,
    open_change_request,
    read_artwork_round,
    read_budget_ledger,
    read_change_request,
    read_claim,
    read_cost_model,
    read_item,
    read_run,
    read_specification,
    read_supplier,
    start_relaunch,
)
from test_helpers.test_users import DIRECTOR_1, DIRECTOR_HEADERS, SOURCING_HEADERS


def _accept_a_substitution(api, ctx, **overrides):
    """Open a 168/33/50 request and let a director accept it: T3, net 17 cents."""
    request = open_change_request(
        api, ctx, factory=f.ingredient_substitution_payload, **overrides
    )
    return validate_success(
        api.decide_change_request(
            request["id"], f.decision_payload(DECISION_ACCEPT), DIRECTOR_HEADERS
        )
    )


def test_one_accepted_ingredient_substitution_walks_all_five_hops(api):
    """Cost model, specification, panel, claim and item all move on one decision.

    PRD 3.9: "**Hop one**: the cost model's `effective_base_cents` increases by
    `net_increase_cents`, both `landed_unit_cost_cents_as_quoted` and
    `landed_unit_cost_cents_audited` are recomputed from the new base, and the cost
    model's `version` increments."

    PRD 3.9: "**Hop two**: because the pinned cost model changed, the item's
    specification standing at `LOCKED` whose `pinned_cost_model_id` is this cost
    model transitions `LOCKED → SUPERSEDE_PENDING`, with its `version` incremented"

    PRD 3.9: "**Hop three**: because that specification entered `SUPERSEDE_PENDING`
    **and** the accepted request's `substitution_scope` is `INGREDIENT`, the artwork
    round named by that specification's `pinned_artwork_round_id` moves
    `nutrition_status` `VALID → INVALIDATED`, with its `version` incremented."

    PRD 3.9: "**Hop four**: because the round's panel became `INVALIDATED`, every
    label claim on that round standing at `APPROVED` whose `depends_on_nutrition` is
    true transitions `APPROVED → RESCINDED`, each with its `version` incremented"

    PRD 3.9: "**Hop five**: because at least one claim was rescinded, if the item
    whose specification pinned that round is `LAUNCHED`, the item transitions
    `LAUNCHED → RELAUNCH_PENDING`, with its `version` incremented."

    Design: Difficulty/transitive_cascade/ingredient_substitution_five_hop_cascade
    """
    ctx = build_chain(api, upto=31)
    spec_before = read_specification(api, ctx["specification_id"])
    round_before = read_artwork_round(api, ctx["artwork_round_id"])
    claim_before = read_claim(api, ctx["claim_id"])
    item_before = read_item(api, ctx["item_id"])
    assert_item_state(item_before, ITEM_LAUNCHED, POSTURE_GREEN)

    accepted = _accept_a_substitution(api, ctx)

    assert_status(accepted, CCR_ACCEPTED, "cost change request")
    assert accepted["decided_by_user_id"] == DIRECTOR_1
    assert_settlement(accepted, escalation_tier=TIER_T3, net_increase_cents=17)

    cost_model = read_cost_model(api, ctx["cost_model_id"])
    assert_money_cents(cost_model["effective_base_cents"], 238, "effective_base_cents")
    assert_landed_costs(cost_model, as_quoted=287, audited=302)
    assert cost_model["open_change_request_count"] == 0

    spec = read_specification(api, ctx["specification_id"])
    assert_status(spec, SPEC_SUPERSEDE_PENDING, "specification")
    assert_version_advanced_by(spec_before, spec, 1, "specification")

    round_ = read_artwork_round(api, ctx["artwork_round_id"])
    assert_artwork_state(round_, ARTWORK_APPROVED, NUTRITION_INVALIDATED)
    assert_version_advanced_by(round_before, round_, 1, "artwork round")

    claim = read_claim(api, ctx["claim_id"])
    assert claim["depends_on_nutrition"] is True
    assert_status(claim, CLAIM_RESCINDED, "label claim")
    assert_version_advanced_by(claim_before, claim, 1, "label claim")

    item = read_item(api, ctx["item_id"])
    assert_item_state(item, ITEM_RELAUNCH_PENDING, POSTURE_GREEN)
    assert_version_advanced_by(item_before, item, 1, "item")


def test_the_same_settlement_scoped_to_nothing_stops_the_cascade_at_hop_two(api):
    """Identical money, identical supersede — but the panel and the item hold still.

    PRD 3.9: "**Hop three**: because that specification entered `SUPERSEDE_PENDING`
    **and** the accepted request's `substitution_scope` is `INGREDIENT`, the artwork
    round named by that specification's `pinned_artwork_round_id` moves
    `nutrition_status` `VALID → INVALIDATED`, with its `version` incremented. A
    `PACKAGING_MATERIAL` or `NONE` substitution stops the cascade here, leaving the
    panel `VALID`."

    PRD 3.9: "**Hop four**: because the round's panel became `INVALIDATED`, every
    label claim on that round standing at `APPROVED` whose `depends_on_nutrition` is
    true transitions `APPROVED → RESCINDED`, each with its `version` incremented;
    claims that do not depend on nutrition, and claims not in `APPROVED`, are left
    alone."

    Design: Difficulty/transitive_cascade/ingredient_substitution_five_hop_cascade
    """
    ctx = build_chain(api, upto=31)
    round_before = read_artwork_round(api, ctx["artwork_round_id"])
    claim_before = read_claim(api, ctx["claim_id"])
    item_before = read_item(api, ctx["item_id"])

    accepted = _accept_a_substitution(
        api, ctx, substitution_scope=SCOPE_NONE, substitution_material_desc=None
    )

    assert accepted["substitution_scope"] == SCOPE_NONE
    assert_settlement(accepted, escalation_tier=TIER_T3, net_increase_cents=17)
    cost_model = read_cost_model(api, ctx["cost_model_id"])
    assert_money_cents(cost_model["effective_base_cents"], 238, "effective_base_cents")
    assert_landed_costs(cost_model, as_quoted=287, audited=302)

    assert_status(
        read_specification(api, ctx["specification_id"]),
        SPEC_SUPERSEDE_PENDING,
        "specification",
    )

    round_ = read_artwork_round(api, ctx["artwork_round_id"])
    assert_artwork_state(round_, ARTWORK_APPROVED, NUTRITION_VALID)
    assert_version_advanced_by(round_before, round_, 0, "artwork round")

    claim = read_claim(api, ctx["claim_id"])
    assert_status(claim, CLAIM_APPROVED, "label claim")
    assert_version_advanced_by(claim_before, claim, 0, "label claim")

    item = read_item(api, ctx["item_id"])
    assert_item_state(item, ITEM_LAUNCHED, POSTURE_GREEN)
    assert_version_advanced_by(item_before, item, 0, "item")


def _two_items_one_supplier(api):
    """A locked item with a scheduled run, plus a second item on the same plant."""
    ctx = build_chain(api, upto=26)
    second = add_second_item(api, ctx)
    add_complaint(api, ctx["item_id"], lot_code="PL-0802-A1")
    add_complaint(api, ctx["item_id"], lot_code="PL-0802-A2")
    add_complaint(api, second["item_id"], lot_code="PL-0802-B1")
    return ctx, second


def test_a_second_item_reaching_probation_turns_the_supplier_conditional_and_holds_its_run(
    api,
):
    """One complaint on the second item walks the count to 2 and stops the line.

    PRD 3.8: "Otherwise `complaint_ppm_90d` is the weighted point total multiplied
    by 1,000,000 and divided by `trailing_90d_units`, rounded half up to two
    decimals. From that figure the recomputed posture is `PROBATION` when the
    parts-per-million figure is at least 150.00, otherwise `WATCH` when it is at
    least 60.00, otherwise `GREEN`."

    PRD 3.8: "The `probation_item_count` is the number of that supplier's items
    currently standing at `PROBATION`, and it carries a cascade: when an item's move
    into `PROBATION` brings that count to 2 or more while the supplier stands at
    `QUALIFIED`, the supplier transitions `QUALIFIED → CONDITIONAL`. That supplier
    transition — not the complaint itself — is then what pushes every one of that
    supplier's `SCHEDULED` and `APPROVED` production runs to `HOLD` with
    `hold_reason` `SUPPLIER_CONDITIONAL`, as §3.7 describes."

    PRD 3.7: "When the item's awarded supplier moves to `CONDITIONAL` or to
    `SUSPENDED`, every run of that supplier's items sitting at `SCHEDULED` or at
    `APPROVED` transitions to `HOLD`, with `hold_reason` set to
    `SUPPLIER_CONDITIONAL` or `SUPPLIER_SUSPENDED` respectively"

    Design: Difficulty/transitive_cascade/complaint_ppm_probation_supplier_conditional_run_hold
    """
    ctx, second = _two_items_one_supplier(api)

    add_complaint(api, second["item_id"], lot_code="PL-0802-B2")

    item_b = read_item(api, second["item_id"])
    assert_two_decimal_value(item_b["complaint_ppm_90d"], 200.00, "complaint_ppm_90d")
    assert_item_state(item_b, ITEM_SOURCED, POSTURE_PROBATION)
    item_a = read_item(api, ctx["item_id"])
    assert_item_state(item_a, ITEM_SPEC_LOCKED, POSTURE_PROBATION)

    supplier = read_supplier(api, ctx["supplier_id"])
    assert supplier["probation_item_count"] == 2
    assert supplier["weighted_complaint_points"] == 20
    assert_supplier_status(supplier, SUPPLIER_CONDITIONAL)

    run = read_run(api, ctx["run_id"])
    assert_status(run, RUN_HOLD, "production run")
    assert run["hold_reason"] == HOLD_SUPPLIER_CONDITIONAL
    assert_money_cents(run["committed_tooling_cents"], 400000, "committed_tooling_cents")
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]),
        committed_budget_cents=666980,
        lifetime_released_cents=0,
    )


def test_one_item_at_probation_leaves_the_supplier_qualified_and_the_run_scheduled(api):
    """The cascade needs a count of two: the complaints alone never move the run.

    PRD 3.8: "Fifty thousand trailing units carrying one `CRITICAL`, one `MAJOR` and
    one `MINOR` complaint accumulate eight points, read 160.00 and land on
    `PROBATION`; drop the critical complaint and the same units read exactly 60.00
    and land on `WATCH` at the inclusive boundary."

    PRD 3.8: "The `probation_item_count` is the number of that supplier's items
    currently standing at `PROBATION`, and it carries a cascade: when an item's move
    into `PROBATION` brings that count to 2 or more while the supplier stands at
    `QUALIFIED`, the supplier transitions `QUALIFIED → CONDITIONAL`. That supplier
    transition — not the complaint itself — is then what pushes every one of that
    supplier's `SCHEDULED` and `APPROVED` production runs to `HOLD` with
    `hold_reason` `SUPPLIER_CONDITIONAL`, as §3.7 describes."

    Design: Difficulty/transitive_cascade/complaint_ppm_probation_supplier_conditional_run_hold
    """
    ctx, second = _two_items_one_supplier(api)

    item_a = read_item(api, ctx["item_id"])
    assert_two_decimal_value(item_a["complaint_ppm_90d"], 200.00, "complaint_ppm_90d")
    assert_item_state(item_a, ITEM_SPEC_LOCKED, POSTURE_PROBATION)
    item_b = read_item(api, second["item_id"])
    assert_two_decimal_value(item_b["complaint_ppm_90d"], 100.00, "complaint_ppm_90d")
    assert_item_state(item_b, ITEM_SOURCED, POSTURE_WATCH)

    supplier = read_supplier(api, ctx["supplier_id"])
    assert supplier["probation_item_count"] == 1
    assert supplier["weighted_complaint_points"] == 15
    assert_supplier_status(supplier, SUPPLIER_QUALIFIED)

    run = read_run(api, ctx["run_id"])
    assert_status(run, RUN_SCHEDULED, "production run")
    assert run["hold_reason"] is None
    assert_money_cents(run["committed_tooling_cents"], 400000, "committed_tooling_cents")


def test_the_posture_walks_to_probation_and_back_while_the_development_status_holds(api):
    """Two CRITICAL complaints and a bigger denominator never touch SPEC_LOCKED.

    PRD 2.10: "Development progress and quality standing move on their own tracks: a
    `LAUNCHED` item can be `PROBATION`, and a `CONCEPT` item can be `SUSPENDED`
    because its awarded supplier was suspended."

    PRD 3.8: "`GREEN → WATCH` and `WATCH → PROBATION` fire when the recomputed
    posture is worse than the stored one; `PROBATION → WATCH` and `PROBATION →
    GREEN` fire when a growing shipment denominator dilutes the complaint rate."

    PRD 3.8: "It overwrites the stored value and then triggers the same
    recomputation a new complaint triggers."

    Design: Difficulty/non_linear_state_machine/item_parallel_development_and_posture_dimensions
    """
    ctx = build_chain(api, upto=25)
    assert_item_state(read_item(api, ctx["item_id"]), ITEM_SPEC_LOCKED, POSTURE_GREEN)

    add_complaint(api, ctx["item_id"], lot_code="PL-0803-A1")
    add_complaint(api, ctx["item_id"], lot_code="PL-0803-A2")
    probation = read_item(api, ctx["item_id"])
    assert_two_decimal_value(probation["complaint_ppm_90d"], 200.00, "complaint_ppm_90d")
    assert_item_state(probation, ITEM_SPEC_LOCKED, POSTURE_PROBATION)

    diluted = validate_success(
        api.post_shipment_feed(
            ctx["item_id"], f.shipment_feed_payload(100000), SOURCING_HEADERS
        )
    )

    assert diluted["trailing_90d_units"] == 100000
    assert_two_decimal_value(diluted["complaint_ppm_90d"], 100.00, "complaint_ppm_90d")
    assert_item_state(diluted, ITEM_SPEC_LOCKED, POSTURE_WATCH)
    assert_money_cents(diluted["retail_price_cents"], 409, "retail_price_cents")
    assert_retail_price_ends_in_nine(diluted["retail_price_cents"])
    assert_status(
        read_specification(api, ctx["specification_id"]), SPEC_LOCKED, "specification"
    )
    assert_supplier_status(read_supplier(api, ctx["supplier_id"]), SUPPLIER_QUALIFIED)


def test_a_launched_item_can_stand_at_probation_without_losing_its_launch(api):
    """The worst posture in the system does not walk the development track back.

    PRD 2.10: "Development progress and quality standing move on their own tracks: a
    `LAUNCHED` item can be `PROBATION`, and a `CONCEPT` item can be `SUSPENDED`
    because its awarded supplier was suspended."

    PRD 2.10: "`RATIONALIZED` and `DISCONTINUED` are the terminal development states;
    the posture dimension has no terminal state and continues to move for as long as
    the item is not rationalized or discontinued."

    Design: Difficulty/non_linear_state_machine/item_parallel_development_and_posture_dimensions
    """
    ctx = build_chain(api, upto=30)
    assert_item_state(read_item(api, ctx["item_id"]), ITEM_LAUNCHED, POSTURE_GREEN)

    add_complaint(api, ctx["item_id"], lot_code="PL-0804-A1")
    watch = read_item(api, ctx["item_id"])
    assert_two_decimal_value(watch["complaint_ppm_90d"], 100.00, "complaint_ppm_90d")
    assert_item_state(watch, ITEM_LAUNCHED, POSTURE_WATCH)

    add_complaint(api, ctx["item_id"], lot_code="PL-0804-A2")

    item = read_item(api, ctx["item_id"])
    assert_two_decimal_value(item["complaint_ppm_90d"], 200.00, "complaint_ppm_90d")
    assert_item_state(item, ITEM_LAUNCHED, POSTURE_PROBATION)
    assert_money_cents(item["retail_price_cents"], 409, "retail_price_cents")
    assert_status(read_run(api, ctx["run_id"]), RUN_COMPLETED, "production run")
    supplier = read_supplier(api, ctx["supplier_id"])
    assert supplier["probation_item_count"] == 1
    assert_supplier_status(supplier, SUPPLIER_QUALIFIED)


def test_relaunching_before_a_new_specification_is_locked_is_rejected(api):
    """The cascade left no LOCKED revision behind, so the relaunch has no basis.

    PRD 3.7: "From `RELAUNCH_PENDING`, launching moves the item `RELAUNCH_PENDING →
    LAUNCHED` and instead requires that the item's regulatory basis has been
    rebuilt: a specification of the item must stand at `LOCKED` with its
    `revision_no` equal to the item's current `spec_revision_count` — that is, the
    newest revision must be the locked one — and that specification's pinned artwork
    round must have `nutrition_status` `VALID` with no claim on it standing at
    `PENDING` or `RESCINDED`. A relaunch attempted before that basis exists is
    refused with `ERR_RELAUNCH_PRECONDITION_UNMET` (HTTP 409)."

    Design: Corner/state_machines/item_launch_from_relaunch_pending_without_locked_specification_rejected
    """
    ctx = build_chain(api, upto=31)
    _accept_a_substitution(api, ctx)
    assert_item_state(
        read_item(api, ctx["item_id"]), ITEM_RELAUNCH_PENDING, POSTURE_GREEN
    )

    response = api.launch_item(ctx["item_id"], DIRECTOR_HEADERS)
    validate_error(response, ApiErrorId.ERR_RELAUNCH_PRECONDITION_UNMET.value, 409)

    item = read_item(api, ctx["item_id"])
    assert_item_state(item, ITEM_RELAUNCH_PENDING, POSTURE_GREEN)
    assert item["spec_revision_count"] == 1
    assert_status(
        read_specification(api, ctx["specification_id"]),
        SPEC_SUPERSEDE_PENDING,
        "specification",
    )
    assert_artwork_state(
        read_artwork_round(api, ctx["artwork_round_id"]),
        ARTWORK_APPROVED,
        NUTRITION_INVALIDATED,
    )
    assert_status(read_claim(api, ctx["claim_id"]), CLAIM_RESCINDED, "label claim")
    assert_landed_costs(
        read_cost_model(api, ctx["cost_model_id"]), as_quoted=287, audited=302
    )
    assert_status(read_run(api, ctx["run_id"]), RUN_COMPLETED, "production run")


def test_completing_the_relaunch_while_an_item_still_waits_is_rejected(api):
    """The freeze cannot lift while the article the cascade took down is unresolved.

    PRD 3.1: "With `action` set to `COMPLETE_RELAUNCH` the program returns
    `RELAUNCH_FREEZE → ACTIVE`, but only once no item under it is still
    `RELAUNCH_PENDING`; while one remains, the attempt is refused with
    `ERR_RELAUNCH_INCOMPLETE` (HTTP 409)."

    PRD 3.1: "With `action` set to `START_RELAUNCH` the program moves `ACTIVE →
    RELAUNCH_FREEZE`, but only if at least one item under the program is `LAUNCHED`
    or `RELAUNCH_PENDING` — there is nothing to relaunch otherwise, and the attempt
    is refused with `ERR_NO_LAUNCHED_ITEMS` (HTTP 409)."

    Design: Corner/state_machines/program_complete_relaunch_while_item_relaunch_pending_rejected
    """
    ctx = build_chain(api, upto=31)
    accepted = _accept_a_substitution(api, ctx)
    frozen = start_relaunch(api, ctx["program_id"])
    assert_status(frozen, PROGRAM_RELAUNCH_FREEZE, "program")

    response = api.program_lifecycle(
        ctx["program_id"],
        f.program_lifecycle_payload(ACTION_COMPLETE_RELAUNCH),
        DIRECTOR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_RELAUNCH_INCOMPLETE.value, 409)

    program = validate_success(api.get_program(ctx["program_id"], DIRECTOR_HEADERS))
    assert_status(program, PROGRAM_RELAUNCH_FREEZE, "program")
    assert_item_state(
        read_item(api, ctx["item_id"]), ITEM_RELAUNCH_PENDING, POSTURE_GREEN
    )
    assert_status(
        read_specification(api, ctx["specification_id"]),
        SPEC_SUPERSEDE_PENDING,
        "specification",
    )
    assert_artwork_state(
        read_artwork_round(api, ctx["artwork_round_id"]),
        ARTWORK_APPROVED,
        NUTRITION_INVALIDATED,
    )
    assert_status(read_claim(api, ctx["claim_id"]), CLAIM_RESCINDED, "label claim")
    request = read_change_request(api, accepted["id"])
    assert_status(request, CCR_ACCEPTED, "cost change request")
    assert_settlement(request, escalation_tier=TIER_T3, net_increase_cents=17)
