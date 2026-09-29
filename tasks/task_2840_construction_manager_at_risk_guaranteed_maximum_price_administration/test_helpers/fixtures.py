"""Composite setup builders.

The rules under test almost always need a project that has already walked some
distance down the preconstruction and buyout path. These builders drive that walk
through the public endpoints only — there is no back door into the store — and
return the freshly read representations so a test can start from known figures.

Every builder uses the lenient success reader, because a setup step that fails is
a setup error rather than the assertion the test is making.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import (
    CLOCK_START,
    SOLICITATION_CLOSE,
    STD_CONSTRUCTION_CONTINGENCY,
    STD_COST_OF_WORK,
    STD_GENERAL_CONDITIONS,
    STD_OWNER_CONTINGENCY,
)
from .test_users import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    CM_HEADERS,
    CM_PM_HEADERS,
    OWNER_HEADERS,
    PO_HEADERS,
    PO_INDEPENDENT_HEADERS,
)
from .types import JsonObject, Numeric


# --- primitives ------------------------------------------------------------


def set_clock(client: ApiClient, current_utc: str) -> JsonObject:
    """Move the logical clock every subsequent timestamp is stamped from."""
    return get_success_data(client.set_clock(current_utc, ADMIN_HEADERS))


def create_project(client: ApiClient, **kwargs: Any) -> JsonObject:
    """Register a CMAR project at PRECONSTRUCTION with every money field 0.00."""
    return get_success_data(
        client.create_project(f.project_payload(**kwargs), ADMIN_HEADERS)
    )


def read_project(client: ApiClient, project_id: str, headers: Any = ADMIN_HEADERS) -> JsonObject:
    """Read one project including every derived contingency and savings figure."""
    return get_success_data(client.get_project(project_id, headers))


def project_version(client: ApiClient, project_id: str) -> int:
    """The project's current optimistic-concurrency counter."""
    return read_project(client, project_id)["version"]


def read_work_package(client: ApiClient, package_id: str) -> JsonObject:
    return get_success_data(client.get_work_package(package_id, CM_HEADERS))


def work_package_version(client: ApiClient, package_id: str) -> int:
    return read_work_package(client, package_id)["version"]


def read_bid(client: ApiClient, bid_id: str) -> JsonObject:
    return get_success_data(client.get_bid(bid_id, PO_HEADERS))


def read_subcontract(client: ApiClient, subcontract_id: str) -> JsonObject:
    return get_success_data(client.get_subcontract(subcontract_id, CM_HEADERS))


def read_estimate(client: ApiClient, estimate_id: str) -> JsonObject:
    return get_success_data(client.get_estimate(estimate_id, CM_HEADERS))


def read_proposal(client: ApiClient, proposal_id: str) -> JsonObject:
    return get_success_data(client.get_gmp_proposal(proposal_id, CM_HEADERS))


def read_qualification_item(client: ApiClient, item_id: str) -> JsonObject:
    return get_success_data(client.get_qualification_item(item_id, CM_HEADERS))


def read_cost_report(client: ApiClient, report_id: str) -> JsonObject:
    return get_success_data(client.get_cost_report(report_id, CM_HEADERS))


def read_change_event(client: ApiClient, event_id: str) -> JsonObject:
    return get_success_data(client.get_change_event(event_id, CM_HEADERS))


def read_draw(client: ApiClient, draw_id: str) -> JsonObject:
    return get_success_data(client.get_draw(draw_id, CM_HEADERS))


def list_draws(client: ApiClient, **params: Any) -> List[JsonObject]:
    """Listing is the only channel through which a cascade-minted draw is found."""
    return get_success_data(client.list_draws(CM_HEADERS, params))


def list_proposals(client: ApiClient, **params: Any) -> List[JsonObject]:
    return get_success_data(client.list_gmp_proposals(CM_HEADERS, params))


# --- preconstruction -------------------------------------------------------


