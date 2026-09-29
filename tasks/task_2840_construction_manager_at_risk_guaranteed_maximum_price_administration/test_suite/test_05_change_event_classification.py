"""The cost-responsibility fork, and the three-level cascade one branch sets off.

All three classifications leave the event in the identical state, yet the paperwork
each one mints is mutually exclusive; and the amendment branch reaches all the way
down to estimates reconciled long before the event existed.
"""

from decimal import Decimal
from typing import Tuple

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import (
    CM_HEADERS,
    CM_PM_HEADERS,
    OWNER_HEADERS,
    ApiClient,
    assert_equals,
    assert_fields,
    assert_money,
    assert_money_fields,
    assert_project_axes,
    factories,
    fixtures,
    single_row,
    user_id_of,
)
from test_helpers.types import JsonObject

RIVERSIDE_DATA_HALL = {
    "cm_fee_pct": Decimal("0.0375"),
    "insurance_rate": Decimal("0.0125"),
    "cost_of_work_total": Decimal("40000000.00"),
    "general_conditions_total": Decimal("2500000.00"),
    "owner_contingency_amount": Decimal("1200000.00"),
    "construction_contingency_amount": Decimal("240000.00"),
    "project_kwargs": {
        "name": "Riverside Data Hall",
        "owner_org": "Riverside Utilities",
        "precon_fee_amount": Decimal("250000.00"),
    },
}

DEWATERING_NOTE = "site dewatering scope added between SD and CD_100"


def _event_under_review(
    api: ApiClient, project_id: str, amount: Decimal, origin: str, description: str
) -> JsonObject:
    """Log a cost impact as the project manager and hand it to the owner to review."""
    return fixtures.event_under_review(
        api,
        project_id,
        estimated_amount=amount,
        origin=origin,
        description=description,
        submitter_headers=CM_PM_HEADERS,
    )


def _classify(
    api: ApiClient, event_id: str, classification: str, note: str
) -> JsonObject:
    """Make the cost-responsibility determination as the owner's representative."""
    return validate_success(
        api.classify_change_event(
            event_id,
            factories.classify_payload(classification, classification_note=note),
            OWNER_HEADERS,
        )
    )


def _civic_center_with_a_layered_estimate_trail(
    api: ApiClient,
) -> Tuple[str, JsonObject, JsonObject, JsonObject]:
    """An executed project behind two reconciled estimates and one still submitted.

    The schematic-design estimate and the construction-documents estimate are both
    reconciled, the latter over the justification threshold; a third estimate at the
    ``GMP_BASIS`` milestone is left at ``SUBMITTED`` so the cascade has something it
    must not touch.
    """
    project = fixtures.create_project(
        api,
        name="Harborview Civic Center",
        owner_org="Harborview County Owner Authority",
        precon_fee_amount=Decimal("40000.00"),
    )
    project_id = project["id"]
    est_sd = fixtures.reconciled_estimate(
        api,
        project_id,
        milestone_code="SD",
        submitted_cost_of_work=Decimal("950000.00"),
    )
    est_cd = fixtures.reconciled_estimate(
        api,
        project_id,
        milestone_code="CD_100",
        submitted_cost_of_work=Decimal("1000000.00"),
        justification_note=DEWATERING_NOTE,
    )
    est_basis = fixtures.create_estimate(
        api,
        project_id,
        milestone_code="GMP_BASIS",
        submitted_cost_of_work=Decimal("1000000.00"),
    )
    validate_success(
        api.submit_estimate(
            est_basis["id"], factories.estimate_submit_payload(), CM_HEADERS
        )
    )

    proposal = validate_success(
        api.create_gmp_proposal(
            factories.gmp_proposal_payload(
                project_id,
                est_cd["id"],
                fixtures.project_version(api, project_id),
            ),
            CM_HEADERS,
        ),
        201,
    )
    validate_success(api.submit_gmp_proposal(proposal["id"], CM_HEADERS))
    validate_success(
        api.decide_gmp_proposal(
            proposal["id"], factories.proposal_decision_payload("EXECUTE"), OWNER_HEADERS
        )
    )
    return project_id, est_sd, est_cd, est_basis


