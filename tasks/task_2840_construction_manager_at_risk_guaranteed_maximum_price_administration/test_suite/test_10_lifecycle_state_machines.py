"""Initial states, legal edges, terminal lockdowns and the side effects each edge fires.

Several rows in this domain carry two independent machines, and several single calls move
two rows at once. These tests pin where each machine starts, which edges exist, which
verbs a terminal state must refuse, and exactly how much of the price a transition is
allowed to write.
"""

from decimal import Decimal

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    CM_HEADERS,
    OWNER_HEADERS,
    PO_HEADERS,
    ApiClient,
    ApiErrorId,
    assert_equals,
    assert_fields,
    assert_money,
    assert_money_fields,
    assert_project_axes,
    assert_ratio,
    factories,
    fixtures,
    row_by_id,
    user_id_of,
)

#: The registration payload every recipe in this file starts from.
HARBORVIEW_CLINIC = {"name": "Harborview Clinic", "owner_org": "Harborview Health"}

#: The same clinic, priced through the fixtures, with its preconstruction fee declared.
CLINIC_KWARGS = {
    "project_kwargs": {
        "name": "Harborview Clinic",
        "owner_org": "Harborview Health",
        "precon_fee_amount": Decimal("25000.00"),
    }
}

STD_COST_OF_WORK = Decimal("1000000.00")


def _registered_clinic(api: ApiClient) -> dict:
    """Register the clinic and hand back the freshly minted project row."""
    return validate_success(
        api.create_project(factories.project_payload(**HARBORVIEW_CLINIC), ADMIN_HEADERS),
        201,
    )


def test_the_first_estimate_of_a_project_is_born_a_draft_with_no_basis(
    api: ApiClient,
) -> None:
    """No reconciled predecessor exists, so the variance rule takes its NO_BASIS branch.

    PRD: "The milestone codes, in ascending design maturity, are `SD`, `DD`, `CD_50`, `CD_100` and `GMP_BASIS`; the server stamps a `milestone_rank` on the row from a fixed ranking in which `SD` ranks 1, `DD` ranks 2, `CD_50` ranks 3, `CD_100` ranks 4 and `GMP_BASIS` ranks 5."

    PRD: "If that candidate set is empty, there is no basis, `variance_basis` is recorded as `NO_BASIS`, `variance_basis_estimate_id` stays null and `variance_pct` is 0.0000."

    PRD: "Submission by the `ConstructionManager` advances the estimate `DRAFT → SUBMITTED`, and the same action re-entered from a returned estimate advances it `RETURNED → SUBMITTED` — a loop that may repeat without bound."

    PRD: "Filing a newer estimate for the same `project_id` and the same `milestone_code` supersedes its predecessor: any prior estimate of that project and milestone whose status is `DRAFT`, `SUBMITTED` or `RETURNED` moves to `SUPERSEDED`, has its `superseded_by_estimate_id` set to the new row's identifier, and has its `version` incremented."

    Design: Corner/state_machines/estimate_creation_mints_draft_at_the_initial_state_with_no_variance_basis
    """
    project = _registered_clinic(api)
    estimate = validate_success(
        api.create_estimate(
            factories.estimate_payload(
                project["id"],
                project["version"],
                milestone_code="SD",
                submitted_cost_of_work=STD_COST_OF_WORK,
            ),
            CM_HEADERS,
        ),
        201,
    )

    assert_fields(
        estimate,
        {
            "status": "DRAFT",
            "milestone_code": "SD",
            "variance_basis": "NO_BASIS",
            "variance_basis_estimate_id": None,
            "reconciliation_stale": False,
            "superseded_by_estimate_id": None,
        },
    )
    assert_equals(estimate, "milestone_rank", 1)
    assert_ratio(estimate["variance_pct"], Decimal("0.0000"), "variance_pct")
    assert_money(
        estimate["submitted_cost_of_work"], STD_COST_OF_WORK, "submitted_cost_of_work"
    )

    assert_project_axes(
        fixtures.read_project(api, project["id"]), gmp_status="PRECONSTRUCTION"
    )