def create_estimate(
    client: ApiClient,
    project_id: str,
    milestone_code: str = "SD",
    submitted_cost_of_work: Numeric = STD_COST_OF_WORK,
    expected_project_version: Optional[int] = None,
    **kwargs: Any,
) -> JsonObject:
    """File a progressive estimate under optimistic concurrency on the project."""
    version = (
        expected_project_version
        if expected_project_version is not None
        else project_version(client, project_id)
    )
    return get_success_data(
        client.create_estimate(
            f.estimate_payload(
                project_id,
                version,
                milestone_code=milestone_code,
                submitted_cost_of_work=submitted_cost_of_work,
                **kwargs,
            ),
            CM_HEADERS,
        )
    )


def reconciled_estimate(
    client: ApiClient,
    project_id: str,
    milestone_code: str = "SD",
    submitted_cost_of_work: Numeric = STD_COST_OF_WORK,
    justification_note: Optional[str] = None,
    **kwargs: Any,
) -> JsonObject:
    """Walk an estimate DRAFT -> SUBMITTED -> RECONCILED."""
    estimate = create_estimate(
        client,
        project_id,
        milestone_code=milestone_code,
        submitted_cost_of_work=submitted_cost_of_work,
        **kwargs,
    )
    get_success_data(
        client.submit_estimate(
            estimate["id"],
            f.estimate_submit_payload(justification_note=justification_note),
            CM_HEADERS,
        )
    )
    return get_success_data(
        client.reconcile_estimate(
            estimate["id"], f.estimate_reconcile_payload("ACCEPT"), OWNER_HEADERS
        )
    )


@dataclass
class PricedProject:
    """A project priced through the four-step build-up, with its paper trail."""

    project: JsonObject
    estimate: JsonObject
    proposal: JsonObject

    @property
    def id(self) -> str:
        return self.project["id"]

    @property
    def version(self) -> int:
        return self.project["version"]


def draft_priced_project(
    client: ApiClient,
    cm_fee_pct: Numeric = Decimal("0.04"),
    insurance_rate: Numeric = Decimal("0.01"),
    cost_of_work_total: Numeric = STD_COST_OF_WORK,
    general_conditions_total: Numeric = STD_GENERAL_CONDITIONS,
    owner_contingency_amount: Numeric = STD_OWNER_CONTINGENCY,
    construction_contingency_amount: Numeric = STD_CONSTRUCTION_CONTINGENCY,
    project_kwargs: Optional[Dict[str, Any]] = None,
) -> PricedProject:
    """A project with a reconciled estimate and a base proposal still at DRAFT."""
    project = create_project(
        client,
        cm_fee_pct=cm_fee_pct,
        insurance_rate=insurance_rate,
        **(project_kwargs or {}),
    )
    estimate = reconciled_estimate(
        client, project["id"], submitted_cost_of_work=cost_of_work_total
    )
    proposal = get_success_data(
        client.create_gmp_proposal(
            f.gmp_proposal_payload(
                project["id"],
                estimate["id"],
                project_version(client, project["id"]),
                cost_of_work_total=cost_of_work_total,
                general_conditions_total=general_conditions_total,
                owner_contingency_amount=owner_contingency_amount,
                construction_contingency_amount=construction_contingency_amount,
            ),
            CM_HEADERS,
        )
    )
    return PricedProject(
        project=read_project(client, project["id"]), estimate=estimate, proposal=proposal
    )