def test_scope_change_mints_a_draft_amendment_and_draws_no_contingency(
    api: ApiClient,
) -> None:
    """The owner-pays branch moves the proposed price while the executed one holds.

    PRD: "An amendment proposal is minted with `proposal_type` `AMENDMENT`, `status` `DRAFT`, `based_on_estimate_id` null, `change_event_id` naming this event, `amount_delta` equal to the event's `estimated_amount`, and its own `gmp_amount` equal to the project's current `gmp_amount` plus that `amount_delta`."

    PRD: "Its four proposed money components — `cost_of_work_total`, `general_conditions_total`, `owner_contingency_amount` and `construction_contingency_amount` — are all 0.00, as are `provisional_fee_amount`, `insurance_amount` and `cm_fee_amount`, because the entire impact is carried by `amount_delta`."

    PRD: "No contingency is drawn on this branch."

    PRD: "Because the amendment lands at `DRAFT`, it must still be submitted and then executed by the owner before the envelope actually moves; listing proposals filtered by `change_event_id` is the only discovery channel for a cascade-minted amendment."

    Design: Difficulty/non_linear_state_machine/change_event_three_way_classification_fork_with_divergent_side_effect_sets
    """
    priced = fixtures.executed_project(api, **RIVERSIDE_DATA_HALL)
    event = _event_under_review(
        api,
        priced.id,
        Decimal("300000.00"),
        "OWNER_DIRECTIVE",
        "owner directive: add redundant cooling loop",
    )

    classified = _classify(
        api, event["id"], "SCOPE_CHANGE", "owner-directed added scope"
    )
    assert_fields(classified, {"status": "CLASSIFIED", "classification": "SCOPE_CHANGE"})

    amendments, meta = validate_paginated(
        api.list_gmp_proposals(
            OWNER_HEADERS, {"project_id": priced.id, "proposal_type": "AMENDMENT"}
        )
    )
    assert meta["total_count"] == 1, (
        "the scope-change branch did not mint exactly one amendment proposal"
    )
    amendment = single_row(amendments, "change_event_id", event["id"])
    assert_fields(
        amendment,
        {"status": "DRAFT", "proposal_type": "AMENDMENT", "based_on_estimate_id": None},
    )
    assert_money_fields(
        amendment,
        {
            "amount_delta": Decimal("300000.00"),
            "gmp_amount": Decimal("46405590.83"),
            "cost_of_work_total": Decimal("0.00"),
            "general_conditions_total": Decimal("0.00"),
            "owner_contingency_amount": Decimal("0.00"),
            "construction_contingency_amount": Decimal("0.00"),
            "provisional_fee_amount": Decimal("0.00"),
            "insurance_amount": Decimal("0.00"),
            "cm_fee_amount": Decimal("0.00"),
        },
    )

    project = fixtures.read_project(api, priced.id)
    assert_equals(project, "pending_amendment_count", 1)
    assert_money_fields(
        project,
        {
            "proposed_gmp_amount": Decimal("46405590.83"),
            "gmp_amount": Decimal("46105590.83"),
        },
    )
    _draws, draw_meta = validate_paginated(
        api.list_draws(OWNER_HEADERS, {"change_event_id": event["id"]})
    )
    assert draw_meta["total_count"] == 0, (
        "the scope-change branch drew contingency it should not have"
    )


