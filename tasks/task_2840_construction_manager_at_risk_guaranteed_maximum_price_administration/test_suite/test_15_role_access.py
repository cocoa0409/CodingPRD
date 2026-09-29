"""Who may do what, and which gate answers when two of them would both refuse.

Five roles are load-bearing here: no single actor can drive a project from
registration through buyout to audit. The positive half of the matrix walks one
exclusive operation per role in the order the workflow demands them; the negative
half proves each denial is a refusal of authority rather than a refusal of state,
by aiming every forbidden call at a row that a later gate would also have turned
away. Two endpoints are shared at the endpoint level and partitioned by action
underneath, and one determination is separated at the level of the individual
operator rather than the role.
"""

from decimal import Decimal
from typing import Tuple

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    CM_HEADERS,
    CM_PM_2_HEADERS,
    CM_PM_HEADERS,
    OWNER_HEADERS,
    PO_HEADERS,
    ApiClient,
    ApiErrorId,
    assert_equals,
    assert_fields,
    assert_money,
    assert_null,
    assert_page_meta,
    assert_project_axes,
    factories,
    fixtures,
    user_id_of,
)
from test_helpers.types import JsonObject

CLINIC_KWARGS = {
    "project_kwargs": {"name": "Harborview Clinic", "owner_org": "Harborview Health"}
}
SOLICITATION_OPENS = "2026-08-01T00:00:00Z"
SOLICITATION_CLOSES = "2026-08-15T00:00:00Z"
AUGUST = ("2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z")


def _clinic_with_a_sealed_concrete_bid(
    api: ApiClient,
) -> Tuple[fixtures.PricedProject, JsonObject, JsonObject]:
    """An executed clinic whose concrete market is open with one sealed bid in it."""
    executed = fixtures.executed_project(api, **CLINIC_KWARGS)
    package = fixtures.soliciting_package(
        api,
        executed.id,
        budget_amount=Decimal("500000.00"),
        trade_division="03-CONCRETE",
        self_perform_intent=False,
        solicitation_opens_at=SOLICITATION_OPENS,
        solicitation_closes_at=SOLICITATION_CLOSES,
    )
    bid = fixtures.third_party_bid(
        api,
        package["id"],
        base_bid_amount=Decimal("460000.00"),
        bidder_name="Cascade Concrete",
    )
    return executed, package, bid


