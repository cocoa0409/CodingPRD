"""Optimistic concurrency tokens and the derived link counter.

Three layers are exercised here. Two of them are the only version pins in the
service — the inventory token an analyst must hold to compute a growth scenario
and the element token a clerk must hold to move an amendment — both of which are
invalidated by writes that change nothing the holder cares about. The third is
`open_consistency_link_count`, the recomputed counter that decides whether the
plan may hold hearings at all.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions as a
from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_AMENDMENT_NOT_ADOPTED,
    ERR_AMENDMENT_NOT_PROPOSED,
    ERR_CROSS_PLAN_AMENDMENT,
    ERR_INVENTORY_TYPE_MISMATCH,
    ERR_POLICY_COUNT_NEGATIVE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_ELEMENT_VERSION,
    ERR_STALE_INVENTORY_VERSION,
    ERR_TARGET_ELEMENT_NOT_REVIEWABLE,
    ERR_UNRESOLVED_AMENDMENTS,
)
from test_helpers.test_users import CLERK, CLERK_2, DIRECTOR, DIRECTOR_ID, STAFF

# The reference acreage row of 400 vacant, 250 underutilized, 60
# infrastructure-constrained acres at 18 allowed units per acre, read twice.
REF_GROSS_CAPACITY = 11700
REF_NET_CAPACITY = 7115


def _certified_land_use_dataset(api):
    """A DRAFTING plan holding one CERTIFIED land-use dataset on the reference acreage."""
    plan = fx.create_plan(api)
    dataset = fx.create_land_use_inventory(api, plan["id"])
    return plan, fx.certify_inventory(api, dataset["id"])


def _scenario_body(plan_id, land_use_id, token, method, label):
    return f.growth_scenario_payload(
        plan_id, land_use_id, token, method=method, label=label
    )


# ==================================== the token on a dataset nobody edited
def test_a_scenario_that_only_reads_acreage_still_advances_the_dataset(api):
    """The accepted create leaves the dataset's figures alone and its token behind.

    "When the scenario is accepted it enters `DRAFT`, the pinned dataset's
    `referencing_scenario_count` is incremented by one and the dataset's `version` is
    incremented by one — which is exactly why a second scenario pinned to the same
    dataset must re-read it first."

    Design: Corner/complexity_layers/inventory_version_pin_on_scenario_creation
    """
    plan, land_use = _certified_land_use_dataset(api)
    assert land_use["referencing_scenario_count"] == 0

    scenario = validate_success(
        api.create_growth_scenario(
            _scenario_body(
                plan["id"], land_use["id"], land_use["version"], C.METHOD_TREND,
                "Trend 2045",
            ),
            STAFF,
        ),
        201,
    )

    assert scenario["status"] == C.SCENARIO_STATUS_DRAFT
    refreshed = validate_success(api.get_inventory_dataset(land_use["id"], STAFF))
    a.assert_versioned_row(refreshed, land_use["version"] + 1)
    assert refreshed["referencing_scenario_count"] == 1
    # Nothing the analyst read about the land itself moved.
    a.assert_unchanged(
        land_use,
        refreshed,
        [
            "vacant_acres",
            "underutilized_acres",
            "infrastructure_constrained_acres",
            "allowed_density_units_per_acre",
            "status",
        ],
    )


def test_replaying_the_token_the_first_scenario_consumed_is_refused(api):
    """The rejected create advances neither the token nor the reference count.

    "If that value does not equal the dataset's current `version`, the request is
    rejected with `ERR_STALE_INVENTORY_VERSION` (HTTP 412) and no scenario is computed."

    Design: Corner/complexity_layers/inventory_version_pin_on_scenario_creation
    """
    plan, land_use = _certified_land_use_dataset(api)
    stale_token = land_use["version"]
    validate_success(
        api.create_growth_scenario(
            _scenario_body(
                plan["id"], land_use["id"], stale_token, C.METHOD_TREND, "Trend 2045"
            ),
            STAFF,
        ),
        201,
    )
    consumed = validate_success(api.get_inventory_dataset(land_use["id"], STAFF))

    validate_error(
        api.create_growth_scenario(
            _scenario_body(
                plan["id"], land_use["id"], stale_token, C.METHOD_TREND,
                "Trend 2045 moved again on the token already spent",
            ),
            STAFF,
        ),
        ERR_STALE_INVENTORY_VERSION,
        412,
    )

    after = validate_success(api.get_inventory_dataset(land_use["id"], STAFF))
    assert after["version"] == consumed["version"]
    assert after["referencing_scenario_count"] == consumed["referencing_scenario_count"] == 1
    _, meta = validate_paginated(
        api.list_growth_scenarios(STAFF, params={"plan_update_id": plan["id"]})
    )
    assert meta["total_count"] == 1


def test_two_scenarios_may_pin_one_dataset_on_successive_tokens(api):
    """One acreage row, two accepted creates, two legitimately different capacities.

    "On a reference inventory of 400 vacant acres, 250 underutilized acres, 60
    infrastructure-constrained acres and 18 allowed units per acre, `GROSS_CAPACITY`
    yields 11700 units while `NET_CAPACITY` yields 7115: the same inventory row, two
    legitimately different capacities."

    Design: Corner/complexity_layers/inventory_version_pin_on_scenario_creation
    """
    plan, land_use = _certified_land_use_dataset(api)

    first = validate_success(
        api.create_growth_scenario(
            _scenario_body(
                plan["id"], land_use["id"], land_use["version"], C.METHOD_TREND,
                "Trend 2045",
            ),
            STAFF,
        ),
        201,
    )
    assert first["capacity_variant"] == C.CAPACITY_VARIANT_GROSS
    assert first["land_capacity_units"] == REF_GROSS_CAPACITY

    refreshed_token = validate_success(
        api.get_inventory_dataset(land_use["id"], STAFF)
    )["version"]
    second = validate_success(
        api.create_growth_scenario(
            _scenario_body(
                plan["id"], land_use["id"], refreshed_token, C.METHOD_POLICY,
                "Policy 2045",
            ),
            STAFF,
        ),
        201,
    )

    assert second["capacity_variant"] == C.CAPACITY_VARIANT_NET
    assert second["land_capacity_units"] == REF_NET_CAPACITY
    final = validate_success(api.get_inventory_dataset(land_use["id"], STAFF))
    assert final["version"] == refreshed_token + 1
    assert final["referencing_scenario_count"] == 2
    _, meta = validate_paginated(
        api.list_growth_scenarios(STAFF, params={"land_use_inventory_id": land_use["id"]})
    )
    assert meta["total_count"] == 2


def test_a_token_pinned_to_the_wrong_kind_of_dataset_is_never_the_reported_failure(api):
    """A dataset of the wrong type and a spent token together report the type mismatch.

    "Validation is therefore a strictly ordered ladder, evaluated from the top, and the
    first rule that fails determines the response."

    Design: Corner/complexity_layers/inventory_version_pin_on_scenario_creation
    """
    plan, land_use = _certified_land_use_dataset(api)
    demographic = fx.certify_inventory(
        api,
        fx.create_tabular_inventory(api, plan["id"], C.INVENTORY_DEMOGRAPHIC)["id"],
    )
    spent_token = land_use["version"]
    validate_success(
        api.create_growth_scenario(
            _scenario_body(
                plan["id"], land_use["id"], spent_token, C.METHOD_TREND, "Trend 2045"
            ),
            STAFF,
        ),
        201,
    )

    validate_error(
        api.create_growth_scenario(
            _scenario_body(
                plan["id"], demographic["id"], spent_token, C.METHOD_TREND,
                "Pinned to the wrong dataset",
            ),
            STAFF,
        ),
        ERR_INVENTORY_TYPE_MISMATCH,
        409,
    )

    untouched = validate_success(api.get_inventory_dataset(demographic["id"], STAFF))
    assert untouched["referencing_scenario_count"] == 0
    assert untouched["version"] == demographic["version"]
    _, meta = validate_paginated(
        api.list_growth_scenarios(STAFF, params={"plan_update_id": plan["id"]})
    )
    assert meta["total_count"] == 1


# ================================ the token on an element only docketed
def _open_hearing_on_certified_plan(api):
    """A STATE_CERTIFIED plan with a CLEAR posture, one reconciled dependency and an
    open commission hearing. The clock ends at the hearing's scheduled start."""
    ctx = fx.state_certified_plan(api)
    link = fx.create_link(
        api,
        ctx["elements"][C.ELEMENT_TRANSPORTATION]["id"],
        ctx["elements"][C.ELEMENT_LAND_USE]["id"],
        dependency_type=C.DEPENDENCY_LEVEL_OF_SERVICE,
    )
    ctx["link"] = fx.reconcile_link(
        api, link["id"], note="Mobility LOS realigned to the land use capacity."
    )
    ctx["hearing"] = fx.open_commission_hearing(api, ctx["plan_id"])
    ctx["parks_id"] = ctx["elements"][C.ELEMENT_PARKS]["id"]
    return ctx


