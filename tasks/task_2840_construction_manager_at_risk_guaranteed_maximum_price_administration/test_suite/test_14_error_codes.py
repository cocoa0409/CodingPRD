"""Which identifier a refusal names, and why a near-miss does not get the same one.

Every error in this catalogue has a neighbour it could plausibly be confused with: a
generic 404 for an entity-specific one, a stale-version 412 for a closed-envelope 409, a
posture complaint for a status complaint. Each test here pins the boundary between a code
and its nearest rival, and then proves the refusal wrote nothing.
"""

from decimal import Decimal
from typing import Tuple

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CM_HEADERS,
    CM_PM_HEADERS,
    OWNER_HEADERS,
    PO_HEADERS,
    PO_INDEPENDENT_HEADERS,
    ApiClient,
    ApiErrorId,
    assert_equals,
    assert_fields,
    assert_gmp_identity,
    assert_money,
    assert_money_fields,
    assert_null,
    assert_project_axes,
    factories,
    fixtures,
    headers_for,
    user_id_of,
)
from test_helpers.constants import (
    ROLE_CONSTRUCTION_MANAGER,
    ROLE_PROCUREMENT_OFFICER,
)
from test_helpers.types import JsonObject

CLINIC_KWARGS = {"project_kwargs": {"name": "Harborview Clinic", "owner_org": "Harborview Health"}}
ABSENT_SUBCONTRACT_ID = "11111111-1111-1111-1111-111111111111"
ABSENT_CHANGE_EVENT_ID = "22222222-2222-2222-2222-222222222222"
ABSENT_PROPOSAL_ID = "33333333-3333-3333-3333-333333333333"
DUAL_HAT_OPERATOR = "dual-hat-operator"
AUGUST = ("2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z")


def test_the_four_way_split_of_not_found_is_observable_on_every_channel(
    api: ApiClient,
) -> None:
    """A subcontract, a change event and a proposal all vanish differently.

    PRD: "Identifiers that appear in a URL path are resolved left to right, and the first identifier that fails to resolve determines the error: a project identifier in a path that does not resolve yields `ERR_PROJECT_NOT_FOUND` (HTTP 404), a work-package identifier `ERR_WORK_PACKAGE_NOT_FOUND` (HTTP 404), a subcontract identifier `ERR_SUBCONTRACT_NOT_FOUND` (HTTP 404), a change-event identifier `ERR_CHANGE_EVENT_NOT_FOUND` (HTTP 404), and any other identifier — an estimate, a proposal, a qualification item, a self-perform bid, a contingency draw or a cost report — `ERR_RESOURCE_NOT_FOUND` (HTTP 404)."

    PRD: "The same four-way split applies to identifiers supplied in a request body: an unresolvable `project_id` yields `ERR_PROJECT_NOT_FOUND`, an unresolvable `work_package_id` yields `ERR_WORK_PACKAGE_NOT_FOUND`, and every other unresolvable body identifier — `prior_estimate_id`, `based_on_estimate_id`, `gmp_proposal_id`, `awarded_bid_id`, `bid_id`, `qualification_item_id`, `source_subcontract_id`, or a cost line's `work_package_id` — yields `ERR_RESOURCE_NOT_FOUND`."

    PRD: "The `message` provides a human-readable explanation of what went wrong."

    PRD: "`version` — an integer that starts at 1 when the row is created and increments by exactly 1 on every mutation of that row."

    Design: Corner/errors/unresolvable_ids_return_the_entity_specific_not_found_code_not_a_generic_one
    """
    executed = fixtures.executed_project(api, **CLINIC_KWARGS)
    settled_version = fixtures.project_version(api, executed.id)

    refusals = [
        validate_error(
            api.get_subcontract(ABSENT_SUBCONTRACT_ID, CM_HEADERS),
            ApiErrorId.SUBCONTRACT_NOT_FOUND,
            404,
        ),
        validate_error(
            api.progress_payment(
                ABSENT_SUBCONTRACT_ID,
                factories.progress_payment_payload(Decimal("1000.00")),
                CM_HEADERS,
            ),
            ApiErrorId.SUBCONTRACT_NOT_FOUND,
            404,
        ),
        validate_error(
            api.get_change_event(ABSENT_CHANGE_EVENT_ID, OWNER_HEADERS),
            ApiErrorId.CHANGE_EVENT_NOT_FOUND,
            404,
        ),
        validate_error(
            api.submit_change_event(
                ABSENT_CHANGE_EVENT_ID,
                CM_PM_HEADERS,
                factories.change_event_submit_payload(),
            ),
            ApiErrorId.CHANGE_EVENT_NOT_FOUND,
            404,
        ),
        validate_error(
            api.create_qualification_item(
                factories.qualification_item_payload(
                    ABSENT_PROPOSAL_ID, text="orphan assumption"
                ),
                CM_HEADERS,
            ),
            ApiErrorId.RESOURCE_NOT_FOUND,
            404,
        ),
    ]
    for refusal in refusals:
        assert refusal.get("message"), (
            f"every error body must carry a human-readable message, got {refusal!r}"
        )

    assert_equals(
        fixtures.read_project(api, executed.id), "version", settled_version
    )


