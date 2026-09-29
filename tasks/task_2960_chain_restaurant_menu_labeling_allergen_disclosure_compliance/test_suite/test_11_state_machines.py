"""Transitions taken one at a time: initial states, terminals and the guards.

Each case drives a single defined move and then reads back both the row that
moved and the counters the move was declared to disturb.
"""

from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_ALREADY_TERMINAL,
    ERR_ANALYSIS_ALREADY_DECIDED,
    ERR_BOARD_NOT_DRAFT,
    ERR_PACKET_NOT_DRAFT,
    ERR_RECIPE_NOT_DRAFT,
    ERR_UNIT_HAS_OPEN_ENFORCEMENT,
    ERR_VARIANCE_STATE_INVALID,
)
from test_helpers.assertions import (
    assert_brand_counters,
    assert_date_only,
    assert_fields_are_none,
    assert_instant_equals,
    assert_item_declaration,
    assert_numeric_equals,
    expected_display_calorie_text,
    ids_of,
    validate_unpaginated,
)
from test_helpers.constants import (
    ACTION_OPEN,
    ANALYSIS_CERTIFIED,
    ANALYSIS_REJECTED,
    ANALYSIS_SUBMITTED,
    CHANNEL_IN_STORE_BINDER,
    CHANNEL_PHONE_LINE,
    CHANNEL_WEBSITE,
    CITATION_ALLERGEN_MATRIX_MISSING,
    CLOCK_EPOCH_COMPACT,
    COMPLIANCE_CURRENT,
    COVERAGE_COVERED,
    COVERAGE_NOT_COVERED,
    COVERED_UNIT_THRESHOLD,
    DECISION_REJECT,
    EXTRA_REQUIREMENT_NONE,
    ITEM_CLASS_DAILY_SPECIAL,
    LABELING_DECLARATION_PENDING,
    LABELING_DECLARED,
    METHOD_DATABASE,
    PACKET_DRAFT,
    PACKET_PUBLISHED,
    PACKET_SUPERSEDED,
    POSTURE_COMPLIANT,
    POSTURE_EXEMPT,
    PREEMPTION_PREEMPTED,
    PREEMPTION_VARIANCE_ALLOWED,
    PUBLICATION_PUBLISHED,
    REASON_BELOW_UNIT_THRESHOLD,
    REASON_COVERED_BY_UNIT_COUNT,
    RECIPE_ANALYSIS_PENDING,
    RECIPE_APPROVED,
    RECIPE_DRAFT,
    RECIPE_REJECTED,
    REQUIREMENT_ADDED_SUGAR_ICON,
    REQUIREMENT_WRITTEN_INFO_FORMAT,
    TIER_FEDERAL_ALIGNED,
    UNIT_OPERATING,
    UNIT_PERMANENTLY_CLOSED,
    UNIT_PLANNED,
    UNIT_TEMPORARILY_CLOSED,
    VARIANCE_DECISION_DENIED,
    VARIANCE_DECISION_GRANTED,
    VARIANCE_DECISION_OPEN_REVIEW,
    VARIANCE_DENIED,
    VARIANCE_GRANTED,
    VARIANCE_SUBMITTED,
    VARIANCE_UNDER_REVIEW,
)
from test_helpers.factories import (
    analysis_decision_payload,
    board_publish_payload,
    brioche_bun_component,
    chicken_breast_component,
    enforcement_action_payload,
    establishment_batch_payload,
    establishment_payload,
    listing_payload,
    menu_item_payload,
    recipe_payload,
    status_change_payload,
    submit_for_analysis_payload,
    variance_decision_payload,
    variance_request_payload,
)
from test_helpers.fixtures import (
    Env,
    certify_recipe_version,
    draft_and_publish_packet,
    draft_packet,
    make_brand,
    make_jurisdiction,
    make_menu_item,
    published_board,
    publish_packet,
    seed_registry,
    set_clock,
)
from test_helpers.test_users import (
    ANALYST_CERTIFIER,
    ANALYST_SUBMITTER,
    ANALYST_SUBMITTER_USER_ID,
    PLATFORM_ADMIN,
    make_brand_officer_headers,
    make_regulator_headers,
)


