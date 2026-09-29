"""Version guards, and the promise that nothing lags behind a write.

The first four cases drive the two optimistic-concurrency guards of §2.8 with a
version that a cascade has quietly moved on, then replay them with the
refreshed one. The last two check the consistency model from the other side: a
write's own response already carries every derived figure the cascade produced,
and a read issued immediately afterwards agrees with it field for field.
"""

from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_STALE_BRAND_VERSION,
    ERR_STALE_MENU_ITEM_VERSION,
)
from test_helpers.assertions import assert_numeric_equals, validate_unpaginated
from test_helpers.constants import (
    ALLERGEN_WHEAT,
    ANALYSIS_CERTIFIED,
    CHANNEL_IN_STORE_BINDER,
    COVERAGE_COVERED,
    COVERAGE_NOT_COVERED,
    CROSS_CONTACT_NONE,
    DECISION_CERTIFY,
    ITEM_CLASS_STANDARD,
    ITEM_CLASS_TEST_MARKET,
    LABELING_DECLARED,
    LABELING_NOT_REQUIRED,
    METHOD_DATABASE,
    PACKET_DRAFT,
    POSTURE_COMPLIANT,
    PREEMPTION_PREEMPTED,
    REASON_BELOW_UNIT_THRESHOLD,
    REASON_COVERED_BY_UNIT_COUNT,
    RECIPE_DRAFT,
    ROLE_BASE,
    UNIT_OPERATING,
    VARIABLE_NONE,
)
from test_helpers.factories import (
    analysis_decision_payload,
    component_payload,
    disclosure_packet_payload,
    establishment_batch_payload,
    menu_item_payload,
    offer_window_payload,
    recipe_payload,
    submit_for_analysis_payload,
)
from test_helpers.fixtures import (
    Env,
    make_brand,
    make_establishment,
    make_jurisdiction,
    set_clock,
)
from test_helpers.test_users import (
    ANALYST_CERTIFIER,
    ANALYST_SUBMITTER,
    PLATFORM_ADMIN,
    make_brand_officer_headers,
    make_regulator_headers,
)

DECLARED_CALORIES = 100
DECLARED_SODIUM_MG = 200


def _sandwich_as_served() -> Dict[str, Any]:
    """One BASE component of 100 g at 100 Cal and 200 mg sodium per 100 g."""
    return component_payload(
        component_name="Sandwich as served",
        role=ROLE_BASE,
        grams=100,
        calories_per_100g=100,
        sodium_mg_per_100g=DECLARED_SODIUM_MG,
        added_sugar_g_per_100g=0,
        allergen_group=ALLERGEN_WHEAT,
        cross_contact_risk=CROSS_CONTACT_NONE,
    )