def _parks_element(api, ctx, headers=CLERK):
    return validate_success(api.get_plan_element(ctx["parks_id"], headers))


def _move_amendment(api, ctx, token, summary, policy_delta=2, headers=CLERK):
    return api.create_amendment(
        f.amendment_payload(
            ctx["hearing"]["id"],
            ctx["parks_id"],
            token,
            summary=summary,
            policy_delta=policy_delta,
        ),
        headers,
    )


def test_docketing_a_motion_moves_the_element_token_and_nothing_else(api):
    """The element's version advances while every field the clerk read stays put.

    "On success the amendment enters `PROPOSED`, its `element_version_at_proposal`
    records the pinned version, `proposed_by_user_id` records the moving clerk's
    `X-User-ID`, `applied_policy_count` and `prior_element_status` are both null, the
    hearing's `amendment_count` is incremented by one and the hearing's `version`
    incremented; and the target element is **docketed**, meaning its `updated_at` is
    refreshed and its `version` is incremented by one even though its content has not
    changed."

    Design: Corner/complexity_layers/element_version_pin_across_docketed_amendments
    """
    ctx = _open_hearing_on_certified_plan(api)
    parks = _parks_element(api, ctx)
    assert parks["policy_count"] == 6

    amendment = validate_success(
        _move_amendment(
            api,
            ctx,
            parks["version"],
            "Add two neighborhood park level-of-service policies.",
        ),
        201,
    )

    assert amendment["status"] == C.AMENDMENT_STATUS_PROPOSED
    assert amendment["element_version_at_proposal"] == parks["version"]
    assert amendment["applied_policy_count"] is None
    assert amendment["prior_element_status"] is None

    docketed = _parks_element(api, ctx)
    assert docketed["version"] == parks["version"] + 1
    assert docketed["policy_count"] == 6
    a.assert_unchanged(
        parks, docketed, ["status", "consistency_status", "title", "created_at"]
    )
    hearing = validate_success(api.get_hearing(ctx["hearing"]["id"], CLERK))
    assert hearing["amendment_count"] == 1
    assert hearing["adopted_amendment_count"] == 0