# ---------------------------------------------------------------------------
# The unit register
# ---------------------------------------------------------------------------
def _authority_and_brand(api: ApiClient) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, str]]:
    set_clock(api)
    authority = make_jurisdiction(
        api, code="ID-MIN", name="Idaho", preemption_mode=PREEMPTION_PREEMPTED
    )
    brand = make_brand(api)
    return authority, brand, make_brand_officer_headers(brand["id"])


def _register_unit(
    api: ApiClient,
    brand_id: str,
    jurisdiction_id: str,
    unit_label: str,
    unit_status: str = UNIT_OPERATING,
) -> Dict[str, Any]:
    return validate_success(
        api.create_establishment(
            establishment_payload(
                brand_id=brand_id,
                jurisdiction_id=jurisdiction_id,
                unit_label=unit_label,
                unit_status=unit_status,
            ),
            PLATFORM_ADMIN,
        ),
        201,
    )


def test_the_twentieth_unit_opening_carries_the_brand_into_coverage(api):
    """PRD §3.1: "The defined moves are `PLANNED` to `OPERATING`, `OPERATING` to
    `TEMPORARILY_CLOSED`, `TEMPORARILY_CLOSED` back to `OPERATING` — a genuine
    reopening cycle — and `OPERATING` or `TEMPORARILY_CLOSED` to
    `PERMANENTLY_CLOSED`." "Each of the first three moves recomputes
    `Brand.counted_unit_count`, re-runs the coverage determination on the
    `OPERATING_ONLY` basis, and recomputes `compliance_posture`". "if
    `counted_unit_count` is at least twenty, `coverage_status` is `COVERED` and
    `coverage_reason` is `COVERED_BY_UNIT_COUNT`."

    Design: Corner/state_machines/establishment_planned_to_operating_flips_brand_coverage_at_twenty_units
    """
    authority, brand, officer = _authority_and_brand(api)
    validate_success(
        api.create_menu_item(
            menu_item_payload(brand_id=brand["id"], name="Grill Sandwich"), officer
        ),
        201,
    )
    batch = validate_success(
        api.create_establishment_batch(
            brand["id"],
            establishment_batch_payload(
                jurisdiction_id=authority["id"],
                unit_count=COVERED_UNIT_THRESHOLD - 1,
                unit_label_prefix="ID-B",
            ),
            PLATFORM_ADMIN,
        ),
        201,
    )
    assert batch["created_count"] == COVERED_UNIT_THRESHOLD - 1
    assert batch["brand_counted_unit_count"] == COVERED_UNIT_THRESHOLD - 1
    assert batch["brand_coverage_status"] == COVERAGE_NOT_COVERED

    planned = _register_unit(
        api, brand["id"], authority["id"], "ID-0020", unit_status=UNIT_PLANNED
    )
    assert_brand_counters(
        validate_unpaginated(api.get_brand(brand["id"], officer)),
        counted_unit_count=COVERED_UNIT_THRESHOLD - 1,
        coverage_status=COVERAGE_NOT_COVERED,
        coverage_reason=REASON_BELOW_UNIT_THRESHOLD,
        compliance_posture=POSTURE_EXEMPT,
    )

    opened = validate_unpaginated(
        api.change_establishment_status(
            planned["id"],
            status_change_payload(
                new_unit_status=UNIT_OPERATING, effective_note="Grand opening"
            ),
            officer,
        )
    )

    assert opened["unit_status"] == UNIT_OPERATING
    assert_brand_counters(
        validate_unpaginated(api.get_brand(brand["id"], officer)),
        counted_unit_count=COVERED_UNIT_THRESHOLD,
        coverage_status=COVERAGE_COVERED,
        coverage_reason=REASON_COVERED_BY_UNIT_COUNT,
        compliance_posture=POSTURE_COMPLIANT,
        standard_item_count=1,
    )