def test_submitting_the_base_proposal_moves_two_machines_and_copies_nothing(
    api: ApiClient,
) -> None:
    """The proposal reaches owner review and drags the project axis with it — no money moves.

    PRD: "Submitting the proposal, with an optional `cover_note`, advances it `DRAFT → OWNER_REVIEW`, and the same action re-entered after a return advances it `RETURNED_FOR_REVISION → OWNER_REVIEW`; that revision loop may repeat without bound."

    PRD: "A base submission is additionally gated on the estimate behind `based_on_estimate_id` still being `RECONCILED`, and it drags the project's own axis along with it: `gmp_status` advances `PRECONSTRUCTION → GMP_UNDER_REVIEW` and the project's `version` increments."

    PRD: "A base proposal is minted with `proposal_type` recorded as `BASE`, `status` at `DRAFT`, `amount_delta` at 0.00 and `change_event_id` null, and the create increments the project's `version` by 1."

    PRD: "An `EXECUTE` on a **base** proposal is the moment the guaranteed maximum price comes into existence."

    PRD: "`proposed_gmp_amount` becomes the project's `gmp_amount` plus the sum of `amount_delta` over every amendment proposal of that project whose status is `DRAFT`, `OWNER_REVIEW` or `RETURNED_FOR_REVISION`, and `pending_amendment_count` becomes the count of those same rows."

    Design: Corner/state_machines/proposal_submit_advances_the_proposal_and_the_project_axis_together
    """
    priced = fixtures.draft_priced_project(api, **CLINIC_KWARGS)
    assert_fields(priced.proposal, {"status": "DRAFT", "proposal_type": "BASE"})

    submitted = validate_success(
        api.submit_gmp_proposal(
            priced.proposal["id"],
            CM_HEADERS,
            factories.proposal_submit_payload("GMP proposal for owner review"),
        )
    )
    assert_fields(submitted, {"status": "OWNER_REVIEW", "proposal_type": "BASE"})
    assert_equals(submitted, "revision_count", 0)
    assert_money_fields(
        submitted,
        {
            "provisional_fee_amount": Decimal("44000.00"),
            "insurance_amount": Decimal("11440.00"),
            "cm_fee_amount": Decimal("44457.60"),
            "gmp_amount": Decimal("1245897.60"),
            "amount_delta": Decimal("0.00"),
        },
    )

    project = fixtures.read_project(api, priced.id)
    assert_project_axes(project, gmp_status="GMP_UNDER_REVIEW")
    assert_equals(project, "pending_amendment_count", 0)
    assert_money_fields(
        project,
        {
            "gmp_amount": Decimal("0.00"),
            "cm_fee_amount": Decimal("0.00"),
            "insurance_amount": Decimal("0.00"),
            "owner_contingency_original": Decimal("0.00"),
            "construction_contingency_original": Decimal("0.00"),
        },
    )


def test_the_audit_may_not_open_over_a_report_that_is_still_open(
    api: ApiClient,
) -> None:
    """The same request fails and then succeeds, changed only by a sibling row's state.

    PRD: "An `OwnerRepresentative` exercises those rights with an optional `audit_scope_note`, moving `audit_status` `NOT_REQUESTED → IN_PROGRESS`."

    PRD: "Two preconditions apply: the project's `gmp_status` must be `EXECUTED` (`ERR_GMP_NOT_EXECUTED`, HTTP 409), and at least one cost report of the project must be at `RECONCILED` — there must be something to audit, and an empty reconciled set is rejected with `ERR_NO_RECONCILED_COST_REPORT` (HTTP 422) rather than opening an audit over nothing."

    PRD: "A `RECONCILE` decision is permitted from `OPEN` or from `DISPUTED` — the latter being how a dispute is resolved after the parties settle it — and requires the report's `line_count` to be at least 1; it advances the report to `RECONCILED` and stamps `reconciled_at` from the logical clock."

    PRD: "The report's `reported_cost_total` is then the sum of `line_amount` over every line, `undisputed_cost_total` is the sum of `line_amount` over lines whose `disputed` is false, `disputed_cost_total` is the sum over lines whose `disputed` is true, and `line_count` is the number of entries in `lines`."

    Design: Corner/state_machines/audit_request_without_a_reconciled_cost_report_is_refused_then_succeeds
    """
    priced = fixtures.executed_project(api, **CLINIC_KWARGS)
    report = fixtures.cost_report(api, priced.id)
    fixtures.append_line(
        api,
        report["id"],
        cost_code="03-100",
        quantity=Decimal("1.0000"),
        unit_rate=Decimal("900000.0000"),
        markup_pct=Decimal("0.0000"),
        disputed=False,
    )
    assert_fields(fixtures.read_cost_report(api, report["id"]), {"status": "OPEN"})

    validate_error(
        api.request_audit(priced.id, OWNER_HEADERS),
        ApiErrorId.NO_RECONCILED_COST_REPORT,
        422,
    )
    assert_project_axes(
        fixtures.read_project(api, priced.id), audit_status="NOT_REQUESTED"
    )

    reconciled = validate_success(
        api.reconcile_cost_report(
            report["id"],
            factories.cost_report_reconcile_payload("RECONCILE"),
            OWNER_HEADERS,
        )
    )
    assert_fields(reconciled, {"status": "RECONCILED"})
    assert_money(
        reconciled["reported_cost_total"], Decimal("900000.00"), "reported_cost_total"
    )

    validate_success(api.request_audit(priced.id, OWNER_HEADERS))
    project = fixtures.read_project(api, priced.id)
    assert_project_axes(project, audit_status="IN_PROGRESS")
    assert_money(
        project["audit_adjustment_total"], Decimal("0.00"), "audit_adjustment_total"
    )


