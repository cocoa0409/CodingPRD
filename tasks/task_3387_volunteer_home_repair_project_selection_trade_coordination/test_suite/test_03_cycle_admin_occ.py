"""Optimistic concurrency, state-vs-fiscal ordering, and candidacy gates
(PRD §2.9/§2.10/§3.2/§3.5)."""

from test_helpers import (
    ApiErrorId,
    amend_scope,
    api_client,
    cancel_project,
    complete_assessment,
    create_application,
    create_assessment,
    create_candidate,
    create_commitment,
    create_contractor,
    create_cycle,
    create_scope_amendment_payload,
    create_selection_run,
    create_sponsor,
    create_verified_application,
    create_work_order,
    get_application,
    get_commitment,
    get_cycle,
    get_project,
    get_scope_item,
    get_selection_run,
    open_selection,
    patch_application_status,
    reset_clock,
    scope_assessment,
    scope_item_payload,
    setup_selected_project,
    trade_scope_item_payload,
    validate_created,
    validate_error,
    validate_ok,
    STAFF,
)


def test_selection_run_create_with_stale_cycle_version_returns_412():
    """PRD §2.9: "In either case, if the client's last observed version has
    fallen behind the server's — another writer advanced the parent since the
    client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP
    412), preventing the client from overwriting state it has not observed."

    After run1's creation bumps the cycle version, a second create still
    carrying the pre-run1 version is rejected 412 and the surviving run is not
    superseded by the failed call.

    Design: Corner/cross_cutting_complexity_layers/selection_run_create_with_stale_cycle_version_returns_412
    """
    reset_clock()
    cycle = create_cycle()
    create_candidate(cycle["id"])
    open_selection(cycle["id"])
    stale_version = get_cycle(cycle["id"])["version"]
    run1 = create_selection_run(cycle["id"])
    resp = api_client.create_selection_run(
        cycle["id"], {"expected_funding_cycle_version": stale_version}, STAFF
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    run1_after = get_selection_run(run1["id"])
    assert run1_after["status"] == "COMPUTED", (
        "the failed second create must not supersede the live run"
    )


def test_scope_amendment_with_stale_project_version_returns_412():
    """PRD §2.9: "Amending a project's scope requires `expected_project_version`
    equal to the project's current `version`."
    PRD §2.9: "In either case, if the client's last observed version has fallen
    behind the server's — another writer advanced the parent since the client
    read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412),
    preventing the client from overwriting state it has not observed."

    A first amendment bumps the project version; replaying the pre-amendment
    version on an otherwise-valid payload is rejected 412 and changes nothing.

    Design: Corner/cross_cutting_complexity_layers/scope_amendment_with_stale_project_version_returns_412
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
    proj_v = project["version"]
    si_drop = next(i for i in ctx["scope_items"] if i["description"] == "drop")
    si_keep = next(i for i in ctx["scope_items"] if i["description"] == "keep")
    updated = amend_scope(project["id"], drop_item_ids=[si_drop["id"]])
    assert updated["version"] == proj_v + 1
    resp = api_client.create_scope_amendment(
        project["id"],
        create_scope_amendment_payload(proj_v, drop_item_ids=[si_keep["id"]]),
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert get_scope_item(si_keep["id"])["status"] == "INCLUDED", (
        "the rejected second amendment changed nothing"
    )


def test_commitment_withdrawn_is_terminal():
    """PRD §3.1: "Marking a `PLEDGED` commitment `RECEIVED` is staff work: it
    stamps `received_at` from the logical clock and immediately raises the
    cycle's `pool_cents` and `available_cents` by `amount_cents`."
    PRD §3.1: "Withdrawing a `PLEDGED` commitment merely stamps `withdrawn_at`;
    the pool is unchanged because the money never entered it."

    A WITHDRAWN commitment cannot be revived: RECEIVED after withdrawal is a
    from-state violation, and the pool is untouched by the attempt.

    Design: Corner/state_machines/commitment_withdrawn_is_terminal
    """
    cycle = create_cycle()
    sponsor = create_sponsor(name="Term Sponsor")
    commitment = create_commitment(sponsor["id"], cycle["id"], 500_000)
    validate_ok(
        api_client.patch_commitment(commitment["id"], {"status": "WITHDRAWN"}, STAFF)
    )
    resp = api_client.patch_commitment(
        commitment["id"], {"status": "RECEIVED"}, STAFF
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_cycle(cycle["id"])["pool_cents"] == 1_000_000, (
        "a PLEDGED commitment never entered the pool; the failed revival "
        "changes nothing"
    )
    assert get_commitment(commitment["id"])["status"] == "WITHDRAWN"


def test_application_jump_submitted_to_candidate_returns_invalid_state():
    """PRD §3.2: "`AffiliateStaff` may nominate an `ASSESSED` application to
    `CANDIDATE`, or defer a `CANDIDATE` application to `DEFERRED` with a
    `decision_reason` recorded; both reject a wrong source state with
    `ERR_INVALID_STATE`."

    SUBMITTED -> CANDIDATE skips the verification and assessment pipeline and
    is rejected; the application stays SUBMITTED.

    Design: Corner/state_machines/application_jump_submitted_to_candidate_returns_invalid_state
    """
    cycle = create_cycle()
    app = create_application(cycle["id"], homeowner_name="Skipper")
    resp = api_client.patch_application(app["id"], {"status": "CANDIDATE"}, STAFF)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_application(app["id"])["status"] == "SUBMITTED"


def test_candidacy_rejected_while_assessment_not_scoped():
    """PRD §3.2: "`AffiliateStaff` may nominate an `ASSESSED` application to
    `CANDIDATE`, or defer a `CANDIDATE` application to `DEFERRED` with a
    `decision_reason` recorded; both reject a wrong source state with
    `ERR_INVALID_STATE`."
    PRD §3.3: "When the scoped assessment is the application's latest one, the
    application leaves `ASSESSING` for `ASSESSED` and its `priority_score` is
    recomputed — and this recomputation is where the hazard bonus enters."

    While the application's latest assessment is merely COMPLETED the
    application is still ASSESSING, and the CANDIDATE nomination is rejected.

    Design: Difficulty/cross_entity_state_dependency/candidacy_requires_latest_assessment_scoped
    """
    reset_clock()
    cycle = create_cycle()
    app = create_verified_application(cycle["id"], homeowner_name="Gate A")
    asm = create_assessment(app["id"], scheduled_on="2026-09-02")
    complete_assessment(asm["id"])
    assert get_application(app["id"])["status"] == "ASSESSING"
    resp = api_client.patch_application(app["id"], {"status": "CANDIDATE"}, STAFF)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_application(app["id"])["status"] == "ASSESSING"


def test_candidacy_succeeds_after_assessment_scoped():
    """PRD §3.3: "When the scoped assessment is the application's latest one,
    the application leaves `ASSESSING` for `ASSESSED` and its `priority_score`
    is recomputed — and this recomputation is where the hazard bonus enters."
    PRD §3.2: "`AffiliateStaff` may nominate an `ASSESSED` application to
    `CANDIDATE`, or defer a `CANDIDATE` application to `DEFERRED` with a
    `decision_reason` recorded; both reject a wrong source state with
    `ERR_INVALID_STATE`."

    Once the assessment is SCOPED the application auto-advances to ASSESSED and
    the same nomination succeeds — the gating fact lives on the assessment, a
    different entity than the one being transitioned.

    Design: Difficulty/cross_entity_state_dependency/candidacy_requires_latest_assessment_scoped
    """
    reset_clock()
    cycle = create_cycle()
    app = create_verified_application(cycle["id"], homeowner_name="Gate A")
    asm = create_assessment(app["id"], scheduled_on="2026-09-02")
    complete_assessment(asm["id"])
    scope_assessment(asm["id"])
    assert get_application(app["id"])["status"] == "ASSESSED"
    nominated = patch_application_status(app["id"], "CANDIDATE")
    assert nominated["status"] == "CANDIDATE"


def test_amend_cancelled_project_state_error_beats_fiscal_error():
    """PRD §2.10: "6. State-machine from-state legality (`ERR_INVALID_STATE`
    and the specific state errors `ERR_CYCLE_NOT_SELECTION_OPEN`,
    `ERR_EVENT_NOT_PUBLISHED`, `ERR_EVENT_NOT_LOCKABLE`,
    `ERR_PROJECT_NOT_COMPLETED`)."
    PRD §2.10: "11. Fiscal rules, always last (`ERR_INSUFFICIENT_FUNDING`,
    `ERR_ENVELOPE_EXCEEDED`, `ERR_WARRANTY_CAP_EXCEEDED`)."
    PRD §3.5: "Between selection and the build, staff may amend a project's
    scope, provided the project is still `PLANNING` or `READY` — any other
    state is `ERR_INVALID_STATE` — and the request carries
    `expected_project_version` per §2.9."

    Amending a CANCELLED project with an addition whose envelope delta would
    also exceed available funds surfaces ERR_INVALID_STATE, not
    ERR_ENVELOPE_EXCEEDED.

    Design: Difficulty/priority_pair_validation_conflict/amend_cancelled_project_state_error_beats_fiscal_error
    """
    ctx = setup_selected_project(budget_cents=200_000)
    project = cancel_project(ctx["project"]["id"], "STAFF_DECISION")
    resp = api_client.create_scope_amendment(
        project["id"],
        create_scope_amendment_payload(
            project["version"],
            add_items=[
                scope_item_payload(
                    est_low_cents=500_000,
                    est_high_cents=500_000,
                    description="room addition",
                )
            ],
        ),
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_amend_live_project_fiscal_error_when_state_legal():
    """PRD §3.5: "If the recomputed envelope would push the project's reserved
    balance above the cycle's available headroom, the amendment is rejected
    with `ERR_ENVELOPE_EXCEEDED` (HTTP 402)."

    Control for the priority pair: the same +500000-cent addition against a
    live PLANNING project (estimate 600000 -> envelope 660000, delta 545000
    against 85000 available) fires the fiscal rule that the CANCELLED project
    masked.

    Design: Difficulty/priority_pair_validation_conflict/amend_cancelled_project_state_error_beats_fiscal_error
    """
    ctx = setup_selected_project(budget_cents=200_000)
    project = ctx["project"]
    resp = api_client.create_scope_amendment(
        project["id"],
        create_scope_amendment_payload(
            project["version"],
            add_items=[
                scope_item_payload(
                    est_low_cents=500_000,
                    est_high_cents=500_000,
                    description="room addition",
                )
            ],
        ),
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_ENVELOPE_EXCEEDED)
    assert get_project(project["id"])["provisional_estimate_cents"] == 100_000, (
        "the rejected amendment changed nothing"
    )


def test_drop_item_covered_by_work_order_returns_not_droppable():
    """PRD §3.5: "Dropping requires the item to be `INCLUDED` (else
    `ERR_INVALID_STATE`) and not covered by any non-terminal trade work order —
    a covered item refuses to drop with `ERR_SCOPE_ITEM_NOT_DROPPABLE`."

    The covered item refuses to drop while a QUOTE_REQUESTED (non-terminal)
    order covers it; the uncovered item drops cleanly in the same project
    state.

    Design: Corner/validations/drop_item_covered_by_work_order_returns_not_droppable
    """
    ctx = setup_selected_project(
        budget_cents=1_000_000,
        scope_items=[
            trade_scope_item_payload(description="covered"),
            trade_scope_item_payload(description="free"),
        ],
    )
    contractor = create_contractor(legal_name="Drop Co")
    project = ctx["project"]
    si_cov = next(i for i in ctx["scope_items"] if i["description"] == "covered")
    si_free = next(i for i in ctx["scope_items"] if i["description"] == "free")
    create_work_order(project["id"], contractor["id"], [si_cov["id"]])
    proj_v = get_project(project["id"])["version"]
    resp = api_client.create_scope_amendment(
        project["id"],
        create_scope_amendment_payload(proj_v, drop_item_ids=[si_cov["id"]]),
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_SCOPE_ITEM_NOT_DROPPABLE)
    # The first attempt failed without a version bump, so the same captured
    # version still authorizes the second, independent amendment.
    resp2 = api_client.create_scope_amendment(
        project["id"],
        create_scope_amendment_payload(proj_v, drop_item_ids=[si_free["id"]]),
        STAFF,
    )
    updated = validate_created(resp2)
    assert updated["provisional_estimate_cents"] == 50_000
    assert get_scope_item(si_cov["id"])["status"] == "INCLUDED"