def test_a_permanently_closed_unit_cannot_be_reopened(api):
    """PRD §3.1: "`PERMANENTLY_CLOSED` is terminal; a request that would move a
    unit already in it fails on the terminal-lockdown rung." PRD §2.6 rung 10:
    "The row the request would move is not already in a terminal state for the
    state field being moved, else `ERR_ALREADY_TERMINAL`."

    Design: Corner/state_machines/establishment_permanently_closed_is_terminal_and_rejects_reopening
    """
    authority, brand, officer = _authority_and_brand(api)
    unit = _register_unit(api, brand["id"], authority["id"], "ID-0001")

    closed = validate_unpaginated(
        api.change_establishment_status(
            unit["id"],
            status_change_payload(
                new_unit_status=UNIT_PERMANENTLY_CLOSED, effective_note="Lease ended"
            ),
            officer,
        )
    )
    assert closed["unit_status"] == UNIT_PERMANENTLY_CLOSED
    assert closed["board_count"] == 0

    validate_error(
        api.change_establishment_status(
            unit["id"],
            status_change_payload(
                new_unit_status=UNIT_OPERATING, effective_note="Reopening attempt"
            ),
            officer,
        ),
        ERR_ALREADY_TERMINAL,
        409,
    )

    assert validate_unpaginated(api.get_establishment(unit["id"], officer))[
        "unit_status"
    ] == UNIT_PERMANENTLY_CLOSED
    assert_brand_counters(
        validate_unpaginated(api.get_brand(brand["id"], officer)),
        counted_unit_count=0,
        coverage_status=COVERAGE_NOT_COVERED,
    )


def test_a_live_citation_blocks_permanent_closure_but_not_a_temporary_one(api):
    """PRD §2.6 rung 40: "When the requested `new_unit_status` is
    `PERMANENTLY_CLOSED`, no enforcement file of that unit is in `OPEN`,
    `RESPONSE_SUBMITTED`, `INFO_REQUESTED`, `ESCALATED` or `PENALTY_ASSESSED`,
    else `ERR_UNIT_HAS_OPEN_ENFORCEMENT`. Applies to the unit status change, and
    only for the `PERMANENTLY_CLOSED` target — moves to `OPERATING` and
    `TEMPORARILY_CLOSED` are not gated by it."

    Design: Corner/state_machines/establishment_permanent_closure_blocked_while_a_citation_is_live
    """
    authority, brand, officer = _authority_and_brand(api)
    unit = _register_unit(api, brand["id"], authority["id"], "ID-0001")
    regulator = make_regulator_headers(authority["id"])

    citation = validate_success(
        api.create_enforcement_action(
            enforcement_action_payload(
                establishment_id=unit["id"],
                citation_code=CITATION_ALLERGEN_MATRIX_MISSING,
                inspection_note="No allergen binder on site",
            ),
            regulator,
        ),
        201,
    )
    # PRD 3.9: the file copies its jurisdiction_id from the cited establishment
    # at opening time rather than taking it from the request.
    assert citation["status"] == ACTION_OPEN
    assert citation["jurisdiction_id"] == authority["id"]
    assert_instant_equals(citation["opened_at"], CLOCK_EPOCH_COMPACT, "opened_at")
    assert citation["penalty_total_cents"] == 0

    validate_error(
        api.change_establishment_status(
            unit["id"],
            status_change_payload(
                new_unit_status=UNIT_PERMANENTLY_CLOSED,
                effective_note="Attempted closure with a live citation",
            ),
            officer,
        ),
        ERR_UNIT_HAS_OPEN_ENFORCEMENT,
        409,
    )
    assert validate_unpaginated(api.get_establishment(unit["id"], officer))[
        "unit_status"
    ] == UNIT_OPERATING

    paused = validate_unpaginated(
        api.change_establishment_status(
            unit["id"],
            status_change_payload(
                new_unit_status=UNIT_TEMPORARILY_CLOSED,
                effective_note="Seasonal closure",
            ),
            officer,
        )
    )
    assert paused["unit_status"] == UNIT_TEMPORARILY_CLOSED

    rows, _meta = validate_paginated(
        api.list_establishment_enforcement_actions(
            unit["id"], regulator, params={"status": ACTION_OPEN}
        )
    )
    assert ids_of(rows) == [citation["id"]]


# ---------------------------------------------------------------------------
# The recipe sheet and its single decision
# ---------------------------------------------------------------------------
def _brand_item_and_draft_recipe(
    api: ApiClient,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, str]]:
    set_clock(api)
    brand = make_brand(api)
    officer = make_brand_officer_headers(brand["id"])
    item = validate_success(
        api.create_menu_item(
            menu_item_payload(brand_id=brand["id"], name="Grill Sandwich"), officer
        ),
        201,
    )
    recipe = validate_success(
        api.create_recipe(
            item["id"],
            recipe_payload(expected_menu_item_version=item["version"]),
            ANALYST_SUBMITTER,
        ),
        201,
    )
    return brand, item, recipe, officer