def executed_project(
    client: ApiClient,
    cm_fee_pct: Numeric = Decimal("0.04"),
    insurance_rate: Numeric = Decimal("0.01"),
    cost_of_work_total: Numeric = STD_COST_OF_WORK,
    general_conditions_total: Numeric = STD_GENERAL_CONDITIONS,
    owner_contingency_amount: Numeric = STD_OWNER_CONTINGENCY,
    construction_contingency_amount: Numeric = STD_CONSTRUCTION_CONTINGENCY,
    project_kwargs: Optional[Dict[str, Any]] = None,
) -> PricedProject:
    """A project whose base proposal has been submitted and executed by the owner."""
    priced = draft_priced_project(
        client,
        cm_fee_pct=cm_fee_pct,
        insurance_rate=insurance_rate,
        cost_of_work_total=cost_of_work_total,
        general_conditions_total=general_conditions_total,
        owner_contingency_amount=owner_contingency_amount,
        construction_contingency_amount=construction_contingency_amount,
        project_kwargs=project_kwargs,
    )
    get_success_data(
        client.submit_gmp_proposal(priced.proposal["id"], CM_HEADERS)
    )
    proposal = get_success_data(
        client.decide_gmp_proposal(
            priced.proposal["id"], f.proposal_decision_payload("EXECUTE"), OWNER_HEADERS
        )
    )
    return PricedProject(
        project=read_project(client, priced.id),
        estimate=priced.estimate,
        proposal=proposal,
    )


def submitted_proposal_project(client: ApiClient, **kwargs: Any) -> PricedProject:
    """A project whose base proposal sits at OWNER_REVIEW, project at GMP review."""
    priced = draft_priced_project(client, **kwargs)
    proposal = get_success_data(
        client.submit_gmp_proposal(priced.proposal["id"], CM_HEADERS)
    )
    return PricedProject(
        project=read_project(client, priced.id),
        estimate=priced.estimate,
        proposal=proposal,
    )


# --- qualification log -----------------------------------------------------


def allowance_item(
    client: ApiClient,
    proposal_id: str,
    allowance_amount: Numeric = Decimal("75000.00"),
    allocated_units: Numeric = Decimal("1500.00"),
    unit_of_measure: str = "SF",
    **kwargs: Any,
) -> JsonObject:
    """An ALLOWANCE entry opening its own unit-and-value ledger."""
    return get_success_data(
        client.create_qualification_item(
            f.allowance_item_payload(
                proposal_id,
                allowance_amount=allowance_amount,
                allocated_units=allocated_units,
                unit_of_measure=unit_of_measure,
                **kwargs,
            ),
            CM_HEADERS,
        )
    )


def qualification_item(
    client: ApiClient, proposal_id: str, item_type: str = "ASSUMPTION", **kwargs: Any
) -> JsonObject:
    return get_success_data(
        client.create_qualification_item(
            f.qualification_item_payload(proposal_id, item_type=item_type, **kwargs),
            CM_HEADERS,
        )
    )


# --- buyout ----------------------------------------------------------------


def work_package(
    client: ApiClient,
    project_id: str,
    budget_amount: Numeric = Decimal("500000.00"),
    **kwargs: Any,
) -> JsonObject:
    """A budgeted trade package at BUDGETED / SEALED."""
    return get_success_data(
        client.create_work_package(
            f.work_package_payload(project_id, budget_amount=budget_amount, **kwargs),
            CM_HEADERS,
        )
    )


def soliciting_package(
    client: ApiClient,
    project_id: str,
    budget_amount: Numeric = Decimal("500000.00"),
    solicitation_opens_at: str = CLOCK_START,
    solicitation_closes_at: str = SOLICITATION_CLOSE,
    **kwargs: Any,
) -> JsonObject:
    """A package whose bid market is open over the named solicitation window."""
    package = work_package(client, project_id, budget_amount=budget_amount, **kwargs)
    return get_success_data(
        client.solicit_work_package(
            package["id"],
            f.solicit_payload(solicitation_opens_at, solicitation_closes_at),
            CM_HEADERS,
        )
    )


def third_party_bid(
    client: ApiClient,
    package_id: str,
    base_bid_amount: Numeric = Decimal("460000.00"),
    headers: Any = CM_HEADERS,
    **kwargs: Any,
) -> JsonObject:
    """A sealed open-market bid, exempt from the open-book disclosure gate."""
    return get_success_data(
        client.create_bid(
            f.third_party_bid_payload(
                package_id, base_bid_amount=base_bid_amount, **kwargs
            ),
            headers,
        )
    )


