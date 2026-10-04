"""Selection runs, funding envelopes, and the sponsor waterfall (PRD §3.4/§3.5)."""

from test_helpers import (
    ApiErrorId,
    amend_scope,
    api_client,
    apply_run,
    create_candidate,
    create_commitment,
    create_cycle,
    create_scope_amendment_payload,
    create_selection_run,
    create_sponsor,
    get_application,
    get_commitment,
    get_cycle,
    get_project_for_application,
    get_scope_item,
    get_selection_run,
    open_selection,
    patch_application_status,
    reset_clock,
    run_selection,
    scope_item_payload,
    set_clock,
    setup_selected_project,
    validate_created,
    validate_error,
    validate_ok,
    STAFF,
)


def _setup_two_tier_candidates():
    """One cycle carrying two candidates: A estimates exactly 500000 (midpoints
    150000 + 350000), B estimates 499999 (midpoints 199999 + 300000)."""
    reset_clock()
    cycle = create_cycle(total_budget_cents=5_000_000)
    ctx_a = create_candidate(
        cycle["id"],
        scope_items=[
            scope_item_payload(
                category="SAFETY",
                est_low_cents=100_000,
                est_high_cents=200_000,
                description="item a1",
            ),
            scope_item_payload(
                category="GENERAL",
                est_low_cents=300_000,
                est_high_cents=400_000,
                description="item a2",
            ),
        ],
        homeowner_name="A Tier",
        date_of_birth="1960-05-05",
        household_size=2,
        household_income_cents=3_000_000,
        is_veteran=True,
    )
    ctx_b = create_candidate(
        cycle["id"],
        scope_items=[
            scope_item_payload(
                category="SAFETY",
                est_low_cents=199_998,
                est_high_cents=200_000,
                description="item b1",
            ),
            scope_item_payload(
                category="GENERAL",
                est_low_cents=300_000,
                est_high_cents=300_000,
                description="item b2",
            ),
        ],
        homeowner_name="B Tier",
        date_of_birth="1960-05-05",
        household_size=2,
        household_income_cents=3_000_000,
    )
    open_selection(cycle["id"])
    sel = run_selection(cycle["id"])
    assert sel["apply"]["applied_count"] == 2, (
        "both envelopes (550000 + 574999) fit the 5000000 pool"
    )
    project_a = get_project_for_application(ctx_a["application"]["id"])
    project_b = get_project_for_application(ctx_b["application"]["id"])
    return cycle, project_a, project_b


def test_envelope_tier_falls_to_10pct_at_exact_500000():
    """PRD §3.4: "Then a contingency rate is keyed on that pre-contingency
    estimate: 15% when the estimate is below 500,000 cents; 10% when it is
    500,000 cents or more but still below 2,000,000 cents; and 5% when it
    reaches 2,000,000 cents or more — so an estimate of exactly 500,000 cents
    falls into the 10% band, never the 15% band."
    PRD §3.4: "Finally the envelope is the estimate scaled by one plus the
    rate, rounded half up to the cent."

    Estimate exactly 500000 is NOT below 500000, so it takes the 10% band:
    envelope 550000.

    Design: Difficulty/combinatorial_formula/funding_envelope_contingency_tier_keyed_on_pre_contingency_estimate
    """
    _, project_a, _ = _setup_two_tier_candidates()
    assert project_a["provisional_estimate_cents"] == 500_000
    assert project_a["envelope_cents"] == 550_000, (
        f"500000 exactly must fall into the 10% band; got envelope "
        f"{project_a['envelope_cents']}"
    )


def test_envelope_15pct_tier_at_499999_inverts_ordering():
    """PRD §3.4: "Then a contingency rate is keyed on that pre-contingency
    estimate: 15% when the estimate is below 500,000 cents; 10% when it is
    500,000 cents or more but still below 2,000,000 cents; and 5% when it
    reaches 2,000,000 cents or more — so an estimate of exactly 500,000 cents
    falls into the 10% band, never the 15% band."

    Estimate 499999 stays in the 15% band: round_half_up(499999 * 1.15) =
    round_half_up(574998.85) = 574999 — a LARGER envelope than the 550000
    produced by the larger estimate 500000, proving the tier keys on the
    pre-contingency estimate, never on the envelope itself.

    Design: Difficulty/combinatorial_formula/funding_envelope_contingency_tier_keyed_on_pre_contingency_estimate
    """
    _, project_a, project_b = _setup_two_tier_candidates()
    assert project_b["provisional_estimate_cents"] == 499_999
    assert project_b["envelope_cents"] == 574_999, (
        f"499999 takes the 15% band; got envelope {project_b['envelope_cents']}"
    )
    assert project_b["envelope_cents"] > project_a["envelope_cents"], (
        "the inversion proves the tier is keyed on the pre-contingency estimate"
    )