def test_a_second_motion_needs_the_token_the_docketing_produced(api):
    """The same body is refused on the pre-docket token and accepted on the fresh one.

    "If that value does not equal the element's current `version`, the request is
    rejected with `ERR_STALE_ELEMENT_VERSION` (HTTP 412) and nothing is created."

    Design: Corner/complexity_layers/element_version_pin_across_docketed_amendments
    """
    ctx = _open_hearing_on_certified_plan(api)
    parks = _parks_element(api, ctx)
    validate_success(
        _move_amendment(api, ctx, parks["version"], "First motion of the sitting."), 201
    )
    docketed = _parks_element(api, ctx)

    validate_error(
        _move_amendment(
            api,
            ctx,
            parks["version"],
            "Second motion moved on the token the clerk read before the first.",
            policy_delta=1,
        ),
        ERR_STALE_ELEMENT_VERSION,
        412,
    )

    unmoved = _parks_element(api, ctx)
    assert unmoved["version"] == docketed["version"]
    assert validate_success(api.get_hearing(ctx["hearing"]["id"], CLERK))[
        "amendment_count"
    ] == 1

    second = validate_success(
        _move_amendment(
            api,
            ctx,
            docketed["version"],
            "Second motion, moved on the refreshed token.",
            policy_delta=1,
        ),
        201,
    )

    assert second["element_version_at_proposal"] == docketed["version"]
    assert _parks_element(api, ctx)["version"] == docketed["version"] + 1
    assert validate_success(api.get_hearing(ctx["hearing"]["id"], CLERK))[
        "amendment_count"
    ] == 2