def test_a_second_base_price_is_refused_by_the_envelope_not_by_the_version_check(
    api: ApiClient,
) -> None:
    """The version supplied is the current one, so only the executed envelope can be refusing.

    PRD: "If the named `based_on_estimate_id` does not name an estimate whose status is `RECONCILED`, the create is rejected with `ERR_ESTIMATE_STATE_INVALID` (HTTP 409); if the project's `gmp_status` is already `EXECUTED` or `CLOSED`, it is rejected with `ERR_GMP_ALREADY_EXECUTED` (HTTP 409)."

    PRD: "Creating a base guaranteed-maximum-price proposal likewise requires `expected_project_version` to equal the project's current `version`, and a mismatch is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412)."

    PRD: "As with estimates, a newer base proposal supersedes its predecessor: any prior base proposal of the same project whose status is `DRAFT`, `OWNER_REVIEW` or `RETURNED_FOR_REVISION` moves to `SUPERSEDED` with `superseded_by_proposal_id` set to the new row's identifier and its `version` incremented."

    PRD: "7. Stale-version rejection on the three creation operations listed in §2.10."

    Design: Corner/errors/a_second_base_proposal_after_execution_returns_gmp_already_executed
    """
    executed = fixtures.executed_project(api, **CLINIC_KWARGS)
    current_version = fixtures.project_version(api, executed.id)

    validate_error(
        api.create_gmp_proposal(
            factories.gmp_proposal_payload(
                executed.id,
                executed.estimate["id"],
                current_version,
                cost_of_work_total=Decimal("1010000.00"),
                general_conditions_total=Decimal("100000.00"),
                owner_contingency_amount=Decimal("50000.00"),
                construction_contingency_amount=Decimal("40000.00"),
            ),
            CM_HEADERS,
        ),
        ApiErrorId.GMP_ALREADY_EXECUTED,
        409,
    )

    assert_fields(
        fixtures.read_proposal(api, executed.proposal["id"]), {"status": "EXECUTED"}
    )
    project = fixtures.read_project(api, executed.id)
    assert_money_fields(
        project,
        {
            "gmp_amount": Decimal("1245897.60"),
            "cost_of_work_budget_total": Decimal("1000000.00"),
        },
    )
    assert_equals(project, "version", current_version)
    _, meta = validate_paginated(
        api.list_gmp_proposals(CM_HEADERS, {"project_id": executed.id})
    )
    assert meta["total_count"] == 1, (
        f"the refused create must not have stored a row, got {meta['total_count']}"
    )