def test_the_two_contingency_branches_mint_draws_with_opposite_approval_verdicts(
    api: ApiClient,
) -> None:
    """The owner's pot always needs a signature; the manager's pot needs one only above the line.

    PRD: "A contingency draw is minted with `contingency_type` `OWNER`, `origin` `CHANGE_EVENT_CLASSIFICATION`, `status` `REQUESTED`, `amount` equal to the event's `estimated_amount`, `change_event_id` naming this event, `source_subcontract_id` null, and `requires_owner_approval` set to true unconditionally — it is the owner's money, so the owner always signs for it."

    PRD: "A contingency draw is minted with `contingency_type` `CONSTRUCTION`, `origin` `CHANGE_EVENT_CLASSIFICATION`, `status` `REQUESTED`, `amount` equal to the event's `estimated_amount`, `change_event_id` naming this event and `source_subcontract_id` null, with `requires_owner_approval` determined by the approval rule in §3.7 rather than being forced true."

    PRD: "No amendment proposal is minted, and the project's `pending_amendment_count` and `proposed_gmp_amount` are untouched."

    Design: Difficulty/non_linear_state_machine/change_event_three_way_classification_fork_with_divergent_side_effect_sets
    """
    priced = fixtures.executed_project(api, **RIVERSIDE_DATA_HALL)
    owner_event = _event_under_review(
        api,
        priced.id,
        Decimal("80000.00"),
        "FIELD_CONDITION",
        "unforeseen rock excavation",
    )
    cm_event = _event_under_review(
        api,
        priced.id,
        Decimal("30000.00"),
        "DESIGN_DEVELOPMENT",
        "coordination rework at level 2",
    )

    _classify(
        api,
        owner_event["id"],
        "CONTINGENCY_USE_OWNER",
        "owner contingency absorbs the differing site condition",
    )
    _classify(
        api,
        cm_event["id"],
        "CONTINGENCY_USE_CONSTRUCTION",
        "coordination rework is the CM's risk",
    )

    draws, meta = validate_paginated(
        api.list_draws(OWNER_HEADERS, {"project_id": priced.id})
    )
    assert meta["total_count"] == 2, (
        "the two contingency branches did not mint exactly two draws"
    )
    owner_draw = single_row(draws, "change_event_id", owner_event["id"])
    cm_draw = single_row(draws, "change_event_id", cm_event["id"])
    assert_fields(
        owner_draw,
        {
            "contingency_type": "OWNER",
            "origin": "CHANGE_EVENT_CLASSIFICATION",
            "status": "REQUESTED",
            "requires_owner_approval": True,
            "source_subcontract_id": None,
        },
    )
    assert_money(owner_draw["amount"], Decimal("80000.00"), "owner draw amount")
    assert_fields(
        cm_draw,
        {
            "contingency_type": "CONSTRUCTION",
            "origin": "CHANGE_EVENT_CLASSIFICATION",
            "status": "REQUESTED",
            "requires_owner_approval": False,
            "source_subcontract_id": None,
        },
    )
    assert_money(cm_draw["amount"], Decimal("30000.00"), "construction draw amount")

    _rows, amendment_meta = validate_paginated(
        api.list_gmp_proposals(
            OWNER_HEADERS, {"project_id": priced.id, "proposal_type": "AMENDMENT"}
        )
    )
    assert amendment_meta["total_count"] == 0, (
        "a contingency branch minted an amendment proposal"
    )
    project = fixtures.read_project(api, priced.id)
    assert_equals(project, "pending_amendment_count", 0)
    assert_money_fields(
        project,
        {
            "proposed_gmp_amount": Decimal("46105590.83"),
            "gmp_amount": Decimal("46105590.83"),
        },
    )