def self_perform_bid(
    client: ApiClient,
    package_id: str,
    base_bid_amount: Numeric = Decimal("460000.00"),
    headers: Any = CM_HEADERS,
    **kwargs: Any,
) -> JsonObject:
    """A sealed bid from the construction manager's own forces."""
    return get_success_data(
        client.create_bid(
            f.self_perform_bid_payload(
                package_id, base_bid_amount=base_bid_amount, **kwargs
            ),
            headers,
        )
    )


def opened_bid(
    client: ApiClient,
    package_id: str,
    base_bid_amount: Numeric = Decimal("460000.00"),
    close_instant: str = SOLICITATION_CLOSE,
    headers: Any = PO_INDEPENDENT_HEADERS,
) -> JsonObject:
    """A third-party bid unsealed after the solicitation close instant is reached."""
    bid = third_party_bid(client, package_id, base_bid_amount=base_bid_amount)
    set_clock(client, close_instant)
    return get_success_data(client.open_bid(bid["id"], headers))


@dataclass
class AwardedPackage:
    """A bought-out package together with its winning bid."""

    package: JsonObject
    bid: JsonObject
    losing_bids: List[JsonObject] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.package["id"]

    @property
    def version(self) -> int:
        return self.package["version"]


def awarded_package(
    client: ApiClient,
    project_id: str,
    budget_amount: Numeric = Decimal("500000.00"),
    base_bid_amount: Numeric = Decimal("460000.00"),
    solicitation_opens_at: str = CLOCK_START,
    solicitation_closes_at: str = SOLICITATION_CLOSE,
    **kwargs: Any,
) -> AwardedPackage:
    """Solicit, bid, open and award a package, recomputing both savings figures."""
    package = soliciting_package(
        client,
        project_id,
        budget_amount=budget_amount,
        solicitation_opens_at=solicitation_opens_at,
        solicitation_closes_at=solicitation_closes_at,
        **kwargs,
    )
    bid = opened_bid(
        client,
        package["id"],
        base_bid_amount=base_bid_amount,
        close_instant=solicitation_closes_at,
    )
    awarded = get_success_data(
        client.award_work_package(
            package["id"], f.award_payload(bid["id"]), PO_HEADERS
        )
    )
    return AwardedPackage(package=awarded, bid=read_bid(client, bid["id"]))


# --- subcontracts ----------------------------------------------------------


@dataclass
class SubcontractSetup:
    """An executed subcontract with the package and bid it was written from."""

    subcontract: JsonObject
    package: JsonObject
    bid: JsonObject

    @property
    def id(self) -> str:
        return self.subcontract["id"]


def active_subcontract(
    client: ApiClient,
    project_id: str,
    budget_amount: Numeric = Decimal("500000.00"),
    base_bid_amount: Numeric = Decimal("460000.00"),
    contract_amount: Optional[Numeric] = None,
    bond_required: Optional[bool] = None,
    bond_amount: Optional[Numeric] = None,
    performance_start: str = "2026-09-01T00:00:00Z",
    performance_end: str = "2026-11-30T00:00:00Z",
) -> SubcontractSetup:
    """A subcontract at ACTIVE against a freshly awarded package."""
    awarded = awarded_package(
        client, project_id, budget_amount=budget_amount, base_bid_amount=base_bid_amount
    )
    subcontract = get_success_data(
        client.create_subcontract(
            f.subcontract_payload(
                awarded.id,
                awarded.bid["id"],
                work_package_version(client, awarded.id),
                contract_amount=contract_amount
                if contract_amount is not None
                else base_bid_amount,
                performance_start=performance_start,
                performance_end=performance_end,
                bond_required=bond_required,
                bond_amount=bond_amount,
            ),
            CM_HEADERS,
        )
    )
    return SubcontractSetup(
        subcontract=subcontract,
        package=read_work_package(client, awarded.id),
        bid=awarded.bid,
    )


