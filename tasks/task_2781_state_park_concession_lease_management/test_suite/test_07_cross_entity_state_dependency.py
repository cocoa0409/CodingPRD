"""Transitions whose legality is decided by a status carried on a different
row: the opportunity behind a prospectus, and the lease behind a season plan."""
from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_cents_equals,
    assert_lease_state,
    assert_null,
    assert_status,
)


def _draft_prospectus_on_unapproved_opportunity(api):
    """A prospectus drafted under an opportunity that no officer has cleared for
    solicitation; its market analysis has been filed, so it sits at
    ANALYSIS_COMPLETE."""
    X.set_clock(api, X.BOOTSTRAP_CLOCK)
    park = X.register_park(api)
    opportunity = X.create_opportunity(api, park["id"])
    X.record_market_analysis(
        api,
        opportunity["id"],
        comparable_gross_receipts_cents=200000000,
        market_capture_pct=80.00,
        analyst_note="Regional lodging comparables at 80 percent capture.",
    )
    prospectus = X.draft_prospectus(api, opportunity["id"])
    return {
        "park_id": park["id"],
        "opportunity_id": opportunity["id"],
        "prospectus_id": prospectus["id"],
    }


def _holdover_lease_with_a_submitted_plan(api):
    """The canonical active lease with a never-approved 2027 season plan, moved
    into HOLDOVER once the clock passes term_end."""
    ctx = X.setup_active_lease(api)
    plan = X.submit_operating_plan(
        api,
        ctx["lease_id"],
        ctx["offeror_id"],
        season_start="2027-03-01",
        season_end="2027-12-31",
        service_level="FULL",
        max_lodging_rate_cents=22000,
        max_meal_rate_cents=3400,
        max_activity_rate_cents=10000,
    )
    X.set_clock(api, "2037-03-01T00:00:00Z")
    lease = get_success_data(api.enter_holdover(ctx["lease_id"], X.exec_officer_headers()))
    assert_lease_state(lease, contract_status="HOLDOVER")
    ctx.update({"plan": plan, "plan_id": plan["id"]})
    return ctx


def test_prospectus_issue_is_refused_while_its_opportunity_is_uncleared(api):
    """PRD §3.2: "Issuing a `DRAFT` prospectus takes no payload and enforces two conditions in ladder order: the opportunity behind it must have reached `APPROVED_FOR_SOLICITATION`, else `ERR_OPPORTUNITY_NOT_APPROVED`, and the logical clock must be strictly before `submission_deadline`, else `ERR_SUBMISSION_WINDOW_CLOSED` — the agency does not publish a solicitation nobody can answer."
    PRD §2.9: "12. **Opportunity clearance** — `ERR_OPPORTUNITY_NOT_APPROVED` when the prospectus being issued hangs off an opportunity that has not reached `APPROVED_FOR_SOLICITATION`."
    PRD §5: "| `ERR_OPPORTUNITY_NOT_APPROVED` | 409 |"

    Design: Difficulty/cross_entity_state_dependency/prospectus_issue_blocked_by_opportunity_not_yet_approved
    """
    ctx = _draft_prospectus_on_unapproved_opportunity(api)

    response = api.issue_prospectus(ctx["prospectus_id"], X.specialist_headers())
    validate_error(response, "ERR_OPPORTUNITY_NOT_APPROVED", 409)

    prospectus = get_success_data(
        api.get_prospectus(ctx["prospectus_id"], X.specialist_headers())
    )
    assert_status(prospectus, "DRAFT")