def _test_market_item_with_one_offer_window(
    api: ApiClient,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """A TEST_MARKET item whose version has been moved on by an append."""
    set_clock(api)
    brand = make_brand(api)
    officer = make_brand_officer_headers(brand["id"])
    created = validate_unpaginated(
        api.create_menu_item(
            menu_item_payload(
                brand_id=brand["id"],
                name="Test Market Melt",
                item_class=ITEM_CLASS_TEST_MARKET,
                variable_type=VARIABLE_NONE,
                first_offered_on="2026-04-01",
            ),
            officer,
        ),
        201,
    )
    appended = validate_unpaginated(
        api.append_offer_window(
            created["id"],
            offer_window_payload(start_date="2026-04-01", end_date="2026-04-20"),
            officer,
        )
    )
    return brand, created, appended


def test_an_offer_window_append_makes_the_observed_item_version_stale(api):
    """The version read at item creation no longer opens a recipe version.

    PRD 2.8: "Recipe-version creation against a menu item requires
    `expected_menu_item_version`, carrying the `version` of the `MenuItem` that
    the client last observed. If it does not equal the item's current
    `version`, the request is rejected with `ERR_STALE_MENU_ITEM_VERSION` and
    HTTP 412." The append is what moves it, since PRD 3.2 says "An offer-window
    append supplies a `start_date` and an `end_date` and adds one entry to the
    item's append-only `offer_windows` list" and "Each append immediately
    recomputes `cumulative_offered_days` by the same merge described next."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_menu_item_version_blocks_a_new_recipe_version
    """
    brand, created, appended = _test_market_item_with_one_offer_window(api)
    assert appended["version"] > created["version"], (
        "the offer-window append must increment the item version: "
        f"{created['version']} then {appended['version']}"
    )
    assert appended["cumulative_offered_days"] == 20
    assert appended["labeling_exempt"] is True
    assert appended["labeling_status"] == LABELING_NOT_REQUIRED

    validate_error(
        api.create_recipe(
            created["id"],
            recipe_payload(
                expected_menu_item_version=created["version"],
                change_note="Branching from a stale view of the item",
            ),
            ANALYST_SUBMITTER,
        ),
        ERR_STALE_MENU_ITEM_VERSION,
        412,
    )

    rows, meta = validate_paginated(
        api.list_recipes(
            make_brand_officer_headers(brand["id"]),
            params={"menu_item_id": created["id"], "limit": 10},
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_the_refreshed_item_version_opens_the_first_recipe_version(api):
    """Replaying the guard with the version the append reported is accepted.

    PRD 3.3: "Opening a new recipe version for a menu item requires
    `expected_menu_item_version` — the optimistic-concurrency guard of §2.8 —
    and a `change_note` of 1 to 240 non-blank characters describing what changed
    against the prior version." The accepted call's own output is fixed there
    too: "The new row starts with `status` `DRAFT`, `revision_round` 0,
    `supersedes_recipe_id` null, `component_count` 0" with "`version_no` set to
    1 for the item's first recipe or to the item's highest existing `version_no`
    plus 1 thereafter."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_menu_item_version_blocks_a_new_recipe_version
    """
    brand, created, appended = _test_market_item_with_one_offer_window(api)

    recipe = validate_unpaginated(
        api.create_recipe(
            created["id"],
            recipe_payload(
                expected_menu_item_version=appended["version"],
                change_note="Initial specification",
            ),
            ANALYST_SUBMITTER,
        ),
        201,
    )

    assert recipe["menu_item_id"] == created["id"]
    assert recipe["version_no"] == 1
    assert recipe["revision_round"] == 0
    assert recipe["status"] == RECIPE_DRAFT
    assert recipe["supersedes_recipe_id"] is None

    rows, meta = validate_paginated(
        api.list_recipes(
            make_brand_officer_headers(brand["id"]),
            params={"menu_item_id": created["id"], "limit": 10},
        )
    )
    assert [row["id"] for row in rows] == [recipe["id"]]
    assert meta["total_count"] == 1

    item = validate_unpaginated(api.get_menu_item(created["id"], PLATFORM_ADMIN))
    assert item["cumulative_offered_days"] == 20
    assert item["labeling_exempt"] is True


def _nineteen_certified_units_then_a_twentieth(
    api: ApiClient,
) -> Tuple[Env, int, int]:
    """A certified STANDARD item, 19 units read, then a twentieth unit added.

    Returns the environment together with the brand `version` observed while
    the estate stood at 19 units and the `version` observed after the
    twentieth landed.
    """
    set_clock(api)
    jurisdiction = make_jurisdiction(
        api, code="ID-MIN", name="Idaho", preemption_mode=PREEMPTION_PREEMPTED
    )
    brand = make_brand(api)
    batch = validate_unpaginated(
        api.create_establishment_batch(
            brand["id"],
            establishment_batch_payload(
                jurisdiction_id=jurisdiction["id"],
                unit_count=19,
                unit_status=UNIT_OPERATING,
                unit_label_prefix="ID-B",
            ),
            PLATFORM_ADMIN,
        ),
        201,
    )
    first_unit = validate_unpaginated(
        api.get_establishment(batch["first_created_establishment_id"], PLATFORM_ADMIN)
    )
    env = Env(api=api, jurisdiction=jurisdiction, brand=brand, establishment=first_unit)

    item = validate_unpaginated(
        api.create_menu_item(
            menu_item_payload(
                brand_id=brand["id"],
                name="Grill Sandwich",
                item_class=ITEM_CLASS_STANDARD,
                variable_type=VARIABLE_NONE,
                first_offered_on="2026-01-05",
            ),
            env.officer,
        ),
        201,
    )
    recipe = validate_unpaginated(
        api.create_recipe(
            item["id"],
            recipe_payload(
                expected_menu_item_version=item["version"],
                change_note="Initial specification",
            ),
            ANALYST_SUBMITTER,
        ),
        201,
    )
    validate_unpaginated(
        api.add_recipe_component(
            recipe["id"], _sandwich_as_served(), ANALYST_SUBMITTER
        ),
        201,
    )
    analysis = validate_unpaginated(
        api.submit_for_analysis(
            recipe["id"],
            submit_for_analysis_payload(method=METHOD_DATABASE),
            ANALYST_SUBMITTER,
        ),
        201,
    )
    validate_unpaginated(
        api.decide_analysis(
            analysis["id"],
            analysis_decision_payload(decision=DECISION_CERTIFY),
            ANALYST_CERTIFIER,
        )
    )

    at_nineteen = env.read_brand()
    assert at_nineteen["coverage_status"] == COVERAGE_NOT_COVERED
    assert at_nineteen["coverage_reason"] == REASON_BELOW_UNIT_THRESHOLD

    make_establishment(
        api,
        brand_id=brand["id"],
        jurisdiction_id=jurisdiction["id"],
        unit_label="ID-B-0020",
        unit_status=UNIT_OPERATING,
        headers=env.officer,
    )
    at_twenty = env.read_brand()
    assert at_twenty["coverage_status"] == COVERAGE_COVERED
    return env, at_nineteen["version"], at_twenty["version"]


def test_a_brand_version_observed_at_nineteen_units_no_longer_drafts_a_packet(api):
    """The twentieth unit moves the brand, so the earlier guard is stale.

    PRD 2.8: "Packet drafting against a brand requires `expected_brand_version`,
    carrying the `version` of the `Brand` that the client last observed. If it
    does not equal the brand's current `version`, the request is rejected with
    `ERR_STALE_BRAND_VERSION` and HTTP 412." PRD 2.6 rung 9 fixes that this
    beats the coverage precondition of rung 20: "Because this rung sits after
    existence and before every state precondition, a stale version against an
    already-terminal parent reports the stale-version error, not a state error."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_brand_version_blocks_a_new_disclosure_packet
    """
    env, brand_v1, brand_v2 = _nineteen_certified_units_then_a_twentieth(api)
    assert brand_v2 > brand_v1, (
        "the twentieth unit must move the brand version: "
        f"{brand_v1} then {brand_v2}"
    )

    validate_error(
        env.api.create_disclosure_packet(
            env.brand_id,
            disclosure_packet_payload(
                expected_brand_version=brand_v1,
                cross_contact_statement="",
                written_info_channels=[CHANNEL_IN_STORE_BINDER],
            ),
            env.officer,
        ),
        ERR_STALE_BRAND_VERSION,
        412,
    )

    rows, meta = validate_paginated(
        env.api.list_brand_disclosure_packets(
            env.brand_id, env.officer, params={"limit": 10}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_the_refreshed_brand_version_drafts_the_brands_first_packet(api):
    """Replaying the guard with the post-twentieth version is accepted.

    PRD 3.5: "The new packet takes `status` `DRAFT`, `published_at` null, and
    `packet_version` set to 1 for the brand's first packet or to the brand's
    highest existing `packet_version` plus 1 thereafter." The synthesis figures
    follow from the one certified item, since "`covered_item_count` is the
    number of those items that actually have a recipe in `APPROVED`" and
    `allergen_matrix_complete` is true when "`covered_item_count` equals the
    brand's `standard_item_count` — that is, when every non-exempt item on the
    menu has a certified recipe behind it." The single component carries no
    cross-contact risk, and "`cross_contact_statement_required` is true when any
    component of any `APPROVED` recipe of any non-exempt item of the brand has a
    `cross_contact_risk` other than `NONE`."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_brand_version_blocks_a_new_disclosure_packet
    """
    env, _brand_v1, brand_v2 = _nineteen_certified_units_then_a_twentieth(api)

    packet = validate_unpaginated(
        env.api.create_disclosure_packet(
            env.brand_id,
            disclosure_packet_payload(
                expected_brand_version=brand_v2,
                cross_contact_statement="",
                written_info_channels=[CHANNEL_IN_STORE_BINDER],
            ),
            env.officer,
        ),
        201,
    )

    assert packet["brand_id"] == env.brand_id
    assert packet["packet_version"] == 1
    assert packet["status"] == PACKET_DRAFT
    assert packet["published_at"] is None
    assert packet["covered_item_count"] == 1
    assert packet["allergen_matrix_complete"] is True
    assert packet["cross_contact_statement_required"] is False

    rows, meta = validate_paginated(
        env.api.list_brand_disclosure_packets(
            env.brand_id, env.officer, params={"limit": 10}
        )
    )
    assert [row["id"] for row in rows] == [packet["id"]]
    assert meta["total_count"] == 1


def _a_submitted_analysis_and_no_units_yet(
    api: ApiClient,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """A STANDARD item whose one-component recipe awaits a decision."""
    set_clock(api)
    jurisdiction = make_jurisdiction(
        api, code="ID-MIN", name="Idaho", preemption_mode=PREEMPTION_PREEMPTED
    )
    brand = make_brand(api)
    officer = make_brand_officer_headers(brand["id"])
    item = validate_unpaginated(
        api.create_menu_item(
            menu_item_payload(
                brand_id=brand["id"],
                name="Grill Sandwich",
                item_class=ITEM_CLASS_STANDARD,
                variable_type=VARIABLE_NONE,
                first_offered_on="2026-01-05",
            ),
            officer,
        ),
        201,
    )
    recipe = validate_unpaginated(
        api.create_recipe(
            item["id"],
            recipe_payload(
                expected_menu_item_version=item["version"],
                change_note="Initial specification",
            ),
            ANALYST_SUBMITTER,
        ),
        201,
    )
    validate_unpaginated(
        api.add_recipe_component(
            recipe["id"], _sandwich_as_served(), ANALYST_SUBMITTER
        ),
        201,
    )
    analysis = validate_unpaginated(
        api.submit_for_analysis(
            recipe["id"],
            submit_for_analysis_payload(method=METHOD_DATABASE),
            ANALYST_SUBMITTER,
        ),
        201,
    )
    return jurisdiction, brand, item, analysis


def _certify(api: ApiClient, analysis_id: str) -> Dict[str, Any]:
    """The certification response itself, not a readback of the row."""
    return validate_unpaginated(
        api.decide_analysis(
            analysis_id,
            analysis_decision_payload(decision=DECISION_CERTIFY),
            ANALYST_CERTIFIER,
        )
    )


def test_the_certification_response_already_carries_the_declared_figures(api):
    """The writing call reports the cascade it caused, and the read agrees.

    PRD 3.4: "The analysis moves to `CERTIFIED` with `certified_at` stamped from
    the logical clock, `decided_by_user_id` and `decision_note` written, and the
    declared figures `declared_calorie_min`, `declared_calorie_max` and
    `declared_sodium_mg` snapshotted onto the analysis row so that the certified
    numbers survive later recipe churn." The item follows in the same operation:
    "the item's `declared_calorie_min`, `declared_calorie_max`,
    `declared_sodium_mg`, `allergen_groups`, `cross_contact_groups` and
    `approved_recipe_version_no` are all rewritten from the newly approved
    recipe, and `labeling_status` moves from `DECLARATION_PENDING` to `DECLARED`
    on a first declaration".

    Design: Corner/consistency_model/derived_cross_aggregate_fields_are_visible_in_the_same_response
    """
    _jurisdiction, brand, item, analysis = _a_submitted_analysis_and_no_units_yet(api)

    decided = _certify(api, analysis["id"])
    assert decided["status"] == ANALYSIS_CERTIFIED
    assert_numeric_equals(
        decided["declared_calorie_min"], DECLARED_CALORIES, "declared_calorie_min"
    )
    assert_numeric_equals(
        decided["declared_calorie_max"], DECLARED_CALORIES, "declared_calorie_max"
    )
    assert_numeric_equals(
        decided["declared_sodium_mg"], DECLARED_SODIUM_MG, "declared_sodium_mg"
    )

    read_back = validate_unpaginated(
        api.get_menu_item(item["id"], make_brand_officer_headers(brand["id"]))
    )
    assert read_back["labeling_status"] == LABELING_DECLARED
    assert_numeric_equals(
        read_back["declared_calorie_min"], DECLARED_CALORIES, "item calorie min"
    )
    assert_numeric_equals(
        read_back["declared_calorie_max"], DECLARED_CALORIES, "item calorie max"
    )
    assert_numeric_equals(
        read_back["declared_sodium_mg"], DECLARED_SODIUM_MG, "item sodium"
    )
    assert read_back["approved_recipe_version_no"] == 1


def test_the_batch_response_already_reports_the_coverage_it_caused(api):
    """Twenty units in one call, and the summary read needs no second pass.

    PRD 3.1: "The response summarises the batch rather than echoing every row:
    `brand_id`, `created_count`, the `unit_status` the batch was created in,
    `first_created_establishment_id`, and the brand's resulting
    `brand_coverage_status` and `brand_counted_unit_count`." and "Coverage is
    re-determined exactly once after the whole batch lands, and the brand's
    `version` increments exactly once — not once per unit." PRD 3.1 also fixes
    that the summary is not a cached view: "a brand's compliance summary is
    recomputed from current rows at read time rather than served from stored
    counters."

    Design: Corner/consistency_model/derived_cross_aggregate_fields_are_visible_in_the_same_response
    """
    jurisdiction, brand, _item, analysis = _a_submitted_analysis_and_no_units_yet(api)
    _certify(api, analysis["id"])

    batch = validate_unpaginated(
        api.create_establishment_batch(
            brand["id"],
            establishment_batch_payload(
                jurisdiction_id=jurisdiction["id"],
                unit_count=20,
                unit_status=UNIT_OPERATING,
                unit_label_prefix="ID-B",
            ),
            PLATFORM_ADMIN,
        ),
        201,
    )
    assert batch["brand_id"] == brand["id"]
    assert batch["created_count"] == 20
    assert batch["unit_status"] == UNIT_OPERATING
    assert batch["brand_coverage_status"] == COVERAGE_COVERED
    assert batch["brand_counted_unit_count"] == 20

    summary = validate_unpaginated(
        api.get_brand_compliance_summary(
            brand["id"], make_regulator_headers(jurisdiction["id"])
        )
    )
    assert summary["brand_id"] == brand["id"]
    assert summary["coverage_status"] == COVERAGE_COVERED
    assert summary["coverage_reason"] == REASON_COVERED_BY_UNIT_COUNT
    assert summary["counted_unit_count"] == 20
    assert summary["standard_item_count"] == 1
    assert summary["compliance_posture"] == POSTURE_COMPLIANT