def notice_default(client: ApiClient, subcontract_id: str, reason: str = "Abandoned the site.") -> JsonObject:
    """Advance a subcontract ACTIVE -> DEFAULT_NOTICED."""
    return get_success_data(
        client.subcontract_status_action(
            subcontract_id,
            f.status_action_payload("NOTICE_DEFAULT", default_reason=reason),
            CM_HEADERS,
        )
    )


def terminate_for_default(client: ApiClient, subcontract_id: str) -> JsonObject:
    """Run the termination-for-default cascade from DEFAULT_NOTICED."""
    return get_success_data(
        client.subcontract_status_action(
            subcontract_id, f.status_action_payload("TERMINATE_FOR_DEFAULT"), CM_HEADERS
        )
    )


def pay_subcontract(client: ApiClient, subcontract_id: str, amount: Numeric) -> JsonObject:
    """Apply a progress payment, moving the paid and unpaid ledger together."""
    return get_success_data(
        client.progress_payment(
            subcontract_id, f.progress_payment_payload(amount), CM_HEADERS
        )
    )


# --- change events and draws ----------------------------------------------


def change_event(
    client: ApiClient,
    project_id: str,
    estimated_amount: Numeric = Decimal("30000.00"),
    origin: str = "FIELD_CONDITION",
    headers: Any = CM_PM_HEADERS,
    **kwargs: Any,
) -> JsonObject:
    """A change event at DRAFT with its classification deliberately null."""
    return get_success_data(
        client.create_change_event(
            f.change_event_payload(
                project_id,
                estimated_amount=estimated_amount,
                origin=origin,
                **kwargs,
            ),
            headers,
        )
    )


def event_under_review(
    client: ApiClient,
    project_id: str,
    estimated_amount: Numeric = Decimal("30000.00"),
    origin: str = "FIELD_CONDITION",
    submitter_headers: Any = CM_PM_HEADERS,
    **kwargs: Any,
) -> JsonObject:
    """A change event walked DRAFT -> SUBMITTED -> UNDER_REVIEW."""
    event = change_event(
        client,
        project_id,
        estimated_amount=estimated_amount,
        origin=origin,
        headers=submitter_headers,
        **kwargs,
    )
    get_success_data(client.submit_change_event(event["id"], submitter_headers))
    return get_success_data(
        client.review_change_event(
            event["id"], f.change_event_review_payload("BEGIN_REVIEW"), OWNER_HEADERS
        )
    )


@dataclass
class ClassifiedEvent:
    """A classified change event and whatever the fork minted behind it."""

    event: JsonObject
    draw: Optional[JsonObject] = None
    amendment: Optional[JsonObject] = None


def classified_event(
    client: ApiClient,
    project_id: str,
    classification: str,
    estimated_amount: Numeric = Decimal("30000.00"),
    origin: str = "FIELD_CONDITION",
    submitter_headers: Any = CM_PM_HEADERS,
    classifier_headers: Any = OWNER_HEADERS,
    **kwargs: Any,
) -> ClassifiedEvent:
    """Take a change event through the cost-responsibility fork."""
    event = event_under_review(
        client,
        project_id,
        estimated_amount=estimated_amount,
        origin=origin,
        submitter_headers=submitter_headers,
        **kwargs,
    )
    classified = get_success_data(
        client.classify_change_event(
            event["id"], f.classify_payload(classification), classifier_headers
        )
    )
    draws = list_draws(client, change_event_id=event["id"])
    amendments = list_proposals(client, change_event_id=event["id"])
    return ClassifiedEvent(
        event=classified,
        draw=draws[0] if draws else None,
        amendment=amendments[0] if amendments else None,
    )


def requested_draw(
    client: ApiClient,
    project_id: str,
    amount: Numeric,
    classification: str = "CONTINGENCY_USE_CONSTRUCTION",
    **kwargs: Any,
) -> JsonObject:
    """A contingency draw at REQUESTED, minted by a classification."""
    minted = classified_event(
        client, project_id, classification, estimated_amount=amount, **kwargs
    )
    assert minted.draw is not None, "classification did not mint a contingency draw"
    return minted.draw