def test_a_motion_aimed_at_another_plans_element_is_an_ownership_failure(api):
    """The foreign element is approved and its token correct, so only ownership is left.

    "The version pin is checked next, then the ownership rule: an element belonging to a
    plan other than the hearing's plan is refused with `ERR_CROSS_PLAN_AMENDMENT`."

    Design: Corner/complexity_layers/element_version_pin_across_docketed_amendments
    """
    ctx = _open_hearing_on_certified_plan(api)
    other_plan = fx.create_plan(
        api, title="Riverside Specific Plan", jurisdiction_code="CA0452"
    )
    foreign = fx.approved_element(
        api, other_plan["id"], C.ELEMENT_PARKS, policy_count=4
    )
    assert foreign["status"] == C.ELEMENT_STATUS_APPROVED

    validate_error(
        api.create_amendment(
            f.amendment_payload(
                ctx["hearing"]["id"],
                foreign["id"],
                foreign["version"],
                summary="Motion aimed at another plan's parks element.",
                policy_delta=1,
            ),
            CLERK,
        ),
        ERR_CROSS_PLAN_AMENDMENT,
        409,
    )

    untouched = validate_success(api.get_plan_element(foreign["id"], CLERK))
    assert untouched["version"] == foreign["version"]
    assert untouched["policy_count"] == 4
    assert validate_success(api.get_hearing(ctx["hearing"]["id"], CLERK))[
        "amendment_count"
    ] == 0


def test_the_recommendation_cannot_close_over_motions_still_on_the_floor(api):
    """Two proposed motions and the outcome is refused, leaving the sitting untouched.

    "and no amendment of the hearing may still be `PROPOSED`, otherwise
    `ERR_UNRESOLVED_AMENDMENTS`."

    Design: Corner/complexity_layers/element_version_pin_across_docketed_amendments
    """
    ctx = _open_hearing_on_certified_plan(api)
    parks = _parks_element(api, ctx)
    validate_success(
        _move_amendment(api, ctx, parks["version"], "First motion of the sitting."), 201
    )
    validate_success(
        _move_amendment(
            api,
            ctx,
            _parks_element(api, ctx)["version"],
            "Second motion of the sitting.",
            policy_delta=1,
        ),
        201,
    )

    validate_error(
        api.record_hearing_outcome(
            ctx["hearing"]["id"],
            f.outcome_payload(
                C.OUTCOME_RECOMMEND,
                "Attempted while two motions are still on the floor.",
            ),
            CLERK,
        ),
        ERR_UNRESOLVED_AMENDMENTS,
        409,
    )

    hearing = validate_success(api.get_hearing(ctx["hearing"]["id"], CLERK))
    assert hearing["status"] == C.HEARING_STATUS_OPEN
    assert hearing["outcome"] is None
    plan = fx.read_plan(api, ctx["plan_id"])
    assert plan["status"] == C.PLAN_STATUS_STATE_CERTIFIED
    assert plan["compliance_posture"] == C.POSTURE_CLEAR


def test_a_withdrawn_motion_applies_nothing_and_can_go_no_further(api):
    """Withdrawal touches only the amendment, and the row then refuses both transitions.

    "It carries an optional `withdrawal_reason`, requires the amendment to be `PROPOSED`
    and its hearing to be `OPEN`, and moves the amendment `PROPOSED → WITHDRAWN` while
    incrementing only the amendment's `version`. No element field and no plan field
    changes; in particular the element's `policy_count` is untouched, because a withdrawn
    amendment was never applied."

    Design: Corner/complexity_layers/element_version_pin_across_docketed_amendments
    """
    ctx = _open_hearing_on_certified_plan(api)
    parks = _parks_element(api, ctx)
    amendment = validate_success(
        _move_amendment(api, ctx, parks["version"], "Motion later withdrawn by its mover."),
        201,
    )
    docketed = _parks_element(api, ctx)

    withdrawn = validate_success(
        api.withdraw_amendment(
            amendment["id"], {"withdrawal_reason": "Motion withdrawn by its mover."}, CLERK
        )
    )

    assert withdrawn["status"] == C.AMENDMENT_STATUS_WITHDRAWN
    assert withdrawn["version"] == amendment["version"] + 1
    assert withdrawn["applied_policy_count"] is None
    after = _parks_element(api, ctx)
    assert after["policy_count"] == 6
    assert after["version"] == docketed["version"]

    validate_error(
        api.adopt_amendment(amendment["id"], {}, CLERK_2), ERR_AMENDMENT_NOT_PROPOSED, 409
    )
    validate_error(
        api.rescind_amendment(
            amendment["id"],
            {"rescission_reason": "Attempting to rescind something never adopted."},
            CLERK_2,
        ),
        ERR_AMENDMENT_NOT_ADOPTED,
        409,
    )
    assert validate_success(api.get_amendment(amendment["id"], CLERK))["status"] == (
        C.AMENDMENT_STATUS_WITHDRAWN
    )