def test_classify_and_request_revision_both_need_the_review_to_have_been_opened(
    api: ApiClient,
) -> None:
    """A draft event has no submitter to compare against, so the refusal cannot be identity-based.

    PRD: "A new event is minted with `status` at `DRAFT`, `classification` deliberately null, `revision_count` at 0, and `submitted_by_user_id`, `classified_by_user_id`, `classified_at` and `review_note` all null."

    PRD: "Every submission overwrites `submitted_by_user_id` with the acting `X-User-ID`, which is the anchor of the segregation-of-duties rule at classification time; a resubmission by a different operator therefore moves the anchor."

    PRD: "Requesting a revision advances `UNDER_REVIEW → REVISION_REQUESTED` and increments `revision_count` by 1; the loop from submission through review to revision request and back to submission may repeat without bound."

    PRD: "Each review action is permitted only from the status named and otherwise draws `ERR_CHANGE_EVENT_STATE_INVALID` (HTTP 409), and each increments the event's `version`."

    PRD: "It is permitted only from `UNDER_REVIEW` (otherwise `ERR_CHANGE_EVENT_STATE_INVALID`, HTTP 409), only while the project is `EXECUTED` (otherwise `ERR_GMP_NOT_EXECUTED`, HTTP 409), only before the project's `closeout_status` reaches `SETTLEMENT_EXECUTED` (otherwise `ERR_CLOSEOUT_ALREADY_SETTLED`, HTTP 409), and only by an operator whose `X-User-ID` differs from the event's `submitted_by_user_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`, HTTP 403)."

    Design: Corner/errors/classify_and_review_before_the_event_is_under_review_return_change_event_state_invalid
    """
    executed = fixtures.executed_project(api, **CLINIC_KWARGS)
    event = fixtures.change_event(
        api,
        executed.id,
        estimated_amount=Decimal("18000.00"),
        origin="FIELD_CONDITION",
        description="unforeseen rock at the west footings",
    )
    minted_version = event["version"]
    assert_fields(event, {"status": "DRAFT"})
    assert_null(event, "submitted_by_user_id", "classification", "classified_by_user_id")

    validate_error(
        api.classify_change_event(
            event["id"],
            factories.classify_payload("CONTINGENCY_USE_CONSTRUCTION"),
            OWNER_HEADERS,
        ),
        ApiErrorId.CHANGE_EVENT_STATE_INVALID,
        409,
    )
    assert_fields(
        fixtures.read_change_event(api, event["id"]),
        {"status": "DRAFT", "version": minted_version},
    )

    validate_error(
        api.review_change_event(
            event["id"],
            factories.change_event_review_payload("REQUEST_REVISION"),
            OWNER_HEADERS,
        ),
        ApiErrorId.CHANGE_EVENT_STATE_INVALID,
        409,
    )

    submitted = validate_success(
        api.submit_change_event(
            event["id"], CM_PM_HEADERS, factories.change_event_submit_payload()
        )
    )
    assert_fields(
        submitted,
        {"status": "SUBMITTED", "submitted_by_user_id": user_id_of("cm_pm")},
    )

    validate_error(
        api.classify_change_event(
            event["id"],
            factories.classify_payload("CONTINGENCY_USE_CONSTRUCTION"),
            OWNER_HEADERS,
        ),
        ApiErrorId.CHANGE_EVENT_STATE_INVALID,
        409,
    )

    settled = fixtures.read_change_event(api, event["id"])
    assert_fields(settled, {"status": "SUBMITTED", "revision_count": 0})
    assert_null(settled, "classification", "classified_by_user_id", "classified_at")
    _, draw_meta = validate_paginated(
        api.list_draws(OWNER_HEADERS, {"project_id": executed.id})
    )
    assert draw_meta["total_count"] == 0, (
        f"no draw may be minted before a classification, got {draw_meta['total_count']}"
    )
    assert_money(
        fixtures.read_project(api, executed.id)["construction_contingency_remaining"],
        Decimal("40000.00"),
        "construction_contingency_remaining",
    )