def posted_draw(
    client: ApiClient,
    project_id: str,
    amount: Numeric,
    classification: str = "CONTINGENCY_USE_CONSTRUCTION",
    **kwargs: Any,
) -> JsonObject:
    """A contingency draw walked all the way to POSTED, moving the ledger."""
    draw = requested_draw(client, project_id, amount, classification, **kwargs)
    if draw["requires_owner_approval"]:
        get_success_data(
            client.approve_draw(draw["id"], f.draw_approve_payload(True), OWNER_HEADERS)
        )
    return get_success_data(client.post_draw(draw["id"], CM_HEADERS))


# --- cost reporting and closeout ------------------------------------------


def cost_report(
    client: ApiClient,
    project_id: str,
    period_start: str = "2026-08-01T00:00:00Z",
    period_end: str = "2026-09-01T00:00:00Z",
    **kwargs: Any,
) -> JsonObject:
    """A monthly report at OPEN with an empty lines array."""
    return get_success_data(
        client.create_cost_report(
            f.cost_report_payload(
                project_id, period_start=period_start, period_end=period_end, **kwargs
            ),
            CM_HEADERS,
        )
    )


def append_line(client: ApiClient, report_id: str, **kwargs: Any) -> JsonObject:
    """Append one open-book cost line, rounded before it enters any total."""
    return get_success_data(
        client.append_cost_line(report_id, f.cost_line_payload(**kwargs), CM_HEADERS)
    )


def reconciled_cost_report(
    client: ApiClient,
    project_id: str,
    period_start: str = "2026-08-01T00:00:00Z",
    period_end: str = "2026-09-01T00:00:00Z",
    quantity: Numeric = Decimal("100.0000"),
    unit_rate: Numeric = Decimal("200.0000"),
    markup_pct: Numeric = Decimal("0.0000"),
    **kwargs: Any,
) -> JsonObject:
    """A monthly report carrying one line and decided RECONCILE by the owner."""
    report = cost_report(
        client, project_id, period_start=period_start, period_end=period_end, **kwargs
    )
    append_line(
        client,
        report["id"],
        quantity=quantity,
        unit_rate=unit_rate,
        markup_pct=markup_pct,
    )
    return get_success_data(
        client.reconcile_cost_report(
            report["id"], f.cost_report_reconcile_payload("RECONCILE"), OWNER_HEADERS
        )
    )


def audit_in_progress(client: ApiClient, project_id: str) -> JsonObject:
    """Exercise the owner's audit rights, moving audit_status to IN_PROGRESS."""
    return get_success_data(client.request_audit(project_id, OWNER_HEADERS))


def closed_audit(
    client: ApiClient, project_id: str, adjustment_amount: Optional[Numeric] = None
) -> JsonObject:
    """An audit engagement closed by the independent auditor."""
    audit_in_progress(client, project_id)
    if adjustment_amount is not None:
        get_success_data(
            client.audit_action(
                project_id,
                f.audit_action_payload(
                    "POST_ADJUSTMENT", adjustment_amount=adjustment_amount
                ),
                AUDITOR_HEADERS,
            )
        )
    return get_success_data(
        client.audit_action(project_id, f.audit_action_payload("CLOSE"), AUDITOR_HEADERS)
    )


def provisional_savings(client: ApiClient, project_id: str) -> JsonObject:
    """Compute the conservative pre-audit provisional shared-savings split."""
    return get_success_data(
        client.shared_savings(
            project_id,
            f.shared_savings_payload("PRE_AUDIT_PROVISIONAL", False),
            OWNER_HEADERS,
        )
    )


def final_savings(client: ApiClient, project_id: str, execute: bool = False) -> JsonObject:
    """Compute, and optionally settle, the audited final shared-savings split."""
    return get_success_data(
        client.shared_savings(
            project_id, f.shared_savings_payload("POST_AUDIT_FINAL", execute), OWNER_HEADERS
        )
    )