def test_execution_copies_four_figures_and_funds_both_pots_without_the_provisional_fee(
    api: ApiClient,
) -> None:
    """The only call that writes the price onto the project, and what it must leave behind.

    PRD: "The proposal advances `OWNER_REVIEW → EXECUTED`, the project advances `GMP_UNDER_REVIEW → EXECUTED`, and the proposal's figures are copied onto the project: `gmp_amount` from the proposal's `gmp_amount`, `cost_of_work_budget_total` from `cost_of_work_total`, `general_conditions_total` from `general_conditions_total`, `insurance_amount` from `insurance_amount`, and `cm_fee_amount` from `cm_fee_amount`."

    PRD: "Both contingency pots are funded at once: `owner_contingency_original` and `owner_contingency_remaining` are both set to the proposal's `owner_contingency_amount`, and `construction_contingency_original` and `construction_contingency_remaining` are both set to the proposal's `construction_contingency_amount`, while `contingency_drawn_to_cost_total` is set to 0.00."

    PRD: "The project's `proposed_gmp_amount` is then rolled up — with no pending amendments it equals the executed `gmp_amount` — the `contingency_posture` is re-derived (a fully funded construction pot yields `OPEN`), and the project's `version` increments by 1."

    PRD: "This figure exists only to gross up the insurance base; it is never itself a component of the guaranteed maximum price."

    PRD: "A lump-sum `precon_fee_amount` for preconstruction services may also be supplied; it must be at least 0.00, defaults to 0.00 when omitted, and is invoiced **outside** the guaranteed maximum price, so it never appears in any of the envelope identities."

    Design: Corner/state_machines/gmp_execution_copies_the_four_priced_outputs_and_funds_both_pots
    """
    priced = fixtures.submitted_proposal_project(api, **CLINIC_KWARGS)
    executed = validate_success(
        api.decide_gmp_proposal(
            priced.proposal["id"],
            factories.proposal_decision_payload("EXECUTE", "GMP executed"),
            OWNER_HEADERS,
        )
    )
    assert_fields(executed, {"status": "EXECUTED"})
    assert_money(
        executed["provisional_fee_amount"], Decimal("44000.00"), "provisional_fee_amount"
    )

    project = fixtures.read_project(api, priced.id)
    assert_project_axes(project, gmp_status="EXECUTED", contingency_posture="OPEN")
    assert_equals(project, "pending_amendment_count", 0)
    assert_money_fields(
        project,
        {
            "gmp_amount": Decimal("1245897.60"),
            "cost_of_work_budget_total": Decimal("1000000.00"),
            "general_conditions_total": Decimal("100000.00"),
            "insurance_amount": Decimal("11440.00"),
            "cm_fee_amount": Decimal("44457.60"),
            "owner_contingency_original": Decimal("50000.00"),
            "owner_contingency_remaining": Decimal("50000.00"),
            "construction_contingency_original": Decimal("40000.00"),
            "construction_contingency_remaining": Decimal("40000.00"),
            "contingency_drawn_to_cost_total": Decimal("0.00"),
            "proposed_gmp_amount": Decimal("1245897.60"),
            "precon_fee_amount": Decimal("25000.00"),
        },
    )
    assert "provisional_fee_amount" not in project, (
        "the provisional fee leaked from the proposal onto the project"
    )