def test_a_reconciled_report_refuses_lines_and_a_second_decision_by_status_not_posture(
    api: ApiClient,
) -> None:
    """Release-hold on a healthy OPEN report is a status complaint, not a posture complaint.

    PRD: "It is permitted only from `RECONCILIATION_HELD` (`ERR_COST_REPORT_STATE_INVALID`, HTTP 409) and only once the project's `contingency_posture` has recovered to `OPEN`; a release attempted while the posture is still `CONSTRAINED` or `FROZEN` is rejected with `ERR_POSTURE_NOT_RECOVERED` (HTTP 409)."

    PRD: "8. State preconditions — the family of `409 Conflict` conditions detailed in §3, in this internal order: the project's `gmp_status` gates, then the per-entity status gates for estimates, proposals, work packages, bids, subcontracts, bond claims, change events, contingency draws, cost reports and the audit engagement, then `ERR_CLOSEOUT_ALREADY_SETTLED`, then `ERR_CONTINGENCY_FROZEN`, then `ERR_POSTURE_NOT_RECOVERED`."

    PRD: "A `RECONCILE` decision is permitted from `OPEN` or from `DISPUTED` — the latter being how a dispute is resolved after the parties settle it — and requires the report's `line_count` to be at least 1; it advances the report to `RECONCILED` and stamps `reconciled_at` from the logical clock."

    PRD: "A `DISPUTE` decision is permitted only from `OPEN` and only when the report's `disputed_cost_total` is strictly greater than 0.00 — there is nothing to dispute on a report with no disputed lines — and advances the report to `DISPUTED`."

    PRD: "A report sitting at `RECONCILIATION_HELD` accepts neither new lines nor a reconcile decision, and any action attempted from a status that does not permit it is rejected with `ERR_COST_REPORT_STATE_INVALID` (HTTP 409)."

    PRD: "Appending a line is permitted from `OPEN` or `DISPUTED`, and is refused after settlement with `ERR_CLOSEOUT_ALREADY_SETTLED` (HTTP 409)."

    Design: Corner/errors/lines_reconcile_and_release_hold_on_the_wrong_report_status_return_cost_report_state_invalid
    """
    executed = fixtures.executed_project(api, **CLINIC_KWARGS)
    report = fixtures.cost_report(
        api, executed.id, period_start=AUGUST[0], period_end=AUGUST[1]
    )
    fixtures.append_line(
        api,
        report["id"],
        cost_code="03-100",
        quantity=Decimal("200.0000"),
        unit_rate=Decimal("62.5000"),
        markup_pct=Decimal("0.0000"),
        disputed=False,
    )
    assert_project_axes(
        fixtures.read_project(api, executed.id), contingency_posture="OPEN"
    )

    validate_error(
        api.release_hold(
            report["id"], OWNER_HEADERS, factories.release_hold_payload("nothing is being held")
        ),
        ApiErrorId.COST_REPORT_STATE_INVALID,
        409,
    )
    assert_fields(fixtures.read_cost_report(api, report["id"]), {"status": "OPEN"})

    reconciled = validate_success(
        api.reconcile_cost_report(
            report["id"],
            factories.cost_report_reconcile_payload("RECONCILE"),
            OWNER_HEADERS,
        )
    )
    assert_fields(reconciled, {"status": "RECONCILED"})
    assert_money(
        reconciled["reported_cost_total"], Decimal("12500.00"), "reported_cost_total"
    )
    decided_version = reconciled["version"]

    validate_error(
        api.append_cost_line(
            report["id"],
            factories.cost_line_payload(
                quantity=Decimal("10.0000"),
                unit_rate=Decimal("100.0000"),
                markup_pct=Decimal("0.0000"),
                cost_code="03-200",
                disputed=False,
            ),
            CM_HEADERS,
        ),
        ApiErrorId.COST_REPORT_STATE_INVALID,
        409,
    )
    validate_error(
        api.reconcile_cost_report(
            report["id"],
            factories.cost_report_reconcile_payload("DISPUTE"),
            OWNER_HEADERS,
        ),
        ApiErrorId.COST_REPORT_STATE_INVALID,
        409,
    )

    settled = fixtures.read_cost_report(api, report["id"])
    assert_equals(settled, "line_count", 1)
    assert_money(
        settled["reported_cost_total"], Decimal("12500.00"), "reported_cost_total"
    )
    assert_fields(settled, {"status": "RECONCILED", "version": decided_version})