def test_a_freshly_opened_recipe_version_starts_draft_with_nothing_computed(api):
    """PRD §3.3: "The new row starts with `status` `DRAFT`, `revision_round` 0,
    `supersedes_recipe_id` null, `component_count` 0, `computed_base_calories` 0,
    `computed_declared_min`, `computed_declared_max`, `computed_sodium_mg` and
    `approved_at` all null, and `version_no` set to 1 for the item's first
    recipe". PRD §3.2: "A `STANDARD` item gets `labeling_exempt` false and
    `labeling_status` `DECLARATION_PENDING`."

    Design: Corner/state_machines/recipe_initial_state_is_draft_with_zeroed_counters
    """
    _brand, item, recipe, officer = _brand_item_and_draft_recipe(api)

    assert recipe["status"] == RECIPE_DRAFT
    assert recipe["menu_item_id"] == item["id"]
    assert recipe["version_no"] == 1
    assert recipe["revision_round"] == 0
    assert recipe["component_count"] == 0
    assert_numeric_equals(recipe["computed_base_calories"], 0, "computed_base_calories")
    assert_fields_are_none(
        recipe,
        [
            "computed_declared_min",
            "computed_declared_max",
            "computed_sodium_mg",
            "supersedes_recipe_id",
            "approved_at",
        ],
        "a DRAFT recipe",
    )

    stored_item = validate_unpaginated(api.get_menu_item(item["id"], officer))
    assert_item_declaration(
        stored_item, labeling_status=LABELING_DECLARATION_PENDING, labeling_exempt=False
    )
    assert_fields_are_none(
        stored_item, ["declared_calorie_max"], "an item awaiting its first declaration"
    )


def test_a_recipe_in_analysis_refuses_new_components_and_a_second_submission(api):
    """PRD §3.3: "Components may be added only while the recipe is `DRAFT`; an
    attempt against any other status is refused with `ERR_RECIPE_NOT_DRAFT`."
    PRD §2.6 rung 12: "The recipe's `status` is `DRAFT`, else
    `ERR_RECIPE_NOT_DRAFT`. Applies to component addition and analysis
    submission."

    Design: Corner/state_machines/recipe_component_add_and_resubmit_while_analysis_pending_returns_recipe_not_draft
    """
    _brand, _item, recipe, officer = _brand_item_and_draft_recipe(api)
    validate_success(
        api.add_recipe_component(
            recipe["id"], chicken_breast_component(), ANALYST_SUBMITTER
        ),
        201,
    )

    analysis = validate_success(
        api.submit_for_analysis(
            recipe["id"],
            submit_for_analysis_payload(method=METHOD_DATABASE),
            ANALYST_SUBMITTER,
        ),
        201,
    )
    assert analysis["status"] == ANALYSIS_SUBMITTED
    assert analysis["recipe_id"] == recipe["id"]
    assert analysis["method"] == METHOD_DATABASE
    assert analysis["submitted_by_user_id"] == ANALYST_SUBMITTER_USER_ID

    pending = validate_unpaginated(api.get_recipe(recipe["id"], officer))
    assert pending["status"] == RECIPE_ANALYSIS_PENDING
    assert_numeric_equals(
        pending["computed_base_calories"], "196.00", "computed_base_calories"
    )

    validate_error(
        api.add_recipe_component(
            recipe["id"], brioche_bun_component(), ANALYST_SUBMITTER
        ),
        ERR_RECIPE_NOT_DRAFT,
        409,
    )
    validate_error(
        api.submit_for_analysis(
            recipe["id"],
            submit_for_analysis_payload(method=METHOD_DATABASE),
            ANALYST_SUBMITTER,
        ),
        ERR_RECIPE_NOT_DRAFT,
        409,
    )

    assert validate_unpaginated(api.get_recipe(recipe["id"], officer))[
        "component_count"
    ] == 1
    _rows, meta = validate_paginated(
        api.list_recipe_nutrition_analyses(recipe["id"], ANALYST_SUBMITTER)
    )
    assert meta["total_count"] == 1