def test_application_defer_and_reactivate_while_cycle_open():
    """PRD §3.2: "`AffiliateStaff` may nominate an `ASSESSED` application to
    `CANDIDATE`, or defer a `CANDIDATE` application to `DEFERRED` with a
    `decision_reason` recorded; both reject a wrong source state with
    `ERR_INVALID_STATE`."
    PRD §3.2: "A deferred application can be restored to `CANDIDATE`, but only
    while its cycle is `OPEN` or `SELECTION_OPEN`, otherwise
    `ERR_INVALID_STATE`."

    The CANDIDATE -> DEFERRED -> CANDIDATE cycle is legal while the cycle is
    still OPEN.

    Design: Difficulty/non_linear_state_machine/application_defer_reactivate_cycle_returns_to_pool
    """
    reset_clock()
    cycle = create_cycle()
    ctx = create_candidate(cycle["id"])
    app_id = ctx["application"]["id"]
    deferred = patch_application_status(app_id, "DEFERRED", decision_reason="waitlist")
    assert deferred["status"] == "DEFERRED"
    assert deferred["decision_reason"] == "waitlist"
    restored = patch_application_status(app_id, "CANDIDATE")
    assert restored["status"] == "CANDIDATE", (
        "restoration is legal while the cycle is OPEN"
    )


def test_reactivated_candidate_is_selected_with_project():
    """PRD §3.2: "A deferred application can be restored to `CANDIDATE`, but
    only while its cycle is `OPEN` or `SELECTION_OPEN`, otherwise
    `ERR_INVALID_STATE`."
    PRD §3.4: "Each selected application becomes `SELECTED` and spawns a
    project in `PLANNING`."

    The re-entered candidate is still selectable: the apply selects it, and the
    spawned project freezes envelope 115000 (round_half_up(100000 * 1.15)).

    Design: Difficulty/non_linear_state_machine/application_defer_reactivate_cycle_returns_to_pool
    """
    reset_clock()
    cycle = create_cycle()
    ctx = create_candidate(cycle["id"])
    app_id = ctx["application"]["id"]
    patch_application_status(app_id, "DEFERRED", decision_reason="waitlist")
    patch_application_status(app_id, "CANDIDATE")
    open_selection(cycle["id"])
    sel = run_selection(cycle["id"])
    assert sel["apply"]["applied_count"] == 1
    app_after = get_application(app_id)
    assert app_after["status"] == "SELECTED"
    project = get_project_for_application(app_id)
    assert project["envelope_cents"] == 115_000
    assert project["reserved_balance_cents"] == 115_000