def test_the_surety_axis_refuses_every_action_it_has_no_state_for(api: ApiClient) -> None:
    """An unbonded subcontract never opens the axis, and a bonded one insists on the order.

    PRD: "Its **surety axis branches on the creation payload**: when `bond_required` is true the `bond_claim_status` is initialised to `NONE`, meaning a claim is possible but has not been filed; when `bond_required` is false it is initialised to `NOT_APPLICABLE`, a terminal dead axis on which no bond-claim action will ever be accepted."

    PRD: "A `ConstructionManager` files the claim with an `action` of `FILE` and a `claim_amount`, which must not exceed the subcontract's `bond_amount`; filing requires `bond_required` to be true — so the axis is at `NONE` rather than `NOT_APPLICABLE` — and requires the `contract_status` to be `TERMINATED_FOR_DEFAULT`."

    PRD: "It advances `NONE → FILED` and records `bond_claim_amount` from the supplied `claim_amount`."

    PRD: "`SETTLE` advances `ACKNOWLEDGED → SETTLED` and carries a `recovered_amount` that must not exceed the `bond_claim_amount`."

    PRD: "Any action attempted from a status that does not permit it, and any action at all against a `NOT_APPLICABLE` axis, is rejected with `ERR_BOND_CLAIM_STATE_INVALID` (HTTP 409)."

    PRD: "This endpoint never touches `contract_status`: a denied claim leaves the contract `TERMINATED_FOR_DEFAULT`, and a settled claim does not resurrect it."

    PRD: "If `bond_required` is true, the `bond_claim_status` stays exactly where it was at `NONE` — termination does not file a claim, and the claim must still be filed explicitly."

    Design: Corner/errors/bond_claim_actions_out_of_order_or_on_an_unbonded_subcontract_return_bond_claim_state_invalid
    """
    executed = fixtures.executed_project(api, **CLINIC_KWARGS)
    unbonded = fixtures.active_subcontract(
        api,
        executed.id,
        budget_amount=Decimal("300000.00"),
        base_bid_amount=Decimal("280000.00"),
        contract_amount=Decimal("280000.00"),
        bond_required=False,
    )
    bonded = fixtures.active_subcontract(
        api,
        executed.id,
        budget_amount=Decimal("500000.00"),
        base_bid_amount=Decimal("240000.00"),
        contract_amount=Decimal("240000.00"),
        bond_required=True,
        bond_amount=Decimal("240000.00"),
    )
    assert_fields(
        unbonded.subcontract,
        {"bond_claim_status": "NOT_APPLICABLE", "contract_status": "ACTIVE"},
    )
    assert_fields(
        bonded.subcontract, {"bond_claim_status": "NONE", "contract_status": "ACTIVE"}
    )
    unbonded_version = unbonded.subcontract["version"]

    validate_error(
        api.bond_claim(
            unbonded.id,
            factories.bond_claim_payload("FILE", claim_amount=Decimal("100000.00")),
            CM_HEADERS,
        ),
        ApiErrorId.BOND_CLAIM_STATE_INVALID,
        409,
    )
    assert_fields(
        fixtures.read_subcontract(api, unbonded.id),
        {"bond_claim_status": "NOT_APPLICABLE", "version": unbonded_version},
    )

    validate_error(
        api.bond_claim(
            bonded.id,
            factories.bond_claim_payload("SETTLE", recovered_amount=Decimal("50000.00")),
            OWNER_HEADERS,
        ),
        ApiErrorId.BOND_CLAIM_STATE_INVALID,
        409,
    )
    validate_error(
        api.bond_claim(
            bonded.id,
            factories.bond_claim_payload("FILE", claim_amount=Decimal("100000.00")),
            CM_HEADERS,
        ),
        ApiErrorId.BOND_CLAIM_STATE_INVALID,
        409,
    )
    assert_fields(
        fixtures.read_subcontract(api, bonded.id),
        {"bond_claim_status": "NONE", "contract_status": "ACTIVE"},
    )
    assert_money_fields(
        fixtures.read_project(api, executed.id),
        {
            "construction_contingency_remaining": Decimal("40000.00"),
            "contingency_drawn_to_cost_total": Decimal("0.00"),
        },
    )

    fixtures.notice_default(api, bonded.id)
    terminated = fixtures.terminate_for_default(api, bonded.id)
    assert_fields(
        terminated,
        {"contract_status": "TERMINATED_FOR_DEFAULT", "bond_claim_status": "NONE"},
    )

    filed = validate_success(
        api.bond_claim(
            bonded.id,
            factories.bond_claim_payload("FILE", claim_amount=Decimal("100000.00")),
            CM_HEADERS,
        )
    )
    assert_fields(filed, {"bond_claim_status": "FILED"})
    assert_money(filed["bond_claim_amount"], Decimal("100000.00"), "bond_claim_amount")

    validate_error(
        api.bond_claim(
            bonded.id,
            factories.bond_claim_payload("FILE", claim_amount=Decimal("120000.00")),
            CM_HEADERS,
        ),
        ApiErrorId.BOND_CLAIM_STATE_INVALID,
        409,
    )
    settled = fixtures.read_subcontract(api, bonded.id)
    assert_money(settled["bond_claim_amount"], Decimal("100000.00"), "bond_claim_amount")
    assert_fields(
        settled,
        {"bond_claim_status": "FILED", "contract_status": "TERMINATED_FOR_DEFAULT"},
    )


def _two_open_markets(api: ApiClient, project_id: str) -> Tuple[JsonObject, JsonObject, JsonObject, JsonObject]:
    """Two soliciting packages of one project, each carrying one unsealed bid."""
    finishes = fixtures.soliciting_package(
        api,
        project_id,
        budget_amount=Decimal("300000.00"),
        trade_division="09-FINISHES",
    )
    alder = fixtures.third_party_bid(
        api,
        finishes["id"],
        base_bid_amount=Decimal("280000.00"),
        bidder_name="Alder Finishes",
    )
    concrete = fixtures.soliciting_package(
        api,
        project_id,
        budget_amount=Decimal("500000.00"),
        trade_division="03-CONCRETE",
    )
    cascade = fixtures.third_party_bid(
        api,
        concrete["id"],
        base_bid_amount=Decimal("460000.00"),
        bidder_name="Cascade Concrete",
    )
    fixtures.set_clock(api, "2026-08-15T00:00:00Z")
    for bid in (alder, cascade):
        validate_success(api.open_bid(bid["id"], PO_HEADERS))
    return finishes, alder, concrete, cascade