def test_each_of_the_five_roles_drives_the_step_that_only_it_may_drive(
    api: ApiClient,
) -> None:
    """The positive half of the matrix: one exclusive operation per role, in workflow order.

    PRD: "A `ProgramAdmin` is the owner-side program administrator. It registers CMAR projects and controls the logical clock, and holds no authority over pricing, procurement or the contingency ledger."

    PRD: "A `ProcurementOfficer` is an independent procurement officer holding the sealed-bid opening and award authority, and publishing open-book breakdowns to the owner."

    PRD: "Cost lines are appended one at a time by the `ConstructionManager`, each carrying a `cost_code` identifying the cost classification, a `quantity`, a `unit_rate`, a `markup_pct`, and optionally a `work_package_id` tying the line to a bought-out trade package, a `qualification_item_id` tying it to an allowance or assumption, and a `disputed` flag."

    PRD: "The report's `reported_cost_total` is then the sum of `line_amount` over every line, `undisputed_cost_total` is the sum of `line_amount` over lines whose `disputed` is false, `disputed_cost_total` is the sum over lines whose `disputed` is true, and `line_count` is the number of entries in `lines`."

    PRD: "A `RECONCILE` decision is permitted from `OPEN` or from `DISPUTED` — the latter being how a dispute is resolved after the parties settle it — and requires the report's `line_count` to be at least 1; it advances the report to `RECONCILED` and stamps `reconciled_at` from the logical clock."

    PRD: "An `OwnerRepresentative` exercises those rights with an optional `audit_scope_note`, moving `audit_status` `NOT_REQUESTED → IN_PROGRESS`."

    PRD: "A `POST_ADJUSTMENT`, permitted only while `audit_status` is `IN_PROGRESS`, carries an `adjustment_amount` and an optional `adjustment_note`, and adds the amount **signed** to the project's `audit_adjustment_total`."

    PRD: "| GET | `/cost-reports/{id}` | Reads one monthly cost report including its embedded `lines` array and all three rounded subtotals. | ConstructionManager, OwnerRepresentative, IndependentAuditor, ProgramAdmin |"

    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_operations
    """
    executed, package, bid = _clinic_with_a_sealed_concrete_bid(api)

    validate_success(api.set_clock(SOLICITATION_CLOSES, ADMIN_HEADERS))

    opened = validate_success(api.open_bid(bid["id"], PO_HEADERS))
    assert_fields(opened, {"status": "OPENED"})
    awarded = validate_success(
        api.award_work_package(
            package["id"],
            factories.award_payload(bid["id"], award_note="lowest responsive bid"),
            PO_HEADERS,
        )
    )
    assert_fields(awarded, {"procurement_status": "AWARDED"})
    assert_fields(fixtures.read_bid(api, bid["id"]), {"status": "AWARDED"})

    report = validate_success(
        api.create_cost_report(
            factories.cost_report_payload(
                executed.id, period_start=AUGUST[0], period_end=AUGUST[1]
            ),
            CM_HEADERS,
        ),
        201,
    )
    lined = validate_success(
        api.append_cost_line(
            report["id"],
            factories.cost_line_payload(
                quantity=Decimal("100.0000"),
                unit_rate=Decimal("200.0000"),
                markup_pct=Decimal("0.0000"),
                cost_code="03-100",
                disputed=False,
            ),
            CM_HEADERS,
        ),
        201,
    )
    assert_equals(lined, "line_count", 1)
    assert_money(lined["reported_cost_total"], Decimal("20000.00"), "reported_cost_total")

    reconciled = validate_success(
        api.reconcile_cost_report(
            report["id"],
            factories.cost_report_reconcile_payload("RECONCILE"),
            OWNER_HEADERS,
        )
    )
    assert_fields(reconciled, {"status": "RECONCILED"})

    audited = validate_success(api.request_audit(executed.id, OWNER_HEADERS))
    assert_project_axes(audited, audit_status="IN_PROGRESS")

    adjusted = validate_success(
        api.audit_action(
            executed.id,
            factories.audit_action_payload(
                "POST_ADJUSTMENT",
                adjustment_amount=Decimal("-2500.00"),
                adjustment_note="unsupported equipment rental",
            ),
            AUDITOR_HEADERS,
        )
    )
    assert_money(
        adjusted["audit_adjustment_total"],
        Decimal("-2500.00"),
        "audit_adjustment_total",
    )

    admin_read = validate_success(api.get_cost_report(report["id"], ADMIN_HEADERS))
    assert_fields(admin_read, {"id": report["id"], "status": "RECONCILED"})