def test_a_draft_estimate_cannot_be_reconciled_until_it_has_been_submitted(
    api: ApiClient,
) -> None:
    """The identical reconcile payload is refused, then accepted, once submit has run.

    PRD: "An `OwnerRepresentative` decides a submitted estimate with a `decision` of either `ACCEPT` or `RETURN`, optionally recording a `reconciliation_note` which is written onto the row in either case."

    PRD: "Both decisions are permitted only from `SUBMITTED`; anything else is `ERR_ESTIMATE_STATE_INVALID` (HTTP 409)."

    PRD: "`ACCEPT` advances the estimate `SUBMITTED → RECONCILED` and clears `reconciliation_stale` to false; `RETURN` advances it `SUBMITTED → RETURNED`, sending it back to the construction manager for revision."

    Design: Corner/state_machines/reconcile_on_a_draft_estimate_is_rejected_before_submission
    """
    project = _registered_clinic(api)
    estimate = fixtures.create_estimate(
        api, project["id"], expected_project_version=project["version"]
    )

    validate_error(
        api.reconcile_estimate(
            estimate["id"],
            factories.estimate_reconcile_payload("ACCEPT", "premature"),
            OWNER_HEADERS,
        ),
        ApiErrorId.ESTIMATE_STATE_INVALID,
        409,
    )
    untouched = fixtures.read_estimate(api, estimate["id"])
    assert_fields(
        untouched,
        {
            "status": "DRAFT",
            "reconciliation_note": None,
            "version": estimate["version"],
        },
    )

    submitted = validate_success(
        api.submit_estimate(
            estimate["id"], factories.estimate_submit_payload(), CM_HEADERS
        )
    )
    assert_fields(submitted, {"status": "SUBMITTED"})

    reconciled = validate_success(
        api.reconcile_estimate(
            estimate["id"],
            factories.estimate_reconcile_payload("ACCEPT", "accepted"),
            OWNER_HEADERS,
        )
    )
    assert_fields(
        reconciled,
        {
            "status": "RECONCILED",
            "reconciliation_note": "accepted",
            "reconciliation_stale": False,
        },
    )


def test_a_reconciled_milestone_is_terminal_on_both_of_its_verbs(
    api: ApiClient,
) -> None:
    """Neither submit nor a second reconcile may reopen a milestone the owner accepted.

    PRD: "Submission is refused from any other status with `ERR_ESTIMATE_STATE_INVALID` (HTTP 409)."

    PRD: "Both decisions are permitted only from `SUBMITTED`; anything else is `ERR_ESTIMATE_STATE_INVALID` (HTTP 409)."

    PRD: "Either decision increments the estimate's `version`."

    PRD: "Estimates already at `RECONCILED` are never superseded; they remain the reconciliation basis for everything downstream."

    Design: Corner/state_machines/reconciled_estimate_refuses_both_a_further_submit_and_a_further_reconcile
    """
    project = _registered_clinic(api)
    estimate = fixtures.create_estimate(
        api, project["id"], expected_project_version=project["version"]
    )
    validate_success(
        api.submit_estimate(
            estimate["id"], factories.estimate_submit_payload(), CM_HEADERS
        )
    )
    reconciled = validate_success(
        api.reconcile_estimate(
            estimate["id"],
            factories.estimate_reconcile_payload("ACCEPT", "accepted at SD"),
            OWNER_HEADERS,
        )
    )
    settled_version = reconciled["version"]

    validate_error(
        api.submit_estimate(
            estimate["id"],
            factories.estimate_submit_payload("reopening"),
            CM_HEADERS,
        ),
        ApiErrorId.ESTIMATE_STATE_INVALID,
        409,
    )
    validate_error(
        api.reconcile_estimate(
            estimate["id"],
            factories.estimate_reconcile_payload("RETURN", "changed my mind"),
            OWNER_HEADERS,
        ),
        ApiErrorId.ESTIMATE_STATE_INVALID,
        409,
    )

    assert_fields(
        fixtures.read_estimate(api, estimate["id"]),
        {
            "status": "RECONCILED",
            "reconciliation_note": "accepted at SD",
            "version": settled_version,
        },
    )