def test_a_bid_from_the_neighbouring_package_cannot_be_laundered_into_this_one(
    api: ApiClient,
) -> None:
    """The bid exists and is even unsealed; it simply belongs to the other trade.

    PRD: "A tighter sibling rule governs bids: the bid named by a subcontract's `awarded_bid_id` must sit on the same work package as the subcontract itself, and the bid named by an award's `bid_id` must belong to the package in the path; either mismatch is rejected with `ERR_WORK_PACKAGE_PROJECT_MISMATCH` (HTTP 422)."

    PRD: "A bid that is not `OPENED` is rejected with `ERR_BID_STATE_INVALID` (HTTP 409), a bid belonging to a different package with `ERR_WORK_PACKAGE_PROJECT_MISMATCH` (HTTP 422), and a package in the wrong `procurement_status` with `ERR_PACKAGE_STATE_INVALID` (HTTP 409); the project must also be `EXECUTED`, failing which the award is rejected with `ERR_GMP_NOT_EXECUTED` (HTTP 409)."

    PRD: "The award advances the package `SOLICITING → AWARDED`, writes `awarded_bid_id` from the supplied `bid_id` and `awarded_amount` from that bid's `base_bid_amount`, advances the winning bid `OPENED → AWARDED`, and moves **every other** bid on that package that is currently `OPENED` to `NOT_AWARDED`."

    PRD: "11. Referential-integrity rules — `ERR_CROSS_PROJECT_REFERENCE`, then `ERR_WORK_PACKAGE_PROJECT_MISMATCH`, then `ERR_MILESTONE_RANK_REGRESSION`."

    Design: Corner/errors/awarding_a_bid_that_belongs_to_another_package_returns_work_package_project_mismatch
    """
    executed = fixtures.executed_project(api, **CLINIC_KWARGS)
    finishes, alder, concrete, cascade = _two_open_markets(api, executed.id)
    soliciting_version = fixtures.read_work_package(api, finishes["id"])["version"]

    validate_error(
        api.award_work_package(
            finishes["id"], factories.award_payload(cascade["id"]), PO_HEADERS
        ),
        ApiErrorId.WORK_PACKAGE_PROJECT_MISMATCH,
        422,
    )
    refused = fixtures.read_work_package(api, finishes["id"])
    assert_fields(
        refused,
        {"procurement_status": "SOLICITING", "version": soliciting_version},
    )
    assert_null(refused, "awarded_bid_id")
    assert_fields(fixtures.read_bid(api, cascade["id"]), {"status": "OPENED"})

    awarded = validate_success(
        api.award_work_package(
            finishes["id"], factories.award_payload(alder["id"]), PO_HEADERS
        )
    )
    assert_fields(awarded, {"awarded_bid_id": alder["id"]})
    assert_money(awarded["awarded_amount"], Decimal("280000.00"), "awarded_amount")

    # Carry the neighbouring bid all the way to AWARDED on its own package, so the
    # subcontract refusal below can only be about which package the bid sits on.
    # Per PRD 2.11 the per-entity bid status gate (level 8) precedes the
    # referential-integrity rules (level 11), so an OPENED bid would be turned away
    # by ERR_BID_STATE_INVALID before the sibling rule was ever reached.
    validate_success(
        api.award_work_package(
            concrete["id"], factories.award_payload(cascade["id"]), PO_HEADERS
        )
    )
    assert_fields(fixtures.read_bid(api, cascade["id"]), {"status": "AWARDED"})

    validate_error(
        api.create_subcontract(
            factories.subcontract_payload(
                finishes["id"],
                cascade["id"],
                fixtures.work_package_version(api, finishes["id"]),
                contract_amount=Decimal("460000.00"),
                subcontractor_name="Cascade Concrete",
                bond_required=False,
            ),
            CM_HEADERS,
        ),
        ApiErrorId.WORK_PACKAGE_PROJECT_MISMATCH,
        422,
    )
    _, meta = validate_paginated(
        api.list_subcontracts(CM_HEADERS, {"work_package_id": finishes["id"]})
    )
    assert meta["total_count"] == 0, (
        f"the refused subcontract must not exist, got {meta['total_count']}"
    )


