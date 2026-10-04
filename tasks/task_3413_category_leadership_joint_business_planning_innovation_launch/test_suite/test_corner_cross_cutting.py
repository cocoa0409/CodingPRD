"""Corner queue — cross-cutting layers: the single OCC-guarded write and the
plan version counter's per-mutation discipline.

Each test translates one non-stub corner-design `cross_cutting_complexity_layers`
instance and cites the PRD sentence that pins the asserted rule. Version
assertions are delta-pinned (each mutation adds exactly 1): the PRD pins the
increment, not the counter's initial value.
"""
from test_helpers import (
    ApiErrorId,
    assert_plan,
    assert_shelf_recommendation,
    create_accepted_analysis,
    create_activate_payload,
    create_category,
    create_plan_payload,
    create_retailer,
    create_shelf_rec_payload,
    get_plan_version,
    make_retailer_buyer_headers,
    setup_accepted_plan,
    setup_activated_plan,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_shelf_rec_create_with_stale_plan_version_refused(
    api, manufacturer_planner_headers, category_advisor_headers
):
    """PRD §2.8: "That request must carry `expected_plan_version`, set to the `version` of the owning `JointBusinessPlan` the client last observed. If the plan's current `version` has advanced past the submitted value, the create is rejected with `ERR_STALE_VERSION` (HTTP 412), and nothing is created."

    The version captured while the plan was ACCEPTED has been advanced past by
    activation, so the create carrying it fails 412 and no recommendation is
    persisted.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_expected_plan_version_returns_412
    """
    scenario = setup_accepted_plan()
    plan_id = scenario["plan"]["id"]
    stale_version = scenario["plan"]["version"]

    activated = validate_success(
        api.activate_plan(plan_id, create_activate_payload(), manufacturer_planner_headers), 200
    )
    assert activated["version"] == stale_version + 1, (
        "activation must advance the plan version past the captured one (PRD §3.1: "
        "'moves the plan `ACCEPTED → ACTIVATED`, and increments its `version`')"
    )
    create_accepted_analysis(plan_id, scenario["retailer"]["id"])

    validate_error(
        api.create_shelf_recommendation(
            plan_id,
            create_shelf_rec_payload(stale_version, title="Stale Reset"),
            category_advisor_headers,
        ),
        ApiErrorId.ERR_STALE_VERSION,
    )

    recs, meta = validate_paginated(
        api.list_shelf_recommendations(plan_id, category_advisor_headers)
    )
    assert recs == [], f"nothing is created on a stale-version refusal, got {recs!r}"
    assert meta["total_count"] == 0


def test_shelf_rec_create_with_fresh_version_bumps_plan_version(
    api, manufacturer_planner_headers, category_advisor_headers
):
    """PRD §3.4: "the plan's currently `PROPOSED` recommendation, if one exists, is auto-superseded to `WITHDRAWN` with its own `version` incremented, and the plan's `version` itself increments by 1, so the next advisor must read afresh before recommending again."
    PRD §3.4: "The newcomer is born `PROPOSED`, with `accepted_at` and `verified_store_count` still null, and the plan's recommendation list can be browsed filtered by `status`."

    A create carrying the plan's current version succeeds 201 / PROPOSED and
    the parent plan's version climbs by exactly 1 — the OCC write-side
    contract.

    Design: Corner/cross_cutting_complexity_layers/occ_fresh_version_succeeds_and_bumps_plan_version
    """
    scenario = setup_activated_plan()
    plan_id = scenario["plan"]["id"]
    create_accepted_analysis(plan_id, scenario["retailer"]["id"])
    version_before = get_plan_version(plan_id)

    resp = api.create_shelf_recommendation(
        plan_id, create_shelf_rec_payload(version_before), category_advisor_headers
    )
    rec = validate_success(resp, 201)
    assert_shelf_recommendation(rec)
    assert rec["status"] == "PROPOSED", f"the newcomer must be born PROPOSED, got {rec['status']}"

    version_after = get_plan_version(plan_id)
    assert version_after == version_before + 1, (
        f"a successful shelf-rec create must bump the plan version by exactly 1: "
        f"{version_before} -> {version_after}"
    )


def test_each_successful_plan_mutation_increments_version_by_one(
    api, manufacturer_planner_headers
):
    """PRD §2.5: "`version` (integer): a system-managed integer that increments by exactly 1 on every mutation of the resource, including the automatic transitions the server performs on its own (supersessions, expirations, cascades)."
    PRD §3.1: "on success the plan's `growth_target_pct` is replaced by the proposed value, `negotiation_round` climbs by 1, and the plan's `version` increments as the plan moves `PROPOSED → COUNTERED`."
    PRD §3.1: "Every successful decision increments the plan's `version`, and a decide call by the wrong party fails with `ERR_NOT_YOUR_MOVE` just as a negotiation call would."
    PRD §3.1: "moves the plan `ACCEPTED → ACTIVATED`, and increments its `version`."

    Create, negotiate, decide, and activate each add exactly 1 to the plan
    version, in order.

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_each_plan_mutation
    """
    retailer = create_retailer()
    category = create_category()
    buyer_headers = make_retailer_buyer_headers(retailer["id"])

    created = validate_success(
        api.create_plan(create_plan_payload(retailer["id"], category["id"]),
                        manufacturer_planner_headers),
        201,
    )
    assert_plan(created)
    v0 = created["version"]

    countered = validate_success(
        api.negotiate_plan(created["id"], {"growth_target_pct": 9}, buyer_headers), 200
    )
    assert_plan(countered)
    assert countered["status"] == "COUNTERED"
    assert countered["version"] == v0 + 1, (
        f"negotiate must add exactly 1: {v0} -> {countered['version']}"
    )

    # From COUNTERED the decision belongs to the ManufacturerPlanner (PRD §3.1).
    accepted = validate_success(
        api.decide_plan(created["id"], {"decision": "ACCEPT"}, manufacturer_planner_headers), 200
    )
    assert_plan(accepted)
    assert accepted["status"] == "ACCEPTED"
    assert accepted["version"] == v0 + 2, (
        f"decide must add exactly 1: {v0 + 1} -> {accepted['version']}"
    )

    activated = validate_success(
        api.activate_plan(created["id"], create_activate_payload(), manufacturer_planner_headers),
        200,
    )
    assert_plan(activated)
    assert activated["status"] == "ACTIVATED"
    assert activated["version"] == v0 + 3, (
        f"activate must add exactly 1: {v0 + 2} -> {activated['version']}"
    )