def test_a_second_submit_of_a_proposal_under_review_is_refused_not_absorbed(
    api: ApiClient,
) -> None:
    """Submit is not idempotent: the replay must fail loudly rather than re-fire the axis.

    PRD: "Submitting from any other status is `ERR_PROPOSAL_STATE_INVALID` (HTTP 409)."

    PRD: "Submitting the proposal, with an optional `cover_note`, advances it `DRAFT → OWNER_REVIEW`, and the same action re-entered after a return advances it `RETURNED_FOR_REVISION → OWNER_REVIEW`; that revision loop may repeat without bound."

    PRD: "A `RETURN` advances the proposal `OWNER_REVIEW → RETURNED_FOR_REVISION`, increments its `revision_count` by 1, and for a base proposal walks the project back `GMP_UNDER_REVIEW → PRECONSTRUCTION` so that the construction manager can revise its pricing while the project sits in preconstruction again."

    Design: Corner/state_machines/second_submit_of_a_proposal_under_review_is_rejected_not_absorbed
    """
    priced = fixtures.submitted_proposal_project(api, **CLINIC_KWARGS)
    version_after_first_submit = fixtures.project_version(api, priced.id)

    validate_error(
        api.submit_gmp_proposal(
            priced.proposal["id"],
            CM_HEADERS,
            factories.proposal_submit_payload("resubmitting the same proposal"),
        ),
        ApiErrorId.PROPOSAL_STATE_INVALID,
        409,
    )

    proposal = fixtures.read_proposal(api, priced.proposal["id"])
    assert_fields(proposal, {"status": "OWNER_REVIEW", "proposal_type": "BASE"})
    assert_equals(proposal, "revision_count", 0)

    project = fixtures.read_project(api, priced.id)
    assert_project_axes(project, gmp_status="GMP_UNDER_REVIEW")
    assert_equals(project, "version", version_after_first_submit)


def test_the_disclosure_ratchet_moves_without_touching_the_procurement_axis(
    api: ApiClient,
) -> None:
    """One package row, two machines: the disclosure axis walks while buyout stands still.

    PRD: "Neither axis constrains the other's position: a package may be `DISCLOSED` while still `BUDGETED`, or while already `CLOSED`."

    PRD: "A `ProcurementOfficer` publishes the cost breakdowns to the owner by naming `target_status` `DISCLOSED`, advancing the package `SEALED → DISCLOSED`; this requires the package to have attracted at least one bid, that is `bid_count` of 1 or more."

    PRD: "An `IndependentAuditor` then certifies them by naming `target_status` `AUDITED`, advancing `DISCLOSED → AUDITED`."

    PRD: "Neither step may be skipped and neither may be regressed — a request to reach `AUDITED` from `SEALED`, or to return to `SEALED` from anywhere, is rejected with `ERR_PACKAGE_STATE_INVALID` (HTTP 409) — and the package's `procurement_status` is never touched by either step."

    PRD: "A new package begins with `procurement_status` at `BUDGETED`, `transparency_status` at `SEALED`, `awarded_bid_id` null, `awarded_amount` at 0.00, `committed_amount` at 0.00, `replacement_reserve_amount` at 0.00, `bid_count` at 0, and both `solicitation_opens_at` and `solicitation_closes_at` null."

    Design: Corner/state_machines/transparency_axis_advances_while_the_procurement_axis_stays_budgeted
    """
    priced = fixtures.executed_project(api, **CLINIC_KWARGS)
    concrete = fixtures.soliciting_package(
        api, priced.id, budget_amount=Decimal("500000.00"), trade_division="03-CONCRETE"
    )
    fixtures.third_party_bid(api, concrete["id"], base_bid_amount=Decimal("460000.00"))
    finishes = fixtures.work_package(
        api, priced.id, budget_amount=Decimal("300000.00"), trade_division="09-FINISHES"
    )

    validate_error(
        api.set_transparency(
            concrete["id"], factories.transparency_payload("AUDITED"), AUDITOR_HEADERS
        ),
        ApiErrorId.PACKAGE_STATE_INVALID,
        409,
    )
    assert_fields(
        fixtures.read_work_package(api, concrete["id"]),
        {"transparency_status": "SEALED", "procurement_status": "SOLICITING"},
    )

    disclosed = validate_success(
        api.set_transparency(
            concrete["id"],
            factories.transparency_payload(
                "DISCLOSED", "open-book breakdowns published"
            ),
            PO_HEADERS,
        )
    )
    assert_fields(disclosed, {"transparency_status": "DISCLOSED"})
    audited = validate_success(
        api.set_transparency(
            concrete["id"], factories.transparency_payload("AUDITED"), AUDITOR_HEADERS
        )
    )
    assert_fields(
        audited,
        {
            "transparency_status": "AUDITED",
            "procurement_status": "SOLICITING",
            "awarded_bid_id": None,
        },
    )
    assert_equals(audited, "bid_count", 1)
    assert_money(audited["awarded_amount"], Decimal("0.00"), "awarded_amount")
    assert_money(audited["committed_amount"], Decimal("0.00"), "committed_amount")

    assert_fields(
        fixtures.read_work_package(api, finishes["id"]),
        {
            "transparency_status": "SEALED",
            "procurement_status": "BUDGETED",
            "awarded_bid_id": None,
            "solicitation_opens_at": None,
            "solicitation_closes_at": None,
        },
    )