def test_an_analysis_accepts_exactly_one_decision(api):
    """PRD §3.4: "A decision against an analysis whose `status` is no longer
    `SUBMITTED` is refused with `ERR_ANALYSIS_ALREADY_DECIDED`." "The analysis
    moves to `CERTIFIED` with `certified_at` stamped from the logical clock,
    `decided_by_user_id` and `decision_note` written, and the declared figures
    `declared_calorie_min`, `declared_calorie_max` and `declared_sodium_mg`
    snapshotted onto the analysis row so that the certified numbers survive later
    recipe churn."

    Design: Corner/state_machines/nutrition_analysis_second_decision_returns_already_decided
    """
    _brand, item, recipe, officer = _brand_item_and_draft_recipe(api)
    validate_success(
        api.add_recipe_component(
            recipe["id"], chicken_breast_component(), ANALYST_SUBMITTER
        ),
        201,
    )
    analysis = validate_success(
        api.submit_for_analysis(
            recipe["id"], submit_for_analysis_payload(), ANALYST_SUBMITTER
        ),
        201,
    )

    certified = validate_unpaginated(
        api.decide_analysis(
            analysis["id"],
            analysis_decision_payload(decision_note="Database values verified"),
            ANALYST_CERTIFIER,
        )
    )
    assert certified["status"] == ANALYSIS_CERTIFIED
    assert certified["decided_by_user_id"] != ANALYST_SUBMITTER_USER_ID
    assert_instant_equals(certified["certified_at"], CLOCK_EPOCH_COMPACT, "certified_at")
    assert certified["declared_calorie_min"] == 200
    assert certified["declared_calorie_max"] == 200
    assert certified["declared_sodium_mg"] == 340

    assert validate_unpaginated(api.get_recipe(recipe["id"], officer))[
        "status"
    ] == RECIPE_APPROVED
    assert_item_declaration(
        validate_unpaginated(api.get_menu_item(item["id"], officer)),
        labeling_status=LABELING_DECLARED,
        approved_recipe_version_no=1,
    )

    validate_error(
        api.decide_analysis(
            analysis["id"],
            analysis_decision_payload(
                decision_note="Replay of the same certification"
            ),
            ANALYST_CERTIFIER,
        ),
        ERR_ANALYSIS_ALREADY_DECIDED,
        409,
    )

    replayed = validate_unpaginated(
        api.get_nutrition_analysis(analysis["id"], ANALYST_CERTIFIER)
    )
    assert replayed["decision_note"] == "Database values verified"
    assert_item_declaration(
        validate_unpaginated(api.get_menu_item(item["id"], officer)),
        approved_recipe_version_no=1,
        declared_calorie_max=200,
    )


