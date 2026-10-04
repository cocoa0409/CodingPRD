"""Condition assessment and capital need estimation tests."""
from test_helpers import (
    api_client, TEST_USERS,
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    assert_assessment, assert_capital_item,
    create_capital_item_payload,
    create_target, create_assessment_with_items, submit_assessment,
    accept_assessment,
    make_headers,
)


def _draft_assessment_with_item(item_payloads):
    target = create_target()
    return create_assessment_with_items(target["id"], item_payloads)


def test_capital_need_planning_vs_filing_diverge(api):
    """PRD §3.2: "The planning variant, `planning_estimate_cents`, is the internal
    view: sum the `cost_low_cents` of every item of the assessment in `PLANNED`,
    `SCHEDULED`, or `EXECUTED` status (items that are `SPLIT` or `CANCELLED` are
    excluded), increase the total by a ten percent planning contingency, and round
    half-up to a whole cent. The filing variant, `filing_estimate_cents`, is the
    regulatory view: sum the per-item rounded `midpoint_estimate_cents` over the
    same set of items, increase the total by a fifteen percent filing contingency,
    and round half-up to a whole cent."

    Design: Difficulty/dual_variant_calc/capital_need_planning_vs_filing_diverge
    """
    items = [
        create_capital_item_payload(category="DISTRIBUTION", description="main replacement",
                                    cost_low_cents=100000, cost_high_cents=100001),
        create_capital_item_payload(category="TREATMENT", horizon="SHORT_TERM",
                                    description="plant rehab",
                                    cost_low_cents=50000, cost_high_cents=50002),
    ]
    assessment, _ = _draft_assessment_with_item(items)
    submitted = submit_assessment(assessment["id"])
    assert submitted["planning_estimate_cents"] == 165000
    assert submitted["filing_estimate_cents"] == 172502
    assert submitted["planning_estimate_cents"] != submitted["filing_estimate_cents"]

    fetched = get_success_data(api.get_assessment(assessment["id"], TEST_USERS["analyst_headers"]))
    assert fetched["planning_estimate_cents"] == 165000
    assert fetched["filing_estimate_cents"] == 172502


def test_capital_need_planning_vs_filing_diverge_via_acceptance_copy(api):
    """PRD §3.2: "if the target is still in `SCREENING`, the target automatically
    advances `SCREENING → VALUATION`: the accepted assessment's
    `filing_estimate_cents` is copied onto the target, and the target's `version`
    increments by 1."

    Design: Difficulty/dual_variant_calc/capital_need_planning_vs_filing_diverge
    """
    items = [
        create_capital_item_payload(category="DISTRIBUTION", description="main replacement",
                                    cost_low_cents=100000, cost_high_cents=100001),
        create_capital_item_payload(category="TREATMENT", horizon="SHORT_TERM",
                                    description="plant rehab",
                                    cost_low_cents=50000, cost_high_cents=50002),
    ]
    target = create_target(permitted_valuation_methods=["FMV_INDEPENDENT", "REPLACEMENT_COST"])
    assessment, _ = create_assessment_with_items(target["id"], items)
    submit_assessment(assessment["id"])
    accept_assessment(assessment["id"])

    fresh = get_success_data(api.get_target(target["id"], TEST_USERS["analyst_headers"]))
    assert fresh["status"] == "VALUATION"
    assert fresh["filing_estimate_cents"] == 172502


def test_capital_need_per_line_rounding_order(api):
    """PRD §2.6: "for the filing-variant capital estimate, each line item's
    midpoint is rounded to a whole cent *first* and the rounded midpoints are
    *then* summed; summing unrounded averages and rounding once at the end is a
    different number and is not acceptable."

    Design: Difficulty/combinatorial_formula/capital_need_per_line_rounding_order
    """
    items = [
        create_capital_item_payload(category="COLLECTION", description="d1",
                                    cost_low_cents=100000, cost_high_cents=100001),
        create_capital_item_payload(category="COLLECTION", description="d2",
                                    cost_low_cents=100000, cost_high_cents=100001),
    ]
    assessment, created = _draft_assessment_with_item(items)
    assert created[0]["midpoint_estimate_cents"] == 100001
    assert created[1]["midpoint_estimate_cents"] == 100001

    submitted = submit_assessment(assessment["id"])
    assert submitted["filing_estimate_cents"] == 230002
    assert submitted["planning_estimate_cents"] == 220000