def test_the_operator_who_sealed_the_bid_may_not_be_the_one_who_unseals_it(
    api: ApiClient,
) -> None:
    """Same role, different identifier — and the refusal is about the identifier.

    PRD: "The operator who opens a sealed bid must not be the operator who prepared it. The comparison is between the acting `X-User-ID` and the bid's recorded `prepared_by_user_id`."

    PRD: "Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    PRD: "A bid is minted at `SEALED` with `prepared_by_user_id` taken from the submitting operator's `X-User-ID`, `opened_by_user_id` null and `opened_at` null; the parent package's `bid_count` increases by 1 and its `version` increments."

    PRD: "A successful open advances the bid `SEALED → OPENED`, records `opened_by_user_id` from the acting `X-User-ID` and `opened_at` from the logical clock, and increments the bid's `version`."

    PRD: "A bid whose `bidder_type` is `CM_SELF_PERFORM` may only be opened once the package's `transparency_status` has reached `DISCLOSED` or `AUDITED`, and opening one while the package is still `SEALED` is rejected with `ERR_OPEN_BOOK_DISCLOSURE_REQUIRED` (HTTP 422); third-party bids are exempt, because the gate exists specifically for the case where the construction manager is bidding against the trades it also administers."

    PRD: "A `ProcurementOfficer` publishes the cost breakdowns to the owner by naming `target_status` `DISCLOSED`, advancing the package `SEALED → DISCLOSED`; this requires the package to have attracted at least one bid, that is `bid_count` of 1 or more."

    Design: Corner/errors/the_operator_that_prepared_a_bid_cannot_be_the_operator_that_opens_it
    """
    executed = fixtures.executed_project(api, **CLINIC_KWARGS)
    package = fixtures.soliciting_package(
        api,
        executed.id,
        budget_amount=Decimal("500000.00"),
        trade_division="03-CONCRETE",
        self_perform_intent=True,
    )
    bid = fixtures.self_perform_bid(
        api,
        package["id"],
        base_bid_amount=Decimal("455000.00"),
        headers=headers_for(ROLE_CONSTRUCTION_MANAGER, DUAL_HAT_OPERATOR),
        bidder_name="Harborview CM Concrete Division",
    )
    assert_fields(
        bid, {"status": "SEALED", "prepared_by_user_id": DUAL_HAT_OPERATOR}
    )
    sealed_version = bid["version"]
    validate_success(
        api.set_transparency(
            package["id"],
            factories.transparency_payload(
                "DISCLOSED", "self-perform crew rates and burdens disclosed"
            ),
            PO_HEADERS,
        )
    )
    fixtures.set_clock(api, "2026-08-15T00:00:00Z")

    validate_error(
        api.open_bid(bid["id"], headers_for(ROLE_PROCUREMENT_OFFICER, DUAL_HAT_OPERATOR)),
        ApiErrorId.SEGREGATION_OF_DUTIES,
        403,
    )
    still_sealed = fixtures.read_bid(api, bid["id"])
    assert_fields(still_sealed, {"status": "SEALED", "version": sealed_version})
    assert_null(still_sealed, "opened_by_user_id", "opened_at")

    opened = validate_success(api.open_bid(bid["id"], PO_INDEPENDENT_HEADERS))
    assert_fields(
        opened,
        {
            "status": "OPENED",
            "opened_by_user_id": user_id_of("procurement_officer_independent"),
            "prepared_by_user_id": DUAL_HAT_OPERATOR,
        },
    )