def test_the_fourth_rejection_ends_the_revision_loop_for_good(api):
    """PRD §3.4: "While `revision_round` is below 3, the recipe returns from
    `ANALYSIS_PENDING` to `DRAFT` with `revision_round` incremented by 1 and
    becomes editable again so further components can be added". "When
    `revision_round` is already exactly 3, the recipe goes instead to `REJECTED`,
    which is terminal: that version can never be resubmitted, and a fresh version
    must be opened." "a `REJECT` from that same analyst is entirely permitted."

    Design: Corner/state_machines/recipe_rejected_on_the_fourth_review_round_is_terminal
    """
    _brand, item, recipe, officer = _brand_item_and_draft_recipe(api)
    validate_success(
        api.add_recipe_component(
            recipe["id"], chicken_breast_component(), ANALYST_SUBMITTER
        ),
        201,
    )

    notes = (
        "Missing supplier documentation",
        "Serving weight still unverified",
        "Third round still incomplete",
    )
    for expected_round, note in enumerate(notes, start=1):
        analysis = validate_success(
            api.submit_for_analysis(
                recipe["id"], submit_for_analysis_payload(), ANALYST_SUBMITTER
            ),
            201,
        )
        validate_unpaginated(
            api.decide_analysis(
                analysis["id"],
                analysis_decision_payload(decision=DECISION_REJECT, decision_note=note),
                ANALYST_SUBMITTER,
            )
        )
        returned = validate_unpaginated(api.get_recipe(recipe["id"], officer))
        assert returned["status"] == RECIPE_DRAFT
        assert returned["revision_round"] == expected_round

    fourth = validate_success(
        api.submit_for_analysis(
            recipe["id"], submit_for_analysis_payload(), ANALYST_SUBMITTER
        ),
        201,
    )
    decided = validate_unpaginated(
        api.decide_analysis(
            fourth["id"],
            analysis_decision_payload(
                decision=DECISION_REJECT, decision_note="Fourth round - version abandoned"
            ),
            ANALYST_SUBMITTER,
        )
    )
    assert decided["status"] == ANALYSIS_REJECTED

    abandoned = validate_unpaginated(api.get_recipe(recipe["id"], officer))
    assert abandoned["status"] == RECIPE_REJECTED
    assert abandoned["revision_round"] == 3

    stored_item = validate_unpaginated(api.get_menu_item(item["id"], officer))
    assert_item_declaration(
        stored_item, labeling_status=LABELING_DECLARATION_PENDING
    )
    assert_fields_are_none(
        stored_item, ["declared_calorie_max"], "an item whose only version was rejected"
    )

    validate_error(
        api.submit_for_analysis(
            recipe["id"], submit_for_analysis_payload(), ANALYST_SUBMITTER
        ),
        ERR_ALREADY_TERMINAL,
        409,
    )

    rows, meta = validate_paginated(
        api.list_recipe_nutrition_analyses(recipe["id"], ANALYST_SUBMITTER)
    )
    assert meta["total_count"] == 4
    assert [row["status"] for row in rows] == [ANALYSIS_REJECTED] * 4


# ---------------------------------------------------------------------------
# Variance relief: a two-step machine with a terminal denial
# ---------------------------------------------------------------------------
def _brand_before_one_authority(
    api: ApiClient, code: str = "NY-VAR"
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, str], Dict[str, str]]:
    set_clock(api)
    authority = make_jurisdiction(
        api,
        code=code,
        name="New York",
        preemption_mode=PREEMPTION_VARIANCE_ALLOWED,
        extra_requirement=EXTRA_REQUIREMENT_NONE,
        enforcement_tier=TIER_FEDERAL_ALIGNED,
    )
    brand = make_brand(api)
    return (
        authority,
        brand,
        make_brand_officer_headers(brand["id"]),
        make_regulator_headers(authority["id"]),
    )


def test_relief_cannot_be_granted_before_the_review_is_opened(api):
    """PRD §3.8: "The state machine is deliberately two-step: `OPEN_REVIEW` is
    defined only from `SUBMITTED` and moves the request to `UNDER_REVIEW`, while
    `GRANTED` and `DENIED` are defined only from `UNDER_REVIEW`. A regulator
    therefore cannot grant straight out of `SUBMITTED`, and any decision requested
    from the wrong state is refused with `ERR_VARIANCE_STATE_INVALID`."

    Design: Corner/state_machines/variance_grant_without_opening_review_returns_variance_state_invalid
    """
    authority, brand, officer, regulator = _brand_before_one_authority(api)

    filed = validate_success(
        api.create_variance_request(
            variance_request_payload(
                brand_id=brand["id"],
                jurisdiction_id=authority["id"],
                requirement_code=REQUIREMENT_WRITTEN_INFO_FORMAT,
                justification="Binder reprint pending",
            ),
            officer,
        ),
        201,
    )
    assert filed["status"] == VARIANCE_SUBMITTED
    assert_fields_are_none(
        filed,
        ["effective_start_date", "effective_end_date"],
        "a freshly filed variance request",
    )

    validate_error(
        api.decide_variance_request(
            filed["id"],
            variance_decision_payload(
                decision=VARIANCE_DECISION_GRANTED,
                decision_note="Skipping the review step",
            ),
            regulator,
        ),
        ERR_VARIANCE_STATE_INVALID,
        409,
    )
    refused = validate_unpaginated(api.get_variance_request(filed["id"], officer))
    assert refused["status"] == VARIANCE_SUBMITTED
    assert_fields_are_none(
        refused, ["effective_start_date"], "a request that was never opened"
    )

    docketed = validate_unpaginated(
        api.decide_variance_request(
            filed["id"],
            variance_decision_payload(
                decision=VARIANCE_DECISION_OPEN_REVIEW, decision_note="Docketed"
            ),
            regulator,
        )
    )
    assert docketed["status"] == VARIANCE_UNDER_REVIEW
    assert docketed["decided_by_user_id"] == authority["id"]

    granted = validate_unpaginated(
        api.decide_variance_request(
            filed["id"],
            variance_decision_payload(
                decision=VARIANCE_DECISION_GRANTED,
                decision_note="Relief granted as requested",
            ),
            regulator,
        )
    )
    assert granted["status"] == VARIANCE_GRANTED
    assert_date_only(granted["effective_start_date"], "2026-09-01")
    assert_date_only(granted["effective_end_date"], "2026-09-30")