def test_progress_payments_keep_the_paid_and_unpaid_ledger_summing_to_the_contract(
    api: ApiClient,
) -> None:
    """Completion is gated on the ledger, so it is refused midway and accepted at the end.

    PRD: "A new subcontract begins with `contract_status` at `ACTIVE`, `paid_to_date` at 0.00, `unpaid_committed_amount` equal to its `contract_amount`, `replacement_cost_amount` at 0.00, `bond_claim_amount` at 0.00, `bond_recovered_amount` at 0.00, `default_notice_at` null and `cure_count` at 0."

    PRD: "Monthly progress is applied by the `ConstructionManager` supplying a `payment_amount`, which increases the subcontract's `paid_to_date` by that amount and rewrites `unpaid_committed_amount` as `contract_amount` less `paid_to_date` — reducing, payment by payment, the exposure a default would have to replace."

    PRD: "Completing advances `ACTIVE → COMPLETED` and requires that `paid_to_date` has reached `contract_amount` exactly."

    PRD: "Each of these actions is permitted only from the status named, and any other combination is rejected with `ERR_SUBCONTRACT_STATE_INVALID` (HTTP 409)."

    PRD: "That recount is defined once and used everywhere: a package's `committed_amount` is the sum of `contract_amount` over its subcontracts whose `contract_status` is `ACTIVE`, `DEFAULT_NOTICED` or `COMPLETED`, plus the sum of `paid_to_date` over its subcontracts whose `contract_status` is `TERMINATED_FOR_DEFAULT`."

    Design: Corner/state_machines/progress_payments_keep_the_paid_and_unpaid_subcontract_ledger_in_step
    """
    priced = fixtures.executed_project(api, **CLINIC_KWARGS)
    setup = fixtures.active_subcontract(
        api,
        priced.id,
        budget_amount=Decimal("500000.00"),
        base_bid_amount=Decimal("460000.00"),
    )
    assert_fields(
        setup.subcontract,
        {"contract_status": "ACTIVE", "bond_claim_status": "NOT_APPLICABLE"},
    )
    assert_equals(setup.subcontract, "cure_count", 0)
    assert_money_fields(
        setup.subcontract,
        {
            "contract_amount": Decimal("460000.00"),
            "paid_to_date": Decimal("0.00"),
            "unpaid_committed_amount": Decimal("460000.00"),
            "replacement_cost_amount": Decimal("0.00"),
        },
    )

    first = validate_success(
        api.progress_payment(
            setup.id,
            factories.progress_payment_payload(Decimal("120000.00")),
            CM_HEADERS,
        )
    )
    assert_money_fields(
        first,
        {
            "paid_to_date": Decimal("120000.00"),
            "unpaid_committed_amount": Decimal("340000.00"),
        },
    )

    validate_error(
        api.subcontract_status_action(
            setup.id, factories.status_action_payload("COMPLETE"), CM_HEADERS
        ),
        ApiErrorId.SUBCONTRACT_STATE_INVALID,
        409,
    )
    assert_fields(
        fixtures.read_subcontract(api, setup.id), {"contract_status": "ACTIVE"}
    )

    second = validate_success(
        api.progress_payment(
            setup.id,
            factories.progress_payment_payload(Decimal("340000.00")),
            CM_HEADERS,
        )
    )
    assert_money_fields(
        second,
        {
            "paid_to_date": Decimal("460000.00"),
            "unpaid_committed_amount": Decimal("0.00"),
        },
    )

    completed = validate_success(
        api.subcontract_status_action(
            setup.id, factories.status_action_payload("COMPLETE"), CM_HEADERS
        )
    )
    assert_fields(completed, {"contract_status": "COMPLETED"})

    package = fixtures.read_work_package(api, setup.package["id"])
    assert_money_fields(
        package,
        {
            "committed_amount": Decimal("460000.00"),
            "awarded_amount": Decimal("460000.00"),
        },
    )
    assert_money_fields(
        fixtures.read_project(api, priced.id),
        {
            "buyout_savings_trade_level": Decimal("40000.00"),
            "buyout_savings_project_net": Decimal("40000.00"),
        },
    )