def test_all_three_branches_end_in_one_state_with_mutually_exclusive_paperwork(
    api: ApiClient,
) -> None:
    """Three events, one status, and three different sets of consequences behind it.

    PRD: "Whichever branch is taken, the event advances `UNDER_REVIEW → CLASSIFIED`, its `classification` is written from the payload, `classified_by_user_id` is recorded from the acting `X-User-ID`, `classified_at` is stamped from the logical clock, and both the event's `version` and the project's `version` increment by 1."

    PRD: "`CONTINGENCY_USE_CONSTRUCTION` means the construction manager absorbs the cost inside the guaranteed price."

    PRD: "No amendment proposal is minted and the guaranteed maximum price does not move at all."

    Design: Difficulty/non_linear_state_machine/change_event_three_way_classification_fork_with_divergent_side_effect_sets
    """
    priced = fixtures.executed_project(api, **RIVERSIDE_DATA_HALL)
    scope_event = _event_under_review(
        api,
        priced.id,
        Decimal("300000.00"),
        "OWNER_DIRECTIVE",
        "owner directive: add redundant cooling loop",
    )
    owner_event = _event_under_review(
        api,
        priced.id,
        Decimal("80000.00"),
        "FIELD_CONDITION",
        "unforeseen rock excavation",
    )
    cm_event = _event_under_review(
        api,
        priced.id,
        Decimal("30000.00"),
        "DESIGN_DEVELOPMENT",
        "coordination rework at level 2",
    )

    for event_id, classification, note in (
        (scope_event["id"], "SCOPE_CHANGE", "owner-directed added scope"),
        (
            owner_event["id"],
            "CONTINGENCY_USE_OWNER",
            "owner contingency absorbs the differing site condition",
        ),
        (
            cm_event["id"],
            "CONTINGENCY_USE_CONSTRUCTION",
            "coordination rework is the CM's risk",
        ),
    ):
        classified = _classify(api, event_id, classification, note)
        assert_fields(
            classified,
            {
                "status": "CLASSIFIED",
                "classification": classification,
                "classified_by_user_id": user_id_of("owner_rep"),
            },
        )

    amendments, amendment_meta = validate_paginated(
        api.list_gmp_proposals(
            OWNER_HEADERS, {"project_id": priced.id, "proposal_type": "AMENDMENT"}
        )
    )
    assert amendment_meta["total_count"] == 1, (
        "exactly one of the three branches should have minted an amendment"
    )
    single_row(amendments, "change_event_id", scope_event["id"])

    draws, draw_meta = validate_paginated(
        api.list_draws(OWNER_HEADERS, {"project_id": priced.id})
    )
    assert draw_meta["total_count"] == 2, (
        "exactly two of the three branches should have minted a draw"
    )
    assert scope_event["id"] not in [draw["change_event_id"] for draw in draws], (
        "the scope-change event has a contingency draw behind it"
    )

    project = fixtures.read_project(api, priced.id)
    assert_project_axes(
        project, gmp_status="EXECUTED", contingency_posture="OPEN"
    )
    assert_money_fields(
        project,
        {
            "owner_contingency_remaining": Decimal("1200000.00"),
            "construction_contingency_remaining": Decimal("240000.00"),
            "contingency_drawn_to_cost_total": Decimal("0.00"),
            "gmp_amount": Decimal("46105590.83"),
            "proposed_gmp_amount": Decimal("46405590.83"),
        },
    )