def test_adoption_then_rescission_returns_the_policy_inventory_exactly(api):
    """A +2 adoption and its rescission land back on the count the chapter started with.

    "After an adopted amendment has been rescinded, the target element's `policy_count`
    must equal the value it held immediately before that amendment was adopted, the
    element's `status` must equal the amendment's recorded `prior_element_status`, the
    plan's `open_consistency_link_count` must once again equal the number of links of the
    plan whose status is `OPEN` or `STALE`, and no consistency link may still carry
    `staled_by_amendment_id` pointing at the rescinded amendment."

    Design: Corner/complexity_layers/element_version_pin_across_docketed_amendments
    """
    ctx = _open_hearing_on_certified_plan(api)
    parks = _parks_element(api, ctx)
    amendment = validate_success(
        _move_amendment(
            api,
            ctx,
            parks["version"],
            "Add two neighborhood park level-of-service policies.",
        ),
        201,
    )

    # The clerk who moved it may not carry it.
    validate_error(
        api.adopt_amendment(amendment["id"], {}, CLERK), ERR_SEGREGATION_OF_DUTIES, 403
    )
    adopted = validate_success(api.adopt_amendment(amendment["id"], {}, CLERK_2))

    assert adopted["status"] == C.AMENDMENT_STATUS_ADOPTED
    assert adopted["applied_policy_count"] == 8
    assert adopted["prior_element_status"] == C.ELEMENT_STATUS_APPROVED
    amended = _parks_element(api, ctx, CLERK_2)
    assert amended["policy_count"] == 8
    assert amended["status"] == C.ELEMENT_STATUS_APPROVED
    assert amended["consistency_status"] == C.CONSISTENCY_STALE
    assert amended["version"] == parks["version"] + 2

    # The arithmetic is only checked when the motion is carried.
    overreach = validate_success(
        _move_amendment(
            api,
            ctx,
            amended["version"],
            "Strike twenty policies the element does not have.",
            policy_delta=-20,
        ),
        201,
    )
    assert overreach["status"] == C.AMENDMENT_STATUS_PROPOSED
    validate_error(
        api.adopt_amendment(overreach["id"], {}, CLERK_2), ERR_POLICY_COUNT_NEGATIVE, 409
    )
    validate_success(
        api.withdraw_amendment(
            overreach["id"], {"withdrawal_reason": "Mover concedes the count."}, CLERK
        )
    )

    rescinded = validate_success(
        api.rescind_amendment(
            amendment["id"],
            {"rescission_reason": "Reconsidered on the floor before the vote closed."},
            CLERK_2,
        )
    )

    assert rescinded["status"] == C.AMENDMENT_STATUS_RESCINDED
    restored = _parks_element(api, ctx, CLERK_2)
    assert restored["policy_count"] == 6
    assert restored["status"] == adopted["prior_element_status"]
    assert restored["consistency_status"] == C.CONSISTENCY_CLEARED
    link = validate_success(api.get_consistency_link(ctx["link"]["id"], CLERK_2))
    assert link["status"] == C.LINK_STATUS_CLEARED
    assert link["staled_by_amendment_id"] is None
    summary = fx.read_summary(api, ctx["plan_id"])
    assert summary["open_consistency_link_count"] == 0
    assert summary["compliance_posture"] == C.POSTURE_CLEAR

    closed = validate_success(
        api.record_hearing_outcome(
            ctx["hearing"]["id"],
            f.outcome_payload(
                C.OUTCOME_RECOMMEND, "Register clear; recommended to council."
            ),
            CLERK,
        )
    )

    assert closed["outcome"] == C.OUTCOME_RECOMMEND
    assert closed["status"] == C.HEARING_STATUS_RECOMMENDED
    assert closed["amendment_count"] == 2
    assert closed["adopted_amendment_count"] == 0
    assert fx.read_plan(api, ctx["plan_id"])["status"] == (
        C.PLAN_STATUS_COMMISSION_RECOMMENDED
    )