def test_each_sealed_bid_bumps_the_parent_package_count_and_version(
    api: ApiClient,
) -> None:
    """Inserting a child mutates the parent, and the sealed breakdown stays hidden.

    PRD: "A bid is minted at `SEALED` with `prepared_by_user_id` taken from the submitting operator's `X-User-ID`, `opened_by_user_id` null and `opened_at` null; the parent package's `bid_count` increases by 1 and its `version` increments."

    PRD: "A sealed bid's breakdown is suppressed on read: `open_book_cost_breakdown` is populated in responses only for bids whose status is `OPENED`, `AWARDED` or `NOT_AWARDED`, and reads as null while the bid is still `SEALED`."

    PRD: "The award advances the package `SOLICITING → AWARDED`, writes `awarded_bid_id` from the supplied `bid_id` and `awarded_amount` from that bid's `base_bid_amount`, advances the winning bid `OPENED → AWARDED`, and moves **every other** bid on that package that is currently `OPENED` to `NOT_AWARDED`."

    Design: Corner/state_machines/bid_submission_bubbles_the_bid_count_up_to_the_parent_package
    """
    priced = fixtures.executed_project(api, **CLINIC_KWARGS)
    package = fixtures.soliciting_package(
        api, priced.id, budget_amount=Decimal("500000.00"), trade_division="03-CONCRETE"
    )
    assert_equals(package, "bid_count", 0)
    version_before_bids = package["version"]

    cascade = validate_success(
        api.create_bid(
            factories.third_party_bid_payload(
                package["id"],
                base_bid_amount=Decimal("460000.00"),
                bidder_name="Cascade Concrete",
            ),
            CM_HEADERS,
        ),
        201,
    )
    ironbound = validate_success(
        api.create_bid(
            factories.third_party_bid_payload(
                package["id"],
                base_bid_amount=Decimal("471500.00"),
                bidder_name="Ironbound Concrete",
            ),
            CM_HEADERS,
        ),
        201,
    )
    for bid in (cascade, ironbound):
        assert_fields(
            bid,
            {
                "status": "SEALED",
                "prepared_by_user_id": user_id_of("cm_estimator"),
                "opened_by_user_id": None,
                "opened_at": None,
                "open_book_cost_breakdown": None,
            },
        )

    after = fixtures.read_work_package(api, package["id"])
    assert_equals(after, "bid_count", 2)
    assert_equals(after, "version", version_before_bids + 2)
    assert_fields(
        after, {"procurement_status": "SOLICITING", "awarded_bid_id": None}
    )
    assert_money(after["awarded_amount"], Decimal("0.00"), "awarded_amount")

    rows, meta = validate_paginated(
        api.list_bids(CM_HEADERS, {"work_package_id": package["id"]})
    )
    assert meta["total_count"] == 2, "the package did not list both of its sealed bids"
    for bid in (cascade, ironbound):
        listed = row_by_id(rows, bid["id"])
        assert_fields(
            listed, {"status": "SEALED", "open_book_cost_breakdown": None}
        )