def test_capital_need_per_line_rounding_order_single_item_half_cent(api):
    """PRD §3.2: "Each item's `midpoint_estimate_cents` is the average of its low
    and high cost bounds, rounded half-up to a whole cent, computed per item at
    creation."

    Design: Difficulty/combinatorial_formula/capital_need_per_line_rounding_order
    """
    items = [
        create_capital_item_payload(category="COLLECTION", description="half",
                                    cost_low_cents=100001, cost_high_cents=100002),
    ]
    assessment, created = _draft_assessment_with_item(items)
    # (100001 + 100002) / 2 = 100001.5 -> round half-up -> 100002
    assert created[0]["midpoint_estimate_cents"] == 100002

    submitted = submit_assessment(assessment["id"])
    # 100002 * 1.15 = 115002.3 -> 115002
    assert submitted["filing_estimate_cents"] == 115002
    # 100001 * 1.10 = 110001.1 -> 110001
    assert submitted["planning_estimate_cents"] == 110001


def test_capital_item_midpoint_is_computed_input_ignored(api):
    """PRD §3.2: "Each item's `midpoint_estimate_cents` is the average of its low
    and high cost bounds, rounded half-up to a whole cent, computed per item at
    creation."

    Design: Corner/entities/capital_item_midpoint_is_computed_input_ignored
    """
    target = create_target(state_code="OH")
    assessment, _ = create_assessment_with_items(target["id"], [])
    resp = api.create_capital_item(
        assessment["id"],
        create_capital_item_payload(category="GENERAL", cost_low_cents=101,
                                    cost_high_cents=200),
        TEST_USERS["analyst_headers"])
    item = validate_success(resp, 201)
    assert_capital_item(item)
    assert item["midpoint_estimate_cents"] == 151  # 150.5 rounds half-up