def test_the_role_gate_answers_before_every_state_and_identity_gate_beneath_it(
    api: ApiClient,
) -> None:
    """Eight forbidden calls, every one aimed at a row a later gate would also have refused.

    PRD: "If the headers are well-formed but the named role is not authorized for the endpoint being invoked, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    PRD: "When a single request could fail several ways, the system reports the failure that comes first in the following order, and stops."

    PRD: "2. Endpoint-level role authority — `ERR_UNAUTHORIZED`."

    PRD: "8. State preconditions — the family of `409 Conflict` conditions detailed in §3, in this internal order: the project's `gmp_status` gates, then the per-entity status gates for estimates, proposals, work packages, bids, subcontracts, bond claims, change events, contingency draws, cost reports and the audit engagement, then `ERR_CLOSEOUT_ALREADY_SETTLED`, then `ERR_CONTINGENCY_FROZEN`, then `ERR_POSTURE_NOT_RECOVERED`."

    PRD: "9. Segregation-of-duties checks on the operator identifier — `ERR_SEGREGATION_OF_DUTIES`."

    PRD: "| POST | `/projects` | Registers a CMAR project with its fee and insurance rates, at `gmp_status` PRECONSTRUCTION, `contingency_posture` OPEN, `audit_status` NOT_REQUESTED, `closeout_status` NOT_STARTED and every money field 0.00. | ProgramAdmin |"

    PRD: "| POST | `/estimates` | Creates a progressive estimate at a design milestone against a project, under optimistic concurrency on the project's `version`. | ConstructionManager |"

    PRD: "| POST | `/gmp-proposals/{id}/decide` | The owner executes, returns for revision or rejects a proposal under review. | OwnerRepresentative |"

    PRD: "The role is deliberately separated from `ConstructionManager` so that the construction manager cannot open the bids it competes against, and from `OwnerRepresentative` so that the hand which buys out the trades is not the hand which approves contingency."

    PRD: "| POST | `/projects/{id}/audit-actions` | The independent auditor posts a signed cost adjustment or closes the audit engagement. | IndependentAuditor |"

    PRD: "It cannot itself settle the shared savings it audits."

    PRD: "| GET | `/estimates` | Lists progressive estimates, filterable by project, `milestone` and `status`. | ConstructionManager, OwnerRepresentative, IndependentAuditor, ProgramAdmin |"

    Design: Corner/rbac/roles_cannot_perform_another_roles_exclusive_operations
    """
    executed, package, bid = _clinic_with_a_sealed_concrete_bid(api)
    fixtures.set_clock(api, SOLICITATION_CLOSES)
    pinned_version = fixtures.project_version(api, executed.id)

    refusal = validate_error(
        api.create_project(
            factories.project_payload(
                name="Rogue Project", owner_org="Harborview Health"
            ),
            CM_HEADERS,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    assert refusal["message"], "an ERR_UNAUTHORIZED refusal must explain itself"

    validate_error(
        api.create_estimate(
            factories.estimate_payload(
                executed.id,
                pinned_version,
                milestone_code="DD",
                submitted_cost_of_work=Decimal("1040000.00"),
            ),
            OWNER_HEADERS,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )

    validate_error(
        api.decide_gmp_proposal(
            executed.proposal["id"],
            factories.proposal_decision_payload("REJECT"),
            CM_HEADERS,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )

    validate_error(
        api.open_bid(bid["id"], CM_HEADERS),
        ApiErrorId.UNAUTHORIZED,
        403,
    )

    validate_error(
        api.award_work_package(
            package["id"], factories.award_payload(bid["id"]), CM_HEADERS
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )

    validate_error(
        api.audit_action(executed.id, factories.audit_action_payload("CLOSE"), OWNER_HEADERS),
        ApiErrorId.UNAUTHORIZED,
        403,
    )

    validate_error(
        api.shared_savings(
            executed.id,
            factories.shared_savings_payload("PRE_AUDIT_PROVISIONAL", execute=False),
            AUDITOR_HEADERS,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )

    validate_error(
        api.list_estimates(PO_HEADERS, {"project_id": executed.id}),
        ApiErrorId.UNAUTHORIZED,
        403,
    )

    projects, meta = validate_paginated(api.list_projects(ADMIN_HEADERS))
    assert_page_meta(meta, total_count=1)
    assert len(projects) == 1, "no rogue project was registered"

    unmoved = fixtures.read_project(api, executed.id)
    assert_fields(unmoved, {"version": pinned_version})
    assert_project_axes(unmoved, gmp_status="EXECUTED", audit_status="NOT_REQUESTED")
    assert_fields(
        fixtures.read_proposal(api, executed.proposal["id"]), {"status": "EXECUTED"}
    )
    sealed = fixtures.read_bid(api, bid["id"])
    assert_fields(sealed, {"status": "SEALED", "version": bid["version"]})
    assert_null(sealed, "opened_by_user_id", "opened_at")


def test_the_transparency_endpoint_partitions_its_two_actions_between_its_two_holders(
    api: ApiClient,
) -> None:
    """Both roles hold the endpoint; neither holds the other's step on it.

    PRD: "Two endpoints are shared between roles at the endpoint level but partitioned by action underneath, and the same `ERR_UNAUTHORIZED` (HTTP 403) is returned when an authorized role requests an action it does not own:"

    PRD: "On the work-package transparency endpoint, advancing the disclosure axis to `DISCLOSED` is `ProcurementOfficer`-only, and certifying it to `AUDITED` is `IndependentAuditor`-only."

    PRD: "3. Action-level authority on the two role-partitioned shared endpoints described in §2.1 — also `ERR_UNAUTHORIZED`."

    PRD: "A `ProcurementOfficer` publishes the cost breakdowns to the owner by naming `target_status` `DISCLOSED`, advancing the package `SEALED → DISCLOSED`; this requires the package to have attracted at least one bid, that is `bid_count` of 1 or more."

    PRD: "An `IndependentAuditor` then certifies them by naming `target_status` `AUDITED`, advancing `DISCLOSED → AUDITED`."

    PRD: "Neither step may be skipped and neither may be regressed — a request to reach `AUDITED` from `SEALED`, or to return to `SEALED` from anywhere, is rejected with `ERR_PACKAGE_STATE_INVALID` (HTTP 409) — and the package's `procurement_status` is never touched by either step."

    PRD: "Each step increments the package's `version`."

    PRD: "Neither axis constrains the other's position: a package may be `DISCLOSED` while still `BUDGETED`, or while already `CLOSED`."

    Design: Corner/rbac/shared_endpoints_partition_their_actions_between_the_two_holder_roles
    """
    executed = fixtures.executed_project(api, **CLINIC_KWARGS)
    package = fixtures.soliciting_package(
        api,
        executed.id,
        budget_amount=Decimal("500000.00"),
        trade_division="03-CONCRETE",
        self_perform_intent=True,
        solicitation_opens_at=SOLICITATION_OPENS,
        solicitation_closes_at=SOLICITATION_CLOSES,
    )
    fixtures.self_perform_bid(
        api,
        package["id"],
        base_bid_amount=Decimal("455000.00"),
        bidder_name="Harborview CM Concrete Division",
    )
    sealed_version = fixtures.work_package_version(api, package["id"])

    validate_error(
        api.set_transparency(
            package["id"],
            factories.transparency_payload(
                "DISCLOSED",
                disclosure_note="auditor cannot publish what it must certify",
            ),
            AUDITOR_HEADERS,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    still_sealed = fixtures.read_work_package(api, package["id"])
    assert_fields(
        still_sealed, {"transparency_status": "SEALED", "version": sealed_version}
    )

    disclosed = validate_success(
        api.set_transparency(
            package["id"],
            factories.transparency_payload(
                "DISCLOSED",
                disclosure_note="crew rates, burdens and equipment rates published to the owner",
            ),
            PO_HEADERS,
        )
    )
    assert_fields(
        disclosed,
        {
            "transparency_status": "DISCLOSED",
            "procurement_status": "SOLICITING",
            "version": sealed_version + 1,
        },
    )

    validate_error(
        api.set_transparency(
            package["id"], factories.transparency_payload("AUDITED"), PO_HEADERS
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    assert_fields(
        fixtures.read_work_package(api, package["id"]),
        {"transparency_status": "DISCLOSED", "version": sealed_version + 1},
    )

    certified = validate_success(
        api.set_transparency(
            package["id"], factories.transparency_payload("AUDITED"), AUDITOR_HEADERS
        )
    )
    assert_fields(
        certified,
        {
            "transparency_status": "AUDITED",
            "procurement_status": "SOLICITING",
            "version": sealed_version + 2,
        },
    )


def test_the_forbidden_classifier_is_whoever_submitted_last_not_a_fixed_operator(
    api: ApiClient,
) -> None:
    """The identity the rule compares against moves with every resubmission.

    PRD: "The operator who classifies a change event must not be the operator who most recently submitted it. The comparison is between the acting `X-User-ID` and the event's recorded `submitted_by_user_id`."

    PRD: "Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    PRD: "Note that classification is deliberately shared between `ConstructionManager` and `OwnerRepresentative` precisely so that either side of the contract may make the cost-responsibility determination — but never the operator who asked for it."

    PRD: "Every submission overwrites `submitted_by_user_id` with the acting `X-User-ID`, which is the anchor of the segregation-of-duties rule at classification time; a resubmission by a different operator therefore moves the anchor."

    PRD: "Requesting a revision advances `UNDER_REVIEW → REVISION_REQUESTED` and increments `revision_count` by 1; the loop from submission through review to revision request and back to submission may repeat without bound."

    PRD: "Whichever branch is taken, the event advances `UNDER_REVIEW → CLASSIFIED`, its `classification` is written from the payload, `classified_by_user_id` is recorded from the acting `X-User-ID`, `classified_at` is stamped from the logical clock, and both the event's `version` and the project's `version` increment by 1."

    PRD: "A contingency draw is minted with `contingency_type` `OWNER`, `origin` `CHANGE_EVENT_CLASSIFICATION`, `status` `REQUESTED`, `amount` equal to the event's `estimated_amount`, `change_event_id` naming this event, `source_subcontract_id` null, and `requires_owner_approval` set to true unconditionally — it is the owner's money, so the owner always signs for it."

    PRD: "The threshold comparison is strict, on 2-decimal money: a construction draw of exactly 50,000.00 on an `OPEN`-posture project arising from a change-event classification does not require approval, while a draw of 50,000.01 does."

    PRD: "A successful post advances the draw `REQUESTED → POSTED` or `OWNER_APPROVED → POSTED` with identical ledger effects in both cases: `posted_at` is stamped from the logical clock, the drawn pot's remaining balance decreases by the draw's `amount`, and the project's `contingency_drawn_to_cost_total` increases by the same `amount`, leaving `gmp_amount` unmoved."

    Design: Corner/rbac/the_operator_that_submitted_a_change_event_cannot_be_the_operator_that_classifies_it
    """
    executed = fixtures.executed_project(api, **CLINIC_KWARGS)
    event = fixtures.event_under_review(
        api,
        executed.id,
        estimated_amount=Decimal("18000.00"),
        origin="FIELD_CONDITION",
        description="differing site condition at the west footings",
        submitter_headers=CM_PM_HEADERS,
    )
    assert_fields(event, {"submitted_by_user_id": user_id_of("cm_pm")})

    validate_error(
        api.classify_change_event(
            event["id"],
            factories.classify_payload("CONTINGENCY_USE_OWNER"),
            CM_PM_HEADERS,
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES,
        403,
    )
    unmoved = fixtures.read_change_event(api, event["id"])
    assert_fields(unmoved, {"status": "UNDER_REVIEW", "revision_count": 0})
    assert_null(unmoved, "classification", "classified_by_user_id", "classified_at")
    assert not fixtures.list_draws(api, project_id=executed.id), (
        "a refused classification mints no contingency draw"
    )

    returned = validate_success(
        api.review_change_event(
            event["id"],
            factories.change_event_review_payload(
                "REQUEST_REVISION",
                review_note="resubmit with the geotech backup attached",
            ),
            OWNER_HEADERS,
        )
    )
    assert_fields(returned, {"status": "REVISION_REQUESTED", "revision_count": 1})

    resubmitted = validate_success(
        api.submit_change_event(
            event["id"],
            CM_PM_2_HEADERS,
            factories.change_event_submit_payload("geotech backup attached"),
        )
    )
    assert_fields(
        resubmitted,
        {
            "status": "SUBMITTED",
            "submitted_by_user_id": user_id_of("cm_pm_2"),
            "revision_count": 1,
        },
    )
    validate_success(
        api.review_change_event(
            event["id"],
            factories.change_event_review_payload("BEGIN_REVIEW"),
            OWNER_HEADERS,
        )
    )

    classified = validate_success(
        api.classify_change_event(
            event["id"],
            factories.classify_payload(
                "CONTINGENCY_USE_OWNER",
                classification_note="the owner elects to absorb the differing site condition",
            ),
            CM_PM_HEADERS,
        )
    )
    assert_fields(
        classified,
        {
            "status": "CLASSIFIED",
            "classification": "CONTINGENCY_USE_OWNER",
            "classified_by_user_id": user_id_of("cm_pm"),
        },
    )

    draws = fixtures.list_draws(api, project_id=executed.id)
    assert len(draws) == 1, "the owner branch mints exactly one draw"
    assert_fields(
        draws[0],
        {
            "contingency_type": "OWNER",
            "origin": "CHANGE_EVENT_CLASSIFICATION",
            "status": "REQUESTED",
            "requires_owner_approval": True,
            "change_event_id": event["id"],
        },
    )
    assert_money(draws[0]["amount"], Decimal("18000.00"), "amount")
    assert_null(draws[0], "source_subcontract_id")
    assert_money(
        fixtures.read_project(api, executed.id)["owner_contingency_remaining"],
        Decimal("50000.00"),
        "owner_contingency_remaining",
    )
