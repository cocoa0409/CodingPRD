"""Round trips that restore a conserved quantity without drift.

Each test below translates exactly one designed instance; the `Design:` line at
the end of every docstring names the instance it comes from.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_cents, assert_collection, assert_score
from test_helpers.constants import (
    BenefitCategory,
    CapClosureOutcome,
    CapDecisionOutcome,
    CapStatus,
    CompliancePosture,
    CooperationStatus,
    EscalationStatus,
    FulfillmentStatus,
    NetworkTier,
    NoticeType,
    NqtlItemStatus,
    PlanYearStatus,
    RemedyType,
    SubClassification,
    SubmissionType,
)


def _violation_with_a_drafted_design_change(api):
    """An item in VIOLATION carrying one DRAFT design change worth 1,655,433 cents.

    The determination is recorded by `user-officer-01`, leaving `user-officer-02`
    free to both approve and close the plan.  The raw product is 1,655,432.50
    cents, so the frozen figure is a rounded one and any compensating leg that
    recomputes rather than reverses it will drift.
    """
    scenario = fx.item_in_violation(api, sub_classification=SubClassification.OFFICE_VISITS)
    cap = fx.draft_cap(
        api,
        scenario.item_id,
        headers=scenario.sponsor_headers,
        remedy_type=RemedyType.DESIGN_CHANGE,
        affected_claims_count=1327,
        average_claim_cents=4990,
    )
    scenario.cap_id = cap["id"]
    scenario.cap = cap
    return scenario


def test_approving_then_abandoning_a_remedy_returns_the_ledger_to_exactly_zero(
    api, officer_alt_headers
):
    """The rounded amount goes onto the ledger and the identical amount comes off.

    Nothing is booked while the plan is merely drafted; approval adds the frozen
    1,655,433 cents; abandonment removes exactly that figure rather than
    re-deriving it, so the ledger lands on 0 and not on a cent either side.

    PRD: "Both outcomes reduce the plan year's `remediation_liability_cents` by
    exactly the plan's frozen `reprocessing_liability_cents` and increment the
    plan's own `version` by 1 — this is the compensating leg of the money invariant,
    and it is what makes an approve-then-abandon round trip return the plan year to
    precisely its previous total with zero drift."

    Design: Difficulty/compensating_invariant/approve_then_abandon_returns_plan_year_liability_to_zero_with_no_drift
    """
    scenario = _violation_with_a_drafted_design_change(api)
    assert_cents(
        fx.read_plan_year(api, scenario.plan_year_id)["remediation_liability_cents"],
        0,
        "remediation_liability_cents before the approval",
    )

    approved = validate_success(
        api.decide_corrective_action_plan(
            scenario.cap_id,
            f.cap_decision_payload(
                CapDecisionOutcome.APPROVED,
                decision_note="Design change approved by an independent officer.",
            ),
            officer_alt_headers,
        )
    )
    assert approved["status"] == CapStatus.APPROVED
    assert_cents(
        fx.read_plan_year(api, scenario.plan_year_id)["remediation_liability_cents"],
        1655433,
        "remediation_liability_cents after the approval",
    )

    abandoned = validate_success(
        api.close_corrective_action_plan(
            scenario.cap_id,
            f.cap_closure_payload(
                CapClosureOutcome.ABANDONED,
                closure_note=(
                    "The design change was withdrawn before implementation; a replacement plan "
                    "will be filed."
                ),
            ),
            officer_alt_headers,
        )
    )
    assert abandoned["status"] == CapStatus.ABANDONED
    assert_cents(
        abandoned["reprocessing_liability_cents"], 1655433, "reprocessing_liability_cents"
    )
    assert_cents(
        fx.read_plan_year(api, scenario.plan_year_id)["remediation_liability_cents"],
        0,
        "remediation_liability_cents after the abandonment",
    )


def test_the_abandoned_remedy_leaves_the_violation_and_its_disclosure_standing(
    api, officer_alt_headers
):
    """The compensation is deliberately partial: only the money comes back.

    The item is still in VIOLATION, the plan year still counts one open violation
    and still sits in REMEDIATION, and the disclosure minted by the determination
    is still the single notice on the record — an implementation that treats
    abandonment as a general undo is caught here.

    PRD: "Abandonment is the remedy being called off: the owning item keeps `status`
    `VIOLATION`, no participant notice is created at all, and the plan year's
    `version` increments by 1 for the ledger reduction alone."

    Design: Difficulty/compensating_invariant/approve_then_abandon_returns_plan_year_liability_to_zero_with_no_drift
    """
    scenario = _violation_with_a_drafted_design_change(api)
    fx.decide_cap(api, scenario.cap_id, CapDecisionOutcome.APPROVED, officer_alt_headers)
    fx.close_cap(api, scenario.cap_id, CapClosureOutcome.ABANDONED, officer_alt_headers)

    assert fx.read_item(api, scenario.item_id)["status"] == NqtlItemStatus.VIOLATION

    notices, _ = assert_collection(
        api.list_participant_notices(scenario.item_id, None, officer_alt_headers), 1, 1, False
    )
    assert notices[0]["notice_type"] == NoticeType.VIOLATION_DISCLOSURE

    plan_year = fx.read_plan_year(api, scenario.plan_year_id)
    assert plan_year["open_violation_count"] == 1
    assert plan_year["compliance_posture"] == CompliancePosture.VIOLATION
    assert plan_year["status"] == PlanYearStatus.REMEDIATION


def _one_unproduced_request_on_a_quiet_plan_year(api):
    """A single OPEN request against a plan year that holds no NQTL item at all.

    Nothing on the plan year can generate a violation of its own, so its posture
    can only ever move through the administrator's cooperation status.
    """
    scenario = fx.classified_plan(
        api,
        benefit_category=BenefitCategory.PRESCRIPTION_DRUGS,
        network_tier=NetworkTier.NOT_APPLICABLE,
    )
    request = fx.issue_vendor_request(
        api,
        scenario.admin_id,
        scenario.plan_year_id,
        requested_item_count=1,
        requested_submission_types=[SubmissionType.DENIAL_RATES],
    )
    scenario.vendor_request_id = request["id"]
    return scenario


def test_producing_in_full_restores_both_cooperation_scores_to_their_baseline(api):
    """The clock alone breaks the score and a forward action, not an undo, restores it.

    At the baseline the administrator is perfect.  Moving the clock past both
    deadlines costs 15 points on each basis without the TPA doing anything.  The
    fulfilling submission then takes the request out of the live set that lateness
    is counted over, so both scores return to exactly 100.00 even though the clock
    never moves backwards.

    PRD: "When the arriving submission is the one that brings the count up to exactly
    `requested_item_count`, `fulfillment_status` moves from `OPEN` or `PARTIAL` to
    `FULFILLED`, and that fulfilment is what closes the obligation: the
    administrator's `outstanding_request_count` is decremented by exactly 1, and
    `late_request_count`, `regulator_reportable_late_count`, both cooperation-score
    variants and `cooperation_status` are all recomputed."

    Design: Difficulty/compensating_invariant/production_returns_administrator_lateness_counters_to_their_baseline
    """
    scenario = _one_unproduced_request_on_a_quiet_plan_year(api)

    baseline = fx.read_administrator(api, scenario.admin_id)
    assert baseline["outstanding_request_count"] == 1
    assert baseline["late_request_count"] == 0
    assert_score(baseline["cooperation_score"], 100.00, "cooperation_score at the baseline")
    assert baseline["cooperation_status"] == CooperationStatus.COOPERATIVE

    fx.advance_clock(api, "2026-09-16T00:00:00Z")
    late = fx.read_administrator(api, scenario.admin_id)
    assert late["late_request_count"] == 1
    assert_score(late["cooperation_score"], 85.00, "cooperation_score while late")

    fx.produce_submission(
        api,
        scenario.vendor_request_id,
        f.denial_rate_submission_payload(scenario.classification_id),
        scenario.admin_id,
    )

    restored = fx.read_administrator(api, scenario.admin_id)
    assert restored["outstanding_request_count"] == 0
    assert restored["late_request_count"] == 0
    assert restored["breach_count"] == 0
    assert_score(restored["cooperation_score"], 100.00, "cooperation_score once produced")
    assert_score(
        restored["regulatory_basis_cooperation_score"],
        100.00,
        "regulatory_basis_cooperation_score once produced",
    )
    assert restored["cooperation_status"] == CooperationStatus.COOPERATIVE


def test_the_produced_request_stops_being_overdue_and_the_plan_year_never_wavers(api):
    """Fulfilment clears the overdue flag without any escalation ever happening.

    The request reaches FULFILLED with its enforcement dimension still at NONE, and
    `is_overdue` reads false afterwards even though the clock stands a day past
    `due_at`.  Because the administrator never fell out of COOPERATIVE, the plan
    year's posture stayed COMPLIANT from beginning to end.

    PRD: "The derived `is_overdue` flag on a request is true exactly when the logical
    clock now stands strictly later than `due_at` and `fulfillment_status` is not yet
    `FULFILLED`."

    Design: Difficulty/compensating_invariant/production_returns_administrator_lateness_counters_to_their_baseline
    """
    scenario = _one_unproduced_request_on_a_quiet_plan_year(api)
    assert (
        fx.read_plan_year(api, scenario.plan_year_id)["compliance_posture"]
        == CompliancePosture.COMPLIANT
    )

    fx.advance_clock(api, "2026-09-16T00:00:00Z")
    assert fx.read_vendor_request(api, scenario.vendor_request_id)["is_overdue"] is True
    assert (
        fx.read_plan_year(api, scenario.plan_year_id)["compliance_posture"]
        == CompliancePosture.COMPLIANT
    )

    fx.produce_submission(
        api,
        scenario.vendor_request_id,
        f.denial_rate_submission_payload(scenario.classification_id),
        scenario.admin_id,
    )

    request = fx.read_vendor_request(api, scenario.vendor_request_id)
    assert request["fulfillment_status"] == FulfillmentStatus.FULFILLED
    assert request["escalation_status"] == EscalationStatus.NONE
    assert request["is_overdue"] is False
    assert (
        fx.read_plan_year(api, scenario.plan_year_id)["compliance_posture"]
        == CompliancePosture.COMPLIANT
    )