def test_capital_item_rejects_inverted_cost_bounds(api):
    """PRD §3.2: "the low bound must be at least zero and the high bound must be
    at least the low bound".

    Design: Corner/entities/capital_item_rejects_inverted_cost_bounds
    """
    target = create_target(state_code="OH")
    assessment, _ = create_assessment_with_items(target["id"], [])
    resp = api.create_capital_item(
        assessment["id"],
        create_capital_item_payload(category="GENERAL", cost_low_cents=500,
                                    cost_high_cents=100),
        TEST_USERS["analyst_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_submit_assessment_without_items_rejected(api):
    """PRD §3.2: "Submission requires the assessment to have at least one
    non-`SPLIT` capital item; submitting an empty assessment is rejected with
    `ERR_ASSESSMENT_EMPTY` (HTTP 409)."

    Design: Corner/state_machines/submit_assessment_without_items_rejected
    """
    target = create_target(state_code="OH")
    assessment, _ = create_assessment_with_items(target["id"], [])
    resp = api.submit_assessment(assessment["id"],
                                 make_headers("analyst-1", "AcquisitionAnalyst"))
    validate_error(resp, ApiErrorId.ERR_ASSESSMENT_EMPTY)
    fetched = get_success_data(api.get_assessment(assessment["id"], TEST_USERS["analyst_headers"]))
    assert fetched["status"] == "DRAFT"


def test_assessment_revision_loop(api):
    """PRD §3.2: "The reviewer may reject the assessment, returning it to `DRAFT`
    and bumping its `revision_count` by one for the revision loop".

    Design: Difficulty/non_linear_state_machine/assessment_revision_loop
    """
    items = [create_capital_item_payload(category="STORAGE", horizon="LONG_TERM",
                                         description="tank", cost_low_cents=7000,
                                         cost_high_cents=9000)]
    target = create_target(state_code="OH", customer_count=10)
    assessment, _ = create_assessment_with_items(target["id"], items)
    submit_assessment(assessment["id"])
    rejected = get_success_data(api.reject_assessment(
        assessment["id"], TEST_USERS["reviewer_headers"]))
    assert rejected["status"] == "DRAFT"
    assert rejected["revision_count"] == 1

    resubmitted = submit_assessment(assessment["id"])
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_count"] == 1
    fresh = get_success_data(api.get_target(target["id"], TEST_USERS["analyst_headers"]))
    assert fresh["status"] == "SCREENING"


def test_assessment_revision_loop_resubmission_then_accept(api):
    """PRD §3.2: "or accept it, moving it to `ACCEPTED`. Acceptance requires the
    target to be in `SCREENING` or `VALUATION`".

    Design: Difficulty/non_linear_state_machine/assessment_revision_loop
    """
    items = [create_capital_item_payload(cost_low_cents=4000, cost_high_cents=4000)]
    target = create_target(state_code="OH", customer_count=10)
    assessment, _ = create_assessment_with_items(target["id"], items)
    submit_assessment(assessment["id"])
    api.reject_assessment(assessment["id"], TEST_USERS["reviewer_headers"])
    submit_assessment(assessment["id"])
    accepted = accept_assessment(assessment["id"])
    assert accepted["status"] == "ACCEPTED"
    assert accepted["revision_count"] == 1


def test_assessment_acceptance_supersede_and_advance_cascade(api):
    """PRD §3.2: "Acceptance has two cascades. If the target already has another
    `ACCEPTED` assessment, that earlier assessment is superseded to `SUPERSEDED`
    so at most one accepted assessment stands. And if the target is still in
    `SCREENING`, the target automatically advances `SCREENING → VALUATION`".

    Design: Difficulty/transitive_cascade/assessment_acceptance_supersede_and_advance_cascade
    """
    target = create_target(state_code="OH", customer_count=10)
    a1, _ = create_assessment_with_items(
        target["id"], [create_capital_item_payload(category="STORAGE",
                                                   cost_low_cents=1000, cost_high_cents=1000)],
        notes="first", creator_user_id="analyst-1")
    submit_assessment(a1["id"], user_id="analyst-1")
    accept_assessment(a1["id"])

    a2, _ = create_assessment_with_items(
        target["id"], [create_capital_item_payload(category="STORAGE", horizon="SHORT_TERM",
                                                   cost_low_cents=3000, cost_high_cents=3000)],
        notes="second", creator_user_id="analyst-2")
    submit_assessment(a2["id"], user_id="analyst-2")
    accepted2 = accept_assessment(a2["id"])
    assert accepted2["status"] == "ACCEPTED"

    a1_now = get_success_data(api.get_assessment(a1["id"], TEST_USERS["analyst_headers"]))
    assert a1_now["status"] == "SUPERSEDED"

    fresh = get_success_data(api.get_target(target["id"], TEST_USERS["analyst_headers"]))
    assert fresh["status"] == "VALUATION"


def test_assessment_acceptance_supersede_only_one_accepted_stands(api):
    """PRD §3.2: "If the target already has another `ACCEPTED` assessment, that
    earlier assessment is superseded to `SUPERSEDED` so at most one accepted
    assessment stands."

    Design: Difficulty/transitive_cascade/assessment_acceptance_supersede_and_advance_cascade
    """
    target = create_target(state_code="OH", customer_count=10)
    accepted_ids = []
    for idx in range(3):
        a, _ = create_assessment_with_items(
            target["id"], [create_capital_item_payload(cost_low_cents=1000,
                                                       cost_high_cents=1000)],
            notes=f"round {idx}", creator_user_id=f"analyst-{idx}")
        submit_assessment(a["id"], user_id=f"analyst-{idx}")
        accept_assessment(a["id"])
        accepted_ids.append(a["id"])
    for stale in accepted_ids[:-1]:
        data = get_success_data(api.get_assessment(stale, TEST_USERS["analyst_headers"]))
        assert data["status"] == "SUPERSEDED"
    latest = get_success_data(api.get_assessment(accepted_ids[-1], TEST_USERS["analyst_headers"]))
    assert latest["status"] == "ACCEPTED"


def test_split_invalid_state_beats_invalid_split(api):
    """PRD §3.2: "Splits and cancels are only possible while the owning assessment
    is `DRAFT`; attempting either once the assessment has moved on is rejected
    with `ERR_INVALID_STATE` (HTTP 409)."
    PRD §2.10: "then state-machine legality (`ERR_INVALID_STATE`) ... then
    money-range and split validity (`ERR_INVALID_REQUEST`, `ERR_INVALID_SPLIT`)".

    Design: Difficulty/priority_pair_validation_conflict/split_invalid_state_beats_invalid_split
    """
    target = create_target(state_code="OH", customer_count=10)
    assessment, items = create_assessment_with_items(
        target["id"], [create_capital_item_payload(category="GENERAL",
                                                   cost_low_cents=1000, cost_high_cents=2000)])
    submit_assessment(assessment["id"])
    resp = api.split_capital_item(items[0]["id"],
                                  {"split_low_cents": 5000, "split_high_cents": 9000},
                                  TEST_USERS["analyst_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    item = get_success_data(api.get_capital_item(items[0]["id"], TEST_USERS["analyst_headers"]))
    assert item["status"] == "PLANNED"


def test_split_invalid_state_beats_invalid_split_cancel_variant(api):
    """PRD §3.2: "Splits and cancels are only possible while the owning assessment
    is `DRAFT`; attempting either once the assessment has moved on is rejected
    with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/split_invalid_state_beats_invalid_split
    """
    target = create_target(state_code="OH", customer_count=10)
    assessment, items = create_assessment_with_items(
        target["id"], [create_capital_item_payload(cost_low_cents=1000, cost_high_cents=2000)])
    submit_assessment(assessment["id"])
    resp = api.cancel_capital_item(items[0]["id"], TEST_USERS["analyst_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    item = get_success_data(api.get_capital_item(items[0]["id"], TEST_USERS["analyst_headers"]))
    assert item["status"] == "PLANNED"


def test_capital_split_conservation(api):
    """PRD §3.2: "child A carries the split amounts as its low and high bounds,
    child B carries the remainders (the parent's low bound minus
    `split_low_cents`, and the parent's high bound minus `split_high_cents`)."
    and "The split conserves money exactly: the two children's low bounds sum to
    the parent's low bound, and likewise for the high bounds."

    Design: Difficulty/compensating_invariant/capital_split_conservation
    """
    target = create_target(state_code="OH", customer_count=10)
    assessment, items = create_assessment_with_items(
        target["id"], [create_capital_item_payload(cost_low_cents=10000,
                                                   cost_high_cents=25000,
                                                   crews_required=2)])
    parent = items[0]
    resp = api.split_capital_item(parent["id"],
                                  {"split_low_cents": 4000, "split_high_cents": 9000},
                                  TEST_USERS["analyst_headers"])
    split_parent = validate_success(resp, 200)
    assert split_parent["status"] == "SPLIT"

    resp = api.list_capital_items(assessment["id"], TEST_USERS["analyst_headers"])
    all_items, _meta = validate_paginated(resp)
    children = [i for i in all_items if i["id"] != parent["id"]]
    assert len(children) == 2
    lows = sorted(c["cost_low_cents"] for c in children)
    highs = sorted(c["cost_high_cents"] for c in children)
    assert lows == [4000, 6000]
    assert highs == [9000, 16000]
    assert sum(lows) == 10000
    assert sum(highs) == 25000
    for child in children:
        assert child["status"] == "PLANNED"
        assert child["category"] == parent["category"]
        assert child["horizon"] == parent["horizon"]
        assert child["description"] == parent["description"]
        assert child["crews_required"] == parent["crews_required"]


def test_capital_split_conservation_children_inherit_fields(api):
    """PRD §3.2: "Both children copy the parent's `category`, `horizon`,
    `description`, and `crews_required`."

    Design: Difficulty/compensating_invariant/capital_split_conservation
    """
    target = create_target(state_code="OH", customer_count=10)
    assessment, items = create_assessment_with_items(
        target["id"], [create_capital_item_payload(category="TREATMENT",
                                                   horizon="LONG_TERM",
                                                   description="plant rehab",
                                                   cost_low_cents=8000,
                                                   cost_high_cents=12000,
                                                   crews_required=2)])
    parent = items[0]
    api.split_capital_item(parent["id"], {"split_low_cents": 8000, "split_high_cents": 0},
                           TEST_USERS["analyst_headers"])
    resp = api.list_capital_items(assessment["id"], TEST_USERS["analyst_headers"])
    all_items, _ = validate_paginated(resp)
    children = [i for i in all_items if i["id"] != parent["id"]]
    assert len(children) == 2
    for child in children:
        assert child["category"] == "TREATMENT"
        assert child["horizon"] == "LONG_TERM"
        assert child["description"] == "plant rehab"
        assert child["crews_required"] == 2
    assert sorted(c["cost_low_cents"] for c in children) == [0, 8000]
    assert sorted(c["cost_high_cents"] for c in children) == [0, 12000]


def test_filing_estimate_copied_to_target_on_accept(api):
    """PRD §3.2: "if the target is still in `SCREENING`, the target
    automatically advances `SCREENING → VALUATION`: the accepted assessment's
    `filing_estimate_cents` is copied onto the target, and the target's
    `version` increments by 1."

    Design: Corner/calculations/filing_estimate_copied_to_target_on_accept
    """
    target = create_target(state_code="OH", customer_count=5)
    assessment, _ = create_assessment_with_items(
        target["id"],
        [create_capital_item_payload(category="SOURCE", description="well",
                                     cost_low_cents=40000, cost_high_cents=60000)])
    submit_assessment(assessment["id"])
    accepted = accept_assessment(assessment["id"])
    assert accepted["status"] == "ACCEPTED"
    # midpoint = 50000; filing = round_half_up(50000 * 1.15) = 57500
    assert accepted["filing_estimate_cents"] == 57500
    fresh = get_success_data(api.get_target(target["id"], TEST_USERS["analyst_headers"]))
    assert fresh["filing_estimate_cents"] == 57500
    assert fresh["status"] == "VALUATION"