def test_a_denied_request_cannot_be_granted_on_appeal(api):
    """PRD §3.8: "`DENIED` and `EXPIRED` are terminal states; a decision against a
    request already in one of them fails on the terminal-lockdown rung." "Where a
    denial is issued instead, `decision_note` is recorded and both effective dates
    stay null."

    Design: Corner/state_machines/variance_denied_is_terminal_and_cannot_be_granted_afterwards
    """
    authority, brand, officer, regulator = _brand_before_one_authority(api)
    filed = validate_success(
        api.create_variance_request(
            variance_request_payload(
                brand_id=brand["id"],
                jurisdiction_id=authority["id"],
                requirement_code=REQUIREMENT_ADDED_SUGAR_ICON,
                justification="Icon artwork not yet approved",
            ),
            officer,
        ),
        201,
    )
    validate_unpaginated(
        api.decide_variance_request(
            filed["id"],
            variance_decision_payload(decision=VARIANCE_DECISION_OPEN_REVIEW),
            regulator,
        )
    )

    denied = validate_unpaginated(
        api.decide_variance_request(
            filed["id"],
            variance_decision_payload(
                decision=VARIANCE_DECISION_DENIED,
                decision_note="No statutory basis for relief",
            ),
            regulator,
        )
    )
    assert denied["status"] == VARIANCE_DENIED
    assert_fields_are_none(
        denied,
        ["effective_start_date", "effective_end_date"],
        "a denied variance request",
    )

    validate_error(
        api.decide_variance_request(
            filed["id"],
            variance_decision_payload(
                decision=VARIANCE_DECISION_GRANTED,
                decision_note="Reversal attempt",
                effective_start_date="2026-09-01",
                effective_end_date="2026-09-30",
            ),
            regulator,
        ),
        ERR_ALREADY_TERMINAL,
        409,
    )

    unchanged = validate_unpaginated(api.get_variance_request(filed["id"], officer))
    assert unchanged["status"] == VARIANCE_DENIED
    assert_fields_are_none(
        unchanged, ["effective_start_date"], "a denied request after the appeal"
    )


# ---------------------------------------------------------------------------
# Publication is a one-way door, for packets and for boards alike
# ---------------------------------------------------------------------------
def _covered_brand_with_one_certified_item(api: ApiClient) -> Tuple[Env, Dict[str, Any]]:
    env = seed_registry(
        api,
        code="ID-MIN",
        name="Idaho",
        preemption_mode=PREEMPTION_PREEMPTED,
        unit_label="ID-0001",
        unit_label_prefix="ID-B",
    )
    item = make_menu_item(env)
    certify_recipe_version(env, item["id"], [chicken_breast_component()])
    return env, item