# ============================= the counter that recomputes over link statuses
def _plan_with_three_draft_elements(api):
    """A DRAFTING plan with three DRAFT elements, no adopted projection and no
    allocations, so the capacity gate is the only one standing before any link exists."""
    plan = fx.create_plan(api)
    elements = {
        element_type: fx.create_element(api, plan["id"], element_type, policy_count=3)
        for element_type in (
            C.ELEMENT_LAND_USE,
            C.ELEMENT_TRANSPORTATION,
            C.ELEMENT_PARKS,
        )
    }
    return plan, elements


def _two_dependencies_on_the_land_use_element(api, elements):
    """A mobility dependency and a parks dependency, both pointing at LAND_USE."""
    mobility = fx.create_link(
        api,
        elements[C.ELEMENT_TRANSPORTATION]["id"],
        elements[C.ELEMENT_LAND_USE]["id"],
        dependency_type=C.DEPENDENCY_LEVEL_OF_SERVICE,
    )
    parks = fx.create_link(
        api,
        elements[C.ELEMENT_PARKS]["id"],
        elements[C.ELEMENT_LAND_USE]["id"],
        dependency_type=C.DEPENDENCY_POLICY_ALIGNMENT,
    )
    return mobility, parks


def test_declaring_a_dependency_withdraws_the_plans_eligibility_at_once(api):
    """Zero, one, two open links, and the posture the counter forces at each step.

    "A newly declared link enters `OPEN`. Its source element's `consistency_status` is set
    to `PENDING` if it had previously reached `CLEARED`, the plan's
    `open_consistency_link_count` is incremented by one, the plan's `compliance_posture`
    is recomputed — which, with at least one open link, necessarily yields
    `CONSISTENCY_HOLD` unless the plan is already frozen at the state — and the plan's
    `version` is incremented by one."

    Design: Corner/complexity_layers/open_link_counter_tracks_every_link_write
    """
    plan, elements = _plan_with_three_draft_elements(api)

    opening = fx.read_summary(api, plan["id"])
    assert opening["open_consistency_link_count"] == 0
    assert opening["compliance_posture"] == C.POSTURE_CAPACITY_HOLD

    mobility = fx.create_link(
        api,
        elements[C.ELEMENT_TRANSPORTATION]["id"],
        elements[C.ELEMENT_LAND_USE]["id"],
        dependency_type=C.DEPENDENCY_LEVEL_OF_SERVICE,
    )
    assert mobility["status"] == C.LINK_STATUS_OPEN

    after_first = fx.read_summary(api, plan["id"])
    assert after_first["open_consistency_link_count"] == 1
    assert after_first["compliance_posture"] == C.POSTURE_CONSISTENCY_HOLD
    a.assert_posture_consistent(fx.read_plan(api, plan["id"]))

    # A second dependency on the same target is legal even though that target is
    # still being drafted.
    fx.create_link(
        api,
        elements[C.ELEMENT_PARKS]["id"],
        elements[C.ELEMENT_LAND_USE]["id"],
        dependency_type=C.DEPENDENCY_POLICY_ALIGNMENT,
    )

    after_second = fx.read_summary(api, plan["id"])
    assert after_second["open_consistency_link_count"] == 2
    assert after_second["compliance_posture"] == C.POSTURE_CONSISTENCY_HOLD