def test_a_held_report_stays_held_until_the_surety_money_refills_the_pot(
    api: ApiClient,
) -> None:
    """The ledger releases the hold, not the owner's wish — and the envelope never moves.

    PRD: "On the subcontract itself, `unpaid_committed_amount` is frozen at `contract_amount` less `paid_to_date`, and `replacement_cost_amount` is written as that frozen unpaid amount multiplied by 1.15 — a fifteen-percent replacement premium — rounded half-up to 2 decimal places."

    PRD: "Otherwise, if the remaining percentage is less than or equal to ten percent — that is, at most 0.1000 after the 4-decimal rounding — the posture is `CONSTRAINED`."

    PRD: "When the posture moves from `OPEN` to `CONSTRAINED`, every cost report of that project whose status is `OPEN` is immediately moved to `RECONCILIATION_HELD` with its `held_reason` set to the string `CONSTRUCTION_CONTINGENCY_CONSTRAINED`, and each such report's own `version` increments."

    PRD: "Each one requires an explicit release by an `OwnerRepresentative`, and that release is itself refused with `ERR_POSTURE_NOT_RECOVERED` (HTTP 409) while the posture is still `CONSTRAINED` or `FROZEN`."

    PRD: "The subcontract's `bond_recovered_amount` is written as the lesser of the supplied `recovered_amount` and the `bond_claim_amount`."

    PRD: "The credit is added to the project's `construction_contingency_remaining` and subtracted from its `contingency_drawn_to_cost_total`, so the envelope identity of §2.6 is preserved exactly — the surety's money refills the construction manager's contingency rather than reducing the guaranteed maximum price."

    PRD: "The release returns the report to `OPEN`, clears `held_reason` to null, and increments the report's `version` by 1."

    PRD: "`gmp_amount` equals the sum of `cost_of_work_budget_total`, `general_conditions_total`, `insurance_amount`, `cm_fee_amount`, `owner_contingency_remaining`, `construction_contingency_remaining`, and `contingency_drawn_to_cost_total`."

    Design: Corner/errors/releasing_a_held_report_before_the_posture_recovers_returns_posture_not_recovered
    """
    executed = fixtures.executed_project(api, **CLINIC_KWARGS)
    report = fixtures.cost_report(
        api, executed.id, period_start=AUGUST[0], period_end=AUGUST[1]
    )
    bonded = fixtures.active_subcontract(
        api,
        executed.id,
        budget_amount=Decimal("500000.00"),
        base_bid_amount=Decimal("240000.00"),
        contract_amount=Decimal("240000.00"),
        bond_required=True,
        bond_amount=Decimal("240000.00"),
    )
    fixtures.notice_default(api, bonded.id)
    terminated = fixtures.terminate_for_default(api, bonded.id)
    assert_money_fields(
        terminated,
        {
            "unpaid_committed_amount": Decimal("240000.00"),
            "replacement_cost_amount": Decimal("276000.00"),
        },
    )

    constrained = fixtures.read_project(api, executed.id)
    assert_money_fields(
        constrained,
        {
            "construction_contingency_remaining": Decimal("4000.00"),
            "contingency_drawn_to_cost_total": Decimal("36000.00"),
            "gmp_amount": Decimal("1245897.60"),
        },
    )
    assert_project_axes(constrained, contingency_posture="CONSTRAINED")
    assert_gmp_identity(constrained)

    held = fixtures.read_cost_report(api, report["id"])
    assert_fields(
        held,
        {
            "status": "RECONCILIATION_HELD",
            "held_reason": "CONSTRUCTION_CONTINGENCY_CONSTRAINED",
        },
    )
    held_version = held["version"]

    validate_error(
        api.release_hold(
            report["id"], OWNER_HEADERS, factories.release_hold_payload("premature")
        ),
        ApiErrorId.POSTURE_NOT_RECOVERED,
        409,
    )
    assert_fields(
        fixtures.read_cost_report(api, report["id"]),
        {"status": "RECONCILIATION_HELD", "version": held_version},
    )

    validate_success(
        api.bond_claim(
            bonded.id,
            factories.bond_claim_payload("FILE", claim_amount=Decimal("240000.00")),
            CM_HEADERS,
        )
    )
    validate_success(
        api.bond_claim(bonded.id, factories.bond_claim_payload("ACKNOWLEDGE"), OWNER_HEADERS)
    )
    settled_claim = validate_success(
        api.bond_claim(
            bonded.id,
            factories.bond_claim_payload("SETTLE", recovered_amount=Decimal("36000.00")),
            OWNER_HEADERS,
        )
    )
    assert_fields(settled_claim, {"bond_claim_status": "SETTLED"})
    assert_money(
        settled_claim["bond_recovered_amount"],
        Decimal("36000.00"),
        "bond_recovered_amount",
    )

    recovered = fixtures.read_project(api, executed.id)
    assert_money_fields(
        recovered,
        {
            "construction_contingency_remaining": Decimal("40000.00"),
            "contingency_drawn_to_cost_total": Decimal("0.00"),
            "gmp_amount": Decimal("1245897.60"),
        },
    )
    assert_project_axes(recovered, contingency_posture="OPEN")
    assert_gmp_identity(recovered)

    released = validate_success(
        api.release_hold(
            report["id"],
            OWNER_HEADERS,
            factories.release_hold_payload(
                "surety settlement restored the construction pot"
            ),
        )
    )
    assert_fields(released, {"status": "OPEN", "version": held_version + 1})
    assert_null(released, "held_reason")