def test_settlement_closes_the_price_freezes_the_pots_and_closes_awarded_packages(
    api: ApiClient,
) -> None:
    """One settling call fires four transitions and then locks the project against replay.

    PRD: "**Settlement** is `POST_AUDIT_FINAL` with `execute` true, and it is permitted only when the project's `closeout_status` is already `FINAL_COMPUTED` — the audited figures must have been computed and stored before they can be settled."

    PRD: "Settlement advances `closeout_status` `FINAL_COMPUTED → SETTLEMENT_EXECUTED`, which is terminal, and cascades three further changes: the project's `gmp_status` moves `EXECUTED → CLOSED`; the project's `contingency_posture` moves to `FROZEN` from whichever of `OPEN` or `CONSTRAINED` it held; and every work package of the project whose `procurement_status` is `AWARDED` moves to `CLOSED`."

    PRD: "Attempting settlement on a project already at `SETTLEMENT_EXECUTED` is rejected with `ERR_CLOSEOUT_ALREADY_SETTLED` (HTTP 409), and — as §2.11 sets out — after settlement the frozen posture, not the settled closeout, is what turns away any attempt to post or void a contingency draw."

    PRD: "It is permitted from `REQUESTED` only when `requires_owner_approval` is false, and otherwise from `OWNER_APPROVED`; from any other status it draws `ERR_DRAW_STATE_INVALID` (HTTP 409)."

    PRD: "With `execute` false it writes `final_savings_pool`, `final_cm_savings_share` and `final_owner_savings_share` and moves `closeout_status` to `FINAL_COMPUTED`, from either `NOT_STARTED` or `PROVISIONAL_COMPUTED`."

    Design: Corner/state_machines/settlement_execution_closes_the_price_freezes_contingency_and_closes_awarded_packages
    """
    priced = fixtures.executed_project(api, **CLINIC_KWARGS)
    awarded = fixtures.awarded_package(
        api,
        priced.id,
        budget_amount=Decimal("500000.00"),
        base_bid_amount=Decimal("460000.00"),
    )
    draw = fixtures.requested_draw(
        api,
        priced.id,
        Decimal("30000.00"),
        "CONTINGENCY_USE_CONSTRUCTION",
        description="unforeseen dewatering at the north footing",
    )
    assert_fields(
        draw,
        {
            "status": "REQUESTED",
            "contingency_type": "CONSTRUCTION",
            "origin": "CHANGE_EVENT_CLASSIFICATION",
            "requires_owner_approval": False,
        },
    )

    fixtures.reconciled_cost_report(
        api,
        priced.id,
        quantity=Decimal("1.0000"),
        unit_rate=Decimal("1155000.0000"),
    )
    fixtures.closed_audit(api, priced.id)
    fixtures.final_savings(api, priced.id, execute=False)

    computed = fixtures.read_project(api, priced.id)
    assert_project_axes(computed, closeout_status="FINAL_COMPUTED")
    assert_money_fields(
        computed,
        {
            "final_savings_pool": Decimal("35000.00"),
            "final_cm_savings_share": Decimal("11114.40"),
            "final_owner_savings_share": Decimal("23885.60"),
        },
    )

    validate_success(
        api.shared_savings(
            priced.id,
            factories.shared_savings_payload("POST_AUDIT_FINAL", True),
            OWNER_HEADERS,
        )
    )
    settled = fixtures.read_project(api, priced.id)
    assert_project_axes(
        settled,
        gmp_status="CLOSED",
        contingency_posture="FROZEN",
        closeout_status="SETTLEMENT_EXECUTED",
    )
    assert_money_fields(
        settled,
        {
            "final_savings_pool": Decimal("35000.00"),
            "final_cm_savings_share": Decimal("11114.40"),
            "final_owner_savings_share": Decimal("23885.60"),
        },
    )
    assert_fields(
        fixtures.read_work_package(api, awarded.id), {"procurement_status": "CLOSED"}
    )

    validate_error(
        api.shared_savings(
            priced.id,
            factories.shared_savings_payload("POST_AUDIT_FINAL", True),
            OWNER_HEADERS,
        ),
        ApiErrorId.CLOSEOUT_ALREADY_SETTLED,
        409,
    )
    validate_error(
        api.post_draw(
            draw["id"], CM_HEADERS, factories.draw_post_payload("posting after settlement")
        ),
        ApiErrorId.CONTINGENCY_FROZEN,
        409,
    )
    assert_fields(fixtures.read_draw(api, draw["id"]), {"status": "REQUESTED"})
    assert_money_fields(
        fixtures.read_project(api, priced.id),
        {
            "construction_contingency_remaining": Decimal("40000.00"),
            "contingency_drawn_to_cost_total": Decimal("0.00"),
        },
    )