def test_selection_run_create_supersedes_prior_computed():
    """PRD §3.4: "At creation the run freezes the cycle's `priority_mode` into
    `priority_mode_snapshot`, computes `ranked_application_ids` as every
    application of the cycle sitting in `CANDIDATE`, ordered by `priority_score`
    descending with ties broken by the application's `created_at` ascending so
    earlier applicants win ties, supersedes any previous `COMPUTED` run of the
    cycle to `SUPERSEDED`, and increments the cycle's `version` by one."
    PRD §3.4: "Applying a `COMPUTED` run is the allocation step, restricted to
    `AffiliateStaff`, and it again demands a cycle in `SELECTION_OPEN`
    (`ERR_CYCLE_NOT_SELECTION_OPEN`) and a run still in `COMPUTED`
    (`ERR_INVALID_STATE`)."

    A second run created with the current cycle version supersedes the first;
    the SUPERSEDED run can no longer be applied.

    Design: Corner/state_machines/selection_run_create_supersedes_prior_computed
    """
    reset_clock()
    cycle = create_cycle()
    ctx = create_candidate(cycle["id"])
    open_selection(cycle["id"])
    run1 = create_selection_run(cycle["id"])
    assert run1["status"] == "COMPUTED"
    run2 = create_selection_run(cycle["id"])
    assert run2["status"] == "COMPUTED"
    run1_after = get_selection_run(run1["id"])
    assert run1_after["status"] == "SUPERSEDED"
    resp = api_client.apply_selection_run(run1["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert run2["ranked_application_ids"] == [ctx["application"]["id"]]


def test_provisional_estimate_excludes_dropped_items_and_rebases_envelope():
    """PRD §3.5: "Every amendment recomputes the project's economics. The
    `provisional_estimate_cents` is re-aggregated over the surviving `INCLUDED`
    items, `envelope_cents` is re-derived through the tiered-contingency formula
    of §3.4, and `reserved_balance_cents` is adjusted by the envelope delta."
    PRD §3.5: "A successful amendment increments the project's `version` by
    one."

    Dropping the 50000-midpoint item recomputes the estimate over the surviving
    INCLUDED set (150000 -> 100000), rebases the envelope (172500 -> 115000),
    and releases exactly the 57500 delta from the cycle reserve.

    Design: Corner/calculations/provisional_estimate_excludes_dropped_items_and_rebases_envelope
    """
    ctx = setup_selected_project(
        budget_cents=1_000_000,
        scope_items=[
            scope_item_payload(
                est_low_cents=100_000, est_high_cents=100_000, description="keep"
            ),
            scope_item_payload(
                est_low_cents=50_000, est_high_cents=50_000, description="drop"
            ),
        ],
    )
    project = ctx["project"]
    assert project["envelope_cents"] == 172_500
    assert project["provisional_estimate_cents"] == 150_000
    proj_v = project["version"]
    si_drop = next(
        i for i in ctx["scope_items"] if i["description"] == "drop"
    )
    updated = amend_scope(project["id"], drop_item_ids=[si_drop["id"]])
    assert updated["provisional_estimate_cents"] == 100_000, (
        "the DROPPED item's midpoint 50000 is excluded from the input set"
    )
    assert updated["envelope_cents"] == 115_000
    assert updated["reserved_balance_cents"] == 115_000, (
        "the 57500 envelope delta is released from the reserve"
    )
    assert updated["version"] == proj_v + 1
    cycle = get_cycle(ctx["cycle"]["id"])
    assert cycle["reserved_cents"] == 115_000
    assert cycle["available_cents"] == 885_000
    assert get_scope_item(si_drop["id"])["status"] == "DROPPED"


def test_waterfall_allocates_in_received_order_with_partial_tail():
    """PRD §3.4: "The need is the sum of the newly created envelopes, and
    funding sources are consumed in a pinned order: the cycle's base
    `total_budget_cents` first, then each `RECEIVED` commitment in `received_at`
    ascending order with ties broken by the commitment's `created_at`
    ascending."
    PRD §3.4: "Any commitment receiving a positive allocation transitions to
    `ALLOCATED` with its `allocated_amount_cents` recorded — a partially
    allocated commitment still takes `ALLOCATED` with its partial amount, and
    its unallocated remainder simply stays in the pool."

    Need 517500 (envelope of estimate 450000): the base budget 200000 absorbs
    first, C1 (300000, received 2026-09-01) is consumed in full, and C2
    (400000, received 2026-09-02) takes only the 17500 tail as ALLOCATED.

    Design: Corner/calculations/waterfall_allocates_in_received_order_with_partial_tail
    """
    reset_clock()
    cycle = create_cycle(total_budget_cents=200_000)
    sponsor = create_sponsor(name="Waterfall Inc")
    com1 = create_commitment(sponsor["id"], cycle["id"], 300_000, receive=True)
    com2 = create_commitment(sponsor["id"], cycle["id"], 400_000)
    set_clock("2026-09-02T00:00:00Z")
    validate_ok(
        api_client.patch_commitment(com2["id"], {"status": "RECEIVED"}, STAFF)
    )
    create_candidate(
        cycle["id"],
        scope_items=[
            scope_item_payload(
                est_low_cents=100_000, est_high_cents=200_000, description="w1"
            ),
            scope_item_payload(
                est_low_cents=300_000, est_high_cents=300_000, description="w2"
            ),
        ],
        homeowner_name="Fall Site",
    )
    open_selection(cycle["id"])
    sel = run_selection(cycle["id"])
    assert sel["apply"]["applied_count"] == 1
    c1_after = get_commitment(com1["id"])
    c2_after = get_commitment(com2["id"])
    assert c1_after["status"] == "ALLOCATED"
    assert c1_after["allocated_amount_cents"] == 300_000, (
        "the earlier-received commitment is consumed in full after the base "
        "budget"
    )
    assert c2_after["status"] == "ALLOCATED"
    assert c2_after["allocated_amount_cents"] == 17_500, (
        "517500 - 200000 - 300000 = 17500; the partial tail is allocated and "
        "the 382500 remainder stays in the pool"
    )


def test_run_create_before_selection_open_returns_cycle_not_selection_open():
    """PRD §3.4: "`AffiliateStaff` (or a `PlatformAdmin`) create a run against
    a cycle that is `SELECTION_OPEN` — any other cycle state is
    `ERR_CYCLE_NOT_SELECTION_OPEN` — and the request must carry
    `expected_funding_cycle_version` per §2.9."
    PRD §2.9: "On success, each operation increments the parent entity's
    `version` by one."

    A perfectly fresh OCC version cannot rescue a run create against an OPEN
    cycle, and the rejected call leaves the cycle version untouched.

    Design: Corner/endpoints/run_create_before_selection_open_returns_cycle_not_selection_open
    """
    cycle = create_cycle()
    version_before = cycle["version"]
    resp = api_client.create_selection_run(
        cycle["id"],
        {"expected_funding_cycle_version": version_before},
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_SELECTION_OPEN)
    cycle_after = get_cycle(cycle["id"])
    assert cycle_after["version"] == version_before, (
        "a rejected run create must not bump the cycle version"
    )