def test_a_dependency_may_not_be_reconciled_against_a_draft_target(api):
    """The refused reconciliation changes nothing; submitting the target makes it legal.

    "The target element must additionally be far enough along to be relied upon — its
    status must be `IN_REVIEW`, `APPROVED` or `ADOPTED` — otherwise the attempt is refused
    with `ERR_TARGET_ELEMENT_NOT_REVIEWABLE`."

    Design: Corner/complexity_layers/open_link_counter_tracks_every_link_write
    """
    plan, elements = _plan_with_three_draft_elements(api)
    _, parks_link = _two_dependencies_on_the_land_use_element(api, elements)
    note = "Parks policies aligned to the land use map."

    validate_error(
        api.reconcile_consistency_link(
            parks_link["id"], f.reconcile_payload(note), DIRECTOR
        ),
        ERR_TARGET_ELEMENT_NOT_REVIEWABLE,
        409,
    )

    held = validate_success(api.get_consistency_link(parks_link["id"], STAFF))
    assert held["status"] == C.LINK_STATUS_OPEN
    assert held["reconciled_by_user_id"] is None
    assert fx.read_summary(api, plan["id"])["open_consistency_link_count"] == 2

    submitted = fx.submit_element(api, elements[C.ELEMENT_LAND_USE]["id"])
    assert submitted["status"] == C.ELEMENT_STATUS_IN_REVIEW

    cleared = validate_success(
        api.reconcile_consistency_link(
            parks_link["id"], f.reconcile_payload(note), DIRECTOR
        )
    )

    assert cleared["status"] == C.LINK_STATUS_CLEARED
    assert cleared["reconciled_by_user_id"] == DIRECTOR_ID
    assert cleared["reconciliation_note"] == note
    summary = fx.read_summary(api, plan["id"])
    assert summary["open_consistency_link_count"] == 1
    assert summary["compliance_posture"] == C.POSTURE_CONSISTENCY_HOLD


def test_the_cleared_flag_on_a_source_element_is_its_own_business(api):
    """One source has all its dependencies cleared, the other still has one outstanding.

    "The source element's `consistency_status` becomes `CLEARED` only if every link
    sourced from it is now `CLEARED`; if any sibling link is still outstanding, the source
    element's status is left unchanged."

    Design: Corner/complexity_layers/open_link_counter_tracks_every_link_write
    """
    plan, elements = _plan_with_three_draft_elements(api)
    _, parks_link = _two_dependencies_on_the_land_use_element(api, elements)
    fx.submit_element(api, elements[C.ELEMENT_LAND_USE]["id"])

    fx.reconcile_link(
        api, parks_link["id"], note="Parks policies aligned to the land use map."
    )

    parks = fx.read_element(api, elements[C.ELEMENT_PARKS]["id"])
    assert parks["consistency_status"] == C.CONSISTENCY_CLEARED
    mobility_source = fx.read_element(api, elements[C.ELEMENT_TRANSPORTATION]["id"])
    assert mobility_source["consistency_status"] == C.CONSISTENCY_PENDING
    assert fx.read_summary(api, plan["id"])["open_consistency_link_count"] == 1


def test_the_counter_is_recomputed_over_statuses_rather_than_decremented(api):
    """With both dependencies cleared the counter reads zero and the next gate takes over.

    "`open_consistency_link_count` is the number of consistency links whose source element
    belongs to this plan and whose status is either `OPEN` or `STALE` — cleared links do
    not count, and stale links count exactly as much as open ones."

    Design: Corner/complexity_layers/open_link_counter_tracks_every_link_write
    """
    plan, elements = _plan_with_three_draft_elements(api)
    mobility_link, parks_link = _two_dependencies_on_the_land_use_element(api, elements)
    fx.submit_element(api, elements[C.ELEMENT_LAND_USE]["id"])
    fx.reconcile_link(
        api, parks_link["id"], note="Parks policies aligned to the land use map."
    )

    fx.reconcile_link(
        api,
        mobility_link["id"],
        note="Mobility level of service realigned to the land use capacity.",
    )

    summary = fx.read_summary(api, plan["id"])
    assert summary["open_consistency_link_count"] == 0
    assert summary["compliance_posture"] == C.POSTURE_CAPACITY_HOLD
    assert (
        fx.read_element(api, elements[C.ELEMENT_TRANSPORTATION]["id"])[
            "consistency_status"
        ]
        == C.CONSISTENCY_CLEARED
    )
    a.assert_posture_consistent(fx.read_plan(api, plan["id"]))

    rows, meta = validate_paginated(
        api.list_consistency_links(
            STAFF, params={"target_element_id": elements[C.ELEMENT_LAND_USE]["id"]}
        )
    )
    assert meta["total_count"] == 2
    assert [row["status"] for row in rows] == [
        C.LINK_STATUS_CLEARED,
        C.LINK_STATUS_CLEARED,
    ]
