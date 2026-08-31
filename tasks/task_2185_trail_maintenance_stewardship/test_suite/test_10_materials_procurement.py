"""Requisition pricing, the checks that guard submission, and the money it moves."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_bridge_requisition,
    add_signage_requisition,
    assert_material_order,
    create_material_order,
    read_agreement,
    read_material_order,
    read_party,
    read_plan,
    read_segment,
    read_shift,
    read_volunteer,
    setup_approved_plan,
    setup_confirmed_party,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


def test_freight_is_keyed_on_the_post_discount_subtotal(api):
    """PRD 3.8: "Step one produces `line_subtotal_cents`: for each line, the `unit_price_cents` multiplied by the `quantity`, summed across all lines."
    PRD 3.8: "Below that threshold, freight is a base charge of 4,500 cents plus 2 percent of `discounted_subtotal_cents`, where that percentage is rounded half up to whole cents before being added to the base."
    PRD 3.8: "A signage order with lines totalling 205,000 cents attracts a 4 percent discount of 8,200 cents, leaving a discounted subtotal of 196,800 cents, which sits below the free-freight threshold and therefore pays 4,500 plus 3,936, or 8,436 cents of freight — where keying the tier on the untouched 205,000 would have wrongly made freight free."
    PRD 3.8: "Step five sets `bridge_surcharge_cents`, the engineered-structure surcharge, which is non-zero only when `category` is `BRIDGE`: it is 6 percent of `discounted_subtotal_cents`, rounded half up to whole cents, and it is 0 for every other category."
    PRD 3.8: "Step six sums the three to give `total_cents`: `discounted_subtotal_cents` plus `freight_cents` plus `bridge_surcharge_cents`."

    Design: Difficulty/combinatorial_formula/material_order_freight_tier_keyed_on_post_discount_subtotal
    """
    world = setup_approved_plan()
    order = add_signage_requisition(world)

    assert_material_order(order)
    assert order["line_subtotal_cents"] == 205000
    assert order["discount_cents"] == 8200
    assert order["discounted_subtotal_cents"] == 196800
    assert order["freight_cents"] == 8436
    assert order["freight_cents"] != 0, "the post-discount subtotal is below 200,000"
    assert order["bridge_surcharge_cents"] == 0
    assert order["total_cents"] == 205236


def test_the_priced_requisition_commits_against_the_plan_ledger_on_creation(api):
    """PRD 3.8: "That `total_cents` is committed against the plan immediately on creation, subject to the admission cap of section 3.3 being checked first, and the plan's `version` advances by 1 as the ledger moves."
    PRD 3.3: "The plan's `committed_cents` is the sum of `total_cents` over the plan's material orders whose status is `DRAFT`, `SUBMITTED` or `APPROVED`."
    PRD 3.3: "From `available_cents` the server derives `budget_posture` in four bands: it is `OVER_COMMITTED` when `available_cents` is below 0; `EXHAUSTED` when `available_cents` is exactly 0; `TIGHT` when `available_cents` is above 0 but strictly below a floor equal to one fifth of `approved_budget_cents` — that is, `approved_budget_cents` multiplied by 0.20 and rounded half up to whole cents; and `HEALTHY` in every remaining case."

    Design: Difficulty/combinatorial_formula/material_order_freight_tier_keyed_on_post_discount_subtotal
    """
    world = setup_approved_plan()
    order = add_signage_requisition(world)
    assert order["total_cents"] == 205236

    plan = read_plan(world["plan_id"])
    assert plan["committed_cents"] == 205236
    assert plan["available_cents"] == 44764
    assert plan["budget_posture"] == "TIGHT"


def test_engineering_review_error_pre_empts_the_over_committed_error_on_submit(api):
    """PRD 3.8: "Submitting the order moves it `DRAFT → SUBMITTED` and enforces three checks in this order: the plan must be `APPROVED`, otherwise `ERR_WORK_PLAN_NOT_APPROVED`; a `BRIDGE` order under an agency with `requires_engineering_review` true must carry a non-null `engineering_review_ref`, otherwise `ERR_ENGINEERING_REVIEW_REQUIRED`; and the plan's `budget_posture` must not be `OVER_COMMITTED`, otherwise `ERR_PLAN_OVER_COMMITTED`."
    PRD 3.1: "The `requires_engineering_review` flag defaults to false and, when true, forces a structural sign-off reference onto bridge requisitions."

    Design: Difficulty/priority_pair_validation_conflict/engineering_review_safety_outranks_over_committed_fiscal_on_order_submit
    """
    world = setup_approved_plan()
    bridge = add_bridge_requisition(world)
    add_signage_requisition(world)
    assert read_plan(world["plan_id"])["budget_posture"] == "OVER_COMMITTED"

    response = api.submit_material_order(bridge["id"], world["lead_headers"])
    error_data = validate_error(
        response, ApiErrorId.ERR_ENGINEERING_REVIEW_REQUIRED.value, 422
    )
    assert error_data["error_id"] != ApiErrorId.ERR_PLAN_OVER_COMMITTED.value
    assert read_material_order(bridge["id"])["status"] == "DRAFT"


def test_the_fiscal_check_surfaces_only_once_the_engineering_reference_is_present(api):
    """PRD 3.8: "Submitting the order moves it `DRAFT → SUBMITTED` and enforces three checks in this order: the plan must be `APPROVED`, otherwise `ERR_WORK_PLAN_NOT_APPROVED`; a `BRIDGE` order under an agency with `requires_engineering_review` true must carry a non-null `engineering_review_ref`, otherwise `ERR_ENGINEERING_REVIEW_REQUIRED`; and the plan's `budget_posture` must not be `OVER_COMMITTED`, otherwise `ERR_PLAN_OVER_COMMITTED`."
    PRD 2.7: "Plan not over-committed (`ERR_PLAN_OVER_COMMITTED`, HTTP 409), on material-order submission and material-order approval."

    Design: Difficulty/priority_pair_validation_conflict/engineering_review_safety_outranks_over_committed_fiscal_on_order_submit
    """
    world = setup_approved_plan()
    bridge = create_material_order(
        world["plan_id"],
        world["lead_id"],
        category="BRIDGE",
        lines=[{"sku": "BRIDGE_STRINGER", "unit_price_cents": 20000, "quantity": 2}],
        engineering_review_ref="ENG-2026-114",
    )
    add_signage_requisition(world)
    assert read_plan(world["plan_id"])["budget_posture"] == "OVER_COMMITTED"

    response = api.submit_material_order(bridge["id"], world["lead_headers"])
    validate_error(response, ApiErrorId.ERR_PLAN_OVER_COMMITTED.value, 409)
    assert read_material_order(bridge["id"])["status"] == "DRAFT"


def test_terminating_the_adoption_closes_the_approved_plan(api):
    """PRD 3.3: "When the parent adoption terminates, an `APPROVED` plan moves to `CLOSED`, which is terminal — no further requisition and no further permit may reference it."
    PRD 3.2: "Every work plan under the agreement whose status is `APPROVED` moves to `CLOSED`."
    PRD 3.2: "The segment's `adoption_status` returns to `UNADOPTED` and the agency's `adopted_segment_count` drops by 1."

    Design: Difficulty/cross_entity_state_dependency/material_order_submit_gated_by_work_plan_status
    """
    world = setup_approved_plan()
    order = add_signage_requisition(world)
    assert order["total_cents"] == 205236

    terminated = validate_success(
        api.terminate_adoption_agreement(
            world["agreement_id"], {"reason": "Crew disbanded mid-season."}, COORD
        )
    )
    assert terminated["status"] == "TERMINATED"
    assert read_plan(world["plan_id"])["status"] == "CLOSED"
    assert read_segment(world["seg_id"])["adoption_status"] == "UNADOPTED"


def test_requisition_submit_is_refused_once_its_plan_has_closed(api):
    """PRD 3.8: "Submitting the order moves it `DRAFT → SUBMITTED` and enforces three checks in this order: the plan must be `APPROVED`, otherwise `ERR_WORK_PLAN_NOT_APPROVED`; a `BRIDGE` order under an agency with `requires_engineering_review` true must carry a non-null `engineering_review_ref`, otherwise `ERR_ENGINEERING_REVIEW_REQUIRED`; and the plan's `budget_posture` must not be `OVER_COMMITTED`, otherwise `ERR_PLAN_OVER_COMMITTED`."
    PRD 3.3: "When the parent adoption terminates, an `APPROVED` plan moves to `CLOSED`, which is terminal — no further requisition and no further permit may reference it."

    Design: Difficulty/cross_entity_state_dependency/material_order_submit_gated_by_work_plan_status
    """
    world = setup_approved_plan()
    order = add_signage_requisition(world)
    validate_success(
        api.terminate_adoption_agreement(
            world["agreement_id"], {"reason": "Crew disbanded mid-season."}, COORD
        )
    )

    response = api.submit_material_order(order["id"], world["lead_headers"])
    validate_error(response, ApiErrorId.ERR_WORK_PLAN_NOT_APPROVED.value, 409)
    assert read_material_order(order["id"])["status"] == "DRAFT"


def test_an_over_committing_requisition_suspends_the_governing_adoption(api):
    """PRD 3.8: "If the commitment drives `budget_posture` to `OVER_COMMITTED`, the parent adoption suspends and its work parties suspend behind it, exactly as section 3.2 describes."
    PRD 3.2: "When a work plan's `budget_posture` becomes `OVER_COMMITTED`, or when the segment's posture becomes `INCIDENT_CLOSED`, the agreement moves `ACTIVE → SUSPENDED` and `suspension_reason` is set to `BUDGET_OVER_COMMIT` or `SEGMENT_INCIDENT` accordingly."

    Design: Difficulty/transitive_cascade/material_overcommit_cascades_plan_then_agreement_then_party_then_shift
    """
    world = setup_confirmed_party()
    bridge = add_bridge_requisition(world)
    assert bridge["total_cents"] == 47700

    signage = add_signage_requisition(world)
    assert signage["total_cents"] == 205236

    plan = read_plan(world["plan_id"])
    assert plan["committed_cents"] == 252936
    assert plan["spent_cents"] == 0
    assert plan["available_cents"] == -2936
    assert plan["budget_posture"] == "OVER_COMMITTED"

    agreement = read_agreement(world["agreement_id"])
    assert agreement["status"] == "SUSPENDED"
    assert agreement["suspension_reason"] == "BUDGET_OVER_COMMIT"


def test_the_over_commit_cascade_suspends_the_party_and_withdraws_its_shift(api):
    """PRD 3.2: "That suspension carries the cascade described in section 2.10: every work party under the agreement's plans whose `schedule_status` is `CONFIRMED` moves to `SUSPENDED` with `readiness_status` `BLOCKED` and `block_reason` `AGREEMENT_SUSPENDED`, while every party sitting in `PLANNED` keeps its `schedule_status` and merely acquires the same `readiness_status` and `block_reason`; both sets are processed in `created_at` ascending order."
    PRD 3.2: "Then, on each party that actually moved to `SUSPENDED`, every shift in `REGISTERED` moves to `WITHDRAWN` and that volunteer's `active_registration_count` drops by 1, again in `created_at` ascending order."

    Design: Difficulty/transitive_cascade/material_overcommit_cascades_plan_then_agreement_then_party_then_shift
    """
    world = setup_confirmed_party()
    add_bridge_requisition(world)
    add_signage_requisition(world)

    party = read_party(world["party_id"])
    assert party["schedule_status"] == "SUSPENDED"
    assert party["readiness_status"] == "BLOCKED"
    assert party["block_reason"] == "AGREEMENT_SUSPENDED"

    assert read_shift(world["shift_saw_id"])["status"] == "WITHDRAWN"
    assert read_volunteer(world["saw_id"])["active_registration_count"] == 0


def test_an_over_committed_plan_blocks_approval_of_an_already_submitted_order(api):
    """PRD 2.7: "Plan not over-committed (`ERR_PLAN_OVER_COMMITTED`, HTTP 409), on material-order submission and material-order approval."
    PRD 3.8: "Approval by a `StewardshipCoordinator` moves the order `SUBMITTED → APPROVED`, again requires the plan to be `APPROVED`, and records the acting `X-User-ID` as `approved_by_user_id`; it also has a side effect elsewhere in the system, because an escalated condition report naming this order through `condition_report_id` becomes resolvable by a coordinator once the order reaches `APPROVED`."

    Design: Corner/validations/over_committed_plan_blocks_material_order_approval
    """
    world = setup_approved_plan()
    bridge = create_material_order(
        world["plan_id"],
        world["lead_id"],
        category="BRIDGE",
        lines=[{"sku": "BRIDGE_STRINGER", "unit_price_cents": 20000, "quantity": 2}],
        engineering_review_ref="ENG-2026-114",
    )
    submitted = validate_success(
        api.submit_material_order(bridge["id"], world["lead_headers"])
    )
    assert submitted["status"] == "SUBMITTED"

    signage = add_signage_requisition(world)
    assert signage["total_cents"] == 205236
    assert read_plan(world["plan_id"])["budget_posture"] == "OVER_COMMITTED"

    response = api.approve_material_order(bridge["id"], COORD)
    validate_error(response, ApiErrorId.ERR_PLAN_OVER_COMMITTED.value, 409)

    stored = read_material_order(bridge["id"])
    assert stored["status"] == "SUBMITTED"
    assert stored["approved_by_user_id"] is None