def test_a_published_packet_is_superseded_rather_than_republished(api):
    """PRD §3.5: "It requires the packet's `status` to be `DRAFT`, on pain of
    `ERR_PACKET_NOT_DRAFT` — an already `PUBLISHED` or `STALE` packet cannot be
    republished, and a fresh packet must be drafted instead." "On success the
    packet moves from `DRAFT` to `PUBLISHED`, `published_at` is stamped from the
    logical clock, `Brand.has_published_disclosure_packet` becomes true, and any
    other packet of the same brand whose `status` was `PUBLISHED` or `STALE` moves
    to `SUPERSEDED` with its `version` incremented by 1. `SUPERSEDED` is
    terminal."

    Design: Corner/state_machines/disclosure_packet_second_publish_returns_packet_not_draft_then_supersede
    """
    env, _item = _covered_brand_with_one_certified_item(api)

    first = draft_packet(env)
    assert first["status"] == PACKET_DRAFT
    assert first["packet_version"] == 1
    assert first["covered_item_count"] == 1
    assert first["allergen_matrix_complete"] is True
    assert first["cross_contact_statement_required"] is False

    published = publish_packet(env, first["id"])
    assert published["status"] == PACKET_PUBLISHED
    assert_instant_equals(published["published_at"], CLOCK_EPOCH_COMPACT, "published_at")
    assert env.read_brand()["has_published_disclosure_packet"] is True

    validate_error(
        env.api.publish_disclosure_packet(first["id"], env.officer),
        ERR_PACKET_NOT_DRAFT,
        409,
    )

    second = draft_packet(
        env,
        written_info_channels=[
            CHANNEL_IN_STORE_BINDER,
            CHANNEL_WEBSITE,
            CHANNEL_PHONE_LINE,
        ],
    )
    assert second["packet_version"] == 2
    assert publish_packet(env, second["id"])["status"] == PACKET_PUBLISHED

    superseded = env.read_packet(first["id"])
    assert superseded["status"] == PACKET_SUPERSEDED
    assert superseded["version"] == published["version"] + 1

    validate_error(
        env.api.publish_disclosure_packet(first["id"], env.officer),
        ERR_ALREADY_TERMINAL,
        409,
    )

    rows, _meta = validate_paginated(
        env.api.list_brand_disclosure_packets(
            env.brand_id, env.officer, params={"status": PACKET_PUBLISHED}
        )
    )
    assert ids_of(rows) == [second["id"]]


def test_a_published_board_refuses_a_second_publish_and_a_new_line(api):
    """PRD §2.6 rung 11: "The board's `publication_status` is `DRAFT`, else
    `ERR_BOARD_NOT_DRAFT`. Applies to listing creation and board publication.
    Re-publishing an already `PUBLISHED` board therefore fails here, before any
    display-window arithmetic is attempted." PRD §3.6: "Publication moves
    `publication_status` from `DRAFT` to `PUBLISHED`, writes `effective_from` and
    `effective_to` from the request, refreshes every line's
    `declared_min_snapshot`, `declared_max_snapshot` and `display_calorie_text`
    from its item's current declaration, and recomputes
    `Establishment.board_count`."

    Design: Corner/state_machines/menu_board_publish_is_not_idempotent_and_freezes_its_listings
    """
    env, item = _covered_brand_with_one_certified_item(api)
    draft_and_publish_packet(env)
    special = make_menu_item(
        env,
        name="Soup of the Day",
        item_class=ITEM_CLASS_DAILY_SPECIAL,
        first_offered_on="2026-08-01",
    )
    board = published_board(env, item["id"])

    live = validate_unpaginated(
        env.api.get_menu_board(board.board_id, env.officer)
    )
    assert live["publication_status"] == PUBLICATION_PUBLISHED
    assert_instant_equals(live["effective_from"], CLOCK_EPOCH_COMPACT, "effective_from")
    assert live["effective_to"] is None
    assert live["calorie_compliance_status"] == COMPLIANCE_CURRENT
    assert live["listing_count"] == 1

    line = env.read_listing(board.board_id, board.listing["id"])
    assert line["declared_min_snapshot"] == 200
    assert line["declared_max_snapshot"] == 200
    assert line["display_calorie_text"] == expected_display_calorie_text(200, 200)
    assert env.read_establishment()["board_count"] == 1

    validate_error(
        env.api.publish_menu_board(
            board.board_id, board_publish_payload(), env.publisher
        ),
        ERR_BOARD_NOT_DRAFT,
        409,
    )
    validate_error(
        env.api.create_listing(
            board.board_id, listing_payload(special["id"]), env.publisher
        ),
        ERR_BOARD_NOT_DRAFT,
        409,
    )

    assert validate_unpaginated(
        env.api.get_menu_board(board.board_id, env.officer)
    )["listing_count"] == 1
    rows, _meta = validate_paginated(
        env.api.list_menu_board_listings(board.board_id, env.publisher)
    )
    assert ids_of(rows) == [board.listing["id"]]