def test_refused_issue_leaves_the_opportunity_at_analysis_complete(api):
    """PRD §3.1: "Recording the analysis moves a `DRAFT` opportunity to `ANALYSIS_COMPLETE`, and on an opportunity already at `ANALYSIS_COMPLETE` it is a self-loop that leaves the status where it is while recomputing the projection from the new comparables — the analysis may be redone any number of times until an officer clears the opportunity."
    PRD §3.1: "The projection itself is deliberately simple: `estimated_annual_gross_receipts_cents` is the comparable's receipts multiplied by `market_capture_pct` and divided by one hundred, with the result rounded half up to whole cents."
    PRD §3.2: "On success the prospectus moves `DRAFT → ISSUED`, its opportunity is dragged from `APPROVED_FOR_SOLICITATION` to `SOLICITED`, and both rows advance their `version` by one."

    Design: Difficulty/cross_entity_state_dependency/prospectus_issue_blocked_by_opportunity_not_yet_approved
    """
    ctx = _draft_prospectus_on_unapproved_opportunity(api)

    validate_error(
        api.issue_prospectus(ctx["prospectus_id"], X.specialist_headers()),
        "ERR_OPPORTUNITY_NOT_APPROVED",
        409,
    )

    opportunity = get_success_data(
        api.get_opportunity(ctx["opportunity_id"], X.specialist_headers())
    )
    assert_status(opportunity, "ANALYSIS_COMPLETE")
    assert_cents_equals(
        opportunity["estimated_annual_gross_receipts_cents"],
        160000000,
        "estimated_annual_gross_receipts_cents",
    )


def test_operating_plan_approval_is_refused_once_the_lease_is_in_holdover(api):
    """PRD §3.6: "Approval belongs to a `ContractingOfficer` and moves the plan `SUBMITTED → APPROVED`. It takes no payload and enforces three things after the plan's own status: the lease must still be `ACTIVE`; the season must not collide with another `APPROVED` season on the same lease; and every rate must sit under its ceiling."
    PRD §2.9: "11. **The referenced lease's contract posture** — `ERR_LEASE_NOT_ACTIVE` when a capital improvement, operating plan, gross receipts report or fee reconciliation is filed against a lease whose `contract_status` is not `ACTIVE`, and equally when an improvement or a plan is approved; `ERR_LEASE_STATUS_INVALID` when a compliance action names a lease outside `ACTIVE` or `HOLDOVER`, or an audit engagement names a lease outside `ACTIVE`, `HOLDOVER` or `EXPIRED`."
    PRD §3.6: "The agency may instead return the plan, moving `SUBMITTED → RETURNED` with a `deficiency_note` explaining why."

    Design: Difficulty/cross_entity_state_dependency/operating_plan_approval_blocked_by_lease_in_holdover
    """
    ctx = _holdover_lease_with_a_submitted_plan(api)

    response = api.approve_operating_plan(ctx["plan_id"], X.exec_officer_headers())
    validate_error(response, "ERR_LEASE_NOT_ACTIVE", 409)

    plan = get_success_data(api.get_operating_plan(ctx["plan_id"], X.exec_officer_headers()))
    assert_status(plan, "SUBMITTED")
    assert_null(plan, "deficiency_note")


def test_holdover_is_neither_a_default_nor_a_deficiency_after_the_refusal(api):
    """PRD §3.9: "When the term is up but a successor has not yet been selected, the officer may move the lease `ACTIVE → HOLDOVER`, which keeps the operating obligation alive: it requires that the logical clock's date be at or after `term_end` — the day `term_end` itself is early enough, unlike expiration — else `ERR_TERM_NOT_ELAPSED`, and that no other lease naming this one as its `predecessor_lease_id` be `ACTIVE` already, else `ERR_SUCCESSOR_ALREADY_ACTIVE`."
    PRD §3.9: "Holdover is not a default and not a deficiency; a lease in `HOLDOVER` reports receipts, is reconciled and is audited exactly as an `ACTIVE` one."
    PRD §2.10: "Neither dimension is ever read as a precondition for a transition of the other, and they advance on entirely different triggers, so a lease may legitimately be `HOLDOVER` and `DEFICIENT` at the same time, or `ACTIVE` and `DEFAULT`."

    Design: Difficulty/cross_entity_state_dependency/operating_plan_approval_blocked_by_lease_in_holdover
    """
    ctx = _holdover_lease_with_a_submitted_plan(api)

    validate_error(
        api.approve_operating_plan(ctx["plan_id"], X.exec_officer_headers()),
        "ERR_LEASE_NOT_ACTIVE",
        409,
    )

    lease = get_success_data(api.get_lease(ctx["lease_id"], X.exec_officer_headers()))
    assert_lease_state(lease, contract_status="HOLDOVER", compliance_status="COMPLIANT")