def test_one_scope_change_propagates_three_levels_down_to_reconciled_estimates(
    api: ApiClient,
) -> None:
    """Amendment, then rollup, then the staling of everything already reconciled.

    PRD: "Minting that row is itself the trigger for the rollup of §3.2, which increments the project's `pending_amendment_count` by 1 and rewrites `proposed_gmp_amount`."

    PRD: "And that rewrite is itself the trigger for a third-level cascade: **every** progressive estimate of the project whose status is `RECONCILED` has `reconciliation_stale` raised to true, because the scope those estimates were reconciled against has formally moved."

    PRD: "`proposed_gmp_amount` becomes the project's `gmp_amount` plus the sum of `amount_delta` over every amendment proposal of that project whose status is `DRAFT`, `OWNER_REVIEW` or `RETURNED_FOR_REVISION`, and `pending_amendment_count` becomes the count of those same rows."

    Design: Difficulty/transitive_cascade/scope_change_classification_three_level_cascade_stales_reconciled_estimates
    """
    project_id, est_sd, est_cd, _est_basis = _civic_center_with_a_layered_estimate_trail(
        api
    )
    before = fixtures.read_project(api, project_id)
    assert_money(before["gmp_amount"], Decimal("1245897.60"), "gmp_amount")
    assert_equals(before, "pending_amendment_count", 0)

    event = _event_under_review(
        api,
        project_id,
        Decimal("250000.00"),
        "OWNER_DIRECTIVE",
        "owner directive: council chamber audiovisual fit-out",
    )
    classified = _classify(
        api, event["id"], "SCOPE_CHANGE", "owner-directed added scope"
    )
    assert_fields(
        classified,
        {
            "status": "CLASSIFIED",
            "classification": "SCOPE_CHANGE",
            "classified_by_user_id": user_id_of("owner_rep"),
        },
    )

    amendments, meta = validate_paginated(
        api.list_gmp_proposals(OWNER_HEADERS, {"change_event_id": event["id"]})
    )
    assert meta["total_count"] == 1, "the first cascade level minted no amendment"
    amendment = single_row(amendments, "change_event_id", event["id"])
    assert_fields(amendment, {"proposal_type": "AMENDMENT", "status": "DRAFT"})
    assert_money_fields(
        amendment,
        {
            "amount_delta": Decimal("250000.00"),
            "gmp_amount": Decimal("1495897.60"),
        },
    )

    project = fixtures.read_project(api, project_id)
    assert_equals(project, "pending_amendment_count", 1)
    assert_money_fields(
        project,
        {
            "proposed_gmp_amount": Decimal("1495897.60"),
            "gmp_amount": Decimal("1245897.60"),
        },
    )

    assert_fields(
        fixtures.read_estimate(api, est_sd["id"]),
        {"status": "RECONCILED", "reconciliation_stale": True},
    )
    assert_fields(
        fixtures.read_estimate(api, est_cd["id"]),
        {"status": "RECONCILED", "reconciliation_stale": True},
    )


def test_the_staling_cascade_skips_the_estimate_that_was_never_reconciled(
    api: ApiClient,
) -> None:
    """A submitted estimate on the same project is left alone, and no pot is touched.

    PRD: "And that rewrite is itself the trigger for a third-level cascade: **every** progressive estimate of the project whose status is `RECONCILED` has `reconciliation_stale` raised to true, because the scope those estimates were reconciled against has formally moved."

    PRD: "The `reconciliation_stale` flag is not merely decorative — §3.6 describes the one cascade that raises it, marking every previously reconciled estimate of a project as needing a fresh look once the scope of the work has formally changed."

    PRD: "No contingency is drawn on this branch."

    Design: Difficulty/transitive_cascade/scope_change_classification_three_level_cascade_stales_reconciled_estimates
    """
    project_id, _est_sd, _est_cd, est_basis = _civic_center_with_a_layered_estimate_trail(
        api
    )
    assert_fields(
        fixtures.read_estimate(api, est_basis["id"]),
        {"status": "SUBMITTED", "reconciliation_stale": False},
    )

    event = _event_under_review(
        api,
        project_id,
        Decimal("250000.00"),
        "OWNER_DIRECTIVE",
        "owner directive: council chamber audiovisual fit-out",
    )
    _classify(api, event["id"], "SCOPE_CHANGE", "owner-directed added scope")

    skipped = fixtures.read_estimate(api, est_basis["id"])
    assert_fields(skipped, {"status": "SUBMITTED", "reconciliation_stale": False})
    assert_money(
        skipped["submitted_cost_of_work"],
        Decimal("1000000.00"),
        "submitted_cost_of_work",
    )

    _draws, draw_meta = validate_paginated(
        api.list_draws(OWNER_HEADERS, {"project_id": project_id})
    )
    assert draw_meta["total_count"] == 0, (
        "a scope change touched a contingency pot"
    )
    project = fixtures.read_project(api, project_id)
    assert_project_axes(project, gmp_status="EXECUTED", contingency_posture="OPEN")
    assert_money_fields(
        project,
        {
            "owner_contingency_remaining": Decimal("50000.00"),
            "construction_contingency_remaining": Decimal("40000.00"),
            "contingency_drawn_to_cost_total": Decimal("0.00"),
        },
    )
